from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import time
from asyncio import run as asyncio_run
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
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
from .queen_context import build_context_bundle, ensure_queen_context_file, load_queen_context, render_queen_context
from .skill_loader import load_skills_from_md
from .autonomy import AutonomyPolicy, DEFAULT_AUTONOMY_POLICY
from .queen_updates import write_queen_update
from .queen_actions import ActionContext, QueenActionLoop, build_default_action_registry
from .tool_adapters import register_action_tools, register_worker_tools
from .tool_runtime import ToolExecutionPolicy, ToolExecutor, ToolLoopEngine, ToolRegistry
from .llm_provider import build_llm_router


@dataclass
class QueenConfig:
    honeycomb_root: Path
    max_reruns: int = 1
    scheduler_backend: str = "auto"  # auto | inline | celery | temporal
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
    worker_context_curator_blueprint_id: str = "blueprint.worker.context_curator"
    autonomy_policy: AutonomyPolicy | None = None
    execution_mode: str = "legacy_worker"  # legacy_worker | model_tools | hybrid


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
        self._llm_router = build_llm_router(
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
        )
        self._tool_registry: ToolRegistry | None = None
        self._tool_executor: ToolExecutor | None = None
        self._tool_loop_engine: ToolLoopEngine | None = None
        if self.config.execution_mode in ("model_tools", "hybrid"):
            self._tool_registry = ToolRegistry()
            register_worker_tools(
                self._tool_registry,
                self.worker_runtime,
                self.honeycomb,
                self.registry,
            )

            def _action_ctx_factory() -> ActionContext:
                return ActionContext(
                    honeycomb_root=self.config.honeycomb_root,
                    honeycomb=self.honeycomb,
                    worker_runtime=self.worker_runtime,
                    registry=self.registry,
                    worker_registry=self.worker_registry,
                )

            register_action_tools(
                self._tool_registry,
                self._action_registry,
                _action_ctx_factory,
            )
            policy = ToolExecutionPolicy(
                max_steps=10,
                max_cost_per_turn_usd=2.0,
                require_human_approval_for_tools=["spawn_worker"],
            )

            def _tool_guardrail(tool_name: str, arguments: dict[str, Any]) -> tuple[bool, str | None, bool]:
                from .guardrails import evaluate_tool_call
                rule = self.registry.resolve_profiles(self.config.queen_blueprint_id).rule
                return evaluate_tool_call(tool_name, arguments, rule)

            self._tool_executor = ToolExecutor(
                self._tool_registry,
                honeycomb=self.honeycomb,
                policy=policy,
                tool_guardrail_fn=_tool_guardrail,
            )
            self._tool_loop_engine = ToolLoopEngine(self._tool_executor, policy=policy)
            try:
                from .mcp_transport import register_mcp_servers_from_config
                register_mcp_servers_from_config(self._tool_registry)
            except Exception:
                pass

    def _build_scheduler(self) -> Scheduler | None:
        if self.config.scheduler_backend == "celery":
            return self._build_celery_scheduler()
        if self.config.scheduler_backend == "inline":
            return self._build_inline_scheduler()
        return None

    def _build_celery_scheduler(self) -> CeleryScheduler:
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

    def _build_inline_scheduler(self) -> InlineScheduler:
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

    @staticmethod
    def _is_tcp_reachable(host: str, port: int, timeout_seconds: float = 0.35) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                return True
        except Exception:
            return False

    @staticmethod
    def _endpoint_host_port(endpoint: str, default_port: int) -> tuple[str, int]:
        value = (endpoint or "").strip()
        if "://" in value:
            parsed = urlparse(value)
            host = parsed.hostname or "localhost"
            port = parsed.port or default_port
            return host, int(port)
        if ":" in value:
            host, port_text = value.rsplit(":", 1)
            try:
                return host, int(port_text)
            except ValueError:
                return host or "localhost", default_port
        return value or "localhost", default_port

    def _can_connect_celery(self) -> bool:
        host, port = self._endpoint_host_port(self.config.celery_broker_url, 6379)
        return self._is_tcp_reachable(host, port)

    def _can_connect_temporal(self) -> bool:
        if not TEMPORAL_AVAILABLE:
            return False
        host, port = self._endpoint_host_port(self.config.temporal_endpoint, 7233)
        return self._is_tcp_reachable(host, port)

    @staticmethod
    def _payload_prefers_temporal(payload: dict[str, Any]) -> bool:
        if payload.get("require_durable") is True:
            return True
        if payload.get("long_running") is True:
            return True
        durability = str(payload.get("durability", "")).strip().lower()
        if durability in {"high", "strict", "durable"}:
            return True
        if payload.get("workflow") is not None:
            return True
        try:
            expected_seconds = float(payload.get("expected_runtime_seconds", 0))
        except (TypeError, ValueError):
            expected_seconds = 0.0
        return expected_seconds >= 90.0

    def _resolve_scheduler_backend(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        requested = str(self.config.scheduler_backend or "inline").strip().lower()
        if requested in {"inline", "celery", "temporal"}:
            return requested, {"requested": requested, "selected": requested, "reason": "explicit_scheduler"}
        if requested != "auto":
            return "inline", {
                "requested": requested,
                "selected": "inline",
                "reason": "unknown_scheduler_fallback",
            }

        prefers_temporal = self._payload_prefers_temporal(payload)
        celery_ready = self._can_connect_celery()
        temporal_ready = self._can_connect_temporal()
        if prefers_temporal and temporal_ready:
            selected = "temporal"
            reason = "durability_hint_and_temporal_ready"
        elif prefers_temporal and celery_ready:
            selected = "celery"
            reason = "durability_hint_temporal_unavailable_using_celery"
        elif celery_ready:
            selected = "celery"
            reason = "queue_ready_default"
        elif temporal_ready:
            selected = "temporal"
            reason = "celery_unavailable_using_temporal"
        else:
            selected = "inline"
            reason = "queue_unavailable_fallback_inline"
        return selected, {
            "requested": requested,
            "selected": selected,
            "reason": reason,
            "prefers_temporal": prefers_temporal,
            "celery_ready": celery_ready,
            "temporal_ready": temporal_ready,
        }

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
                skill_profile_id="skill.context.curator",
                name="Context Curator",
                description="Curates durable user/project memories from completed chat turns.",
                when_to_use="after chat turn completion for memory ingestion",
                tool_allowlist=["memory_write", "memory_search", "semantic_index"],
                capabilities=["memory_curation"],
                can_search_web=False,
                can_execute_code=False,
                max_parallel_tools=1,
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
                capabilities=["web_search", "fact_synthesis", "compute", "audit", "memory_curation"],
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
                blueprint_id="blueprint.worker.context_curator",
                name="Context Curator Worker",
                agent_type="worker",
                worker_kind=WorkerKind.context_curator,
                profile_bundle=ProfileBundleRef(
                    soul_id="soul.balanced",
                    abilities_id="abilities.default",
                    accountabilities_id="accountability.default",
                    rules_id="rule.default",
                    guardrails_id="guardrails.default",
                    skills_id="skill.context.curator",
                ),
                tags=["worker", "memory", "context"],
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
        worker_kind = self._route_worker_kind(intent, payload, trace_id=queen_trace_id)
        required_skills = ["web_search"]
        if worker_kind == WorkerKind.heavy_compute:
            required_skills = ["compute"]
        if worker_kind == WorkerKind.audit:
            required_skills = ["audit"]
        if worker_kind == WorkerKind.context_curator:
            required_skills = ["memory_curation"]
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
        if task.worker_kind == WorkerKind.context_curator:
            return "skill.context.curator"
        if task.worker_kind == WorkerKind.heavy_compute:
            return "skill.compute.heavy"
        if task.worker_kind == WorkerKind.forged:
            return "skill.research.web"
        return "skill.research.web"

    @staticmethod
    def _normalize_worker_kind(intent: str) -> str:
        raw = re.sub(r"[^a-z0-9_]+", "_", intent.lower().replace("-", "_").replace(" ", "_"))
        raw = re.sub(r"_+", "_", raw).strip("_")
        return f"custom_{raw or 'task'}"

    @staticmethod
    def _extract_query_keywords(payload: dict[str, Any]) -> list[str]:
        query_hint = str(payload.get("query") or payload.get("topic") or "").strip().lower()
        if not query_hint:
            return []
        words: list[str] = []
        for token in re.split(r"[^a-z0-9]+", query_hint):
            if len(token) > 3 and token not in words:
                words.append(token)
            if len(words) >= 8:
                break
        return words

    @staticmethod
    def _fallback_workers_for_payload(payload: dict[str, Any]) -> list[str]:
        if payload.get("numbers") is not None or payload.get("operation"):
            return ["heavy_compute", "web_search"]
        return ["web_search"]

    @staticmethod
    def _worker_class_name(worker_kind_str: str) -> str:
        tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", worker_kind_str) if token]
        base = "".join(token[:1].upper() + token[1:] for token in tokens) or "CustomWorker"
        if not base.endswith("Worker"):
            base += "Worker"
        return base

    @staticmethod
    def _build_forged_worker_source(worker_kind_str: str, class_name: str, intent: str, name: str) -> str:
        safe_name = name.replace('"', "'")
        safe_intent = intent.replace('"', "'")
        return (
            '"""Auto-generated worker plugin for on-demand forged routing."""\n'
            "from __future__ import annotations\n\n"
            "from beekeeper.worker import ForgedWorker\n\n\n"
            f"class {class_name}(ForgedWorker):\n"
            f'    """Generated worker for intent "{safe_intent}" ({safe_name})."""\n'
            f'    worker_kind = "{worker_kind_str}"\n'
        )

    def _gather_worker_build_context(self, intent: str, payload: dict[str, Any]) -> str:
        """Ask the LLM for a 3-5 sentence technical spec before generating worker code.
        Returns empty string on any error — never raises.
        """
        try:
            query = str(payload.get("query") or payload.get("topic") or intent)
            payload_keys = [k for k in payload if not k.startswith("_")]
            system_prompt = (
                "You are a software architect for the Beekeeper autonomous agent platform.\n"
                "Provide a concise 3-5 sentence technical specification for a worker that will handle the given intent.\n"
                "Cover: step-by-step logic the worker should follow, relevant payload fields to use, "
                "appropriate stdlib modules, and expected output format.\n"
                "Be precise and implementation-focused. No code, just the spec."
            )
            user_prompt = (
                f"Intent: {intent}\n"
                f"Task description: {query}\n"
                f"Available payload keys: {payload_keys}\n\n"
                "Write the technical specification for the worker."
            )
            reply, _source = self.worker_runtime.direct_chat(
                query=user_prompt,
                system=system_prompt,
            )
            return (reply or "").strip()
        except Exception:
            return ""

    def _generate_worker_source_via_llm(
        self,
        worker_kind_str: str,
        class_name: str,
        intent: str,
        name: str,
        payload: dict[str, Any],
        build_context: str = "",
    ) -> str:
        """Ask the LLM to generate a real specialist worker for this intent.
        Returns Python source code. Raises on failure so caller can fall back.
        """
        query = str(payload.get("query") or payload.get("topic") or intent)
        payload_keys = [k for k in payload if not k.startswith("_")]

        system_prompt = (
            "You are a Python code generator for the Beekeeper autonomous agent platform.\n"
            "Generate a specialist Worker class for a specific task type.\n\n"
            "## Rules\n"
            "- Inherit from ForgedWorker (provides self.llm_router for LLM calls)\n"
            "- Set worker_kind as a plain string class attribute (NOT a WorkerKind enum)\n"
            "- Implement execute(task, context) returning a dict matching WebSearchOutput\n"
            "- Use try/except for error handling\n"
            "- Emit status with: self._emit_status(context, '...')\n"
            "- For LLM calls: reply, source = self.llm_router.call(prompt=..., system=...)\n"
            "- For file I/O: use pathlib.Path\n"
            "- Allowed imports: os, pathlib, json, urllib, datetime, re, io (stdlib only)\n"
            "- DO NOT import requests, httpx, or any third-party library\n"
            "- Return ONLY valid Python code, no markdown fences, no explanation\n\n"
            "## Output dict schema (WebSearchOutput):\n"
            "  query: str, evidence: list (can be []), assistant_reply: str, "
            "response_source: str, synthesis: str\n\n"
            "## Template:\n"
            "from __future__ import annotations\n"
            "import os\n"
            "from pathlib import Path\n"
            "from typing import Any\n"
            "from beekeeper.worker import ForgedWorker\n"
            "from beekeeper.contracts import TaskEnvelope, WorkerContext, WebSearchOutput\n\n"
            "class {ClassName}(ForgedWorker):\n"
            "    worker_kind = '{worker_kind_str}'\n"
            "    def execute(self, task: TaskEnvelope, context: WorkerContext) -> dict[str, Any]:\n"
            "        ...\n"
            "        return WebSearchOutput(...).model_dump(mode='json')\n"
        )

        user_prompt = (
            f"Generate a worker class for intent: {intent}\n"
            f"Worker kind string: \"{worker_kind_str}\"\n"
            f"Class name: {class_name}\n"
            f"Task description: {query}\n"
            f"Payload keys available: {payload_keys}\n\n"
            "Return ONLY the Python code."
        )
        if build_context:
            user_prompt += f"\n\nTechnical specification:\n{build_context}"

        reply, _source = self.worker_runtime.direct_chat(
            query=user_prompt,
            system=system_prompt,
        )
        if not reply or not reply.strip():
            raise ValueError("LLM returned empty response for worker code generation")

        # Strip markdown fences if LLM included them
        code = reply.strip()
        if code.startswith("```"):
            lines = code.splitlines()
            code = "\n".join(
                line for line in lines[1:]
                if not line.strip().startswith("```")
            ).strip()

        # Validate: must compile cleanly
        compile(code, f"<generated:{worker_kind_str}>", "exec")

        # Validate: must contain a ForgedWorker subclass
        import ast as _ast
        try:
            tree = _ast.parse(code)
        except SyntaxError as exc:
            raise ValueError(f"Generated code has syntax error: {exc}") from exc
        class_defs = [node for node in _ast.walk(tree) if isinstance(node, _ast.ClassDef)]
        has_forged_worker = any(
            any(
                (isinstance(base, _ast.Name) and base.id == "ForgedWorker")
                or (isinstance(base, _ast.Attribute) and base.attr == "ForgedWorker")
                for base in cls.bases
            )
            for cls in class_defs
        )
        if not has_forged_worker:
            raise ValueError("Generated code does not contain a ForgedWorker subclass")
        return code

    def _ensure_worker_plugin(self, worker_kind_str: str, intent: str, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        root = Path(self.config.honeycomb_root)
        generated_dir = root / "workers" / "generated"
        generated_dir.mkdir(parents=True, exist_ok=True)
        class_name = self._worker_class_name(worker_kind_str)
        plugin_path = generated_dir / f"{worker_kind_str}.py"
        created_file = False
        build_context = ""
        if not plugin_path.exists():
            build_context = self._gather_worker_build_context(intent, payload or {})
            try:
                plugin_source = self._generate_worker_source_via_llm(
                    worker_kind_str, class_name, intent, name, payload or {},
                    build_context=build_context,
                )
            except Exception:
                plugin_source = self._build_forged_worker_source(worker_kind_str, class_name, intent, name)
                build_context = ""
            plugin_path.write_text(plugin_source, encoding="utf-8")
            created_file = True
        plugins_path = root / "workers" / "plugins.json"
        plugins_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {"workers": []}
        if plugins_path.exists():
            try:
                loaded = json.loads(plugins_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except (json.JSONDecodeError, OSError):
                data = {"workers": []}
        workers = data.get("workers")
        if not isinstance(workers, list):
            workers = []
        module_path = str(Path("workers") / "generated" / f"{worker_kind_str}.py")
        existing = next(
            (
                entry for entry in workers
                if isinstance(entry, dict)
                and str(entry.get("worker_kind", "")).strip() == worker_kind_str
            ),
            None,
        )
        created_plugin_entry = False
        if existing is None:
            workers.append(
                {
                    "worker_kind": worker_kind_str,
                    "module_path": module_path,
                    "class_name": class_name,
                }
            )
            created_plugin_entry = True
        data["workers"] = workers
        plugins_path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")
        return {
            "plugin_file_created": created_file,
            "plugin_file_path": str(plugin_path),
            "plugin_entry_created": created_plugin_entry,
            "plugin_class_name": class_name,
            "plugin_module_path": module_path,
            "build_context": build_context,
        }

    def _test_generated_worker(
        self, worker_kind_str: str, intent: str, payload: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Run the newly generated worker against the current payload.
        Returns (True, None) on success, (False, error_string) on failure.
        Uses an isolated test trace ID so it does not pollute the main trace.
        """
        try:
            test_trace_id = f"test-{uuid4().hex[:12]}"
            test_payload = {k: v for k, v in payload.items() if not k.startswith("_")}
            test_payload["_runtime_worker_key"] = worker_kind_str
            test_task = TaskEnvelope(
                queen_trace_id=test_trace_id,
                queen_request_id=test_trace_id,
                task_type=intent,
                worker_kind=WorkerKind.forged,
                payload=test_payload,
                required_skills=["custom"],
                budget_usd=0.5,
                max_retries=0,
                idempotency_key=test_trace_id,
                status=Status.queued,
            )
            context = self._build_worker_context(test_task)
            result = self.worker_runtime.run_once(test_task, context)
            if result.status == Status.success:
                return True, None
            error_msg = str(result.output.get("error", "worker returned non-success status"))
            return False, error_msg
        except Exception as exc:
            return False, str(exc)

    def _fix_worker_code(
        self,
        worker_kind_str: str,
        class_name: str,
        intent: str,
        name: str,
        payload: dict[str, Any],
        previous_code: str,
        error_msg: str,
        build_context: str = "",
    ) -> str:
        """Ask the LLM to fix broken generated worker code.
        Returns fixed Python source. Raises on failure so the retry loop can catch it.
        """
        query = str(payload.get("query") or payload.get("topic") or intent)
        system_prompt = (
            "You are a Python debugging expert for the Beekeeper autonomous agent platform.\n"
            "You will receive broken worker code and the error it produced.\n"
            "Fix the code so it runs correctly.\n\n"
            "## Rules\n"
            "- Keep ForgedWorker inheritance and worker_kind class attribute\n"
            "- Fix the execute(task, context) method to return a valid WebSearchOutput dict\n"
            "- Use try/except for error handling\n"
            "- Allowed imports: os, pathlib, json, urllib, datetime, re, io (stdlib only)\n"
            "- DO NOT import requests, httpx, or any third-party library\n"
            "- Return ONLY the complete fixed Python code, no markdown fences, no explanation\n"
        )
        user_prompt = (
            f"Intent: {intent}\n"
            f"Worker kind: {worker_kind_str}\n"
            f"Class name: {class_name}\n"
            f"Task description: {query}\n\n"
            f"Error encountered:\n{error_msg}\n\n"
            f"Broken code:\n{previous_code}\n\n"
            "Return ONLY the fixed Python code."
        )
        if build_context:
            user_prompt += f"\n\nTechnical specification:\n{build_context}"

        reply, _source = self.worker_runtime.direct_chat(
            query=user_prompt,
            system=system_prompt,
        )
        if not reply or not reply.strip():
            raise ValueError("LLM returned empty response for worker fix")

        code = reply.strip()
        if code.startswith("```"):
            lines = code.splitlines()
            code = "\n".join(
                line for line in lines[1:]
                if not line.strip().startswith("```")
            ).strip()

        compile(code, f"<fixed:{worker_kind_str}>", "exec")

        import ast as _ast
        try:
            tree = _ast.parse(code)
        except SyntaxError as exc:
            raise ValueError(f"Fixed code has syntax error: {exc}") from exc
        class_defs = [node for node in _ast.walk(tree) if isinstance(node, _ast.ClassDef)]
        has_forged_worker = any(
            any(
                (isinstance(base, _ast.Name) and base.id == "ForgedWorker")
                or (isinstance(base, _ast.Attribute) and base.attr == "ForgedWorker")
                for base in cls.bases
            )
            for cls in class_defs
        )
        if not has_forged_worker:
            raise ValueError("Fixed code does not contain a ForgedWorker subclass")
        return code

    def _auto_spawn_worker(self, intent: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Register a new custom worker blueprint when no content match exists for this intent.
        The spawned worker uses ForgedWorker (LLM) for execution but is persisted to the registry
        so future requests with the same intent pattern are correctly routed.
        """
        worker_kind_str = self._normalize_worker_kind(intent)
        # Check if already registered (avoid duplicate spawning)
        existing = next(
            (w for w in self.worker_registry.list_workers() if w.get("worker_kind") == worker_kind_str),
            None,
        )
        if existing:
            return {"worker_kind": worker_kind_str, "created": False}
        name = intent.replace("_", " ").replace("-", " ").title()
        keywords = self._extract_query_keywords(payload)
        fallback_workers = self._fallback_workers_for_payload(payload)
        self.worker_registry.register_custom_worker(
            worker_kind=worker_kind_str,
            name=name,
            description=f"Auto-spawned worker for intent: {intent}",
            capabilities=["custom", intent.lower()],
            intent_patterns=[intent, intent.lower()],
            payload_triggers=[],
            query_keywords=keywords,
            priority=15,
            fallback_workers=fallback_workers,
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
        plugin = self._ensure_worker_plugin(worker_kind_str, intent=intent, name=name, payload=payload)
        self.worker_runtime.reload_plugins(self.config.honeycomb_root)
        self.worker_registry.reload()

        MAX_FIX_ATTEMPTS = 2
        plugin_path = Path(self.config.honeycomb_root) / "workers" / "generated" / f"{worker_kind_str}.py"
        build_context = plugin.get("build_context", "")
        class_name = self._worker_class_name(worker_kind_str)

        test_ok, test_error = self._test_generated_worker(worker_kind_str, intent, payload)
        if test_ok:
            payload["_runtime_worker_key"] = worker_kind_str
            return {
                "worker_kind": worker_kind_str,
                "created": True,
                "verified": True,
                "keywords": keywords,
                "fallback_workers": fallback_workers,
                **plugin,
            }

        current_code = plugin_path.read_text(encoding="utf-8")
        for attempt in range(MAX_FIX_ATTEMPTS):
            try:
                fixed = self._fix_worker_code(
                    worker_kind_str, class_name, intent, name, payload,
                    previous_code=current_code, error_msg=test_error or "unknown",
                    build_context=build_context,
                )
                plugin_path.write_text(fixed, encoding="utf-8")
                self.worker_runtime.reload_plugins(self.config.honeycomb_root)
                self.worker_registry.reload()
                test_ok, test_error = self._test_generated_worker(worker_kind_str, intent, payload)
                if test_ok:
                    payload["_runtime_worker_key"] = worker_kind_str
                    return {
                        "worker_kind": worker_kind_str,
                        "created": True,
                        "verified": True,
                        "fix_attempts": attempt + 1,
                        "keywords": keywords,
                        "fallback_workers": fallback_workers,
                        **plugin,
                    }
                current_code = fixed
            except Exception as fix_exc:
                test_error = str(fix_exc)

        # All retries exhausted — write static fallback
        static = self._build_forged_worker_source(worker_kind_str, class_name, intent, name)
        plugin_path.write_text(static, encoding="utf-8")
        self.worker_runtime.reload_plugins(self.config.honeycomb_root)
        self.worker_registry.reload()
        return {
            "worker_kind": worker_kind_str,
            "created": True,
            "verified": False,
            "forge_error": test_error,
            "keywords": keywords,
            "fallback_workers": fallback_workers,
            **plugin,
        }

    def _route_worker_kind(self, intent: str, payload: dict[str, Any], trace_id: str | None = None) -> WorkerKind:
        if intent == "context_curation":
            return WorkerKind.context_curator
        query = str(payload.get("query") or payload.get("topic") or "").strip()
        # File/dir operations: parse action from query, enrich payload, route to FileWorker
        if query:
            file_action = self._infer_file_action(query)
            if file_action:
                payload.update(file_action)
                return WorkerKind.file_system
        details = self.worker_registry.select_worker_details(intent, payload, query)
        worker_kind = details["worker_kind"]
        best_score = details["best_score"]
        content_score = details["content_score"]
        worker_kind_str = details["worker_kind_str"]
        if worker_kind == WorkerKind.custom and worker_kind_str:
            payload["_runtime_worker_key"] = worker_kind_str
        if content_score == 0:
            # No intent/payload/keyword matched — auto-spawn a worker for this intent and use ForgedWorker now
            try:
                spawn = self._auto_spawn_worker(intent, payload)
            except Exception as exc:
                spawn = {
                    "worker_kind": self._normalize_worker_kind(intent),
                    "created": False,
                    "forge_error": str(exc),
                }
            if trace_id:
                self.honeycomb.write_event(
                    trace_id,
                    {
                        "kind": "auto_worker_spawn",
                        "intent": intent,
                        "content_score": content_score,
                        "best_score": best_score,
                        **spawn,
                    },
                )
            if spawn.get("verified") and spawn.get("worker_kind"):
                payload["_runtime_worker_key"] = spawn["worker_kind"]
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
        elif task.worker_kind == WorkerKind.context_curator:
            blueprint_id = self.config.worker_context_curator_blueprint_id
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
        scheduler_backend: str,
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
        result = self._execute_worker_task(
            policy_task,
            context,
            scheduler_backend=scheduler_backend,
            parent_span_id=parent_span_id,
        )
        return result, None

    def _execute_worker_task(
        self,
        task: TaskEnvelope,
        context: WorkerContext,
        scheduler_backend: str,
        parent_span_id: str | None = None,
    ) -> ResultEnvelope:
        backend = scheduler_backend.strip().lower()
        if backend == "temporal":
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
        if backend == "celery":
            scheduler = self.scheduler if isinstance(self.scheduler, CeleryScheduler) else self._build_celery_scheduler()
            job_id = scheduler.submit(
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
            payload = scheduler.collect(job_id, timeout_seconds=self.config.scheduler_timeout_seconds)
            return ResultEnvelope.model_validate(payload)
        if backend == "inline":
            scheduler = self.scheduler if isinstance(self.scheduler, InlineScheduler) else self._build_inline_scheduler()
            job_id = scheduler.submit(
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
            payload = scheduler.collect(job_id, timeout_seconds=self.config.scheduler_timeout_seconds)
            return ResultEnvelope.model_validate(payload)
        # Unknown scheduler values should not break execution.
        return self.worker_runtime.run_once(task, context, parent_span_id=parent_span_id)

    def _run_tool_loop(
        self,
        queen_trace_id: str,
        payload: dict[str, Any],
        status_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any] | None:
        """Run the model-driven tool loop. Returns result dict for run() or None on failure/fallback."""
        if self._tool_loop_engine is None or self._tool_registry is None or self._llm_router is None:
            return None
        query = str(payload.get("query") or payload.get("topic") or "").strip()
        if not query:
            return None
        prior = payload.get("messages") or []
        initial_messages: list[dict[str, Any]] = []
        for m in prior[:20]:
            if isinstance(m, dict) and m.get("role") in ("user", "assistant", "system"):
                initial_messages.append({"role": m.get("role", "user"), "content": m.get("content", "") or ""})
        initial_messages.append({"role": "user", "content": query})

        model_override = (payload.get("model_override") or "").strip() or None

        def decision_fn(messages: list[dict[str, Any]], tool_schemas: list[dict[str, Any]]) -> dict[str, Any]:
            decision = self._llm_router.call_with_tools(
                messages,
                tool_schemas,
                model_override=model_override,
            )
            return {
                "tool_calls": [{"name": tc.get("name"), "arguments": tc.get("arguments", {})} for tc in (decision.tool_calls or [])],
                "final_text": decision.final_text,
                "error": decision.error,
            }

        if status_callback:
            try:
                status_callback("Running model-driven tool loop…")
            except Exception:
                pass
        context = {"trace_id": queen_trace_id, "status_callback": status_callback}
        final = self._tool_loop_engine.run(
            queen_trace_id,
            initial_messages,
            decision_fn=decision_fn,
            context=context,
        )
        self.honeycomb.write_event(
            queen_trace_id,
            {"kind": "tool_loop_complete", "status": final.status, "step_count": final.step_count},
        )
        return {
            "final_text": final.final_text,
            "tool_trace": final.tool_trace,
            "cost_metrics": final.cost_metrics.model_dump(mode="json"),
            "status": final.status,
            "step_count": final.step_count,
        }

    # (operation, compiled_regex, path_group, content_group_or_None)
    _FILE_ACTION_PATTERNS: list[tuple[str, Any, int, int | None]] = []

    @classmethod
    def _build_file_action_patterns(cls) -> None:
        cls._FILE_ACTION_PATTERNS = [
            ("write",  re.compile(r'create\s+(?:a\s+)?file\s+["\']?(\S+?)["\']?\s+with\s+content\s+(.+)',   re.IGNORECASE | re.DOTALL), 1, 2),
            ("write",  re.compile(r'write\s+["\']?(.+?)["\']?\s+to\s+(?:file\s+)?["\']?(\S+?)["\']?\s*$',  re.IGNORECASE | re.DOTALL), 2, 1),
            ("write",  re.compile(r'save\s+["\']?(.+?)["\']?\s+(?:to|as)\s+["\']?(\S+?)["\']?\s*$',        re.IGNORECASE | re.DOTALL), 2, 1),
            ("append", re.compile(r'append\s+["\']?(.+?)["\']?\s+to\s+(?:file\s+)?["\']?(\S+?)["\']?\s*$', re.IGNORECASE | re.DOTALL), 2, 1),
            ("delete", re.compile(r'(?:delete|remove|rm)\s+(?:(?:the\s+)?file\s+)?["\']?(\S+\.\S+)["\']?\s*$', re.IGNORECASE), 1, None),
            ("mkdir",  re.compile(r'(?:create|make|mkdir)\s+(?:a\s+)?(?:directory|dir|folder)\s+["\']?(\S+?)["\']?\s*$', re.IGNORECASE), 1, None),
        ]

    @classmethod
    def _infer_file_action(cls, query: str) -> dict[str, Any] | None:
        """Parse file/dir operations from a natural-language query.
        Returns a dict with keys: operation, file_path, content (if applicable).
        Returns None if the query is not a file operation.
        """
        if not cls._FILE_ACTION_PATTERNS:
            cls._build_file_action_patterns()
        for op, pattern, path_grp, content_grp in cls._FILE_ACTION_PATTERNS:
            m = pattern.search(query)
            if m:
                result: dict[str, Any] = {"operation": op, "file_path": m.group(path_grp).strip()}
                if content_grp is not None:
                    result["content"] = m.group(content_grp).strip()
                return result
        return None

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
        # File / directory operations must be delegated, not answered in direct chat
        query = str(payload.get("query") or payload.get("topic") or "").strip()
        if query and self._infer_file_action(query):
            return True
        return False

    _WORKER_STATUS: dict[WorkerKind, str] = {
        WorkerKind.web_search: "Dispatching to web search worker: querying index and synthesizing from sources…",
        WorkerKind.heavy_compute: "Dispatching to heavy compute worker: running analysis…",
        WorkerKind.audit: "Dispatching to audit worker: performing validation…",
        WorkerKind.context_curator: "Dispatching to context curator: extracting durable memory…",
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
        scheduler_backend, scheduler_decision = self._resolve_scheduler_backend(payload)
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
            self.honeycomb.write_event(
                queen_trace_id,
                {"kind": "scheduler_decision", **scheduler_decision},
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
            if self.config.execution_mode in ("model_tools", "hybrid"):
                tool_result = self._run_tool_loop(queen_trace_id, payload, status_callback)
                if tool_result is not None:
                    if self.config.execution_mode == "model_tools" or tool_result.get("status") == "success":
                        cost = tool_result.get("cost_metrics") or {}
                        return {
                            "trace_id": queen_trace_id,
                            "request_id": queen_request_id,
                            "queen_soul_profile_id": self.queen_soul.soul_profile_id,
                            "ollama_base_url": self.config.ollama_base_url,
                            "results": [
                                {
                                    "task_id": str(uuid4()),
                                    "agent_id": "queen-tool-loop",
                                    "worker_kind": WorkerKind.custom.value,
                                    "status": Status.success.value,
                                    "confidence": 0.9,
                                    "output": {
                                        "assistant_reply": tool_result.get("final_text", ""),
                                        "tool_trace": tool_result.get("tool_trace", []),
                                        "synthesis": "Model-driven tool loop.",
                                    },
                                    "cost_metrics": cost,
                                    "output_schema": "QueenToolLoopOutput",
                                }
                            ],
                            "trace_events": self.tracer.events,
                            "semantic_hits_for_intent": self.honeycomb.semantic_search(intent),
                        }
            if not self._should_delegate_to_workers(payload):
                query = str(payload.get("query") or payload.get("topic") or intent).strip()
                if query:
                    _emit("Analyzing request and determining execution path…")
                    context_bundle = build_context_bundle(
                        query=query,
                        payload=payload,
                        honeycomb=self.honeycomb,
                        honeycomb_root=self.config.honeycomb_root,
                    )
                    self.honeycomb.write_event(
                        queen_trace_id,
                        {"kind": "context_bundle", "phase": "direct", **context_bundle.get("diagnostics", {})},
                    )
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
                    md_memories = context_bundle.get("md_memory_context") or []
                    if md_memories:
                        queen_context = queen_context + "\n\n## Markdown memory context\n" + "\n".join(f"- {m}" for m in md_memories)
                    semantic_context = context_bundle.get("semantic_context") or []
                    if semantic_context:
                        queen_context = queen_context + "\n\n## Semantic memory context\n" + "\n".join(f"- {m}" for m in semantic_context)
                    messages = context_bundle.get("messages") or []
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
                context_bundle = build_context_bundle(
                    query=query_or_intent,
                    payload=payload,
                    honeycomb=self.honeycomb,
                    honeycomb_root=self.config.honeycomb_root,
                )
                self.honeycomb.write_event(
                    queen_trace_id,
                    {"kind": "context_bundle", "phase": "delegated", **context_bundle.get("diagnostics", {})},
                )
                payload["messages"] = context_bundle.get("messages") or []
                payload["user_memories"] = context_bundle.get("user_memories") or []
                payload["_context_bundle"] = context_bundle
                queen_mems = self.honeycomb.read_queen_memories(limit=10)
                semantic_hits = self.honeycomb.semantic_search_with_content(query_or_intent, limit=5)
                md_hits = context_bundle.get("md_memory_context") or []
                if queen_mems:
                    payload["_queen_memories"] = [m.get("content", "") for m in queen_mems[:10] if m.get("content")]
                if semantic_hits:
                    payload["_semantic_context"] = [text for _, text in semantic_hits if text and text.strip()][:5]
                if md_hits:
                    payload["_md_memory_context"] = md_hits[:6]
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
                        task,
                        scheduler_backend=scheduler_backend,
                        parent_span_id=queen_span,
                        status_callback=status_callback,
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
