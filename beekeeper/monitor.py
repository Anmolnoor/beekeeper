from __future__ import annotations

from dataclasses import dataclass

from .contracts import ResultEnvelope, Status, TaskEnvelope, WorkerKind


@dataclass
class MonitorDecision:
    action: str
    reason: str
    quality_score: float = 0.0
    retry_category: str | None = None


class SentinelMonitor:
    """
    Scores worker output and triggers rerun/escalation signals.
    """

    def __init__(self, min_confidence: float = 0.6) -> None:
        self.min_confidence = min_confidence

    def score_quality(self, task: TaskEnvelope, result: ResultEnvelope) -> float:
        score = result.confidence
        if task.worker_kind == WorkerKind.web_search:
            evidence = result.output.get("evidence", [])
            if isinstance(evidence, list):
                score = min(1.0, score + (0.05 * min(len(evidence), 4)))
        elif task.worker_kind == WorkerKind.heavy_compute:
            aggregate = result.output.get("aggregate", {})
            if isinstance(aggregate, dict) and aggregate:
                score = min(1.0, score + 0.1)
        elif task.worker_kind == WorkerKind.audit:
            verdict = str(result.output.get("verdict", "review"))
            if verdict == "pass":
                score = min(1.0, score + 0.1)
            elif verdict == "fail":
                score = max(0.0, score - 0.2)
        return max(0.0, min(1.0, score))

    def inspect(self, task: TaskEnvelope, result: ResultEnvelope) -> MonitorDecision:
        quality_score = self.score_quality(task, result)
        if result.status != Status.success:
            return MonitorDecision(
                action="rerun",
                reason="non_success_status",
                quality_score=quality_score,
                retry_category="transient",
            )
        if task.worker_kind == WorkerKind.web_search:
            evidence = result.output.get("evidence", [])
            if not isinstance(evidence, list) or len(evidence) < 2:
                return MonitorDecision(
                    action="rerun",
                    reason="insufficient_web_evidence",
                    quality_score=quality_score,
                    retry_category="quality",
                )
        if task.worker_kind == WorkerKind.heavy_compute:
            latency = result.cost_metrics.latency_ms
            if latency > 10_000:
                return MonitorDecision(
                    action="rerun",
                    reason="high_compute_latency",
                    quality_score=quality_score,
                    retry_category="transient",
                )
            aggregate = result.output.get("aggregate", {})
            if not isinstance(aggregate, dict) or not aggregate:
                return MonitorDecision(
                    action="rerun",
                    reason="missing_compute_aggregate",
                    quality_score=quality_score,
                    retry_category="quality",
                )
        if task.worker_kind == WorkerKind.file_system:
            operation = str(result.output.get("operation", ""))
            if operation == "write":
                bytes_written = int(result.output.get("bytes_written", 0) or 0)
                preview = str(result.output.get("content_preview", "") or "").strip().lower()
                if bytes_written < 64 and preview:
                    return MonitorDecision(
                        action="escalate",
                        reason="insufficient_file_content_for_report",
                        quality_score=min(quality_score, 0.45),
                        retry_category="quality",
                    )
        if task.worker_kind == WorkerKind.audit:
            verdict = str(result.output.get("verdict", "review"))
            if verdict == "fail":
                return MonitorDecision(
                    action="escalate",
                    reason="audit_failed",
                    quality_score=quality_score,
                    retry_category="policy",
                )
        if quality_score < self.min_confidence:
            return MonitorDecision(
                action="rerun",
                reason="low_confidence",
                quality_score=quality_score,
                retry_category="quality",
            )
        return MonitorDecision(action="accept", reason="quality_threshold_passed", quality_score=quality_score)
