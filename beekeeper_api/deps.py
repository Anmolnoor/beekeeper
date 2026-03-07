from __future__ import annotations

import os
from pathlib import Path

from beekeeper.honeycomb import HoneycombConfig, HoneycombStore
from beekeeper.store import BeekeeperStore
from beekeeper.worker_registry import WorkerRegistry


def _resolve_root(preferred_env_var: str, fallback: str) -> Path:
    raw = os.getenv(preferred_env_var, fallback)
    root = Path(raw)
    if not root.is_absolute():
        root = Path.cwd() / root
    return root.resolve()


def get_store() -> BeekeeperStore:
    root = _resolve_root("BEEKEEPER_STORE_ROOT", ".beekeeper_store")
    return BeekeeperStore(root=root)


def get_honeycomb(honeycomb_root: str = ".honeycomb") -> HoneycombStore:
    root = _resolve_root("BEEKEEPER_HONEYCOMB_ROOT", honeycomb_root)
    return HoneycombStore(
        HoneycombConfig(
            root_dir=root,
            durable_state_backend=os.getenv("BEEKEEPER_DATABASE_BACKEND") or None,
            durable_state_dsn=os.getenv("BEEKEEPER_DATABASE_DSN") or None,
            artifact_backend=os.getenv("BEEKEEPER_ARTIFACT_BACKEND", "local"),
            artifact_bucket=os.getenv("BEEKEEPER_OBJECT_STORAGE_BUCKET") or None,
            artifact_endpoint=os.getenv("BEEKEEPER_OBJECT_STORAGE_ENDPOINT") or None,
        )
    )


def get_worker_registry(honeycomb_root: str = ".honeycomb") -> WorkerRegistry:
    root = _resolve_root("BEEKEEPER_HONEYCOMB_ROOT", honeycomb_root)
    return WorkerRegistry(root)
