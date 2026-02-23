# 06 — Infrastructure & Deployment

## Docker Services

All services are orchestrated via `docker-compose.yml`. Start everything with:

```bash
docker compose up --build
```

Or use the CLI:

```bash
beekeeper up               # core services (Redis, Temporal, Qdrant, SearXNG)
beekeeper up --with-workers  # + Celery and Temporal workers
beekeeper up --with-open-webui  # + Open WebUI
```

### Service Map

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `redis` | `redis:7-alpine` | `6379` | Celery broker + result backend |
| `temporal` | `temporalio/server:latest` | `7233` (gRPC), `8233` (UI) | Durable workflow engine |
| `qdrant` | `qdrant/qdrant:latest` | `6333` (HTTP), `6334` (gRPC) | Vector database for semantic memory |
| `searxng` | `searxng/searxng:latest` | `8080` | Privacy-respecting web search |
| `celery-worker` | local build | — | Processes tasks from Redis queue |
| `temporal-worker` | local build | — | Executes Temporal workflow activities |
| `pulse` | local build | — | Background autonomous task scheduler |
| `queen-api` | local build | `8788` (host) | OpenAI-compatible Queen API |
| `open-webui` | `ghcr.io/open-webui/open-webui` | `3000` | Chat UI for users |

SearXNG is configured via a host-mounted settings file:

```bash
./searxng/settings.yml -> /etc/searxng/settings.yml
```

### Shared Volume: `honeycomb_data`

All workers, Pulse, and the Queen API share a Docker volume mounted at `/app/runtime/honeycomb` so all services read/write the same Honeycomb data.

---

## Scheduler Backends

### 1. Inline (default for local/CLI)

```
QueenAgent → InlineScheduler → WorkerRuntime (same Python process)
```

No external dependencies. Good for development and `beekeeper chat`.

### 2. Celery (queue-based)

```
QueenAgent → CeleryScheduler → Redis → Celery Worker → WorkerRuntime
```

- Set `BEEKEEPER_CELERY_BROKER_URL=redis://localhost:6379/0`
- Set `BEEKEEPER_CELERY_BACKEND_URL=redis://localhost:6379/1`
- Run: `celery -A beekeeper.celery_app.celery_app worker --loglevel=INFO`
- Use: `QueenConfig(scheduler_backend="celery")`

### 3. Temporal (durable workflows)

```
QueenAgent → TemporalBeekeeperClient → Temporal Server → Temporal Worker → WorkerRuntime
```

- Provides exactly-once execution, automatic retries, and visibility UI at `:8233`
- Run: `python -m beekeeper.temporal_worker`
- Use: `QueenConfig(scheduler_backend="temporal")`
- Set `BEEKEEPER_TEMPORAL_ENDPOINT=localhost:7233`

---

## LLM Provider Configuration

Providers are tried in order. First success wins.

```
BEEKEEPER_LLM_PROVIDERS=gemini,ollama  →  (compose default) tries Gemini first, then Ollama fallback
BEEKEEPER_LLM_PROVIDERS=ollama,gemini  →  Ollama first, Gemini fallback
BEEKEEPER_LLM_PROVIDER=ollama          →  single provider (legacy)
```

### Ollama (local)

```bash
BEEKEEPER_OLLAMA_BASE_URL=http://100.99.106.59:11434
BEEKEEPER_OLLAMA_MODEL=catsarethebest/qwen2.5-N2:1.5b
BEEKEEPER_OLLAMA_TIMEOUT_SECONDS=120
```

Model tier overrides:
```bash
BEEKEEPER_OLLAMA_MODEL_ECONOMY=tiny-model
BEEKEEPER_OLLAMA_MODEL_STANDARD=base-model
BEEKEEPER_OLLAMA_MODEL_PREMIUM=large-model
```

### Gemini (Google)

```bash
BEEKEEPER_GEMINI_API_KEY=your-key
BEEKEEPER_GEMINI_MODEL=gemini-1.5-flash
BEEKEEPER_GEMINI_TIMEOUT_SECONDS=120
```

### OpenAI (or compatible)

```bash
BEEKEEPER_OPENAI_API_KEY=your-key
BEEKEEPER_OPENAI_MODEL=gpt-4o-mini
BEEKEEPER_OPENAI_BASE_URL=https://api.openai.com/v1   # optional, for compatible endpoints
BEEKEEPER_OPENAI_TIMEOUT_SECONDS=120
```

---

## CLI Commands Reference

```bash
beekeeper                              # health check + auto-start Docker if needed
beekeeper quickstart                   # health check + init tenant + ready message
beekeeper chat                         # interactive chat loop
beekeeper chat --scheduler celery      # chat with Celery backend
beekeeper run --intent research_topic --payload '{"query":"..."}' # single run
beekeeper doctor                       # check all service dependencies
beekeeper doctor --auto-start          # check and start Docker services
beekeeper up                           # docker compose up (core services)
beekeeper up --with-workers            # + Celery and Temporal workers
beekeeper up --with-open-webui         # + Open WebUI
beekeeper ps                           # docker compose ps
beekeeper down                         # docker compose down
beekeeper restart                      # docker compose restart
beekeeper reload                       # hot reload app services
beekeeper rebuild [--core|--api|--all] # rebuild Docker images
beekeeper reset [--core|--api|--all]   # reset data/containers
beekeeper init-tenant --org "Acme" --hive "Ops"  # initialize tenant
beekeeper settings list|get|set        # manage settings
beekeeper channels list|set            # manage channel configs
beekeeper templates list|instantiate   # manage agent templates
beekeeper review list                  # list pending HITL reviews
beekeeper review approve <id> --approver oncall --resume  # approve review
beekeeper metrics                      # print metrics report
beekeeper pulse --interval 60          # run Pulse background scheduler
```

---

## Reverse Proxy / Remote Access

See `docs/REMOTE_ACCESS_AND_TAILSCALE.md` for:
- **Tailscale** — zero-config mesh VPN (recommended for home/remote dev)
- **ngrok** — public tunnel for webhook testing
- **Cloudflare Tunnel** — production-grade secure access
