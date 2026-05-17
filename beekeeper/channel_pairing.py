"""Channel pairing for DMs: require pairing code before processing DM messages."""
from __future__ import annotations

import re
from typing import Any


def is_dm(channel: str, payload: dict[str, Any]) -> bool:
    """Detect if the message is from a DM."""
    if channel == "slack":
        ev = payload.get("event", {})
        return ev.get("channel_type") == "im"
    if channel == "telegram":
        msg = payload.get("message", {})
        chat = msg.get("chat", {})
        return chat.get("type") == "private"
    if channel == "discord":
        # For slash commands, check if channel is a DM (optional)
        return False  # Discord webhook uses slash commands; DM detection would need channel API
    return False


def looks_like_pairing_code(text: str) -> bool:
    """Check if message looks like a 6-digit pairing code."""
    return bool(re.fullmatch(r"\d{6}", (text or "").strip()))
