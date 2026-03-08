from __future__ import annotations

from ..data_plane.models import ApprovalRecord, new_id
from ..data_plane.repositories.runtime_state import RuntimeStateRepository
from ..trace import TraceEventStore
from ..workers.base import ApprovalRequest


class ApprovalService:
    def __init__(self, repository: RuntimeStateRepository, trace_store: TraceEventStore) -> None:
        self.repository = repository
        self.trace_store = trace_store

    def ensure_pending_approval(
        self,
        *,
        run_id: str,
        job_id: str,
        request: ApprovalRequest,
    ) -> dict[str, object]:
        pending = [
            approval
            for approval in self.repository.list_approvals(run_id=run_id, status="pending")
            if approval["job_id"] == job_id and approval["action_type"] == request.action_type
        ]
        if pending:
            return pending[0]
        approval = self.repository.create_approval(
            ApprovalRecord(
                approval_id=new_id("approval"),
                run_id=run_id,
                job_id=job_id,
                action_type=request.action_type,
                risk_level=request.risk_level,
                request_payload_json={"reason": request.reason, **request.payload},
                status="pending",
            )
        )
        self.trace_store.append(
            run_id=run_id,
            job_id=job_id,
            event_type="approval_requested",
            actor="approval_service",
            payload=approval,
        )
        return approval

    def resolve(self, approval_id: str, *, approved: bool, resolved_by: str) -> dict[str, object]:
        status = "approved" if approved else "rejected"
        approval = self.repository.resolve_approval(approval_id, status=status, resolved_by=resolved_by)
        next_job_status = "ready" if approved else "rejected"
        self.repository.update_job(approval["job_id"], status=next_job_status)
        run_status = "queued" if approved else "failed"
        self.repository.update_run(approval["run_id"], status=run_status, requires_approval=False)
        self.trace_store.append(
            run_id=approval["run_id"],
            job_id=approval["job_id"],
            event_type="approval_resolved",
            actor=resolved_by,
            payload={"approval_id": approval_id, "status": status},
        )
        return approval

    def is_approved(self, *, run_id: str, job_id: str, action_type: str) -> bool:
        approvals = self.repository.list_approvals(run_id=run_id)
        return any(
            approval["job_id"] == job_id
            and approval["action_type"] == action_type
            and approval["status"] == "approved"
            for approval in approvals
        )
