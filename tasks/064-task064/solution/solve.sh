#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP:-/app}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
EDGE_ASSIGNMENT="$(printenv D03_BIN_EDGE_ASSIGNMENT || printf floor)"
exec python3 "$SCRIPT_DIR/solve.py" "$APP_ROOT/environment/assets" "$APP_ROOT" "$EDGE_ASSIGNMENT"
