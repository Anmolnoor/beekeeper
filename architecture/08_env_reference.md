# 08 — Environment Variables Reference

All environment variables used by the platform. Set them in `.env` (loaded automatically) or export in your shell.

---

## Core Runtime

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEHIVE_HONEYCOMB_ROOT` | `.honeycomb` | Path to the Honeycomb data directory |
| `BEEHIVE_SCHEDULER_BACKEND` | `inline` | Scheduler: `inline` \| `celery` \| `temporal` |
| `BEEHIVE_VECTOR_BACKEND` | `memory` | Vector store: `memory` \| `qdrant` |
| `BEEHIVE_VECTOR_URL` | `http://localhost:6333` | Qdrant server URL |
| `BEEHIVE_VECTOR_COLLECTION` | `honeycomb_memory` | Qdrant collection name |
| `BEEKEEPER_STORE_ROOT` | `.beekeeper_store` | Path to the Beekeeper multi-tenant store |

---

## LLM Providers

### Provider Selection

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEHIVE_LLM_PROVIDERS` | _(not set)_ | Comma-separated ordered list: `ollama,gemini,openai` |
| `BEEHIVE_LLM_PROVIDER` | `ollama` | Legacy single-provider setting (overridden by `BEEHIVE_LLM_PROVIDERS`) |

### Ollama

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEHIVE_OLLAMA_BASE_URL` | `http://100.99.106.59:11434` | Ollama server base URL |
| `BEEHIVE_OLLAMA_MODEL` | `catsarethebest/qwen2.5-N2:1.5b` | Default model |
| `BEEHIVE_OLLAMA_TIMEOUT_SECONDS` | `120` | Request timeout |
| `BEEHIVE_OLLAMA_MODEL_ECONOMY` | _(unset)_ | Model for economy tier |
| `BEEHIVE_OLLAMA_MODEL_STANDARD` | _(unset)_ | Model for standard tier |
| `BEEHIVE_OLLAMA_MODEL_PREMIUM` | _(unset)_ | Model for premium tier |

### Gemini

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEHIVE_GEMINI_API_KEY` | _(required)_ | Google API key |
| `BEEHIVE_GEMINI_MODEL` | `gemini-1.5-flash` | Default model |
| `BEEHIVE_GEMINI_TIMEOUT_SECONDS` | `120` | Request timeout |
| `BEEHIVE_GEMINI_MODEL_ECONOMY` | _(unset)_ | Economy tier model |
| `BEEHIVE_GEMINI_MODEL_STANDARD` | _(unset)_ | Standard tier model |
| `BEEHIVE_GEMINI_MODEL_PREMIUM` | _(unset)_ | Premium tier model |

### OpenAI

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEHIVE_OPENAI_API_KEY` | _(required)_ | OpenAI API key |
| `BEEHIVE_OPENAI_MODEL` | `gpt-4o-mini` | Default model |
| `BEEHIVE_OPENAI_BASE_URL` | `https://api.openai.com/v1` | API base (override for compatible endpoints) |
| `BEEHIVE_OPENAI_TIMEOUT_SECONDS` | `120` | Request timeout |

---

## Celery

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEHIVE_CELERY_BROKER_URL` | `redis://localhost:6379/0` | Redis broker URL |
| `BEEHIVE_CELERY_BACKEND_URL` | `redis://localhost:6379/1` | Redis result backend URL |

---

## Temporal

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEHIVE_TEMPORAL_ENDPOINT` | `localhost:7233` | Temporal gRPC endpoint |
| `BEEHIVE_TEMPORAL_NAMESPACE` | `default` | Temporal namespace |
| `BEEHIVE_TEMPORAL_TASK_QUEUE` | `beehive-queue` | Task queue name |
| `BEEHIVE_TEMPORAL_ENDPOINT_FALLBACKS` | _(unset)_ | Comma-separated fallback endpoints, e.g. `temporal:7233,localhost:7233` |

---

## Web Search

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEHIVE_SEARXNG_BASE_URL` | `http://localhost:8080` | SearXNG instance URL |

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
BEEHIVE_LLM_PROVIDERS=ollama,gemini
BEEHIVE_OLLAMA_BASE_URL=http://100.99.106.59:11434
BEEHIVE_OLLAMA_MODEL=catsarethebest/qwen2.5-N2:1.5b
BEEHIVE_OLLAMA_TIMEOUT_SECONDS=120
BEEHIVE_GEMINI_API_KEY=your-gemini-key
BEEHIVE_GEMINI_MODEL=gemini-1.5-flash

# Runtime
BEEHIVE_HONEYCOMB_ROOT=.honeycomb
BEEHIVE_SCHEDULER_BACKEND=inline
BEEHIVE_VECTOR_BACKEND=qdrant
BEEHIVE_VECTOR_URL=http://localhost:6333
BEEHIVE_VECTOR_COLLECTION=honeycomb_memory

# Search
BEEHIVE_SEARXNG_BASE_URL=http://localhost:8080

# Celery (if using Celery scheduler)
BEEHIVE_CELERY_BROKER_URL=redis://localhost:6379/0
BEEHIVE_CELERY_BACKEND_URL=redis://localhost:6379/1

# Temporal (if using Temporal scheduler)
BEEHIVE_TEMPORAL_ENDPOINT=localhost:7233
BEEHIVE_TEMPORAL_NAMESPACE=default
BEEHIVE_TEMPORAL_TASK_QUEUE=beehive-queue

# Security
BEEKEEPER_JWT_SECRET=change-me-in-production
BEEKEEPER_AUDIT_SIGNING_KEY=change-me-in-production
BEEKEEPER_CHANNEL_ENCRYPTION_KEY=change-me-in-production
```
