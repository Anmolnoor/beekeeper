# Restore Drill Runbook

## Goal
Validate that run metadata survives process restart and remains inspectable.

## Procedure
1. `HONEYCOMB_ROOT=.honeycomb_recovery_drill ./scripts/run_recovery_drill.sh`
2. Confirm output includes `[OK] recovery drill passed`.
3. Confirm `control_plane.db` exists under the drill root.
4. Verify at least two runs are present via SQL:
   - `SELECT COUNT(*) FROM runs;`
5. Verify run state transitions exist:
   - `SELECT COUNT(*) FROM run_state_transitions;`

## Recovery signal
A drill is considered healthy when both run and transition counts increase after repeated executions.
