"""Channel mention check: require @mention before processing when require_mention is enabled."""
from __future__ import annotations

from typing import Any


def _get_slack_bot_user_id(bot_token: str) -> str | None:
    """Fetch Slack bot user ID via auth.test. Returns None on failure."""
    try:
        from slack_sdk import WebClient
        client = WebClient(token=bot_token)
        resp = client.auth_test()
        if resp.get("ok"):
            return resp.get("user_id")
    except Exception:
        pass
    return None


def check_mention_required(
    config: dict[str, Any],
    channel: str,
    text: str,
    *,
    bot_user_id: str | None = None,
    chat_type: str | None = None,
) -> tuple[bool, str | None]:
    """
    Check if message should be processed when require_mention is enabled.
    Returns (should_process, reason_if_denied).
    - If require_mention is False: return (True, None).
    - If require_mention is True and message mentions bot: return (True, None).
    - If require_mention is True and no mention: return (False, "mention_required").
    """
    if not config.get("require_mention"):
        return True, None

    text = (text or "").strip()
    if not text:
        return False, "mention_required"

    if channel == "slack":
        bid = bot_user_id or config.get("slack_bot_user_id")
        if not bid:
            return True, None  # No bot id configured: allow (cannot verify mention)
        mention = f"<@{bid}>"
        if mention in text:
            return True, None
        return False, "mention_required"

    if channel == "telegram":
        if chat_type == "private":
            return True, None  # DMs: no mention needed
        username = config.get("telegram_bot_username", "").strip().lstrip("@")
        if not username:
            return True, None
        if username.lower() in text.lower() or f"@{username}".lower() in text.lower():
            return True, None
        return False, "mention_required"

    if channel == "discord":
        bid = bot_user_id or config.get("discord_bot_id") or config.get("discord_application_id")
        if not bid:
            return True, None
        mention = f"<@{bid}>"
        if mention in text:
            return True, None
        return False, "mention_required"

    return True, None
