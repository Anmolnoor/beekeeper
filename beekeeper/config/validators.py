from __future__ import annotations

import os
from dataclasses import dataclass

from .settings import RuntimeMode


@dataclass(frozen=True)
class RuntimeConfigValidationReport:
    mode: RuntimeMode
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


class ConfigValidationError(RuntimeError):
    """Raised when runtime configuration is invalid for the selected mode."""


def _is_missing(name: str) -> bool:
    return not (os.getenv(name) or "").strip()


def _is_dev_default(value: str, *, denylist: set[str]) -> bool:
    normalized = value.strip().lower()
    return normalized in denylist or "dev" in normalized


def validate_runtime_config(mode: RuntimeMode) -> RuntimeConfigValidationReport:
    """Validate runtime settings. Non-dev modes fail closed on critical config."""
    errors: list[str] = []
    warnings: list[str] = []

    critical_required = [
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

    if mode is RuntimeMode.DEV:
        for name in critical_required:
            if _is_missing(name):
                warnings.append(f"{name} is not set (allowed in dev mode)")
        return RuntimeConfigValidationReport(mode=mode, errors=errors, warnings=warnings)

    for name in critical_required:
        if _is_missing(name):
            errors.append(f"{name} is required in {mode.value} mode")

    jwt_secret = (os.getenv("BEEKEEPER_JWT_SECRET") or "").strip()
    if jwt_secret and _is_dev_default(
        jwt_secret,
        denylist={"dev-secret-change-in-production", "beekeeper-dev-jwt"},
    ):
        errors.append("BEEKEEPER_JWT_SECRET uses an insecure development default")

    audit_key = (os.getenv("BEEKEEPER_AUDIT_SIGNING_KEY") or "").strip()
    if audit_key and _is_dev_default(
        audit_key,
        denylist={"beekeeper-dev-signing-key", "dev-signing-key"},
    ):
        errors.append("BEEKEEPER_AUDIT_SIGNING_KEY uses an insecure development default")

    provider = (os.getenv("BEEKEEPER_SECRET_MANAGER_PROVIDER") or "").strip().lower()
    if provider and provider in {"none", "local", "filesystem"}:
        errors.append("BEEKEEPER_SECRET_MANAGER_PROVIDER must reference a managed secret backend")

    return RuntimeConfigValidationReport(mode=mode, errors=errors, warnings=warnings)


def format_runtime_validation_errors(report: RuntimeConfigValidationReport) -> str:
    items = "\n".join(f"- {err}" for err in report.errors)
    return f"runtime config validation failed for mode '{report.mode.value}':\n{items}"
