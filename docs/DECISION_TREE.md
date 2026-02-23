# Decision Tree: Which Scheduler? Worker? Channel?

Use this guide to choose the right configuration for your use case.

---

## Which Scheduler?

| Scheduler | When to Use | Requirements | Command |
|-----------|-------------|--------------|---------|
| **inline** | Local dev, quick tests, single-process runs | None | `beekeeper run --scheduler inline` |
| **celery** | Production queue: Redis-backed, horizontal scaling | Redis, Celery worker | `beekeeper run --scheduler celery` |
| **temporal** | Durable workflows, retries, long-running tasks | Temporal server, Temporal worker | `beekeeper run --scheduler temporal` |

**Quick choice:**
- **Just trying Beekeeper?** → `inline`
- **Team/production with multiple workers?** → `celery`
- **Need durable execution and retries?** → `temporal`

---

## Which Worker?

The Queen routes requests to workers based on intent, payload, and query. Built-in workers:

| Worker | Use When | Intent | Example Payload |
|--------|----------|--------|-----------------|
| **web_search** | Query needs web lookup, evidence, or research | `research_topic` | `{"query": "agent reliability patterns", "domains": ["docs.python.org"]}` |
| **heavy_compute** | Numeric aggregation, simulations, math | `heavy_compute` | `{"numbers": [2,4,6,8], "operation": "distribution_summary"}` |
| **audit** | Review/validate another worker's output | `audit_result` | `{"target_task_id": "...", "target_result": {...}}` |

**Adding custom workers:**
- **Plugin package:** `beekeeper install <package>` — see [EXTENSION_POINTS.md](EXTENSION_POINTS.md)
- **Core code:** See [BUILDING_NEW_WORKERS.md](BUILDING_NEW_WORKERS.md)

---

## Which Channel?

| Channel | Use When | Setup |
|---------|----------|-------|
| **Terminal** | Local dev, scripts, CLI | `beekeeper chat` or `beekeeper run --query "..."` |
| **Open WebUI** | Web chat UI, team access | `beekeeper up --with-open-webui` → http://localhost:3000 |
| **Slack** | Team chat, ops alerts | `beekeeper channels set slack '{"slack_bot_token":"...","slack_signing_secret":"..."}'` |
| **Telegram** | DMs, group bots | `beekeeper channels set telegram '{"telegram_bot_token":"..."}'` |
| **Discord** | Community, gaming | `beekeeper channels set discord '{"discord_bot_token":"...","discord_public_key":"..."}'` |
| **WhatsApp** | Business messaging | Configure WhatsApp Cloud API vars in `.env` |

**Quick choice:**
- **Solo or local?** → Terminal or Open WebUI
- **Team in Slack?** → Slack channel
- **Public/community?** → Discord or Telegram

For channel allowlists and DM pairing, see [CHANNEL_ALLOWLISTS.md](CHANNEL_ALLOWLISTS.md).
