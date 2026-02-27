from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
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
    ContextCuratorOutput,
    CuratedMemoryItem,
    CostMetrics,
    FileOperationOutput,
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


def _build_user_context_system(payload: dict[str, Any]) -> str | None:
    memories = payload.get("user_memories") or []
    lines = []
    if isinstance(memories, list):
        for m in memories[:15]:
            if isinstance(m, str):
                lines.append(f"- {m}")
            elif isinstance(m, dict) and m.get("content"):
                lines.append(f"- {m['content']}")
    for m in (payload.get("_semantic_context") or [])[:8]:
        if isinstance(m, str) and m.strip():
            lines.append(f"- {m.strip()}")
    for m in (payload.get("_md_memory_context") or [])[:8]:
        if isinstance(m, str) and m.strip():
            lines.append(f"- {m.strip()}")
    bundle = payload.get("_context_bundle")
    if isinstance(bundle, dict):
        for m in (bundle.get("semantic_context") or [])[:6]:
            if isinstance(m, str) and m.strip():
                lines.append(f"- {m.strip()}")
    if not lines:
        return None
    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        deduped.append(line)
    return "User context from past conversations:\n" + "\n".join(deduped[:20])


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
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "llama3.2",
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

    def execute(self, task: TaskEnvelope, context: WorkerContext) -> dict[str, Any]:
        query = str(task.payload.get("query") or task.payload.get("topic") or task.task_type).strip()
        use_web_search = task.payload.get("use_web_search", False) is True
        user_system = _build_user_context_system(task.payload)
        prior = task.payload.get("messages") or []
        messages = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in prior if isinstance(m, dict)]
        if not use_web_search:
            self._emit_status(context, "Consulting language model for response generation…")
            model_tier = task.payload.get("model_tier")
            assistant_reply, source = self._assistant_reply(
                query, system=user_system, messages=messages or None, model_tier=model_tier
            )
            if assistant_reply is None:
                assistant_reply = (
                    "I could not reach any configured LLM. "
                    "Check Ollama connectivity, BEEKEEPER_GEMINI_API_KEY, and Gemini billing/quota."
                )
            return WebSearchOutput(
                query=query,
                evidence=[],
                assistant_reply=assistant_reply,
                response_source=source,
                synthesis="Direct chat (LLM only, no web search).",
            ).model_dump(mode="json")
        _payload_domains = task.payload.get("domains")
        if _payload_domains is not None:
            domains = list(_payload_domains)
        elif context.rule.allowed_domains:
            domains = list(context.rule.allowed_domains)
        else:
            domains = []
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
            query, system=user_system, messages=messages or None, model_tier=model_tier
        )
        if assistant_reply is None:
            assistant_reply = (
                f"I could not reach any configured LLM, but I prepared an evidence-backed synthesis for '{query}'. "
                "Check Ollama connectivity, BEEKEEPER_GEMINI_API_KEY, and Gemini billing/quota."
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


class ForgedWorker(BaseSpecialistWorker):
    """Handles intents with no matching worker or custom-spawned worker kinds. Uses LLM to fulfill the request."""
    worker_kind = WorkerKind.forged
    output_model = WebSearchOutput

    def preflight(self, task: TaskEnvelope, context: WorkerContext) -> None:
        # Accept both forged and custom worker kinds — ForgedWorker is the executor for all custom/spawned workers
        if task.worker_kind not in (WorkerKind.forged, WorkerKind.custom):
            raise ValueError(f"worker_kind_mismatch expected={self.worker_kind.value} or custom got={task.worker_kind.value}")

    def __init__(
        self,
        llm_providers: str | None = None,
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "catsarethebest/qwen2.5-N2:1.5b",
        ollama_timeout_seconds: int = 120,
        gemini_api_key: str = "",
        gemini_model: str = "gemini-1.5-flash",
        gemini_timeout_seconds: int = 120,
        openai_api_key: str = "",
        openai_model: str = "gpt-4o-mini",
        openai_base_url: str | None = None,
        openai_timeout_seconds: int = 120,
    ) -> None:
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

    import re as _re

    # Patterns tried in order; first match wins.
    # Each tuple: (action_kind, compiled_regex, path_group, content_group_or_None)
    _FILE_PATTERNS: list[tuple[str, Any, int, int | None]] = []

    @classmethod
    def _build_patterns(cls) -> None:
        import re
        cls._FILE_PATTERNS = [
            # "create a file foo.txt with content Hello World"
            ("write_file", re.compile(
                r'create\s+(?:a\s+)?file\s+["\']?(\S+?)["\']?\s+with\s+content\s+(.+)',
                re.IGNORECASE | re.DOTALL), 1, 2),
            # "write Hello World to foo.txt"
            ("write_file", re.compile(
                r'write\s+["\']?(.+?)["\']?\s+to\s+(?:file\s+)?["\']?(\S+?)["\']?\s*$',
                re.IGNORECASE | re.DOTALL), 2, 1),
            # "save Hello World to/as foo.txt"
            ("write_file", re.compile(
                r'save\s+["\']?(.+?)["\']?\s+(?:to|as)\s+["\']?(\S+?)["\']?\s*$',
                re.IGNORECASE | re.DOTALL), 2, 1),
            # "make/create/mkdir directory foo"
            ("make_dir", re.compile(
                r'(?:create|make|mkdir)\s+(?:a\s+)?(?:directory|dir|folder)\s+["\']?(\S+?)["\']?\s*$',
                re.IGNORECASE), 1, None),
            # "delete/remove/rm file foo.txt"
            ("delete_file", re.compile(
                r'(?:delete|remove|rm)\s+(?:(?:the\s+)?file\s+)?["\']?(\S+\.\S+)["\']?\s*$',
                re.IGNORECASE), 1, None),
            # "append Hello World to foo.txt"
            ("append_file", re.compile(
                r'append\s+["\']?(.+?)["\']?\s+to\s+(?:file\s+)?["\']?(\S+?)["\']?\s*$',
                re.IGNORECASE | re.DOTALL), 2, 1),
        ]

    def _infer_action_from_query(self, query: str) -> dict[str, Any] | None:
        """Parse file/dir operations directly from the query — no LLM needed."""
        if not self.__class__._FILE_PATTERNS:
            self.__class__._build_patterns()
        for action_kind, pattern, path_grp, content_grp in self.__class__._FILE_PATTERNS:
            m = pattern.search(query)
            if not m:
                continue
            result: dict[str, Any] = {"action": action_kind, "path": m.group(path_grp).strip()}
            if content_grp is not None:
                result["content"] = m.group(content_grp).strip()
            return result
        return None

    def _execute_action(self, action: dict[str, Any]) -> tuple[str, list[str]]:
        """Run the parsed action. Returns (human summary, list of evidence strings)."""
        kind = str(action.get("action", "answer")).strip().lower()
        evidence: list[str] = []

        if kind == "write_file":
            path = Path(str(action["path"])).expanduser()
            content = str(action.get("content", ""))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            summary = f"Created file: {path} ({len(content)} chars)"
            evidence.append(f"wrote:{path}")

        elif kind == "append_file":
            path = Path(str(action["path"])).expanduser()
            content = str(action.get("content", ""))
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(content)
            summary = f"Appended to file: {path} ({len(content)} chars)"
            evidence.append(f"appended:{path}")

        elif kind == "delete_file":
            path = Path(str(action["path"])).expanduser()
            if path.exists():
                path.unlink()
                summary = f"Deleted file: {path}"
                evidence.append(f"deleted:{path}")
            else:
                summary = f"File not found (nothing deleted): {path}"

        elif kind == "make_dir":
            path = Path(str(action["path"])).expanduser()
            path.mkdir(parents=True, exist_ok=True)
            summary = f"Created directory: {path}"
            evidence.append(f"mkdir:{path}")

        else:  # answer / unknown
            summary = str(action.get("reply", ""))

        return summary, evidence

    def execute(self, task: TaskEnvelope, context: WorkerContext) -> dict[str, Any]:
        self._emit_status(context, "Planning action…")
        query = str(task.payload.get("query") or task.payload.get("topic") or task.task_type).strip()
        prior = task.payload.get("messages") or []
        messages = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in prior if isinstance(m, dict)]

        # Step 1: try to infer a file/dir action directly from the query (no LLM, fully reliable)
        action = self._infer_action_from_query(query)
        evidence: list[str] = []
        source = "fallback"

        if action:
            # Execute without calling the LLM at all
            self._emit_status(context, f"Executing {action['action']}…")
            try:
                action_summary, evidence = self._execute_action(action)
            except Exception as exc:
                action_summary = f"Action failed: {exc}"
                evidence = [f"action_error:{exc}"]
        else:
            # Step 2: not a file op — ask LLM for a plain-text answer (no JSON required)
            self._emit_status(context, "Answering with LLM…")
            user_system = _build_user_context_system(task.payload)
            raw_reply, source = self.llm_router.call(
                prompt=query,
                system=user_system,
                messages=messages or None,
            )
            action_summary = raw_reply or "I could not process this request."

        return WebSearchOutput(
            query=query,
            evidence=[],
            assistant_reply=action_summary,
            response_source=source,
            synthesis=f"ForgedWorker. evidence={evidence}",
        ).model_dump(mode="json")


