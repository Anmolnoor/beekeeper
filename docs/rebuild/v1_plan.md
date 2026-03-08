# Beekeeper V1 Rebuild Plan

This document is now the short overview for the branch-local V1 rebuild plan. The detailed, execution-oriented version lives under [`/.plans`](../../.plans/README.md).

## Product Definition

Beekeeper V1 is a local-first, secure, observable agent engine. It runs one runtime agent efficiently, connects that agent to LLMs, and executes real work through isolated workers while tracing, logging, monitoring, and controlling the full lifecycle.

V1 stays intentionally narrow at the start:

- one runtime agent
- real isolated workers
- Postgres-backed state
- append-only trace proof
- MinIO-backed local artifacts
- CLI-first control surface

## How This Plan Is Structured

- [`../../.plans/README.md`](../../.plans/README.md) is the main entrypoint for the phased plan.
- [`../../.plans/01_phase_0_reset.md`](../../.plans/01_phase_0_reset.md) covers the repo reset and runtime-spine definition.
- [`../../.plans/02_phase_1_working_core_engine.md`](../../.plans/02_phase_1_working_core_engine.md) contains the concrete V1 delivery bar, scope, runtime decisions, and acceptance criteria.
- [`../../.plans/03_phase_2_hardening.md`](../../.plans/03_phase_2_hardening.md) covers hardening after the core engine is working.
- [`../../.plans/04_phase_3_product_layers.md`](../../.plans/04_phase_3_product_layers.md) covers dashboard, MCP, broader policy, and scheduling work.
- [`../../.plans/05_phase_4_expansion.md`](../../.plans/05_phase_4_expansion.md) covers later expansion beyond the proven single-agent core.

## Phase Summary

### Phase 0: Reset

Re-center the repo on the Queen / Worker / Honeycomb metaphor, quarantine platform-heavy features from the new core path, and define the runtime spine around state, trace, artifacts, workers, and CLI control.

### Phase 1: Working Core Engine

Deliver one runtime agent with isolated workers, Postgres-backed state, MinIO-backed artifacts, append-only trace coverage, background runs, and the minimum approval kernel needed for safe local execution.

### Phase 2: Hardening

Strengthen worker isolation, recovery, retries, leases, heartbeats, model policy refinement, and sandboxed validation while keeping the runtime shape narrow.

### Phase 3: Product Layers

Add the browser dashboard, MCP support, broader policy, and recurring job support only after the native runtime is solid.

### Phase 4: Expansion

Add optional multi-agent orchestration, richer desktop and web surfaces, and broader worker or memory layers only after the earlier phases are proven.

## Supporting Context

- [`main_branch_references.md`](./main_branch_references.md) captures what to reuse, rewrite, delay, or exclude from the current `main` branch.
- `.plans/` is the stable location for phased execution docs in this branch.
