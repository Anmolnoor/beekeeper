from __future__ import annotations

from pathlib import Path

from beekeeper.contracts import PolicyDecision, TaskEnvelope, WorkerKind
from beekeeper.data_plane.repositories import DurableStateRepository
from beekeeper.honeycomb import HoneycombConfig, HoneycombStore
from beekeeper.queen import QueenAgent, QueenConfig


def test_sqlite_durable_state_records_runs_tasks_and_outbox(tmp_path: Path) -> None:
    repo = DurableStateRepository(tmp_path / "control_plane.db")

    repo.record_run_state(
        trace_id="trace-1",
        request_id="req-1",
        intent="research_topic",
        state="requested",
        payload={"scheduler_backend": "inline"},
    )
    repo.record_run_state(
        trace_id="trace-1",
        request_id="req-1",
        intent="research_topic",
        state="running",
    )
    run = repo.get_run("trace-1")
    assert run is not None
    assert run["state"] == "running"

    task = TaskEnvelope(
        queen_trace_id="trace-1",
        queen_request_id="req-1",
        task_type="research_topic",
        worker_kind=WorkerKind.web_search,
        payload={"query": "x"},
        idempotency_key="idem-1",
    )
    repo.record_task(task)
    row = repo.get_task(task.task_id)
    assert row is not None
    assert row["status"] == "queued"

    repo.enqueue_outbox(
        event_type="task_state_changed",
        aggregate_type="task",
        aggregate_id=task.task_id,
        idempotency_key=f"task_state:{task.task_id}:queued",
        payload={"task_id": task.task_id},
    )
    pending = repo.list_pending_outbox(limit=10)
    assert len(pending) == 1
    repo.mark_outbox_dispatched(pending[0]["id"])
    assert repo.list_pending_outbox(limit=10) == []


def test_honeycomb_dual_writes_task_policy_and_outbox(tmp_path: Path) -> None:
    store = HoneycombStore(HoneycombConfig(root_dir=tmp_path / ".honeycomb"))
    assert store.durable_state is not None

    task = TaskEnvelope(
        queen_trace_id="trace-2",
        queen_request_id="req-2",
        task_type="research_topic",
        worker_kind=WorkerKind.web_search,
        payload={"query": "durable"},
        idempotency_key="idem-2",
    )
    store.write_task(task)
    task_row = store.durable_state.get_task(task.task_id)
    assert task_row is not None
    assert task_row["status"] == "queued"

    decision = PolicyDecision(task_id=task.task_id, status="approve", reason="ok")
    store.write_policy_decision(decision, trace_id=task.queen_trace_id)
    pending = store.durable_state.list_pending_outbox(limit=20)
    event_types = {item["event_type"] for item in pending}
    assert "task_state_changed" in event_types
    assert "policy_decision_recorded" in event_types


def test_honeycomb_records_artifact_manifest_in_durable_state(tmp_path: Path) -> None:
    store = HoneycombStore(HoneycombConfig(root_dir=tmp_path / ".honeycomb"))
    store.record_run_state(
        trace_id="trace-artifact",
        request_id="req-artifact",
        intent="research_topic",
        state="requested",
    )
    artifact = store.write_artifact("trace-artifact", "task-artifact", '{"ok":true}', kind="json")
    assert artifact.object_key is not None
    assert artifact.storage_backend == "local"
    assert store.durable_state is not None
    inspection = store.durable_state.get_run_inspection("trace-artifact")
    assert inspection is not None
    assert len(inspection["artifacts"]) == 1
    assert inspection["artifacts"][0]["artifact_id"] == artifact.artifact_id
    assert inspection["artifacts"][0]["object_key"] == artifact.object_key


def test_honeycomb_reviews_use_durable_repository(tmp_path: Path) -> None:
    store = HoneycombStore(HoneycombConfig(root_dir=tmp_path / ".honeycomb"))
    assert store.durable_state is not None
    task = TaskEnvelope(
        queen_trace_id="trace-review",
        queen_request_id="req-review",
        task_type="research_topic",
        worker_kind=WorkerKind.web_search,
        payload={"query": "approval path"},
        idempotency_key="idem-review",
    )
    review = store.enqueue_review(task=task, reason="human_approval_required")
    loaded = store.durable_state.get_review(review.review_id)
    assert loaded is not None
    assert loaded.status == "pending"
    assert store.get_review(review.review_id) is not None
    pending = store.durable_state.list_pending_reviews()
    assert any(item.review_id == review.review_id for item in pending)

    resolved = store.resolve_review(review.review_id, approved=True, approver="qa", note="approved")
    assert resolved.status == "approved"
    reloaded = store.durable_state.get_review(review.review_id)
    assert reloaded is not None
    assert reloaded.status == "approved"
    outbox_types = [row["event_type"] for row in store.durable_state.list_pending_outbox(limit=50)]
    assert outbox_types.count("approval_state_changed") >= 2


def test_queen_run_records_durable_run_state(tmp_path: Path) -> None:
    queen = QueenAgent(
        QueenConfig(
            honeycomb_root=tmp_path / ".honeycomb",
            scheduler_backend="inline",
            max_reruns=0,
        )
    )
    queen.worker_runtime.direct_chat = lambda query, system=None, messages=None, model_override=None: ("ok", "stub")  # type: ignore[assignment]
    out = queen.run(intent="research_topic", payload={"query": "hello"})
    trace_id = out["trace_id"]
    assert queen.honeycomb.durable_state is not None
    run_row = queen.honeycomb.durable_state.get_run(trace_id)
    assert run_row is not None
    assert run_row["state"] == "succeeded"
    assert (tmp_path / ".honeycomb" / "control_plane.db").exists()


def test_durable_state_run_inspection_contains_timeline_and_tasks(tmp_path: Path) -> None:
    repo = DurableStateRepository(tmp_path / "control_plane.db")
    repo.record_run_state(
        trace_id="trace-inspect",
        request_id="req-inspect",
        intent="research_topic",
        state="requested",
    )
    repo.record_run_state(
        trace_id="trace-inspect",
        request_id="req-inspect",
        intent="research_topic",
        state="running",
    )
    task = TaskEnvelope(
        queen_trace_id="trace-inspect",
        queen_request_id="req-inspect",
        task_type="research_topic",
        worker_kind=WorkerKind.web_search,
        payload={"query": "inspection"},
        idempotency_key="idem-inspect",
    )
    repo.record_task(task)
    repo.record_policy_decision(
        PolicyDecision(task_id=task.task_id, status="approve", reason="safe"),
        trace_id="trace-inspect",
    )
    inspection = repo.get_run_inspection("trace-inspect")
    assert inspection is not None
    assert inspection["run"]["trace_id"] == "trace-inspect"
    assert len(inspection["run_state_timeline"]) >= 2
    assert len(inspection["tasks"]) == 1
    assert inspection["tasks"][0]["task_id"] == task.task_id
    assert len(inspection["tasks"][0]["state_timeline"]) >= 1
    assert len(inspection["policy_decisions"]) == 1
