from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import urllib.parse
import urllib.request
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel

from .plugins import load_worker_plugins
from .contracts import (
    AgentIdentity,
    AbilitiesProfile,
    AccountabilityPolicy,
    AuditFinding,
    AuditOutput,
    CostMetrics,
    GuardrailProfile,
    HeavyComputeOutput,
    ResultEnvelope,
    RuleProfile,
    SkillProfile,
    SoulProfile,
    Status,
    TaskEnvelope,
    WebEvidence,
    WebSearchOutput,
    WorkerKind,
)
from .honeycomb import HoneycombConfig, HoneycombStore
from .llm_provider import LLMRouter, build_llm_router
from .tracing import Tracer
from .web_adapters import SearxngAdapter, WebAdapterError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class WorkerContext:
    identity: AgentIdentity
    skill: SkillProfile
    rule: RuleProfile
    soul: SoulProfile
    abilities: AbilitiesProfile | None = None
    accountability: AccountabilityPolicy | None = None
    guardrails: GuardrailProfile | None = None
    status_callback: Callable[[str], None] | None = None


class BaseSpecialistWorker:
    worker_kind: WorkerKind
    output_model: type[BaseModel]

    @staticmethod
    def _emit_status(context: WorkerContext, msg: str) -> None:
        if context.status_callback:
            try:
                context.status_callback(msg)
            except Exception:
                pass

    def preflight(self, task: TaskEnvelope, context: WorkerContext) -> None:
        if task.worker_kind != self.worker_kind:
            raise ValueError(f"worker_kind_mismatch expected={self.worker_kind.value} got={task.worker_kind.value}")

    def execute(self, task: TaskEnvelope, context: WorkerContext) -> dict[str, Any]:
        raise NotImplementedError

    def validate(self, payload: dict[str, Any]) -> BaseModel:
        return self.output_model.model_validate(payload)

    def terminate(self, task: TaskEnvelope, context: WorkerContext) -> None:
        _ = (task, context)


