from __future__ import annotations

import hashlib
import os
import time
from asyncio import run as asyncio_run
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .contracts import (
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
from .soul import load_default_queen_soul
from .temporal_integration import TEMPORAL_AVAILABLE, TemporalBeehiveClient, TemporalConfig
from .tracing import Tracer
from .worker import WorkerContext, WorkerRuntime, execute_task_serialized, make_worker_identity


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
    temporal_task_queue: str = "beehive-queue"
    vector_backend: str = "memory"  # memory | qdrant
    vector_collection: str = "honeycomb_memory"
    vector_url: str = "http://localhost:6333"
    queen_soul_profile_id: str = "soul.queen.crown"
    llm_provider: str = field(default_factory=lambda: os.getenv("BEEHIVE_LLM_PROVIDER", "ollama"))
    ollama_base_url: str = field(default_factory=lambda: os.getenv("BEEHIVE_OLLAMA_BASE_URL", "http://100.99.106.59:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("BEEHIVE_OLLAMA_MODEL", "catsarethebest/qwen2.5-N2:1.5b"))
    ollama_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("BEEHIVE_OLLAMA_TIMEOUT_SECONDS", "120")))
    gemini_api_key: str = field(default_factory=lambda: os.getenv("BEEHIVE_GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("BEEHIVE_GEMINI_MODEL", "gemini-1.5-flash"))
    gemini_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("BEEHIVE_GEMINI_TIMEOUT_SECONDS", "120")))
    searxng_base_url: str = field(default_factory=lambda: os.getenv("BEEHIVE_SEARXNG_BASE_URL", "http://localhost:8080"))
    auto_approve_human_reviews: bool = False


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
        self.guardrail_engine = GuardrailPolicyEngine(
            [
                SchemaGuardrail(),
                PIIGuardrail(),
                JailbreakGuardrail(),
                WebDomainGuardrail(),
                HeavyComputeBudgetGuardrail(),
                AuditPayloadGuardrail(),
            ]
        )
        self.worker_runtime = WorkerRuntime(
            self.honeycomb,
            self.tracer,
            llm_provider=self.config.llm_provider,
            ollama_base_url=self.config.ollama_base_url,
            ollama_model=self.config.ollama_model,
            ollama_timeout_seconds=self.config.ollama_timeout_seconds,
            gemini_api_key=self.config.gemini_api_key,
            gemini_model=self.config.gemini_model,
            gemini_timeout_seconds=self.config.gemini_timeout_seconds,
            searxng_base_url=self.config.searxng_base_url,
        )
        self.monitor = SentinelMonitor(min_confidence=0.65)
        self.routing_optimizer = RoutingFeedbackOptimizer()
        self.scheduler = self._build_scheduler()
        self._seed_defaults()
        self.queen_soul = self.registry.get_soul(self.config.queen_soul_profile_id)

    def _build_scheduler(self) -> Scheduler | None:
        if self.config.scheduler_backend == "celery":
            os.environ.setdefault("BEEHIVE_CELERY_BROKER_URL", self.config.celery_broker_url)
            os.environ.setdefault("BEEHIVE_CELERY_BACKEND_URL", self.config.celery_backend_url)
            os.environ.setdefault("BEEHIVE_HONEYCOMB_ROOT", str(self.config.honeycomb_root.resolve()))
            os.environ.setdefault("BEEHIVE_VECTOR_BACKEND", self.config.vector_backend)
            os.environ.setdefault("BEEHIVE_VECTOR_COLLECTION", self.config.vector_collection)
            os.environ.setdefault("BEEHIVE_VECTOR_URL", self.config.vector_url)
            os.environ.setdefault("BEEHIVE_LLM_PROVIDER", self.config.llm_provider)
            os.environ.setdefault("BEEHIVE_OLLAMA_BASE_URL", self.config.ollama_base_url)
            os.environ.setdefault("BEEHIVE_OLLAMA_MODEL", self.config.ollama_model)
            os.environ.setdefault("BEEHIVE_OLLAMA_TIMEOUT_SECONDS", str(self.config.ollama_timeout_seconds))
            os.environ.setdefault("BEEHIVE_GEMINI_API_KEY", self.config.gemini_api_key)
            os.environ.setdefault("BEEHIVE_GEMINI_MODEL", self.config.gemini_model)
            os.environ.setdefault("BEEHIVE_GEMINI_TIMEOUT_SECONDS", str(self.config.gemini_timeout_seconds))
            os.environ.setdefault("BEEHIVE_SEARXNG_BASE_URL", self.config.searxng_base_url)
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
                description="Searches and synthesizes web context",
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
                description="Monitors worker outputs and quality",
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
                description="Executes bounded high-compute style tasks",
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
        self.registry.register_soul(load_default_queen_soul())

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
        return "skill.research.web"

    def _route_worker_kind(self, intent: str, payload: dict[str, Any]) -> WorkerKind:
        lowered = intent.lower()
        if "audit" in lowered:
            return WorkerKind.audit
        if any(token in lowered for token in ("compute", "analysis", "simulate", "aggregate")):
            return WorkerKind.heavy_compute
        if isinstance(payload.get("numbers"), list) or payload.get("operation"):
            return WorkerKind.heavy_compute
        feedback = self.honeycomb.read_routing_feedback()
        if feedback:
            required_skill = "skill.compute.heavy" if isinstance(payload.get("numbers"), list) or payload.get("operation") else "skill.research.web"
            risk_action = str(payload.get("action", "")).strip()
            requested_budget = float(payload.get("budget_usd", 0.5))
            best_kind = WorkerKind.web_search
            best_score = -1.0
            for entry in feedback.values():
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
            if best_kind in {WorkerKind.web_search, WorkerKind.heavy_compute}:
                return best_kind
        return WorkerKind.web_search

    def _build_worker_context(self, task: TaskEnvelope) -> WorkerContext:
        skill_id = self._route_skill(task)
        soul_id = "soul.balanced"
        worker_id = make_worker_identity(
            agent_type=f"worker.{task.task_type}",
            skill_profile_id=skill_id,
            soul_profile_id=soul_id,
        )
        return WorkerContext(
            identity=worker_id,
            skill=self.registry.get_skill(skill_id),
            rule=self.registry.get_rule("rule.default"),
            soul=self.registry.get_soul(soul_id),
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

    def _run_task_with_policies(self, task: TaskEnvelope, parent_span_id: str | None = None) -> tuple[ResultEnvelope, RetryCategory | None]:
        context = self._build_worker_context(task)
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
            temporal_client = TemporalBeehiveClient(
                TemporalConfig(
                    endpoint=self.config.temporal_endpoint,
                    namespace=self.config.temporal_namespace,
                    task_queue=self.config.temporal_task_queue,
                )
            )
            workflow_id = f"beehive-{task.queen_trace_id}-{task.task_id}"
            payload = asyncio_run(
                temporal_client.execute(
                    workflow_id=workflow_id,
                    task_payload=task.model_dump(mode="json"),
                    context_payload={
                        "identity": context.identity.model_dump(mode="json"),
                        "skill": context.skill.model_dump(mode="json"),
                        "rule": context.rule.model_dump(mode="json"),
                        "soul": context.soul.model_dump(mode="json"),
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
                },
            )
            payload = self.scheduler.collect(job_id, timeout_seconds=self.config.scheduler_timeout_seconds)
            return ResultEnvelope.model_validate(payload)
        return self.worker_runtime.run_once(task, context, parent_span_id=parent_span_id)

    def run(self, intent: str, payload: dict[str, Any]) -> dict[str, Any]:
        queen_trace_id = f"trace_{uuid4().hex}"
        queen_request_id = str(uuid4())
        with self.tracer.span(queen_trace_id, "queen.run") as queen_span:
            tasks = self.decompose_intent(queen_trace_id, queen_request_id, intent, payload)
            results: list[ResultEnvelope] = []
            for task in tasks:
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
                    final_result, result_retry_category = self._run_task_with_policies(task, parent_span_id=queen_span)
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
