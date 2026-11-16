#!/usr/bin/env bash
set -euo pipefail
export TESTS="${TESTS:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
exec python3 -B "$TESTS/verify.py" "$@"
