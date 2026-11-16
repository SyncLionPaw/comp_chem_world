#!/usr/bin/env bash
set -euo pipefail
if [[ $# -gt 1 ]]; then
  echo "usage: solve.sh [OUTPUT_DIR]" >&2
  exit 2
fi
here="$(cd -- "$(dirname -- "$0")" && pwd -P)"
out="${1:-${APP:-/app}}"
exec python3 "$here/solve.py" "$out"
