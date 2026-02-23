from __future__ import annotations

import json
import re
from pathlib import Path

from .contracts import SoulProfile

_SCHEMA_VERSION = "v1"
_QUEEN_SOUL_ID = "soul.queen.crown"
_QUEEN_SOUL_NAME = "Queen Crown Protocol"

_TONE_VALUES: tuple[str, ...] = ("neutral", "concise", "detailed", "assertive")
_RISK_VALUES: tuple[str, ...] = ("low", "balanced", "high")
_VERBOSITY_VALUES: tuple[str, ...] = ("low", "medium", "high")
_ESCALATION_VALUES: tuple[str, ...] = ("strict", "balanced", "lenient")


def _norm_literal(val: str, choices: tuple[str, ...], default: str) -> str:
    v = (val or "").strip().lower()
    for c in choices:
        if c in v or v in c:
            return c
    return default


def load_soul_file(path: Path) -> SoulProfile:
    data = json.loads(path.read_text(encoding="utf-8"))
    return SoulProfile.model_validate(data)


def load_soul_from_markdown(path: Path) -> SoulProfile:
    """
    Parse SOUL.md into SoulProfile. Sections: ## Tone, ## Risk Appetite, ## Verbosity,
    ## Escalation Style, ## Traits (YAML block or key-value list).
    """
    text = path.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []

    for line in text.splitlines():
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            if current:
                sections[current] = "\n".join(buf).strip()
            current = m.group(1).strip().lower().replace(" ", "_")
            buf = []
        elif current:
            buf.append(line)

    if current:
        sections[current] = "\n".join(buf).strip()

    tone = _norm_literal(sections.get("tone", ""), _TONE_VALUES, "neutral")
    risk = _norm_literal(sections.get("risk_appetite", ""), _RISK_VALUES, "balanced")
    verbosity = _norm_literal(sections.get("verbosity", ""), _VERBOSITY_VALUES, "medium")
    escalation = _norm_literal(sections.get("escalation_style", ""), _ESCALATION_VALUES, "balanced")

    traits: dict[str, object] = {}
    traits_raw = sections.get("traits", "")
    if traits_raw.strip():
        try:
            import yaml
            parsed = yaml.safe_load(traits_raw)
            if isinstance(parsed, dict):
                traits = parsed
        except Exception:
            for ln in traits_raw.splitlines():
                if ":" in ln:
                    k, _, v = ln.partition(":")
                    if k.strip():
                        traits[k.strip()] = v.strip()

    return SoulProfile(
        soul_profile_id=_QUEEN_SOUL_ID,
        name=_QUEEN_SOUL_NAME,
        tone=tone,
        risk_appetite=risk,
        verbosity=verbosity,
        escalation_style=escalation,
        traits=traits,
        version=_SCHEMA_VERSION,
    )


def load_queen_soul(honeycomb_root: Path | None = None) -> SoulProfile:
    """
    Load Queen soul with resolution order: .soul.json, SOUL.soul.json, SOUL.md, queen.soul.json.
    """
    default_path = Path(__file__).parent / "souls" / "queen.soul.json"
    search_dirs: list[Path] = []
    if honeycomb_root:
        root = Path(honeycomb_root).resolve()
        if root.name == ".honeycomb":
            search_dirs.append(root.parent)
        else:
            search_dirs.append(root)
    search_dirs.append(Path.cwd())

    for d in search_dirs:
        for name, loader in [
            (".soul.json", lambda p: load_soul_file(p)),
            ("SOUL.soul.json", lambda p: load_soul_file(p)),
            ("SOUL.md", lambda p: load_soul_from_markdown(p)),
        ]:
            path = d / name
            if path.exists():
                try:
                    return loader(path)
                except Exception:
                    pass

    return load_soul_file(default_path)


def load_default_queen_soul() -> SoulProfile:
    soul_path = Path(__file__).parent / "souls" / "queen.soul.json"
    return load_soul_file(soul_path)
