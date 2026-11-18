#!/bin/sh
set -eu
APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
export CCB_CASE_ID="case-02-curvature-bias"
exec python3 "$TESTS/verify.py" "$APP/final"
