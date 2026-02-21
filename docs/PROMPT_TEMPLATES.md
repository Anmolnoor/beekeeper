# Prompt Templates

Beehive supports loadable prompt templates so you can customize prompts without editing source code.

## Location

Place template files under:

```
.honeycomb/prompts/
├── user_memory_extract.md   # User memory extraction (default if absent)
├── your_custom.md           # Custom templates
└── your_custom.txt
```

Supported extensions: `.md`, `.txt`.

## Built-in Templates

| Template ID | Purpose | Placeholders |
|-------------|---------|--------------|
| `user_memory_extract` | Extract facts from conversation for user memory | `{user_msg}`, `{assistant_reply}` |

## Customizing user_memory_extract

Create `.honeycomb/prompts/user_memory_extract.md`:

```markdown
From this conversation, extract 1-5 facts about the user. Focus on:
- Project and goals
- Tools and stack
- Preferences

User: {user_msg}
Assistant: {assistant_reply}

Output one fact per line. If nothing to remember, output: NONE
```

The user memory pipeline will use this instead of the built-in default.

## Creating Custom Templates

1. Create a file: `.honeycomb/prompts/my_template.md`
2. Use `{placeholder}` for variables
3. Load in your code:

```python
from beehive.prompt_templates import load_prompt_template, render_prompt

template = load_prompt_template(Path(".honeycomb"), "my_template")
text = render_prompt(template, foo="value", bar="other")
```

## Environment

Templates are loaded relative to `BEEHIVE_HONEYCOMB_ROOT` (default `.honeycomb`). The Queen and chat flows use the honeycomb root from their config.
