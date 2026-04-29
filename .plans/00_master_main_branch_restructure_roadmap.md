# Main-Branch Restructure Master Roadmap

## Preamble
This roadmap is an **in-place restructure plan for `main`**, not a rebuild plan. It treats the currently tracked repository as the baseline system, then narrows and hardens the supported path over five phases.

## Do Not Rebuild — Hard Constraints
1. **Preserve working runtime spine.** Keep the running path operational while restructuring; do not replace `main` with a clean-slate architecture.
2. **Migrate incrementally.** Land changes in controlled slices with compatibility boundaries and explicit cutover rules.
3. **Keep compatibility shims where needed.** Maintain adapters/shims until replacement paths are verified and adopted.
4. **Remove breadth from defaults before removing code from the repo.** First narrow support claims and default entrypoints; only then consider deeper retirement.

## Support Status Vocabulary (Roadmap-Wide)
| Support status | Meaning in this roadmap | Required disposition tag(s) |
|---|---|---|
| `supported` | Primary path for production claims and release gates | `reuse as-is`, `reuse but narrow`, `migrate behind new seam` |
| `legacy` | Still present and usable for transition, not default | `reuse but narrow`, `migrate behind new seam` |
| `experimental` | Available for development/exploration only | `quarantine as experimental` |
| `deferred` | Explicitly outside the 5-phase execution bar | `defer beyond the 5-phase roadmap` |

## Source Appendix (Merged Inputs)
This master file merges and reconciles the following tracked sources:

### Governed platform roadmap inputs
- `future/governed_agent_platform_plan/00_README_Roadmap.md`
- `future/governed_agent_platform_plan/01_Phase_0_Baseline_Truth_and_Focus.md`
- `future/governed_agent_platform_plan/02_Phase_1_Split_Queen_and_Runner.md`
- `future/governed_agent_platform_plan/03_Phase_2_Durable_State_and_Execution_Plane.md`
- `future/governed_agent_platform_plan/04_Phase_3_Security_Policy_and_Sandboxing.md`
- `future/governed_agent_platform_plan/05_Phase_4_Operability_Testing_and_Release.md`
- `future/governed_agent_platform_plan/06_Phase_5_Tenancy_Channels_and_Product_Focus.md`
- `future/governed_agent_platform_plan/08_Verification_Matrix_Against_Points_4_5_6.md`
- `future/governed_agent_platform_plan/10_Execution_Checklist_Status.md`
- `future/governed_agent_platform_plan/11_Ten_Implementation_Steps.md`

### Baseline/current-state grounding inputs
- `future/2026-03-06_current_queen_worker_architecture_baseline.md`
- `docs/risks-and-known-gaps.md`
- `docs/architecture/current-state.md`
- `docs/architecture/storage-classification.md`
- `docs/support-matrix.md`
- `docs/maturity-model.md`

### March 6 supporting inputs (migration/quarantine sharpening only)
- `future/2026-03-06_dual_capability_run_create_workers_policy_control_plan.md`
- `future/2026-03-06_queen_reuse_existing_workers_migration_plan.md`
- `future/2026-03-06_audit_trace_standards_and_improvement_plan.md`
- `future/2026-03-06_service_and_report_workflow_findings.md`

### Planning-tree note
At planning time, no existing `.plans/` document set was present in the tracked tree. Therefore this file is the initial `.plans/` source of truth unless additional `.plans/` docs are added before implementation work that depends on them.

