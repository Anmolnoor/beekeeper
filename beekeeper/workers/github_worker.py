from __future__ import annotations

import subprocess
from pathlib import Path

from .base import ApprovalRequest, BaseWorker, WorkerContext, WorkerResult

_READ_ONLY_ACTIONS = {
    "status": ["git", "status", "--short"],
    "diff": ["git", "diff", "--stat"],
    "log": ["git", "log", "--oneline", "-n", "20"],
    "branches": ["git", "branch", "--all"],
}


class GitHubWorker(BaseWorker):
    kind = "github"

    def preflight(self, payload: dict[str, object], context: WorkerContext) -> ApprovalRequest | None:
        action = str(payload.get("action", "status")).strip().lower()
        if action not in _READ_ONLY_ACTIONS:
            return ApprovalRequest(
                action_type="github.write",
                risk_level="high",
                reason="github_write_action_requires_approval",
                payload={"action": action},
            )
        return None

    def execute(self, payload: dict[str, object], context: WorkerContext) -> WorkerResult:
        action = str(payload.get("action", "status")).strip().lower()
        command = _READ_ONLY_ACTIONS[action]
        cwd = Path(str(payload.get("cwd") or context.workspace_path)).resolve()
        if context.workspace_path not in {cwd, *cwd.parents}:
            raise PermissionError("github_worker_cwd_outside_workspace")
        proc = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True)
        artifact = context.artifact_store.put_text(
            run_id=context.run_id,
            job_id=context.job_id,
            attempt_id=context.attempt_id,
            object_key=f"{context.run_id}/{context.job_id}/{context.attempt_id}/git.txt",
            content=proc.stdout + ("\n" + proc.stderr if proc.stderr else ""),
        )
        status = "succeeded" if proc.returncode == 0 else "failed"
        return WorkerResult(
            status=status,
            summary=f"github action {action} finished with code {proc.returncode}",
            output={
                "action": action,
                "returncode": proc.returncode,
                "stdout_preview": proc.stdout[:5000],
                "stderr_preview": proc.stderr[:5000],
            },
            artifacts=[artifact],
        )
