#!/usr/bin/env bash
set -euo pipefail
APP=${APP:-/app}
TESTS=${TESTS:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)}
LOGS=${LOGS:-/logs/verifier}
export APP TESTS LOGS
mkdir -p "$LOGS"
python3 "$TESTS/verify.py"
