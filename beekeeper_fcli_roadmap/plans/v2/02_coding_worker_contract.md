# 02: Coding Worker Contract Plan

Date: 2026-06-08

## Context

The roadmap decision is that Beekeeper should supervise a `coding_worker`, while FCLI supplies the execution kernel. That only works if the boundary is explicit.

The contract must prevent two failure modes:

1. Beekeeper parsing human terminal text and breaking whenever FCLI changes its UI.
2. Beekeeper importing so much FCLI internals that the control plane and worker plane collapse into one system.

The V2 job is to define the stable bridge before V3 executes anything through it.

## Desired User Outcome

The user does not see schemas directly. The user sees a coding run that has clear states:

- queued
- running
- waiting for approval
- failed
- completed

Under the hood, those states come from a contract Beekeeper can trust.

## Ownership Boundary

Beekeeper owns:

- run creation,
- user identity,
- workspace admission,
- policy posture,
- approval persistence,
- durable memory,
- task and result records,
- final judgment,
- dashboard/API representation.

The coding worker owns:

- inspecting files,
- editing files when allowed,
- running shell verification when allowed,
- reading git status/diff/log,
- producing execution events,
- producing verification results,
- returning final summary and artifacts.

FCLI specifically contributes the worker-plane implementation, not the Beekeeper product shell.

## Contract Objects

### CodingWorkerTask

The task object describes what Beekeeper is asking the worker to do.

Required fields:

| Field | Meaning |
|---|---|
| `schema_version` | Contract version. |
| `run_id` | Beekeeper run identifier. |
| `trace_id` | Trace identifier shared across events and artifacts. |
| `workspace_path` | Local repo or workspace root admitted by Beekeeper. |
| `user_request` | The natural-language request. |
| `provider_profile` | Named provider profile or credential reference, not raw secret values. |
| `allowed_side_effects` | Side-effect classes allowed without approval. |
| `approval_policy` | Which actions must request Beekeeper approval. |
| `limits` | Runtime, command, output, file, and retry limits. |

Optional fields:

| Field | Meaning |
|---|---|
| `initial_context` | Beekeeper-provided project or user context. |
| `target_files` | User-supplied files or paths to prioritize. |
| `verification_hint` | Suggested command or check, if known. |
| `memory_hints` | Approved memories relevant to this repo or user. |

### CodingWorkerEvent

Events are append-only worker observations. They feed the run timeline.

Required fields:

| Field | Meaning |
|---|---|
| `schema_version` | Contract version. |
| `run_id` | Beekeeper run identifier. |
| `trace_id` | Shared trace identifier. |
| `event_id` | Unique event identifier. |
| `timestamp` | Worker event time. |
| `kind` | Event type. |
| `message` | Short display text. |
| `payload` | Type-specific structured details. |

Event kinds should include:

- `run_started`
- `plan_created`
- `tool_started`
- `tool_finished`
- `file_read`
- `file_changed`
- `command_started`
- `command_finished`
- `git_status`
- `git_diff`
- `approval_requested`
- `verification_started`
- `verification_finished`
- `artifact_created`
- `run_failed`
- `run_completed`

### CodingWorkerApprovalRequest

Approval requests describe a side effect the worker cannot perform on its own.

Required fields:

| Field | Meaning |
|---|---|
| `review_id` | Beekeeper approval identifier or worker-generated request ID before persistence. |
| `run_id` | Run requesting approval. |
| `trace_id` | Shared trace identifier. |
| `action` | Requested action, such as `git_commit` or `network_access`. |
| `risk_tier` | Risk classification. |
| `reason` | Worker explanation. |
| `target` | Resource or command target. |
| `evidence` | Relevant file, diff, command, or policy evidence. |

V2 only defines this shape. V4 implements the deeper approval lifecycle.

### CodingWorkerResult

The final result should be small enough for dashboard and API use, but rich enough for audit.

Required fields:

| Field | Meaning |
|---|---|
| `schema_version` | Contract version. |
| `run_id` | Beekeeper run identifier. |
| `trace_id` | Shared trace identifier. |
| `status` | `completed`, `failed`, `blocked`, or `cancelled`. |
| `summary` | Human-readable final answer. |
| `changed_files` | Files changed by the worker. |
| `verification` | Structured verification result. |
| `artifacts` | Artifact references. |
| `approval_state` | Whether approvals were required, granted, denied, or still pending. |

Verification statuses:

- `passed`
- `failed`
- `unavailable`
- `not_attempted`

### CodingWorkerArtifact

Artifacts are durable evidence links, not arbitrary blobs hidden in worker logs.

Artifact kinds should include:

- `final_diff`
- `changed_file_summary`
- `command_output`
- `verification_report`
- `worker_trace`
- `approval_evidence`
- `final_summary`

## Side-Effect Model

V2 should define side effects before implementing enforcement.

Suggested categories:

| Category | Default posture |
|---|---|
| Read files in workspace | Allowed. |
| Search files in workspace | Allowed. |
| Edit files in workspace | Allowed only when task permits mutation. |
| Run verification commands | Allowed when command is workspace-confined and non-destructive. |
| Git status/diff/log/show | Allowed. |
| Git stage/commit | Approval required. |
| Git push/fetch/pull | Blocked or approval required later. |
| Network access | Blocked or approval required. |
| Destructive shell commands | Blocked or approval required. |
| Paths outside workspace | Blocked by default. |
| Secrets access | Blocked unless represented as approved secret refs. |

## Implementation Sequence

### Step 1: Draft JSON Schemas or Pydantic Models

Define the task, event, approval, result, artifact, side-effect, and verification objects.

Verification:

- Sample payloads validate.
- Invalid payloads fail with useful errors.

### Step 2: Map to Existing Beekeeper Concepts

Map new objects to existing `TaskEnvelope`, `ResultEnvelope`, approval records, trace IDs, and artifact records.

Verification:

- A coding-worker task can be represented from Beekeeper's current task model.
- A coding-worker result can be stored without losing trace or artifact links.

### Step 3: Create Fixtures

Create example fixtures for:

- read-only run,
- successful mutation run,
- failed verification,
- approval requested,
- blocked path escape,
- final result with diff artifact.

Verification:

- Fixtures pass schema validation.
- Fixtures are readable enough to become docs.

### Step 4: Define Compatibility Rules

Add a versioning policy.

Rules:

- Additive fields are allowed.
- Required field changes require a schema version bump.
- Event kind removals require a schema version bump.
- Unknown event kinds should be stored but not crash the timeline.

Verification:

- Contract tests cover unknown optional fields and unknown event kinds.

## Non-Goals

- Do not launch FCLI.
- Do not implement process management.
- Do not implement dashboard rendering.
- Do not implement approval resolution.
- Do not decide remote-worker hosting.

## Acceptance Bar

V2 is complete when Beekeeper can validate and store a complete fake coding-worker run from structured fixtures:

1. task accepted,
2. events ingested,
3. approval request represented,
4. result stored,
5. artifacts linked,
6. verification status visible from stored data.

