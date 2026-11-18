#!/bin/sh
set -eu
APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
export CCB_CASE_ID="case-01-derivative-consistency"
exec python3 "$TESTS/verify.py" "$APP/final"
