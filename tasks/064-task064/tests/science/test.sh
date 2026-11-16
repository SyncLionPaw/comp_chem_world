#!/usr/bin/env bash
set -euo pipefail
TESTS="$(cd -- "$(dirname -- "$0")" && pwd)"
APP="${APP:-/app}"
LOGS="${LOGS:-/logs/verifier}"
export APP TESTS LOGS
exec python3 -B "$TESTS/verify.py" --runner
