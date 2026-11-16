#!/bin/bash
set -euo pipefail
exec python3 "${TESTS:-/tests}/verify.py"
