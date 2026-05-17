from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contracts import RuleProfile, SkillProfile, TaskEnvelope, WorkerKind


@dataclass
class CapabilityManifest:
    manifest_id: str
    subject_id: str
    allowed_worker_kinds: set[WorkerKind] = field(default_factory=set)
    allowed_tools: set[str] = field(default_factory=set)
    allowed_secret_refs: set[str] = field(default_factory=set)
    allowed_network_domains: set[str] = field(default_factory=set)
    max_runtime_seconds: int = 120
    max_budget_usd: float = 2.0
    require_human_approval_for_actions: set[str] = field(default_factory=set)
    allowed_data_tags: set[str] = field(default_factory=set)
    allowed_channels: set[str] = field(default_factory=set)
    sandbox_tier: int = 0
    policy_version: str = "local/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "subject_id": self.subject_id,
            "allowed_worker_kinds": [kind.value for kind in sorted(self.allowed_worker_kinds, key=lambda k: k.value)],
            "allowed_tools": sorted(self.allowed_tools),
            "allowed_secret_refs": sorted(self.allowed_secret_refs),
            "allowed_network_domains": sorted(self.allowed_network_domains),
            "max_runtime_seconds": self.max_runtime_seconds,
            "max_budget_usd": self.max_budget_usd,
            "require_human_approval_for_actions": sorted(self.require_human_approval_for_actions),
            "allowed_data_tags": sorted(self.allowed_data_tags),
            "allowed_channels": sorted(self.allowed_channels),
            "sandbox_tier": self.sandbox_tier,
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CapabilityManifest":
        kinds: set[WorkerKind] = set()
        for raw in payload.get("allowed_worker_kinds") or []:
            try:
                kinds.add(WorkerKind(str(raw)))
            except ValueError:
                continue
        return cls(
            manifest_id=str(payload.get("manifest_id", "")),
            subject_id=str(payload.get("subject_id", "")),
            allowed_worker_kinds=kinds,
            allowed_tools=_as_string_set(payload.get("allowed_tools")),
            allowed_secret_refs=_as_string_set(payload.get("allowed_secret_refs")),
            allowed_network_domains=_as_string_set(payload.get("allowed_network_domains")),
            max_runtime_seconds=int(payload.get("max_runtime_seconds", 120)),
            max_budget_usd=float(payload.get("max_budget_usd", 2.0)),
            require_human_approval_for_actions=_as_string_set(payload.get("require_human_approval_for_actions")),
            allowed_data_tags=_as_string_set(payload.get("allowed_data_tags")),
            allowed_channels=_as_string_set(payload.get("allowed_channels")),
            sandbox_tier=int(payload.get("sandbox_tier", 0)),
            policy_version=str(payload.get("policy_version", "local/v1")),
        )

    def check_task(self, task: TaskEnvelope) -> tuple[bool, list[str], bool]:
        reason_codes: list[str] = []
        if self.allowed_worker_kinds and task.worker_kind not in self.allowed_worker_kinds:
            reason_codes.append("worker_kind_not_allowed")
        if task.budget_usd > self.max_budget_usd:
            reason_codes.append("budget_exceeds_manifest_limit")
        task_domains = _extract_domains_from_payload(task.payload)
        if self.allowed_network_domains and any(domain not in self.allowed_network_domains for domain in task_domains):
            reason_codes.append("network_domain_not_allowed")
        requested_tags = _as_string_set(task.payload.get("data_tags"))
        if requested_tags and self.allowed_data_tags and not requested_tags.issubset(self.allowed_data_tags):
            reason_codes.append("data_tags_not_allowed")
        requested_channel = str(task.payload.get("channel", "")).strip().lower()
        if requested_channel and self.allowed_channels and requested_channel not in self.allowed_channels:
            reason_codes.append("channel_not_allowed")
        action = str(task.payload.get("action", "")).strip()
        needs_human = bool(action and action in self.require_human_approval_for_actions)
        return len(reason_codes) == 0, reason_codes, needs_human

    def check_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> tuple[bool, list[str], bool]:
        reason_codes: list[str] = []
        if self.allowed_tools and tool_name not in self.allowed_tools:
            reason_codes.append("tool_not_in_capability_manifest")
        call_domains = _extract_domains_from_payload(arguments)
        if self.allowed_network_domains and any(domain not in self.allowed_network_domains for domain in call_domains):
            reason_codes.append("tool_domain_not_allowed")
        action = str(arguments.get("action", "")).strip()
        needs_human = bool(action and action in self.require_human_approval_for_actions)
        return len(reason_codes) == 0, reason_codes, needs_human


class CapabilityManifestRegistry:
    def __init__(self) -> None:
        self._by_subject: dict[str, CapabilityManifest] = {}

    def register(self, manifest: CapabilityManifest) -> None:
        self._by_subject[manifest.subject_id] = manifest

    def get(self, subject_id: str) -> CapabilityManifest | None:
        return self._by_subject.get(subject_id)


def build_manifest_from_skill_rule(
    *,
    manifest_id: str,
    subject_id: str,
    worker_kind: WorkerKind,
    skill: SkillProfile,
    rule: RuleProfile,
    sandbox_tier: int = 0,
) -> CapabilityManifest:
    tool_allowlist = {tool.strip() for tool in (skill.tool_allowlist or []) if tool.strip()}
    domains = {domain.lower().strip() for domain in (rule.allowed_domains or []) if domain.strip()}
    human_actions = {action.strip() for action in (rule.require_human_approval_for or []) if action.strip()}
    return CapabilityManifest(
        manifest_id=manifest_id,
        subject_id=subject_id,
        allowed_worker_kinds={worker_kind},
        allowed_tools=tool_allowlist,
        allowed_network_domains=domains,
        max_runtime_seconds=max(1, int(rule.max_runtime_seconds)),
        max_budget_usd=max(0.0, float(rule.hard_budget_usd)),
        require_human_approval_for_actions=human_actions,
        allowed_data_tags={"internal_only", "public"},
        allowed_channels={"slack", "telegram", "discord", "whatsapp", "api"},
        sandbox_tier=sandbox_tier,
    )


def _as_string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    out: set[str] = set()
    for item in value:
        text = str(item).strip().lower()
        if text:
            out.add(text)
    return out


def _extract_domains_from_payload(payload: dict[str, Any]) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    domains: set[str] = set()
    raw_domains = payload.get("domains")
    if isinstance(raw_domains, list):
        for item in raw_domains:
            text = str(item).strip().lower()
            if text:
                domains.add(text)
    raw_urls = payload.get("fetched_urls")
    if isinstance(raw_urls, list):
        for item in raw_urls:
            text = str(item).strip().lower()
            if "://" in text:
                host = text.split("://", 1)[1].split("/", 1)[0].strip()
                if host:
                    domains.add(host)
    return domains
