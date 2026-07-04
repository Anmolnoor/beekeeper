# Beekeeper + FCLI Inventory and V1 Roadmap

Date: 2026-06-08

## Read Scope

This pass reviewed both local checkouts and the public GitHub metadata:

- Beekeeper: `Anmolnoor/beekeeper`, local `main` at `cfaf9dfe51c4d968e696e677fc2cdabb0c9596a5`.
- FCLI / Foundation CLI: `Anmolnoor/fcli`, local `main` at `d00ab9892a1cc1d33fd27583d5c1e7dcbb783649`.
- Beekeeper currently has pre-existing uncommitted local changes outside this planning doc. FCLI is clean.
- GitHub metadata confirms both repos are public Python projects:
  - Beekeeper: governed agent runtime with tool-level policy enforcement, AGPL-3.0.
  - FCLI: local-first shell-native coding agent, MIT.

Local size snapshot:

| Project | Python modules | Python LOC | Test files | Test definitions |
|---|---:|---:|---:|---:|
| Beekeeper | 92 | 22,701 | 27 | 162 |
| FCLI | 44 | 23,626 | 39 | 481 |

## Product Read

### Beekeeper

Beekeeper is trying to be a personal agent manager with a governed-agent-runtime spine:

- Queen orchestrates.
- Workers execute.
- Pulse schedules.
- Honeycomb remembers and audits.
- HITL approvals gate risky actions.
- MCP connects external tools.
- Worker Forge can create tools, but is still experimental.

The stronger product framing is not "enterprise multi-agent platform first." It is:

> A personal agent manager that can supervise workers, remember context, schedule work, call tools, ask for approval, and keep an audit trail.

The enterprise-grade architecture is useful, but it should not dominate V1.

### FCLI

FCLI is a local-first coding-agent execution kernel:

- It has a real `plan -> approve -> execute -> observe` loop.
- It can read/edit files, inspect git, run shell commands, verify work, recover from errors, and emit detailed traces.
- It is not a long-lived personal assistant, scheduler, memory manager, or multi-worker control plane.

The strongest use for FCLI inside the combined vision is as a disposable coding worker, not as the product shell.

## What Beekeeper Has

### Control Plane and Personal Agent Pieces

| Capability | What exists | Current fit |
|---|---|---|
| Queen orchestration | `beekeeper/queen.py`, planner/routing/worker dispatch | Good core, still too much logic in one module. |
| Worker registry | `beekeeper/worker_registry.py`, plugins, registry files | Good for installed/pre-provisioned workers. |
| Worker runtime | `beekeeper/worker.py` with web, compute, audit, context curator, file, bash, forged | Good primitives, but coding loop is weaker than FCLI. |
| Personal memory | `user_memory.py`, ContextCurator, Honeycomb memory writes, vector store | Good foundation; weak user-facing memory management. |
| Scheduling | `pulse.py` cron/backlog/Queen jobs | Strong for personal-agent-manager vision; weak chat/UI creation flow. |
| HITL approvals | Honeycomb review queue, review CLI/API/dashboard paths | Strong concept; needs cleaner UX and coding-worker bridge. |
| Governance | guardrails, policy adapter, tool broker, user policy | Strong differentiator; too much for V1 if all enabled. |
| Tool loop | `tool_runtime.py`, `tool_adapters.py`, execution modes | Good model-tool runtime; should remain Beekeeper-owned. |
| MCP | `mcp_adapter.py`, `mcp_transport.py` stdio/HTTP/SSE registration | Valuable, but not required for first V1 path. |
| Channels | Slack, Telegram, Discord, WhatsApp, transcription | Useful later; V1 should not claim broad channel depth. |
| APIs | Beekeeper API and OpenAI-compatible Queen API | Strong surface area; V1 can use a narrowed subset. |
| Dashboard | Static HTML pages: dashboard, activity, trace, audit, setup | Useful prototype; needs focused V1 panels. |
| Setup/runtime config | setup wizard, env, doctor, runtime-mode validation | Good but currently too broad/heavy. |
| Durable execution | inline/Celery/Temporal dispatch service | Keep inline/local for V1; Temporal is later. |
| Tenancy | org/hive/queen/user store | Built but should be hidden in personal V1. |
| Worker Forge | auto-spawn/generated workers | Built/experimental; not V1-critical. |

### Beekeeper Gaps

| Gap | Why it matters |
|---|---|
| Product focus is split | The code says governed runtime; vision says personal agent manager. V1 needs one user story. |
| Setup is too heavy | Personal V1 cannot require users to understand nine services. |
| Coding worker is not mature | Basic `file_system` and `bash` workers exist, but not a robust coding-agent loop. |
| Dashboard is prototype-grade | Needs runs, approvals, memory, worker activity, and artifacts as first-class panels. |
| Control and execution still blur | API routes and Queen paths still execute too much in-process. |
| Worker Forge is ahead of proof | Generated workers need promotion gates before product claims. |
| Production path is not V1 | Postgres/Temporal/S3/OPA/OTel are important but should not block personal V1. |

