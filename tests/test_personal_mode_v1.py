from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from beekeeper.personal_mode import (
    build_personal_status,
    format_personal_status,
    run_personal_setup,
)
from beekeeper.store import BeekeeperStore
from beekeeper.runner import _run_doctor, _run_status
from beekeeper_api.app import app


class _ProviderHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/api/tags":
            body = b'{"models":[{"name":"local-ready"}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return


class ProviderServer:
    def __enter__(self) -> str:
        self.server = HTTPServer(("127.0.0.1", 0), _ProviderHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, *_exc: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()


def test_personal_setup_creates_hidden_defaults_and_is_idempotent(tmp_path: Path) -> None:
    store = BeekeeperStore(tmp_path / "store")
    honeycomb_root = tmp_path / "honeycomb"

    first = run_personal_setup(
        store=store,
        honeycomb_root=honeycomb_root,
        provider="mock",
        model="local-ready",
    )
    second = run_personal_setup(
        store=store,
        honeycomb_root=honeycomb_root,
        provider="mock",
        model="local-ready",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert len(store.list_orgs()) == 1
    assert len(store.list_hives()) == 1
    assert len(store.list_queens()) == 1
    assert (honeycomb_root / "events").is_dir()
    assert (honeycomb_root / "artifacts").is_dir()


def test_personal_status_reports_ready_without_platform_infra(tmp_path: Path) -> None:
    store = BeekeeperStore(tmp_path / "store")
    run_personal_setup(
        store=store,
        honeycomb_root=tmp_path / "honeycomb",
        provider="mock",
        model="local-ready",
    )

    status = build_personal_status(store=store, env={})
    report = format_personal_status(status)

    assert status["overall"] == "ready"
    assert status["required"]["provider"]["status"] == "ready"
    assert status["workers"]["coding_worker"]["status"] == "planned"
    assert "planned/not connected" in report
    assert "Redis" not in report
    assert "Qdrant" not in report
    assert "tenant" not in report.lower()


def test_personal_status_validates_provider_without_printing_secret(tmp_path: Path) -> None:
    store = BeekeeperStore(tmp_path / "store")
    run_personal_setup(
        store=store,
        honeycomb_root=tmp_path / "honeycomb",
        provider="ollama",
        model="minimax-m3:cloud",
        endpoint="not-a-url",
        api_key_env="BEEKEEPER_TEST_API_KEY",
    )

    missing = build_personal_status(store=store, env={})
    invalid = build_personal_status(store=store, env={"BEEKEEPER_TEST_API_KEY": "super-secret"})

    assert missing["overall"] == "blocked"
    assert "BEEKEEPER_TEST_API_KEY" in format_personal_status(missing)
    assert "super-secret" not in json.dumps(missing)
    assert invalid["overall"] == "blocked"
    assert invalid["required"]["provider"]["detail"] == "Provider endpoint is not a valid URL."


def test_personal_status_accepts_valid_ollama_endpoint(tmp_path: Path) -> None:
    store = BeekeeperStore(tmp_path / "store")
    with ProviderServer() as endpoint:
        run_personal_setup(
            store=store,
            honeycomb_root=tmp_path / "honeycomb",
            provider="ollama",
            model="local-ready",
            endpoint=endpoint,
        )

        status = build_personal_status(store=store, env={})

    assert status["overall"] == "ready"
    assert status["required"]["provider"]["status"] == "ready"


def test_personal_doctor_and_status_json_skip_optional_platform_checks(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    run_personal_setup(
        store=BeekeeperStore(tmp_path / "store"),
        honeycomb_root=tmp_path / "honeycomb",
        provider="mock",
        model="local-ready",
    )

    assert _run_doctor(personal=True, json_output=True) == 0
    doctor_payload = json.loads(capsys.readouterr().out)
    assert doctor_payload["overall"] == "ready"
    assert "redis" not in doctor_payload["required"]

    args = type("Args", (), {
        "personal": True,
        "json": True,
        "honeycomb_root": str(tmp_path / "honeycomb"),
        "once": True,
        "interval": 0.1,
    })
    assert _run_status(args) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["workers"]["coding_worker"]["label"] == "planned/not connected"


def test_personal_status_api_matches_cli_payload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    run_personal_setup(
        store=BeekeeperStore(tmp_path / "store"),
        honeycomb_root=tmp_path / "honeycomb",
        provider="mock",
        model="local-ready",
    )

    client = TestClient(app)
    response = client.get("/api/personal/status")

    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "ready"
    assert body["provider"]["name"] == "mock"
    assert body["workers"]["coding_worker"]["label"] == "planned/not connected"

