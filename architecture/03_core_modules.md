# 03 — Core Modules Reference

All modules live in `beekeeper/`. Each section covers purpose, key classes/functions, and how they fit into the system.

---

## `contracts.py` — Typed Schemas & Envelopes

**Purpose**: The single source of truth for all data models. Every other module imports from here.

| Class | Description |
|-------|-------------|
| `TaskEnvelope` | Unit of work: `task_id`, `task_type`, `worker_kind`, `payload`, `budget_usd`, `trust_tier`, `status` |
| `ResultEnvelope` | Output from a worker: `task_id`, `status`, `output`, `cost_metrics`, `artifact_refs` |
| `AgentIdentity` | Runtime identity: `agent_id`, `agent_type`, `skill_profile_id`, `soul_profile_id`, `trust_tier` |
| `AgentBlueprint` | Template for Queen or Worker: combines `ProfileBundleRef` pointing to all 6 profile types |
| `ProfileBundleRef` | Pointer to 6 profile IDs: soul, abilities, accountabilities, rules, guardrails, skills |
| `SkillProfile` | Worker capabilities: `can_search_web`, `can_execute_code`, `tool_allowlist`, `max_parallel_tools` |
| `SoulProfile` | Behavioral traits: `tone`, `risk_appetite`, `verbosity`, `escalation_style` |
| `RuleProfile` | Hard constraints: `hard_budget_usd`, `max_runtime_seconds`, `max_retries`, `allowed_domains`, `require_human_approval_for` |
| `GuardrailProfile` | Active guardrails: `enabled_guardrails`, `allow_external_network`, `enforce_domain_allowlist` |
| `AbilitiesProfile` | Tool/capability allowlist + `max_parallel_tools` |
| `AccountabilityPolicy` | Governance: `must_emit_audit_log`, `max_unapproved_actions`, `requires_trace_for_all_actions` |
| `PolicyDecision` | Guardrail outcome: `status` ∈ {`approve`, `block`, `needs_human`}, `guardrail_flags`, `approved_by` |
| `ArtifactRef` | Pointer to a stored artifact: `artifact_id`, `task_id`, `kind`, `location`, `checksum` |
| `CostMetrics` | Telemetry: `input_tokens`, `output_tokens`, `latency_ms`, `estimated_cost_usd` |
| `WorkerPerformanceRecord` | Telemetry record per worker execution for adaptive routing |
| `RoutingFeedback` | Per-(worker_kind, intent) rolling stats: quality, latency, cost, success rate |

**Key enums**: `Status` (queued/running/success/failed/blocked), `WorkerKind` (web_search/heavy_compute/audit/monitor/logger/custom), `TrustTier` (low/medium/high), `RetryCategory` (transient/tool/model/policy/quality)

---

## `queen.py` — Queen Agent (Orchestrator)

**Purpose**: Central planner, router, and execution loop. The brain of the platform.

### `QueenConfig`
Configuration dataclass for the Queen agent:
- `honeycomb_root` — where data is persisted
- `scheduler_backend` — `"inline"` | `"celery"` | `"temporal"`
- `vector_backend` — `"memory"` | `"qdrant"`
- `max_reruns` — how many monitor-triggered reruns allowed
- `llm_provider`, `ollama_*`, `gemini_*`, `openai_*` — LLM config

### `QueenAgent`
Main class. Key methods:

