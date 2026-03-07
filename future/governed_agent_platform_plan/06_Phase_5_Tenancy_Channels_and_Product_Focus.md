# Phase 5 — Real Tenancy, Deep Channels, and Product Focus

## Goal

Move from a good logical model to a safer operational model for tenancy, narrow the product surface area, and make one channel deeply reliable before broadening again.

This phase fixes the “logical tenancy”, “channel breadth over depth”, and “too many backends” problems.

---

## Why this phase matters

The current structure for orgs / hives / queens / users is a good control-plane concept, but that is not the same as serious multi-tenancy. Likewise, supporting many channels superficially is not the same as having a reliable messaging layer.

The platform becomes more credible if it chooses less and does it well.

---

## Supported tenancy model

Suggested semantic model:

| Entity | Meaning |
|---|---|
| `organization` | billing, policy, and quota root |
| `hive` | workspace / environment namespace under an organization |
| `queen` | orchestration profile / agent configuration entity |
| `user` | human or service principal |
| `run` | execution instance inside a queen/hive context |

### Tenancy guarantees to implement
- tenant-scoped secret access
- tenant-scoped quotas
- tenant-scoped rate limits
- tenant-filtered observability
- tenant-aware policy inputs
- tenant-aware artifact access checks
- tenant-aware search/filtering in operator views

### What this phase does **not** claim yet
- full hard isolation between all tenants at the infrastructure level
- separate cryptographic hardware roots per tenant
- independent per-tenant clusters by default

Those can come later for high-assurance environments.

---

## Practical tenancy controls

### Quotas
Add configurable quotas for:
- concurrent runs
- daily spend
- token budget
- artifact storage
- channel send rate
- webhook ingest rate

### Secret scoping
Secrets are scoped at least by:
- environment
- organization
- hive
- capability manifest

### Audit scoping
Operators can filter by organization / hive / queen / run.

### Rate limiting
Implement tenant-aware limits on:
- API submission
- channel ingress
- outbound channel sends
- worker creation if relevant

---

## Channel strategy

### Recommended focus order
1. **Slack** — supported and deep
2. everything else — experimental until Slack is reliable and fully instrumented

If a second channel is truly needed, add it only after the Slack adapter meets all exit criteria.

### Channel contract to standardize

| Concern | Requirement |
|---|---|
| Inbound verification | signature / token check, timestamp validation if supported, replay defense, dedupe |
| Normalization | map provider event into one normalized internal event schema |
| Conversation identity | workspace, channel, thread, message, external user IDs |
| Delivery | retries, dead-letter handling, idempotent send semantics |
| State | durable session/thread state in DB, not memory |
| Observability | provider event ID, correlation IDs, latency, retries, failures |
| Capability matrix | explicitly list attachments, threads, buttons, slash commands, edits, etc. |

### Do not do this
- do not rely on channel-specific behavior scattered throughout Queen
- do not let channels bypass policy checks
- do not call shallow channel support “battle-tested”

---

## Product focus rules

### Rule 1 — One production scheduler
Temporal only.

### Rule 2 — One supported channel
Slack only, until proven otherwise.

### Rule 3 — One supported storage architecture
Postgres + object storage + audit/event tables.

### Rule 4 — One primary LLM path
One provider only as the default path.

### Rule 5 — Explicit experimental label
Any extra backend/channel/provider must be labeled experimental and excluded from the production readiness claim.

---

## Admin / operator console requirements

By the end of this phase, the console should support:

- tenant filtering
- run timeline
- approval queue
- policy decision inspection
- artifact list
- channel delivery inspection
- quota / budget view
- health and alert summaries

This is where the UI stops being only a prototype surface and becomes an operations tool.

---

## Suggested repo additions

```text
app/
  tenancy/
    quotas.py
    rate_limits.py
    tenancy_context.py
    secret_scopes.py

  channels/
    normalized_events.py
    slack/
      ingress.py
      egress.py
      capabilities.py
```

---

## Definition of done

Phase 5 is complete when all of the following are true:

- tenant quotas and rate limits exist
- secrets and policy inputs are tenant-aware
- the operator console can filter and inspect by tenant
- Slack has verified ingress, dedupe, retries, observability, and a clear capability matrix
- all non-reference channels/backends/providers are marked experimental
- product language matches actual supported depth

---

## Success metrics

- per-tenant run visibility coverage
- quota/rate-limit enforcement coverage
- Slack delivery success / retry visibility
- percentage of channel code using normalized events
- number of officially supported backends reduced to the reference path

---

## Risks and how to handle them

### Risk: product breadth feels reduced
Mitigation: depth increases trust; unsupported breadth stays available as experimental.

### Risk: tenancy rules surface hidden coupling
Mitigation: that is useful pressure; fix boundaries instead of hiding them.

### Risk: channel feature pressure returns quickly
Mitigation: require a capability matrix and exit criteria before adding new channels.

---

## Mapping to the critique

This phase directly addresses:

- **4F** multi-tenancy exists, but is still mostly logical tenancy
- **4H** channel support is broader than it is deep
- **5 Gap 5** UI/admin layer is behind platform claims
- **5 Gap 6** too many backends, not enough proof
- **6 Priority 4** narrow the claims
- **6 Priority 5** choose one production path and make it excellent

---

## Research basis

Primary references: `[R6]`, `[R7]`, `[R9]`, `[R12]`

Why these matter here:

- `[R6]` informs the move from ad hoc authorization to explicit relationship/scoping thinking.
- `[R7]` supports versioned, observable worker deployments that can be scoped by workload/tenant strategies.
- `[R9]` supports tenant-aware trace/log/metric correlation.
- `[R12]` supports secure logging, access control, and validation discipline.
