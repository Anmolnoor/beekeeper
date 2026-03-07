from pathlib import Path

import pytest

from beekeeper.config.settings import RuntimeMode
from beekeeper.queen import QueenAgent, QueenConfig
from beekeeper.vector_store import build_vector_store


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


def test_auto_scheduler_prefers_celery_for_queueable_payload(tmp_path: Path, monkeypatch) -> None:
    queen = QueenAgent(
        QueenConfig(
            honeycomb_root=tmp_path / "honeycomb",
            scheduler_backend="auto",
            max_reruns=0,
        )
    )
    monkeypatch.setattr(queen, "_can_connect_celery", lambda: True)
    monkeypatch.setattr(queen, "_can_connect_temporal", lambda: True)
    selected, decision = queen._resolve_scheduler_backend({"use_web_search": True})
    assert selected == "celery"
    assert decision["reason"] == "queue_ready_default"


def test_auto_scheduler_prefers_temporal_for_durable_payload(tmp_path: Path, monkeypatch) -> None:
    queen = QueenAgent(
        QueenConfig(
            honeycomb_root=tmp_path / "honeycomb",
            scheduler_backend="auto",
            max_reruns=0,
        )
    )
    monkeypatch.setattr(queen, "_can_connect_celery", lambda: True)
    monkeypatch.setattr(queen, "_can_connect_temporal", lambda: True)
    selected, decision = queen._resolve_scheduler_backend({"require_durable": True})
    assert selected == "temporal"
    assert decision["reason"] == "durability_hint_and_temporal_ready"


def test_auto_scheduler_falls_back_inline_when_backends_unavailable(tmp_path: Path, monkeypatch) -> None:
    queen = QueenAgent(
        QueenConfig(
            honeycomb_root=tmp_path / "honeycomb",
            scheduler_backend="auto",
            max_reruns=0,
        )
    )
    monkeypatch.setattr(queen, "_can_connect_celery", lambda: False)
    monkeypatch.setattr(queen, "_can_connect_temporal", lambda: False)
    selected, decision = queen._resolve_scheduler_backend({"query": "hello"})
    assert selected == "inline"
    assert decision["reason"] == "queue_unavailable_fallback_inline"


def test_inline_scheduler_disallowed_in_non_dev_prefers_temporal(tmp_path: Path, monkeypatch) -> None:
    queen = QueenAgent(
        QueenConfig(
            honeycomb_root=tmp_path / "honeycomb",
            scheduler_backend="inline",
            max_reruns=0,
        )
    )
    monkeypatch.setattr("beekeeper.queen.resolve_runtime_mode", lambda: RuntimeMode.PROD)
    monkeypatch.setattr(queen, "_can_connect_temporal", lambda: True)
    monkeypatch.setattr(queen, "_can_connect_celery", lambda: False)
    selected, decision = queen._resolve_scheduler_backend({"query": "hello"})
    assert selected == "temporal"
    assert decision["reason"] == "inline_disallowed_non_dev_temporal_selected"


def test_inline_scheduler_disallowed_in_non_dev_without_backends_raises(tmp_path: Path, monkeypatch) -> None:
    queen = QueenAgent(
        QueenConfig(
            honeycomb_root=tmp_path / "honeycomb",
            scheduler_backend="inline",
            max_reruns=0,
        )
    )
    monkeypatch.setattr("beekeeper.queen.resolve_runtime_mode", lambda: RuntimeMode.PROD)
    monkeypatch.setattr(queen, "_can_connect_temporal", lambda: False)
    monkeypatch.setattr(queen, "_can_connect_celery", lambda: False)
    with pytest.raises(RuntimeError, match="inline_scheduler_not_allowed_in_non_dev_without_queue_backend"):
        queen._resolve_scheduler_backend({"query": "hello"})


def test_qdrant_adapter_fallback_search() -> None:
    store = build_vector_store("qdrant", url="http://localhost:6333", collection="test_beekeeper_collection")
    store.upsert("item-1", "queen worker architecture")
    hits = store.search("queen architecture", limit=3)
    assert "item-1" in hits
