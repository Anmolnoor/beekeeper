from __future__ import annotations

import json
from typing import Any

try:
    from sqlalchemy import Boolean, Integer, String, Text, create_engine, select
    from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
except Exception:  # pragma: no cover - optional dependency path
    Boolean = Integer = String = Text = None
    create_engine = None
    select = None
    DeclarativeBase = object
    Session = None
    mapped_column = None
    Mapped = Any

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


def _json_loads(value: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return json.loads(value or "{}")


if create_engine is not None:
    class Base(DeclarativeBase):
        pass


    class RunModel(Base):
        __tablename__ = "runs"

        run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
        workspace_path: Mapped[str] = mapped_column(Text)
        goal: Mapped[str] = mapped_column(Text)
        status: Mapped[str] = mapped_column(String(32))
        current_step: Mapped[str] = mapped_column(Text, default="")
        result_summary: Mapped[str] = mapped_column(Text, default="")
        requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
        created_at: Mapped[str] = mapped_column(String(64))
        updated_at: Mapped[str] = mapped_column(String(64))
        completed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)


    class JobModel(Base):
        __tablename__ = "jobs"

        job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
        run_id: Mapped[str] = mapped_column(String(64), index=True)
        job_type: Mapped[str] = mapped_column(String(64))
        worker_kind: Mapped[str] = mapped_column(String(64))
        payload_json: Mapped[str] = mapped_column(Text, default="{}")
        status: Mapped[str] = mapped_column(String(32), index=True)
        lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
        lease_expires_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
        attempt_count: Mapped[int] = mapped_column(Integer, default=0)
        created_at: Mapped[str] = mapped_column(String(64))
        scheduled_at: Mapped[str] = mapped_column(String(64))
        started_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
        finished_at: Mapped[str | None] = mapped_column(String(64), nullable=True)


    class WorkerAttemptModel(Base):
        __tablename__ = "worker_attempts"

        attempt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
        job_id: Mapped[str] = mapped_column(String(64), index=True)
        run_id: Mapped[str] = mapped_column(String(64), index=True)
        worker_kind: Mapped[str] = mapped_column(String(64))
        status: Mapped[str] = mapped_column(String(32))
        pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
        started_at: Mapped[str] = mapped_column(String(64))
        heartbeat_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
        finished_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
        exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
        error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
        artifact_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)


    class ApprovalModel(Base):
        __tablename__ = "approvals"

        approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
        run_id: Mapped[str] = mapped_column(String(64), index=True)
        job_id: Mapped[str] = mapped_column(String(64), index=True)
        action_type: Mapped[str] = mapped_column(String(128))
        risk_level: Mapped[str] = mapped_column(String(32))
        request_payload_json: Mapped[str] = mapped_column(Text, default="{}")
        status: Mapped[str] = mapped_column(String(32), index=True)
        requested_at: Mapped[str] = mapped_column(String(64))
        resolved_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
        resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


    class TraceEventModel(Base):
        __tablename__ = "trace_events"

        event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
        run_id: Mapped[str] = mapped_column(String(64), index=True)
        job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
        attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
        parent_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
        event_type: Mapped[str] = mapped_column(String(64))
        actor: Mapped[str] = mapped_column(String(128))
        payload_json: Mapped[str] = mapped_column(Text, default="{}")
        created_at: Mapped[str] = mapped_column(String(64))


    class ArtifactModel(Base):
        __tablename__ = "artifacts"

        artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
        run_id: Mapped[str] = mapped_column(String(64), index=True)
        job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
        attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
        bucket: Mapped[str] = mapped_column(String(128))
        object_key: Mapped[str] = mapped_column(Text)
        content_type: Mapped[str] = mapped_column(String(256))
        size_bytes: Mapped[int] = mapped_column(Integer)
        sha256: Mapped[str] = mapped_column(String(128))
        created_at: Mapped[str] = mapped_column(String(64))
else:  # pragma: no cover - import fallback
    Base = object
    RunModel = JobModel = WorkerAttemptModel = ApprovalModel = TraceEventModel = ArtifactModel = object