class ContextCuratorWorker(BaseSpecialistWorker):
    """Background worker that curates long-term and daily context memory."""

    worker_kind = WorkerKind.context_curator
    output_model = ContextCuratorOutput

    def execute(self, task: TaskEnvelope, context: WorkerContext) -> dict[str, Any]:
        self._emit_status(context, "Curating context and saving durable memory…")
        user_id = str(task.payload.get("user_id", "")).strip()
        chat_id = str(task.payload.get("chat_id", "")).strip() or None
        user_msg = str(task.payload.get("user_msg", "")).strip()
        assistant_reply = str(task.payload.get("assistant_reply", "")).strip()
        honeycomb_root = Path(str(task.payload.get("honeycomb_root") or ".honeycomb"))
        if not user_msg and not assistant_reply:
            return ContextCuratorOutput(notes="No conversation content to curate.").model_dump(mode="json")

        from .honeycomb import HoneycombConfig, HoneycombStore
        from .store import BeekeeperStore
        from .user_memory import (
            append_daily_memory_note,
            append_durable_memory,
            classify_memory_item,
            ensure_memory_files,
            extract_memories,
            is_sensitive_memory_content,
        )

        ensure_memory_files(honeycomb_root)
        extracted = extract_memories(user_msg, assistant_reply, honeycomb_root=honeycomb_root)
        if not extracted:
            # Always preserve a brief daily breadcrumb even when extraction has no durable facts.
            if user_msg:
                append_daily_memory_note(honeycomb_root, f"User asked: {user_msg[:220]}", source="context_curator")
                return ContextCuratorOutput(saved_md_entries=1, notes="Saved daily note only.").model_dump(mode="json")
            return ContextCuratorOutput(notes="No durable memory extracted.").model_dump(mode="json")

        saved_user = 0
        saved_queen = 0
        saved_md = 0
        skipped_sensitive = 0
        items: list[CuratedMemoryItem] = []
        store = BeekeeperStore(root=Path(os.getenv("BEEKEEPER_STORE_ROOT", ".beekeeper_store")))
        honeycomb = HoneycombStore(
            HoneycombConfig(
                root_dir=honeycomb_root,
                vector_backend=os.getenv("BEEKEEPER_VECTOR_BACKEND", "memory"),
                vector_collection=os.getenv("BEEKEEPER_VECTOR_COLLECTION", "honeycomb_memory"),
                vector_url=os.getenv("BEEKEEPER_VECTOR_URL", "http://localhost:6333"),
            )
        )
        for line in extracted[:8]:
            if is_sensitive_memory_content(line):
                skipped_sensitive += 1
                continue
            tier, score = classify_memory_item(line)
            items.append(CuratedMemoryItem(content=line, tier=tier, score=score))
            append_daily_memory_note(honeycomb_root, line, source=f"context_curator:{tier}")
            saved_md += 1
            if tier in {"profile_fact", "project_preference"} and score >= 0.8:
                append_durable_memory(honeycomb_root, line, tier=tier)
                saved_md += 1
                honeycomb.write_queen_memory(line, source="context_curator", tags=[tier])
                saved_queen += 1
                if user_id:
                    store.append_user_memory_with_metadata(
                        user_id,
                        line,
                        chat_id=chat_id,
                        tier=tier,
                        score=score,
                    )
                    saved_user += 1
        return ContextCuratorOutput(
            saved_user_memories=saved_user,
            saved_queen_memories=saved_queen,
            saved_md_entries=saved_md,
            items=items,
            notes=f"Context curation completed. skipped_sensitive={skipped_sensitive}",
        ).model_dump(mode="json")


