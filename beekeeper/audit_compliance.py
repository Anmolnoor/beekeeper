from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .security import sign_payload, verify_payload


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = line.strip()
            if not row:
                continue
            try:
                payload = json.loads(row)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _metrics_path(root: Path) -> Path:
    return root / "metrics" / "audit_metrics.json"


def _load_metrics(root: Path) -> dict[str, Any]:
    path = _metrics_path(root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _store_metrics(root: Path, patch: dict[str, Any]) -> None:
    path = _metrics_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _load_metrics(root)
    payload.update(patch)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _audit_file_for_day(root: Path, day: datetime) -> Path:
    return root / "audit" / f"{day.strftime('%Y%m%d')}.jsonl"


def reconcile_audit_trace_links(
    honeycomb_root: Path,
    *,
    days: int = 7,
    persist_report: bool = True,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    total = 0
    linked = 0
    missing_at_write = 0
    resolved_later = 0
    still_missing = 0

    for day_offset in range(max(1, days)):
        day = now - timedelta(days=day_offset)
        path = _audit_file_for_day(honeycomb_root, day)
        for row in _iter_jsonl(path):
            trace_id = str(row.get("trace_id", "")).strip()
            if not trace_id:
                continue
            total += 1
            state = str(row.get("trace_link_state", "")).strip().lower()
            events_file = honeycomb_root / "events" / f"{trace_id}.jsonl"
            exists_now = events_file.exists()
            if state == "linked":
                linked += 1
                continue
            missing_at_write += 1
            if exists_now:
                linked += 1
                resolved_later += 1
            else:
                still_missing += 1

    linkage_rate = (linked / total) if total else 1.0
    report = {
        "generated_at": now.isoformat(),
        "days": max(1, days),
        "trace_link_total": total,
        "trace_link_linked": linked,
        "trace_link_missing_at_write": missing_at_write,
        "trace_link_resolved_later": resolved_later,
        "trace_link_still_missing": still_missing,
        "audit_trace_linkage_rate": linkage_rate,
        "status": "pass" if linkage_rate >= 0.995 else "fail",
    }

    if persist_report:
        report_path = honeycomb_root / "metrics" / "audit_reconciliation_latest.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
        _store_metrics(
            honeycomb_root,
            {
                "trace_linkage_resolved_count": resolved_later,
                "trace_linkage_still_missing_count": still_missing,
                "audit_trace_linkage_rate": linkage_rate,
            },
        )
    return report


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity_dir(root: Path) -> Path:
    return root / "metrics" / "integrity"


def _checkpoint_path(root: Path, day_key: str) -> Path:
    return _integrity_dir(root) / f"{day_key}.checkpoint.json"


def create_integrity_checkpoint(
    honeycomb_root: Path,
    *,
    day_key: str | None = None,
) -> dict[str, Any]:
    if not day_key:
        day_key = datetime.now(timezone.utc).strftime("%Y%m%d")
    audit_file = honeycomb_root / "audit" / f"{day_key}.jsonl"
    if not audit_file.exists():
        return {
            "day": day_key,
            "status": "missing_audit_file",
            "checkpoint_path": str(_checkpoint_path(honeycomb_root, day_key)),
        }

    line_count = sum(1 for line in audit_file.read_text(encoding="utf-8").splitlines() if line.strip())
    payload = {
        "day": day_key,
        "audit_file": str(audit_file),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bytes": audit_file.stat().st_size,
        "line_count": line_count,
        "sha256": _sha256_file(audit_file),
    }
    payload["signature"] = sign_payload(payload)
    out = _checkpoint_path(honeycomb_root, day_key)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return {
        "day": day_key,
        "status": "checkpoint_written",
        "checkpoint_path": str(out),
    }


def create_integrity_checkpoints(
    honeycomb_root: Path,
    *,
    days: int = 7,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    for day_offset in range(max(1, days)):
        day_key = (now - timedelta(days=day_offset)).strftime("%Y%m%d")
        results.append(create_integrity_checkpoint(honeycomb_root, day_key=day_key))
    written = sum(1 for item in results if item.get("status") == "checkpoint_written")
    return {"days": max(1, days), "written": written, "results": results}


def verify_integrity(
    honeycomb_root: Path,
    *,
    days: int = 7,
    persist_status: bool = True,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    checked = 0
    ok = 0
    missing_checkpoint = 0
    missing_audit_file = 0
    signature_failures = 0
    hash_mismatches = 0

    details: list[dict[str, Any]] = []
    for day_offset in range(max(1, days)):
        day_key = (now - timedelta(days=day_offset)).strftime("%Y%m%d")
        audit_file = honeycomb_root / "audit" / f"{day_key}.jsonl"
        checkpoint_file = _checkpoint_path(honeycomb_root, day_key)
        if not audit_file.exists():
            missing_audit_file += 1
            details.append({"day": day_key, "status": "missing_audit_file"})
            continue
        if not checkpoint_file.exists():
            missing_checkpoint += 1
            details.append({"day": day_key, "status": "missing_checkpoint"})
            continue

        checked += 1
        try:
            payload = json.loads(checkpoint_file.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                signature_failures += 1
                details.append({"day": day_key, "status": "invalid_checkpoint_format"})
                continue
        except Exception:
            signature_failures += 1
            details.append({"day": day_key, "status": "invalid_checkpoint_read"})
            continue

        signature = str(payload.get("signature", ""))
        signed_payload = {k: v for k, v in payload.items() if k != "signature"}
        if not signature or not verify_payload(signed_payload, signature):
            signature_failures += 1
            details.append({"day": day_key, "status": "signature_fail"})
            continue

        digest = _sha256_file(audit_file)
        if digest != str(payload.get("sha256", "")):
            hash_mismatches += 1
            details.append({"day": day_key, "status": "hash_mismatch"})
            continue
        ok += 1
        details.append({"day": day_key, "status": "ok"})

    status = "pass" if checked > 0 and (signature_failures + hash_mismatches + missing_checkpoint) == 0 else "fail"
    report = {
        "generated_at": now.isoformat(),
        "days": max(1, days),
        "status": status,
        "checked": checked,
        "ok": ok,
        "missing_checkpoint": missing_checkpoint,
        "missing_audit_file": missing_audit_file,
        "signature_failures": signature_failures,
        "hash_mismatches": hash_mismatches,
        "details": details,
    }

    if persist_status:
        status_path = honeycomb_root / "metrics" / "audit_integrity_status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
        _store_metrics(
            honeycomb_root,
            {
                "integrity_verification_status": status,
                "integrity_last_verified_at": now.isoformat(),
                "integrity_last_result": {
                    "checked": checked,
                    "ok": ok,
                    "missing_checkpoint": missing_checkpoint,
                    "signature_failures": signature_failures,
                    "hash_mismatches": hash_mismatches,
                },
            },
        )
    return report