## What FCLI Has

### Execution Kernel Pieces

| Capability | What exists | Current fit |
|---|---|---|
| Agent entrypoint | `foundation`, `foundation chat`, one-shot requests | Good standalone CLI; Beekeeper should not copy the UI. |
| Typed file capabilities | read, read_chunk, write, edit, apply_diff | Strong; should become the coding-worker file layer. |
| Typed git capabilities | status, diff, show, log, stage, unstage, commit approval | Strong; V1 should use status/diff/log and gate commit. |
| Shell runtime | buffered/stream/PTY, workspace boundary, timeouts, output capture | Strong; better than Beekeeper's current bash worker. |
| Capability registry | built-in manifests for search/files/git/help/shell | Strong adapter material for Beekeeper worker manifest. |
| Policy engine | capability risk, side effects, scope checks, approvals | Strong execution-side classifier; Beekeeper should own final policy. |
| Bounded replanning | read/edit/run/fix loop with hard caps and stop reasons | This is the main coding-worker value. |
| Verification taxonomy | passed/failed/unavailable/not attempted | Good V1 artifact and UI signal. |
| History/trace | SQLite sessions, approvals, tool calls, trace graph | Good local worker trace; Beekeeper needs normalized summary. |
| Event stream | redacted NDJSON plus optional Unix socket / local HTTP SSE | Best bridge surface for Beekeeper. |
| Provider adapters | Codex, OpenAI, Ollama, config + keychain/env support | Useful; V1 should support one configured worker provider. |
| Live terminal UX | concise output, live status line, prompt/session polish | Good standalone experience; not the Beekeeper UI. |
| Bootstrap/testing | `scripts/bootstrap.sh`, `scripts/uv`, strict mypy, 481 tests | Strong quality bar for the worker. |

### FCLI Gaps

| Gap | Why it matters |
|---|---|
| No personal manager layer | It does not schedule life/work tasks, manage worker teams, or own durable personal memory. |
| No channel/API/dashboard surface | Great CLI, weak product shell for a personal agent manager. |
| No long-lived control plane | It is designed per workspace/session, not as a supervisor of many workers. |
| Networked git/PR automation missing | Push/fetch/pull/PR are out of scope today. |
| External tools not executable beyond local modeled capabilities | No MCP-style external tool ecosystem in the runtime. |
| Approvals are local to a run | Beekeeper needs durable approval records and review UX. |
| Not a worker package yet | It needs an adapter/contract to be supervised by Beekeeper. |

## Combined Product Decision

Build **Beekeeper Personal V1**:

> A local personal agent manager that supervises one excellent coding worker, remembers useful context, shows what happened, and asks for approval before risky work.

This gets the best of both worlds:

- Beekeeper contributes the long-lived personal assistant, memory, scheduling, approvals, dashboard, API, and governance.
- FCLI contributes the coding-worker execution kernel: file/git/shell capabilities, bounded repair loop, verification, and event stream.

Do not make V1 an enterprise platform. Do not make V1 just a renamed FCLI. Do not make Worker Forge the headline.

## V1 Minimal Scope

### V1 Goal

A user should be able to open Beekeeper, ask for a coding task in a local repo, watch a supervised worker run, review the result/diff/test outcome, and approve or reject risky final actions.

### V1 User Story

1. User runs personal setup.
2. User connects/selects a local repo.
3. User asks: "Fix this bug" or "Add this small feature."
4. Beekeeper creates a run and dispatches `coding_worker`.
5. `coding_worker` uses FCLI-grade read/edit/run/fix behavior.
6. Beekeeper displays events, final diff, verification, artifacts, and any approval needs.
7. Beekeeper stores the run and learns durable user/project preferences.

### V1 Must-Haves

