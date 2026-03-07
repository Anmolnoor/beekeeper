from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .store import BeekeeperStore


@dataclass
class TenantRateLimiter:
    store: BeekeeperStore

    def _org_key(self, org_id: str | None) -> str:
        org = (org_id or "").strip()
        return org if org else "__default__"

    def _config(self) -> dict[str, Any]:
        payload = self.store.read_setting("tenant_rate_limits", default={})
        return payload if isinstance(payload, dict) else {}

    def _state(self) -> dict[str, Any]:
        payload = self.store.read_setting("tenant_rate_limit_state", default={})
        return payload if isinstance(payload, dict) else {}

    def _write_state(self, state: dict[str, Any]) -> None:
        self.store.write_setting("tenant_rate_limit_state", state)

    def limit_for(self, org_id: str | None, key: str, default: int) -> int:
        cfg = self._config()
        org_key = self._org_key(org_id)
        row = cfg.get(org_key) or cfg.get("__default__") or {}
        try:
            return max(1, int(row.get(key, default)))
        except (TypeError, ValueError):
            return default

    def check_and_record(
        self,
        *,
        org_id: str | None,
        key: str,
        default_limit: int,
        window_seconds: int = 60,
    ) -> tuple[bool, int, int]:
        state = self._state()
        org_key = self._org_key(org_id)
        org_state = state.get(org_key)
        if not isinstance(org_state, dict):
            org_state = {}
            state[org_key] = org_state
        events = org_state.get(key)
        if not isinstance(events, list):
            events = []
        now_ts = int(datetime.now(timezone.utc).timestamp())
        keep_after = now_ts - max(1, int(window_seconds))
        pruned = [int(ts) for ts in events if isinstance(ts, int) and ts > keep_after]
        limit = self.limit_for(org_id, key, default=default_limit)
        if len(pruned) >= limit:
            org_state[key] = pruned
            self._write_state(state)
            return False, len(pruned), limit
        pruned.append(now_ts)
        org_state[key] = pruned
        self._write_state(state)
        return True, len(pruned), limit

    def snapshot(self, org_id: str | None) -> dict[str, Any]:
        cfg = self._config()
        state = self._state()
        org_key = self._org_key(org_id)
        return {
            "org_id": org_key,
            "configured": cfg.get(org_key) or cfg.get("__default__") or {},
            "state": state.get(org_key) if isinstance(state.get(org_key), dict) else {},
        }
