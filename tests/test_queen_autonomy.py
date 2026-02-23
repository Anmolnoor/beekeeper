"""Tests for Queen autonomy features: actions, memory, worker spawning."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from beekeeper.contracts import QueenActionRequest, QueenActionResult
from beekeeper.honeycomb import HoneycombConfig, HoneycombStore
from beekeeper.queen import QueenAgent, QueenConfig
from beekeeper.queen_actions import (
    ActionContext,
    QueenActionLoop,
    QueenActionRegistry,
    _action_remember,
    _action_spawn_worker,
    build_default_action_registry,
)
from beekeeper.user_memory import extract_and_save_queen_memories
from beekeeper.worker_registry import WorkerRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path) -> HoneycombStore:
    return HoneycombStore(HoneycombConfig(root_dir=tmp_path / ".honeycomb"))


def _make_queen(tmp_path: Path) -> QueenAgent:
    return QueenAgent(
        QueenConfig(
            honeycomb_root=tmp_path / ".honeycomb",
            scheduler_backend="inline",
            vector_backend="memory",
            max_reruns=0,
        )
    )


def _stub_llm(queen: QueenAgent) -> None:
    """Patch LLM router to avoid network calls."""
    from beekeeper.worker import WebSearchWorker, WorkerKind

    worker = queen.worker_runtime._workers.get(WorkerKind.web_search)
    if isinstance(worker, WebSearchWorker):
        worker.llm_router.call = lambda **kwargs: ("stubbed_reply", "stub")  # type: ignore


def _stub_searxng(queen: QueenAgent) -> None:
    from beekeeper.worker import WebSearchWorker, WorkerKind

    worker = queen.worker_runtime._workers.get(WorkerKind.web_search)
    if isinstance(worker, WebSearchWorker):
        worker.searxng.search = lambda **kwargs: []  # type: ignore


# ---------------------------------------------------------------------------
# HoneycombStore queen memory tests
# ---------------------------------------------------------------------------

def test_honeycomb_write_read_queen_memories(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    mid1 = store.write_queen_memory("Queen learned about agent autonomy", source="test", tags=["ai"])
    mid2 = store.write_queen_memory("Beehive uses inline scheduler by default", source="test", tags=["config"])

    memories = store.read_queen_memories(limit=10)
    assert len(memories) == 2
    ids = [m["memory_id"] for m in memories]
    assert mid1 in ids
    assert mid2 in ids


def test_honeycomb_read_queen_memories_tag_filter(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.write_queen_memory("About AI", source="test", tags=["ai"])
    store.write_queen_memory("About config", source="test", tags=["config"])

    ai_mems = store.read_queen_memories(tag="ai")
    assert len(ai_mems) == 1
    assert "AI" in ai_mems[0]["content"]


def test_honeycomb_queen_memory_limit(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    for i in range(10):
        store.write_queen_memory(f"Memory {i}", source="test")

    memories = store.read_queen_memories(limit=5)
    assert len(memories) == 5


# ---------------------------------------------------------------------------
# Action registry tests
# ---------------------------------------------------------------------------

def test_action_registry_unknown_action(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    ctx = ActionContext(
        honeycomb_root=tmp_path / ".honeycomb",
        honeycomb=store,
        worker_runtime=MagicMock(),
        registry=MagicMock(),
        worker_registry=MagicMock(),
    )
    reg = QueenActionRegistry()
    result = reg.execute(QueenActionRequest(action_name="nonexistent"), ctx)
    assert result.success is False
    assert "unknown_action" in result.error


def test_action_remember_writes_memory(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    ctx = ActionContext(
        honeycomb_root=tmp_path / ".honeycomb",
        honeycomb=store,
        worker_runtime=MagicMock(),
        registry=MagicMock(),
        worker_registry=MagicMock(),
    )
    req = QueenActionRequest(
        action_name="remember",
        parameters={"content": "Beekeeper agent framework is modular.", "tags": ["beekeeper"]},
    )
    result = _action_remember(req, ctx)
    assert result.success is True
    assert "memory_id" in result.output

    memories = store.read_queen_memories()
    assert len(memories) == 1
    assert memories[0]["content"] == "Beekeeper agent framework is modular."
    assert "beekeeper" in memories[0]["tags"]


def test_action_remember_requires_content(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    ctx = ActionContext(
        honeycomb_root=tmp_path / ".honeycomb",
        honeycomb=store,
        worker_runtime=MagicMock(),
        registry=MagicMock(),
        worker_registry=MagicMock(),
    )
    req = QueenActionRequest(action_name="remember", parameters={})
    result = _action_remember(req, ctx)
    assert result.success is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# spawn_worker tests
# ---------------------------------------------------------------------------

def test_queen_spawn_worker_registers_blueprint(tmp_path: Path) -> None:
    queen = _make_queen(tmp_path)
    _stub_llm(queen)
    _stub_searxng(queen)

    result = queen.run(
        intent="spawn_worker",
        payload={
            "queen_actions": [
                {
                    "action": "spawn_worker",
                    "parameters": {
                        "name": "summarizer",
                        "description": "Summarises long documents",
                        "capabilities": ["summarize"],
                        "intent_patterns": ["summarize"],
                    },
                }
            ],
            "stop_after_actions": True,
        },
    )
    al = result.get("action_loop", {})
    assert al.get("success") is True

    action_res = al.get("action_results", [{}])[0]
    assert action_res.get("success") is True
    output = action_res.get("output", {})
    assert output.get("worker_kind") == "custom_summarizer"
    assert output.get("blueprint_id") == "blueprint.worker.custom_summarizer"

    # Verify skill was registered
    skill = queen.registry.get_skill("skill.custom.custom_summarizer")
    assert skill.name == "summarizer"


def test_worker_registry_register_custom_worker(tmp_path: Path) -> None:
    registry = WorkerRegistry(tmp_path / ".honeycomb")
    entry = registry.register_custom_worker(
        worker_kind="custom_tester",
        name="Tester",
        description="Test worker",
        capabilities=["test"],
        intent_patterns=["test_task"],
        persist=False,  # no disk write needed in unit test
    )
    assert entry["worker_kind"] == "custom_tester"
    assert "test" in entry["capabilities"]


def test_worker_registry_register_custom_worker_persists(tmp_path: Path) -> None:
    registry = WorkerRegistry(tmp_path / ".honeycomb")
    registry.ensure_registry_file()
    registry.register_custom_worker(
        worker_kind="custom_persisted",
        name="Persisted",
        description="Persisted worker",
        capabilities=["persist"],
        intent_patterns=["persist"],
        persist=True,
    )
    # Reload from disk
    registry2 = WorkerRegistry(tmp_path / ".honeycomb")
    workers = registry2.list_workers()
    kinds = [w["worker_kind"] for w in workers]
    assert "custom_persisted" in kinds


def test_worker_registry_register_custom_worker_merges_existing(tmp_path: Path) -> None:
    registry = WorkerRegistry(tmp_path / ".honeycomb")
    registry.ensure_registry_file()
    registry.register_custom_worker(
        worker_kind="custom_merge",
        name="Merge Worker",
        description="first",
        capabilities=["alpha"],
        intent_patterns=["merge_a"],
        query_keywords=["alpha"],
        fallback_workers=["web_search"],
        priority=10,
        persist=True,
    )
    registry.register_custom_worker(
        worker_kind="custom_merge",
        name="Merge Worker",
        description="second",
        capabilities=["beta"],
        intent_patterns=["merge_b"],
        query_keywords=["beta"],
        fallback_workers=["heavy_compute"],
        priority=15,
        persist=True,
    )
    worker = next(w for w in registry.list_workers() if w.get("worker_kind") == "custom_merge")
    assert set(worker["capabilities"]) >= {"alpha", "beta"}
    assert set(worker["intent_patterns"]) >= {"merge_a", "merge_b"}
    assert set(worker["query_keywords"]) >= {"alpha", "beta"}
    assert set(worker["fallback_workers"]) >= {"web_search", "heavy_compute"}
    assert int(worker["priority"]) == 15


# ---------------------------------------------------------------------------
# Action loop integration tests
# ---------------------------------------------------------------------------

def test_queen_action_loop_integration(tmp_path: Path) -> None:
    """queen_actions in payload triggers action loop; memories auto-saved."""
    queen = _make_queen(tmp_path)
    _stub_llm(queen)
    _stub_searxng(queen)

    result = queen.run(
        intent="test_actions",
        payload={
            "queen_actions": [
                {"action": "remember", "parameters": {"content": "Loop integration test passed."}},
            ],
            "stop_after_actions": True,
        },
    )
    assert result["trace_id"].startswith("trace_")
    al = result.get("action_loop", {})
    assert al.get("success") is True
    assert len(al.get("action_results", [])) == 1

    # Memory should be persisted
    memories = queen.honeycomb.read_queen_memories()
    contents = [m["content"] for m in memories]
    assert any("Loop integration test passed" in c for c in contents)


def test_queen_action_loop_emits_trace_event(tmp_path: Path) -> None:
    queen = _make_queen(tmp_path)
    _stub_llm(queen)

    result = queen.run(
        intent="test",
        payload={
            "queen_actions": [
                {"action": "remember", "parameters": {"content": "Trace event test."}}
            ],
            "stop_after_actions": True,
        },
    )
    trace_id = result["trace_id"]
    events = queen.honeycomb.read_events(trace_id)
    kinds = [e.get("kind") for e in events]
    assert "queen_action_loop" in kinds


def test_queen_action_loop_continues_to_workers(tmp_path: Path) -> None:
    """When stop_after_actions=False, the action loop runs then falls through to workers."""
    queen = _make_queen(tmp_path)
    _stub_llm(queen)
    _stub_searxng(queen)

    result = queen.run(
        intent="research_topic",
        payload={
            "query": "beekeeper architecture",
            "queen_actions": [
                {"action": "remember", "parameters": {"content": "Pre-task memory."}}
            ],
            "stop_after_actions": False,   # continue to worker delegation
        },
    )
    # Should have normal results (not just action_loop)
    assert "results" in result


# ---------------------------------------------------------------------------
# extract_and_save_queen_memories tests
# ---------------------------------------------------------------------------

def test_extract_and_save_queen_memories_empty(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    saved = extract_and_save_queen_memories("", store)
    assert saved == []


def test_extract_and_save_queen_memories_no_llm(tmp_path: Path, monkeypatch) -> None:
    """When LLM is unreachable, function should return empty list gracefully."""
    store = _make_store(tmp_path)

    import beekeeper.user_memory as um
    monkeypatch.setattr(um, "_make_extractor_llm", lambda: (lambda prompt: None))

    saved = extract_and_save_queen_memories("Some observation text.", store)
    assert saved == []


# ---------------------------------------------------------------------------
# Default action registry
# ---------------------------------------------------------------------------

def test_default_action_registry_has_all_actions() -> None:
    reg = build_default_action_registry()
    actions = reg.list_actions()
    for expected in ("remember", "web_search", "spawn_worker", "run_task", "summarize"):
        assert expected in actions, f"Missing action: {expected}"
