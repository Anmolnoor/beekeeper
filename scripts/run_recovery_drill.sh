#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HONEYCOMB_ROOT="${HONEYCOMB_ROOT:-.honeycomb_recovery_drill}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
rm -rf "$HONEYCOMB_ROOT"

# 1) Create an initial run and persist durable state.
$PYTHON_BIN -m beekeeper.runner smoke-test --honeycomb-root "$HONEYCOMB_ROOT" --json >/tmp/recovery_smoke_1.json

TRACE_ID_1="$($PYTHON_BIN -c 'import json;print(json.load(open("/tmp/recovery_smoke_1.json"))["summary"]["trace_id"])')"

# 2) Simulate process restart by creating a new run in a new process.
$PYTHON_BIN -m beekeeper.runner smoke-test --honeycomb-root "$HONEYCOMB_ROOT" --json >/tmp/recovery_smoke_2.json

TRACE_ID_2="$($PYTHON_BIN -c 'import json;print(json.load(open("/tmp/recovery_smoke_2.json"))["summary"]["trace_id"])')"

# 3) Validate durable control-plane DB and inspect run history.
$PYTHON_BIN - <<'PY'
from pathlib import Path
import sqlite3
import os

root = Path(os.environ.get("HONEYCOMB_ROOT", ".honeycomb_recovery_drill"))
db = root / "control_plane.db"
if not db.exists():
    raise SystemExit("[FAIL] recovery drill: control_plane.db missing")

conn = sqlite3.connect(str(db))
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM runs")
runs_count = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM run_state_transitions")
transitions_count = cur.fetchone()[0]
conn.close()

if runs_count < 2:
    raise SystemExit(f"[FAIL] recovery drill: expected >=2 runs, found {runs_count}")
if transitions_count < 2:
    raise SystemExit(f"[FAIL] recovery drill: expected >=2 run state transitions, found {transitions_count}")

print("[OK] recovery drill passed")
print({
    "honeycomb_root": str(root),
    "runs_count": runs_count,
    "run_state_transitions": transitions_count,
})
PY

echo "[OK] recovery traces: $TRACE_ID_1, $TRACE_ID_2"
