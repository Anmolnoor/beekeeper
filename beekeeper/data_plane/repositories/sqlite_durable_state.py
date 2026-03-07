from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...contracts import HumanReviewRecord, PolicyDecision, TaskEnvelope


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteDurableStateRepository:
    """Durable control-plane metadata store (sqlite dev adapter)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    trace_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    source TEXT,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_state_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_run_state_transitions_trace
                ON run_state_transitions(trace_id, id);

                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    worker_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_trace ON tasks(trace_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_idempotency_key ON tasks(idempotency_key);

                CREATE TABLE IF NOT EXISTS task_state_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_task_state_transitions_task
                ON task_state_transitions(task_id, id);

                CREATE TABLE IF NOT EXISTS policy_decisions (
                    decision_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    guardrail_flags_json TEXT NOT NULL DEFAULT '[]',
                    reason_codes_json TEXT NOT NULL DEFAULT '[]',
                    obligations_json TEXT NOT NULL DEFAULT '[]',
                    policy_version TEXT NOT NULL DEFAULT 'v1',
                    requires_human_approval INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_policy_decisions_trace
                ON policy_decisions(trace_id, created_at);

                CREATE TABLE IF NOT EXISTS approvals (
                    review_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolved_by TEXT,
                    resolution_note TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_approvals_task
                ON approvals(task_id, requested_at);

                CREATE INDEX IF NOT EXISTS idx_approvals_pending
                ON approvals(status, requested_at);

                CREATE TABLE IF NOT EXISTS approval_state_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_approval_state_transitions_review
                ON approval_state_transitions(review_id, id);

                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    aggregate_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    dispatched_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_outbox_pending
                ON outbox(dispatched_at, id);

                CREATE TABLE IF NOT EXISTS webhook_replay_keys (
                    replay_key TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );

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
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_artifacts_trace
                ON artifacts(trace_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_webhook_replay_expires
                ON webhook_replay_keys(expires_at);
                """
            )

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
        now = _utcnow_iso()
        payload_json = json.dumps(payload or {}, ensure_ascii=True)
        detail_json = json.dumps(details or {}, ensure_ascii=True)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(trace_id, request_id, intent, source, state, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    request_id=excluded.request_id,
                    intent=excluded.intent,
                    source=excluded.source,
                    state=excluded.state,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (trace_id, request_id, intent, source, state, payload_json, now, now),
            )
            conn.execute(
                """
                INSERT INTO run_state_transitions(trace_id, state, detail_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (trace_id, state, detail_json, now),
            )

    def record_task(self, task: TaskEnvelope, *, details: dict[str, Any] | None = None) -> None:
        now = _utcnow_iso()
        payload_json = json.dumps(task.payload or {}, ensure_ascii=True)
        detail_json = json.dumps(details or {}, ensure_ascii=True)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks(task_id, trace_id, task_type, worker_kind, status, payload_json, idempotency_key, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    payload_json,
                    task.idempotency_key,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO task_state_transitions(task_id, trace_id, status, detail_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task.task_id, task.queen_trace_id, task.status.value, detail_json, now),
            )

    def record_policy_decision(self, decision: PolicyDecision, *, trace_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO policy_decisions(
                    decision_id, trace_id, task_id, status, reason, guardrail_flags_json, reason_codes_json,
                    obligations_json, policy_version, requires_human_approval, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    1 if decision.requires_human_approval else 0,
                    decision.created_at.isoformat(),
                ),
            )

    def record_artifact(self, artifact: Any, *, trace_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO artifacts(
                    artifact_id, trace_id, task_id, kind, location, storage_backend, storage_bucket,
                    object_key, content_type, tenant_scope, checksum, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def create_review(self, review: HumanReviewRecord) -> HumanReviewRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO approvals(
                    review_id, task_id, trace_id, task_type, reason, payload_json, status, requested_at,
                    resolved_at, resolved_by, resolution_note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                """
                INSERT INTO approval_state_transitions(review_id, task_id, trace_id, status, detail_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    review.review_id,
                    review.task_id,
                    review.trace_id,
                    review.status,
                    json.dumps({"reason": review.reason}, ensure_ascii=True),
                    _utcnow_iso(),
                ),
            )
        return review

    def get_review(self, review_id: str) -> HumanReviewRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT review_id, task_id, trace_id, task_type, reason, payload_json, status, requested_at,
                       resolved_at, resolved_by, resolution_note
                FROM approvals
                WHERE review_id = ?
                """,
                (review_id,),
            ).fetchone()
        if row is None:
            return None
        return HumanReviewRecord.model_validate(
            {
                "review_id": str(row["review_id"]),
                "task_id": str(row["task_id"]),
                "trace_id": str(row["trace_id"]),
                "task_type": str(row["task_type"]),
                "reason": str(row["reason"]),
                "payload": json.loads(row["payload_json"]),
                "status": str(row["status"]),
                "requested_at": str(row["requested_at"]),
                "resolved_at": str(row["resolved_at"]) if row["resolved_at"] else None,
                "resolved_by": str(row["resolved_by"]) if row["resolved_by"] else None,
                "resolution_note": str(row["resolution_note"]) if row["resolution_note"] else None,
            }
        )

    def list_pending_reviews(self) -> list[HumanReviewRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT review_id, task_id, trace_id, task_type, reason, payload_json, status, requested_at,
                       resolved_at, resolved_by, resolution_note
                FROM approvals
                WHERE status = 'pending'
                ORDER BY requested_at ASC
                """
            ).fetchall()
        return [
            HumanReviewRecord.model_validate(
                {
                    "review_id": str(row["review_id"]),
                    "task_id": str(row["task_id"]),
                    "trace_id": str(row["trace_id"]),
                    "task_type": str(row["task_type"]),
                    "reason": str(row["reason"]),
                    "payload": json.loads(row["payload_json"]),
                    "status": str(row["status"]),
                    "requested_at": str(row["requested_at"]),
                    "resolved_at": str(row["resolved_at"]) if row["resolved_at"] else None,
                    "resolved_by": str(row["resolved_by"]) if row["resolved_by"] else None,
                    "resolution_note": str(row["resolution_note"]) if row["resolution_note"] else None,
                }
            )
            for row in rows
        ]

    def find_review_for_task(self, task_id: str, *, pending_only: bool = False) -> HumanReviewRecord | None:
        query = """
            SELECT review_id, task_id, trace_id, task_type, reason, payload_json, status, requested_at,
                   resolved_at, resolved_by, resolution_note
            FROM approvals
            WHERE task_id = ?
        """
        params: tuple[Any, ...] = (task_id,)
        if pending_only:
            query += " AND status = 'pending'"
        query += " ORDER BY requested_at DESC LIMIT 1"
        with self._lock, self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        if row is None:
            return None
        return HumanReviewRecord.model_validate(
            {
                "review_id": str(row["review_id"]),
                "task_id": str(row["task_id"]),
                "trace_id": str(row["trace_id"]),
                "task_type": str(row["task_type"]),
                "reason": str(row["reason"]),
                "payload": json.loads(row["payload_json"]),
                "status": str(row["status"]),
                "requested_at": str(row["requested_at"]),
                "resolved_at": str(row["resolved_at"]) if row["resolved_at"] else None,
                "resolved_by": str(row["resolved_by"]) if row["resolved_by"] else None,
                "resolution_note": str(row["resolution_note"]) if row["resolution_note"] else None,
            }
        )

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
                """
                UPDATE approvals
                SET status = ?, resolved_at = ?, resolved_by = ?, resolution_note = ?
                WHERE review_id = ?
                """,
                (
                    review.status,
                    review.resolved_at.isoformat() if review.resolved_at else None,
                    review.resolved_by,
                    review.resolution_note,
                    review.review_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO approval_state_transitions(review_id, task_id, trace_id, status, detail_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    review.review_id,
                    review.task_id,
                    review.trace_id,
                    review.status,
                    json.dumps({"resolved_by": approver, "note": note or ""}, ensure_ascii=True),
                    _utcnow_iso(),
                ),
            )
        return review

    def enqueue_outbox(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO outbox(
                    event_type, aggregate_type, aggregate_id, idempotency_key, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    idempotency_key,
                    json.dumps(payload, ensure_ascii=True),
                    _utcnow_iso(),
                ),
            )

    def list_pending_outbox(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, event_type, aggregate_type, aggregate_id, idempotency_key, payload_json, created_at
                FROM outbox
                WHERE dispatched_at IS NULL
                ORDER BY id ASC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        pending: list[dict[str, Any]] = []
        for row in rows:
            pending.append(
                {
                    "id": int(row["id"]),
                    "event_type": str(row["event_type"]),
                    "aggregate_type": str(row["aggregate_type"]),
                    "aggregate_id": str(row["aggregate_id"]),
                    "idempotency_key": str(row["idempotency_key"]),
                    "payload": json.loads(row["payload_json"]),
                    "created_at": str(row["created_at"]),
                }
            )
        return pending

    def mark_outbox_dispatched(self, entry_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE outbox SET dispatched_at = ? WHERE id = ?",
                (_utcnow_iso(), int(entry_id)),
            )

    def claim_webhook_replay_key(
        self,
        *,
        channel: str,
        replay_key: str,
        ttl_seconds: int = 86_400,
    ) -> bool:
        now = datetime.now(timezone.utc)
        expires = now.timestamp() + max(1, int(ttl_seconds))
        now_iso = now.isoformat()
        expires_iso = datetime.fromtimestamp(expires, tz=timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM webhook_replay_keys WHERE expires_at <= ?",
                (now_iso,),
            )
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO webhook_replay_keys(replay_key, channel, first_seen_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (replay_key, channel, now_iso, expires_iso),
            )
            return (cur.rowcount or 0) > 0

    def get_run(self, trace_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT trace_id, request_id, intent, source, state, payload_json, created_at, updated_at
                FROM runs
                WHERE trace_id = ?
                """,
                (trace_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "trace_id": str(row["trace_id"]),
            "request_id": str(row["request_id"]),
            "intent": str(row["intent"]),
            "source": str(row["source"] or ""),
            "state": str(row["state"]),
            "payload": json.loads(row["payload_json"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT task_id, trace_id, task_type, worker_kind, status, payload_json, idempotency_key, created_at, updated_at
                FROM tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "task_id": str(row["task_id"]),
            "trace_id": str(row["trace_id"]),
            "task_type": str(row["task_type"]),
            "worker_kind": str(row["worker_kind"]),
            "status": str(row["status"]),
            "payload": json.loads(row["payload_json"]),
            "idempotency_key": str(row["idempotency_key"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def get_run_inspection(self, trace_id: str) -> dict[str, Any] | None:
        run = self.get_run(trace_id)
        if run is None:
            return None

        with self._lock, self._connect() as conn:
            run_state_rows = conn.execute(
                """
                SELECT state, detail_json, created_at
                FROM run_state_transitions
                WHERE trace_id = ?
                ORDER BY id ASC
                """,
                (trace_id,),
            ).fetchall()
            task_rows = conn.execute(
                """
                SELECT task_id, trace_id, task_type, worker_kind, status, payload_json, idempotency_key, created_at, updated_at
                FROM tasks
                WHERE trace_id = ?
                ORDER BY created_at ASC
                """,
                (trace_id,),
            ).fetchall()
            task_state_rows = conn.execute(
                """
                SELECT task_id, status, detail_json, created_at
                FROM task_state_transitions
                WHERE trace_id = ?
                ORDER BY id ASC
                """,
                (trace_id,),
            ).fetchall()
            policy_rows = conn.execute(
                """
                SELECT decision_id, task_id, status, reason, guardrail_flags_json, reason_codes_json,
                       obligations_json, policy_version, requires_human_approval, created_at
                FROM policy_decisions
                WHERE trace_id = ?
                ORDER BY created_at ASC
                """,
                (trace_id,),
            ).fetchall()
            artifact_rows = conn.execute(
                """
                SELECT artifact_id, task_id, kind, location, storage_backend, storage_bucket, object_key,
                       content_type, tenant_scope, checksum, created_at
                FROM artifacts
                WHERE trace_id = ?
                ORDER BY created_at ASC
                """,
                (trace_id,),
            ).fetchall()
            approval_rows = conn.execute(
                """
                SELECT review_id, task_id, trace_id, task_type, reason, payload_json, status, requested_at,
                       resolved_at, resolved_by, resolution_note
                FROM approvals
                WHERE trace_id = ?
                ORDER BY requested_at ASC
                """,
                (trace_id,),
            ).fetchall()
            outbox_rows = conn.execute(
                """
                SELECT id, event_type, aggregate_type, aggregate_id, idempotency_key, payload_json, created_at
                FROM outbox
                WHERE dispatched_at IS NULL AND (
                    payload_json LIKE ? OR aggregate_id = ?
                )
                ORDER BY id ASC
                """,
                (f'%"trace_id": "{trace_id}"%', trace_id),
            ).fetchall()

        task_timeline: dict[str, list[dict[str, Any]]] = {}
        for row in task_state_rows:
            task_id = str(row["task_id"])
            task_timeline.setdefault(task_id, []).append(
                {
                    "status": str(row["status"]),
                    "details": json.loads(row["detail_json"]),
                    "at": str(row["created_at"]),
                }
            )

        tasks: list[dict[str, Any]] = []
        for row in task_rows:
            task_id = str(row["task_id"])
            tasks.append(
                {
                    "task_id": task_id,
                    "trace_id": str(row["trace_id"]),
                    "task_type": str(row["task_type"]),
                    "worker_kind": str(row["worker_kind"]),
                    "status": str(row["status"]),
                    "payload": json.loads(row["payload_json"]),
                    "idempotency_key": str(row["idempotency_key"]),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                    "state_timeline": task_timeline.get(task_id, []),
                }
            )

        approvals: list[dict[str, Any]] = []
        for row in approval_rows:
            approvals.append(
                {
                    "review_id": str(row["review_id"]),
                    "task_id": str(row["task_id"]),
                    "trace_id": str(row["trace_id"]),
                    "task_type": str(row["task_type"]),
                    "reason": str(row["reason"]),
                    "payload": json.loads(row["payload_json"]),
                    "status": str(row["status"]),
                    "requested_at": str(row["requested_at"]),
                    "resolved_at": str(row["resolved_at"]) if row["resolved_at"] else None,
                    "resolved_by": str(row["resolved_by"]) if row["resolved_by"] else None,
                    "resolution_note": str(row["resolution_note"]) if row["resolution_note"] else None,
                }
            )

        policy_decisions: list[dict[str, Any]] = []
        for row in policy_rows:
            policy_decisions.append(
                {
                    "decision_id": str(row["decision_id"]),
                    "task_id": str(row["task_id"]),
                    "status": str(row["status"]),
                    "reason": str(row["reason"]),
                    "guardrail_flags": json.loads(row["guardrail_flags_json"]),
                    "reason_codes": json.loads(row["reason_codes_json"]),
                    "obligations": json.loads(row["obligations_json"]),
                    "policy_version": str(row["policy_version"]),
                    "requires_human_approval": bool(int(row["requires_human_approval"])),
                    "created_at": str(row["created_at"]),
                }
            )

        artifacts: list[dict[str, Any]] = []
        for row in artifact_rows:
            artifacts.append(
                {
                    "artifact_id": str(row["artifact_id"]),
                    "task_id": str(row["task_id"]),
                    "kind": str(row["kind"]),
                    "location": str(row["location"]),
                    "storage_backend": str(row["storage_backend"]),
                    "storage_bucket": str(row["storage_bucket"]) if row["storage_bucket"] else None,
                    "object_key": str(row["object_key"]) if row["object_key"] else None,
                    "content_type": str(row["content_type"]),
                    "tenant_scope": str(row["tenant_scope"]) if row["tenant_scope"] else None,
                    "checksum": str(row["checksum"]) if row["checksum"] else None,
                    "created_at": str(row["created_at"]),
                }
            )

        pending_outbox: list[dict[str, Any]] = []
        for row in outbox_rows:
            pending_outbox.append(
                {
                    "id": int(row["id"]),
                    "event_type": str(row["event_type"]),
                    "aggregate_type": str(row["aggregate_type"]),
                    "aggregate_id": str(row["aggregate_id"]),
                    "idempotency_key": str(row["idempotency_key"]),
                    "payload": json.loads(row["payload_json"]),
                    "created_at": str(row["created_at"]),
                }
            )

        return {
            "run": run,
            "run_state_timeline": [
                {"state": str(row["state"]), "details": json.loads(row["detail_json"]), "at": str(row["created_at"])}
                for row in run_state_rows
            ],
            "tasks": tasks,
            "artifacts": artifacts,
            "policy_decisions": policy_decisions,
            "approvals": approvals,
            "pending_outbox": pending_outbox,
        }


DurableStateRepository = SqliteDurableStateRepository
