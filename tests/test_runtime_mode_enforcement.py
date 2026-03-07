from __future__ import annotations

import pytest

from beekeeper.config import ConfigValidationError
from beekeeper.runner import _enforce_runtime_mode_or_exit


_CRITICAL_KEYS = [
    "BEEKEEPER_JWT_SECRET",
    "BEEKEEPER_AUDIT_SIGNING_KEY",
    "BEEKEEPER_CHANNEL_ENCRYPTION_KEY",
    "BEEKEEPER_WEBHOOK_SECRET",
    "BEEKEEPER_DATABASE_DSN",
    "BEEKEEPER_OBJECT_STORAGE_ENDPOINT",
    "BEEKEEPER_OBJECT_STORAGE_BUCKET",
    "BEEKEEPER_TEMPORAL_ENDPOINT",
    "BEEKEEPER_TEMPORAL_NAMESPACE",
    "BEEKEEPER_SECRET_MANAGER_PROVIDER",
]


def test_runtime_mode_enforcement_blocks_non_bypass_commands(monkeypatch) -> None:
    monkeypatch.setenv("BEEKEEPER_RUNTIME_MODE", "prod")
    for key in _CRITICAL_KEYS:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ConfigValidationError):
        _enforce_runtime_mode_or_exit("run")


def test_runtime_mode_enforcement_allows_bypass_commands(monkeypatch) -> None:
    monkeypatch.setenv("BEEKEEPER_RUNTIME_MODE", "prod")
    for key in _CRITICAL_KEYS:
        monkeypatch.delenv(key, raising=False)
    _enforce_runtime_mode_or_exit("doctor")
