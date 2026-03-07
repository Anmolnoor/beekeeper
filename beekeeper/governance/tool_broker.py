from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..contracts import ToolCall, ToolResult, ToolSpec
from ..honeycomb import HoneycombStore


ToolExecutorFn = Callable[[str, dict[str, Any], dict[str, Any]], ToolResult]


@dataclass
class ToolBrokerContext:
    trace_id: str
    call: ToolCall
    tool_spec: ToolSpec
    context: dict[str, Any]


class LocalToolBroker:
    """Single mediation point for side effects, approvals, and provenance."""

    def __init__(self, honeycomb: HoneycombStore | None = None) -> None:
        self.honeycomb = honeycomb

    def execute(self, *, executor: ToolExecutorFn, broker_context: ToolBrokerContext) -> ToolResult:
        result = executor(broker_context.call.tool_name, broker_context.call.arguments, broker_context.context)
        if self.honeycomb and broker_context.trace_id:
            self.honeycomb.write_event(
                broker_context.trace_id,
                {
                    "kind": "tool_broker",
                    "tool_name": broker_context.call.tool_name,
                    "call_id": broker_context.call.call_id,
                    "success": result.success,
                    "error": result.error,
                    "policy_flags": list(result.policy_flags or []),
                },
            )
        return result
