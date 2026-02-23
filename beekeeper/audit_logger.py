"""Central audit logger for full-stack service invocations.

Logs when Redis, Queen, Qdrant, LLM, etc. are called, with caller source.
Stores entries in .honeycomb/audit/YYYYMMDD.jsonl.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _honeycomb_root() -> Path:
    return Path(os.getenv("BEEKEEPER_HONEYCOMB_ROOT", ".honeycomb")).resolve()


def _audit_enabled() -> bool:
    return os.getenv("BEEKEEPER_AUDIT_ENABLED", "true").lower() in ("true", "1", "yes")


_audit_lock = threading.Lock()


def log_service_call(
    service: str,
    action: str = "called",
    source: str | None = None,
    trace_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append a service call entry to the audit log.

    service: redis | queen | qdrant | ollama | gemini | openai | searxng | temporal | beekeeper_api | queen_api
    action: called | submitted | completed | failed
    source: queen_api | beekeeper_api:chat | web_ui | channel:slack | cli | pulse | etc.
    """
    if not _audit_enabled():
        return
    row = {
        "at": _utcnow_iso(),
        "service": service,
        "action": action,
        "source": source or "unknown",
    }
    if trace_id:
        row["trace_id"] = trace_id
    if extra:
        row["extra"] = extra

    def _write() -> None:
        try:
            root = _honeycomb_root()
            audit_dir = root / "audit"
            audit_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now(timezone.utc).strftime("%Y%m%d")
            path = audit_dir / f"{today}.jsonl"
            line = json.dumps(row, ensure_ascii=True) + "\n"
            with _audit_lock:
                with path.open("a", encoding="utf-8") as f:
                    f.write(line)
        except Exception:
            pass  # Never fail the request path

    threading.Thread(target=_write, daemon=True).start()
