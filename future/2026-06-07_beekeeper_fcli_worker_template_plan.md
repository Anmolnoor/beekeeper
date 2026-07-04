# Beekeeper + FCLI Worker Template Plan

Date: 2026-06-07

## Context and Problem

Beekeeper already has the right control-plane pieces: Queen routing, worker registry, policy/guardrails, approvals, audit traces, scheduler selection, Honeycomb dev traces, and future roadmap docs for durable state and execution separation. `fcli` has the right worker-plane pieces: shell-native execution, typed file/git/shell capabilities, bounded planning loops, approval stop states, provider configuration, bootstrap, and a redacted event stream.

The missing bridge is a governed coding-worker template: Beekeeper should be able to provision and supervise a disposable `fcli`-style worker without absorbing the entire `foundation` CLI as Beekeeper's architecture.

## Goals

- Keep Beekeeper as the durable control plane: admission, routing, policy, approvals, memory, audit, worker registry, and final judgment.
- Turn the useful parts of `fcli` into a versioned worker template for local coding tasks.
- Define a small adapter contract between Beekeeper and the worker: task in, events out, artifacts/results back.
- Keep runtime worker creation disabled or experimental; templates should be pre-provisioned, reviewed, and activated.
- Make this buildable incrementally with tests at each boundary.

## Non-Goals

- Do not merge `fcli` into Beekeeper.
- Do not make Queen execute shell/file/git operations directly.
- Do not copy the whole `foundation` CLI UI into Beekeeper.
- Do not promote worker forge as mature until template provenance, tests, sandboxing, and rollout gates exist.

## Handpick From Beekeeper

| Area | Keep / Use | Why |
|---|---|---|
| Worker registry | `beekeeper/worker_registry.py`, `.honeycomb/workers/registry.json`, plugin manifest flow | Source of truth for installed workers and routing metadata. |
| Worker contracts | `WorkerKind`, `TaskEnvelope`, `ResultEnvelope`, `WorkerContext`, `AgentBlueprint`, `SkillProfile`, `RuleProfile` in `beekeeper/contracts.py` | Gives the template a stable Beekeeper-facing contract. |
| Dispatch boundary | `beekeeper/dispatch_service.py`, Celery/Temporal/inline selection | Lets coding work run outside the API/control-plane process. |
| Admission/run state | `beekeeper/submission_service.py`, durable-state roadmap | Gives every worker run a traceable lifecycle before execution starts. |
| Governance | `beekeeper/tool_runtime.py`, `beekeeper/governance/tool_broker.py`, `policy_adapter.py`, `guardrails.py`, `user_policy.py` | Beekeeper must own permission decisions and side-effect mediation. |
| Approvals | `PolicyDecision`, approval records, HITL defaults | High-risk worker actions should pause at Beekeeper, not inside hidden worker logic. |
| Audit and traces | `HoneycombStore`, `Tracer`, audit compliance tests | Beekeeper needs the final auditable record and operator timeline. |
| Worker promotion | `docs/BUILDING_NEW_WORKERS.md`, `docs/EXTENSION_POINTS.md`, Phase 6 worker forge gates | The template should enter as a governed worker package, not runtime-generated code. |
| Dashboard surfaces | `beekeeper_api/static/dashboard.html`, existing future UI plan | Operator UI should show runs, approvals, events, artifacts, and promotion state. |
| Config validation | `beekeeper/config/settings.py`, `runtime_env.py`, doctor scripts | Template activation should fail closed when provider, sandbox, or queue requirements are missing. |

## Build From FCLI Worker Template

