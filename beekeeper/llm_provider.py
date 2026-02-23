"""Unified multi-provider LLM API with fallback chain.

Supports Ollama, Gemini, and optionally OpenAI. Configure via BEEKEEPER_LLM_PROVIDERS
(comma-separated, e.g. "ollama,gemini") for ordered fallback.
"""
from __future__ import annotations

import json
import os

from .audit_logger import log_service_call
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    text: str
    source: str  # "ollama", "gemini", "openai", "fallback"
    model: str | None = None


class LLMProvider(ABC):
    """Abstract LLM provider interface."""

    @abstractmethod
    def chat(
        self,
        prompt: str,
        system: str | None = None,
        messages: list[dict[str, str]] | None = None,
        model_override: str | None = None,
    ) -> LLMResponse | None:
        """Send a chat request. model_override selects model for this call. Returns None on failure."""
        ...


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama2",
        timeout_seconds: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = max(5, timeout_seconds)

    def chat(
        self,
        prompt: str,
        system: str | None = None,
        messages: list[dict[str, str]] | None = None,
        model_override: str | None = None,
    ) -> LLMResponse | None:
        model = model_override or self.model
        if messages:
            url = f"{self.base_url}/api/chat"
            msgs: list[dict[str, Any]] = []
            if system:
                msgs.append({"role": "system", "content": system})
            for m in messages:
                msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})
            msgs.append({"role": "user", "content": prompt})
            payload = {"model": model, "messages": msgs, "stream": False}
        else:
            url = f"{self.base_url}/api/generate"
            payload = {"model": model, "prompt": prompt, "stream": False}
            if system:
                payload["system"] = system
        req = urllib.request.Request(
            url=url,
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
            text = str(raw.get("message", raw).get("content", raw.get("response", ""))).strip()
            if text:
                return LLMResponse(text=text, source="ollama", model=model)
        except Exception:
            pass
        return None


class GeminiProvider(LLMProvider):
    """Google Gemini API provider."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-1.5-flash",
        timeout_seconds: int = 120,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model
        self.timeout = max(5, timeout_seconds)

    def chat(
        self,
        prompt: str,
        system: str | None = None,
        messages: list[dict[str, str]] | None = None,
        model_override: str | None = None,
    ) -> LLMResponse | None:
        if not self.api_key:
            return None
        model = model_override or self.model
        model_enc = urllib.parse.quote(model, safe=":")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_enc}:generateContent?key={self.api_key}"
        contents: list[dict[str, Any]] = []
        if system or messages:
            text_parts: list[str] = []
            if system:
                text_parts.append(f"[System]\n{system}\n")
            for m in (messages or []):
                role = m.get("role", "user")
                content = m.get("content", "")
                text_parts.append(f"[{role.title()}]\n{content}\n")
            text_parts.append(f"[User]\n{prompt}")
            contents.append({"role": "user", "parts": [{"text": "\n".join(text_parts)}]})
        else:
            contents.append({"role": "user", "parts": [{"text": prompt}]})
        payload = {
            "contents": contents,
            "generationConfig": {"temperature": 0.5},
        }
        req = urllib.request.Request(
            url=url,
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
            candidates = raw.get("candidates", [])
            if isinstance(candidates, list) and candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if isinstance(parts, list):
                    text = "".join(
                        str(part.get("text", "")) for part in parts if isinstance(part, dict)
                    ).strip()
                    if text:
                        return LLMResponse(text=text, source="gemini", model=model)
        except Exception:
            pass
        return None


class OpenAIProvider(LLMProvider):
    """OpenAI API provider (also works with Azure/compatible endpoints via BEEKEEPER_OPENAI_BASE_URL)."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.timeout = max(5, timeout_seconds)

    def chat(
        self,
        prompt: str,
        system: str | None = None,
        messages: list[dict[str, str]] | None = None,
        model_override: str | None = None,
    ) -> LLMResponse | None:
        if not self.api_key:
            return None
        model = model_override or self.model
        msgs: list[dict[str, Any]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        for m in (messages or []):
            msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        msgs.append({"role": "user", "content": prompt})
        payload = {"model": model, "messages": msgs}
        url = f"{self.base_url}/chat/completions"
        req = urllib.request.Request(
            url=url,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
            choices = raw.get("choices", [])
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message", {})
                text = str(msg.get("content", "")).strip()
                if text:
                    return LLMResponse(text=text, source="openai", model=model)
        except Exception:
            pass
        return None


def _resolve_model_for_tier(tier: str, provider: str) -> str | None:
    """Resolve model name from model_tier. Returns None to use default."""
    if not tier or tier not in ("economy", "standard", "premium"):
        return None
    key_suffix = f"_{tier.upper()}"
    if provider == "ollama":
        return os.getenv(f"BEEKEEPER_OLLAMA_MODEL{key_suffix}") or os.getenv("BEEKEEPER_OLLAMA_MODEL")
    if provider == "gemini":
        return os.getenv(f"BEEKEEPER_GEMINI_MODEL{key_suffix}") or os.getenv("BEEKEEPER_GEMINI_MODEL")
    if provider == "openai":
        return os.getenv(f"BEEKEEPER_OPENAI_MODEL{key_suffix}") or os.getenv("BEEKEEPER_OPENAI_MODEL")
    return None


class LLMRouter:
    """Routes chat requests to providers in order with fallback. Supports model_tier scoping."""

    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = providers

    def call(
        self,
        prompt: str,
        system: str | None = None,
        messages: list[dict[str, str]] | None = None,
        model_tier: str | None = None,
        model_override: str | None = None,
    ) -> tuple[str | None, str]:
        """Try each provider in order. model_override takes precedence; model_tier selects economy/standard/premium. Returns (text, source) or (None, 'fallback')."""
        resolved_model: str | None = model_override
        if not resolved_model and model_tier:
            for p in self.providers:
                provider_name = (
                    "ollama" if isinstance(p, OllamaProvider)
                    else "gemini" if isinstance(p, GeminiProvider)
                    else "openai" if isinstance(p, OpenAIProvider)
                    else "ollama"
                )
                resolved = _resolve_model_for_tier(model_tier, provider_name)
                if resolved:
                    resolved_model = resolved
                    break
        for p in self.providers:
            resp = p.chat(prompt, system=system, messages=messages, model_override=resolved_model)
            if resp and resp.text:
                log_service_call(resp.source, "completed", source="queen")
                return resp.text, resp.source
        return None, "fallback"

    @classmethod
    def from_env(cls) -> "LLMRouter":
        """Build router from BEEKEEPER_LLM_PROVIDERS and per-provider env vars."""
        providers_str = os.getenv("BEEKEEPER_LLM_PROVIDERS", "").strip()
        if not providers_str:
            # Legacy: single provider
            single = (os.getenv("BEEKEEPER_LLM_PROVIDER") or "ollama").strip().lower()
            providers_str = single

        provider_names = [p.strip().lower() for p in providers_str.split(",") if p.strip()]
        if not provider_names:
            provider_names = ["ollama"]

        providers: list[LLMProvider] = []
        for name in provider_names:
            if name == "ollama":
                providers.append(
                    OllamaProvider(
                        base_url=os.getenv("BEEKEEPER_OLLAMA_BASE_URL", "http://localhost:11434"),
                        model=os.getenv("BEEKEEPER_OLLAMA_MODEL", "llama3.2"),
                        timeout_seconds=int(os.getenv("BEEKEEPER_OLLAMA_TIMEOUT_SECONDS", "120")),
                    )
                )
            elif name == "gemini":
                key = (os.getenv("BEEKEEPER_GEMINI_API_KEY") or "").strip()
                if key:
                    providers.append(
                        GeminiProvider(
                            api_key=key,
                            model=os.getenv("BEEKEEPER_GEMINI_MODEL", "gemini-1.5-flash"),
                            timeout_seconds=int(os.getenv("BEEKEEPER_GEMINI_TIMEOUT_SECONDS", "120")),
                        )
                    )
            elif name == "openai":
                key = (os.getenv("BEEKEEPER_OPENAI_API_KEY") or "").strip()
                if key:
                    providers.append(
                        OpenAIProvider(
                            api_key=key,
                            model=os.getenv("BEEKEEPER_OPENAI_MODEL", "gpt-4o-mini"),
                            base_url=os.getenv("BEEKEEPER_OPENAI_BASE_URL") or None,
                            timeout_seconds=int(os.getenv("BEEKEEPER_OPENAI_TIMEOUT_SECONDS", "120")),
                        )
                    )
        if not providers:
            providers.append(
                OllamaProvider(
                    base_url=os.getenv("BEEKEEPER_OLLAMA_BASE_URL", "http://localhost:11434"),
                    model=os.getenv("BEEKEEPER_OLLAMA_MODEL", "llama3.2"),
                    timeout_seconds=int(os.getenv("BEEKEEPER_OLLAMA_TIMEOUT_SECONDS", "120")),
                )
            )
        return cls(providers)


def build_llm_router(
    *,
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
) -> LLMRouter:
    """Build LLMRouter from explicit config (for WorkerRuntime, etc.)."""
    if llm_providers:
        names = [p.strip().lower() for p in llm_providers.split(",") if p.strip()]
    else:
        single = os.getenv("BEEKEEPER_LLM_PROVIDER", "ollama").strip().lower()
        names = [single]

    providers: list[LLMProvider] = []
    for name in names:
        if name == "ollama":
            providers.append(
                OllamaProvider(
                    base_url=ollama_base_url,
                    model=ollama_model,
                    timeout_seconds=ollama_timeout_seconds,
                )
            )
        elif name == "gemini" and gemini_api_key:
            providers.append(
                GeminiProvider(
                    api_key=gemini_api_key,
                    model=gemini_model,
                    timeout_seconds=gemini_timeout_seconds,
                )
            )
        elif name == "openai" and openai_api_key:
            providers.append(
                OpenAIProvider(
                    api_key=openai_api_key,
                    model=openai_model,
                    base_url=openai_base_url,
                    timeout_seconds=openai_timeout_seconds,
                )
            )
    if not providers:
        providers.append(
            OllamaProvider(
                base_url=ollama_base_url,
                model=ollama_model,
                timeout_seconds=ollama_timeout_seconds,
            )
        )
    return LLMRouter(providers)
