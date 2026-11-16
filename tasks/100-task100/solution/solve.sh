#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="${APP:-/app}"
ASSETS="${ASSETS:-$APP/assets}"
PYTHON="${PYTHON:-python3}"
if [[ -z "${BENCH15_MD_NATIVE_ROOT:-}" ]]; then
  printf '%s\n' 'No native run was found. Set BENCH15_MD_NATIVE_ROOT to a completed candidate-produced N2/seed-24101 run bundle; this solver will not synthesize or replay a result.' >&2
  exit 2
fi
"$PYTHON" "$HERE/analyze_native_submission.py" \
  --native-root "$BENCH15_MD_NATIVE_ROOT" --assets "$ASSETS" --output "$APP"
