from pathlib import Path

from beehive.queen import QueenAgent, QueenConfig
from beehive.vector_store import build_vector_store


def test_queen_run_creates_results(tmp_path: Path) -> None:
    queen = QueenAgent(QueenConfig(honeycomb_root=tmp_path / "honeycomb", max_reruns=1))
    out = queen.run(intent="research_topic", payload={"query": "agent frameworks"})
    assert out["trace_id"].startswith("trace_")
    assert len(out["results"]) >= 1
    assert out["queen_soul_profile_id"] == "soul.queen.crown"
    assert out["ollama_base_url"].startswith("http://")


def test_guardrail_blocks_pii(tmp_path: Path) -> None:
    queen = QueenAgent(QueenConfig(honeycomb_root=tmp_path / "honeycomb", max_reruns=0))
    out = queen.run(intent="research_topic", payload={"email": "alice@example.com", "use_web_search": True})
    statuses = [result["status"] for result in out["results"]]
    assert "blocked" in statuses


def test_inline_scheduler_backend(tmp_path: Path) -> None:
    queen = QueenAgent(
        QueenConfig(
            honeycomb_root=tmp_path / "honeycomb",
            scheduler_backend="inline",
            max_reruns=0,
        )
    )
    out = queen.run(intent="research_topic", payload={"query": "queue scheduler"})
    assert out["results"]


def test_qdrant_adapter_fallback_search() -> None:
    store = build_vector_store("qdrant", url="http://localhost:6333", collection="test_beehive_collection")
    store.upsert("item-1", "queen worker architecture")
    hits = store.search("queen architecture", limit=3)
    assert "item-1" in hits
