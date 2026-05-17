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
