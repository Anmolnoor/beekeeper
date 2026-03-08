# Main Branch Reference Map For V1

## Reusable Concepts From `main`

These ideas from `main` should carry into V1:

- Queen / Worker / Honeycomb metaphor
- append-only trace as a core product behavior
- approval for destructive or sensitive actions
- durable state as a first-class concern

The best high-level statement of the metaphor is in:

- `architecture/01_overview.md`

## Likely Reusable Code Areas

These are the strongest candidates for reuse as-is or partial reuse:

- `beekeeper/contracts.py`
  - useful typed contracts and enums
- `beekeeper/worker.py`
  - useful worker concepts and existing worker implementations
- `beekeeper/data_plane/repositories/postgres_durable_state.py`
  - strong starting point for Postgres-backed state
- `beekeeper/runner.py`
  - useful CLI surface ideas and command structure
- `architecture/01_overview.md`
  - strongest existing product metaphor and system framing

## Reuse With Rewrite

These areas contain useful intent but should not be carried forward unchanged:

- `beekeeper/queen.py`
  - too much mixed responsibility and too many runtime paths
- `beekeeper/guardrails.py`
  - useful concepts, but V1 needs a smaller approval kernel first
- `beekeeper/policy_service.py`
  - should be narrowed to local approval and execution mediation in V1
- `beekeeper/tool_runtime.py`
  - useful ideas, but V1 should center isolated worker execution before broad tool-loop abstraction
- `queen_api/app.py`
  - useful local API direction, but V1 should keep the API minimal and runtime-centric

## Delay or Exclude From V1 Core

These should be delayed or kept out of the V1 core runtime:

- `beekeeper/mcp_adapter.py`
- `beekeeper/mcp_transport.py`
- `beekeeper/temporal_integration.py`
- `beekeeper/temporal_worker.py`
- `beekeeper/worker_forge_service.py`
- dashboard, channel, and notification flows under `beekeeper_api/*`

The reason is not that these are bad ideas. The reason is sequencing: the native local runtime must be reliable before these layers are added.

## Gap Summary Against V1

The main branch shows several gaps relative to the V1 rebuild direction:

- too many runtime modes
- governance layers arrive too early
- no single clean runtime spine
- insufficient focus on isolated workers for the local operator workflow
- too many platform surfaces before the core engine is stable

## Practical Reuse Guidance

When implementing V1:

- keep the metaphor and the core terminology
- reuse contracts and Postgres state ideas where they simplify the rebuild
- reuse worker logic only when it fits the new isolated-worker model
- avoid carrying forward platform complexity just because it already exists
- treat `main` as a reference source, not as the architecture to preserve