## Current-State Inventory (Repo-Truth Grounded)
| Bucket | Subsystem | Current evidence | Disposition tag |
|---|---|---|---|
| canonical now | Core orchestration path | `beekeeper/queen.py` and `beekeeper/runner.py` still hold the live orchestration/CLI behavior; `beekeeper/cli/main.py` is a shim to `runner.py`. | `reuse as-is` |
| canonical now | API/control surfaces | `queen_api` and `beekeeper_api` both exist; `queen_api` is the intended supported runtime-facing surface, while broader legacy/admin behavior remains in `beekeeper_api`. | `reuse but narrow` |
| canonical now | Runtime-mode and support posture controls | Runtime-mode validation and support/maturity docs exist and already distinguish safer production posture from broader code availability. | `reuse as-is` |
| reusable but legacy | Honeycomb-centric timeline/store flows | Honeycomb/file-backed paths are still deeply used in operational defaults and developer workflows. | `migrate behind new seam` |
| reusable but legacy | Broad compose/default topology | `README.md` and `docker-compose.yml` still narrate/start a broad stack (temporal/qdrant/pulse/multi-surface APIs/channels). | `reuse but narrow` |
| reusable but legacy | Dashboard/admin breadth | Dashboard and admin surfaces cover more than canonical runtime/governance/operator inspection. | `migrate behind new seam` |
| experimental | Worker forge and dynamic generation | Forge/generation is available in repo narrative and code but not a supported core path. | `quarantine as experimental` |
| experimental | MCP/plugin/pulse breadth, non-Slack channels, multi-scheduler breadth | Available in code/docs; verification depth and support status are narrower than breadth implies. | `quarantine as experimental` |
| deferred | Worker-forge maturation and broad expansion programs | Old Phase 6 style maturation work exists as optional future program, not part of the 5-phase restructure bar. | `defer beyond the 5-phase roadmap` |
| deferred | Broad multi-channel and retrieval/platform expansion | Plugin/forge/MCP/retrieval/pulse/channel expansion remains backlog until canonical runtime and governance are complete. | `defer beyond the 5-phase roadmap` |

---

## Phase 1 — Baseline Consolidation + Canonical Spine Declaration
### What already exists in code
- Live orchestration still runs primarily via `beekeeper/queen.py` and `beekeeper/runner.py`.
- `beekeeper/cli/main.py` exists but is currently a compatibility shim to `runner.py`.
- `queen_api` exists as the intended runtime-facing API surface.
- Runtime-mode, support-matrix, and maturity controls already exist in docs/tests.
- `README.md` and `docker-compose.yml` still advertise broader stack breadth beyond what should be treated as equally supported.

### What must remain
- Working Queen/Runner behavior while migration seams are introduced.
- `queen_api` as the preferred API/runtime narrative target.
- CLI migration destination behind `beekeeper/cli/main.py` as the future supported command surface.
- Existing support-matrix/runtime-mode guardrails that enforce fail-closed posture in stricter modes.

### What is missing / gap
- No tracked `beekeeper/runtime/*` source implementation currently exists; it is a gap, not a finished spine.
- Canonical path and legacy/experimental breadth are not yet consistently separated across defaults, docs, and entrypoints.
- Multiple surfaces still appear peer-supported by default narrative.

### Restructure work
- Fold all prior Phase 0/reset/baseline material into this phase as the first execution step.
- Formally define the preferred spine narrative around: `queen_api`, durable-state repositories, runtime-mode/support-matrix controls, and the intended CLI migration behind `beekeeper/cli/main.py`.
- Explicitly document present truth that the tracked repo still executes primarily through `queen.py` + `runner.py`.
- Reclassify defaults and claims:
  - Forge, MCP/plugin/pulse breadth, non-Slack channels, multi-scheduler breadth, and dashboard breadth are `legacy` or `experimental` unless promoted later.
- Publish one subsystem-by-subsystem support-status mapping (`supported`, `legacy`, `experimental`, `deferred`) tied to disposition tags.

### Risks and sequencing constraints
- Premature default rewiring could break currently working CLI/API flows.
- Narrowing claims without clear compatibility language can confuse operators.
- If runtime-source gaps are not called out, teams may assume non-existent spine code is already complete.

### Exit criteria
- One canonical runtime path is documented with explicit current-vs-target truth.
- Live `queen.py`/`runner.py` path remains available as migration surface, not roadmap destination.
- Default narrative no longer treats all available breadth as equally supported.

### Tests / proof required
- Canonical-path smoke proof for CLI, API, worker/supervisor ownership boundaries, and compose topology.
- Explicit documentation of today’s shim reality (`beekeeper/cli/main.py` -> `runner.py`) and missing runtime-source gap.
- Structure/content validation that support statuses and disposition tags are applied consistently.

## Phase 2 — Durable Runtime State as Authority
### What already exists in code
- Storage-classification and current-state documents already define durable metadata vs event/artifact/vector roles.
- Honeycomb/filesystem paths and migration-era persistence mechanisms remain active in current flows.
- Trace/audit concepts and artifacts exist, but authority boundaries are still mixed.

