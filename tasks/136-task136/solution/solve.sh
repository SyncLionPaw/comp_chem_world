#!/usr/bin/env bash
# Oracle-only adapter for the Harbor /solution mount.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="${APP:-/app}"
OUTPUT="${1:-${APP_ROOT%/}/final}"
exec "${PYTHON:-python3}" "${SCRIPT_DIR}/reference.py" --output "$OUTPUT"
