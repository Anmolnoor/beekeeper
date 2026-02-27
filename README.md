# Beekeeper Agent Platform

**Governed agent runtime with tool-level policy enforcement:** Queen orchestrates tasks, every tool call is checked against guardrails, and Honeycomb stores traces and approvals.

## Quick Start (5 min)

```bash
beekeeper quickstart
beekeeper chat
```

Or a single query:

```bash
beekeeper run --scheduler auto --vector memory --query "best agent sdk patterns"
```

**First-run wizard:** On a fresh install (no `.env`, no store), visit `/` or `/setup` to configure LLM, API keys, and channels. Runs once.

## Core Concepts

- **Queen** — Planner/router that decomposes intents into tasks and delegates to workers.
- **Workers** — Ephemeral specialists: `web_search`, `heavy_compute`, `audit`, and `forged` (for unmatched intents).
- **Honeycomb** — Append-only store for events, artifacts, traces, and HITL approvals.
- **Tools** — Model-driven tool loop (ToolLoopEngine) with policy checks; optional MCP servers (stdio/HTTP) for external tools.

## What makes Beekeeper different

- **Tool-level policy** — Every tool goes through the ToolRegistry and guardrails (PII, domain allowlists, HITL for high-risk tools). No raw tool execution without policy.
- **Dual execution** — Legacy worker dispatch and/or model-driven tool loop; run in `legacy_worker`, `model_tools`, or `hybrid` mode. Optional MCP tools from external servers.
- **Governance and audit** — Honeycomb records every event; HITL for sensitive actions; optional audit worker for validation.
- Unlike generic agent frameworks (e.g. LangGraph) or pure chat gateways (e.g. OpenClaw), Beekeeper is built for teams that need policy enforcement, audit trails, and human-in-the-loop on tool use.

## Key Commands

| Command | Description |
|---------|-------------|
| `beekeeper` | Health checks, auto-start Docker if needed |
| `beekeeper chat` | Interactive chat |
| `beekeeper run --query "..."` | Single query |
| `beekeeper doctor` | Service health |
| `beekeeper review list` | Pending HITL approvals |
| `beekeeper review approve <id> --resume` | Approve and resume task |
| `beekeeper init-tenant --org X --hive Y` | Create tenant |
| `beekeeper channels set slack '{"slack_bot_token":"..."}'` | Configure channel |

## Docker / Compose

```bash
docker compose up --build
```

Starts Redis, Temporal, Qdrant, SearXNG, Celery, Queen API (8788), Open WebUI (3000). Configure via `.env` (see `.env.example`).

## Channels

- **Slack, Telegram, Discord** — Webhooks via `beekeeper channels set`. See [docs/CHANNEL_ALLOWLISTS.md](docs/CHANNEL_ALLOWLISTS.md).
- **WhatsApp** — Cloud API; supports text and audio/voice (transcription via OpenAI Whisper if `BEEKEEPER_OPENAI_API_KEY` set).

## Dashboard

Open `http://localhost:8788/dashboard` (or 8787 in Docker). Sign in to manage channels, templates, orgs, and **HITL approvals** (approve/reject pending tasks). For Grafana, add Beekeeper API as JSON datasource and use `/api/analytics/latency`.

## HITL Approval

High-risk actions (e.g. `payment_action`, `data_delete`) require human approval. Pending items appear in the dashboard and via `beekeeper review list`. Approve via API: `POST /api/approvals/{id}/approve`. Push notifications to WhatsApp/Telegram when configured (`hitl_notify_chat_id`, `hitl_notify_phone`).

## Worker Forge

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
