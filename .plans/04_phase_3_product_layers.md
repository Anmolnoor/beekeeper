# Phase 3: Product Layers

Phase 3 adds new product surfaces only after the native runtime is solid.

The implementation-ready companion for this phase lives in [`04a_phase_3_build_spec.md`](./04a_phase_3_build_spec.md).

## Goal

- Add a browser dashboard on top of the runtime API and trace data.
- Add MCP support only after the native tool runtime is solid.
- Expand policy beyond the minimal approval kernel.
- Add scheduling and recurring jobs after background runs are stable.

## Deliverables

- A browser-based view into runtime state and trace data.
- MCP support layered onto the proven native runtime instead of defining it.
- Broader policy controls than the minimal local approval model used in Phase 1.
- Scheduling and recurring job support built on stable background run semantics.

## Dependencies

- Requires a proven native tool and worker runtime from Phases 1 and 2.
- Requires stable background runs before adding scheduling or recurring jobs.
- Should keep new product layers subordinate to the runtime, not the other way around.

## Exit Criteria

- The dashboard reflects real runtime state rather than a parallel control path.
- MCP and broader policy support fit the existing runtime cleanly.
- Scheduling builds on stable background execution instead of papering over runtime gaps.
