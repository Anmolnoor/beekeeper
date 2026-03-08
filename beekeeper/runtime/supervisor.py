from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from ..config.settings import Phase1Settings
from ..data_plane.models import WorkerAttemptRecord, new_id, utcnow_iso
from ..trace import TraceEventStore
from ..workers.base import BaseWorker, WorkerContext
from .approval_service import ApprovalService


class Supervisor:
    def __init__(
        self,
        repository: Any,
        trace_store: TraceEventStore,
        artifact_store: Any,
        approval_service: ApprovalService,
        workers: dict[str, BaseWorker],
        settings: Phase1Settings,
    ) -> None:
        self.repository = repository
        self.trace_store = trace_store
        self.artifact_store = artifact_store
        self.approval_service = approval_service
        self.workers = workers
        self.settings = settings
        self.lease_owner = f"supervisor:{os.getpid()}"

    def run_until_idle(self, *, run_id: str | None = None, max_idle_cycles: int = 3) -> bool:
        idle_cycles = 0
        processed = False
        while idle_cycles < max_idle_cycles:
            did_work = self.run_once(run_id=run_id)
            processed = processed or did_work
            if did_work:
                idle_cycles = 0
                continue
            idle_cycles += 1
            time.sleep(self.settings.supervisor_poll_seconds)
        return processed

    def run_once(self, *, run_id: str | None = None) -> bool:
        job = self.repository.claim_next_job(lease_owner=self.lease_owner, run_id=run_id)
        if job is None:
            return False
        worker = self.workers.get(job["worker_kind"])
        if worker is None:
            self.repository.update_job(job["job_id"], status="failed", finished_at=utcnow_iso())
            self.repository.update_run(job["run_id"], status="failed", result_summary=f"unsupported worker {job['worker_kind']}")
            return True
        attempt = self.repository.create_attempt(
            WorkerAttemptRecord(
                attempt_id=new_id("attempt"),
                job_id=job["job_id"],
                run_id=job["run_id"],
                worker_kind=job["worker_kind"],
                status="running",
                pid=os.getpid(),
                heartbeat_at=utcnow_iso(),
                artifact_prefix=f"{job['run_id']}/{job['job_id']}",
            )
        )
        self.trace_store.append(
            run_id=job["run_id"],
            job_id=job["job_id"],
            attempt_id=attempt["attempt_id"],
            event_type="job_started",
            actor="supervisor",
            payload={"worker_kind": job["worker_kind"], "job_type": job["job_type"]},
        )
        workspace_path = Path(self.repository.get_run(job["run_id"])["workspace_path"]).resolve()
        context = WorkerContext(
            run_id=job["run_id"],
            job_id=job["job_id"],
            attempt_id=attempt["attempt_id"],
            workspace_path=workspace_path,
            settings=self.settings,
            artifact_store=self.artifact_store,
        )
        approval_request = worker.preflight(job["payload_json"], context)
        if approval_request is not None:
            if self.approval_service.is_approved(
                run_id=job["run_id"],
                job_id=job["job_id"],
                action_type=approval_request.action_type,
            ):
                approval_request = None
        if approval_request is not None:
            approval = self.approval_service.ensure_pending_approval(
                run_id=job["run_id"],
                job_id=job["job_id"],
                request=approval_request,
            )
            self.repository.update_job(job["job_id"], status="awaiting_approval", finished_at=utcnow_iso())
            self.repository.update_attempt(
                attempt["attempt_id"],
                status="blocked",
                heartbeat_at=utcnow_iso(),
                finished_at=utcnow_iso(),
                error_code="approval_required",
            )
            self.repository.update_run(
                job["run_id"],
                status="awaiting_approval",
                requires_approval=True,
                current_step=f"Waiting for approval {approval['approval_id']}",
                result_summary=approval_request.reason,
            )
            return True
        try:
            result = worker.execute(job["payload_json"], context)
        except Exception as exc:
            self.repository.update_job(job["job_id"], status="failed", finished_at=utcnow_iso())
            self.repository.update_attempt(
                attempt["attempt_id"],
                status="failed",
                heartbeat_at=utcnow_iso(),
                finished_at=utcnow_iso(),
                error_code=exc.__class__.__name__,
            )
            self.repository.update_run(job["run_id"], status="failed", result_summary=str(exc))
            self.trace_store.append(
                run_id=job["run_id"],
                job_id=job["job_id"],
                attempt_id=attempt["attempt_id"],
                event_type="job_failed",
                actor="supervisor",
                payload={"error": str(exc), "error_type": exc.__class__.__name__},
            )
            return True

        job_status = result.status
        self.repository.update_job(job["job_id"], status=job_status, finished_at=utcnow_iso())
        self.repository.update_attempt(
            attempt["attempt_id"],
            status=job_status,
            heartbeat_at=utcnow_iso(),
            finished_at=utcnow_iso(),
            exit_code=0 if job_status == "succeeded" else 1,
        )
        self.trace_store.append(
            run_id=job["run_id"],
            job_id=job["job_id"],
            attempt_id=attempt["attempt_id"],
            event_type="job_finished",
            actor="supervisor",
            payload={
                "status": job_status,
                "summary": result.summary,
                "output": result.output,
                "artifacts": result.artifacts,
            },
        )
        jobs = self.repository.list_jobs(run_id=job["run_id"])
        if all(item["status"] == "succeeded" for item in jobs):
            self.repository.update_run(
                job["run_id"],
                status="completed",
                current_step="done",
                result_summary=result.summary,
                completed_at=utcnow_iso(),
                requires_approval=False,
            )
        elif any(item["status"] == "failed" for item in jobs):
            self.repository.update_run(job["run_id"], status="failed", result_summary=result.summary)
        else:
            next_step = next((item["job_type"] for item in jobs if item["status"] in {"queued", "ready", "running"}), "running")
            self.repository.update_run(job["run_id"], status="running", current_step=next_step, result_summary=result.summary)
        return True
