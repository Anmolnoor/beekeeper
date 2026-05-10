# X (Twitter) launch thread — Beekeeper

> **Style:** lowercase, conversational, no LinkedIn voice.
> **Each tweet ≤ 280 chars** — counts noted below.
> **Media:** tweet 1 gets the social preview. Tweet 5 should get a short screen
> recording (terminal cast or web UI) of a tool call being gated → HITL prompt
> → executed.

---

## 1/9 — Hook (270 chars)

shipped: open-sourced beekeeper, a multi-agent runtime where every tool call hits a policy gate before it runs. queen plans, workers execute, honeycomb records every decision so you can replay it.

repo + write-up + why i'm gating contributions from day one ↓

## 2/9 — The problem (266 chars)

every agent framework i tried treated tool execution as free. the model "decides" → the tool runs. one prompt injection or one bad cot = unbounded blast radius. that's fine for demos. it's not fine for anything you'd put in front of real users or real data.

## 3/9 — The shape (276 chars)

beekeeper inverts that. tool calls aren't free. every call goes:

  registry → guardrails (pii / domain allowlist / quotas) → optional HITL → execute

the model never touches tools directly. there's a buffer. that buffer is the entire point.

## 4/9 — The trace (252 chars)

honeycomb is an append-only event log. every queen decision, every worker spawn, every tool call, every guardrail verdict, every HITL outcome — written, replayable, auditable.

if something goes wrong, you can replay the run. nothing is implicit.

## 5/9 — Demo (240 chars)

[short video: terminal showing `beekeeper run --query "..."` → queen plans → tool call → guardrail blocks → HITL prompt → human approves → tool executes → honeycomb event timeline]

this is the default path. not an opt-in.

## 6/9 — The contribution gate (276 chars)

the same AI that makes this fun makes slop PRs trivial. every public repo is drowning. so beekeeper ships with badlogic/pi-mono's gate ported in: issues + PRs from non-allowlisted accounts auto-close. maintainers approve real contributors with `lgtm`.

## 7/9 — Why that's not hostile (270 chars)

it's a buffer. the maintainer reviews the tracker on a schedule instead of in real-time panic. the bar is low for being approved (one good issue). the bar is high for getting through the gate by spamming. that asymmetry is the point.

## 8/9 — Roadmap (256 chars)

next:
- worker forge sandboxing + provenance gates
- mcp client polish (resources + prompts, not just tools)
- richer honeycomb queries (replay + diff between runs)
- better postgres + temporal production path docs

issues welcome via the gate. discussions are open.

## 9/9 — Links (220 chars)

repo: github.com/Anmolnoor/beekeeper
deep write-up: <BLOG_URL>

apache 2.0. python 3.10+.

if governed agents, audit trails, or HITL on tool execution is your problem space, ⭐ helps.

(credits: badlogic/pi-mono for the gate.)
