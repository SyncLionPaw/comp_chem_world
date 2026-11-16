#!/bin/sh
set -eu
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
APP="${1:-/app}"
mkdir -p "$APP/final"
cp "$(dirname "$0")/_impl/capacitance_analysis.py" "$APP/final/analyze.py"
python3 "$APP/final/analyze.py" \
  --input "$APP/assets/reference_sweeps.csv" \
  --refinement "$APP/assets/curve_refinement.csv" \
  --manifest "$APP/assets/analysis_contract.json" \
  --out "$APP/final"
