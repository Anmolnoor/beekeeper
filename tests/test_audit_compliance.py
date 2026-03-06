from __future__ import annotations

import json
from pathlib import Path

from beekeeper.audit_compliance import (
    create_integrity_checkpoint,
    reconcile_audit_trace_links,
    verify_integrity,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def test_reconcile_reports_resolved_and_missing(tmp_path: Path) -> None:
    root = tmp_path / ".honeycomb"
    audit_file = root / "audit" / "20260101.jsonl"
    _write_jsonl(
        audit_file,
        [
            {
                "at": "2026-01-01T01:00:00+00:00",
                "service": "queen",
                "action": "called",
                "source": "cli",
                "trace_id": "trace_linked",
                "trace_link_state": "linked",
            },
            {
                "at": "2026-01-01T01:01:00+00:00",
                "service": "queen",
                "action": "called",
                "source": "cli",
                "trace_id": "trace_resolved_later",
                "trace_link_state": "missing",
            },
            {
                "at": "2026-01-01T01:02:00+00:00",
                "service": "queen",
                "action": "called",
                "source": "cli",
                "trace_id": "trace_still_missing",
                "trace_link_state": "missing",
            },
        ],
    )
    events_dir = root / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    (events_dir / "trace_linked.jsonl").write_text("{}\n", encoding="utf-8")
    (events_dir / "trace_resolved_later.jsonl").write_text("{}\n", encoding="utf-8")

    report = reconcile_audit_trace_links(root, days=120)

    assert report["trace_link_total"] == 3
    assert report["trace_link_resolved_later"] == 1
    assert report["trace_link_still_missing"] == 1
    assert report["status"] == "fail"


def test_integrity_checkpoint_and_verify_pass(tmp_path: Path) -> None:
    root = tmp_path / ".honeycomb"
    day = "20260102"
    audit_file = root / "audit" / f"{day}.jsonl"
    _write_jsonl(audit_file, [{"at": "2026-01-02T00:00:00+00:00", "service": "queen"}])

    checkpoint = create_integrity_checkpoint(root, day_key=day)
    assert checkpoint["status"] == "checkpoint_written"

    report = verify_integrity(root, days=120)
    assert report["status"] == "pass"
    assert report["ok"] >= 1


def test_integrity_verify_fails_after_tamper(tmp_path: Path) -> None:
    root = tmp_path / ".honeycomb"
    day = "20260103"
    audit_file = root / "audit" / f"{day}.jsonl"
    _write_jsonl(audit_file, [{"at": "2026-01-03T00:00:00+00:00", "service": "queen"}])
    create_integrity_checkpoint(root, day_key=day)

    # Tamper with the audit file after checkpoint generation.
    _write_jsonl(audit_file, [{"at": "2026-01-03T00:00:00+00:00", "service": "queen", "tampered": True}])

    report = verify_integrity(root, days=120)
    assert report["status"] == "fail"
    assert report["hash_mismatches"] >= 1
