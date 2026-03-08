# Phase 1: Working Core Engine

Phase 1 is the first delivery bar for Beekeeper V1. It defines the working runtime, the supported worker set, the core guardrails, and the acceptance criteria for the narrow initial product.

The implementation-ready companion for this phase lives in [`02a_phase_1_build_spec.md`](./02a_phase_1_build_spec.md).

## Goal

- Deliver one agent that can run real work against LLMs.
- Support foreground and background runs.
- Persist state in Postgres and artifacts in MinIO.
- Emit a full append-only trace tree.
- Ship the Bash, GitHub, Filesystem, and Network workers.
- Keep approvals limited to the minimal kernel needed for local safety.

## Included In Phase 1

- local-first runtime
- one runtime agent
- isolated workers
- Postgres-backed state
- append-only traces
- MinIO-backed artifacts
- background runs
- CLI-first interaction
- minimal local API for control and inspection

## Explicitly Delayed

- MCP integration
- browser dashboard
- desktop app
- worker forge
- multi-agent orchestration
- vector memory
- broad policy engine
- channel integrations
- full platform surfaces

## Worker Set

- `bash`
- `github`
- `filesystem`
- `network`

## Guardrails

- destructive and sensitive actions require approval
- non-allowlisted shell commands require approval
- writes are automatic only inside the allocated workspace
- network is disabled by default and only available through the Network worker
- off-track handling supports kill, retry from last good step, and traceable mistake capture

## Runtime Decisions

### Models

- OpenAI is the primary provider in phase 1.
- Local model fallback is supported after the cloud path is working.
- Model selection is per worker in phase 1.

### Storage

- Postgres is required in phase 1.
- Trace data is append-only.
- Trace is proof; state tables remain the current operational truth.
- MinIO is the default local S3-compatible artifact store.

### Worker And Tool Rules

- Workers remain first-class isolated execution units.
- Network access must flow through the Network worker.
- Shell access supports local shell, SSH, curl, and Docker through allowlist-controlled execution.
- GitHub support includes repo read, issues, PRs, code search, and write actions.

## Acceptance Criteria

Phase 1 is successful when all of the following are true:

- Beekeeper can attach to a local repo and run one agent end to end.
- The agent can use Bash, GitHub, Filesystem, and Network workers to do real work.
- The engine can run jobs in the background and reattach to them later.
- Destructive or non-allowlisted actions stop for approval before execution.
- Every loop and worker call is fully traced with lineage and timing.
- Artifacts are persisted and retrievable.
- A full run can be replayed from the trace tree.
- The dependency-maintenance workflow works in practice:
  - inspect a repo
  - identify deprecated or vulnerable dependencies
  - propose or apply changes
  - produce a clear result with full trace coverage

## Dependencies For Later Phases

- Phase 2 depends on this phase establishing the stable runtime, worker process model, and core approval kernel.
- Phase 3 depends on this phase keeping the API minimal and runtime-centric before adding richer product layers.
