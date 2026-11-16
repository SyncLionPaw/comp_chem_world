#!/bin/sh
set -u
TESTS_DIR=${TESTS:-/tests}
LOGS_DIR=${LOGS:-/logs/verifier}
mkdir -p "$LOGS_DIR" || exit 2
rm -f "$LOGS_DIR/reward.txt" "$LOGS_DIR/verification.json" || exit 2
# Bound local numerical-library pools for the fixed verifier time budget.
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
python3 "$TESTS_DIR/verify.py"
rc=$?
if [ "$rc" -gt 1 ]; then
    rm -f "$LOGS_DIR/reward.txt"
    if ! grep -Eq '"status"[[:space:]]*:[[:space:]]*"ENV_INVALID"' "$LOGS_DIR/verification.json" 2>/dev/null; then
        printf '%s\n' '{"status":"ENV_INVALID","reason":"Scorer entrypoint or trusted evaluator environment failure"}' > "$LOGS_DIR/verification.json" || true
    fi
    cat "$LOGS_DIR/verification.json" 2>/dev/null || true
    exit 2
fi
if [ ! -s "$LOGS_DIR/verification.json" ]; then
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
