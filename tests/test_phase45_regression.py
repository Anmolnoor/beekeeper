from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from beekeeper.honeycomb import HoneycombConfig, HoneycombStore
from beekeeper.queen import QueenAgent, QueenConfig


def _make_queen(tmp_path: Path) -> QueenAgent:
    return QueenAgent(
        QueenConfig(
            honeycomb_root=tmp_path / ".honeycomb",
            scheduler_backend="inline",
            max_reruns=1,
            auto_approve_human_reviews=False,
        )
    )


def test_hitl_blocks_without_approval(tmp_path: Path) -> None:
    queen = _make_queen(tmp_path)
    response = queen.run(
        intent="research_topic",
        payload={
            "query": "prepare payment change request",
            "action": "payment_action",
            "requires_human_approval": True,
            "use_web_search": True,
        },
    )
    statuses = [item["status"] for item in response["results"]]
    assert "blocked" in statuses
    policy_rows = (tmp_path / ".honeycomb" / "governance" / f"{response['trace_id']}.jsonl").read_text(encoding="utf-8")
    assert "needs_human" in policy_rows


def test_hitl_approval_path_allows_execution(tmp_path: Path) -> None:
    queen = _make_queen(tmp_path)
    response = queen.run(
        intent="research_topic",
        payload={
            "query": "prepare payment change request",
            "action": "payment_action",
            "requires_human_approval": True,
            "human_approved": True,
            "human_approver": "test-oncall",
        },
    )
    statuses = [item["status"] for item in response["results"]]
    assert "success" in statuses


def test_adaptive_feedback_file_created(tmp_path: Path) -> None:
    queen = _make_queen(tmp_path)
    queen.run(intent="research_topic", payload={"query": "durable workflows", "use_web_search": True})
    feedback_file = tmp_path / ".honeycomb" / "optimizer" / "routing_feedback.json"
    assert feedback_file.exists()
    content = feedback_file.read_text(encoding="utf-8")
    assert "web_search" in content


def test_retention_lifecycle_moves_aged_artifacts(tmp_path: Path) -> None:
    root = tmp_path / ".honeycomb"
    store = HoneycombStore(HoneycombConfig(root_dir=root))
    artifact = root / "artifacts" / "old.txt"
    artifact.write_text("old artifact", encoding="utf-8")
    old_time = (datetime.now(timezone.utc) - timedelta(days=120)).timestamp()
    artifact.touch()
    import os

    os.utime(artifact, (old_time, old_time))
    moved = store.enforce_retention_lifecycle(hot_days=30, warm_days=90)
    assert moved["cold"] == 1
    assert (root / "archive" / "cold" / "old.txt").exists()
