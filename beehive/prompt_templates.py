"""Prompt templates: loadable text templates with {placeholder} and {{var}} substitution.

Available variables:
- Single-brace (str.format): {user_msg}, {assistant_reply} (user_memory_extract)
- Double-brace (request context): {{intent}}, {{domain}}, {{worker_kind}}

Place templates in .honeycomb/prompts/<id>.md or .txt.
"""
from __future__ import annotations

import re
from pathlib import Path


def load_prompt_template(
    honeycomb_root: Path,
    template_id: str,
) -> str:
    """
    Load a prompt template by ID.

    Search order:
      1. .honeycomb/prompts/{template_id}.md
      2. .honeycomb/prompts/{template_id}.txt
      3. Built-in defaults for known ids

    Returns the raw template string (caller does .format() or substitute).
    """
    root = Path(honeycomb_root).resolve()
    if root.name == ".honeycomb":
        prompts_dir = root / "prompts"
    else:
        prompts_dir = root / ".honeycomb" / "prompts"

    for ext in (".md", ".txt"):
        path = prompts_dir / f"{template_id}{ext}"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()

    # Built-in defaults
    if template_id == "user_memory_extract":
        return _DEFAULT_USER_MEMORY_EXTRACT.strip()
    if template_id == "queen_system":
        return ""  # Queen uses queen_context, not this

    raise FileNotFoundError(f"Prompt template not found: {template_id}")


def render_prompt(
    template: str,
    **kwargs: str | None,
) -> str:
    """
    Render a template by substituting placeholders with kwargs.

    - {{var}}: Double braces for intent, domain, worker_kind (substituted first; missing -> "").
    - {var}: Single braces for known keys (e.g. {user_msg}, {assistant_reply}); missing -> KeyError.

    Uses explicit replacement instead of str.format() so JSON and other literal braces
    in templates (e.g. TaskEnvelope examples) are not interpreted as format placeholders.
    """
    safe = {k: (v if v is not None else "") for k, v in kwargs.items()}
    # 1. Replace double-brace {{var}}
    for m in re.finditer(r"\{\{(\w+)\}\}", template):
        key = m.group(1)
        template = template.replace(m.group(0), str(safe.get(key, "")))
    # 2. Replace single-brace {var} only for known keys (avoids KeyError on JSON braces)
    for key, val in safe.items():
        placeholder = "{" + key + "}"
        if placeholder in template:
            template = template.replace(placeholder, str(val))
    return template


_DEFAULT_USER_MEMORY_EXTRACT = """From this brief conversation, extract 1-3 factual statements about the user that would help future responses. Focus on:
- What they are working on or their current project
- Preferences, tools, or technologies they use
- Important context about them or their goals

User: {user_msg}
Assistant: {assistant_reply}

Output ONLY the statements, one per line. No numbering or bullets. If nothing worth remembering, output exactly: NONE"""
