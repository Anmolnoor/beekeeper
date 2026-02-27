from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import PolicyDecision, RuleProfile, TaskEnvelope, WorkerKind


class Guardrail(Protocol):
    def evaluate(self, task: TaskEnvelope, rule_profile: RuleProfile) -> tuple[bool, str | None]:
        ...


@dataclass
class SchemaGuardrail:
    def evaluate(self, task: TaskEnvelope, rule_profile: RuleProfile) -> tuple[bool, str | None]:
        if not task.task_type.strip():
            return False, "missing_task_type"
        return True, None


@dataclass
class PIIGuardrail:
    email_pattern: re.Pattern[str] = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

    def evaluate(self, task: TaskEnvelope, rule_profile: RuleProfile) -> tuple[bool, str | None]:
        text = " ".join(str(value) for value in task.payload.values())
        if self.email_pattern.search(text):
            return False, "pii_email_detected"
        return True, None


@dataclass
class JailbreakGuardrail:
    blocked_phrases: tuple[str, ...] = (
        "ignore previous instructions",
        "bypass safety",
        "disable guardrails",
    )

    def evaluate(self, task: TaskEnvelope, rule_profile: RuleProfile) -> tuple[bool, str | None]:
        haystack = " ".join([task.task_type, " ".join(str(v) for v in task.payload.values())]).lower()
        for phrase in self.blocked_phrases:
            if phrase in haystack:
                return False, "jailbreak_phrase_detected"
        return True, None


@dataclass
class WebDomainGuardrail:
    def _is_allowed(self, domain: str, allowed_domains: list[str]) -> bool:
        if not allowed_domains:
            return True
        return domain in {entry.lower() for entry in allowed_domains}

    def _domain_from_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        return (parsed.hostname or "").lower()

    def evaluate(self, task: TaskEnvelope, rule_profile: RuleProfile) -> tuple[bool, str | None]:
        if task.worker_kind != WorkerKind.web_search:
            return True, None
        domains = task.payload.get("domains", [])
        if not domains:
            return True, None
        if not isinstance(domains, list):
            return False, "invalid_domains_payload"
        normalized_domains = [str(domain).lower() for domain in domains]
        if rule_profile.allowed_domains and any(domain not in rule_profile.allowed_domains for domain in normalized_domains):
            return False, "domain_not_allowed"
        fetched_urls = task.payload.get("fetched_urls", [])
        if isinstance(fetched_urls, list):
            for raw_url in fetched_urls:
                domain = self._domain_from_url(str(raw_url))
                if domain and not self._is_allowed(domain, rule_profile.allowed_domains):
                    return False, "fetched_domain_not_allowed"
        return True, None


@dataclass
class HeavyComputeBudgetGuardrail:
    def evaluate(self, task: TaskEnvelope, rule_profile: RuleProfile) -> tuple[bool, str | None]:
        if task.worker_kind != WorkerKind.heavy_compute:
            return True, None
        # Enforce hard ceiling with a tiny tolerance for float noise.
        if task.budget_usd > (rule_profile.hard_budget_usd * 1.05):
            return False, "budget_exceeds_rule_limit"
        sample = task.payload.get("numbers")
        if isinstance(sample, list) and len(sample) > 10_000:
            return False, "compute_payload_too_large"
        return True, None


@dataclass
class AuditPayloadGuardrail:
    def evaluate(self, task: TaskEnvelope, rule_profile: RuleProfile) -> tuple[bool, str | None]:
        _ = rule_profile
        if task.worker_kind != WorkerKind.audit:
            return True, None
        target_task_id = str(task.payload.get("target_task_id", "")).strip()
        if not target_task_id:
            return False, "audit_target_missing"
        return True, None


