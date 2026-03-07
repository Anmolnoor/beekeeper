"""Adapt existing workers and Queen actions as tools for the model-driven tool runtime."""

from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4

from .contracts import (
    QueenActionRequest,
    Status,
    TaskEnvelope,
    ToolResult,
    ToolSpec,
    TrustTier,
    WorkerKind,
)
from .queen_actions import ActionContext, QueenActionRegistry
from .worker import WorkerContext, make_worker_identity
from .idempotency import stable_idempotency_key


# ---------------------------------------------------------------------------
# ToolSpec definitions for workers
# ---------------------------------------------------------------------------

def _worker_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="web_search",
            description="Search the web and synthesize an answer. Use when the user needs current information, research, or external sources.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query or research question"},
                    "use_web_search": {"type": "boolean", "description": "Whether to use web search (SearXNG)", "default": True},
                    "domains": {"type": "array", "items": {"type": "string"}, "description": "Optional domain allowlist"},
                },
                "required": ["query"],
            },
            trust_tier=TrustTier.medium,
            source="worker",
        ),
        ToolSpec(
            name="heavy_compute",
            description="Run numeric aggregation or analysis on a list of numbers.",
            parameters={
                "type": "object",
                "properties": {
                    "numbers": {"type": "array", "items": {"type": "number"}, "description": "List of numbers to analyze"},
                    "operation": {"type": "string", "description": "Operation name", "default": "distribution_summary"},
                },
                "required": [],
            },
            trust_tier=TrustTier.low,
            source="worker",
        ),
        ToolSpec(
            name="audit",
            description="Audit or validate a prior task result for quality and policy compliance.",
            parameters={
                "type": "object",
                "properties": {
                    "target_task_id": {"type": "string", "description": "Task ID to audit"},
                    "target_result": {"type": "object", "description": "Result payload to validate"},
                },
                "required": ["target_task_id"],
            },
            trust_tier=TrustTier.medium,
            source="worker",
        ),
        ToolSpec(
            name="context_curator",
            description="Curate durable memory from a user message and assistant reply (e.g. after a chat turn).",
            parameters={
                "type": "object",
                "properties": {
                    "user_msg": {"type": "string"},
                    "assistant_reply": {"type": "string"},
                    "user_id": {"type": "string"},
                    "chat_id": {"type": "string"},
                    "honeycomb_root": {"type": "string", "default": ".honeycomb"},
                },
                "required": [],
            },
            trust_tier=TrustTier.medium,
            source="worker",
        ),
        ToolSpec(
            name="forged",
            description="Handle a request with the LLM when no specialist worker matches (generic fallback).",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "User query or task description"},
                    "topic": {"type": "string"},
                },
                "required": ["query"],
            },
            trust_tier=TrustTier.medium,
            source="worker",
        ),
        ToolSpec(
            name="write_file",
            description="Write content to a file on the local filesystem. Creates parent directories automatically. Use when the user wants to save, create, or write to a file.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative or absolute path (e.g. reports/report.md)"},
                    "content": {"type": "string", "description": "Text content to write"},
                    "operation": {"type": "string", "enum": ["write", "append", "mkdir"], "default": "write"},
                    "base_dir": {"type": "string", "description": "Base directory for relative paths, defaults to CWD"},
                },
                "required": ["file_path", "content"],
            },
            trust_tier=TrustTier.medium,
            source="worker",
        ),
        ToolSpec(
            name="read_file",
            description="Read the contents of a local file.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to read"},
                },
                "required": ["file_path"],
            },
            trust_tier=TrustTier.low,
            source="worker",
        ),
    ]


# ---------------------------------------------------------------------------
# ToolSpec definitions for Queen actions
# ---------------------------------------------------------------------------

def _action_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="remember",
            description="Persist a memory snippet to the Queen's memory store.",
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Memory content to save"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "source": {"type": "string", "default": "queen_action"},
                },
                "required": ["content"],
            },
            trust_tier=TrustTier.low,
            source="action",
        ),
        ToolSpec(
            name="queen_web_search",
            description="Run a web search via the Queen action pipeline (same as web_search worker).",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "use_web_search": {"type": "boolean", "default": True},
                    "domains": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["query"],
            },
            trust_tier=TrustTier.medium,
            source="action",
        ),
        ToolSpec(
            name="summarize",
            description="Summarize a long text with the LLM. Optionally save the summary as memory.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to summarize"},
                    "save_memory": {"type": "boolean", "default": False},
                },
                "required": ["text"],
            },
            trust_tier=TrustTier.low,
            source="action",
        ),
        ToolSpec(
            name="spawn_worker",
            description="Dynamically register a new custom worker blueprint.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "capabilities": {"type": "array", "items": {"type": "string"}},
                    "intent_patterns": {"type": "array", "items": {"type": "string"}},
                    "payload_triggers": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name"],
            },
            trust_tier=TrustTier.high,
            source="action",
        ),
        ToolSpec(
            name="run_task",
            description="Dispatch a task to a specific worker kind through the worker pipeline.",
            parameters={
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "default": "research_topic"},
                    "worker_kind": {"type": "string", "default": "web_search"},
                    "payload": {"type": "object"},
                },
                "required": [],
            },
            trust_tier=TrustTier.medium,
            source="action",
        ),
    ]


