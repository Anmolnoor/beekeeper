from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from .queen import QueenAgent


CompletionCallback = Callable[[bool], None]
SuccessCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class SubmissionReceipt:
    trace_id: str
    request_id: str
    state: str
    accepted: bool
    async_execution: bool
    result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "state": self.state,
            "accepted": self.accepted,
            "async_execution": self.async_execution,
        }
        if self.result is not None:
            payload["result"] = self.result
        return payload


class RunAdmissionService:
    """Control-plane admission shim that can decouple API latency from run execution."""

    def submit(
        self,
        *,
        queen: QueenAgent,
        intent: str,
        payload: dict[str, Any],
        source: str,
        async_execution: bool,
        on_complete: CompletionCallback | None = None,
        on_success: SuccessCallback | None = None,
    ) -> SubmissionReceipt:
        if not async_execution:
            result = queen.run(intent=intent, payload=payload, source=source)
            if on_success is not None:
                on_success(result)
            if on_complete is not None:
                on_complete(True)
            return SubmissionReceipt(
                trace_id=str(result.get("trace_id", "")),
                request_id=str(result.get("request_id", "")),
                state="completed",
                accepted=True,
                async_execution=False,
                result=result,
            )

        trace_id = f"trace_{uuid4().hex}"
        request_id = str(uuid4())
        queen.honeycomb.record_run_state(
            trace_id=trace_id,
            request_id=request_id,
            intent=intent,
            state="requested",
            source=source,
            payload={"submission_mode": "async_thread"},
            details={"admission": "control_plane"},
        )
        queen.honeycomb.record_run_state(
            trace_id=trace_id,
            request_id=request_id,
            intent=intent,
            state="admitted",
            source=source,
            payload={"submission_mode": "async_thread"},
            details={"admission": "control_plane"},
        )
        queen.honeycomb.record_run_state(
            trace_id=trace_id,
            request_id=request_id,
            intent=intent,
            state="queued",
            source=source,
            payload={"submission_mode": "async_thread"},
            details={"admission": "control_plane"},
        )

        def _run() -> None:
            ok = False
            try:
                result = queen.run(
                    intent=intent,
                    payload={
                        **payload,
                        "_trace_id": trace_id,
                        "_request_id": request_id,
                        "_admission_recorded": True,
                    },
                    source=source,
                )
                ok = True
                if on_success is not None:
                    on_success(result)
            except Exception as exc:
                queen.honeycomb.record_run_state(
                    trace_id=trace_id,
                    request_id=request_id,
                    intent=intent,
                    state="failed",
                    source=source,
                    payload={"submission_mode": "async_thread"},
                    details={"error": str(exc)[:240]},
                )
            finally:
                if on_complete is not None:
                    on_complete(ok)

        threading.Thread(target=_run, daemon=True).start()
        return SubmissionReceipt(
            trace_id=trace_id,
            request_id=request_id,
            state="queued",
            accepted=True,
            async_execution=True,
        )
