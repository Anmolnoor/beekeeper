# Governed Agent Platform Execution Checklist Status

Last audited: 2026-03-07
Source of truth: `future/governed_agent_platform_plan/ALL_PHASES_MASTER_CONTEXT.md`
Audit basis: current repo code, docs, scripts, and passing tests (`141 passed`)
Execution order for the remaining platform-hardening work: `future/governed_agent_platform_plan/11_Ten_Implementation_Steps.md`

## Status legend

- `DONE` = implemented and backed by code/tests/docs
- `PARTIAL` = meaningful implementation exists, but roadmap exit criteria are not yet met
- `MISSING` = not implemented to roadmap standard yet

## Overall status

- Phase 0: `PARTIAL`
- Phase 1: `PARTIAL`
- Phase 2: `PARTIAL`
- Phase 3: `PARTIAL`
- Phase 4: `PARTIAL`
- Phase 5: `PARTIAL`
- Phase 6: `MISSING`

The repo is materially advanced, but the roadmap's target production path is not complete yet. The biggest remaining gaps are:

- authoritative Postgres state instead of local SQLite/dev filesystem defaults
- object storage for artifacts
- real control-plane vs execution-plane separation
- external policy engine and tool broker
- managed secrets and enforced sandbox tiers
- OpenTelemetry-based operability
- governed worker forge pipeline

## Remaining implementation TODOs after the current cut

- switch non-dev runtime from fallback-capable repository selection to true Postgres-only authority, including real dependency wiring and startup/readiness failure when Postgres is unavailable
- replace the S3-shaped dev mirror with a real S3-compatible client path and validate restore/recovery against object storage instead of local mirrors
- move API and channel execution fully off the in-process/threaded admission shim onto durable Temporal submission and worker-driven completion/state updates
- finish extracting planner, routing, dispatch, context loading, and approval coordination out of `beekeeper/queen.py`
- move remaining command bodies from `beekeeper/runner.py` into `beekeeper/cli/commands/` and reduce `runner.py` to compatibility/bootstrap glue
- replace the HTTP policy seam fallback with a real OPA/Rego decision service integration, including persisted input/output correlation and policy bundle/version management
- expand the tool broker from an event/provenance seam into the mandatory execution path for all destructive and externally side-effectful tools
- replace secret-reference support with a production-grade Vault-backed retrieval path, error handling, tenant scoping, rotation handling, and audit evidence for secret usage
- replace sandbox-profile signaling with real execution isolation controls for filesystem, network, secret access, and resource limits
- normalize Slack/session/delivery state into durable control-plane records with retries, dead-letter inspection, and operator-facing drillability
- wire OpenTelemetry traces, metrics, and logs across API admission, queue submission, worker execution, policy, broker, approvals, artifacts, and channel delivery
- upgrade operator/dashboard surfaces to read durable state and telemetry directly instead of relying on Honeycomb event files as the main reconstruction path
- add live Docker-backed end-to-end coverage for golden path, approval path, failure/retry path, Slack delivery path, and Postgres-plus-object-store restore drills
- add worker build/version metadata, rollout checks, rollback checks, and release-gate enforcement for the supported production path
- keep worker forge frozen as experimental and implement the promotion pipeline before any further forge expansion


## Remaining-work TODO list (requested update)

Status snapshot for the four priority tracks:

1. **Priority 1 — Split the Queen**: `PARTIAL`
   - [x] `response_aggregation_service` extracted and wired.
   - [x] Added explicit coordinator services for planning, policy, dispatch, execution-mode selection, and worker forge orchestration.
   - [ ] Continue reducing `queen.py` by moving context and approval orchestration into dedicated service modules.

2. **Priority 2 — Honest layered storage story**: `PARTIAL`
   - [x] Storage tiers documented explicitly (dev/local JSONL/filesystem, prod metadata Postgres, prod event/log pipeline, artifact object storage, vector Qdrant).
   - [ ] Runtime still needs full production backend enforcement and migration off local-first defaults.

