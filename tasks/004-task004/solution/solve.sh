#!/bin/sh
set -eu

# Author-equivalent v2 protocol on the public runtime inputs only.
APP=/app
RUNNER=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROTOCOL="$RUNNER/protocol-author-equivalent.v2.json"

test -f "$RUNNER/run_case04_runtime.py"
test -f "$PROTOCOL"
mkdir -p "$APP/final"

python - "$RUNNER" "$PROTOCOL" "$APP" <<'PY'
from pathlib import Path
import sys

solution_dir, protocol_path, app_dir = map(Path, sys.argv[1:])
sys.path.insert(0, str(solution_dir))
import case04_protocol as protocol

protocol.CASE = app_dir
protocol.ROOT = app_dir
protocol.ASSETS = app_dir / "assets"
import run_case04_runtime as runner

runner.main(["--protocol", str(protocol_path), "--final-dir", str(app_dir / "final")])
PY
