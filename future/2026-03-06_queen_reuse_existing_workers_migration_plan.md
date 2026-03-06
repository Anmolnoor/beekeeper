# Queen Reuse Existing Workers Migration Plan

Date: 2026-03-06

## Goal
Stop all runtime worker creation by Queen. Queen should only route and execute workers that already exist in the registry/runtime.

## Current Behavior (What exists today)
- `QueenAgent._route_worker_kind()` triggers background `self._auto_spawn_worker(...)` when `content_score == 0`, then returns `WorkerKind.forged` for current request.
- `QueenAgent._auto_spawn_worker()`:
  - writes a `custom_*` worker into worker registry,
  - creates a skill + blueprint,
  - generates plugin code into `.honeycomb/workers/generated/`,
  - hot-reloads plugins.
- Queen action system supports `spawn_worker` (`beekeeper/queen_actions.py`) and registers it in default action registry.
- Model tool loop exposes `spawn_worker` tool (`beekeeper/tool_adapters.py`) and sets HITL requirement for it.
- Queen API has POST `/v1/workers` endpoint named `spawn_worker` for dynamic registration.
- Docs and tests explicitly describe and validate auto-forge/spawn behavior.

## Target Architecture
- No dynamic worker provisioning in runtime request path.
- Worker set is pre-provisioned by operator/developer via:
  - core built-in workers,
  - preinstalled plugins,
  - pre-edited registry files.
- Queen routing must degrade gracefully when no strong match exists:
  - use configured default worker (typically `web_search`), or
  - use `forged` only as generic executor (without creating new workers).
- Queen may still suggest adding/installing workers, but must not create/register them itself.

## Decisions To Lock Before Implementation
1. Keep or remove `WorkerKind.forged`:
- Recommended: keep as generic fallback executor to avoid behavior regression.

2. `spawn_worker` API/action/tool handling:
- Recommended: keep interface temporarily but return deterministic `disabled_by_architecture_migration` error (deprecation path), then remove in v2.

3. Fallback policy when no content match:
- Recommended: route to `registry.default_worker`; only use `forged` if explicitly configured as default worker.

## Implementation Plan

### Phase 1: Disable Runtime Worker Creation Path
Files:
- `beekeeper/queen.py`
- `beekeeper/worker_registry.py` (docstring/comments only)

Changes:
- In `_route_worker_kind()`, remove background thread call to `_auto_spawn_worker` on `content_score == 0`.
- Replace behavior with deterministic fallback selection from registry default worker metadata.
- Remove `auto_spawn_started` event emission.
- Keep `_auto_spawn_worker()` temporarily but make it unused and clearly deprecated (or delete if no remaining references).
- Update comments that currently say content-score zero "triggers auto-spawn".

Acceptance criteria:
- No request path calls `_auto_spawn_worker`.
- No new files under `.honeycomb/workers/generated/` are produced by Queen execution.

### Phase 2: Block Spawn Surfaces (Action, Tool, API)
Files:
- `beekeeper/queen_actions.py`
- `beekeeper/tool_adapters.py`
- `queen_api/app.py`
- `beekeeper/queen.py` (tool policy list)
- `beekeeper/guardrails.py`
- `beekeeper/user_policy.py`

Changes:
- `queen_actions.py`:
  - Replace `_action_spawn_worker` body with explicit failure result: `success=False`, `error="spawn_worker_disabled"`, and migration hint in output.
  - Optionally keep action registration for compatibility in short term.
- `tool_adapters.py`:
  - Remove `spawn_worker` from action tool specs or map it to a disabled executor that returns structured error.
- `queen_api/app.py`:
  - Change POST `/v1/workers` to return 410/400 style response with message: worker creation disabled; use install/preprovision workflow.
- `queen.py`:
  - Remove `spawn_worker` from tool execution policy HITL list if tool removed.
- `guardrails.py` and `user_policy.py`:
  - Remove/adjust references to `spawn_worker` so policy UX is coherent.

Acceptance criteria:
- Any attempt to call spawn APIs/tools/actions returns explicit disabled response.
- No hidden code path can still register custom workers at runtime.

### Phase 3: Routing and Fallback Hardening
Files:
- `beekeeper/worker_registry.py`
- `beekeeper/queen.py`

Changes:
- Ensure `select_worker_details()` fallback behavior is explicit and well-tested when `content_score == 0`.
- Optionally add config flag: `strict_existing_workers_only: bool = True` (default true) to lock architecture intent.
- Ensure `_runtime_worker_key` handling only applies to existing registered workers.

Acceptance criteria:
- Unmatched intents route predictably to default worker.
- No custom worker kind is invented unless already present in registry.

### Phase 4: Tests Migration
Files:
- `tests/test_queen_autonomy.py`
- `tests/test_tool_runtime.py`
- Any API tests covering `/v1/workers`

Changes:
- Remove/replace tests that expect:
  - auto-spawn thread behavior,
  - generated plugin creation,
  - spawn_worker success path.
- Add tests for:
  - unmatched intent uses default worker and does not spawn,
  - spawn action/tool/API return disabled errors,
  - no `auto_spawn_started` events are emitted.

Acceptance criteria:
- Test suite reflects new architecture intent and passes.

### Phase 5: Documentation & Operator Runbook
Files:
- `README.md`
- `HOW_TO_USE.md`
- `architecture/03_core_modules.md`
- `docs/BUILDING_NEW_WORKERS.md`
- `docs/DECISION_TREE.md`

Changes:
- Remove "Worker Forge" runtime creation narrative.
- Replace with "pre-provision workers" workflow:
  - install plugin package,
  - edit registry,
  - reload/restart service.
- Add migration notes for users currently relying on auto-spawn.

Acceptance criteria:
- No user-facing docs claim queen runtime creates workers.

## Migration Strategy

### Compatibility Window (recommended)
- Release N:
  - disable runtime spawn,
  - keep spawn interfaces returning explicit disabled errors,
  - add deprecation notes.
- Release N+1:
  - remove `spawn_worker` interfaces and dead code.

### Config/State Migration
- Existing custom workers already in registry/plugins continue to work.
- No data migration required for existing worker entries.
- Optional cleanup script (later): identify orphaned generated workers not referenced by registry.

## Risks and Mitigations
- Risk: behavior drift for unmatched intents.
  - Mitigation: explicit fallback tests; track routed worker in trace events.

- Risk: clients depend on `/v1/workers` spawn success.
  - Mitigation: return stable error contract first; document replacement workflow.

- Risk: stale references to spawn in policy/UX.
  - Mitigation: remove from defaults and docs in same release.

## Verification Checklist
- Run unit tests for autonomy, tool runtime, API.
- Manual checks:
  - unmatched intent does not create files in `.honeycomb/workers/generated/`.
  - POST `/v1/workers` returns disabled response.
  - queen action loop with `spawn_worker` returns explicit failure and continues safely.
- Trace validation:
  - no `auto_spawn_started` events.

## Concrete Work Breakdown (Execution Order)
1. Disable `_route_worker_kind` auto-spawn path.
2. Disable spawn action/tool/API surfaces.
3. Update policy/guardrail references.
4. Rewrite/replace tests.
5. Update docs and release notes.
6. Optional cleanup of deprecated code (`_auto_spawn_worker`, plugin generation helpers) after one release.

## Definition of Done
- Queen cannot create/register/generate workers during request execution.
- Queen routes only to pre-existing workers.
- Spawn interfaces are either removed or explicitly disabled.
- Tests and docs are aligned with new architecture.
