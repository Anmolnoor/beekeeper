from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_idempotency_key(namespace: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    raw = f"{namespace}:{canonical}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
