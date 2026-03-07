# Storage Classification

## Explicit Storage Tiers

- **Dev/local store (current default for local development):** JSONL/filesystem (`.honeycomb/`, `.beekeeper_store/`) for quick iteration and local debugability.
- **Prod metadata store (authoritative state):** Postgres (`runs`, `tasks`, `approvals`, `policy_decisions`, `tool_calls`).
- **Prod event/log store (append-only telemetry/history):** Postgres/Kafka/ClickHouse/object storage, selected by throughput and retention goals.
- **Artifact store (generated payloads, exports, large blobs):** S3-compatible object storage.
- **Vector store (semantic retrieval only):** Qdrant.

## Classification Rules

- **State metadata:** Required for correctness and restart safety.
- **Event/log stream:** Operational reconstruction and analytics.
- **Artifact payloads:** Large generated outputs and files.
- **Vector memory:** Retrieval acceleration; not authoritative business state.
- **Cache/temp:** Deletable without correctness loss.
- **Config:** Runtime settings and non-secret defaults.

## Non-Negotiable Rule

- Local disk must not be the authoritative source of truth in production mode.
- One storage layer must not carry mixed responsibilities across metadata, telemetry, and artifacts in production.
