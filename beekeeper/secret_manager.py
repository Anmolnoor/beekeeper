from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class SecretProvider(Protocol):
    def resolve(self, reference: str) -> str:
        ...


class SecretResolutionError(RuntimeError):
    pass


class EnvSecretProvider:
    def resolve(self, reference: str) -> str:
        key = reference.removeprefix("secret://env/").removeprefix("env://").removeprefix("env:")
        value = os.getenv(key, "")
        if not value:
            raise SecretResolutionError(f"missing_env_secret:{key}")
        return value


class LocalFileSecretProvider:
    def resolve(self, reference: str) -> str:
        raw = reference.removeprefix("secret://file/").removeprefix("file://")
        path = Path(raw)
        if not path.exists():
            raise SecretResolutionError(f"missing_file_secret:{path}")
        return path.read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class VaultSecretProvider:
    address: str
    token: str

    def resolve(self, reference: str) -> str:
        path = reference.removeprefix("secret://vault/").removeprefix("vault://")
        request = urllib.request.Request(
            f"{self.address.rstrip('/')}/v1/{path.lstrip('/')}",
            headers={"X-Vault-Token": self.token},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # pragma: no cover - network path
            raise SecretResolutionError(f"vault_resolution_failed:{path}:{exc}") from exc
        data = payload.get("data", {})
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        if not isinstance(data, dict) or "value" not in data:
            raise SecretResolutionError(f"vault_secret_missing_value:{path}")
        value = str(data["value"]).strip()
        if not value:
            raise SecretResolutionError(f"vault_secret_empty:{path}")
        return value


def is_secret_reference(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized.startswith(("secret://", "env://", "env:", "vault://", "file://"))


def build_secret_provider(provider: str | None = None) -> SecretProvider:
    selected = (provider or os.getenv("BEEKEEPER_SECRET_MANAGER_PROVIDER") or "env").strip().lower()
    if selected == "vault":
        address = os.getenv("BEEKEEPER_VAULT_ADDR", "").strip()
        token = os.getenv("BEEKEEPER_VAULT_TOKEN", "").strip()
        if not address or not token:
            raise SecretResolutionError("vault_provider_requires_address_and_token")
        return VaultSecretProvider(address=address, token=token)
    if selected in {"env", "environment"}:
        return EnvSecretProvider()
    if selected in {"local", "filesystem", "file"}:
        return LocalFileSecretProvider()
    raise SecretResolutionError(f"unsupported_secret_provider:{selected}")
