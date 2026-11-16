#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="${APP:-/app}"
ASSETS="${ASSETS:-$APP/assets}"
PYTHON="${PYTHON:-python3}"
mkdir -p "$APP/final"
"$PYTHON" "$HERE/invert_dcm.py" "$ASSETS" "$APP/final"
