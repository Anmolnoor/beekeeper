"""demo_autonomy.py — Demonstrates the full Queen autonomy loop.

Run with:
    python -m beekeeper.demo_autonomy

No live LLM required — all LLM calls are stubbed so this runs in CI / offline.

Shows:
  1. Queen takes a web_search action → gets synthesised results
  2. Memories are auto-saved from the action output
  3. Queen takes a remember action → manual memory write
  4. Queen spawns a new custom worker (custom_summarizer)
  5. Queen runs a task via run_task action
  6. All persisted memories are printed at the end
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Stub LLM so we don't need Ollama/Gemini running
# ---------------------------------------------------------------------------
_STUB_REPLY = "The agent processed your request successfully. Key finding: autonomy is working."


def _patch_llm(worker_runtime: Any) -> None:
    """Monkeypatch the WebSearchWorker's LLM reply to avoid live network calls."""
    from beekeeper.worker import WebSearchWorker, WorkerKind

    worker = worker_runtime._workers.get(WorkerKind.web_search)
    if isinstance(worker, WebSearchWorker):
        # Return "ollama" as source — must be a valid Literal["ollama","gemini","fallback"]
        worker.llm_router.call = lambda **kwargs: (_STUB_REPLY, "ollama")  # type: ignore[method-assign]


def _patch_searxng(worker_runtime: Any) -> None:
    """Monkeypatch SearXNG so no HTTP call is made."""
    from beekeeper.worker import WebSearchWorker, WorkerKind

    worker = worker_runtime._workers.get(WorkerKind.web_search)
    if isinstance(worker, WebSearchWorker):
        worker.searxng.search = lambda **kwargs: []  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------

def run_demo(honeycomb_root: Path) -> None:
    from beekeeper.queen import QueenAgent, QueenConfig

    print("\n" + "═" * 60)
    print("  🐝  Queen Autonomy Demo")
    print("═" * 60)

    queen = QueenAgent(
        QueenConfig(
            honeycomb_root=honeycomb_root,
            scheduler_backend="inline",
            vector_backend="memory",
        )
    )

    # Patch LLM so demo runs offline
    _patch_llm(queen.worker_runtime)
    _patch_searxng(queen.worker_runtime)

    # ------------------------------------------------------------------
    # Step 1 & 2: web_search action → auto-memory from findings
    # ------------------------------------------------------------------
    print("\n[1] Queen takes web_search action…")
    result = queen.run(
        intent="research_topic",
        payload={
            "query": "What is agent autonomy?",
            "queen_actions": [
                {
                    "action": "web_search",
                    "parameters": {
                        "query": "agent autonomy definition ai",
                        "use_web_search": False,   # use LLM only (stubbed)
                    },
                }
            ],
            "stop_after_actions": True,
        },
        status_callback=lambda msg: print(f"   ↳ {msg}"),
    )
    action_loop = result.get("action_loop", {})
    print(f"   ✓ Actions executed. Memories auto-saved: {action_loop.get('memories_saved', [])}")

    # ------------------------------------------------------------------
    # Step 3: manual remember action
    # ------------------------------------------------------------------
    print("\n[2] Queen saves a manual memory via remember action…")
    result2 = queen.run(
        intent="remember",
        payload={
            "queen_actions": [
                {
                    "action": "remember",
                    "parameters": {
                        "content": "The demo project uses Beehive with inline scheduler and memory vector backend.",
                        "tags": ["project", "config"],
                        "source": "demo_autonomy",
                    },
                }
            ],
            "stop_after_actions": True,
        },
        status_callback=lambda msg: print(f"   ↳ {msg}"),
    )
    al2 = result2.get("action_loop", {})
    print(f"   ✓ Memory saved. memories_saved IDs: {al2.get('memories_saved', [])}")

    # ------------------------------------------------------------------
    # Step 4: spawn a new custom worker
    # ------------------------------------------------------------------
    print("\n[3] Queen spawns a new custom worker (custom_summarizer)…")
    result3 = queen.run(
        intent="spawn_worker",
        payload={
            "queen_actions": [
                {
                    "action": "spawn_worker",
                    "parameters": {
                        "name": "summarizer",
                        "description": "Summarises long inputs into concise paragraphs",
                        "capabilities": ["summarize", "condense"],
                        "intent_patterns": ["summarize", "condense", "shorten"],
                        "payload_triggers": ["long_text"],
                    },
                }
            ],
            "stop_after_actions": True,
        },
        status_callback=lambda msg: print(f"   ↳ {msg}"),
    )
    al3 = result3.get("action_loop", {})
    spawned_result = (al3.get("action_results") or [{}])[0]
    print(f"   ✓ Spawned: {spawned_result.get('output', {}).get('worker_kind')}")

    # ------------------------------------------------------------------
    # Step 5: run_task via the spawned worker (falls back to web worker)
    # ------------------------------------------------------------------
    print("\n[4] Queen dispatches a task via run_task action…")
    result4 = queen.run(
        intent="research_topic",
        payload={
            "queen_actions": [
                {
                    "action": "run_task",
                    "parameters": {
                        "intent": "research_topic",
                        "worker_kind": "web_search",
                        "payload": {"query": "What is the Beehive agent platform?"},
                    },
                }
            ],
            "stop_after_actions": True,
        },
        status_callback=lambda msg: print(f"   ↳ {msg}"),
    )
    al4 = result4.get("action_loop", {})
    task_result = (al4.get("action_results") or [{}])[0]
    print(f"   ✓ Task result success: {task_result.get('success')}")

    # ------------------------------------------------------------------
    # Step 6: print all persisted memories
    # ------------------------------------------------------------------
    print("\n[5] Persisted Queen memories:")
    memories = queen.honeycomb.read_queen_memories(limit=20)
    if not memories:
        print("   (none yet)")
    for i, mem in enumerate(memories, 1):
        print(f"   {i}. [{', '.join(mem.get('tags', []))}] {mem['content'][:100]}")

    print("\n" + "═" * 60)
    print("  ✅  Demo complete!")
    print("═" * 60 + "\n")


def main() -> None:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="beekeeper_demo_") as tmpdir:
        run_demo(Path(tmpdir) / "honeycomb")


if __name__ == "__main__":
    main()
