from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import (
    AbilitiesProfile,
    AccountabilityPolicy,
    AgentBlueprint,
    GuardrailProfile,
    RuleProfile,
    SkillProfile,
    SoulProfile,
)


@dataclass
class RuntimeProfileSet:
    skill: SkillProfile
    rule: RuleProfile
    soul: SoulProfile
    abilities: AbilitiesProfile
    accountability: AccountabilityPolicy
    guardrails: GuardrailProfile


@dataclass
class SkillRuleSoulRegistry:
    skills: dict[str, SkillProfile] = field(default_factory=dict)
    rules: dict[str, RuleProfile] = field(default_factory=dict)
    souls: dict[str, SoulProfile] = field(default_factory=dict)
    abilities: dict[str, AbilitiesProfile] = field(default_factory=dict)
    accountabilities: dict[str, AccountabilityPolicy] = field(default_factory=dict)
    guardrails: dict[str, GuardrailProfile] = field(default_factory=dict)
    blueprints: dict[str, AgentBlueprint] = field(default_factory=dict)

    def register_skill(self, profile: SkillProfile) -> None:
        self.skills[profile.skill_profile_id] = profile

    def register_rule(self, profile: RuleProfile) -> None:
        self.rules[profile.rule_profile_id] = profile

    def register_soul(self, profile: SoulProfile) -> None:
        self.souls[profile.soul_profile_id] = profile

    def register_abilities(self, profile: AbilitiesProfile) -> None:
        self.abilities[profile.abilities_profile_id] = profile

    def register_accountability(self, profile: AccountabilityPolicy) -> None:
        self.accountabilities[profile.accountability_id] = profile

    def register_guardrail_profile(self, profile: GuardrailProfile) -> None:
        self.guardrails[profile.guardrail_profile_id] = profile

    def register_blueprint(self, blueprint: AgentBlueprint) -> None:
        self.blueprints[blueprint.blueprint_id] = blueprint

    def get_skill(self, skill_profile_id: str) -> SkillProfile:
        return self.skills[skill_profile_id]

    def get_rule(self, rule_profile_id: str) -> RuleProfile:
        return self.rules[rule_profile_id]

    def get_soul(self, soul_profile_id: str) -> SoulProfile:
        return self.souls[soul_profile_id]

    def get_abilities(self, abilities_profile_id: str) -> AbilitiesProfile:
        return self.abilities[abilities_profile_id]

    def get_accountability(self, accountability_id: str) -> AccountabilityPolicy:
        return self.accountabilities[accountability_id]

    def get_guardrail_profile(self, guardrail_profile_id: str) -> GuardrailProfile:
        return self.guardrails[guardrail_profile_id]

    def get_blueprint(self, blueprint_id: str) -> AgentBlueprint:
        return self.blueprints[blueprint_id]

    def resolve_profiles(self, blueprint_id: str) -> RuntimeProfileSet:
        blueprint = self.get_blueprint(blueprint_id)
        bundle = blueprint.profile_bundle
        return RuntimeProfileSet(
            skill=self.get_skill(bundle.skills_id),
            rule=self.get_rule(bundle.rules_id),
            soul=self.get_soul(bundle.soul_id),
            abilities=self.get_abilities(bundle.abilities_id),
            accountability=self.get_accountability(bundle.accountabilities_id),
            guardrails=self.get_guardrail_profile(bundle.guardrails_id),
        )
