#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -d ".venv" ] && source .venv/bin/activate

# Require Python 3.10+ (needed for mcp and other deps)
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "ERROR: This project requires Python 3.10+. Current: $(python3 --version 2>/dev/null || true)"
  echo "Recreate the venv with Python 3.10+, then re-run this script:"
  echo "  rm -rf .venv && python3.10 -m venv .venv && source .venv/bin/activate"
  echo "  # or: python3.11 -m venv .venv   if you have 3.11"
  exit 1
fi

pip install -e . -q

COMPOSE_CMD=""
if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
else
  echo "[FAIL] Docker Compose not found. Install docker compose or docker-compose."
  exit 1
fi

DATA_ROOT="./runtime/docker-data"
mkdir -p \
  "${DATA_ROOT}/redis" \
  "${DATA_ROOT}/temporal" \
  "${DATA_ROOT}/qdrant" \
  "${DATA_ROOT}/honeycomb" \
  "${DATA_ROOT}/store" \
  "${DATA_ROOT}/open-webui"

echo "[INFO] data root: ${DATA_ROOT}"
echo "[INFO] full no-cache rebuild for all services..."
$COMPOSE_CMD -f docker-compose.yml build --no-cache

echo "[INFO] force recreating full stack..."
$COMPOSE_CMD -f docker-compose.yml up -d --force-recreate --remove-orphans

echo "[OK] rebuild and run complete."