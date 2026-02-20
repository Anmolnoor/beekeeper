# Beehive Agent Platform

Reference implementation of a beehive-style multi-agent architecture:

- `QueenAgent` decomposes requests into atomic tasks.
- Workers are ephemeral, execute one task, persist results, and terminate.
- Specialist workers are first-class: `web_search`, `heavy_compute`, and `audit`.
- Honeycomb stores events, artifacts, governance decisions, and traces.
- Skills, rules, guardrails, and soul profiles are first-class runtime controls.
- Queue-backed scheduling via Redis/Celery.
- Durable worker execution via Temporal workflows.
- Semantic memory adapters with in-memory and Qdrant backends.

## Quick Start

```bash
python -m beehive.demo
```

Or with CLI:

```bash
beehive run --scheduler inline --vector memory --query "best agent sdk patterns"
```

## One-Command Infra Boot

```bash
docker compose up --build
```

This starts:
- Redis (`6379`)
- Temporal (`7233`, UI `8233`)
- Qdrant (`6333`)
- SearXNG (`8080`)
- Celery worker
- Temporal worker

Compose reads `.env`, including:
- `BEEHIVE_LLM_PROVIDER=ollama`
- `BEEHIVE_OLLAMA_BASE_URL=http://100.99.106.59:11434`
- `BEEHIVE_OLLAMA_MODEL=catsarethebest/qwen2.5-N2:1.5b`
- `BEEHIVE_OLLAMA_TIMEOUT_SECONDS=120`
- `BEEHIVE_GEMINI_MODEL=gemini-1.5-flash`
- `BEEHIVE_GEMINI_TIMEOUT_SECONDS=120`
- `BEEHIVE_SEARXNG_BASE_URL=http://localhost:8080`

## Layout

- `beehive/contracts.py` core typed schemas and versioned envelopes.
- `beehive/queen.py` queen planner/router and execution loop.
- `beehive/worker.py` worker runtime.
- `beehive/worker.py` specialist worker runtime and lifecycle hooks.
- `beehive/honeycomb.py` append-only data plane.
- `beehive/guardrails.py` guardrail framework and built-ins.
- `beehive/monitor.py` sentinel monitor and rerun triggers.
- `beehive/tracing.py` simple trace/span instrumentation.
- `beehive/scheduler.py` inline and Celery-backed scheduler adapters.
- `beehive/celery_app.py` Celery task app for queue workers.
- `beehive/temporal_integration.py` Temporal workflow, activity, and worker client.
- `beehive/vector_store.py` semantic vector adapters (`memory`, `qdrant`).

## Celery Queue Runtime

```bash
export BEEHIVE_CELERY_BROKER_URL=redis://localhost:6379/0
export BEEHIVE_CELERY_BACKEND_URL=redis://localhost:6379/1
export BEEHIVE_HONEYCOMB_ROOT=.honeycomb
celery -A beehive.celery_app.celery_app worker --loglevel=INFO
```

Set `QueenConfig(scheduler_backend="celery")` to dispatch worker tasks to the queue.

## Temporal Runtime

Start a Temporal server, then run:

```bash
python -m beehive.temporal_worker
```

Set `QueenConfig(scheduler_backend="temporal")` for durable execution.
If the runtime environment differs (host vs Docker), set
`BEEHIVE_TEMPORAL_ENDPOINT` and optionally
`BEEHIVE_TEMPORAL_ENDPOINT_FALLBACKS=temporal:7233,localhost:7233,host.docker.internal:7233`.

## CLI Runner

Run directly against your stack:

```bash
beehive run --scheduler celery --vector qdrant --query "research agent guardrails"
beehive run --scheduler temporal --vector qdrant --query "durable orchestration setup"
beehive run --scheduler inline --vector memory --query "quick local test"
beehive run --scheduler inline --intent heavy_compute --payload '{"numbers":[12,18,5,9],"operation":"distribution_summary"}'
```

Specialist worker intent examples:

