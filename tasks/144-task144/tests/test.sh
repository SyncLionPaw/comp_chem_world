#!/bin/bash
set -euo pipefail
APP="${APP:-/app}"
LOGS="${LOGS:-/logs/verifier}"
TESTS="${TESTS:-/tests}"
mkdir -p "$LOGS"
python "$TESTS/verify.py"
