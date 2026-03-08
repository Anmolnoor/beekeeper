from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from beekeeper.config.settings import Phase1Settings
from beekeeper.lite_agent import LiteAssistant, LiteAssistantConfig
from beekeeper.runtime import Phase1RuntimeService
import queen_api.app as queen_app


def _runtime(tmp_path: Path) -> Phase1RuntimeService:
    settings = Phase1Settings(
        workspace_root=tmp_path,
        runtime_root=tmp_path / ".phase1",
        state_db_path=tmp_path / ".phase1" / "state.db",
        artifact_root=tmp_path / ".phase1" / "artifacts",
    )
    return Phase1RuntimeService(settings)


class FakeRouter:
    def call(self, prompt, system=None, messages=None, model_override=None):
        return f"echo:{prompt}", "fake"


def test_phase1_api_create_run_and_fetch_trace(monkeypatch, tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(queen_app, "_runtime", runtime)
    client = TestClient(queen_app.app)

    response = client.post(
        "/v1/runs",
        json={
            "goal": "Write a note",
            "workspace_path": str(tmp_path),
            "worker_kind": "filesystem",
            "job_type": "write",
            "payload": {"operation": "write", "path": "note.txt", "content": "phase1"},
        },
    )

    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "completed"
    trace = client.get(f"/v1/runs/{run['run_id']}/trace")
    artifacts = client.get(f"/v1/runs/{run['run_id']}/artifacts")
    assert trace.status_code == 200
    assert artifacts.status_code == 200
    assert any(event["event_type"] == "job_finished" for event in trace.json()["events"])
    assert artifacts.json()["artifacts"][0]["object_key"].endswith("write.txt")


def test_phase1_api_approval_endpoints(monkeypatch, tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(queen_app, "_runtime", runtime)
    client = TestClient(queen_app.app)

    response = client.post(
        "/v1/runs",
        json={
            "goal": "Create a guarded file",
            "workspace_path": str(tmp_path),
            "worker_kind": "bash",
            "payload": {"command": "touch approved-via-api.txt"},
        },
    )

    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "awaiting_approval"
    approval_id = run["pending_approvals"][0]["approval_id"]

    approval = client.post(
        f"/v1/approvals/{approval_id}/approve",
        json={"resolved_by": "api-tester"},
    )

    assert approval.status_code == 200
    runtime.drain(run_id=run["run_id"])
    resumed = client.get(f"/v1/runs/{run['run_id']}")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"


def test_phase1_chat_compat_endpoints(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        queen_app,
        "_assistant",
        LiteAssistant(
            config=LiteAssistantConfig(store_root=tmp_path / "store"),
            router=FakeRouter(),
        ),
    )
    client = TestClient(queen_app.app)

    models = client.get("/v1/models")
    assert models.status_code == 200
    assert models.json()["data"][0]["id"] == "beekeeper-lite"

    response = client.post(
        "/v1/chat/completions",
        headers={"X-Beekeeper-User-Id": "api-tester"},
        json={
            "model": "beekeeper-lite",
            "stream": False,
            "messages": [{"role": "user", "content": "Hello there"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "echo:Hello there"
    assert body["provider"] == "fake"
    assert body["chat_id"]

    chats = client.get("/v1/chats", params={"user_id": "api-tester"})
    assert chats.status_code == 200
    assert chats.json()["chats"][0]["chat_id"] == body["chat_id"]

    chat = client.get(f"/v1/chats/{body['chat_id']}")
    assert chat.status_code == 200
    assert [message["role"] for message in chat.json()["messages"]] == ["user", "assistant"]
