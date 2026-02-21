from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import (
    AbilitiesProfile,
    AccountabilityPolicy,
    GuardrailProfile,
    RuleProfile,
    SkillProfile,
    SoulProfile,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_profile(profile_type: str, path: Path) -> Any:
    payload = _load_json(path)
    if profile_type == "skills":
        return SkillProfile.model_validate(payload)
    if profile_type == "rules":
        return RuleProfile.model_validate(payload)
    if profile_type == "soul":
        return SoulProfile.model_validate(payload)
    if profile_type == "abilities":
        return AbilitiesProfile.model_validate(payload)
    if profile_type == "accountabilities":
        return AccountabilityPolicy.model_validate(payload)
    if profile_type == "guardrails":
        return GuardrailProfile.model_validate(payload)
    raise ValueError(f"unsupported_profile_type={profile_type}")


def validate_profile_bundle(profile_paths: dict[str, Path]) -> dict[str, Any]:
    """
    Validate and return typed profile objects for deterministic composition order:
    accountabilities -> rules -> guardrails -> skills -> soul.
    """
    ordered = ["accountabilities", "rules", "guardrails", "skills", "soul", "abilities"]
    out: dict[str, Any] = {}
    for profile_type in ordered:
        path = profile_paths.get(profile_type)
        if path is None:
            continue
        out[profile_type] = load_profile(profile_type, path)
    return out
