# Verification Matrix Against Critique Sections 4, 5, and 6

This matrix checks whether the roadmap actually covers the issues raised in your critique.

## Legend

- **Full** — directly addressed by a defined phase with clear deliverables and acceptance criteria
- **Partial** — addressed, but strongest version is deferred or depends on later infrastructure choices
- **Deferred by design** — intentionally postponed because shipping it earlier would create a maturity illusion

---

## Section 4 — The hard truth: what is weak or overstated

| Critique point | Concern | Covered by phase(s) | Coverage | What in the plan fixes it |
|---|---|---:|---|---|
| 4A | Architecture is over-centralized (`queen.py`) | 1, 2 | Full | Queen becomes a coordinator; services own planning, routing, policy, context, dispatch, aggregation |
| 4B | `runner.py` is too large | 1 | Full | CLI package split into command modules; business logic moved out |
| 4C | Persistence model is elegant but weak operationally | 2 | Full | Postgres + object storage + Temporal; Honeycomb re-scoped to dev-friendly audit/event adapter |
| 4D | Guardrails are shallow | 3 | Full | OPA policy engine, capability manifests, approval state machine, tool broker, provenance |
| 4E | Worker forge story is ahead of proof | 6 | Deferred by design | Worker forge stays experimental until promotion pipeline, sandboxing, tests, and evidence exist |
| 4F | Multi-tenancy is mostly logical | 5 | Partial | Tenant-aware quotas, secrets, rate limits, observability; strongest isolation can come later if needed |
| 4G | Security defaults are too loose | 0, 3 | Full | fail-closed config, managed secrets, replay defense, explicit sandbox tiers |
| 4H | Channel support is broader than deep | 5 | Full | Slack-first strategy, normalized event contract, retries, dedupe, capability matrix |
| 4I | Test story is weaker than docs imply | 0, 4 | Full | clean bootstrap, smoke test, e2e paths, recovery drills, clean-container CI truth source |

---

## Section 5 — Where the architecture has real gaps

| Critique point | Concern | Covered by phase(s) | Coverage | What in the plan fixes it |
|---|---|---:|---|---|
| 5 Gap 1 | No clean separation between control plane and execution plane | 2 | Full | control plane owns state and scheduling; workers own execution; Temporal mediates |
| 5 Gap 2 | No strong sandbox story | 3 | Partial | container baseline + gVisor + Firecracker tiers; strongest isolation depends on deployment environment |
| 5 Gap 3 | No strong policy engine abstraction | 3 | Full | OPA / Rego decision service, policy input/output contracts, policy versioning |
| 5 Gap 4 | Observability is trace logging, not full operability | 4 | Full | OpenTelemetry correlation, dashboards, operator run views, recovery drills |
| 5 Gap 5 | UI/admin layer is behind the platform claims | 4, 5 | Full | operator console requirements, tenant filtering, approval queue, channel delivery views |
| 5 Gap 6 | Too many backends, not enough proof | 0, 5 | Full | one production path, explicit experimental labels, reduced supported surface |

---

## Section 6 — What to change first

| Critique priority | Concern | Covered by phase(s) | Coverage | What in the plan fixes it |
|---|---|---:|---|---|
| 6 Priority 1 | Split the Queen | 1 | Full | explicit services and coordinator shell |
| 6 Priority 2 | Make the storage story honest and layered | 2 | Full | clear storage tiers, state vs artifact split, Honeycomb re-scope |
| 6 Priority 3 | Harden security defaults | 0, 3 | Full | fail-closed startup, secret manager, replay defense, sandboxing |
| 6 Priority 4 | Narrow the claims | 0, 5, 6 | Full | support matrix, maturity labels, experimental wording for unsupported depth |
| 6 Priority 5 | Choose one production path and make it excellent | 0, 5 | Full | reference stack defined; unsupported breadth downgraded |
| 6 Priority 6 | Add real end-to-end tests | 4 | Full | golden path, approval path, channel path, failure/retry path, recovery drills |

---

## Coverage summary

### Fully addressed
- centralization
- oversized CLI layer
- weak operational persistence
- shallow guardrails
- loose security defaults
- shallow channels
- weak test story
- missing control/execution split
- missing policy abstraction
- missing observability
- weak admin/operator surface
- backend sprawl
- lack of production focus

### Partially addressed
- **serious multi-tenancy** — addressed with quotas, policy, secrets, and observability; strongest hard-isolation strategies can be added later if required by customer/regulatory pressure
- **strong sandboxing** — addressed via trust-tiered isolation; the heaviest isolation depends on infrastructure adoption

### Intentionally deferred
- **worker forge maturity** — deferred on purpose so the project does not claim maturity it has not earned

---

## Final verification verdict

The roadmap is aligned with the critique **without hiding the hard parts**:

- it does **not** pretend filesystem JSONL is enough for serious production state
- it does **not** pretend worker forge is mature today
- it does **not** pretend logical tenancy equals strong tenancy
- it does **not** pretend unit-heavy or local-only tests equal production confidence
- it does **not** try to “fix maturity” by adding more surface area

Instead, it reduces surface area, hardens boundaries, and ties claims to evidence.
