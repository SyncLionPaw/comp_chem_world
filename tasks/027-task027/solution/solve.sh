#!/usr/bin/env bash
set -euo pipefail

assets="${APP:-/app}/assets"
out="${APP:-/app}/final"
python3 "$(dirname "$0")/_support/solve.py" --assets "$assets" --output "$out" "$@"
