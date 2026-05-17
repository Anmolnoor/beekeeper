from __future__ import annotations

import re
import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ..contracts import PolicyDecision, RuleProfile, TaskEnvelope
from .capability_manifests import CapabilityManifest


@dataclass
class PolicyAdapterDecision:
    decision: Literal["allow", "deny", "escalate"]
    reason_codes: list[str] = field(default_factory=list)
    obligations: list[str] = field(default_factory=list)
    policy_version: str = "local/v1"


class PolicyAdapter(Protocol):
    def evaluate_task(
        self,
        *,
        task: TaskEnvelope,
        rule_profile: RuleProfile,
        capability_manifest: CapabilityManifest | None,
        base_policy: PolicyDecision,
    ) -> PolicyAdapterDecision:
        ...

    def evaluate_tool_call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        rule_profile: RuleProfile,
        capability_manifest: CapabilityManifest | None,
    ) -> PolicyAdapterDecision:
        ...


class LocalPolicyAdapter:
    """Local policy engine adapter that composes rule profile + capability manifest checks."""

    policy_version = "local/v1"
    _email_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

    def evaluate_task(
        self,
        *,
        task: TaskEnvelope,
        rule_profile: RuleProfile,
        capability_manifest: CapabilityManifest | None,
        base_policy: PolicyDecision,
    ) -> PolicyAdapterDecision:
        if base_policy.status == "block":
            return PolicyAdapterDecision(
                decision="deny",
                reason_codes=list(base_policy.guardrail_flags or [base_policy.reason]),
                policy_version=self.policy_version,
            )
        reason_codes: list[str] = []
        obligations: list[str] = []
        if task.budget_usd > max(0.0, float(rule_profile.hard_budget_usd)):
            reason_codes.append("budget_exceeds_rule_limit")
        if capability_manifest is not None:
            ok, manifest_codes, needs_human = capability_manifest.check_task(task)
            if not ok:
                reason_codes.extend(manifest_codes)
            if needs_human:
                obligations.append("require_approval")
        action = str(task.payload.get("action", "")).strip()
        if action and action in set(rule_profile.require_human_approval_for):
            obligations.append("require_approval")
        if base_policy.status == "needs_human":
            obligations.append("require_approval")
            reason_codes.append("human_approval_required")
        if reason_codes and "human_approval_required" not in reason_codes:
            return PolicyAdapterDecision("deny", sorted(set(reason_codes)), obligations, self.policy_version)
        if "require_approval" in obligations:
            return PolicyAdapterDecision("escalate", sorted(set(reason_codes)), sorted(set(obligations)), self.policy_version)
        return PolicyAdapterDecision("allow", sorted(set(reason_codes)), sorted(set(obligations)), self.policy_version)

    def evaluate_tool_call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        rule_profile: RuleProfile,
        capability_manifest: CapabilityManifest | None,
    ) -> PolicyAdapterDecision:
        reason_codes: list[str] = []
        obligations: list[str] = []
        if tool_name in set(rule_profile.disallowed_tools or []):
            reason_codes.append("tool_disallowed_by_rule")
        if capability_manifest is not None:
            ok, manifest_codes, needs_human = capability_manifest.check_tool_call(tool_name, arguments)
            if not ok:
                reason_codes.extend(manifest_codes)
            if needs_human:
                obligations.append("require_approval")
        action = TOOL_TO_ACTION_MAP.get(tool_name)
        if action and action in set(rule_profile.require_human_approval_for or []):
            obligations.append("require_approval")
        haystack = " ".join(str(v) for v in arguments.values()) if isinstance(arguments, dict) else ""
        if self._email_pattern.search(haystack):
            reason_codes.append("pii_email_in_tool_args")
        if reason_codes:
            return PolicyAdapterDecision("deny", sorted(set(reason_codes)), sorted(set(obligations)), self.policy_version)
        if obligations:
            return PolicyAdapterDecision("escalate", sorted(set(reason_codes)), sorted(set(obligations)), self.policy_version)
        return PolicyAdapterDecision("allow", [], [], self.policy_version)


class HttpPolicyAdapter:
    """OPA-compatible HTTP policy adapter with local fallback semantics."""

    def __init__(self, endpoint: str, *, timeout_seconds: int = 5) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.policy_version = "http/v1"

    def _post(self, path: str, payload: dict[str, Any]) -> PolicyAdapterDecision:
        request = urllib.request.Request(
            f"{self.endpoint}/{path.lstrip('/')}",
            data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:  # pragma: no cover - network path
            raw = json.loads(response.read().decode("utf-8"))
        return PolicyAdapterDecision(
            decision=str(raw.get("decision", "deny")),  # type: ignore[arg-type]
            reason_codes=[str(item) for item in raw.get("reason_codes", [])],
            obligations=[str(item) for item in raw.get("obligations", [])],
            policy_version=str(raw.get("policy_version", self.policy_version)),
        )

    def evaluate_task(
        self,
        *,
        task: TaskEnvelope,
        rule_profile: RuleProfile,
        capability_manifest: CapabilityManifest | None,
        base_policy: PolicyDecision,
    ) -> PolicyAdapterDecision:
        return self._post(
            "task",
            {
                "task": task.model_dump(mode="json"),
                "rule_profile": rule_profile.model_dump(mode="json"),
                "capability_manifest": capability_manifest.to_dict() if capability_manifest else None,
                "base_policy": base_policy.model_dump(mode="json"),
            },
        )

    def evaluate_tool_call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        rule_profile: RuleProfile,
        capability_manifest: CapabilityManifest | None,
    ) -> PolicyAdapterDecision:
        return self._post(
            "tool",
            {
                "tool_name": tool_name,
                "arguments": arguments,
                "rule_profile": rule_profile.model_dump(mode="json"),
                "capability_manifest": capability_manifest.to_dict() if capability_manifest else None,
            },
        )


def adapter_decision_to_policy(task_id: str, decision: PolicyAdapterDecision) -> PolicyDecision:
    if decision.decision == "deny":
        return PolicyDecision(
            task_id=task_id,
            status="block",
            reason="policy_adapter_deny",
            guardrail_flags=decision.reason_codes,
            reason_codes=decision.reason_codes,
            obligations=decision.obligations,
            policy_version=decision.policy_version,
        )
    if decision.decision == "escalate":
        return PolicyDecision(
            task_id=task_id,
            status="needs_human",
            reason="policy_adapter_escalate",
            guardrail_flags=decision.reason_codes,
            reason_codes=decision.reason_codes,
            obligations=decision.obligations,
            policy_version=decision.policy_version,
            requires_human_approval=True,
        )
    return PolicyDecision(
        task_id=task_id,
        status="approve",
        reason="policy_adapter_allow",
        guardrail_flags=decision.reason_codes,
        reason_codes=decision.reason_codes,
        obligations=decision.obligations,
        policy_version=decision.policy_version,
    )


TOOL_TO_ACTION_MAP: dict[str, str] = {
    "spawn_worker": "spawn_worker",
    "run_task": "run_task",
}


def build_policy_adapter() -> PolicyAdapter:
    endpoint = os.getenv("BEEKEEPER_POLICY_ENDPOINT", "").strip()
    if endpoint:
        return HttpPolicyAdapter(endpoint)
    return LocalPolicyAdapter()
