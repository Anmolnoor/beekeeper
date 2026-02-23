# Onboarding: Beekeeper Agent Platform

Quick path from zero to a working Queen agent.

## 1. Install

```bash
cd /path/to/agent
pip install -e .
```

Verify:

```bash
beekeeper --help
beekeeper version
```

## 2. First Run (No Docker)

For a quick local test without Docker:

```bash
beekeeper run --scheduler inline --vector memory --query "What is 2+2?"
```

This uses in-memory vector store and inline execution. Ollama and SearXNG are optional for this minimal test.

## 3. Full Stack (Docker)

```bash
beekeeper
```

With no subcommand, Beekeeper:
1. Runs health checks (`doctor`)
2. Auto-starts Docker services if checks fail (redis, temporal, qdrant, searxng)
3. Prints a command guide

Then:

```bash
beekeeper up --with-workers
```

This brings up Redis, Temporal, Qdrant, SearXNG, Celery worker, and Temporal worker.

## 4. Chat

**Terminal chat:**
```bash
beekeeper chat --scheduler inline --intent research_topic
```

**Web UI:**
```bash
beekeeper up --with-open-webui
```

Open http://localhost:3000. Configure Queen:
- Admin Settings → Connections → OpenAI
- Base URL: `http://localhost:8788/v1` (or `http://queen-api:8787/v1` in Docker)
- Model: `beekeeper-queen`

## 5. Tenant Setup

```bash
beekeeper init-tenant --org "My Org" --hive "Main Hive"
```

## 6. Control Dashboard

Open `http://localhost:8787/dashboard`. Register or sign in to view channels, templates, and orgs. Configure channel allowlists via CLI (`beekeeper channels set`).

## 7. Channels (Slack, Discord)

1. Configure Beekeeper API: `beekeeper up --with-beekeeper`
2. Set channel secrets: `beekeeper channels set slack '{"slack_bot_token":"xoxb-...","slack_signing_secret":"..."}'`
3. Configure webhook in Slack/Discord to point to your Beekeeper webhook URL.

## 8. Next Steps

- [HOW_TO_USE.md](../HOW_TO_USE.md) — CLI reference
- [DECISION_TREE.md](DECISION_TREE.md) — Which scheduler? Worker? Channel?
- [BUILDING_NEW_WORKERS.md](BUILDING_NEW_WORKERS.md) — Add custom workers
- [PROMPT_TEMPLATES.md](PROMPT_TEMPLATES.md) — Customize prompts
- [REMOTE_ACCESS_AND_TAILSCALE.md](REMOTE_ACCESS_AND_TAILSCALE.md) — Remote access
