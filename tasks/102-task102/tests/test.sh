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
# Always emit a numeric reward so Harbor does not raise RewardFileNotFoundError.
# Structural rejection / review-required paths score 0; only explicit PASS may set 1.
if [[ -f "$LOGS/reward.txt" ]]; then
  exit 0
fi
if [[ "$rc" == 0 ]]; then
  printf '1\n' > "$LOGS/reward.txt"
  exit 0
fi
printf '0\n' > "$LOGS/reward.txt"
if [[ "$rc" == 2 && -f "$LOGS/research-evidence.json" ]]; then
  python3 - "$LOGS/research-evidence.json" <<'PYCODE' || true
import json, pathlib, sys
evidence = json.loads(pathlib.Path(sys.argv[1]).read_text())
print("REVIEW_REQUIRED: structural checks complete; no science decision or reward=0", flush=True)
print(json.dumps({"status": evidence.get("status"), "science_decision": evidence.get("science_decision")}, ensure_ascii=False))
PYCODE
fi
exit 0
