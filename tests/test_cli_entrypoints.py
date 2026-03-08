from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from beekeeper import runner


def test_project_scripts_map_primary_and_legacy_entrypoints() -> None:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]

    assert scripts["beekeeper"] == "beekeeper.cli.main:main"
    assert scripts["beekeeper-legacy"] == "beekeeper.runner:main"


def test_legacy_runner_help_uses_legacy_prog_name(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["beekeeper-legacy", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        runner.main()

    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "usage: beekeeper-legacy" in output
    assert "Supported Phase 1 workflows now live under `beekeeper`." in output
