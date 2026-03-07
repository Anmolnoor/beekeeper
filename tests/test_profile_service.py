from __future__ import annotations

from beekeeper.autonomy import DEFAULT_AUTONOMY_POLICY
from beekeeper.profile_service import ProfileService
from beekeeper.user_policy import UserPolicy, save_user_policy


def test_profile_service_uses_default_policy_without_user_id() -> None:
    service = ProfileService()
    result = service.resolve_autonomy_policy({}, default_autonomy_policy=DEFAULT_AUTONOMY_POLICY)
    assert result.user_policy is None
    assert result.autonomy_policy == DEFAULT_AUTONOMY_POLICY


def test_profile_service_merges_user_policy(tmp_path, monkeypatch) -> None:
    store_root = tmp_path / ".store"
    save_user_policy(
        store_root,
        "alice",
        UserPolicy(
            always_allow=["compute"],
            always_ask=[],
            always_deny=[],
            max_auto_cost_usd=1.23,
        ),
    )
    monkeypatch.setenv("BEEKEEPER_STORE_ROOT", str(store_root))
    service = ProfileService(default_store_root=str(store_root))
    result = service.resolve_autonomy_policy(
        {"user_id": "alice"},
        default_autonomy_policy=DEFAULT_AUTONOMY_POLICY,
    )
    assert result.user_policy is not None
    assert result.autonomy_policy.max_auto_cost_usd == 1.23
    assert "heavy_compute" in result.autonomy_policy.allowed_intents


def test_profile_service_falls_back_on_loader_errors(monkeypatch) -> None:
    service = ProfileService()
    monkeypatch.setattr("beekeeper.profile_service.load_user_policy", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    result = service.resolve_autonomy_policy(
        {"user_id": "alice"},
        default_autonomy_policy=DEFAULT_AUTONOMY_POLICY,
    )
    assert result.user_policy is None
    assert result.autonomy_policy == DEFAULT_AUTONOMY_POLICY
