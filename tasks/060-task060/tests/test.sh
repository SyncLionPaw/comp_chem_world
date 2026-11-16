#!/usr/bin/env bash
set -euo pipefail
exec python3 "${TESTS:-/tests}/verify.py"
