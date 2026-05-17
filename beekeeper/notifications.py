"""Push notifications for HITL approvals to WhatsApp/Telegram."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from .store import BeekeeperStore


def _get_store() -> BeekeeperStore:
    root = Path(os.getenv("BEEKEEPER_STORE_ROOT", ".beekeeper_store"))
    if not root.is_absolute():
        root = Path.cwd() / root
    return BeekeeperStore(root=root)


def send_approval_notification(review_id: str, task_id: str, reason: str) -> None:
    """Send push notification to WhatsApp/Telegram when HITL approval is needed."""
    base = os.getenv("BEEKEEPER_BASE_URL", "http://localhost:8788")
    msg = f"HITL approval needed: task_id={task_id}, reason={reason}. Approve at {base}/dashboard#approvals"
    store = _get_store()
    for channel in ("telegram", "whatsapp"):
        try:
            config = store.get_channel_config_decrypted(channel)
            if not config:
                continue
            if channel == "telegram":
                token = config.get("telegram_bot_token")
                chat_id = config.get("hitl_notify_chat_id") or config.get("telegram_admin_chat_id")
                if token and chat_id:
                    url = f"https://api.telegram.org/bot{token}/sendMessage"
                    req = urllib.request.Request(
                        url,
                        data=urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode(),
                        method="POST",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    urllib.request.urlopen(req, timeout=10)
            elif channel == "whatsapp":
                token = config.get("whatsapp_access_token")
                phone_id = config.get("whatsapp_phone_number_id")
                to = config.get("hitl_notify_phone")
                if token and phone_id and to:
                    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
                    data = json.dumps({
                        "messaging_product": "whatsapp",
                        "to": to.replace("@s.whatsapp.net", ""),
                        "type": "text",
                        "text": {"body": msg[:4000]},
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        url,
                        data=data,
                        method="POST",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                        },
                    )
                    urllib.request.urlopen(req, timeout=15)
        except Exception:
            pass
