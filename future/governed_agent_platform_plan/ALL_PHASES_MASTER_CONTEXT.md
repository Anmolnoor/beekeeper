# Governed-Agent Platform Master Context

Generated: 2026-03-07T02:41:00Z

This file consolidates roadmap + all phase documents for fresh-context execution.


---

## Source: 00_README_Roadmap.md

# Governed-Agent Platform Hardening Roadmap

## Purpose

This roadmap fixes the three structural problems identified in the critique:

1. **Too centralized** — `queen.py` behaves like a god object and `runner.py` is carrying too much glue.
2. **Too filesystem-dependent** — the current storage approach is useful for development but too weak for concurrency, durability, queryability, and multi-instance operation.
3. **Too optimistic about maturity** — governance, tenancy, security, channels, observability, and tests are directionally good but not yet deep enough to justify strong production claims.

The plan is intentionally sequenced so the project becomes **simpler, safer, and easier to operate**, not just bigger.

---

## The simple target state

Build toward a platform with four explicit layers:

- **Control plane**  
  orgs / hives / queens / users, auth, admission, approvals, policy evaluation, run registry, scheduling decisions
- **Execution plane**  
  workers, tool execution, LLM calls, channel delivery, retries, heartbeats
- **Data plane**  
  Postgres for metadata, object storage for artifacts, append-only audit/event log, Qdrant only when retrieval is truly needed
- **Governance plane**  
  policy engine, approval rules, capability manifests, secret scopes, audit evidence

---

## Recommended reference stack

This is the **single production path** the roadmap assumes. Everything else should be downgraded to experimental until proven.

| Concern | Recommended production default | Notes |
|---|---|---|
| Metadata / authoritative state | **Postgres** | run state, steps, tasks, approvals, policy decisions, leases, channel sessions |
| Durable workflow / queue | **Temporal** | production path only; inline scheduler remains local-dev only |
| Artifacts / large payloads | **S3-compatible object storage** | MinIO in dev, S3-compatible in production |
| Policy engine | **OPA / Rego** | externalize policy decisions from orchestration code |
| Observability | **OpenTelemetry** | traces, metrics, logs, context propagation |
| Secrets | **Secret manager** | cloud secret manager or Vault; no dev defaults in prod |
| Worker isolation | **Containers + rootless + read-only FS** as baseline; **gVisor** for semi-trusted; **Firecracker** for generated / untrusted | isolation level depends on trust tier |
| Retrieval | **Qdrant only when needed** | do not make vector storage mandatory for the whole platform |
| Channels | **Slack first** | all other channels experimental until Slack is deep and reliable |
| LLM provider path | **One primary provider** | one default path, optional fallback later, no multi-provider sprawl now |

---

## Non-negotiable platform rules

1. **Local disk is never the source of truth.**
2. **No long-running work happens inside the API / control process.**
3. **Every run, task, approval, tool call, and artifact has a durable record.**
4. **Every sensitive external action is policy-mediated.**
5. **Every retryable action is idempotent or explicitly fenced.**
6. **Every claim about maturity must be backed by an acceptance test, a dashboard, or a drill.**

---

## Phase sequence

### Phase 0 — Baseline, truth, focus
Create an honest baseline, choose one production path, classify current storage and backends, fail closed on security defaults, and make a clean clone/test/bootstrap story.

### Phase 1 — Split the Queen and shrink the Runner
Turn `queen.py` into a thin coordinator and move its responsibilities into explicit services. Break `runner.py` into a real CLI package.

### Phase 2 — Durable state and control/execution separation
Move authoritative state to Postgres, move artifacts to object storage, keep Honeycomb only as a dev-friendly audit/event adapter, and push execution into workers.

### Phase 3 — Real governance, security, and sandboxing
Replace lightweight guardrails with policy-as-code, capability manifests, approval state machines, secret scoping, webhook replay defense, and worker isolation tiers.

### Phase 4 — Operability, observability, testing, and release discipline
Add OpenTelemetry, dashboards, failure drills, clean bootstrap, end-to-end tests, worker deployment discipline, and release gates.

