# 09 — Running with Docker Compose & Open WebUI

Chat with the Queen through a browser using Open WebUI, backed by the full
Beehive stack (Qdrant vector store, SearXNG web search, Queen API).

---

## Prerequisites

| Requirement | Check |
|-------------|-------|
| Docker Desktop running | `docker info` |
| `.env` file configured | `cp .env.example .env` then fill in LLM keys |
| Project installed | `pip install -e .` (for the `beehive` CLI) |

> [!IMPORTANT]
> You must set at least **one LLM provider** in `.env`:
> - Ollama: `BEEHIVE_OLLAMA_BASE_URL=http://<host>:11434`
> - Gemini: `BEEHIVE_GEMINI_API_KEY=your-key`
> - OpenAI: `BEEHIVE_OPENAI_API_KEY=your-key`

---

## Step 1 — First-time setup

```bash
cd /Users/anmolnoor/Developer/agent

# Copy and edit env file
cp .env.example .env
# (open .env and fill in your LLM provider key)

# Run setup wizard
beehive setup
```

`beehive setup` checks your environment, initialises the default tenant, and
verifies Docker services are reachable.

---

## Step 2 — Start everything

### Option A — One command (recommended)

```bash
beehive up --with-open-webui
```

This starts:
- `redis` (task broker)
- `qdrant` (vector memory)
- `searxng` (web search)
- `temporal` (durable scheduling)
- `queen-api` → **`http://localhost:8788`**
- `open-webui` → **`http://localhost:3000`** ← chat here

### Option B — Docker Compose directly

```bash
docker-compose up -d redis qdrant searxng temporal queen-api open-webui
```

### Option C — Minimal (no Temporal/Celery)

```bash
docker-compose up -d qdrant searxng queen-api open-webui
```

> [!NOTE]
> Omitting `temporal` and `redis` is fine when `BEEHIVE_SCHEDULER_BACKEND=inline`
> (the default). The Queen runs tasks in-process without a queue.

---

## Step 3 — Open the UI

Go to **[http://localhost:3000](http://localhost:3000)**

On first launch, create an admin account (any username/password — it's local).

---

## Step 4 — Connect Open WebUI to the Queen API

1. Click **profile icon → Settings → Connections**
2. Under **OpenAI API**, click **+** and add:

   | Field | Value |
   |-------|-------|
   | Name | `Beehive Queen` |
   | Base URL | `http://host.docker.internal:8788/v1` |
   | API Key | `any` (not validated) |

3. Click **Verify → Save**
4. In the chat, open the model picker and select **`beehive-queen`**

> [!TIP]
> `host.docker.internal` lets the Open WebUI container reach the Queen API
> container via the host machine's network. On Linux, confirm
> `extra_hosts: host.docker.internal:host-gateway` is in `docker-compose.yml`
> (it already is).

---

## Step 5 — Chat!

Type any message in the Open WebUI chat. Examples:

```
What is agent autonomy in AI?
Search for the latest Python 3.13 features
Summarise the concept of RAG for me
```

To trigger **web search**, the Queen looks for cues like "search for",
"look up", or "find". Or use the `X-Beehive-Intent` header from the API
to explicitly set the intent.

---

## Step 6 — Use the new autonomy features from the API

While you chat in the UI, you can also call the Queen's autonomy endpoints
directly from a terminal:

```bash
# Save a memory the Queen will use in future chats
curl -X POST http://localhost:8788/v1/memories \
  -H "Content-Type: application/json" \
  -d '{"content": "User prefers concise answers.", "tags": ["preference"]}'

# Spawn a custom worker
curl -X POST http://localhost:8788/v1/workers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "analyst",
    "description": "Deep data analysis worker",
    "capabilities": ["compute", "analyze"],
    "intent_patterns": ["analyze_data"]
  }'

# Read all Queen memories
curl http://localhost:8788/v1/memories

# Run a direct action loop
curl -X POST http://localhost:8788/v1/actions \
  -H "Content-Type: application/json" \
  -d '{
    "actions": [
      {"action": "web_search", "parameters": {"query": "AI agent news 2025"}},
      {"action": "remember",   "parameters": {"content": "AI agents are trending in 2025"}}
    ]
  }'
```

---

## Step 7 — Check status & logs

```bash
# Service status
beehive ps

# Queen API logs
docker logs beehive-queen-api -f

# Open WebUI logs
docker logs beehive-open-webui -f

# Health check
curl http://localhost:8788/health
```

---

## Step 8 — Stop everything

```bash
beehive down
# or
docker-compose down
```

---

## Ports at a glance

| Service | URL |
|---------|-----|
| **Open WebUI** (chat) | `http://localhost:3000` |
| **Queen API** | `http://localhost:8788` |
| **Queen API docs** | `http://localhost:8788/docs` |
| Beekeeper API | `http://localhost:8787` |
| SearXNG | `http://localhost:8080` |
| Qdrant dashboard | `http://localhost:6333/dashboard` |
| Temporal UI | `http://localhost:8233` |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Open WebUI can't reach Queen API | Use `http://host.docker.internal:8788/v1` not `localhost` |
| `beehive-queen` model not shown | Re-verify the connection in Settings → Connections |
| LLM not responding | Check `BEEHIVE_OLLAMA_BASE_URL` or API key in `.env` |
| Port 3000 in use | Edit `docker-compose.yml` → change `3000:8080` to e.g. `3001:8080` |
| Images out of date | Run `beehive rebuild` to rebuild with latest code |
