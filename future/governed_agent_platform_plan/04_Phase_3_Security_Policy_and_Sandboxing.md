# Phase 3 — Real Governance, Security, and Sandboxing

## Goal

Replace shallow guardrails with **runtime-enforced governance**, **fail-closed security**, and **real execution isolation**.

This phase is where the project starts earning the word “governed”.

---

## Why this phase matters

The current direction is promising, but the critique correctly points out that current controls are still relatively shallow:

- regex-ish or phrase-match style guardrails
- lightweight budget/domain checks
- permissive security defaults
- unclear replay defense
- no strong sandbox story
- no deep policy composition model
- no robust provenance handling for external tool outputs

This phase turns those into explicit platform capabilities.

---

## The three governance checkpoints

Every sensitive action should be mediated at one or more of these checkpoints:

### 1. Admission-time policy
Can this run be created at all?

### 2. Plan-time policy
Does the proposed plan exceed allowed scope, cost, tools, data domains, or risk tier?

### 3. Action-time policy
Can this exact tool call or outbound action happen **right now**, under this principal, tenant, resource scope, risk tier, and approval state?

---

## Adopt a policy engine

Recommended choice: **OPA / Rego**.

Use the application to **enforce** policy outcomes, but not to **define** policy inline with orchestration code.

### Policy decision contract

Suggested input shape:

```json
{
  "principal": {
    "user_id": "...",
    "roles": ["..."],
    "org_id": "...",
    "hive_id": "..."
  },
  "run": {
    "run_id": "...",
    "queen_id": "...",
    "risk_tier": "low|medium|high",
    "approval_state": "pending|approved|denied|not_required"
  },
  "action": {
    "type": "tool_call|channel_send|artifact_export|secret_access",
    "tool": "...",
    "resource_scope": ["..."],
    "network_targets": ["..."]
  },
  "budgets": {
    "tokens": 0,
    "cost_limit": 0,
    "runtime_seconds": 0
  },
  "data_tags": ["pii", "customer_data", "internal_only"],
  "environment": {
    "mode": "dev|internal|prod"
  }
}
```

Suggested output shape:

```json
{
  "decision": "allow|deny|escalate",
  "reason_codes": ["..."],
  "obligations": [
    "require_approval",
    "mask_output",
    "record_provenance",
    "force_sandbox_tier_2"
  ],
  "policy_version": "..."
}
```

---

## Add capability manifests

Each worker / queen / tool profile should declare:

- allowed tools
- allowed secret references
- allowed network destinations
- max runtime
- max tokens
- max spend
- required sandbox tier
- whether human approval is required
- allowed data classifications
- allowed channels

This replaces ambient authority with explicit capability boundaries.

---

## Approval model

Approval must be a **state machine**, not a UI convention.

Rules:

- approval is bound to a **frozen plan snapshot**
- if the plan changes materially, approval becomes `superseded`
- approval records must capture who approved, when, under which policy version, and for what scope
- action-time policy must verify approval state before high-risk calls

---

## Secrets management model

### New rule
In production, workers never rely on dev-default secrets or generated one-off encryption keys.

### Required changes
- move long-lived secrets to a secret manager
- store only secret references in platform metadata
- scope access by org / hive / worker capability
- rotate secrets
- audit secret access
- support emergency break-glass procedures

### Special note on channel encryption
If encryption keys are generated ad hoc on restart, encrypted data can become undecryptable. Fix this by using stable, managed key material per environment and, where needed, per tenant.

---

## Webhook and channel ingress hardening

For every inbound webhook/provider event:

- verify signature
- validate timestamp / freshness
- store provider event ID for dedupe
- enforce idempotent handler semantics
- record verification result in audit log
- reject invalid or replayed requests

This must be standardized across channel adapters, not reimplemented ad hoc.

---

## Introduce a tool broker

Workers should not hold broad credentials directly for sensitive operations.

Preferred model:

1. worker requests operation from tool broker
2. broker evaluates policy + capability manifest
3. broker obtains scoped credential or performs action
4. result + provenance are written back
5. audit event is emitted

This is especially important for:
- outbound messaging
- secrets retrieval
- file export
- destructive third-party actions
- generated worker operations

---

## Sandboxing model

Use **trust-tiered isolation**.

| Tier | Use case | Minimum isolation |
|---|---|---|
| Tier 0 | built-in trusted worker code | rootless container, read-only root FS, tmpfs scratch, no host mounts, egress allowlist |
| Tier 1 | semi-trusted integrations / third-party tools | Tier 0 + gVisor sandbox runtime |
| Tier 2 | generated workers / untrusted code / strong tenant isolation | Firecracker microVM or equivalent isolated execution substrate |

### Non-negotiable sandbox rules
- no shared host write access
- no broad network egress
- no shared broad credentials
- no persistent local state
- clear per-run scratch directory lifecycle
- explicit resource limits
- kill / timeout support

---

## Provenance requirements

For every significant tool or model action, store:

- request hash or snapshot reference
- output checksum
- provider/model/version
- tool version
- worker version/build
- policy version
- secret reference IDs used (not secret values)
- actor/principal
- timestamp

This is required for:
- auditability
- incident review
- regression analysis
- reproducibility

---

## Suggested module additions

```text
app/
  governance/
    policy_client.py
    policy_models.py
    approval_service.py
    capability_manifests.py
    provenance_service.py
    tool_broker.py

  security/
    config_enforcement.py
    secrets_service.py
    webhook_verifier.py
    replay_store.py
    sandbox_profiles.py
```

---

## Definition of done

Phase 3 is complete when all of the following are true:

- prod startup fails on missing or insecure critical config
- side-effectful actions cannot bypass policy evaluation
- approvals pause the runtime through durable state
- secrets come from a managed source in prod
- every inbound webhook path has signature + replay defense
- workers run under explicit sandbox profiles
- significant tool/model actions capture provenance metadata

---

## Success metrics

- percentage of side-effect tools routed through tool broker
- percentage of production secrets retrieved from secret manager
- percentage of inbound webhook paths with replay defense tests
- percentage of high-risk actions requiring approval
- percentage of workers assigned an explicit sandbox tier

---

## Risks and how to handle them

### Risk: policy engine adoption feels like extra work
Mitigation: start with a small decision surface and a thin adapter; grow policy coverage gradually.

### Risk: sandboxing adds performance cost
Mitigation: use tiered isolation. Do not run every workload in the heaviest isolation profile.

### Risk: secret manager migration is disruptive
Mitigation: introduce secret references first, then replace inline reads gradually.

---

## Mapping to the critique

This phase directly addresses:

- **4D** guardrails are directionally right but shallow
- **4G** security defaults are too loose
- **5 Gap 2** no strong sandbox story
- **5 Gap 3** no strong policy engine abstraction
- **6 Priority 3** harden security defaults

It also supports:

- safer channels
- safer multi-tenancy
- safer worker forge later

---

## Research basis

Primary references: `[R2]`, `[R3]`, `[R4]`, `[R5]`, `[R6]`, `[R10]`, `[R11]`, `[R12]`

Why these matter here:

- `[R5]` is the main basis for policy-as-code.
- `[R6]` informs scalable authorization thinking and explainable policy modeling.
- `[R10]` and `[R11]` justify real runtime isolation rather than purely logical guardrails.
- `[R12]` informs secrets, logging, and verification practices.
- `[R3]` and `[R4]` anchor governance, provenance, pre-deployment testing, and incident handling for AI systems.
- `[R2]` adds AI/GenAI-specific secure development expectations.
