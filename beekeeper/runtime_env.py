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


def normalize_ollama_base_url(base_url: str) -> str:
    """Return the Ollama server root, accepting either root or /api base URLs."""
    normalized = (base_url or "http://localhost:11434").rstrip("/")
    if normalized.endswith("/api"):
        return normalized.removesuffix("/api")
    return normalized


def resolve_ollama_api_key(api_key: str | None = None) -> str:
    """Resolve Ollama Cloud auth from Beekeeper alias or official env var."""
    return (
        api_key
        or os.getenv("BEEKEEPER_OLLAMA_API_KEY")
        or os.getenv("OLLAMA_API_KEY")
        or ""
    ).strip()


def resolve_llm_providers() -> list[str]:
    """Resolve provider chain with explicit precedence: providers -> provider -> ollama,gemini,openai."""
    raw = (os.getenv("BEEKEEPER_LLM_PROVIDERS") or "").strip()
    if not raw:
        raw = (os.getenv("BEEKEEPER_LLM_PROVIDER") or "ollama,gemini,openai").strip()
    providers = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return providers or ["ollama", "gemini", "openai"]


def validate_llm_provider_env() -> tuple[list[str], list[str], list[str]]:
    """Return (providers, errors, warnings)."""
    providers = resolve_llm_providers()
    errors: list[str] = []
    warnings: list[str] = []
    ollama_base_url = (os.getenv("BEEKEEPER_OLLAMA_BASE_URL") or "").strip().lower()
    ollama_api_key = resolve_ollama_api_key()

    for name in providers:
        if name == "ollama":
            if "ollama.com" in ollama_base_url and not ollama_api_key:
                errors.append("BEEKEEPER_OLLAMA_API_KEY or OLLAMA_API_KEY is required when Ollama Cloud is configured")
        elif name == "gemini" and not (os.getenv("BEEKEEPER_GEMINI_API_KEY") or "").strip():
            errors.append("BEEKEEPER_GEMINI_API_KEY is required when gemini is configured")
        elif name == "openai" and not (os.getenv("BEEKEEPER_OPENAI_API_KEY") or "").strip():
            errors.append("BEEKEEPER_OPENAI_API_KEY is required when openai is configured")
        elif name not in {"ollama", "gemini", "openai"}:
            errors.append(f"unknown provider '{name}'")

    if ollama_api_key and "ollama" not in providers:
        warnings.append("OLLAMA_API_KEY is set but ollama is not in BEEKEEPER_LLM_PROVIDERS")
    gemini_key = (os.getenv("BEEKEEPER_GEMINI_API_KEY") or "").strip()
    if gemini_key and "gemini" not in providers:
        warnings.append("BEEKEEPER_GEMINI_API_KEY is set but gemini is not in BEEKEEPER_LLM_PROVIDERS")
    openai_key = (os.getenv("BEEKEEPER_OPENAI_API_KEY") or "").strip()
    if openai_key and "openai" not in providers:
        warnings.append("BEEKEEPER_OPENAI_API_KEY is set but openai is not in BEEKEEPER_LLM_PROVIDERS")
    return providers, errors, warnings