### Phase 5 — Real tenancy, deep channels, and product focus
Move from logical tenancy to enforceable tenancy controls, make one channel excellent, add quotas/rate limits/admin operations, and narrow public claims.

### Phase 6 — Worker Forge maturation (optional, only after Phases 0–5)
Treat generated workers as a governed product capability only after they pass a promotion pipeline with tests, signatures, sandboxing, and rollout controls.

---

## End-state architecture (text diagram)

```text
Client / Channel / CLI
        |
        v
+-----------------------------+
| Control Plane               |
| - API / admission           |
| - org/hive/queen/user auth  |
| - run registry              |
| - planner coordinator       |
| - approval coordinator      |
| - policy adapter            |
+-----------------------------+
        |
        v
+-----------------------------+
| Temporal / durable queue    |
+-----------------------------+
        |
        v
+-----------------------------+
| Execution Plane             |
| - worker runtime            |
| - tool broker               |
| - LLM / channel adapters    |
| - sandbox profiles          |
+-----------------------------+
        |
        +------> Object storage (artifacts, prompts, logs, traces)
        +------> Secret manager (scoped credentials)
        +------> External APIs / channels / tools

Shared durable services
- Postgres
- Append-only audit/event tables + archive
- OpenTelemetry collector / metrics / logs / traces
- Optional Qdrant
```

---

## What gets explicitly downgraded

Until later phases are complete, the following should be labeled **experimental** or **dev-only**:

- inline scheduler in any serious environment
- multiple production schedulers
- multiple production channel stacks
- generated worker forge
- filesystem-backed authoritative state
- broad multi-provider support as a selling point
- “serious multi-tenancy” language
- “battle-tested” or “production-ready” wording

---

## Exit gates by phase

| Phase | Do not proceed unless… |
|---|---|
| 0 | supported production path is declared; secrets fail closed in prod; bootstrap works from clean environment |
| 1 | `queen.py` is a coordinator, not a god object; CLI commands are modular |
| 2 | authoritative state survives restart; workers run outside control process |
| 3 | sensitive actions cannot bypass policy; replay/idempotency protections exist |
| 4 | one golden path, one approval path, one failure/retry path, and one restore drill are automated |
| 5 | tenancy controls, quotas, channel semantics, and operator views exist for the supported path |
| 6 | generated workers pass the same safety/release bar as hand-written workers |

---

## How to use these files

- Read `01_Phase_0_Baseline_Truth_and_Focus.md` first.
- Then execute phases in order.
- Use `08_Verification_Matrix_Against_Points_4_5_6.md` to verify the roadmap against the critique.
- Use `09_Research_Basis.md` to see the standards, papers, and official docs that informed the design.

---

## Research basis IDs used in the phase files

- `[R1]` NIST SP 800-218 SSDF 1.1
- `[R2]` NIST SP 800-218A SSDF Community Profile for Generative AI / dual-use foundation models
- `[R3]` NIST AI RMF 1.0
- `[R4]` NIST AI RMF Generative AI Profile
- `[R5]` OPA / Rego policy-as-code
- `[R6]` Zanzibar authorization model
- `[R7]` Temporal durable execution / task queues / workers / versioning / prod checklist
- `[R8]` Azure architecture guidance for event sourcing / outbox / web-queue-worker
- `[R9]` OpenTelemetry signals / traces / context propagation
- `[R10]` gVisor sandboxing
- `[R11]` Firecracker microVM isolation
- `[R12]` OWASP secrets, logging, microservices security, ASVS
- `[R13]` SLSA supply-chain levels
- `[R14]` Google continuous testing research


---

## Source: 01_Phase_0_Baseline_Truth_and_Focus.md

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


---

## Source: 02_Phase_1_Split_Queen_and_Runner.md

# Phase 1 — Split the Queen and Shrink the Runner

## Goal

Turn `queen.py` from a god object into a **thin coordinator**, and turn `runner.py` from a large script into a **real CLI package**.

This phase primarily fixes the over-centralization problem.

---

## Why this phase matters

