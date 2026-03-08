from __future__ import annotations

from pathlib import Path

from .base import ApprovalRequest, BaseWorker, WorkerContext, WorkerResult


class FilesystemWorker(BaseWorker):
    kind = "filesystem"

    def _resolve_target(self, context: WorkerContext, payload: dict[str, object]) -> Path:
        target = Path(str(payload.get("path") or ""))
        resolved = (context.workspace_path / target).resolve() if not target.is_absolute() else target.resolve()
        if context.workspace_path not in {resolved, *resolved.parents}:
            raise PermissionError("filesystem_target_outside_workspace")
        return resolved

    def preflight(self, payload: dict[str, object], context: WorkerContext) -> ApprovalRequest | None:
        operation = str(payload.get("operation", "read")).strip().lower()
        if operation in {"delete", "remove"}:
            return ApprovalRequest(
                action_type="filesystem.delete",
                risk_level="high",
                reason="destructive_filesystem_action",
                payload={"operation": operation, "path": str(payload.get("path", ""))},
            )
        return None

    def execute(self, payload: dict[str, object], context: WorkerContext) -> WorkerResult:
        operation = str(payload.get("operation", "read")).strip().lower()
        target = self._resolve_target(context, payload)
        if operation == "read":
            content = target.read_text(encoding="utf-8")
            artifact = context.artifact_store.put_text(
                run_id=context.run_id,
                job_id=context.job_id,
                attempt_id=context.attempt_id,
                object_key=f"{context.run_id}/{context.job_id}/{context.attempt_id}/read.txt",
                content=content,
            )
            return WorkerResult(
                status="succeeded",
                summary=f"read {target}",
                output={"path": str(target), "content": content},
                artifacts=[artifact],
            )
        if operation == "write":
            content = str(payload.get("content", ""))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            artifact = context.artifact_store.put_text(
                run_id=context.run_id,
                job_id=context.job_id,
                attempt_id=context.attempt_id,
                object_key=f"{context.run_id}/{context.job_id}/{context.attempt_id}/write.txt",
                content=content,
            )
            return WorkerResult(
                status="succeeded",
                summary=f"wrote {target}",
                output={"path": str(target), "bytes_written": len(content.encode('utf-8'))},
                artifacts=[artifact],
            )
        if operation == "list":
            entries = sorted(path.name for path in target.iterdir())
            return WorkerResult(
                status="succeeded",
                summary=f"listed {target}",
                output={"path": str(target), "entries": entries},
            )
        raise ValueError(f"unsupported_filesystem_operation:{operation}")
