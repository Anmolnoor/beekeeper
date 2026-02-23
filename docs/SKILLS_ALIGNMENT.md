# Agent Skills Standard Alignment

Beekeeper `SkillProfile` aligns with the Agent Skills standard (Cursor/Codex SKILL.md format) for consistent skill definition across agent platforms.

## Alignment

| Standard Field | SkillProfile | Notes |
|----------------|--------------|-------|
| `name` | `name` | Human-readable display name |
| `description` | `description` | Third-person; includes WHAT and WHEN |
| When to use | `when_to_use` | Trigger scenarios, keywords |
| ID/slug | `skill_profile_id` | e.g. `skill.research.web` |

## Description Guidelines

Per Agent Skills standard:
- **Third person**: "Searches the web..." not "I search the web"
- **WHAT**: Specific capabilities
- **WHEN**: Trigger scenarios or keywords

Example:
```python
SkillProfile(
    skill_profile_id="skill.research.web",
    name="Web Research",
    description="Searches the web, gathers evidence, and synthesizes answers. Use when user query needs web lookup, external sources, or research.",
    when_to_use="use_web_search in payload, query mentions research/lookup/find, domains specified",
    ...
)
```

## Adding New Skills

When defining a skill in `queen.py` or a plugin:

1. **skill_profile_id**: `skill.<domain>.<kind>` (e.g. `skill.research.web`)
2. **name**: Human-readable (e.g. "Web Research")
3. **description**: Third-person, WHAT + WHEN
4. **when_to_use**: Comma-separated triggers for routing

See [BUILDING_NEW_WORKERS.md](BUILDING_NEW_WORKERS.md) for full worker/skill registration.
