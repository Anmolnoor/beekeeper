"""Worker registry: configurable catalog of workers for Queen to select from.

Queen consults this registry to decide which worker handles a task.
Edit .honeycomb/workers/registry.json to:
- Change which worker handles which intent (intent_patterns, payload_triggers, query_keywords)
- Set fallback_workers for when the primary fails
- Change default_worker when nothing matches

To add new worker kinds, implement them in WorkerRuntime and extend WorkerKind.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import WorkerKind

DEFAULT_REGISTRY = {
    "version": "1",
    "default_worker": "web_search",
    "workers": [
        {
            "worker_kind": "web_search",
            "name": "Web Search",
            "description": "Searches the web, gathers evidence, and synthesizes answers using LLM.",
            "capabilities": ["search", "research", "lookup", "find", "web", "internet"],
            "intent_patterns": ["research_topic", "search", "lookup"],
            "payload_triggers": ["use_web_search", "domains"],
            "query_keywords": ["search for", "look up", "find", "research", "what is"],
            "priority": 20,
            "fallback_workers": ["heavy_compute"],
        },
        {
            "worker_kind": "heavy_compute",
            "name": "Heavy Compute",
            "description": "Numeric aggregation, simulations, data analysis.",
            "capabilities": ["compute", "aggregate", "simulate", "analyze", "numbers"],
            "intent_patterns": ["compute", "analysis", "simulate", "aggregate"],
            "payload_triggers": ["numbers", "operation"],
            "query_keywords": ["sum", "average", "aggregate", "simulate", "calculate"],
            "priority": 30,
            "fallback_workers": [],
        },
        {
            "worker_kind": "audit",
            "name": "Audit",
            "description": "Reviews and validates outputs from other workers.",
            "capabilities": ["audit", "review", "validate"],
            "intent_patterns": ["audit", "audit_result", "review"],
            "payload_triggers": ["target_task_id"],
            "priority": 10,
            "fallback_workers": [],
        },
    ],
}


def _worker_kind_from_str(s: str) -> WorkerKind:
    try:
        return WorkerKind(s)
    except ValueError:
        return WorkerKind.custom


def _registry_roots(honeycomb_root: Path) -> list[Path]:
    """Return registry search roots: honeycomb first, then project-local .beehive."""
    roots = [Path(honeycomb_root)]
    beehive_dir = Path(honeycomb_root).resolve().parent / ".beehive"
    if beehive_dir.exists():
        roots.append(beehive_dir)
    return roots


class WorkerRegistry:
    """Loads and queries the worker catalog. Queen uses this to pick workers."""

    def __init__(self, honeycomb_root: Path) -> None:
        self.root = Path(honeycomb_root)
        self._registry: dict[str, Any] | None = None

    def _registry_path(self) -> Path:
        return self.root / "workers" / "registry.json"

    def _load(self) -> dict[str, Any]:
        if self._registry is not None:
            return self._registry
        merged: dict[str, Any] = dict(DEFAULT_REGISTRY)
        workers_by_kind: dict[str, dict[str, Any]] = {w.get("worker_kind"): w for w in merged.get("workers", [])}

        for root in _registry_roots(self.root):
            path = root / "workers" / "registry.json"
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            for w in data.get("workers", []):
                kind = w.get("worker_kind")
                if kind:
                    workers_by_kind[kind] = w
            if data.get("default_worker"):
                merged["default_worker"] = data["default_worker"]

        merged["workers"] = list(workers_by_kind.values())
        self._registry = merged
        return self._registry

    def reload(self) -> None:
        """Reload registry from disk (e.g. after user edits)."""
        self._registry = None
        self._load()

    def list_workers(self) -> list[dict[str, Any]]:
        """Return all worker entries for inspection/UI."""
        reg = self._load()
        return list(reg.get("workers", []))

    def get_default_worker(self) -> WorkerKind:
        """Worker to use when nothing matches."""
        reg = self._load()
        kind = reg.get("default_worker", "web_search")
        return _worker_kind_from_str(kind)

    def select_worker(
        self,
        intent: str,
        payload: dict[str, Any],
        query: str = "",
    ) -> tuple[WorkerKind, list[WorkerKind]]:
        """
        Pick the best worker for this task.
        Returns (selected_worker, fallback_workers).
        """
        reg = self._load()
        workers = reg.get("workers", [])
        query_lower = (query or "").lower()
        intent_lower = intent.lower()

        best_match: dict[str, Any] | None = None
        best_score = -1

        for w in workers:
            score = 0
            kind_str = w.get("worker_kind", "")
            try:
                _ = WorkerKind(kind_str)
            except ValueError:
                continue

            if intent_lower in [p.lower() for p in w.get("intent_patterns", [])]:
                score += 50
            for p in w.get("intent_patterns", []):
                if p.lower() in intent_lower:
                    score += 25
                    break

            for key in w.get("payload_triggers", []):
                if payload.get(key) is not None:
                    score += 40
                    break

            for kw in w.get("query_keywords", []):
                if kw.lower() in query_lower:
                    score += 15
                    break

            for cap in w.get("capabilities", []):
                if cap.lower() in query_lower or cap.lower() in intent_lower:
                    score += 10
                    break

            score += w.get("priority", 0)

            if score > best_score:
                best_score = score
                best_match = w

        if best_match and best_score > 0:
            kind = _worker_kind_from_str(best_match["worker_kind"])
            fallbacks = [
                _worker_kind_from_str(f)
                for f in best_match.get("fallback_workers", [])
            ]
            return kind, fallbacks

        default = self.get_default_worker()
        default_entry = next(
            (w for w in workers if w.get("worker_kind") == default.value),
            None,
        )
        fallbacks = list(default_entry.get("fallback_workers", [])) if default_entry else []
        return default, [_worker_kind_from_str(f) for f in fallbacks]

    def ensure_registry_file(self) -> Path:
        """Create the registry file if missing (so users can edit it)."""
        path = self._registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("w", encoding="utf-8") as f:
                json.dump(DEFAULT_REGISTRY, f, indent=2)
        return path

    def register_custom_worker(
        self,
        worker_kind: str,
        name: str,
        description: str,
        capabilities: list[str],
        intent_patterns: list[str],
        payload_triggers: list[str] | None = None,
        query_keywords: list[str] | None = None,
        priority: int = 15,
        persist: bool = True,
    ) -> dict[str, Any]:
        """
        Add a new custom worker entry to the registry at runtime.

        If ``persist=True``, writes/merges the entry into the on-disk
        registry.json so it survives restarts and is visible to other
        processes. Invalidates the in-memory cache so the next
        ``select_worker`` call picks up the new entry.

        Returns the created worker entry dict.
        """
        entry: dict[str, Any] = {
            "worker_kind": worker_kind,
            "name": name,
            "description": description,
            "capabilities": capabilities,
            "intent_patterns": intent_patterns,
            "payload_triggers": payload_triggers or [],
            "query_keywords": query_keywords or [],
            "priority": priority,
            "fallback_workers": ["web_search"],
        }

        if persist:
            path = self.ensure_registry_file()
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                data = dict(DEFAULT_REGISTRY)

            workers: list[dict[str, Any]] = list(data.get("workers", []))
            # Replace existing entry with same kind, or append
            updated = [w for w in workers if w.get("worker_kind") != worker_kind]
            updated.append(entry)
            data["workers"] = updated
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        # Invalidate in-memory cache so next call re-reads
        self._registry = None
        return entry

