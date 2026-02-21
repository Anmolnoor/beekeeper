# 05 — Data Layer

## Overview

The platform uses **two separate stores** with distinct purposes:

| Store | Location | Purpose |
|-------|----------|---------|
| `HoneycombStore` | `.honeycomb/` | Append-only runtime data: events, artifacts, results, governance |
| `BeekeeperStore` | `.beekeeper_store/` | Multi-tenant config: orgs, hives, queens, templates, channels, users |

---

## HoneycombStore — Directory Layout

```
.honeycomb/
├── events/
│   └── <trace_id>.jsonl          ← all telemetry events for a trace
├── tasks/
│   └── <task_id>.json            ← TaskEnvelope snapshots
├── artifacts/
│   └── <artifact_id>.json        ← ArtifactRef + content
├── governance/
│   └── <decision_id>.json        ← PolicyDecision records
├── graph/
│   └── <trace_id>.jsonl          ← parent→child task edges (DAG)
├── performance/
│   └── *.jsonl                   ← WorkerPerformanceRecord per execution
├── optimizer/
│   └── routing_feedback.json     ← RoutingFeedback by worker_kind/intent
├── reviews/
│   └── <review_id>.json          ← HumanReviewRecord (HITL queue)
├── backlog/
│   └── backlog.jsonl             ← Pulse autonomous task queue
├── session/
│   └── <session_id>.jsonl        ← Multi-turn session links
└── archive/
    ├── warm/                     ← Artifacts 30-90 days old
    └── cold/                     ← Artifacts > 90 days old
```

### Lifecycle Tiers

| Age | Location | Policy |
|-----|----------|--------|
| < 30 days | `artifacts/` | Hot — immediately accessible |
| 30–90 days | `archive/warm/` | Warm — moved by `enforce_retention_lifecycle()` |
| > 90 days | `archive/cold/` | Cold — archived |

---

## BeekeeperStore — Directory Layout

```
.beekeeper_store/
├── orgs/
│   └── <org_id>.json             ← OrganizationRecord
├── hives/
│   └── <hive_id>.json            ← HiveRecord
├── honeycombs/
│   └── <honeycomb_id>.json       ← HoneycombRecord (includes root_path)
├── queens/
│   └── <queen_id>.json           ← QueenInstanceRecord
├── templates/
│   └── <template_id>.json        ← AgentBlueprint + profile refs
├── settings/
│   └── <key>.json                ← Global key-value settings
├── hive_settings/
│   └── <hive_id>_<key>.json      ← Per-hive settings
├── channels/
│   └── <channel>.json            ← Encrypted channel config
├── users/
│   └── <user_id>.json            ← UserRecord (bcrypt hash)
├── roles/
│   └── <role_id>.json            ← UserOrgRole
├── pairing/
│   └── <channel>_<user>.json     ← DM pairing state
└── audit.jsonl                   ← HMAC-signed audit log
```

---

## Core Data Models

### `TaskEnvelope`

```python
task_id: str           # UUID
task_type: str         # intent name (e.g. "research_topic")
worker_kind: WorkerKind
payload: dict          # input data
budget_usd: float      # max spend for this task
trust_tier: TrustTier  # low | medium | high
status: Status         # queued | running | success | failed | blocked
parent_task_id: str | None
trace_id: str | None
idempotency_key: str | None
```

### `ResultEnvelope`

```python
result_id: str
task_id: str
trace_id: str
status: Status
output: dict           # worker-specific output dict
cost_metrics: CostMetrics
artifact_refs: list[ArtifactRef]
error: str | None
created_at: datetime
```

### `PolicyDecision`

```python
decision_id: str
task_id: str
status: Literal["approve", "block", "needs_human"]
reason: str
guardrail_flags: list[str]
requires_human_approval: bool
approved_by: str | None
approved_at: datetime | None
```

### `RoutingFeedback` (adaptive routing)

Per `(worker_kind, intent, skill_id)` bucket:
```python
quality_score: float        # recency-weighted average
avg_latency_ms: float
avg_cost_usd: float
success_rate: float
sample_count: int
updated_at: str
```

---

## Vector Store

Used for semantic search over past artifact content.

| Backend | Class | Storage |
|---------|-------|---------|
| `memory` | `InMemoryVectorStore` | In-process Python list (lost on restart) |
| `qdrant` | `QdrantVectorStore` | Qdrant server, persisted to Docker volume |

`HoneycombStore.semantic_search(query, limit)` embeds the query and returns top-k matching artifact summaries.

---

## Security

### Channel Config Encryption
Channel secrets (Slack tokens, Telegram tokens, etc.) are stored encrypted in `BeekeeperStore`. Decryption uses `PyNaCl` secret box with key from `BEEKEEPER_CHANNEL_ENCRYPTION_KEY` env var.

### Audit Log Signing
`append_audit_event()` uses HMAC-SHA256 with `BEEKEEPER_AUDIT_SIGNING_KEY` to produce tamper-evident signed audit entries in `audit.jsonl`.

### JWT Authentication
Beekeeper API uses `python-jose` for JWT token signing/verification. Tokens include `user_id` claim.
