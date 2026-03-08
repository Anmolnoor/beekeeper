# Beekeeper Phase 1

This branch is now centered on the Phase 1 Beekeeper runtime:
- one Queen control plane
- isolated `bash`, `filesystem`, `github`, and `network` workers
- durable run state and append-only trace
- Postgres for production state
- MinIO for production artifacts
- CLI-first control and inspection

## Quick Start

Bring up the whole supported stack with one command:

```bash
beekeeper start --build
```

That starts Docker Compose, initializes the database schema, ensures the MinIO bucket exists, and prints the main service URLs.

Run the same flow through `make` if you prefer:

```bash
make start
```

Create a run once the stack is up:

```bash
beekeeper run "Show the repo status" --worker-kind github --payload '{"action":"status"}'
```

Legacy workflows are still available, but only through:

```bash
beekeeper-legacy --help
```

## Core Concepts

- **Queen** — Planner/router that decomposes intents into tasks and delegates to workers.
- **Workers** — Ephemeral specialists: `web_search`, `heavy_compute`, `audit`, and `forged` (for unmatched intents).
- **Honeycomb** — Developer-friendly append-only timeline for traces/events and local debugging.
- **Tools** — Model-driven tool loop (ToolLoopEngine) with policy checks; optional MCP servers (stdio/HTTP) for external tools.

## Support and Maturity

- Supported production path target: Postgres + Temporal + S3-compatible object storage + policy mediation + OpenTelemetry.
- Storage tiers are explicit: dev/local JSONL+filesystem, prod metadata Postgres, prod event/log pipeline, object artifacts, and Qdrant for vectors.
- Current channel focus: Slack depth first; other channels are available but not considered equally hardened.
- Worker forge/generation: experimental until full promotion, sandboxing, and provenance gates are met.
- Credibility posture: experimental worker forge, prototype dashboard, logical multi-tenancy, unit-tested core with limited live integration coverage.
- Detailed status: [docs/support-matrix.md](docs/support-matrix.md), [docs/maturity-model.md](docs/maturity-model.md), [docs/risks-and-known-gaps.md](docs/risks-and-known-gaps.md)

## What makes Beekeeper different

- **Tool-level policy** — Every tool goes through the ToolRegistry and guardrails (PII, domain allowlists, HITL for high-risk tools). No raw tool execution without policy.
- **Dual execution** — Legacy worker dispatch and/or model-driven tool loop; run in `legacy_worker`, `model_tools`, or `hybrid` mode. Optional MCP tools from external servers.
- **Governance and audit** — Honeycomb records every event; HITL for sensitive actions; optional audit worker for validation.
- Unlike generic agent frameworks (e.g. LangGraph) or pure chat gateways (e.g. OpenClaw), Beekeeper is built for teams that need policy enforcement, audit trails, and human-in-the-loop on tool use.

## Key Commands

| Command | Description |
|---------|-------------|
| `beekeeper start --build` | One command to build, start, and initialize the whole Phase 1 stack |
| `beekeeper init` | Initialize the configured database schema and artifact bucket |
| `beekeeper stack up --build` | Start the Docker stack |
| `beekeeper stack down` | Stop the Docker stack |
| `beekeeper stack ps` | Show service status |
| `beekeeper stack logs [service]` | Show compose logs |
| `beekeeper stack restart [service]` | Restart the stack or one service |
| `beekeeper run ...` | Submit a run |
| `beekeeper attach <run_id>` | Reattach to a run |
| `beekeeper status <run_id>` | Inspect run state |
| `beekeeper approve <approval_id> --by <name>` | Approve and resume a gated action |
| `beekeeper trace <run_id>` | Show the append-only trace |
| `beekeeper-legacy ...` | Access the old pre-Phase-1 command tree |

## Docker / Compose

```bash
beekeeper start --build
```

Starts Postgres, MinIO, `queen-api`, and the background supervisor. The compose file sets the production adapters by default:
- `BEEKEEPER_DURABLE_STATE_BACKEND=postgres`
- `BEEKEEPER_DATABASE_URL=postgresql+psycopg://...`
- `BEEKEEPER_ARTIFACT_BACKEND=minio`
- `BEEKEEPER_MINIO_ENDPOINT=minio:9000`

## Channels

- **Slack** — primary supported channel path.
- **Telegram, Discord** — available, currently treated as experimental depth.
- **WhatsApp** — Cloud API; supports text and audio/voice (transcription via OpenAI Whisper if `BEEKEEPER_OPENAI_API_KEY` set).

## Dashboard

Open `http://localhost:8788/dashboard` (or 8787 in Docker). Sign in to manage channels, templates, orgs, and **HITL approvals** (approve/reject pending tasks). For Grafana, add Beekeeper API as JSON datasource and use `/api/analytics/latency`.

## HITL Approval

High-risk actions (e.g. `payment_action`, `data_delete`) require human approval. Pending items appear in the dashboard and via `beekeeper review list`. Approve via API: `POST /api/approvals/{id}/approve`. Push notifications to WhatsApp/Telegram when configured (`hitl_notify_chat_id`, `hitl_notify_phone`).

## Worker Forge

Worker forge is currently **experimental**.

When no worker matches an intent (no content match), Queen auto-forges a custom worker on demand by:
- registering a `custom_*` worker profile in the worker registry,
- generating a worker plugin in `.honeycomb/workers/generated/`,
- updating `.honeycomb/workers/plugins.json`, and
- hot-reloading worker plugins at runtime.

Current request still falls back safely to `forged` execution if generation/loading fails; subsequent matching intents route through the generated custom worker.

## Docs

- [docs/ONBOARDING.md](docs/ONBOARDING.md) — Setup guide
- [docs/DECISION_TREE.md](docs/DECISION_TREE.md) — Scheduler, worker, channel choices
- [docs/PROMPT_TEMPLATES.md](docs/PROMPT_TEMPLATES.md) — Customize prompts
- [docs/REMOTE_ACCESS_AND_TAILSCALE.md](docs/REMOTE_ACCESS_AND_TAILSCALE.md) — Remote access

## Migration from beehive

Rename `BEEHIVE_*` → `BEEKEEPER_*`, `~/.beehive/` → `~/.beekeeper/`, use `beekeeper` CLI. Add `beekeeper-queen` to Open WebUI allowlist.

If you still need the previous command surface during migration, use `beekeeper-legacy`.
