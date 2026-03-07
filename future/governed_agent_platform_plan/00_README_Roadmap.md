# Governed-Agent Platform Hardening Roadmap

## Purpose

This roadmap fixes the three structural problems identified in the critique:

1. **Too centralized** — `queen.py` behaves like a god object and `runner.py` is carrying too much glue.
2. **Too filesystem-dependent** — the current storage approach is useful for development but too weak for concurrency, durability, queryability, and multi-instance operation.
3. **Too optimistic about maturity** — governance, tenancy, security, channels, observability, and tests are directionally good but not yet deep enough to justify strong production claims.

The plan is intentionally sequenced so the project becomes **simpler, safer, and easier to operate**, not just bigger.

---

## The simple target state

Build toward a platform with four explicit layers:

- **Control plane**  
  orgs / hives / queens / users, auth, admission, approvals, policy evaluation, run registry, scheduling decisions
- **Execution plane**  
  workers, tool execution, LLM calls, channel delivery, retries, heartbeats
- **Data plane**  
  Postgres for metadata, object storage for artifacts, append-only audit/event log, Qdrant only when retrieval is truly needed
- **Governance plane**  
  policy engine, approval rules, capability manifests, secret scopes, audit evidence

---

## Recommended reference stack

This is the **single production path** the roadmap assumes. Everything else should be downgraded to experimental until proven.

| Concern | Recommended production default | Notes |
|---|---|---|
| Metadata / authoritative state | **Postgres** | run state, steps, tasks, approvals, policy decisions, leases, channel sessions |
| Durable workflow / queue | **Temporal** | production path only; inline scheduler remains local-dev only |
| Artifacts / large payloads | **S3-compatible object storage** | MinIO in dev, S3-compatible in production |
| Policy engine | **OPA / Rego** | externalize policy decisions from orchestration code |
| Observability | **OpenTelemetry** | traces, metrics, logs, context propagation |
| Secrets | **Secret manager** | cloud secret manager or Vault; no dev defaults in prod |
| Worker isolation | **Containers + rootless + read-only FS** as baseline; **gVisor** for semi-trusted; **Firecracker** for generated / untrusted | isolation level depends on trust tier |
| Retrieval | **Qdrant only when needed** | do not make vector storage mandatory for the whole platform |
| Channels | **Slack first** | all other channels experimental until Slack is deep and reliable |
| LLM provider path | **One primary provider** | one default path, optional fallback later, no multi-provider sprawl now |

---

## Non-negotiable platform rules

1. **Local disk is never the source of truth.**
2. **No long-running work happens inside the API / control process.**
3. **Every run, task, approval, tool call, and artifact has a durable record.**
4. **Every sensitive external action is policy-mediated.**
5. **Every retryable action is idempotent or explicitly fenced.**
6. **Every claim about maturity must be backed by an acceptance test, a dashboard, or a drill.**

---

## Phase sequence

### Phase 0 — Baseline, truth, focus
Create an honest baseline, choose one production path, classify current storage and backends, fail closed on security defaults, and make a clean clone/test/bootstrap story.

### Phase 1 — Split the Queen and shrink the Runner
Turn `queen.py` into a thin coordinator and move its responsibilities into explicit services. Break `runner.py` into a real CLI package.

### Phase 2 — Durable state and control/execution separation
Move authoritative state to Postgres, move artifacts to object storage, keep Honeycomb only as a dev-friendly audit/event adapter, and push execution into workers.

### Phase 3 — Real governance, security, and sandboxing
Replace lightweight guardrails with policy-as-code, capability manifests, approval state machines, secret scoping, webhook replay defense, and worker isolation tiers.

### Phase 4 — Operability, observability, testing, and release discipline
Add OpenTelemetry, dashboards, failure drills, clean bootstrap, end-to-end tests, worker deployment discipline, and release gates.

### Phase 5 — Real tenancy, deep channels, and product focus
Move from logical tenancy to enforceable tenancy controls, make one channel excellent, add quotas/rate limits/admin operations, and narrow public claims.

### Phase 6 — Worker Forge maturation (optional, only after Phases 0–5)
Treat generated workers as a governed product capability only after they pass a promotion pipeline with tests, signatures, sandboxing, and rollout controls.

---

## End-state architecture (text diagram)

```text
Client / Channel / CLI
        |
        v
+-----------------------------+
| Control Plane               |
| - API / admission           |
| - org/hive/queen/user auth  |
| - run registry              |
| - planner coordinator       |
| - approval coordinator      |
| - policy adapter            |
+-----------------------------+
        |
        v
+-----------------------------+
| Temporal / durable queue    |
+-----------------------------+
        |
        v
+-----------------------------+
| Execution Plane             |
| - worker runtime            |
| - tool broker               |
| - LLM / channel adapters    |
| - sandbox profiles          |
+-----------------------------+
        |
        +------> Object storage (artifacts, prompts, logs, traces)
        +------> Secret manager (scoped credentials)
        +------> External APIs / channels / tools

Shared durable services
- Postgres
- Append-only audit/event tables + archive
- OpenTelemetry collector / metrics / logs / traces
- Optional Qdrant
```

---

## What gets explicitly downgraded

Until later phases are complete, the following should be labeled **experimental** or **dev-only**:

- inline scheduler in any serious environment
- multiple production schedulers
- multiple production channel stacks
- generated worker forge
- filesystem-backed authoritative state
- broad multi-provider support as a selling point
- “serious multi-tenancy” language
- “battle-tested” or “production-ready” wording

---

## Exit gates by phase

| Phase | Do not proceed unless… |
|---|---|
| 0 | supported production path is declared; secrets fail closed in prod; bootstrap works from clean environment |
| 1 | `queen.py` is a coordinator, not a god object; CLI commands are modular |
| 2 | authoritative state survives restart; workers run outside control process |
| 3 | sensitive actions cannot bypass policy; replay/idempotency protections exist |
| 4 | one golden path, one approval path, one failure/retry path, and one restore drill are automated |
| 5 | tenancy controls, quotas, channel semantics, and operator views exist for the supported path |
| 6 | generated workers pass the same safety/release bar as hand-written workers |

---

## How to use these files

- Read `01_Phase_0_Baseline_Truth_and_Focus.md` first.
- Then execute phases in order.
- For the shortest repo-grounded version of the remaining work, read `11_Ten_Implementation_Steps.md`.
- Use `08_Verification_Matrix_Against_Points_4_5_6.md` to verify the roadmap against the critique.
- Use `09_Research_Basis.md` to see the standards, papers, and official docs that informed the design.

---

## Research basis IDs used in the phase files

- `[R1]` NIST SP 800-218 SSDF 1.1
- `[R2]` NIST SP 800-218A SSDF Community Profile for Generative AI / dual-use foundation models
- `[R3]` NIST AI RMF 1.0
- `[R4]` NIST AI RMF Generative AI Profile
- `[R5]` OPA / Rego policy-as-code
- `[R6]` Zanzibar authorization model
- `[R7]` Temporal durable execution / task queues / workers / versioning / prod checklist
- `[R8]` Azure architecture guidance for event sourcing / outbox / web-queue-worker
- `[R9]` OpenTelemetry signals / traces / context propagation
- `[R10]` gVisor sandboxing
- `[R11]` Firecracker microVM isolation
- `[R12]` OWASP secrets, logging, microservices security, ASVS
- `[R13]` SLSA supply-chain levels
- `[R14]` Google continuous testing research
