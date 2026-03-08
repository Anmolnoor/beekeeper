# Phase 2: Hardening

Phase 2 strengthens the working core engine after the Phase 1 path is real and stable.

The implementation-ready companion for this phase lives in [`03a_phase_2_build_spec.md`](./03a_phase_2_build_spec.md).

## Goal

- Add stronger worker isolation and recovery semantics.
- Improve retries, leases, heartbeats, and stuck-job handling.
- Add local model fallback and per-worker model policy refinement.
- Add sandboxed validation steps for repo maintenance workflows.
- Add skills as thin reusable recipes over native workers.

## Deliverables

- More robust worker execution boundaries and failure recovery.
- Better operational handling for long-running or stuck background jobs.
- Tighter model selection controls once the primary cloud path is working.
- Validation steps that keep maintenance workflows safer and more reproducible.
- Skills layered on top of the native worker model rather than replacing it.

## Dependencies

- Requires the Phase 1 core runtime, background run path, and trace model to be stable.
- Should preserve the narrow V1 runtime shape rather than expanding product surfaces early.

## Exit Criteria

- Worker isolation and recovery are materially stronger than the initial delivery bar.
- Background execution semantics are more resilient under retry, lease, and failure conditions.
- Skills and validation steps fit the native worker model cleanly.
