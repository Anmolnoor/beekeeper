"""Channel allowlists: restrict which channels and users can use the bot."""
from __future__ import annotations

from typing import Any


def check_channel_allowlist(
    config: dict[str, Any],
    channel_id: str | None,
    user_id: str,
) -> tuple[bool, str | None]:
    """
    Check if the incoming request is allowed by channel config.

    Config may include:
      - allowed_channel_ids: list of channel IDs (Slack channel, Discord channel_id, Telegram chat_id as str)
      - allowed_user_ids: list of user IDs (Slack/Discord user id, Telegram from.id as str)

    When a list is absent or empty, that dimension has no restriction.
    When non-empty, the request must match.

    Returns (allowed, reason_if_denied).
    """
    allowed_channels = config.get("allowed_channel_ids")
    if isinstance(allowed_channels, list) and len(allowed_channels) > 0:
        if not channel_id or channel_id not in [str(c) for c in allowed_channels]:
            return False, "channel_not_in_allowlist"

    allowed_users = config.get("allowed_user_ids")
    if isinstance(allowed_users, list) and len(allowed_users) > 0:
        if not user_id or user_id not in [str(u) for u in allowed_users]:
            return False, "user_not_in_allowlist"

    return True, None
