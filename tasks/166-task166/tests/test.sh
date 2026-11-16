#!/usr/bin/env bash
set -euo pipefail

PREP_LOG_DIR="${LOGS:-/logs/verifier}"
[[ ! -L "$PREP_LOG_DIR" ]] || { printf '%s\n' 'unsafe verifier log directory' >&2; exit 2; }
mkdir -p "$PREP_LOG_DIR"
[[ -d "$PREP_LOG_DIR" && ! -L "$PREP_LOG_DIR" ]] || { printf '%s\n' 'unsafe verifier log directory' >&2; exit 2; }
chown root:root "$PREP_LOG_DIR"
chmod 700 "$PREP_LOG_DIR"
stale_bad=0
for stale in reward.txt reward.json; do
  if [[ -L "$PREP_LOG_DIR/$stale" || -f "$PREP_LOG_DIR/$stale" ]]; then
    rm -f "$PREP_LOG_DIR/$stale"
  elif [[ -e "$PREP_LOG_DIR/$stale" ]]; then
    stale_bad=1
  fi
done
if (( stale_bad )); then
  printf '%s\n' 'stale verifier reward is a special filesystem entry' >&2
  exit 2
fi

if [[ "${CCB_BENCH25_GUARDED:-}" != "1" ]]; then
  exec python3 -B -I /opt/bench25/entrypoint.py grade -- /bin/bash "$0" "$@"
fi

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
APP_DIR="${APP:-$(pwd -P)}"
APP_DIR="${APP:-/app}"
LOG_DIR="${LOGS:-/logs/verifier}"
VERIFY="$TEST_DIR/verify.py"
V2_PROOF_ROOT="/trusted/case05-v2-scoring"
V2_REJECTION_ROOT="/trusted/case05-v2-rejection"
mkdir -p "$LOG_DIR"
chmod 700 "$LOG_DIR"

# A prior invocation must not let an environment error inherit an old score.
rm -f "$LOG_DIR/reward.txt" "$LOG_DIR/reward.json" "$LOG_DIR/verification.json" "$LOG_DIR/verdict.json"
stdout_file="$(mktemp "$LOG_DIR/.case05-verify-stdout.XXXXXX")"
stderr_file="$(mktemp "$LOG_DIR/.case05-verify-stderr.XXXXXX")"
report_tmp="$(mktemp "$LOG_DIR/.case05-verification.XXXXXX")"
trap 'rm -f "$stdout_file" "$stderr_file" "$report_tmp"' EXIT

# Public geometries are mounted with their case-relative inputs/ path under /app.
set +e
# Proof routing is selected only by runner-owned proof presence or runner
# manifest variables. The shared context digest alone selects neither route.
if [[ -d /trusted/case05-pyscf-rejection && -f /trusted/case05-pyscf-rejection/proof.json ]]; then
  export CCB_CASE05_PYSCF_REJECTION_PROOF_SHA256="$(sha256sum /trusted/case05-pyscf-rejection/proof.json | cut -d' ' -f1)"
fi
if [[ -d /trusted/case05-pyscf-failure && -f /trusted/case05-pyscf-failure/proof.json ]]; then
  export CCB_CASE05_PYSCF_FAILURE_PROOF_SHA256="$(sha256sum /trusted/case05-pyscf-failure/proof.json | cut -d' ' -f1)"
fi
v2_requested=0
if [[ -e "$V2_PROOF_ROOT" || -L "$V2_PROOF_ROOT" \
      || -n ${CCB_CASE05_V2_SCORING_MANIFEST_SHA256+x} ]]; then
  v2_requested=1
fi
rejection_v2_requested=0
if [[ -e "$V2_REJECTION_ROOT" || -L "$V2_REJECTION_ROOT" \
      || -n ${CCB_CASE05_V2_REJECTION_MANIFEST_SHA256+x} ]]; then
  rejection_v2_requested=1
fi
shared_v2_context_requested=0
if [[ -n ${CCB_CASE05_V2_RUN_CONTEXT_SHA256+x} ]]; then
  shared_v2_context_requested=1
fi
if (( v2_requested && rejection_v2_requested )); then
  printf '%s\n' "ENV_INVALID: completed and pre-dispatch rejection proofs cannot be selected together" >&2
  verify_rc=2
elif (( shared_v2_context_requested && ! v2_requested && ! rejection_v2_requested )); then
  printf '%s\n' "ENV_INVALID: a Case05 v2 context was supplied without its selected proof manifest" >&2
  verify_rc=2
elif (( rejection_v2_requested )); then
  python3 "$VERIFY" --route rejection >"$stdout_file" 2>"$stderr_file"
  verify_rc=$?
elif (( v2_requested )); then
  python3 "$VERIFY" --route v2 >"$stdout_file" 2>"$stderr_file"
  verify_rc=$?
else
  python3 "$VERIFY" --route legacy "$APP_DIR" --reference-dir "$APP_DIR/inputs" >"$stdout_file" 2>"$stderr_file"
  verify_rc=$?
fi
set -e

case "$verify_rc" in
  0) status="PASS"; reward="1"; message="trusted Case05 verification passed" ;;
  1) status="FAIL"; reward="0"; message="candidate failed Case05 verification" ;;
  2) status="ENV_INVALID"; reward=""; message="trusted Case05 verification context is unavailable or invalid" ;;
  *) status="ENV_INVALID"; reward=""; message="verifier exited unexpectedly"; verify_rc=2 ;;
esac

python3 - "$report_tmp" "$status" "$verify_rc" "$reward" "$message" "$stdout_file" "$stderr_file" <<'PY'
import json
import sys
from pathlib import Path

target, status, exit_code, reward, message, stdout_path, stderr_path = sys.argv[1:]
details = "\n".join(part for part in (
    Path(stdout_path).read_text(encoding="utf-8", errors="replace").strip(),
    Path(stderr_path).read_text(encoding="utf-8", errors="replace").strip(),
) if part)
record = {
    "schema": "compchembench-scorer-report/v1",
    "case_id": "case-05",
    "status": status,
    "exit_code": int(exit_code),
    "message": message + (": " + details[-4000:] if details else ""),
}
if reward:
    record["reward"] = int(reward)
Path(target).write_text(json.dumps(record, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
PY
chmod 600 "$report_tmp"
mv "$report_tmp" "$LOG_DIR/verification.json"
if [[ -n "$reward" ]]; then
  reward_tmp="$(mktemp "$LOG_DIR/.case05-reward.XXXXXX")"
  printf '%s\n' "$reward" >"$reward_tmp"
  chmod 600 "$reward_tmp"
  mv "$reward_tmp" "$LOG_DIR/reward.txt"
fi

exit "$verify_rc"
