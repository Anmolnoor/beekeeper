# Beehive CLI: How To Use

**Quick start in 5 minutes:** `beehive quickstart` then `beehive chat`.

For choosing scheduler, worker, or channel, see [docs/DECISION_TREE.md](docs/DECISION_TREE.md).

## 1) Install the CLI command

From the project root:

```bash
pip install -e .
```

This installs the `beehive` command from `beehive.runner:main`. Also installs `beekeeper-api` and `queen-api` for dashboard and chat APIs.

If you do not want to install yet, you can still run:

```bash
python -m beehive.runner --help
```

## 2) First-time setup

**5-minute path:**
```bash
beehive quickstart
```
Runs health checks, initializes tenant with defaults, minimal prompts.

**Full interactive wizard:**
```bash
beehive setup
```
Copies `.env.example` to `.env` if needed, runs health checks, initializes org/hive/honeycomb, optionally creates an admin user. Use `--non-interactive` for CI/automation.

## 3) Fastest way to start

```bash
beehive
```

What `beehive` (no subcommand) does:
- Runs runtime health checks (`doctor`)
- If checks fail, tries to start core Docker services (`redis`, `temporal`, `qdrant`, `searxng`)
- Re-runs checks
- Prints a command guide

## 4) Command reference

**Infrastructure**
- `beehive` — Health check + auto-start core infra if required.
- `beehive doctor` — Health checks only. Use `--json` for machine-readable output.
- `beehive doctor --auto-start` — Health checks, then auto-starts core Docker infra if checks fail.
- `beehive up` — Starts core services: `redis`, `temporal`, `qdrant`, `searxng`.
- `beehive up --with-workers` — Starts core services + worker containers: `celery-worker`, `temporal-worker`.
- `beehive up --with-open-webui` — Starts core services + `queen-api` + `open-webui` for chat (Queen via Open WebUI at `http://localhost:3000`).
- `beehive ps` — Shows Docker Compose status for Beehive services.
- `beehive down` — Stops Beehive Docker Compose services.
- `beehive restart` — Restarts all Docker Compose services (core, workers, queen-api, open-webui).
- `beehive reload` — Restarts `queen-api` only. Use after editing config to pick up changes.
- `beehive rebuild` / `beehive reset` — Rebuild Docker images with latest code and restart.
  - `beehive rebuild` or `beehive rebuild --all` — rebuild workers + queen-api.
  - `beehive rebuild --core` — rebuild workers only (celery-worker, temporal-worker).
  - `beehive rebuild --api` or `beehive rebuild --dashboard` — rebuild queen-api only.

**Tenant & onboarding**
- `beehive setup [--non-interactive]` — First-time setup wizard (doctor, tenant, optional admin).
- `beehive onboard [--non-interactive]` — Onboard a Queen into an existing hive.
- `beehive init-tenant --org <name> --hive <name> [--honeycomb-root .honeycomb]` — Creates org, hive, and honeycomb records in `.beekeeper_store`.

**Running the Queen**
- `beehive run --scheduler <inline|celery|temporal> --vector <memory|qdrant> --query "<text>"` — Runs a single Queen request.
- `beehive chat` — Interactive Queen chat in terminal. Use `--scheduler`, `--vector`, `--intent` to configure.
- `beehive pulse [--interval 2] [--honeycomb-root .honeycomb]` — Runs Pulse tick loop for Queen autonomy (cron jobs, backlog).

**APIs**
- `beekeeper-api` — Starts Beekeeper API on `http://localhost:8787`. Dashboard at `/dashboard` for channels, templates, settings.
- `queen-api` — OpenAI-compatible Queen API (used by Open WebUI). Runs in Docker when using `beehive up --with-open-webui` on port 8788.

**Review & metrics**
- `beehive review list` — Lists pending human-approval queue records.
- `beehive review approve <review_id> --approver <name> [--resume] [--note "..."]` — Approves and optionally resumes execution.
- `beehive review reject <review_id> --approver <name> [--note "..."]` — Rejects a human review.
- `beehive metrics [--honeycomb-root .honeycomb] [--webhook-url <url>]` — Computes Honeycomb telemetry and can send alerts to webhook.

**Settings & channels**
- `beehive settings list|get <key>|set <key> <json_value>` — Manage Beekeeper settings via CLI.
- `beehive channels list|set <channel> <json>` — Manage channel configs (slack, telegram, discord).

**Templates & sessions**
- `beehive templates list` — List agent templates.
- `beehive templates instantiate <template_id> --hive <hive_id> --name <queen_name>` — Instantiate a template as a Queen.
- `beehive sessions list|create|traces <session_id>|tree <trace_id>` — Session tree and branching.

**Traces**
- `beehive traces compact [--trace-id X] [--all] [--min-age-hours N]` — Compact trace files to reduce size.
- `beehive traces tree <trace_id>` — Show trace tree (session branching).
- `beehive traces fork <trace_id> [--session-id X]` — Fork a trace (create new branch).

