#!/usr/bin/env bash
set -euo pipefail
APP="${APP:-/app}"
LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json" "$LOGS/research-evidence.json" "$LOGS/reward.json"
set +e
python3 "${TESTS:-/tests}/verify.py" "$APP/final" --evidence-out "$LOGS/research-evidence.json"
rc=$?
set -e
# If the verifier already wrote a scientific reward, keep it.
if [[ -f "$LOGS/reward.txt" ]]; then
  exit 0
fi
# Pending science (NOT_MADE_BY_AUTOMATION / REVIEW_REQUIRED) must not be auto-scored as 1.
if [[ -f "$LOGS/research-evidence.json" ]]; then
  python3 - "$LOGS" "$rc" <<'PYCODE'
import json, pathlib, sys
logs = pathlib.Path(sys.argv[1])
rc = int(sys.argv[2])
evidence = json.loads((logs / "research-evidence.json").read_text())
status = evidence.get("status")
decision = evidence.get("science_decision")
if status == "CASE07_INVALID":
    (logs / "reward.txt").write_text("0\n", encoding="ascii")
    raise SystemExit(1)
if status == "ENV_INVALID" or rc not in (0, 1, 2):
    (logs / "reward.json").write_text(json.dumps({
        "infra_error": 1, "reward": None, "status": status, "exit_code": rc,
    }, ensure_ascii=False) + "\n")
    raise SystemExit(2)
# REVIEW_REQUIRED / structural-OK pending science: marker only, never reward=1.
(logs / "reward.json").write_text(json.dumps({
    "review_required": 1,
    "reward": None,
    "status": status,
    "science_decision": decision,
}, ensure_ascii=False) + "\n")
print("REVIEW_REQUIRED: structural checks complete; no science decision or reward", flush=True)
raise SystemExit(0)
PYCODE
  exit $?
fi
if [[ "$rc" == 0 ]]; then
  printf '{"review_required": 1, "reward": null}\n' > "$LOGS/reward.json"
  exit 0
fi
printf '{"infra_error": 1, "reward": null, "exit_code": %s}\n' "$rc" > "$LOGS/reward.json"
exit 2