class WebSearchWorker(BaseSpecialistWorker):
    worker_kind = WorkerKind.web_search
    output_model = WebSearchOutput
    
    def __init__(
        self,
        llm_provider: str = "ollama",
        llm_providers: str | None = None,
        ollama_base_url: str = "http://100.99.106.59:11434",
        ollama_model: str = "catsarethebest/qwen2.5-N2:1.5b",
        ollama_timeout_seconds: int = 120,
        gemini_api_key: str = "",
        gemini_model: str = "gemini-1.5-flash",
        gemini_timeout_seconds: int = 120,
        openai_api_key: str = "",
        openai_model: str = "gpt-4o-mini",
        openai_base_url: str | None = None,
        openai_timeout_seconds: int = 120,
        searxng_base_url: str = "http://localhost:8080",
    ) -> None:
        self.llm_provider = (llm_provider or "ollama").strip().lower()
        self.llm_router = build_llm_router(
            llm_providers=llm_providers,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            ollama_timeout_seconds=ollama_timeout_seconds,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            gemini_timeout_seconds=gemini_timeout_seconds,
            openai_api_key=openai_api_key,
            openai_model=openai_model,
            openai_base_url=openai_base_url,
            openai_timeout_seconds=openai_timeout_seconds,
        )
        self.searxng = SearxngAdapter(base_url=searxng_base_url)

    def _assistant_reply(
        self,
        query: str,
        system: str | None = None,
        messages: list[dict[str, str]] | None = None,
        model_tier: str | None = None,
        model_override: str | None = None,
    ) -> tuple[str | None, str]:
        """Call LLM via router with fallback. model_override takes precedence; model_tier selects economy/standard/premium. Returns (text, source)."""
        return self.llm_router.call(
            prompt=query,
            system=system,
            messages=messages,
            model_tier=model_tier,
            model_override=model_override,
        )

    def _domain_from_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        return (parsed.hostname or "").lower()

    def _user_context_system(self, payload: dict[str, Any]) -> str | None:
        """Build system prompt from user memories if present."""
        memories = payload.get("user_memories") or []
        if not isinstance(memories, list) or not memories:
            return None
        lines = []
        for m in memories[:15]:
            if isinstance(m, str):
                lines.append(f"- {m}")
            elif isinstance(m, dict) and m.get("content"):
                lines.append(f"- {m['content']}")
        if not lines:
            return None
        return "User context from past conversations:\n" + "\n".join(lines)

    def execute(self, task: TaskEnvelope, context: WorkerContext) -> dict[str, Any]:
        query = str(task.payload.get("query") or task.payload.get("topic") or task.task_type).strip()
        use_web_search = task.payload.get("use_web_search", False) is True
        user_system = self._user_context_system(task.payload)
        if not use_web_search:
            self._emit_status(context, "Consulting language model for response generation…")
            model_tier = task.payload.get("model_tier")
            assistant_reply, source = self._assistant_reply(
                query, system=user_system, model_tier=model_tier
            )
            if assistant_reply is None:
                assistant_reply = (
                    "I could not reach any configured LLM. "
                    "Ensure Ollama is running (BEEHIVE_OLLAMA_BASE_URL) and/or BEEHIVE_GEMINI_API_KEY is set."
                )
            return WebSearchOutput(
                query=query,
                evidence=[],
                assistant_reply=assistant_reply,
                response_source=source,
                synthesis="Direct chat (Ollama only, no web search).",
            ).model_dump(mode="json")
        domains = list(task.payload.get("domains", [])) or context.rule.allowed_domains or [
            "docs.python.org",
            "github.com",
            "openai.com",
        ]
        allowed_domains = {str(domain).lower() for domain in domains}
        evidence: list[WebEvidence] = []
        search_error: str | None = None
        self._emit_status(context, "Querying search index for relevant sources…")
        try:
            rows = self.searxng.search(query=query, allowed_domains=list(allowed_domains), limit=4)
            fetched_urls: list[str] = []
            for idx, row in enumerate(rows):
                url = str(row.get("url", "")).strip()
                if not url:
                    continue
                domain = self._domain_from_url(url)
                if allowed_domains and domain not in allowed_domains:
                    continue
                fetched_urls.append(url)
                snippet = str(row.get("snippet", "")).strip()
                if not snippet:
                    try:
                        snippet = self.searxng.fetch(url)
                    except WebAdapterError:
                        snippet = f"No snippet available from {domain}."
                if idx == 0:
                    self._emit_status(context, "Retrieving source content and extracting snippets…")
                evidence.append(
                    WebEvidence(
                        title=str(row.get("title", f"{query[:60]} source {idx + 1}")).strip(),
                        domain=domain,
                        url=url,
                        snippet=snippet[:320],
                        source=str(row.get("source", "searxng")),
                        relevance=max(0.3, 0.92 - (idx * 0.15)),
                    )
                )
            task.payload["fetched_urls"] = fetched_urls
        except WebAdapterError as exc:
            search_error = exc.code
        if not evidence:
            for idx, domain in enumerate(list(allowed_domains)[:3]):
                evidence.append(
                    WebEvidence(
                        title=f"{query[:60]} source {idx + 1}",
                        domain=domain,
                        snippet=f"Fallback signal from {domain} for query '{query[:80]}'.",
                        source=f"fallback:{search_error or 'none'}",
                        relevance=max(0.35, 0.9 - (idx * 0.15)),
                    )
                )
        synthesis = f"Synthesized {len(evidence)} evidence points for '{query}'."
        if search_error:
            synthesis += f" SearXNG degraded ({search_error}); fallback evidence used."
        else:
            synthesis += " Primary source: SearXNG."
        self._emit_status(context, "Synthesizing response from gathered evidence…")
        model_tier = task.payload.get("model_tier")
        assistant_reply, source = self._assistant_reply(
            query, system=user_system, model_tier=model_tier
        )
        if assistant_reply is None:
            assistant_reply = (
                f"I could not reach any configured LLM, but I prepared an evidence-backed synthesis for '{query}'. "
                "Ensure Ollama is running (BEEHIVE_OLLAMA_BASE_URL) and/or BEEHIVE_GEMINI_API_KEY is set."
            )
        return WebSearchOutput(
            query=query,
            evidence=evidence,
            assistant_reply=assistant_reply,
            response_source=source,
            synthesis=synthesis,
        ).model_dump(mode="json")


