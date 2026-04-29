# Beekeeper

An experimental multi-agent orchestrator built around three ideas:

1. A central planner, the Queen, decomposes a request into typed tasks.
2. Ephemeral workers execute those tasks under per-action policy gates.
3. Honeycomb records an append-only event trace for decisions, artifacts, and review.

Status: research / personal use. Not production-ready. The architecture is more
ambitious than the current implementation. Read the status matrix below before
adopting any of this.

This is also a side learning project. Part of the point is to understand how AI
agent systems work under the hood: how planning gets broken into actions, how
guardrails can be enforced before tools run, how logs and monitors make behavior
visible, and how human review fits into automated workflows.

## What is actually shipping

| Subsystem | Status | Notes |
|-----------|--------|-------|
| Queen -> Worker dispatch | Working locally | Core tests cover basic planning, dispatch, reruns, and results. |
| Per-action user policy gate | Working locally | `allow` / `ask` / `deny` decisions are enforced through the tool path. |
| HITL approval flow | Working locally | Review queue, API endpoints, and persistence exist; UI is minimal. |
| Honeycomb event log | Partial | Append-only traces, artifacts, replay data, and SSE stream. Not authoritative state. |
| LLM provider chain | Working locally | Configurable provider order across OpenAI, Gemini, and Ollama. |
| Worker registry / forge | Experimental | Can register/generated workers for unmatched intents. Promotion and sandboxing are incomplete. |
| Scheduler backends | Mixed | Inline works for local runs; Celery and Temporal paths require external services. |
| Slack channel | Working depth-first | Primary channel path. Keep treating it as integration-tested, not hardened. |
| Telegram / Discord / WhatsApp | Skeleton / experimental | Adapters exist, but verification depth is not equal to Slack. |
| Multi-tenant quotas | Skeleton | Models and docs exist; hot-path enforcement is not complete. |
| Production deploy story | Not implemented | Postgres + Temporal + object storage is the intended path, not a proven deploy. |
| CI | Not implemented | Run `pytest` locally. |

## Quick Start (No Docker)

```bash
pip install -e .
cp .env.example .env
# edit .env to set one provider key, such as BEEKEEPER_OPENAI_API_KEY,
# BEEKEEPER_GEMINI_API_KEY, or BEEKEEPER_OLLAMA_API_KEY
beekeeper run --scheduler inline --vector memory --query "What is 2+2?"
```

The CLI also has a guided path:

```bash
beekeeper quickstart
beekeeper chat
```

On a fresh install, the API exposes a first-run setup wizard at `/` and `/setup`
for LLM keys, channels, and local configuration.

## Known limitations

- God objects: `beekeeper/queen.py`, `beekeeper/runner.py`, and `beekeeper/worker.py` still hold multiple concerns and need decomposition.
- Three execution modes coexist: legacy worker dispatch, model-driven tool loop, and hybrid mode. The roadmap is to converge on the hybrid path and delete the rest.
- Honeycomb is advisory. It is an event trace and local debugging surface, not the source of truth for production state.
- No CI yet. Tests run locally with `pytest`.
- Worker forge is powerful and risky. Generated worker code does not yet pass a full promotion, signing, sandbox, and provenance pipeline.
- Channels are broader than the verification depth. Slack is the focus; other adapters should be treated as experiments.

## Why this exists

I am publishing Beekeeper to get feedback on three specific ideas:

1. Is per-action policy gating with `allow` / `ask` / `deny` the right primitive
   for agent governance, or is it too coarse?
2. Is an append-only event log the right shape for agent audit, or does useful
   audit require authoritative state from day one?
3. Is Queen -> Worker decomposition useful in practice, or does it collapse into
   a single agent loop in real use?

If you have worked on these problems, open an issue or PR. This is personal-time
work, so response times and stability are not guaranteed.

## Core commands

| Command | Description |
|---------|-------------|
| `beekeeper quickstart` | Guided local setup |
| `beekeeper chat` | Interactive chat loop |
| `beekeeper run --query "..."` | Single query |
| `beekeeper doctor` | Service and config health checks |
| `beekeeper smoke-test` | Minimal end-to-end run plus persistence check |
| `beekeeper review list` | Pending HITL approvals |
| `beekeeper review approve <id> --resume` | Approve and resume a task |
| `beekeeper init-tenant --org X --hive Y` | Create tenant metadata |
| `beekeeper channels set slack '{"slack_bot_token":"..."}'` | Configure Slack |

## Docker / Compose

```bash
docker compose up --build
```

Compose starts Redis, Temporal, Qdrant, SearXNG, Celery, Queen API, and Open
WebUI. Configure via `.env` copied from `.env.example`.

## Dashboard and HITL

Open `http://localhost:8788/dashboard` for local channel setup, templates, orgs,
and HITL approvals. High-risk actions such as `payment_action` and `data_delete`
enter the review queue and can be approved through the dashboard, CLI, or API.

## Docs

- [docs/ONBOARDING.md](docs/ONBOARDING.md) - Setup guide
- [docs/support-matrix.md](docs/support-matrix.md) - Support depth and boundaries
- [docs/maturity-model.md](docs/maturity-model.md) - Maturity labels
- [docs/risks-and-known-gaps.md](docs/risks-and-known-gaps.md) - Current risks
- [docs/DECISION_TREE.md](docs/DECISION_TREE.md) - Scheduler, worker, and channel choices
- [docs/PROMPT_TEMPLATES.md](docs/PROMPT_TEMPLATES.md) - Prompt customization
- [docs/REMOTE_ACCESS_AND_TAILSCALE.md](docs/REMOTE_ACCESS_AND_TAILSCALE.md) - Remote access

## Migration from beehive

Rename `BEEHIVE_*` to `BEEKEEPER_*`, `~/.beehive/` to `~/.beekeeper/`, and use
the `beekeeper` CLI. Add `beekeeper-queen` to the Open WebUI allowlist if you use
that integration.
