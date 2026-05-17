# Risks and Known Gaps

## Known Gaps

- `beekeeper/queen.py` and `beekeeper/runner.py` still hold multiple concerns and require decomposition.
- Honeycomb remains heavily used for local trace/event storage and should not be treated as authoritative production state.
- Channel implementations are broader than current verification depth.
- Worker forge exists but does not yet pass a full promotion/signing/sandbox pipeline.

## Active Risks

- Back-end breadth can outpace proof and create overstated readiness language.
- Non-dev misconfiguration can silently weaken security if fail-closed checks are bypassed.
- Retry/idempotency behavior may regress without explicit state-machine and contract coverage.

## Mitigations in Progress

- Runtime mode validation with fail-closed behavior for `internal` and `prod`.
- Smoke-test entrypoint and doctor command for baseline operational checks.
- Support matrix and maturity labeling to keep claims aligned with evidence.
