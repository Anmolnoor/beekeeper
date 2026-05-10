# Contributing to Beekeeper

This guide saves both sides time. Read it before opening an issue or PR.

## The One Rule

**You must understand your code.** If you cannot explain what your changes do and how they interact with the rest of the system — Queen routing, the tool registry, guardrails, Honeycomb tracing — your PR will be closed.

Using AI to write code is fine. Submitting AI-generated slop you have not read is not.

If you use a coding agent locally, run it from the repo root so it picks up the root `AGENTS.md` automatically. Your agent must follow the rules in that file.

## Contribution Gate

All issues and PRs from new contributors are auto-closed by default. This is intentional. Beekeeper is a small project and the maintainer cannot keep up with agent-generated noise in real time. The gate creates a buffer so issues are reviewed on a maintainer's schedule, not the tracker's.

Approval happens through maintainer comments on issues:

- `lgtmi` — your future **issues** will not be auto-closed.
- `lgtm` — your future **issues and PRs** will not be auto-closed.

`lgtmi` does not grant rights to submit PRs. Only `lgtm` grants rights to submit PRs.

Issues opened **Friday through Sunday (UTC)** are auto-closed and not part of the review queue. If a problem is urgent, that's not what the issue tracker is for — open a Discussion or wait until Monday.

Maintainers review auto-closed issues and reopen the ones that meet the quality bar below. Issues that don't meet the bar will not be reopened and will not get a reply.

## Quality Bar for Issues

Use one of the GitHub issue templates. Blank issues are disabled.

Keep issues short, concrete, and worth reading.

- Concise — if it doesn't fit on one screen, it's too long.
- Written in your own voice. Not a wall of model output.
- State the bug or request clearly.
- Explain why it matters.
- If you want to implement the change yourself, say so.

If the issue is real and well-written, a maintainer may reopen it, reply `lgtmi`, or reply `lgtm`.

## Blocking

If you ignore this document twice, or if you spam the tracker with agent-generated issues, your GitHub account will be permanently blocked from this repository.

If you send a large volume of issues through automation, your GitHub account will be permanently blocked. No takesies-backsies.

## Before Submitting a PR

Do not open a PR unless you have already been approved with `lgtm`.

Before submitting a PR:

```bash
pip install -e .
pip install pytest ruff
ruff check .
pytest tests/
```

Both must pass.

Do not edit `CHANGELOG.md`. Changelog entries are added by maintainers at release time.

If you are adding a new LLM provider in `beekeeper/llm_provider.py` or a new worker kind in `beekeeper/`, see the root `AGENTS.md` for required tests and contracts.

## Philosophy

Beekeeper's core is small on purpose:

- **Queen** plans and routes.
- **Workers** execute, ephemerally.
- **Honeycomb** records every event.
- **Tool Registry + Guardrails** mediate every tool call.

If your feature does not belong in that core, it belongs in an extension or a custom worker — not in the runtime. PRs that bloat the core (configurability nobody asked for, abstractions for hypothetical futures, "improvements" to adjacent code) will be rejected.

Small, surgical changes. Match existing style.

## Questions

Open a [Discussion](https://github.com/Anmolnoor/beekeeper/discussions) — that's the unfiltered place. The issue tracker is gated on purpose.

## FAQ

### Why are new issues and PRs auto-closed?

Because the alternative is silent maintainer burnout. Beekeeper receives more inbound than the maintainer can responsibly review in real time, and most of it is automated, polished, and wrong. Auto-closing creates a buffer so the tracker can be reviewed on a schedule and the issues that meet the bar can be reopened.

### Why are weekend issues not reviewed?

The maintainer needs time away from the tracker. Issues opened Friday through Sunday (UTC) are auto-closed and are not part of the Monday review queue. Discussions are still open if you need to talk something through.

### Why do some issues get no reply?

A reply is maintenance work. Low-signal issues, unclear reports, duplicates, and issues that don't follow this guide may be closed without discussion. This keeps time available for reproducible bugs, thoughtful requests, and contributors who have done the work.

### Why not let AI triage everything?

AI helps spot duplicates and missing information. It is not trusted to make final maintainer decisions. Polished AI-generated reports can still be wrong, misleading, or expensive to investigate. Human review is the final gate.

### Is this hostile to contributors?

No. Short, concrete, reproducible issues are welcome. Thoughtful PRs from approved contributors are welcome. Automated slop and large volumes of low-effort reports are not. The gate is a guardrail against burnout, not a wall against people.

---

The contribution gate workflow is adapted from [`badlogic/pi-mono`](https://github.com/badlogic/pi-mono), which faces the same problem and solved it well.
