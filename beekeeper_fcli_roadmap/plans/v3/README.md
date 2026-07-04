# V3: FCLI Bridge

V3 makes the coding-worker contract executable.

## Detailed Plan

- `03_fcli_bridge.md`

## V3 Goal

Beekeeper should be able to start or call an FCLI-grade coding worker, consume structured events, and receive a normalized result without parsing terminal prose.

## V3 Scope

- Process bridge first.
- Package/import bridge later if it proves cleaner.
- NDJSON event consumption.
- Workspace admission.
- Run lifecycle mapping.
- Worker timeout, cancellation, and failure handling.
- Read-only run first, mutation run second.

## V3 Exit Criteria

V3 is done when Beekeeper can dispatch a tiny local coding task, receive structured worker events, store the result, and show whether verification passed or failed.

