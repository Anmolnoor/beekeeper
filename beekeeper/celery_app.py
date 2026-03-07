from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from celery import Celery

from .runtime_env import resolve_searxng_base_url
from .worker import execute_task_serialized

broker_url = os.getenv("BEEKEEPER_CELERY_BROKER_URL", "redis://localhost:6379/0")
backend_url = os.getenv("BEEKEEPER_CELERY_BACKEND_URL", "redis://localhost:6379/1")
honeycomb_root = os.getenv("BEEKEEPER_HONEYCOMB_ROOT", str(Path(".honeycomb").resolve()))
vector_backend = os.getenv("BEEKEEPER_VECTOR_BACKEND", "memory")
vector_collection = os.getenv("BEEKEEPER_VECTOR_COLLECTION", "honeycomb_memory")
vector_url = os.getenv("BEEKEEPER_VECTOR_URL", "http://localhost:6333")
llm_provider = os.getenv("BEEKEEPER_LLM_PROVIDER", "openai")
llm_providers = os.getenv("BEEKEEPER_LLM_PROVIDERS", "openai,gemini,ollama") or None
ollama_base_url = os.getenv("BEEKEEPER_OLLAMA_BASE_URL", "http://localhost:11434")
ollama_model = os.getenv("BEEKEEPER_OLLAMA_MODEL", "catsarethebest/qwen2.5-N2:1.5b")
ollama_timeout_seconds = int(os.getenv("BEEKEEPER_OLLAMA_TIMEOUT_SECONDS", "120"))
gemini_api_key = os.getenv("BEEKEEPER_GEMINI_API_KEY", "")
gemini_model = os.getenv("BEEKEEPER_GEMINI_MODEL", "gemini-1.5-flash")
gemini_timeout_seconds = int(os.getenv("BEEKEEPER_GEMINI_TIMEOUT_SECONDS", "120"))
searxng_base_url = resolve_searxng_base_url(runtime_context="docker")

celery_app = Celery("beekeeper", broker=broker_url, backend=backend_url)


@celery_app.task(name="beekeeper.execute_worker_task")
def execute_worker_task(task_payload: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    return execute_task_serialized(
        task_payload=task_payload,
        context_payload=context_payload,
        honeycomb_root=honeycomb_root,
        vector_backend=vector_backend,
        vector_collection=vector_collection,
        vector_url=vector_url,
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