class SqlAlchemyRuntimeStateRepository:
    """Production-oriented durable state repository backed by SQLAlchemy."""

    def __init__(self, database_url: str) -> None:
        if create_engine is None or Session is None or select is None:
            raise RuntimeError("sqlalchemy_not_installed")
        self.database_url = database_url
        self.engine = create_engine(database_url, future=True, pool_pre_ping=True)

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)

    @staticmethod
    def _run_to_dict(row: RunModel) -> dict[str, Any]:
        return {
            "run_id": row.run_id,
            "workspace_path": row.workspace_path,
            "goal": row.goal,
            "status": row.status,
            "current_step": row.current_step,
            "result_summary": row.result_summary,
            "requires_approval": bool(row.requires_approval),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "completed_at": row.completed_at,
        }

    @staticmethod
    def _job_to_dict(row: JobModel) -> dict[str, Any]:
        return {
            "job_id": row.job_id,
            "run_id": row.run_id,
            "job_type": row.job_type,
            "worker_kind": row.worker_kind,
            "payload_json": _json_loads(row.payload_json),
            "status": row.status,
            "lease_owner": row.lease_owner,
            "lease_expires_at": row.lease_expires_at,
            "attempt_count": row.attempt_count,
            "created_at": row.created_at,
            "scheduled_at": row.scheduled_at,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
        }

    @staticmethod
    def _attempt_to_dict(row: WorkerAttemptModel) -> dict[str, Any]:
        return {
            "attempt_id": row.attempt_id,
            "job_id": row.job_id,
            "run_id": row.run_id,
            "worker_kind": row.worker_kind,
            "status": row.status,
            "pid": row.pid,
            "started_at": row.started_at,
            "heartbeat_at": row.heartbeat_at,
            "finished_at": row.finished_at,
            "exit_code": row.exit_code,
            "error_code": row.error_code,
            "artifact_prefix": row.artifact_prefix,
        }

    @staticmethod
    def _approval_to_dict(row: ApprovalModel) -> dict[str, Any]:
        return {
            "approval_id": row.approval_id,
            "run_id": row.run_id,
            "job_id": row.job_id,
            "action_type": row.action_type,
            "risk_level": row.risk_level,
            "request_payload_json": _json_loads(row.request_payload_json),
            "status": row.status,
            "requested_at": row.requested_at,
            "resolved_at": row.resolved_at,
            "resolved_by": row.resolved_by,
        }

    @staticmethod
    def _trace_to_dict(row: TraceEventModel) -> dict[str, Any]:
        return {
            "event_id": row.event_id,
            "run_id": row.run_id,
            "job_id": row.job_id,
            "attempt_id": row.attempt_id,
            "parent_event_id": row.parent_event_id,
            "event_type": row.event_type,
            "actor": row.actor,
            "payload_json": _json_loads(row.payload_json),
            "created_at": row.created_at,
        }

    @staticmethod
    def _artifact_to_dict(row: ArtifactModel) -> dict[str, Any]:
        return {
            "artifact_id": row.artifact_id,
            "run_id": row.run_id,
            "job_id": row.job_id,
            "attempt_id": row.attempt_id,
            "bucket": row.bucket,
            "object_key": row.object_key,
            "content_type": row.content_type,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "created_at": row.created_at,
        }

    def create_run(self, record: RunRecord) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = RunModel(**record.to_dict())
            session.add(row)
            session.commit()
        return record.to_dict()

    def update_run(self, run_id: str, **fields: Any) -> dict[str, Any]:
        fields["updated_at"] = utcnow_iso()
        with Session(self.engine) as session:
            row = session.get(RunModel, run_id)
            if row is None:
                raise KeyError(run_id)
            for key, value in fields.items():
                setattr(row, key, value)
            session.commit()
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(RunModel, run_id)
            if row is None:
                return None
            result = self._run_to_dict(row)
        result["jobs"] = self.list_jobs(run_id=run_id)
        result["pending_approvals"] = self.list_approvals(run_id=run_id, status="pending")
        return result

    def create_job(self, record: JobRecord) -> dict[str, Any]:
        payload = record.to_dict()
        payload["payload_json"] = _json_dumps(record.payload_json)
        with Session(self.engine) as session:
            session.add(JobModel(**payload))
            session.commit()
        job = self.get_job(record.job_id)
        if job is None:
            raise KeyError(record.job_id)
        return job

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(JobModel, job_id)
            if row is None:
                return None
            return self._job_to_dict(row)

    def list_jobs(self, *, run_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            stmt = select(JobModel).order_by(JobModel.created_at.asc())
            if run_id is not None:
                stmt = stmt.where(JobModel.run_id == run_id)
            if status is not None:
                stmt = stmt.where(JobModel.status == status)
            rows = session.execute(stmt).scalars().all()
            return [self._job_to_dict(row) for row in rows]

    def claim_next_job(self, *, lease_owner: str, run_id: str | None = None) -> dict[str, Any] | None:
        now = utcnow_iso()
        with Session(self.engine) as session:
            stmt = (
                select(JobModel)
                .where(JobModel.status.in_(("queued", "ready")))
                .order_by(JobModel.scheduled_at.asc(), JobModel.created_at.asc())
                .with_for_update(skip_locked=True)
            )
            if run_id is not None:
                stmt = stmt.where(JobModel.run_id == run_id)
            row = session.execute(stmt.limit(1)).scalars().first()
            if row is None:
                return None
            row.status = "running"
            row.lease_owner = lease_owner
            row.lease_expires_at = now
            row.started_at = row.started_at or now
            row.attempt_count += 1
            session.commit()
            return self._job_to_dict(row)

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(JobModel, job_id)
            if row is None:
                raise KeyError(job_id)
            for key, value in fields.items():
                if key == "payload_json" and isinstance(value, dict):
                    value = _json_dumps(value)
                setattr(row, key, value)
            session.commit()
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def create_attempt(self, record: WorkerAttemptRecord) -> dict[str, Any]:
        with Session(self.engine) as session:
            session.add(WorkerAttemptModel(**record.to_dict()))
            session.commit()
        attempt = self.get_attempt(record.attempt_id)
        if attempt is None:
            raise KeyError(record.attempt_id)
        return attempt

    def get_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(WorkerAttemptModel, attempt_id)
            if row is None:
                return None
            return self._attempt_to_dict(row)

    def update_attempt(self, attempt_id: str, **fields: Any) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(WorkerAttemptModel, attempt_id)
            if row is None:
                raise KeyError(attempt_id)
            for key, value in fields.items():
                setattr(row, key, value)
            session.commit()
        attempt = self.get_attempt(attempt_id)
        if attempt is None:
            raise KeyError(attempt_id)
        return attempt

    def create_approval(self, record: ApprovalRecord) -> dict[str, Any]:
        payload = record.to_dict()
        payload["request_payload_json"] = _json_dumps(record.request_payload_json)
        with Session(self.engine) as session:
            session.add(ApprovalModel(**payload))
            session.commit()
        approval = self.get_approval(record.approval_id)
        if approval is None:
            raise KeyError(record.approval_id)
        return approval

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(ApprovalModel, approval_id)
            if row is None:
                return None
            return self._approval_to_dict(row)

    def resolve_approval(self, approval_id: str, *, status: str, resolved_by: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(ApprovalModel, approval_id)
            if row is None:
                raise KeyError(approval_id)
            row.status = status
            row.resolved_at = utcnow_iso()
            row.resolved_by = resolved_by
            session.commit()
        approval = self.get_approval(approval_id)
        if approval is None:
            raise KeyError(approval_id)
        return approval

    def list_approvals(self, *, run_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            stmt = select(ApprovalModel).order_by(ApprovalModel.requested_at.asc())
            if run_id is not None:
                stmt = stmt.where(ApprovalModel.run_id == run_id)
            if status is not None:
                stmt = stmt.where(ApprovalModel.status == status)
            rows = session.execute(stmt).scalars().all()
            return [self._approval_to_dict(row) for row in rows]

    def append_trace_event(self, record: TraceEventRecord) -> dict[str, Any]:
        payload = record.to_dict()
        payload["payload_json"] = _json_dumps(record.payload_json)
        with Session(self.engine) as session:
            session.add(TraceEventModel(**payload))
            session.commit()
        return record.to_dict()

    def list_trace_events(self, run_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            stmt = select(TraceEventModel).where(TraceEventModel.run_id == run_id).order_by(TraceEventModel.created_at.asc())
            rows = session.execute(stmt).scalars().all()
            return [self._trace_to_dict(row) for row in rows]

    def create_artifact(self, record: ArtifactRecord) -> dict[str, Any]:
        with Session(self.engine) as session:
            session.add(ArtifactModel(**record.to_dict()))
            session.commit()
        return record.to_dict()

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            stmt = select(ArtifactModel).where(ArtifactModel.run_id == run_id).order_by(ArtifactModel.created_at.asc())
            rows = session.execute(stmt).scalars().all()
            return [self._artifact_to_dict(row) for row in rows]
