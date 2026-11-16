#!/usr/bin/env bash
set -euo pipefail
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
APP="${APP:-/app}"
mkdir -p "$APP/final"
cp "$(dirname -- "$0")/_impl/analyze.py" "$APP/final/analyze.py"
python3 "$APP/final/analyze.py" --input "$APP/assets/trajectory_sample.npz" --out "$APP/final"
