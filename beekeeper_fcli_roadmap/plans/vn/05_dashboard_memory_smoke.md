# 05: Dashboard, Memory, and Golden Smoke Plan

Date: 2026-06-08

## Context

Once Beekeeper can run a coding worker and govern side effects, the product still needs to feel usable. A correct backend is not enough if the user cannot see what happened, inspect memory, or rerun a smoke test that proves the system still works.

Vn is the ongoing product acceptance layer.

It turns the roadmap into a repeatable bar:

> Can Beekeeper show the run, explain the evidence, expose memory, and pass a tiny end-to-end coding task?

## Dashboard Goal

The dashboard should be a work surface, not a marketing page and not a broad admin maze.

Primary panels:

- Runs
- Approvals
- Memories
- Workers

Later panels can include schedules, settings, traces, channels, and skill promotion. The first dashboard should focus on the coding-worker path.

## Runs Panel

The Runs panel should show:

- run ID,
- request summary,
- workspace,
- worker,
- status,
- elapsed time,
- changed files count,
- verification status,
- approval state,
- created time,
- final result link.

Run detail should show:

- timeline events,
- final summary,
- changed files,
- final diff,
- commands run,
- verification result,
- approval records,
- artifacts,
- memory updates proposed or written.

## Approvals Panel

The Approvals panel should show pending and resolved approvals.

Each item should include:

- action,
- risk tier,
- requesting worker,
- run link,
- target,
- policy reason,
- evidence links,
- approve/reject controls,
- resolution note.

The UI should make it clear whether approving continues the existing run, enables rerun, or only records permission for a future action.

## Memories Panel

Beekeeper needs a user-facing memory surface because personal-agent memory is only valuable when the user can correct it.

Minimum memory actions:

- list memories,
- search memories,
- inspect memory source,
- edit a memory,
- delete a memory,
- show project vs user scope where available.

Future memory inbox states:

- proposed,
- approved,
- rejected,
- needs clarification.

The first version can be simpler, but it must avoid invisible permanent memory writes.

## Workers Panel

The Workers panel should show:

- worker name,
- worker kind,
- version,
- source,
- status,
- provider profile,
- capability summary,
- last run,
- last failure,
- health check result.

For `coding_worker`, it should show:

- bridge type,
- contract version,
- event protocol,
- admitted workspace policy,
- side-effect policy,
- verification capability.

## Golden Smoke

The golden smoke is the repeatable proof that the product works end to end.

It should use a tiny local test repo or fixture workspace.

The smoke should:

1. Start or connect to Beekeeper personal mode.
2. Register or select the local workspace.
3. Submit a small coding request.
4. Dispatch `coding_worker`.
5. Read files.
6. Make one safe edit.
7. Run one verification command.
8. Return final summary.
9. Store final diff.
10. Store verification result.
11. Show run timeline.
12. Show artifacts.
13. Show approval posture.
14. Optionally propose one memory update.

The smoke passes only when the user can inspect the result from Beekeeper without manually digging through worker logs.

## Smoke Failure Categories

Failures should be classified:

| Category | Meaning |
|---|---|
| `setup_failed` | Personal mode could not start or validate. |
| `workspace_failed` | Workspace selection/admission failed. |
| `dispatch_failed` | Beekeeper could not start the worker. |
| `event_failed` | Worker events were missing or malformed. |
| `execution_failed` | Worker could not complete the coding task. |
| `verification_failed` | Worker completed but verification failed. |
| `artifact_failed` | Result exists but evidence is missing. |
| `dashboard_failed` | Backend succeeded but UI cannot show the result. |
| `memory_failed` | Memory surface wrote or displayed incorrect state. |

## Implementation Sequence

### Step 1: Define Run Detail Contract

List exactly what the dashboard needs from the run API.

Verification:

- One completed run can be rendered from structured data without scraping raw logs.

### Step 2: Build Minimal Runs Panel

Show runs and run detail.

Verification:

- Completed, failed, blocked, and running states render clearly.

### Step 3: Build Approval Detail Flow

Connect approval list and run detail.

Verification:

- A blocked run links to the pending approval, and the approval links back to the run.

### Step 4: Build Memory Surface

Expose memory list, edit, and delete.

Verification:

- A bad memory can be found, edited, or removed.

### Step 5: Build Worker Health Panel

Show worker readiness and contract version.

Verification:

- `coding_worker` health makes it clear whether provider, bridge, and workspace policy are ready.

### Step 6: Automate Golden Smoke

Add a repeatable command or test harness.

Verification:

- One command produces a pass/fail result and links to the stored Beekeeper run.

## Non-Goals

- No marketing landing page.
- No full SPA rewrite unless static UI becomes the bottleneck.
- No broad channel experience.
- No mobile app.
- No production compliance export.
- No generated worker marketplace.

## Standing Acceptance Bar

Every later roadmap step should preserve this path:

```text
personal setup
  -> workspace selected
  -> coding request submitted
  -> worker dispatched
  -> events visible
  -> side effects governed
  -> result stored
  -> diff and verification inspectable
  -> memory inspectable/editable
```

If a later feature breaks this path, the product is regressing even if the new feature works in isolation.

