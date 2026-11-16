#!/bin/sh
# New private replacement reference; the removed original cannot be recovered.
set -eu
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 BLIS_NUM_THREADS=1
solution_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$solution_dir/analysis.py"
