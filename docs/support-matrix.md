# Support Matrix

This document defines support depth as of March 6, 2026.

## Supported Production Path

- Workflow/durable execution: Temporal
- Authoritative metadata: Postgres
- Artifacts: S3-compatible object storage
- Policy engine: OPA/Rego (planned integration contract; local adapter still present for transitional flows)
- Observability: OpenTelemetry correlation model (required path)
- Channel: Slack-first
- Primary LLM path: one configured default provider

## Internal / Transitional

- Honeycomb JSONL trace and audit timeline as developer-facing adapter
- Inline scheduler for local debugging and development flows
- Qdrant for retrieval-only workloads when explicitly enabled

## Experimental / Dev Only

- Experimental worker forge
- Prototype dashboard
- Logical multi-tenancy
- Unit-tested core, limited live integration coverage
- Multi-channel production claims (Telegram/Discord/WhatsApp depth)
- Multi-provider LLM breadth as production narrative
- Filesystem-backed authoritative run state
