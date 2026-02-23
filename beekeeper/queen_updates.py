"""Queen updates: things the Queen learned, built, or decided. Reported to Beekeeper."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .honeycomb import HoneycombConfig, HoneycombStore, utcnow_iso


class QueenUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    update_id: str = Field(default_factory=lambda: str(uuid4()))
    honeycomb_id: str = ""
    trace_id: str = ""
    kind: Literal["learned", "built", "decision", "report"] = "report"
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def write_queen_update(
    honeycomb: HoneycombStore,
    *,
    trace_id: str,
    kind: Literal["learned", "built", "decision", "report"] = "report",
    summary: str,
    payload: dict[str, Any] | None = None,
    honeycomb_id: str = "",
) -> QueenUpdate:
    """Append a Queen update to Honeycomb. Used after autonomous runs."""
    update = QueenUpdate(
        trace_id=trace_id,
        kind=kind,
        summary=summary,
        payload=payload or {},
        honeycomb_id=honeycomb_id,
    )
    updates_dir = honeycomb.root_dir / "queen_updates"
    updates_dir.mkdir(parents=True, exist_ok=True)
    path = updates_dir / "queen_updates.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(update.model_dump_json() + "\n")
    honeycomb.write_event("queen_updates", {"kind": "queen_update", "update_id": update.update_id})
    return update


def list_queen_updates(honeycomb: HoneycombStore, limit: int = 50) -> list[QueenUpdate]:
    """List recent Queen updates from Honeycomb."""
    path = honeycomb.root_dir / "queen_updates" / "queen_updates.jsonl"
    if not path.exists():
        return []
    updates: list[QueenUpdate] = []
    lines: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            updates.append(QueenUpdate.model_validate_json(line))
        except Exception:
            continue
        if len(updates) >= limit:
            break
    return updates
