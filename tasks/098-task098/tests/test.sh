#!/usr/bin/env bash
set -u
APP="${APP:-/app}"
TESTS="${TESTS:-/tests}"
LOGS="${LOGS:-/logs/verifier}"
mkdir -p "$LOGS"
rm -f "$LOGS/reward.txt" "$LOGS/verification.json"
python3 - "$APP" "$TESTS" "$LOGS" '8d24c044a1799e38eac350632ee27c947ea0ecccd7991eef239d64a6741e2e2d' <<'PYCODE'
import hashlib, json, subprocess, sys
from pathlib import Path
app, tests, logs = map(Path, sys.argv[1:4])
expected_manifest_sha = sys.argv[4]
def infra(message):
    (logs / "verification.json").write_text(json.dumps({"overall":"ERROR","infra_error":message}, indent=2)+"\n", encoding="utf-8")
    raise SystemExit(2)
manifest_path = tests / "refs.json"
try:
    manifest_bytes = manifest_path.read_bytes()
except OSError as exc:
    infra(f"reference manifest unavailable: {exc}")
if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha:
    infra("reference manifest hash mismatch")
try:
    manifest = json.loads(manifest_bytes)
except (UnicodeDecodeError, json.JSONDecodeError) as exc:
    infra(f"reference manifest invalid: {exc}")
if not isinstance(manifest, dict):
    infra("reference manifest root must be an object")
if manifest.get("schema") != "p15-verifier-reference-manifest/v1" or manifest.get("case_id") != 'case-03-md-spectra-elastic-moduli':
    infra("reference manifest schema/case mismatch")
for item in manifest.get("files", []):
    path = tests / item["path"]
    try:
        raw = path.read_bytes()
    except OSError as exc:
        infra(f"reference unavailable: {item.get('path')}: {exc}")
    if len(raw) != item.get("bytes") or hashlib.sha256(raw).hexdigest() != item.get("sha256"):
        infra(f"reference SHA-256 mismatch: {item.get('path')}")
try:
    import numpy, scipy
    if numpy.__version__ != "2.3.5" or scipy.__version__ != "1.16.2":
        infra(f"runtime dependency version mismatch: numpy={numpy.__version__} scipy={scipy.__version__}")
except Exception as exc:
    infra(f"runtime dependency unavailable: {exc}")
try:
    run = subprocess.run(["python3", str(tests / "verify.py"), "--json", str(app / "final")], capture_output=True, text=True)
except Exception as exc:
    infra(f"verifier could not be started: {exc}")
try:
    report = json.loads(run.stdout)
except json.JSONDecodeError:
    infra(f"verifier JSON invalid (rc={run.returncode}): {run.stderr[-1000:]}")
if not isinstance(report, dict):
    infra("verifier JSON root must be an object")
(logs / "verification.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
overall = report.get("overall")
if overall == "PASS" and run.returncode == 0:
    (logs / "reward.txt").write_text("1\n", encoding="utf-8")
    raise SystemExit(0)
if overall == "FAIL" and run.returncode == 1:
    (logs / "reward.txt").write_text("0\n", encoding="utf-8")
    raise SystemExit(1)
infra(f"verifier outcome/exit mismatch or ERROR: overall={overall!r}, rc={run.returncode}; stderr={run.stderr[-1000:]}")
PYCODE
