from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from .base import ApprovalRequest, BaseWorker, WorkerContext, WorkerResult

_HIGH_RISK_TOKENS = {"rm", "mv", "sudo", "chmod", "chown", "dd", "mkfs", "shutdown", "reboot"}


class BashWorker(BaseWorker):
    kind = "bash"

    def preflight(self, payload: dict[str, object], context: WorkerContext) -> ApprovalRequest | None:
        command = str(payload.get("command", "")).strip()
        if not command:
            return ApprovalRequest(
                action_type="shell.execute",
                risk_level="high",
                reason="missing_command",
                payload={"command": command},
            )
        try:
            tokens = shlex.split(command)
        except ValueError:
            return ApprovalRequest(
                action_type="shell.execute",
                risk_level="high",
                reason="unparseable_command",
                payload={"command": command},
            )
        if not tokens:
            return ApprovalRequest(
                action_type="shell.execute",
                risk_level="high",
                reason="empty_command",
                payload={"command": command},
            )
        binary = tokens[0]
        if binary in _HIGH_RISK_TOKENS:
            return ApprovalRequest(
                action_type="shell.execute",
                risk_level="high",
                reason="destructive_command",
                payload={"command": command},
            )
        if binary not in context.settings.bash_allowlist:
            return ApprovalRequest(
                action_type="shell.execute",
                risk_level="medium",
                reason="command_not_allowlisted",
                payload={"command": command, "allowlist": context.settings.bash_allowlist},
            )
        return None

    def execute(self, payload: dict[str, object], context: WorkerContext) -> WorkerResult:
        command = str(payload["command"])
        requested_cwd = Path(str(payload.get("cwd") or context.workspace_path))
        cwd = requested_cwd.resolve()
        if context.workspace_path not in {cwd, *cwd.parents}:
            raise PermissionError("bash_worker_cwd_outside_workspace")
        proc = subprocess.run(
            shlex.split(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        stdout_artifact = context.artifact_store.put_text(
            run_id=context.run_id,
            job_id=context.job_id,
            attempt_id=context.attempt_id,
            object_key=f"{context.run_id}/{context.job_id}/{context.attempt_id}/stdout.txt",
            content=proc.stdout,
        )
        stderr_artifact = context.artifact_store.put_text(
            run_id=context.run_id,
            job_id=context.job_id,
            attempt_id=context.attempt_id,
            object_key=f"{context.run_id}/{context.job_id}/{context.attempt_id}/stderr.txt",
            content=proc.stderr,
        )
        status = "succeeded" if proc.returncode == 0 else "failed"
        summary = f"{command} exited with code {proc.returncode}"
        return WorkerResult(
            status=status,
            summary=summary,
            output={
                "command": command,
                "returncode": proc.returncode,
                "stdout_preview": proc.stdout[:5000],
                "stderr_preview": proc.stderr[:5000],
                "cwd": str(cwd),
            },
            artifacts=[stdout_artifact, stderr_artifact],
        )
