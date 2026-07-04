# Beekeeper Personal V1 Implementation Plan

Date: 2026-06-08

## Objective

Implement the V1 personal-mode slice in the real Beekeeper app. V1 makes Beekeeper usable locally with one owner, one hidden default workspace, one Queen, one provider profile, local storage, and honest status output.

## Scope

- `beekeeper setup --personal`
- `beekeeper doctor --personal`
- `beekeeper status --personal`
- `beekeeper start --personal`
- `/api/personal/status`
- Dashboard card rendering the same personal status payload

## Explicit Non-Goals

These remain later roadmap work and must not be faked in V1:

- executable coding worker
- FCLI bridge
- coding-worker task/event/result contract
- workspace mutation policy
- final diff/artifact flow
- coding-worker smoke path

V1 reports `coding_worker` as `planned/not connected`.

## Implementation Steps

1. Add a canonical personal-mode status module.
2. Wire CLI setup and personal doctor/status commands.
3. Add an API endpoint for dashboard parity.
4. Update the dashboard surface.

## Acceptance Bar

A fresh local run can create or load the personal profile, validate the configured provider, show ready/blocking status without platform jargon, expose the dashboard status payload, and clearly explain that coding-worker supervision is not connected until V2/V3.
