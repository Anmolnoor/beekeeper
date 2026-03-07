from __future__ import annotations

from beekeeper.store import BeekeeperStore


def test_channel_secret_reference_resolves_from_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEEKEEPER_SECRET_MANAGER_PROVIDER", "env")
    monkeypatch.setenv("SLACK_BOT_TOKEN_SECRET", "xoxb-secret")
    store = BeekeeperStore(tmp_path / "store")

    store.write_channel_config("slack", {"slack_bot_token": "env://SLACK_BOT_TOKEN_SECRET"})
    resolved = store.get_channel_config_decrypted("slack")

    assert resolved is not None
    assert resolved["slack_bot_token"] == "xoxb-secret"
