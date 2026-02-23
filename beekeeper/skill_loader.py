"""Load skills from SKILL.md with YAML frontmatter (Agent Skills standard)."""
from __future__ import annotations

import re
from pathlib import Path

from .contracts import SkillProfile

_SCHEMA_VERSION = "v1"


def _parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Split YAML frontmatter from body. Returns (frontmatter_dict, body)."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not match:
        return {}, text
    fm, body = match.group(1), match.group(2)
    try:
        import yaml
        data = yaml.safe_load(fm) or {}
        return dict(data) if isinstance(data, dict) else {}, body
    except Exception:
        return {}, body


def load_skill_from_md(path: Path, skill_profile_id: str | None = None) -> SkillProfile:
    """
    Load SkillProfile from SKILL.md with YAML frontmatter.
    Frontmatter: name (required), description (required), when_to_use (optional), skill_profile_id (optional).
    """
    text = path.read_text(encoding="utf-8")
    fm, _body = _parse_frontmatter(text)
    name = str(fm.get("name", path.parent.name)).strip()
    description = str(fm.get("description", "")).strip()
    when_to_use = fm.get("when_to_use")
    if when_to_use is not None:
        when_to_use = str(when_to_use).strip() or None
    sid = skill_profile_id or fm.get("skill_profile_id") or f"skill.{path.parent.name.replace('-', '_')}"
    sid = str(sid).strip()

    capabilities: list[str] = []
    if isinstance(fm.get("capabilities"), list):
        capabilities = [str(c) for c in fm["capabilities"]]
    elif isinstance(fm.get("capabilities"), str):
        capabilities = [c.strip() for c in fm["capabilities"].split(",") if c.strip()]

    tool_allowlist: list[str] = []
    if isinstance(fm.get("tool_allowlist"), list):
        tool_allowlist = [str(t) for t in fm["tool_allowlist"]]
    elif isinstance(fm.get("tool_allowlist"), str):
        tool_allowlist = [t.strip() for t in fm["tool_allowlist"].split(",") if t.strip()]

    can_search_web = bool(fm.get("can_search_web", False))
    can_execute_code = bool(fm.get("can_execute_code", False))
    max_parallel_tools = int(fm.get("max_parallel_tools", 2))

    return SkillProfile(
        skill_profile_id=sid,
        name=name,
        description=description,
        when_to_use=when_to_use,
        tool_allowlist=tool_allowlist,
        capabilities=capabilities,
        can_search_web=can_search_web,
        can_execute_code=can_execute_code,
        max_parallel_tools=max_parallel_tools,
        version=_SCHEMA_VERSION,
    )


def discover_skill_md_paths(honeycomb_root: Path) -> list[Path]:
    """Discover SKILL.md files from .honeycomb/skills/, ~/.beekeeper/skills/, project skills/."""
    paths: list[Path] = []
    root = Path(honeycomb_root).resolve()
    project_root = root.parent if root.name == ".honeycomb" else root

    dirs = [
        root / "skills",
        Path.home() / ".beekeeper" / "skills",
        project_root / "skills",
    ]
    for d in dirs:
        if not d.exists():
            continue
        for p in d.glob("*/SKILL.md"):
            if p.is_file():
                paths.append(p)
    return paths


def load_skills_from_md(honeycomb_root: Path) -> list[SkillProfile]:
    """Load all SkillProfiles from discovered SKILL.md files."""
    profiles: list[SkillProfile] = []
    seen: set[str] = set()
    for path in discover_skill_md_paths(honeycomb_root):
        try:
            profile = load_skill_from_md(path)
            if profile.skill_profile_id not in seen:
                seen.add(profile.skill_profile_id)
                profiles.append(profile)
        except Exception:
            pass
    return profiles
