from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass(slots=True)
class RunRecord:
    run_id: str
    workspace_path: str
    goal: str
    status: str
    current_step: str = ""
    result_summary: str = ""
    requires_approval: bool = False
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class JobRecord:
    job_id: str
    run_id: str
    job_type: str
    worker_kind: str
    payload_json: dict[str, Any]
    status: str
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    attempt_count: int = 0
    created_at: str = field(default_factory=utcnow_iso)
    scheduled_at: str = field(default_factory=utcnow_iso)
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkerAttemptRecord:
    attempt_id: str
    job_id: str
    run_id: str
    worker_kind: str
    status: str
    pid: int | None = None
    started_at: str = field(default_factory=utcnow_iso)
    heartbeat_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error_code: str | None = None
    artifact_prefix: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ApprovalRecord:
    approval_id: str
    run_id: str
    job_id: str
    action_type: str
    risk_level: str
    request_payload_json: dict[str, Any]
    status: str
    requested_at: str = field(default_factory=utcnow_iso)
    resolved_at: str | None = None
    resolved_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TraceEventRecord:
    event_id: str
    run_id: str
    job_id: str | None
    attempt_id: str | None
    parent_event_id: str | None
    event_type: str
    actor: str
    payload_json: dict[str, Any]
    created_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ArtifactRecord:
    artifact_id: str
    run_id: str
    job_id: str | None
    attempt_id: str | None
    bucket: str
    object_key: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
