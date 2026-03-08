from __future__ import annotations

from pathlib import Path

from beekeeper.config.settings import Phase1Settings
from beekeeper.runtime import Phase1RuntimeService


def _runtime(tmp_path: Path) -> Phase1RuntimeService:
    settings = Phase1Settings(
        workspace_root=tmp_path,
        runtime_root=tmp_path / ".phase1",
        state_db_path=tmp_path / ".phase1" / "state.db",
        artifact_root=tmp_path / ".phase1" / "artifacts",
    )
    return Phase1RuntimeService(settings)


def test_phase1_run_executes_and_persists_trace(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    run = runtime.submit_run(
        {
            "goal": "Show the working directory",
            "workspace_path": str(tmp_path),
            "worker_kind": "bash",
            "job_type": "inspect",
            "payload": {"command": "pwd"},
        }
    )

    assert run["status"] == "completed"
    assert run["jobs"][0]["status"] == "succeeded"
    trace = runtime.get_trace(run["run_id"])
    assert [event["event_type"] for event in trace][:2] == ["run_created", "job_enqueued"]
    artifacts = runtime.get_artifacts(run["run_id"])
    assert {artifact["object_key"].split("/")[-1] for artifact in artifacts} == {"stdout.txt", "stderr.txt"}


def test_phase1_run_waits_for_approval_then_resumes(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    run = runtime.submit_run(
        {
            "goal": "Create an approved file",
            "workspace_path": str(tmp_path),
            "worker_kind": "bash",
            "job_type": "touch",
            "payload": {"command": "touch approved.txt"},
        }
    )

    assert run["status"] == "awaiting_approval"
    approval_id = run["pending_approvals"][0]["approval_id"]

    runtime.resolve_approval(approval_id, approved=True, resolved_by="tester")
    runtime.drain(run_id=run["run_id"])
    resumed = runtime.get_run(run["run_id"])

    assert resumed is not None
    assert resumed["status"] == "completed"
    assert (tmp_path / "approved.txt").exists()
