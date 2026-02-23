from pathlib import Path
import json

from beekeeper.contracts import (
    AbilitiesProfile,
    AccountabilityPolicy,
    AgentIdentity,
    GuardrailProfile,
    RuleProfile,
    SkillProfile,
    SoulProfile,
    Status,
    TaskEnvelope,
    WorkerKind,
)
from beekeeper.honeycomb import HoneycombConfig, HoneycombStore
from beekeeper.store import BeekeeperStore
from beekeeper.queen_context import build_context_bundle
from beekeeper.user_memory import append_daily_memory_note, ensure_memory_files
from beekeeper.worker import WebSearchWorker, WorkerContext


def test_context_bundle_merges_sources(tmp_path: Path) -> None:
    honeycomb_root = tmp_path / "honeycomb"
    store = HoneycombStore(HoneycombConfig(root_dir=honeycomb_root, vector_backend="memory"))
    ensure_memory_files(honeycomb_root)
    store.write_queen_memory("User prefers concise answers.", source="test", tags=["profile_fact"])
    append_daily_memory_note(honeycomb_root, "Project uses qdrant vector backend.", source="test")
    payload = {
        "messages": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}],
        "user_memories": [{"content": "User likes TypeScript."}],
    }
    bundle = build_context_bundle(
        query="qdrant and concise answers",
        payload=payload,
        honeycomb=store,
        honeycomb_root=honeycomb_root,
    )
    assert bundle["messages"]
    assert bundle["user_memories"]
    assert bundle["semantic_context"]
    assert bundle["md_memory_context"]
    assert bundle["diagnostics"]["messages_count"] == 2


def test_web_worker_receives_message_context() -> None:
    worker = WebSearchWorker(llm_provider="ollama")
    captured: dict[str, object] = {}

    def fake_reply(
        query: str,
        system: str | None = None,
        messages: list[dict[str, str]] | None = None,
        model_tier: str | None = None,
        model_override: str | None = None,
    ) -> tuple[str | None, str]:
        captured["messages"] = messages
        return ("ok", "fallback")

    worker._assistant_reply = fake_reply  # type: ignore[method-assign]
    task = TaskEnvelope(
        queen_trace_id="trace_1",
        queen_request_id="req_1",
        task_type="research_topic",
        worker_kind=WorkerKind.web_search,
        payload={
            "query": "remember prior",
            "use_web_search": False,
            "messages": [{"role": "user", "content": "this is prior context"}],
        },
        idempotency_key="id_1",
        status=Status.queued,
    )
    context = WorkerContext(
        identity=AgentIdentity(agent_type="worker.web", skill_profile_id="skill.research.web", soul_profile_id="soul.balanced"),
        skill=SkillProfile(skill_profile_id="skill.research.web", name="web", description="web"),
        rule=RuleProfile(rule_profile_id="rule.default", name="default"),
        soul=SoulProfile(soul_profile_id="soul.balanced", name="balanced"),
        abilities=AbilitiesProfile(abilities_profile_id="abilities.default", name="default"),
        accountability=AccountabilityPolicy(accountability_id="acc.default", name="default"),
        guardrails=GuardrailProfile(guardrail_profile_id="guardrails.default", name="default"),
    )
    out = worker.execute(task, context)
    assert out["assistant_reply"] == "ok"
    assert isinstance(captured.get("messages"), list)
    assert captured["messages"]


def test_user_memory_ttl_cleanup_removes_expired_low_value(tmp_path: Path) -> None:
    store = BeekeeperStore(root=tmp_path / "store")
    user_id = "user_ttl"
    store.append_user_memory_with_metadata(
        user_id,
        "Temporary note that should expire quickly.",
        tier="ephemeral_note",
        score=0.4,
    )
    mem_file = tmp_path / "store" / "user_memories" / f"{user_id}.jsonl"
    lines = [json.loads(line) for line in mem_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    # Force-expire the first row, then ensure list call cleans it up.
    lines[0]["expires_at"] = "2000-01-01T00:00:00+00:00"
    mem_file.write_text("\n".join(json.dumps(r, ensure_ascii=True) for r in lines) + "\n", encoding="utf-8")
    remaining = store.list_user_memories(user_id, limit=10)
    assert remaining == []
    text_after = mem_file.read_text(encoding="utf-8").strip()
    assert text_after == ""
