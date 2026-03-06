# Beekeeper CLI: How To Use

**Quick start in 5 minutes:** `beekeeper quickstart` then `beekeeper chat`.

For choosing scheduler, worker, or channel, see [docs/DECISION_TREE.md](docs/DECISION_TREE.md).

## 1) Install the CLI command

From the project root:

```bash
pip install -e .
```

This installs the `beekeeper` command from `beekeeper.runner:main`. Also installs `beekeeper-api` and `queen-api` for dashboard and chat APIs.

If you do not want to install yet, you can still run:

```bash
python -m beekeeper.runner --help
```

## 2) First-time setup

**5-minute path:**
```bash
beekeeper quickstart
```
Runs health checks, initializes tenant with defaults, minimal prompts.

**Full interactive wizard:**
```bash
beekeeper setup
```
Copies `.env.example` to `.env` if needed, runs health checks, initializes org/hive/honeycomb, optionally creates an admin user. Use `--non-interactive` for CI/automation.

## 3) Fastest way to start

```bash
beekeeper
```

What `beekeeper` (no subcommand) does:
- Runs runtime health checks (`doctor`)
- If checks fail, tries to start core Docker services (`redis`, `temporal`, `qdrant`, `searxng`)
- Re-runs checks
- Prints a command guide

## 4) Command reference

**Infrastructure**
- `beekeeper` — Health check + auto-start core infra if required.
- `beekeeper doctor` — Health checks only. Use `--json` for machine-readable output.
- `beekeeper doctor --auto-start` — Health checks, then auto-starts core Docker infra if checks fail.
- `beekeeper up` — Starts core services: `redis`, `temporal`, `qdrant`, `searxng`.
- `beekeeper up --with-workers` — Starts core services + worker containers: `celery-worker`, `temporal-worker`.
- `beekeeper up --with-open-webui` — Starts core services + `queen-api` + `open-webui` for chat (Queen via Open WebUI at `http://localhost:3000`).
- `beekeeper ps` — Shows Docker Compose status for Beekeeper services.
- `beekeeper down` — Stops Beekeeper Docker Compose services.
- `beekeeper restart` — Restarts all Docker Compose services (core, workers, queen-api, open-webui).
- `beekeeper reload` — Restarts `queen-api` only. Use after editing config to pick up changes.
- `beekeeper rebuild` / `beekeeper reset` — Rebuild Docker images with latest code and restart.
  - `beekeeper rebuild` or `beekeeper rebuild --all` — rebuild workers + queen-api.
  - `beekeeper rebuild --core` — rebuild workers only (celery-worker, temporal-worker).
  - `beekeeper rebuild --api` or `beekeeper rebuild --dashboard` — rebuild queen-api only.

**Tenant & onboarding**
- `beekeeper setup [--non-interactive]` — First-time setup wizard (doctor, tenant, optional admin).
- `beekeeper onboard [--non-interactive]` — Onboard a Queen into an existing hive.
- `beekeeper init-tenant --org <name> --hive <name> [--honeycomb-root .honeycomb]` — Creates org, hive, and honeycomb records in `.beekeeper_store`.

**Running the Queen**
- `beekeeper run --scheduler <auto|inline|celery|temporal> --vector <memory|qdrant> --query "<text>"` — Runs a single Queen request.
- `beekeeper chat` — Interactive Queen chat in terminal. Use `--scheduler`, `--vector`, `--intent` to configure.
- `beekeeper pulse [--interval 2] [--honeycomb-root .honeycomb]` — Runs Pulse tick loop for Queen autonomy (cron jobs, backlog).

**APIs**
- `beekeeper-api` — Starts Beekeeper API on `http://localhost:8787`. Dashboard at `/dashboard` for channels, templates, settings.
- `queen-api` — OpenAI-compatible Queen API (used by Open WebUI). Runs in Docker when using `beekeeper up --with-open-webui` on port 8788.

**Review & metrics**
- `beekeeper review list` — Lists pending human-approval queue records.
- `beekeeper review approve <review_id> --approver <name> [--resume] [--note "..."]` — Approves and optionally resumes execution.
- `beekeeper review reject <review_id> --approver <name> [--note "..."]` — Rejects a human review.
- `beekeeper metrics [--honeycomb-root .honeycomb] [--webhook-url <url>]` — Computes Honeycomb telemetry and can send alerts to webhook.

**Settings & channels**
- `beekeeper settings list|get <key>|set <key> <json_value>` — Manage Beekeeper settings via CLI.
- `beekeeper channels list|set <channel> <json>` — Manage channel configs (slack, telegram, discord).

**Templates & sessions**
- `beekeeper templates list` — List agent templates.
- `beekeeper templates instantiate <template_id> --hive <hive_id> --name <queen_name>` — Instantiate a template as a Queen.
- `beekeeper sessions list|create|traces <session_id>|tree <trace_id>` — Session tree and branching.

**Traces**
- `beekeeper traces compact [--trace-id X] [--all] [--min-age-hours N]` — Compact trace files to reduce size.
- `beekeeper traces tree <trace_id>` — Show trace tree (session branching).
- `beekeeper traces fork <trace_id> [--session-id X]` — Fork a trace (create new branch).

**Plugins & misc**
- `beekeeper --help` — Shows top-level help and subcommands.
- `beekeeper install <package> [--editable] [--no-registry]` / `beekeeper install --list` — Install worker/guardrail package from PyPI.
- `beekeeper shell` — Interactive shell with command discovery. Type `help` or `commands` for options.
- `beekeeper commands` — List all commands with short descriptions.
- `beekeeper version` — Show installed version.
- `beekeeper update` — Upgrade beekeeper package (`pip install --upgrade beekeeper-agent-platform`).