# ---------------------------------------------------------------------------
# Worker executors: (tool_name, arguments, context) -> ToolResult
# ---------------------------------------------------------------------------

def _make_worker_executor(worker_runtime: Any, honeycomb: Any, registry: Any) -> dict[str, tuple[ToolSpec, Any]]:
    """Build ToolSpec + executor for each worker. context must have trace_id, and may have rule/soul from registry."""
    from .contracts import TaskEnvelope
    from .worker import WorkerContext

    specs = _worker_tool_specs()
    out: dict[str, tuple[ToolSpec, Any]] = {}

    def run_worker(worker_kind: WorkerKind, payload: dict[str, Any], context: dict[str, Any]) -> ToolResult:
        trace_id = context.get("trace_id") or ""
        request_id = str(uuid4())
        task = TaskEnvelope(
            queen_trace_id=trace_id,
            queen_request_id=request_id,
            task_type=payload.get("task_type", "research_topic"),
            worker_kind=worker_kind,
            payload=payload,
            idempotency_key=stable_idempotency_key(
                "tool_run_worker",
                {
                    "trace_id": trace_id,
                    "worker_kind": worker_kind.value,
                    "task_type": payload.get("task_type", "research_topic"),
                    "payload": payload,
                },
            ),
            status=Status.queued,
        )
        blueprint_id = "blueprint.worker.web"
        if worker_kind == WorkerKind.heavy_compute:
            blueprint_id = "blueprint.worker.heavy"
        elif worker_kind == WorkerKind.audit:
            blueprint_id = "blueprint.worker.audit"
        elif worker_kind == WorkerKind.context_curator:
            blueprint_id = "blueprint.worker.context_curator"
        elif worker_kind == WorkerKind.forged:
            blueprint_id = "blueprint.worker.web"
        elif worker_kind == WorkerKind.file_system:
            blueprint_id = "blueprint.worker.web"
        try:
            resolved = registry.resolve_profiles(blueprint_id)
        except Exception:
            resolved = registry.resolve_profiles("blueprint.worker.web")
        skill = registry.get_skill("skill.research.web")
        if worker_kind == WorkerKind.heavy_compute:
            skill = registry.get_skill("skill.compute.heavy") or skill
        if worker_kind == WorkerKind.audit:
            skill = registry.get_skill("skill.monitor.audit") or skill
        if worker_kind == WorkerKind.context_curator:
            skill = registry.get_skill("skill.context.curator") or skill
        wc = WorkerContext(
            identity=make_worker_identity("worker.tool", skill.skill_profile_id, resolved.soul.soul_profile_id),
            skill=skill,
            rule=resolved.rule,
            soul=resolved.soul,
            abilities=resolved.abilities,
            status_callback=context.get("status_callback"),
        )
        result = worker_runtime.run_once(task, wc)
        return ToolResult(
            call_id=context.get("call_id", ""),
            tool_name=result.worker_kind.value if hasattr(result.worker_kind, "value") else str(result.worker_kind),
            success=result.status == Status.success,
            output=result.output,
            error=None if result.status == Status.success else str(result.output.get("error", result.status)),
            cost_metrics=result.cost_metrics,
        )

    for spec in specs:
        if spec.name == "web_search":
            def _web(tn: str, args: dict, ctx: dict) -> ToolResult:
                args["task_type"] = "research_topic"
                args["use_web_search"] = args.get("use_web_search", True)
                return run_worker(WorkerKind.web_search, args, ctx)
            out[spec.name] = (spec, _web)
        elif spec.name == "heavy_compute":
            def _heavy(tn: str, args: dict, ctx: dict) -> ToolResult:
                args["task_type"] = "heavy_compute"
                return run_worker(WorkerKind.heavy_compute, args, ctx)
            out[spec.name] = (spec, _heavy)
        elif spec.name == "audit":
            def _audit(tn: str, args: dict, ctx: dict) -> ToolResult:
                args["task_type"] = "audit_result"
                return run_worker(WorkerKind.audit, args, ctx)
            out[spec.name] = (spec, _audit)
        elif spec.name == "context_curator":
            def _curator(tn: str, args: dict, ctx: dict) -> ToolResult:
                args["task_type"] = "context_curation"
                args["honeycomb_root"] = args.get("honeycomb_root", ".honeycomb")
                return run_worker(WorkerKind.context_curator, args, ctx)
            out[spec.name] = (spec, _curator)
        elif spec.name == "forged":
            def _forged(tn: str, args: dict, ctx: dict) -> ToolResult:
                args["task_type"] = args.get("query", args.get("topic", "research_topic"))
                args["query"] = args.get("query") or args.get("topic", "")
                return run_worker(WorkerKind.forged, args, ctx)
            out[spec.name] = (spec, _forged)
        elif spec.name == "write_file":
            def _write(tn: str, args: dict, ctx: dict) -> ToolResult:
                args["task_type"] = "file_write"
                args["operation"] = args.get("operation", "write")
                return run_worker(WorkerKind.file_system, args, ctx)
            out[spec.name] = (spec, _write)
        elif spec.name == "read_file":
            def _read(tn: str, args: dict, ctx: dict) -> ToolResult:
                args["task_type"] = "file_read"
                args["operation"] = "read"
                return run_worker(WorkerKind.file_system, args, ctx)
            out[spec.name] = (spec, _read)
    return out


