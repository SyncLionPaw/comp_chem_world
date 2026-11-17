#!/usr/bin/env bash
set -euo pipefail
PKG="${APP:-/app}"
exec "${PYTHON_BIN:-python3}" -B "$PKG/public/replay.py" --inputs "$PKG/inputs" --spec "${2:-$PKG/public/example-spec.json}" --out "${1:-/app/final}"
