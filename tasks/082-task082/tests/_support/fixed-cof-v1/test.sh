#!/usr/bin/env bash
set -uo pipefail

APP="${APP:-/app}"
LOGS="${LOGS:-/logs/verifier}"
TESTS="${TESTS:-/tests}"
CASE07_PUBLIC_INPUTS="${CASE07_PUBLIC_INPUTS:-${CASE07_PACKAGE_ROOT:-$APP}/inputs}"
CASE07_AUTHOR_TOOLS="${CASE07_AUTHOR_TOOLS:-$TESTS/_support/author-tools}"
export APP LOGS TESTS
export CASE07_PUBLIC_INPUTS CASE07_AUTHOR_TOOLS

if [ -L "$LOGS" ]; then
  echo "LOGS directory is symlinked" >&2
  exit 2
fi
mkdir -p "$LOGS" || exit 2
# LOGS is now confirmed to be a real directory. Clear stale reward before any
# later exit path, including rejection of a symlinked verification report.
rm -f "$LOGS/reward.txt" || exit 2
if [ -L "$LOGS/verification.json" ]; then
  echo "verification output path is symlinked" >&2
  exit 2
fi
rm -f "$LOGS/verification.json"

set +e
python3 -I "$TESTS/verify.py"
verifier_rc=$?
set -e

if [ ! -f "$LOGS/verification.json" ] || [ -L "$LOGS/verification.json" ]; then
  rm -f "$LOGS/reward.txt"
  echo "verifier did not emit a safe structured report" >&2
  exit 2
fi

decision="$(python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); s=d.get("status"); r=d.get("reward"); absent="reward" not in d; print("PASS" if s=="PASS" and type(r) is int and r==1 else ("REVIEW_REQUIRED" if s=="REVIEW_REQUIRED" and absent else ("FAIL" if s=="FAIL" and type(r) is int and r==0 else ("ENV_INVALID" if s=="ENV_INVALID" and absent else "INVALID"))))' "$LOGS/verification.json" 2>/dev/null)" || decision="INVALID"
case "$verifier_rc:$decision" in
  0:PASS)
    if [ -L "$LOGS/reward.txt" ]; then
      echo "reward path is symlinked" >&2
      exit 2
    fi
    printf '1\n' > "$LOGS/reward.txt"
    exit 0
    ;;
  0:REVIEW_REQUIRED)
    rm -f "$LOGS/reward.txt"
    exit 0
    ;;
  1:FAIL)
    if [ -L "$LOGS/reward.txt" ]; then
      echo "reward path is symlinked" >&2
      exit 2
    fi
    printf '0\n' > "$LOGS/reward.txt"
    # Harbor requires a successful verifier process; reward.txt records the score.
    exit 0
    ;;
  2:ENV_INVALID)
    rm -f "$LOGS/reward.txt"
    exit 2
    ;;
esac
rm -f "$LOGS/reward.txt"
echo "verifier exit/status/reward contract mismatch; no reward emitted" >&2
exit 2
