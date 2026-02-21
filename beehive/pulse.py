"""Pulse: periodic tick loop and cron-driven jobs for Queen autonomy.

Inspired by OpenClaw's cron + heartbeat. Runs analyzers, invokes Queen,
executes commands on schedule.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .honeycomb import HoneycombConfig, HoneycombStore
from .queen import QueenAgent, QueenConfig
from .ops import compute_ops_metrics


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PulseConfig:
    honeycomb_root: Path
    interval_seconds: float = 2.0
    jobs_path: Path | None = None
    max_queen_runs_per_tick: int = 1
    command_allowlist: frozenset[str] | None = None  # None = allow any; else exact match


def _default_jobs_path(honeycomb_root: Path) -> Path:
    return honeycomb_root / "pulse" / "jobs.json"


def _load_jobs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    jobs = raw.get("jobs", [])
    return jobs if isinstance(jobs, list) else []


def _save_jobs(path: Path, jobs: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"jobs": jobs}, ensure_ascii=True, indent=2), encoding="utf-8")


def _job_is_due(job: dict[str, Any], now: datetime) -> bool:
    """Check if job is due to run at or before now."""
    sched = job.get("schedule") or {}
    kind = sched.get("kind", "cron")
    tz = timezone.utc
    if kind == "at":
        at_str = sched.get("at")
        if not at_str:
            return False
        try:
            target = datetime.fromisoformat(at_str.replace("Z", "+00:00"))
            return now >= target
        except (ValueError, TypeError):
            return False
    if kind == "every":
        every_ms = sched.get("everyMs", 60000)
        last_run = job.get("_last_run_ts")
        if last_run is None:
            return True
        return (now.timestamp() - last_run) * 1000 >= every_ms
    if kind == "cron":
        try:
            from croniter import croniter

            expr = sched.get("expr", "0 * * * *")
            last_run = job.get("_last_run_ts")
            base = datetime.fromtimestamp(last_run, tz=timezone.utc) if last_run else datetime(1970, 1, 1, tzinfo=timezone.utc)
            it = croniter(expr, base)
            next_run = it.get_next(datetime)
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=timezone.utc)
            return now >= next_run
        except Exception:
            return False
    return False


def _mark_job_run(job: dict[str, Any]) -> dict[str, Any]:
    j = dict(job)
    j["_last_run_ts"] = datetime.now(timezone.utc).timestamp()
    return j


def run_backlog_processor(
    queen: QueenAgent,
    honeycomb: HoneycombStore,
    limit: int = 5,
    on_update: Callable[[dict[str, Any]], None] | None = None,
) -> int:
    """Pull tasks from backlog, run via Queen, emit updates. Returns count run."""
    tasks = honeycomb.pull_backlog_tasks(limit=limit)
    count = 0
    for t in tasks:
        intent = t.get("intent", "research_topic")
        payload = dict(t.get("payload", {}))
        payload.setdefault("query", t.get("query", ""))
        source = t.get("source", "pulse_backlog")
        result = queen.run_autonomous(source, {"intent": intent, "payload": payload})
        if result.get("blocked"):
            continue
        count += 1
        if on_update and result.get("results"):
            summary = _summarize_result(result)
            on_update({"kind": "report", "trace_id": result.get("trace_id", ""), "summary": summary})
    return count


def _summarize_result(result: dict[str, Any]) -> str:
    results = result.get("results", [])
    if not results:
        return "No output"
    first = results[0] if isinstance(results[0], dict) else {}
    out = first.get("output", {})
    for k in ("assistant_reply", "answer", "summary", "text"):
        v = out.get(k)
        if isinstance(v, str) and v.strip():
            return (v[:200] + "…") if len(v) > 200 else v
    return str(out)[:200]


def run_trace_health_analyzer(
    honeycomb: HoneycombStore,
    honeycomb_root: Path,
) -> dict[str, Any]:
    """Compute trace health metrics. Lightweight, no Queen call."""
    return compute_ops_metrics(honeycomb_root)


def run_command_job(
    job: dict[str, Any],
    config: PulseConfig,
) -> tuple[bool, str]:
    """Execute a command job. Returns (success, output_or_error)."""
    payload = job.get("payload") or {}
    cmd_str = payload.get("cmd", "").strip()
    if not cmd_str:
        return False, "missing cmd"
    default_allowlist = frozenset({"beehive metrics", "beehive review list"})
    allowlist = config.command_allowlist if config.command_allowlist is not None else default_allowlist
    if allowlist and cmd_str not in allowlist:
        allowed = ", ".join(allowlist)
        return False, f"command_not_allowed (allowlist: {allowed})"
    try:
        result = subprocess.run(
            cmd_str.split(),
            capture_output=True,
            text=True,
            timeout=60,
            cwd=Path.cwd(),
        )
        out = (result.stdout or "").strip() or (result.stderr or "").strip()
        if result.returncode != 0:
            return False, out or f"exit code {result.returncode}"
        return True, out
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def run_queen_job(
    job: dict[str, Any],
    queen: QueenAgent,
    session_target: str,
    on_update: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run a Queen job (payload.kind == 'queen')."""
    payload = job.get("payload") or {}
    intent = payload.get("intent", "research_topic")
    message = payload.get("message", payload.get("query", ""))
    pl = dict(payload)
    pl.setdefault("query", message)
    source = f"pulse:{job.get('jobId', job.get('name', 'unnamed'))}"
    result = queen.run_autonomous(source, {"intent": intent, "payload": pl, "message": message})
    if on_update and result.get("results") and not result.get("blocked"):
        summary = _summarize_result(result)
        on_update({"kind": "report", "trace_id": result.get("trace_id", ""), "summary": summary})
    return result


