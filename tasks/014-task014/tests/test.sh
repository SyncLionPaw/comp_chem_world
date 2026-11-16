#!/bin/sh
set -u
TESTS_DIR=${TESTS:-/tests}
LOGS_DIR=${LOGS:-/logs/verifier}
mkdir -p "$LOGS_DIR" || exit 2
# A previous run must never leak a score into this run. If the verifier log
# mount has become read-only, the runner treats exit 2 as ENV_INVALID and
# ignores any stale files it cannot remove.
rm -f "$LOGS_DIR/reward.txt" "$LOGS_DIR/verification.json" || exit 2
python3 "$TESTS_DIR/verify.py"
rc=$?
if [ "$rc" -gt 1 ]; then
    rm -f "$LOGS_DIR/reward.txt"
    if ! grep -Eq '"status"[[:space:]]*:[[:space:]]*"ENV_INVALID"' "$LOGS_DIR/verification.json" 2>/dev/null; then
        printf '%s\n' '{"status":"ENV_INVALID","reason":"Scorer entrypoint, dependency, or environment failure"}' > "$LOGS_DIR/verification.json" || true
    fi
    cat "$LOGS_DIR/verification.json" 2>/dev/null || true
    exit 2
fi
if [ ! -s "$LOGS_DIR/verification.json" ]; then
    # An evaluator crash while writing its result (for example ENOSPC or a
    # read-only log mount) is an environment failure, never a scientific FAIL.
    rm -f "$LOGS_DIR/reward.txt"
    printf '%s\n' '{"status":"ENV_INVALID","reason":"Scorer exited without a verification report"}' > "$LOGS_DIR/verification.json" || true
    cat "$LOGS_DIR/verification.json" 2>/dev/null || true
    exit 2
fi
# Scientific rejection with an explicit zero reward is a valid scored result.
if [ "$rc" -eq 1 ]; then
    case "$(cat "$LOGS_DIR/reward.txt" 2>/dev/null)" in
        0|0.0) exit 0 ;;
    esac
fi
exit "$rc"
