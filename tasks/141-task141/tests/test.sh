#!/bin/sh
set -eu
APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
export CCB_CASE_ID="case-04-saddle-search"
exec python "$TESTS/verify.py" "$APP/final"
