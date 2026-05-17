#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTEST_BIN="${PYTEST_BIN:-pytest}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

$PYTEST_BIN --collect-only -q >/dev/null
PYTEST_BIN="$PYTEST_BIN" $PYTHON_BIN -m beekeeper.runner smoke-test --json >/dev/null
./scripts/run_e2e.sh
./scripts/run_recovery_drill.sh

echo "[OK] phase4 release gate passed"
