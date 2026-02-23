#!/bin/sh
# Create sandboxed beekeeper-agent Linux user (no sudo privileges).
# Run as root on Linux only. Skips on macOS.
# Usage: sudo ./scripts/create_beekeeper_user.sh
set -e
case "$(uname -s)" in
  Linux)
    if [ "$(id -u)" -ne 0 ]; then
      echo "Run as root: sudo $0"
      exit 1
    fi
    id beekeeper-agent 2>/dev/null || useradd -r -m -s /bin/bash beekeeper-agent
    echo "Created user beekeeper-agent"
    ;;
  *)
    echo "Skipping: Linux only"
    ;;
esac
