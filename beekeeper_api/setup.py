"""First-run setup detection and completion."""
from __future__ import annotations

import os
from pathlib import Path

from beekeeper.store import BeekeeperStore


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _setup_done_path() -> Path:
    return _project_root() / ".beekeeper_setup_done"


def _env_path() -> Path:
    return _project_root() / ".env"


def _store_root() -> Path:
    return Path(os.getenv("BEEKEEPER_STORE_ROOT", ".beekeeper_store"))


def is_setup_done() -> bool:
    """True if setup wizard has completed (flag file exists)."""
    return _setup_done_path().exists()


def is_fresh_install() -> bool:
    """
    True if this is a fresh install needing setup.
    Fresh = no .env AND (no store dir OR store has no orgs).
    If setup_done exists, never fresh.
    """
    if is_setup_done():
        return False
    if _env_path().exists():
        return False
    store_path = _store_root()
    if not store_path.is_absolute():
        store_path = _project_root() / store_path
    if not store_path.exists():
        return True
    try:
        store = BeekeeperStore(root=store_path)
        return len(store.list_orgs()) == 0
    except Exception:
        return True


def mark_setup_done() -> None:
    """Persist flag so setup never runs again."""
    _setup_done_path().write_text("setup complete\n", encoding="utf-8")


# Keys used by setup form and dashboard env editor
_ENV_KEYS = [
    "BEEKEEPER_LLM_PROVIDER",
    "BEEKEEPER_OLLAMA_BASE_URL",
    "BEEKEEPER_OLLAMA_MODEL",
    "BEEKEEPER_GEMINI_API_KEY",
    "BEEKEEPER_OPENAI_API_KEY",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_VERIFY_TOKEN",
]


def read_env_from_file() -> dict[str, str]:
    """
    Parse .env file and return key-value pairs for setup-relevant keys.
    Falls back to os.environ when a key is not in the file (covers Docker overrides).
    """
    result: dict[str, str] = {}
    env_path = _env_path()
    file_values: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1].replace('\\"', '"')
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1].replace("\\'", "'")
            file_values[key] = val
    for key in _ENV_KEYS:
        result[key] = file_values.get(key) or os.environ.get(key, "")
    return result


def write_env_from_config(config: dict[str, str]) -> None:
    """
    Write .env from wizard config.
    When .env exists: read it, merge config over parsed values, write back.
    When .env does not exist: use .env.example as template.
    """
    env_path = _env_path()
    example = _project_root() / ".env.example"

    def _quote(val: str) -> str:
        return f'"{val}"' if (" " in val or val.startswith("#")) else val

    if env_path.exists():
        # Merge with existing .env: update lines for keys in config, preserve others
        lines = env_path.read_text(encoding="utf-8").splitlines()
        seen_keys: set[str] = set()
        new_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                new_lines.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            seen_keys.add(key)
            if key in config:
                val = config[key]
                new_lines.append(f"{key}={_quote(val)}")
                del config[key]
            else:
                new_lines.append(line)
        for key, val in config.items():
            if key not in seen_keys:
                new_lines.append(f"{key}={_quote(val)}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    else:
        # No .env: use .env.example as template
        lines: list[str] = []
        if example.exists():
            for line in example.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or "=" not in stripped:
                    lines.append(line)
                    continue
                key = line.split("=", 1)[0].strip()
                if key in config:
                    val = config[key]
                    lines.append(f"{key}={_quote(val)}")
                    del config[key]
                else:
                    lines.append(line)
        for key, val in config.items():
            lines.append(f"{key}={_quote(val)}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
