# Getting Started — Beekeeper Agent Platform

Step-by-step guide for first-time installation, setup, and usage. Follow these steps in order.

---

## Prerequisites

- **Python 3.9+** — for CLI and local runs
- **Docker & Docker Compose** — for full stack (Redis, Temporal, Qdrant, SearXNG, workers, Open WebUI)
- **Optional:** Ollama (local LLM) running at `http://localhost:11434` for local model inference

---

## Step 1: Install

From the project root:

```bash
cd /path/to/agent
pip install -e .
```

Verify:

```bash
beekeeper version
```

---

## Step 2: Environment Setup

Copy the example environment file and adjust as needed:

```bash
cp .env.example .env
```

Edit `.env` and set:

| Variable | Description |
|----------|-------------|
| `BEEKEEPER_LLM_PROVIDER` | `ollama`, `gemini`, or `openai` |
| `BEEKEEPER_OLLAMA_BASE_URL` | For Ollama: default `http://localhost:11434` |
| `BEEKEEPER_OLLAMA_MODEL` | Model name (e.g. `catsarethebest/qwen2.5-N2:1.5b`) |
| `BEEKEEPER_GEMINI_API_KEY` | Required if using Gemini |
| `BEEKEEPER_OPENAI_API_KEY` | Required if using OpenAI |

See [.env.example](.env.example) and [architecture/08_env_reference.md](architecture/08_env_reference.md) for full reference.

---

## Step 3: Quick Path — Minimal First Run (No Docker)

For a fast sanity check without Docker:

```bash
beekeeper run --scheduler inline --vector memory --query "What is 2+2?"
```

Uses in-memory vector store and inline execution. Your LLM (Ollama, Gemini, or OpenAI) must be reachable per `.env`.

---

## Step 4: Full Stack with Docker

### Option A: Use rebuild-and-run.sh

```bash
./rebuild-and-run.sh
```

This script:

- Activates `.venv` if present
- Installs with `pip install -e . -q`
- Runs `beekeeper rebuild`
- Runs `beekeeper up --with-open-webui`

### Option B: Manual steps

```bash
beekeeper
beekeeper up --with-open-webui
```

With no subcommand, `beekeeper` runs health checks and auto-starts core Docker services (Redis, Temporal, Qdrant, SearXNG) if needed.

`beekeeper up --with-open-webui` starts the full stack: Redis, Temporal, Qdrant, SearXNG, Celery worker, Temporal worker, Beekeeper API, Queen API, and Open WebUI.

---

## Step 5: First-Time Setup Wizard

On a fresh install (no `.env` or no store), visit:

- **http://localhost:8787/** or **http://localhost:8787/setup**

The wizard configures:

1. LLM provider (Ollama, Gemini, OpenAI)
2. Channels (Telegram, WhatsApp) — optional
3. Admin account
4. Organization and Hive

After setup, you are redirected to the dashboard.

---

## Step 6: Using the Platform

### CLI chat (terminal)

```bash
beekeeper chat --scheduler inline --vector memory
```

### Web chat (Open WebUI)

1. Open **http://localhost:3000**
2. Create an account or sign in
3. Configure Queen connection:
   - Admin Settings → Connections → OpenAI
   - Base URL: `http://host.docker.internal:8788/v1`
   - Model: `beekeeper-queen`

### Dashboard

- **http://localhost:8787/dashboard** — channels, templates, HITL approvals, settings

### Single query

```bash
beekeeper run --scheduler inline --vector memory --query "best agent sdk patterns"
```

---

## Troubleshooting

| Issue | Action |
|-------|--------|
| Health checks fail | Run `beekeeper doctor` or `beekeeper doctor --auto-start` |
| Docker services not starting | Ensure Docker daemon is running |
| Ollama unreachable | Verify `BEEKEEPER_OLLAMA_BASE_URL` (use `host.docker.internal` for containers) |
| Dashboard env edits not persisting | For Docker: uncomment the `./.env:/app/.env` volume in docker-compose.yml (create `.env` first) |
| `beekeeper` not found | Re-run `pip install -e .` in your active environment |

---

## Next Steps

- [HOW_TO_USE.md](HOW_TO_USE.md) — full CLI reference
- [docs/DECISION_TREE.md](docs/DECISION_TREE.md) — scheduler, worker, channel choices
- [docs/CHANNEL_ALLOWLISTS.md](docs/CHANNEL_ALLOWLISTS.md) — Slack, Discord, etc.
