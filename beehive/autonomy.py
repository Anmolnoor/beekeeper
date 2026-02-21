"""Autonomy policy: what the Queen is allowed to do without human request.

The Queen checks this before running a task from Pulse (not from user).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AutonomyPolicy:
    """Defines what the Queen can do autonomously when invoked by Pulse."""

    allowed_intents: frozenset[str]
    max_auto_cost_usd: float
    min_confidence_before_autorelease: float
    require_human_approval_for: frozenset[str]

    def allows_intent(self, intent: str) -> bool:
        return intent in self.allowed_intents

    def allows_payload(self, payload: dict[str, Any]) -> tuple[bool, str | None]:
        """Check if payload triggers human-approval-required actions."""
        action = str(payload.get("action", "")).strip()
        if action and action in self.require_human_approval_for:
            return False, f"action_requires_human_approval:{action}"
        for key in ("data_delete", "financial_transaction", "privacy_sensitive_export"):
            if payload.get(key) is True and key in self.require_human_approval_for:
                return False, f"payload_requires_human_approval:{key}"
        return True, None

    def validate(self, intent: str, payload: dict[str, Any]) -> tuple[bool, str | None]:
        """Validate that the task is allowed under autonomy policy."""
        if not self.allows_intent(intent):
            return False, f"intent_not_allowed:{intent}"
        ok, reason = self.allows_payload(payload)
        if not ok:
            return False, reason
        return True, None


DEFAULT_AUTONOMY_POLICY = AutonomyPolicy(
    allowed_intents=frozenset({"research_topic", "heavy_compute", "summarize_traces"}),
    max_auto_cost_usd=0.5,
    min_confidence_before_autorelease=0.75,
    require_human_approval_for=frozenset({"data_delete", "financial_transaction", "privacy_sensitive_export"}),
)
