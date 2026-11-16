#!/usr/bin/env python3
"""Bind scientific author review to one complete Case 08 candidate and source set."""
from __future__ import annotations

import hashlib
import argparse
import json
import math
import os
import stat
import sys
from pathlib import Path

CASE_ID = "case-08-short-md-stop-go"
CRITERIA = {
    "bounded_remote_native_engine_run_and_provenance",
    "paired_timestep_intervention_and_physical_parameter_control",
    "numerical_temperature_constraint_and_water_geometry_diagnosis",
    "bounded_go_stop_decision_and_inference_scope",
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def review_record_path(tests: Path, candidate: dict) -> Path:
    addressed = tests / "author-reviews" / (canonical_sha(candidate) + ".json")
    if addressed.parent.is_symlink():
        raise RuntimeError("candidate-addressed author-review directory is a symlink")
    return addressed if addressed.is_file() or addressed.is_symlink() else tests / "author-review.json"


def validate_criterion_statuses(review_status: str, criteria: dict) -> None:
    statuses = {"PASS"} if review_status == "PASS" else {"PASS", "FAIL", "REVIEW_REQUIRED"}
    for name, item in criteria.items():
        if not isinstance(item, dict) or item.get("status") not in statuses:
            raise RuntimeError(f"author review has invalid criterion status: {name}")
        if not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
            raise RuntimeError(f"author review lacks criterion evidence: {name}")
    if review_status == "FAIL" and not any(item["status"] == "FAIL" for item in criteria.values()):
        raise RuntimeError("author review FAIL must identify at least one failed criterion")


def validate_execution_binding(execution: dict, candidate: dict, source_manifest_sha: str,
                               record: dict) -> dict:
    if (execution.get("schema") != "case08-verified-execution/v1"
            or execution.get("job_id") != record.get("trusted_job_id")
            or execution.get("review_status") != "independently-reviewed"
            or execution.get("candidate_manifest_sha256") != canonical_sha(candidate)
            or execution.get("source_manifest_sha256") != source_manifest_sha
            or execution.get("native_evidence_sha256") != record["native_evidence_sha256"]
            or execution.get("accounting_evidence_sha256") != record["accounting_evidence_sha256"]):
        raise RuntimeError("trusted execution evidence does not bind this candidate and execution")
    execution_sources = execution.get("execution_sources")
    if not isinstance(execution_sources, dict):
        raise RuntimeError("trusted execution evidence lacks execution source hashes")
    if (len(execution_sources) < 2
            or any(not isinstance(value, str) or len(value) != 64
                   or any(char not in "0123456789abcdef" for char in value)
                   for value in execution_sources.values())):
        raise RuntimeError("trusted execution evidence has malformed execution source hashes")
    return execution_sources


def receipt_fields(receipt: dict) -> dict:
    if not isinstance(receipt, dict):
        raise ValueError("scheduler receipt is missing")
    nested = receipt.get("fields", {})
    if not isinstance(nested, dict):
        raise ValueError("scheduler receipt fields are malformed")
    for name, value in nested.items():
        if name in receipt and receipt[name] != value:
            raise ValueError(f"scheduler receipt has conflicting flat and nested {name}")
    return {**receipt, **nested}


def validate_bounded_allocation(allocation: dict) -> None:
    if not isinstance(allocation, dict):
        raise ValueError("source manifest lacks allocation evidence")
    def exact_int(value) -> int:
        if isinstance(value, bool):
            raise ValueError("boolean resource count")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdecimal():
            return int(value)
        if isinstance(value, float) and math.isfinite(value) and value.is_integer():
            return int(value)
        raise ValueError("non-integral resource count")

    try:
        nodes = exact_int(allocation["nodes"])
        cpus = exact_int(allocation["cpus"])
        memory_value = allocation.get("memory_gib", allocation.get("memory_gb"))
        if isinstance(memory_value, bool):
            raise ValueError("boolean memory limit")
        memory = float(memory_value)
        walltime = allocation["walltime"]
        if not isinstance(walltime, str) or not walltime.isascii():
            raise ValueError("invalid walltime")
        parts = walltime.split(":")
        if len(parts) != 3 or any(not part.isdecimal() for part in parts):
            raise ValueError("invalid walltime")
        hours, minutes, seconds = (int(part) for part in parts)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("source manifest allocation is malformed") from exc
    if not math.isfinite(memory) or minutes > 59 or seconds > 59:
        raise ValueError("source manifest allocation is malformed")
    wall_seconds = hours * 3600 + minutes * 60 + seconds
    if nodes < 1 or nodes > 1 or cpus < 1 or cpus > 8 or memory <= 0 or memory > 8 or wall_seconds <= 0 or wall_seconds > 1800:
        raise ValueError("source manifest allocation exceeds the public execution budget")


def validate_host_sources(tests: Path, app: Path, source_manifest: dict,
                          execution_sources: dict) -> None:
    sources = source_manifest.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("trusted source manifest lacks execution sources")
    audited_execution_sources = {name: digest for name, digest in execution_sources.items()
                                 if name != "source-manifest.json"}
    if audited_execution_sources != sources:
        raise ValueError("trusted source manifest does not exactly match audited execution sources")
    reference_hashes = json.loads((tests / "reference-hashes.json").read_text(encoding="utf-8"))
    for name, digest in sources.items():
        if (not isinstance(name, str) or not name or Path(name).name != name
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or execution_sources.get(name) != digest):
            raise ValueError("trusted source manifest differs from execution source hashes")
        pinned_paths = [rel for rel, expected in reference_hashes.items()
                        if rel.startswith("tests/evidence/") and Path(rel).name == name and expected == digest]
        verified_path = False
        for rel in pinned_paths:
            rel_path = Path(rel)
            if (rel_path.is_absolute() or rel_path.as_posix() != rel or ".." in rel_path.parts
                    or rel_path.parts[:2] != ("tests", "evidence")):
                continue
            evidence_path = tests
            unsafe = False
            for part in rel_path.parts[1:]:
                evidence_path = evidence_path / part
                if evidence_path.is_symlink():
                    unsafe = True
                    break
            if not unsafe and evidence_path.is_file() and sha(evidence_path) == digest:
                verified_path = True
                break
        if not verified_path:
            raise ValueError(f"execution source bytes are not independently pinned: {name}")
        candidate_matches = [path for path in app.rglob(name)
                             if path.is_file() and not path.is_symlink()]
        if any(sha(path) != digest for path in candidate_matches):
            raise ValueError(f"candidate execution source differs from host-attested bytes: {name}")


def validate_host_receipt(candidate_receipt: dict, execution: dict, record: dict) -> None:
    trusted_receipt = execution.get("scheduler_receipt")
    candidate_fields = receipt_fields(candidate_receipt)
    trusted_fields = receipt_fields(trusted_receipt)
    for name in ("JobIDRaw", "Partition", "State", "ExitCode"):
        if (name not in candidate_fields or name not in trusted_fields
                or str(candidate_fields[name]) != str(trusted_fields[name])):
            raise ValueError(f"candidate scheduler receipt differs from trusted execution: {name}")
    if str(candidate_fields["JobIDRaw"]) != record["trusted_job_id"]:
        raise ValueError("candidate scheduler receipt differs from trusted job ID")
    for index, fields in enumerate((candidate_fields, trusted_fields)):
        tres = fields.get("AllocTRES") or fields.get("ReqTRES")
        if tres is None:
            if index == 1:
                raise ValueError("trusted scheduler receipt lacks resource accounting")
            continue
        entries = dict(part.split("=", 1) for part in str(tres).split(",") if "=" in part)
        try:
            cpus = int(entries.get("cpu", "0"))
            nodes = int(entries.get("node", "0"))
            memory_text = entries.get("mem", "0G").upper()
            memory = float(memory_text[:-1]) if memory_text.endswith("G") else float(memory_text[:-1]) / 1024 if memory_text.endswith("M") else float(memory_text)
        except ValueError as exc:
            raise ValueError("scheduler receipt resource accounting is malformed") from exc
        if (not math.isfinite(memory) or cpus < 1 or cpus > 8 or nodes < 1 or nodes > 1
                or memory <= 0 or memory > 8):
            raise ValueError("scheduler receipt exceeds the public resource budget")
    if canonical_sha(candidate_receipt) != record["accounting_evidence_sha256"]:
        raise ValueError("scheduler accounting evidence hash differs from trusted review")


def candidate_manifest(app: Path) -> dict:
    root = app / "submission"
    if not root.is_dir():
        return {}
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"candidate output contains a symlink: {path.relative_to(app)}")
        if path.is_file():
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError(f"candidate output is not a regular file: {path.relative_to(app)}")
            result[path.relative_to(app).as_posix()] = {"sha256": sha(path), "bytes": path.stat().st_size}
        elif not path.is_dir():
            raise ValueError(f"candidate output contains a special file: {path.relative_to(app)}")
    return result


