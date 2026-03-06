from __future__ import annotations

import os
from pathlib import Path

from beekeeper.llm_provider import GeminiProvider, OllamaProvider, build_llm_router
from beekeeper.runner import _load_env_early


def test_build_llm_router_prefers_explicit_llm_provider_over_env(monkeypatch) -> None:
    monkeypatch.setenv("BEEKEEPER_LLM_PROVIDER", "gemini")

    router = build_llm_router(
        llm_provider="ollama",
        llm_providers=None,
        ollama_base_url="http://localhost:11434",
        ollama_model="qwen3.5:35b",
        gemini_api_key="dummy-key",
    )

    assert router.providers
    assert isinstance(router.providers[0], OllamaProvider)


def test_build_llm_router_respects_chain_order() -> None:
    router = build_llm_router(
        llm_provider="ollama",
        llm_providers="ollama,gemini",
        ollama_base_url="http://localhost:11434",
        ollama_model="qwen3.5:35b",
        gemini_api_key="dummy-key",
    )

    assert len(router.providers) == 2
    assert isinstance(router.providers[0], OllamaProvider)
    assert isinstance(router.providers[1], GeminiProvider)


def test_load_env_early_does_not_override_explicit_env(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    (project / ".env").write_text("BEEKEEPER_LLM_PROVIDER=gemini\n", encoding="utf-8")

    monkeypatch.chdir(project)
    monkeypatch.setenv("BEEKEEPER_LLM_PROVIDER", "ollama")

    _load_env_early()

    assert "BEEKEEPER_LLM_PROVIDER" in os.environ
    assert os.environ["BEEKEEPER_LLM_PROVIDER"] == "ollama"
