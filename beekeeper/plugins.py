"""Pluggable workers and guardrails via discovery and dynamic loading.

Extension points:
- Entry points (beekeeper.workers, beekeeper.guardrails): Load via importlib.metadata from installed packages
- JSON config: .honeycomb/workers/plugins.json, .honeycomb/guardrails/plugins.json

Built-in workers/guardrails are always loaded; entry-point and JSON plugins extend them.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, TypeVar

from .contracts import WorkerKind

T = TypeVar("T")


def _get_entry_points(group: str) -> list[Any]:
    """Load entry points for a group. Compatible with Python 3.9 and 3.10+."""
    try:
        from importlib.metadata import entry_points
    except ImportError:
        try:
            from importlib_metadata import entry_points
        except ImportError:
            return []
    all_eps = entry_points()
    if hasattr(all_eps, "select"):
        eps = all_eps.select(group=group)
    elif hasattr(all_eps, "get"):
        eps = all_eps.get(group, [])
    else:
        eps = []
    return list(eps) if eps else []


def _load_plugin_class(module_path: str, class_name: str, root: Path | None = None) -> type | None:
    """Dynamically load a class from module_path.class_name or from file path."""
    try:
        path = Path(module_path)
        file_path = path if path.is_absolute() and path.exists() else (Path(root or Path.cwd()) / module_path if root else path)
        if path.suffix == ".py" and file_path.exists():
            spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod
                spec.loader.exec_module(mod)
                return getattr(mod, class_name, None)
        mod = importlib.import_module(module_path)
        return getattr(mod, class_name, None)
    except (ImportError, AttributeError, OSError):
        return None


def load_worker_plugins_from_entry_points() -> dict[WorkerKind, Any]:
    """
    Load worker plugins from beekeeper.workers entry points (installed packages).
    Entry point value: module.path:ClassName (class must have worker_kind attribute).
    Returns dict of WorkerKind -> worker instance.
    """
    result: dict[WorkerKind, Any] = {}
    for ep in _get_entry_points("beekeeper.workers"):
        try:
            obj = ep.load()
            instance = obj() if (isinstance(obj, type) or callable(obj)) else obj
            if not hasattr(instance, "worker_kind"):
                continue
            kind = getattr(instance, "worker_kind")
            if isinstance(kind, WorkerKind):
                result[kind] = instance
            else:
                try:
                    result[WorkerKind(kind)] = instance
                except (ValueError, TypeError):
                    result[WorkerKind.custom] = instance
        except Exception:
            pass
    return result


def _plugin_roots(honeycomb_root: Path) -> list[Path]:
    """Return plugin search roots: honeycomb_root first, then project-local .beekeeper if present."""
    roots = [honeycomb_root]
    beekeeper_dir = honeycomb_root.resolve().parent / ".beekeeper"
    if beekeeper_dir.exists():
        roots.append(beekeeper_dir)
    return roots


def load_worker_plugins(honeycomb_root: Path) -> dict[WorkerKind | str, Any]:
    """
    Load worker plugins from entry points and .honeycomb/workers/plugins.json (and .beekeeper/workers/ if present).
    Entry points are loaded first; JSON plugins override for same worker_kind.
    Returns dict of WorkerKind -> worker instance (extends built-ins).
    """
    result = load_worker_plugins_from_entry_points()
    for root in _plugin_roots(honeycomb_root):
        plugins_path = root / "workers" / "plugins.json"
        if not plugins_path.exists():
            continue

        try:
            raw = json.loads(plugins_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        entries = raw.get("workers", [])
        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            module_path = entry.get("module_path", "").strip()
            class_name = entry.get("class_name", "").strip()
            kind_str = entry.get("worker_kind", "").strip()
            if not module_path or not class_name or not kind_str:
                continue
            try:
                kind: WorkerKind | str = WorkerKind(kind_str)
            except ValueError:
                kind = kind_str if kind_str.startswith("forged_") else WorkerKind.custom
            cls = _load_plugin_class(module_path, class_name, root=root)
            if cls is None:
                continue
            try:
                instance = cls()
                if hasattr(instance, "worker_kind"):
                    result[kind] = instance
            except Exception:
                pass
    return result


def load_guardrail_plugins_from_entry_points() -> list[Any]:
    """
    Load guardrail plugins from beekeeper.guardrails entry points.
    Entry point value: module.path:ClassName (class must have evaluate method).
    Returns list of guardrail instances.
    """
    result: list[Any] = []
    for ep in _get_entry_points("beekeeper.guardrails"):
        try:
            obj = ep.load()
            instance = obj() if (isinstance(obj, type) or callable(obj)) else obj
            if hasattr(instance, "evaluate"):
                result.append(instance)
        except Exception:
            pass
    return result


def load_guardrail_plugins(honeycomb_root: Path) -> list[Any]:
    """
    Load guardrail plugins from entry points and .honeycomb/guardrails/plugins.json (and .beekeeper/guardrails/ if present).
    Returns list of guardrail instances (to append to built-ins).
    """
    result = load_guardrail_plugins_from_entry_points()
    for root in _plugin_roots(honeycomb_root):
        plugins_path = root / "guardrails" / "plugins.json"
        if not plugins_path.exists():
            continue

        try:
            raw = json.loads(plugins_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        entries = raw.get("guardrails", [])
        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            module_path = entry.get("module_path", "").strip()
            class_name = entry.get("class_name", "").strip()
            if not module_path or not class_name:
                continue
            cls = _load_plugin_class(module_path, class_name)
            if cls is None:
                continue
            try:
                instance = cls()
                if hasattr(instance, "evaluate"):
                    result.append(instance)
            except Exception:
                pass
    return result
