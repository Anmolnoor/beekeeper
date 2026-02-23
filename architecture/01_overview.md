# 01 — System Overview

## What Is Beekeeper?

**Beekeeper Agent Platform** is a **multi-agent orchestration system** modeled on a beekeeper metaphor:

- A **Queen Agent** is the central planner/router. It decomposes user requests into sub-tasks and delegates them to workers.
- **Workers** are ephemeral: they receive one task, execute it, persist their result to the Honeycomb, and terminate.
- The **Honeycomb** is the append-only event/artifact data store that holds all task history, governance decisions, and telemetry.
- The **Beekeeper** is the management layer (multi-tenant store, channels, authentication, settings).

## Design Philosophy

| Principle | How It's Applied |
|-----------|-----------------|
| **Ephemeral workers** | Each worker runs once and exits. No persistent worker state. |
| **Append-only data plane** | Honeycomb never mutates records — only appends events, artifacts, results. |
| **Policy-first execution** | Every task is evaluated by guardrails before execution. |
| **Profile-driven modularization** | Agent behavior is composed from `soul`, `abilities`, `rules`, `guardrails`, `skills`, `accountability` profiles. |
| **Multi-backend flexibility** | Scheduler (inline/Celery/Temporal), LLM (Ollama/Gemini/OpenAI), vector store (memory/Qdrant). |
| **Human-in-the-loop (HITL)** | High-risk tasks are blocked pending human approval. |
| **Adaptive routing** | Quality/latency/cost feedback loop optimizes worker routing over time. |

## Lifecycle of a Request

1. **Entry point**: CLI (`beekeeper run`), Beekeeper API, Queen API, Slack/Telegram/Discord webhook, or `BeekeeperClient` SDK.
2. **Queen.run()**: The Queen agent receives `intent + payload`.
3. **Decomposition**: Queen calls an LLM to decompose the intent into atomic sub-tasks (`TaskEnvelope`).
4. **Guardrail evaluation**: `GuardrailPolicyEngine` checks each task (schema, PII, jailbreak, domain, budget).
5. **Human review (if needed)**: Task is queued in Honeycomb for human approval if required.
6. **Scheduling**: Task dispatched to scheduler (Inline, Celery, or Temporal).
7. **Worker execution**: Specialist worker (`WebSearch`, `HeavyCompute`, `Audit`) or custom worker executes the task.
8. **Result persistence**: Worker writes `ResultEnvelope` + `ArtifactRef` to Honeycomb.
9. **Monitor evaluation**: Queen's monitor checks result quality and triggers retries if needed.
10. **Routing feedback**: Performance metrics update the adaptive routing table.
11. **Response**: The accumulated results are returned to the caller.

## Key Concepts Glossary

| Term | Definition |
|------|-----------|
| `TaskEnvelope` | Typed message wrapping a unit of work: task_id, intent, payload, worker_kind, budget, trust tier |
| `ResultEnvelope` | Typed output from a worker: task_id, status, output dict, cost metrics |
| `SkillProfile` | Declares what a worker *can do*: tools allowed, capabilities, web search permission |
| `SoulProfile` | Personality/behavioral traits: tone, risk appetite, verbosity, escalation style |
| `RuleProfile` | Hard constraints: budget cap, runtime limits, max retries, allowed domains |
| `GuardrailProfile` | Enabled guardrails and network policy |
| `AbilitiesProfile` | Tool allowlist and parallelism limits |
| `AccountabilityPolicy` | Audit and governance requirements |
| `AgentBlueprint` | Template combining a profile bundle — defines a Queen or Worker shape |
| `HoneycombStore` | Append-only data plane: events, artifacts, governance, routing feedback |
| `BeekeeperStore` | Multi-tenant store: orgs, hives, honeycombs, queens, templates, channels, users |
| `Pulse` | Background scheduler that triggers periodic autonomous tasks |
| `Monitor` | Post-execution evaluator that classifies retry categories and quality scores |

## Package Entry Points

```
beekeeper         → beekeeper.runner:main        (CLI: beekeeper run / chat / doctor / up / etc.)
beekeeper-api   → beekeeper_api.app:main     (Management REST API on :8787)
queen-api       → queen_api.app:main         (OpenAI-compatible chat API on :8788)
```
