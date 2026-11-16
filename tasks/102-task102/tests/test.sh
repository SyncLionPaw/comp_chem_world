#!/usr/bin/env bash
set -euo pipefail
APP="${APP:-/app}"
LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json" "$LOGS/research-evidence.json"
set +e
python3 "${TESTS:-/tests}/verify.py" "$APP/final" --evidence-out "$LOGS/research-evidence.json"
rc=$?
set -e
# Structural rejection is a candidate failure, not an accepted scientific claim.
# A valid research submission still requires independent review; no automatic 1.
if [[ "$rc" == 2 && -f "$LOGS/research-evidence.json" ]]; then
  python3 - "$LOGS/research-evidence.json" "$LOGS/reward.txt" <<'PYCODE'
import json, pathlib, sys
evidence = json.loads(pathlib.Path(sys.argv[1]).read_text())
if (evidence.get("status") == "CASE07_INVALID" and evidence.get("reward") is None
        and evidence.get("science_decision") == "NOT_MADE_BY_AUTOMATION"):
    pathlib.Path(sys.argv[2]).write_text("0\n")
    raise SystemExit(1)
raise SystemExit(2)
PYCODE
fi
exit "$rc"
