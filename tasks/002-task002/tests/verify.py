#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Mechanistic features and experimental barrier prediction.
"""Run required Case 02 checks and report Harbor reward eligibility explicitly."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def classify(exit_code: int, payload: dict) -> str:
    if not isinstance(payload, dict):
        return "INFRA_ERROR"
    status = payload.get("status")
    if exit_code == 2 and status == "INFRA_ERROR":
        return "INFRA_ERROR"
    if exit_code == 1 and status in {"FAIL", "SCIENTIFIC_BAND_FAIL", "INVALID_SUBMISSION"}:
        return "FAIL"
    if exit_code == 11 and status in {"REVIEW_REQUIRED", "NOT_VERIFIED"}:
        return "REVIEW_REQUIRED"
    if exit_code == 0 and status == "PASS":
        return "PASS"
    return "INFRA_ERROR"


def write_reports(logs: Path, report: dict) -> None:
    logs.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    (logs / "case02-check.json").write_text(encoded, encoding="utf-8")
    (logs / "verification.json").write_text(encoded, encoding="utf-8")


def main() -> int:
    app = Path(os.environ.get("APP", "/app"))
    tests = Path(os.environ.get("TESTS", "/tests"))
    logs = Path(os.environ.get("LOGS", "/logs/verifier"))
    checker = tests / "_support" / "case02_checker.py"
    assets, refs = app / "assets", tests / "refs.json"
    final = app / "final"
    calls = [
        ("independent", ["--submission", str(app)], True),
        ("paired_ablation_v2", ["--ablation", str(final / "ablation-v2")], True),
    ]
    optional_ts = final / "ts-ablation-v3"
    if optional_ts.is_dir():
        calls.append(("optional_ts_ablation_v3", ["--ts-ablation", str(optional_ts)], False))

    started = time.monotonic()
    results = []
    for name, mode_args, required in calls:
        remaining = 570 - (time.monotonic() - started)
        if remaining <= 0:
            stage = {"name": name, "required": required, "status": "INFRA_ERROR",
                     "reason": "shared verifier time budget exhausted before stage launch",
                     "reward_eligible": False, "refit_verified": False}
            results.append(stage)
            continue
        command = [sys.executable, str(checker), *mode_args, "--assets", str(assets), "--refs", str(refs)]
        try:
            process = subprocess.run(command, capture_output=True, text=True,
                                     timeout=min(270, remaining))
            response = process.stdout.strip() or process.stderr.strip()
            try:
                payload = json.loads(response)
            except json.JSONDecodeError:
                payload = {"status": "INFRA_ERROR", "reason": "checker emitted invalid JSON",
                           "stdout": process.stdout, "stderr": process.stderr}
            status = classify(process.returncode, payload)
            if not isinstance(payload, dict):
                payload = {"status": "INFRA_ERROR", "reason": "checker JSON response must be an object",
                           "response": payload}
            reason = payload.get("errors", payload.get("reason"))
            if reason is None and status != "PASS":
                reason = payload.get("status", f"checker exited {process.returncode}")
            stage = {"name": name, "required": required, "status": status,
                     "exit_code": process.returncode, "reason": reason,
                     "checker": payload, "stderr": process.stderr,
                     "reward_eligible": status == "PASS",
                     "refit_verified": bool(payload.get("declared_protocol_independent_refit_verified")),
                     "candidate_training_execution_verified": bool(payload.get("training_execution_verified"))}
        except subprocess.TimeoutExpired as exc:
            stage = {"name": name, "required": required, "status": "INFRA_ERROR",
                     "reason": f"checker timed out: {exc}", "reward_eligible": False,
                     "refit_verified": False, "candidate_training_execution_verified": False}
        results.append(stage)
        print(json.dumps(stage, ensure_ascii=False))

    required_results = [stage for stage in results if stage["required"]]
    statuses = {stage["status"] for stage in required_results}
    if "INFRA_ERROR" in statuses:
        verdict, code, reward = "INFRA_ERROR", 2, None
    elif "FAIL" in statuses:
        verdict, code, reward = "FAIL", 10, 0
    elif "REVIEW_REQUIRED" in statuses:
        verdict, code, reward = "REVIEW_REQUIRED", 11, None
    else:
        verdict, code, reward = "PASS", 0, 1
    report = {
        "status": verdict,
        "reward": reward,
        "reward_eligible": verdict == "PASS",
        "no_reward_reason": None if verdict == "PASS" else verdict,
        "required_stages": [stage["name"] for stage in required_results],
        "required_stage_statuses": {stage["name"]: stage["status"] for stage in required_results},
        "static_scientific_checks": results,
        "candidate_training_execution_verified": False,
        "runtime_binding": "declared_protocol_numerical_refit",
    }
    try:
        write_reports(logs, report)
    except OSError as exc:
        print(f"INFRA_ERROR: unable to write verifier reports: {exc}", file=sys.stderr)
        return 2
    summary = {"status": verdict, "reward": reward, "reward_eligible": verdict == "PASS",
               "required_protocols": report["required_stages"]}
    print(json.dumps(summary, ensure_ascii=False))
    if verdict in {"REVIEW_REQUIRED", "INFRA_ERROR"}:
        print(f"No reward: required verification status is {verdict}.", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
