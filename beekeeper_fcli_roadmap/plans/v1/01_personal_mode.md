# 01: Personal Mode Plan

Date: 2026-06-08

## Context

Beekeeper already has many platform pieces: Queen orchestration, workers, Honeycomb storage, approvals, scheduling, MCP paths, channels, runtime modes, and production-oriented infrastructure. That is useful long term, but it is too much surface area for the first personal product.

The V1 problem is not "can Beekeeper do everything?" The problem is:

> Can a person start Beekeeper locally and immediately understand how to use it as their personal agent manager?

Before coding-worker integration, Beekeeper needs a narrow personal-mode baseline. This gives every later version a stable control-plane shell.

## Desired User Outcome

The user should be able to:

1. Run one setup command.
2. Pick or confirm a provider profile.
3. Start Beekeeper locally.
4. Open the dashboard or chat surface.
5. See a clear status page showing what works and what is pending.
6. Avoid learning Beekeeper's full enterprise architecture just to use the personal workflow.

## Assumptions

- Personal mode is local-first.
- The first user is the owner/operator.
- Local filesystem storage is acceptable for V1.
- Existing org, hive, Queen, and user concepts can remain internally, but should be hidden behind defaults.
- Docker, Temporal, Postgres, S3, OPA, OpenTelemetry, and broad channel setup are not required to prove V1.
- The coding worker is not implemented in this version. V1 prepares the control-plane shell that later versions plug into.

## Goals

- Add or formalize a personal setup path.
- Hide multi-tenant and production vocabulary from the default user flow.
- Create stable defaults for one user, one hive, one Queen, local storage, and one provider.
- Make doctor/status output explain readiness in human terms.
- Keep the code and docs honest about what is not implemented yet.

## Non-Goals

- No FCLI execution bridge.
- No coding-worker package.
- No Worker Forge promotion.
- No automatic git operations.
- No broad channel setup.
- No production deployment story.
- No frontend rewrite.

## Personal Defaults

V1 should make these decisions automatically unless the user overrides them:

| Area | Default |
|---|---|
| User | One local owner user. |
| Hive | One default personal hive. |
| Queen | One default Queen attached to that hive. |
| Storage | Local storage. |
| Runtime | Inline/local where possible. |
| Provider | One explicitly configured provider profile. |
| Channels | None required. |
| Workers | Existing Beekeeper workers only; coding worker shown as not connected. |
| Approvals | Enabled, but only for existing Beekeeper actions until V4 expands the policy model. |

## Setup Flow

The target flow is:

```text
beekeeper setup --personal
beekeeper doctor
beekeeper start
```

The exact command names can follow existing CLI conventions, but the product flow should stay this simple.

The setup command should:

1. Create or update a personal profile.
2. Confirm local storage location.
3. Confirm provider role and model.
4. Validate required secrets without printing them.
5. Create default hive and Queen records if missing.
6. Write a status summary.

The doctor command should:

1. Validate runtime config.
2. Validate provider connectivity.
3. Validate local storage paths.
4. Validate dashboard/API reachability where applicable.
5. Report missing optional features separately from broken required features.

## Dashboard and Chat Baseline

The V1 dashboard does not need to be the final product UI. It needs to be honest and scannable.

Required panels or sections:

- **Status**: ready, degraded, or blocked.
- **Provider**: selected provider role, model, and connection health.
- **Queen**: active personal Queen and profile.
- **Workers**: existing workers, with `coding_worker` marked as planned/not connected.
- **Approvals**: pending approval count.
- **Memory**: whether durable memory is enabled and where it lives.

Chat can remain simple. The important V1 behavior is that chat and dashboard agree about system readiness.

## Implementation Sequence

### Step 1: Inventory Current Setup

Review the existing setup, doctor, runtime validation, dashboard setup page, and environment docs.

Verification:

- List the current setup entrypoints.
- List which settings are required for local personal use.
- List which settings are production-only or optional.

### Step 2: Define Personal Profile Defaults

Create a small personal-mode profile that maps to the existing internal objects.

Verification:

- A personal profile can be represented without requiring the user to manually create org, hive, Queen, channel, queue, or production state.

### Step 3: Add Setup Path

Add or formalize the personal setup command using existing CLI patterns.

Verification:

- Running setup twice is safe.
- Missing provider settings produce a specific next step.
- Secrets are never printed.

### Step 4: Tighten Doctor Output

Separate required checks from optional future checks.

Verification:

- A valid local setup reports ready.
- Missing optional production services do not make personal mode look broken.
- A broken provider reports the exact failing check.

### Step 5: Update Status Surface

Make dashboard and CLI status show the same readiness categories.

Verification:

- Dashboard and CLI agree on provider, storage, Queen, worker, and approval status.

## Acceptance Tests

At minimum, V1 should include tests or manual verification for:

- fresh personal setup,
- repeat setup idempotency,
- missing provider credentials,
- invalid provider endpoint,
- valid provider endpoint,
- local storage path creation,
- dashboard status rendering,
- doctor output for required vs optional checks.

## Risks

| Risk | Control |
|---|---|
| Personal mode becomes a second config system | Keep it as defaults over existing config, not a separate architecture. |
| Hidden platform objects become confusing later | Expose advanced settings only after the basic flow is working. |
| Doctor stays too noisy | Separate required, optional, and future checks. |
| V1 overpromises coding work | Show coding-worker status as planned until V2 and V3 are complete. |

## Exit Criteria

V1 is complete when a fresh user can start Beekeeper locally, validate provider health, open the status surface, and understand that the personal manager is ready for future coding-worker supervision.

