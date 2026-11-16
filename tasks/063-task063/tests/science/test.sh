#!/usr/bin/env bash
set -euo pipefail
TESTS="$(cd -- "$(dirname -- "$0")" && pwd)"
APP="${1:-${APP:-$(dirname -- "$TESTS")}}"
export APP TESTS
LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS"
tmp="$(mktemp "$LOGS/.verify.XXXXXX")"
python3 - "$TESTS" "$APP" "$LOGS" <<'PY_PREFLIGHT'
import pathlib, sys
sys.path.insert(0, sys.argv[1])
try:
    from review_status import preflight_trusted_sources
    preflight_trusted_sources(pathlib.Path(sys.argv[2]).resolve(), pathlib.Path(sys.argv[1]).resolve())
except Exception as exc:
    import json
    logs = pathlib.Path(sys.argv[3])
    (logs / "verification.json").write_text(json.dumps({"status": "INFRA_ERROR", "error": f"trusted source preflight failed: {exc}"}) + "\n", encoding="utf-8")
    print(f"trusted source preflight failed: {exc}", file=sys.stderr)
    raise SystemExit(2)
PY_PREFLIGHT
set +e
python3 -B "$TESTS/verify.py" >"$tmp"
verifier_rc=$?
set -e
python3 - "$tmp" "$LOGS" "$verifier_rc" <<'PY'
import json, os, pathlib, sys
source, logs, rc = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), int(sys.argv[3])
try:
    report = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(report, dict): raise ValueError("report must be an object")
except Exception as exc:
    report = {"status": "INFRA_ERROR", "error": f"verifier emitted invalid JSON: {exc}"}
status = report.get("status")
if status == "REVIEW_REQUIRED":
    sys.path.insert(0, os.environ["TESTS"])
    try:
        from review_status import adjudicate
        report = adjudicate(pathlib.Path(os.environ["APP"]).resolve(), pathlib.Path(os.environ["TESTS"]).resolve(), report)
        status = report.get("status")
    except Exception as exc:
        report = {"status": "INFRA_ERROR", "error": f"author review binding failed: {exc}"}
        status = "INFRA_ERROR"
if status == "INFRASTRUCTURE_ERROR": report["status"] = status = "INFRA_ERROR"
(logs / "verification.json").write_text(json.dumps(report, ensure_ascii=False) + "\n", encoding="utf-8")
(logs / "reward.txt").unlink(missing_ok=True)
if status == "FAIL":
    (logs / "reward.txt").write_text("0\n", encoding="ascii")
elif status == "PASS":
    (logs / "reward.txt").write_text("1\n", encoding="ascii")
elif status in {"REVIEW_REQUIRED", "INFRA_ERROR"}:
    pass
else:
    report = {"status": "INFRA_ERROR", "error": f"unsupported verifier status: {status!r}"}
    (logs / "verification.json").write_text(json.dumps(report) + "\n", encoding="utf-8")
(logs / "raw-verifier.stdout.json").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
source.unlink(missing_ok=True)
if status == "FAIL":
    code = 1 if rc in (0, 1) else 2
elif status in {"REVIEW_REQUIRED", "PASS"}:
    code = 0 if rc == 0 else 2
elif status == "INFRA_ERROR":
    code = 2
else:
    code = 2
sys.exit(code)
PY
