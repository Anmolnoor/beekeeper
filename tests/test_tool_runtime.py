"""Tests for model-driven tool runtime: ToolRegistry, ToolExecutor, ToolLoopEngine and tool-call guardrails."""

import pytest

from beekeeper.contracts import RuleProfile, ToolCall, ToolExecutionPolicy, ToolResult, ToolSpec, TrustTier
from beekeeper.guardrails import evaluate_tool_call
from beekeeper.tool_runtime import ToolExecutor, ToolLoopEngine, ToolRegistry


def test_tool_registry_register_and_list() -> None:
    reg = ToolRegistry()
    spec = ToolSpec(name="echo", description="Echo back", parameters={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]})
    reg.register(spec, lambda tn, args, ctx: ToolResult(call_id=ctx.get("call_id", ""), tool_name=tn, success=True, output=args))
    assert reg.get("echo") == spec
    assert reg.list_tool_names() == ["echo"]
    openai_tools = reg.get_openai_compatible_tools()
    assert len(openai_tools) == 1
    assert openai_tools[0]["type"] == "function"
    assert openai_tools[0]["function"]["name"] == "echo"


def test_tool_executor_unknown_tool() -> None:
    reg = ToolRegistry()
    reg.register(ToolSpec(name="a", description="A", parameters={}))
    policy = ToolExecutionPolicy(disallowed_tools=[], allowed_tools=None)
    executor = ToolExecutor(reg, honeycomb=None, policy=policy)
    call = ToolCall(tool_name="nonexistent", arguments={})
    result = executor.execute(call, {}, trace_id="t1")
    assert result.success is False
    assert "unknown_tool" in (result.error or "")


def test_tool_executor_disallowed_by_policy() -> None:
    reg = ToolRegistry()
    spec = ToolSpec(name="danger", description="D", parameters={})
    reg.register(spec, lambda tn, args, ctx: ToolResult(call_id=ctx.get("call_id"), tool_name=tn, success=True, output={}))
    policy = ToolExecutionPolicy(disallowed_tools=["danger"])
    executor = ToolExecutor(reg, honeycomb=None, policy=policy)
    call = ToolCall(tool_name="danger", arguments={})
    result = executor.execute(call, {}, trace_id="t1")
    assert result.success is False
    assert "disallowed" in (result.error or "")


def test_tool_executor_schema_validation_missing_required() -> None:
    reg = ToolRegistry()
    spec = ToolSpec(
        name="need_x",
        description="Requires x",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
    )
    reg.register(spec, lambda tn, args, ctx: ToolResult(call_id=ctx.get("call_id", ""), tool_name=tn, success=True, output=args))
    executor = ToolExecutor(reg, honeycomb=None, policy=ToolExecutionPolicy())
    call = ToolCall(tool_name="need_x", arguments={})
    result = executor.execute(call, {}, trace_id="t1")
    assert result.success is False
    assert "Missing required" in (result.error or "")
    assert "validation_failed" in (result.policy_flags or [])


def test_tool_loop_engine_terminates_on_final_text() -> None:
    reg = ToolRegistry()
    spec = ToolSpec(name="nop", description="Nop", parameters={})
    reg.register(spec, lambda tn, args, ctx: ToolResult(call_id=ctx.get("call_id", ""), tool_name=tn, success=True, output={}))
    executor = ToolExecutor(reg, honeycomb=None, policy=ToolExecutionPolicy())
    engine = ToolLoopEngine(executor, max_steps=3)

    def decision_fn(messages: list, tool_schemas: list) -> dict:
        return {"tool_calls": [], "final_text": "Done.", "error": None}

    final = engine.run("trace_1", [{"role": "user", "content": "Hi"}], decision_fn=decision_fn, context={})
    assert final.final_text == "Done."
    assert final.status == "success"
    assert final.step_count == 1


def test_tool_loop_engine_max_steps() -> None:
    """Loop terminates after max_steps when model keeps requesting tools."""
    reg = ToolRegistry()
    spec = ToolSpec(name="counter", description="Count", parameters={})
    call_count = 0

    def count_exec(tn, args, ctx):
        nonlocal call_count
        call_count += 1
        return ToolResult(call_id=ctx.get("call_id", ""), tool_name=tn, success=True, output={"n": call_count})

    reg.register(spec, count_exec)
    executor = ToolExecutor(reg, honeycomb=None, policy=ToolExecutionPolicy(max_steps=2))
    engine = ToolLoopEngine(executor, max_steps=2)

    def decision_fn(messages: list, tool_schemas: list) -> dict:
        # Always return a tool call, no final_text
        return {"tool_calls": [{"name": "counter", "arguments": {}}], "final_text": None, "error": None}

    final = engine.run("trace_max", [{"role": "user", "content": "Go"}], decision_fn=decision_fn, context={})
    assert final.status == "partial"
    assert final.final_text == "Max steps reached."
    assert final.step_count == 2


# ---------------------------------------------------------------------------
# Tool-call guardrails (evaluate_tool_call)
# ---------------------------------------------------------------------------

def _rule(disallowed_tools=None, require_human_approval_for=None, allowed_domains=None):
    return RuleProfile(
        rule_profile_id="rule.test",
        name="Test",
        disallowed_tools=disallowed_tools or [],
        require_human_approval_for=require_human_approval_for or [],
        allowed_domains=allowed_domains or [],
    )


def test_evaluate_tool_call_disallowed() -> None:
    rule = _rule(disallowed_tools=["danger_tool"])
    allowed, reason, needs_human = evaluate_tool_call("danger_tool", {}, rule)
    assert allowed is False
    assert reason == "tool_disallowed_by_rule"
    assert needs_human is False


def test_evaluate_tool_call_needs_human() -> None:
    rule = _rule(require_human_approval_for=["spawn_worker"])
    allowed, reason, needs_human = evaluate_tool_call("spawn_worker", {"name": "x"}, rule)
    assert allowed is True
    assert reason is None
    assert needs_human is True


def test_evaluate_tool_call_pii_block() -> None:
    rule = _rule()
    allowed, reason, _ = evaluate_tool_call("web_search", {"query": "email me at user@example.com"}, rule)
    assert allowed is False
    assert "pii" in (reason or "").lower()


def test_evaluate_tool_call_domain_not_allowed() -> None:
    rule = _rule(allowed_domains=["docs.python.org", "github.com"])
    allowed, reason, _ = evaluate_tool_call("web_search", {"query": "x", "domains": ["evil.com"]}, rule)
    assert allowed is False
    assert reason == "domain_not_allowed"


def test_evaluate_tool_call_domain_allowed() -> None:
    rule = _rule(allowed_domains=["docs.python.org"])
    allowed, reason, _ = evaluate_tool_call("web_search", {"query": "x", "domains": ["docs.python.org"]}, rule)
    assert allowed is True
    assert reason is None