3. **Priority 3 — Harden security defaults**: `PARTIAL`
   - [x] Non-dev startup validation now fails closed for webhook secret sets, replay window, secret rotation policy, tenant secret scoping, and tool credential boundaries.
   - [x] Replay-protection configuration validated as required in non-dev mode.
   - [ ] Implement managed rotation orchestration and fully scoped secret backends in runtime execution path.

4. **Priority 4 — Narrow claims**: `DONE`
   - [x] Documentation now explicitly claims: experimental worker forge, prototype dashboard, logical multi-tenancy, and unit-tested core with limited live integration coverage.

## Phase 0 - Baseline, Truth, and Focus

Status: `PARTIAL`

### Checklist

- [x] Support matrix exists
  Evidence: `docs/support-matrix.md`
- [x] Maturity model exists
  Evidence: `docs/maturity-model.md`
- [x] Risk register exists
  Evidence: `docs/risks-and-known-gaps.md`
- [x] Current-state docs exist
  Evidence: `docs/architecture/current-state.md`, `docs/architecture/trust-boundaries.md`, `docs/architecture/storage-classification.md`
- [x] Runtime modes exist (`dev`, `internal`, `prod`)
  Evidence: `beekeeper/config/settings.py`
- [x] Non-dev config validation fails closed on missing critical settings
  Evidence: `beekeeper/config/validators.py`, `tests/test_runtime_config_validation.py`
- [x] `doctor` command exists
  Evidence: `beekeeper/runner.py`, `scripts/doctor.py`, `Makefile`
- [x] `smoke-test` command exists
  Evidence: `beekeeper/runner.py`, `scripts/smoke_test.sh`, `Makefile`
- [x] Clean bootstrap script exists
  Evidence: `scripts/bootstrap_dev.sh`, `Makefile`
- [x] Docs explicitly narrow maturity claims
  Evidence: `README.md`, `docs/support-matrix.md`, `docs/maturity-model.md`
- [ ] Production path is implemented, not just declared
  Gap: docs declare Postgres + Temporal + object storage, but runtime still defaults to local/dev adapters
- [ ] Honeycomb is only a dev audit/event adapter in actual storage behavior
  Gap: Honeycomb still carries significant default persistence responsibility

### Exit gate assessment

- Clean clone bootstrap: `DONE`
- Test collection from current environment: `DONE`
- Public support matrix: `DONE`
- Prod fails closed on missing secrets/config: `DONE`
- Single production path explicitly named: `DONE`
- Single production path actually realized in code/runtime: `MISSING`

### Execute next for Phase 0

1. Remove any remaining ambiguity between declared production path and default runtime path.
2. Make docs and startup output explicitly state when the system is using dev adapters.
3. Stop implying production equivalence for filesystem-backed state in any runtime path.

## Phase 1 - Split the Queen and Shrink the Runner

Status: `PARTIAL`

### Checklist

- [x] Some service extraction has started
  Evidence: `beekeeper/profile_service.py`, `beekeeper/response_aggregation_service.py`, `beekeeper/governance/policy_adapter.py`, `beekeeper/tenancy_context.py`
- [x] Transitional CLI package exists
  Evidence: `beekeeper/cli/main.py`, `beekeeper/cli/commands/health.py`
- [x] Extracted services have tests
  Evidence: `tests/test_profile_service.py`, `tests/test_response_aggregation_service.py`
- [ ] `queen.py` is a thin coordinator
  Gap: `beekeeper/queen.py` remains large and owns multiple concerns
- [ ] `runner.py` is replaced by modular CLI commands
  Gap: `beekeeper/runner.py` remains the real CLI implementation; `beekeeper/cli/main.py` is still a shim
- [ ] Scheduler selection, policy checks, and context loading are isolated behind clear service/port boundaries
  Gap: partial extraction only
- [ ] New features can be added without editing `queen.py` first
  Gap: not true yet

### Exit gate assessment

- `queen.py` reduced to coordinator size: `MISSING`
- `runner.py` replaced by CLI package: `MISSING`
- service-level unit tests exist: `PARTIAL`
- clearer module boundaries: `PARTIAL`

