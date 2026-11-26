#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Blinded native-evidence review.
"""CompChemBench bridge with binary reward for the audit-v2 required checks."""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

EXPECTED_MANIFEST_SHA256 = "ad18c7738f927a1085f78b02c90a059617f3dd6bb1fc5976bd6ab6e0aa6aba84"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    tests = Path(os.environ.get("TESTS", "/tests"))
    app = Path(os.environ.get("APP", "/app"))
    logs = Path(os.environ.get("LOGS", "/logs/verifier"))
    logs.mkdir(parents=True, exist_ok=True)
    reward_path = logs / "reward.txt"
    reward_path.unlink(missing_ok=True)
    report_path = logs / "verification.json"
    report_path.unlink(missing_ok=True)
    try:
        protected = tests / "protected"
        manifest_path = protected / "assets.json"
        if manifest_path.is_symlink() or digest(manifest_path) != EXPECTED_MANIFEST_SHA256:
            raise ValueError("protected manifest missing or damaged")
        manifest = json.loads(manifest_path.read_text())
        for name, expected in manifest["files"].items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("unsafe protected asset path")
            path = protected / relative
            if any(part.is_symlink() for part in [path, *path.parents]) or digest(path) != expected:
                raise ValueError(f"protected asset missing or damaged: {name}")
        spec = importlib.util.spec_from_file_location("audit_v2_protected", protected / "runtime/audit-v2/evaluator/grade.py")
        grader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(grader)
        grader.PROJECT = protected / "sources"
        submissions = app / "final/submissions"
        if submissions.is_symlink() or any(p.is_symlink() for p in submissions.rglob("*")):
            result = {"full_pass": False, "total_score_percent": 0.0,
                      "error": "candidate submissions must contain regular files"}
        else:
            result = grader.grade(protected / "participant.zip", submissions)
        diagnostic_fraction = result["total_score_percent"] / 100.0
        if not math.isfinite(diagnostic_fraction) or not 0 <= diagnostic_fraction <= 1:
            raise ValueError("invalid native score")
        if bool(result["full_pass"]) != (diagnostic_fraction == 1.0):
            raise ValueError("native full-pass flag and score disagree")
        reward = 1.0 if result["full_pass"] else 0.0
        status = "PASS" if result["full_pass"] else "FAIL"
        report = {"status": status, "reward": reward, "audit_version": "audit-v2",
                  "native_score": result, "diagnostic_fraction": diagnostic_fraction,
                  "score_mapping": "binary: 1 iff all required checks pass; otherwise 0"}
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        reward_path.write_text(f"{reward:.12g}\n")
        print(json.dumps({"status": status, "reward": reward}))
        return 0 if status == "PASS" else 1
    except Exception as error:
        reward_path.unlink(missing_ok=True)
        report_path.write_text(json.dumps({"status": "ENV_INVALID", "error": f"{type(error).__name__}: {error}"}, indent=2) + "\n")
        print(json.dumps({"status": "ENV_INVALID", "error": f"{type(error).__name__}: {error}"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