**Plugins & misc**
- `beehive --help` — Shows top-level help and subcommands.
- `beehive install <package> [--editable] [--no-registry]` / `beehive install --list` — Install worker/guardrail package from PyPI.
- `beehive shell` — Interactive shell with command discovery. Type `help` or `commands` for options.
- `beehive commands` — List all commands with short descriptions.
- `beehive version` — Show installed version.
- `beehive update` — Upgrade beehive package (`pip install --upgrade beehive-agent-platform`).

## 5) `beehive run` options

```bash
beehive run \
  --scheduler <inline|celery|temporal> \
  --vector <memory|qdrant> \
  --intent <intent_name> \
  --query "<text>" \
  --payload '{"query":"text"}' \
  --honeycomb-root .honeycomb \
  --max-reruns 1
```

Notes:
- `--scheduler` default: `inline`
- `--vector` default: `memory`
- `--intent` default: `research_topic`
- `--query` and `--payload` are optional (payload is JSON string)
- `--honeycomb-root` default: `.honeycomb`
- `--max-reruns` default: `1`

## 6) Common examples

```bash
# 1) First-time setup
beehive setup

# 2) Start/check everything quickly
beehive

# 3) Only check dependencies
beehive doctor

# 4) Check + auto-start if needed
beehive doctor --auto-start

# 5) Bring infra up
beehive up

# 6) Bring infra + workers up
beehive up --with-workers

# 7) Bring infra + queen-api + Open WebUI for chat
beehive up --with-open-webui

# 8) Run via inline scheduler + memory vector store
beehive run --scheduler inline --vector memory --query "quick local test"

# 9) Interactive Queen chat
beehive chat --scheduler inline --vector memory

# 10) Run via celery + qdrant
beehive run --scheduler celery --vector qdrant --query "research agent guardrails"

# 11) Run via temporal + qdrant
beehive run --scheduler temporal --vector qdrant --query "durable orchestration setup"

# 12) View service status
beehive ps

# 13) Stop services
beehive down

# 14) List pending human approvals
beehive review list --honeycomb-root .honeycomb

# 15) Approve and resume a pending review
beehive review approve <review_id> --approver oncall --resume

# 16) Show metrics and alerts
beehive metrics --honeycomb-root .honeycomb

# 17) Start Beekeeper dashboard (run separately)
beekeeper-api

# 18) Initialize a tenant
beehive init-tenant --org "Acme" --hive "Ops Hive"
```

## 7) Environment variables

Copy `.env.example` to `.env` and configure. Key variables:

**LLM**
- `BEEHIVE_LLM_PROVIDER` (default `ollama`) — Primary provider: `ollama`, `gemini`, `openai`
- `BEEHIVE_LLM_PROVIDERS` — Comma-separated fallback chain (e.g. `ollama,gemini`)
- `BEEHIVE_OLLAMA_BASE_URL`, `BEEHIVE_OLLAMA_MODEL`, `BEEHIVE_OLLAMA_TIMEOUT_SECONDS`
- `BEEHIVE_GEMINI_API_KEY`, `BEEHIVE_GEMINI_MODEL`, `BEEHIVE_GEMINI_TIMEOUT_SECONDS`
- `BEEHIVE_OPENAI_API_KEY`, `BEEHIVE_OPENAI_MODEL`, `BEEHIVE_OPENAI_BASE_URL`, `BEEHIVE_OPENAI_TIMEOUT_SECONDS`

**Infrastructure**
- `BEEHIVE_CELERY_BROKER_URL` (default `redis://localhost:6379/0`)
- `BEEHIVE_CELERY_BACKEND_URL` (default `redis://localhost:6379/1`)
- `BEEHIVE_TEMPORAL_ENDPOINT` (default `localhost:7233`)
- `BEEHIVE_TEMPORAL_ENDPOINT_FALLBACKS` — Comma-separated fallbacks for Docker networking
- `BEEHIVE_TEMPORAL_NAMESPACE` (default `default`), `BEEHIVE_TEMPORAL_TASK_QUEUE` (default `beehive-queue`)
- `BEEHIVE_VECTOR_BACKEND` (default `qdrant`), `BEEHIVE_VECTOR_URL` (default `http://localhost:6333`)
- `BEEHIVE_VECTOR_COLLECTION` (default `honeycomb_memory`)
- `BEEHIVE_SEARXNG_BASE_URL` (default `http://localhost:8080`)

**Beekeeper**
- `BEEKEEPER_STORE_ROOT` (default `.beekeeper_store`)
- `BEEKEEPER_AUDIT_SIGNING_KEY` (default `beekeeper-dev-signing-key`)

**Channels** (optional)
- `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`

## 8) Troubleshooting

- **Docker daemon not running** — Start Docker Desktop and rerun.
- **Command not found for `beehive`** — Re-run `pip install -e .` in your active environment.
- **Upgrade beehive** — Run `beehive update` or `pip install --upgrade beehive-agent-platform`.
- **Ollama check fails** — Verify `BEEHIVE_OLLAMA_BASE_URL` is reachable from your machine.
- **LLM provider check fails** — Ensure API keys are set for `gemini`/`openai` when used in `BEEHIVE_LLM_PROVIDERS`.
