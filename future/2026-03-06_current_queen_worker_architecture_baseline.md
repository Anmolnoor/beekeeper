# Current Architecture Baseline: Queen + Workers

Date captured: 2026-03-06
Purpose: Frozen snapshot of the current architecture before migration, to support future update tracking.

## High-Level Flow
1. Request enters `QueenAgent.run()` in `beekeeper/queen.py`.
2. Queen classifies intent and routes a worker via `WorkerRegistry.select_worker_details()`.
3. If no content match (`content_score == 0`), Queen currently starts background auto-spawn and returns `WorkerKind.forged` for immediate execution.
4. Task executes through `WorkerRuntime` (`beekeeper/worker.py`) and result is persisted in Honeycomb.

## Core Modules and Responsibilities
- `beekeeper/queen.py`
  - Orchestration, routing, policy integration, action loop integration.
  - Dynamic worker generation path via `_auto_spawn_worker()`.
  - Background spawn trigger in `_route_worker_kind()` when unmatched intent.

- `beekeeper/worker_registry.py`
  - Worker catalog source of truth for routing.
  - Built-in defaults in `DEFAULT_REGISTRY`.
  - Runtime custom registration via `register_custom_worker()`.

- `beekeeper/worker.py`
  - Runtime executors for workers (`web_search`, `heavy_compute`, `audit`, `file_system`, `bash`, `forged`, etc.).
  - `ForgedWorker` handles fallback/custom execution style.

- `beekeeper/queen_actions.py`
  - Queen action registry includes `spawn_worker`, `remember`, `web_search`, `run_task`, `summarize`.
  - `spawn_worker` currently registers custom worker + skill + blueprint.

- `beekeeper/tool_adapters.py`
  - Exposes action tools to model tool loop.
  - Includes `spawn_worker` tool spec.

- `queen_api/app.py`
  - API route `POST /v1/workers` currently supports dynamic worker registration.
  - `GET /v1/workers` lists built-in + custom + generated workers.

## Dynamic Worker Creation Surfaces (Current)
1. Auto-spawn path:
- `QueenAgent._route_worker_kind()` -> thread target `_auto_spawn_worker()`.
- Emits `auto_spawn_started` event in trace.

2. Action surface:
- `queen_actions._action_spawn_worker()`.

3. Tool surface:
- `spawn_worker` in `tool_adapters` action tool specs.

4. API surface:
- `POST /v1/workers` (`queen_api/app.py`).

## Persistence and Generated Artifacts
- Registry file:
  - `.honeycomb/workers/registry.json`
- Generated plugins:
  - `.honeycomb/workers/generated/*.py`
- Plugin manifest:
  - `.honeycomb/workers/plugins.json`

## Policy/Guardrail References to Spawn
- `beekeeper/guardrails.py`:
  - `TOOL_TO_ACTION_MAP` includes `spawn_worker`.
- `beekeeper/user_policy.py`:
  - Default `always_ask` includes `spawn_worker`.
- `beekeeper/queen.py`:
  - Tool execution policy requires human approval for `spawn_worker`.

## Test Coverage Areas (Current)
- `tests/test_queen_autonomy.py`
  - Spawn action success.
  - Auto-spawn generation and second-run reuse behavior.
  - Auto-spawn event assertions.

- `tests/test_tool_runtime.py`
  - Guardrail/human approval behavior for `spawn_worker` tool.

## Known Current Behavior Summary
- Queen can create workers at runtime through multiple entry points.
- Unmatched intent can mutate runtime state by creating registry/plugin entries.
- Architecture mixes orchestration and provisioning responsibilities in the Queen path.

## Baseline References
- `beekeeper/queen.py`
- `beekeeper/worker_registry.py`
- `beekeeper/worker.py`
- `beekeeper/queen_actions.py`
- `beekeeper/tool_adapters.py`
- `queen_api/app.py`
- `beekeeper/guardrails.py`
- `beekeeper/user_policy.py`
- `tests/test_queen_autonomy.py`
- `tests/test_tool_runtime.py`
