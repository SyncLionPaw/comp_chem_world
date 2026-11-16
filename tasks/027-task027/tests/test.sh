#!/usr/bin/env bash
set -euo pipefail
APP=${APP:-/app}
TESTS=${TESTS:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)}
LOGS=${LOGS:-/logs/verifier}
export APP TESTS LOGS
rm -f "$LOGS"/reward.txt "$LOGS"/verification.json
mkdir -p "$LOGS"
python3 - <<'PYTHON'
import hashlib
import json
import os
from pathlib import Path
import sys

app = Path(os.environ["APP"])
tests = Path(os.environ["TESTS"])
logs = Path(os.environ["LOGS"])
final = app / "final"
sys.path.insert(0, str(tests / "_support"))
import fresh_evidence

# Reuse historical independent assessments only for their exact reviewed bytes.
# Fresh/changed submissions retain the original PENDING review defaults.
review_dir = tests / "protected" / "reference-reviews"
review_paths = {
    "CCB_CASE07_REVIEW_ASSESSMENT_PATH": review_dir / "independent-review.json",
    "CCB_CASE07_NATIVE_REVIEW_PATH": review_dir / "native-review-v3.json",
    "CCB_CASE07_RESOURCE_REVIEW_PATH": review_dir / "resource-review.json",
}
if not any(name in os.environ for name in review_paths):
    try:
        report_path = final / "ts_search_report.json"
        report = json.loads(report_path.read_text())
        manifest = fresh_evidence._manifest_from_disk(final)
        binding = {
            "attempt_id": report.get("attempt_id"),
            "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            "artifact_manifest_sha256": fresh_evidence.canonical_sha256(manifest),
        }
        reviews = [json.loads(path.read_text()) for path in review_paths.values()]
        exact = all(all(item.get(key) == value for key, value in binding.items())
                    for item in reviews)
    except (OSError, ValueError, TypeError, KeyError):
        exact = False
    if exact:
        os.environ.update({name: str(path) for name, path in review_paths.items()})

os.execv(sys.executable, [sys.executable, str(tests / "verify.py"),
                        "--app", str(app), "--tests", str(tests), "--logs", str(logs)])
PYTHON
