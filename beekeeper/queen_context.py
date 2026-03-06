"""Queen context: identity, capabilities, worker protocol, and response format.

The Queen reads this to know who she is, what she has, and how to communicate.

Markdown Agent Config (load order):
  1. ~/.beekeeper/agent/ (global: BEEKEEPER.md, AGENTS.md, SOUL.md)
  2. Project root and parent dirs: BEEKEEPER.md, AGENTS.md, SOUL.md
  3. .honeycomb/context/queen.md

- BEEKEEPER.md: Project/hive description, setup
- AGENTS.md: Agent roles, capabilities, routing hints
- SOUL.md: Persona, tone, operational doctrine (supplements queen.soul.json)

Template variables in queen.md: {{intent}}, {{domain}}, {{worker_kind}}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .prompt_templates import render_prompt
from .user_memory import ensure_memory_files, load_markdown_memory_snippets

DEFAULT_QUEEN_CONTEXT = """# Queen Identity & Protocol

You are the Queen: the orchestration agent of this hive. You coordinate workers and respond to the user.

## Who You Are
- **Role**: Central orchestrator. You decide when to respond directly vs. delegate to workers.
- **Direct chat**: For simple conversation, you reply using your LLM (Ollama/Gemini) without involving workers.
- **Delegation**: For research, computation, file operations, or audits you assign tasks to workers and synthesize their outputs.

## What You Have

### Built-in Workers
- **web_search**: Searches the web, gathers evidence, synthesizes answers.
  Use when: `use_web_search: true` or query needs web lookup / external sources.
- **heavy_compute**: Numeric aggregation, simulations.
  Use when: `numbers` or `operation` in payload.
- **audit**: Reviews and validates other workers' outputs. Used automatically for governance.

### Forged Worker (OS action executor)
- **forged**: Handles any intent that has no dedicated worker.
  It asks the LLM to decide the right action, then **executes it for real**.
  Supported actions it can perform:
  - `write_file` — create or overwrite a file on disk
  - `append_file` — append text to an existing file
  - `delete_file` — delete a file from disk
  - `make_dir` — create a directory (including parent dirs)
  - `answer` — reply with plain text (for questions, research summaries, etc.)

  Use forged when the user asks to: **create, write, save, append to, delete a file**, **make a directory**, or anything else not covered by a built-in worker.

### Auto-Spawning
When no worker matches an intent, you automatically spawn and hot-load a new custom worker for it. The spawned worker is verified before use. If the generated code fails, you self-heal (up to 2 fix attempts) and fall back to the forged worker.

{{available_workers}}

## Routing Decision Guide
| User wants to… | Route to |
|---|---|
| Search the web / look something up | web_search |
| Do math / aggregate numbers | heavy_compute |
| Create / write / save a file | forged |
| Append to a file | forged |
| Delete a file | forged |
| Make a directory | forged |
| Answer a general question | direct chat or forged (answer action) |
| Audit / validate results | audit |

## How Workers Return Results
Workers return a **ResultEnvelope** with `output.assistant_reply` as the main text.
For file operations the reply confirms what was done (e.g. "Created file: hello.txt (11 chars)").