| Method | Description |
|--------|-------------|
| `__init__(config)` | Builds scheduler, seeds default profiles/blueprints, initializes Honeycomb and Tracer |
| `_seed_defaults()` | Seeds all default skills, rules, souls, guardrails, abilities, accountability profiles into registry |
| `decompose_intent(trace_id, request_id, intent, payload)` | Calls LLM to break intent into `TaskEnvelope` list |
| `_route_worker_kind(intent, payload)` | Maps intent string to the correct `WorkerKind` |
| `_route_skill(task)` | Resolves the best matching `SkillProfile` for a task |
| `_build_worker_context(task)` | Assembles `WorkerContext` from profile registry |
| `_run_task_with_policies(task)` | Runs guardrail evaluation, handles HITL, dispatches to scheduler |
| `_execute_worker_task(task, context)` | Calls `WorkerRuntime.run_once()` and records performance |
| `_resolve_human_approval(task, policy)` | Checks if task already has human approval in payload |
| `resume_human_review(review_id, approver, approved)` | Resolves a pending HITL review |
| `run_autonomous(source, task)` | Runs a task from Pulse without user request, validated against `AutonomyPolicy` |
| `run(intent, payload, ...)` | **Main entrypoint** — full request lifecycle with decomposition, policy, scheduling, monitoring |

---

## `worker.py` — Worker Runtime & Specialist Workers

**Purpose**: Ephemeral task execution. Each worker runs once, writes results, and terminates.

### `WorkerContext`
Dataclass bundling all profiles needed for a run: `identity`, `skill`, `rule`, `soul`, `abilities`, `accountability`, `guardrails`, `status_callback`.

### `BaseSpecialistWorker` (Protocol)
Interface all specialist workers implement:
- `preflight(task, context)` — pre-execution validation
- `execute(task, context)` — **main logic**
- `validate(payload)` — payload schema check
- `terminate(task, context)` — post-execution cleanup

### Specialist Workers

| Class | `WorkerKind` | What It Does |
|-------|-------------|-------------|
| `WebSearchWorker` | `web_search` | Runs direct LLM reply or SearXNG-backed retrieval depending on `use_web_search`; returns `WebSearchOutput` |
| `HeavyComputeWorker` | `heavy_compute` | Statistical analysis of number arrays, returns `HeavyComputeOutput` |
| `AuditWorker` | `audit` | Reviews a target task result for quality/compliance, returns `AuditOutput` |

### `WorkerRuntime`
The execution engine that:
1. Looks up the appropriate specialist worker (built-in or plugin via `plugins.py`)
2. Calls `preflight()` → `execute()` → `terminate()`
3. Writes `ResultEnvelope`, `ArtifactRef`, and performance record to Honeycomb
4. Tracks retries with backoff (`RetryCategory`-aware)

---

## `honeycomb.py` — Append-Only Data Plane

**Purpose**: All persistence for task events, artifacts, results, governance decisions, routing feedback.

### `HoneycombConfig`
- `root_dir` — filesystem path (default: `.honeycomb/`)
- `vector_backend`, `vector_url`, `vector_collection` — semantic memory config

### `HoneycombStore` — Key Methods

| Category | Methods |
|----------|---------|
| **Events** | `write_event()`, `read_events()`, `list_traces()` |
| **Tasks** | `write_task()` |
| **Results** | `write_result()` |
| **Artifacts** | `write_artifact()` |
| **Governance** | `write_policy_decision()` |
| **Graph** | `read_graph()` (parent-child DAG edges) |
| **HITL** | `enqueue_review()`, `get_review()`, `list_pending_reviews()`, `resolve_review()` |
| **Routing** | `record_routing_outcome()`, `read_routing_feedback()`, `top_worker_kinds()` |
| **Performance** | `write_worker_performance()` |
| **Vector** | `semantic_search()`, `embed_artifact()` |
| **Lifecycle** | `enforce_retention_lifecycle()` — moves old artifacts to warm/cold archive |

---

## `scheduler.py` — Task Dispatch

**Purpose**: Abstracts task submission and result collection across 3 backends.

| Class | Backend | How It Works |
|-------|---------|-------------|
| `InlineScheduler` | In-process | Calls handler synchronously, stores result in dict |
| `CeleryScheduler` | Redis/Celery | Sends task via `celery.send_task()`, polls `AsyncResult` |
| `TemporalScheduler` | Temporal | Dispatches via Temporal workflow client (see `temporal_integration.py`) |

### `RoutingFeedbackOptimizer`
Scores a worker's historical performance: `quality (60%) + latency (25%) + cost (15%)`. Used for adaptive routing decisions.

