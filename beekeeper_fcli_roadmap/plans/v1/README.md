# V1: Personal Mode

V1 makes Beekeeper usable as a local personal agent manager before the FCLI bridge is introduced.

## Detailed Plan

- `01_personal_mode.md`

## V1 Goal

A user should be able to run Beekeeper locally, complete personal setup, select one provider profile, open the dashboard or chat surface, and understand that Beekeeper is ready to supervise local work.

## V1 Scope

- One local user.
- One default hive and Queen.
- Local storage by default.
- One configured provider profile.
- Simple setup and doctor flow.
- Personal-mode docs and status output.
- No requirement to understand orgs, tenancy, Temporal, Postgres, object storage, OPA, channels, or Worker Forge.

## V1 Exit Criteria

V1 is done when a fresh local setup can:

- create or load a personal profile,
- validate the configured model provider,
- start Beekeeper in local mode,
- open the dashboard or chat surface,
- show health/status without platform jargon,
- run a read-only doctor check,
- explain what is still not connected yet, especially the coding worker.

