from __future__ import annotations

from pathlib import Path

from beekeeper.contracts import PolicyDecision, RuleProfile, TaskEnvelope, WorkerKind
from beekeeper.data_plane.repositories import DurableStateRepository
from beekeeper.governance.capability_manifests import CapabilityManifest
from beekeeper.governance.policy_adapter import LocalPolicyAdapter
from beekeeper.replay_store import ReplayStore


def _task(**overrides) -> TaskEnvelope:
    payload = {
        "query": "hello",
        "action": "",
        "domains": ["docs.python.org"],
    }
    payload.update(overrides.pop("payload", {}))
    return TaskEnvelope(
        queen_trace_id="trace-1",
        queen_request_id="req-1",
        task_type="research_topic",
        worker_kind=WorkerKind.web_search,
        payload=payload,
        idempotency_key="idem-1",
        **overrides,
    )


def test_capability_manifest_blocks_wrong_worker_kind() -> None:
    manifest = CapabilityManifest(
        manifest_id="m-1",
        subject_id="blueprint.worker.web",
        allowed_worker_kinds={WorkerKind.heavy_compute},
        max_budget_usd=5.0,
    )
    ok, reason_codes, _ = manifest.check_task(_task())
    assert ok is False
    assert "worker_kind_not_allowed" in reason_codes


def test_policy_adapter_escalates_for_human_action() -> None:
    adapter = LocalPolicyAdapter()
    rule = RuleProfile(
        rule_profile_id="rule-1",
        name="r1",
        require_human_approval_for=["payment_action"],
    )
    decision = adapter.evaluate_task(
        task=_task(payload={"action": "payment_action"}),
        rule_profile=rule,
        capability_manifest=None,
        base_policy=PolicyDecision(task_id="t-1", status="approve", reason="ok"),
    )
    assert decision.decision == "escalate"
    assert "require_approval" in decision.obligations


def test_policy_adapter_denies_tool_outside_manifest() -> None:
    adapter = LocalPolicyAdapter()
    manifest = CapabilityManifest(
        manifest_id="m-1",
        subject_id="blueprint.queen.default",
        allowed_tools={"web_search"},
    )
    decision = adapter.evaluate_tool_call(
        tool_name="run_task",
        arguments={"intent": "research_topic"},
        rule_profile=RuleProfile(rule_profile_id="rule-1", name="r1"),
        capability_manifest=manifest,
    )
    assert decision.decision == "deny"
    assert "tool_not_in_capability_manifest" in decision.reason_codes


def test_replay_store_claim_only_once(tmp_path: Path) -> None:
    repo = DurableStateRepository(tmp_path / "control_plane.db")
    replay = ReplayStore(repo)
    first = replay.claim(channel="slack", replay_key="slack:evt_123")
    second = replay.claim(channel="slack", replay_key="slack:evt_123")
    assert first is True
    assert second is False
