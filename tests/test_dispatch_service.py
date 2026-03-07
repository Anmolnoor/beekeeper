from __future__ import annotations

from beekeeper.dispatch_service import DispatchConfig, DispatchService


class _DummyScheduler:
    pass


class _DummyRuntime:
    pass


def _build_service(*, scheduler_backend: str = "auto") -> DispatchService:
    config = DispatchConfig(
        scheduler_backend=scheduler_backend,
        celery_broker_url="redis://localhost:6379/0",
        temporal_endpoint="localhost:7233",
        temporal_namespace="default",
        temporal_task_queue="beekeeper",
        scheduler_timeout_seconds=60,
        honeycomb_root=".honeycomb",
        vector_backend="memory",
        vector_collection="honeycomb_memory",
        vector_url="http://localhost:6333",
        llm_provider="ollama",
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3.2",
        ollama_timeout_seconds=120,
        gemini_api_key="",
        gemini_model="gemini-1.5-flash",
        gemini_timeout_seconds=120,
        searxng_base_url="http://localhost:8080",
    )
    return DispatchService(
        config=config,
        scheduler=_DummyScheduler(),
        worker_runtime=_DummyRuntime(),
        build_celery_scheduler=lambda: _DummyScheduler(),
        build_inline_scheduler=lambda: _DummyScheduler(),
    )


def test_auto_scheduler_prefers_temporal_when_payload_requires_durability(monkeypatch) -> None:
    service = _build_service(scheduler_backend="auto")
    monkeypatch.setattr(service, "_can_connect_temporal", lambda: True)
    monkeypatch.setattr(service, "_can_connect_celery", lambda: True)

    selected, decision = service.resolve_scheduler_backend({"require_durable": True})

    assert selected == "temporal"
    assert decision["reason"] == "durability_hint_and_temporal_ready"


def test_unknown_scheduler_falls_back_to_inline(monkeypatch) -> None:
    service = _build_service(scheduler_backend="bogus")
    monkeypatch.setattr(service, "_can_connect_temporal", lambda: False)
    monkeypatch.setattr(service, "_can_connect_celery", lambda: False)

    selected, decision = service.resolve_scheduler_backend({})

    assert selected == "inline"
    assert decision["reason"] == "unknown_scheduler_fallback"
