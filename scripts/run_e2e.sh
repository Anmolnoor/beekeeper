#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTEST_BIN="${PYTEST_BIN:-pytest}"

# Golden + approval + failure/retry path coverage for local CI/dev.
$PYTEST_BIN -q \
  tests/test_phase45_regression.py \
  tests/test_phase678_regression.py
