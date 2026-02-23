# Beekeeper Agent Platform

Multi-agent runtime: Queen decomposes requests into tasks, ephemeral workers execute them, honeycomb stores traces and governance.

## Quick Start (5 min)

```bash
beekeeper quickstart
beekeeper chat
```

Or a single query:

```bash
beekeeper run --scheduler inline --vector memory --query "best agent sdk patterns"
```

**First-run wizard:** On a fresh install (no `.env`, no store), visit `/` or `/setup` to configure LLM, API keys, and channels. Runs once.

## Core Concepts

- **Queen** — Planner/router that decomposes intents into tasks and delegates to workers.
- **Workers** — Ephemeral specialists: `web_search`, `heavy_compute`, `audit`, and `forged` (for unmatched intents).
- **Honeycomb** — Append-only store for events, artifacts, traces, and HITL approvals.

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

When no worker matches an intent (score ≤ 10), Queen routes to the `forged` worker, which uses the LLM to fulfill the request directly.

## Docs

- [docs/ONBOARDING.md](docs/ONBOARDING.md) — Setup guide
- [docs/DECISION_TREE.md](docs/DECISION_TREE.md) — Scheduler, worker, channel choices
- [docs/PROMPT_TEMPLATES.md](docs/PROMPT_TEMPLATES.md) — Customize prompts
- [docs/REMOTE_ACCESS_AND_TAILSCALE.md](docs/REMOTE_ACCESS_AND_TAILSCALE.md) — Remote access

## Migration from beehive

Rename `BEEHIVE_*` → `BEEKEEPER_*`, `~/.beehive/` → `~/.beekeeper/`, use `beekeeper` CLI. Add `beekeeper-queen` to Open WebUI allowlist.
