# Alerts

Recommended baseline alerts for Phase 4:

- HITL queue pressure (`hitl_queue_pressure_10m`)
- Worker quality drift (`quality_by_worker`)
- Worker latency regressions (`latency_p95_by_worker`)
- Cost guardrail regressions (`cost_avg_by_worker`)
- Audit trace linkage degradation (`audit_trace_linkage_rate`)

Current metric source: `beekeeper.ops.compute_ops_metrics`.
