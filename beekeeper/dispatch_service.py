from __future__ import annotations

import socket
from asyncio import run as asyncio_run
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from .config import RuntimeMode, resolve_runtime_mode
from .contracts import ResultEnvelope, TaskEnvelope
from .scheduler import CeleryScheduler, InlineScheduler
from .temporal_integration import TEMPORAL_AVAILABLE, TemporalBeekeeperClient, TemporalConfig
from .worker import WorkerContext


@dataclass(frozen=True)
class DispatchConfig:
    scheduler_backend: str
    celery_broker_url: str
    temporal_endpoint: str
    temporal_namespace: str
    temporal_task_queue: str
    scheduler_timeout_seconds: int
    honeycomb_root: str
    vector_backend: str
    vector_collection: str
    vector_url: str
    llm_provider: str
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_seconds: int
    gemini_api_key: str
    gemini_model: str
    gemini_timeout_seconds: int
    searxng_base_url: str


class DispatchService:
    def __init__(
        self,
        config: DispatchConfig,
        scheduler: Any,
        worker_runtime: Any,
        build_celery_scheduler: Callable[[], CeleryScheduler],
        build_inline_scheduler: Callable[[], InlineScheduler],
    ) -> None:
        self.config = config
        self.scheduler = scheduler
        self.worker_runtime = worker_runtime
        self._build_celery_scheduler = build_celery_scheduler
        self._build_inline_scheduler = build_inline_scheduler

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

    def resolve_scheduler_backend(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
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

    @staticmethod
    def _context_payload(context: WorkerContext) -> dict[str, Any]:
        return {
            "identity": context.identity.model_dump(mode="json"),
            "skill": context.skill.model_dump(mode="json"),
            "rule": context.rule.model_dump(mode="json"),
            "soul": context.soul.model_dump(mode="json"),
            "abilities": context.abilities.model_dump(mode="json") if context.abilities else None,
            "accountability": context.accountability.model_dump(mode="json") if context.accountability else None,
            "guardrails": context.guardrails.model_dump(mode="json") if context.guardrails else None,
            "capability_manifest": context.capability_manifest.to_dict() if context.capability_manifest else None,
        }

    def execute_worker_task(
        self,
        task: TaskEnvelope,
        context: WorkerContext,
        scheduler_backend: str,
        parent_span_id: str | None = None,
    ) -> ResultEnvelope:
        backend = scheduler_backend.strip().lower()
        context_payload = self._context_payload(context)
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
                    context_payload=context_payload,
                    honeycomb_root=self.config.honeycomb_root,
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
            job_id = scheduler.submit(task.model_dump(mode="json"), context_payload)
            payload = scheduler.collect(job_id, timeout_seconds=self.config.scheduler_timeout_seconds)
            return ResultEnvelope.model_validate(payload)
        if backend == "inline":
            scheduler = self.scheduler if isinstance(self.scheduler, InlineScheduler) else self._build_inline_scheduler()
            job_id = scheduler.submit(task.model_dump(mode="json"), context_payload)
            payload = scheduler.collect(job_id, timeout_seconds=self.config.scheduler_timeout_seconds)
            return ResultEnvelope.model_validate(payload)
        return self.worker_runtime.run_once(task, context, parent_span_id=parent_span_id)
