from __future__ import annotations

import os
from dataclasses import dataclass

from .config.settings import RuntimeMode, resolve_runtime_mode
from .contracts import TaskEnvelope, WorkerKind


@dataclass(frozen=True)
class SandboxProfile:
    name: str
    allow_network: bool
    allow_secret_resolution: bool
    read_only_filesystem: bool
    max_runtime_seconds: int


PROFILE_STANDARD = SandboxProfile(
    name="builtin-standard",
    allow_network=True,
    allow_secret_resolution=True,
    read_only_filesystem=False,
    max_runtime_seconds=120,
)

PROFILE_RESTRICTED = SandboxProfile(
    name="builtin-restricted",
    allow_network=False,
    allow_secret_resolution=False,
    read_only_filesystem=True,
    max_runtime_seconds=60,
)

PROFILE_FORGED = SandboxProfile(
    name="forged-strict",
    allow_network=False,
    allow_secret_resolution=False,
    read_only_filesystem=True,
    max_runtime_seconds=45,
)


def resolve_sandbox_profile(task: TaskEnvelope) -> SandboxProfile:
    if task.worker_kind == WorkerKind.forged or task.task_type.startswith("forged_"):
        return PROFILE_FORGED
    if task.worker_kind in {WorkerKind.bash, WorkerKind.file_system}:
        return PROFILE_RESTRICTED
    return PROFILE_STANDARD


def enforce_sandbox_profile(task: TaskEnvelope) -> SandboxProfile:
    profile = resolve_sandbox_profile(task)
    available = {
        item.strip()
        for item in os.getenv(
            "BEEKEEPER_SANDBOX_AVAILABLE_PROFILES",
            "builtin-standard,builtin-restricted,forged-strict",
        ).split(",")
        if item.strip()
    }
    mode = resolve_runtime_mode()
    if profile.name not in available and mode is not RuntimeMode.DEV:
        raise RuntimeError(f"required_sandbox_profile_unavailable:{profile.name}")
    return profile
