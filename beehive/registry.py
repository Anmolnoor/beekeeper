from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import RuleProfile, SkillProfile, SoulProfile


@dataclass
class SkillRuleSoulRegistry:
    skills: dict[str, SkillProfile] = field(default_factory=dict)
    rules: dict[str, RuleProfile] = field(default_factory=dict)
    souls: dict[str, SoulProfile] = field(default_factory=dict)

    def register_skill(self, profile: SkillProfile) -> None:
        self.skills[profile.skill_profile_id] = profile

    def register_rule(self, profile: RuleProfile) -> None:
        self.rules[profile.rule_profile_id] = profile

    def register_soul(self, profile: SoulProfile) -> None:
        self.souls[profile.soul_profile_id] = profile

    def get_skill(self, skill_profile_id: str) -> SkillProfile:
        return self.skills[skill_profile_id]

    def get_rule(self, rule_profile_id: str) -> RuleProfile:
        return self.rules[rule_profile_id]

    def get_soul(self, soul_profile_id: str) -> SoulProfile:
        return self.souls[soul_profile_id]
