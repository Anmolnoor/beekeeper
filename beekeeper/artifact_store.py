from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .contracts import ArtifactRef


def _kind_to_content_type(kind: str) -> str:
    return {
        "json": "application/json",
        "text": "text/plain",
        "report": "text/plain",
        "log": "text/plain",
        "binary": "application/octet-stream",
    }.get(kind, "application/octet-stream")


class ArtifactStore(Protocol):
    def write_text(
        self,
        *,
        trace_id: str,
        task_id: str,
        content: str,
        kind: str,
        tenant_scope: str | None = None,
    ) -> ArtifactRef:
        ...


@dataclass(frozen=True)
class ArtifactStorageConfig:
    backend: str = "local"  # local | s3
    local_root: Path | None = None
    bucket: str | None = None
    endpoint: str | None = None
    prefix: str = "artifacts"
    s3_dev_mirror_root: Path | None = None


class LocalArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def write_text(self, *, trace_id: str, task_id: str, content: str, kind: str, tenant_scope: str | None = None) -> ArtifactRef:
        artifact_id = str(uuid4())
        suffix = ".json" if kind == "json" else ".txt"
        tenant_segment = (tenant_scope or "__default__").replace("/", "_")
        object_key = f"{tenant_segment}/{trace_id}/{artifact_id}{suffix}"
        path = self.root / object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return ArtifactRef(
            artifact_id=artifact_id,
            task_id=task_id,
            kind=kind,
            location=str(path),
            storage_backend="local",
            object_key=object_key,
            content_type=_kind_to_content_type(kind),
            tenant_scope=tenant_scope,
            checksum=checksum,
        )


class S3CompatibleArtifactStore:
    """S3-shaped adapter that can mirror writes locally in development."""

    def __init__(self, *, bucket: str, prefix: str = "artifacts", endpoint: str | None = None, dev_mirror_root: Path | None = None) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/") or "artifacts"
        self.endpoint = endpoint
        self.dev_mirror_root = dev_mirror_root
        if self.dev_mirror_root is not None:
            self.dev_mirror_root.mkdir(parents=True, exist_ok=True)

    def write_text(self, *, trace_id: str, task_id: str, content: str, kind: str, tenant_scope: str | None = None) -> ArtifactRef:
        artifact_id = str(uuid4())
        suffix = ".json" if kind == "json" else ".txt"
        tenant_segment = (tenant_scope or "__default__").replace("/", "_")
        object_key = f"{self.prefix}/{tenant_segment}/{trace_id}/{artifact_id}{suffix}"
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if self.dev_mirror_root is not None:
            mirror = self.dev_mirror_root / object_key
            mirror.parent.mkdir(parents=True, exist_ok=True)
            mirror.write_text(content, encoding="utf-8")
        location = f"s3://{self.bucket}/{object_key}"
        return ArtifactRef(
            artifact_id=artifact_id,
            task_id=task_id,
            kind=kind,
            location=location,
            storage_backend="s3",
            storage_bucket=self.bucket,
            object_key=object_key,
            content_type=_kind_to_content_type(kind),
            tenant_scope=tenant_scope,
            checksum=checksum,
        )


def build_artifact_store(*, default_root: Path, config: ArtifactStorageConfig | None = None) -> ArtifactStore:
    cfg = config or ArtifactStorageConfig()
    backend = (cfg.backend or os.getenv("BEEKEEPER_ARTIFACT_BACKEND", "local")).strip().lower()
    if backend == "s3":
        bucket = cfg.bucket or os.getenv("BEEKEEPER_OBJECT_STORAGE_BUCKET") or "beekeeper"
        mirror_root = cfg.s3_dev_mirror_root
        if mirror_root is None:
            raw = os.getenv("BEEKEEPER_OBJECT_STORAGE_DEV_ROOT", "")
            mirror_root = Path(raw).resolve() if raw else None
        return S3CompatibleArtifactStore(
            bucket=bucket,
            prefix=cfg.prefix,
            endpoint=cfg.endpoint or os.getenv("BEEKEEPER_OBJECT_STORAGE_ENDPOINT"),
            dev_mirror_root=mirror_root,
        )
    local_root = cfg.local_root or default_root
    return LocalArtifactStore(local_root)
