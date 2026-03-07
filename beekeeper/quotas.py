from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .store import BeekeeperStore


@dataclass
class TenantQuotaManager:
    store: BeekeeperStore

    DEFAULTS: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.DEFAULTS is None:
            self.DEFAULTS = {
                "concurrent_runs": 10,
                "daily_runs": 500,
                "channel_send_daily": 1000,
                "webhook_ingest_daily": 5000,
            }

    def _today_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _org_key(self, org_id: str | None) -> str:
        org = (org_id or "").strip()
        return org if org else "__default__"

    def _quota_config(self) -> dict[str, Any]:
        payload = self.store.read_setting("tenant_quotas", default={})
        return payload if isinstance(payload, dict) else {}

    def _quota_state(self) -> dict[str, Any]:
        payload = self.store.read_setting("tenant_quota_state", default={})
        return payload if isinstance(payload, dict) else {}

    def _write_state(self, state: dict[str, Any]) -> None:
        self.store.write_setting("tenant_quota_state", state)

    def get_quota(self, org_id: str | None) -> dict[str, int]:
        config = self._quota_config()
        org_key = self._org_key(org_id)
        row = config.get(org_key) or config.get("__default__") or {}
        quota: dict[str, int] = {}
        for key, default in self.DEFAULTS.items():
            try:
                quota[key] = max(1, int(row.get(key, default)))
            except (TypeError, ValueError):
                quota[key] = default
        return quota

    def _state_row(self, state: dict[str, Any], org_id: str | None) -> dict[str, Any]:
        org_key = self._org_key(org_id)
        row = state.get(org_key)
        if not isinstance(row, dict):
            row = {}
        if str(row.get("day", "")) != self._today_key():
            row = {
                "day": self._today_key(),
                "runs_started": 0,
                "runs_completed": 0,
                "channel_sends": 0,
                "webhook_ingest": 0,
                "in_flight_runs": 0,
            }
        state[org_key] = row
        return row

    def check_and_start_run(self, org_id: str | None) -> tuple[bool, str]:
        state = self._quota_state()
        quota = self.get_quota(org_id)
        row = self._state_row(state, org_id)
        if int(row.get("in_flight_runs", 0)) >= quota["concurrent_runs"]:
            return False, "concurrent_run_quota_exceeded"
        if int(row.get("runs_started", 0)) >= quota["daily_runs"]:
            return False, "daily_run_quota_exceeded"
        row["runs_started"] = int(row.get("runs_started", 0)) + 1
        row["in_flight_runs"] = int(row.get("in_flight_runs", 0)) + 1
        self._write_state(state)
        return True, "ok"

    def complete_run(self, org_id: str | None, *, success: bool) -> None:
        state = self._quota_state()
        row = self._state_row(state, org_id)
        row["in_flight_runs"] = max(0, int(row.get("in_flight_runs", 0)) - 1)
        if success:
            row["runs_completed"] = int(row.get("runs_completed", 0)) + 1
        self._write_state(state)

    def record_channel_send(self, org_id: str | None) -> tuple[bool, str]:
        state = self._quota_state()
        quota = self.get_quota(org_id)
        row = self._state_row(state, org_id)
        if int(row.get("channel_sends", 0)) >= quota["channel_send_daily"]:
            return False, "channel_send_quota_exceeded"
        row["channel_sends"] = int(row.get("channel_sends", 0)) + 1
        self._write_state(state)
        return True, "ok"

    def record_webhook_ingest(self, org_id: str | None) -> tuple[bool, str]:
        state = self._quota_state()
        quota = self.get_quota(org_id)
        row = self._state_row(state, org_id)
        if int(row.get("webhook_ingest", 0)) >= quota["webhook_ingest_daily"]:
            return False, "webhook_ingest_quota_exceeded"
        row["webhook_ingest"] = int(row.get("webhook_ingest", 0)) + 1
        self._write_state(state)
        return True, "ok"

    def snapshot(self, org_id: str | None) -> dict[str, Any]:
        state = self._quota_state()
        row = self._state_row(state, org_id)
        return {
            "org_id": self._org_key(org_id),
            "quota": self.get_quota(org_id),
            "usage": {
                "day": row.get("day", self._today_key()),
                "runs_started": int(row.get("runs_started", 0)),
                "runs_completed": int(row.get("runs_completed", 0)),
                "in_flight_runs": int(row.get("in_flight_runs", 0)),
                "channel_sends": int(row.get("channel_sends", 0)),
                "webhook_ingest": int(row.get("webhook_ingest", 0)),
            },
        }
