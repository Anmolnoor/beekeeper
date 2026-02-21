from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "v1"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Status(str, Enum):
    queued = "queued"
    running = "running"
    success = "success"
    failed = "failed"
    blocked = "blocked"


class TrustTier(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class WorkerKind(str, Enum):
    web_search = "web_search"
    heavy_compute = "heavy_compute"
    audit = "audit"
    monitor = "monitor"
    logger = "logger"
    custom = "custom"


class ProfileType(str, Enum):
    soul = "soul"
    abilities = "abilities"
    accountabilities = "accountabilities"
    rules = "rules"
    guardrails = "guardrails"
    skills = "skills"


class AbilitiesProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abilities_profile_id: str
    name: str
    capabilities: list[str] = Field(default_factory=list)
    tool_allowlist: list[str] = Field(default_factory=list)
    max_parallel_tools: int = 2
    version: str = SCHEMA_VERSION


class AccountabilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accountability_id: str
    name: str
    owner: str = "platform"
    must_emit_audit_log: bool = True
    max_unapproved_actions: int = 0
    requires_trace_for_all_actions: bool = True
    version: str = SCHEMA_VERSION


class GuardrailProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guardrail_profile_id: str
    name: str
    enabled_guardrails: list[str] = Field(default_factory=list)
    allow_external_network: bool = True
    enforce_domain_allowlist: bool = True
    version: str = SCHEMA_VERSION


class ProfileBundleRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    soul_id: str
    abilities_id: str
    accountabilities_id: str
    rules_id: str
    guardrails_id: str
    skills_id: str


class AgentBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blueprint_id: str
    name: str
    agent_type: Literal["queen", "worker"]
    worker_kind: WorkerKind | None = None
    trust_tier: TrustTier = TrustTier.medium
    profile_bundle: ProfileBundleRef
    tags: list[str] = Field(default_factory=list)
    is_template: bool = False
    version: str = SCHEMA_VERSION


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    kind: Literal["report", "json", "text", "log", "binary", "other"] = "other"
    location: str
    checksum: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class CostMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_name: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0


class AgentIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_type: str
    skill_profile_id: str
    soul_profile_id: str
    trust_tier: TrustTier = TrustTier.medium
    version: str = SCHEMA_VERSION


class SkillProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_profile_id: str
    name: str
    description: str
    when_to_use: str | None = Field(default=None, description="Trigger scenarios (Agent Skills standard: when to apply)")
    tool_allowlist: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    can_search_web: bool = False
    can_execute_code: bool = False
    max_parallel_tools: int = 2
    version: str = SCHEMA_VERSION


class RuleProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_profile_id: str
    name: str
    hard_budget_usd: float = 2.0
    max_runtime_seconds: int = 120
    max_retries: int = 2
    allowed_domains: list[str] = Field(default_factory=list)
    disallowed_tools: list[str] = Field(default_factory=list)
    require_human_approval_for: list[str] = Field(default_factory=list)
    version: str = SCHEMA_VERSION


class SoulProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    soul_profile_id: str
    name: str
    tone: Literal["neutral", "concise", "detailed", "assertive"] = "neutral"
    risk_appetite: Literal["low", "balanced", "high"] = "balanced"
    verbosity: Literal["low", "medium", "high"] = "medium"
    escalation_style: Literal["strict", "balanced", "lenient"] = "balanced"
    traits: dict[str, Any] = Field(default_factory=dict)
    version: str = SCHEMA_VERSION


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    status: Literal["approve", "block", "needs_human"]
    reason: str
    guardrail_flags: list[str] = Field(default_factory=list)
    requires_human_approval: bool = False
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    version: str = SCHEMA_VERSION


class RetryCategory(str, Enum):
    transient = "transient"
    tool = "tool"
    model = "model"
    policy = "policy"
    quality = "quality"


class WorkerPerformanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(default_factory=lambda: str(uuid4()))
    trace_id: str
    task_id: str
    worker_kind: WorkerKind
    status: Status
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0
    failure_reason: str | None = None
    retry_category: RetryCategory | None = None
    created_at: datetime = Field(default_factory=utcnow)
    version: str = SCHEMA_VERSION


class RoutingFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_kind: WorkerKind
    total_runs: int = 0
    success_runs: int = 0
    avg_quality: float = 0.0
    avg_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    recent_quality_ema: float = 0.0
    by_intent: dict[str, dict[str, float]] = Field(default_factory=dict)
    by_skill: dict[str, dict[str, float]] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utcnow)
    version: str = SCHEMA_VERSION


class WebEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    domain: str
    url: str | None = None
    snippet: str
    source: str = "unknown"
    relevance: float = Field(default=0.5, ge=0.0, le=1.0)


class HumanReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    trace_id: str
    task_type: str
    reason: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "approved", "rejected"] = "pending"
    requested_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None
    version: str = SCHEMA_VERSION


class WebSearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    evidence: list[WebEvidence] = Field(default_factory=list)
    assistant_reply: str
    response_source: Literal["ollama", "gemini", "fallback"] = "fallback"
    synthesis: str


class HeavyComputeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str
    sample_size: int
    aggregate: dict[str, float] = Field(default_factory=dict)
    notes: str


class AuditFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["low", "medium", "high"]
    code: str
    detail: str


class AuditOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_task_id: str
    score: float = Field(default=0.5, ge=0.0, le=1.0)
    findings: list[AuditFinding] = Field(default_factory=list)
    verdict: Literal["pass", "review", "fail"] = "review"


class TaskEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    parent_id: str | None = None
    queen_trace_id: str
    queen_request_id: str
    task_type: str
    worker_kind: WorkerKind = WorkerKind.web_search
    payload: dict[str, Any] = Field(default_factory=dict)
    required_skills: list[str] = Field(default_factory=list)
    trust_tier: TrustTier = TrustTier.medium
    deadline_at: datetime | None = None
    budget_usd: float = 1.0
    max_retries: int = 2
    idempotency_key: str
    status: Status = Status.queued
    created_at: datetime = Field(default_factory=utcnow)
    version: str = SCHEMA_VERSION


class ResultEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    agent_id: str
    worker_kind: WorkerKind
    status: Status
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    output: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    policy_flags: list[str] = Field(default_factory=list)
    cost_metrics: CostMetrics = Field(default_factory=CostMetrics)
    created_at: datetime = Field(default_factory=utcnow)
    output_schema: str = "generic"
    version: str = SCHEMA_VERSION


class QueenActionRequest(BaseModel):
    """A single action the Queen wants to execute."""
    model_config = ConfigDict(extra="forbid")

    action_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""
    triggered_by: str = "queen"
    created_at: datetime = Field(default_factory=utcnow)


class QueenActionResult(BaseModel):
    """Result of a Queen action execution, including any memories to persist."""
    model_config = ConfigDict(extra="forbid")

    action_name: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    memory_snippets: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
