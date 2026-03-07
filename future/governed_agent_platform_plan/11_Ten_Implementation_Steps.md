# 11 — Ten Implementation Steps

Date: 2026-03-07

## Purpose

This file turns the remaining roadmap gaps into one ordered implementation sequence tied to the current codebase. It is intentionally concrete: each step names the primary modules to change, the dependency it unlocks, and the acceptance bar before moving on.

These steps are ordered. Some work can overlap, but the platform should not claim the supported production path until Steps 1 through 9 are complete, and Step 10 must block further worker-forge expansion.

---

## Step 1 — Replace the SQLite durable-state adapter with a Postgres repository

### Why first
- The declared production path already says Postgres is authoritative.
- Run, task, approval, policy, and outbox state should stop depending on a local SQLite file.

### Primary touchpoints
- `beekeeper/data_plane/repositories/sqlite_durable_state.py`
- `beekeeper/data_plane/repositories/__init__.py`
- `beekeeper/honeycomb.py`
- `beekeeper/config/settings.py`
- `beekeeper/config/validators.py`
- `tests/test_phase2_durable_state.py`

### Implementation shape
- Keep the current repository method surface stable so callers do not change first.
- Extract shared repository contract expectations from the current SQLite adapter behavior.
- Add a Postgres-backed implementation with the same method names and return semantics.
- Select the repository by runtime config/DSN, with SQLite explicitly treated as dev-only.
- Preserve outbox and inspection behavior.

### Acceptance
- API/control-plane restart does not lose run/task/approval/policy state.
- Durable-state tests run against Postgres, not just SQLite.
- Non-dev startup fails closed if Postgres is required but unavailable.

---

## Step 2 — Add an object-storage adapter for artifacts

### Why now
- Artifacts are still written to Honeycomb local paths and treated as authoritative.
- State and blobs need to be separated before execution is pushed fully out of process.

### Primary touchpoints
- `beekeeper/honeycomb.py`
- `beekeeper/contracts.py`
- `beekeeper_api/routes.py`
- `tests/test_phase2_durable_state.py`
- `docs/architecture/storage-classification.md`

### Implementation shape
- Introduce an artifact storage service with a local dev adapter and an S3-compatible adapter.
- Make artifact records durable metadata plus object key/checksum/content type, not filesystem truth.
- Keep Honeycomb artifact events as a debugging mirror only.
- Update operator/run inspection views to resolve artifacts from metadata instead of Honeycomb paths.

### Acceptance
- Artifact metadata lives in durable state; artifact bytes live in object storage.
- No API/operator surface assumes `HoneycombStore.artifacts_dir` is authoritative.
- Recovery drill can validate artifact presence independently of the API host filesystem.

---

## Step 3 — Move API request execution to queue/Temporal submission

### Why now
- Control-plane routes still execute work directly through `queen.run(...)`.
- This violates the roadmap rule that no long-running work happens inside the API process.

### Primary touchpoints
- `beekeeper_api/routes.py`
- `beekeeper/temporal_integration.py`
- `beekeeper/temporal_worker.py`
- `beekeeper/celery_app.py`
- `beekeeper/contracts.py`

### Current direct-execution surfaces to remove first
- `/api/chat/run` in `beekeeper_api/routes.py`
- web chat submission paths in `beekeeper_api/routes.py`
- any equivalent route that blocks on `queen.run(...)`

### Implementation shape
- Convert API submission routes into admission + durable run creation + queue/workflow submission.
- Return run/task identifiers and initial state immediately.
- Let workers update durable state asynchronously.
- Keep inline execution only for explicit local-dev modes.

### Acceptance
- API request latency is decoupled from worker execution time.
- Killing the API process does not kill admitted work.
- Operator views can show queued/running/completed state from durable records alone.

---

## Step 4 — Refactor `queen.py` into a coordinator plus services

### Why after Step 3 starts
- The coordinator boundary becomes clearer once API submission and execution are separated.
- Refactoring should follow actual platform boundaries, not just move functions around.

### Primary touchpoints
- `beekeeper/queen.py`
- `beekeeper/profile_service.py`
- `beekeeper/response_aggregation_service.py`
- `beekeeper/queen_context.py`
- `beekeeper/queen_actions.py`
- `beekeeper/tool_runtime.py`
- new service modules for planner, routing, dispatch, and context orchestration

### Target split
- coordinator: high-level request lifecycle only
- planner service: intent decomposition and plan creation
- routing service: worker selection and forge gating
- dispatch service: queue submission, retry, and completion handoff
- context service: queen/user/run context loading and rendering

### Acceptance
- `queen.py` becomes orchestration glue rather than implementation center.
- New behavior can be added in services without editing `queen.py` first.
- Extracted services have direct unit tests.

---

## Step 5 — Replace the local policy adapter with an external policy contract layer

### Why here
- Once queueing and coordinator boundaries exist, policy becomes a real control-plane contract instead of inline orchestration logic.

### Primary touchpoints
- `beekeeper/governance/policy_adapter.py`
- `beekeeper/governance/__init__.py`
- `beekeeper/queen.py`
- `beekeeper/tool_runtime.py`
- `tests/test_phase3_governance.py`

### Implementation shape
- Keep an adapter boundary, but replace `LocalPolicyAdapter` as the primary path.
- Define an explicit request/response contract for OPA/Rego-compatible decisions.
- Translate run/task/tool context into policy input documents.
- Treat the current local adapter as a dev fallback or test double only.

### Acceptance
- Sensitive allow/deny/escalate decisions flow through the external-policy contract.
- Policy version and obligations are persisted with decisions.
- Policy bypass is not possible on supported paths.

---

