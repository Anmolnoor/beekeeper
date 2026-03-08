from __future__ import annotations

import json
import sys
from pathlib import Path

import beekeeper.cli.main as cli_main


def _set_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BEEKEEPER_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("BEEKEEPER_RUNTIME_ROOT", str(tmp_path / ".phase1"))
    monkeypatch.setenv("BEEKEEPER_STATE_DB_PATH", str(tmp_path / ".phase1" / "state.db"))
    monkeypatch.setenv("BEEKEEPER_ARTIFACT_ROOT", str(tmp_path / ".phase1" / "artifacts"))


def test_cli_run_status_and_trace(monkeypatch, tmp_path: Path, capsys) -> None:
    _set_env(monkeypatch, tmp_path)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "beekeeper",
            "run",
            "Write a file",
            "--worker-kind",
            "filesystem",
            "--payload",
            '{"operation":"write","path":"cli.txt","content":"hello"}',
            "--json",
        ],
    )
    cli_main.main()
    run = json.loads(capsys.readouterr().out)
    run_id = run["run_id"]

    monkeypatch.setattr(sys, "argv", ["beekeeper", "status", run_id, "--json"])
    cli_main.main()
    status = json.loads(capsys.readouterr().out)
    assert status["status"] == "completed"

    monkeypatch.setattr(sys, "argv", ["beekeeper", "trace", run_id, "--json"])
    cli_main.main()
    trace = json.loads(capsys.readouterr().out)
    assert any(event["event_type"] == "job_finished" for event in trace["events"])


def test_cli_approve(monkeypatch, tmp_path: Path, capsys) -> None:
    _set_env(monkeypatch, tmp_path)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "beekeeper",
            "run",
            "Create guarded file",
            "--worker-kind",
            "bash",
            "--payload",
            '{"command":"touch cli-approved.txt"}',
            "--json",
        ],
    )
    cli_main.main()
    run = json.loads(capsys.readouterr().out)
    approval_id = run["pending_approvals"][0]["approval_id"]

    monkeypatch.setattr(sys, "argv", ["beekeeper", "approve", approval_id, "--by", "cli-tester", "--json"])
    cli_main.main()
    approval = json.loads(capsys.readouterr().out)
    assert approval["status"] == "approved"

    monkeypatch.setattr(sys, "argv", ["beekeeper", "attach", run["run_id"], "--drain", "--json"])
    cli_main.main()
    attached = json.loads(capsys.readouterr().out)
    assert attached["status"] == "completed"


def test_cli_start_and_stack_commands(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_main, "stack_up", lambda **kwargs: {"ok": True, "action": "up", "kwargs": kwargs})
    monkeypatch.setattr(cli_main, "stack_ps", lambda: {"ok": True, "action": "ps"})
    monkeypatch.setattr(cli_main, "stack_down", lambda **kwargs: {"ok": True, "action": "down", "kwargs": kwargs})
    monkeypatch.setattr(cli_main, "stack_restart", lambda **kwargs: {"ok": True, "action": "restart", "kwargs": kwargs})
    monkeypatch.setattr(cli_main, "init_runtime", lambda settings: {"ok": True, "action": "init", "backend": settings.durable_state_backend})
    monkeypatch.setattr(cli_main, "_print_urls", lambda: print("urls"))

    monkeypatch.setattr(sys, "argv", ["beekeeper", "start", "--build"])
    cli_main.main()
    assert capsys.readouterr().out.strip() == "urls"

    monkeypatch.setattr(sys, "argv", ["beekeeper", "stack", "ps", "--json"])
    cli_main.main()
    assert json.loads(capsys.readouterr().out)["action"] == "ps"

    monkeypatch.setattr(sys, "argv", ["beekeeper", "stack", "down", "--volumes", "--json"])
    cli_main.main()
    down = json.loads(capsys.readouterr().out)
    assert down["kwargs"]["volumes"] is True

    monkeypatch.setattr(sys, "argv", ["beekeeper", "stack", "restart", "queen-api", "--json"])
    cli_main.main()
    restart = json.loads(capsys.readouterr().out)
    assert restart["kwargs"]["service"] == "queen-api"
