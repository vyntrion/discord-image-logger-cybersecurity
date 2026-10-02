#!/usr/bin/env bash
# Convenience wrapper: setup on first run, then server + tunnel in one shot.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

# First run: walk through the wizard, then start.
if [ ! -f config.json ]; then
  echo "no config.json yet — running the setup wizard first…"
  python3 setup.py || true
fi

exec python3 run.py "$@"
