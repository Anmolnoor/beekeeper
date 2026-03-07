# Storage Classification

## Source of Truth Targets

- State metadata target: Postgres (`runs`, `tasks`, `approvals`, `policy_decisions`, `tool_calls`)
- Artifacts target: S3-compatible object storage
- Durable workflow target: Temporal

## Current Local Paths (Development)

- `.honeycomb/`: trace/audit timeline and related local artifacts
- `.beekeeper_store/`: tenant/settings/user/channel records for local operation
- `.pytest_cache/`, `.pycache*`, `.migration_*`: cache/temp/operational support data

## Classification Rules

- State: records required for correctness and restart safety
- Artifact: large payloads and generated outputs
- Log/Event: append-only timeline and diagnostics
- Cache/Temp: deletable without correctness loss
- Config: runtime settings and non-secret defaults

## Non-Negotiable Rule

- Local disk must not be the authoritative source of truth in production mode.
