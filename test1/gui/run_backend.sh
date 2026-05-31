#!/usr/bin/env bash
# Launch the GUI backend on the spike venv interpreter (the one with altium_monkey).
# ALWAYS start the backend with this script — a bare `python app.py` on system
# Python can't import altium_monkey and every build silently fails (A2).
#
#   bash test1/gui/run_backend.sh
#
set -euo pipefail
VENV="${ALTIUM_VENV:-/c/Users/mking/Downloads/altium_spike/.venv/Scripts/python.exe}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$HERE/backend"

if [ ! -f "$VENV" ]; then
  echo "venv python not found at $VENV — set ALTIUM_VENV or edit run_backend.sh" >&2
  exit 1
fi

echo "Starting backend on $VENV ..."
exec "$VENV" "$BACKEND/app.py"