## How to Present Responses to the User
- **Direct chat**: Reply naturally, conversationally. Be helpful and concise.
- **After worker delegation**: Surface `assistant_reply` as the primary response.
- **File operations**: Confirm the action ("Created hello.txt", "Appended 3 lines to log.txt", etc.).
- **Errors**: If a worker fails or Ollama is unreachable, explain clearly and suggest next steps.
"""

_DEFAULT_CONTEXT_HASH = "v3-2026-03-04"  # bump this when DEFAULT_QUEEN_CONTEXT changes

_CONTEXT_FILENAMES = ("BEEKEEPER.md", "AGENTS.md", "SOUL.md")


def _read_file_safe(path: Path) -> str | None:
    """Read file content or return None on error."""
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None


def _load_from_dir(dir_path: Path) -> list[str]:
    """Load BEEKEEPER.md, AGENTS.md, SOUL.md from a directory, in order. Returns list of non-empty contents."""
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
      1. ~/.beekeeper/agent/ (BEEKEEPER.md, AGENTS.md) - global defaults
      2. Project root and parent dirs: BEEKEEPER.md, AGENTS.md
      3. .honeycomb/context/queen.md
      4. DEFAULT_QUEEN_CONTEXT if nothing found
    """
    parts: list[str] = []

    # 1. Global defaults from ~/.beekeeper/agent/
    home = Path.home()
    global_agent_dir = home / ".beekeeper" / "agent"
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
    local_context_dir = Path(honeycomb_root) / "context"
    for local_name in ("queen.md", "QUEEN_CONTEXT.md", "MEMORY_POLICY.md"):
        local_content = _read_file_safe(local_context_dir / local_name)
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
    available_workers: str = "",
) -> str:
    """Render Queen context with {{intent}}, {{domain}}, {{worker_kind}}, {{available_workers}} placeholders."""
    rendered = render_prompt(context, intent=intent, domain=domain, worker_kind=worker_kind)
    if available_workers:
        if "{{available_workers}}" in rendered:
            rendered = rendered.replace("{{available_workers}}", available_workers)
        else:
            rendered = rendered + "\n\n" + available_workers
    else:
        # Remove the placeholder if no workers to inject
        rendered = rendered.replace("{{available_workers}}", "")
    return rendered.strip()


def ensure_queen_context_file(honeycomb_root: Path) -> Path:
    """Create or refresh queen.md.

    Writes the default if missing. Force-refreshes if the file was auto-generated
    with an older default (detected by absence of the version hash comment).
    User-edited files that contain the hash comment are left untouched.
    """
    path = Path(honeycomb_root) / "context" / "queen.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_write = not path.exists()
    if not needs_write:
        try:
            existing = path.read_text(encoding="utf-8")
            # Refresh if it's a stale auto-generated file (missing the version marker)
            if _DEFAULT_CONTEXT_HASH not in existing and "# Queen Context Override" not in existing:
                needs_write = True
        except OSError:
            needs_write = True
    if needs_write:
        path.write_text(DEFAULT_QUEEN_CONTEXT + f"\n<!-- {_DEFAULT_CONTEXT_HASH} -->\n", encoding="utf-8")
    alt = Path(honeycomb_root) / "context" / "QUEEN_CONTEXT.md"
    if not alt.exists():
        alt.write_text(
            "# Queen Context Override\n\nAdd project-specific behavior rules here.\n",
            encoding="utf-8",
        )
    ensure_memory_files(honeycomb_root)
    return path


def normalize_messages(messages: list[dict[str, Any]], max_messages: int = 24) -> list[dict[str, str]]:
    """Normalize and trim chat messages while preserving recent context."""
    normalized: list[dict[str, str]] = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "user")).strip() or "user"
        content = str(m.get("content", "")).strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content[:4000]})
    if len(normalized) <= max_messages:
        return normalized
    return normalized[-max_messages:]


def build_context_bundle(
    *,
    query: str,
    payload: dict[str, Any],
    honeycomb: Any,
    honeycomb_root: Path,
) -> dict[str, Any]:
    """Create one context bundle for direct and delegated execution paths."""
    messages = normalize_messages(payload.get("messages") or [])
    user_memories = payload.get("user_memories") or []
    if not isinstance(user_memories, list):
        user_memories = []
    semantic_hits = honeycomb.semantic_search_with_content(query, limit=6) if query else []
    semantic_text = [text for _, text in semantic_hits if text and text.strip()]
    md_hits = load_markdown_memory_snippets(honeycomb_root, query, limit=6) if query else []
    bundle = {
        "messages": messages,
        "user_memories": user_memories[:18],
        "semantic_context": semantic_text[:6],
        "md_memory_context": md_hits[:6],
        "diagnostics": {
            "messages_count": len(messages),
            "user_memories_count": len(user_memories),
            "semantic_hits_count": len(semantic_text),
            "md_hits_count": len(md_hits),
        },
    }
    return bundle
