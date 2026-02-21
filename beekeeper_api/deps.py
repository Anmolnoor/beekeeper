from __future__ import annotations

import os
from pathlib import Path

from beehive.honeycomb import HoneycombConfig, HoneycombStore
from beehive.store import BeekeeperStore
from beehive.worker_registry import WorkerRegistry


def get_store() -> BeekeeperStore:
    root = Path(os.getenv("BEEKEEPER_STORE_ROOT", ".beekeeper_store"))
    return BeekeeperStore(root=root)


def get_honeycomb(honeycomb_root: str = ".honeycomb") -> HoneycombStore:
    root = Path(honeycomb_root)
    if not root.is_absolute():
        root = Path.cwd() / root
    return HoneycombStore(HoneycombConfig(root_dir=root))


def get_worker_registry(honeycomb_root: str = ".honeycomb") -> WorkerRegistry:
    root = Path(honeycomb_root)
    if not root.is_absolute():
        root = Path.cwd() / root
    return WorkerRegistry(root)
