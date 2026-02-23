from __future__ import annotations

import hashlib
import os
import time
from asyncio import run as asyncio_run
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .contracts import (
    AbilitiesProfile,
    AccountabilityPolicy,
    AgentBlueprint,
    CostMetrics,
    GuardrailProfile,
    ProfileBundleRef,
    PolicyDecision,
    ResultEnvelope,
    RetryCategory,
    RuleProfile,
    SkillProfile,
    SoulProfile,
    Status,
    TaskEnvelope,
    WorkerPerformanceRecord,
    WorkerKind,
)
from .plugins import load_guardrail_plugins
from .guardrails import (
    AuditPayloadGuardrail,
    GuardrailPolicyEngine,
    HeavyComputeBudgetGuardrail,
    JailbreakGuardrail,
    PIIGuardrail,
    SchemaGuardrail,
    WebDomainGuardrail,
)
from .honeycomb import HoneycombConfig, HoneycombStore
from .monitor import SentinelMonitor
from .registry import SkillRuleSoulRegistry
from .scheduler import (
    CeleryScheduler,
    InlineScheduler,
    RoutingFeedbackOptimizer,
    Scheduler,
    classify_retry_category,
    retry_backoff_seconds,
)
from .soul import load_queen_soul
from .audit_logger import log_service_call
from .temporal_integration import TEMPORAL_AVAILABLE, TemporalBeekeeperClient, TemporalConfig
from .tracing import Tracer
from .worker import WorkerContext, WorkerRuntime, execute_task_serialized, make_worker_identity
from .worker_registry import WorkerRegistry
from .queen_context import ensure_queen_context_file, load_queen_context, render_queen_context
from .skill_loader import load_skills_from_md
from .autonomy import AutonomyPolicy, DEFAULT_AUTONOMY_POLICY
from .queen_updates import write_queen_update
from .queen_actions import ActionContext, QueenActionLoop, build_default_action_registry


@dataclass
class QueenConfig:
    honeycomb_root: Path
    max_reruns: int = 1
    scheduler_backend: str = "inline"  # inline | celery | temporal
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_backend_url: str = "redis://localhost:6379/1"
    scheduler_timeout_seconds: int = 60
    temporal_endpoint: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "beekeeper-queue"
    vector_backend: str = "memory"  # memory | qdrant
    vector_collection: str = "honeycomb_memory"
    vector_url: str = "http://localhost:6333"
    queen_soul_profile_id: str = "soul.queen.crown"
    llm_provider: str = field(default_factory=lambda: os.getenv("BEEKEEPER_LLM_PROVIDER", "ollama"))
    llm_providers: str = field(default_factory=lambda: os.getenv("BEEKEEPER_LLM_PROVIDERS", ""))
    ollama_base_url: str = field(default_factory=lambda: os.getenv("BEEKEEPER_OLLAMA_BASE_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("BEEKEEPER_OLLAMA_MODEL", "llama3.2"))
    ollama_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("BEEKEEPER_OLLAMA_TIMEOUT_SECONDS", "120")))
    gemini_api_key: str = field(default_factory=lambda: os.getenv("BEEKEEPER_GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("BEEKEEPER_GEMINI_MODEL", "gemini-1.5-flash"))
    gemini_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("BEEKEEPER_GEMINI_TIMEOUT_SECONDS", "120")))
    openai_api_key: str = field(default_factory=lambda: os.getenv("BEEKEEPER_OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.getenv("BEEKEEPER_OPENAI_MODEL", "gpt-4o-mini"))
    openai_base_url: str | None = field(default_factory=lambda: os.getenv("BEEKEEPER_OPENAI_BASE_URL") or None)
    openai_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("BEEKEEPER_OPENAI_TIMEOUT_SECONDS", "120")))
    searxng_base_url: str = field(default_factory=lambda: os.getenv("BEEKEEPER_SEARXNG_BASE_URL", "http://localhost:8080"))
    auto_approve_human_reviews: bool = False
    queen_blueprint_id: str = "blueprint.queen.default"
    worker_web_blueprint_id: str = "blueprint.worker.web"
    worker_heavy_blueprint_id: str = "blueprint.worker.heavy"
    worker_audit_blueprint_id: str = "blueprint.worker.audit"
    autonomy_policy: AutonomyPolicy | None = None


