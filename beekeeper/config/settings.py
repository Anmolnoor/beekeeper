from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any


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


class Phase1Settings:
    """Local-first Phase 1 runtime settings.

    The supported production topology is Postgres + MinIO, but the default
    local/test implementation keeps the same runtime shape using a local sqlite
    file and artifact directory until those adapters are wired in.
    """

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        runtime_root: Path | None = None,
        state_db_path: Path | None = None,
        artifact_root: Path | None = None,
        durable_state_backend: str | None = None,
        database_url: str | None = None,
        artifact_backend: str | None = None,
        minio_endpoint: str | None = None,
        minio_access_key: str | None = None,
        minio_secret_key: str | None = None,
        minio_bucket: str | None = None,
        minio_secure: bool | None = None,
        api_host: str | None = None,
        api_port: int | None = None,
        supervisor_poll_seconds: float | None = None,
        bash_allowlist: list[str] | None = None,
        enable_network_worker: bool | None = None,
        allowed_network_hosts: list[str] | None = None,
    ) -> None:
        cwd = Path.cwd()
        self.workspace_root = (workspace_root or Path(os.getenv("BEEKEEPER_WORKSPACE_ROOT", str(cwd)))).resolve()
        self.runtime_root = (runtime_root or Path(os.getenv("BEEKEEPER_RUNTIME_ROOT", str(self.workspace_root / ".beekeeper")))).resolve()
        self.state_db_path = (state_db_path or Path(os.getenv("BEEKEEPER_STATE_DB_PATH", str(self.runtime_root / "state" / "phase1.db")))).resolve()
        self.artifact_root = (artifact_root or Path(os.getenv("BEEKEEPER_ARTIFACT_ROOT", str(self.runtime_root / "artifacts")))).resolve()
        self.durable_state_backend = (durable_state_backend or os.getenv("BEEKEEPER_DURABLE_STATE_BACKEND", "sqlite")).strip().lower()
        default_db_url = f"sqlite:///{self.state_db_path}"
        self.database_url = (database_url or os.getenv("BEEKEEPER_DATABASE_URL", default_db_url)).strip()
        self.artifact_backend = (artifact_backend or os.getenv("BEEKEEPER_ARTIFACT_BACKEND", "local")).strip().lower()
        self.minio_endpoint = (minio_endpoint or os.getenv("BEEKEEPER_MINIO_ENDPOINT", "localhost:9000")).strip()
        self.minio_access_key = (minio_access_key or os.getenv("BEEKEEPER_MINIO_ACCESS_KEY", "minioadmin")).strip()
        self.minio_secret_key = (minio_secret_key or os.getenv("BEEKEEPER_MINIO_SECRET_KEY", "minioadmin")).strip()
        self.minio_bucket = (minio_bucket or os.getenv("BEEKEEPER_MINIO_BUCKET", "beekeeper-artifacts")).strip()
        self.minio_secure = self._env_bool("BEEKEEPER_MINIO_SECURE", minio_secure, default=False)
        self.api_host = api_host or os.getenv("BEEKEEPER_API_HOST", "0.0.0.0")
        self.api_port = int(api_port or os.getenv("BEEKEEPER_QUEEN_PORT", os.getenv("BEEKEEPER_PORT", "8788")))
        self.supervisor_poll_seconds = float(supervisor_poll_seconds or os.getenv("BEEKEEPER_SUPERVISOR_POLL_SECONDS", "0.25"))
        self.bash_allowlist = bash_allowlist or self._split_csv(
            os.getenv(
                "BEEKEEPER_BASH_ALLOWLIST",
                "pwd,ls,cat,echo,git,rg,find,head,tail,sed,python3,pytest",
            )
        )
        self.enable_network_worker = self._env_bool("BEEKEEPER_ENABLE_NETWORK_WORKER", enable_network_worker, default=False)
        self.allowed_network_hosts = allowed_network_hosts or self._split_csv(
            os.getenv("BEEKEEPER_ALLOWED_NETWORK_HOSTS", "")
        )
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.state_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _split_csv(raw: str) -> list[str]:
        return [item.strip() for item in raw.split(",") if item.strip()]

    @staticmethod
    def _env_bool(name: str, override: bool | None, *, default: bool) -> bool:
        if override is not None:
            return override
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_root": str(self.workspace_root),
            "runtime_root": str(self.runtime_root),
            "state_db_path": str(self.state_db_path),
            "artifact_root": str(self.artifact_root),
            "durable_state_backend": self.durable_state_backend,
            "database_url": self.database_url,
            "artifact_backend": self.artifact_backend,
            "minio_endpoint": self.minio_endpoint,
            "minio_bucket": self.minio_bucket,
            "minio_secure": self.minio_secure,
            "api_host": self.api_host,
            "api_port": self.api_port,
            "supervisor_poll_seconds": self.supervisor_poll_seconds,
            "bash_allowlist": list(self.bash_allowlist),
            "enable_network_worker": self.enable_network_worker,
            "allowed_network_hosts": list(self.allowed_network_hosts),
        }
