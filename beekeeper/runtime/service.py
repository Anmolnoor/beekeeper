from __future__ import annotations

import subprocess
import sys
from typing import Any

from ..artifacts import FilesystemArtifactStore, MinioArtifactStore
from ..config.settings import Phase1Settings
from ..data_plane.repositories.runtime_state import RuntimeStateRepository
from ..data_plane.repositories.sqlalchemy_runtime_state import SqlAlchemyRuntimeStateRepository
from ..trace import TraceEventStore
from ..workers.bash_worker import BashWorker
from ..workers.filesystem_worker import FilesystemWorker
from ..workers.github_worker import GitHubWorker
from ..workers.network_worker import NetworkWorker
from .approval_service import ApprovalService
from .coordinator import RuntimeCoordinator
from .supervisor import Supervisor

_RUNTIME_SINGLETON: "Phase1RuntimeService | None" = None


class Phase1RuntimeService:
    def __init__(self, settings: Phase1Settings | None = None) -> None:
        self.settings = settings or Phase1Settings()
        self.repository = self._build_repository()
        self.trace_store = TraceEventStore(self.repository)
        self.artifact_store = self._build_artifact_store()
        self._initialize_backends()
        self.approval_service = ApprovalService(self.repository, self.trace_store)
        self.coordinator = RuntimeCoordinator(self.repository, self.trace_store, self.settings)
        self.supervisor = Supervisor(
            self.repository,
            self.trace_store,
            self.artifact_store,
            self.approval_service,
            workers={
                "bash": BashWorker(),
                "filesystem": FilesystemWorker(),
                "github": GitHubWorker(),
                "network": NetworkWorker(),
            },
            settings=self.settings,
        )

    def _build_repository(self):
        if self.settings.durable_state_backend == "postgres" or self.settings.database_url.startswith(("postgresql://", "postgresql+", "postgres://")):
            return SqlAlchemyRuntimeStateRepository(self.settings.database_url)
        return RuntimeStateRepository(self.settings.state_db_path)

    def _build_artifact_store(self):
        if self.settings.artifact_backend == "minio":
            return MinioArtifactStore(self.repository, self.settings)
        return FilesystemArtifactStore(self.repository, self.settings.artifact_root, bucket=self.settings.minio_bucket)

    def _initialize_backends(self) -> None:
        initialize = getattr(self.repository, "initialize", None)
        if callable(initialize):
            initialize()
        artifact_initialize = getattr(self.artifact_store, "initialize", None)
        if callable(artifact_initialize):
            artifact_initialize()

    def submit_run(self, request: dict[str, Any], *, background: bool = False) -> dict[str, Any]:
        run = self.coordinator.create_run(request)
        if background:
            self._spawn_supervisor(run["run_id"])
            return self.get_run(run["run_id"]) or run
        self.supervisor.run_until_idle(run_id=run["run_id"])
        return self.get_run(run["run_id"]) or run

    def _spawn_supervisor(self, run_id: str) -> None:
        subprocess.Popen(
            [sys.executable, "-m", "beekeeper.runtime.supervisor_entry", "--run-id", run_id],
            cwd=str(self.settings.workspace_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def drain(self, *, run_id: str | None = None) -> bool:
        return self.supervisor.run_until_idle(run_id=run_id)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.repository.get_run(run_id)

    def get_trace(self, run_id: str) -> list[dict[str, Any]]:
        return self.trace_store.replay(run_id)

    def get_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        return self.artifact_store.list_artifacts(run_id)

    def resolve_approval(self, approval_id: str, *, approved: bool, resolved_by: str) -> dict[str, Any]:
        approval = self.approval_service.resolve(approval_id, approved=approved, resolved_by=resolved_by)
        if approved:
            self._spawn_supervisor(str(approval["run_id"]))
        return approval


def get_runtime_service(settings: Phase1Settings | None = None) -> Phase1RuntimeService:
    global _RUNTIME_SINGLETON
    if settings is not None:
        return Phase1RuntimeService(settings)
    if _RUNTIME_SINGLETON is None:
        _RUNTIME_SINGLETON = Phase1RuntimeService()
    return _RUNTIME_SINGLETON
