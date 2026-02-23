from __future__ import annotations

import json
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .contracts import HumanReviewRecord


def _parse_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = line.strip()
            if not row:
                continue
            payload = json.loads(row)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def compute_ops_metrics(honeycomb_root: Path) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    ten_minutes_ago = now - timedelta(minutes=10)
    performance_dir = honeycomb_root / "performance"
    human_review_dir = honeycomb_root / "human_review"
    worker_quality: dict[str, list[float]] = defaultdict(list)
    worker_latency: dict[str, list[int]] = defaultdict(list)
    worker_cost: dict[str, list[float]] = defaultdict(list)

    for file_path in performance_dir.glob("*.jsonl"):
        for row in _iter_jsonl(file_path):
            worker = str(row.get("worker_kind", "unknown"))
            worker_quality[worker].append(float(row.get("quality_score", 0.0)))
            worker_latency[worker].append(int(row.get("latency_ms", 0)))
            worker_cost[worker].append(float(row.get("estimated_cost_usd", 0.0)))

    pending_reviews: list[HumanReviewRecord] = []
    pressure = 0
    for file_path in human_review_dir.glob("*.json"):
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        review = HumanReviewRecord.model_validate(payload)
        if review.status != "pending":
            continue
        pending_reviews.append(review)
        if review.requested_at >= ten_minutes_ago:
            pressure += 1

    quality_by_worker = {
        worker: (sum(values) / len(values) if values else 0.0) for worker, values in worker_quality.items()
    }
    latency_p95_by_worker: dict[str, float] = {}
    for worker, values in worker_latency.items():
        if not values:
            latency_p95_by_worker[worker] = 0.0
            continue
        sorted_values = sorted(values)
        idx = min(len(sorted_values) - 1, int(round((len(sorted_values) - 1) * 0.95)))
        latency_p95_by_worker[worker] = float(sorted_values[idx])
    cost_avg_by_worker = {worker: (sum(values) / len(values) if values else 0.0) for worker, values in worker_cost.items()}

    alerts: list[dict[str, Any]] = []
    if pressure > 5:
        alerts.append({"kind": "hitl_queue_pressure", "severity": "high", "message": f"pending approvals in 10m={pressure}"})
    for worker, quality in quality_by_worker.items():
        if quality < 0.65:
            alerts.append({"kind": "quality_drift", "severity": "medium", "message": f"{worker} quality average={quality:.2f}"})
    heavy_latency = latency_p95_by_worker.get("heavy_compute", 0.0)
    if heavy_latency > 10_000:
        alerts.append(
            {"kind": "latency_regression", "severity": "medium", "message": f"heavy_compute latency p95={int(heavy_latency)}ms"}
        )
    for worker, avg_cost in cost_avg_by_worker.items():
        if avg_cost > 0.55:
            alerts.append({"kind": "cost_guard", "severity": "medium", "message": f"{worker} avg cost={avg_cost:.3f}usd"})

    return {
        "generated_at": now.isoformat(),
        "pending_human_reviews": len(pending_reviews),
        "hitl_queue_pressure_10m": pressure,
        "quality_by_worker": quality_by_worker,
        "latency_p95_by_worker": latency_p95_by_worker,
        "cost_avg_by_worker": cost_avg_by_worker,
        "alerts": alerts,
    }


def send_alert_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        url=webhook_url,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=body,
    )
    with urllib.request.urlopen(request, timeout=5):
        return