class HeavyComputeWorker(BaseSpecialistWorker):
    worker_kind = WorkerKind.heavy_compute
    output_model = HeavyComputeOutput

    def execute(self, task: TaskEnvelope, context: WorkerContext) -> dict[str, Any]:
        self._emit_status(context, "Running computational analysis on numeric inputs…")
        raw_numbers = task.payload.get("numbers", [])
        numbers = [float(value) for value in raw_numbers if isinstance(value, (int, float))]
        if not numbers:
            seed = max(3, len(str(task.payload.get("query", ""))) // 8)
            numbers = [float(i * i) for i in range(1, seed + 1)]
        sample_size = len(numbers)
        aggregate = {
            "sum": float(sum(numbers)),
            "mean": float(sum(numbers) / sample_size),
            "min": float(min(numbers)),
            "max": float(max(numbers)),
        }
        return HeavyComputeOutput(
            operation=str(task.payload.get("operation", "distribution_summary")),
            sample_size=sample_size,
            aggregate=aggregate,
            notes="Computed deterministic summary metrics over numeric inputs.",
        ).model_dump(mode="json")


class AuditWorker(BaseSpecialistWorker):
    worker_kind = WorkerKind.audit
    output_model = AuditOutput

    def execute(self, task: TaskEnvelope, context: WorkerContext) -> dict[str, Any]:
        self._emit_status(context, "Performing audit and validation of prior result…")
        target_task_id = str(task.payload.get("target_task_id", "")).strip()
        target_result = task.payload.get("target_result")
        findings: list[AuditFinding] = []
        score = 1.0
        if not target_task_id:
            findings.append(AuditFinding(severity="high", code="target_missing", detail="target_task_id is required"))
            score -= 0.6
        if not isinstance(target_result, dict):
            findings.append(
                AuditFinding(
                    severity="medium",
                    code="result_unavailable",
                    detail="target_result payload was unavailable for full audit depth",
                )
            )
            score -= 0.25
        else:
            confidence = float(target_result.get("confidence", 0.0))
            if confidence < 0.7:
                findings.append(
                    AuditFinding(
                        severity="medium",
                        code="low_confidence",
                        detail=f"target_result confidence below threshold: {confidence:.2f}",
                    )
                )
                score -= 0.25
        score = max(0.0, min(1.0, score))
        verdict = "pass" if score >= 0.8 else "review" if score >= 0.55 else "fail"
        return AuditOutput(target_task_id=target_task_id, score=score, findings=findings, verdict=verdict).model_dump(mode="json")


class WorkerRuntime:
    """
    Single-task worker: execute once, persist, terminate.
    Supports pluggable workers via .honeycomb/workers/plugins.json.
    """

    def __init__(
        self,
        honeycomb: HoneycombStore,
        tracer: Tracer,
        llm_provider: str = "ollama",
        llm_providers: str | None = None,
        ollama_base_url: str = "http://100.99.106.59:11434",
        ollama_model: str = "catsarethebest/qwen2.5-N2:1.5b",
        ollama_timeout_seconds: int = 120,
        gemini_api_key: str = "",
        gemini_model: str = "gemini-1.5-flash",
        gemini_timeout_seconds: int = 120,
        openai_api_key: str = "",
        openai_model: str = "gpt-4o-mini",
        openai_base_url: str | None = None,
        openai_timeout_seconds: int = 120,
        searxng_base_url: str = "http://localhost:8080",
        extra_workers: dict[WorkerKind, BaseSpecialistWorker] | None = None,
    ) -> None:
        self.honeycomb = honeycomb
        self.tracer = tracer
        self._workers: dict[WorkerKind, BaseSpecialistWorker] = {
            WorkerKind.web_search: WebSearchWorker(
                llm_provider=llm_provider,
                llm_providers=llm_providers,
                ollama_base_url=ollama_base_url,
                ollama_model=ollama_model,
                ollama_timeout_seconds=ollama_timeout_seconds,
                gemini_api_key=gemini_api_key,
                gemini_model=gemini_model,
                gemini_timeout_seconds=gemini_timeout_seconds,
                openai_api_key=openai_api_key,
                openai_model=openai_model,
                openai_base_url=openai_base_url,
                openai_timeout_seconds=openai_timeout_seconds,
                searxng_base_url=searxng_base_url,
            ),
            WorkerKind.heavy_compute: HeavyComputeWorker(),
            WorkerKind.audit: AuditWorker(),
        }
        if extra_workers:
            for kind, worker in extra_workers.items():
                self._workers[kind] = worker
        else:
            plugin_workers = load_worker_plugins(honeycomb.root_dir)
            for kind, worker in plugin_workers.items():
                self._workers[kind] = worker

    def direct_chat(
        self,
        query: str,
        system: str | None = None,
        messages: list[dict[str, str]] | None = None,
        model_override: str | None = None,
    ) -> tuple[str | None, str]:
        """Call LLM (Ollama/Gemini) directly without any worker pipeline. Returns (reply, source)."""
        worker = self._workers[WorkerKind.web_search]
        assert isinstance(worker, WebSearchWorker)
        return worker._assistant_reply(query, system, messages, model_override=model_override)

    def run_once(self, task: TaskEnvelope, context: WorkerContext, parent_span_id: str | None = None) -> ResultEnvelope:
        started = perf_counter()
        with self.tracer.span(
            task.queen_trace_id,
            f"worker:{context.identity.agent_type}",
            parent_span_id=parent_span_id,
            attributes={"worker_kind": task.worker_kind.value, "agent_id": context.identity.agent_id},
        ):
            task.status = Status.running
            self.honeycomb.write_task(task)
            worker = self._workers[task.worker_kind]
            self.honeycomb.write_event(
                task.queen_trace_id,
                {"kind": "worker_lifecycle", "stage": "preflight", "task_id": task.task_id, "worker_kind": task.worker_kind.value},
            )
            worker.preflight(task, context)
            self.honeycomb.write_event(
                task.queen_trace_id,
                {"kind": "worker_lifecycle", "stage": "execute", "task_id": task.task_id, "worker_kind": task.worker_kind.value},
            )
            raw_output = worker.execute(task, context)
            validated = worker.validate(raw_output)
            self.honeycomb.write_event(
                task.queen_trace_id,
                {"kind": "worker_lifecycle", "stage": "validate", "task_id": task.task_id, "worker_kind": task.worker_kind.value},
            )
            summary = json.dumps(validated.model_dump(mode="json"), ensure_ascii=True, sort_keys=True)
            artifact_kind = "json" if task.worker_kind in {WorkerKind.heavy_compute, WorkerKind.audit} else "report"
            artifact = self.honeycomb.write_artifact(task.queen_trace_id, task.task_id, summary, kind=artifact_kind)

            elapsed_ms = int((perf_counter() - started) * 1000)
            output_payload = validated.model_dump(mode="json")
            confidence = 0.82
            if task.worker_kind == WorkerKind.audit:
                confidence = float(output_payload.get("score", 0.5))
            result = ResultEnvelope(
                task_id=task.task_id,
                agent_id=context.identity.agent_id,
                worker_kind=task.worker_kind,
                status=Status.success,
                confidence=confidence,
                output=output_payload,
                artifact_refs=[artifact],
                cost_metrics=CostMetrics(
                    model_name="simulated-runtime",
                    input_tokens=120,
                    output_tokens=80,
                    latency_ms=elapsed_ms,
                    estimated_cost_usd=min(task.budget_usd, 0.01),
                ),
                output_schema=validated.__class__.__name__,
            )
            task.status = Status.success
            self.honeycomb.write_task(task)
            self.honeycomb.write_result(task.queen_trace_id, result)
            self.honeycomb.write_event(
                task.queen_trace_id,
                {"kind": "worker_lifecycle", "stage": "terminate", "task_id": task.task_id, "worker_kind": task.worker_kind.value},
            )
            worker.terminate(task, context)
            return result


def make_worker_identity(agent_type: str, skill_profile_id: str, soul_profile_id: str) -> AgentIdentity:
    return AgentIdentity(
        agent_id=str(uuid4()),
        agent_type=agent_type,
        skill_profile_id=skill_profile_id,
        soul_profile_id=soul_profile_id,
    )


def execute_task_serialized(
    *,
    task_payload: dict[str, Any],
    context_payload: dict[str, Any],
    honeycomb_root: str,
    vector_backend: str = "memory",
    vector_collection: str = "honeycomb_memory",
    vector_url: str = "http://localhost:6333",
    llm_provider: str = "ollama",
    llm_providers: str | None = None,
    ollama_base_url: str = "http://100.99.106.59:11434",
    ollama_model: str = "catsarethebest/qwen2.5-N2:1.5b",
    ollama_timeout_seconds: int = 120,
    gemini_api_key: str = "",
    gemini_model: str = "gemini-1.5-flash",
    gemini_timeout_seconds: int = 120,
    searxng_base_url: str = "http://localhost:8080",
) -> dict[str, Any]:
    task = TaskEnvelope.model_validate(task_payload)
    context = WorkerContext(
        identity=AgentIdentity.model_validate(context_payload["identity"]),
        skill=SkillProfile.model_validate(context_payload["skill"]),
        rule=RuleProfile.model_validate(context_payload["rule"]),
        soul=SoulProfile.model_validate(context_payload["soul"]),
        abilities=(
            AbilitiesProfile.model_validate(context_payload["abilities"])
            if isinstance(context_payload.get("abilities"), dict)
            else None
        ),
        accountability=(
            AccountabilityPolicy.model_validate(context_payload["accountability"])
            if isinstance(context_payload.get("accountability"), dict)
            else None
        ),
        guardrails=(
            GuardrailProfile.model_validate(context_payload["guardrails"])
            if isinstance(context_payload.get("guardrails"), dict)
            else None
        ),
    )
    honeycomb = HoneycombStore(
        HoneycombConfig(
            root_dir=Path(honeycomb_root),
            vector_backend=vector_backend,
            vector_collection=vector_collection,
            vector_url=vector_url,
        )
    )
    tracer = Tracer()
    runtime = WorkerRuntime(
        honeycomb,
        tracer,
        llm_provider=llm_provider,
        llm_providers=llm_providers,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        ollama_timeout_seconds=ollama_timeout_seconds,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        gemini_timeout_seconds=gemini_timeout_seconds,
        searxng_base_url=searxng_base_url,
    )
    effective_capabilities = set(context.skill.capabilities)
    if context.abilities is not None:
        effective_capabilities.update(context.abilities.capabilities)
    if task.worker_kind == WorkerKind.web_search and "web_search" not in effective_capabilities:
        raise ValueError("context_skill_missing_web_search_capability")
    if task.worker_kind == WorkerKind.heavy_compute and "compute" not in effective_capabilities:
        raise ValueError("context_skill_missing_compute_capability")
    if task.worker_kind == WorkerKind.audit and "audit" not in effective_capabilities:
        raise ValueError("context_skill_missing_audit_capability")
    result = runtime.run_once(task, context)
    return result.model_dump(mode="json")