`queen.py` currently appears to combine too many responsibilities:

- orchestration
- routing
- decomposition
- scheduler selection
- action registry
- tool runtime integration
- worker forge behavior
- context loading
- profile resolution
- monitor interaction
- plugin reload logic

That makes it difficult to:

- reason about behavior
- test logic in isolation
- change one concern without touching the others
- define clear control-plane boundaries

Likewise, a `runner.py` that has grown into ~2000+ lines usually means the CLI layer is doing much more than presentation and command dispatch.

---

## The design rule for this phase

**Queen coordinates. Services decide. Workers execute.**

---

## Target module layout

Suggested layout for the refactor:

```text
app/
  domain/
    models.py
    events.py
    state_machines.py
    errors.py

  control_plane/
    queen_coordinator.py
    planner_service.py
    routing_service.py
    dispatch_service.py
    policy_adapter.py
    approval_service.py
    context_service.py
    profile_service.py
    response_aggregation_service.py

  execution_plane/
    worker_runtime.py
    step_handlers/
    tool_broker_client.py

  adapters/
    schedulers/
    storage/
    channels/
    llm/
    monitoring/

  cli/
    main.py
    commands/
      run.py
      admin.py
      audit.py
      channels.py
      workers.py
      doctor.py
```

### Transitional recommendation

Keep the old files temporarily as shims:

- `queen.py` imports and delegates to `queen_coordinator.py`
- `runner.py` imports and delegates to `cli/main.py`

That allows gradual migration without breaking imports immediately.

---

## Service responsibilities

## Queen Coordinator
Owns only:

- request admission into the orchestration flow
- high-level phase transitions
- delegation to services
- construction of the run context
- correlation IDs

Does **not** own:

- storage internals
- policy logic
- scheduling implementation
- worker generation internals
- channel formatting
- monitoring side effects

## Planner Service
Owns:

- plan generation
- task decomposition
- planning metadata
- frozen plan snapshots for approvals

## Routing Service
Owns:

- step routing decisions
- queue / task-queue selection
- selection among execution profiles

## Dispatch Service
Owns:

- dispatch commands
- idempotent submit semantics
- lease / retry metadata

## Policy Adapter
Owns:

- packaging policy inputs
- asking the policy engine for a decision
- mapping decision outputs into platform actions

## Context Service
Owns:

- context loading
- retrieval hooks
- run-scoped context shaping

## Profile Service
Owns:

- resolution of agent / queen / user / tenant configuration
- profile inheritance and overrides

## Response Aggregation Service
Owns:

- collecting step outputs
- building user-facing outputs
- assembling final response bundles

## CLI package
Owns only:

- parsing arguments
- loading config
- calling application services
- formatting output for terminal or JSON

---

## Work items, in order

1. **Create domain objects**
   - `RunRequest`
   - `Plan`
   - `PlanStep`
   - `DispatchCommand`
   - `ExecutionResult`
   - `PolicyInput`
   - `PolicyDecision`

2. **Extract interfaces / ports**
   - scheduler port
   - storage port
   - policy port
   - tool runtime port
   - channel port
   - monitor port

3. **Move logic out of Queen**
   - one responsibility at a time
   - keep Queen as orchestrating shell

4. **Move CLI commands into package**
   - split operational/admin commands from run commands
   - remove business logic from CLI layer

5. **Create tests per service**
   - planner tests
   - routing tests
   - dispatch tests
   - context/profile tests
   - response aggregation tests

6. **Measure complexity**
   - line count
   - import fan-in/fan-out
   - module-level testability

---

## Practical extraction order

Recommended order to keep risk low:

1. `profile_service`
2. `context_service`
3. `response_aggregation_service`
4. `dispatch_service`
5. `routing_service`
6. `planner_service`
7. `policy_adapter`
8. worker forge service extraction
9. monitor/plugin reload extraction
10. CLI split

Reason: start with lower-coupling concerns before cutting core orchestration paths.

---

## Definition of done

Phase 1 is complete when all of the following are true:

- `queen.py` is a thin adapter or coordinator
- core orchestration decisions live in named services
- `runner.py` is replaced by a CLI package
- each extracted service has direct unit tests
- scheduler selection, policy checks, and context loading can be tested without spinning up the whole app
- new features no longer require editing Queen first

---

## Success metrics

- `queen.py` reduced to coordinator size
- CLI split into command modules
- service-level unit tests cover extracted logic
- import graph shows clearer boundaries
- lower regression rate when changing one concern

---

## Risks and how to handle them

### Risk: extracting too much at once
Mitigation: use adapter shims and one service at a time.

### Risk: hidden coupling between Queen and storage/tooling
Mitigation: add ports first, then move implementations.

### Risk: plugin reload or monitor code has implicit side effects
Mitigation: isolate and wrap them before moving.

---

## Mapping to the critique

This phase directly addresses:

- **4A** architecture is over-centralized
- **4B** `runner.py` is too large
- **6 Priority 1** split the Queen

It also prepares for:

- **5 Gap 1** clean control-plane / execution-plane separation

---

## Research basis

Primary references: `[R5]`, `[R7]`, `[R8]`, `[R14]`

Why these matter here:

- `[R5]` supports decoupling policy decisions from the orchestrator.
- `[R7]` shows the value of keeping orchestration separate from worker execution.
- `[R8]` supports explicit service boundaries and queue-mediated work.
- `[R14]` supports smaller, testable units that improve feedback and change safety.


---

## Source: 03_Phase_2_Durable_State_and_Execution_Plane.md

# Phase 2 — Durable State and Clean Control/Execution Separation

## Goal

Replace implicit filesystem state with durable, queryable platform storage and move long-running execution into workers.

This phase fixes the “filesystem-dependent” problem and creates the real separation between control plane and execution plane.

---

## The core principle

**Artifacts are not state. Logs are not queues. Folders are not databases.**

---

## What changes in this phase

### Before
- local disk acts as state store, artifact store, trace store, and sometimes coordination mechanism
- control and execution concerns are mixed
- “append-only” is true in spirit for some areas, but not a strict system guarantee
- multi-process and multi-instance behavior is fragile

### After
- Postgres stores authoritative metadata and state transitions
- object storage stores large artifacts and bundles
- Temporal stores durable workflow/task orchestration state
- workers execute outside the control-plane process
- Honeycomb remains only as a dev-friendly append-only audit/event adapter

---

## Storage tier design

| Concern | Dev mode | Production mode | Notes |
|---|---|---|---|
| Run / task / approval / policy metadata | Postgres local container | Postgres | authoritative source of truth |
| Workflow execution / queueing | Temporal local | Temporal | one production path only |
| Artifacts / large outputs / prompt bundles | MinIO or local object adapter | S3-compatible object storage | store blobs, not business state |
| Audit / event history | append-only table + optional JSONL dev mirror | append-only table + archive to object storage | replay and audit evidence |
| Vector memory | optional Qdrant | optional Qdrant | only when retrieval is truly required |
| Local filesystem | temp/scratch only | temp/scratch only | deleteable, non-authoritative |

---

## Re-scope Honeycomb explicitly

Recommended new statement:

> Honeycomb is the project’s **developer-friendly audit/event adapter**, not the platform’s universal production data plane.

### Allowed Honeycomb usage
- append-only local JSONL traces in development
- human-readable run timelines for debugging
- export / archive of events for offline inspection

### Disallowed Honeycomb usage
- authoritative workflow state in production
- approval state
- mutable tenant configuration
- any data that must survive multi-instance concurrency safely
- anything that requires transactional guarantees

---

## Data model to introduce

Minimum durable entities:

| Entity | Purpose |
|---|---|
| `organizations` | tenant root |
| `hives` | workspace / environment namespace |
| `queens` | orchestrator profile/config entity |
| `users` | principals |
| `runs` | top-level execution records |
| `run_steps` | plan steps attached to a run |
| `tasks` | executable units sent to workers |
| `task_leases` | claim / heartbeat / timeout tracking |
| `approvals` | HITL state machine records |
| `policy_decisions` | allow / deny / escalate results |
| `tool_calls` | auditable external actions |
| `artifacts` | metadata and provenance for blobs |
| `audit_events` | append-only event records |
| `channel_sessions` | normalized channel/thread/session state |
| `secret_refs` | references to secrets, never raw values |

