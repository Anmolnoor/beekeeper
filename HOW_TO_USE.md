# Beehive CLI: How To Use

## 1) Install the CLI command

From the project root:

```bash
pip install -e .
```

This installs the `beehive` command from `beehive.runner:main`.

If you do not want to install yet, you can still run:

```bash
python -m beehive.runner --help
```

## 2) Fastest way to start

```bash
beehive
```

What `beehive` (no subcommand) does:
- Runs runtime health checks (`doctor`)
- If checks fail, tries to start core Docker services (`redis`, `temporal`, `qdrant`, `searxng`)
- Re-runs checks
- Prints a command guide

## 3) Command reference

- `beehive`
  - Health check + auto-start core infra if required.

- `beehive doctor`
  - Health checks only.

- `beehive doctor --auto-start`
  - Health checks, then auto-starts core Docker infra if checks fail.

- `beehive up`
  - Starts core services: `redis`, `temporal`, `qdrant`, `searxng`.

- `beehive up --with-workers`
  - Starts core services + worker containers: `celery-worker`, `temporal-worker`.

- `beehive ps`
  - Shows Docker Compose status for Beehive services.

- `beehive down`
  - Stops Beehive Docker Compose services.

- `beehive review list`
  - Lists pending human-approval queue records.

- `beehive review approve <review_id> --approver <name> --resume`
  - Approves a human review and optionally resumes execution via Queen.

- `beehive review reject <review_id> --approver <name>`
  - Rejects a human review.

- `beehive metrics [--webhook-url <url>]`
  - Computes Honeycomb telemetry (HITL pressure, quality drift, latency/cost trends) and can send alerts to webhook.

- `beehive run --scheduler ... --vector ... --query ...`
  - Runs a single Queen request.

- `beehive --help`
  - Shows top-level help and subcommands.

## 4) `beehive run` options

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

## 5) Common examples

```bash
# 1) Start/check everything quickly
beehive

# 2) Only check dependencies
beehive doctor

# 3) Check + auto-start if needed
beehive doctor --auto-start

# 4) Bring infra up
beehive up

# 5) Bring infra + workers up
beehive up --with-workers

# 6) Run via inline scheduler + memory vector store
beehive run --scheduler inline --vector memory --query "quick local test"

# 7) Run via celery + qdrant
beehive run --scheduler celery --vector qdrant --query "research agent guardrails"

# 8) Run via temporal + qdrant
beehive run --scheduler temporal --vector qdrant --query "durable orchestration setup"

# 9) View service status
beehive ps

# 10) Stop services
beehive down

# 11) List pending human approvals
beehive review list --honeycomb-root .honeycomb

# 12) Approve and resume a pending review
beehive review approve <review_id> --approver oncall --resume

# 13) Show metrics and alerts
beehive metrics --honeycomb-root .honeycomb
```

## 6) Environment variables used by CLI/runtime

- `BEEHIVE_CELERY_BROKER_URL` (default `redis://localhost:6379/0`)
- `BEEHIVE_CELERY_BACKEND_URL` (default `redis://localhost:6379/1`)
- `BEEHIVE_TEMPORAL_ENDPOINT` (default `localhost:7233`)
- `BEEHIVE_TEMPORAL_NAMESPACE` (default `default`)
- `BEEHIVE_TEMPORAL_TASK_QUEUE` (default `beehive-queue`)
- `BEEHIVE_VECTOR_URL` (default `http://localhost:6333`)
- `BEEHIVE_VECTOR_COLLECTION` (default `honeycomb_memory`)
- `BEEHIVE_OLLAMA_BASE_URL` (default `http://100.99.106.59:11434`)
- `BEEHIVE_SEARXNG_BASE_URL` (default `http://localhost:8080`)

## 7) Troubleshooting

- If `beehive` says Docker daemon is not running:
  - Start Docker Desktop and rerun.
- If command not found for `beehive`:
  - Re-run `pip install -e .` in your active environment.
- If Ollama check fails:
  - Verify `BEEHIVE_OLLAMA_BASE_URL` is reachable from your machine.
