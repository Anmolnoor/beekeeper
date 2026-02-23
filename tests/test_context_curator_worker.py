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
from beekeeper.worker import ContextCuratorWorker, WorkerContext


def _mk_context() -> WorkerContext:
    return WorkerContext(
        identity=AgentIdentity(agent_type="worker.context", skill_profile_id="skill.context.curator", soul_profile_id="soul.balanced"),
        skill=SkillProfile(
            skill_profile_id="skill.context.curator",
            name="Context Curator",
            description="test",
            capabilities=["memory_curation"],
        ),
        rule=RuleProfile(rule_profile_id="rule.default", name="Default"),
        soul=SoulProfile(soul_profile_id="soul.balanced", name="Balanced"),
        abilities=AbilitiesProfile(abilities_profile_id="abilities.default", name="default", capabilities=["memory_curation"]),
        accountability=AccountabilityPolicy(accountability_id="acc.default", name="default"),
        guardrails=GuardrailProfile(guardrail_profile_id="guardrails.default", name="default"),
    )


def test_context_curator_persists_balanced_memories(tmp_path: Path, monkeypatch) -> None:
    store_root = tmp_path / "store"
    honeycomb_root = tmp_path / "honeycomb"
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(store_root))
    monkeypatch.setenv("BEEKEEPER_VECTOR_BACKEND", "memory")

    from beekeeper import user_memory

    monkeypatch.setattr(
        user_memory,
        "extract_memories",
        lambda user_msg, assistant_reply, honeycomb_root=None: [
            "I prefer TypeScript for backend services.",
            "Project uses Docker and Qdrant by default.",
        ],
    )
    worker = ContextCuratorWorker()
    task = TaskEnvelope(
        queen_trace_id="trace_test",
        queen_request_id="req_test",
        task_type="context_curation",
        worker_kind=WorkerKind.context_curator,
        payload={
            "user_id": "user_123",
            "chat_id": "chat_123",
            "user_msg": "remember my setup",
            "assistant_reply": "noted",
            "honeycomb_root": str(honeycomb_root),
        },
        idempotency_key="idem_1",
        status=Status.queued,
    )
    out = worker.execute(task, _mk_context())
    assert out["saved_user_memories"] >= 1
    assert (honeycomb_root / "memory" / "MEMORY.md").exists()
    daily_files = list((honeycomb_root / "memory").glob("*.md"))
    assert daily_files


def test_context_curator_filters_sensitive_memories(tmp_path: Path, monkeypatch) -> None:
    store_root = tmp_path / "store"
    honeycomb_root = tmp_path / "honeycomb"
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(store_root))
    monkeypatch.setenv("BEEKEEPER_VECTOR_BACKEND", "memory")

    from beekeeper import user_memory

    monkeypatch.setattr(
        user_memory,
        "extract_memories",
        lambda user_msg, assistant_reply, honeycomb_root=None: [
            "My API key is sk-1234567890ABCDE",
            "Contact me at person@example.com",
            "I prefer concise responses.",
        ],
    )
    worker = ContextCuratorWorker()
    task = TaskEnvelope(
        queen_trace_id="trace_sensitive",
        queen_request_id="req_sensitive",
        task_type="context_curation",
        worker_kind=WorkerKind.context_curator,
        payload={
            "user_id": "user_321",
            "chat_id": "chat_321",
            "user_msg": "remember this",
            "assistant_reply": "ok",
            "honeycomb_root": str(honeycomb_root),
        },
        idempotency_key="idem_sensitive",
        status=Status.queued,
    )
    out = worker.execute(task, _mk_context())
    assert "skipped_sensitive=" in out["notes"]
    mem_file = store_root / "user_memories" / "user_321.jsonl"
    if mem_file.exists():
        rows = [json.loads(line) for line in mem_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            assert "sk-" not in row.get("content", "")
            assert "@example.com" not in row.get("content", "")