---

## Required state machines

### Run state machine
`requested -> admitted -> planning -> waiting_approval -> queued -> running -> succeeded | failed | cancelled | expired`

### Task state machine
`created -> queued -> leased -> running -> succeeded | failed | retry_scheduled | dead_lettered`

### Approval state machine
`not_required -> pending -> approved | denied | expired | superseded`

### Tool call state machine
`prepared -> policy_checked -> executing -> succeeded | failed | compensating | blocked`

---

## Control plane vs execution plane

## Control plane responsibilities
- admission
- run registry
- plan persistence
- approval coordination
- policy evaluation requests
- queueing work
- publishing events
- operator visibility

## Execution plane responsibilities
- polling / receiving work
- claiming tasks
- creating scratch space
- loading inputs and artifacts
- calling tools / LLMs
- heartbeats
- writing results and artifacts
- reporting completion/failure

The control plane must **never** execute long-running tasks in-process.

---

## Recommended workflow path

### Production
- one Temporal namespace per environment or tenancy strategy
- distinct task queues per workload category
- workers run outside the API/control-plane process
- version workers deliberately

### Development
- use Temporal local for realistic behavior
- keep inline mode only as a thin dev shortcut
- do not use inline mode to justify production maturity claims

---

## Required implementation patterns

## Pattern 1 — Repository layer
No application code writes directly to storage implementations. Everything goes through repositories or storage services.

## Pattern 2 — Outbox
When state changes and an event/message must also be emitted, write both in a reliable, coordinated way. Use an outbox table or equivalent pattern.

## Pattern 3 — Idempotency
Every retryable side effect must have a stable idempotency key.

## Pattern 4 — Artifact manifests
Every blob written to object storage gets:
- checksum
- content type
- logical producer
- run/task provenance
- retention class

---

## Suggested repository layout

```text
app/
  data_plane/
    repositories/
      runs.py
      tasks.py
      approvals.py
      policy_decisions.py
      artifacts.py
      channel_sessions.py
      audit_events.py
    storage/
      postgres/
      object_store/
      temporal/
      honeycomb_dev/
```

---

## Migration path

Do this as a strangler migration, not a rewrite.

1. wrap current file access behind interfaces
2. dual-write new state to Postgres and artifacts to object storage
3. preserve legacy reads temporarily
4. cut reads over after parity checks
5. remove direct filesystem state writes
6. leave Honeycomb as dev-only audit adapter

---

## Definition of done

Phase 2 is complete when all of the following are true:

- killing the API/control-plane process does not lose authoritative run state
- workers continue independently of API process lifetime
- filesystem folders are no longer the source of truth for runs/tasks/approvals
- artifacts and state are stored separately
- the platform can reconstruct a run timeline from durable records
- Honeycomb is no longer described as the whole production data plane

---

## Success metrics

- percentage of authoritative state off local disk
- restart-resume success rate for in-flight runs
- duplicate side-effect rate after retries
- mean query time for run/task/operator views
- successful replay of audit/event history for a run

---

## Risks and how to handle them

### Risk: dual-write bugs during migration
Mitigation: compare old/new records and add parity checks before cutover.

### Risk: trying to support many schedulers at once
Mitigation: Temporal only for production. Everything else is dev-only or deprecated.

### Risk: “append-only” language becomes politically sticky
Mitigation: keep the useful part — append-only audit events — but stop forcing all persistence into that story.

---

## Mapping to the critique

This phase directly addresses:

- **4C** persistence model is elegant conceptually, weak operationally
- **5 Gap 1** no clean separation between control plane and execution plane
- **6 Priority 2** make the storage story honest and layered

It also materially helps:

- centralization
- concurrency
- recovery
- operator visibility

---

## Research basis

Primary references: `[R7]`, `[R8]`, `[R9]`, `[R12]`

