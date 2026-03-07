#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    cmd = [sys.executable, "-m", "beekeeper.runner", "doctor", "--json"]
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
