#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -d ".venv" ] && source .venv/bin/activate
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