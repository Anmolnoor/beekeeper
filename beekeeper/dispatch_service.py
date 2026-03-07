from __future__ import annotations

from asyncio import run as asyncio_run
from dataclasses import dataclass
from typing import Any, Callable

from .contracts import ResultEnvelope, TaskEnvelope
from .scheduler import CeleryScheduler, InlineScheduler
from .temporal_integration import TEMPORAL_AVAILABLE, TemporalBeekeeperClient, TemporalConfig
from .worker import WorkerContext


@dataclass(frozen=True)
class DispatchConfig:
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
