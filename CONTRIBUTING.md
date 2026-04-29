# Contributing

Beekeeper is a research prototype maintained on personal time. Contributions are
welcome, but PRs and issues may sit unreviewed for a while.

## Useful contributions

- Reproducible bug reports with the command, payload, environment, and traceback.
- Small PRs that tighten policy gating, HITL behavior, Honeycomb trace quality,
  scheduler behavior, or documentation accuracy.
- Tests that capture current behavior before changing architecture.

## Before opening a PR

1. Keep the scope narrow.
2. Run `pytest` locally.
3. Update docs when you change support status, operational behavior, or public
   commands.
4. Be explicit about whether your change is prototype-only or moves something
   closer to the supported path.

## Project posture

This repository is not a production support channel. Stability, response times,
and compatibility are best-effort until the maturity model says otherwise.
