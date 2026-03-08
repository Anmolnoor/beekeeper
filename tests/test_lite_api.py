from __future__ import annotations

from fastapi.testclient import TestClient

import queen_api.app as queen_app


def test_health_reports_phase1_mode():
    client = TestClient(queen_app.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["mode"] == "phase1"
