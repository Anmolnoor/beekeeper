# Plan: Borrow Odysseus UI Patterns for Beekeeper Governance

Date: 2026-06-05

## Context and Problem

Beekeeper already has a prototype dashboard at `beekeeper_api/static/dashboard.html` with auth, channels, workers, approvals, settings, KPI, traces, Queen updates, and audit logs. The current shape is useful but still feels like a packed admin page instead of a durable control surface for governing Queen, workers, skills, memory, approvals, and audit evidence.

Odysseus has mature UI primitives and panels that map well to Beekeeper's product surface. The goal is to borrow its shell, task, memory, skills, modal, theme, spinner, and provider-settings UX patterns without importing Odysseus's broad in-process agent architecture.

Reference source areas:

- Shell and primitives: `/Users/anmolnoor/Developer/odysseus/static/js/ui.js`, `modalManager.js`, `windowDrag.js`, `windowResize.js`, `sidebar-layout.js`, `spinner.js`, `theme.js`
- Tasks: `/Users/anmolnoor/Developer/odysseus/static/js/tasks.js`
- Memory: `/Users/anmolnoor/Developer/odysseus/static/js/memory.js`
- Skills: `/Users/anmolnoor/Developer/odysseus/static/js/skills.js`

## Goals

- Replace the one-page dashboard feel with a sidebar-driven governance shell.
- Make worker activity visible as tasks: queued, running, paused, blocked, completed, failed, and stopped.
- Give operators direct controls: schedule, run now, pause, resume, stop, review history, open evidence, and inspect activity logs.
- Turn Queen memory into an approval inbox with `proposed`, `approved`, `rejected`, and `needs_clarification` states.
- Turn skills/workers into a promotion pipeline: `draft -> sandboxed -> tested -> reviewed -> approved -> active`.
- Keep chat as the Queen command center, showing worker summaries, evidence, and links to detail pages instead of full worker transcripts.
- Add clear model/provider settings for Queen, coding workers, verifier, and cheap memory curator models.

## Non-Goals

- Do not import Odysseus `agent_loop.py` or its agent runtime structure.
- Do not add the image editor, gallery, voice, TTS, full Cookbook model-serving stack, shell/file admin tools, or Deep Research in the first milestone.
- Do not rewrite Beekeeper into a general chat workspace. The core UX is worker governance.
- Do not start with a full frontend framework migration unless the static shell cannot support the required flows.

## Options Considered

### Option A: Keep the Current Static Dashboard and Add Cards

This is the smallest change. Add more cards to `dashboard.html` for tasks, memory, skills, and settings. It keeps implementation cheap but makes the already dense page harder to scan and does not create durable navigation or modal/workspace behavior.

### Option B: Modular Static JS Shell Inspired by Odysseus

Keep Beekeeper's lightweight static frontend but split it into modules under `beekeeper_api/static/js/`. Add a sidebar shell, reusable modal manager, toasts, spinner states, theme handling, and focused panels for Dashboard, Tasks, Workers, Approvals, Memory, Skills, Audit, and Settings. This fits the current repo and can be verified incrementally.

### Option C: Full SPA Rewrite

Move the dashboard to React/Vite/Next and rebuild the UI as an app. This could improve long-term maintainability, but it adds build tooling and frontend migration risk before the product surface is stable.

## Recommendation

Choose Option B first. It borrows the strongest Odysseus UI patterns while respecting Beekeeper's current static dashboard, existing API routes, and governance roadmap. Defer a framework rewrite until the panel contracts stabilize.

## Implementation Phases

### Phase 0: Inventory and Contracts

- Inventory current dashboard data sources:
  - `/api/auth/me`
  - `/api/approvals`
  - `/api/reviews`
  - `/api/workers`
  - `/api/workers/registry`
  - `/api/history`
  - `/api/activity/series`
  - `/api/traces`
  - `/api/queen-updates`
  - `/api/audit/logs`
  - `/api/settings/effective`
  - `/api/env`
  - `/api/policy`
