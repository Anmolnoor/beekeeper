"""Central audit logger for full-stack service invocations.

Logs when Redis, Queen, Qdrant, LLM, etc. are called, with caller source.
Stores entries in .honeycomb/audit/YYYYMMDD.jsonl.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
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


def _audit_sync_write() -> bool:
    return os.getenv("BEEKEEPER_AUDIT_SYNC_WRITE", "false").lower() in ("true", "1", "yes")


_audit_lock = threading.Lock()
_metrics_lock = threading.Lock()
_worker_lock = threading.Lock()
_audit_queue: "queue.Queue[dict[str, Any]] | None" = None
_audit_worker_started = False
_AUDIT_SCHEMA_VERSION = "v2"
_VALID_OUTCOMES = {"success", "failure", "denied", "blocked", "unknown"}
_REDACTION_MASK = "***REDACTED***"
_MAX_ERROR_LEN = 512
_MAX_FIELD_LEN = 4096
_MAX_EXTRA_JSON_LEN = 8192
_QUEUE_MAXSIZE = max(50, int(os.getenv("BEEKEEPER_AUDIT_QUEUE_MAXSIZE", "2048")))
_QUEUE_TIMEOUT_SECONDS = max(0.1, float(os.getenv("BEEKEEPER_AUDIT_QUEUE_TIMEOUT_SECONDS", "1.0")))
_MAX_RETRIES = max(0, int(os.getenv("BEEKEEPER_AUDIT_MAX_RETRIES", "3")))
_RETRY_BASE_MS = max(10, int(os.getenv("BEEKEEPER_AUDIT_RETRY_BASE_MS", "50")))
_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|bearer|password|secret|private[_-]?key)\b"),
    re.compile(r"(?i)\bsk-[a-z0-9]{16,}\b"),
    re.compile(r"(?i)\bghp_[a-z0-9]{20,}\b"),
]


def _metrics_path() -> Path:
    return _honeycomb_root() / "metrics" / "audit_metrics.json"


def _dead_letter_path() -> Path:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _honeycomb_root() / "audit" / f"dead_letter_{day}.jsonl"


def _update_metrics(
    *,
    written: int = 0,
    write_failures: int = 0,
    redaction_hits: int = 0,
    linkage_checked: int = 0,
    linkage_missing: int = 0,
    retry_count: int = 0,
    dead_letter_count: int = 0,
    queue_overflow_count: int = 0,
    queue_depth: int | None = None,
) -> None:
    path = _metrics_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _metrics_lock:
        payload: dict[str, Any] = {
            "schema_version": _AUDIT_SCHEMA_VERSION,
            "updated_at": _utcnow_iso(),
            "audit_write_count": 0,
            "audit_write_failure_count": 0,
            "redaction_hit_count": 0,
            "trace_linkage_checked_count": 0,
            "trace_linkage_missing_count": 0,
            "audit_retry_count": 0,
            "audit_dead_letter_count": 0,
            "audit_queue_overflow_count": 0,
            "audit_queue_depth": 0,
            "audit_queue_max_depth_seen": 0,
        }
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    payload.update(existing)
            except Exception:
                pass
        payload["schema_version"] = _AUDIT_SCHEMA_VERSION
        payload["updated_at"] = _utcnow_iso()
        payload["audit_write_count"] = int(payload.get("audit_write_count", 0)) + int(written)
        payload["audit_write_failure_count"] = int(payload.get("audit_write_failure_count", 0)) + int(write_failures)
        payload["redaction_hit_count"] = int(payload.get("redaction_hit_count", 0)) + int(redaction_hits)
        payload["trace_linkage_checked_count"] = int(payload.get("trace_linkage_checked_count", 0)) + int(linkage_checked)
        payload["trace_linkage_missing_count"] = int(payload.get("trace_linkage_missing_count", 0)) + int(linkage_missing)
        payload["audit_retry_count"] = int(payload.get("audit_retry_count", 0)) + int(retry_count)
        payload["audit_dead_letter_count"] = int(payload.get("audit_dead_letter_count", 0)) + int(dead_letter_count)
        payload["audit_queue_overflow_count"] = int(payload.get("audit_queue_overflow_count", 0)) + int(queue_overflow_count)
        if queue_depth is not None:
            payload["audit_queue_depth"] = int(queue_depth)
            payload["audit_queue_max_depth_seen"] = max(
                int(payload.get("audit_queue_max_depth_seen", 0)),
                int(queue_depth),
            )
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _append_dead_letter(row: dict[str, Any], error: str, attempts: int) -> None:
    entry = {
        "at": _utcnow_iso(),
        "schema_version": _AUDIT_SCHEMA_VERSION,
        "attempts": attempts,
        "error": error[:240],
        "row": row,
    }
    path = _dead_letter_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _audit_lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")


def _normalize_outcome(action: str, outcome: str | None) -> str:
    if outcome:
        value = str(outcome).strip().lower()
        if value in _VALID_OUTCOMES:
            return value
    if action == "failed":
        return "failure"
    if action in {"completed", "submitted"}:
        return "success"
    return "unknown"


def _trace_link_state(trace_id: str | None) -> tuple[str, str]:
    if not trace_id:
        return "not_provided", "missing_trace_id"
    events_file = _honeycomb_root() / "events" / f"{trace_id}.jsonl"
    if events_file.exists():
        return "linked", ""
    return "missing", "event_file_not_found_at_write_time"


def _sanitize_string(value: str) -> tuple[str, int]:
    text = value.strip()
    hits = 0
    for pattern in _SENSITIVE_PATTERNS:
        if pattern.search(text):
            text = pattern.sub(_REDACTION_MASK, text)
            hits += 1
    if len(text) > _MAX_FIELD_LEN:
        text = text[:_MAX_FIELD_LEN]
    return text, hits


def _sanitize_value(value: Any) -> tuple[Any, int]:
    if value is None:
        return None, 0
    if isinstance(value, str):
        return _sanitize_string(value)
    if isinstance(value, dict):
        total_hits = 0
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_l = str(key).lower()
            if any(tok in key_l for tok in ("token", "secret", "password", "authorization", "api_key", "private_key")):
                cleaned[str(key)] = _REDACTION_MASK
                total_hits += 1
                continue
            val, hits = _sanitize_value(item)
            cleaned[str(key)] = val
            total_hits += hits
        return cleaned, total_hits
    if isinstance(value, list):
        total_hits = 0
        cleaned_items: list[Any] = []
        for item in value:
            val, hits = _sanitize_value(item)
            cleaned_items.append(val)
            total_hits += hits
        return cleaned_items, total_hits
    return value, 0


def _write_row(row: dict[str, Any]) -> None:
    root = _honeycomb_root()
    audit_dir = root / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = audit_dir / f"{today}.jsonl"
    line = json.dumps(row, ensure_ascii=True) + "\n"
    with _audit_lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


def _write_with_retry(
    row: dict[str, Any],
    *,
    redaction_hits: int,
    linkage_checked: int,
    linkage_missing: int,
) -> None:
    retries_used = 0
    for attempt in range(_MAX_RETRIES + 1):
        try:
            _write_row(row)
            _update_metrics(
                written=1,
                redaction_hits=redaction_hits,
                linkage_checked=linkage_checked,
                linkage_missing=linkage_missing,
                retry_count=retries_used,
                queue_depth=(_audit_queue.qsize() if _audit_queue is not None else None),
            )
            return
        except Exception as exc:
            if attempt >= _MAX_RETRIES:
                try:
                    _append_dead_letter(row, str(exc), attempts=attempt + 1)
                except Exception:
                    pass
                _update_metrics(
                    write_failures=1,
                    redaction_hits=redaction_hits,
                    retry_count=retries_used,
                    dead_letter_count=1,
                    queue_depth=(_audit_queue.qsize() if _audit_queue is not None else None),
                )
                return
            retries_used += 1
            sleep_ms = _RETRY_BASE_MS * (2**attempt)
            time.sleep(sleep_ms / 1000.0)


def _ensure_worker_started() -> None:
    global _audit_queue, _audit_worker_started
    with _worker_lock:
        if _audit_queue is None:
            import queue

            _audit_queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        if _audit_worker_started:
            return

        def _worker() -> None:
            while True:
                if _audit_queue is None:
                    time.sleep(0.05)
                    continue
                item = _audit_queue.get()
                try:
                    _write_with_retry(
                        item["row"],
                        redaction_hits=int(item.get("redaction_hits", 0)),
                        linkage_checked=int(item.get("linkage_checked", 0)),
                        linkage_missing=int(item.get("linkage_missing", 0)),
                    )
                except Exception as exc:
                    try:
                        print(f"[beekeeper.audit] worker write failure: {exc}", file=sys.stderr)
                    except Exception:
                        pass
                finally:
                    _audit_queue.task_done()

        threading.Thread(target=_worker, daemon=True, name="beekeeper-audit-writer").start()
        _audit_worker_started = True


def log_service_call(
    service: str,
    action: str = "called",
    source: str | None = None,
    trace_id: str | None = None,
    extra: dict[str, Any] | None = None,
    user_id: str | None = None,
    resource: str | None = None,
    outcome: str | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Append a service call entry to the audit log.

    service: redis | queen | qdrant | ollama | gemini | openai | searxng | temporal | beekeeper_api | queen_api
    action: called | submitted | completed | failed
    source: queen_api | beekeeper_api:chat | web_ui | channel:slack | cli | pulse | etc.
    """
    if not _audit_enabled():
        return
    trace_state, trace_reason = _trace_link_state(trace_id)
    linkage_checked = 1 if trace_id else 0
    linkage_missing = 1 if trace_id and trace_state != "linked" else 0
    normalized_outcome = _normalize_outcome(action, outcome)
    sanitized_error, error_hits = _sanitize_value(error)
    sanitized_extra, extra_hits = _sanitize_value(extra or {})
    if isinstance(sanitized_error, str):
        sanitized_error = sanitized_error[:_MAX_ERROR_LEN]
    if isinstance(sanitized_extra, dict):
        try:
            extra_json = json.dumps(sanitized_extra, ensure_ascii=True)
            if len(extra_json) > _MAX_EXTRA_JSON_LEN:
                sanitized_extra = {"truncated": True, "summary": extra_json[:_MAX_EXTRA_JSON_LEN]}
        except Exception:
            sanitized_extra = {"truncated": True, "summary": "extra_unserializable"}
    redaction_hits = error_hits + extra_hits
    row = {
        "at": _utcnow_iso(),
        "schema_version": _AUDIT_SCHEMA_VERSION,
        "service": service,
        "action": action,
        "source": source or "unknown",
        "outcome": normalized_outcome,
        "trace_link_state": trace_state,
    }
    if trace_reason:
        row["trace_link_reason"] = trace_reason
    if trace_id:
        row["trace_id"] = trace_id
    if user_id:
        row["user_id"] = user_id
    if resource:
        row["resource"] = resource
    if sanitized_error:
        row["error"] = sanitized_error
    if duration_ms is not None:
        row["duration_ms"] = duration_ms
    if sanitized_extra:
        row["extra"] = sanitized_extra
    if redaction_hits:
        row["redaction_applied"] = True

    if _audit_sync_write():
        _write_with_retry(
            row,
            redaction_hits=redaction_hits,
            linkage_checked=linkage_checked,
            linkage_missing=linkage_missing,
        )
    else:
        _ensure_worker_started()
        if _audit_queue is None:
            _write_with_retry(
                row,
                redaction_hits=redaction_hits,
                linkage_checked=linkage_checked,
                linkage_missing=linkage_missing,
            )
            return
        item = {
            "row": row,
            "redaction_hits": redaction_hits,
            "linkage_checked": linkage_checked,
            "linkage_missing": linkage_missing,
        }
        try:
            _audit_queue.put(item, timeout=_QUEUE_TIMEOUT_SECONDS)
            _update_metrics(queue_depth=_audit_queue.qsize())
        except Exception:
            _update_metrics(queue_overflow_count=1, queue_depth=_audit_queue.qsize())
            _write_with_retry(
                row,
                redaction_hits=redaction_hits,
                linkage_checked=linkage_checked,
                linkage_missing=linkage_missing,
            )
