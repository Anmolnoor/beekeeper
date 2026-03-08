from __future__ import annotations

from typing import Any


class JobDispatcher:
    def build_jobs(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        jobs = request.get("jobs")
        if isinstance(jobs, list) and jobs:
            normalized: list[dict[str, Any]] = []
            for index, job in enumerate(jobs):
                item = dict(job)
                item.setdefault("job_type", f"step_{index + 1}")
                item.setdefault("worker_kind", "bash")
                item.setdefault("payload", {})
                normalized.append(item)
            return normalized
        payload = dict(request.get("payload") or {})
        if "command" in request and "command" not in payload:
            payload["command"] = request["command"]
        if "path" in request and "path" not in payload:
            payload["path"] = request["path"]
        if "url" in request and "url" not in payload:
            payload["url"] = request["url"]
        return [
            {
                "job_type": str(request.get("job_type", "task")),
                "worker_kind": str(request.get("worker_kind", "bash")),
                "payload": payload,
            }
        ]
