# Beekeeper + FCLI Roadmap Plans

Date: 2026-06-08

## Source

This plan set expands the roadmap in:

- `future/2026-06-08_beekeeper_fcli_inventory_and_v1_roadmap.md`

Supporting context exists in earlier planning docs:

- `future/2026-06-07_beekeeper_fcli_worker_template_plan.md`
- `future/2026-06-05_odysseus_ui_patterns_for_beekeeper_plan.md`

The June 8 roadmap is the source of truth. The earlier docs are used only to add detail where the roadmap already points in the same direction.

## Product Decision

The combined product direction is **Beekeeper Personal**:

> A local personal agent manager that supervises one excellent coding worker, remembers useful context, shows what happened, and asks for approval before risky work.

Beekeeper remains the durable control plane:

- admission
- routing
- run state
- approvals
- memory
- audit
- worker registry
- final judgment

FCLI remains the disposable worker-plane execution kernel:

- workspace inspection
- typed file operations
- typed git operations
- shell command execution
- bounded repair loop
- verification signals
- redacted event stream

The roadmap should not turn Beekeeper into a renamed FCLI. It should also not make FCLI absorb Beekeeper's long-lived assistant, memory, scheduler, or dashboard responsibilities.

## Directory Map

| Folder | Plan file | Main question answered |
|---|---|---|
| `v1/` | `01_personal_mode.md` | How does Beekeeper become a simple local personal manager before worker integration gets complicated? |
| `v2/` | `02_coding_worker_contract.md` | What stable contract lets Beekeeper supervise a coding worker without absorbing FCLI internals? |
| `v3/` | `03_fcli_bridge.md` | How does Beekeeper run or consume an FCLI-grade worker through a machine-readable bridge? |
| `v4/` | `04_policy_approvals_artifacts.md` | How do risky actions, approvals, diffs, verification, and audit evidence become first-class? |
| `vn/` | `05_dashboard_memory_smoke.md` | What ongoing dashboard, memory, and golden-smoke bar proves the whole product path? |

## Roadmap Shape

This version split is intentionally capability-first:

1. **V1 makes the product usable locally.**
   The user can set up Beekeeper in personal mode without understanding the full platform architecture.

2. **V2 defines the worker boundary.**
   Beekeeper and the coding worker get a stable task, event, approval, result, and artifact contract.

3. **V3 proves the execution bridge.**
   Beekeeper can dispatch a coding run and consume machine-readable worker events.

4. **V4 makes risk visible and governable.**
   File changes, shell commands, git actions, approvals, diffs, and verification results are visible and stored.

5. **Vn keeps the product honest.**
   The dashboard, memory surface, and repeatable smoke test become the acceptance bar for every later iteration.

## Cross-Version Principles

- Keep Beekeeper as the supervisor, not the shell executor.
- Keep FCLI as the coding execution kernel, not the personal assistant.
- Prefer local-first defaults until the workflow is proven.
- Do not parse human terminal prose as an integration contract.
- Treat NDJSON or JSON events as the durable bridge shape.
- Do not auto-commit, auto-push, or publish without explicit approval.
- Hide enterprise-grade complexity from personal-mode V1.
- Let every risky side effect produce visible policy, approval, and audit evidence.
- Make every version pass a concrete acceptance bar before expanding scope.

## Open Decisions

These decisions should be made before implementation begins:

1. Should the first coding worker mutate the selected repo directly, or work in a temporary worktree and return a patch?
2. Should the first worker provider be Codex, OpenAI, or Ollama Cloud?
3. Should the dashboard be the primary status surface, with CLI as a fallback, or should both be equal in V1?
4. Should the first bridge shell out to an FCLI command, import FCLI services as a package, or support both behind one adapter?

