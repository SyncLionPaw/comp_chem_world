#!/usr/bin/env bash
set -euo pipefail
exec python "${TESTS:-/tests}/verify.py" --runner
