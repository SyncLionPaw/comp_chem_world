#!/usr/bin/env bash
set -euo pipefail
tests=${TESTS:-/tests}
exec python3 "$tests/verify.py"
