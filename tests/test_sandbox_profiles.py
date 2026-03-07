from __future__ import annotations

import pytest

from beekeeper.contracts import TaskEnvelope, WorkerKind
from beekeeper.sandbox_profiles import enforce_sandbox_profile


def _task(worker_kind: WorkerKind, *, task_type: str = "research_topic") -> TaskEnvelope:
    return TaskEnvelope(
        queen_trace_id="trace-sandbox",
        queen_request_id="req-sandbox",
        task_type=task_type,
        worker_kind=worker_kind,
        payload={"query": "hello"},
        idempotency_key=f"idem-{worker_kind.value}",
    )


def test_forged_workloads_require_strict_profile(monkeypatch) -> None:
    monkeypatch.setenv("BEEKEEPER_SANDBOX_AVAILABLE_PROFILES", "builtin-standard,builtin-restricted,forged-strict")
    profile = enforce_sandbox_profile(_task(WorkerKind.forged, task_type="forged_worker"))
    assert profile.name == "forged-strict"


def test_missing_profile_fails_closed_outside_dev(monkeypatch) -> None:
    monkeypatch.setenv("BEEKEEPER_RUNTIME_MODE", "prod")
    monkeypatch.setenv("BEEKEEPER_SANDBOX_AVAILABLE_PROFILES", "builtin-standard")
    with pytest.raises(RuntimeError):
        enforce_sandbox_profile(_task(WorkerKind.bash))
