#!/usr/bin/env bash
set -euo pipefail
: "${APP:=/app}" "${TESTS:=$(cd "$(dirname "$0")" && pwd)}" "${LOGS:=/logs/verifier}"
export APP TESTS LOGS
exec python3 "$TESTS/verify.py" --grade
