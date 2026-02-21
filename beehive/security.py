from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _secret() -> bytes:
    return os.getenv("BEEKEEPER_AUDIT_SIGNING_KEY", "beekeeper-dev-signing-key").encode("utf-8")


def sign_payload(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hmac.new(_secret(), body, hashlib.sha256).hexdigest()


def verify_payload(payload: dict[str, Any], signature: str) -> bool:
    expected = sign_payload(payload)
    return hmac.compare_digest(expected, signature)


def append_signed_audit_log(path: Path, event: dict[str, Any]) -> dict[str, Any]:
    stamped = {"at": datetime.now(timezone.utc).isoformat(), **event}
    stamped["signature"] = sign_payload(stamped)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(stamped, ensure_ascii=True) + "\n")
    return stamped
