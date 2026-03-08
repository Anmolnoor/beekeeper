from __future__ import annotations

from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .base import ApprovalRequest, BaseWorker, WorkerContext, WorkerResult


class NetworkWorker(BaseWorker):
    kind = "network"

    def preflight(self, payload: dict[str, object], context: WorkerContext) -> ApprovalRequest | None:
        url = str(payload.get("url", "")).strip()
        method = str(payload.get("method", "GET")).strip().upper()
        host = urlparse(url).hostname or ""
        if method != "GET":
            return ApprovalRequest(
                action_type="network.request",
                risk_level="high",
                reason="non_get_network_request",
                payload={"url": url, "method": method},
            )
        if not context.settings.enable_network_worker:
            return ApprovalRequest(
                action_type="network.request",
                risk_level="medium",
                reason="network_worker_disabled_by_default",
                payload={"url": url, "method": method},
            )
        if context.settings.allowed_network_hosts and host not in context.settings.allowed_network_hosts:
            return ApprovalRequest(
                action_type="network.request",
                risk_level="medium",
                reason="host_not_allowlisted",
                payload={"url": url, "allowed_hosts": context.settings.allowed_network_hosts},
            )
        return None

    def execute(self, payload: dict[str, object], context: WorkerContext) -> WorkerResult:
        url = str(payload["url"])
        req = Request(url, method="GET", headers={"User-Agent": "beekeeper-phase1/0.1"})
        with urlopen(req, timeout=15) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            artifact = context.artifact_store.put_bytes(
                run_id=context.run_id,
                job_id=context.job_id,
                attempt_id=context.attempt_id,
                object_key=f"{context.run_id}/{context.job_id}/{context.attempt_id}/response.bin",
                content=body,
                content_type=content_type,
            )
            preview = body[:2000].decode("utf-8", errors="replace")
            return WorkerResult(
                status="succeeded",
                summary=f"fetched {url}",
                output={"url": url, "status_code": response.status, "preview": preview},
                artifacts=[artifact],
            )
