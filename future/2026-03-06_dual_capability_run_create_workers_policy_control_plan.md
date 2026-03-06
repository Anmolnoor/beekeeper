# Plan: Dual Capability (Run + Create Workers) with Per-User Policy Control

Date: 2026-03-06

## Summary
Implement a dual-capability architecture where Queen can both run existing workers and create new workers, but worker creation is controlled by per-user policy and HITL.
Default behavior for unmatched intents will be: attempt create only after policy check (`ask` requires approval), otherwise fallback to existing worker routing.

## Public Interface Changes
- Add a clear runtime capability setting for worker creation behavior exposure (enabled), while enforcement remains user-policy based.
- Update `POST /v1/workers` contract to require user identity header and return policy-aware outcomes:
  - `allowed`: worker created
  - `ask`: review queued / pending approval
  - `deny`: creation blocked
- Keep `spawn_worker` action/tool publicly available, but make responses explicitly policy-scoped (`allow` / `ask` / `deny`) with consistent error codes.

## Implementation Changes
- Routing and auto-spawn behavior:
  - Gate `_route_worker_kind()` unmatched-intent auto-spawn behind user policy evaluation.
  - For policy `ask`, enqueue human review before creation.
  - For policy `deny`, skip create and route to default existing worker.
  - For policy `allow`, proceed with current create flow.
- Creation surfaces unification:
  - Centralize worker-creation authorization into one shared policy/HITL helper used by:
    - auto-spawn path,
    - `spawn_worker` queen action,
    - `spawn_worker` tool adapter,
    - `/v1/workers` API.
  - Remove divergent behavior between action/tool/API so all use one decision path.
- Policy model alignment:
  - Keep `spawn_worker` as a first-class action in user policy (`always_allow/ask/deny`).
  - Ensure API passes user context into policy evaluation consistently.
- Trace and audit:
  - Add explicit events for `spawn_policy_allowed`, `spawn_policy_ask`, `spawn_policy_denied`, and `spawn_review_enqueued`.
  - Preserve existing worker creation telemetry/events for successful creates.

## Test Plan
- Unit tests:
  - Policy helper returns correct decision for `allow`, `ask`, `deny`.
  - Auto-spawn route behavior for unmatched intents under each policy state.
  - `spawn_worker` action/tool return consistent policy-aware outputs.
- API tests:
  - `/v1/workers` with identity header:
    - allow creates worker,
    - ask queues review,
    - deny blocks with stable error.
  - Missing identity returns validation/auth error.
- Regression tests:
  - Existing worker execution path unchanged.
  - Generated worker reuse still works after successful creation.
  - No silent background creation when policy is `ask` or `deny`.

## Assumptions and Defaults
- Control model: Per-user policy only.
- Unmatched-intent behavior: Require Ask/HITL before auto-create.
- API governance: Enforce user policy + HITL for `/v1/workers`.
- `spawn_worker` remains available as a capability, not removed.
