from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import threading
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
from .profile_service import ProfileService
from .response_aggregation_service import ResponseAggregationService
from .user_policy import UserPolicy
from .queen_updates import write_queen_update
from .queen_actions import ActionContext, QueenActionLoop, build_default_action_registry
from .tool_adapters import register_action_tools, register_worker_tools
from .tool_runtime import ToolExecutionPolicy, ToolExecutor, ToolLoopEngine, ToolRegistry
from .llm_provider import build_llm_router
from .runtime_env import resolve_llm_providers, resolve_searxng_base_url
from .config import RuntimeMode, resolve_runtime_mode
from .governance import (
    CapabilityManifestRegistry,
    build_policy_adapter,
    adapter_decision_to_policy,
    build_manifest_from_skill_rule,
)
from .governance.tool_broker import LocalToolBroker


_SHELL_TASK_KEYWORDS = re.compile(
    r'(?:'
    # Unambiguous shell commands — always route to bash
    r'\b(?:mv|cp|chmod|mkdir|curl)\b'
    # Tilde path — always a filesystem reference
    r'|~/'
    # move/copy/rename require a file/folder/path context to avoid "move on", "copy that"
    r'|\b(?:move|copy|rename)\b.{0,60}?\b(?:file|folder|dir(?:ectory)?|\.[\w]{1,6}|~\/|\/\w)\b'
    # find/list/delete/remove only when followed by file/folder nouns
    r'|\b(?:find|list|delete|remove)\b\s+(?:(?:the|all|my|a)\s+)?(?:file|files|folder|folders|dir(?:ectory|ectories)?)\b'
    # create/make a dir or folder
    r'|\b(?:create|make)\s+(?:a\s+)?(?:dir(?:ectory)?|folder)\b'
    # save/write to a path (must end with extension or start with ~/ or /)
    r'|\b(?:save|write)\b.{0,80}?(?:to|as|in)\s+(?:~\/|\/|\S+\.(?:md|txt|json|csv|log|py|sh|yaml|yml))\b'
    r')',
    re.IGNORECASE | re.DOTALL,
)


