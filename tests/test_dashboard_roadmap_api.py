from __future__ import annotations

from fastapi.testclient import TestClient

from beekeeper_api.app import app


def _auth_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/auth/register",
        json={"email": "roadmap@example.com", "password": "pass1234"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_settings_catalog_and_templates(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    client = TestClient(app)
    headers = _auth_headers(client)

    cat = client.get("/api/settings/catalog", headers=headers)
    assert cat.status_code == 200
    catalog = cat.json()["catalog"]
    assert any(section["category"] == "model_runtime" for section in catalog)

    templates = client.get("/api/settings/templates", headers=headers)
    assert templates.status_code == 200
    template_ids = {row["template_id"] for row in templates.json()["templates"]}
    assert "solo-fast" in template_ids


def test_settings_validate_and_permissions_simulation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    client = TestClient(app)
    headers = _auth_headers(client)

    validate = client.post(
        "/api/settings/validate",
        headers=headers,
        json={
            "config": {
                "llm_provider": "openai",
                "openai_api_key": "",
                "whatsapp_access_token": "abc",
                "whatsapp_phone_number_id": "",
            }
        },
    )
    assert validate.status_code == 200
    body = validate.json()
    assert body["ok"] is True
    assert any("openai_api_key is empty" in warning for warning in body["warnings"])

    simulation = client.post(
        "/api/settings/permissions/simulate",
        headers=headers,
        json={
            "rules": [
                {"action": "allow", "tools": ["read"], "pattern": "**/*.md"},
                {"action": "deny", "tools": ["read"], "pattern": "**/.env*"},
            ],
            "tool": "read",
            "sample_targets": ["README.md", ".env"],
        },
    )
    assert simulation.status_code == 200
    results = simulation.json()["results"]
    decisions = {row["target"]: row["decision"] for row in results}
    assert decisions["README.md"] == "allow"
    assert decisions[".env"] == "deny"


def test_governance_and_kpi_endpoints(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    client = TestClient(app)
    headers = _auth_headers(client)

    evt = client.post("/api/analytics/events", headers=headers, json={"event": "dashboard_loaded", "metadata": {"screen": "main"}})
    assert evt.status_code == 200
    summary = client.get("/api/analytics/events/summary?days=30", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["events_total"] >= 1

    staffing = client.post(
        "/api/roadmap/staffing",
        headers=headers,
        json={"staffing": {"product_manager": "alex", "backend_engineer": "sam"}},
    )
    assert staffing.status_code == 200
    staffing_get = client.get("/api/roadmap/staffing", headers=headers)
    assert staffing_get.status_code == 200
    assert staffing_get.json()["staffing"]["product_manager"] == "alex"

    usability = client.post(
        "/api/roadmap/usability",
        headers=headers,
        json={"sprint": "Sprint 1", "participant_count": 6, "task_success_rate": 0.83, "notes": "good"},
    )
    assert usability.status_code == 200
    sessions = client.get("/api/roadmap/usability", headers=headers)
    assert sessions.status_code == 200
    assert len(sessions.json()["sessions"]) == 1