### Execute next for Phase 1

1. Extract routing service from `beekeeper/queen.py`.
2. Extract dispatch service from `beekeeper/queen.py`.
3. Extract planner/context orchestration into explicit services.
4. Move CLI command bodies from `beekeeper/runner.py` into `beekeeper/cli/commands/`.

## Phase 2 - Durable State and Clean Control/Execution Separation

Status: `PARTIAL`

### Checklist

- [x] Durable control-plane repository exists
  Evidence: `beekeeper/data_plane/repositories/sqlite_durable_state.py`
- [x] Run/task/approval/policy/outbox persistence exists
  Evidence: `beekeeper/data_plane/repositories/sqlite_durable_state.py`
- [x] Honeycomb dual-write to durable repository exists
  Evidence: `beekeeper/honeycomb.py`
- [x] Run inspection view exists
  Evidence: `beekeeper_api/routes.py`, `tests/test_dashboard_roadmap_api.py`
- [x] Durable state is covered by tests
  Evidence: `tests/test_phase2_durable_state.py`
- [x] Temporal worker path exists in repo
  Evidence: `beekeeper/temporal_worker.py`, `docker-compose.yml`
- [ ] Authoritative metadata is in Postgres
  Gap: current durable repository is SQLite dev adapter only
- [ ] Artifacts are in S3-compatible object storage
  Gap: artifacts still write to local Honeycomb filesystem
- [ ] Control plane never executes long-running work in-process
  Gap: API routes still call `queen.run(...)` directly
- [ ] Workers continue independently of API process lifetime for the supported path
  Gap: not established as the primary path yet
- [ ] Honeycomb is no longer a major default state layer
  Gap: still central in default execution path

### Exit gate assessment

- API restart does not lose authoritative state: `PARTIAL`
- workers independent from API process lifetime: `PARTIAL`
- filesystem no longer source of truth for state: `MISSING`
- artifacts and state separated: `MISSING`
- run timeline reconstructable from durable records: `DONE`

### Execute next for Phase 2

1. Add Postgres repository implementation behind the current durable-state interface.
2. Add object-storage adapter for artifacts and artifact manifests.
3. Change API/control-plane routes from direct execution to queue/Temporal submission.
4. Keep Honeycomb as a dev mirror only after durable backends are primary.

## Phase 3 - Real Governance, Security, and Sandboxing

Status: `PARTIAL`

### Checklist

- [x] Capability manifests exist
  Evidence: `beekeeper/governance/capability_manifests.py`
- [x] Policy adapter abstraction exists
  Evidence: `beekeeper/governance/policy_adapter.py`
- [x] Replay defense store exists
  Evidence: `beekeeper/replay_store.py`
- [x] Webhook signature/replay checks exist on channel ingress
  Evidence: `beekeeper_api/routes.py`, `beekeeper/channel_auth.py`
- [x] Approval records persist through durable state
  Evidence: `beekeeper/data_plane/repositories/sqlite_durable_state.py`
- [x] Governance tests exist
  Evidence: `tests/test_phase3_governance.py`
- [x] Sandbox tier metadata exists
  Evidence: `beekeeper/governance/capability_manifests.py`, `beekeeper/queen.py`
- [ ] External policy engine exists (OPA/Rego)
  Gap: current implementation is `LocalPolicyAdapter`
- [ ] Tool broker exists and mediates sensitive actions
  Gap: not implemented
- [ ] Managed secret backend is integrated
  Gap: runtime validates for one, but does not implement one
- [ ] Workers run under enforced sandbox profiles
  Gap: sandbox tier is metadata, not runtime isolation
- [ ] Provenance service captures model/tool/provider/build metadata comprehensively
  Gap: only partial event/audit data exists
- [ ] Inbound webhook verification is standardized through one reusable verifier path
  Gap: checks are present but still route-specific

### Exit gate assessment

