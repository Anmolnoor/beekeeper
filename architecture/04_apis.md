# 04 — REST APIs

The platform exposes two FastAPI services.

---

## Beekeeper API (`beekeeper_api/`)

**Entry point**: `beekeeper-api` → `beekeeper_api.app:main`
**Default port**: `8787`
**Purpose**: Multi-tenant management, channel webhooks, chat persistence, settings.

### Authentication

- `POST /auth/register` — register a new user (email + password)
- `POST /auth/login` — returns JWT
- `GET /auth/me` — current user info

Protected endpoints require `Authorization: Bearer <jwt>`.

### Tenant Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/orgs` | List organizations |
| `POST` | `/orgs` | Create organization |
| `GET` | `/hives` | List hives (filter by `org_id`) |
| `POST` | `/hives` | Create hive |
| `GET` | `/honeycombs` | List honeycombs |
| `POST` | `/honeycombs` | Create honeycomb |
| `GET` | `/queens` | List queen instances |
| `POST` | `/queens` | Create queen instance |

### Templates

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/templates` | List agent blueprint templates |
| `POST` | `/templates` | Create template |
| `POST` | `/templates/instantiate` | Instantiate template → new queen |

### Onboarding

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/onboarding/bootstrap` | One-call tenant init: org + hive + honeycomb + queen |

### Settings & Channels

| Method | Path | Description |
|--------|------|-------------|
| `GET/POST` | `/settings` | Global key-value settings |
| `GET/POST` | `/channels` | Channel configs (Slack/Telegram/Discord) |
| `GET` | `/channels/list` | List configured channels |

### Chat (Persistent Sessions)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chats` | Create chat session |
| `GET` | `/chats` | List user's chats |
| `GET` | `/chats/{chat_id}` | Get chat + messages |
| `POST` | `/chats/{chat_id}/messages` | Send message to chat (runs Queen) |
| `PATCH` | `/chats/{chat_id}` | Update chat (title, pinned) |
| `DELETE` | `/chats/{chat_id}` | Delete chat |

`POST /chats/{chat_id}/messages` enriches the Queen payload with prior chat
history and user memories, and currently sets:
- `delegate_to_worker=true`
- `use_web_search=true`

### Channel Webhooks

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhooks/slack/events` | Slack Events API webhook |
| `POST` | `/webhooks/slack/slash` | Slack slash command handler |
| `POST` | `/webhooks/telegram` | Telegram bot webhook |
| `POST` | `/webhooks/discord` | Discord interaction webhook |

### Trace / Observability

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/traces` | List recent trace IDs |
| `GET` | `/traces/{trace_id}` | Get all events for a trace |
| `GET` | `/traces/{trace_id}/graph` | Task DAG for a trace |
| `GET` | `/metrics` | Aggregated queue/performance metrics |

### Human-in-the-Loop (HITL)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/reviews` | List pending human reviews |
| `POST` | `/reviews/{review_id}/approve` | Approve a pending task |
| `POST` | `/reviews/{review_id}/reject` | Reject a pending task |

### Operational

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Health check |
| `GET` | `/init/status` | Whether tenant is initialized |
| `GET` | `/dashboard` | Lightweight web dashboard (HTML) |

---

## Queen API (`queen_api/`)

**Entry point**: `queen-api` → `queen_api.app:main`
**Default port**: `8788`
**Purpose**: OpenAI-compatible adapter so any OpenAI client (Open WebUI, LangChain, etc.) can talk to the Queen agent.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/models` | Returns `beekeeper-queen` model listing |
| `POST` | `/v1/chat/completions` | Chat completions — forwards to `QueenAgent.run()` |
| `GET` | `/health` | Health check: `{"status": "ok", "service": "queen-api"}` |

### Chat Completions Request

Standard OpenAI `ChatCompletionRequest` format:
```json
{
  "model": "beekeeper-queen",
  "messages": [{"role": "user", "content": "what is agent reliability?"}],
  "stream": false
}
```

### Custom Headers

| Header | Description |
|--------|-------------|
| `X-Beekeeper-Intent` | Override the Queen intent (default: `research_topic`) |
| `X-Beekeeper-Model` | Override LLM model for this request |
| `X-Beekeeper-Delegate-Worker` | Override worker delegation (`true`/`false`, default: `true`) |
| `X-Beekeeper-Use-Web-Search` | Override web search usage (`true`/`false`, default: `true`) |

### Message Parsing
The Queen API extracts the last user message as `query` and passes prior messages as conversation history context to the Queen agent.

### Configuration (via env vars)
- `BEEKEEPER_HONEYCOMB_ROOT` — data directory
- `BEEKEEPER_SCHEDULER_BACKEND` — scheduler to use (default: `inline`)
- `BEEKEEPER_VECTOR_BACKEND` / `BEEKEEPER_VECTOR_URL` — vector store

---

## Dashboard

Served by Beekeeper API at `http://localhost:8787/dashboard`:
- View organizations, hives, queens
- Manage channels and templates
- Requires browser sign-in (JWT cookie)