- Define panel contracts before UI build:
  - Task summary
  - Task run history row
  - Worker registry row
  - Approval review row
  - Memory inbox item
  - Skill promotion row
  - Audit event row
  - Model/provider profile
- Verify: one markdown/API contract note exists and current endpoints are mapped to each target panel.

### Phase 1: Beekeeper Shell

- Create modular UI assets:
  - `beekeeper_api/static/js/ui.js`
  - `beekeeper_api/static/js/modalManager.js`
  - `beekeeper_api/static/js/sidebar.js`
  - `beekeeper_api/static/js/spinner.js`
  - `beekeeper_api/static/js/theme.js`
  - `beekeeper_api/static/js/api.js`
- Adapt Odysseus shell ideas:
  - sidebar navigation
  - keyboard shortcut registry
  - toast and error surface
  - loading spinners
  - draggable/resizable detail modals only where useful
  - persistent theme choice
- Keep cards flat. Use modals for item detail and approvals, not nested cards.
- Verify: `/dashboard` loads, auth still works, each nav item switches panels, and existing overview data still renders.

### Phase 2: Tasks as Worker Governance

Adapt Odysseus Tasks into Beekeeper's job surface.

Target panels and controls:

- Queue: queued/running/blocked jobs, owner, worker kind, schedule, lease/heartbeat, elapsed time.
- Scheduled Tasks: manual and recurring Queen tasks, next run, cadence, pause/resume.
- Run History: completed/failed/stopped runs with duration, model, cost if available, result summary, evidence links.
- Activity Log: compact status timeline, live updates, retry/stop controls.

Needed task state vocabulary:

- `queued`
- `running`
- `paused`
- `blocked_approval`
- `completed`
- `failed`
- `stopped`

Initial API shape:

- `GET /api/tasks`
- `POST /api/tasks`
- `PUT /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/run`
- `POST /api/tasks/{task_id}/pause`
- `POST /api/tasks/{task_id}/resume`
- `POST /api/tasks/{task_id}/stop`
- `GET /api/tasks/{task_id}/runs`
- `GET /api/tasks/activity`

Verify: create a manual Queen task, run it, see it move through state, stop a running task when supported, and open its run history.

### Phase 3: Approvals as First-Class Gates

- Promote the current HITL card into a full Approvals panel.
- Show pending destructive or permission-sensitive actions with:
  - action type
  - requesting worker
  - Queen rationale
  - policy rule
  - requested target/resource
  - evidence links
  - approve/reject controls
  - optional note
- Keep `/api/approvals` and `/api/reviews` as the backend foundation.
- Verify: approving and rejecting from the panel changes backend state and refreshes the task/activity detail.

### Phase 4: Queen Memory Inbox

Adapt Odysseus Memory UI for Queen durable memory, not worker-local memory.

Target states:

- `proposed`
- `approved`
- `rejected`
- `needs_clarification`

Target flows:

- Search/filter/category/sort
- Edit proposed memory before approval
- Bulk approve/reject
- Import/export
- Tidy/deduplicate
- Link each proposed memory to source task, chat summary, trace, or evidence

Initial API shape:

- `GET /api/memory/inbox`
- `POST /api/memory/inbox/{memory_id}/approve`
- `POST /api/memory/inbox/{memory_id}/reject`
- `POST /api/memory/inbox/{memory_id}/clarify`
- `PUT /api/memory/inbox/{memory_id}`
- `POST /api/memory/import`
- `GET /api/memory/export`
- `POST /api/memory/tidy`

Verify: a proposed memory can be reviewed, edited, approved into durable Queen memory, rejected, and traced back to its source.

### Phase 5: Skills and Worker Promotion Pipeline

Adapt Odysseus Skills UI into a registry and promotion pipeline.

Target skill states:

- `draft`
- `sandboxed`
- `tested`
- `reviewed`
- `approved`
- `active`

Target flows:

