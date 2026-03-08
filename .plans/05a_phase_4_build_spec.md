# Phase 4 Build Spec

This document turns Phase 4 into an implementation-ready expansion spec. It broadens the product only after the single-agent runtime, hardening work, and product layers are already proven.

## Fixed Decisions

- The single-agent runtime remains the canonical core.
- Expansion features are additive and optional.
- New surfaces and execution patterns must reuse the existing durable state, trace, policy, approval, and artifact systems.
- Memory, retrieval, plugins, and orchestration are opt-in capabilities, not new mandatory foundations.

## Primary Goals

- add optional multi-agent orchestration
- add desktop and richer web operator surfaces
- add more workers and plugin mechanisms
- add optional memory and retrieval layers where they provide clear value

## Expansion Areas

### Multi-Agent Orchestration

- keep one run as the top-level durable execution record
- represent subordinate agent work as child jobs or child runs
- preserve one approval and policy model across parent and child execution
- make agent coordination observable in the same trace tree

### Richer Operator Surfaces

- expand the web UI beyond the narrow dashboard
- optionally add a desktop shell only if it consumes the same APIs as the web UI
- surface trace, approvals, schedules, and artifacts without duplicating backend logic

### Additional Workers And Plugins

- add a formal worker registration path
- version worker capabilities and compatibility
- require capability manifests for non-core workers
- treat plugins as optional packages with explicit lifecycle and ownership

### Optional Memory And Retrieval

- keep retrieval off by default
- enable memory or retrieval only for workloads that benefit from it
- store retrieval configuration durably and trace when retrieval affected outcomes

## Schema Changes

### New Table: `worker_versions`

- `worker_version_id`
- `worker_kind`
- `version`
- `capability_manifest_json`
- `status`
- `created_at`

### New Table: `plugins`

- `plugin_id`
- `name`
- `version`
- `status`
- `owner`
- `manifest_json`
- `installed_at`

### New Table: `agent_relationships`

- `relationship_id`
- `parent_run_id`
- `child_run_id`
- `relationship_type`
- `created_at`

### Optional Table: `retrieval_profiles`

- `profile_id`
- `name`
- `status`
- `backend`
- `config_json`
- `created_at`
- `updated_at`

## Repository Layout Additions

- `beekeeper/orchestration/`
- `beekeeper/plugins/registry.py`
- `beekeeper/plugins/loader.py`
- `beekeeper/workers/versioning.py`
- `beekeeper/memory/`
- `queen_api/plugin_routes.py`
- `queen_api/orchestration_routes.py`

## API Surface Additions

- `GET /v1/workers`
- `GET /v1/workers/{worker_kind}/versions`
- `GET /v1/plugins`
- `POST /v1/plugins/install`
- `GET /v1/runs/{run_id}/children`
- `GET /v1/retrieval-profiles`

Any plugin install or activation API must remain approval-gated and policy-mediated.

## Frontend Scope

The richer operator surface may add:

- child-run visualization
- worker and plugin inventory
- retrieval-profile inspection
- richer artifact browsing
- deeper trace and attempt inspection

The desktop app, if built, should be a thin shell over the web/runtime APIs.

## Milestone Sequence

### Milestone 1: Worker And Plugin Maturity

- add worker version tracking
- add plugin manifest and registration model
- make non-core workers discoverable and inspectable

### Milestone 2: Multi-Agent Optionality

- add parent/child run relationships
- coordinate subordinate work through the same durable job model
- preserve approval and policy semantics across orchestration boundaries

### Milestone 3: Optional Retrieval And Richer Surfaces

- add retrieval profiles and traceable retrieval usage
- expand the operator UI and, only if justified, desktop shell support
- verify optional features remain optional and do not destabilize the core path

## Test Plan

- worker-version registry tests
- plugin manifest and activation tests
- orchestration relationship tests
- approval and policy propagation tests for child runs
- retrieval-profile tests
- UI/API tests for worker inventory and child-run visibility

## Exit Criteria

- multi-agent execution is optional and traceable
- worker and plugin lifecycle is versioned and inspectable
- retrieval remains opt-in and observable
- richer operator surfaces reuse existing APIs and state
- the base single-agent path remains the simplest and most reliable supported path
