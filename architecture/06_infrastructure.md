# 06 — Infrastructure & Deployment

## Docker Services

All services are orchestrated via `docker-compose.yml`. Start everything with:

```bash
docker compose up --build
```

Or use the CLI:

```bash
beehive up               # core services (Redis, Temporal, Qdrant, SearXNG)
beehive up --with-workers  # + Celery and Temporal workers
beehive up --with-open-webui  # + Open WebUI
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

### Shared Volume: `honeycomb_data`

All workers, Pulse, and the Queen API share a Docker volume mounted at `/app/runtime/honeycomb` so all services read/write the same Honeycomb data.

---

## Scheduler Backends

### 1. Inline (default for local/CLI)

```
QueenAgent → InlineScheduler → WorkerRuntime (same Python process)
```

No external dependencies. Good for development and `beehive chat`.

### 2. Celery (queue-based)

```
QueenAgent → CeleryScheduler → Redis → Celery Worker → WorkerRuntime
```

- Set `BEEHIVE_CELERY_BROKER_URL=redis://localhost:6379/0`
- Set `BEEHIVE_CELERY_BACKEND_URL=redis://localhost:6379/1`
- Run: `celery -A beehive.celery_app.celery_app worker --loglevel=INFO`
- Use: `QueenConfig(scheduler_backend="celery")`

### 3. Temporal (durable workflows)

```
QueenAgent → TemporalBeehiveClient → Temporal Server → Temporal Worker → WorkerRuntime
```

- Provides exactly-once execution, automatic retries, and visibility UI at `:8233`
- Run: `python -m beehive.temporal_worker`
- Use: `QueenConfig(scheduler_backend="temporal")`
- Set `BEEHIVE_TEMPORAL_ENDPOINT=localhost:7233`

---

## LLM Provider Configuration

Providers are tried in order. First success wins.

```
BEEHIVE_LLM_PROVIDERS=ollama,gemini  →  tries Ollama first, Gemini as fallback
BEEHIVE_LLM_PROVIDER=ollama          →  single provider (legacy)
```

### Ollama (local)

```bash
BEEHIVE_OLLAMA_BASE_URL=http://100.99.106.59:11434
BEEHIVE_OLLAMA_MODEL=catsarethebest/qwen2.5-N2:1.5b
BEEHIVE_OLLAMA_TIMEOUT_SECONDS=120
```

Model tier overrides:
```bash
BEEHIVE_OLLAMA_MODEL_ECONOMY=tiny-model
BEEHIVE_OLLAMA_MODEL_STANDARD=base-model
BEEHIVE_OLLAMA_MODEL_PREMIUM=large-model
```

### Gemini (Google)

```bash
BEEHIVE_GEMINI_API_KEY=your-key
BEEHIVE_GEMINI_MODEL=gemini-1.5-flash
BEEHIVE_GEMINI_TIMEOUT_SECONDS=120
```

### OpenAI (or compatible)

```bash
BEEHIVE_OPENAI_API_KEY=your-key
BEEHIVE_OPENAI_MODEL=gpt-4o-mini
BEEHIVE_OPENAI_BASE_URL=https://api.openai.com/v1   # optional, for compatible endpoints
BEEHIVE_OPENAI_TIMEOUT_SECONDS=120
```

---

## CLI Commands Reference

```bash
beehive                              # health check + auto-start Docker if needed
beehive quickstart                   # health check + init tenant + ready message
beehive chat                         # interactive chat loop
beehive chat --scheduler celery      # chat with Celery backend
beehive run --intent research_topic --payload '{"query":"..."}' # single run
beehive doctor                       # check all service dependencies
beehive doctor --auto-start          # check and start Docker services
beehive up                           # docker compose up (core services)
beehive up --with-workers            # + Celery and Temporal workers
beehive up --with-open-webui         # + Open WebUI
beehive ps                           # docker compose ps
beehive down                         # docker compose down
beehive restart                      # docker compose restart
beehive reload                       # hot reload app services
beehive rebuild [--core|--api|--all] # rebuild Docker images
beehive reset [--core|--api|--all]   # reset data/containers
beehive init-tenant --org "Acme" --hive "Ops"  # initialize tenant
beehive settings list|get|set        # manage settings
beehive channels list|set            # manage channel configs
beehive templates list|instantiate   # manage agent templates
beehive review list                  # list pending HITL reviews
beehive review approve <id> --approver oncall --resume  # approve review
beehive metrics                      # print metrics report
beehive pulse --interval 60          # run Pulse background scheduler
```

---

## Reverse Proxy / Remote Access

See `docs/REMOTE_ACCESS_AND_TAILSCALE.md` for:
- **Tailscale** — zero-config mesh VPN (recommended for home/remote dev)
- **ngrok** — public tunnel for webhook testing
- **Cloudflare Tunnel** — production-grade secure access
