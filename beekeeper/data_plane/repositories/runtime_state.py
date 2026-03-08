from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from ..models import (
    ApprovalRecord,
    ArtifactRecord,
    JobRecord,
    RunRecord,
    TraceEventRecord,
    WorkerAttemptRecord,
    utcnow_iso,
)


def _json_dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


class RuntimeStateRepository:
    """Phase 1 durable state, trace, and artifact metadata store.

    The repository uses sqlite for local execution and tests, while keeping
    the schema aligned with the Phase 1 Postgres target.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def initialize(self) -> None:
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    workspace_path TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_step TEXT NOT NULL DEFAULT '',
                    result_summary TEXT NOT NULL DEFAULT '',
                    requires_approval INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    worker_kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, scheduled_at);

                CREATE TABLE IF NOT EXISTS worker_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    worker_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pid INTEGER,
                    started_at TEXT NOT NULL,
                    heartbeat_at TEXT,
                    finished_at TEXT,
                    exit_code INTEGER,
                    error_code TEXT,
                    artifact_prefix TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_attempts_job ON worker_attempts(job_id, started_at);

                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    request_payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolved_by TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_approvals_run ON approvals(run_id, requested_at);
                CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, requested_at);

                CREATE TABLE IF NOT EXISTS trace_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    job_id TEXT,
                    attempt_id TEXT,
                    parent_event_id TEXT,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_trace_run ON trace_events(run_id, created_at);

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    job_id TEXT,
                    attempt_id TEXT,
                    bucket TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id, created_at);
                """
            )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in ("payload_json", "request_payload_json"):
            if key in result and isinstance(result[key], str):
                result[key] = json.loads(result[key])
        return result

    def create_run(self, record: RunRecord) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs(
                    run_id, workspace_path, goal, status, current_step, result_summary,
                    requires_approval, created_at, updated_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.workspace_path,
                    record.goal,
                    record.status,
                    record.current_step,
                    record.result_summary,
                    1 if record.requires_approval else 0,
                    record.created_at,
                    record.updated_at,
                    record.completed_at,
                ),
            )
        return record.to_dict()

    def update_run(self, run_id: str, **fields: Any) -> dict[str, Any]:
        if not fields:
            existing = self.get_run(run_id)
            if existing is None:
                raise KeyError(run_id)
            return existing
        fields["updated_at"] = utcnow_iso()
        columns = ", ".join(f"{key} = ?" for key in fields)
        values = [1 if value is True and key == "requires_approval" else 0 if value is False and key == "requires_approval" else value for key, value in fields.items()]
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE runs SET {columns} WHERE run_id = ?", [*values, run_id])
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        result = self._row_to_dict(row)
        if result is not None:
            result["requires_approval"] = bool(result["requires_approval"])
            result["jobs"] = self.list_jobs(run_id=run_id)
            result["pending_approvals"] = self.list_approvals(run_id=run_id, status="pending")
        return result

    def create_job(self, record: JobRecord) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs(
                    job_id, run_id, job_type, worker_kind, payload_json, status, lease_owner,
                    lease_expires_at, attempt_count, created_at, scheduled_at, started_at, finished_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.job_id,
                    record.run_id,
                    record.job_type,
                    record.worker_kind,
                    _json_dumps(record.payload_json),
                    record.status,
                    record.lease_owner,
                    record.lease_expires_at,
                    record.attempt_count,
                    record.created_at,
                    record.scheduled_at,
                    record.started_at,
                    record.finished_at,
                ),
            )
        job = self.get_job(record.job_id)
        if job is None:
            raise KeyError(record.job_id)
        return job

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._row_to_dict(row)

    def list_jobs(self, *, run_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        where: list[str] = []
        values: list[Any] = []
        if run_id is not None:
            where.append("run_id = ?")
            values.append(run_id)
        if status is not None:
            where.append("status = ?")
            values.append(status)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM jobs {clause} ORDER BY created_at ASC",
                values,
            ).fetchall()
        return [self._row_to_dict(row) for row in rows if self._row_to_dict(row) is not None]

    def claim_next_job(self, *, lease_owner: str, run_id: str | None = None) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            if run_id:
                row = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE run_id = ? AND status IN ('queued', 'ready')
                    ORDER BY scheduled_at ASC, created_at ASC
                    LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status IN ('queued', 'ready')
                    ORDER BY scheduled_at ASC, created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
            if row is None:
                return None
            now = utcnow_iso()
            conn.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    lease_owner = ?,
                    lease_expires_at = ?,
                    started_at = COALESCE(started_at, ?),
                    attempt_count = attempt_count + 1
                WHERE job_id = ?
                """,
                (lease_owner, now, now, row["job_id"]),
            )
        return self.get_job(str(row["job_id"]))

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any]:
        if not fields:
            existing = self.get_job(job_id)
            if existing is None:
                raise KeyError(job_id)
            return existing
        if "payload_json" in fields and isinstance(fields["payload_json"], dict):
            fields["payload_json"] = _json_dumps(fields["payload_json"])
        columns = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values())
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {columns} WHERE job_id = ?", [*values, job_id])
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def create_attempt(self, record: WorkerAttemptRecord) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO worker_attempts(
                    attempt_id, job_id, run_id, worker_kind, status, pid, started_at,
                    heartbeat_at, finished_at, exit_code, error_code, artifact_prefix
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.attempt_id,
                    record.job_id,
                    record.run_id,
                    record.worker_kind,
                    record.status,
                    record.pid,
                    record.started_at,
                    record.heartbeat_at,
                    record.finished_at,
                    record.exit_code,
                    record.error_code,
                    record.artifact_prefix,
                ),
            )
        attempt = self.get_attempt(record.attempt_id)
        if attempt is None:
            raise KeyError(record.attempt_id)
        return attempt

    def get_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM worker_attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        return self._row_to_dict(row)

    def update_attempt(self, attempt_id: str, **fields: Any) -> dict[str, Any]:
        if not fields:
            existing = self.get_attempt(attempt_id)
            if existing is None:
                raise KeyError(attempt_id)
            return existing
        columns = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values())
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE worker_attempts SET {columns} WHERE attempt_id = ?", [*values, attempt_id])
        attempt = self.get_attempt(attempt_id)
        if attempt is None:
            raise KeyError(attempt_id)
        return attempt

    def create_approval(self, record: ApprovalRecord) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals(
                    approval_id, run_id, job_id, action_type, risk_level,
                    request_payload_json, status, requested_at, resolved_at, resolved_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.approval_id,
                    record.run_id,
                    record.job_id,
                    record.action_type,
                    record.risk_level,
                    _json_dumps(record.request_payload_json),
                    record.status,
                    record.requested_at,
                    record.resolved_at,
                    record.resolved_by,
                ),
            )
        approval = self.get_approval(record.approval_id)
        if approval is None:
            raise KeyError(record.approval_id)
        return approval

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        return self._row_to_dict(row)

    def resolve_approval(self, approval_id: str, *, status: str, resolved_by: str) -> dict[str, Any]:
        now = utcnow_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE approvals
                SET status = ?, resolved_at = ?, resolved_by = ?
                WHERE approval_id = ?
                """,
                (status, now, resolved_by, approval_id),
            )
        approval = self.get_approval(approval_id)
        if approval is None:
            raise KeyError(approval_id)
        return approval

    def list_approvals(self, *, run_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        where: list[str] = []
        values: list[Any] = []
        if run_id is not None:
            where.append("run_id = ?")
            values.append(run_id)
        if status is not None:
            where.append("status = ?")
            values.append(status)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM approvals {clause} ORDER BY requested_at ASC",
                values,
            ).fetchall()
        return [self._row_to_dict(row) for row in rows if self._row_to_dict(row) is not None]

    def append_trace_event(self, record: TraceEventRecord) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trace_events(
                    event_id, run_id, job_id, attempt_id, parent_event_id, event_type,
                    actor, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.event_id,
                    record.run_id,
                    record.job_id,
                    record.attempt_id,
                    record.parent_event_id,
                    record.event_type,
                    record.actor,
                    _json_dumps(record.payload_json),
                    record.created_at,
                ),
            )
        return record.to_dict()

    def list_trace_events(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM trace_events
                WHERE run_id = ?
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows if self._row_to_dict(row) is not None]

    def create_artifact(self, record: ArtifactRecord) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts(
                    artifact_id, run_id, job_id, attempt_id, bucket, object_key, content_type,
                    size_bytes, sha256, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.artifact_id,
                    record.run_id,
                    record.job_id,
                    record.attempt_id,
                    record.bucket,
                    record.object_key,
                    record.content_type,
                    record.size_bytes,
                    record.sha256,
                    record.created_at,
                ),
            )
        return record.to_dict()

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM artifacts
                WHERE run_id = ?
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows if self._row_to_dict(row) is not None]
