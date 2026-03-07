from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from beekeeper.contracts import ResultEnvelope, Status
from beekeeper.queen import QueenAgent, QueenConfig
from beekeeper.store import BeekeeperStore
from beekeeper_api.app import app


def _auth_headers(client: TestClient, email: str) -> dict[str, str]:
    resp = client.post("/api/auth/register", json={"email": email, "password": "pass1234"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _prepare_org(store: BeekeeperStore, *, honeycomb_root: str, user_email: str) -> str:
    org = store.create_org("Prod Path Org")
    hive = store.create_hive(org.org_id, "Prod Path Hive")
    store.create_honeycomb(hive.hive_id, "Prod Path Comb", honeycomb_root)
    user = store.get_user_by_email(user_email)
    assert user is not None
    store.assign_org_role(user.user_id, org.org_id, "admin")
    return org.org_id


def _seed_store(tmp_path: Path, monkeypatch) -> BeekeeperStore:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    return BeekeeperStore(tmp_path / "store")


def test_prod_path_golden_temporal_run(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BEEKEEPER_RUNTIME_MODE", "prod")
    store = _seed_store(tmp_path, monkeypatch)
    client = TestClient(app)
    headers = _auth_headers(client, "golden@example.com")
    _prepare_org(store, honeycomb_root=str(tmp_path / "honeycomb"), user_email="golden@example.com")

    monkeypatch.setattr(
        QueenAgent,
        "run",
        lambda self, intent, payload, source=None, status_callback=None, session_id=None, parent_trace_id=None: {
            "trace_id": payload.get("_trace_id", "trace_golden"),
            "request_id": payload.get("_request_id", "req_golden"),
            "results": [{"output": {"assistant_reply": "production path ok"}}],
        },
    )

    resp = client.post(
        "/api/chat/run",
        headers=headers,
        json={
            "intent": "research_topic",
            "payload": {"query": "golden path"},
            "honeycomb_root": str(tmp_path / "honeycomb"),
            "scheduler": "temporal",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["async_execution"] is True
    assert body["state"] == "queued"


def test_prod_path_hitl_queue_and_approve(tmp_path: Path) -> None:
    queen = QueenAgent(
        QueenConfig(
            honeycomb_root=tmp_path / ".honeycomb",
            scheduler_backend="inline",
            auto_approve_human_reviews=False,
        )
    )

    blocked = queen.run(
        intent="research_topic",
        payload={
            "query": "payment migration",
            "action": "payment_action",
            "requires_human_approval": True,
            "use_web_search": True,
        },
    )
    review_id = blocked["results"][0]["output"]["human_review_id"]

    resumed = queen.resume_human_review(review_id, approver="ops", approved=True, note="safe")

    assert resumed["resumed"] is True
    assert resumed["run"]["results"][0]["status"] == "success"


def test_prod_path_slack_channel_allowed_telegram_blocked(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BEEKEEPER_RUNTIME_MODE", "prod")
    store = _seed_store(tmp_path, monkeypatch)
    client = TestClient(app)
    headers = _auth_headers(client, "channel@example.com")
    _prepare_org(store, honeycomb_root=str(tmp_path / "honeycomb"), user_email="channel@example.com")

    monkeypatch.setattr(
        "beekeeper.channels.ChatHub.dispatch",
        lambda self, channel, payload, intent="research_topic", source=None: {
            "channel": channel,
            "response": {"trace_id": "trace_channel", "results": [{"output": {"assistant_reply": "ok"}}]},
        },
    )

    ok = client.post(
        "/api/chat/channel",
        headers=headers,
        json={
            "channel": "slack",
            "intent": "research_topic",
            "payload": {"text": "hello"},
            "honeycomb_root": str(tmp_path / "honeycomb"),
        },
    )
    blocked = client.post(
        "/api/chat/channel",
        headers=headers,
        json={
            "channel": "telegram",
            "intent": "research_topic",
            "payload": {"text": "hello"},
            "honeycomb_root": str(tmp_path / "honeycomb"),
        },
    )

    assert ok.status_code == 200
    assert ok.json()["channel"] == "slack"
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "experimental_channel_not_supported_in_prod"


def test_prod_path_retry_then_success_records_attempts(monkeypatch, tmp_path: Path) -> None:
    queen = QueenAgent(QueenConfig(honeycomb_root=tmp_path / ".honeycomb", scheduler_backend="inline", max_reruns=1))
    calls = {"count": 0}

    def fake_run_task_with_policies(self, task, scheduler_backend, parent_span_id, status_callback=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return (
                ResultEnvelope(
                    task_id=task.task_id,
                    agent_id="worker.web_search",
                    worker_kind=task.worker_kind,
                    status=Status.failed,
                    confidence=0.2,
                    output={"assistant_reply": "failed", "evidence": []},
                ),
                None,
            )
        return (
            ResultEnvelope(
                task_id=task.task_id,
                agent_id="worker.web_search",
                worker_kind=task.worker_kind,
                status=Status.success,
                confidence=0.9,
                output={
                    "assistant_reply": "recovered",
                    "evidence": [{"source": "a"}, {"source": "b"}],
                },
            ),
            None,
        )

    monkeypatch.setattr(QueenAgent, "_run_task_with_policies", fake_run_task_with_policies)

    out = queen.run(intent="research_topic", payload={"query": "retry path", "use_web_search": True})

    assert calls["count"] >= 2
    assert out["results"][0]["status"] == "success"
    events = queen.honeycomb.read_events(out["trace_id"])
    monitor_events = [e for e in events if e.get("kind") == "monitor_decision"]
    assert len(monitor_events) >= 2
    assert monitor_events[0]["action"] == "rerun"
    assert monitor_events[1]["action"] == "accept"
