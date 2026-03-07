from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

from ...contracts import ArtifactRef, HumanReviewRecord, PolicyDecision, TaskEnvelope

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - optional dependency path
    psycopg = None
    dict_row = None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresDurableStateRepository:
    """Authoritative Postgres control-plane metadata store."""

    def __init__(self, dsn: str) -> None:
        if psycopg is None or dict_row is None:
            raise RuntimeError("psycopg_not_installed")
        self.dsn = dsn
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    trace_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    source TEXT,
                    state TEXT NOT NULL,
                    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_state_transitions (
                    id BIGSERIAL PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_run_state_transitions_trace ON run_state_transitions(trace_id, id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    worker_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    idempotency_key TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_trace ON tasks(trace_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_idempotency_key ON tasks(idempotency_key)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_state_transitions (
                    id BIGSERIAL PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_state_transitions_task ON task_state_transitions(task_id, id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS policy_decisions (
                    decision_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    guardrail_flags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                    reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                    obligations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                    policy_version TEXT NOT NULL DEFAULT 'v1',
                    requires_human_approval BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_policy_decisions_trace ON policy_decisions(trace_id, created_at)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    location TEXT NOT NULL,
                    storage_backend TEXT NOT NULL,
                    storage_bucket TEXT,
                    object_key TEXT,
                    content_type TEXT NOT NULL DEFAULT 'text/plain',
                    tenant_scope TEXT,
                    checksum TEXT,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_trace ON artifacts(trace_id, created_at)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    review_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    status TEXT NOT NULL,
                    requested_at TIMESTAMPTZ NOT NULL,
                    resolved_at TIMESTAMPTZ,
                    resolved_by TEXT,
                    resolution_note TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_task ON approvals(task_id, requested_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_pending ON approvals(status, requested_at)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_state_transitions (
                    id BIGSERIAL PRIMARY KEY,
                    review_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_approval_state_transitions_review ON approval_state_transitions(review_id, id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outbox (
                    id BIGSERIAL PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    aggregate_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    dispatched_at TIMESTAMPTZ
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(dispatched_at, id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS webhook_replay_keys (
                    replay_key TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    first_seen_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_webhook_replay_expires ON webhook_replay_keys(expires_at)")
            conn.commit()

    def record_run_state(self, *, trace_id: str, request_id: str, intent: str, state: str, source: str = "", payload: dict[str, Any] | None = None, details: dict[str, Any] | None = None) -> None:
        now = _utcnow_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(trace_id, request_id, intent, source, state, payload_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT(trace_id) DO UPDATE SET
                    request_id=excluded.request_id,
                    intent=excluded.intent,
                    source=excluded.source,
                    state=excluded.state,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (trace_id, request_id, intent, source, state, json.dumps(payload or {}, ensure_ascii=True), now, now),
            )
            conn.execute(
                "INSERT INTO run_state_transitions(trace_id, state, detail_json, created_at) VALUES (%s, %s, %s::jsonb, %s)",
                (trace_id, state, json.dumps(details or {}, ensure_ascii=True), now),
            )
            conn.commit()

    def record_task(self, task: TaskEnvelope, *, details: dict[str, Any] | None = None) -> None:
        now = _utcnow_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks(task_id, trace_id, task_type, worker_kind, status, payload_json, idempotency_key, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                ON CONFLICT(task_id) DO UPDATE SET
                    status=excluded.status,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    task.task_id,
                    task.queen_trace_id,
                    task.task_type,
                    task.worker_kind.value,
                    task.status.value,
                    json.dumps(task.payload or {}, ensure_ascii=True),
                    task.idempotency_key,
                    now,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO task_state_transitions(task_id, trace_id, status, detail_json, created_at) VALUES (%s, %s, %s, %s::jsonb, %s)",
                (task.task_id, task.queen_trace_id, task.status.value, json.dumps(details or {}, ensure_ascii=True), now),
            )
            conn.commit()

    def record_policy_decision(self, decision: PolicyDecision, *, trace_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO policy_decisions(
                    decision_id, trace_id, task_id, status, reason, guardrail_flags_json, reason_codes_json,
                    obligations_json, policy_version, requires_human_approval, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s)
                ON CONFLICT(decision_id) DO UPDATE SET
                    status=excluded.status,
                    reason=excluded.reason,
                    guardrail_flags_json=excluded.guardrail_flags_json,
                    reason_codes_json=excluded.reason_codes_json,
                    obligations_json=excluded.obligations_json,
                    policy_version=excluded.policy_version,
                    requires_human_approval=excluded.requires_human_approval,
                    created_at=excluded.created_at
                """,
                (
                    decision.decision_id,
                    trace_id,
                    decision.task_id,
                    decision.status,
                    decision.reason,
                    json.dumps(decision.guardrail_flags, ensure_ascii=True),
                    json.dumps(decision.reason_codes, ensure_ascii=True),
                    json.dumps(decision.obligations, ensure_ascii=True),
                    decision.policy_version,
                    decision.requires_human_approval,
                    decision.created_at.isoformat(),
                ),
            )
            conn.commit()

    def record_artifact(self, artifact: ArtifactRef, *, trace_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts(
                    artifact_id, trace_id, task_id, kind, location, storage_backend, storage_bucket, object_key,
                    content_type, tenant_scope, checksum, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    location=excluded.location,
                    storage_backend=excluded.storage_backend,
                    storage_bucket=excluded.storage_bucket,
                    object_key=excluded.object_key,
                    content_type=excluded.content_type,
                    tenant_scope=excluded.tenant_scope,
                    checksum=excluded.checksum
                """,
                (
                    artifact.artifact_id,
                    trace_id,
                    artifact.task_id,
                    artifact.kind,
                    artifact.location,
                    artifact.storage_backend,
                    artifact.storage_bucket,
                    artifact.object_key,
                    artifact.content_type,
                    artifact.tenant_scope,
                    artifact.checksum,
                    artifact.created_at.isoformat(),
                ),
            )
            conn.commit()

    def create_review(self, review: HumanReviewRecord) -> HumanReviewRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals(
                    review_id, task_id, trace_id, task_type, reason, payload_json, status, requested_at,
                    resolved_at, resolved_by, resolution_note
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                ON CONFLICT(review_id) DO UPDATE SET
                    status=excluded.status,
                    resolved_at=excluded.resolved_at,
                    resolved_by=excluded.resolved_by,
                    resolution_note=excluded.resolution_note
                """,
                (
                    review.review_id,
                    review.task_id,
                    review.trace_id,
                    review.task_type,
                    review.reason,
                    json.dumps(review.payload, ensure_ascii=True),
                    review.status,
                    review.requested_at.isoformat(),
                    review.resolved_at.isoformat() if review.resolved_at else None,
                    review.resolved_by,
                    review.resolution_note,
                ),
            )
            conn.execute(
                "INSERT INTO approval_state_transitions(review_id, task_id, trace_id, status, detail_json, created_at) VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
                (review.review_id, review.task_id, review.trace_id, review.status, json.dumps({'reason': review.reason}, ensure_ascii=True), _utcnow_iso()),
            )
            conn.commit()
        return review

    def _review_from_row(self, row: dict[str, Any]) -> HumanReviewRecord:
        return HumanReviewRecord.model_validate(
            {
                "review_id": str(row["review_id"]),
                "task_id": str(row["task_id"]),
                "trace_id": str(row["trace_id"]),
                "task_type": str(row["task_type"]),
                "reason": str(row["reason"]),
                "payload": row["payload_json"] if isinstance(row["payload_json"], dict) else json.loads(row["payload_json"]),
                "status": str(row["status"]),
                "requested_at": row["requested_at"].isoformat() if hasattr(row["requested_at"], "isoformat") else str(row["requested_at"]),
                "resolved_at": row["resolved_at"].isoformat() if row.get("resolved_at") else None,
                "resolved_by": str(row["resolved_by"]) if row.get("resolved_by") else None,
                "resolution_note": str(row["resolution_note"]) if row.get("resolution_note") else None,
            }
        )

    def get_review(self, review_id: str) -> HumanReviewRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE review_id = %s", (review_id,)).fetchone()
        return None if row is None else self._review_from_row(row)

    def list_pending_reviews(self) -> list[HumanReviewRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM approvals WHERE status = 'pending' ORDER BY requested_at ASC").fetchall()
        return [self._review_from_row(row) for row in rows]

    def find_review_for_task(self, task_id: str, *, pending_only: bool = False) -> HumanReviewRecord | None:
        query = "SELECT * FROM approvals WHERE task_id = %s"
        params: list[Any] = [task_id]
        if pending_only:
            query += " AND status = 'pending'"
        query += " ORDER BY requested_at DESC LIMIT 1"
        with self._lock, self._connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return None if row is None else self._review_from_row(row)

    def resolve_review(self, review_id: str, *, approved: bool, approver: str, note: str | None = None) -> HumanReviewRecord:
        review = self.get_review(review_id)
        if review is None:
            raise KeyError(f"unknown_review_id={review_id}")
        if review.status != "pending":
            return review
        review.status = "approved" if approved else "rejected"
        review.resolved_by = approver
        review.resolution_note = note
        review.resolved_at = datetime.now(timezone.utc)
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE approvals SET status = %s, resolved_at = %s, resolved_by = %s, resolution_note = %s WHERE review_id = %s",
                (review.status, review.resolved_at.isoformat(), review.resolved_by, review.resolution_note, review.review_id),
            )
            conn.execute(
                "INSERT INTO approval_state_transitions(review_id, task_id, trace_id, status, detail_json, created_at) VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
                (review.review_id, review.task_id, review.trace_id, review.status, json.dumps({"resolved_by": approver, "note": note or ""}, ensure_ascii=True), _utcnow_iso()),
            )
            conn.commit()
        return review

    def enqueue_outbox(self, *, event_type: str, aggregate_type: str, aggregate_id: str, idempotency_key: str, payload: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO outbox(event_type, aggregate_type, aggregate_id, idempotency_key, payload_json, created_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (event_type, aggregate_type, aggregate_id, idempotency_key, json.dumps(payload, ensure_ascii=True), _utcnow_iso()),
            )
            conn.commit()

    def list_pending_outbox(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, event_type, aggregate_type, aggregate_id, idempotency_key, payload_json, created_at
                FROM outbox
                WHERE dispatched_at IS NULL
                ORDER BY id ASC
                LIMIT %s
                """,
                (max(1, limit),),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "event_type": str(row["event_type"]),
                "aggregate_type": str(row["aggregate_type"]),
                "aggregate_id": str(row["aggregate_id"]),
                "idempotency_key": str(row["idempotency_key"]),
                "payload": row["payload_json"] if isinstance(row["payload_json"], dict) else json.loads(row["payload_json"]),
                "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            }
            for row in rows
        ]

    def mark_outbox_dispatched(self, entry_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE outbox SET dispatched_at = %s WHERE id = %s", (_utcnow_iso(), int(entry_id)))
            conn.commit()

    def claim_webhook_replay_key(self, *, channel: str, replay_key: str, ttl_seconds: int = 86_400) -> bool:
        now = datetime.now(timezone.utc)
        expires = datetime.fromtimestamp(now.timestamp() + max(1, int(ttl_seconds)), tz=timezone.utc)
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM webhook_replay_keys WHERE expires_at <= %s", (now.isoformat(),))
            cur = conn.execute(
                """
                INSERT INTO webhook_replay_keys(replay_key, channel, first_seen_at, expires_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(replay_key) DO NOTHING
                """,
                (replay_key, channel, now.isoformat(), expires.isoformat()),
            )
            conn.commit()
            return (cur.rowcount or 0) > 0

    def get_run(self, trace_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE trace_id = %s", (trace_id,)).fetchone()
        if row is None:
            return None
        payload = row["payload_json"] if isinstance(row["payload_json"], dict) else json.loads(row["payload_json"])
        return {
            "trace_id": str(row["trace_id"]),
            "request_id": str(row["request_id"]),
            "intent": str(row["intent"]),
            "source": str(row["source"] or ""),
            "state": str(row["state"]),
            "payload": payload,
            "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
        }

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = %s", (task_id,)).fetchone()
        if row is None:
            return None
        payload = row["payload_json"] if isinstance(row["payload_json"], dict) else json.loads(row["payload_json"])
        return {
            "task_id": str(row["task_id"]),
            "trace_id": str(row["trace_id"]),
            "task_type": str(row["task_type"]),
            "worker_kind": str(row["worker_kind"]),
            "status": str(row["status"]),
            "payload": payload,
            "idempotency_key": str(row["idempotency_key"]),
            "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
        }

    def get_run_inspection(self, trace_id: str) -> dict[str, Any] | None:
        run = self.get_run(trace_id)
        if run is None:
            return None
        with self._lock, self._connect() as conn:
            run_state_rows = conn.execute("SELECT state, detail_json, created_at FROM run_state_transitions WHERE trace_id = %s ORDER BY id ASC", (trace_id,)).fetchall()
            task_rows = conn.execute("SELECT * FROM tasks WHERE trace_id = %s ORDER BY created_at ASC", (trace_id,)).fetchall()
            task_state_rows = conn.execute("SELECT task_id, status, detail_json, created_at FROM task_state_transitions WHERE trace_id = %s ORDER BY id ASC", (trace_id,)).fetchall()
            policy_rows = conn.execute("SELECT * FROM policy_decisions WHERE trace_id = %s ORDER BY created_at ASC", (trace_id,)).fetchall()
            artifact_rows = conn.execute("SELECT * FROM artifacts WHERE trace_id = %s ORDER BY created_at ASC", (trace_id,)).fetchall()
            approval_rows = conn.execute("SELECT * FROM approvals WHERE trace_id = %s ORDER BY requested_at ASC", (trace_id,)).fetchall()
            outbox_rows = conn.execute(
                """
                SELECT id, event_type, aggregate_type, aggregate_id, idempotency_key, payload_json, created_at
                FROM outbox
                WHERE dispatched_at IS NULL AND (CAST(payload_json AS TEXT) LIKE %s OR aggregate_id = %s)
                ORDER BY id ASC
                """,
                (f'%"trace_id": "{trace_id}"%', trace_id),
            ).fetchall()
        task_timeline: dict[str, list[dict[str, Any]]] = {}
        for row in task_state_rows:
            details = row["detail_json"] if isinstance(row["detail_json"], dict) else json.loads(row["detail_json"])
            task_timeline.setdefault(str(row["task_id"]), []).append(
                {
                    "status": str(row["status"]),
                    "details": details,
                    "at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
                }
            )
        tasks = []
        for row in task_rows:
            payload = row["payload_json"] if isinstance(row["payload_json"], dict) else json.loads(row["payload_json"])
            task_id = str(row["task_id"])
            tasks.append(
                {
                    "task_id": task_id,
                    "trace_id": str(row["trace_id"]),
                    "task_type": str(row["task_type"]),
                    "worker_kind": str(row["worker_kind"]),
                    "status": str(row["status"]),
                    "payload": payload,
                    "idempotency_key": str(row["idempotency_key"]),
                    "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
                    "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
                    "state_timeline": task_timeline.get(task_id, []),
                }
            )
        policies = []
        for row in policy_rows:
            policies.append(
                {
                    "decision_id": str(row["decision_id"]),
                    "task_id": str(row["task_id"]),
                    "status": str(row["status"]),
                    "reason": str(row["reason"]),
                    "guardrail_flags": row["guardrail_flags_json"] if isinstance(row["guardrail_flags_json"], list) else json.loads(row["guardrail_flags_json"]),
                    "reason_codes": row["reason_codes_json"] if isinstance(row["reason_codes_json"], list) else json.loads(row["reason_codes_json"]),
                    "obligations": row["obligations_json"] if isinstance(row["obligations_json"], list) else json.loads(row["obligations_json"]),
                    "policy_version": str(row["policy_version"]),
                    "requires_human_approval": bool(row["requires_human_approval"]),
                    "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
                }
            )
        artifacts = []
        for row in artifact_rows:
            artifacts.append(
                {
                    "artifact_id": str(row["artifact_id"]),
                    "task_id": str(row["task_id"]),
                    "kind": str(row["kind"]),
                    "location": str(row["location"]),
                    "storage_backend": str(row["storage_backend"]),
                    "storage_bucket": str(row["storage_bucket"]) if row.get("storage_bucket") else None,
                    "object_key": str(row["object_key"]) if row.get("object_key") else None,
                    "content_type": str(row["content_type"]),
                    "tenant_scope": str(row["tenant_scope"]) if row.get("tenant_scope") else None,
                    "checksum": str(row["checksum"]) if row.get("checksum") else None,
                    "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
                }
            )
        approvals = [self._review_from_row(row).model_dump(mode="json") for row in approval_rows]
        outbox = [
            {
                "id": int(row["id"]),
                "event_type": str(row["event_type"]),
                "aggregate_type": str(row["aggregate_type"]),
                "aggregate_id": str(row["aggregate_id"]),
                "idempotency_key": str(row["idempotency_key"]),
                "payload": row["payload_json"] if isinstance(row["payload_json"], dict) else json.loads(row["payload_json"]),
                "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            }
            for row in outbox_rows
        ]
        return {
            "run": run,
            "run_state_timeline": [
                {
                    "state": str(row["state"]),
                    "details": row["detail_json"] if isinstance(row["detail_json"], dict) else json.loads(row["detail_json"]),
                    "at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
                }
                for row in run_state_rows
            ],
            "tasks": tasks,
            "artifacts": artifacts,
            "policy_decisions": policies,
            "approvals": approvals,
            "pending_outbox": outbox,
        }
