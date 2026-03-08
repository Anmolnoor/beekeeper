from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from ..config.settings import Phase1Settings
from .service import Phase1RuntimeService


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def compose_file() -> Path:
    return project_root() / "docker-compose.yml"


def stack_settings() -> Phase1Settings:
    return Phase1Settings(
        durable_state_backend="postgres",
        database_url="postgresql+psycopg://beekeeper:beekeeper@localhost:5432/beekeeper",
        artifact_backend="minio",
        minio_endpoint="localhost:9000",
        minio_access_key="minioadmin",
        minio_secret_key="minioadmin",
        minio_bucket="beekeeper-artifacts",
        minio_secure=False,
    )


def detect_compose_command() -> list[str]:
    docker = shutil.which("docker")
    if docker is not None:
        return [docker, "compose"]
    docker_compose = shutil.which("docker-compose")
    if docker_compose is not None:
        return [docker_compose]
    raise RuntimeError("docker_compose_not_found")


def run_compose(args: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = detect_compose_command() + ["-f", str(compose_file())] + args
    return subprocess.run(cmd, cwd=str(project_root()), capture_output=capture_output, text=True)


def init_runtime(settings: Phase1Settings | None = None) -> dict[str, object]:
    runtime = Phase1RuntimeService(settings or Phase1Settings())
    return {
        "ok": True,
        "database_backend": runtime.settings.durable_state_backend,
        "artifact_backend": runtime.settings.artifact_backend,
        "database_url": runtime.settings.database_url,
        "minio_bucket": runtime.settings.minio_bucket,
    }


def stack_up(*, build: bool, detach: bool = True, wait_seconds: float = 2.0) -> dict[str, object]:
    args = ["up"]
    if build:
        args.append("--build")
    if detach:
        args.append("-d")
    result = run_compose(args, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "compose_up_failed")
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    init_payload = wait_for_stack_initialization()
    return {
        "ok": True,
        "action": "up",
        "stdout": result.stdout.strip(),
        "init": init_payload,
    }


def stack_down(*, volumes: bool = False) -> dict[str, object]:
    args = ["down"]
    if volumes:
        args.append("-v")
    result = run_compose(args, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "compose_down_failed")
    return {"ok": True, "action": "down", "stdout": result.stdout.strip()}


def stack_ps() -> dict[str, object]:
    result = run_compose(["ps"], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "compose_ps_failed")
    return {"ok": True, "action": "ps", "output": result.stdout.strip()}


def stack_logs(*, service: str | None = None, follow: bool = False, tail: int = 200) -> dict[str, object]:
    args = ["logs", f"--tail={tail}"]
    if follow:
        args.append("-f")
    if service:
        args.append(service)
    result = run_compose(args, capture_output=not follow)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "compose_logs_failed")
    return {"ok": True, "action": "logs", "output": (result.stdout or "").strip()}


def stack_restart(*, service: str | None = None) -> dict[str, object]:
    args = ["restart"]
    if service:
        args.append(service)
    result = run_compose(args, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "compose_restart_failed")
    return {"ok": True, "action": "restart", "stdout": result.stdout.strip()}


def wait_for_stack_initialization(*, attempts: int = 20, delay_seconds: float = 1.0) -> dict[str, object]:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return init_runtime(stack_settings())
        except Exception as exc:  # pragma: no cover - timing dependent
            last_error = exc
            time.sleep(delay_seconds)
    if last_error is None:
        raise RuntimeError("stack_initialization_failed")
    raise last_error


def service_urls(settings: Phase1Settings | None = None) -> dict[str, str]:
    cfg = settings or stack_settings()
    scheme = "https" if cfg.minio_secure else "http"
    return {
        "queen_api": f"http://localhost:{cfg.api_port}",
        "health": f"http://localhost:{cfg.api_port}/health",
        "minio_api": f"{scheme}://{cfg.minio_endpoint}",
        "minio_console": "http://localhost:9001",
        "postgres": "postgresql://beekeeper:beekeeper@localhost:5432/beekeeper",
    }