| Area | Source in `fcli` | Template Output |
|---|---|---|
| Bootstrap | `scripts/bootstrap.sh`, `scripts/uv`, `pyproject.toml`, `uv.lock` | Reproducible worker package setup and local dev commands. |
| Provider config | `src/foundation/settings.py`, provider docs | Worker-local provider profile: codex/openai/ollama, timeout, base URL, credential ref. |
| Capability manifests | `models/capability.py`, `services/capabilities.py` | Beekeeper-readable capability manifest for search/files/git/shell. |
| Policy classifier | `services/guardrails.py` | Initial risk classification and requested side-effect extraction. |
| Shell runtime | `services/shell.py` | Workspace-bound command execution with timeout, capture limits, PTY/stream/buffered modes. |
| File runtime | `services/file_service.py`, `models/file.py` | Typed read/write/edit/apply-diff operations with hashes and conflict checks. |
| Git runtime | `services/git_service.py`, `models/git.py` | Typed status/diff/show/log/stage/commit operations with approval boundaries. |
| Orchestration loop | `services/orchestrator.py`, `models/orchestration.py` | Bounded plan/execute/observe loop and terminal stop reasons. |
| Approval semantics | `services/approval.py`, loop stop handling | Worker can request approval, but Beekeeper should own approval resolution. |
| Event stream | `observability.py`, `monitor/*`, `docs/monitor-protocol.md` | NDJSON/SSE event adapter feeding Beekeeper run timeline. |
| Session/history | `services/session.py`, `services/history.py` | Optional worker-local scratch memory, not durable Beekeeper memory. |
| Doctor/tests | `doctor.py`, tests around shell/file/git/provider/orchestrator | Template health checks and contract tests before activation. |

## Options Considered

### Option A: Shell Out to `foundation`

Beekeeper invokes `foundation chat` or `foundation run` as an external process. This is fastest and useful for a spike, but Beekeeper gets a weak contract and must parse CLI behavior.

### Option B: Package an FCLI-Based Coding Worker

Create a worker package that imports selected `foundation` services behind a Beekeeper adapter. Beekeeper passes a `TaskEnvelope`; the worker emits normalized events and returns a `ResultEnvelope` plus artifacts. This is the best first durable architecture.

### Option C: Reimplement FCLI Capabilities Inside Beekeeper

Port shell/file/git/planner logic directly into Beekeeper. This reduces dependency coupling but duplicates a working execution kernel and increases the chance that Beekeeper becomes both control plane and worker plane.

## Tradeoffs

| Option | Cost | Risk | Reversibility |
|---|---|---|---|
| A | Low | Brittle CLI parsing; hidden contract drift | High |
| B | Medium | Requires adapter and versioning discipline | High |
| C | High | Collapses ownership boundary and duplicates logic | Medium |

## Recommendation

Use Option B, with Option A allowed only as a temporary spike. The first shippable target should be a pre-provisioned `coding_worker` template package whose Beekeeper-facing surface is stable even if `fcli` internals continue to change.

## Implementation Plan

1. **Contract inventory** -> verify: write one adapter contract for task input, event envelopes, approval requests, artifacts, and final result.
2. **Template package skeleton** -> verify: package installs locally and exposes one Beekeeper worker entry point.
3. **Read-only coding run** -> verify: worker can inspect workspace status/files and return a trace without mutating files.
4. **Event bridge** -> verify: selected `fcli` events appear in Beekeeper run/activity history with trace IDs.
5. **Approval bridge** -> verify: mutating file/git/shell actions pause as Beekeeper approvals and resume/stop deterministically.
6. **Mutation path** -> verify: typed file edit and git status/diff work in a sandboxed scratch workspace.
7. **Artifact/result handoff** -> verify: final diff, command outputs, test results, and summary are attached to Beekeeper artifacts.
8. **Promotion gates** -> verify: lint/type/test/doctor/template contract tests must pass before worker activation.
9. **UI surface** -> verify: dashboard shows coding-worker runs, live events, approvals, artifacts, and worker health.
10. **Retire spike path** -> verify: Beekeeper no longer depends on parsing `foundation` CLI text for supported runs.

## Decisions I Am Making Now

- The worker template belongs under the developer project area when created, not inside Beekeeper unless we intentionally vendor it later.
- The first template worker should be named `coding_worker`, not `fcli_worker`; Beekeeper should describe capability, not implementation.
- Beekeeper owns durable memory and approvals. Worker-local history is scratch context only.
- Runtime worker auto-spawn stays disabled/experimental. Worker templates are created, reviewed, installed, and activated deliberately.
- The adapter contract should be JSON/NDJSON first so the worker can later run as a process, package, container, or Temporal activity.

## Questions To Grill You On Later

- Do you want the first `coding_worker` to target only this Mac/local repos, or should it be designed from day one for remote worker hosts?
- Should the worker be allowed to commit code, or should it stop at staged diffs until you approve the final commit?
- Should the first implementation live in a new standalone project under `~/Developer`, or as a package folder inside the existing `fcli` repo?

