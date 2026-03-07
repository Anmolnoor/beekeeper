from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .contracts import PolicyDecision, ResultEnvelope, RetryCategory, Status, TaskEnvelope
from .governance import adapter_decision_to_policy


@dataclass
class PolicyService:
    honeycomb: Any
    guardrail_engine: Any
    policy_adapter: Any
    resolve_human_approval: Callable[[TaskEnvelope, PolicyDecision], PolicyDecision]
    execute_worker_task: Callable[[TaskEnvelope, Any, str, str | None], ResultEnvelope]
    build_worker_context: Callable[[TaskEnvelope, Callable[[str], None] | None], Any]

    def run_task_with_policies(
        self,
        task: TaskEnvelope,
        scheduler_backend: str,
        parent_span_id: str | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> tuple[ResultEnvelope, RetryCategory | None]:
        context = self.build_worker_context(task, status_callback)
        policy_task, budget_decision = self.guardrail_engine.apply_budget_controls(task, context.rule)
        self.honeycomb.write_event(
            task.queen_trace_id,
            {
                "kind": "budget_control",
                "task_id": task.task_id,
                "decision": budget_decision,
                "model_tier": policy_task.payload.get("model_tier"),
                "early_stop": bool(policy_task.payload.get("early_stop", False)),
            },
        )
        base_policy = self.guardrail_engine.evaluate(policy_task, context.rule)
        adapter_decision = self.policy_adapter.evaluate_task(
            task=policy_task,
            rule_profile=context.rule,
            capability_manifest=context.capability_manifest,
            base_policy=base_policy,
        )
        policy = adapter_decision_to_policy(policy_task.task_id, adapter_decision)
        policy = self.resolve_human_approval(policy_task, policy)
        self.honeycomb.write_policy_decision(policy, trace_id=task.queen_trace_id)
        if policy.status == "block":
            policy_task.status = Status.blocked
            self.honeycomb.write_task(policy_task)
            return (
                ResultEnvelope(
                    task_id=policy_task.task_id,
                    agent_id=context.identity.agent_id,
                    worker_kind=policy_task.worker_kind,
                    status=Status.blocked,
                    confidence=0.0,
                    output={"error": policy.reason},
                    policy_flags=policy.guardrail_flags,
                    output_schema="PolicyBlock",
                ),
                RetryCategory.policy,
            )
        if policy.status == "needs_human":
            policy_task.status = Status.blocked
            self.honeycomb.write_task(policy_task)
            return (
                ResultEnvelope(
                    task_id=policy_task.task_id,
                    agent_id=context.identity.agent_id,
                    worker_kind=policy_task.worker_kind,
                    status=Status.blocked,
                    confidence=0.0,
                    output={
                        "error": "awaiting_human_approval",
                        "reason": policy.reason,
                        "human_review_id": policy_task.payload.get("human_review_id"),
                    },
                    policy_flags=["needs_human_approval"],
                    output_schema="HumanApprovalPending",
                ),
                RetryCategory.policy,
            )
        result = self.execute_worker_task(
            policy_task,
            context,
            scheduler_backend,
            parent_span_id,
        )
        return result, None