Why these matter here:

- `[R7]` supports task queues, external workers, durable execution, versioned worker deployments, and production readiness.
- `[R8]` supports event sourcing tradeoffs, transactional outbox, and web-queue-worker separation.
- `[R9]` helps preserve end-to-end visibility as work crosses service/worker boundaries.
- `[R12]` reinforces audit logging and structured event design.


---

## Source: 04_Phase_3_Security_Policy_and_Sandboxing.md

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


---

## Source: 05_Phase_4_Operability_Testing_and_Release.md

# Phase 4 — Operability, Observability, Testing, and Release Discipline

## Goal

Turn the platform from something developers can demo into something operators can understand, monitor, test, and release safely.

This phase fixes the “trace logging is not full operability” and “tests are weaker than the docs imply” problems.

---

## Why this phase matters

A governed platform that cannot answer these questions is still immature:

- What is the current state of a run?
- Why is a run blocked?
- Which worker last touched it?
- Was a policy decision involved?
- Did a webhook replay?
- Which artifact version was produced?
- Can we resume after a crash?
- Can a clean clone run the tests?
- Can we restore the system from backup?

This phase makes those questions answerable.

---

## Observability design

Recommended baseline: **OpenTelemetry everywhere**.

### Correlation model
Every request, run, task, tool call, approval, artifact write, channel delivery, and webhook event should carry:

- trace ID
- span ID
- run ID
- task ID
- org / hive
- queen ID
- worker build/version
- policy version

### Minimum telemetry types
- traces
- metrics
- logs
- baggage / contextual metadata for cross-boundary correlation

---

## Dashboards to build

### 1. Run operations dashboard
- runs by state
- stuck runs
- average time in each phase
- blocked approvals
- failure reasons

### 2. Worker dashboard
- active workers
- queue depth / backlog
- lease timeouts
- retry rates
- saturation / concurrency

### 3. Governance dashboard
- policy allows / denies / escalations
- approval backlog
- high-risk action attempts
- webhook verification failures
- sandbox tier usage

### 4. Channel dashboard
- inbound events by provider
- signature failures
- dedupe hits
- send failures
- retry backlog

### 5. Tenancy dashboard
- runs per org / hive
- spend / token use
- quota pressure
- rate-limit hits
- hot tenants

---

## Operator views to support

An operator should be able to open a run and immediately see:

- current state
- state timeline
- last heartbeat
- owning task queue
- assigned worker version
- pending approval reason
- recent tool calls
- linked artifacts
- policy decisions
- failure or retry history

This is the minimum bar for a serious operator console.

---

## Testing model

### Test pyramid

#### Unit tests
- domain models
- state machines
- planner logic
- policy input/output translation
- artifact manifest rules

#### Integration tests
- Postgres repositories
- Temporal integration
- object storage
- secret manager adapter
- policy adapter
- channel adapter ingress verification

#### Contract tests
- API schemas
- worker/task payload schemas
- policy decision contract
- channel normalized event contract

#### End-to-end tests
At minimum automate these four:

1. **Golden path**
   - create run
   - plan
   - queue
   - execute
   - store artifact
   - return result

2. **Approval path**
   - high-risk step pauses
   - approval recorded
   - run resumes

3. **Channel path**
   - inbound verified event
   - deduped correctly
   - response delivered

4. **Failure / retry path**
   - worker crash or timeout
   - task reprocessed safely
   - idempotency preserved

#### Recovery drills
- API restart during active work
- worker death mid-task
- DB restore validation
- object storage restore validation

---

## Clean bootstrap requirement

A clean environment must be able to do all of this:

1. install dependencies
2. start local dependencies
3. run test collection
4. run smoke tests
5. run at least one end-to-end path

This should be scripted, not tribal knowledge.

---

## Release discipline

### Required release gates
- test collection passes in clean environment
- unit/integration/e2e required suites pass
- migrations apply cleanly
- worker build/version is tracked
- configuration validation passes
- provenance/build evidence is generated
- restore drill has not regressed

