"""Package ecosystem: beehive install for workers and guardrails.

Enables `beehive install <package>` to:
- pip install the package
- Discover workers/guardrails via package metadata ([tool.beehive] in pyproject.toml or beehive.json)
- Register in .honeycomb/workers/plugins.json and .honeycomb/guardrails/plugins.json
- Optionally add registry entry for workers
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any



def _run_pip_install(package: str, editable: bool = False) -> bool:
    """Run pip install. Returns True on success."""
    cmd = [sys.executable, "-m", "pip", "install", "--quiet"]
    if editable:
        cmd.append("-e")
    cmd.append(package)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def _find_package_metadata(package_name: str) -> dict[str, Any] | None:
    """Find beehive metadata from installed package. Returns None if not found."""
    try:
        import importlib.metadata
        dist = importlib.metadata.distribution(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None

    # 1. Check for beehive entry points
    workers: list[dict[str, str]] = []
    guardrails: list[dict[str, str]] = []
    try:
        eps = dist.entry_points or []
        if hasattr(eps, "select"):
            for ep in eps.select(group="beehive.workers"):
                workers.append({
                    "module_path": ep.module,
                    "class_name": ep.attr or ep.name.split(".")[-1],
                    "worker_kind": ep.name.split(".")[0] if "." in ep.name else "custom",
                })
            for ep in eps.select(group="beehive.guardrails"):
                guardrails.append({
                    "module_path": ep.module,
                    "class_name": ep.attr or ep.name.split(".")[-1],
                })
        else:
            for ep in eps:
                grp = getattr(ep, "group", "")
                if grp == "beehive.workers":
                    workers.append({
                        "module_path": getattr(ep, "module", ""),
                        "class_name": getattr(ep, "attr", "") or (ep.name.split(".")[-1] if ep.name else ""),
                        "worker_kind": "custom",
                    })
                elif grp == "beehive.guardrails":
                    guardrails.append({
                        "module_path": getattr(ep, "module", ""),
                        "class_name": getattr(ep, "attr", "") or (ep.name.split(".")[-1] if ep.name else ""),
                    })
    except Exception:
        pass

    if workers or guardrails:
        return {"workers": workers, "guardrails": guardrails}

    # 2. Check for beehive.json in package
    try:
        files = dist.files or []
        for f in files:
            if f.name.endswith("beehive.json"):
                path = dist.locate_file(f)
                if path and Path(path).exists():
                    raw = json.loads(Path(path).read_text(encoding="utf-8"))
                    return raw
    except Exception:
        pass

    # 3. Check pyproject.toml [tool.beehive]
    try:
        if dist.files:
            for f in dist.files:
                if "pyproject.toml" in str(f):
                    loc = dist.locate_file(f)
                    if loc:
                        proj_path = Path(loc).parent / "pyproject.toml"
                        if proj_path.exists():
                            import tomllib  # Python 3.11+
                            with open(proj_path, "rb") as fp:
                                proj = tomllib.load(fp)
                            tool = proj.get("tool", {}).get("beehive", {})
                            if tool:
                                return tool
                    break
    except ImportError:
        pass
    except Exception:
        pass

    return None


def _ensure_plugins_file(path: Path, key: str) -> list[dict[str, Any]]:
    """Ensure plugins file exists and return current entries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return list(raw.get(key, []))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _write_plugins(path: Path, key: str, entries: list[dict[str, Any]]) -> None:
    """Write plugins file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({key: entries}, indent=2, ensure_ascii=True), encoding="utf-8")


def _ensure_registry_file(honeycomb_root: Path) -> Path:
    """Ensure workers registry exists. Returns path."""
    path = honeycomb_root / "workers" / "registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        from .worker_registry import DEFAULT_REGISTRY
        path.write_text(json.dumps(DEFAULT_REGISTRY, indent=2, ensure_ascii=True), encoding="utf-8")
    return path


def _add_worker_to_registry(honeycomb_root: Path, worker_kind: str, name: str, description: str) -> None:
    """Add worker entry to registry if not already present."""
    path = _ensure_registry_file(honeycomb_root)
    raw = json.loads(path.read_text(encoding="utf-8"))
    workers = list(raw.get("workers", []))
    existing_kinds = {w.get("worker_kind") for w in workers}
    if worker_kind in existing_kinds:
        return
    workers.append({
        "worker_kind": worker_kind,
        "name": name,
        "description": description or f"Plugin worker: {worker_kind}",
        "capabilities": [worker_kind],
        "intent_patterns": [worker_kind],
        "payload_triggers": [],
        "query_keywords": [],
        "priority": 15,
        "fallback_workers": [],
    })
    raw["workers"] = workers
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=True), encoding="utf-8")


def install_package(
    package: str,
    honeycomb_root: Path,
    *,
    editable: bool = False,
    registry: bool = True,
) -> tuple[bool, str]:
    """
    Install a beehive package (workers/guardrails).
    Returns (success, message).
    """
    if not package or not package.strip():
        return False, "Package name required"

    pkg = package.strip()

    if not _run_pip_install(pkg, editable=editable):
        return False, f"pip install failed for {pkg}"

    # Normalize package name for metadata lookup (e.g. "beehive-worker-xyz" -> "beehive_worker_xyz")
    lookup_name = pkg.replace("-", "_").split("[")[0].split("==")[0]

    meta = _find_package_metadata(lookup_name)
    if not meta:
        return True, f"Installed {pkg} (no beehive workers/guardrails metadata found)"

    workers = meta.get("workers", [])
    guardrails = meta.get("guardrails", [])

    if workers:
        plugins_path = honeycomb_root / "workers" / "plugins.json"
        entries = _ensure_plugins_file(plugins_path, "workers")
        seen = {(e.get("module_path"), e.get("class_name")) for e in entries}
        for w in workers:
            mp = (w.get("module_path") or "").strip()
            cn = (w.get("class_name") or "").strip()
            kind = (w.get("worker_kind") or "custom").strip()
            if mp and cn and (mp, cn) not in seen:
                entries.append({"module_path": mp, "class_name": cn, "worker_kind": kind})
                seen.add((mp, cn))
                if registry:
                    _add_worker_to_registry(
                        honeycomb_root,
                        kind,
                        w.get("name", kind),
                        w.get("description", ""),
                    )
        _write_plugins(plugins_path, "workers", entries)

    if guardrails:
        plugins_path = honeycomb_root / "guardrails" / "plugins.json"
        entries = _ensure_plugins_file(plugins_path, "guardrails")
        seen = {(e.get("module_path"), e.get("class_name")) for e in entries}
        for g in guardrails:
            mp = (g.get("module_path") or "").strip()
            cn = (g.get("class_name") or "").strip()
            if mp and cn and (mp, cn) not in seen:
                entries.append({"module_path": mp, "class_name": cn})
                seen.add((mp, cn))
        _write_plugins(plugins_path, "guardrails", entries)

    parts = []
    if workers:
        parts.append(f"{len(workers)} worker(s)")
    if guardrails:
        parts.append(f"{len(guardrails)} guardrail(s)")
    msg = f"Installed {pkg}: registered {', '.join(parts)}"
    return True, msg


def _plugin_roots(honeycomb_root: Path) -> list[Path]:
    """Return plugin search roots: honeycomb_root first, then project-local .beehive if present."""
    roots = [honeycomb_root]
    beehive_dir = honeycomb_root.resolve().parent / ".beehive"
    if beehive_dir.exists():
        roots.append(beehive_dir)
    return roots


def list_installed_plugins(honeycomb_root: Path) -> dict[str, list[dict[str, Any]]]:
    """List currently registered workers and guardrails from plugins.json (including .beehive/ if present)."""
    out: dict[str, list[dict[str, Any]]] = {"workers": [], "guardrails": []}
    seen_workers: set[tuple[str, str]] = set()
    seen_guardrails: set[tuple[str, str]] = set()
    for root in _plugin_roots(honeycomb_root):
        for key, subpath in [("workers", "workers/plugins.json"), ("guardrails", "guardrails/plugins.json")]:
            path = root / subpath
            if not path.exists():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                entries = raw.get(key, [])
            except (json.JSONDecodeError, OSError):
                continue
            for e in entries:
                if key == "workers":
                    k = (e.get("module_path", ""), e.get("class_name", ""))
                    if k not in seen_workers:
                        seen_workers.add(k)
                        out["workers"].append(e)
                else:
                    k = (e.get("module_path", ""), e.get("class_name", ""))
                    if k not in seen_guardrails:
                        seen_guardrails.add(k)
                        out["guardrails"].append(e)
    return out


def uninstall_plugin(
    honeycomb_root: Path,
    *,
    worker: str | None = None,
    guardrail: str | None = None,
) -> tuple[bool, str]:
    """
    Remove a worker or guardrail from plugins.json.
    worker: "module_path:class_name" or worker_kind
    guardrail: "module_path:class_name"
    """
    if worker and guardrail:
        return False, "Specify either --worker or --guardrail, not both"
    if not worker and not guardrail:
        return False, "Specify --worker or --guardrail"

    if worker:
        path = honeycomb_root / "workers" / "plugins.json"
        key = "workers"
        entries = _ensure_plugins_file(path, key)
        if ":" in worker:
            mp, cn = worker.split(":", 1)
            entries = [e for e in entries if e.get("module_path") != mp or e.get("class_name") != cn]
        else:
            entries = [e for e in entries if e.get("worker_kind") != worker]
        _write_plugins(path, key, entries)
        return True, f"Removed worker: {worker}"

    if guardrail:
        path = honeycomb_root / "guardrails" / "plugins.json"
        key = "guardrails"
        entries = _ensure_plugins_file(path, key)
        if ":" in guardrail:
            mp, cn = guardrail.split(":", 1)
            entries = [e for e in entries if e.get("module_path") != mp or e.get("class_name") != cn]
        else:
            entries = [e for e in entries if e.get("module_path") != guardrail]
        _write_plugins(path, key, entries)
        return True, f"Removed guardrail: {guardrail}"

    return False, ""
