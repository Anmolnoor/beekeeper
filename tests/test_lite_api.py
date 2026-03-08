from __future__ import annotations

from fastapi.testclient import TestClient

import queen_api.app as queen_app


class StubAssistant:
    def __init__(self):
        self.calls = []

    def chat(self, *, messages, user_id, chat_id=None, model_override=None):
        self.calls.append(
            {
                "messages": messages,
                "user_id": user_id,
                "chat_id": chat_id,
                "model_override": model_override,
            }
        )
        return {
            "ok": True,
            "reply": "Lite reply",
            "chat_id": "chat_123",
            "provider": "stub",
            "title": "Test Chat",
        }

    def list_chats(self, user_id: str, limit: int = 50):
        return [{"chat_id": "chat_123", "title": "Test Chat", "updated_at": "now"}]

    def get_chat(self, chat_id: str):
        if chat_id != "chat_123":
            return None
        return {"chat_id": chat_id, "title": "Test Chat", "messages": []}


def test_chat_completions_uses_lite_assistant(monkeypatch):
    stub = StubAssistant()
    monkeypatch.setattr(queen_app, "_assistant", stub)
    client = TestClient(queen_app.app)

    response = client.post(
        "/v1/chat/completions",
        headers={
            "X-Beekeeper-User-Id": "anmol",
            "X-Beekeeper-Chat-Id": "chat_existing",
            "X-Beekeeper-Model": "local-test-model",
        },
        json={
            "model": "beekeeper-lite",
            "stream": False,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "Lite reply"
    assert body["chat_id"] == "chat_123"
    assert body["provider"] == "stub"
    assert stub.calls[0]["user_id"] == "anmol"
    assert stub.calls[0]["chat_id"] == "chat_existing"
    assert stub.calls[0]["model_override"] == "local-test-model"


def test_chat_listing_endpoint(monkeypatch):
    stub = StubAssistant()
    monkeypatch.setattr(queen_app, "_assistant", stub)
    client = TestClient(queen_app.app)

    response = client.get("/v1/chats", params={"user_id": "anmol"})

    assert response.status_code == 200
    assert response.json()["chats"][0]["chat_id"] == "chat_123"
