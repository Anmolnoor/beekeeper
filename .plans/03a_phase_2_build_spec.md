# Phase 2 Build Spec

This document turns Phase 2 into an implementation-ready hardening spec that extends the supported Phase 1 runtime path rather than replacing it.

Phase 2 assumes the Phase 1 stack and schema already exist. It strengthens reliability, isolation, recovery, and model policy while keeping the product surface intentionally narrow.

## Fixed Decisions

- Keep the Phase 1 control plane: `queen-api` + `supervisor` + Postgres + MinIO.
- Keep one supported single-agent runtime path.
- Continue using subprocess workers as the baseline execution model.
- Do not add dashboard, MCP, multi-agent orchestration, or broad channel integrations in this phase.
- Add local-model fallback only after the primary OpenAI path is already stable and measurable.

## Primary Hardening Goals

- strengthen worker execution isolation
- make retries and leases safe and observable
- detect and recover stuck work without operator guesswork
- add per-worker model policy controls
- add validation steps for repo-maintenance workflows
- introduce skills as thin recipes over native workers

## Capability Additions

### Worker Isolation

- add explicit worker runtime profiles:
  - `trusted_local`
  - `restricted_local`
  - `network_restricted`
- each worker kind must declare:
  - allowed filesystem scope
  - network access mode
  - default timeout
  - max retries
  - approval escalation rules

### Recovery Semantics

- add job lease renewal and expiry handling
- add stuck-attempt detection based on heartbeat age
- add retry classification:
  - retryable transient failure
  - retryable infrastructure failure
  - non-retryable user or policy failure
- add idempotent requeue rules for retryable jobs only

### Model Policy

- add per-worker provider selection and model defaults
- keep OpenAI primary
- add local fallback behind explicit policy and health checks
- record provider, model, and fallback reason in trace and attempt state

### Validation Layer

- support pre-apply validation steps for repo-maintenance workflows:
  - syntax checks
  - unit test subset
  - formatting check
  - diff summary
- validation runs must be traceable and artifact-backed

### Skills

- define skills as reusable execution recipes over existing worker capabilities
- skills may sequence worker calls and validation steps
- skills must not become an alternate runtime or policy bypass

## Schema Changes

Extend the Phase 1 schema with the minimum additional fields needed for hardening.

### `jobs`

- `max_retries`
- `retry_policy`
- `last_lease_renewed_at`
- `next_retry_at`
- `failure_class`

### `worker_attempts`

- `runtime_profile`
- `worker_version`
- `provider_name`
- `model_name`
- `fallback_used`
- `fallback_reason`
- `last_progress_at`

### `trace_events`

- add event coverage for:
  - lease claimed
  - lease renewed
  - lease expired
  - retry scheduled
  - retry abandoned
  - validation started
  - validation passed
  - validation failed

### New Table: `skills`

- `skill_id`
- `name`
- `version`
- `definition_json`
- `status`
- `created_at`
- `updated_at`

This table stores registered skill metadata only. Skill execution remains part of the main run and job model.

## Repository Layout Additions

- `beekeeper/runtime/recovery.py`
- `beekeeper/runtime/lease_service.py`
- `beekeeper/runtime/retry_policy.py`
- `beekeeper/runtime/validation_service.py`
- `beekeeper/workers/runtime_profiles.py`
- `beekeeper/skills/registry.py`
- `beekeeper/skills/executor.py`

## API Surface Additions

Add only the minimum inspection and control APIs needed for hardened execution:

- `GET /v1/runs/{run_id}/attempts`
- `POST /v1/runs/{run_id}/retry`
- `POST /v1/jobs/{job_id}/cancel`
- `GET /v1/skills`

Do not add dashboard-oriented APIs yet; keep responses runtime-centric.

## CLI Surface Additions

- `beekeeper retry <run_id>`
- `beekeeper cancel <job_id>`
- `beekeeper attempts <run_id>`
- `beekeeper skills list`

## Docker And Runtime Changes

- keep Postgres and MinIO as core services
- optionally add a local-model service only for explicit fallback testing
- do not make local model infrastructure required for the default path
- supervisor must own:
  - heartbeat updates
  - stuck-run detection
  - retry scheduling

## Milestone Sequence

### Milestone 1: Recovery Foundation

- add lease renewal and expiry tracking
- classify failures and safe retry rules
- add stuck-attempt detection
- persist recovery decisions in state and trace

### Milestone 2: Isolation And Model Policy

- add worker runtime profiles and enforce them in subprocess launches
- add per-worker model policy configuration
- record provider/model/fallback data in attempts and traces
- verify local fallback is disabled unless explicitly configured

### Milestone 3: Validation And Skills

- add validation-service execution before sensitive repo changes
- persist validation outputs as artifacts
- add skill registry and skill execution as thin recipes
- prove that skills use the same policy, trace, and worker path as native execution

## Test Plan

- lease renewal and lease expiry unit tests
- retry classification and backoff tests
- stuck-worker recovery tests
- worker-profile enforcement tests
- provider fallback policy tests
- validation pipeline tests for pass/fail behavior
- skill execution tests showing trace continuity and policy reuse

## Exit Criteria

- background jobs recover safely after worker death or stalled heartbeats
- retries are classified, bounded, and observable
- worker runtime profiles are enforced, not just documented
- local fallback works only under explicit policy
- validation steps and skills fit the native runtime path cleanly