- prod startup fails on insecure critical config: `DONE`
- side effects cannot bypass policy evaluation: `PARTIAL`
- approvals pause runtime through durable state: `DONE`
- secrets come from managed source in prod: `MISSING`
- webhook paths have signature + replay defense: `PARTIAL`
- workers run under explicit sandbox profiles: `MISSING`
- provenance metadata complete: `MISSING`

### Execute next for Phase 3

1. Replace `LocalPolicyAdapter` with an external-policy client contract.
2. Introduce a tool broker for destructive or externally side-effectful actions.
3. Implement secret references plus a real secret manager adapter.
4. Enforce sandbox profiles at execution runtime, not just in metadata.

## Phase 4 - Operability, Observability, Testing, and Release Discipline

Status: `PARTIAL`

### Checklist

- [x] Operator inspection endpoint exists
  Evidence: `beekeeper_api/routes.py`
- [x] Dashboard/operator surfaces exist
  Evidence: `beekeeper_api/static/dashboard.html`
- [x] Release gate script exists
  Evidence: `scripts/release_gate.sh`
- [x] Recovery drill script exists
  Evidence: `scripts/run_recovery_drill.sh`
- [x] Smoke test and test-collection entrypoints exist
  Evidence: `Makefile`, `scripts/smoke_test.sh`
- [x] Regression/e2e-style pytest coverage exists for approval/failure/retry paths
  Evidence: `scripts/run_e2e.sh`, `tests/test_phase45_regression.py`, `tests/test_phase678_regression.py`
- [ ] OpenTelemetry is implemented
  Gap: referenced in docs only, not wired in code
- [ ] Traces, metrics, and logs correlate across API/control/worker/channel boundaries
  Gap: current operability is mostly Honeycomb trace/audit plus endpoint summaries
- [ ] Live integration/e2e suite covers golden path, approval path, channel path, failure/retry path against real backing services
  Gap: current `run_e2e.sh` runs pytest subsets, not full live stack validation
- [ ] Restore drill validates DB restore plus object-store restore for the target architecture
  Gap: current drill validates local SQLite/Honeycomb restart persistence
- [ ] Worker versioning/rollout/rollback discipline is implemented
  Gap: not present to roadmap standard

### Exit gate assessment

- operator can inspect a run end-to-end: `PARTIAL`
- clean clone can bootstrap/tests/smoke: `DONE`
- one golden path automated: `PARTIAL`
- one approval path automated: `PARTIAL`
- one channel path automated: `PARTIAL`
- one failure/retry path automated: `PARTIAL`
- repeatable restore drill: `PARTIAL`
- release gates documented and enforced: `PARTIAL`

### Execute next for Phase 4

1. Add OpenTelemetry instrumentation for API, Queen, workers, approvals, and channels.
2. Add live full-stack e2e tests against Docker services.
3. Upgrade recovery drill to cover target durable backends.
4. Add worker version/build metadata and release rollout checks.

## Phase 5 - Real Tenancy, Deep Channels, and Product Focus

Status: `PARTIAL`

### Checklist

- [x] Tenant quotas exist
  Evidence: `beekeeper/quotas.py`
- [x] Tenant rate limits exist
  Evidence: `beekeeper/rate_limits.py`
- [x] Tenant controls are enforced in API paths
  Evidence: `beekeeper_api/routes.py`
- [x] Tenant controls are covered by tests
  Evidence: `tests/test_phase5_tenancy_channels.py`
- [x] Support matrix narrows production path and labels experimental areas
  Evidence: `docs/support-matrix.md`
- [x] Channel capability matrix exists
  Evidence: `beekeeper/channel_capabilities.py`
- [x] Slack is marked as the supported channel path
  Evidence: `docs/support-matrix.md`, `beekeeper/channel_capabilities.py`
- [x] Non-Slack channels are blocked in prod mode
  Evidence: `beekeeper_api/routes.py`, `tests/test_phase5_tenancy_channels.py`
- [ ] Tenancy is backed by the target durable architecture
  Gap: current tenancy state is still local-store centric
