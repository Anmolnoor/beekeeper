# Phase 0 — Baseline, Truth, and Focus

## Goal

Create an **honest baseline** for the project before any heavy refactor. This phase reduces confusion, cuts unsupported paths, and makes later work cheaper.

This phase directly fixes the “too optimistic about maturity” problem.

---

## Why this phase is first

Right now the project appears to have:

- too many backends for its proof level
- unclear separation between dev-only and production-worthy paths
- security-sensitive defaults that are too permissive
- a test/bootstrap story that is harder than the docs imply
- claims that run ahead of verified operational evidence

If you do not fix that first, every later phase will keep inheriting ambiguity.

---

## Scope

### In scope

1. **Current-state inventory**
   - every filesystem write
   - every env var and secret
   - every scheduler/backend path
   - every channel ingress/egress path
   - every place the process keeps state in memory
   - every place a webhook or external action can replay or duplicate

2. **Reference-stack decision**
   - declare the single supported production path
   - mark everything else experimental or dev-only

3. **Runtime mode cleanup**
   - `dev`, `internal`, and `prod` modes with different enforcement
   - fail-closed config validation in non-dev modes

4. **Bootstrap and test entrypoint**
   - clean-clone bootstrap
   - smoke test command
   - dependency sanity check
   - environment doctor command

5. **Documentation honesty**
   - README language
   - support matrix
   - maturity table
   - risk register

### Out of scope

- major domain refactors
- storage migration
- worker isolation
- policy engine replacement

Those come later.

---

## The concrete decisions to make in Phase 0

## Decision 1 — Choose the production path

Recommended decision:

- **Scheduler / durable execution:** Temporal
- **Authoritative metadata:** Postgres
- **Artifacts:** S3-compatible object storage
- **Policy:** OPA
- **Observability:** OpenTelemetry
- **Secrets:** secret manager
- **Supported channel:** Slack only
- **Primary LLM path:** one provider only
- **Dev-only local adapter:** inline/local mode, but never presented as production-equal

Anything else remains behind a feature flag and is documented as experimental.

## Decision 2 — Re-scope Honeycomb

Recommended position:

- keep Honeycomb **only as a developer-friendly audit/event adapter**
- do **not** present it as the complete data plane
- do **not** use it as the authoritative source of truth in production

Practical meaning:

- JSONL / filesystem append-only logging remains acceptable for local development and trace inspection
- mutable config blobs, review updates, retention moves, and store documents are treated as ordinary state, not “append-only ledger” state

## Decision 3 — Make production start fail closed

In non-dev modes, startup must fail if any of these are missing or invalid:

- JWT secret
- audit signing key
- channel encryption key
- webhook secrets
- database DSN
- object storage config
- Temporal connection / namespace config
- secret manager config

---

## Repository changes to make in this phase

Suggested additions:

```text
docs/
  architecture/
    current-state.md
    trust-boundaries.md
    storage-classification.md
  support-matrix.md
  maturity-model.md
  risks-and-known-gaps.md

scripts/
  bootstrap_dev.sh
  doctor.py
  smoke_test.sh

app/
  config/
    settings.py
    validators.py
```

Suggested output documents:

- `current-state.md` — system map as it is now
- `storage-classification.md` — every path tagged as state / artifact / cache / temp / config / log
- `support-matrix.md` — supported vs experimental
- `maturity-model.md` — prototype / internal / production gates
- `risks-and-known-gaps.md` — explicit known weaknesses

---

## Work items, in order

1. **Inventory all writes**
   - grep file writes, JSON writes, JSONL writes, temp folder creation, moves/renames
   - classify each one as state, artifact, cache, temp, config, or log

2. **Inventory all backends**
   - schedulers
   - vector stores
   - channels
   - LLM providers
   - secret sources
   - persistence layers

3. **Mark each path**
   - supported for production
   - supported for internal only
   - dev only
   - experimental
   - deprecated

4. **Add strict config validator**
   - one validator module
   - per-mode checks
   - startup banner that clearly states mode and supported guarantees

5. **Add `doctor` command**
   - checks Python version
   - checks required packages/imports
   - checks env vars
   - checks DB/object store/Temporal reachability
   - explains what is missing

6. **Add `smoke_test` command**
   - boot app
   - create dummy run
   - persist a record
   - enqueue a no-op task
   - read the result
   - exit non-zero on failure

7. **Rewrite README / status language**
   - replace broad claims with precise maturity labels
   - add supported-path matrix
   - add “not yet hardened” section

---

## Definition of done

Phase 0 is complete when all of the following are true:

- a clean clone can be bootstrapped using one command
- test collection runs without hidden environment assumptions
- the project has a public support matrix
- prod mode fails closed on missing secrets
- a single production architecture path is explicitly named
- Honeycomb is documented honestly
- docs no longer imply battle-tested maturity without evidence

---

## Success metrics

- `make doctor` or equivalent passes in a clean container
- `make smoke-test` or equivalent passes from a clean setup
- **zero** dev-default secrets allowed in prod mode
- supported backends count is reduced to the reference path
- README claims are traceable to actual tests or dashboards

---

## Risks and how to handle them

### Risk: cutting feature breadth upsets current users
Mitigation: mark features experimental before removing them.

### Risk: bootstrap reveals hidden assumptions
Mitigation: that is the point; fix them now rather than after deeper refactors.

### Risk: “one production path” feels restrictive
Mitigation: it is intentionally restrictive. Breadth is the current tax on maturity.

---

## Mapping to the critique

This phase primarily addresses:

- weak / overstated claims
- loose security defaults
- test/bootstrap friction
- too many backends without enough proof
- need to narrow claims
- need to choose one production path

See the verification matrix for exact row coverage.

---

## Research basis

Primary references: `[R1]`, `[R2]`, `[R3]`, `[R4]`, `[R7]`, `[R12]`, `[R13]`, `[R14]`

Why these matter here:

- `[R1]` and `[R2]` provide an outcome-based way to turn vague security maturity claims into concrete practices.
- `[R3]` and `[R4]` reinforce that AI risk management must be tied to governance, testing, provenance, and incident handling rather than product language alone.
- `[R7]` shows that production durability must be demonstrated, not assumed.
- `[R12]` and `[R13]` help define release/security gates instead of vibes.
- `[R14]` supports making testing and fast feedback first-class.