## Step 6 — Introduce a tool broker for side effects and secrets access

### Why after policy externalization
- High-risk actions need one choke point that can enforce policy, capability manifests, approvals, and provenance.

### Primary touchpoints
- `beekeeper/tool_runtime.py`
- `beekeeper/tool_adapters.py`
- `beekeeper/queen_actions.py`
- new `beekeeper/governance/tool_broker.py`
- new provenance and broker-facing contracts

### Broker responsibilities
- outbound side effects
- secret access mediation
- approval checks for high-risk actions
- provenance capture
- idempotency keys for retryable side effects

### Acceptance
- Destructive or externally side-effectful actions no longer execute directly from worker/tool code.
- Tool execution paths can be audited at the broker boundary.
- High-risk actions can be blocked or escalated without special-casing each tool.

---

## Step 7 — Add managed secret references and a real secret-provider path

### Why after the broker exists
- Secret access should be mediated through one runtime path, not scattered env/config reads.

### Primary touchpoints
- `beekeeper/store.py`
- `beekeeper/config/validators.py`
- `beekeeper/runtime_env.py`
- `beekeeper_api/routes.py`
- new secret-reference and secret-provider modules

### Implementation shape
- Introduce durable secret references, not raw secret values, in platform metadata.
- Add a secret-provider interface and at least one real managed backend path.
- Route tool/channel/provider secret retrieval through the broker/provider path.
- Reduce validation-only checks by wiring actual retrieval and failure handling.

### Acceptance
- Production paths can resolve secrets from a managed provider.
- Audit records show secret reference usage, not secret material.
- Runtime fails closed if a required managed secret cannot be resolved.

---

## Step 8 — Enforce sandbox profiles explicitly

### Why after broker + secret path
- Isolation policy needs to be attached to real execution, not just metadata declarations.

### Primary touchpoints
- `beekeeper/worker.py`
- `beekeeper/governance/capability_manifests.py`
- `beekeeper/queen.py`
- `beekeeper/runtime_env.py`
- new sandbox profile enforcement module(s)
- tests covering runtime-mode and sandbox enforcement

### Implementation shape
- Replace passive `sandbox_tier` metadata with an executable sandbox-profile model.
- Enforce network, filesystem, secret, and resource constraints at execution time.
- Make generated/untrusted workloads use stricter profiles than built-in workers.

### Acceptance
- Worker execution cannot silently ignore sandbox requirements.
- Operator telemetry can show which sandbox profile was applied to each run/task.
- High-risk or generated workloads fail closed if the required isolation profile is unavailable.

---

## Step 9 — Add OpenTelemetry and wire operator views to those signals

### Why after control/execution boundaries are real
- End-to-end telemetry is only meaningful once runs cross API, queue, worker, policy, and broker boundaries.

### Primary touchpoints
- `beekeeper/tracing.py`
- `beekeeper/audit_logger.py`
- `beekeeper_api/app.py`
- `beekeeper_api/routes.py`
- `beekeeper_api/static/dashboard.html`
- `ops/dashboards/`
- `ops/alerts/`

### Implementation shape
- Instrument API admission, run creation, queue submission, worker execution, approvals, tool broker calls, artifact writes, and channel delivery.
- Correlate trace/span IDs with durable run/task identifiers.
- Back operator views with OTel-derived signals instead of Honeycomb-only local traces.

### Acceptance
- Operators can inspect a run end-to-end across API, queue, worker, policy, and artifact events.
- Metrics/logs/traces share consistent correlation identifiers.
- The supported path has dashboards and alerts tied to those signals.

---

## Step 10 — Freeze worker forge as experimental and add the Phase 6 promotion pipeline

### Why last
- Worker forge should not expand before the durable, governed, observable path exists.
- Promotion requirements depend on the previous nine steps.

### Primary touchpoints
- `beekeeper/queen.py`
- `beekeeper/worker.py`
- `beekeeper/tool_adapters.py`
- `docs/maturity-model.md`
- `docs/support-matrix.md`
- `future/governed_agent_platform_plan/07_Phase_6_Worker_Forge_Maturation_Optional.md`

### Implementation shape
- Keep forge labeled experimental in code paths, docs, and UI.
- Gate forge creation/execution behind policy, sandbox, provenance, and release checks.
- Add a promotion pipeline covering tests, signatures, versioning, approval, and rollout controls before any scope expansion.

### Acceptance
- No doc or UI implies forge is a mature production pillar.
- Generated workers cannot bypass the same policy/broker/sandbox/provenance path as built-in workers.
- Phase 6 promotion criteria are implemented before adding more forge breadth.

---

## Recommended execution bundles

### Bundle A — Durable foundations
1. Step 1
2. Step 2
3. Step 3

### Bundle B — Control-plane decomposition
4. Step 4
5. Step 5
6. Step 6

### Bundle C — Enforcement and operability
7. Step 7
8. Step 8
9. Step 9

### Bundle D — Experimental freeze and promotion
10. Step 10

---

## Do not skip these dependency rules

- Do not treat Postgres as optional on the supported path after Step 1 lands.
- Do not keep Honeycomb artifact paths as authority after Step 2 lands.
- Do not add new API surfaces that call `queen.run(...)` directly after Step 3 lands.
- Do not expand worker forge before Step 10 is in place.

---

## Completion bar

This ten-step sequence is complete only when:

- the supported production path is Postgres + Temporal + object storage in real runtime behavior
- API/control-plane processes only admit, persist, evaluate, queue, and observe
- workers execute through policy, broker, secret, sandbox, and telemetry boundaries
- operator views and recovery drills validate the supported path
- worker forge remains experimental until the promotion pipeline exists