### `classify_retry_category(reason)` + `retry_backoff_seconds(attempt, category)`
Maps error strings to `RetryCategory`, applies exponential backoff (capped at 8s). Policy errors get 0s backoff (human must intervene).

---

## `guardrails.py` — Policy Enforcement

**Purpose**: Pre-execution policy checks on every task.

### Built-in Guardrails

| Class | What It Blocks |
|-------|---------------|
| `SchemaGuardrail` | Tasks with empty `task_type` |
| `PIIGuardrail` | Payloads containing email addresses |
| `JailbreakGuardrail` | Prompts with phrases like "ignore previous instructions" |
| `WebDomainGuardrail` | Web search to domains not in `allowed_domains` |
| `HeavyComputeBudgetGuardrail` | Budgets over limit, or payloads > 10,000 numbers |
| `AuditPayloadGuardrail` | Audit tasks missing `target_task_id` |

### `GuardrailPolicyEngine`
- `evaluate(task, rule_profile)` → `PolicyDecision` (`approve` | `block` | `needs_human`)
- `apply_budget_controls(task, rule_profile)` → Downgrades/upgrades model tier based on budget ratio

---

## `llm_provider.py` — LLM Abstraction

**Purpose**: Unified interface for multiple LLM backends with ordered fallback.

### Providers

| Class | Provider | Notes |
|-------|---------|-------|
| `OllamaProvider` | Ollama (local) | Calls `/api/chat` or `/api/generate` via HTTP |
| `GeminiProvider` | Google Gemini | Calls `generativelanguage.googleapis.com` REST API |
| `OpenAIProvider` | OpenAI / compatible | Calls `/chat/completions`, supports custom `base_url` |

### `LLMRouter`
- `call(prompt, system, messages, model_tier, model_override)` → `(text, source)`
- Tries providers in order; returns first success
- `model_tier` ∈ {`economy`, `standard`, `premium`} resolves model from env vars like `BEEKEEPER_OLLAMA_MODEL_PREMIUM`
- `LLMRouter.from_env()` builds router from `BEEKEEPER_LLM_PROVIDERS` env var

---

## `store.py` — Beekeeper Multi-Tenant Store

**Purpose**: Manages organizational hierarchy, templates, channels, users, settings, memory.

### `BeekeeperStore` — Key Capabilities

| Domain | Methods |
|--------|---------|
| **Organizations** | `create_org()`, `list_orgs()` |
| **Hives** | `create_hive()`, `list_hives()`, `get_hive()` |
| **Honeycombs** | `create_honeycomb()`, `list_honeycombs()` |
| **Queens** | `create_queen()`, `list_queens()` |
| **Templates** | `save_template()`, `list_templates()`, `export_template()`, `import_template()` |
| **Settings** | `write_setting()`, `read_setting()`, `write_hive_setting()` |
| **Channels** | `write_channel_config()` (secrets encrypted), `get_channel_config_decrypted()` |
| **Auth** | `create_user()`, `get_user_by_email()`, `set_password_hash()` |
| **Pairing** | `create_pairing_code()`, `validate_pairing_code()`, `is_dm_paired()` |
| **Audit** | `append_audit_event()` (signed HMAC logs) |
| **User Memory** | `append_user_memory()`, `list_user_memories()` |
| **LLM Resolution** | `resolve_llm_model()` — hive-level override then global |

---

## `monitor.py` — Quality Sentinel

**Purpose**: Post-execution quality evaluator that triggers retries.

- Evaluates `ResultEnvelope` for confidence, completeness, evidence quality
- Classifies retry categories (`RetryCategory`)
- Emits monitor events with `quality_score` to Honeycomb
- Feeds back to `RoutingFeedbackOptimizer` for adaptive routing

---

## `pulse.py` — Background Scheduler

**Purpose**: Periodic background task trigger (cron-like agent heartbeat).