### Worker deployment discipline
Because workers are long-running services, they need:
- explicit versioning
- controlled rollout
- rollback plan
- safe handling of in-flight executions

### Recommended deployment practice
Use worker versioning and gradual rollout for breaking workflow changes.

---

## Suggested repo additions

```text
tests/
  unit/
  integration/
  contract/
  e2e/
  recovery/

ops/
  dashboards/
  alerts/
  runbooks/
  restore_drills/

scripts/
  bootstrap_dev.sh
  run_e2e.sh
  run_recovery_drill.sh
```

---

## Definition of done

Phase 4 is complete when all of the following are true:

- traces, metrics, and logs correlate across API, control plane, workers, and channels
- operators can inspect a run end-to-end
- one golden path, one approval path, one channel path, and one failure/retry path are automated
- a clean clone can run smoke tests and collect tests successfully
- there is a repeatable restore drill
- release gates are documented and enforced

---

## Success metrics

- time to diagnose failed run
- percentage of failed runs with enough telemetry to explain them
- test success rate from clean environment
- restore drill success rate
- queue lag and worker saturation visibility
- approval backlog visibility

---

## Risks and how to handle them

### Risk: too much logging without structure
Mitigation: use correlation IDs and structured logs; define event schemas.

### Risk: tracing only the happy path
Mitigation: instrument approvals, retries, timeouts, and webhook rejections too.

### Risk: docs claim “all tests pass” but environment is fragile
Mitigation: test in a clean container in CI and make that the truth source.

---

## Mapping to the critique

This phase directly addresses:

- **4I** test story is weaker than the docs imply
- **5 Gap 4** observability is trace logging, not full operability
- **5 Gap 5** UI/admin layer is behind platform claims
- **6 Priority 6** add real end-to-end tests

It also strengthens:

- run supportability
- safe release practice
- evidence-backed maturity

---

## Research basis

Primary references: `[R1]`, `[R7]`, `[R9]`, `[R12]`, `[R13]`, `[R14]`

Why these matter here:

- `[R7]` supports monitoring, worker deployment strategy, production checklists, and versioning.
- `[R9]` supports unified traces/metrics/logs with context propagation.
- `[R12]` supports security-relevant logging and correlation IDs.
- `[R1]` and `[R13]` support release/security gates and evidence-based maturity.
- `[R14]` reinforces the importance of fast, practical, scalable test feedback.


---

## Source: 06_Phase_5_Tenancy_Channels_and_Product_Focus.md

# Phase 5 — Real Tenancy, Deep Channels, and Product Focus

## Goal

Move from a good logical model to a safer operational model for tenancy, narrow the product surface area, and make one channel deeply reliable before broadening again.

This phase fixes the “logical tenancy”, “channel breadth over depth”, and “too many backends” problems.

---

## Why this phase matters

The current structure for orgs / hives / queens / users is a good control-plane concept, but that is not the same as serious multi-tenancy. Likewise, supporting many channels superficially is not the same as having a reliable messaging layer.

The platform becomes more credible if it chooses less and does it well.

---

## Supported tenancy model

Suggested semantic model:

| Entity | Meaning |
|---|---|
| `organization` | billing, policy, and quota root |
| `hive` | workspace / environment namespace under an organization |
| `queen` | orchestration profile / agent configuration entity |
| `user` | human or service principal |
| `run` | execution instance inside a queen/hive context |

### Tenancy guarantees to implement
- tenant-scoped secret access
- tenant-scoped quotas
- tenant-scoped rate limits
- tenant-filtered observability
- tenant-aware policy inputs
- tenant-aware artifact access checks
- tenant-aware search/filtering in operator views

### What this phase does **not** claim yet
- full hard isolation between all tenants at the infrastructure level
- separate cryptographic hardware roots per tenant
- independent per-tenant clusters by default

Those can come later for high-assurance environments.

---

## Practical tenancy controls

### Quotas
Add configurable quotas for:
- concurrent runs
- daily spend
- token budget
- artifact storage
- channel send rate
- webhook ingest rate

### Secret scoping
Secrets are scoped at least by:
- environment
- organization
- hive
- capability manifest

