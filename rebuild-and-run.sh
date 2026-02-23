#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -d ".venv" ] && source .venv/bin/activate
pip install -e . -q
beekeeper rebuild
beekeeper up --with-open-webui