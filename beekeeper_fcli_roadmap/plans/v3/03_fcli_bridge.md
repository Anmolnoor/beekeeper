# 03: FCLI Bridge Plan

Date: 2026-06-08

## Context

FCLI already has the worker-plane pieces Beekeeper needs: typed file, git, and shell operations; bounded plan/execute/observe loops; verification taxonomy; local traces; and redacted event output.

The bridge must use those strengths without making Beekeeper depend on FCLI's interactive terminal UX.

The V3 problem is:

> Can Beekeeper dispatch a coding task and consume FCLI-grade execution through a machine-readable contract?

## Desired User Outcome

The user asks Beekeeper for a small coding task in a local repo. Beekeeper creates a run, dispatches the coding worker, shows live progress, and ends with a summary, changed files, diff, and verification status.

The user should not need to know whether the worker was launched as a subprocess, imported package, or later moved into a container.

## Bridge Strategy

### First Bridge: Process Adapter

The first practical bridge can launch an FCLI command as a subprocess and consume structured output.

This is acceptable only if:

- the worker emits NDJSON or another documented machine-readable event stream,
- Beekeeper does not parse terminal prose,
- the command receives task input as JSON or a path to JSON,
- the final result is structured,
- stderr/stdout are captured as artifacts or diagnostic evidence.

### Later Bridge: Package Adapter

After the process bridge proves the contract, a package adapter can import FCLI services directly behind the same Beekeeper-facing interface.

This should happen only when it reduces operational complexity. It should not force Beekeeper to absorb FCLI's orchestration internals.

## Required Inputs

The bridge needs:

- `CodingWorkerTask` from V2,
- admitted workspace path,
- provider profile or credential reference,
- side-effect policy,
- run and trace IDs,
- output directory for event/result/artifact files,
- timeout and output limits.

## Required Outputs

The bridge should return:

- normalized `CodingWorkerResult`,
- event stream consumed into Beekeeper run history,
- artifact references,
- worker exit code,
- error classification if the worker failed,
- raw diagnostic logs where safe.

## Event Handling

The event consumer should:

1. Read worker events incrementally.
2. Validate each event against the V2 contract.
3. Store valid events in Beekeeper run history.
4. Preserve unknown but validly shaped event kinds.
5. Mark malformed events as bridge errors without crashing the whole server.
6. Keep a raw redacted event artifact for debugging.

## Run Lifecycle Mapping

| Worker observation | Beekeeper run state |
|---|---|
| process started | `running` |
| first valid event | `running` with activity |
| approval request | `blocked_approval` |
| successful result | `completed` |
| failed result | `failed` |
| timeout | `failed` with timeout reason |
| cancelled by user | `cancelled` |
| worker bridge crash | `failed` with bridge error |

## Workspace Admission

Before launching the worker, Beekeeper should verify:

- workspace path exists,
- workspace path is a directory,
- workspace path is inside an allowed local root or has been explicitly registered,
- workspace path is not a sensitive system directory,
- requested task is allowed for that workspace,
- policy side effects match the task mode.

The worker should still enforce workspace boundaries itself. Beekeeper admission is the first gate, not the only gate.

## Failure Model

Bridge failures should be specific:

| Failure | Meaning |
|---|---|
| `worker_not_found` | FCLI executable or package adapter is unavailable. |
| `invalid_task` | Task payload failed contract validation. |
| `workspace_not_admitted` | Workspace path failed Beekeeper admission. |
| `provider_unavailable` | Provider profile failed validation. |
| `event_stream_invalid` | Worker emitted malformed structured events. |
| `worker_timeout` | Worker exceeded runtime limit. |
| `worker_failed` | Worker returned a valid failed result. |
| `bridge_error` | Adapter failed before it could normalize the result. |

## Implementation Sequence

### Step 1: Build Bridge Interface

Define a Beekeeper-side interface such as:

```text
run_coding_worker(task) -> CodingWorkerResult
```

The implementation can be process-backed first, but callers should not care.

Verification:

- Unit tests can use a fake worker that emits valid NDJSON.

### Step 2: Add Fake Worker Harness

Before launching real FCLI, add a fake local command or test harness that emits V2 fixture events.

Verification:

- Beekeeper can ingest events and store a result from the fake worker.

### Step 3: Add Read-Only FCLI Run

Run a task that inspects workspace status/files but does not mutate anything.

Verification:

- Beekeeper receives structured events.
- Beekeeper stores a final result.
- No file changes occur.

### Step 4: Add Mutation Run

Allow a small workspace-confined edit when task policy permits mutation.

Verification:

- Changed files are reported.
- Final diff artifact is created.
- Verification status is reported.

### Step 5: Add Timeout and Cancellation

Make long or stuck runs stop cleanly.

Verification:

- Timed-out run is marked failed with timeout reason.
- Cancelled run is marked cancelled.
- Partial events remain available.

## Non-Goals

- No automatic commit.
- No push or PR creation.
- No remote worker hosts.
- No container sandbox requirement yet.
- No full dashboard rebuild.
- No Worker Forge integration.

## Acceptance Bar

V3 is complete when a tiny local repo task can run through Beekeeper with:

- valid task input,
- structured worker events,
- stored run timeline,
- normalized final result,
- changed-file summary when applicable,
- verification status,
- clear failure classification when something breaks.

