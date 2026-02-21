from __future__ import annotations

from pathlib import Path

from beehive.honeycomb import HoneycombConfig, HoneycombStore
from beehive.ops import compute_ops_metrics
from beehive.queen import QueenAgent, QueenConfig
from beehive.web_adapters import WebAdapterError
from beehive.worker import WebSearchWorker, WorkerContext, make_worker_identity
from beehive.contracts import RuleProfile, SkillProfile, SoulProfile, TaskEnvelope, WorkerKind


def _worker_context() -> WorkerContext:
    return WorkerContext(
        identity=make_worker_identity(
            agent_type="worker.research_topic",
            skill_profile_id="skill.research.web",
            soul_profile_id="soul.balanced",
        ),
        skill=SkillProfile(
            skill_profile_id="skill.research.web",
            name="Web",
            description="Web search",
            capabilities=["web_search"],
            tool_allowlist=["web_search"],
            can_search_web=True,
        ),
        rule=RuleProfile(
            rule_profile_id="rule.default",
            name="Default",
            allowed_domains=["docs.python.org", "github.com"],
        ),
        soul=SoulProfile(soul_profile_id="soul.balanced", name="Balanced"),
    )


def test_web_search_worker_uses_searxng_results(monkeypatch) -> None:
    worker = WebSearchWorker(
        llm_provider="ollama",
        ollama_base_url="http://localhost:11434",
        ollama_model="test",
        searxng_base_url="http://localhost:8080",
    )

    def fake_search(query: str, allowed_domains: list[str], limit: int = 5):
        _ = (query, limit)
        return [
            {
                "title": "Python docs",
                "url": "https://docs.python.org/3/tutorial/",
                "domain": "docs.python.org",
                "snippet": "Official tutorial",
                "source": "searxng",
            }
        ]

    monkeypatch.setattr(worker.searxng, "search", fake_search)
    task = TaskEnvelope(
        queen_trace_id="trace_test",
        queen_request_id="req_test",
        task_type="research_topic",
        worker_kind=WorkerKind.web_search,
        payload={"query": "python tutorial", "use_web_search": True},
        idempotency_key="id_test",
    )
    output = worker.execute(task, _worker_context())
    assert output["response_source"] in {"ollama", "fallback", "gemini"}
    assert output["evidence"][0]["source"] == "searxng"
    assert "fetched_urls" in task.payload


def test_web_search_worker_fallback_when_searxng_unavailable(monkeypatch) -> None:
    worker = WebSearchWorker(
        llm_provider="ollama",
        ollama_base_url="http://localhost:11434",
        ollama_model="test",
        searxng_base_url="http://localhost:8080",
    )
    monkeypatch.setattr(
        worker.searxng,
        "search",
        lambda query, allowed_domains, limit=5: (_ for _ in ()).throw(
            WebAdapterError(code="unavailable", message="offline")
        ),
    )
    task = TaskEnvelope(
        queen_trace_id="trace_test",
        queen_request_id="req_test",
        task_type="research_topic",
        worker_kind=WorkerKind.web_search,
        payload={"query": "python tutorial", "use_web_search": True},
        idempotency_key="id_test",
    )
    output = worker.execute(task, _worker_context())
    assert output["evidence"]
    assert output["evidence"][0]["source"].startswith("fallback:")


def test_hitl_queue_and_resume(tmp_path: Path) -> None:
    queen = QueenAgent(
        QueenConfig(
            honeycomb_root=tmp_path / ".honeycomb",
            scheduler_backend="inline",
            max_reruns=1,
            auto_approve_human_reviews=False,
        )
    )
    blocked = queen.run(
        intent="research_topic",
        payload={"query": "payment migration", "action": "payment_action", "requires_human_approval": True, "use_web_search": True},
    )
    first = blocked["results"][0]["output"]
    review_id = first["human_review_id"]
    pending = queen.honeycomb.list_pending_reviews()
    assert any(item.review_id == review_id for item in pending)

    resumed = queen.resume_human_review(review_id, approver="qa", approved=True, note="looks safe")
    assert resumed["resumed"] is True
    assert resumed["run"]["results"][0]["status"] == "success"


def test_routing_feedback_tracks_intent_and_skill(tmp_path: Path) -> None:
    store = HoneycombStore(HoneycombConfig(root_dir=tmp_path / ".honeycomb"))
    record = store.record_routing_outcome(
        worker_kind=WorkerKind.web_search,
        intent="research_topic",
        skill_id="skill.research.web",
        quality_score=0.8,
        latency_ms=500,
        cost_usd=0.02,
        success=True,
    )
    assert record.recent_quality_ema > 0
    assert "research_topic" in record.by_intent
    assert "skill.research.web" in record.by_skill


def test_metrics_reports_pending_reviews(tmp_path: Path) -> None:
    root = tmp_path / ".honeycomb"
    store = HoneycombStore(HoneycombConfig(root_dir=root))
    task = TaskEnvelope(
        queen_trace_id="trace",
        queen_request_id="req",
        task_type="research_topic",
        worker_kind=WorkerKind.web_search,
        payload={"query": "x"},
        idempotency_key="id",
    )
    store.enqueue_review(task=task, reason="human_approval_required")
    metrics = compute_ops_metrics(root)
    assert metrics["pending_human_reviews"] == 1
    assert "alerts" in metrics
