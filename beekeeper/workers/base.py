from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config.settings import Phase1Settings


@dataclass(slots=True)
class ApprovalRequest:
    action_type: str
    risk_level: str
    reason: str
    payload: dict[str, Any]


@dataclass(slots=True)
class WorkerContext:
    run_id: str
    job_id: str
    attempt_id: str
    workspace_path: Path
    settings: Phase1Settings
    artifact_store: Any


@dataclass(slots=True)
class WorkerResult:
    status: str
    summary: str
    output: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, str]] = field(default_factory=list)


class BaseWorker:
    kind = "base"

    def preflight(self, payload: dict[str, Any], context: WorkerContext) -> ApprovalRequest | None:
        return None

    def execute(self, payload: dict[str, Any], context: WorkerContext) -> WorkerResult:
        raise NotImplementedError
