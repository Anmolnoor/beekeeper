# Audit + Trace Standards Review and Improvement Plan
Date: 2026-03-06

## Top 3 standards to align with
1. **NIST SP 800-92 (Guide to Computer Security Log Management)**
2. **OWASP ASVS v4 (Logging and Monitoring controls, esp. V10)**
3. **ISO/IEC 27001:2022 Annex A** (especially controls for logging, monitoring, and evidence integrity)

## What was tested
- UI audit page implementation and filters (`beekeeper_api/static/audit.html`).
- Trace detail page linkage (`beekeeper_api/static/trace.html`).
- Audit write path (`beekeeper/audit_logger.py`).
- Audit and trace API endpoints (`beekeeper_api/routes.py`).
- Trace compaction tests (`tests/test_trace_compaction.py`) using local venv pytest.
- Live log/file consistency check in local `.honeycomb` data (today's audit log and events directory).

## Test evidence summary
- Trace compaction tests pass: `6 passed in 0.17s`.
- Audit records are structured JSONL with core fields (`at`, `service`, `action`, `source`) and optional `trace_id`, `outcome`, `resource`, `error`, `duration_ms`, `user_id`, `extra`.
- Audit UI links trace IDs to `/trace/<id>` and backend has corresponding trace endpoint.
- **Critical consistency finding**: multiple recent audit entries include `trace_id`, but matching event files are missing in `.honeycomb/events` for many sampled IDs.

## Current compliance posture (high-level)

### 1) NIST SP 800-92
- **Partially aligned**
- Strengths:
  - Centralized structured log format.
  - Basic filtering by service/action/source/since.
  - UTC timestamps used in storage.
- Gaps:
  - No tamper-evidence/signature per audit row.
  - No explicit retention lifecycle and archival policy enforcement.
  - No guaranteed write durability (async fire-and-forget thread).
  - Trace-to-audit correlation reliability is not guaranteed (observed missing trace files).

### 2) OWASP ASVS V10 (Logging/Monitoring)
- **Partially aligned**
- Strengths:
  - Security-relevant outcomes (success/failure) captured.
  - Auth required for audit/trace APIs.
- Gaps:
  - No explicit sensitive-data redaction policy in logger.
  - No clear event schema versioning or validation.
  - No alerting pipeline for repeated failures/anomalies.

### 3) ISO/IEC 27001:2022 Annex A (logging and monitoring controls)
- **Partially aligned**
- Strengths:
  - Operational monitoring surfaces exist (dashboard, trace/audit views).
- Gaps:
  - Integrity and non-repudiation controls for logs are not implemented.
  - Access-review and audit-log-of-audit-log access not evident.
  - Correlation completeness between audit and trace evidence is not enforced.

## Improvement plan

### Phase 1 (Immediate: 1-2 weeks) - Reliability and integrity baseline
1. Enforce **trace correlation contract**:
   - If an audit row has `trace_id`, ensure corresponding trace artifact exists (or record explicit `trace_state: unavailable` with reason).
   - Add background reconciliation job and metric: `audit_trace_linkage_rate`.
2. Add **schema validation** for audit rows at write time:
   - Required: `at`, `service`, `action`, `source`.
   - Optional fields constrained by type and max size.
   - Add `schema_version`.
3. Add **safe redaction** rules:
   - Redact secrets/tokens/credentials/PII from `error` and `extra`.
4. Add **write-failure telemetry**:
   - Emit counter/alert when audit write thread fails.

Acceptance criteria:
- `audit_trace_linkage_rate >= 99.5%` in staging.
- 0 unhandled schema-invalid rows.
- Redaction tests pass for known secret patterns.

### Phase 2 (Near term: 2-4 weeks) - Compliance hardening
1. Implement **tamper evidence**:
   - Hash chain per daily log file (or per entry) with periodic signed checkpoints.
2. Define and enforce **retention policy**:
   - Hot retention (e.g., 30-90 days), archive retention (e.g., 1 year+), and deletion policy.
3. Add **monitoring and alerting**:
   - Alerts on unusual failure rates, source anomalies, missing trace linkage spikes.
4. Add **access auditing**:
   - Log read/export access to audit and trace endpoints.

Acceptance criteria:
- Verification tool can prove file integrity for sampled windows.
- Retention job produces auditable reports.
- Alert SLOs defined and tested.

### Phase 3 (Mid term: 4-8 weeks) - Operational maturity
1. Build **standardized controls dashboard**:
   - Coverage for NIST/OWASP/ISO control mapping.
2. Add **quarterly control tests**:
   - Traceability sampling, integrity verification, redaction regression tests.
3. Document **IR-ready evidence workflow**:
   - One-click export package per incident trace.

Acceptance criteria:
- Documented control ownership and test cadence.
- Successful dry-run incident evidence package generation.

## Priority risks
1. Broken audit-trace linkage reduces forensic reliability.
2. Lack of tamper evidence weakens audit defensibility.
3. Potential sensitive data leakage in `error`/`extra` without systematic redaction.

## Suggested implementation order
1. Correlation and schema validation
2. Redaction and write telemetry
3. Integrity chain/signing
4. Retention + alerts
