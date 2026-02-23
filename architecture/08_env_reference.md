# 08 — Environment Variables Reference

All environment variables used by the platform. Set them in `.env` (loaded automatically) or export in your shell.

---

## Core Runtime

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEKEEPER_HONEYCOMB_ROOT` | `.honeycomb` | Path to the Honeycomb data directory |
| `BEEKEEPER_SCHEDULER_BACKEND` | `inline` | Scheduler: `inline` \| `celery` \| `temporal` |
| `BEEKEEPER_VECTOR_BACKEND` | `memory` | Vector store: `memory` \| `qdrant` |
| `BEEKEEPER_VECTOR_URL` | `http://localhost:6333` | Qdrant server URL |
| `BEEKEEPER_VECTOR_COLLECTION` | `honeycomb_memory` | Qdrant collection name |
| `BEEKEEPER_STORE_ROOT` | `.beekeeper_store` | Path to the Beekeeper multi-tenant store |

---

## LLM Providers

### Provider Selection

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEKEEPER_LLM_PROVIDERS` | _(not set)_ | Comma-separated ordered list: `ollama,gemini,openai` |
| `BEEKEEPER_LLM_PROVIDER` | `ollama` | Legacy single-provider setting (overridden by `BEEKEEPER_LLM_PROVIDERS`) |

> In `docker-compose.yml`, several services set
> `BEEKEEPER_LLM_PROVIDERS=${BEEKEEPER_LLM_PROVIDERS:-gemini,ollama}`, so the
> compose default order is Gemini first, then Ollama.

### Ollama

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEKEEPER_OLLAMA_BASE_URL` | `http://100.99.106.59:11434` | Ollama server base URL |
| `BEEKEEPER_OLLAMA_MODEL` | `catsarethebest/qwen2.5-N2:1.5b` | Default model |
| `BEEKEEPER_OLLAMA_TIMEOUT_SECONDS` | `120` | Request timeout |
| `BEEKEEPER_OLLAMA_MODEL_ECONOMY` | _(unset)_ | Model for economy tier |
| `BEEKEEPER_OLLAMA_MODEL_STANDARD` | _(unset)_ | Model for standard tier |
| `BEEKEEPER_OLLAMA_MODEL_PREMIUM` | _(unset)_ | Model for premium tier |

### Gemini

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEKEEPER_GEMINI_API_KEY` | _(required)_ | Google API key |
| `BEEKEEPER_GEMINI_MODEL` | `gemini-1.5-flash` | Default model |
| `BEEKEEPER_GEMINI_TIMEOUT_SECONDS` | `120` | Request timeout |
| `BEEKEEPER_GEMINI_MODEL_ECONOMY` | _(unset)_ | Economy tier model |
| `BEEKEEPER_GEMINI_MODEL_STANDARD` | _(unset)_ | Standard tier model |
| `BEEKEEPER_GEMINI_MODEL_PREMIUM` | _(unset)_ | Premium tier model |

### OpenAI

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEKEEPER_OPENAI_API_KEY` | _(required)_ | OpenAI API key |
| `BEEKEEPER_OPENAI_MODEL` | `gpt-4o-mini` | Default model |
| `BEEKEEPER_OPENAI_BASE_URL` | `https://api.openai.com/v1` | API base (override for compatible endpoints) |
| `BEEKEEPER_OPENAI_TIMEOUT_SECONDS` | `120` | Request timeout |

---

## Celery

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEKEEPER_CELERY_BROKER_URL` | `redis://localhost:6379/0` | Redis broker URL |
| `BEEKEEPER_CELERY_BACKEND_URL` | `redis://localhost:6379/1` | Redis result backend URL |

> In Docker Compose services, use container DNS names (for example
> `redis://redis:6379/0`) instead of `localhost`.

---

## Temporal

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEKEEPER_TEMPORAL_ENDPOINT` | `localhost:7233` | Temporal gRPC endpoint |
| `BEEKEEPER_TEMPORAL_NAMESPACE` | `default` | Temporal namespace |
| `BEEKEEPER_TEMPORAL_TASK_QUEUE` | `beekeeper-queue` | Task queue name |
| `BEEKEEPER_TEMPORAL_ENDPOINT_FALLBACKS` | _(unset)_ | Comma-separated fallback endpoints, e.g. `temporal:7233,localhost:7233` |

---

## Web Search

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEKEEPER_SEARXNG_BASE_URL` | `http://localhost:8080` | SearXNG instance URL |

---

## Security

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEKEEPER_AUDIT_SIGNING_KEY` | _(required for signed logs)_ | HMAC key for audit log signing |
| `BEEKEEPER_CHANNEL_ENCRYPTION_KEY` | _(required for channel secrets)_ | NaCl secret box key for channel config encryption |
| `BEEKEEPER_JWT_SECRET` | _(required)_ | JWT signing secret for Beekeeper API auth |

---

## Beekeeper API

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEKEEPER_API_PORT` | `8787` | Port for Beekeeper API |
| `BEEKEEPER_API_HOST` | `0.0.0.0` | Host for Beekeeper API |

---

## Queen API

| Variable | Default | Description |
|----------|---------|-------------|
| `QUEEN_API_PORT` | `8788` | Port for Queen API |

---

## Example `.env` File

```bash
# LLM
BEEKEEPER_LLM_PROVIDERS=ollama,gemini
BEEKEEPER_OLLAMA_BASE_URL=http://100.99.106.59:11434
BEEKEEPER_OLLAMA_MODEL=catsarethebest/qwen2.5-N2:1.5b
BEEKEEPER_OLLAMA_TIMEOUT_SECONDS=120
BEEKEEPER_GEMINI_API_KEY=your-gemini-key
BEEKEEPER_GEMINI_MODEL=gemini-1.5-flash

# Runtime
BEEKEEPER_HONEYCOMB_ROOT=.honeycomb
BEEKEEPER_SCHEDULER_BACKEND=inline
BEEKEEPER_VECTOR_BACKEND=qdrant
BEEKEEPER_VECTOR_URL=http://localhost:6333
BEEKEEPER_VECTOR_COLLECTION=honeycomb_memory

# Search
BEEKEEPER_SEARXNG_BASE_URL=http://localhost:8080

# Celery (if using Celery scheduler)
BEEKEEPER_CELERY_BROKER_URL=redis://localhost:6379/0
BEEKEEPER_CELERY_BACKEND_URL=redis://localhost:6379/1

# Temporal (if using Temporal scheduler)
BEEKEEPER_TEMPORAL_ENDPOINT=localhost:7233
BEEKEEPER_TEMPORAL_NAMESPACE=default
BEEKEEPER_TEMPORAL_TASK_QUEUE=beekeeper-queue

# Security
BEEKEEPER_JWT_SECRET=change-me-in-production
BEEKEEPER_AUDIT_SIGNING_KEY=change-me-in-production
BEEKEEPER_CHANNEL_ENCRYPTION_KEY=change-me-in-production
```
