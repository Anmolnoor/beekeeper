from __future__ import annotations

import json
from pathlib import Path

from .contracts import SoulProfile


def load_soul_file(path: Path) -> SoulProfile:
    data = json.loads(path.read_text(encoding="utf-8"))
    return SoulProfile.model_validate(data)


def load_default_queen_soul() -> SoulProfile:
    soul_path = Path(__file__).parent / "souls" / "queen.soul.json"
    return load_soul_file(soul_path)
