#!/bin/sh
set -eu
APP_DIR=${APP:-/app}
TESTS_DIR=${TESTS:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
LOGS_DIR=${LOGS:-/logs/verifier}
mkdir -p "$LOGS_DIR" || exit 2
rm -f "$LOGS_DIR/reward.txt" "$LOGS_DIR/verification.json"
APP="$APP_DIR" TESTS="$TESTS_DIR" LOGS="$LOGS_DIR" python3 "$TESTS_DIR/verify.py" --harbor
