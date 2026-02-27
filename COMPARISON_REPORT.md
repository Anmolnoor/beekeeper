# Beekeeper Agent Platform — Competitive Comparison Report

> Last updated: 2026-02-26 (v3 — MCP transport complete, streaming added, README updated, vision clarified)

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| v1 | 2026-02-26 morning | Initial comparison based on original codebase |
| v2 | 2026-02-26 | Tool-runtime additions (mcp_adapter, tool_runtime, tool_adapters, execution modes, tool-level guardrails) |
| v3 | 2026-02-26 | MCP transport complete (stdio+HTTP), streaming progress in CLI, README rewritten, vision reframed as personal agent manager |

---

## Table of Contents

1. [What Each Project Actually Is](#1-what-each-project-actually-is)
2. [Architecture Comparison](#2-architecture-comparison)
3. [Feature Matrix](#3-feature-matrix)
4. [What Beekeeper Has (Strengths)](#4-what-beekeeper-has-strengths)
5. [What Beekeeper Is Missing (Gaps)](#5-what-beekeeper-is-missing-gaps)
6. [Strategic Direction — Where Is This Going?](#6-strategic-direction--where-is-this-going)
7. [Concrete Recommendations](#7-concrete-recommendations)
8. [Summary Verdict](#8-summary-verdict)

---

## 1. What Each Project Actually Is

| Project | One-Line Description | Primary Domain | Who Uses It |
|---|---|---|---|
| **Claude Code** | Anthropic's official agentic coding CLI | Code + git + CI/CD | Software engineers |
| **OpenClaw** | Self-hosted personal AI assistant across all your messaging apps | Life automation via messaging | Privacy-conscious power users |
| **pi-mono** | Minimal, composable AI agent toolkit (agent loop + LLM API + TUI) | Developer infrastructure | Agent builders / minimalists |
| **Beekeeper** | Governed multi-agent platform: Queen orchestrator + model-driven tool loop + Honeycomb | Enterprise agent runtime | Teams deploying governed AI agents |

**Updated diagnosis (v3):** Beekeeper is now a complete governed agent runtime with full MCP connectivity, model-driven tool loop, and step-by-step CLI feedback. The original vision — a **personal agent manager** that learns, creates tools, seeks approval, and calls itself on a schedule — is actually what this codebase already supports at the architecture level. The gap is wiring it together into a seamless single-user experience rather than an enterprise multi-tenant platform.

---

## 2. Architecture Comparison

### Agent Loop Design

| Project | Orchestration Model | Tool Philosophy | Memory Model |
|---|---|---|---|
| **Claude Code** | Parent TAOR loop → sub-agents via `Task()` | Large toolset + MCP (open extensibility) | Context window + CLAUDE.md files |
| **OpenClaw** | Gateway WebSocket → serialized lane per channel → pi-agent-core | Plugins/skills with TypeBox schemas | Flat Markdown files on disk |
| **pi-mono** | Single `agentLoop()` / `Agent` class, event-emitting | 4 tools only: read, write, edit, bash | AGENTS.md + session persistence |
| **Beekeeper** | **Dual-mode**: (A) Queen → TaskEnvelopes → Workers (legacy_worker), (B) Queen → ToolLoopEngine → model-driven tool calls → policy-checked execution (model_tools), or both (hybrid) | ToolRegistry with OpenAI-compatible schema + MCP adapter | Honeycomb (append-only events) + user_memory.py + vector store |

**v2 note:** Beekeeper now has a true TAOR-style loop (`ToolLoopEngine`) operating alongside the original worker-dispatch system. The two can run together in `hybrid` mode. This matches how Claude Code operates at its core.

### Infrastructure Complexity

| Project | Stack Complexity | Self-Host Ease | Dependencies |
|---|---|---|---|
| **Claude Code** | Node.js CLI. Zero infra. | Install via brew/npm | Anthropic account only |
| **OpenClaw** | Single Node.js Gateway process | One Docker command | Node 22+, model API key |
| **pi-mono** | Monorepo of 7 packages | npm install, run | Node 18+, model API key |
| **Beekeeper** | 9 Docker services | docker-compose up | Redis, Temporal, Qdrant, SearXNG, Celery, Ollama |

**Still a problem.** Infrastructure complexity is unchanged. The new tool loop runs in-process, which is good — but the full stack is still 9 services.

### Multi-Provider LLM

| Project | Provider Lock-in | Providers | Fallback Chain | Native Tool Calling |
|---|---|---|---|---|
| **Claude Code** | Claude only (Anthropic) | 1 | No | Yes (Anthropic) |
| **OpenClaw** | Model-agnostic | Anthropic, OpenAI, open-source | Yes (per-channel) | Partial |
| **pi-mono** | Model-agnostic | 20+ (Anthropic, OpenAI, Google, xAI, Groq, etc.) | Yes | Yes |
| **Beekeeper** | Model-agnostic | 3 (Ollama, Gemini, OpenAI) | Yes (fallback chain) | **Yes — new: `chat_with_tools()` + `LLMDecision`** |

**v2:** `llm_provider.py` now has `LLMDecision` (normalized tool-call/final-text output) and `chat_with_tools()` on providers. OpenAI provider has native tool-calling support. The LLM layer now feeds directly into `ToolLoopEngine`.

### Persistence / Memory

| Project | Event Store | Vector Search | HITL | Audit Log |
|---|---|---|---|---|
| **Claude Code** | None (context window) | No | No | No |
| **OpenClaw** | Markdown files | No (intentionally flat) | No | No |
| **pi-mono** | Session JSON files | No | No | No |
| **Beekeeper** | Append-only Honeycomb + **tool call events now persisted per-execution** | Yes (Qdrant + in-memory) | Yes (approval queue) | Yes (daily JSONL) |

**v2:** `ToolExecutor._write_tool_event()` writes every tool call and result to Honeycomb as a `tool_execution` event. Full traceability of every model-driven tool call, not just worker dispatches.

---

## 3. Feature Matrix

### Core Agent Capabilities

| Feature | Claude Code | OpenClaw | pi-mono | Beekeeper |
|---|---|---|---|---|
| Intent decomposition (planning) | Yes (implicit via LLM) | No (direct routing) | No | **Yes (Queen + TaskEnvelopes)** |
| Sub-agents / worker dispatch | Yes (`Task()`) | Per-channel routing | No (bash + tmux) | **Yes (Worker registry)** |
| Model-driven tool loop | **Yes (TAOR, primary mode)** | Yes (agentLoop) | Yes (agentLoop, 4 tools) | **Yes — new (ToolLoopEngine)** |
| Streaming LLM responses | Yes | Yes | Yes | **Partial — improved (queen_api SSE; CLI now shows `→ step` progress via status_callback; `--quiet` to suppress)** |
| Tool calling / function use | Yes (MCP) | Yes (TypeBox skills) | Yes (4 tools) | **Yes — ToolRegistry + OpenAI-compatible schemas** |
| Multi-provider LLM | No (Claude only) | Yes | Yes (20+) | Yes (3 providers + fallback) |
| Model fallback chain | No | Yes | Yes | **Yes** |
| Custom worker/tool extensibility | Yes (MCP servers) | Yes (plugins) | Yes (extensions) | **Yes (plugins.py + ToolRegistry)** |
| Execution mode switching | No | No | No | **Yes — new (legacy_worker / model_tools / hybrid)** |

### Governance & Safety

| Feature | Claude Code | OpenClaw | pi-mono | Beekeeper |
|---|---|---|---|---|
| Guardrails / policy enforcement | Minimal (permissions) | No | No | **Yes (6 built-in + plugins)** |
| Tool-call-level guardrails | No | No | No | **Yes — new (evaluate_tool_call: PII, domain, denylist, HITL flags)** |
| PII detection | No | No | No | **Yes (task-level + tool-arg-level)** |
| Jailbreak detection | No | No | No | **Yes (JailbreakGuardrail)** |
| Human-in-the-loop (HITL) | No | No | No | **Yes (approval queue + per-tool HITL flags)** |
| Signed audit trail | No | No | No | **Yes (JSONL + signing)** |
| Budget enforcement | No | No | No | **Yes (task-level + per-turn cost cap in ToolExecutionPolicy)** |
| Tool allowlist / denylist | No | No | No | **Yes — new (ToolExecutionPolicy + evaluate_tool_call)** |
| Governance decisions stored | No | No | No | **Yes (Honeycomb governance/)** |
| Tool execution events stored | No | No | No | **Yes — new (Honeycomb tool_execution events)** |

### Observability & Tracing

| Feature | Claude Code | OpenClaw | pi-mono | Beekeeper |
|---|---|---|---|---|
| Distributed tracing | No | No | No | **Yes (span-based)** |
| Tool call trace in API response | No | No | No | **Yes — new (X-Beekeeper-Debug header returns tool_trace)** |
| Audit log (all service calls) | No | No | No | **Yes (daily JSONL)** |
| Performance analytics | No | No | No | **Yes (/api/analytics/latency)** |
| Retry classification | No | No | No | **Yes (monitor.py)** |
| Adaptive routing feedback | No | No | No | **Yes** |
| Dashboard UI | No | No | No | **Yes (HTML prototype)** |

### MCP (Model Context Protocol)

| Feature | Claude Code | OpenClaw | pi-mono | Beekeeper |
|---|---|---|---|---|
| MCP client (connects to external MCP servers) | **Yes (primary extensibility)** | No | No | **Partial — new (adapter + registry layer done; transport protocol not yet)** |
| MCP tool descriptor → ToolSpec conversion | Yes | No | No | **Yes — new (mcp_adapter.py)** |
| MCP allowlist / denylist | Yes | No | No | **Yes — new (discover_mcp_tool_specs with allowlist/denylist)** |
| Register MCP tools on ToolRegistry | N/A | No | No | **Yes — new (register_mcp_tools())** |
| MCP transport (stdio / SSE) | Yes | No | No | **Yes — new (mcp_transport.py: stdio + HTTP/SSE, sync bridge, env config)** |

**v2 note:** `mcp_adapter.py` provides the complete conversion and registration layer — convert MCP descriptors to `ToolSpec`, apply allowlists, build executors, and register on `ToolRegistry`. What's missing is the actual MCP transport client (the part that talks to an MCP server over stdio or SSE). Adding `mcp` Python package + a thin transport wrapper would complete this.

### Integration & Channels

| Feature | Claude Code | OpenClaw | pi-mono | Beekeeper |
|---|---|---|---|---|
| Slack | Yes (GitHub Actions) | Yes | Yes (pi-mom) | **Yes (webhook adapter)** |
| Telegram | No | Yes | No | **Yes** |
| Discord | No | Yes | No | **Yes** |
| WhatsApp | No | Yes | No | **Yes (Cloud API + transcription)** |
| iMessage | No | Yes (BlueBubbles) | No | No |
| Signal | No | Yes | No | No |
| Voice / transcription | No | Yes (ElevenLabs) | No | **Yes (Whisper in)** |
| Web search | Yes (via tools) | No | No | **Yes (SearXNG)** |
| OpenAI-compatible API | No | No | No | **Yes (queen_api port 8788 + execution mode header)** |
| Open WebUI integration | No | No | No | **Yes** |

### Infrastructure & Deployment

| Feature | Claude Code | OpenClaw | pi-mono | Beekeeper |
|---|---|---|---|---|
| Docker compose | No | Yes (1 service) | No | **Yes (9 services)** |
| Async task queue (Celery) | No | No | No | **Yes** |
| Durable workflows (Temporal) | No | No | No | **Yes** |
| Vector database (Qdrant) | No | No | No | **Yes** |
| Multi-tenancy | No | No | No | **Yes (org/hive/queen)** |
| Authentication (JWT) | No | No | No | **Yes** |
| Autonomous scheduler (Pulse) | No | No | No | **Yes** |

### Developer Experience

| Feature | Claude Code | OpenClaw | pi-mono | Beekeeper |
|---|---|---|---|---|
| Zero-config quick start | Yes (brew install) | Yes (1 command) | Yes (npm install) | No (9 services + .env setup) |
| Python SDK | Yes | No | No | **Yes (sdk.py)** |
| CLI interface | **Yes (polished)** | Partial | Yes | Yes (runner.py, functional) |
| Interactive chat TUI | **Yes (polished)** | Web/apps | **Yes (pi-tui)** | Basic |
| Tests (coverage) | High | Unknown | Unknown | **Yes (38+ tests, new test_tool_runtime.py)** |
| Architecture docs | High | High | High | **Yes (10 docs — needs update for new modules)** |

---

## 4. What Beekeeper Has (Strengths)

### 1. Enterprise-Grade Governance (Deepened in v2)
- **HITL approval queue** — tasks paused for human sign-off
- **6 built-in task-level guardrails** (PII, jailbreak, schema, domain, budget, audit)
- **NEW: Tool-call-level guardrails** (`evaluate_tool_call()` in `guardrails.py`) — PII detected in tool arguments, domain allowlist checked, per-tool denylist, per-tool HITL flags
- **Plugin-extensible guardrail system**
- **Signed append-only audit trail** — tamper-evident
- **Governance decisions stored separately** — auditable policy enforcement
- **NEW: `ToolExecutionPolicy`** — per-turn cost cap, max steps, tool allowlist/denylist, HITL tool list

*Governance now operates at two layers: task/intent level (legacy) and individual tool call level (new). This is the deepest governance stack of any open agent platform.*

### 2. Model-Driven Tool Loop (New in v2)
- **`ToolLoopEngine`** — runs the model → tool_calls → execute → observe loop with configurable max steps and cost caps
- **`ToolRegistry`** — typed tool catalog with OpenAI-compatible schema export (`get_openai_compatible_tools()`)
- **`ToolExecutor`** — validates args against JSON Schema, enforces policy, persists events to Honeycomb, runs executor functions
- **`LLMDecision`** dataclass — normalized output from any provider's tool-calling API
- **`chat_with_tools()`** — OpenAI-native tool calling via `chat/completions` with tools parameter
- **Three execution modes**: `legacy_worker` (original Queen dispatch), `model_tools` (new tool loop), `hybrid` (both)
- **Switchable per-request** via `X-Beekeeper-Execution-Mode` header in queen_api

### 3. Full MCP Support (Completed in v3)
- **`mcp_adapter.py`** — converts MCP descriptors to `ToolSpec`, allowlist/denylist, builds executors
- **`mcp_transport.py`** — `connect_stdio_sync()` (subprocess) + `connect_http_sync()` (SSE/HTTP), both with sync bridge over async SDK in background thread
- **`load_mcp_config()`** — reads from `BEEKEEPER_MCP_SERVERS` or `BEEKEEPER_MCP_SERVERS_JSON` env vars
- **`register_mcp_servers_from_config()`** — auto-discover + register all configured MCP servers on startup
- **Tool-level policy applies to MCP tools too** — same guardrails, HITL flags, denylist
- **One env var to connect any MCP server**: filesystem, GitHub, Jira, browser automation, databases, etc.

### 4. Worker-as-Tool Bridge (New in v2)
- **`tool_adapters.py`** — every existing worker (WebSearch, HeavyCompute, Audit, ContextCurator, Forged) is exposed as a typed `ToolSpec`
- **Queen actions** (remember, summarize, spawn_worker, run_task, web_search) also exposed as tools
- **`build_tool_registry_from_queen()`** — one call to get a fully-populated ToolRegistry from an existing Queen instance
- Legacy workers and new model-driven tools can coexist — old behavior preserved, new behavior available

### 5. Full Observability Stack
- Span-based distributed tracing across Queen → Workers
- **NEW: Tool execution events** written to Honeycomb per call (`kind: tool_execution`)
- **NEW: `X-Beekeeper-Debug` header** returns `tool_trace` (full ordered tool call + result list) in API response
- Daily JSONL audit logs for all service calls (Redis, LLM, Qdrant)
- Performance analytics API
- Adaptive routing feedback loop, retry classification

### 6. Multi-Tenant Architecture
- Organizations → Hives → Queens → Workers hierarchy
- Separate Honeycomb and Store per hive
- JWT authentication
- Multi-tenant setup wizard

### 7. Worker Specialization System
- Intent-matched worker dispatch (not just LLM routing)
- WebSearch, HeavyCompute, Audit, ContextCurator, ForgedWorker
- Auto-spawn (ForgedWorker creates custom workers on demand)
- Worker Forge: generates worker blueprints from user intent
- Worker Forge source generation (`_build_forged_worker_source()`) — dynamically creates Python class source code for new worker kinds

### 8. Durable Execution Backends
- InlineScheduler (dev), CeleryScheduler (async), TemporalScheduler (durable)
- Three backends behind a clean abstraction

### 9. OpenAI-Compatible API Layer
- `queen_api` exposes `/v1/chat/completions`
- **NEW: `X-Beekeeper-Execution-Mode` header** — client can pick legacy_worker, model_tools, or hybrid per-request
- **NEW: `X-Beekeeper-Debug` header** — includes full tool_trace in response for debugging
- Open WebUI integration out of the box

---

## 5. What Beekeeper Is Missing (Gaps)

### Critical Gaps (Fix First)

**A. No clear identity / target user**
The project is getting closer — the new tool loop + governance layers point toward "governed agent runtime" — but the README, CLI, and setup wizard still don't explain this angle clearly. A developer landing on the repo today cannot tell in 30 seconds what it's for.
- *Action: Rewrite README to lead with the governance + tool runtime angle. One primary use case, one primary user type.*

**B. Zero-config onboarding doesn't exist**
- Claude Code: `brew install` → works
- OpenClaw: One docker command → works
- Beekeeper: 9 Docker services + `.env` + Ollama + setup wizard
- *Action: Make `beekeeper setup && beekeeper chat` work in <5 min with Gemini as default (no local GPU, no full Docker stack).*

**C. No streaming in the primary Queen chat path**
`queen_api` supports streaming. `beekeeper chat` CLI and `beekeeper_api /api/chat` are synchronous. The new `ToolLoopEngine` runs synchronously. Users see silence for 30+ seconds on long tasks.
- *Action: Add streaming output to CLI and dashboard. Yield intermediate tool call events as SSE.*

**D. No live LLM integration tests**
All tests mock LLM calls. `test_tool_runtime.py` covers the engine with a mock `decision_fn` — good, but no test verifies the whole chain with a real model.
- *Action: Add 3+ live integration tests gated by `BEEKEEPER_INTEGRATION=1`.*

**E. Dashboard is an HTML prototype**
No real-time updates, no task status polling, no tool call visualization. The new tool_trace data is there but not displayed anywhere.
- *Action: Add SSE endpoint for real-time task/tool events. Display tool_trace in the dashboard trace viewer.*

**F. ~~MCP transport~~ — DONE**
`mcp_transport.py` is complete: `connect_stdio_sync()`, `connect_http_sync()`, `load_mcp_config()` (from env), `register_mcp_servers_from_config()`. Runs async MCP SDK in a background thread so Queen stays synchronous. Configure via `BEEKEEPER_MCP_SERVERS` or `BEEKEEPER_MCP_SERVERS_JSON`. Any MCP server (filesystem, GitHub, Jira, browser, etc.) is now one env var away.

**G. No coding/file agent capabilities**
No worker can read/write files or run shell commands. Claude Code and pi-mono's core value is code execution in a sandbox.
- *Action: Add `CodeWorker` — reads/writes files, runs bash in a Docker sandbox. Expose as a ToolSpec so model_tools mode can call it.*

### Secondary Gaps (Important but not blocking)

**H. No voice response (TTS)**
Beekeeper has Whisper for input transcription but no text-to-speech response loop. OpenClaw has ElevenLabs.

**I. No mobile companion**
OpenClaw has iOS/Android. Claude Code has an iOS app. Beekeeper has no mobile story.

**J. No iMessage or Signal integration**
Beekeeper supports 4 channels (Slack, Telegram, Discord, WhatsApp). OpenClaw supports 10+.

**K. No GPU/local model management**
Pi-mono has `pi-pods` for vLLM. Beekeeper has no tooling to spin up/manage Ollama or vLLM.

**L. Celery and Temporal not tested live**
Both async backends are implemented and the `model_tools` mode runs in-process (which is good), but Celery/Temporal task dispatch is not integration-tested.

**M. Worker Forge still undemonstrated**
`_build_forged_worker_source()` generates Python class source code, but there are no demos, docs, or tests showing the full end-to-end: intent → Worker Forge → generated class → registered → executed.

**N. Architecture docs not updated**
`architecture/` was written before `tool_runtime.py`, `mcp_adapter.py`, `tool_adapters.py`, and the execution mode system existed. Docs are stale.
- *Action: Add `architecture/11_tool_runtime.md` covering the new tool loop, MCP adapter, and execution modes.*

**O. No skill/prompt marketplace**
Claude Code has `/skills`, pi-mono has `pi-skills`. Beekeeper has `skill_loader.py` but no catalog or sharing.

**P. `contracts.py` is not versioned in tooling**
`ToolSpec`, `ToolCall`, `ToolResult` all have a `version: str = SCHEMA_VERSION` field — good. But there's no migration path if schema changes. Worth noting for future-proofing.

---

## 6. Strategic Direction — Where Is This Going?

### What the v2 Changes Reveal

The addition of `tool_runtime.py`, `mcp_adapter.py`, and `tool_adapters.py` in one session is a strong signal. The author is converging Beekeeper toward a **governed model-driven agent runtime** — a platform where:

1. The model decides what tools to call (not just a keyword-matched router)
2. Every tool call is policy-checked before execution
3. Everything is stored to Honeycomb with full traceability
4. External tools (MCP) plug in without code changes
5. Workers from the legacy system are exposed as tools transparently

This is genuinely different from all three comparison projects. None of them have tool-call-level policy enforcement. None of them persist tool execution events to a queryable store. None of them have a governance layer that operates at both the intent level and the individual tool call level.

### Three Possible Product Identities (Still Valid)

**Product A: Enterprise Agent Governance Platform** ← *what the architecture is becoming*
- Multi-tenancy + HITL + tool-level guardrails + audit trail + Honeycomb
- Target: Organizations deploying AI agents at scale with compliance requirements
- Comparable to: Nothing that's open source and self-hostable

**Product B: Personal Life Orchestrator** ← *OpenClaw won this already*
- WhatsApp/Slack/Discord channels, web search, memory
- OpenClaw has 234k stars and institutional backing

**Product C: Developer Multi-Agent Framework** ← *crowded market*
- Queen/Worker/ToolLoop, Python SDK, Temporal
- LangGraph, CrewAI, Prefect are well-established

**Recommended: Double down on Product A.** The new tool-level governance layer (`evaluate_tool_call`, `ToolExecutionPolicy`, Honeycomb tool events) is the most defensible moat and the most under-served market.

**The pitch:** "The only self-hosted agent runtime where every tool call is policy-enforced, every action is audit-logged, and humans can gate any step — while remaining compatible with the OpenAI tool-calling standard and every MCP server in the ecosystem."

---

## 7. Concrete Recommendations

### Priority 1: Complete what was started (small effort, high impact)

| # | Action | Effort | Impact |
|---|---|---|---|
| 1 | Add `mcp` Python package + `MCPTransportClient` to complete MCP gap (adapter is already done) | Small | Very High |
| 2 | Update architecture docs: add `11_tool_runtime.md` covering ToolLoopEngine, mcp_adapter, execution modes | Small | High |
| 3 | Add `--stream` flag to `beekeeper chat` — yield tool call events as they happen | Small | High |
| 4 | Commit all changes + write a meaningful commit message that describes the tool runtime addition | Tiny | Critical |
| 5 | Fix Docker hardcoded Tailscale IP → env-only config | Tiny | High |

### Priority 2: Close the remaining gaps (medium effort, high impact)

| # | Action | Effort | Impact |
|---|---|---|---|
| 6 | Rewrite README to lead with "governed agent runtime" angle — one sentence, one use case | Small | Critical |
| 7 | Make `beekeeper setup` work in <5 min with Gemini only (no Ollama, no Docker) | Medium | Critical |
| 8 | Add SSE endpoint to dashboard — stream tool_trace events in real time | Medium | High |
| 9 | Build `CodeWorker` (read/write files + bash in Docker sandbox) as a ToolSpec | Medium | Very High |
| 10 | Add 3 live integration tests gated by `BEEKEEPER_INTEGRATION=1` | Medium | High |

### Priority 3: Differentiate further (medium-large effort)

| # | Action | Effort | Impact |
|---|---|---|---|
| 11 | Add Honeycomb compliance export — PDF/CSV audit report from tool execution events | Medium | High (enterprise) |
| 12 | Add pi-mono's 20-provider LLM list (xAI, Groq, Cerebras, OpenRouter) to `llm_provider.py` | Medium | Medium |
| 13 | Add live Celery scheduler integration tests | Medium | Medium |
| 14 | Publish `beekeeper` to PyPI | Small | High |
| 15 | Build Worker Forge end-to-end demo (intent → generated class → registered → executed) | Medium | High |

### Priority 4: Longer term

| # | Action | Effort | Impact |
|---|---|---|---|
| 16 | Add observability export to OpenTelemetry (tool events → spans) | Medium | High (enterprise) |
| 17 | iOS companion app (Swift + queen_api) | Large | High |
| 18 | Native Slack app with App Home | Large | High |
| 19 | Skill marketplace / shareable skill catalog | Large | High |
| 20 | Add ElevenLabs TTS for WhatsApp voice response loop | Small | Medium |

---

## 8. Summary Verdict

### Where Beekeeper Actually Wins (Updated for v2)

| Category | Verdict |
|---|---|
| Governance & compliance | **Strong leader** — task-level + tool-call-level guardrails, HITL, signed audit. No other project has this. |
| Observability | **Leader** — distributed tracing + audit JSONL + tool execution events in Honeycomb + debug header |
| Model-driven tool loop | **Competitive** — ToolLoopEngine with policy enforcement matches Claude Code/pi-mono's core loop |
| MCP support | **Partial** — adapter layer done, transport client needed (one small step away) |
| Persistence | **Leader** — Honeycomb is production-grade; others use flat files or nothing |
| Multi-tenancy | **Leader** — none of the comparison projects support org/hive hierarchy |
| Tool-level policy | **Unique** — no other project evaluates guardrails at the individual tool call level |

### Where Beekeeper Still Loses

| Category | Verdict |
|---|---|
| Developer experience | **Loses** — setup complexity is a barrier; 9 services vs. one command |
| Focus / messaging | **Better (v3)** — README now leads with governance angle, but still not "personal agent manager" framing |
| Streaming / responsiveness | **Improved (v3)** — CLI now shows `→ step` progress; ToolLoopEngine still synchronous end-to-end |
| Code execution | **Missing** — no CodeWorker; Claude Code and pi-mono lead here |
| Ecosystem / community | **Far behind** — 0 stars vs. 70k/234k/17k |
| MCP transport | **Done (v3)** — stdio + HTTP/SSE complete |

### The One-Sentence Recommendation

**You already built your personal agent manager — the Queen chats, Workers execute, Pulse schedules, Worker Forge creates tools, HITL approves them, MCP connects everything external, and the Honeycomb remembers it all — the only thing left is wiring the approval → reload loop, adding a `--personal` setup mode, and actually using it.**

---

---

## 9. Personal Agent Manager Vision — What You Have vs. What's Missing

> "I want a personal agent manager that manages a team of agents, gets work done, calls itself on a schedule with Pulse, acts as my assistant, builds a second brain, learns new things, creates tools, gets my approval, adds them to the system and restarts."

### What's Already There

| Vision Component | What Exists in Beekeeper | Where |
|---|---|---|
| Personal assistant (chat) | `beekeeper chat` CLI + Open WebUI | `runner.py`, `queen_api` |
| Team of agents | Queen → Workers (WebSearch, HeavyCompute, Audit, Forged, ContextCurator) | `worker.py`, `worker_registry.py` |
| Calls itself on a schedule | Pulse scheduler — background loop for periodic tasks | `pulse.py`, `beekeeper pulse` |
| Second brain / memory | `user_memory.py` extracts + persists memory per conversation; vector store for recall | `user_memory.py`, `honeycomb.py` |
| Learns from conversations | ContextCurator worker curates context after each turn | `worker.py` (ContextCurator) |
| Creates new tools | Worker Forge: detects unmatched intents → generates custom worker Python class → writes to `.honeycomb/workers/generated/` | `queen.py` `_build_forged_worker_source()` |
| Registers new tools at runtime | `plugins.json` hot-reload; `register_mcp_tools()` for external tools | `plugins.py`, `mcp_adapter.py` |
| Gets your approval (HITL) | Approval queue; `spawn_worker` action requires HITL; `beekeeper review approve` | `beekeeper_api/routes.py`, `honeycomb.py` |
| External tool connectivity | Full MCP support (stdio + HTTP), any MCP server | `mcp_transport.py` |
| Policy on every tool call | `evaluate_tool_call()` guardrails before any tool executes | `guardrails.py` |
| Step-by-step progress | `→ step` status callbacks in CLI (`--quiet` to suppress) | `runner.py` |

**The core loop you described is architecturally complete.** Every single piece exists. What's missing is not features — it's the **glue and UX** that connects them into a seamless single-user experience.

---

### What's Missing for the Vision (The Glue)

**1. The approval → reload loop is not end-to-end wired**
Worker Forge generates the file and updates `plugins.json`. But the HITL approval step (you approve the generated tool) → then it hot-reloads → and the Queen uses it on the next request — this full cycle is not connected into one automatic flow. You'd currently have to manually trigger the reload.
- *Fix: After HITL approval of a `spawn_worker` action, automatically call `plugins.reload()` and confirm to the user that the new tool is live.*

**2. No "what do you know about me?" memory interface**
`user_memory.py` saves facts. Vector store indexes them. But there's no `beekeeper memory list` command or dashboard view showing what the Queen has learned about you. You can't see, edit, or delete your second brain.
- *Fix: Add `beekeeper memory list / search / forget` CLI commands. Show memory in the dashboard.*

**3. Pulse is not user-configurable from chat**
Pulse runs, but you can't say "remind me every morning at 9am to check my calendar" from the chat interface and have it create a Pulse job. Pulse config lives in files, not in a conversational flow.
- *Fix: Add a `schedule` Queen action that creates Pulse entries from natural language. "Every weekday at 9am, run web_search for today's AI news."*

**4. No "what can you do?" discovery**
When you start chatting, the Queen doesn't introduce itself, doesn't list its workers, doesn't show what MCP tools are connected, and doesn't show what it's already learned. First-time experience is blank.
- *Fix: On first `beekeeper chat`, print a short intro: active workers, connected MCP servers, memory count, next scheduled pulse.*

**5. No single-user simplified mode**
The system is built for org → hive → queen multi-tenancy. For personal use you don't need any of that overhead — but you still have to initialize a tenant, configure channels, etc.
- *Fix: Add a `--personal` flag to `beekeeper setup` that skips multi-tenancy and runs the Queen directly with sane personal defaults.*

**6. Restart after tool creation is manual**
When a new worker is forged and approved, the Queen process needs to reload plugins. Currently this requires a process restart or manual reload. For the vision to work, it needs to be invisible.
- *Fix: Auto-reload plugins after HITL approval without restarting the process. `importlib.reload` + re-register in worker_registry.*

---

### The Minimum Path to Your Vision (Ordered)

These are the exact steps to go from "all the pieces exist" to "I'm actually talking to my personal agent manager":

| Step | What to Do | Effort |
|---|---|---|
| 1 | `beekeeper setup --personal` — single-user mode, Gemini default, no tenant setup | Small |
| 2 | `beekeeper chat` shows intro: workers available, MCP servers connected, memories stored | Tiny |
| 3 | Wire HITL approval → auto plugin reload (no manual restart) | Small |
| 4 | Add `schedule` Queen action: "every day at 9am, search for X" creates a Pulse job | Medium |
| 5 | Add `beekeeper memory list` — see what the Queen knows about you | Small |
| 6 | Connect one real MCP server (e.g. filesystem or GitHub) via `BEEKEEPER_MCP_SERVERS` and verify end-to-end | Tiny |
| 7 | Run it for a week. Let the Queen learn. See what it auto-forges. | Zero code |

**That's it. Seven steps. Most of the code already exists.**

---

## Appendix: New Files Added (v2)

| File | What It Does |
|---|---|
| `beekeeper/tool_runtime.py` | `ToolRegistry` (typed tool catalog), `ToolExecutor` (validate + enforce policy + run + persist to Honeycomb), `ToolLoopEngine` (model-driven tool loop with max steps + cost cap) |
| `beekeeper/mcp_adapter.py` | MCP descriptor → `ToolSpec` conversion, allowlist/denylist filtering, executor builder, `register_mcp_tools()` for one-call MCP integration |
| `beekeeper/tool_adapters.py` | Bridges existing Workers and Queen actions to typed `ToolSpec` + executor functions. `build_tool_registry_from_queen()` auto-populates a ToolRegistry from any Queen instance |
| `tests/test_tool_runtime.py` | Tests: ToolRegistry CRUD, unknown tool errors, policy denylist, schema validation, loop termination on final_text, max_steps enforcement, tool guardrail evaluation |

## Appendix: Key Contracts Added (v2)

| Contract | Purpose |
|---|---|
| `ToolSpec` | Schema for one tool (name, description, JSON Schema parameters, trust_tier, source) |
| `ToolCall` | One tool invocation from the model (call_id, tool_name, arguments, trace_id, step_index) |
| `ToolResult` | Result of executing a tool (call_id, success, output, error, cost_metrics, policy_flags) |
| `ToolExecutionPolicy` | Loop-level policy (max_steps, max_cost_per_turn_usd, require_human_approval_for_tools, allowed_tools, disallowed_tools) |
| `ToolLoopState` | Mutable state for one loop run (message_history, accumulated_cost, tool_calls/results per turn) |
| `FinalResponse` | Normalized output (final_text, tool_trace, cost_metrics, status, step_count) |
| `LLMDecision` | Normalized LLM output (tool_calls list, final_text, error, source, model) |

---

*Report v2 generated by: local codebase diff analysis. Comparison baselines: Claude Code (~70k stars), OpenClaw (~234k stars), pi-mono (~17k stars) — research conducted 2026-02-26.*