## 5) `beekeeper run` options

```bash
beekeeper run \
  --scheduler <auto|inline|celery|temporal> \
  --vector <memory|qdrant> \
  --intent <intent_name> \
  --query "<text>" \
  --payload '{"query":"text"}' \
  --honeycomb-root .honeycomb \
  --max-reruns 1
```

Notes:
- `--scheduler` default: `auto`
- `--vector` default: `memory`
- `--intent` default: `research_topic`
- `--query` and `--payload` are optional (payload is JSON string)
- `--honeycomb-root` default: `.honeycomb`
- `--max-reruns` default: `1`

## 6) Common examples

```bash
# 1) First-time setup
beekeeper setup

# 2) Start/check everything quickly
beekeeper

# 3) Only check dependencies
beekeeper doctor

# 4) Check + auto-start if needed
beekeeper doctor --auto-start

# 5) Bring infra up
beekeeper up

# 6) Bring infra + workers up
beekeeper up --with-workers

# 7) Bring infra + queen-api + Open WebUI for chat
beekeeper up --with-open-webui

# 8) Run via auto scheduler + memory vector store
beekeeper run --scheduler auto --vector memory --query "quick local test"

# 9) Interactive Queen chat
beekeeper chat --scheduler auto --vector memory

# 10) Run via celery + qdrant
beekeeper run --scheduler celery --vector qdrant --query "research agent guardrails"

# 11) Run via temporal + qdrant
beekeeper run --scheduler temporal --vector qdrant --query "durable orchestration setup"

# 12) View service status
beekeeper ps

# 13) Stop services
beekeeper down

# 14) List pending human approvals
beekeeper review list --honeycomb-root .honeycomb

# 15) Approve and resume a pending review
beekeeper review approve <review_id> --approver oncall --resume

# 16) Show metrics and alerts
beekeeper metrics --honeycomb-root .honeycomb

# 17) Start Beekeeper dashboard (run separately)
beekeeper-api

# 18) Initialize a tenant
beekeeper init-tenant --org "Acme" --hive "Ops Hive"
```

## 7) Environment variables

Copy `.env.example` to `.env` and configure. Key variables:

**LLM**
- `BEEKEEPER_LLM_PROVIDER` (default `ollama`) — Primary provider: `ollama`, `gemini`, `openai`
- `BEEKEEPER_LLM_PROVIDERS` — Comma-separated fallback chain (e.g. `ollama,gemini`)
- Precedence: `BEEKEEPER_LLM_PROVIDERS` overrides `BEEKEEPER_LLM_PROVIDER`.
- CLI/session env overrides (for example `BEEKEEPER_LLM_PROVIDER=ollama beekeeper run ...`) take precedence over `.env`.
- `BEEKEEPER_OLLAMA_BASE_URL`, `BEEKEEPER_OLLAMA_MODEL`, `BEEKEEPER_OLLAMA_TIMEOUT_SECONDS`
- `BEEKEEPER_GEMINI_API_KEY`, `BEEKEEPER_GEMINI_MODEL`, `BEEKEEPER_GEMINI_TIMEOUT_SECONDS`
- `BEEKEEPER_OPENAI_API_KEY`, `BEEKEEPER_OPENAI_MODEL`, `BEEKEEPER_OPENAI_BASE_URL`, `BEEKEEPER_OPENAI_TIMEOUT_SECONDS`

**Infrastructure**
- `BEEKEEPER_CELERY_BROKER_URL` (default `redis://localhost:6379/0`)
- `BEEKEEPER_CELERY_BACKEND_URL` (default `redis://localhost:6379/1`)
- `BEEKEEPER_TEMPORAL_ENDPOINT` (default `localhost:7233`)
- `BEEKEEPER_TEMPORAL_ENDPOINT_FALLBACKS` — Comma-separated fallbacks for Docker networking
- `BEEKEEPER_TEMPORAL_NAMESPACE` (default `default`), `BEEKEEPER_TEMPORAL_TASK_QUEUE` (default `beekeeper-queue`)
- `BEEKEEPER_VECTOR_BACKEND` (default `qdrant`), `BEEKEEPER_VECTOR_URL` (default `http://localhost:6333`)
- `BEEKEEPER_VECTOR_COLLECTION` (default `honeycomb_memory`)
- `BEEKEEPER_SEARXNG_BASE_URL_LOCAL` (default `http://localhost:8080`) for local CLI and host runs
- `BEEKEEPER_SEARXNG_BASE_URL_DOCKER` (default `http://searxng:8080`) for Docker services
- `BEEKEEPER_SEARXNG_BASE_URL` legacy fallback (kept for backward compatibility)

**Beekeeper**
- `BEEKEEPER_STORE_ROOT` (default `.beekeeper_store`)
- `BEEKEEPER_AUDIT_SIGNING_KEY` (default `beekeeper-dev-signing-key`)

**Channels** (optional)
- `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`

## 8) Troubleshooting

- **Docker daemon not running** — Start Docker Desktop and rerun.
- **Command not found for `beekeeper`** — Re-run `pip install -e .` in your active environment.
- **Upgrade beekeeper** — Run `beekeeper update` or `pip install --upgrade beekeeper-agent-platform`.
- **Ollama check fails** — Verify `BEEKEEPER_OLLAMA_BASE_URL` is reachable from your machine.
- **Expected Ollama but got Gemini/OpenAI** — Set both `BEEKEEPER_LLM_PROVIDER=ollama` and `BEEKEEPER_LLM_PROVIDERS=ollama` for single-provider runs, or order your chain explicitly (for example `ollama,gemini`).
- **LLM provider check fails** — Ensure API keys are set for `gemini`/`openai` when used in `BEEKEEPER_LLM_PROVIDERS`.
