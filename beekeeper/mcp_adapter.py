"""MCP (Model Context Protocol) adapter: discover tools, convert to ToolSpec, execute with policy."""

from __future__ import annotations

import json
from typing import Any, Callable

from .contracts import CostMetrics, ToolResult, ToolSpec, TrustTier


def mcp_descriptor_to_tool_spec(
    descriptor: dict[str, Any],
    trust_tier: TrustTier = TrustTier.medium,
) -> ToolSpec:
    """Convert an MCP tool descriptor to ToolSpec. MCP uses name, description, inputSchema."""
    name = str(descriptor.get("name", "")).strip() or "unknown"
    description = str(descriptor.get("description", "")).strip() or f"MCP tool: {name}"
    input_schema = descriptor.get("inputSchema")
    if isinstance(input_schema, dict):
        parameters = input_schema
    else:
        parameters = {"type": "object", "properties": {}, "required": []}
    return ToolSpec(
        name=name,
        description=description,
        parameters=parameters,
        trust_tier=trust_tier,
        source="mcp",
    )


def discover_mcp_tool_specs(
    descriptors: list[dict[str, Any]],
    allowlist: list[str] | None = None,
    denylist: list[str] | None = None,
    default_trust_tier: TrustTier = TrustTier.medium,
) -> list[ToolSpec]:
    """Convert a list of MCP tool descriptors to ToolSpecs, applying allowlist/denylist."""
    specs: list[ToolSpec] = []
    denylist_set = set(denylist or [])
    allowlist_set = set(allowlist) if allowlist is not None else None
    for d in descriptors:
        if not isinstance(d, dict):
            continue
        name = str(d.get("name", "")).strip()
        if not name:
            continue
        if name in denylist_set:
            continue
        if allowlist_set is not None and name not in allowlist_set:
            continue
        specs.append(mcp_descriptor_to_tool_spec(d, trust_tier=default_trust_tier))
    return specs


def make_mcp_executor(
    call_tool_fn: Callable[[str, dict[str, Any]], dict[str, Any] | str],
    timeout_seconds: float = 30.0,
) -> Callable[[str, dict[str, Any], dict[str, Any]], ToolResult]:
    """
    Build an executor callable (tool_name, arguments, context) -> ToolResult
    that invokes call_tool_fn(tool_name, arguments) and maps the result to ToolResult.
    call_tool_fn may return a dict (content or result) or a string; on exception returns error ToolResult.
    """

    def executor(tool_name: str, arguments: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        call_id = context.get("call_id", "")
        try:
            raw = call_tool_fn(tool_name, arguments)
            if isinstance(raw, dict):
                output = raw
            elif isinstance(raw, str):
                output = {"content": raw, "text": raw}
            else:
                output = {"result": str(raw)}
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                success=True,
                output=output,
                cost_metrics=CostMetrics(latency_ms=0),
            )
        except TimeoutError as e:
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                success=False,
                error=f"timeout:{timeout_seconds}s",
                output={"error": str(e)},
            )
        except Exception as e:
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                success=False,
                error=str(e)[:500],
                output={"error": str(e)},
            )

    return executor


def register_mcp_tools(
    tool_registry: Any,
    descriptors: list[dict[str, Any]],
    call_tool_fn: Callable[[str, dict[str, Any]], dict[str, Any] | str],
    allowlist: list[str] | None = None,
    denylist: list[str] | None = None,
    default_trust_tier: TrustTier = TrustTier.medium,
    timeout_seconds: float = 30.0,
) -> None:
    """
    Register MCP tools on the given ToolRegistry. Discovers specs from descriptors,
    applies allowlist/denylist, and registers the executor built from call_tool_fn.
    """
    from .tool_runtime import ToolRegistry
    if not isinstance(tool_registry, ToolRegistry):
        return
    specs = discover_mcp_tool_specs(descriptors, allowlist=allowlist, denylist=denylist, default_trust_tier=default_trust_tier)
    executor = make_mcp_executor(call_tool_fn, timeout_seconds=timeout_seconds)
    for spec in specs:
        tool_registry.register(spec, executor)
