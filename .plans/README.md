# Beekeeper V1 Phased Plan

This directory is the execution-oriented form of the V1 rebuild plan for this branch.

The source overview lives in [`docs/rebuild/v1_plan.md`](../docs/rebuild/v1_plan.md). Shared implementation context from the current `main` branch lives in [`docs/rebuild/main_branch_references.md`](../docs/rebuild/main_branch_references.md).

## V1 Summary

Beekeeper V1 is a local-first, secure, observable agent engine. It runs one runtime agent efficiently, connects that agent to LLMs, and executes real work through isolated workers while tracing, logging, monitoring, and controlling the full lifecycle.

V1 stays intentionally narrow at the start:

- one runtime agent
- real isolated workers
- Postgres-backed state
- append-only trace proof
- MinIO-backed local artifacts
- CLI-first control surface

## Core Architecture

### Runtime Model

- The Queen remains the top-level orchestrator in phase 1.
- Workers are real isolated execution units, not just logical tool labels.
- The agent can loop autonomously until work is complete.
- After each loop, the engine records:
  - current goal
  - what happened in the last step
  - current result or status
  - next intended step
  - whether approval is required before continuing

### Execution Backbone

- Phase 1 uses a Postgres-backed hybrid queue for background jobs.
- The CLI or API creates runs and jobs.
- A local supervisor claims jobs from Postgres and spawns worker subprocesses.
- Worker attempts emit append-only events and separately update current run and job state.

### Truth Model

- State tables represent current truth for runs, jobs, approvals, and worker attempts.
- Trace events represent append-only proof that something happened.
- Artifacts are stored in MinIO locally through an S3-compatible interface.
- Large outputs live in object storage; the database stores metadata and references.

## Phase Order

1. [Phase 0: Reset](./01_phase_0_reset.md)
2. [Phase 1: Working Core Engine](./02_phase_1_working_core_engine.md)
   Build spec: [Phase 1 Build Spec](./02a_phase_1_build_spec.md)
3. [Phase 2: Hardening](./03_phase_2_hardening.md)
   Build spec: [Phase 2 Build Spec](./03a_phase_2_build_spec.md)
4. [Phase 3: Product Layers](./04_phase_3_product_layers.md)
   Build spec: [Phase 3 Build Spec](./04a_phase_3_build_spec.md)
5. [Phase 4: Expansion](./05_phase_4_expansion.md)
   Build spec: [Phase 4 Build Spec](./05a_phase_4_build_spec.md)

## How To Use This Plan

- Start with [Phase 0](./01_phase_0_reset.md) to reset the repository around the V1 runtime spine.
- Use [Phase 1](./02_phase_1_working_core_engine.md) as the first delivery target; it contains the concrete V1 scope, constraints, runtime decisions, and acceptance bar.
- Use [the Phase 1 build spec](./02a_phase_1_build_spec.md) for the exact dependency set, service topology, schema targets, and milestone sequence.
- Use [the Phase 2 build spec](./03a_phase_2_build_spec.md), [the Phase 3 build spec](./04a_phase_3_build_spec.md), and [the Phase 4 build spec](./05a_phase_4_build_spec.md) when you move from roadmap language to implementation.
- Treat [the main-branch reference map](../docs/rebuild/main_branch_references.md) as reuse guidance, not as architecture to preserve.
- Keep `docs/rebuild/v1_plan.md` as the short overview and use this directory for phase-by-phase execution.