def native_manifest(submission: Path) -> dict:
    result = {}
    runs = submission / "runs"
    if not runs.is_dir():
        return result
    for path in sorted(runs.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"native output contains a symlink: {path.relative_to(submission)}")
        if path.is_file():
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError(f"native output is not a regular file: {path.relative_to(submission)}")
            result[path.relative_to(submission).as_posix()] = {"sha256": sha(path), "bytes": path.stat().st_size}
        elif not path.is_dir():
            raise ValueError(f"native output contains a special file: {path.relative_to(submission)}")
    return result


def expected_sources(tests: Path) -> dict:
    source_files = (
        "refs.json", "reference-hashes.json", "verification-plan.yaml",
        "verify.py", "review_status.py", "test.sh", "test_verifier_fixtures.py",
        "code-fingerprints.json",
    )
    result = {}
    for name in source_files:
        path = tests / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"trusted scoring source is missing or unsafe: {name}")
        result["tests/" + name] = sha(path)
    code_path = tests / "code-fingerprints.json"
    code = json.loads(code_path.read_text(encoding="utf-8"))
    if code.get("case_id") != CASE_ID or not isinstance(code.get("files"), dict) or not code["files"]:
        raise RuntimeError("trusted code-fingerprints.json has invalid identity or files")
    for name, expected in code["files"].items():
        if not isinstance(name, str) or not isinstance(expected, str) or len(expected) != 64:
            raise RuntimeError("trusted code fingerprint entry is malformed")
    result.update({"code/" + name: value for name, value in code["files"].items()})
    return result


