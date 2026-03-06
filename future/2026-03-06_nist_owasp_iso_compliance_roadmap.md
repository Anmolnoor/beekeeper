## Audit/Trace Compliance Roadmap: NIST First, OWASP Parallel, ISO Readiness Later (180 Days)

### Summary
Use a **180-day staged rollout** owned by **Platform/Backend**, with **NIST SP 800-92** as the operating baseline, **OWASP ASVS V10** controls implemented in parallel in app/API flows, and **ISO 27001 readiness artifacts** built throughout (without certification commitment yet).  
Primary objective: make audit and trace data operationally reliable, security-appropriate, and audit-defensible.

### Implementation Changes
1. **Phase 1 (Days 0-60): NIST baseline controls**
- Define and enforce canonical audit event schema (`schema_version`, required fields, typed optional fields, size limits).
- Enforce audit-trace correlation contract:
  - If `trace_id` is present, trace record must exist; otherwise emit explicit linkage state + reason.
  - Add linkage metric (`audit_trace_linkage_rate`) and daily reconciliation job.
- Improve logging reliability:
  - Replace best-effort fire-and-forget behavior with bounded queue + retry/failure counters.
  - Add write-failure telemetry and operator-visible error budget.
- Implement retention tiers and rotation policy (hot retention + archive rules + deletion lifecycle).

2. **Phase 2 (Days 30-120): OWASP ASVS V10 controls in parallel**
- Add sensitive-data redaction policy for `error` and `extra` fields (tokens, credentials, PII patterns).
- Expand event coverage for security-relevant actions:
  - authn/authz failures, privilege changes, admin actions, data-access denials, policy decisions.
- Add detection/monitoring:
  - anomaly alerts for repeated failures, unusual source/service patterns, linkage drops.
- Add audit-read access logging for trace/audit viewers and export endpoints.

3. **Phase 3 (Days 90-180): ISO readiness layer**
- Add tamper-evidence:
  - daily hash-chain/checkpoint signing and integrity verification command/report.
- Build control-evidence pack:
  - control mapping matrix (NIST/OWASP -> ISO Annex A), owner, frequency, proof artifacts.
- Establish governance cadence:
  - monthly control review, quarterly evidence sampling, incident evidence dry-run.
- Produce readiness outputs:
  - documented policies, runbooks, and evidence index suitable for future certification initiation.

### Public Interfaces / Contract Changes
- **Audit event contract** gains: `schema_version`, `trace_link_state`, `trace_link_reason` (when unresolved), and standardized `outcome` taxonomy.
- **Audit API response** remains backward-compatible but includes new fields when present.
- **Ops metrics surface** adds:
  - `audit_trace_linkage_rate`
  - `audit_write_failure_count`
  - `redaction_hit_count`
  - `integrity_verification_status`
- **Operational jobs** added: linkage reconciliation, retention/rotation, integrity verification.

### Test Plan
1. **Schema + contract tests**
- Reject/flag malformed audit rows; accept valid rows across all services/actions.
- Verify backward compatibility for consumers that ignore new fields.

2. **Correlation tests**
- For sampled traces, ensure audit rows with `trace_id` resolve to trace artifacts.
- Validate reconciliation job catches and reports mismatches.

3. **Security/redaction tests**
- Inject known secrets/PII patterns into error paths and verify masking before persistence.
- Confirm high-risk fields never store raw secret material.

4. **Reliability/integrity tests**
- Simulate write failures and verify retries/telemetry/alerts.
- Verify hash-chain/checkpoint integrity reports detect tampering.

5. **Acceptance targets**
- `audit_trace_linkage_rate >= 99.5%` sustained in staging, then production.
- `audit_write_failure_count` within defined SLO/error budget.
- 100% redaction test pass rate for defined sensitive patterns.
- Monthly ISO-readiness evidence pack complete and reviewable.

### Assumptions and Defaults
- Timeline fixed at **180 days**.
- Ownership model: **Platform/Backend-led** with security review checkpoints.
- ISO scope is **readiness only** in this plan; no certification audit date is committed.
- Existing audit/trace UI remains, with incremental API/metric enhancements rather than replacement.

## Combined With Live Findings (2026-03-06 Test Run)
Findings reference: `future/2026-03-06_queen_test_anmol_noor_trace_audit_monitoring_report.md`

Observed gaps from the live Queen test:
- False-pass audit result on low-quality output.
- Contradictory trace/save outcome signals.
- Queue readiness + temporal worker instability.
- Thin audit coverage for task-level results.

## Implemented Now (this iteration)
The following roadmap items are now implemented in code:

1. **NIST baseline (Phase 1)**
- Canonical audit schema fields added:
  - `schema_version` (`v2`)
  - `trace_link_state`
  - `trace_link_reason` (when unresolved)
  - normalized `outcome`
- Trace correlation contract enforcement at write-time:
  - audit rows now mark linkage state (`linked` / `missing` / `not_provided`)
- Reliability/telemetry counters added in `.honeycomb/metrics/audit_metrics.json`:
  - `audit_write_count`
  - `audit_write_failure_count`
  - `trace_linkage_checked_count`
  - `trace_linkage_missing_count`

2. **OWASP ASVS V10 controls (Phase 2)**
- Sensitive data redaction in audit `error` and `extra` paths:
  - key-name redaction (`token`, `secret`, `password`, etc.)
  - token pattern masking (e.g., bearer/API key-like content)
  - `redaction_hit_count` telemetry
- Audit/trace read access logging added on API endpoints:
  - trace list/get/tree/graph/events
  - audit logs endpoint

3. **Finding-driven functional hardening**
- Fixed save-intent parsing bug causing `"it in local"` to be treated as literal file content.
- Monitor now escalates tiny write outputs for report-like flows (`insufficient_file_content_for_report`).
- Audit worker now flags undersized/placeholder file-write outputs with findings and lower score.
- Queen now emits task-level audit rows for monitor outcomes and save canonicalization outcomes.

## Metrics Surface Added
`compute_ops_metrics()` now returns:
- `audit_trace_linkage_rate`
- `audit_write_failure_count`
- `redaction_hit_count`
- `integrity_verification_status` (currently `not_configured`)

## Files Changed
- `beekeeper/audit_logger.py`
- `beekeeper/queen.py`
- `beekeeper/monitor.py`
- `beekeeper/worker.py`
- `beekeeper/ops.py`
- `beekeeper_api/routes.py`
- `tests/test_audit_trace_compliance_impl.py`
