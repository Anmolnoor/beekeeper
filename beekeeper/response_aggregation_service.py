from __future__ import annotations

from typing import Any

from .contracts import ResultEnvelope, Status


class ResponseAggregationService:
    """Builds normalized run responses and terminal run states."""

    def terminal_state_for_results(self, results: list[ResultEnvelope]) -> str:
        statuses = [r.status.value for r in results]
        if any(status == Status.failed.value for status in statuses):
            return "failed"
        if any(
            status == Status.blocked.value and isinstance(r.output, dict) and r.output.get("human_review_id")
            for r, status in zip(results, statuses)
        ):
            return "waiting_approval"
        return "succeeded"

    def build_response(
        self,
        *,
        trace_id: str,
        request_id: str,
        queen_soul_profile_id: str,
        ollama_base_url: str,
        results: list[ResultEnvelope] | None = None,
        trace_events: list[dict[str, Any]] | None = None,
        semantic_hits_for_intent: list[str] | None = None,
        action_loop: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "trace_id": trace_id,
            "request_id": request_id,
            "queen_soul_profile_id": queen_soul_profile_id,
            "ollama_base_url": ollama_base_url,
            "results": [result.model_dump(mode="json") for result in (results or [])],
            "trace_events": trace_events or [],
            "semantic_hits_for_intent": semantic_hits_for_intent or [],
        }
        if action_loop is not None:
            payload["action_loop"] = action_loop
        return payload

