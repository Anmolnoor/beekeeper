from __future__ import annotations

from typing import Any


CHANNEL_CAPABILITY_MATRIX: dict[str, dict[str, Any]] = {
    "slack": {
        "support_level": "supported",
        "ingress_verification": True,
        "replay_defense": True,
        "dedupe": True,
        "threads": True,
        "attachments": "partial",
        "slash_commands": True,
        "buttons": "partial",
        "edits": False,
    },
    "telegram": {
        "support_level": "experimental",
        "ingress_verification": True,
        "replay_defense": True,
        "dedupe": True,
        "threads": "partial",
        "attachments": "partial",
        "slash_commands": "partial",
        "buttons": "partial",
        "edits": False,
    },
    "discord": {
        "support_level": "experimental",
        "ingress_verification": True,
        "replay_defense": True,
        "dedupe": True,
        "threads": "partial",
        "attachments": "partial",
        "slash_commands": True,
        "buttons": "partial",
        "edits": False,
    },
    "whatsapp": {
        "support_level": "experimental",
        "ingress_verification": True,
        "replay_defense": True,
        "dedupe": True,
        "threads": False,
        "attachments": "partial",
        "slash_commands": False,
        "buttons": False,
        "edits": False,
    },
}
