# Phase 3 Build Spec

This document turns Phase 3 into an implementation-ready product-layer spec. It adds operator-facing surfaces and broader policy only after the hardened Phase 1 and Phase 2 runtime is stable.

## Fixed Decisions

- Keep the Phase 1 runtime path as the canonical engine.
- New product layers must consume the existing run, approval, trace, artifact, and worker models.
- No UI or protocol layer may invent its own state machine for runs or approvals.
- Scheduling and recurring jobs may be added only on top of stable background execution from earlier phases.

## Primary Goals

- add a browser dashboard over the existing runtime API and trace data
- add MCP support as an adapter, not as a new execution model
- expand policy beyond minimal approvals
- add scheduling and recurring jobs with durable state

## Product-Layer Components

### Dashboard

Build a browser dashboard that can:

- list runs by state
- inspect a run timeline
- inspect approvals and blocked actions
- inspect recent worker attempts
- browse artifacts and traces

The dashboard must read from the same authoritative Postgres-backed runtime state as the CLI and API.

### MCP Adapter

- expose selected runtime capabilities through MCP
- map MCP requests into the same run/job/approval flow as native CLI and API calls
- ensure MCP actions cannot bypass policy, approval, or trace recording

### Broader Policy Layer

- expand from action approvals to a real policy decision contract
- support:
  - admission-time policy
  - plan-time policy
  - action-time policy
- policy outcomes must be durable and traceable

### Scheduling

- add recurring-job definitions
- materialize scheduled runs into the existing `runs` and `jobs` tables
- persist next-run time and last-run outcome
- ensure scheduling is restart-safe and idempotent

## Schema Changes

### New Table: `policy_decisions`

- `decision_id`
- `run_id`
- `job_id`
- `decision_stage`
- `input_snapshot_json`
- `decision`
- `reason_codes_json`
- `obligations_json`
- `policy_version`
- `created_at`

### New Table: `schedules`

- `schedule_id`
- `name`
- `status`
- `trigger_type`
- `trigger_config_json`
- `next_run_at`
- `last_run_at`
- `last_run_status`
- `created_at`
- `updated_at`

### New Table: `mcp_sessions`

- `session_id`
- `client_name`
- `principal_id`
- `status`
- `created_at`
- `last_seen_at`

### Existing Tables

- `runs`
  - add `trigger_source`
  - add `schedule_id`
- `approvals`
  - add `policy_decision_id`

## Repository Layout Additions

- `beekeeper/governance/policy_client.py`
- `beekeeper/governance/policy_models.py`
- `beekeeper/runtime/scheduler.py`
- `beekeeper/runtime/schedule_service.py`
- `beekeeper/mcp_adapter/`
- `queen_api/dashboard_routes.py`
- `queen_api/mcp_routes.py`

If the existing repo uses different package names during implementation, preserve the behavior-level split above.

## API Surface Additions

### Dashboard APIs

- `GET /v1/runs`
- `GET /v1/runs/{run_id}/timeline`
- `GET /v1/approvals`
- `GET /v1/policy-decisions/{decision_id}`
- `GET /v1/schedules`

### Scheduling APIs

- `POST /v1/schedules`
- `POST /v1/schedules/{schedule_id}/pause`
- `POST /v1/schedules/{schedule_id}/resume`

### MCP

- expose only approved capabilities
- route all side-effectful calls through the same approval and policy path as native requests

## Frontend Scope

Keep the dashboard narrow:

- run list
- run detail
- approval queue
- artifact list
- trace timeline
- schedule list

Do not build desktop surfaces or channel-heavy operations in this phase.

## Milestone Sequence

### Milestone 1: Policy Broadening

- define the policy decision contract
- persist policy decisions durably
- wire admission, plan, and action checks into the existing runtime

### Milestone 2: Scheduling

- add schedule definitions and materialization
- create recurring runs through the existing run admission path
- prove idempotent schedule processing across restarts

### Milestone 3: Dashboard And MCP

- add dashboard APIs and minimal UI
- add MCP adapter over the same runtime path
- verify dashboard and MCP do not bypass trace, policy, or approval handling

## Test Plan

- policy decision contract tests
- schedule materialization tests
- recurring-run idempotency tests
- dashboard API tests for run, approval, and trace views
- MCP adapter tests for allowed and denied actions
- end-to-end tests covering a scheduled run that triggers an approval and is visible in the dashboard

## Exit Criteria

- the dashboard reflects real runtime state, not a parallel store
- recurring jobs survive restart and do not double-submit work
- policy decisions are durable, inspectable, and reused across surfaces
- MCP is an adapter over the runtime, not an alternate runtime
