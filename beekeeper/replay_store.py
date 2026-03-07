from __future__ import annotations

from dataclasses import dataclass

from .data_plane.repositories import DurableStateRepository


@dataclass
class ReplayStore:
    repo: DurableStateRepository
    default_ttl_seconds: int = 86_400

    def claim(self, *, channel: str, replay_key: str, ttl_seconds: int | None = None) -> bool:
        if not replay_key.strip():
            return True
        return self.repo.claim_webhook_replay_key(
            channel=channel.strip().lower(),
            replay_key=replay_key.strip(),
            ttl_seconds=int(ttl_seconds or self.default_ttl_seconds),
        )