| Item | Source project | Build shape |
|---|---|---|
| Personal mode | Beekeeper | `beekeeper setup --personal` or equivalent defaults: one user, one hive, local storage, one provider, no channel complexity. |
| Coding worker | FCLI + Beekeeper | A Beekeeper worker named `coding_worker`, using FCLI execution as the kernel. |
| Worker contract | New bridge | JSON task input, NDJSON events, approval/status events, final result/artifact schema. |
| Event bridge | FCLI | Consume FCLI redacted NDJSON events and map to Beekeeper activity/trace events. |
| Local repo selection | Beekeeper | Register/select a local workspace under the developer folder or existing repo path. |
| File/git/shell execution | FCLI | Typed file/git/shell capabilities, workspace-confined, no broad shell mutation. |
| Verification result | FCLI | Surface passed/failed/unavailable/not attempted in Beekeeper run detail. |
| Approval posture | Both | V1 allows workspace file edits and verification; blocks commit/push/destructive/network actions unless explicitly approved. |
| Final diff/artifacts | FCLI + Beekeeper | Store diff, changed files, command summaries, and final answer as Beekeeper artifacts/events. |
| Runs dashboard | Beekeeper | Minimal panel: queued/running/completed/failed, live events, changed files, verification, approval state. |
| Approval dashboard | Beekeeper | Use existing approvals but focus on coding-worker decisions. |
| Memory basics | Beekeeper | Show/list durable memories and allow deletion/editing at least from CLI or simple UI. |
| Doctor/smoke | Both | One command verifies provider, workspace, worker executable, event bridge, and a tiny read-only coding run. |

### V1 Explicit Non-Goals

| Not in V1 | Reason |
|---|---|
| Full multi-tenancy | Built in Beekeeper, but it distracts from the personal-agent-manager path. |
| Broad Slack/Telegram/Discord/WhatsApp claims | Channels exist, but V1 should prove one local personal workflow first. |
| Production Postgres/Temporal/S3/OPA | Important later; too heavy for V1. |
| Worker Forge promotion | Experimental; keep it behind a later promotion pipeline. |
| Automatic commits/pushes/PRs | Too much blast radius for V1. Commit can be approval-gated later. |
| Remote worker hosts | Start on this Mac/local repos. |
| Full SPA rewrite | Use focused improvements to existing static UI first. |
| Natural-language schedule creation | Pulse exists; chat-created schedules can be V2. |

## V1 Implementation Plan

1. **Personal defaults**
   - Add or formalize `setup --personal`.
   - Hide org/hive/queen complexity behind defaults.
   - Verify: fresh local config can start Beekeeper and open chat/dashboard without Docker stack knowledge.

2. **Coding-worker adapter contract**
   - Define `CodingWorkerTask`, `CodingWorkerEvent`, `CodingWorkerResult`.
   - Include workspace path, user request, provider profile, allowed side effects, run ID, trace ID.
   - Verify: schema tests and one sample NDJSON trace.

3. **FCLI process bridge first, package adapter second**
   - V1 can start by invoking `foundation` as a subprocess and consuming its NDJSON event log.
   - Do not parse terminal prose as the contract.
   - Later replace subprocess invocation with imported services or a package worker if needed.
   - Verify: a read-only prompt emits events and returns a normalized Beekeeper result.

4. **Workspace and side-effect policy**
   - Use a selected local repo/workspace root.
   - Allow file reads, file edits, shell verification, git status/diff/log.
   - Block or require approval for commit, push, network, destructive shell, out-of-workspace paths.
   - Verify: tests for allowed edit, blocked commit, blocked path escape.

5. **Run timeline and artifacts**
   - Map FCLI events into Beekeeper run/activity records.
   - Store final summary, changed files, diff, verification, and command previews.
   - Verify: dashboard/API can retrieve a full run timeline after completion.

6. **Approval UX**
   - Reuse Beekeeper approval queue.
   - V1 does not need perfect mid-run resume; it must clearly stop and tell the user what approval is needed.
   - Verify: blocked action creates one pending approval with reason, target, and trace link.

7. **Memory surface**
   - Add a simple view/command for "what Beekeeper knows about me/project."
   - Let the user delete or edit bad memories.
   - Verify: one remembered preference appears in the list and can be removed.

8. **Focused dashboard**
   - Panels: Runs, Approvals, Memories, Workers.
   - No marketing UI. No broad admin maze.
   - Verify in browser: run appears, live/progress events render, final artifact opens.

9. **Golden smoke**
   - One tiny local repo task:
     - inspect files,
     - make a small edit,
     - run a verification command,
     - return diff and summary.
   - Verify: Beekeeper records the run, artifacts, approval posture, and memory update.

## V1 Acceptance Bar

V1 is real only when all are true:

- `beekeeper` can start in personal mode with one provider and local storage.
- `coding_worker` can complete a small code task in a local repo.
- File/git/shell actions are workspace-confined and visible.
- Beekeeper shows the run timeline, final diff, verification status, and artifacts.
- Risky actions do not disappear into the worker; they are blocked or approval-gated.
- Beekeeper remembers useful context and lets the user inspect/edit/delete it.
- There is one repeatable smoke test proving the full path.

## Already Built But Not V1

### In Beekeeper