def tick(
    config: PulseConfig,
    queen: QueenAgent,
    honeycomb: HoneycombStore,
    jobs: list[dict[str, Any]],
    on_queen_update: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Run one Pulse tick. Returns list of jobs that were run (for persistence)."""
    now = utcnow()
    jobs_path = config.jobs_path or _default_jobs_path(config.honeycomb_root)
    ran: list[dict[str, Any]] = []
    updated_jobs = list(jobs)

    for i, job in enumerate(jobs):
        if not job.get("enabled", True):
            continue
        if not _job_is_due(job, now):
            continue
        payload = job.get("payload") or {}
        kind = payload.get("kind", "queen")
        if kind == "backlog_processor":
            run_backlog_processor(
                queen,
                honeycomb,
                limit=config.max_queen_runs_per_tick,
                on_update=on_queen_update,
            )
            updated_jobs[i] = _mark_job_run(job)
            ran.append(job)
        elif kind == "command":
            ok, out = run_command_job(job, config)
            if on_queen_update:
                on_queen_update({"kind": "command_result", "job": job.get("name"), "ok": ok, "output": out[:500]})
            updated_jobs[i] = _mark_job_run(job)
            ran.append(job)
        elif kind == "queen":
            session_target = job.get("sessionTarget", "isolated")
            run_queen_job(job, queen, session_target, on_update=on_queen_update)
            updated_jobs[i] = _mark_job_run(job)
            ran.append(job)

    if updated_jobs != jobs:
        _save_jobs(jobs_path, updated_jobs)

    return ran


def run_pulse_loop(config: PulseConfig) -> None:
    """Main Pulse loop. Runs until interrupted."""
    jobs_path = config.jobs_path or _default_jobs_path(config.honeycomb_root)
    honeycomb = HoneycombStore(HoneycombConfig(root_dir=config.honeycomb_root))
    queen_config = QueenConfig(
        honeycomb_root=config.honeycomb_root,
        scheduler_backend="inline",
        vector_backend="memory",
    )
    queen = QueenAgent(queen_config)

    def _on_update(update: dict[str, Any]) -> None:
        honeycomb.write_event(
            "pulse_updates",
            {"kind": "queen_update", **update},
        )

    while True:
        try:
            jobs = _load_jobs(jobs_path)
            tick(config, queen, honeycomb, jobs, on_queen_update=_on_update)
        except KeyboardInterrupt:
            sys.exit(0)
        except Exception as e:
            honeycomb.write_event("pulse_updates", {"kind": "tick_error", "error": str(e)})
        time.sleep(config.interval_seconds)
