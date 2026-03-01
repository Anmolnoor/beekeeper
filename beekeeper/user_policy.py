"""user_policy.py — Per-user autonomy policy for Beekeeper Queen.

Users can configure what the Queen may do autonomously vs. must ask about.
Stored at: .beekeeper_store/users/{user_id}/policy.json
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field


class UserPolicy(BaseModel):
    """User-configurable autonomy policy. Controls Queen's autonomous behaviour."""

    always_allow: list[str] = Field(
        default_factory=lambda: ["web_search", "summarize", "answer"],
        description="Action categories Queen may perform without asking.",
    )
    always_ask: list[str] = Field(
        default_factory=lambda: ["write_file", "delete_file", "spawn_worker", "send_email"],
        description="Action categories Queen must ask before performing.",
    )
    always_deny: list[str] = Field(
        default_factory=list,
        description="Action categories Queen is never allowed to perform.",
    )
    max_auto_cost_usd: float = Field(
        default=0.50,
        description="Max USD Queen can spend autonomously per request.",
    )
    updated_at: str | None = None


DEFAULT_USER_POLICY = UserPolicy()


def _policy_path(store_root: str | Path, user_id: str) -> Path:
    return Path(store_root) / "users" / user_id / "policy.json"


def load_user_policy(store_root: str | Path, user_id: str) -> UserPolicy:
    """Load user policy from disk, returning the default if not found."""
    path = _policy_path(store_root, user_id)
    if not path.exists():
        return UserPolicy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return UserPolicy.model_validate(data)
    except Exception:
        return UserPolicy()


def save_user_policy(store_root: str | Path, user_id: str, policy: UserPolicy) -> None:
    """Persist user policy to disk."""
    path = _policy_path(store_root, user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    policy.updated_at = datetime.now(timezone.utc).isoformat()
    path.write_text(
        json.dumps(policy.model_dump(mode="json"), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def policy_allows_action(policy: UserPolicy, action: str) -> tuple[bool, str]:
    """Check if an action is allowed under policy.

    Returns (allowed: bool, disposition: "allow" | "ask" | "deny").
    """
    if action in (policy.always_deny or []):
        return False, "deny"
    if action in (policy.always_ask or []):
        return False, "ask"
    if action in (policy.always_allow or []):
        return True, "allow"
    # Default: ask for unknown actions
    return False, "ask"


def merge_policy_into_autonomy(policy: UserPolicy, autonomy_policy: "Any") -> "Any":
    """Apply user policy overrides to an AutonomyPolicy object.

    Returns a new AutonomyPolicy with the user's allowed_intents merged in,
    and max_auto_cost_usd updated.
    """
    from .autonomy import AutonomyPolicy

    allowed_map = {
        "web_search": "research_topic",
        "summarize": "summarize_traces",
        "answer": "research_topic",
        "compute": "heavy_compute",
    }
    extra_intents: set[str] = set()
    for action in (policy.always_allow or []):
        if action in allowed_map:
            extra_intents.add(allowed_map[action])
        extra_intents.add(action)

    new_allowed = frozenset(autonomy_policy.allowed_intents | extra_intents)

    deny_set = frozenset(policy.always_deny or [])
    new_hitl = frozenset(autonomy_policy.require_human_approval_for | frozenset(policy.always_ask or []) | deny_set)

    return AutonomyPolicy(
        allowed_intents=new_allowed,
        max_auto_cost_usd=policy.max_auto_cost_usd,
        min_confidence_before_autorelease=autonomy_policy.min_confidence_before_autorelease,
        require_human_approval_for=new_hitl,
    )
