#!/usr/bin/env bash
set -euo pipefail

# This Oracle path recalculates every reported scientific field from raw, pinned
# native VASP outputs. A fresh Agent run uses the same parser after running VASP.
HERE="$(cd "$(dirname "$0")" && pwd)"
export APP="${APP:-/app}"
export PYTHONPATH="$HERE/reanalysis${PYTHONPATH:+:$PYTHONPATH}"
python3 "$HERE/reanalysis/reanalyze.py"
