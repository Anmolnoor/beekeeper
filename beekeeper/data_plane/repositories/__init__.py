from __future__ import annotations

import os
from pathlib import Path

from ...config.settings import RuntimeMode, resolve_runtime_mode
from .base import DurableStateRepositoryProtocol, resolve_runtime_database_backend, resolve_sqlite_db_path
from .postgres_durable_state import PostgresDurableStateRepository
from .sqlite_durable_state import DurableStateRepository, SqliteDurableStateRepository


def build_durable_state_repository(
    *,
    default_sqlite_path: Path,
    backend: str | None = None,
    dsn: str | None = None,
    sqlite_path: Path | None = None,
) -> DurableStateRepositoryProtocol:
    selected_backend = resolve_runtime_database_backend(
        explicit_backend=backend or os.getenv("BEEKEEPER_DATABASE_BACKEND"),
        dsn=dsn or os.getenv("BEEKEEPER_DATABASE_DSN"),
    )
    if selected_backend == "postgres":
        try:
            return PostgresDurableStateRepository(dsn or os.getenv("BEEKEEPER_DATABASE_DSN", ""))
        except RuntimeError:
            if resolve_runtime_mode() is not RuntimeMode.DEV:
                raise
    return SqliteDurableStateRepository(resolve_sqlite_db_path(explicit_path=sqlite_path, default_path=default_sqlite_path))


__all__ = [
    "DurableStateRepository",
    "DurableStateRepositoryProtocol",
    "SqliteDurableStateRepository",
    "PostgresDurableStateRepository",
    "build_durable_state_repository",
]
