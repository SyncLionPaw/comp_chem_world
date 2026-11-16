#!/usr/bin/env bash
set -euo pipefail
export APP="${APP:-/app}" TESTS="${TESTS:-/tests}" LOGS="${LOGS:-/logs/verifier}"
export PYTHONDONTWRITEBYTECODE=1
exec python3 -I "$TESTS/verify.py" --terminal
