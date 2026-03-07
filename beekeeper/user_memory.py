"""User memory: extract and persist critical info from conversations for context over time."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .worker import WebSearchWorker


def _make_extractor_llm() -> Callable[[str], str | None]:
    """Build a callable that uses the configured LLM for extraction."""
    provider = (os.getenv("BEEKEEPER_LLM_PROVIDER") or "openai").strip().lower()
    providers = (os.getenv("BEEKEEPER_LLM_PROVIDERS") or "ollama,gemini,openai").strip()
    base_url = (os.getenv("BEEKEEPER_OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
    model = os.getenv("BEEKEEPER_OLLAMA_MODEL") or "catsarethebest/qwen2.5-N2:1.5b"
    timeout = max(5, int(os.getenv("BEEKEEPER_OLLAMA_TIMEOUT_SECONDS", "120")))
    gemini_key = (os.getenv("BEEKEEPER_GEMINI_API_KEY") or "").strip()
    gemini_model = os.getenv("BEEKEEPER_GEMINI_MODEL") or "gemini-1.5-flash"
    gemini_timeout = max(5, int(os.getenv("BEEKEEPER_GEMINI_TIMEOUT_SECONDS", "120")))

    worker = WebSearchWorker(
        llm_provider=provider,
        llm_providers=providers,
        ollama_base_url=base_url,
        ollama_model=model,
        ollama_timeout_seconds=timeout,
        gemini_api_key=gemini_key,
        gemini_model=gemini_model,
        gemini_timeout_seconds=gemini_timeout,
        searxng_base_url="http://localhost:8080",
    )

    def _call(prompt: str) -> str | None:
        reply, _ = worker._assistant_reply(prompt)
        return reply

    return _call


EXTRACT_PROMPT = """From this brief conversation, extract 1-3 factual statements about the user that would help future responses. Focus on:
- What they are working on or their current project
- Preferences, tools, or technologies they use
- Important context about them or their goals

User: {user_msg}
Assistant: {assistant_reply}

