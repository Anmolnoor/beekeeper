# 04: Policy, Approvals, and Artifacts Plan

Date: 2026-06-08

## Context

The core Beekeeper value is governance. If the coding worker can edit files, run commands, or touch git without visible policy and approval records, Beekeeper becomes just another agent launcher.

V4 turns the bridge into a supervised workflow:

- policy decides what is allowed,
- approvals gate risky actions,
- artifacts preserve evidence,
- audit records connect the user request to the final result.

## Desired User Outcome

The user should be able to inspect a run and answer:

- What did I ask Beekeeper to do?
- Which worker handled it?
- What files did it read or change?
- What commands did it run?
- What verification did it attempt?
- What actions needed approval?
- What did I approve or reject?
- What final diff or artifact did it produce?

## Policy Posture

V4 should start conservative.

| Action | Default posture |
|---|---|
| Read files under admitted workspace | Allow. |
| Search files under admitted workspace | Allow. |
| Edit files under admitted workspace | Allow only for mutation-enabled tasks. |
| Run safe verification commands | Allow with command logging and limits. |
| Git status/diff/log/show | Allow. |
| Git stage | Approval required. |
| Git commit | Approval required. |
| Git push/fetch/pull | Block by default. |
| Network access | Block or approval required. |
| Destructive shell command | Block or approval required. |
| Out-of-workspace path | Block. |
| Secret access | Block unless using approved secret references. |

## Approval Lifecycle

The first lifecycle can be stop-and-rerun:

1. Worker requests a risky action.
2. Beekeeper records pending approval.
3. Run enters `blocked_approval`.
4. User approves or rejects in Beekeeper.
5. User reruns or resumes once resume support exists.

Mid-run pause/resume can come later. V4 should not fake resume if the worker cannot do it reliably.

## Approval Detail

Each approval should show:

- action,
- requesting worker,
- run ID,
- trace ID,
- workspace,
- target file, command, git operation, or network destination,
- policy reason,
- worker rationale,
- evidence links,
- approve/reject controls,
- optional user note,
- final resolution.

## Artifact Model

Artifacts should be first-class run evidence.

Required artifact types:

| Artifact | Purpose |
|---|---|
| Final diff | Shows exactly what changed. |
| Changed file summary | Quick dashboard view. |
| Command output summary | Shows verification and important command results. |
| Verification report | Stores passed/failed/unavailable/not attempted state. |
| Approval evidence | Stores the reason an approval was requested. |
| Worker event trace | Keeps the structured event stream available. |
| Final answer | Stores the worker summary. |

Artifacts should have stable IDs and trace links. The dashboard should not need to scrape files or logs to reconstruct the run.

## Audit Trail

Every coding run should connect:

```text
user request
  -> Beekeeper run
  -> coding worker task
  -> worker events
  -> policy decisions
  -> approval records
  -> artifacts
  -> final result
```

This is the line Beekeeper owns.

## Implementation Sequence

### Step 1: Map Side Effects to Policy Decisions

Convert worker side-effect requests into Beekeeper policy decisions.

Verification:

- Allowed read action proceeds.
- Blocked path escape is denied.
- Commit request creates approval.

### Step 2: Persist Approval Requests

Use the existing approval queue where possible.

Verification:

- Approval appears in API/dashboard.
- Approval includes action, reason, target, run ID, and trace ID.

### Step 3: Store Required Artifacts

Persist final diff, verification report, event trace, and final summary.

Verification:

- A completed run can be inspected without rerunning the worker.

### Step 4: Add Dashboard Links

Expose artifacts and approvals from run detail.

Verification:

- Run detail links to approval record, final diff, verification report, and event trace.

### Step 5: Add Policy Regression Tests

Cover allowed, blocked, and approval-required paths.

Verification:

- Tests prove file edit, command execution, commit request, network request, destructive shell, and path escape behavior.

## Test Matrix

| Scenario | Expected result |
|---|---|
| Read workspace file | Allowed, event recorded. |
| Edit workspace file with mutation allowed | Allowed, changed file artifact recorded. |
| Edit workspace file in read-only task | Blocked or approval required. |
| Read outside workspace | Blocked. |
| Run safe test command | Allowed, command output summarized. |
| Run destructive command | Blocked or approval required. |
| Git diff | Allowed, artifact recorded. |
| Git commit | Approval required. |
| Git push | Blocked by default. |
| Worker requests network | Blocked or approval required. |

## Non-Goals

- No automatic push.
- No automatic PR creation.
- No broad remote execution.
- No perfect mid-run resume requirement.
- No full compliance export yet.

## Acceptance Bar

V4 is complete when a coding-worker run produces visible policy, approval, artifact, and audit evidence for all meaningful side effects.

