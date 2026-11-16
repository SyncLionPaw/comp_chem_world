"""Optional evaluator-side method-neutral Case07 narrative review.

This assessment is separate from execution provenance and is stored outside the
candidate's final tree. Missing review is pending; a bad binding is ENV_INVALID.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

import fresh_evidence

CASE_ID = "case-07-independent-saddle-point-recomputation"
DEFINITION_REVISION = "2.1"
CRITERIA = ("budgeted_scientific_decisions", "reference_comparison_and_uncertainty")
CRITERIA_SHA256 = fresh_evidence.canonical_sha256({
    "case_id": CASE_ID, "definition_revision": DEFINITION_REVISION, "criteria": list(CRITERIA)})
NATIVE_CRITERIA = ("native_outputs_internally_consistent", "saddle_connects_the_claimed_pair")
NATIVE_CRITERIA_SHA256 = fresh_evidence.canonical_sha256({
    "case_id": CASE_ID, "definition_revision": DEFINITION_REVISION,
    "criteria": list(NATIVE_CRITERIA), "scope": "unsupported-native-route-only-v3"})
RESOURCE_CRITERIA = ("resource_envelope_respected",)
RESOURCE_CRITERIA_SHA256 = fresh_evidence.canonical_sha256({
    "case_id": CASE_ID, "definition_revision": DEFINITION_REVISION,
    "criteria": list(RESOURCE_CRITERIA), "scope": "missing-measurements-only-v1"})


class ReviewEnvironmentError(ValueError):
    pass


def _read(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ReviewEnvironmentError("trusted scientific review path is unsafe")
    try:
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ReviewEnvironmentError("trusted review has duplicate JSON keys")
                result[key] = value
            return result
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewEnvironmentError(f"trusted scientific review cannot be read: {exc}") from exc
    if not isinstance(value, dict):
        raise ReviewEnvironmentError("trusted scientific review must be a JSON object")
    return value


def assess(final: Path, tests: Path, report: dict, receipt_attempt_id: str) -> dict:
    path = Path(os.environ.get("CCB_CASE07_REVIEW_ASSESSMENT_PATH",
                              str(tests / "protected" / "independent-review.json")))
    if not path.exists():
        return {"status": "REVIEW_REQUIRED", "reason": "independent scientific review has not been recorded",
                "criteria": {name: "REVIEW_REQUIRED" for name in CRITERIA}}
    if path.resolve().is_relative_to(final.resolve()):
        raise ReviewEnvironmentError("scientific review must be evaluator-side, outside final/")
    item = _read(path)
    if item.get("status") == "PENDING":
        return {"status": "REVIEW_REQUIRED", "reason": item.get("note", "independent scientific review is pending"),
                "criteria": {name: "REVIEW_REQUIRED" for name in CRITERIA}}
    required = {"schema", "case_id", "definition_revision", "scientific_criteria_sha256", "attempt_id",
                "report_sha256", "artifact_manifest_sha256", "reviewer_id", "reviewed_at_utc", "criteria"}
    if set(item) != required or item.get("schema") != "case07-independent-review/v2":
        raise ReviewEnvironmentError("trusted scientific review schema is invalid")
    report_path = final / "ts_search_report.json"
    manifest = fresh_evidence._manifest_from_disk(final)
    expected = {
        "case_id": CASE_ID,
        "definition_revision": DEFINITION_REVISION,
        "scientific_criteria_sha256": CRITERIA_SHA256,
        "attempt_id": receipt_attempt_id,
        "report_sha256": fresh_evidence.file_sha256(report_path),
        "artifact_manifest_sha256": fresh_evidence.canonical_sha256(manifest),
    }
    for key, value in expected.items():
        if item.get(key) != value:
            raise ReviewEnvironmentError(f"trusted scientific review {key} does not bind current attempt")
    if not isinstance(item.get("reviewer_id"), str) or not item["reviewer_id"].strip():
        raise ReviewEnvironmentError("trusted scientific review lacks reviewer identity")
    try:
        fresh_evidence._parse_utc(item.get("reviewed_at_utc"))
    except (ValueError, TypeError) as exc:
        raise ReviewEnvironmentError("trusted scientific review timestamp is invalid") from exc
    criteria = item.get("criteria")
    if not isinstance(criteria, dict) or set(criteria) != set(CRITERIA):
        raise ReviewEnvironmentError("trusted scientific review criteria set is incomplete")
    statuses = {}
    for name in CRITERIA:
        entry = criteria[name]
        if (not isinstance(entry, dict) or set(entry) != {"status", "reason", "evidence_paths"}
                or entry.get("status") not in {"PASS", "FAIL"}
                or not isinstance(entry.get("reason"), str) or not entry["reason"].strip()
                or not isinstance(entry.get("evidence_paths"), list) or not entry["evidence_paths"]):
            raise ReviewEnvironmentError(f"trusted scientific review criterion is invalid: {name}")
        for relative in entry["evidence_paths"]:
            if not isinstance(relative, str) or relative.startswith("/") or ".." in Path(relative).parts:
                raise ReviewEnvironmentError(f"trusted scientific review evidence path is unsafe: {name}")
            target = final / relative
            if not target.is_file() or target.is_symlink():
                raise ReviewEnvironmentError(f"trusted scientific review evidence is missing: {relative}")
        statuses[name] = entry["status"]
    return {"status": "PASS", "reason": f"independent review by {item['reviewer_id']} is bound to the exact submission",
            "criteria": statuses}


def assess_native(final: Path, tests: Path, report: dict, receipt_attempt_id: str,
                  unsupported: BaseException, execution_audit: dict) -> dict:
    """Read an evaluator-side scientific review for UnsupportedEvidence only.

    This can resolve the two native-parser REVIEW_REQUIRED criteria. It cannot
    override an execution/resource failure, any criterion FAIL, or either v2
    narrative review criterion.
    """
    path = Path(os.environ.get("CCB_CASE07_NATIVE_REVIEW_PATH",
                              str(tests / "protected" / "native-review-v3.json")))
    pending = {name: "REVIEW_REQUIRED" for name in NATIVE_CRITERIA}
    if not path.exists():
        return {"status": "REVIEW_REQUIRED", "reason": "protected unsupported-route review is pending",
                "criteria": pending}
    if path.resolve().is_relative_to(final.resolve()):
        raise ReviewEnvironmentError("native review must be evaluator-side, outside final/")
    if execution_audit.get("status") != "PASS":
        return {"status": "REVIEW_REQUIRED", "reason": "execution receipt has not passed internal cross-checks",
                "criteria": pending}
    item = _read(path)
    required = {"schema", "case_id", "definition_revision", "criteria_sha256", "attempt_id",
                "report_sha256", "artifact_manifest_sha256", "reviewer_id", "reviewed_at_utc",
                "unsupported_evidence", "method", "engine", "route", "criteria"}
    if set(item) != required or item.get("schema") != "case07-native-review/v3":
        raise ReviewEnvironmentError("protected native review v3 schema is invalid")
    manifest = fresh_evidence._manifest_from_disk(final)
    expected = {"case_id": CASE_ID, "definition_revision": DEFINITION_REVISION,
                "criteria_sha256": NATIVE_CRITERIA_SHA256, "attempt_id": receipt_attempt_id,
                "report_sha256": fresh_evidence.file_sha256(final / "ts_search_report.json"),
                "artifact_manifest_sha256": fresh_evidence.canonical_sha256(manifest),
                "method": report.get("final_level"), "engine": report.get("engine")}
    for key, value in expected.items():
        if item.get(key) != value:
            raise ReviewEnvironmentError(f"protected native review {key} does not bind this attempt")
    if not isinstance(item.get("reviewer_id"), str) or not item["reviewer_id"].strip():
        raise ReviewEnvironmentError("protected native review lacks reviewer identity")
    try:
        fresh_evidence._parse_utc(item.get("reviewed_at_utc"))
    except (ValueError, TypeError) as exc:
        raise ReviewEnvironmentError("protected native review timestamp is invalid") from exc
    exception = item.get("unsupported_evidence")
    expected_exception = {"class": type(unsupported).__name__, "message": str(unsupported)}
    if exception != expected_exception or type(unsupported).__name__ != "UnsupportedEvidence":
        raise ReviewEnvironmentError("protected native review is not bound to the actual UnsupportedEvidence")
    if (not isinstance(item.get("route"), str) or not item["route"].strip()
            or item["route"] != report.get("native_route")):
        raise ReviewEnvironmentError("protected native review route does not match the candidate declaration")
    criteria = item.get("criteria")
    if not isinstance(criteria, dict) or set(criteria) != set(NATIVE_CRITERIA):
        raise ReviewEnvironmentError("protected native review criteria are incomplete")
    statuses = {}
    for name in NATIVE_CRITERIA:
        entry = criteria[name]
        if (not isinstance(entry, dict) or set(entry) != {"status", "reason", "evidence_paths", "scientific_basis", "checks"}
                or entry.get("status") not in {"PASS", "FAIL"}
                or not isinstance(entry.get("reason"), str) or not entry["reason"].strip()
                or not isinstance(entry.get("scientific_basis"), str) or not entry["scientific_basis"].strip()
                or not isinstance(entry.get("checks"), list) or not entry["checks"]
                or any(not isinstance(x, str) or not x.strip() for x in entry["checks"])
                or not isinstance(entry.get("evidence_paths"), list) or not entry["evidence_paths"]):
            raise ReviewEnvironmentError(f"protected native review criterion is malformed: {name}")
        for relative in entry["evidence_paths"]:
            if (not isinstance(relative, str) or relative.startswith("/")
                    or ".." in Path(relative).parts or relative not in manifest
                    or not relative.startswith("native_outputs/")):
                raise ReviewEnvironmentError(f"protected native review path is unsafe or not in the exact manifest: {relative}")
        statuses[name] = entry["status"]
    return {"status": "PASS" if all(v == "PASS" for v in statuses.values()) else "FAIL",
            "reason": f"unsupported route independently reviewed by {item['reviewer_id']}",
            "criteria": statuses}


def assess_resources(final: Path, tests: Path, report: dict, receipt_attempt_id: str,
                     source_manifest_sha256: str | None = None, *, native_slurm: bool = False) -> dict:
    """Resolve evaluator-owned resource evidence without promoting candidate hashes."""
    path = Path(os.environ.get("CCB_CASE07_RESOURCE_REVIEW_PATH",
                              str(tests / "protected" / "resource-review.json")))
    pending = {"resource_envelope_respected": "REVIEW_REQUIRED"}
    if not path.exists():
        return {"status": "REVIEW_REQUIRED", "reason": "protected resource review is pending",
                "criteria": pending}
    if path.resolve().is_relative_to(final.resolve()):
        raise ReviewEnvironmentError("resource review must be evaluator-side, outside final/")
    item = _read(path)
    if item.get("status") == "PENDING":
        if set(item) != {"schema", "status"} or item.get("schema") != "case07-resource-review/v1":
            raise ReviewEnvironmentError("protected resource review pending schema is invalid")
        return {"status": "REVIEW_REQUIRED", "reason": "protected resource review is pending",
                "criteria": pending}
    required = {"schema", "case_id", "definition_revision", "resource_criteria_sha256", "attempt_id",
                "report_sha256", "artifact_manifest_sha256", "source_manifest_sha256", "reviewer_id",
                "reviewed_at_utc", "status", "reason", "evidence_summary"}
    expected_schema = "case07-resource-review/v2" if native_slurm else "case07-resource-review/v1"
    if native_slurm and item.get("schema") == "case07-resource-review/v1":
        return {"status": "REVIEW_REQUIRED", "reason": "native Slurm source/attempt/resource preflight is not reviewed",
                "criteria": pending}
    if native_slurm:
        required |= {"native_slurm_preflight", "verifier_source_sha256"}
    if set(item) != required or item.get("schema") != expected_schema:
        raise ReviewEnvironmentError("protected resource review schema is invalid")
    if native_slurm:
        source_files = {path.relative_to(tests).as_posix(): fresh_evidence.file_sha256(path)
                        for path in tests.rglob("*")
                        if path.is_file() and (path.suffix == ".py" or path == tests / "refs.json")}
        if item.get("verifier_source_sha256") != fresh_evidence.canonical_sha256(source_files):
            raise ReviewEnvironmentError("native Slurm review does not bind the current verifier source")
        gates = item.get("native_slurm_preflight")
        required_gates = {"native_source_authenticated", "complete_attempt_jobs_verified",
                          "stage_job_bindings_verified", "concurrent_cpu_memory_scratch_verified",
                          "allocated_core_hours_verified", "wall_time_and_queue_credit_verified"}
        if (not isinstance(gates, dict) or set(gates) != required_gates
                or any(type(value) is not bool for value in gates.values())):
            raise ReviewEnvironmentError("native Slurm independent preflight is incomplete")
        if item.get("status") == "PASS" and not all(gates.values()):
            return {"status": "REVIEW_REQUIRED", "reason": "native Slurm attempt/source/resource evidence remains unverified",
                    "criteria": pending}
    manifest = fresh_evidence._manifest_from_disk(final)
    expected = {"case_id": CASE_ID, "definition_revision": DEFINITION_REVISION,
                "resource_criteria_sha256": RESOURCE_CRITERIA_SHA256,
                "attempt_id": receipt_attempt_id,
                "report_sha256": fresh_evidence.file_sha256(final / "ts_search_report.json"),
                "artifact_manifest_sha256": fresh_evidence.canonical_sha256(manifest)}
    if source_manifest_sha256 is not None:
        expected["source_manifest_sha256"] = source_manifest_sha256
    for key, value in expected.items():
        if item.get(key) != value:
            raise ReviewEnvironmentError(f"protected resource review {key} does not bind current attempt")
    if (not isinstance(item.get("source_manifest_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["source_manifest_sha256"])):
        raise ReviewEnvironmentError("protected resource review source manifest digest is invalid")
    if not isinstance(item.get("reviewer_id"), str) or not item["reviewer_id"].strip():
        raise ReviewEnvironmentError("protected resource review lacks reviewer identity")
    if item.get("status") not in {"PASS", "FAIL"}:
        raise ReviewEnvironmentError("protected resource review status is invalid")
    if not isinstance(item.get("reason"), str) or not item["reason"].strip():
        raise ReviewEnvironmentError("protected resource review reason is invalid")
    try:
        fresh_evidence._parse_utc(item.get("reviewed_at_utc"))
    except (ValueError, TypeError) as exc:
        raise ReviewEnvironmentError("protected resource review timestamp is invalid") from exc
    summary = item.get("evidence_summary")
    if (not isinstance(summary, dict) or set(summary) != {"observed", "enforced", "unknown"}
            or any(not isinstance(summary[key], list)
                   or not summary[key]
                   or any(not isinstance(value, str) or not value.strip() for value in summary[key])
                   for key in summary)):
        raise ReviewEnvironmentError("protected resource review must state observed, enforced, and unknown evidence")
    return {"status": item["status"], "reason": item["reason"],
            "criteria": {"resource_envelope_respected": item["status"]}}
