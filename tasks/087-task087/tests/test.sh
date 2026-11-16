#!/bin/sh
set -eu
: "${TESTS:=/tests}"
export TESTS
exec python3 "$TESTS/verify.py"
