#!/usr/bin/env bash
set -euo pipefail
mkdir -p /app/final
exec python3 /solution/solve.py /app/final
