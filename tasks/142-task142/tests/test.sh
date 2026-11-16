#!/bin/sh
set -eu
APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
export CCB_CASE_ID="case-05-initial-guess-robustness"
exec python "$TESTS/verify.py" "$APP/final"
