from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from beekeeper.audit_logger import log_service_call
from beekeeper.contracts import (
    AgentIdentity,
    RuleProfile,
    SkillProfile,
    SoulProfile,
    Status,
    TaskEnvelope,
    ResultEnvelope,
    WorkerKind,
)
from beekeeper.monitor import SentinelMonitor
from beekeeper.queen import QueenAgent
from beekeeper.queen import QueenConfig
from beekeeper.worker import AuditWorker, WorkerContext


def _audit_context() -> WorkerContext:
    return WorkerContext(
        identity=AgentIdentity(agent_type="worker.audit", skill_profile_id="skill.monitor.audit", soul_profile_id="soul.audit"),
        skill=SkillProfile(
            skill_profile_id="skill.monitor.audit",
            name="Audit",
            description="Audit",
            capabilities=["audit"],
            tool_allowlist=["trace_reader"],
        ),
        rule=RuleProfile(rule_profile_id="rule.default", name="Default"),
        soul=SoulProfile(soul_profile_id="soul.audit", name="Audit"),
    )


def _today_audit_file(root: Path) -> Path:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return root / "audit" / f"{day}.jsonl"


def test_audit_logger_adds_schema_linkage_and_redaction(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / ".honeycomb"
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(root))
    monkeypatch.setenv("BEEKEEPER_AUDIT_SYNC_WRITE", "true")

    log_service_call(
        "queen",
        "failed",
        source="cli",
        trace_id="trace_missing",
        error="Authorization bearer sk-secret-token",
        extra={"access_token": "abc", "nested": {"password": "p@ss"}},
    )

    events_dir = root / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    (events_dir / "trace_linked.jsonl").write_text("{}", encoding="utf-8")
    log_service_call("queen", "completed", source="cli", trace_id="trace_linked")

    rows = [json.loads(line) for line in _today_audit_file(root).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) >= 2
    first = rows[-2]
    second = rows[-1]

    assert first["schema_version"] == "v2"
    assert first["outcome"] == "failure"
    assert first["trace_link_state"] == "missing"
    assert first["trace_link_reason"] == "event_file_not_found_at_write_time"
    assert first["redaction_applied"] is True
    assert "sk-secret-token" not in first.get("error", "")
    assert first["extra"]["access_token"] == "***REDACTED***"
    assert second["trace_link_state"] == "linked"
    metrics = json.loads((root / "metrics" / "audit_metrics.json").read_text(encoding="utf-8"))
    assert metrics["audit_write_count"] >= 2
    assert "audit_retry_count" in metrics
    assert "audit_dead_letter_count" in metrics


def test_save_phrase_is_not_misparsed_as_literal_file_content() -> None:
    query = "Create a report on Anmol Noor and save it in local as anmol_noor_report.md"
    inferred = QueenAgent._infer_file_action(query)
    should_save, filename = QueenAgent._extract_save_to_file_request(query)
    assert inferred is None
    assert should_save is True
    assert filename == "anmol_noor_report.md"


def test_monitor_escalates_tiny_report_file_write() -> None:
    monitor = SentinelMonitor(min_confidence=0.65)
    task = TaskEnvelope(
        queen_trace_id="trace",
        queen_request_id="req",
        task_type="research_topic",
        worker_kind=WorkerKind.file_system,
        payload={"operation": "write"},
        idempotency_key="id",
    )
    result = ResultEnvelope(
        task_id=task.task_id,
        agent_id="worker",
        worker_kind=WorkerKind.file_system,
        status=Status.success,
        confidence=0.82,
        output={"operation": "write", "bytes_written": 11, "content_preview": "it in local"},
    )
    decision = monitor.inspect(task, result)
    assert decision.action == "escalate"
    assert decision.reason == "insufficient_file_content_for_report"


def test_audit_worker_flags_placeholder_small_written_content() -> None:
    worker = AuditWorker()
    task = TaskEnvelope(
        queen_trace_id="trace",
        queen_request_id="req",
        task_type="audit_result",
        worker_kind=WorkerKind.audit,
        payload={
            "target_task_id": "t1",
            "target_result": {
                "confidence": 0.9,
                "output": {
                    "operation": "write",
                    "bytes_written": 11,
                    "content_preview": "it in local",
                },
            },
        },
        idempotency_key="id",
    )
    out = worker.execute(task, _audit_context())
    assert out["verdict"] in {"review", "fail"}
    finding_codes = {f["code"] for f in out["findings"]}
    assert "insufficient_written_content" in finding_codes


def test_report_save_prompt_does_not_route_to_bash(tmp_path: Path) -> None:
    queen = QueenAgent(QueenConfig(honeycomb_root=tmp_path / ".honeycomb", scheduler_backend="inline"))
    payload = {"query": "Create a report on Anmol Noor and save it in local as anmol_noor_report.md"}
    kind = queen._route_worker_kind("research_topic", payload)
    assert kind != WorkerKind.bash