- List/search/filter by state, worker kind, source, capability, risk tier, and last audit.
- Open skill/worker detail with manifest, tests, provenance, permissions, and audit evidence.
- Bulk actions for sandbox, test, request review, approve, activate, deactivate.
- Show failure reasons and required next step.
- Keep generated workers experimental until they pass the pipeline.

Initial API shape:

- `GET /api/skills`
- `GET /api/skills/{skill_id}`
- `PUT /api/skills/{skill_id}`
- `POST /api/skills/{skill_id}/sandbox`
- `POST /api/skills/{skill_id}/test`
- `POST /api/skills/{skill_id}/review`
- `POST /api/skills/{skill_id}/approve`
- `POST /api/skills/{skill_id}/activate`
- `POST /api/skills/bulk`

Verify: a draft generated worker can be seen in the list, tested, reviewed, approved, and activated only through explicit state transitions.

### Phase 6: Queen Command Center and Model Settings

- Keep chat as a command center for Queen.
- Show worker outputs as summaries with links:
  - task detail
  - trace
  - result JSON
  - artifact/report
  - approval record
- Do not stream full worker transcripts into chat by default.
- Add provider/model settings profiles:
  - Queen model
  - coding-worker model
  - verifier model
  - memory-curator model
- Include provider health, masked secrets, and "test connection" controls.
- Verify: changing a model profile updates effective config and a test request proves the selected role uses the expected model path.

### Phase 7: Later Panels

Defer until core governance works:

- Email/calendar/notes as input channels.
- Documents/research as artifact/report viewers.
- Codex integration routes as scoped external-access inspiration.
- PWA/mobile shell if Beekeeper becomes always-on and phone-visible.

## Panel Map

| Beekeeper panel | Odysseus pattern to borrow | Beekeeper-specific meaning |
|---|---|---|
| Dashboard | Sidebar shell, compact status cards, activity indicators | Running workers, queue, approvals, recent results |
| Tasks | Tasks list, schedules, run now, pause/resume, stop, history, activity log | Queued/running/completed worker tasks and Queen schedules |
| Workers | Registry/list/detail cards | Worker templates, status, versions, permissions |
| Approvals | Modal detail and action feedback | Pending permission/destructive-action gates |
| Memory | Search, filters, edit, import/export, tidy, bulk mode | Queen memory inbox and durable memory |
| Skills | List/search/status/audit/bulk actions | Skill and worker promotion pipeline |
| Audit | Activity rows, trace links, detail modals | Event timeline, result JSON, worker logs, traces |
| Settings | Provider/model UI, theme, validation | Models, providers, sandbox policy, integrations |

## Acceptance Criteria

- `/dashboard` has stable sidebar navigation with the eight target panels.
- No target panel requires reading full worker transcripts to understand state.
- Every high-risk action shown in the UI has a visible approval/policy/audit path.
- Task detail pages link to history, evidence, approvals, traces, and result JSON.
- Queen memory changes require explicit approval unless policy says otherwise.
- Skill activation cannot skip the promotion pipeline.
- Existing auth and current dashboard endpoints keep working during the migration.

## Risks and Controls

- Risk: importing too much Odysseus behavior. Control: copy patterns and contracts, not runtime architecture.
- Risk: UI gets ahead of backend state. Control: define API contracts before each panel implementation.
- Risk: static JS becomes too large again. Control: one module per panel plus shared primitives.
- Risk: worker transcript sprawl returns through chat. Control: chat links to task detail and evidence instead of embedding full logs.
- Risk: generated workers look production-ready too early. Control: keep state labels explicit and require pipeline transitions.

## Open Questions

- Should task URLs be `/dashboard/tasks/{id}` with client-side routing, or separate static pages like `/task/{id}`?
- Should "Workers" and "Skills" be separate panels forever, or should workers become one filtered view of the skill/promotion registry?
- Which store becomes authoritative for task state before Postgres lands: Honeycomb events, `.beekeeper_store`, Temporal, or a temporary adapter?
- Should memory approval be per-user, per-Queen, per-hive, or per-org by default?
- What is the first supported production model/provider set for the four model roles?
