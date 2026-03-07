"""Model-driven tool runtime: ToolRegistry, ToolExecutor, ToolLoopEngine.

Tools are registered by name; the executor runs them with schema validation and
persists call/result events to Honeycomb. The loop engine coordinates
model -> tool_calls -> execute -> observe until final answer or max_steps.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .contracts import (
    CostMetrics,
    FinalResponse,
    ToolCall,
    ToolExecutionPolicy,
    ToolLoopState,
    ToolResult,
    ToolSpec,
)
from .governance.tool_broker import LocalToolBroker, ToolBrokerContext
from .honeycomb import HoneycombStore


def _validate_tool_args(spec: ToolSpec, arguments: dict[str, Any]) -> list[str]:
    """Validate arguments against spec.parameters (JSON Schema). Returns list of error messages."""
    errors: list[str] = []
    params = spec.parameters or {}
    if not isinstance(params, dict):
        return ["tool parameters schema must be a dict"]
    props = params.get("properties") or {}
    required = params.get("required") or []
    for key in required:
        if key not in arguments:
            errors.append(f"Missing required argument: {key}")
    for key, value in arguments.items():
        if key not in props and props:
            errors.append(f"Unknown argument: {key}")
    return errors


class ToolRegistry:
    """Registry of tools by name. Register ToolSpec and optional executor callable."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._executors: dict[str, Callable[[str, dict[str, Any], dict[str, Any]], ToolResult]] = {}

    def register(
        self,
        spec: ToolSpec,
        executor: Callable[[str, dict[str, Any], dict[str, Any]], ToolResult] | None = None,
    ) -> None:
        """Register a tool by spec. If executor is None, execute() will return an error for this tool."""
        self._specs[spec.name] = spec
        if executor is not None:
            self._executors[spec.name] = executor

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def list_tools(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def list_tool_names(self) -> list[str]:
        return list(self._specs.keys())

    def get_openai_compatible_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions in OpenAI chat completions tools format."""
        out: list[dict[str, Any]] = []
        for spec in self._specs.values():
            out.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            })
        return out


ToolGuardrailFn = Callable[[str, dict[str, Any]], tuple[bool, str | None, bool]]


class ToolExecutor:
    """Execute tool calls with schema validation and Honeycomb event persistence."""

    def __init__(
        self,
        registry: ToolRegistry,
        honeycomb: HoneycombStore | None = None,
        policy: ToolExecutionPolicy | None = None,
        tool_guardrail_fn: ToolGuardrailFn | None = None,
        tool_broker: LocalToolBroker | None = None,
    ) -> None:
        self.registry = registry
        self.honeycomb = honeycomb
        self.policy = policy or ToolExecutionPolicy()
        self.tool_guardrail_fn = tool_guardrail_fn
        self.tool_broker = tool_broker

    def execute(
        self,
        call: ToolCall,
        context: dict[str, Any],
        trace_id: str = "",
    ) -> ToolResult:
        """Execute a single tool call. Validates args, runs executor, writes event."""
        spec = self.registry.get(call.tool_name)
        if spec is None:
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error=f"unknown_tool:{call.tool_name}",
            )
            self._write_tool_event(trace_id or call.trace_id, call, result)
            return result

        if self.policy.disallowed_tools and call.tool_name in self.policy.disallowed_tools:
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error="tool_disallowed_by_policy",
                policy_flags=["disallowed_tool"],
            )
            self._write_tool_event(trace_id or call.trace_id, call, result)
            return result

        if self.policy.allowed_tools is not None and call.tool_name not in self.policy.allowed_tools:
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error="tool_not_in_allowlist",
                policy_flags=["not_allowed"],
            )
            self._write_tool_event(trace_id or call.trace_id, call, result)
            return result

        if call.tool_name in (self.policy.require_human_approval_for_tools or []):
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error="needs_human_approval",
                policy_flags=["needs_human_approval"],
            )
            self._write_tool_event(trace_id or call.trace_id, call, result)
            return result

        if self.tool_guardrail_fn:
            allowed, block_reason, needs_human = self.tool_guardrail_fn(call.tool_name, call.arguments)
            if not allowed and block_reason:
                result = ToolResult(
                    call_id=call.call_id,
                    tool_name=call.tool_name,
                    success=False,
                    error=block_reason,
                    policy_flags=["guardrail_block"],
                )
                self._write_tool_event(trace_id or call.trace_id, call, result)
                return result
            if needs_human:
                result = ToolResult(
                    call_id=call.call_id,
                    tool_name=call.tool_name,
                    success=False,
                    error="needs_human_approval",
                    policy_flags=["needs_human_approval"],
                )
                self._write_tool_event(trace_id or call.trace_id, call, result)
                return result

        errors = _validate_tool_args(spec, call.arguments)
        if errors:
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error="; ".join(errors),
                policy_flags=["validation_failed"],
            )
            self._write_tool_event(trace_id or call.trace_id, call, result)
            return result

        executor_fn = self.registry._executors.get(call.tool_name)
        if executor_fn is None:
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error="no_executor_registered",
            )
            self._write_tool_event(trace_id or call.trace_id, call, result)
            return result

        ctx = dict(context)
        ctx["call_id"] = call.call_id
        ctx["trace_id"] = trace_id or call.trace_id
        try:
            if self.tool_broker is not None:
                result = self.tool_broker.execute(
                    executor=executor_fn,
                    broker_context=ToolBrokerContext(
                        trace_id=trace_id or call.trace_id,
                        call=call,
                        tool_spec=spec,
                        context=ctx,
                    ),
                )
            else:
                result = executor_fn(call.tool_name, call.arguments, ctx)
        except Exception as exc:
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                success=False,
                error=str(exc)[:500],
            )
        self._write_tool_event(trace_id or call.trace_id, call, result)
        return result

    def _write_tool_event(self, trace_id: str, call: ToolCall, result: ToolResult) -> None:
        if not trace_id or not self.honeycomb:
            return
        self.honeycomb.write_event(
            trace_id,
            {
                "kind": "tool_execution",
                "tool_call": call.model_dump(mode="json"),
                "tool_result": result.model_dump(mode="json"),
            },
        )


class ToolLoopEngine:
    """
    Coordinates the model-driven tool loop. Does not call the LLM itself;
    caller supplies a decision_fn(messages, tool_schemas) -> LLMDecision.
    """

    def __init__(
        self,
        executor: ToolExecutor,
        policy: ToolExecutionPolicy | None = None,
        max_steps: int | None = None,
    ) -> None:
        self.executor = executor
        self.policy = policy or executor.policy
        self._max_steps = max_steps if max_steps is not None else self.policy.max_steps

    def run(
        self,
        trace_id: str,
        initial_messages: list[dict[str, Any]],
        decision_fn: Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> FinalResponse:
        """
        Run the tool loop. decision_fn receives current messages and tool schemas;
        returns { "tool_calls": [ToolCall], "final_text": str | None, "error": str | None }.
        Continues until final_text is set, no tool_calls, error, or max_steps.
        """
        ctx = context or {}
        ctx["trace_id"] = trace_id
        state = ToolLoopState(trace_id=trace_id, message_history=list(initial_messages))
        tool_trace: list[dict[str, Any]] = []
        total_cost = CostMetrics()

        for step in range(self._max_steps):
            state.step_index = step
            tool_schemas = self.executor.registry.get_openai_compatible_tools()
            decision = decision_fn(state.message_history, tool_schemas)

            if decision.get("error"):
                return FinalResponse(
                    final_text=decision.get("final_text") or f"Error: {decision['error']}",
                    tool_trace=tool_trace,
                    cost_metrics=total_cost,
                    status="failed",
                    step_count=step,
                )

            final_text = decision.get("final_text")
            raw_calls = decision.get("tool_calls") or []

            if final_text and not raw_calls:
                state.terminated = True
                state.final_text = final_text
                return FinalResponse(
                    final_text=final_text,
                    tool_trace=tool_trace,
                    cost_metrics=total_cost,
                    status="success",
                    step_count=step + 1,
                )

            if not raw_calls:
                return FinalResponse(
                    final_text=final_text or "No response.",
                    tool_trace=tool_trace,
                    cost_metrics=total_cost,
                    status="partial",
                    step_count=step + 1,
                )

            state.tool_calls_this_turn = []
            state.tool_results_this_turn = []
            tool_results_for_messages: list[dict[str, Any]] = []
            status_callback = ctx.get("status_callback")

            for raw in raw_calls:
                if isinstance(raw, dict):
                    call = ToolCall(
                        tool_name=raw.get("name", raw.get("tool_name", "")),
                        arguments=dict(raw.get("arguments", raw.get("parameters", {}))),
                        trace_id=trace_id,
                        step_index=step,
                    )
                else:
                    call = raw if isinstance(raw, ToolCall) else ToolCall(tool_name="?", arguments={}, trace_id=trace_id, step_index=step)
                state.tool_calls_this_turn.append(call)
                if status_callback:
                    try:
                        status_callback(f"Calling tool {call.tool_name}…")
                    except Exception:
                        pass
                result = self.executor.execute(call, ctx, trace_id=trace_id)
                if status_callback:
                    try:
                        status_callback(f"Tool {call.tool_name} finished.")
                    except Exception:
                        pass
                state.tool_results_this_turn.append(result)
                tool_trace.append({
                    "tool_call": call.model_dump(mode="json"),
                    "tool_result": result.model_dump(mode="json"),
                })
                tool_results_for_messages.append({
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "content": json.dumps(result.output if result.success else {"error": result.error}),
                })
                if result.cost_metrics:
                    total_cost.latency_ms += result.cost_metrics.latency_ms
                    total_cost.estimated_cost_usd += result.cost_metrics.estimated_cost_usd
                state.accumulated_cost_usd += getattr(result.cost_metrics, "estimated_cost_usd", 0.0) or 0.0

            if state.accumulated_cost_usd > self.policy.max_cost_per_turn_usd:
                return FinalResponse(
                    final_text=final_text or "Budget exceeded.",
                    tool_trace=tool_trace,
                    cost_metrics=total_cost,
                    status="blocked",
                    step_count=step + 1,
                )

            # Append assistant message with tool_calls, then tool results (OpenAI-style conversation)
            state.message_history = list(state.message_history)
            assistant_tool_calls = [
                {"id": c.call_id, "type": "function", "function": {"name": c.tool_name, "arguments": json.dumps(c.arguments)}}
                for c in state.tool_calls_this_turn
            ]
            state.message_history.append({
                "role": "assistant",
                "content": final_text or None,
                "tool_calls": assistant_tool_calls,
            })
            for res in tool_results_for_messages:
                state.message_history.append(res)

        return FinalResponse(
            final_text=state.final_text or "Max steps reached.",
            tool_trace=tool_trace,
            cost_metrics=total_cost,
            status="partial",
            step_count=self._max_steps,
        )
