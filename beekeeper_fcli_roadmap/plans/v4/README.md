# V4: Policy, Approvals, and Artifacts

V4 makes risky coding-worker behavior visible, reviewable, and auditable.

## Detailed Plan

- `04_policy_approvals_artifacts.md`

## V4 Goal

Beekeeper should own final side-effect decisions. The coding worker can request risky actions, but Beekeeper must record the policy reason, approval state, evidence, and final artifact trail.

## V4 Scope

- Side-effect policy enforcement.
- Approval queue integration.
- Approval request detail.
- Final diff and command artifacts.
- Verification artifacts.
- Audit trail from request to result.
- Stop-and-rerun first, mid-run resume later.

## V4 Exit Criteria

V4 is done when risky worker actions do not disappear into worker logs. They become Beekeeper approvals or blocked decisions with traceable evidence.

