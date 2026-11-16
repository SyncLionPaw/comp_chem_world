#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including FES.csv, blocks.csv, thermodynamics.json).
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Recompute Binding Free Energy and Choose a Stop/Go Decision.
"""Run the task-local science scorer and forward its JSON report."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

app = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("APP", "/app")).resolve()
tests = Path(__file__).resolve().parent
science = tests / "science"
with tempfile.TemporaryDirectory(prefix="harbor-verifier-") as tmp:
    logs = Path(tmp)
    env = dict(os.environ, APP=str(app), TESTS=str(science), LOGS=str(logs))
    proc = subprocess.run(["bash", str(science / "test.sh"), str(app)], env=env, text=True, capture_output=True)
    report_path = logs / "verification.json"
    if report_path.is_file():
        report_text = report_path.read_text(encoding="utf-8")
    else:
        report_text = proc.stdout.strip()
    try:
        report = json.loads(report_text)
    except Exception as exc:
        report = {"status": "INFRA_ERROR", "error": f"science verifier emitted no valid JSON report: {exc}", "stderr": proc.stderr[-4000:]}
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(proc.returncode)
