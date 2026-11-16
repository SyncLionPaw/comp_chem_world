#!/bin/bash
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
set -euo pipefail
APP="${APP:-/app}"
python3 "$(dirname "$0")/_impl/solve.py" "$APP"
