from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from ...contracts import ArtifactRef, HumanReviewRecord, PolicyDecision, TaskEnvelope


class DurableStateRepositoryProtocol(Protocol):
    def record_run_state(
        self,
        *,
        trace_id: str,
        request_id: str,
        intent: str,
        state: str,
        source: str = "",
        payload: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        ...

    def record_task(self, task: TaskEnvelope, *, details: dict[str, Any] | None = None) -> None:
        ...

    def record_policy_decision(self, decision: PolicyDecision, *, trace_id: str) -> None:
        ...

    def record_artifact(self, artifact: ArtifactRef, *, trace_id: str) -> None:
        ...

    def create_review(self, review: HumanReviewRecord) -> HumanReviewRecord:
        ...

    def get_review(self, review_id: str) -> HumanReviewRecord | None:
        ...

    def list_pending_reviews(self) -> list[HumanReviewRecord]:
        ...

    def find_review_for_task(self, task_id: str, *, pending_only: bool = False) -> HumanReviewRecord | None:
        ...

    def resolve_review(self, review_id: str, *, approved: bool, approver: str, note: str | None = None) -> HumanReviewRecord:
        ...

    def enqueue_outbox(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> None:
        ...

    def list_pending_outbox(self, *, limit: int = 100) -> list[dict[str, Any]]:
        ...

    def mark_outbox_dispatched(self, entry_id: int) -> None:
        ...

    def claim_webhook_replay_key(
        self,
        *,
        channel: str,
        replay_key: str,
        ttl_seconds: int = 86_400,
    ) -> bool:
        ...

    def get_run(self, trace_id: str) -> dict[str, Any] | None:
        ...

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        ...

    def get_run_inspection(self, trace_id: str) -> dict[str, Any] | None:
        ...


def is_postgres_dsn(value: str | None) -> bool:
    raw = (value or "").strip().lower()
    return raw.startswith("postgres://") or raw.startswith("postgresql://")


def resolve_runtime_database_backend(*, explicit_backend: str | None, dsn: str | None) -> str:
    backend = (explicit_backend or "").strip().lower()
    if backend in {"postgres", "sqlite"}:
        return backend
    if is_postgres_dsn(dsn):
        return "postgres"
    return "sqlite"


def resolve_sqlite_db_path(*, explicit_path: Path | None, default_path: Path) -> Path:
    return explicit_path or default_path
