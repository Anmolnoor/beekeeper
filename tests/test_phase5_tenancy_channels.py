from __future__ import annotations

from fastapi.testclient import TestClient

from beekeeper.queen import QueenAgent
from beekeeper.store import BeekeeperStore
from beekeeper_api.app import app


def _auth_headers(client: TestClient, email: str = "phase5@example.com") -> dict[str, str]:
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "pass1234"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _prepare_tenant(store: BeekeeperStore, honeycomb_root: str, user_email: str) -> str:
    org = store.create_org("Phase5 Org")
    hive = store.create_hive(org.org_id, "Phase5 Hive")
    store.create_honeycomb(hive.hive_id, "Phase5 Comb", honeycomb_root)
    user = store.get_user_by_email(user_email)
    assert user is not None
    store.assign_org_role(user.user_id, org.org_id, "admin")
    return org.org_id


def test_phase5_tenant_daily_run_quota_blocks(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    client = TestClient(app)
    headers = _auth_headers(client, email="quota@example.com")
    store = BeekeeperStore(tmp_path / "store")
    org_id = _prepare_tenant(store, str(tmp_path / "honeycomb"), "quota@example.com")
    store.write_setting("tenant_quotas", {org_id: {"daily_runs": 1, "concurrent_runs": 5}})

    monkeypatch.setattr(
        QueenAgent,
        "run",
        lambda self, intent, payload, source=None, status_callback=None: {"trace_id": "trace_q", "results": [{"output": {"assistant_reply": "ok"}}]},
    )

    body = {"intent": "research_topic", "payload": {"query": "one"}, "honeycomb_root": str(tmp_path / "honeycomb"), "scheduler": "auto"}
    first = client.post("/api/chat/run", headers=headers, json=body)
    assert first.status_code == 200
    second = client.post("/api/chat/run", headers=headers, json=body)
    assert second.status_code == 429
    assert second.json()["detail"]["error"] == "daily_run_quota_exceeded"


def test_phase5_tenant_api_rate_limit_blocks(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    client = TestClient(app)
    headers = _auth_headers(client, email="ratelimit@example.com")
    store = BeekeeperStore(tmp_path / "store")
    org_id = _prepare_tenant(store, str(tmp_path / "honeycomb"), "ratelimit@example.com")
    store.write_setting("tenant_rate_limits", {org_id: {"api_submission_per_minute": 1}})
    store.write_setting("tenant_quotas", {org_id: {"daily_runs": 10, "concurrent_runs": 5}})

    monkeypatch.setattr(
        QueenAgent,
        "run",
        lambda self, intent, payload, source=None, status_callback=None: {"trace_id": "trace_r", "results": [{"output": {"assistant_reply": "ok"}}]},
    )

    body = {"intent": "research_topic", "payload": {"query": "one"}, "honeycomb_root": str(tmp_path / "honeycomb"), "scheduler": "auto"}
    first = client.post("/api/chat/run", headers=headers, json=body)
    assert first.status_code == 200
    second = client.post("/api/chat/run", headers=headers, json=body)
    assert second.status_code == 429
    assert second.json()["detail"]["error"] == "tenant_rate_limit_exceeded"


def test_phase5_support_matrix_and_prod_guardrails(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    monkeypatch.setenv("BEEKEEPER_RUNTIME_MODE", "prod")

    client = TestClient(app)
    headers = _auth_headers(client, email="prodmode@example.com")

    matrix = client.get("/api/support/matrix", headers=headers)
    assert matrix.status_code == 200
    assert matrix.json()["channels"]["slack"]["support_level"] == "supported"
    assert matrix.json()["channels"]["telegram"]["support_level"] == "experimental"

    run_inline = client.post(
        "/api/chat/run",
        headers=headers,
        json={"intent": "research_topic", "payload": {"query": "x"}, "honeycomb_root": str(tmp_path / "honeycomb"), "scheduler": "inline"},
    )
    assert run_inline.status_code == 400
    assert run_inline.json()["detail"] == "prod_requires_temporal_scheduler"

    channel_non_slack = client.post(
        "/api/chat/channel",
        headers=headers,
        json={"channel": "telegram", "intent": "research_topic", "payload": {"text": "x"}, "honeycomb_root": str(tmp_path / "honeycomb")},
    )
    assert channel_non_slack.status_code == 400
    assert channel_non_slack.json()["detail"] == "experimental_channel_not_supported_in_prod"


def test_temporal_scheduler_uses_async_admission_response(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    client = TestClient(app)
    headers = _auth_headers(client, email="temporal@example.com")
    store = BeekeeperStore(tmp_path / "store")
    _prepare_tenant(store, str(tmp_path / "honeycomb"), "temporal@example.com")

    monkeypatch.setattr(
        QueenAgent,
        "run",
        lambda self, intent, payload, source=None, status_callback=None, session_id=None, parent_trace_id=None: {
            "trace_id": payload.get("_trace_id", "trace_temporal"),
            "request_id": payload.get("_request_id", "req_temporal"),
            "results": [{"output": {"assistant_reply": "ok"}}],
        },
    )

    response = client.post(
        "/api/chat/run",
        headers=headers,
        json={
            "intent": "research_topic",
            "payload": {"query": "queued"},
            "honeycomb_root": str(tmp_path / "honeycomb"),
            "scheduler": "temporal",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["async_execution"] is True
    assert body["state"] == "queued"
