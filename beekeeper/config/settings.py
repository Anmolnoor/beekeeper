from __future__ import annotations

import os
from enum import Enum


class RuntimeMode(str, Enum):
    DEV = "dev"
    INTERNAL = "internal"
    PROD = "prod"


def resolve_runtime_mode() -> RuntimeMode:
    """Resolve platform runtime mode with conservative fallback to dev."""
    raw = (os.getenv("BEEKEEPER_RUNTIME_MODE") or "dev").strip().lower()
    aliases = {
        "development": "dev",
        "staging": "internal",
        "production": "prod",
    }
    normalized = aliases.get(raw, raw)
    if normalized == "internal":
        return RuntimeMode.INTERNAL
    if normalized == "prod":
        return RuntimeMode.PROD
    return RuntimeMode.DEV
