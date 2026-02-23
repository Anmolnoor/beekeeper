from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from uuid import uuid4

from .audit_logger import log_service_call
from .contracts import RetryCategory

class Scheduler(Protocol):
    def submit(self, task_payload: dict[str, Any], context_payload: dict[str, Any]) -> str:
        ...

    def collect(self, job_id: str, timeout_seconds: int = 60) -> dict[str, Any]:
        ...


def _validate_worker_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("worker_kind")
    schema = payload.get("output_schema")
    if result is None or schema is None:
        raise ValueError("scheduler_payload_missing_specialist_fields")
    return payload


def classify_retry_category(reason: str) -> RetryCategory:
    value = reason.lower().strip()
    if any(token in value for token in ("policy", "guardrail", "approval", "audit_failed")):
        return RetryCategory.policy
    if any(token in value for token in ("model", "llm", "completion")):
        return RetryCategory.model
    if any(token in value for token in ("tool", "adapter", "payload")):
        return RetryCategory.tool
    if any(token in value for token in ("quality", "confidence", "evidence", "aggregate")):
        return RetryCategory.quality
    return RetryCategory.transient


def retry_backoff_seconds(attempt: int, category: RetryCategory) -> float:
    base_by_category = {
        RetryCategory.transient: 0.5,
        RetryCategory.tool: 0.8,
        RetryCategory.model: 1.0,
        RetryCategory.policy: 0.0,
        RetryCategory.quality: 0.2,
    }
    base = base_by_category[category]
    if base <= 0.0:
        return 0.0
    return min(8.0, base * (2 ** max(0, attempt - 1)))


@dataclass
class RoutingFeedbackOptimizer:
    """
    Small feedback-loop helper to tune routing weights from historical outcomes.
    """

    quality_weight: float = 0.6
    latency_weight: float = 0.25
    cost_weight: float = 0.15

    def score(self, *, quality: float, latency_ms: float, cost_usd: float) -> float:
        latency_penalty = min(1.0, latency_ms / 10_000.0)
        cost_penalty = min(1.0, cost_usd / 1.0)
        return max(
            0.0,
            min(
                1.0,
                (quality * self.quality_weight)
                + ((1.0 - latency_penalty) * self.latency_weight)
                + ((1.0 - cost_penalty) * self.cost_weight),
            ),
        )


@dataclass
class InlineScheduler:
    handler: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    _store: dict[str, dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        self._store = {}

    def submit(self, task_payload: dict[str, Any], context_payload: dict[str, Any]) -> str:
        job_id = str(uuid4())
        self._store[job_id] = self.handler(task_payload, context_payload)
        return job_id

    def collect(self, job_id: str, timeout_seconds: int = 60) -> dict[str, Any]:
        if job_id not in self._store:
            raise KeyError(f"unknown_job_id={job_id}")
        return _validate_worker_payload(self._store[job_id])


@dataclass
class CeleryScheduler:
    broker_url: str = "redis://localhost:6379/0"
    backend_url: str = "redis://localhost:6379/1"
    task_name: str = "beekeeper.execute_worker_task"

    def __post_init__(self) -> None:
        from celery import Celery

        self._app = Celery("beekeeper_scheduler", broker=self.broker_url, backend=self.backend_url)

    def submit(self, task_payload: dict[str, Any], context_payload: dict[str, Any]) -> str:
        trace_id = task_payload.get("queen_trace_id") if isinstance(task_payload, dict) else None
        log_service_call("redis", "submitted", source="queen", trace_id=trace_id)
        async_result = self._app.send_task(self.task_name, args=[task_payload, context_payload])
        return str(async_result.id)

    def collect(self, job_id: str, timeout_seconds: int = 60) -> dict[str, Any]:
        from celery.result import AsyncResult

        result = AsyncResult(job_id, app=self._app)
        started = time.time()
        while not result.ready():
            if time.time() - started > timeout_seconds:
                raise TimeoutError(f"celery_job_timeout={job_id}")
            time.sleep(0.2)
        payload = result.get(timeout=timeout_seconds)
        if not isinstance(payload, dict):
            raise TypeError("celery_result_must_be_dict")
        return _validate_worker_payload(payload)
