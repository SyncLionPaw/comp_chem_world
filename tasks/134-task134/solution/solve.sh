#!/usr/bin/env bash
# Oracle-only adapter for the Harbor /solution mount.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="${APP:-/app}"
OUTPUT="${1:-${APP_ROOT%/}/final}"
export CASE_ID="case-02"
export INPUT_ROOT="${INPUT_ROOT:-/app/environment/inputs}"
export NEP_SOURCE_ROOT="${NEP_SOURCE_ROOT:-/opt/nep-cpu}"
exec "${PYTHON:-python3}" "${SCRIPT_DIR}/reference.py" --output "$OUTPUT"
