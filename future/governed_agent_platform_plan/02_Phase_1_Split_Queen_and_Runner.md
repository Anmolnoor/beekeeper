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
