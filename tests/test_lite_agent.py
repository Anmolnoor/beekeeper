from __future__ import annotations

from pathlib import Path

from beekeeper.lite_agent import LiteAssistant, LiteAssistantConfig


class FakeRouter:
    def call(self, prompt, system=None, messages=None, model_override=None):
        assert "simple personal assistant" in (system or "")
        assert prompt == "Hello there"
        assert model_override == "demo-model"
        return "Hi back.", "fake"


def test_lite_agent_creates_and_persists_chat(tmp_path: Path):
    assistant = LiteAssistant(
        config=LiteAssistantConfig(store_root=tmp_path),
        router=FakeRouter(),
    )

    result = assistant.chat(
        messages=[{"role": "user", "content": "Hello there"}],
        user_id="anmol",
        model_override="demo-model",
    )

    assert result["ok"] is True
    assert result["reply"] == "Hi back."
    assert result["provider"] == "fake"
    assert result["chat_id"]

    saved = assistant.get_chat(result["chat_id"])
    assert saved is not None
    assert [message["role"] for message in saved["messages"]] == ["user", "assistant"]
    assert saved["messages"][1]["content"] == "Hi back."
