"""User memory: extract and persist critical info from conversations for context over time."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .worker import WebSearchWorker


def _make_extractor_llm() -> Callable[[str], str | None]:
    """Build a callable that uses the configured LLM for extraction."""
    provider = (os.getenv("BEEKEEPER_LLM_PROVIDER") or "ollama").strip().lower()
    base_url = (os.getenv("BEEKEEPER_OLLAMA_BASE_URL") or "http://100.99.106.59:11434").rstrip("/")
    model = os.getenv("BEEKEEPER_OLLAMA_MODEL") or "catsarethebest/qwen2.5-N2:1.5b"
    timeout = max(5, int(os.getenv("BEEKEEPER_OLLAMA_TIMEOUT_SECONDS", "120")))
    gemini_key = (os.getenv("BEEKEEPER_GEMINI_API_KEY") or "").strip()
    gemini_model = os.getenv("BEEKEEPER_GEMINI_MODEL") or "gemini-1.5-flash"
    gemini_timeout = max(5, int(os.getenv("BEEKEEPER_GEMINI_TIMEOUT_SECONDS", "120")))

    worker = WebSearchWorker(
        llm_provider=provider,
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