Output ONLY the statements, one per line. No numbering or bullets. If nothing worth remembering, output exactly: NONE"""


def _get_extract_template(honeycomb_root: str | Path | None = None) -> str:
    """Get user memory extraction template; custom from .honeycomb/prompts if present."""
    if honeycomb_root is not None:
        try:
            from .prompt_templates import load_prompt_template
            return load_prompt_template(Path(honeycomb_root), "user_memory_extract")
        except FileNotFoundError:
            pass
    return EXTRACT_PROMPT


def extract_memories(
    user_msg: str,
    assistant_reply: str,
    honeycomb_root: str | Path | None = None,
) -> list[str]:
    """
    Use LLM to extract key facts from a conversation turn.
    Returns a list of memory strings to persist, or empty list if extraction fails or finds nothing.
    """
    if not (user_msg or assistant_reply):
        return []
    try:
        llm = _make_extractor_llm()
        template = _get_extract_template(honeycomb_root)
        prompt = template.format(
            user_msg=(user_msg or "")[:500],
            assistant_reply=(assistant_reply or "")[:800],
        )
        out = llm(prompt)
        if not out or not out.strip():
            return []
        first = out.strip().split("\n")[0].strip().upper()
        if first == "NONE":
            return []
        lines = [ln.strip() for ln in out.strip().split("\n") if ln.strip() and len(ln.strip()) > 10]
        return lines[:5]  # cap at 5 memories per exchange
    except Exception:
        return []


def extract_and_save_queen_memories(
    observation: str,
    honeycomb: "Any",  # HoneycombStore — avoid circular import
    tags: list[str] | None = None,
    honeycomb_root: "str | Path | None" = None,
) -> list[str]:
    """
    Queen proactively extracts memories from any observation and saves them.

    Unlike ``extract_memories`` (which needs a user/assistant pair), this
    function works on a single observation string — e.g. the output of an
    action, a task result, or a web-search synthesis.

    Returns the list of memory_ids that were persisted (empty if nothing
    worth remembering was found).
    """
    if not observation or not observation.strip():
        return []
    try:
        llm = _make_extractor_llm()
        template = _get_extract_template(honeycomb_root)
        # Re-use the same template with observation in both slots
        prompt = template.format(
            user_msg="(Queen's autonomous observation)",
            assistant_reply=(observation or "")[:800],
        )
        out = llm(prompt)
        if not out or not out.strip():
            return []
        first = out.strip().split("\n")[0].strip().upper()
        if first == "NONE":
            return []
        lines = [ln.strip() for ln in out.strip().split("\n") if ln.strip() and len(ln.strip()) > 10]
        snippets = lines[:5]
        saved_ids: list[str] = []
        for snippet in snippets:
            mid = honeycomb.write_queen_memory(
                snippet,
                source="queen_auto_extract",
                tags=tags or ["auto"],
            )
            saved_ids.append(mid)
        return saved_ids
    except Exception:
        return []


def ensure_memory_files(honeycomb_root: str | Path) -> dict[str, Path]:
    """Ensure markdown memory/config files exist for durable context."""
    root = Path(honeycomb_root)
    memory_dir = root / "memory"
    context_dir = root / "context"
    memory_dir.mkdir(parents=True, exist_ok=True)
    context_dir.mkdir(parents=True, exist_ok=True)
    memory_path = memory_dir / "MEMORY.md"
    policy_path = context_dir / "MEMORY_POLICY.md"
    queen_ctx_path = context_dir / "QUEEN_CONTEXT.md"
    if not memory_path.exists():
        memory_path.write_text("# Durable Memory\n\n## Profile Facts\n\n## Project Preferences\n", encoding="utf-8")
    if not policy_path.exists():
        policy_path.write_text(
            (
                "# Memory Policy\n\n"
                "Balanced policy:\n"
                "- Save stable profile facts.\n"
                "- Save project/tool preferences that affect future responses.\n"
                "- Keep ephemeral notes in daily logs only.\n"
            ),
            encoding="utf-8",
        )
    if not queen_ctx_path.exists():
        queen_ctx_path.write_text(
            (
                "# Queen Context Override\n\n"
                "Use this file for project-specific Queen behavior notes.\n"
                "This file is appended to Queen context at runtime when present.\n"
            ),
            encoding="utf-8",
        )
    return {"memory": memory_path, "policy": policy_path, "queen_context": queen_ctx_path}


def classify_memory_item(content: str) -> tuple[str, float]:
    """Heuristic balanced-policy classifier for extracted memory statements."""
    text = (content or "").strip()
    lowered = text.lower()
    if not text:
        return ("ephemeral_note", 0.0)
    profile_markers = (
        "i am ",
        "my name",
        "i prefer",
        "prefer ",
        "my goal",
        "i want",
        "i work",
        "i use",
    )
    project_markers = (
        "project",
        "repo",
        "stack",
        "typescript",
        "python",
        "react",
        "docker",
        "queen",
        "worker",
        "api",
    )
    if any(marker in lowered for marker in profile_markers):
        return ("profile_fact", 0.9)
    if any(marker in lowered for marker in project_markers):
        return ("project_preference", 0.82)
    if len(text) > 160:
        return ("ephemeral_note", 0.55)
    return ("ephemeral_note", 0.65)


_SENSITIVE_PATTERNS = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email
    re.compile(r"\b(?:\+?\d[\d\-\s().]{8,}\d)\b"),  # phone-like
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),  # possible card number
    re.compile(r"\b(?:ssn|social security|passport|driver(?:'s)? license)\b", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|access[_-]?token|secret|password|private[_-]?key|bearer)\b", re.IGNORECASE),
    re.compile(r"\b(?:sk-[A-Za-z0-9]{12,}|ghp_[A-Za-z0-9]{20,})\b"),  # common key prefixes
)


def is_sensitive_memory_content(content: str) -> bool:
    """Return True when text appears to contain secrets/PII that should not be persisted."""
    text = (content or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _SENSITIVE_PATTERNS)


def append_daily_memory_note(honeycomb_root: str | Path, content: str, source: str = "context_curator") -> Path:
    root = Path(honeycomb_root)
    ensure_memory_files(root)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = root / "memory" / f"{day}.md"
    if not path.exists():
        path.write_text(f"# Daily Memory {day}\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"- [{source}] {content.strip()}\n")
    return path


def append_durable_memory(honeycomb_root: str | Path, content: str, tier: str) -> Path:
    root = Path(honeycomb_root)
    files = ensure_memory_files(root)
    path = files["memory"]
    section = "## Profile Facts" if tier == "profile_fact" else "## Project Preferences"
    body = path.read_text(encoding="utf-8")
    escaped_section = re.escape(section)
    if re.search(escaped_section, body) is None:
        body += f"\n{section}\n"
    lines = body.splitlines()
    insert_at = len(lines)
    for i, line in enumerate(lines):
        if line.strip() == section:
            insert_at = i + 1
            while insert_at < len(lines) and lines[insert_at].strip().startswith("- "):
                if lines[insert_at].strip() == f"- {content.strip()}":
                    return path
                insert_at += 1
            break
    lines.insert(insert_at, f"- {content.strip()}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def load_markdown_memory_snippets(honeycomb_root: str | Path, query: str, limit: int = 8) -> list[str]:
    """Simple hybrid-ish recall from markdown memory files (keyword + recency)."""
    root = Path(honeycomb_root)
    memory_dir = root / "memory"
    if not memory_dir.exists():
        return []
    tokens = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) > 2]
    scored: list[tuple[float, str]] = []
    files = sorted(memory_dir.glob("*.md"), reverse=True)
    for rank, path in enumerate(files):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            content = line[2:] if line.startswith("- ") else line
            content_l = content.lower()
            keyword_score = float(sum(1 for t in tokens if t in content_l))
            if keyword_score <= 0:
                continue
            recency_boost = max(0.1, 1.0 - (rank * 0.12))
            scored.append((keyword_score + recency_boost, content))
    scored.sort(key=lambda r: r[0], reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for _, text in scored:
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out
