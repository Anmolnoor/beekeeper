from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .autonomy import AutonomyPolicy
from .user_policy import UserPolicy, load_user_policy, merge_policy_into_autonomy


@dataclass
class ProfileResolution:
    autonomy_policy: AutonomyPolicy
    user_policy: UserPolicy | None = None


class ProfileService:
    """Resolves request-scoped user profile/policy settings."""

    def __init__(
        self,
        *,
        store_root_env_var: str = "BEEKEEPER_STORE_ROOT",
        default_store_root: str = ".beekeeper_store",
    ) -> None:
        self.store_root_env_var = store_root_env_var
        self.default_store_root = default_store_root

    def resolve_autonomy_policy(
        self,
        payload: dict[str, Any],
        *,
        default_autonomy_policy: AutonomyPolicy,
    ) -> ProfileResolution:
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            return ProfileResolution(autonomy_policy=default_autonomy_policy, user_policy=None)

        try:
            store_root = os.getenv(self.store_root_env_var, self.default_store_root)
            user_policy = load_user_policy(store_root, user_id)
            return ProfileResolution(
                autonomy_policy=merge_policy_into_autonomy(user_policy, default_autonomy_policy),
                user_policy=user_policy,
            )
        except Exception:
            return ProfileResolution(autonomy_policy=default_autonomy_policy, user_policy=None)
