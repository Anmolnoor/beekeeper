# Third Project (skep): v1 Shipped

Date: 2026-06-11

The third project decided in `2026-06-10_third_project_detailed_plan_and_decisions.md`
exists — renamed from the working name beekeeper-personal to **skep** (G9) — and is at its v1 acceptance bar (spine proven, death path proven, evidence
chain end-to-end, 10/10 reliability runs twice in a row).

| Piece | Where | What |
|---|---|---|
| Contract | `~/Developer/agent-task-contract` (Apache-2.0) | Pydantic models, JSON Schemas, golden fixtures, version-skew helper |
| Worker | `~/Developer/fcli` (GPL-3.0) | `foundation run --headless` + deterministic mock provider |
| Supervisor | `~/Developer/skep` (AGPL-3.0, https://github.com/Anmolnoor/skep) | dispatch pipeline, run store, approval queue, audit trail, `skep run/status/review` CLI |

- Decision record + contract spec v0.1: in the skep repo root
- Build log with per-stage verification evidence: `skep/PROGRESS.md`
- ADRs (contract ownership, patch-as-approval, carve-out boundary, licensing):
  `~/Developer/skep/docs/adr/`

This Beekeeper repo remains the frozen donor: carve-outs are copy-and-upgrade
only (ADR 0003), never imports.