def _looks_like_shell_task(query: str) -> bool:
    return bool(_SHELL_TASK_KEYWORDS.search(query))


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
    llm_provider: str = field(default_factory=lambda: os.getenv("BEEKEEPER_LLM_PROVIDER", "openai"))
    llm_providers: str = field(default_factory=lambda: os.getenv("BEEKEEPER_LLM_PROVIDERS", "openai,gemini,ollama"))
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
    searxng_base_url: str = field(default_factory=resolve_searxng_base_url)
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
                durable_state_dsn=os.getenv("BEEKEEPER_DATABASE_DSN") or None,
                durable_state_backend=os.getenv("BEEKEEPER_DATABASE_BACKEND") or None,
                artifact_backend=os.getenv("BEEKEEPER_ARTIFACT_BACKEND", "local"),
                artifact_bucket=os.getenv("BEEKEEPER_OBJECT_STORAGE_BUCKET") or None,
                artifact_endpoint=os.getenv("BEEKEEPER_OBJECT_STORAGE_ENDPOINT") or None,
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
        self.capability_manifests = CapabilityManifestRegistry()
        self.policy_adapter = build_policy_adapter()
        ensure_queen_context_file(config.honeycomb_root)
        self._seed_defaults()
        queen_blueprint = self.registry.get_blueprint(self.config.queen_blueprint_id)
        queen_profiles = self.registry.resolve_profiles(queen_blueprint.blueprint_id)
        self.queen_soul = queen_profiles.soul
        self.autonomy_policy = self.config.autonomy_policy or DEFAULT_AUTONOMY_POLICY
        self._action_registry = build_default_action_registry()
        self._llm_router = build_llm_router(
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
        )
        self._plugin_reload_lock = threading.Lock()
        self.profile_service = ProfileService()
        self.response_aggregation_service = ResponseAggregationService()
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
                rule = self.registry.resolve_profiles(self.config.queen_blueprint_id).rule
                manifest = self.capability_manifests.get(self.config.queen_blueprint_id)
                decision = self.policy_adapter.evaluate_tool_call(
                    tool_name=tool_name,
                    arguments=arguments,
                    rule_profile=rule,
                    capability_manifest=manifest,
                )
                if decision.decision == "deny":
                    return False, ",".join(decision.reason_codes) if decision.reason_codes else "tool_policy_denied", False
                if decision.decision == "escalate":
                    return True, None, True
                return True, None, False

            self._tool_executor = ToolExecutor(
                self._tool_registry,
                honeycomb=self.honeycomb,
                policy=policy,
                tool_guardrail_fn=_tool_guardrail,
                tool_broker=LocalToolBroker(self.honeycomb),
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
        runtime_mode = resolve_runtime_mode()
        if requested in {"inline", "celery", "temporal"}:
            if requested == "inline" and runtime_mode is not RuntimeMode.DEV:
                temporal_ready = self._can_connect_temporal()
                celery_ready = self._can_connect_celery()
                if temporal_ready:
                    return "temporal", {
                        "requested": requested,
                        "selected": "temporal",
                        "reason": "inline_disallowed_non_dev_temporal_selected",
                        "runtime_mode": runtime_mode.value,
                        "celery_ready": celery_ready,
                        "temporal_ready": temporal_ready,
                    }
                if celery_ready:
                    return "celery", {
                        "requested": requested,
                        "selected": "celery",
                        "reason": "inline_disallowed_non_dev_celery_selected",
                        "runtime_mode": runtime_mode.value,
                        "celery_ready": celery_ready,
                        "temporal_ready": temporal_ready,
                    }
                raise RuntimeError("inline_scheduler_not_allowed_in_non_dev_without_queue_backend")
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
                allowed_domains=["docs.python.org", "openai.com", "github.com", "linkedin.com"],
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
        queen_resolved = self.registry.resolve_profiles("blueprint.queen.default")
        self.capability_manifests.register(
            build_manifest_from_skill_rule(
                manifest_id="manifest.queen.default",
                subject_id="blueprint.queen.default",
                worker_kind=WorkerKind.web_search,
                skill=self.registry.get_skill("skill.research.web"),
                rule=queen_resolved.rule,
                sandbox_tier=0,
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
        context_resolved = self.registry.resolve_profiles("blueprint.worker.context_curator")
        self.capability_manifests.register(
            build_manifest_from_skill_rule(
                manifest_id="manifest.worker.context_curator",
                subject_id="blueprint.worker.context_curator",
                worker_kind=WorkerKind.context_curator,
                skill=self.registry.get_skill("skill.context.curator"),
                rule=context_resolved.rule,
                sandbox_tier=0,
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
        web_resolved = self.registry.resolve_profiles("blueprint.worker.web")
        self.capability_manifests.register(
            build_manifest_from_skill_rule(
                manifest_id="manifest.worker.web",
                subject_id="blueprint.worker.web",
                worker_kind=WorkerKind.web_search,
                skill=self.registry.get_skill("skill.research.web"),
                rule=web_resolved.rule,
                sandbox_tier=0,
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
        heavy_resolved = self.registry.resolve_profiles("blueprint.worker.heavy")
        self.capability_manifests.register(
            build_manifest_from_skill_rule(
                manifest_id="manifest.worker.heavy",
                subject_id="blueprint.worker.heavy",
                worker_kind=WorkerKind.heavy_compute,
                skill=self.registry.get_skill("skill.compute.heavy"),
                rule=heavy_resolved.rule,
                sandbox_tier=1,
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
        audit_resolved = self.registry.resolve_profiles("blueprint.worker.audit")
        self.capability_manifests.register(
            build_manifest_from_skill_rule(
                manifest_id="manifest.worker.audit",
                subject_id="blueprint.worker.audit",
                worker_kind=WorkerKind.audit,
                skill=self.registry.get_skill("skill.monitor.audit"),
                rule=audit_resolved.rule,
                sandbox_tier=0,
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
        try:
            plugin = self._ensure_worker_plugin(worker_kind_str, intent=intent, name=name, payload=payload)
        except Exception as spawn_exc:
            return {"worker_kind": worker_kind_str, "created": False, "plugin_error": str(spawn_exc)}
        with self._plugin_reload_lock:
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
                with self._plugin_reload_lock:
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
        with self._plugin_reload_lock:
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

    _SKILL_CREATION_PHRASES = (
        "create a skill",
        "build a skill",
        "make a skill",
        "create a worker",
        "build a worker",
        "make a worker",
        "make a tool",
        "build a tool",
        "create a tool",
        "teach you to",
        "teach you how to",
        "add a skill",
        "new skill that",
        "new worker that",
    )

    def _detect_skill_creation_intent(self, query: str) -> bool:
        """Return True if the query is asking to create a new skill/worker/tool."""
        lower = query.lower()
        return any(phrase in lower for phrase in self._SKILL_CREATION_PHRASES)

    def _classify_intent_with_llm(self, query: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Use the LLM to classify query intent and suggest a worker.

        Returns dict with keys: intent, worker_hint, tags, needs_delegation.
        Falls back to empty dict on any error (routing continues algorithmically).
        """
        try:
            dynamic_workers = self.worker_registry.format_workers_for_prompt()
            if not dynamic_workers:
                return {}
            classification_prompt = (
                "You are routing a user request. Given the available workers below, "
                "respond with JSON only — no explanation, no markdown fences:\n"
                '{"intent": "<short_snake_case_intent>", "worker_hint": "<worker_kind or empty string>", '
                '"tags": ["tag1", "tag2"], "needs_delegation": true}\n\n'
                f"{dynamic_workers}\n\n"
                f"User query: {query}"
            )
            reply, _src = self.worker_runtime.direct_chat(
                query=classification_prompt,
                system="You are a routing classifier. Return only valid JSON.",
            )
            if not reply:
                return {}
            # Extract the first JSON object from the reply
            json_match = re.search(r"\{[^{}]*\}", reply, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return json.loads(reply.strip())
        except Exception:
            return {}

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
            # Complex file/shell ops: route to BashWorker when query looks like a shell task
            # but didn't match FileWorker's strict patterns
            if _looks_like_shell_task(query):
                save_requested, _ = self._extract_save_to_file_request(query)
                if save_requested and re.search(r"(?i)\b(report|summary|findings?|research)\b", query):
                    # Save-intent on a report request should stay in content-generation flow,
                    # then be saved by post-processing.
                    pass
                else:
                    return WorkerKind.bash
        # Extract LLM classification hints stored by caller
        llm_tags: list[str] = payload.pop("_llm_tags", None) or []
        worker_hint: str = str(payload.pop("_worker_hint", "") or "").strip()
        # If LLM is confident about a specific worker kind, use it directly
        if worker_hint:
            registered_kinds = {w.get("worker_kind", "") for w in self.worker_registry.list_workers()}
            if worker_hint in registered_kinds:
                try:
                    return WorkerKind(worker_hint)
                except ValueError:
                    # custom worker kind — set runtime key and return custom
                    payload["_runtime_worker_key"] = worker_hint
                    return WorkerKind.custom
        details = self.worker_registry.select_worker_details(intent, payload, query, llm_tags=llm_tags or None)
        worker_kind = details["worker_kind"]
        best_score = details["best_score"]
        content_score = details["content_score"]
        worker_kind_str = details["worker_kind_str"]
        if worker_kind == WorkerKind.custom and worker_kind_str:
            payload["_runtime_worker_key"] = worker_kind_str
        if content_score == 0:
            # No intent/payload/keyword matched — fire auto-spawn in background so THIS
            # request returns immediately (ForgedWorker), and the generated worker is
            # available for the NEXT request with the same intent.
            worker_kind_str_bg = self._normalize_worker_kind(intent)
            existing_bg = next(
                (w for w in self.worker_registry.list_workers()
                 if w.get("worker_kind") == worker_kind_str_bg),
                None,
            )
            if not existing_bg:
                threading.Thread(
                    target=self._auto_spawn_worker,
                    args=(intent, dict(payload)),
                    daemon=True,
                    name=f"auto_spawn_{worker_kind_str_bg}",
                ).start()
                if trace_id:
                    self.honeycomb.write_event(
                        trace_id,
                        {
                            "kind": "auto_spawn_started",
                            "worker_kind": worker_kind_str_bg,
                            "intent": intent,
                            "content_score": content_score,
                        },
                    )
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
        capability_manifest = self.capability_manifests.get(blueprint_id)
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
            capability_manifest=capability_manifest,
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
        base_policy = self.guardrail_engine.evaluate(policy_task, context.rule)
        adapter_decision = self.policy_adapter.evaluate_task(
            task=policy_task,
            rule_profile=context.rule,
            capability_manifest=context.capability_manifest,
            base_policy=base_policy,
        )
        policy = adapter_decision_to_policy(policy_task.task_id, adapter_decision)
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
                        "capability_manifest": context.capability_manifest.to_dict() if context.capability_manifest else None,
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
                    "capability_manifest": context.capability_manifest.to_dict() if context.capability_manifest else None,
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
                    "capability_manifest": context.capability_manifest.to_dict() if context.capability_manifest else None,
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

    # Patterns that detect "save results to a file" post-processing intent
    _SAVE_TO_FILE_PATTERNS: list[Any] = []
    _UNVERIFIED_SAVE_CLAIM_RE = re.compile(
        r"(?i)(?:report|file)?\s*(?:has\s+been\s+|was\s+)?saved\s+(?:to|at)\s+[`'\"]?[^`'\"\n]+(?:\.\w+)?[`'\"]?"
    )
    _SAVE_PATH_SECTION_RE = re.compile(
        r"(?is)\n*#{1,6}[^\n]*(?:file path information|path information|exact file path)[^\n]*\n.*?(?=\n#{1,6}\s|\Z)"
    )
    _SAVE_CLAIM_LINE_RE = re.compile(
        r"(?im)^.*\b(?:saved|stored|written|mirrored|prepared)\b.*(?:path|file|report).*$"
    )
    _PATH_NOTE_LINE_RE = re.compile(
        r"(?im)^.*(?:/home/|~/|[a-zA-Z]:\\|`[^`\n]+(?:\.md|\.txt|\.json|\.csv|\.html)`).*$"
    )
    _SAVE_VERB_RE = re.compile(r"(?i)\b(save|write|export|store)\b")
    _FILE_HINT_RE = re.compile(r"(?i)(?:\bfile\b|markdown|text|\.(?:md|txt|json|csv|html|rst)\b)")

    @classmethod
    def _build_save_to_file_patterns(cls) -> None:
        cls._SAVE_TO_FILE_PATTERNS = [
            # "save it in a markdown file", "save it as report.md", "save to file.txt"
            re.compile(r'save\s+(?:it\s+)?(?:in|as|to)\s+(?:a\s+)?(?:markdown\s+file|(?:(?:a\s+)?(?:[\w\-]+\.(md|txt|json|csv|html|rst))))(?:\s+named?\s+["\']?(?P<fname>[\w\-\.]+)["\']?)?', re.IGNORECASE),
            # "and save it in a markdown file named foo.md"
            re.compile(
                r'save\s+(?:(?:it|the\s+(?:results?|report|output|data))\s+)?'
                r'(?:in|as|to)\s+(?:an?\s+)?(?:markdown|text|\.?md)\s+file\s+'
                r'(?:named?\s+)?["\']?(?P<fname>[\w\-\.]+\.(?:md|txt|json|csv|html))["\']?',
                re.IGNORECASE,
            ),
            # "save it in local as foo.md", "save report locally as foo.md"
            re.compile(
                r'save\s+(?:(?:it|the\s+(?:results?|report|output|data))\s+)?'
                r'(?:in\s+(?:local|locally)|locally)\s+as\s+["\']?(?P<fname>[\w\-\.]+\.(?:md|txt|json|csv|html))["\']?',
                re.IGNORECASE,
            ),
            # "write (/save) the results/report/output to foo.md"
            re.compile(r'(?:write|save)\s+(?:the\s+)?(?:results?|report|output|data|findings?|info(?:rmation)?)\s+(?:to|as|into?)\s+["\']?(?P<fname>[\w\-\.]+\.(?:md|txt|json|csv|html))["\']?', re.IGNORECASE),
            # "create a report ... save ..."  with explicit filename anywhere
            re.compile(r'\b(?:save|write|export|store)\s+(?:it\s+)?(?:to|as|in(?:to)?)\s+["\']?(?P<fname>[\w\-\.]+\.(?:md|txt|json|csv|html))["\']?', re.IGNORECASE),
            # "make/create/generate a report file in/at downloads" (no explicit filename)
            re.compile(
                r'(?:make|create|generate|write|produce)\s+(?:a\s+)?(?:report|summary|notes?|file)\s+(?:file\s+)?'
                r'(?:for\s+me\s+)?(?:in|at|to|into)\s+(?:the\s+)?'
                r'(?P<dir>downloads?(?:\s+dir(?:ectory)?)?|download\s+(?:dir(?:ectory)?|folder)|~/\S+)',
                re.IGNORECASE,
            ),
            # "put/store a report in downloads folder"
            re.compile(
                r'(?:put|store|place|save)\s+(?:a\s+)?(?:report|summary|notes?|results?|output)\s+'
                r'(?:file\s+)?(?:in|at|into)\s+(?:the\s+)?'
                r'(?P<dir>downloads?(?:\s+dir(?:ectory)?)?|download\s+(?:dir(?:ectory)?|folder)|~/\S+)',
                re.IGNORECASE,
            ),
        ]

    @classmethod
    def _extract_save_to_file_request(cls, query: str) -> tuple[bool, str]:
        """Return (should_save, filepath). filepath is absolute when a directory is captured."""
        if not cls._SAVE_TO_FILE_PATTERNS:
            cls._build_save_to_file_patterns()
        stopwords = {"a","an","the","and","or","to","in","as","is","it","for","of","on","at","by","from","with","that","this","go","create","make","generate","save","write","report","file","please","can","you","me"}
        for pattern in cls._SAVE_TO_FILE_PATTERNS:
            m = pattern.search(query)
            if m:
                groups = m.groupdict()
                # Directory-based patterns — resolve to absolute path + auto filename
                dir_match = groups.get("dir")
                if dir_match:
                    dir_lower = dir_match.strip().lower()
                    if "download" in dir_lower:
                        base = Path.home() / "Downloads"
                    else:
                        base = Path(dir_match).expanduser()
                    words = re.findall(r'\b[a-zA-Z0-9_\-]+\b', query.lower())
                    slug_words = [w for w in words if w not in stopwords][:4]
                    fname = ("_".join(slug_words) or "report") + ".md"
                    return True, str(base / fname)
                # Explicit filename patterns
                try:
                    fname = groups.get("fname") or m.group("fname")
                except IndexError:
                    fname = None
                if not fname:
                    words = re.findall(r'\b[a-zA-Z0-9_\-]+\b', query.lower())
                    slug_words = [w for w in words if w not in stopwords][:4]
                    fname = ("_".join(slug_words) or "report") + ".md"
                fname = fname.rstrip(".,;:!?")
                return True, fname
        return False, ""

    @classmethod
    def _query_requests_file_save(cls, query: str) -> bool:
        return bool(cls._SAVE_VERB_RE.search(query) and cls._FILE_HINT_RE.search(query))

    @classmethod
    def _remove_unverified_save_claims(cls, text: str) -> str:
        cleaned = cls._SAVE_PATH_SECTION_RE.sub("\n", text or "")
        cleaned = cls._UNVERIFIED_SAVE_CLAIM_RE.sub("", cleaned)
        lines: list[str] = []
        for line in cleaned.splitlines():
            if cls._SAVE_CLAIM_LINE_RE.search(line):
                continue
            if cls._PATH_NOTE_LINE_RE.search(line) and any(
                marker in line.lower() for marker in ("path", "saved", "stored", "mirrored", "report has been prepared")
            ):
                continue
            if cls._PATH_NOTE_LINE_RE.search(line) and line.strip().startswith(("**`", "`")):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    @classmethod
    def _canonicalize_save_reply(
        cls,
        existing: str,
        *,
        save_requested: bool,
        save_succeeded: bool,
        save_path: Path | None,
    ) -> str:
        if not save_requested:
            return existing
        cleaned = cls._remove_unverified_save_claims(existing or "")
        if save_succeeded and save_path is not None:
            suffix = f"\n\n---\n\n**Report saved to:** `{save_path}`"
            return (cleaned + suffix) if cleaned else f"Report saved to `{save_path}`"
        failure = "I could not save the requested file. Please try again with a writable path."
        if not cleaned:
            return failure
        if cleaned.endswith((".", "!", "?")):
            return f"{cleaned}\n\n{failure}"
        return f"{cleaned}.\n\n{failure}"

    @staticmethod
    def _response_slot(output: dict[str, Any]) -> tuple[str, str]:
        for key in ("assistant_reply", "answer", "summary", "text", "synthesis"):
            value = output.get(key)
            if isinstance(value, str):
                return key, value
        return "assistant_reply", ""

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
            ("read",   re.compile(r'(?:open|read|show|display|cat|print|view)\s+(?:(?:the|file)\s+)?["\']?(\S+\.\S+)["\']?\s*$', re.IGNORECASE), 1, None),
        ]

    @classmethod
    def _infer_file_action(cls, query: str) -> dict[str, Any] | None:
        """Parse file/dir operations from a natural-language query.
        Returns a dict with keys: operation, file_path, content (if applicable).
        Returns None if the query is not a file operation.
        """
        if not cls._FILE_ACTION_PATTERNS:
            cls._build_file_action_patterns()
        lower_query = query.lower()
        save_requested, _ = cls._extract_save_to_file_request(query)
        for op, pattern, path_grp, content_grp in cls._FILE_ACTION_PATTERNS:
            m = pattern.search(query)
            if m:
                result: dict[str, Any] = {"operation": op, "file_path": m.group(path_grp).strip()}
                if content_grp is not None:
                    content = m.group(content_grp).strip()
                    # Avoid false-positive parse for prompts like:
                    # "create a report ... and save it in local as report.md".
                    # In these cases, "it in local" is not intended file content.
                    if op in {"write", "append"}:
                        collapsed = " ".join(content.lower().split())
                        pronoun_starts = (
                            "it",
                            "it in",
                            "the report",
                            "the output",
                            "the results",
                            "report",
                            "results",
                            "output",
                        )
                        looks_like_placeholder = collapsed.startswith(pronoun_starts)
                        looks_like_save_phrase = (" save " in f" {lower_query} " and " as " in f" {lower_query} ")
                        if looks_like_placeholder and (save_requested or looks_like_save_phrase):
                            return None
                    result["content"] = content
                return result
        return None

    def _select_execution_path(self, payload: dict[str, Any], action_result_present: bool) -> str:
        """Return the name of the execution path that will be (or was) taken."""
        if action_result_present and payload.get("stop_after_actions"):
            return "action_loop"
        if self.config.execution_mode in ("model_tools", "hybrid"):
            return "tool_loop"
        if not self._should_delegate_to_workers(payload):
            return "direct_chat"
        return "worker_delegation"

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
        if query and self._extract_save_to_file_request(query)[0]:
            return True
        if query and _looks_like_shell_task(query):
            return True
        return False

    _WORKER_STATUS: dict[WorkerKind, str] = {
        WorkerKind.web_search: "Dispatching to web search worker: querying index and synthesizing from sources…",
        WorkerKind.heavy_compute: "Dispatching to heavy compute worker: running analysis…",
        WorkerKind.audit: "Dispatching to audit worker: performing validation…",
        WorkerKind.context_curator: "Dispatching to context curator: extracting durable memory…",
        WorkerKind.custom: "Executing task…",
        WorkerKind.bash: "Running shell command…",
    }

    def _run_action_loop(
        self,
        intent: str,
        payload: dict[str, Any],
        trace_id: str,
        status_callback: Callable[[str], None] | None = None,
        user_policy: Any | None = None,
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
            user_policy=user_policy,
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

        queen_trace_id = str(payload.get("_trace_id") or f"trace_{uuid4().hex}")
        queen_request_id = str(payload.get("_request_id") or str(uuid4()))
        admission_recorded = bool(payload.get("_admission_recorded"))
        scheduler_backend, scheduler_decision = self._resolve_scheduler_backend(payload)

        def _record_run_state(state: str, details: dict[str, Any] | None = None) -> None:
            try:
                self.honeycomb.record_run_state(
                    trace_id=queen_trace_id,
                    request_id=queen_request_id,
                    intent=intent,
                    state=state,
                    source=source or "unknown",
                    payload={"scheduler_backend": scheduler_backend},
                    details=details,
                )
            except Exception:
                pass

        if not admission_recorded:
            _record_run_state("requested")
        log_service_call("queen", "called", source=source or "unknown", trace_id=queen_trace_id)
        # Reset per-request mutable state
        self.tracer.reset()
        self.autonomy_policy = self.config.autonomy_policy or DEFAULT_AUTONOMY_POLICY
        profile_resolution = self.profile_service.resolve_autonomy_policy(
            payload,
            default_autonomy_policy=self.config.autonomy_policy or DEFAULT_AUTONOMY_POLICY,
        )
        _user_policy = profile_resolution.user_policy
        self.autonomy_policy = profile_resolution.autonomy_policy
        if session_id and not self.honeycomb.sessions_dir.joinpath(f"{session_id}.json").exists():
            session_id = None
        with self.tracer.span(queen_trace_id, "queen.run") as queen_span:
            if not admission_recorded:
                _record_run_state("admitted")
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
            # ── Skill creation detection: inject create_skill action when user asks in natural language ──
            _query = str(payload.get("query") or payload.get("topic") or "").strip()
            if _query and self._detect_skill_creation_intent(_query) and not payload.get("queen_actions"):
                payload["queen_actions"] = [
                    {"action": "create_skill", "parameters": {"description": _query}}
                ]
                payload["stop_after_actions"] = True
                _emit("Detected skill creation request — building new skill…")
            # ── Action loop: Queen takes direct actions, learns, spawns workers ──
            action_result = self._run_action_loop(intent, payload, queen_trace_id, status_callback, user_policy=_user_policy)
            chosen_path = self._select_execution_path(payload, action_result is not None)
            self.honeycomb.write_event(
                queen_trace_id,
                {
                    "kind": "execution_path",
                    "path": chosen_path,
                    "execution_mode": self.config.execution_mode,
                    "delegate_to_worker": payload.get("delegate_to_worker"),
                    "use_web_search": payload.get("use_web_search"),
                    "has_actions": bool(payload.get("queen_actions")),
                    "stop_after_actions": payload.get("stop_after_actions", False),
                },
            )
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
                    _record_run_state("succeeded", {"path": "action_loop"})
                    return self.response_aggregation_service.build_response(
                        trace_id=queen_trace_id,
                        request_id=queen_request_id,
                        queen_soul_profile_id=self.queen_soul.soul_profile_id,
                        ollama_base_url=self.config.ollama_base_url,
                        action_loop=action_result,
                        trace_events=self.tracer.events,
                        semantic_hits_for_intent=self.honeycomb.semantic_search(intent),
                    )
            if self.config.execution_mode in ("model_tools", "hybrid"):
                tool_result = self._run_tool_loop(queen_trace_id, payload, status_callback)
                if tool_result is not None:
                    if self.config.execution_mode == "model_tools" or tool_result.get("status") == "success":
                        cost = tool_result.get("cost_metrics") or {}
                        _record_run_state("succeeded", {"path": "tool_loop"})
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
                    dynamic_workers = self.worker_registry.format_workers_for_prompt()
                    queen_context = render_queen_context(
                        queen_context, intent=intent, domain=domain, worker_kind="",
                        available_workers=dynamic_workers,
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
                        providers = resolve_llm_providers()
                        assistant_reply = (
                            "I could not reach any configured LLM provider. "
                            f"Resolved provider chain: {','.join(providers)}. "
                            "Check provider credentials and endpoint configuration."
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
                    _record_run_state("succeeded", {"path": "direct_chat"})
                    return self.response_aggregation_service.build_response(
                        trace_id=queen_trace_id,
                        request_id=queen_request_id,
                        queen_soul_profile_id=self.queen_soul.soul_profile_id,
                        ollama_base_url=self.config.ollama_base_url,
                        results=[result],
                        trace_events=self.tracer.events,
                        semantic_hits_for_intent=self.honeycomb.semantic_search(intent),
                    )
            _emit("Decomposing request into executable tasks…")
            _record_run_state("planning", {"path": "worker_delegation"})
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
            # LLM-assisted intent classification: enrich routing before decomposing
            _classify_query = str(payload.get("query") or payload.get("topic") or intent).strip()
            if _classify_query:
                llm_classification = self._classify_intent_with_llm(_classify_query, payload)
                if llm_classification.get("intent"):
                    intent = llm_classification["intent"]
                if llm_classification.get("tags"):
                    payload["_llm_tags"] = llm_classification["tags"]
                if llm_classification.get("worker_hint"):
                    payload["_worker_hint"] = llm_classification["worker_hint"]
                self.honeycomb.write_event(
                    queen_trace_id,
                    {
                        "kind": "llm_classification",
                        "intent": llm_classification.get("intent", ""),
                        "worker_hint": llm_classification.get("worker_hint", ""),
                        "tags": llm_classification.get("tags", []),
                        "needs_delegation": llm_classification.get("needs_delegation"),
                    },
                )
            tasks = self.decompose_intent(queen_trace_id, queen_request_id, intent, payload)
            _record_run_state("queued", {"task_count": len(tasks)})
            _record_run_state("running")
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
                        log_service_call(
                            "queen",
                            "completed",
                            source=source or "unknown",
                            trace_id=queen_trace_id,
                            resource=f"task:{task.task_id}",
                            outcome="success",
                            extra={
                                "worker_kind": str(task.worker_kind),
                                "monitor_action": monitor_decision.action,
                                "monitor_reason": monitor_decision.reason,
                                "quality_score": monitor_decision.quality_score,
                            },
                        )
                        break
                    if monitor_decision.action == "escalate":
                        log_service_call(
                            "queen",
                            "failed",
                            source=source or "unknown",
                            trace_id=queen_trace_id,
                            resource=f"task:{task.task_id}",
                            outcome="failure",
                            error=monitor_decision.reason,
                            extra={
                                "worker_kind": str(task.worker_kind),
                                "monitor_action": monitor_decision.action,
                                "quality_score": monitor_decision.quality_score,
                            },
                        )
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

            # Post-processing: if user requested saving results to a file, do it now
            _orig_query = str(payload.get("query") or payload.get("topic") or intent).strip()
            _should_save, _save_fname = self._extract_save_to_file_request(_orig_query)
            _save_succeeded = False
            _save_path: Path | None = None
            _save_error: str | None = None
            if _should_save and results:
                try:
                    # Collect all assistant replies into one markdown document
                    _parts: list[str] = []
                    for _r in results:
                        _out = _r.output if hasattr(_r, "output") else {}
                        for _k in ("assistant_reply", "answer", "summary", "text", "synthesis"):
                            _v = _out.get(_k) if isinstance(_out, dict) else None
                            if isinstance(_v, str) and _v.strip():
                                _parts.append(_v.strip())
                                break
                    if _parts:
                        _file_content = "\n\n---\n\n".join(_parts)
                        _save_path = Path(_save_fname).expanduser()
                        if not _save_path.is_absolute():
                            _save_path = Path(os.getcwd()) / _save_fname
                        _save_path.parent.mkdir(parents=True, exist_ok=True)
                        _save_path.write_text(_file_content, encoding="utf-8")
                        _save_succeeded = True
                        _emit(f"Saved report to {_save_path}")
                        self.honeycomb.write_event(
                            queen_trace_id,
                            {"kind": "file_saved", "path": str(_save_path), "bytes": len(_file_content.encode())},
                        )
                except Exception as _exc:
                    _save_error = str(_exc)
                    self.honeycomb.write_event(
                        queen_trace_id,
                        {"kind": "file_save_error", "error": _save_error},
                    )

            _save_requested = self._query_requests_file_save(_orig_query)
            if results and _save_requested:
                for _res in results:
                    _out = _res.output if hasattr(_res, "output") else {}
                    if not isinstance(_out, dict):
                        continue
                    _slot, _existing = self._response_slot(_out)
                    _out[_slot] = self._canonicalize_save_reply(
                        _existing,
                        save_requested=True,
                        save_succeeded=_save_succeeded,
                        save_path=_save_path,
                    )
                self.honeycomb.write_event(
                    queen_trace_id,
                    {
                        "kind": "save_reply_canonicalized",
                        "status": "success" if _save_succeeded else "failed",
                        "verified_path": str(_save_path) if _save_path is not None else "",
                        "error": _save_error or "",
                    },
                )
                log_service_call(
                    "queen",
                    "completed" if _save_succeeded else "failed",
                    source=source or "unknown",
                    trace_id=queen_trace_id,
                    resource="report_save_canonicalization",
                    outcome="success" if _save_succeeded else "failure",
                    error=_save_error if not _save_succeeded else None,
                    extra={"save_requested": True, "save_path": str(_save_path) if _save_path else ""},
                )

            terminal_state = self.response_aggregation_service.terminal_state_for_results(results)
            _record_run_state(terminal_state, {"result_count": len(results)})
            return self.response_aggregation_service.build_response(
                trace_id=queen_trace_id,
                request_id=queen_request_id,
                queen_soul_profile_id=self.queen_soul.soul_profile_id,
                ollama_base_url=self.config.ollama_base_url,
                results=results,
                trace_events=self.tracer.events,
                semantic_hits_for_intent=self.honeycomb.semantic_search(intent),
            )


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
