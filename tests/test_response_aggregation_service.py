from __future__ import annotations

from beekeeper.contracts import ResultEnvelope, Status, WorkerKind
from beekeeper.response_aggregation_service import ResponseAggregationService


def test_terminal_state_waiting_approval_when_blocked_with_review() -> None:
    service = ResponseAggregationService()
    result = ResultEnvelope(
        task_id="t1",
        agent_id="a1",
        worker_kind=WorkerKind.web_search,
        status=Status.blocked,
        output={"human_review_id": "r1"},
    )
    assert service.terminal_state_for_results([result]) == "waiting_approval"


def test_terminal_state_failed_when_any_failed() -> None:
    service = ResponseAggregationService()
    success = ResultEnvelope(
        task_id="t1",
        agent_id="a1",
        worker_kind=WorkerKind.web_search,
        status=Status.success,
    )
    failed = ResultEnvelope(
        task_id="t2",
        agent_id="a1",
        worker_kind=WorkerKind.audit,
        status=Status.failed,
    )
    assert service.terminal_state_for_results([success, failed]) == "failed"