- Runs on a configurable interval
- Calls `QueenAgent.run_autonomous()` with scheduled tasks from Honeycomb backlog
- Respects `AutonomyPolicy` (what can run without a human request)

---

## `celery_app.py` — Celery Integration

**Purpose**: Registers the `beekeeper.execute_worker_task` Celery task.

- Reads broker/backend URLs from env
- Task calls `execute_task_serialized()` from `worker.py`

---

## `temporal_integration.py` — Temporal Workflow Integration

**Purpose**: Durable task execution via Temporal workflows.

- `TemporalConfig` — endpoint, namespace, task queue, fallback endpoints
- `TemporalBeekeeperClient` — wraps Temporal client for workflow submission
- Activities map to `WorkerRuntime.run_once()`

---

## `sdk.py` — Python Client SDK

**Purpose**: High-level client for programmatic use.

- `BeekeeperClient` / `create_client()` — simple wrapper around `QueenAgent.run()`
- Suitable for embedding in other Python applications

---

## `plugins.py` / `worker_registry.py` — Plugin System

**Purpose**: Allows custom worker types to be registered at runtime.

- Workers declared in `.honeycomb/workers/plugins.json`
- `WorkerRegistry` resolves `WorkerKind` → `BaseSpecialistWorker` instance

---

## `vector_store.py` — Semantic Memory

**Purpose**: Embedding storage and similarity search.

| Backend | Class | Notes |
|---------|-------|-------|
| `memory` | `InMemoryVectorStore` | In-process list, cosine similarity |
| `qdrant` | `QdrantVectorStore` | Remote Qdrant server |

Used by `HoneycombStore.semantic_search()` to find relevant past artifacts.

---

## `web_adapters.py` — Web Search Adapter

**Purpose**: Wraps SearXNG for web search queries.

- `SearxngAdapter.search(query, domains)` → list of `WebEvidence`
- Handles domain filtering and result normalization (when domain list is provided)

---

## `tracing.py` — Span/Trace Instrumentation

**Purpose**: Lightweight tracing layer (no external dependency).

- `Tracer` creates spans stored in `HoneycombStore`
- `Span` tracks `trace_id`, `span_id`, `parent_span_id`, start/end times

---

## `souls/` — Queen Soul Profiles

Two files define the Queen's personality:
- `queen.soul.json` — machine-readable `SoulProfile`
- `queen.soul.md` — human-readable soul documentation

Traits: constitutional helpfulness/honesty/harmlessness, explicit uncertainty reporting, deterministic evidence-first orchestration.

---

## Other Modules

| Module | Purpose |
|--------|---------|
| `autonomy.py` | `AutonomyPolicy` — what sources/tasks can trigger Queen autonomously |
| `channel_auth.py` | Channel authentication and signing secret validation |
| `channel_allowlist.py` | Per-channel user allowlist enforcement |
| `channel_mention.py` | Detects bot mentions in channel messages |
| `channel_pairing.py` | DM pairing code flow for user identity binding |
| `channels.py` | Channel dispatch router |
| `profiles.py` | Profile serialization helpers |
| `prompt_templates.py` | Jinja-style prompt template engine |
| `queen_context.py` | Renders Queen context window for multi-turn sessions |
| `queen_updates.py` | Writes streaming status updates for Queen runs |
| `registry.py` | `SkillRuleSoulRegistry` — in-memory registry for all profiles |
| `security.py` | HMAC-signed audit log appending |
| `skill_loader.py` | Loads `SkillProfile` objects from Markdown files |
| `soul.py` | Soul profile loading and validation |
| `tenancy.py` | Pydantic models for org/hive/honeycomb/queen/user records |
| `migrate_blueprints.py` | One-time migration of default blueprints into template store |
| `user_memory.py` | Per-user memory embedding and retrieval |
| `trace_compaction.py` | Compacts old trace JSONL files |
| `runner.py` | CLI entry point — all `beekeeper` subcommands implemented here |
| `demo.py` | Demo scenarios for blocked, approved, and optimized task paths |
