"""Trace compaction: reduce trace size and improve performance.

Compacts .honeycomb/events/*.jsonl by:
- Keeping only the last task state per task_id (deduplicate task_state events)
- Keeping only the last result per task_id
- Collapsing worker_lifecycle (preflight/execute/validate/terminate) into a single summary
- Truncating large payloads in task/result events
- Preserving policy_decision, human_review, artifact refs, monitor_decision, session_link
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# Max chars for payload/result truncation
MAX_PAYLOAD_CHARS = 2000
MAX_RESULT_OUTPUT_CHARS = 3000


def _truncate_value(obj: Any, max_chars: int) -> Any:
    """Truncate string values in nested structures."""
    if isinstance(obj, str):
        if len(obj) <= max_chars:
            return obj
        return obj[:max_chars] + "...[truncated]"
    if isinstance(obj, dict):
        return {k: _truncate_value(v, max_chars) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_truncate_value(v, max_chars) for v in obj]
    return obj


def _compact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact a list of events. Returns new list."""
    last_task: dict[str, dict] = {}
    last_result: dict[str, dict] = {}
    lifecycle_by_task: dict[str, tuple[list[str], str]] = {}  # (stages, last_at)
    kept: list[dict[str, Any]] = []
    # Event kinds we always keep (no compaction)
    keep_kinds = {"policy_decision", "human_review", "artifact", "monitor_decision", "session_link", "retention"}

    for ev in events:
        kind = ev.get("kind", "")
        task_id = ev.get("task_id", "")
        at = ev.get("at", "") or ""

        if kind in keep_kinds:
            kept.append(ev)
            continue

        if kind == "task" and ev.get("stage") == "task_state":
            last_task[task_id] = ev
            continue

        if kind == "result":
            result_ev = dict(ev)
            if "result" in result_ev and isinstance(result_ev["result"], dict):
                out = result_ev["result"].get("output")
                if isinstance(out, (dict, list, str)):
                    result_ev["result"] = dict(result_ev["result"])
                    result_ev["result"]["output"] = _truncate_value(out, MAX_RESULT_OUTPUT_CHARS)
            last_result[task_id] = result_ev
            continue

        if kind == "worker_lifecycle":
            stage = ev.get("stage", "")
            if stage:
                prev = lifecycle_by_task.get(task_id, ([], ""))
                stages = list(prev[0])
                if stage not in stages:
                    stages.append(stage)
                lifecycle_by_task[task_id] = (stages, at)
            continue

        if kind == "worker_performance":
            kept.append(ev)
            continue

        kept.append(ev)

    # Emit last task states (truncate large payloads)
    for _task_id, ev in sorted(last_task.items()):
        task_payload = ev.get("task", {})
        if isinstance(task_payload, dict) and task_payload.get("payload"):
            payload = task_payload["payload"]
            if isinstance(payload, (dict, list, str)) and len(json.dumps(payload)) > MAX_PAYLOAD_CHARS:
                ev = dict(ev)
                ev["task"] = dict(task_payload)
                ev["task"]["payload"] = _truncate_value(payload, MAX_PAYLOAD_CHARS)
        kept.append(ev)

    # Emit last results
    kept.extend(sorted(last_result.values(), key=lambda e: e.get("at", "")))

    # Emit lifecycle summaries
    for task_id, (stages, at) in sorted(lifecycle_by_task.items()):
        if stages:
            kept.append({
                "kind": "worker_lifecycle",
                "stage": "summary",
                "task_id": task_id,
                "stages": stages,
                "at": at,
            })

    kept.sort(key=lambda e: e.get("at", "") or "")
    return kept


def compact_trace_file(events_path: Path, *, in_place: bool = True) -> tuple[int, int]:
    """
    Compact a single trace file.
    Returns (original_line_count, compacted_line_count).
    """
    if not events_path.exists():
        return 0, 0
    events = []
    with events_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    original = len(events)
    compacted = _compact_events(events)
    if in_place:
        with events_path.open("w", encoding="utf-8") as f:
            for ev in compacted:
                f.write(json.dumps(ev, ensure_ascii=True) + "\n")
    return original, len(compacted)


def compact_traces(
    honeycomb_root: Path,
    *,
    trace_id: str | None = None,
    all_traces: bool = False,
    min_age_hours: float = 0,
) -> dict[str, Any]:
    """
    Compact trace files in honeycomb events dir.
    - trace_id: compact only this trace
    - all_traces: compact all traces
    - min_age_hours: only compact traces older than this (default 0 = all)
    Returns summary dict.
    """
    import time
    events_dir = honeycomb_root / "events"
    if not events_dir.exists():
        return {"compacted": 0, "traces": [], "bytes_saved": 0}

    if trace_id:
        paths = [events_dir / f"{trace_id}.jsonl"]
        paths = [p for p in paths if p.exists()]
    elif all_traces:
        paths = list(events_dir.glob("*.jsonl"))
    else:
        return {"compacted": 0, "traces": [], "bytes_saved": 0, "error": "Specify --trace-id or --all"}

    if min_age_hours > 0:
        now = time.time()
        min_mtime = now - (min_age_hours * 3600)
        paths = [p for p in paths if p.stat().st_mtime < min_mtime]

    total_before = 0
    total_after = 0
    traces_done: list[str] = []

    for path in paths:
        before_size = path.stat().st_size
        orig, comp = compact_trace_file(path, in_place=True)
        after_size = path.stat().st_size
        total_before += before_size
        total_after += after_size
        traces_done.append(path.stem)

    return {
        "compacted": len(traces_done),
        "traces": traces_done,
        "bytes_saved": max(0, total_before - total_after),
    }