class QueenAgent:
    def __init__(self, config: QueenConfig) -> None:
        self.config = config
        self.registry = SkillRuleSoulRegistry()
        self.tracer = Tracer()
        self.honeycomb = HoneycombStore(
            HoneycombConfig(
                root_dir=config.honeycomb_root,
                vector_backend=config.vector_backend,
                vector_collection=config.vector_collection,
                vector_url=config.vector_url,
            )
        )
        builtin_guardrails: list[Any] = [
            SchemaGuardrail(),
            PIIGuardrail(),
            JailbreakGuardrail(),
            WebDomainGuardrail(),
            HeavyComputeBudgetGuardrail(),
            AuditPayloadGuardrail(),
        ]
        plugin_guardrails = load_guardrail_plugins(config.honeycomb_root)
        self.guardrail_engine = GuardrailPolicyEngine(builtin_guardrails + plugin_guardrails)
        self.worker_runtime = WorkerRuntime(
            self.honeycomb,
            self.tracer,
            llm_provider=self.config.llm_provider,
            llm_providers=self.config.llm_providers or None,
            ollama_base_url=self.config.ollama_base_url,
            ollama_model=self.config.ollama_model,
            ollama_timeout_seconds=self.config.ollama_timeout_seconds,
            gemini_api_key=self.config.gemini_api_key,
            gemini_model=self.config.gemini_model,
            gemini_timeout_seconds=self.config.gemini_timeout_seconds,
            openai_api_key=self.config.openai_api_key,
            openai_model=self.config.openai_model,
            openai_base_url=self.config.openai_base_url,
            openai_timeout_seconds=self.config.openai_timeout_seconds,
            searxng_base_url=self.config.searxng_base_url,
        )
        self.monitor = SentinelMonitor(min_confidence=0.65)
        self.routing_optimizer = RoutingFeedbackOptimizer()
        self.scheduler = self._build_scheduler()
        self.worker_registry = WorkerRegistry(config.honeycomb_root)
        self.worker_registry.ensure_registry_file()
        ensure_queen_context_file(config.honeycomb_root)
        self._seed_defaults()
        queen_blueprint = self.registry.get_blueprint(self.config.queen_blueprint_id)
        queen_profiles = self.registry.resolve_profiles(queen_blueprint.blueprint_id)
        self.queen_soul = queen_profiles.soul
        self.autonomy_policy = self.config.autonomy_policy or DEFAULT_AUTONOMY_POLICY
        self._action_registry = build_default_action_registry()

    def _build_scheduler(self) -> Scheduler | None:
        if self.config.scheduler_backend == "celery":
            os.environ.setdefault("BEEKEEPER_CELERY_BROKER_URL", self.config.celery_broker_url)
            os.environ.setdefault("BEEKEEPER_CELERY_BACKEND_URL", self.config.celery_backend_url)
            os.environ.setdefault("BEEKEEPER_HONEYCOMB_ROOT", str(self.config.honeycomb_root.resolve()))
            os.environ.setdefault("BEEKEEPER_VECTOR_BACKEND", self.config.vector_backend)
            os.environ.setdefault("BEEKEEPER_VECTOR_COLLECTION", self.config.vector_collection)
            os.environ.setdefault("BEEKEEPER_VECTOR_URL", self.config.vector_url)
            os.environ.setdefault("BEEKEEPER_LLM_PROVIDER", self.config.llm_provider)
            if self.config.llm_providers:
                os.environ.setdefault("BEEKEEPER_LLM_PROVIDERS", self.config.llm_providers)
            os.environ.setdefault("BEEKEEPER_OLLAMA_BASE_URL", self.config.ollama_base_url)
            os.environ.setdefault("BEEKEEPER_OLLAMA_MODEL", self.config.ollama_model)
            os.environ.setdefault("BEEKEEPER_OLLAMA_TIMEOUT_SECONDS", str(self.config.ollama_timeout_seconds))
            os.environ.setdefault("BEEKEEPER_GEMINI_API_KEY", self.config.gemini_api_key)
            os.environ.setdefault("BEEKEEPER_GEMINI_MODEL", self.config.gemini_model)
            os.environ.setdefault("BEEKEEPER_GEMINI_TIMEOUT_SECONDS", str(self.config.gemini_timeout_seconds))
            os.environ.setdefault("BEEKEEPER_SEARXNG_BASE_URL", self.config.searxng_base_url)
            return CeleryScheduler(
                broker_url=self.config.celery_broker_url,
                backend_url=self.config.celery_backend_url,
            )
        if self.config.scheduler_backend == "inline":
            return InlineScheduler(
                handler=lambda task_payload, context_payload: execute_task_serialized(
                    task_payload=task_payload,
                    context_payload=context_payload,
                    honeycomb_root=str(self.config.honeycomb_root.resolve()),
                    vector_backend=self.config.vector_backend,
                    vector_collection=self.config.vector_collection,
                    vector_url=self.config.vector_url,
                    llm_provider=self.config.llm_provider,
                    llm_providers=self.config.llm_providers or None,
                    ollama_base_url=self.config.ollama_base_url,
                    ollama_model=self.config.ollama_model,
                    ollama_timeout_seconds=self.config.ollama_timeout_seconds,
                    gemini_api_key=self.config.gemini_api_key,
                    gemini_model=self.config.gemini_model,
                    gemini_timeout_seconds=self.config.gemini_timeout_seconds,
                    searxng_base_url=self.config.searxng_base_url,
                )
            )
        return None

    def _seed_defaults(self) -> None:
        self.registry.register_skill(
            SkillProfile(
                skill_profile_id="skill.research.web",
                name="Web Research",
                description="Searches the web, gathers evidence, and synthesizes answers. Use when user query needs web lookup, external sources, or research.",
                when_to_use="use_web_search in payload, query mentions research/lookup/find, domains specified",
                tool_allowlist=["web_search", "summarize", "report_writer"],
                capabilities=["web_search", "fact_synthesis"],
                can_search_web=True,
                can_execute_code=False,
                max_parallel_tools=3,
            )
        )
        self.registry.register_skill(
            SkillProfile(
                skill_profile_id="skill.monitor.audit",
                name="Audit Monitoring",
                description="Reviews and validates worker outputs for quality and policy compliance. Use when governance or audit is required.",
                when_to_use="audit_result intent, governance task, quality validation",
                tool_allowlist=["trace_reader", "anomaly_detector"],
                capabilities=["audit", "monitoring"],
                can_search_web=False,
                can_execute_code=False,
                max_parallel_tools=1,
            )
        )
        self.registry.register_skill(
            SkillProfile(
                skill_profile_id="skill.compute.heavy",
                name="Heavy Compute",
                description="Executes numeric aggregation, simulations, and bounded high-compute tasks. Use when payload has numbers or operation.",
                when_to_use="numbers in payload, operation field, heavy_compute intent",
                tool_allowlist=["python_compute", "numeric_aggregator"],
                capabilities=["compute", "analysis"],
                can_search_web=False,
                can_execute_code=True,
                max_parallel_tools=1,
            )
        )
        self.registry.register_rule(
            RuleProfile(
                rule_profile_id="rule.default",
                name="Default Safety Rule",
                hard_budget_usd=2.0,
                max_runtime_seconds=120,
                max_retries=2,
                allowed_domains=["docs.python.org", "openai.com", "github.com"],
                disallowed_tools=["shell_exec_unscoped"],
                require_human_approval_for=["data_delete", "payment_action"],
            )
        )
        self.registry.register_soul(
            SoulProfile(
                soul_profile_id="soul.balanced",
                name="Balanced Persona",
                tone="neutral",
                risk_appetite="balanced",
                verbosity="medium",
                escalation_style="balanced",
                traits={"collaboration": "high", "assertiveness": "medium"},
            )
        )
        self.registry.register_soul(load_queen_soul(self.config.honeycomb_root))
        for skill in load_skills_from_md(self.config.honeycomb_root):
            self.registry.register_skill(skill)
        self.registry.register_abilities(
            AbilitiesProfile(
                abilities_profile_id="abilities.default",
                name="Default abilities",
                capabilities=["web_search", "fact_synthesis", "compute", "audit"],
                tool_allowlist=["web_search", "summarize", "numeric_aggregator", "trace_reader"],
                max_parallel_tools=3,
            )
        )
        self.registry.register_accountability(
            AccountabilityPolicy(
                accountability_id="accountability.default",
                name="Default accountability",
                owner="platform",
                must_emit_audit_log=True,
                max_unapproved_actions=0,
                requires_trace_for_all_actions=True,
            )
        )
        self.registry.register_guardrail_profile(
            GuardrailProfile(
                guardrail_profile_id="guardrails.default",
                name="Default guardrails",
                enabled_guardrails=[
                    "schema",
                    "pii",
                    "jailbreak",
                    "web_domain",
                    "heavy_budget",
                    "audit_payload",
                ],
                allow_external_network=True,
                enforce_domain_allowlist=True,
            )
        )
        self.registry.register_blueprint(
            AgentBlueprint(
                blueprint_id="blueprint.queen.default",
                name="Default Queen",
                agent_type="queen",
                profile_bundle=ProfileBundleRef(
                    soul_id=self.config.queen_soul_profile_id,
                    abilities_id="abilities.default",
                    accountabilities_id="accountability.default",
                    rules_id="rule.default",
                    guardrails_id="guardrails.default",
                    skills_id="skill.research.web",
                ),
                tags=["queen", "default"],
                is_template=True,
            )
        )
        self.registry.register_blueprint(
            AgentBlueprint(
                blueprint_id="blueprint.worker.web",
                name="Web Worker",
                agent_type="worker",
                worker_kind=WorkerKind.web_search,
                profile_bundle=ProfileBundleRef(
                    soul_id="soul.balanced",
                    abilities_id="abilities.default",
                    accountabilities_id="accountability.default",
                    rules_id="rule.default",
                    guardrails_id="guardrails.default",
                    skills_id="skill.research.web",
                ),
                tags=["worker", "web"],
                is_template=True,
            )
        )
        self.registry.register_blueprint(
            AgentBlueprint(
                blueprint_id="blueprint.worker.heavy",
                name="Heavy Worker",
                agent_type="worker",
                worker_kind=WorkerKind.heavy_compute,
                profile_bundle=ProfileBundleRef(
                    soul_id="soul.balanced",
                    abilities_id="abilities.default",
                    accountabilities_id="accountability.default",
                    rules_id="rule.default",
                    guardrails_id="guardrails.default",
                    skills_id="skill.compute.heavy",
                ),
                tags=["worker", "heavy"],
                is_template=True,
            )
        )
        self.registry.register_blueprint(
            AgentBlueprint(
                blueprint_id="blueprint.worker.audit",
                name="Audit Worker",
                agent_type="worker",
                worker_kind=WorkerKind.audit,
                profile_bundle=ProfileBundleRef(
                    soul_id="soul.balanced",
                    abilities_id="abilities.default",
                    accountabilities_id="accountability.default",
                    rules_id="rule.default",
                    guardrails_id="guardrails.default",
                    skills_id="skill.monitor.audit",
                ),
                tags=["worker", "audit"],
                is_template=True,
            )
        )

    def _idempotency_key(self, queen_request_id: str, task_type: str, payload: dict[str, Any]) -> str:
        raw = f"{queen_request_id}:{task_type}:{sorted(payload.items())}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def decompose_intent(
        self, queen_trace_id: str, queen_request_id: str, intent: str, payload: dict[str, Any]
    ) -> list[TaskEnvelope]:
        tasks: list[TaskEnvelope] = []
        min_conf = float(self.queen_soul.traits.get("escalation_thresholds", {}).get("min_confidence_before_autorelease", 0.75))
        worker_kind = self._route_worker_kind(intent, payload)
        required_skills = ["web_search"]
        if worker_kind == WorkerKind.heavy_compute:
            required_skills = ["compute"]
        if worker_kind == WorkerKind.audit:
            required_skills = ["audit"]
        primary_task = TaskEnvelope(
            queen_trace_id=queen_trace_id,
            queen_request_id=queen_request_id,
            task_type=intent,
            worker_kind=worker_kind,
            payload=payload,
            required_skills=required_skills,
            budget_usd=0.5,
            max_retries=2,
            idempotency_key=self._idempotency_key(queen_request_id, intent, payload),
            status=Status.queued,
        )
        tasks.append(primary_task)

        # Queen soul controls governance strictness: strict souls always add audit tasks.
        if self.queen_soul.escalation_style == "strict" or min_conf >= 0.7:
            audit_task = TaskEnvelope(
                queen_trace_id=queen_trace_id,
                queen_request_id=queen_request_id,
                parent_id=primary_task.task_id,
                task_type="audit_result",
                worker_kind=WorkerKind.audit,
                payload={"target_task_id": primary_task.task_id},
                required_skills=["audit"],
                budget_usd=0.1,
                max_retries=1,
                idempotency_key=self._idempotency_key(queen_request_id, "audit_result", {"target": primary_task.task_id}),
                status=Status.queued,
            )
            tasks.append(audit_task)
        return tasks

    def _route_skill(self, task: TaskEnvelope) -> str:
        if "audit" in task.required_skills:
            return "skill.monitor.audit"
        if task.worker_kind == WorkerKind.heavy_compute:
            return "skill.compute.heavy"
        if task.worker_kind == WorkerKind.forged:
            return "skill.research.web"
        return "skill.research.web"

    def _auto_spawn_worker(self, intent: str, payload: dict[str, Any]) -> None:
        """Register a new custom worker blueprint when no content match exists for this intent.
        The spawned worker uses ForgedWorker (LLM) for execution but is persisted to the registry
        so future requests with the same intent pattern are correctly routed.
        """
        worker_kind_str = f"custom_{intent.lower().replace(' ', '_').replace('-', '_')}"
        # Check if already registered (avoid duplicate spawning)
        existing = next(
            (w for w in self.worker_registry.list_workers() if w.get("worker_kind") == worker_kind_str),
            None,
        )
        if existing:
            return
        name = intent.replace("_", " ").replace("-", " ").title()
        query_hint = str(payload.get("query") or payload.get("topic") or "").strip()
        keywords = [w for w in query_hint.lower().split() if len(w) > 3][:5] if query_hint else []
        self.worker_registry.register_custom_worker(
            worker_kind=worker_kind_str,
            name=name,
            description=f"Auto-spawned worker for intent: {intent}",
            capabilities=["custom"],
            intent_patterns=[intent],
            payload_triggers=[],
            query_keywords=keywords,
            priority=15,
            persist=True,
        )
        skill_id = f"skill.custom.{worker_kind_str}"
        self.registry.register_skill(
            SkillProfile(
                skill_profile_id=skill_id,
                name=name,
                description=f"Skills for auto-spawned worker: {intent}",
                capabilities=["custom"],
                tool_allowlist=[],
                can_search_web=False,
                can_execute_code=False,
            )
        )
        base = self.registry.resolve_profiles("blueprint.queen.default")
        self.registry.register_blueprint(
            AgentBlueprint(
                blueprint_id=f"blueprint.worker.{worker_kind_str}",
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
                tags=["worker", "auto_spawned"],
                is_template=False,
            )
        )

    def _route_worker_kind(self, intent: str, payload: dict[str, Any]) -> WorkerKind:
        query = str(payload.get("query") or payload.get("topic") or "").strip()
        worker_kind, _fallbacks, best_score, content_score = self.worker_registry.select_worker_with_metadata(
            intent, payload, query
        )
        if content_score == 0:
            # No intent/payload/keyword matched — auto-spawn a worker for this intent and use ForgedWorker now
            self._auto_spawn_worker(intent, payload)
            return WorkerKind.forged
        feedback = self.honeycomb.read_routing_feedback()
        if feedback and worker_kind in {WorkerKind.web_search, WorkerKind.heavy_compute}:
            required_skill = "skill.compute.heavy" if worker_kind == WorkerKind.heavy_compute else "skill.research.web"
            risk_action = str(payload.get("action", "")).strip()
            requested_budget = float(payload.get("budget_usd", 0.5))
            best_kind = worker_kind
            best_score = -1.0
            for entry in feedback.values():
                if entry.worker_kind not in {WorkerKind.web_search, WorkerKind.heavy_compute}:
                    continue
                base = self.routing_optimizer.score(
                    quality=entry.avg_quality,
                    latency_ms=entry.avg_latency_ms,
                    cost_usd=entry.avg_cost_usd,
                )
                intent_bucket = entry.by_intent.get(intent, {})
                intent_quality = float(intent_bucket.get("avg_quality", entry.avg_quality))
                skill_bucket = entry.by_skill.get(required_skill, {})
                skill_quality = float(skill_bucket.get("avg_quality", entry.avg_quality))
                score = (0.55 * base) + (0.2 * entry.recent_quality_ema) + (0.15 * intent_quality) + (0.1 * skill_quality)
                if requested_budget <= 0.2 and entry.avg_cost_usd > requested_budget:
                    score -= 0.1
                if risk_action in {"data_delete", "payment_action"} and entry.worker_kind == WorkerKind.heavy_compute:
                    score -= 0.1
                if score > best_score:
                    best_score = score
                    best_kind = entry.worker_kind
            return best_kind
        return worker_kind

    def _build_worker_context(
        self, task: TaskEnvelope, status_callback: Callable[[str], None] | None = None
    ) -> WorkerContext:
        skill_id = self._route_skill(task)
        blueprint_id = self.config.worker_web_blueprint_id
        if task.worker_kind == WorkerKind.heavy_compute:
            blueprint_id = self.config.worker_heavy_blueprint_id
        elif task.worker_kind == WorkerKind.audit:
            blueprint_id = self.config.worker_audit_blueprint_id
        elif task.worker_kind == WorkerKind.forged:
            blueprint_id = self.config.worker_web_blueprint_id
        resolved = self.registry.resolve_profiles(blueprint_id)
        worker_id = make_worker_identity(
            agent_type=f"worker.{task.task_type}",
            skill_profile_id=skill_id,
            soul_profile_id=resolved.soul.soul_profile_id,
        )
        return WorkerContext(
            identity=worker_id,
            skill=self.registry.get_skill(skill_id),
            rule=resolved.rule,
            soul=resolved.soul,
            abilities=resolved.abilities,
            accountability=resolved.accountability,
            guardrails=resolved.guardrails,
            status_callback=status_callback,
        )

    def _resolve_human_approval(self, task: TaskEnvelope, policy: PolicyDecision) -> PolicyDecision:
        if policy.status != "needs_human":
            return policy
        review_id = str(task.payload.get("human_review_id", "")).strip()
        if review_id:
            review = self.honeycomb.get_review(review_id)
            if review is not None and review.status == "approved":
                return PolicyDecision(
                    task_id=task.task_id,
                    status="approve",
                    reason="human_approval_granted_from_queue",
                    guardrail_flags=[],
                    approved_by=str(review.resolved_by or "operator"),
                    approved_at=review.resolved_at or policy.created_at,
                )
            if review is not None and review.status == "rejected":
                return PolicyDecision(
                    task_id=task.task_id,
                    status="block",
                    reason="human_approval_rejected",
                    guardrail_flags=["human_review_rejected"],
                )
        human_approved = bool(task.payload.get("human_approved", False))
        if human_approved or self.config.auto_approve_human_reviews:
            if review_id:
                self.honeycomb.resolve_review(
                    review_id,
                    approved=True,
                    approver=str(task.payload.get("human_approver", "operator")),
                    note=str(task.payload.get("human_note", "")) or None,
                )
            return PolicyDecision(
                task_id=task.task_id,
                status="approve",
                reason="human_approval_granted",
                guardrail_flags=[],
                approved_by=str(task.payload.get("human_approver", "operator")),
                approved_at=policy.created_at,
            )
        review = self.honeycomb.enqueue_review(task=task, reason=policy.reason)
        task.payload["human_review_id"] = review.review_id
        return policy

    def resume_human_review(self, review_id: str, *, approver: str, approved: bool, note: str = "") -> dict[str, Any]:
        review = self.honeycomb.resolve_review(review_id, approved=approved, approver=approver, note=note or None)
        if review.status != "approved":
            return {
                "review_id": review.review_id,
                "status": review.status,
                "resumed": False,
            }
        payload = dict(review.payload)
        payload["human_approved"] = True
        payload["human_approver"] = approver
        payload["human_review_id"] = review.review_id
        if note:
            payload["human_note"] = note
        resumed = self.run(intent=review.task_type, payload=payload)
        return {"review_id": review.review_id, "status": review.status, "resumed": True, "run": resumed}

    def _run_task_with_policies(
        self,
        task: TaskEnvelope,
        parent_span_id: str | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> tuple[ResultEnvelope, RetryCategory | None]:
        context = self._build_worker_context(task, status_callback)
        policy_task, budget_decision = self.guardrail_engine.apply_budget_controls(task, context.rule)
        self.honeycomb.write_event(
            task.queen_trace_id,
            {
                "kind": "budget_control",
                "task_id": task.task_id,
                "decision": budget_decision,
                "model_tier": policy_task.payload.get("model_tier"),
                "early_stop": bool(policy_task.payload.get("early_stop", False)),
            },
        )
        policy = self.guardrail_engine.evaluate(policy_task, context.rule)
        policy = self._resolve_human_approval(policy_task, policy)
        self.honeycomb.write_policy_decision(policy, trace_id=task.queen_trace_id)
        if policy.status == "block":
            policy_task.status = Status.blocked
            self.honeycomb.write_task(policy_task)
            return ResultEnvelope(
                task_id=policy_task.task_id,
                agent_id=context.identity.agent_id,
                worker_kind=policy_task.worker_kind,
                status=Status.blocked,
                confidence=0.0,
                output={"error": policy.reason},
                policy_flags=policy.guardrail_flags,
                output_schema="PolicyBlock",
            ), RetryCategory.policy
        if policy.status == "needs_human":
            policy_task.status = Status.blocked
            self.honeycomb.write_task(policy_task)
            return ResultEnvelope(
                task_id=policy_task.task_id,
                agent_id=context.identity.agent_id,
                worker_kind=policy_task.worker_kind,
                status=Status.blocked,
                confidence=0.0,
                output={
                    "error": "awaiting_human_approval",
                    "reason": policy.reason,
                    "human_review_id": policy_task.payload.get("human_review_id"),
                },
                policy_flags=["needs_human_approval"],
                output_schema="HumanApprovalPending",
            ), RetryCategory.policy
        result = self._execute_worker_task(policy_task, context, parent_span_id=parent_span_id)
        return result, None

    def _execute_worker_task(
        self, task: TaskEnvelope, context: WorkerContext, parent_span_id: str | None = None
    ) -> ResultEnvelope:
        if self.config.scheduler_backend == "temporal":
            if not TEMPORAL_AVAILABLE:
                raise RuntimeError("temporal_scheduler_requested_but_temporalio_not_installed")
            temporal_client = TemporalBeekeeperClient(
                TemporalConfig(
                    endpoint=self.config.temporal_endpoint,
                    namespace=self.config.temporal_namespace,
                    task_queue=self.config.temporal_task_queue,
                )
            )
            workflow_id = f"beekeeper-{task.queen_trace_id}-{task.task_id}"
            payload = asyncio_run(
                temporal_client.execute(
                    workflow_id=workflow_id,
                    task_payload=task.model_dump(mode="json"),
                    context_payload={
                        "identity": context.identity.model_dump(mode="json"),
                        "skill": context.skill.model_dump(mode="json"),
                        "rule": context.rule.model_dump(mode="json"),
                        "soul": context.soul.model_dump(mode="json"),
                        "abilities": context.abilities.model_dump(mode="json") if context.abilities else None,
                        "accountability": context.accountability.model_dump(mode="json") if context.accountability else None,
                        "guardrails": context.guardrails.model_dump(mode="json") if context.guardrails else None,
                    },
                    honeycomb_root=str(self.config.honeycomb_root.resolve()),
                    vector_backend=self.config.vector_backend,
                    vector_collection=self.config.vector_collection,
                    vector_url=self.config.vector_url,
                    llm_provider=self.config.llm_provider,
                    ollama_base_url=self.config.ollama_base_url,
                    ollama_model=self.config.ollama_model,
                    ollama_timeout_seconds=self.config.ollama_timeout_seconds,
                    gemini_api_key=self.config.gemini_api_key,
                    gemini_model=self.config.gemini_model,
                    gemini_timeout_seconds=self.config.gemini_timeout_seconds,
                    searxng_base_url=self.config.searxng_base_url,
                )
            )
            return ResultEnvelope.model_validate(payload)
        if self.scheduler is not None:
            job_id = self.scheduler.submit(
                task.model_dump(mode="json"),
                {
                    "identity": context.identity.model_dump(mode="json"),
                    "skill": context.skill.model_dump(mode="json"),
                    "rule": context.rule.model_dump(mode="json"),
                    "soul": context.soul.model_dump(mode="json"),
                    "abilities": context.abilities.model_dump(mode="json") if context.abilities else None,
                    "accountability": context.accountability.model_dump(mode="json") if context.accountability else None,
                    "guardrails": context.guardrails.model_dump(mode="json") if context.guardrails else None,
                },
            )
            payload = self.scheduler.collect(job_id, timeout_seconds=self.config.scheduler_timeout_seconds)
            return ResultEnvelope.model_validate(payload)
        return self.worker_runtime.run_once(task, context, parent_span_id=parent_span_id)

    def _should_delegate_to_workers(self, payload: dict[str, Any]) -> bool:
        """False = Queen responds directly (Ollama only). True = delegate to workers."""
        if payload.get("delegate_to_worker") is True:
            return True
        if payload.get("use_web_search") is True:
            return True
        if payload.get("domains"):
            return True
        if payload.get("numbers") is not None or payload.get("operation"):
            return True
        return False

    _WORKER_STATUS: dict[WorkerKind, str] = {
        WorkerKind.web_search: "Dispatching to web search worker: querying index and synthesizing from sources…",
        WorkerKind.heavy_compute: "Dispatching to heavy compute worker: running analysis…",
        WorkerKind.audit: "Dispatching to audit worker: performing validation…",
        WorkerKind.monitor: "Running monitor task…",
        WorkerKind.logger: "Logging…",
        WorkerKind.custom: "Executing task…",
    }

    def _run_action_loop(
        self,
        intent: str,
        payload: dict[str, Any],
        trace_id: str,
        status_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any] | None:
        """
        If ``payload["queen_actions"]`` is a non-empty list, execute the
        actions in order using ``QueenActionLoop``, auto-persist memory
        snippets, and return the aggregated results dict.

        Returns ``None`` to signal the caller should fall through to normal
        worker delegation.
        """
        raw_actions = payload.get("queen_actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            return None

        ctx = ActionContext(
            honeycomb_root=self.config.honeycomb_root,
            honeycomb=self.honeycomb,
            worker_runtime=self.worker_runtime,
            registry=self.registry,
            worker_registry=self.worker_registry,
            trace_id=trace_id,
            status_callback=status_callback,
        )
        loop = QueenActionLoop(ctx, registry=self._action_registry)
        return loop.run(raw_actions, trace_id=trace_id)

    def run_autonomous(self, source: str, task: dict[str, Any]) -> dict[str, Any]:
        """Run a task without user request (e.g. from Pulse). Validates against autonomy policy."""
        intent = str(task.get("intent", "research_topic"))
        payload = dict(task.get("payload", {}))
        payload["query"] = payload.get("query") or task.get("message") or task.get("query", "")
        ok, reason = self.autonomy_policy.validate(intent, payload)
        if not ok:
            return {
                "trace_id": "",
                "request_id": "",
                "blocked": True,
                "reason": reason,
                "results": [],
            }
        result = self.run(
            intent=intent,
            payload=payload,
            status_callback=None,
            source=f"autonomous:{source}",
        )
        if not result.get("blocked") and result.get("trace_id"):
            summary = _summarize_run_result(result)
            write_queen_update(
                self.honeycomb,
                trace_id=result["trace_id"],
                kind="report",
                summary=summary,
                payload={"intent": intent, "source": source},
            )
        return result

    def run(
        self,
        intent: str,
        payload: dict[str, Any],
        status_callback: Callable[[str], None] | None = None,
        source: str | None = None,
        session_id: str | None = None,
        parent_trace_id: str | None = None,
    ) -> dict[str, Any]:
        def _emit(msg: str) -> None:
            if status_callback:
                try:
                    status_callback(msg)
                except Exception:
                    pass

        queen_trace_id = f"trace_{uuid4().hex}"
        queen_request_id = str(uuid4())
        log_service_call("queen", "called", source=source or "unknown", trace_id=queen_trace_id)
        if session_id and not self.honeycomb.sessions_dir.joinpath(f"{session_id}.json").exists():
            session_id = None
        with self.tracer.span(queen_trace_id, "queen.run") as queen_span:
            if session_id:
                self.honeycomb.link_trace_to_session(session_id, queen_trace_id, parent_trace_id=parent_trace_id)
            if source:
                self.honeycomb.write_event(
                    queen_trace_id,
                    {"kind": "run_source", "source": source, "intent": intent},
                )
            # ── Action loop: Queen takes direct actions, learns, spawns workers ──
            action_result = self._run_action_loop(intent, payload, queen_trace_id, status_callback)
            if action_result is not None:
                # Emit an event so the trace captures the action round
                self.honeycomb.write_event(
                    queen_trace_id,
                    {
                        "kind": "queen_action_loop",
                        "intent": intent,
                        "action_count": len(payload.get("queen_actions", [])),
                        "memories_saved": len(action_result.get("memories_saved", [])),
                        "success": action_result.get("success"),
                    },
                )
                # If payload says stop_after_actions=True (or no further delegation needed) return now
                if payload.get("stop_after_actions", False):
                    return {
                        "trace_id": queen_trace_id,
                        "request_id": queen_request_id,
                        "queen_soul_profile_id": self.queen_soul.soul_profile_id,
                        "ollama_base_url": self.config.ollama_base_url,
                        "action_loop": action_result,
                        "results": [],
                        "trace_events": self.tracer.events,
                        "semantic_hits_for_intent": self.honeycomb.semantic_search(intent),
                    }
            if not self._should_delegate_to_workers(payload):
                query = str(payload.get("query") or payload.get("topic") or intent).strip()
                if query:
                    _emit("Analyzing request and determining execution path…")
                    queen_context = load_queen_context(self.config.honeycomb_root)
                    domains = payload.get("domains") or []
                    domain = str(domains[0]) if isinstance(domains, list) and domains else ""
                    queen_context = render_queen_context(
                        queen_context, intent=intent, domain=domain, worker_kind=""
                    )
                    # Inject Queen memories and semantic search for full platform stack
                    query_or_intent = str(payload.get("query") or payload.get("topic") or intent).strip()
                    queen_memories = self.honeycomb.read_queen_memories(limit=10)
                    semantic_hits = self.honeycomb.semantic_search_with_content(query_or_intent, limit=5)
                    mem_lines: list[str] = []
                    if queen_memories:
                        mem_lines.extend(f"- {m.get('content', '')}" for m in queen_memories[:10] if m.get("content"))
                    if semantic_hits:
                        contents = [text for _, text in semantic_hits if text and text.strip()]
                        mem_lines.extend(f"- {c}" for c in contents[:5])
                    if mem_lines:
                        queen_context = queen_context + "\n\n## Relevant past context (from memory)\n" + "\n".join(mem_lines)
                    memories = payload.get("user_memories") or []
                    if isinstance(memories, list) and memories:
                        mem_text = "\n".join(f"- {m}" if isinstance(m, str) else str(m.get("content", m)) for m in memories[:15])
                        queen_context = queen_context + "\n\n## User context (from past conversations)\n" + mem_text
                    prior = payload.get("messages") or []
                    messages = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in prior if isinstance(m, dict)]
                    model_override = (payload.get("model_override") or "").strip() or None
                    assistant_reply, source = self.worker_runtime.direct_chat(
                        query, system=queen_context, messages=messages or None, model_override=model_override
                    )
                    if assistant_reply is None:
                        if self.config.llm_provider == "gemini":
                            assistant_reply = (
                                "I could not reach Gemini right now. "
                                "Check BEEKEEPER_GEMINI_API_KEY, billing/quota, and API access."
                            )
                        else:
                            assistant_reply = (
                                "I could not reach Ollama right now. "
                                "Set BEEKEEPER_OLLAMA_BASE_URL and ensure Ollama is running."
                            )
                    output = {
                        "query": query,
                        "evidence": [],
                        "assistant_reply": assistant_reply,
                        "response_source": source,
                        "synthesis": "Direct chat (Queen direct, no workers).",
                    }
                    result = ResultEnvelope(
                        task_id=str(uuid4()),
                        agent_id="queen-direct",
                        worker_kind=WorkerKind.custom,
                        status=Status.success,
                        confidence=0.9,
                        output=output,
                        artifact_refs=[],
                        cost_metrics=CostMetrics(latency_ms=0, estimated_cost_usd=0.0),
                        output_schema="QueenDirectOutput",
                    )
                    return {
                        "trace_id": queen_trace_id,
                        "request_id": queen_request_id,
                        "queen_soul_profile_id": self.queen_soul.soul_profile_id,
                        "ollama_base_url": self.config.ollama_base_url,
                        "results": [result.model_dump(mode="json")],
                        "trace_events": self.tracer.events,
                        "semantic_hits_for_intent": self.honeycomb.semantic_search(intent),
                    }
            _emit("Decomposing request into executable tasks…")
            # Enrich payload with Queen memories and semantic context for workers
            query_or_intent = str(payload.get("query") or payload.get("topic") or intent).strip()
            if query_or_intent:
                queen_mems = self.honeycomb.read_queen_memories(limit=10)
                semantic_hits = self.honeycomb.semantic_search_with_content(query_or_intent, limit=5)
                if queen_mems:
                    payload["_queen_memories"] = [m.get("content", "") for m in queen_mems[:10] if m.get("content")]
                if semantic_hits:
                    payload["_semantic_context"] = [text for _, text in semantic_hits if text and text.strip()][:5]
            tasks = self.decompose_intent(queen_trace_id, queen_request_id, intent, payload)
            results: list[ResultEnvelope] = []
            for task in tasks:
                _emit(self._WORKER_STATUS.get(task.worker_kind, "Executing task…"))
                if task.worker_kind == WorkerKind.audit and "target_result" not in task.payload:
                    target_task_id = str(task.payload.get("target_task_id", ""))
                    if target_task_id:
                        for previous in results:
                            if previous.task_id == target_task_id:
                                task.payload["target_result"] = previous.model_dump(mode="json")
                                break
                attempts = 0
                final_result: ResultEnvelope | None = None
                while attempts <= max(self.config.max_reruns, task.max_retries):
                    attempts += 1
                    result_retry_category: RetryCategory | None = None
                    final_result, result_retry_category = self._run_task_with_policies(
                        task, parent_span_id=queen_span, status_callback=status_callback
                    )
                    monitor_decision = self.monitor.inspect(task, final_result)
                    retry_category = result_retry_category or (
                        classify_retry_category(monitor_decision.reason)
                        if monitor_decision.action != "accept"
                        else None
                    )
                    self.honeycomb.write_event(
                        queen_trace_id,
                        {
                            "kind": "monitor_decision",
                            "task_id": task.task_id,
                            "action": monitor_decision.action,
                            "reason": monitor_decision.reason,
                            "attempt": attempts,
                            "quality_score": monitor_decision.quality_score,
                            "retry_category": retry_category.value if retry_category else None,
                        },
                    )
                    performance = WorkerPerformanceRecord(
                        trace_id=queen_trace_id,
                        task_id=task.task_id,
                        worker_kind=task.worker_kind,
                        status=final_result.status,
                        quality_score=monitor_decision.quality_score,
                        confidence=final_result.confidence,
                        latency_ms=final_result.cost_metrics.latency_ms,
                        estimated_cost_usd=final_result.cost_metrics.estimated_cost_usd,
                        failure_reason=(monitor_decision.reason if monitor_decision.action != "accept" else None),
                        retry_category=retry_category,
                    )
                    self.honeycomb.write_worker_performance(queen_trace_id, performance)
                    self.honeycomb.record_routing_outcome(
                        worker_kind=task.worker_kind,
                        intent=task.task_type,
                        skill_id=self._route_skill(task),
                        quality_score=monitor_decision.quality_score,
                        latency_ms=final_result.cost_metrics.latency_ms,
                        cost_usd=final_result.cost_metrics.estimated_cost_usd,
                        success=monitor_decision.action == "accept",
                    )
                    if monitor_decision.action == "accept":
                        break
                    if monitor_decision.action == "escalate":
                        break
                    if attempts > max(self.config.max_reruns, task.max_retries):
                        break
                    if retry_category == RetryCategory.policy:
                        break
                    wait_seconds = retry_backoff_seconds(attempts, retry_category or RetryCategory.transient)
                    if wait_seconds > 0:
                        time.sleep(wait_seconds)
                    task.status = Status.queued
                if final_result is not None:
                    results.append(final_result)
            self.honeycomb.enforce_retention_lifecycle()

            return {
                "trace_id": queen_trace_id,
                "request_id": queen_request_id,
                "queen_soul_profile_id": self.queen_soul.soul_profile_id,
                "ollama_base_url": self.config.ollama_base_url,
                "results": [result.model_dump(mode="json") for result in results],
                "trace_events": self.tracer.events,
                "semantic_hits_for_intent": self.honeycomb.semantic_search(intent),
            }


def _summarize_run_result(result: dict[str, Any]) -> str:
    """Extract a short summary from Queen run result."""
    results = result.get("results", [])
    if not results:
        return "No output"
    first = results[0] if isinstance(results[0], dict) else {}
    out = first.get("output", {})
    for k in ("assistant_reply", "answer", "summary", "text", "synthesis"):
        v = out.get(k)
        if isinstance(v, str) and v.strip():
            return (v[:300] + "…") if len(v) > 300 else v
    return str(out)[:300]