### What must remain
- Safe migration fallback paths for local dev and transition.
- Append-only trace/audit usability for developer/operator inspection.
- Object-store-backed artifact payload handling.

### What is missing / gap
- One authoritative durable contract for runs, jobs/tasks, approvals, attempts, trace metadata, and artifact metadata.
- Clear source-of-truth cutover where SQLite/filesystem/Honeycomb are fallback or mirror only.
- Durable restart/resume semantics consistently anchored to runtime records.

### Restructure work
- Make durable runtime records authoritative for:
  - runs
  - jobs/tasks
  - approvals
  - policy decisions linkage
  - attempts/retries
  - trace metadata
  - artifact metadata (with object-store payloads)
- Restrict SQLite/filesystem/Honeycomb to local-dev fallback and migration mirror roles only.
- Define read/write cutover and dual-write retirement sequencing for legacy flows.
- Keep Honeycomb positioned as trace/audit adapter, not production data-plane truth.

### Risks and sequencing constraints
- Partial dual-write can produce drift without strong reconciliation checks.
- Restart/resume behavior can regress if supervisors still depend on legacy side state.
- Artifact and trace metadata split-brain risk during cutover windows.

### Exit criteria
- Durable runtime records are the declared and enforced authority.
- API/process restarts do not lose run/task/approval truth.
- Honeycomb/filesystem/SQLite are explicitly non-authoritative in supported production posture.

### Tests / proof required
- Durable restart/resume validation.
- Artifact persistence validation (DB metadata + object-store payload integrity).
- Trace replay validation from durable metadata.
- Source-of-truth cutover proof demonstrating no authority ambiguity.

## Phase 3 — Governance Contract Unification and Execution Hardening
### What already exists in code
- Governance modules exist (`capability_manifests`, `policy_adapter`, replay/guardrail components).
- Runtime-mode enforcement and governance-focused tests/docs already exist.
- Policy checks are present but distributed across surfaces and conventions.

### What must remain
- Local policy adapter as first enforced path.
- Existing replay-defense, guardrail, and runtime-mode fail-closed principles.
- Human approval semantics for sensitive actions.

### What is missing / gap
- One durable policy/approval/provenance contract spanning admission, planning, and action execution.
- Unified retry classification and runtime-profile enforcement tied to attempts.
- Consistent durable provenance records for tool/model/action/artifact events.

### Restructure work
- Standardize a single durable policy decision contract used across CLI/API/runtime/channel ingress.
- Keep local policy adapter as default enforcement mechanism in this phase.
- Reframe OPA-first language as a **later adapter option**, not a prerequisite for Phase 3 completion.
- Move approvals to durable run/job state transitions with explicit fail-closed behavior.
- Unify replay defense and dedupe around durable records.
- Attach runtime profiles and retry/failure classification to attempt metadata.

### Risks and sequencing constraints
- Inconsistent policy contract rollout can create bypass paths.
- Replay defenses are fragile if dedupe and approval state are split across stores.
- External policy-engine dependency introduced too early can block practical hardening.

### Exit criteria
- Sensitive actions cannot bypass policy/approval checks.
- Durable provenance exists for policy decisions and execution attempts.
- Retry/replay/runtime-profile behavior is enforced and inspectable.

### Tests / proof required
- Approval lifecycle and policy fail-closed tests.
- Replay defense and dedupe integrity tests.
- Retry classification and runtime-profile enforcement tests.
- Durable provenance assertions for policy + execution records.

## Phase 4 — Operator Surfaces, Acceptance Buckets, and Release Gates
### What already exists in code
- Operator-like APIs/dashboard surfaces and scripts exist.
- Test coverage exists across old/new paths but acceptance mapping is mixed.
- Recovery and release evidence is not yet consistently tied to one canonical state model.

### What must remain
- Operator visibility into runs, approvals, attempts, traces, and artifacts.
- Existing smoke/release automation as migration inputs.
- Governance/runtime evidence required for production claims.

### What is missing / gap
- Operator model centered on canonical runtime + policy data (instead of Honeycomb-first reconstruction).
- Explicit acceptance buckets and release-gate mapping by claim.
- Repeatable recovery drills tied to canonical source-of-truth state.

