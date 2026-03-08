# Phase 0: Reset

Phase 0 re-centers the repository on the Beekeeper V1 product definition before any heavy implementation work.

## Goal

- Re-center the repo on the Queen / Worker / Honeycomb metaphor.
- Quarantine platform-heavy features from the new core path.
- Define the new runtime spine around state, trace, artifacts, workers, and CLI control.

## Why This Phase Exists

The current repository has useful ideas, but it carries too many runtime modes and too much platform surface area for the V1 target. This phase creates a clean baseline so the later phases can build on one coherent local-first runtime.

## Deliverables

- A V1-aligned repository narrative centered on one runtime agent and isolated workers.
- Clear separation between V1 core paths and delayed platform-heavy features.
- A defined runtime spine for:
  - durable state
  - append-only trace
  - artifact storage
  - isolated workers
  - CLI control

## Implementation Notes

- Use [`docs/rebuild/main_branch_references.md`](../docs/rebuild/main_branch_references.md) to decide what to reuse from `main`, what to rewrite, and what to delay.
- Keep the Queen / Worker / Honeycomb metaphor intact while reducing architectural sprawl.
- Treat delayed features as intentionally out of scope for the V1 core, not half-supported defaults.

## Exit Criteria

- The repo is framed around one clear V1 runtime path.
- Platform-heavy or premature surfaces are explicitly quarantined from the new core path.
- The runtime spine is defined well enough for Phase 1 implementation to proceed without re-litigating product shape.
