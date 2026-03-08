from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .llm_provider import LLMRouter, build_llm_router
from .store import BeekeeperStore


LITE_SYSTEM_PROMPT = """You are Beekeeper Lite, a simple personal assistant.

Rules:
- Be direct and concise.
- Do not claim to have searched the web, saved files, run tools, or completed actions unless that actually happened outside the model.
- If a request needs a real tool or file operation that is not available in this chat path, say that plainly.
- Do not roleplay a queen, hive, worker manager, or orchestration system.
- Prefer practical answers over process narration.
"""


@dataclass
class LiteAssistantConfig:
    store_root: Path = field(
        default_factory=lambda: Path(os.getenv("BEEKEEPER_STORE_ROOT", ".beekeeper_store"))
    )
    llm_provider: str = field(default_factory=lambda: os.getenv("BEEKEEPER_LLM_PROVIDER", "ollama"))
    llm_providers: str = field(
        default_factory=lambda: os.getenv("BEEKEEPER_LLM_PROVIDERS", "openai,gemini,ollama")
    )
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv("BEEKEEPER_OLLAMA_BASE_URL", "http://localhost:11434")
    )
    ollama_model: str = field(default_factory=lambda: os.getenv("BEEKEEPER_OLLAMA_MODEL", "llama3.2"))
    ollama_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("BEEKEEPER_OLLAMA_TIMEOUT_SECONDS", "120"))
    )
    gemini_api_key: str = field(default_factory=lambda: os.getenv("BEEKEEPER_GEMINI_API_KEY", ""))
    gemini_model: str = field(
        default_factory=lambda: os.getenv("BEEKEEPER_GEMINI_MODEL", "gemini-1.5-flash")
    )
    gemini_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("BEEKEEPER_GEMINI_TIMEOUT_SECONDS", "120"))
    )
    openai_api_key: str = field(default_factory=lambda: os.getenv("BEEKEEPER_OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.getenv("BEEKEEPER_OPENAI_MODEL", "gpt-4o-mini"))
    openai_base_url: str | None = field(
        default_factory=lambda: os.getenv("BEEKEEPER_OPENAI_BASE_URL") or None
    )
    openai_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("BEEKEEPER_OPENAI_TIMEOUT_SECONDS", "120"))
    )


def _normalize_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "user")).strip() or "user"
        if role not in {"system", "user", "assistant"}:
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(str(part.get("text", "")).strip())
                elif isinstance(part, str):
                    parts.append(part.strip())
            text = " ".join(part for part in parts if part).strip()
        else:
            text = str(content).strip()
        if text:
            normalized.append({"role": role, "content": text})
    return normalized


class LiteAssistant:
    def __init__(
        self,
        config: LiteAssistantConfig | None = None,
        *,
        router: LLMRouter | None = None,
        store: BeekeeperStore | None = None,
    ) -> None:
        self.config = config or LiteAssistantConfig()
        self.router = router or build_llm_router(
            llm_provider=self.config.llm_provider,
            llm_providers=self.config.llm_providers,
            ollama_base_url=self.config.ollama_base_url,
            ollama_model=self.config.ollama_model,
            ollama_timeout_seconds=self.config.ollama_timeout_seconds,
            gemini_api_key=self.config.gemini_api_key,
            gemini_model=self.config.gemini_model,
            gemini_timeout_seconds=self.config.gemini_timeout_seconds,
            openai_api_key=self.config.openai_api_key,
            openai_model=self.config.openai_model,
            openai_base_url=self.config.openai_base_url,
            openai_timeout_seconds=self.config.openai_timeout_seconds,
        )
        self.store = store or BeekeeperStore(self.config.store_root)

    def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        user_id: str,
        chat_id: str | None = None,
        model_override: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_messages(messages)
        if not normalized:
            return {
                "ok": False,
                "reply": "Please provide a message to process.",
                "chat_id": chat_id,
                "provider": "none",
            }

        chat = self.store.get_chat(chat_id) if chat_id else None
        if chat is None:
            title = next(
                (m["content"] for m in normalized if m["role"] == "user"),
                "New Chat",
            )
            chat = self.store.create_chat(user_id=user_id, title=title[:60] or "New Chat")
            chat_id = str(chat["chat_id"])

        existing_messages = chat.get("messages", [])
        if not existing_messages:
            for message in normalized[:-1]:
                self.store.append_chat_message(
                    chat_id=chat_id,
                    role=message["role"],
                    content=message["content"],
                )

        latest_user_message = next(
            (message["content"] for message in reversed(normalized) if message["role"] == "user"),
            "",
        )
        if not latest_user_message:
            return {
                "ok": False,
                "reply": "Please provide a user message to process.",
                "chat_id": chat_id,
                "provider": "none",
            }

        if not existing_messages or (
            existing_messages
            and existing_messages[-1].get("role") != "user"
            and latest_user_message
        ):
            self.store.append_chat_message(chat_id=chat_id, role="user", content=latest_user_message)

        prompt_messages = normalized[:-1]
        prompt, provider = self.router.call(
            latest_user_message,
            system=LITE_SYSTEM_PROMPT,
            messages=prompt_messages if prompt_messages else None,
            model_override=model_override,
        )
        reply = (prompt or "").strip()
        if not reply:
            reply = (
                "No model response was available. Check your configured LLM provider "
                "or local Ollama/OpenAI/Gemini settings."
            )
            provider = "fallback"

        self.store.append_chat_message(
            chat_id=chat_id,
            role="assistant",
            content=reply,
            source=provider,
        )
        saved_chat = self.store.get_chat(chat_id) or chat
        return {
            "ok": True,
            "reply": reply,
            "chat_id": chat_id,
            "provider": provider,
            "messages": saved_chat.get("messages", []),
            "title": saved_chat.get("title", "New Chat"),
        }

    def list_chats(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_chats(user_id=user_id, limit=limit)

    def get_chat(self, chat_id: str) -> dict[str, Any] | None:
        return self.store.get_chat(chat_id)
