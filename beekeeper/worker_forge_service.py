from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class WorkerForgeService:
    normalize_worker_kind: Callable[[str], str]
    list_workers: Callable[[], list[dict[str, Any]]]
    auto_spawn_worker: Callable[[str, dict[str, Any]], None]
    write_event: Callable[[str, dict[str, Any]], None]
    start_background: Callable[[str, Callable[[], None]], None]

    def maybe_start_auto_spawn(self, *, intent: str, payload: dict[str, Any], trace_id: str | None) -> bool:
        worker_kind_str = self.normalize_worker_kind(intent)
        existing = next((w for w in self.list_workers() if w.get("worker_kind") == worker_kind_str), None)
        if existing:
            return False

        def _run() -> None:
            self.auto_spawn_worker(intent, dict(payload))

        self.start_background(f"auto_spawn_{worker_kind_str}", _run)
        if trace_id:
            self.write_event(
                trace_id,
                {
                    "kind": "auto_spawn_started",
                    "worker_kind": worker_kind_str,
                    "intent": intent,
                    "content_score": 0,
                },
            )
        return True
