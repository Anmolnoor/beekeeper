from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from .audit_logger import log_service_call
from .worker import execute_task_serialized

try:
    from temporalio import activity, workflow
    from temporalio.client import Client
    from temporalio.worker import Worker

    TEMPORAL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency path
    TEMPORAL_AVAILABLE = False


@dataclass
class TemporalConfig:
    endpoint: str = "localhost:7233"
    namespace: str = "default"
    task_queue: str = "beekeeper-queue"


if TEMPORAL_AVAILABLE:

    @activity.defn
    async def execute_worker_activity(
        task_payload: dict[str, Any],
        context_payload: dict[str, Any],
        honeycomb_root: str,
        vector_backend: str,
        vector_collection: str,
        vector_url: str,
        llm_provider: str,
        ollama_base_url: str,
        ollama_model: str,
        ollama_timeout_seconds: int,
        gemini_api_key: str,
        gemini_model: str,
        gemini_timeout_seconds: int,
        searxng_base_url: str,
    ) -> dict[str, Any]:
        return execute_task_serialized(
            task_payload=task_payload,
            context_payload=context_payload,
            honeycomb_root=honeycomb_root,
            vector_backend=vector_backend,
            vector_collection=vector_collection,
            vector_url=vector_url,
            llm_provider=llm_provider,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            ollama_timeout_seconds=ollama_timeout_seconds,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            gemini_timeout_seconds=gemini_timeout_seconds,
            searxng_base_url=searxng_base_url,
        )


    @workflow.defn
    class BeekeeperTaskWorkflow:
        @workflow.run
        async def run(
            self,
            task_payload: dict[str, Any],
            context_payload: dict[str, Any],
            honeycomb_root: str,
            vector_backend: str,
            vector_collection: str,
            vector_url: str,
            llm_provider: str,
            ollama_base_url: str,
            ollama_model: str,
            ollama_timeout_seconds: int,
            gemini_api_key: str,
            gemini_model: str,
            gemini_timeout_seconds: int,
            searxng_base_url: str,
        ) -> dict[str, Any]:
            return await workflow.execute_activity(
                execute_worker_activity,
                args=[
                    task_payload,
                    context_payload,
                    honeycomb_root,
                    vector_backend,
                    vector_collection,
                    vector_url,
                    llm_provider,
                    ollama_base_url,
                    ollama_model,
                    ollama_timeout_seconds,
                    gemini_api_key,
                    gemini_model,
                    gemini_timeout_seconds,
                    searxng_base_url,
                ],
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy={
                    "maximum_attempts": 4,
                    "initial_interval": timedelta(seconds=1),
                    "backoff_coefficient": 2.0,
                    "maximum_interval": timedelta(seconds=10),
                    "non_retryable_error_types": ["ValueError"],
                },
            )


class TemporalBeekeeperClient:
    def __init__(self, config: TemporalConfig) -> None:
        if not TEMPORAL_AVAILABLE:
            raise RuntimeError("temporalio_not_installed")
        self.config = config

    @staticmethod
    def _normalize_endpoint(endpoint: str) -> str:
        value = endpoint.strip()
        if "://" in value:
            parsed = urlparse(value)
            host = parsed.hostname or "localhost"
            port = parsed.port or 7233
            return f"{host}:{port}"
        return value

    @staticmethod
    def _parse_fallback_endpoints(raw: str) -> list[str]:
        return [value.strip() for value in raw.split(",") if value.strip()]

    def _connection_candidates(self) -> list[str]:
        candidates = [self._normalize_endpoint(self.config.endpoint)]
        fallback_raw = os.getenv(
            "BEEKEEPER_TEMPORAL_ENDPOINT_FALLBACKS",
            "temporal:7233,localhost:7233,host.docker.internal:7233",
        )
        for endpoint in self._parse_fallback_endpoints(fallback_raw):
            normalized = self._normalize_endpoint(endpoint)
            if normalized not in candidates:
                candidates.append(normalized)
        return candidates

    async def connect(self) -> Client:
        last_error: Exception | None = None
        for endpoint in self._connection_candidates():
            try:
                return await Client.connect(endpoint, namespace=self.config.namespace)
            except Exception as exc:
                last_error = exc
        raise RuntimeError(
            f"temporal_connect_failed endpoints={self._connection_candidates()} last_error={last_error}"
        )

    async def execute(
        self,
        *,
        workflow_id: str,
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
        trace_id = task_payload.get("queen_trace_id") if isinstance(task_payload, dict) else None
        log_service_call("temporal", "submitted", source="queen", trace_id=trace_id)
        client = await self.connect()
        payload = await client.execute_workflow(
            BeekeeperTaskWorkflow.run,
            args=[
                task_payload,
                context_payload,
                honeycomb_root,
                vector_backend,
                vector_collection,
                vector_url,
                llm_provider,
                ollama_base_url,
                ollama_model,
                ollama_timeout_seconds,
                gemini_api_key,
                gemini_model,
                gemini_timeout_seconds,
                searxng_base_url,
            ],
            id=workflow_id,
            task_queue=self.config.task_queue,
        )
        if "worker_kind" not in payload or "output_schema" not in payload:
            raise ValueError("temporal_payload_missing_specialist_fields")
        return payload

    async def run_worker(self) -> None:
        last_error: Exception | None = None
        for _ in range(30):
            try:
                client = await self.connect()
                worker = Worker(
                    client,
                    task_queue=self.config.task_queue,
                    workflows=[BeekeeperTaskWorkflow],
                    activities=[execute_worker_activity],
                )
                await worker.run()
                return
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(2)
        raise RuntimeError(f"temporal_worker_failed_to_connect: {last_error}")
