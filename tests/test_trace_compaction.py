"""Tests for trace compaction."""
from pathlib import Path

import pytest

from beehive.trace_compaction import (
    _compact_events,
    compact_trace_file,
    compact_traces,
)


def test_compact_deduplicates_task_state() -> None:
    events = [
        {"kind": "task", "stage": "task_state", "task_id": "t1", "at": "2020-01-01T00:00:00Z"},
        {"kind": "task", "stage": "task_state", "task_id": "t1", "at": "2020-01-01T00:00:01Z"},
    ]
    compacted = _compact_events(events)
    task_events = [e for e in compacted if e.get("kind") == "task"]
    assert len(task_events) == 1
    assert task_events[0]["task_id"] == "t1"


def test_compact_collapses_worker_lifecycle() -> None:
    events = [
        {"kind": "worker_lifecycle", "stage": "preflight", "task_id": "t1", "at": "2020-01-01T00:00:00Z"},
        {"kind": "worker_lifecycle", "stage": "execute", "task_id": "t1", "at": "2020-01-01T00:00:01Z"},
        {"kind": "worker_lifecycle", "stage": "terminate", "task_id": "t1", "at": "2020-01-01T00:00:02Z"},
    ]
    compacted = _compact_events(events)
    lifecycle = [e for e in compacted if e.get("kind") == "worker_lifecycle"]
    assert len(lifecycle) == 1
    assert lifecycle[0]["stage"] == "summary"
    assert set(lifecycle[0]["stages"]) == {"preflight", "execute", "terminate"}


def test_compact_preserves_policy_decision() -> None:
    events = [
        {"kind": "policy_decision", "task_id": "t1", "status": "allow", "at": "2020-01-01T00:00:00Z"},
    ]
    compacted = _compact_events(events)
    assert len(compacted) == 1
    assert compacted[0]["kind"] == "policy_decision"


def test_compact_trace_file(tmp_path: Path) -> None:
    events_file = tmp_path / "trace_abc.jsonl"
    events_file.write_text(
        '{"kind":"task","stage":"task_state","task_id":"t1","at":"2020-01-01"}\n'
        '{"kind":"task","stage":"task_state","task_id":"t1","at":"2020-01-02"}\n'
    )
    orig, comp = compact_trace_file(events_file, in_place=True)
    assert orig == 2
    assert comp == 1
    lines = events_file.read_text().strip().split("\n")
    assert len(lines) == 1


def test_compact_traces_all(tmp_path: Path) -> None:
    events_dir = tmp_path / "events"
    events_dir.mkdir(parents=True)
    (events_dir / "trace_1.jsonl").write_text('{"kind":"policy_decision","at":"2020-01-01"}\n')
    (events_dir / "trace_2.jsonl").write_text(
        '{"kind":"task","stage":"task_state","task_id":"t1","at":"2020-01-01"}\n'
        '{"kind":"task","stage":"task_state","task_id":"t1","at":"2020-01-02"}\n'
    )
    result = compact_traces(tmp_path, all_traces=True)
    assert result["compacted"] == 2
    assert result["bytes_saved"] >= 0


def test_compact_traces_single(tmp_path: Path) -> None:
    events_dir = tmp_path / "events"
    events_dir.mkdir(parents=True)
    (events_dir / "trace_abc.jsonl").write_text(
        '{"kind":"task","stage":"task_state","task_id":"t1","at":"2020-01-01"}\n'
        '{"kind":"task","stage":"task_state","task_id":"t1","at":"2020-01-02"}\n'
    )
    result = compact_traces(tmp_path, trace_id="trace_abc")
    assert result["compacted"] == 1
    assert "trace_abc" in result["traces"]
