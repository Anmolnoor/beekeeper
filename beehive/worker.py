from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import urllib.parse
import urllib.request
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel

from .contracts import (
    AgentIdentity,
    AuditFinding,
    AuditOutput,
    CostMetrics,
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


class BaseSpecialistWorker:
    worker_kind: WorkerKind
    output_model: type[BaseModel]

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
        llm_provider: str,
        ollama_base_url: str,
        ollama_model: str,
        ollama_timeout_seconds: int = 120,
        gemini_api_key: str = "",
        gemini_model: str = "gemini-1.5-flash",
        gemini_timeout_seconds: int = 120,
        searxng_base_url: str = "http://localhost:8080",
    ) -> None:
        self.llm_provider = llm_provider.strip().lower()
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.ollama_model = ollama_model
        self.ollama_timeout_seconds = max(5, int(ollama_timeout_seconds))
        self.gemini_api_key = gemini_api_key.strip()
        self.gemini_model = gemini_model
        self.gemini_timeout_seconds = max(5, int(gemini_timeout_seconds))
        self.searxng = SearxngAdapter(base_url=searxng_base_url)

    def _ollama_reply(self, query: str) -> tuple[str | None, Literal["ollama", "fallback"]]:
        url = f"{self.ollama_base_url}/api/generate"
        payload = {
            "model": self.ollama_model,
            "prompt": query,
            "stream": False,
        }
        req = urllib.request.Request(
            url=url,
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        )
        try:
            with urllib.request.urlopen(req, timeout=self.ollama_timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
            text = str(raw.get("response", "")).strip()
            if text:
                return text, "ollama"
        except Exception:
            return None, "fallback"
        return None, "fallback"

    def _gemini_reply(self, query: str) -> tuple[str | None, Literal["gemini", "fallback"]]:
        if not self.gemini_api_key:
            return None, "fallback"
        model = urllib.parse.quote(self.gemini_model, safe=":")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.gemini_api_key}"
        payload = {
            "contents": [{"parts": [{"text": query}]}],
            "generationConfig": {"temperature": 0.5},
        }
        req = urllib.request.Request(
            url=url,
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        )
        try:
            with urllib.request.urlopen(req, timeout=self.gemini_timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
            candidates = raw.get("candidates", [])
            if isinstance(candidates, list) and candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if isinstance(parts, list):
                    text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
                    if text:
                        return text, "gemini"
        except Exception:
            return None, "fallback"
        return None, "fallback"

    def _assistant_reply(self, query: str) -> tuple[str | None, Literal["ollama", "gemini", "fallback"]]:
        if self.llm_provider == "gemini":
            return self._gemini_reply(query)
        return self._ollama_reply(query)

    def _domain_from_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        return (parsed.hostname or "").lower()

    def execute(self, task: TaskEnvelope, context: WorkerContext) -> dict[str, Any]:
        query = str(task.payload.get("query") or task.payload.get("topic") or task.task_type).strip()
        domains = list(task.payload.get("domains", [])) or context.rule.allowed_domains or [
            "docs.python.org",
            "github.com",
            "openai.com",
        ]
        allowed_domains = {str(domain).lower() for domain in domains}
        evidence: list[WebEvidence] = []
        search_error: str | None = None
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
        assistant_reply, source = self._assistant_reply(query)
        if assistant_reply is None:
            if self.llm_provider == "gemini":
                assistant_reply = (
                    f"I could not reach Gemini right now, but I prepared an evidence-backed synthesis for '{query}'. "
                    "Set BEEHIVE_GEMINI_API_KEY/BEEHIVE_GEMINI_MODEL and ensure API access is available."
                )
            else:
                assistant_reply = (
                    f"I could not reach Ollama right now, but I prepared an evidence-backed synthesis for '{query}'. "
                    "Set BEEHIVE_OLLAMA_BASE_URL/BEEHIVE_OLLAMA_MODEL and ensure Ollama is reachable."
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
        _ = context
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
        _ = context
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
    """

    def __init__(
        self,
        honeycomb: HoneycombStore,
        tracer: Tracer,
        llm_provider: str = "ollama",
        ollama_base_url: str = "http://100.99.106.59:11434",
        ollama_model: str = "catsarethebest/qwen2.5-N2:1.5b",
        ollama_timeout_seconds: int = 120,
        gemini_api_key: str = "",
        gemini_model: str = "gemini-1.5-flash",
        gemini_timeout_seconds: int = 120,
        searxng_base_url: str = "http://localhost:8080",
    ) -> None:
        self.honeycomb = honeycomb
        self.tracer = tracer
        self._workers: dict[WorkerKind, BaseSpecialistWorker] = {
            WorkerKind.web_search: WebSearchWorker(
                llm_provider=llm_provider,
                ollama_base_url=ollama_base_url,
                ollama_model=ollama_model,
                ollama_timeout_seconds=ollama_timeout_seconds,
                gemini_api_key=gemini_api_key,
                gemini_model=gemini_model,
                gemini_timeout_seconds=gemini_timeout_seconds,
                searxng_base_url=searxng_base_url,
            ),
            WorkerKind.heavy_compute: HeavyComputeWorker(),
            WorkerKind.audit: AuditWorker(),
        }

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
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        ollama_timeout_seconds=ollama_timeout_seconds,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        gemini_timeout_seconds=gemini_timeout_seconds,
        searxng_base_url=searxng_base_url,
    )
    if task.worker_kind == WorkerKind.web_search and "web_search" not in context.skill.capabilities:
        raise ValueError("context_skill_missing_web_search_capability")
    if task.worker_kind == WorkerKind.heavy_compute and "compute" not in context.skill.capabilities:
        raise ValueError("context_skill_missing_compute_capability")
    if task.worker_kind == WorkerKind.audit and "audit" not in context.skill.capabilities:
        raise ValueError("context_skill_missing_audit_capability")
    result = runtime.run_once(task, context)
    return result.model_dump(mode="json")
