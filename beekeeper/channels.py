from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .queen import QueenAgent


@dataclass
class ChannelMessage:
    channel: str
    sender: str
    text: str
    metadata: dict[str, Any]


class ChannelAdapter:
    channel: str = "unknown"

    def format_inbound(self, payload: dict[str, Any]) -> ChannelMessage:
        return ChannelMessage(
            channel=self.channel,
            sender=str(payload.get("sender", "anonymous")),
            text=str(payload.get("text", "")),
            metadata=payload,
        )

    def format_outbound(self, response: dict[str, Any]) -> dict[str, Any]:
        return {"channel": self.channel, "response": response}


class SlackAdapter(ChannelAdapter):
    channel = "slack"


class TelegramAdapter(ChannelAdapter):
    channel = "telegram"


class DiscordAdapter(ChannelAdapter):
    channel = "discord"


class WhatsAppAdapter(ChannelAdapter):
    channel = "whatsapp"


class ChatHub:
    def __init__(self, queen: QueenAgent) -> None:
        self.queen = queen
        self.adapters: dict[str, ChannelAdapter] = {
            "slack": SlackAdapter(),
            "telegram": TelegramAdapter(),
            "discord": DiscordAdapter(),
            "whatsapp": WhatsAppAdapter(),
        }

    def dispatch(
        self,
        channel: str,
        payload: dict[str, Any],
        intent: str = "research_topic",
        source: str | None = None,
    ) -> dict[str, Any]:
        adapter = self.adapters.get(channel)
        if adapter is None:
            raise ValueError(f"unsupported_channel={channel}")
        inbound = adapter.format_inbound(payload)
        run_source = source or f"channel:{channel}"
        run = self.queen.run(
            intent=intent,
            payload={"query": inbound.text, **inbound.metadata},
            source=run_source,
        )
        return adapter.format_outbound(run)
