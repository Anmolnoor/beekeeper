"""Programmatic Python SDK for Beehive.

Use BeehiveClient to run Queen requests, chat, doctor checks, and more from Python.

Example:
    from beehive.sdk import BeehiveClient

    client = BeehiveClient(honeycomb_root=".honeycomb")
    result = client.run(intent="research_topic", payload={"query": "What is Python?"})
    print(result)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from .honeycomb import HoneycombConfig, HoneycombStore
from .queen import QueenAgent, QueenConfig
from .runner import (
    _collect_doctor_checks,
    _doctor_checks_to_json,
    _get_beekeeper_store,
)


class BeehiveClient:
    """Programmatic API for Beehive Queen and runtime operations."""

    def __init__(
        self,
        honeycomb_root: str | Path = ".honeycomb",
        scheduler: str = "inline",
        vector_backend: str = "memory",
        max_reruns: int = 1,
        **kwargs: Any,
    ) -> None:
        self.honeycomb_root = Path(honeycomb_root)
        self.scheduler = scheduler
        self.vector_backend = vector_backend
        self.max_reruns = max_reruns
        self._queen: QueenAgent | None = None
        self._extra_config = kwargs

    def _get_queen(self) -> QueenAgent:
        if self._queen is None:
            cfg = QueenConfig(
                honeycomb_root=self.honeycomb_root,
                max_reruns=self.max_reruns,
                scheduler_backend=self.scheduler,
                vector_backend=self.vector_backend,
                vector_collection=os.getenv("BEEHIVE_VECTOR_COLLECTION", "honeycomb_memory"),
                vector_url=os.getenv("BEEHIVE_VECTOR_URL", "http://localhost:6333"),
                llm_provider=os.getenv("BEEHIVE_LLM_PROVIDER", "ollama"),
                llm_providers=os.getenv("BEEHIVE_LLM_PROVIDERS", ""),
                ollama_base_url=os.getenv("BEEHIVE_OLLAMA_BASE_URL", "http://100.99.106.59:11434"),
                ollama_model=os.getenv("BEEHIVE_OLLAMA_MODEL", "catsarethebest/qwen2.5-N2:1.5b"),
                ollama_timeout_seconds=int(os.getenv("BEEHIVE_OLLAMA_TIMEOUT_SECONDS", "120")),
                gemini_api_key=os.getenv("BEEHIVE_GEMINI_API_KEY", ""),
                gemini_model=os.getenv("BEEHIVE_GEMINI_MODEL", "gemini-1.5-flash"),
                gemini_timeout_seconds=int(os.getenv("BEEHIVE_GEMINI_TIMEOUT_SECONDS", "120")),
                searxng_base_url=os.getenv("BEEHIVE_SEARXNG_BASE_URL", "http://localhost:8080"),
                **self._extra_config,
            )
            self._queen = QueenAgent(cfg)
        return self._queen

    def run(
        self,
        intent: str = "research_topic",
        payload: dict[str, Any] | None = None,
        query: str | None = None,
        session_id: str | None = None,
        parent_trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a single Queen request. Returns full run output."""
        payload = payload or {}
        if query:
            payload = dict(payload, query=query)
        queen = self._get_queen()
        return queen.run(
            intent=intent,
            payload=payload,
            session_id=session_id,
            parent_trace_id=parent_trace_id,
        )

    def chat(
        self,
        message: str,
        intent: str = "research_topic",
    ) -> dict[str, Any]:
        """Send a chat message and get the Queen response. Convenience wrapper for run()."""
        return self.run(intent=intent, payload={"query": message})

    def send_message(
        self,
        message: str,
        session_id: str | None = None,
        intent: str = "research_topic",
    ) -> dict[str, Any]:
        """Send a chat message and get the Queen response. Supports session for trace branching."""
        return self.run(
            intent=intent,
            payload={"query": message},
            session_id=session_id,
        )

    def _get_store(self) -> HoneycombStore:
        return HoneycombStore(
            HoneycombConfig(
                root_dir=self.honeycomb_root,
                vector_backend=self.vector_backend,
                vector_url=os.getenv("BEEHIVE_VECTOR_URL", "http://localhost:6333"),
            )
        )

    def fork_trace(self, trace_id: str, session_id: str | None = None) -> str:
        """Fork a trace: create a new trace linked as child of trace_id. Returns new trace_id."""
        store = self._get_store()
        if not session_id:
            session_id = store.create_session()
        new_trace_id = f"trace_{uuid4().hex}"
        store.link_trace_to_session(session_id, new_trace_id, parent_trace_id=trace_id)
        return new_trace_id

    def doctor(self, auto_start: bool = False, as_dict: bool = False) -> dict[str, Any] | int:
        """
        Run health checks. Returns exit code (0=ok) or dict if as_dict=True.
        """
        checks = _collect_doctor_checks()
        failed = [c for c in checks if not c.ok]
        if auto_start and failed:
            from .runner import _ensure_required_services_running
            if _ensure_required_services_running(include_workers=False) == 0:
                checks = _collect_doctor_checks()
                failed = [c for c in checks if not c.ok]
        if as_dict:
            return _doctor_checks_to_json(checks)
        return 0 if not failed else 1

    def list_traces(self, limit: int = 100) -> list[str]:
        """List trace IDs from honeycomb, most recent first."""
        store = HoneycombStore(
            HoneycombConfig(
                root_dir=self.honeycomb_root,
                vector_backend=self.vector_backend,
                vector_url=os.getenv("BEEHIVE_VECTOR_URL", "http://localhost:6333"),
            )
        )
        return store.list_traces(limit=limit)

    def get_trace_events(self, trace_id: str) -> list[dict[str, Any]]:
        """Get all events for a trace."""
        store = HoneycombStore(
            HoneycombConfig(
                root_dir=self.honeycomb_root,
                vector_backend=self.vector_backend,
                vector_url=os.getenv("BEEHIVE_VECTOR_URL", "http://localhost:6333"),
            )
        )
        return store.read_events(trace_id)

    def create_session(self) -> str:
        """Create a new session for trace branching. Returns session_id."""
        store = HoneycombStore(
            HoneycombConfig(
                root_dir=self.honeycomb_root,
                vector_backend=self.vector_backend,
                vector_url=os.getenv("BEEHIVE_VECTOR_URL", "http://localhost:6333"),
            )
        )
        return store.create_session()

    def list_sessions(self, limit: int = 50) -> list[str]:
        """List session IDs."""
        store = HoneycombStore(
            HoneycombConfig(
                root_dir=self.honeycomb_root,
                vector_backend=self.vector_backend,
                vector_url=os.getenv("BEEHIVE_VECTOR_URL", "http://localhost:6333"),
            )
        )
        return store.list_sessions(limit=limit)

    def get_trace_tree(self, trace_id: str) -> dict[str, Any]:
        """Get trace tree (trace_id, parent_trace_id, session_id, children)."""
        return self._get_store().get_trace_tree(trace_id)

    def get_session_traces(self, session_id: str) -> list[dict[str, Any]]:
        """Get trace entries for a session."""
        return self._get_store().get_session_traces(session_id)

    def init_tenant(
        self,
        org_name: str = "Default Organization",
        hive_name: str = "Main Hive",
    ) -> dict[str, Any]:
        """Initialize Beekeeper org/hive/honeycomb (CLI init-tenant equivalent)."""
        store = _get_beekeeper_store()
        org = store.create_org(org_name)
        hive = store.create_hive(org.org_id, hive_name)
        comb = store.create_honeycomb(hive.hive_id, f"{hive_name}-comb", str(self.honeycomb_root))
        store.create_queen(hive.hive_id, "Main Queen", "blueprint.queen.default")
        return {
            "org": org.model_dump(mode="json"),
            "hive": hive.model_dump(mode="json"),
            "honeycomb": comb.model_dump(mode="json"),
        }


def create_client(
    honeycomb_root: str | Path = ".honeycomb",
    **kwargs: Any,
) -> BeehiveClient:
    """Factory for BeehiveClient with sensible defaults."""
    return BeehiveClient(honeycomb_root=honeycomb_root, **kwargs)