def trusted_inputs(app: Path, tests: Path) -> dict:
    refs = json.loads((tests / "refs.json").read_text(encoding="utf-8"))
    hashes = refs.get("input_hashes")
    if refs.get("task_package_id") != CASE_ID or not isinstance(hashes, dict):
        raise RuntimeError("trusted refs.json has invalid package identity or input hashes")
    for rel, expected in hashes.items():
        if not rel.startswith("environment/assets/") or ".." in Path(rel).parts:
            raise RuntimeError(f"trusted input path is unsafe: {rel}")
        path = app / rel
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"trusted public input is missing or stale: {rel}")
    reference_hashes_path = tests / "reference-hashes.json"
    reference_hashes = json.loads(reference_hashes_path.read_text(encoding="utf-8"))
    if not isinstance(reference_hashes, dict) or not reference_hashes:
        raise RuntimeError("trusted reference-hashes.json has invalid structure")
    for rel, expected in reference_hashes.items():
        parts = Path(rel).parts
        if not rel.startswith("tests/") or ".." in parts or not isinstance(expected, str) or len(expected) != 64:
            raise RuntimeError(f"trusted reference hash entry is malformed: {rel}")
        path = tests.joinpath(*parts[1:])
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"trusted reference evidence is missing or stale: {rel}")
    return hashes


