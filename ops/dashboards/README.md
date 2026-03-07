# Dashboards

Phase 4 dashboard minimums:

- Run operations: run state distribution, stuck runs, blocked approvals, failure reasons.
- Worker operations: queue depth, retry rates, lease/heartbeat lag, concurrency saturation.
- Governance: policy allow/deny/escalate, webhook verification failures, sandbox tier usage.
- Channel operations: inbound volume, dedupe hits, delivery failures and retries.
- Tenancy: runs by org/hive, quota pressure, hot tenants.

Use `/api/ops/overview`, `/api/analytics/latency`, and `/api/runs/{trace_id}/inspection` as primary local data sources.
