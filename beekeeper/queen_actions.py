"""queen_actions.py — Built-in action registry for the Queen.

The Queen can take autonomous actions beyond just delegating to workers:
  - web_search   : search the web and synthesise an answer
  - remember     : persist a memory snippet into the Honeycomb store
  - spawn_worker : dynamically create a new custom worker blueprint
  - run_task     : dispatch a task through the existing worker pipeline
  - summarize    : use the LLM to condense a long text blob

Workflow
--------
1. Queen receives payload with ``queen_actions`` list.
2. ``QueenActionLoop.run()`` iterates through actions in order.
3. Each action can return ``memory_snippets`` → automatically persisted.
4. Aggregated results flow back into ``Queen.run()`` response.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .contracts import (
    AgentBlueprint,
    AbilitiesProfile,
    HumanReviewRecord,
    ProfileBundleRef,
    QueenActionRequest,
    QueenActionResult,
    SkillProfile,
    Status,
    WorkerKind,
)
from .idempotency import stable_idempotency_key


# ---------------------------------------------------------------------------
# Action context — everything an action handler might need
# ---------------------------------------------------------------------------

@dataclass
class ActionContext:
    """Runtime context passed to every action handler."""
    honeycomb_root: Any          # Path
    honeycomb: Any               # HoneycombStore
    worker_runtime: Any          # WorkerRuntime
    registry: Any                # SkillRuleSoulRegistry
    worker_registry: Any         # WorkerRegistry
    llm_router: Any | None = None  # LLMRouter (built lazily)
    trace_id: str = ""
    status_callback: Callable[[str], None] | None = None
    user_policy: Any | None = None  # UserPolicy | None

    def emit(self, msg: str) -> None:
        if self.status_callback:
            try:
                self.status_callback(msg)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------

ActionHandler = Callable[[QueenActionRequest, ActionContext], QueenActionResult]


class QueenActionRegistry:
    """Registry mapping action names to handler callables."""

    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {}

    def register(self, name: str, handler: ActionHandler) -> None:
        self._handlers[name] = handler

    def list_actions(self) -> list[str]:
        return sorted(self._handlers.keys())

    def execute(
        self,
        req: QueenActionRequest,
        ctx: ActionContext,
    ) -> QueenActionResult:
        handler = self._handlers.get(req.action_name)
        if handler is None:
            return QueenActionResult(
                action_name=req.action_name,
                success=False,
                error=f"unknown_action:{req.action_name}",
            )
        try:
            return handler(req, ctx)
        except Exception as exc:  # pragma: no cover
            return QueenActionResult(
                action_name=req.action_name,
                success=False,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Built-in handlers
# ---------------------------------------------------------------------------

def _action_remember(req: QueenActionRequest, ctx: ActionContext) -> QueenActionResult:
    """Persist content to .honeycomb/queen_memories.jsonl."""
    content = str(req.parameters.get("content", "")).strip()
    if not content:
        return QueenActionResult(
            action_name=req.action_name,
            success=False,
            error="remember_action_requires_content_parameter",
        )
    tags = list(req.parameters.get("tags") or [])
    source = str(req.parameters.get("source", "queen_action"))
    ctx.emit(f"Saving memory: {content[:80]}…")
    memory_id = ctx.honeycomb.write_queen_memory(content, source=source, tags=tags)
    return QueenActionResult(
        action_name=req.action_name,
        success=True,
        output={"memory_id": memory_id, "content": content},
    )


def _action_web_search(req: QueenActionRequest, ctx: ActionContext) -> QueenActionResult:
    """Run a web search via SearXNG + LLM synthesis."""
    from .contracts import Status, TaskEnvelope, WorkerKind
    from .worker import WorkerContext, make_worker_identity

    query = str(req.parameters.get("query", "")).strip()
    if not query:
        return QueenActionResult(
            action_name=req.action_name,
            success=False,
            error="web_search_requires_query_parameter",
        )

    ctx.emit(f"Running web search: {query[:80]}…")
    try:
        from uuid import uuid4
        trace_id = req.trace_id or f"action_{uuid4().hex}"
        task = TaskEnvelope(
            queen_trace_id=trace_id,
            queen_request_id=str(uuid4()),
            task_type="research_topic",
            worker_kind=WorkerKind.web_search,
            payload={
                "query": query,
                "use_web_search": bool(req.parameters.get("use_web_search", True)),
                "domains": list(req.parameters.get("domains") or []),
            },
            idempotency_key=stable_idempotency_key(
                "action_web_search",
                {"trace_id": trace_id, "query": query, "domains": list(req.parameters.get("domains") or [])},
            ),
            status=Status.queued,
        )
        # Build a lightweight worker context
        skill = ctx.registry.get_skill("skill.research.web")
        from .registry import SkillRuleSoulRegistry
        resolved = ctx.registry.resolve_profiles("blueprint.queen.default")
        wc = WorkerContext(
            identity=make_worker_identity(
                agent_type="worker.action.web_search",
                skill_profile_id="skill.research.web",
                soul_profile_id=resolved.soul.soul_profile_id,
            ),
            skill=skill,
            rule=resolved.rule,
            soul=resolved.soul,
            abilities=resolved.abilities,
            status_callback=ctx.status_callback,
        )
        result = ctx.worker_runtime.run_once(task, wc)
        output = result.output
        # Extract key snippets for auto-memory
        snippets: list[str] = []
        reply = str(output.get("assistant_reply", "")).strip()
        if reply:
            snippets.append(f"Web search for '{query}': {reply[:300]}")
        return QueenActionResult(
            action_name=req.action_name,
            success=True,
            output=output,
            memory_snippets=snippets,
        )
    except Exception as exc:
        return QueenActionResult(
            action_name=req.action_name,
            success=False,
            error=str(exc),
        )


def _action_spawn_worker(req: QueenActionRequest, ctx: ActionContext) -> QueenActionResult:
    """Dynamically create and register a new custom worker blueprint."""
    name = str(req.parameters.get("name", "")).strip()
    description = str(req.parameters.get("description", "")).strip()
    capabilities: list[str] = list(req.parameters.get("capabilities") or ["custom"])
    intent_patterns: list[str] = list(req.parameters.get("intent_patterns") or [])
    payload_triggers: list[str] = list(req.parameters.get("payload_triggers") or [])

    if not name:
        return QueenActionResult(
            action_name=req.action_name,
            success=False,
            error="spawn_worker_requires_name_parameter",
        )

    ctx.emit(f"Spawning new worker: {name}…")
    try:
        # Register in WorkerRegistry (disk + cache)
        entry = ctx.worker_registry.register_custom_worker(
            worker_kind=f"custom_{name.lower().replace(' ', '_')}",
            name=name,
            description=description or f"Custom worker: {name}",
            capabilities=capabilities,
            intent_patterns=intent_patterns,
            payload_triggers=payload_triggers,
            persist=True,
        )
        worker_kind_str = entry["worker_kind"]

        # Create a matching skill profile
        skill_id = f"skill.custom.{worker_kind_str}"
        skill = SkillProfile(
            skill_profile_id=skill_id,
            name=name,
            description=description or f"Skills for {name}",
            capabilities=capabilities,
            tool_allowlist=[],
            can_search_web="web_search" in capabilities,
            can_execute_code="compute" in capabilities,
        )
        ctx.registry.register_skill(skill)

        # Create a matching agent blueprint
        blueprint_id = f"blueprint.worker.{worker_kind_str}"
        base = ctx.registry.resolve_profiles("blueprint.queen.default")
        blueprint = AgentBlueprint(
            blueprint_id=blueprint_id,
            name=name,
            agent_type="worker",
            worker_kind=WorkerKind.custom,
            profile_bundle=ProfileBundleRef(
                soul_id=base.soul.soul_profile_id,
                abilities_id="abilities.default",
                accountabilities_id="accountability.default",
                rules_id="rule.default",
                guardrails_id="guardrails.default",
                skills_id=skill_id,
            ),
            tags=["worker", "custom", "spawned"],
            is_template=False,
        )
        ctx.registry.register_blueprint(blueprint)

        snippet = f"Spawned new worker '{name}' (kind={worker_kind_str}, capabilities={capabilities})"
        return QueenActionResult(
            action_name=req.action_name,
            success=True,
            output={
                "worker_kind": worker_kind_str,
                "blueprint_id": blueprint_id,
                "skill_id": skill_id,
                "entry": entry,
            },
            memory_snippets=[snippet],
        )
    except Exception as exc:
        return QueenActionResult(
            action_name=req.action_name,
            success=False,
            error=str(exc),
        )


def _action_run_task(req: QueenActionRequest, ctx: ActionContext) -> QueenActionResult:
    """Dispatch a task to a specific worker kind through the worker pipeline."""
    from uuid import uuid4
    from .contracts import Status, TaskEnvelope
    from .worker import WorkerContext, make_worker_identity

    intent = str(req.parameters.get("intent", "research_topic")).strip()
    payload = dict(req.parameters.get("payload") or {})
    worker_kind_str = str(req.parameters.get("worker_kind", "web_search")).strip()

    ctx.emit(f"Running task via worker: intent={intent} worker={worker_kind_str}…")
    try:
        # Resolve worker_kind
        try:
            worker_kind = WorkerKind(worker_kind_str)
        except ValueError:
            worker_kind = WorkerKind.custom

        task = TaskEnvelope(
            queen_trace_id=req.trace_id or f"action_{uuid4().hex}",
            queen_request_id=str(uuid4()),
            task_type=intent,
            worker_kind=worker_kind,
            payload=payload,
            idempotency_key=stable_idempotency_key(
                "action_run_task",
                {
                    "trace_id": req.trace_id or "",
                    "intent": intent,
                    "worker_kind": worker_kind_str,
                    "payload": payload,
                },
            ),
            status=Status.queued,
        )
        # Determine blueprint
        blueprint_id = "blueprint.worker.web"
        if worker_kind == WorkerKind.heavy_compute:
            blueprint_id = "blueprint.worker.heavy"
        elif worker_kind == WorkerKind.audit:
            blueprint_id = "blueprint.worker.audit"
        elif worker_kind == WorkerKind.custom:
            blueprint_id = f"blueprint.worker.custom_{worker_kind_str}"

        try:
            resolved = ctx.registry.resolve_profiles(blueprint_id)
        except KeyError:
            resolved = ctx.registry.resolve_profiles("blueprint.worker.web")

        skill_id = resolved.soul.soul_profile_id.replace("soul.", "skill.")
        try:
            skill = ctx.registry.get_skill(f"skill.research.web")
        except KeyError:
            skill = ctx.registry.get_skill("skill.research.web")

        wc = WorkerContext(
            identity=make_worker_identity(
                agent_type=f"worker.action.{intent}",
                skill_profile_id="skill.research.web",
                soul_profile_id=resolved.soul.soul_profile_id,
            ),
            skill=skill,
            rule=resolved.rule,
            soul=resolved.soul,
            abilities=resolved.abilities,
            status_callback=ctx.status_callback,
        )
        result = ctx.worker_runtime.run_once(task, wc)
        output = result.output
        snippets: list[str] = []
        reply = str(output.get("assistant_reply", "") or output.get("notes", "")).strip()
        if reply:
            snippets.append(f"Task '{intent}': {reply[:300]}")
        return QueenActionResult(
            action_name=req.action_name,
            success=(result.status == Status.success or str(result.status) in ("success", "Status.success")),
            output=output,
            memory_snippets=snippets,
        )
    except Exception as exc:
        return QueenActionResult(
            action_name=req.action_name,
            success=False,
            error=str(exc),
        )


def _action_create_skill(req: QueenActionRequest, ctx: ActionContext) -> QueenActionResult:
    """User-initiated skill creation: build, register, and name a new persistent worker.

    Parameters:
        description (str): Natural language description of what the skill should do.
        name (str, optional): Human-readable name for the skill.
        capabilities (list[str], optional): Capability tags.
        example_queries (list[str], optional): Example queries this skill handles.
    """
    description = str(req.parameters.get("description", "")).strip()
    if not description:
        return QueenActionResult(
            action_name=req.action_name,
            success=False,
            error="create_skill_requires_description_parameter",
        )

    name = str(req.parameters.get("name", "")).strip()
    capabilities: list[str] = list(req.parameters.get("capabilities") or ["custom"])
    example_queries: list[str] = list(req.parameters.get("example_queries") or [])

    # Derive worker_kind and name from description if not provided
    import re
    if not name:
        words = re.sub(r"[^a-z0-9 ]+", " ", description.lower()).split()[:4]
        name = " ".join(words).title()

    worker_kind = f"custom_skill_{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')}"

    ctx.emit(f"Creating skill: {name}…")
    try:
        # Check if already exists
        existing = next(
            (w for w in ctx.worker_registry.list_workers() if w.get("worker_kind") == worker_kind),
            None,
        )
        if existing:
            return QueenActionResult(
                action_name=req.action_name,
                success=True,
                output={
                    "worker_kind": worker_kind,
                    "name": name,
                    "description": description,
                    "created": False,
                    "note": "Skill already exists.",
                    "skill_card": existing,
                },
            )

        # Build intent_patterns from example queries + description keywords
        intent_patterns = [worker_kind]
        query_keywords = [t for t in re.split(r"[^a-z0-9]+", description.lower()) if len(t) > 3][:8]

        entry = ctx.worker_registry.register_custom_worker(
            worker_kind=worker_kind,
            name=name,
            description=description,
            capabilities=capabilities or ["custom"],
            intent_patterns=intent_patterns,
            payload_triggers=[],
            query_keywords=query_keywords,
            priority=15,
            persist=True,
        )

        # Create matching skill + blueprint in registry
        skill_id = f"skill.custom.{worker_kind}"
        skill = SkillProfile(
            skill_profile_id=skill_id,
            name=name,
            description=description,
            capabilities=capabilities,
            tool_allowlist=[],
            can_search_web="search" in description.lower() or "web" in description.lower(),
            can_execute_code="code" in description.lower() or "execute" in description.lower(),
        )
        ctx.registry.register_skill(skill)

        blueprint_id = f"blueprint.worker.{worker_kind}"
        base = ctx.registry.resolve_profiles("blueprint.queen.default")
        blueprint = AgentBlueprint(
            blueprint_id=blueprint_id,
            name=name,
            agent_type="worker",
            worker_kind=WorkerKind.custom,
            profile_bundle=ProfileBundleRef(
                soul_id=base.soul.soul_profile_id,
                abilities_id="abilities.default",
                accountabilities_id="accountability.default",
                rules_id="rule.default",
                guardrails_id="guardrails.default",
                skills_id=skill_id,
            ),
            tags=["worker", "custom", "user_created"],
            is_template=False,
        )
        ctx.registry.register_blueprint(blueprint)

        skill_card = {
            "worker_kind": worker_kind,
            "name": name,
            "description": description,
            "capabilities": capabilities,
            "example_queries": example_queries,
            "blueprint_id": blueprint_id,
            "skill_id": skill_id,
        }
        snippet = f"Created new skill '{name}' (kind={worker_kind}): {description[:200]}"
        return QueenActionResult(
            action_name=req.action_name,
            success=True,
            output={"created": True, "skill_card": skill_card, "entry": entry},
            memory_snippets=[snippet],
        )
    except Exception as exc:
        return QueenActionResult(
            action_name=req.action_name,
            success=False,
            error=str(exc),
        )


def _action_summarize(req: QueenActionRequest, ctx: ActionContext) -> QueenActionResult:
    """Use the LLM to summarise a long text. Writes a memory if save_memory=True."""
    text = str(req.parameters.get("text", "")).strip()
    if not text:
        return QueenActionResult(
            action_name=req.action_name,
            success=False,
            error="summarize_requires_text_parameter",
        )
    ctx.emit("Summarising content with LLM…")
    try:
        prompt = (
            f"Summarise the following in 2-4 concise sentences:\n\n{text[:3000]}"
        )
        reply, _source = ctx.worker_runtime.direct_chat(prompt)
        summary = (reply or "").strip() or text[:300]
        snippets: list[str] = []
        if req.parameters.get("save_memory", False):
            snippets.append(summary)
        return QueenActionResult(
            action_name=req.action_name,
            success=True,
            output={"summary": summary},
            memory_snippets=snippets,
        )
    except Exception as exc:
        return QueenActionResult(
            action_name=req.action_name,
            success=False,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Default registry instance
# ---------------------------------------------------------------------------

def build_default_action_registry() -> QueenActionRegistry:
    """Create and return the default action registry with all built-in actions."""
    reg = QueenActionRegistry()
    reg.register("remember", _action_remember)
    reg.register("web_search", _action_web_search)
    reg.register("spawn_worker", _action_spawn_worker)
    reg.register("create_skill", _action_create_skill)
    reg.register("run_task", _action_run_task)
    reg.register("summarize", _action_summarize)
    return reg


DEFAULT_ACTION_REGISTRY: QueenActionRegistry = build_default_action_registry()


# ---------------------------------------------------------------------------
# Queen Action Loop
# ---------------------------------------------------------------------------

class QueenActionLoop:
    """
    Executes a list of QueenActionRequests in order.

    After each action, auto-persists any memory_snippets to HoneycombStore.
    Returns aggregated results dict suitable for inclusion in Queen.run() output.
    """

    def __init__(
        self,
        ctx: ActionContext,
        registry: QueenActionRegistry | None = None,
    ) -> None:
        self.ctx = ctx
        self.registry = registry or DEFAULT_ACTION_REGISTRY

    def run(
        self,
        actions: list[dict[str, Any]],
        trace_id: str = "",
    ) -> dict[str, Any]:
        """
        Execute actions in order. Returns:
        {
            "action_results": [...],
            "memories_saved": [...],
            "success": bool,
        }
        """
        from .user_policy import policy_allows_action

        results: list[dict[str, Any]] = []
        memories_saved: list[str] = []
        overall_success = True

        for raw in actions:
            action_name = str(raw.get("action", raw.get("action_name", ""))).strip()
            parameters = dict(raw.get("parameters", raw.get("params", {})) or {})

            # Policy gate: check user policy before executing risky actions
            if self.ctx.user_policy is not None:
                allowed, disposition = policy_allows_action(self.ctx.user_policy, action_name)
                if disposition == "deny":
                    self.ctx.emit(f"Action '{action_name}' blocked by user policy.")
                    results.append({
                        "action_name": action_name,
                        "success": False,
                        "error": f"policy_deny:{action_name}",
                        "output": {},
                        "memory_snippets": [],
                    })
                    overall_success = False
                    continue
                if disposition == "ask":
                    # Enqueue HITL review for this action
                    self.ctx.emit(f"Action '{action_name}' requires human approval — queued for review.")
                    from uuid import uuid4
                    review = HumanReviewRecord(
                        task_id=f"action_{uuid4().hex}",
                        trace_id=trace_id or self.ctx.trace_id,
                        task_type=action_name,
                        reason=f"User policy requires approval for action: {action_name}",
                        payload={"action_name": action_name, "parameters": parameters},
                        status="pending",
                    )
                    review_path = self.ctx.honeycomb.human_review_dir / f"{review.review_id}.json"
                    review_path.write_text(
                        __import__("json").dumps(review.model_dump(mode="json"), ensure_ascii=True, indent=2),
                        encoding="utf-8",
                    )
                    self.ctx.honeycomb.write_event(
                        trace_id or self.ctx.trace_id,
                        {
                            "kind": "human_review",
                            "action": "enqueued",
                            "review_id": review.review_id,
                            "task_id": review.task_id,
                            "reason": review.reason,
                        },
                    )
                    results.append({
                        "action_name": action_name,
                        "success": False,
                        "error": f"policy_ask_pending_review:{review.review_id}",
                        "output": {"review_id": review.review_id, "status": "pending"},
                        "memory_snippets": [],
                    })
                    overall_success = False
                    continue

            req = QueenActionRequest(
                action_name=action_name,
                parameters=parameters,
                trace_id=trace_id,
            )
            self.ctx.emit(f"Queen action: {action_name}…")
            result = self.registry.execute(req, self.ctx)
            results.append(result.model_dump(mode="json"))

            if not result.success:
                overall_success = False

            # Auto-persist memory_snippets
            for snippet in result.memory_snippets:
                if snippet.strip():
                    mid = self.ctx.honeycomb.write_queen_memory(
                        snippet,
                        source=f"action:{action_name}",
                        tags=["auto", action_name],
                    )
                    memories_saved.append(mid)

        return {
            "action_results": results,
            "memories_saved": memories_saved,
            "success": overall_success,
        }
