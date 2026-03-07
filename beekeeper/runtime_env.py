from __future__ import annotations

import os
from pathlib import Path


def resolve_runtime_context() -> str:
    """Resolve runtime context for env defaults: docker or local."""
    explicit = (os.getenv("BEEKEEPER_RUNTIME_CONTEXT") or "").strip().lower()
    if explicit:
        return explicit
    if Path("/.dockerenv").exists():
        return "docker"
    return "local"


def resolve_searxng_base_url(*, runtime_context: str | None = None) -> str:
    """Resolve SearXNG URL with split defaults for local vs container runtime."""
    ctx = (runtime_context or resolve_runtime_context()).strip().lower()
    if ctx in {"docker", "container"}:
        return (
            os.getenv("BEEKEEPER_SEARXNG_BASE_URL_DOCKER")
            or os.getenv("BEEKEEPER_SEARXNG_BASE_URL")
            or "http://searxng:8080"
        )
    return (
        os.getenv("BEEKEEPER_SEARXNG_BASE_URL_LOCAL")
        or os.getenv("BEEKEEPER_SEARXNG_BASE_URL")
        or "http://localhost:8080"
    )


def resolve_llm_providers() -> list[str]:
    """Resolve provider chain with explicit precedence: providers -> provider -> openai,gemini,ollama."""
    raw = (os.getenv("BEEKEEPER_LLM_PROVIDERS") or "").strip()
    if not raw:
        raw = (os.getenv("BEEKEEPER_LLM_PROVIDER") or "openai,gemini,ollama").strip()
    providers = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return providers or ["openai", "gemini", "ollama"]


def validate_llm_provider_env() -> tuple[list[str], list[str], list[str]]:
    """Return (providers, errors, warnings)."""
    providers = resolve_llm_providers()
    errors: list[str] = []
    warnings: list[str] = []

    for name in providers:
        if name == "gemini" and not (os.getenv("BEEKEEPER_GEMINI_API_KEY") or "").strip():
            errors.append("BEEKEEPER_GEMINI_API_KEY is required when gemini is configured")
        elif name == "openai" and not (os.getenv("BEEKEEPER_OPENAI_API_KEY") or "").strip():
            errors.append("BEEKEEPER_OPENAI_API_KEY is required when openai is configured")
        elif name not in {"ollama", "gemini", "openai"}:
            errors.append(f"unknown provider '{name}'")

    gemini_key = (os.getenv("BEEKEEPER_GEMINI_API_KEY") or "").strip()
    if gemini_key and "gemini" not in providers:
        warnings.append("BEEKEEPER_GEMINI_API_KEY is set but gemini is not in BEEKEEPER_LLM_PROVIDERS")
    openai_key = (os.getenv("BEEKEEPER_OPENAI_API_KEY") or "").strip()
    if openai_key and "openai" not in providers:
        warnings.append("BEEKEEPER_OPENAI_API_KEY is set but openai is not in BEEKEEPER_LLM_PROVIDERS")
    return providers, errors, warnings
