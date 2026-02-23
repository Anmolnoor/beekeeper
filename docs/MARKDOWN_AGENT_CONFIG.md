# Markdown Agent Config (BEEKEEPER.md, AGENTS.md, SOUL.md)

Beekeeper loads agent context from markdown files in a well-defined order. Place these in your project root, `~/.beekeeper/agent/` (global defaults), or `.honeycomb/context/`.

## Load Order

1. **~/.beekeeper/agent/** (global defaults)
2. **Project root and parent dirs** (walking up from honeycomb root)
3. **.honeycomb/context/queen.md**

Each directory is searched for `BEEKEEPER.md`, `AGENTS.md`, `SOUL.md` in that order. Files are concatenated with `---` separators. Missing files are skipped.

## File Purposes

| File | Purpose |
|------|---------|
| **BEEKEEPER.md** | Project/hive description, setup, environment notes |
| **AGENTS.md** | Agent roles, capabilities, routing hints, multi-agent layout |
| **SOUL.md** | Persona, tone, operational doctrine. Supplements `queen.soul.json` traits |

## Examples

### BEEKEEPER.md
```markdown
# Acme Ops Hive

This hive handles internal operations and support. Workers have access to
docs.python.org, github.com, and our internal runbooks.
```

### AGENTS.md
```markdown
# Agents

## Queen
Central orchestrator. Routes to web_search for research, heavy_compute for numeric tasks.

## Workers
- web_search: Use when query needs external sources
- heavy_compute: Use when payload has `numbers` or `operation`
- audit: Auto-invoked for governance
```

### SOUL.md
```markdown
# Queen Soul

- Constitutional: helpful, honest, harmless
- Explicit uncertainty and confidence reporting
- Policy-first; escalate high-risk actions to humans
- Deterministic, evidence-backed orchestration
```

## Relation to queen.soul.json

- **queen.soul.json**: Structured `SoulProfile` (tone, risk_appetite, traits, escalation_thresholds)
- **SOUL.md**: Free-form markdown doctrine, merged into Queen context

Both are used. The JSON drives runtime behavior; SOUL.md adds narrative context for the LLM.

## .honeycomb/context/queen.md

Project-specific override. Created by `beekeeper` init if missing. Takes precedence over project-level BEEKEEPER.md/AGENTS.md/SOUL.md for local overrides.