- [ ] Secrets and artifact access are durably tenant-scoped in the target data plane
  Gap: partial/logical only
- [ ] Slack adapter has full normalized event contract, durable session state, retries, dead-letter handling, and operator-grade observability
  Gap: partial only
- [ ] Operator console is a mature tenancy-aware operations surface
  Gap: current dashboard is useful but still lightweight/prototype level

### Exit gate assessment

- tenant quotas and rate limits exist: `DONE`
- secrets and policy inputs tenant-aware: `PARTIAL`
- operator console can filter and inspect by tenant: `PARTIAL`
- Slack deeply reliable to roadmap standard: `PARTIAL`
- non-reference paths clearly experimental: `DONE`

### Execute next for Phase 5

1. Move tenancy/session/channel state onto the target durable backends.
2. Normalize Slack events and delivery state into a single internal contract.
3. Add durable delivery retry/dead-letter inspection for channel sends.
4. Extend the dashboard into a real tenant-aware operations console.

## Phase 6 - Worker Forge Maturation (Optional)

Status: `MISSING`

### Checklist

- [x] Worker forge exists as an experimental feature
  Evidence: `README.md`, `beekeeper/queen.py`, `tests/test_queen_autonomy.py`
- [x] Docs label worker forge as experimental
  Evidence: `README.md`, `docs/support-matrix.md`, `docs/maturity-model.md`
- [ ] Generated worker promotion pipeline exists
  Gap: no structured spec -> static verification -> contract test -> rollout pipeline
- [ ] Generated workers have signing/attestation
  Gap: not implemented
- [ ] Generated workers have benchmark gate vs generic path
  Gap: not implemented
- [ ] Generated workers have required owner/review/rollback/runbook metadata
  Gap: not implemented
- [ ] Generated workers run in strongest required sandbox tier by default
  Gap: not implemented
- [ ] Generated worker rollout/rollback is routine and versioned
  Gap: not implemented

### Exit gate assessment

- forge is experimental only: `DONE`
- governed promotion pipeline exists: `MISSING`
- generated workers are versioned/tested/sandboxed/signed: `MISSING`
- evidence of value vs generic path: `MISSING`

### Execute next for Phase 6

1. Do not expand worker forge behavior until Phases 0-5 are completed to roadmap standard.
2. Freeze product claims to experimental language only.
3. Design the promotion pipeline before any production-facing forge work.

## Recommended implementation order from current state

1. Finish Phase 1 service extraction so the architecture can absorb the remaining roadmap work cleanly.
2. Finish Phase 2 target data plane: Postgres, object storage, queue-first execution.
3. Finish Phase 3 enforcement: external policy engine, tool broker, managed secrets, sandbox runtime.
4. Finish Phase 4 observability and live e2e/recovery evidence.
5. Finish Phase 5 deep Slack and durable tenancy boundaries.
6. Leave Phase 6 for last.

## Current evidence anchors

- Core status and maturity framing:
  - `README.md`
  - `docs/support-matrix.md`
  - `docs/maturity-model.md`
  - `docs/risks-and-known-gaps.md`
- Durable state and governance:
  - `beekeeper/data_plane/repositories/sqlite_durable_state.py`
  - `beekeeper/honeycomb.py`
  - `beekeeper/governance/capability_manifests.py`
  - `beekeeper/governance/policy_adapter.py`
  - `beekeeper/replay_store.py`
- CLI and operational scripts:
  - `beekeeper/runner.py`
  - `beekeeper/cli/main.py`
  - `Makefile`
  - `scripts/bootstrap_dev.sh`
  - `scripts/run_e2e.sh`
  - `scripts/run_recovery_drill.sh`
  - `scripts/release_gate.sh`
- Tests:
  - `tests/test_phase2_durable_state.py`
  - `tests/test_phase3_governance.py`
  - `tests/test_phase5_tenancy_channels.py`
  - `tests/test_dashboard_roadmap_api.py`
  - `tests/test_runtime_config_validation.py`
  - `tests/test_queen_autonomy.py`
