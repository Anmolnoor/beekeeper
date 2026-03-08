from __future__ import annotations

from pathlib import Path

import beekeeper.runtime.service as runtime_service
from beekeeper.config.settings import Phase1Settings


class StubRepository:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.initialized = False

    def initialize(self) -> None:
        self.initialized = True

    def list_approvals(self, **kwargs):
        return []


class StubArtifactStore:
    def __init__(self, repository, *args, **kwargs) -> None:
        self.repository = repository
        self.args = args
        self.kwargs = kwargs
        self.initialized = False

    def initialize(self) -> None:
        self.initialized = True


def test_runtime_selects_postgres_and_minio_backends(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runtime_service, "SqlAlchemyRuntimeStateRepository", StubRepository)
    monkeypatch.setattr(runtime_service, "MinioArtifactStore", StubArtifactStore)

    settings = Phase1Settings(
        workspace_root=tmp_path,
        runtime_root=tmp_path / ".phase1",
        durable_state_backend="postgres",
        database_url="postgresql+psycopg://beekeeper:beekeeper@localhost:5432/beekeeper",
        artifact_backend="minio",
    )
    runtime = runtime_service.Phase1RuntimeService(settings)

    assert isinstance(runtime.repository, StubRepository)
    assert isinstance(runtime.artifact_store, StubArtifactStore)
    assert runtime.repository.initialized is True
    assert runtime.artifact_store.initialized is True


def test_sqlalchemy_repository_path_runs_with_sqlite_url(tmp_path: Path) -> None:
    settings = Phase1Settings(
        workspace_root=tmp_path,
        runtime_root=tmp_path / ".phase1",
        durable_state_backend="postgres",
        database_url=f"sqlite:///{tmp_path / 'phase1-prod.db'}",
        artifact_backend="local",
        artifact_root=tmp_path / ".phase1" / "artifacts",
    )

    runtime = runtime_service.Phase1RuntimeService(settings)
    run = runtime.submit_run(
        {
            "goal": "Exercise SQLAlchemy repository",
            "workspace_path": str(tmp_path),
            "worker_kind": "bash",
            "payload": {"command": "pwd"},
        }
    )

    assert run["status"] == "completed"
    assert runtime.get_trace(run["run_id"])[-1]["event_type"] == "job_finished"