def _make_action_executor(
    action_registry: QueenActionRegistry,
    action_context_factory: Callable[[], ActionContext],
) -> dict[str, tuple[ToolSpec, Any]]:
    """Build ToolSpec + executor for each Queen action."""
    from .contracts import QueenActionRequest

    specs = _action_tool_specs()
    out: dict[str, tuple[ToolSpec, Any]] = {}
    name_to_action: dict[str, str] = {
        "remember": "remember",
        "queen_web_search": "web_search",
        "summarize": "summarize",
        "spawn_worker": "spawn_worker",
        "run_task": "run_task",
    }

    def run_action(tool_name: str, action_name: str, args: dict, ctx: dict) -> ToolResult:
        trace_id = ctx.get("trace_id", "")
        req = QueenActionRequest(action_name=action_name, parameters=args, trace_id=trace_id)
        actx = action_context_factory()
        actx.trace_id = trace_id
        result = action_registry.execute(req, actx)
        return ToolResult(
            call_id=ctx.get("call_id", ""),
            tool_name=tool_name,
            success=result.success,
            output=result.output,
            error=result.error,
        )

    for spec in specs:
        action_name = name_to_action.get(spec.name, spec.name)
        if action_name not in action_registry._handlers:
            continue

        def _exec(tn: str, args: dict, context: dict, _an: str = action_name) -> ToolResult:
            return run_action(tn, _an, args, context)

        out[spec.name] = (spec, _exec)
    return out


def register_worker_tools(
    tool_registry: Any,
    worker_runtime: Any,
    honeycomb: Any,
    profile_registry: Any,
) -> None:
    """Register all worker-backed tools on the given ToolRegistry."""
    from .tool_runtime import ToolRegistry
    if not isinstance(tool_registry, ToolRegistry):
        return
    for spec, executor in _make_worker_executor(worker_runtime, honeycomb, profile_registry).values():
        tool_registry.register(spec, executor)


def register_action_tools(
    tool_registry: Any,
    action_registry: QueenActionRegistry,
    action_context_factory: Callable[[], ActionContext],
) -> None:
    """Register all Queen-action-backed tools on the given ToolRegistry."""
    from .tool_runtime import ToolRegistry
    if not isinstance(tool_registry, ToolRegistry):
        return
    for spec, executor in _make_action_executor(action_registry, action_context_factory).items():
        tool_registry.register(spec, executor)


def build_tool_registry_from_queen(
    worker_runtime: Any,
    honeycomb: Any,
    profile_registry: Any,
    action_registry: QueenActionRegistry,
    action_context_factory: Callable[[], ActionContext],
) -> Any:
    """Build a ToolRegistry with all worker and action tools registered."""
    from .tool_runtime import ToolRegistry
    reg = ToolRegistry()
    register_worker_tools(reg, worker_runtime, honeycomb, profile_registry)
    register_action_tools(reg, action_registry, action_context_factory)
    return reg
