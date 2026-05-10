# LinkedIn launch post — Beekeeper

> **Image to attach:** the social-preview PNG (the same one set as GitHub repo
> social preview). Aim for 1200×628.
>
> **Length:** ~1,500 chars. LinkedIn's "see more" cut-off is around 210 chars,
> so the hook line + the next sentence have to do the work.

---

I'm open-sourcing Beekeeper today.

It's a governed multi-agent runtime I've been building — a Queen that plans, ephemeral Workers that execute, and a policy layer that mediates every single tool call before it runs.

The thing I kept hitting in every other agent framework I tried: the model is allowed to call tools directly, with no buffer between "the model decided" and "the tool executed." One prompt-injection or one bad chain-of-thought = unbounded blast radius.

Beekeeper takes the opposite stance. Tool calls aren't free. Every one goes through a registry → guardrails → optional human-in-the-loop, and every decision is recorded in an append-only event log (Honeycomb) you can replay later. Nothing happens that you can't audit afterwards.

Why I'm gating contributions from day one: the same AI that makes building this fun also makes "low-effort PR and slop-issue" generation trivial. Every public OSS maintainer is now drowning in polished, plausible, wrong submissions. So Beekeeper ships with a contribution gate adapted from badlogic/pi-mono — issues and PRs from non-allowlisted contributors auto-close. Maintainers approve real contributors with a single comment. It's not hostile; it's a buffer that lets the tracker be reviewed on a schedule instead of in real-time panic.

If governed agents, audit trails, or HITL on tool execution is your problem space, I'd love a star, a Discussion, or a thoughtful issue.

Repo: https://github.com/Anmolnoor/beekeeper
Deeper write-up on my site: <BLOG_URL>

Apache 2.0. Python 3.10+.

#AI #Agents #OpenSource #Python #LLM