### Restructure work
- Narrow operator surfaces to runtime/governance/operator inspection responsibilities.
- Organize acceptance buckets: unit, integration, contract, e2e, recovery, release-gate.
- Build release gates around canonical runtime state + policy records.
- Align dashboard/admin behavior to inspection and operations, not parallel control planes.

### Risks and sequencing constraints
- Broad dashboard scope can reintroduce competing authority models.
- Recovery drills can be misleading if they validate only legacy reconstruction flows.
- Release claims may drift without test-to-claim mapping.

### Exit criteria
- Operators can inspect a run end-to-end from canonical durable state/policy records.
- Acceptance suite mapping is documented and executable.
- Recovery drills and release gates validate supported path behavior.

### Tests / proof required
- Operator inspection proof across runs/jobs/approvals/attempts/artifacts/traces.
- Acceptance-suite mapping verification.
- Recovery drill execution and evidence capture.
- Release-gate coverage matrix tied to production claims.

## Phase 5 — Tenancy Scoping, Channel Focus, and Expansion Quarantine
### What already exists in code
- Tenant controls, quota/rate-limit components, and channel support distinctions exist.
- Slack has strongest support narrative and verification depth.
- Plugin/forge/MCP/retrieval/pulse breadth exists in code/docs.

### What must remain
- Slack as the single supported reference channel.
- Existing quota/rate-limit and support-matrix enforcement mechanisms.
- Ability to keep non-supported breadth available behind clear lifecycle labels.

### What is missing / gap
- End-to-end tenant scoping consistency across runtime state, artifacts, policy decisions, quotas, and operator filtering.
- Explicit supported-channel enforcement in all entry surfaces.
- Clear promotion gates for experimental expansion surfaces.

### Restructure work
- Lock supported channel path to Slack for this roadmap horizon.
- Enforce tenant scoping across state/artifacts/policies/quotas/operator views.
- Move plugin/forge/MCP/retrieval/pulse/channel expansion to post-roadmap backlog unless later promoted.
- Keep broader surfaces available only as experimental or deferred, reusing canonical runtime contracts.

### Risks and sequencing constraints
- Tenant leakage risk if any legacy store/view path remains unscoped.
- Channel breadth can dilute test depth and support guarantees.
- Expansion pressure can re-expand defaults before canonical hardening completes.

### Exit criteria
- Tenant-aware controls are visible and enforced across canonical runtime/governance/operator surfaces.
- Slack is the only supported end-to-end channel path.
- Experimental breadth is clearly quarantined from supported product claims.

### Tests / proof required
- Tenant quota/rate-limit enforcement tests.
- Tenant-scoped inspection tests for operator surfaces.
- Supported-channel enforcement tests (Slack supported, others explicitly non-supported/experimental).
- Support-matrix assertion tests validating status labels and behavior.

---

## Cross-Phase Dependency Table
| Dependency | Must be established in | Required before |
|---|---|---|
| Canonical path declaration (current truth + target truth + support statuses) | Phase 1 | Phase 2 state-authority cutover |
| Durable runtime record contract and source-of-truth cutover | Phase 2 | Phase 3 governance/approval/provenance unification |
| Unified durable policy/approval/provenance contract | Phase 3 | Phase 4 operator and release-gate consolidation |
| Operator acceptance buckets + release-gate matrix | Phase 4 | Phase 5 tenancy/channel enforcement sign-off |
| Tenant-scoped enforcement + supported-channel lock | Phase 5 | Post-roadmap expansion promotions |

## Repo-Grounding Verification Note (Author Checklist)
Before approving this roadmap implementation package, verify and record:
1. `.plans/` was absent in tracked tree when this master plan was created.
2. `beekeeper/runtime/*` had no tracked source implementation at planning time.
3. `README.md` and `docker-compose.yml` still described broader stack breadth than the supported-core target.
4. March 6 baseline/current-state docs were used to correct or narrow older roadmap claims where they diverged from tracked code.

## Final Post-Roadmap Backlog (Not in 5-Phase Bar)
- Worker-forge maturation program (old optional Phase 6 content): promotion/signing/sandbox/provenance hardening.
- Broader multi-channel depth beyond Slack as supported default.
- Expanded plugin/MCP/retrieval/pulse productization beyond experimental quarantine.
- Additional scheduler breadth promotion beyond the canonical supported execution path.
- Any new control plane that would introduce parallel authority to canonical runtime + policy records.