class GuardrailPolicyEngine:
    def __init__(self, guardrails: list[Guardrail]) -> None:
        self._guardrails = guardrails

    def evaluate(self, task: TaskEnvelope, rule_profile: RuleProfile) -> PolicyDecision:
        flags: list[str] = []
        for guardrail in self._guardrails:
            ok, flag = guardrail.evaluate(task, rule_profile)
            if not ok and flag is not None:
                flags.append(flag)
        high_risk_action = str(task.payload.get("action", "")).strip()
        needs_human = high_risk_action in set(rule_profile.require_human_approval_for)
        if task.payload.get("requires_human_approval") is True:
            needs_human = True
        if flags:
            return PolicyDecision(
                task_id=task.task_id,
                status="block",
                reason="guardrail_denied",
                guardrail_flags=flags,
            )
        if needs_human:
            return PolicyDecision(
                task_id=task.task_id,
                status="needs_human",
                reason="human_approval_required",
                guardrail_flags=[],
                requires_human_approval=True,
            )
        return PolicyDecision(task_id=task.task_id, status="approve", reason="policy_passed", guardrail_flags=[])

    def apply_budget_controls(self, task: TaskEnvelope, rule_profile: RuleProfile) -> tuple[TaskEnvelope, str]:
        """
        Apply early-stop and model-tier hints without mutating caller references.
        """
        clone = TaskEnvelope.model_validate(task.model_dump(mode="json"))
        if clone.budget_usd <= max(0.01, rule_profile.hard_budget_usd * 0.2):
            clone.payload.setdefault("model_tier", "economy")
            clone.payload.setdefault("early_stop", True)
            return clone, "downgraded_to_economy_tier"
        if clone.budget_usd >= rule_profile.hard_budget_usd * 0.8:
            clone.payload.setdefault("model_tier", "premium")
            return clone, "upgraded_to_premium_tier"
        clone.payload.setdefault("model_tier", "standard")
        return clone, "kept_standard_tier"


# ---------------------------------------------------------------------------
# Tool-call-level guardrails (for model-driven tool loop)
# ---------------------------------------------------------------------------

# Tools that correspond to high-risk actions and require HITL when in rule_profile.require_human_approval_for
TOOL_TO_ACTION_MAP: dict[str, str] = {
    "spawn_worker": "spawn_worker",
    "run_task": "run_task",
}

PII_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _domains_from_tool_args(arguments: dict[str, Any]) -> list[str]:
    """Extract domain names from tool arguments (domains list or URLs in string values)."""
    domains: list[str] = []
    if not isinstance(arguments, dict):
        return domains
    if isinstance(arguments.get("domains"), list):
        for d in arguments["domains"]:
            if isinstance(d, str) and d.strip():
                domains.append(d.strip().lower())
    for v in arguments.values():
        if isinstance(v, str) and ("http://" in v or "https://" in v):
            parsed = urllib.parse.urlparse(v)
            if parsed.hostname:
                domains.append(parsed.hostname.lower())
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str) and ("http://" in item or "https://" in item):
                    parsed = urllib.parse.urlparse(item)
                    if parsed.hostname:
                        domains.append(parsed.hostname.lower())
    return list(dict.fromkeys(domains))


def evaluate_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    rule_profile: RuleProfile,
) -> tuple[bool, str | None, bool]:
    """
    Evaluate a single tool call before execution.
    Returns (allowed, block_reason, needs_human).
    If allowed is False, block_reason is set. If needs_human is True, caller should enqueue HITL.
    Evaluates: tool name (allowlist/denylist), tool args (PII, domain allowlist), HITL for high-risk tools.
    """
    if tool_name in (rule_profile.disallowed_tools or []):
        return False, "tool_disallowed_by_rule", False
    action_equivalent = TOOL_TO_ACTION_MAP.get(tool_name)
    if action_equivalent and action_equivalent in (rule_profile.require_human_approval_for or []):
        return True, None, True
    haystack = " ".join(str(v) for v in arguments.values()) if isinstance(arguments, dict) else ""
    if PII_EMAIL_PATTERN.search(haystack):
        return False, "pii_email_in_tool_args", False
    # External network domain: if rule restricts domains, validate any domains in tool args
    allowed_domains = rule_profile.allowed_domains or []
    if allowed_domains:
        normalized_allowed = {d.lower() for d in allowed_domains}
        for domain in _domains_from_tool_args(arguments or {}):
            if domain and domain not in normalized_allowed:
                return False, "domain_not_allowed", False
    return True, None, False