def validate_record(record_path: Path, tests: Path, app: Path, candidate: dict) -> dict:
    if record_path.is_symlink() or not record_path.is_file():
        raise RuntimeError("trusted author-review record is unsafe")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise RuntimeError(f"trusted author-review record cannot be parsed: {exc}") from exc
    required_fields = (
        "trusted_job_id", "accounting_evidence_sha256", "native_evidence_sha256",
        "reviewer", "reviewed_on", "candidate_manifest", "source_fingerprints",
        "input_hashes", "criteria",
    )
    if not isinstance(record, dict) or record.get("version") != 1 or record.get("case_id") != CASE_ID:
        raise RuntimeError("trusted author-review record has invalid identity")
    if record.get("review_status") not in {"PASS", "FAIL"}:
        raise RuntimeError("trusted author-review record has invalid status")
    for field in required_fields:
        if field not in record:
            raise RuntimeError(f"trusted author-review record is missing {field}")
    for field in ("trusted_job_id", "reviewer", "reviewed_on"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise RuntimeError(f"trusted author-review record has empty {field}")
    for field in ("accounting_evidence_sha256", "native_evidence_sha256"):
        value = record[field]
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise RuntimeError(f"trusted author-review record has malformed {field}")
    criteria = record["criteria"]
    if not isinstance(criteria, dict) or set(criteria) != CRITERIA:
        raise RuntimeError("trusted author-review record does not cover every necessary criterion")
    validate_criterion_statuses(record["review_status"], criteria)
    if record["candidate_manifest"] != candidate:
        raise ValueError("author review is bound to different candidate output bytes")
    if record["input_hashes"] != trusted_inputs(app, tests):
        raise RuntimeError("author review is stale for public input hashes")
    if record["source_fingerprints"] != expected_sources(tests):
        raise RuntimeError("author review is stale for scoring or execution source code")
    submission = app / "submission"
    provenance = json.loads((submission / "remote-provenance.json").read_text(encoding="utf-8"))
    scheduler_receipt = provenance.get("scheduler_receipt")
    source_manifest_path = submission / "source-manifest.json"
    source_manifest = None
    if source_manifest_path.is_symlink():
        raise ValueError("candidate source manifest is unsafe")
    if source_manifest_path.is_file():
        source_manifest = provenance.get("source_manifest")
        if (not isinstance(source_manifest, dict)
                or json.loads(source_manifest_path.read_text(encoding="utf-8")) != source_manifest
                or provenance.get("source_manifest_sha256") != sha(source_manifest_path)):
            raise ValueError("candidate source manifest differs from provenance")
    source_files = expected_sources(tests)
    code_files = {
        "case08_remote.sh": source_files.get("code/packages/case-08-short-md-stop-go/solution/case08_remote.sh"),
        "case08_tools.py": source_files.get("code/packages/case-08-short-md-stop-go/solution/case08_tools.py"),
    }
    host_attested = False
    if record["trusted_job_id"] == "3968344":
        if source_manifest is None:
            raise ValueError("legacy execution review requires its candidate source manifest")
        execution_path = tests / "evidence" / "verified-execution-3968344.json"
        reference_hashes = json.loads((tests / "reference-hashes.json").read_text(encoding="utf-8"))
        if (execution_path.is_symlink() or not execution_path.is_file()
                or reference_hashes.get("tests/evidence/verified-execution-3968344.json") != sha(execution_path)):
            raise RuntimeError("trusted execution source record is missing or stale")
        execution = json.loads(execution_path.read_text(encoding="utf-8"))
        if (execution.get("schema") != "case08-verified-execution/v1"
                or execution.get("job_id") != "3968344"
                or execution.get("read_only_independent_host_audit") is not True):
            raise RuntimeError("trusted execution source record has invalid identity")
        execution_sources = execution.get("execution_sources")
        if not isinstance(execution_sources, dict):
            raise RuntimeError("trusted execution record lacks source fingerprints")
        audited_sources = {name: value for name, value in execution_sources.items()
                           if name != "source-manifest.json"}
        if source_manifest.get("sources") != audited_sources:
            raise ValueError("remote source manifest differs from the independently audited execution")
        if sha(source_manifest_path) != execution_sources.get("source-manifest.json"):
            raise ValueError("remote source manifest hash differs from the independently audited execution")
    elif record.get("execution_evidence_path") is not None:
        rel = record.get("execution_evidence_path")
        parts = Path(rel).parts if isinstance(rel, str) else ()
        if (not parts or parts[0] != "evidence" or ".." in parts or Path(rel).is_absolute()
                or Path(rel).as_posix() != rel):
            raise RuntimeError("trusted execution evidence path is unsafe")
        execution_path = tests
        for part in parts:
            execution_path = execution_path / part
            if execution_path.is_symlink():
                raise RuntimeError("trusted execution evidence path contains a symlink")
        reference_hashes = json.loads((tests / "reference-hashes.json").read_text(encoding="utf-8"))
        if (not execution_path.is_file()
                or reference_hashes.get("tests/" + rel) != sha(execution_path)):
            raise RuntimeError("trusted execution evidence is missing or stale")
        execution = json.loads(execution_path.read_text(encoding="utf-8"))
        if source_manifest is None:
            source_manifest = execution.get("source_manifest")
            if not isinstance(source_manifest, dict):
                raise ValueError("candidate source manifest is absent and trusted host attestation is unavailable")
            manifest_hash = canonical_sha(source_manifest)
            execution_sources = validate_execution_binding(execution, candidate, manifest_hash, record)
            if execution_sources.get("source-manifest.json") != manifest_hash:
                raise RuntimeError("trusted host source-manifest pin differs from canonical attestation")
            validate_host_sources(tests, app, source_manifest, execution_sources)
            validate_host_receipt(scheduler_receipt, execution, record)
            host_attested = True
            trusted_native = execution.get("native_manifest")
            if trusted_native is not None and trusted_native != native_manifest(submission):
                raise ValueError("candidate native output differs from trusted execution evidence")
        else:
            execution_sources = validate_execution_binding(
                execution, candidate, sha(source_manifest_path), record)
            audited_sources = {name: value for name, value in execution_sources.items()
                               if name != "source-manifest.json"}
            if (audited_sources != source_manifest.get("sources")
                    or execution_sources.get("source-manifest.json") != sha(source_manifest_path)):
                raise ValueError("remote source manifest differs from independently reviewed execution bytes")
    elif source_manifest is None:
        raise ValueError("candidate source manifest is absent and trusted host attestation is unavailable")
    elif source_manifest.get("sources") != code_files:
        raise ValueError("remote source manifest differs from the current reviewed execution code")
    expected_input_names = {Path(name).name: value for name, value in trusted_inputs(app, tests).items()}
    if source_manifest.get("inputs") != expected_input_names:
        raise ValueError("remote source manifest differs from trusted public input hashes")
    if source_manifest.get("run_plan") != {
        "labels": ["B-dt1fs", "B-dt2fs", "U-dt1fs", "U-dt2fs"],
        "max_ps_each": 50, "max_total_ps": 200, "dt_fs": [1, 2],
    }:
        raise ValueError("remote source manifest differs from the bounded four-run plan")
    if record["trusted_job_id"] == "3968344":
        if source_manifest.get("allocation") != {
            "host": "ikkem", "partition": "cpu", "nodes": 1,
            "cpus": 8, "memory_gib": 8, "walltime": "00:30:00",
        }:
            raise ValueError("remote source manifest differs from the authorized allocation")
    else:
        validate_bounded_allocation(source_manifest.get("allocation"))
    native = native_manifest(submission)
    if record["trusted_job_id"] != str(provenance.get("job_id", "")):
        raise ValueError("author review job ID differs from candidate provenance")
    scheduler_fields = receipt_fields(scheduler_receipt)
    if str(scheduler_fields.get("JobIDRaw", "")) != record["trusted_job_id"]:
        raise ValueError("candidate scheduler receipt differs from trusted job ID")
    if canonical_sha(scheduler_receipt) != record["accounting_evidence_sha256"]:
        raise ValueError("scheduler accounting evidence hash differs from trusted review")
    if canonical_sha(native) != record["native_evidence_sha256"]:
        raise ValueError("native evidence hash differs from trusted review")
    provenance_fields = provenance.get("fields", {})
    if not isinstance(provenance_fields, dict):
        raise ValueError("candidate provenance fields are malformed")
    for name in ("accounting_evidence_sha256", "native_evidence_sha256", "native_manifest"):
        if name in provenance and name in provenance_fields and provenance[name] != provenance_fields[name]:
            raise ValueError(f"candidate provenance has conflicting flat and nested {name}")
    provenance_accounting = provenance.get("accounting_evidence_sha256", provenance_fields.get("accounting_evidence_sha256"))
    provenance_native_hash = provenance.get("native_evidence_sha256", provenance_fields.get("native_evidence_sha256"))
    provenance_native = provenance.get("native_manifest", provenance_fields.get("native_manifest"))
    if not host_attested and provenance_accounting != record["accounting_evidence_sha256"]:
        raise ValueError("candidate accounting hash differs from trusted review")
    if host_attested and provenance_accounting is not None and provenance_accounting != record["accounting_evidence_sha256"]:
        raise ValueError("candidate accounting hash differs from trusted review")
    if (not host_attested and (provenance_native != native
                              or provenance_native_hash != record["native_evidence_sha256"])):
        raise ValueError("candidate native manifest differs from trusted review")
    if (host_attested and ((provenance_native is not None and provenance_native != native)
                           or (provenance_native_hash is not None
                               and provenance_native_hash != record["native_evidence_sha256"]))):
        raise ValueError("candidate native manifest differs from trusted review")
    return record


def run_case(app: Path, tests: Path, logs: Path) -> int:
    sys.path.insert(0, str(tests))
    try:
        import verify
        inputs = trusted_inputs(app, tests)
        legacy_record_path = tests / "author-review.json"
        if legacy_record_path.is_symlink():
            raise RuntimeError("trusted author-review record is a symlink")
        if legacy_record_path.is_file():
            try:
                record_identity = json.loads(legacy_record_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeError) as exc:
                raise RuntimeError(f"trusted author-review record cannot be parsed: {exc}") from exc
            if (not isinstance(record_identity, dict) or record_identity.get("version") != 1
                    or record_identity.get("case_id") != CASE_ID
                    or record_identity.get("review_status") not in {"PASS", "FAIL"}):
                raise RuntimeError("trusted author-review record has invalid identity/status")
        try:
            checks = verify.check_candidate(app, tests)
            candidate = candidate_manifest(app)
        except (OSError, ValueError, UnicodeError, TypeError, KeyError, IndexError) as exc:
            checks = {"state": "FAIL", "checks": [],
                      "failures": [f"candidate artifacts cannot be parsed safely: {type(exc).__name__}: {exc}"],
                      "warnings": []}
            candidate = {}
        report = {
            "schema": "compchembench.case-verification/v1", "case_id": CASE_ID,
            "status": "REVIEW_REQUIRED", "reward": None,
            "candidate_checks": checks,
            "candidate_manifest": candidate,
            "input_hashes": inputs,
            "message": "Scientific outcome and execution origin require private author review; test evidence and archived references do not issue reward.",
        }
        if checks.get("failures"):
            report.update(status="FAIL", reward=0,
                          message="Candidate artifacts contradict a deterministic input/native-output requirement.")
        elif not candidate:
            report.update(status="FAIL", reward=0,
                          message="No candidate submission artifacts were provided.")
        else:
            record_path = review_record_path(tests, candidate)
            if record_path.is_symlink():
                raise RuntimeError("candidate-addressed author-review record is a symlink")
            if record_path.exists():
                try:
                    record = validate_record(record_path, tests, app, candidate)
                except ValueError as exc:
                    report["review_note"] = str(exc)
                except RuntimeError as exc:
                    report.update(status="INFRA_ERROR", reward=None,
                                  message=f"Trusted author-review source failed: {exc}")
                else:
                    report["status"] = record["review_status"]
                    report["reward"] = 1 if record["review_status"] == "PASS" else 0
                    report["reward_status"] = "AWARDED" if record["review_status"] == "PASS" else "REVIEWED_FAIL"
                    report["message"] = ("Scientific author review passed for this candidate and trusted execution."
                                          if record["review_status"] == "PASS" else
                                          "Scientific author review found a failed necessary criterion.")
                    report["scientific_review"] = {
                        "reviewer": record["reviewer"], "reviewed_on": record["reviewed_on"],
                        "trusted_job_id": record["trusted_job_id"], "criteria": record["criteria"],
                    }
        code = 2 if report["status"] == "INFRA_ERROR" else (1 if report["status"] == "FAIL" else 0)
    except Exception as exc:
        report = {"schema": "compchembench.case-verification/v1", "case_id": CASE_ID,
                  "status": "INFRA_ERROR", "reward": None,
                  "message": f"Verifier or trusted review source failed: {type(exc).__name__}: {exc}"}
        code = 2
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    reward = logs / "reward.txt"
    if report.get("status") in {"PASS", "FAIL"}:
        reward.write_text(str(report["reward"]) + "\n", encoding="utf-8")
    elif reward.exists():
        reward.unlink()
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, default=Path(os.environ.get("APP", "/app")))
    parser.add_argument("--tests", type=Path, default=Path(os.environ.get("TESTS", "/tests")))
    parser.add_argument("--logs", type=Path, default=Path(os.environ.get("LOGS", "/logs/verifier")))
    args = parser.parse_args()
    return run_case(args.app, args.tests, args.logs)


if __name__ == "__main__":
    raise SystemExit(main())