### Audit scoping
Operators can filter by organization / hive / queen / run.

### Rate limiting
Implement tenant-aware limits on:
- API submission
- channel ingress
- outbound channel sends
- worker creation if relevant

---

## Channel strategy

### Recommended focus order
1. **Slack** — supported and deep
2. everything else — experimental until Slack is reliable and fully instrumented

If a second channel is truly needed, add it only after the Slack adapter meets all exit criteria.

### Channel contract to standardize

| Concern | Requirement |
|---|---|
| Inbound verification | signature / token check, timestamp validation if supported, replay defense, dedupe |
| Normalization | map provider event into one normalized internal event schema |
| Conversation identity | workspace, channel, thread, message, external user IDs |
| Delivery | retries, dead-letter handling, idempotent send semantics |
| State | durable session/thread state in DB, not memory |
| Observability | provider event ID, correlation IDs, latency, retries, failures |
| Capability matrix | explicitly list attachments, threads, buttons, slash commands, edits, etc. |

### Do not do this
- do not rely on channel-specific behavior scattered throughout Queen
- do not let channels bypass policy checks
- do not call shallow channel support “battle-tested”

---

## Product focus rules

### Rule 1 — One production scheduler
Temporal only.

### Rule 2 — One supported channel
Slack only, until proven otherwise.

### Rule 3 — One supported storage architecture
Postgres + object storage + audit/event tables.

### Rule 4 — One primary LLM path
One provider only as the default path.

### Rule 5 — Explicit experimental label
Any extra backend/channel/provider must be labeled experimental and excluded from the production readiness claim.

---

## Admin / operator console requirements

By the end of this phase, the console should support:

- tenant filtering
- run timeline
- approval queue
- policy decision inspection
- artifact list
- channel delivery inspection
- quota / budget view
- health and alert summaries

This is where the UI stops being only a prototype surface and becomes an operations tool.

---

## Suggested repo additions

```text
app/
  tenancy/
    quotas.py
    rate_limits.py
    tenancy_context.py
    secret_scopes.py

  channels/
    normalized_events.py
    slack/
      ingress.py
      egress.py
      capabilities.py
```

---

## Definition of done

Phase 5 is complete when all of the following are true:

- tenant quotas and rate limits exist
- secrets and policy inputs are tenant-aware
- the operator console can filter and inspect by tenant
- Slack has verified ingress, dedupe, retries, observability, and a clear capability matrix
- all non-reference channels/backends/providers are marked experimental
- product language matches actual supported depth

---

## Success metrics

- per-tenant run visibility coverage
- quota/rate-limit enforcement coverage
- Slack delivery success / retry visibility
- percentage of channel code using normalized events
- number of officially supported backends reduced to the reference path

---

## Risks and how to handle them

### Risk: product breadth feels reduced
Mitigation: depth increases trust; unsupported breadth stays available as experimental.

### Risk: tenancy rules surface hidden coupling
Mitigation: that is useful pressure; fix boundaries instead of hiding them.

### Risk: channel feature pressure returns quickly
Mitigation: require a capability matrix and exit criteria before adding new channels.

---

## Mapping to the critique

This phase directly addresses:

- **4F** multi-tenancy exists, but is still mostly logical tenancy
- **4H** channel support is broader than it is deep
- **5 Gap 5** UI/admin layer is behind platform claims
- **5 Gap 6** too many backends, not enough proof
- **6 Priority 4** narrow the claims
- **6 Priority 5** choose one production path and make it excellent

---

## Research basis

Primary references: `[R6]`, `[R7]`, `[R9]`, `[R12]`

Why these matter here:

- `[R6]` informs the move from ad hoc authorization to explicit relationship/scoping thinking.
- `[R7]` supports versioned, observable worker deployments that can be scoped by workload/tenant strategies.
- `[R9]` supports tenant-aware trace/log/metric correlation.
- `[R12]` supports secure logging, access control, and validation discipline.


---

## Source: 07_Phase_6_Worker_Forge_Maturation_Optional.md

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

