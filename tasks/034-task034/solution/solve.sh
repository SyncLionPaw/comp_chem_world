#!/usr/bin/env bash
# Reference replay for the local reduced-sampling Oracle using the bundled
# solution/reference-final tree. REFERENCE_FINAL may override its location.
set -euo pipefail
APP="${APP:-/app}"
SOLUTION_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REF="${REFERENCE_FINAL:-$SOLUTION_DIR/reference-final}"
OUT="$APP/final"
if [ ! -d "$REF" ]; then
  echo "reference final not staged at $REF" >&2
  echo "see solution/README.md" >&2
  exit 1
fi
rm -rf "$OUT"
mkdir -p "$OUT"
cp -a "$REF"/. "$OUT"/
cd "$OUT"
python3 analysis.py
