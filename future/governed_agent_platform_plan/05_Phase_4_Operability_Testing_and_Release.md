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
