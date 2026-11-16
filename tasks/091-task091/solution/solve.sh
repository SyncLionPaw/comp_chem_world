#!/bin/sh
set -eu
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
APP="${1:-/app}"
mkdir -p "$APP/final"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cp "$SCRIPT_DIR/_impl/edl_solver.py" "$APP/final/solver.py"
cp "$SCRIPT_DIR/_impl/smearing.py" "$APP/final/smearing.py"
python3 "$APP/final/solver.py" --input "$APP/request/edl_request.json" --output-dir "$APP/final"
