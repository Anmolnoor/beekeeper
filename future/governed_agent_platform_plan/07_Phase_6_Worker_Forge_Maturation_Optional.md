# Phase 6 — Worker Forge Maturation (Optional, Only After Phases 0–5)

## Goal

Turn “worker forge” from an interesting experimental path into a governed platform capability with evidence behind it.

This phase is deliberately **last**.

---

## Why this phase is last

The critique is right: the hard problem is not generating a file. The hard problem is proving that a generated worker is:

- correct
- safe
- maintainable
- observable
- worth the complexity
- governable over time
- not just plugin sprawl

Do not productize worker forge until the base platform has durable state, policy enforcement, sandboxing, tests, and versioned releases.

---

## New product language rule

Until this phase is complete, describe the feature as:

- **experimental worker generation**
- **generated worker prototype**
- **dynamic worker path (experimental)**

Do **not** describe it as a mature platform pillar.

---

## Promotion pipeline for generated workers

A generated worker may be promoted only if it passes all of these gates:

### Gate 1 — Structured specification
The generator must emit:
- purpose
- inputs
- outputs
- allowed tools
- required secrets
- network needs
- sandbox tier
- risk tier
- rollback strategy

### Gate 2 — Static verification
- linting
- type checks
- dependency policy check
- secret-use check
- banned import / syscall / network rule checks

### Gate 3 — Contract tests
- input/output schema tests
- failure mode tests
- idempotency tests
- policy enforcement tests

### Gate 4 — Sandbox assignment
No generated worker runs without an explicit sandbox tier, capability manifest, and secret scope.

### Gate 5 — Benchmark against generic fallback
A generated worker must prove one of:
- materially better latency
- materially lower cost
- materially simpler repeated operator path
- materially better domain fit

If it cannot show value against a generic worker/tool composition path, do not keep it.

### Gate 6 — Provenance and signing
The generated artifact must carry:
- generator version
- template version
- source prompt/spec hash
- policy version
- build identity
- signature or attestation reference

### Gate 7 — Controlled rollout
- canary or limited deployment
- observability in place
- rollback path available
- expiration/review date set

---

## Runtime rules for generated workers

- default to strongest reasonable sandbox tier
- no broad filesystem access
- no broad egress
- no direct production secrets
- no self-registration into the platform without approval
- no silent plugin reload into hot path
- no production rollout without version pinning

---

## Governance requirements

Every generated worker must have:

- owner
- review cadence
- deprecation path
- capability manifest
- policy mapping
- test report
- benchmark result
- operator runbook entry

Generated code without an owner is already debt.

---

## Keep the generic path alive

Do **not** let worker forge replace the generic safe path.

Maintain:

- a generic worker runtime
- generic tool broker integration
- a generic orchestrated step model

That way, generated workers remain optional optimizations, not mandatory architecture.

---

## Definition of done

Phase 6 is complete when all of the following are true:

- generated workers pass the promotion pipeline
- generated workers are versioned, testable, observable, and sandboxed
- there is evidence they improve at least one important dimension over the generic path
- rollout and rollback are routine
- product language around worker forge matches actual evidence

---

## Success metrics

- percentage of generated workers with signed provenance
- percentage of generated workers with contract tests
- rollback success for generated worker deployments
- percentage of generated workers outperforming generic path on agreed metric
- number of orphaned generated workers (target: zero)

---

## Risks and how to handle them

### Risk: worker forge creates plugin sprawl
Mitigation: require ownership, expiration, and benchmark justification.

### Risk: generated code hides dangerous capabilities
Mitigation: manifests, static analysis, sandboxing, policy checks.

### Risk: keeping forge experimental frustrates stakeholders
Mitigation: the alternative is overselling immature automation. Credibility matters more.

---

## Mapping to the critique

This phase directly addresses:

- **4E** the worker forge story is ahead of the proof

It also strengthens:

- security
- release safety
- maintainability
- trust in platform claims

---

## Research basis

Primary references: `[R2]`, `[R4]`, `[R7]`, `[R10]`, `[R11]`, `[R13]`

Why these matter here:

- `[R2]` and `[R4]` support AI-specific secure development, provenance, testing, and incident thinking.
- `[R7]` supports versioning and safe rollout of worker code.
- `[R10]` and `[R11]` support isolation for generated or untrusted workloads.
- `[R13]` supports build/provenance maturity thinking.
