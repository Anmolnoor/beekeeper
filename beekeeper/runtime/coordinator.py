from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config.settings import Phase1Settings
from ..data_plane.models import JobRecord, RunRecord, new_id
from ..data_plane.repositories.runtime_state import RuntimeStateRepository
from ..trace import TraceEventStore
from .dispatcher import JobDispatcher


class RuntimeCoordinator:
    def __init__(
        self,
        repository: RuntimeStateRepository,
        trace_store: TraceEventStore,
        settings: Phase1Settings,
        dispatcher: JobDispatcher | None = None,
    ) -> None:
        self.repository = repository
        self.trace_store = trace_store
        self.settings = settings
        self.dispatcher = dispatcher or JobDispatcher()

    def create_run(self, request: dict[str, Any]) -> dict[str, Any]:
        workspace_path = Path(str(request.get("workspace_path") or self.settings.workspace_root)).resolve()
        run = self.repository.create_run(
            RunRecord(
                run_id=new_id("run"),
                workspace_path=str(workspace_path),
                goal=str(request.get("goal") or "Execute requested jobs"),
                status="queued",
            )
        )
        self.trace_store.append(
            run_id=run["run_id"],
            event_type="run_created",
            actor="coordinator",
            payload={"goal": run["goal"], "workspace_path": run["workspace_path"]},
        )
        jobs = self.dispatcher.build_jobs(request)
        if not jobs:
            raise ValueError("run_requires_at_least_one_job")
        for index, job in enumerate(jobs):
            created = self.repository.create_job(
                JobRecord(
                    job_id=new_id("job"),
                    run_id=run["run_id"],
                    job_type=str(job["job_type"]),
                    worker_kind=str(job["worker_kind"]),
                    payload_json=dict(job.get("payload") or {}),
                    status="queued",
                )
            )
            self.trace_store.append(
                run_id=run["run_id"],
                job_id=created["job_id"],
                event_type="job_enqueued",
                actor="dispatcher",
                payload={"order": index + 1, "worker_kind": created["worker_kind"], "job_type": created["job_type"]},
            )
        return self.repository.get_run(run["run_id"]) or run
