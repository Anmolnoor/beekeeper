"""Queen context: identity, capabilities, worker protocol, and response format.

The Queen reads this to know who she is, what she has, and how to communicate.

Markdown Agent Config (load order):
  1. ~/.beehive/agent/ (global: BEEHIVE.md, AGENTS.md, SOUL.md)
  2. Project root and parent dirs: BEEHIVE.md, AGENTS.md, SOUL.md
  3. .honeycomb/context/queen.md

- BEEHIVE.md: Project/hive description, setup
- AGENTS.md: Agent roles, capabilities, routing hints
- SOUL.md: Persona, tone, operational doctrine (supplements queen.soul.json)

Template variables in queen.md: {{intent}}, {{domain}}, {{worker_kind}}
"""
from __future__ import annotations

from pathlib import Path

from .prompt_templates import render_prompt

DEFAULT_QUEEN_CONTEXT = """# Queen Identity & Protocol

You are the Queen: the orchestration agent of this hive. You coordinate workers and respond to the user.

## Who You Are
- **Role**: Central orchestrator. You decide when to respond directly (Ollama) vs. delegate to workers.
- **Direct chat**: For simple conversation, you reply using your LLM (Ollama/Gemini) without involving workers.
- **Delegation**: For research, computation, or audits, you assign tasks to workers and synthesize their outputs.

## What You Have
- **Workers** (from the registry at .honeycomb/workers/registry.json):
  - **web_search**: Searches the web, gathers evidence, synthesizes answers. Use when: `use_web_search: true` or query needs web lookup.
  - **heavy_compute**: Numeric aggregation, simulations. Use when: `numbers` or `operation` in payload.
  - **audit**: Reviews and validates other workers' outputs. Used automatically for governance.
- **Ollama**: Your direct LLM. Default for simple chat.
- **Worker registry**: You pick workers by matching intent, payload triggers, and query keywords.

## How to Talk to Workers
Workers receive a **TaskEnvelope**:
```json
{{
  "task_type": "intent name",
  "worker_kind": "web_search|heavy_compute|audit",
  "payload": {{
    "query": "user question",
    "use_web_search": true,  // optional, for web_search
    "domains": ["example.com"],  // optional, for web_search
    "numbers": [1,2,3],  // for heavy_compute
    "operation": "sum"  // for heavy_compute
  }}
}}
```

Workers return a **ResultEnvelope** with `output` containing their response. For web_search: `output.assistant_reply` is the main text.

## How to Present Responses to the User
- **Direct chat**: Reply naturally, conversationally. Be helpful and concise.
- **After worker delegation**: Surface `assistant_reply` (or the main answer field) as the primary response. Optionally mention synthesis/evidence briefly.
- **Errors**: If a worker fails or Ollama is unreachable, explain clearly and suggest next steps (e.g. "Ollama is not reachable. Ensure it is running at BEEHIVE_OLLAMA_BASE_URL.").
"""

_CONTEXT_FILENAMES = ("BEEHIVE.md", "AGENTS.md", "SOUL.md")


def _read_file_safe(path: Path) -> str | None:
    """Read file content or return None on error."""
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None


def _load_from_dir(dir_path: Path) -> list[str]:
    """Load BEEHIVE.md, AGENTS.md, SOUL.md from a directory, in order. Returns list of non-empty contents."""
    parts: list[str] = []
    for name in _CONTEXT_FILENAMES:
        content = _read_file_safe(dir_path / name)
        if content:
            parts.append(content)
    return parts


def _parent_dirs(start: Path, max_depth: int = 10):
    """Yield start and its parent directories up to max_depth."""
    current = Path(start).resolve()
    seen: set[Path] = set()
    depth = 0
    while current and current != current.parent and depth < max_depth:
        if current in seen:
            break
        seen.add(current)
        yield current
        current = current.parent
        depth += 1


def load_queen_context(honeycomb_root: Path) -> str:
    """Load Queen context from multiple sources and merge.

    Search order:
      1. ~/.beehive/agent/ (BEEHIVE.md, AGENTS.md) - global defaults
      2. Project root and parent dirs: BEEHIVE.md, AGENTS.md
      3. .honeycomb/context/queen.md
      4. DEFAULT_QUEEN_CONTEXT if nothing found
    """
    parts: list[str] = []

    # 1. Global defaults from ~/.beehive/agent/
    home = Path.home()
    global_agent_dir = home / ".beehive" / "agent"
    if global_agent_dir.exists():
        for content in _load_from_dir(global_agent_dir):
            parts.append(content)

    # 2. Project-level: walk up from honeycomb root (or its parent if honeycomb_root is .honeycomb)
    search_root = Path(honeycomb_root).resolve()
    if search_root.name == ".honeycomb":
        search_root = search_root.parent
    for dir_path in _parent_dirs(search_root):
        for content in _load_from_dir(dir_path):
            parts.append(content)

    # 3. Local honeycomb context
    local_path = Path(honeycomb_root) / "context" / "queen.md"
    local_content = _read_file_safe(local_path)
    if local_content:
        parts.append(local_content)

    # 4. Default if nothing found
    if not parts:
        return DEFAULT_QUEEN_CONTEXT.strip()

    return "\n\n---\n\n".join(parts)


def render_queen_context(
    context: str,
    intent: str = "",
    domain: str = "",
    worker_kind: str = "",
) -> str:
    """Render Queen context with {{intent}}, {{domain}}, {{worker_kind}} placeholders."""
    return render_prompt(
        context,
        intent=intent,
        domain=domain,
        worker_kind=worker_kind,
    )


def ensure_queen_context_file(honeycomb_root: Path) -> Path:
    """Create queen.md if missing so users can edit it."""
    path = Path(honeycomb_root) / "context" / "queen.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_QUEEN_CONTEXT, encoding="utf-8")
    return path