| Built thing | Version to use |
|---|---|
| Temporal/Celery production execution path | V3 |
| Postgres/object-store production state | V3 |
| OPA/Rego external policy path | V3 |
| OpenTelemetry production correlation | V3 |
| Full multi-tenancy | V3/V4 |
| Slack-first production channel | V3 |
| Telegram/Discord/WhatsApp breadth | V4 |
| Worker Forge/generated workers | V4/Vn |
| MCP tool ecosystem | V2 |
| OpenAI-compatible Queen API | V2 |
| Audit export/compliance reports | V3 |
| Static dashboard broad admin surfaces | Narrowed in V1, expanded V2 |

### In FCLI

| Built thing | Version to use |
|---|---|
| Interactive `foundation` shell UX | Useful standalone, not Beekeeper V1 core |
| Full trace/history CLI inspection | V2, surfaced through Beekeeper UI/API |
| Live Unix/HTTP event transports | V2, after V1 NDJSON file bridge works |
| Git commit support | V2, approval-gated |
| Networked git/PR automation | V3 |
| Manual playbook capability evaluation | V2/V3 as worker regression suite |
| Provider comparison/testing harnesses | V2/V3 |
| Full CLI refactor/thin entrypoint work | Helps maintenance, not product surface |

## V2 Roadmap

V2 should make V1 feel like a real personal assistant, not just a coding-run supervisor.

| Theme | Work |
|---|---|
| Better approval bridge | Mid-run approval pause/resume, not just stop-and-rerun. |
| Natural-language scheduling | "Every weekday at 9, check X" creates Pulse jobs. |
| Memory inbox | Proposed/approved/rejected/needs-clarification memory states. |
| Worker health | Show worker version, provider, last run, failure rate, capabilities. |
| MCP in personal mode | Add one or two real external MCP servers with explicit allowlists. |
| Commit approval | Allow git commit after user approval; never push by default. |
| GitHub integration | Inspect issues/PRs through approved tools; no automatic publish yet. |
| Better dashboard | Runs, approvals, memory, workers, schedules, settings as focused panels. |
| Regression harness | Adapt FCLI manual playbook into Beekeeper coding-worker acceptance tests. |

## V3 Roadmap

V3 should harden the architecture without losing the personal product.

| Theme | Work |
|---|---|
| Durable execution | Move supported long-running work to Temporal, not API threads. |
| Durable state | Postgres for runs/tasks/approvals/policy/tool calls. |
| Artifact storage | S3-compatible object storage or local object adapter with checksums. |
| Policy contract | External policy adapter/OPA-compatible input and obligations. |
| Secret references | Managed secret refs, not ambient secrets. |
| Sandbox enforcement | Stronger sandbox/worktree/container profiles for coding workers. |
| Observability | OpenTelemetry correlation across Beekeeper and coding-worker events. |
| Slack depth | One real channel with production-depth verification. |
| Restore drills | Prove restart/resume/artifact recovery for admitted work. |

## V4 Roadmap

V4 can expand the agent manager after the core is trustworthy.

| Theme | Work |
|---|---|
| Worker Forge promotion | Generated workers must pass spec, static checks, tests, sandbox, benchmark, provenance, rollout. |
| Worker catalog | Approved worker templates with versions, owners, capabilities, and deprecation dates. |
| Multi-channel personal assistant | Telegram/Discord/WhatsApp/voice after one channel is strong. |
| Mobile/remote companion | Only after auth, approvals, and audit are reliable. |
| PR automation | Branch, commit, push, and open PR with explicit approvals and audit evidence. |
| Team mode | Reintroduce multi-tenancy as a product mode, not the default. |

## Vn Ideas

- Marketplace for skills, workers, prompts, and MCP bundles.
- Cross-machine worker fleet.
- Full compliance exports and signed attestations.
- Budget/cost governance across workers and providers.
- Long-running research/coding workflows with pause/resume over days.
- Voice loop and proactive assistant behavior.
- Generated worker lifecycle with automatic expiration and review cadence.

## Decisions I Am Making

- V1 should be **personal local-first**, not enterprise.
- The first integrated worker should be called `coding_worker`, not `fcli_worker`.
- The worker can be implemented under the developer folder as a separate project/package when created.
- Beekeeper owns memory, schedules, approvals, run state, worker registry, and final judgment.
- FCLI owns code inspection, edits, command execution, verification, and execution events.
- V1 should use FCLI's NDJSON/event protocol as the bridge; do not parse human terminal text.
- V1 should not auto-commit, auto-push, or silently run broad network/destructive commands.

## Questions To Answer Before Implementation

These do not block the roadmap, but they should be answered before code work starts:

1. Should V1 mutate the selected repo directly, or run in a temporary worktree and return a patch?
2. Should the first provider for the coding worker be Codex, OpenAI, or Ollama Cloud?
3. Should Beekeeper V1 be CLI-first, dashboard-first, or both with the dashboard as the primary status surface?

