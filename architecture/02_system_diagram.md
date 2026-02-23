# 02 — System Diagrams

## Component Map

```mermaid
graph TB
    subgraph "Entry Points"
        CLI["CLI\n(beekeeper run/chat)"]
        BKAPI["Beekeeper API\n(:8787)"]
        QAPI["Queen API\n(:8788 OpenAI-compat)"]
        SDK["BeekeeperClient SDK"]
        CHANNELS["Channels\n(Slack/Telegram/Discord)"]
    end

    subgraph "Core Agent Runtime (beekeeper/)"
        QUEEN["QueenAgent\nqueen.py"]
        GUARD["GuardrailPolicyEngine\nguardrails.py"]
        SCHED["Scheduler\nscheduler.py"]
        WR["WorkerRuntime\nworker.py"]
        MONITOR["Monitor\nmonitor.py"]
        PULSE["Pulse\npulse.py"]
    end

    subgraph "Specialist Workers"
        WSW["WebSearchWorker"]
        HCW["HeavyComputeWorker"]
        AW["AuditWorker"]
        CW["Custom Workers\n(via plugins)"]
    end

    subgraph "LLM Layer"
        LLMR["LLMRouter\nllm_provider.py"]
        OLLAMA["Ollama\n(local)"]
        GEMINI["Gemini\n(Google)"]
        OPENAI["OpenAI\n(compatible)"]
    end

    subgraph "Data Layer"
        HC["HoneycombStore\nhoneycomb.py\n(append-only)"]
        BK["BeekeeperStore\nstore.py\n(multi-tenant)"]
        VS["VectorStore\nvector_store.py"]
    end

    subgraph "Infrastructure"
        REDIS["Redis\n:6379"]
        TEMPORAL["Temporal\n:7233"]
        QDRANT["Qdrant\n:6333"]
        SEARXNG["SearXNG\n:8080"]
        OWU["Open WebUI\n:3000"]
    end

    CLI --> QUEEN
    BKAPI --> QUEEN
    QAPI --> QUEEN
    SDK --> QUEEN
    CHANNELS --> BKAPI

    QUEEN --> GUARD
    GUARD --> SCHED
    SCHED --> WR
    WR --> WSW
    WR --> HCW
    WR --> AW
    WR --> CW
    QUEEN --> MONITOR
    PULSE --> QUEEN

    WSW --> LLMR
    HCW --> LLMR
    QUEEN --> LLMR
    LLMR --> OLLAMA
    LLMR --> GEMINI
    LLMR --> OPENAI

    QUEEN --> HC
    WR --> HC
    MONITOR --> HC
    HC --> VS
    BKAPI --> BK

    SCHED --> REDIS
    SCHED --> TEMPORAL
    VS --> QDRANT
    WSW --> SEARXNG
    OWU --> QAPI
```

---

## Request Lifecycle (Sequence)

```mermaid
sequenceDiagram
    participant User
    participant QueenAgent
    participant GuardrailEngine
    participant Scheduler
    participant WorkerRuntime
    participant LLMRouter
    participant HoneycombStore

    User->>QueenAgent: run(intent, payload)
    QueenAgent->>LLMRouter: decompose_intent(intent, payload)
    LLMRouter-->>QueenAgent: list[TaskEnvelope]

    loop For each task
        QueenAgent->>GuardrailEngine: evaluate(task, rule_profile)
        alt Blocked
            GuardrailEngine-->>QueenAgent: PolicyDecision(block)
            QueenAgent->>HoneycombStore: write_policy_decision()
        else Needs Human
            GuardrailEngine-->>QueenAgent: PolicyDecision(needs_human)
            QueenAgent->>HoneycombStore: enqueue_review()
        else Approved
            GuardrailEngine-->>QueenAgent: PolicyDecision(approve)
            QueenAgent->>Scheduler: submit(task_payload, context_payload)
            Scheduler->>WorkerRuntime: execute_task_serialized()
            WorkerRuntime->>LLMRouter: chat(prompt)
            LLMRouter-->>WorkerRuntime: (text, source)
            WorkerRuntime->>HoneycombStore: write_result()
            WorkerRuntime->>HoneycombStore: write_artifact()
            Scheduler-->>QueenAgent: ResultEnvelope
            QueenAgent->>HoneycombStore: record_routing_outcome()
        end
    end

    QueenAgent-->>User: aggregated results
```

---

## Data Flow: Honeycomb Storage

```mermaid
graph LR
    subgraph "HoneycombStore (.honeycomb/)"
        EV["events/<trace_id>.jsonl\n(telemetry, transitions)"]
        TASKS["tasks/<task_id>.json\n(task definitions)"]
        ART["artifacts/<artifact_id>.json\n(reports, output files)"]
        GOV["governance/<decision_id>.json\n(policy decisions)"]
        GRAPH["graph/<trace_id>.jsonl\n(task DAG edges)"]
        PERF["performance/*.jsonl\n(worker metrics)"]
        OPT["optimizer/routing_feedback.json\n(adaptive routing)"]
        REV["reviews/<review_id>.json\n(HITL queue)"]
        ARCH_W["archive/warm/\n(30-90 day artifacts)"]
        ARCH_C["archive/cold/\n(>90 day artifacts)"]
    end

    WR["WorkerRuntime"] --> EV
    WR --> TASKS
    WR --> ART
    GUARD["GuardrailEngine"] --> GOV
    QUEEN["QueenAgent"] --> GRAPH
    QUEEN --> PERF
    QUEEN --> OPT
    QUEEN --> REV
    ART -->|"lifecycle (30d)"| ARCH_W
    ARCH_W -->|"lifecycle (90d)"| ARCH_C
```

---

## Multi-Tenant Hierarchy

```mermaid
graph TD
    BKS["BeekeeperStore\n(.beekeeper_store/)"]
    ORG["Organization"]
    HIVE["Hive"]
    HC2["Honeycomb"]
    QUEEN2["Queen Instance"]
    TPL["Template\n(AgentBlueprint)"]
    CHAN["Channel Config\n(Slack/Telegram/Discord)"]
    USER["User\n(auth)"]

    BKS --> ORG
    ORG --> HIVE
    HIVE --> HC2
    HIVE --> QUEEN2
    BKS --> TPL
    BKS --> CHAN
    BKS --> USER
```

---

## Scheduler Backend Selection

```mermaid
graph LR
    QUEEN["QueenAgent"] -->|"scheduler_backend=inline"| IS["InlineScheduler\n(same process)"]
    QUEEN -->|"scheduler_backend=celery"| CS["CeleryScheduler\n(Redis queue)"]
    QUEEN -->|"scheduler_backend=temporal"| TS["TemporalBeekeeperClient\n(durable workflows)"]

    IS --> WR["WorkerRuntime (sync)"]
    CS --> REDIS["Redis :6379"] --> CELERY["Celery Worker Process"]
    CELERY --> WR
    TS --> TEMPORAL["Temporal Server :7233"] --> TWORKER["Temporal Worker Process"]
    TWORKER --> WR
```

---

## LLM Provider Fallback Chain

```mermaid
graph LR
    LLMRouter -->|"1st choice"| P1["Provider 1\n(e.g. Ollama)"]
    P1 -->|"fails"| P2["Provider 2\n(e.g. Gemini)"]
    P2 -->|"fails"| P3["Provider 3\n(e.g. OpenAI)"]
    P3 -->|"all fail"| FB["(None, 'fallback')"]

    P1 -->|"success"| R["(text, 'ollama')"]
    P2 -->|"success"| R2["(text, 'gemini')"]
    P3 -->|"success"| R3["(text, 'openai')"]
```