```bash
# Web/search worker path
beehive run --intent research_topic --payload '{"query":"agent reliability design","domains":["docs.python.org","github.com"]}'

# Heavy-compute worker path
beehive run --intent heavy_compute --payload '{"numbers":[2,4,6,8,10],"operation":"distribution_summary"}'

# Audit worker path (typically created by Queen as child task)
beehive run --intent audit_result --payload '{"target_task_id":"demo-task","target_result":{"confidence":0.74}}'
```

Phase 4 governance/HITL examples:

```bash
# High-risk action is held for human approval
beehive run --intent research_topic --payload '{"query":"prepare billing migration note","action":"payment_action","requires_human_approval":true}'

# Same task with explicit approval moves forward
beehive run --intent research_topic --payload '{"query":"prepare billing migration note","action":"payment_action","requires_human_approval":true,"human_approved":true,"human_approver":"oncall-lead"}'
```

Phase 5 optimization telemetry:
- worker performance events are written under `.honeycomb/performance/`
- adaptive routing feedback is persisted at `.honeycomb/optimizer/routing_feedback.json`
- monitor events include `quality_score` and retry taxonomy (`transient/tool/model/policy/quality`)
- routing feedback stores recency-weighted quality plus per-intent/per-skill slices

Phase 6 retention lifecycle:
- artifacts newer than 30 days stay hot in `.honeycomb/artifacts/`
- artifacts older than 30 days move to `.honeycomb/archive/warm/`
- artifacts older than 90 days move to `.honeycomb/archive/cold/`

Service health check:

```bash
beehive doctor
```

One-command bootstrap (recommended):

```bash
beehive
```

What it does:
- runs `doctor`
 - if checks fail, tries `docker compose up -d redis temporal qdrant searxng`
- reruns checks and prints a quick command guide

Useful CLI commands:

```bash
beehive --help
beehive chat --scheduler inline
beehive doctor --auto-start
beehive up
beehive up --with-workers
beehive ps
beehive down
beehive review list --honeycomb-root .honeycomb
beehive review approve <review_id> --approver oncall --resume
beehive metrics --honeycomb-root .honeycomb
```

## Interactive Queen Chat

Start a chat loop in your terminal:

```bash
beehive chat --scheduler inline --intent research_topic
```

Chat controls:
- `/intent <name>` switches intent (example: `/intent heavy_compute`)
- `/exit` or `/quit` exits the chat
- plain text sends payload as `{"query": "..."}`
- JSON object input sends the raw payload directly
- Queen web/chat replies use Ollama when reachable; otherwise they fall back with a clear notice.

Temporary Gemini override for one command:

```bash
BEEHIVE_LLM_PROVIDER=gemini BEEHIVE_GEMINI_MODEL=gemini-1.5-flash beehive chat --scheduler inline --intent research_topic
```

Optional env for model endpoint:

```bash
export BEEHIVE_OLLAMA_BASE_URL=http://100.99.106.59:11434
```

## Queen Soul

The Queen now uses a dedicated soul profile at:
- `beehive/souls/queen.soul.json`
- `beehive/souls/queen.soul.md`

The profile is designed from high-signal traits common in leading assistant frameworks:
- constitutional helpfulness/honesty/harmlessness
- explicit uncertainty and confidence reporting
- strict escalation and policy-first behavior
- deterministic, evidence-first orchestration

## Operations Runbook

Recommended alert thresholds:
- **HITL queue pressure**: alert if `needs_human_approval` decisions exceed 5 per 10 minutes.
- **Quality drift**: alert if moving average `quality_score` falls below `0.65` for any worker kind.
- **Latency regression**: alert if heavy-compute `latency_ms` p95 exceeds `10000`.
- **Cost guard**: alert if average `estimated_cost_usd` rises above task budget by more than 10%.

Operational checks:
1. Verify routing feedback freshness (`updated_at`) in `.honeycomb/optimizer/routing_feedback.json`.
2. Inspect latest monitor decisions in `.honeycomb/events/*.jsonl` for repeated retry categories.
3. Inspect pending human approvals with `beehive review list`.
4. Run `beehive metrics` and check for alert entries (or route alerts via `--webhook-url`).
5. Run demo scenarios (`python -m beehive.demo`) to validate blocked, approved, and optimized paths.
