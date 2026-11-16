#!/usr/bin/env bash
set -euo pipefail

APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS"
python3 "$TESTS/review_status.py" --app "$APP" --tests "$TESTS" --logs "$LOGS"
