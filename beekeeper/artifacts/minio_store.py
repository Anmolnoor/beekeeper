from __future__ import annotations

import hashlib
from pathlib import Path

try:
    from minio import Minio
except Exception:  # pragma: no cover - optional dependency path
    Minio = None

from ..config.settings import Phase1Settings
from ..data_plane.models import ArtifactRecord, new_id


class FilesystemArtifactStore:
    def __init__(self, repository, root_dir: Path, bucket: str = "beekeeper-artifacts") -> None:
        self.repository = repository
        self.root_dir = root_dir
        self.bucket = bucket
        (self.root_dir / bucket).mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        (self.root_dir / self.bucket).mkdir(parents=True, exist_ok=True)

    def put_bytes(
        self,
        *,
        run_id: str,
        job_id: str | None,
        attempt_id: str | None,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> dict[str, str]:
        target = self.root_dir / self.bucket / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        sha256 = hashlib.sha256(content).hexdigest()
        record = ArtifactRecord(
            artifact_id=new_id("art"),
            run_id=run_id,
            job_id=job_id,
            attempt_id=attempt_id,
            bucket=self.bucket,
            object_key=object_key,
            content_type=content_type,
            size_bytes=len(content),
            sha256=sha256,
        )
        self.repository.create_artifact(record)
        return {
            "artifact_id": record.artifact_id,
            "bucket": self.bucket,
            "object_key": object_key,
            "path": str(target),
            "sha256": sha256,
        }

    def put_text(
        self,
        *,
        run_id: str,
        job_id: str | None,
        attempt_id: str | None,
        object_key: str,
        content: str,
        content_type: str = "text/plain; charset=utf-8",
    ) -> dict[str, str]:
        return self.put_bytes(
            run_id=run_id,
            job_id=job_id,
            attempt_id=attempt_id,
            object_key=object_key,
            content=content.encode("utf-8"),
            content_type=content_type,
        )

    def list_artifacts(self, run_id: str) -> list[dict[str, str]]:
        artifacts = self.repository.list_artifacts(run_id)
        for artifact in artifacts:
            artifact["path"] = str(self.root_dir / artifact["bucket"] / artifact["object_key"])
            artifact["uri"] = f"file://{artifact['path']}"
        return artifacts


class MinioArtifactStore:
    def __init__(self, repository, settings: Phase1Settings) -> None:
        if Minio is None:
            raise RuntimeError("minio_not_installed")
        self.repository = repository
        self.settings = settings
        self.bucket = settings.minio_bucket
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    def initialize(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def put_bytes(
        self,
        *,
        run_id: str,
        job_id: str | None,
        attempt_id: str | None,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> dict[str, str]:
        from io import BytesIO

        self.client.put_object(
            self.bucket,
            object_key,
            data=BytesIO(content),
            length=len(content),
            content_type=content_type,
        )
        sha256 = hashlib.sha256(content).hexdigest()
        record = ArtifactRecord(
            artifact_id=new_id("art"),
            run_id=run_id,
            job_id=job_id,
            attempt_id=attempt_id,
            bucket=self.bucket,
            object_key=object_key,
            content_type=content_type,
            size_bytes=len(content),
            sha256=sha256,
        )
        self.repository.create_artifact(record)
        scheme = "https" if self.settings.minio_secure else "http"
        return {
            "artifact_id": record.artifact_id,
            "bucket": self.bucket,
            "object_key": object_key,
            "uri": f"{scheme}://{self.settings.minio_endpoint}/{self.bucket}/{object_key}",
            "sha256": sha256,
        }

    def put_text(
        self,
        *,
        run_id: str,
        job_id: str | None,
        attempt_id: str | None,
        object_key: str,
        content: str,
        content_type: str = "text/plain; charset=utf-8",
    ) -> dict[str, str]:
        return self.put_bytes(
            run_id=run_id,
            job_id=job_id,
            attempt_id=attempt_id,
            object_key=object_key,
            content=content.encode("utf-8"),
            content_type=content_type,
        )

    def list_artifacts(self, run_id: str) -> list[dict[str, str]]:
        artifacts = self.repository.list_artifacts(run_id)
        scheme = "https" if self.settings.minio_secure else "http"
        for artifact in artifacts:
            artifact["uri"] = f"{scheme}://{self.settings.minio_endpoint}/{artifact['bucket']}/{artifact['object_key']}"
        return artifacts
