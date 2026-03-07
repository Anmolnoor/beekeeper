# Maturity Model

## Levels

- Prototype: local demo behavior; limited controls; no production claim.
- Internal: repeatable team usage with explicit known gaps and guardrails.
- Production Candidate: fail-closed config, durable state, policy-mediated actions, observable e2e paths.
- Production: release gates, restore drills, tenant controls, and evidence-backed SLO/SLI coverage.

## Current Position

- Platform core: Internal
- Durable execution path: Production Candidate target (Temporal + Postgres + object storage)
- Worker forge: Prototype/Experimental
- Multi-channel support: Internal/Experimental, not production-grade depth

## Promotion Gates

- Non-dev startup fails closed on missing/insecure secrets/config.
- One golden path + one approval path + one failure/retry path + one restore drill are automated.
- Claims in README/docs map to tests, dashboards, or incident runbooks.