class FileWorker(BaseSpecialistWorker):
    """Reads and writes files on the local filesystem. Used by Queen to save reports, data, and artifacts."""
    worker_kind = WorkerKind.file_system
    output_model = FileOperationOutput

    def execute(self, task: TaskEnvelope, context: WorkerContext) -> dict[str, Any]:
        operation = str(task.payload.get("operation", "write")).lower()
        raw_path = str(task.payload.get("file_path") or task.payload.get("path") or "").strip()
        content = str(task.payload.get("content") or task.payload.get("text") or "")
        base_dir = str(task.payload.get("base_dir") or os.getcwd())

        if not raw_path:
            return FileOperationOutput(
                operation=operation, file_path="", success=False,
                notes="No file_path provided in payload."
            ).model_dump(mode="json")

        path = Path(raw_path) if Path(raw_path).is_absolute() else Path(base_dir) / raw_path

        try:
            if operation in ("write", "append"):
                self._emit_status(context, f"Writing to {path}…")
                path.parent.mkdir(parents=True, exist_ok=True)
                if operation == "append":
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(content)
                else:
                    path.write_text(content, encoding="utf-8")
                return FileOperationOutput(
                    operation=operation, file_path=str(path), success=True,
                    bytes_written=len(content.encode()),
                    content_preview=content[:200],
                    notes=f"Wrote {len(content)} chars to {path}",
                ).model_dump(mode="json")
            elif operation == "read":
                self._emit_status(context, f"Reading {path}…")
                text = path.read_text(encoding="utf-8")
                return FileOperationOutput(
                    operation="read", file_path=str(path), success=True,
                    content_preview=text[:500],
                    notes=f"Read {len(text)} chars",
                ).model_dump(mode="json")
            elif operation == "mkdir":
                self._emit_status(context, f"Creating directory {path}…")
                path.mkdir(parents=True, exist_ok=True)
                return FileOperationOutput(
                    operation="mkdir", file_path=str(path), success=True,
                    notes=f"Created directory {path}",
                ).model_dump(mode="json")
            else:
                return FileOperationOutput(
                    operation=operation, file_path=str(path), success=False,
                    notes=f"Unknown operation: {operation}",
                ).model_dump(mode="json")
        except Exception as exc:
            return FileOperationOutput(
                operation=operation, file_path=str(path), success=False,
                notes=str(exc)[:300],
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
        self._workers: dict[WorkerKind | str, BaseSpecialistWorker] = {
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
            WorkerKind.context_curator: ContextCuratorWorker(),
            WorkerKind.file_system: FileWorker(),
            WorkerKind.forged: ForgedWorker(
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
            ),
        }
        # WorkerKind.custom routes to ForgedWorker (LLM fallback for auto-spawned workers)
        self._workers[WorkerKind.custom] = self._workers[WorkerKind.forged]
        if extra_workers:
            for kind, worker in extra_workers.items():
                self._workers[kind] = worker
        else:
            self._load_plugin_workers(honeycomb.root_dir)

    def _load_plugin_workers(self, honeycomb_root: Path) -> None:
        plugin_workers = load_worker_plugins(honeycomb_root)
        for kind, worker in plugin_workers.items():
            self._workers[kind] = worker

    def reload_plugins(self, honeycomb_root: Path | None = None) -> None:
        """Reload worker plugins from disk (e.g. after forge). Merges into _workers."""
        root = honeycomb_root or self.honeycomb.root_dir
        self._load_plugin_workers(root)

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
            runtime_worker_key = str(task.payload.get("_runtime_worker_key", "")).strip()
            worker_key = task.worker_kind
            if runtime_worker_key and runtime_worker_key in self._workers:
                worker_key = runtime_worker_key
            elif task.task_type.startswith("forged_") and task.task_type in self._workers:
                worker_key = task.task_type
            worker = self._workers.get(worker_key) or self._workers[WorkerKind.forged]
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
    if task.worker_kind == WorkerKind.context_curator and "memory_curation" not in effective_capabilities:
        raise ValueError("context_skill_missing_memory_curation_capability")
    result = runtime.run_once(task, context)
    return result.model_dump(mode="json")
