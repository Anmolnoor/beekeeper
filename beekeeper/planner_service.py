from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class PlannerService:
    worker_registry: Any
    worker_runtime: Any
    skill_creation_phrases: tuple[str, ...]

    def detect_skill_creation_intent(self, query: str) -> bool:
        lower = query.lower()
        return any(phrase in lower for phrase in self.skill_creation_phrases)

    def classify_intent_with_llm(self, query: str, payload: dict[str, Any]) -> dict[str, Any]:
        del payload  # reserved for future richer prompts
        try:
            dynamic_workers = self.worker_registry.format_workers_for_prompt()
            if not dynamic_workers:
                return {}
            classification_prompt = (
                "You are routing a user request. Given the available workers below, "
                "respond with JSON only — no explanation, no markdown fences:\n"
                '{"intent": "<short_snake_case_intent>", "worker_hint": "<worker_kind or empty string>", '
                '"tags": ["tag1", "tag2"], "needs_delegation": true}\n\n'
                f"{dynamic_workers}\n\n"
                f"User query: {query}"
            )
            reply, _ = self.worker_runtime.direct_chat(
                query=classification_prompt,
                system="You are a routing classifier. Return only valid JSON.",
            )
            if not reply:
                return {}
            json_match = re.search(r"\{[^{}]*\}", reply, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return json.loads(reply.strip())
        except Exception:
            return {}
