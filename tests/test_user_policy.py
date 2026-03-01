"""Tests for user_policy.py unit functions and related API endpoints."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from beekeeper.user_policy import (
    UserPolicy,
    load_user_policy,
    merge_policy_into_autonomy,
    policy_allows_action,
    save_user_policy,
)
from beekeeper_api.app import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth_headers(client: TestClient, email: str = "policy@example.com") -> dict[str, str]:
    resp = client.post("/api/auth/register", json={"email": email, "password": "pass1234"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Unit tests: UserPolicy model
# ---------------------------------------------------------------------------

def test_default_policy() -> None:
    policy = UserPolicy()
    assert "web_search" in policy.always_allow
    assert "summarize" in policy.always_allow
    assert "write_file" in policy.always_ask
    assert "delete_file" in policy.always_ask
    assert policy.always_deny == []
    assert policy.max_auto_cost_usd == 0.50


# ---------------------------------------------------------------------------
# Unit tests: save and load
# ---------------------------------------------------------------------------

def test_save_and_load_policy(tmp_path: Path) -> None:
    policy = UserPolicy(
        always_allow=["web_search", "compute"],
        always_ask=["write_file"],
        always_deny=["send_email"],
        max_auto_cost_usd=1.00,
    )
    save_user_policy(tmp_path, "user_abc", policy)

    loaded = load_user_policy(tmp_path, "user_abc")
    assert loaded.always_allow == ["web_search", "compute"]
    assert loaded.always_ask == ["write_file"]
    assert loaded.always_deny == ["send_email"]
    assert loaded.max_auto_cost_usd == 1.00
    assert loaded.updated_at is not None


def test_load_policy_returns_default_when_missing(tmp_path: Path) -> None:
    loaded = load_user_policy(tmp_path, "nonexistent_user")
    assert isinstance(loaded, UserPolicy)
    assert "web_search" in loaded.always_allow


def test_load_policy_returns_default_on_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "users" / "bad_user" / "policy.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json}", encoding="utf-8")
    loaded = load_user_policy(tmp_path, "bad_user")
    assert isinstance(loaded, UserPolicy)


# ---------------------------------------------------------------------------
# Unit tests: policy_allows_action
# ---------------------------------------------------------------------------

def test_policy_allows_action_allow() -> None:
    policy = UserPolicy(always_allow=["web_search"], always_ask=[], always_deny=[])
    allowed, disposition = policy_allows_action(policy, "web_search")
    assert allowed is True
    assert disposition == "allow"


def test_policy_allows_action_ask() -> None:
    policy = UserPolicy(always_ask=["write_file"])
    allowed, disposition = policy_allows_action(policy, "write_file")
    assert allowed is False
    assert disposition == "ask"


def test_policy_allows_action_deny() -> None:
    policy = UserPolicy(always_deny=["send_email"])
    allowed, disposition = policy_allows_action(policy, "send_email")
    assert allowed is False
    assert disposition == "deny"


def test_policy_allows_unknown_action_defaults_to_ask() -> None:
    policy = UserPolicy()
    allowed, disposition = policy_allows_action(policy, "some_unknown_action")
    assert allowed is False
    assert disposition == "ask"


# ---------------------------------------------------------------------------
# Unit tests: merge_policy_into_autonomy
# ---------------------------------------------------------------------------

def test_merge_policy_into_autonomy() -> None:
    from beekeeper.autonomy import DEFAULT_AUTONOMY_POLICY

    policy = UserPolicy(
        always_allow=["web_search", "compute"],
        always_ask=["write_file"],
        always_deny=["send_email"],
        max_auto_cost_usd=2.00,
    )
    merged = merge_policy_into_autonomy(policy, DEFAULT_AUTONOMY_POLICY)

    # Cost limit propagated
    assert merged.max_auto_cost_usd == 2.00
    # always_allow actions added to allowed_intents or kept
    assert "web_search" in merged.allowed_intents or "research_topic" in merged.allowed_intents
    # always_ask and always_deny land in require_human_approval_for
    assert "write_file" in merged.require_human_approval_for
    assert "send_email" in merged.require_human_approval_for


# ---------------------------------------------------------------------------
# API integration: GET/PUT /api/policy
# ---------------------------------------------------------------------------

def test_api_policy_get_returns_default_for_new_user(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    client = TestClient(app)
    headers = _auth_headers(client, "policyget@example.com")

    resp = client.get("/api/policy", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "policy" in body
    assert "web_search" in body["policy"]["always_allow"]
    assert "write_file" in body["policy"]["always_ask"]


def test_api_policy_put_and_round_trip(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    client = TestClient(app)
    headers = _auth_headers(client, "policyput@example.com")

    put_resp = client.put(
        "/api/policy",
        headers=headers,
        json={
            "always_allow": ["web_search", "summarize", "compute"],
            "always_ask": ["write_file"],
            "always_deny": ["send_email"],
            "max_auto_cost_usd": 1.50,
        },
    )
    assert put_resp.status_code == 200

    get_resp = client.get("/api/policy", headers=headers)
    assert get_resp.status_code == 200
    policy = get_resp.json()["policy"]
    assert "compute" in policy["always_allow"]
    assert policy["always_deny"] == ["send_email"]
    assert policy["max_auto_cost_usd"] == 1.50


# ---------------------------------------------------------------------------
# API integration: GET /api/workers
# ---------------------------------------------------------------------------

def test_api_workers_list(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    client = TestClient(app)
    headers = _auth_headers(client, "workers@example.com")

    resp = client.get("/api/workers", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "workers" in body
    assert isinstance(body["workers"], list)
    # Should have at least built-in worker kinds
    worker_kinds = {w.get("worker_kind") for w in body["workers"]}
    assert len(worker_kinds) >= 1


# ---------------------------------------------------------------------------
# API integration: GET /api/history
# ---------------------------------------------------------------------------

def test_api_history_returns_list(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    client = TestClient(app)
    headers = _auth_headers(client, "history@example.com")

    resp = client.get("/api/history", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "history" in body
    assert isinstance(body["history"], list)


# ---------------------------------------------------------------------------
# API integration: GET /api/reviews
# ---------------------------------------------------------------------------

def test_api_reviews_list(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BEEKEEPER_HONEYCOMB_ROOT", str(tmp_path / "honeycomb"))
    client = TestClient(app)
    headers = _auth_headers(client, "reviews@example.com")

    resp = client.get("/api/reviews", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "reviews" in body
    assert isinstance(body["reviews"], list)
