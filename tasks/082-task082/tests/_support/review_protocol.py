"""Trusted, digest-bound science-review protocol for case 07.

The review is supplied by the runner through a trusted path and digest. A
candidate's provenance and report fields cannot create or change this review.
"""
from __future__ import annotations

import hashlib
import json
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

SCHEMA = "bench12.case07.trusted-science-review/v1"
CASE_ID = "case-07-cof-excited-state-screening"
POLICY_VERSION = "case07-independent-review/v1"
CRITERIA = (
    "structure_and_fixed_model",
    "optimizer_and_native_termination",
    "force_and_model_error_budget",
    "state_identity_continuity",
    "native_screening_consistency_and_paper_comparison",
    "measured_costs_and_failures",
    "screening_verdict_supported",
)
REQUIRED_EVIDENCE_KINDS = {
    "structure_and_fixed_model": {"source_structure", "stage_input", "native_output", "runtime"},
    "optimizer_and_native_termination": {"stage_input", "native_output", "trajectory", "final_geometry"},
    "force_and_model_error_budget": {"control", "native_output", "report"},
    "state_identity_continuity": {"native_output", "trajectory", "spectrum"},
    "native_screening_consistency_and_paper_comparison": {"native_output", "spectrum", "table", "report"},
    "measured_costs_and_failures": {"sacct", "cost_summary", "native_output"},
    "screening_verdict_supported": {"spectrum", "cost_summary", "threshold_basis", "report"},
}
HEX = re.compile(r"[0-9a-f]{64}\Z")
MAX_REVIEW_BYTES = 2 * 1024 * 1024
RUN_MANIFEST_SCHEMA = "bench12.case07.trusted-run-manifest/v1"
PRODUCTION_STAGES = {
    "gs_optimization", "full_spectrum", "stda_spectrum",
    "full_s1_optimization", "stda_s1_optimization",
}
TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "PREEMPTED",
                   "OUT_OF_MEMORY", "NODE_FAIL", "BOOT_FAIL", "DEADLINE"}


class ReviewEnvironmentError(ValueError):
    """Trusted review material or runner setup is invalid."""


class ReviewStaleError(ValueError):
    """Trusted review is valid but does not bind the current candidate run."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _finite_float(token: str) -> float:
    value = float(token)
    if not __import__("math").isfinite(value):
        raise ValueError("nonfinite JSON number")
    return value


def _read_trusted(path_text: str | None, expected_sha: str | None,
                  app_root: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path_text and not expected_sha:
        return None, None
    if not path_text or not expected_sha:
        raise ReviewEnvironmentError("trusted review path and SHA-256 pin must be configured together")
    if not HEX.fullmatch(expected_sha):
        raise ReviewEnvironmentError("trusted review SHA-256 pin is malformed")
    path = Path(path_text)
    if not path.is_absolute():
        raise ReviewEnvironmentError("trusted review path must be absolute")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            item = current.lstat()
        except OSError:
            raise ReviewEnvironmentError("trusted review file is unavailable") from None
        if stat.S_ISLNK(item.st_mode):
            raise ReviewEnvironmentError("trusted review path contains a symlink")
    try:
        final = path.resolve(strict=True)
        final.relative_to(app_root.resolve(strict=True))
    except ValueError:
        pass
    except OSError:
        raise ReviewEnvironmentError("trusted review file is unavailable") from None
    else:
        raise ReviewEnvironmentError("trusted review must be outside candidate APP")
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise ReviewEnvironmentError("trusted review must be a regular file")
        if path.stat().st_size <= 0 or path.stat().st_size > MAX_REVIEW_BYTES:
            raise ReviewEnvironmentError("trusted review size is outside the supported bound")
        data = path.read_bytes()
    except ReviewEnvironmentError:
        raise
    except OSError:
        raise ReviewEnvironmentError("trusted review file is unavailable") from None
    actual = _sha256(data)
    if actual != expected_sha:
        raise ReviewEnvironmentError("trusted review bytes do not match runner SHA-256 pin")
    try:
        value = json.loads(data, object_pairs_hook=_unique_pairs,
                           parse_float=_finite_float,
                           parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError):
        raise ReviewEnvironmentError("trusted review is not valid finite UTF-8 JSON") from None
    if not isinstance(value, dict):
        raise ReviewEnvironmentError("trusted review root must be an object")
    return value, actual


def load_runner_manifest(*, app_root: Path, path_text: str | None,
                         expected_sha: str | None,
                         artifact_index: dict[str, dict[str, Any]],
                         artifact_manifest_sha256: str,
                         criteria_version: str | None = None,
                         production_native_refs: dict[str, dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Validate externally pinned Slurm records and recompute parent CPU cost."""
    value, digest = _read_trusted(path_text, expected_sha, app_root)
    if value is None:
        return None
    keys = {"schema", "case_id", "run_id", "criteria_version",
            "artifact_manifest_sha256", "attempts"}
    if set(value) != keys or value.get("schema") != RUN_MANIFEST_SCHEMA or value.get("case_id") != CASE_ID:
        raise ReviewEnvironmentError("trusted runner manifest schema or fields are invalid")
    if not isinstance(value.get("run_id"), str) or not value["run_id"].strip():
        raise ReviewEnvironmentError("trusted runner manifest run_id is malformed")
    if not isinstance(value.get("criteria_version"), str) or not value["criteria_version"].strip():
        raise ReviewEnvironmentError("trusted runner manifest criteria_version is malformed")
    if criteria_version is not None and value["criteria_version"] != criteria_version:
        raise ReviewStaleError("trusted runner manifest uses a different criteria_version")
    if value["artifact_manifest_sha256"] != artifact_manifest_sha256:
        raise ReviewStaleError("trusted runner manifest does not bind the current complete final artifact tree")
    attempts = value.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise ReviewEnvironmentError("trusted runner manifest attempts must be a nonempty array")
    rows = []
    seen_jobs: set[str] = set()
    successful_production_stages: set[str] = set()
    costs_by_stage: dict[str, int] = {}
    total_cpu_seconds = 0
    for index, item in enumerate(attempts):
        expected_item_keys = {"stage", "job_id", "state", "elapsed_raw_seconds", "alloc_cpus",
                              "exit_code", "attempt_class", "native_ref", "sacct_ref"}
        if not isinstance(item, dict) or set(item) != expected_item_keys:
            raise ReviewEnvironmentError(f"runner manifest attempts[{index}] fields are invalid")
        stage, job_id = item["stage"], item["job_id"]
        if not isinstance(stage, str) or not stage:
            raise ReviewEnvironmentError(f"runner manifest attempts[{index}] stage is invalid")
        rejected_before_job = (job_id is None and item["state"] == "REJECTED_BEFORE_JOB_CREATION" and
                               item["elapsed_raw_seconds"] == 0 and item["alloc_cpus"] == 0 and
                               item["exit_code"] == "N/A" and item["native_ref"] is None and
                               item["sacct_ref"] is None and item["attempt_class"] in ("diagnostic", "failed"))
        if not rejected_before_job:
            if not isinstance(job_id, str) or not re.fullmatch(r"\d+", job_id):
                raise ReviewEnvironmentError(f"runner manifest attempts[{index}] job ID is invalid")
            if job_id in seen_jobs:
                raise ReviewEnvironmentError("runner manifest repeats a Slurm parent job ID")
            seen_jobs.add(job_id)
        if not rejected_before_job and item["state"] not in TERMINAL_STATES:
            raise ReviewEnvironmentError(f"runner manifest attempts[{index}] is not terminal")
        elapsed, cpus = item["elapsed_raw_seconds"], item["alloc_cpus"]
        if type(elapsed) is not int or elapsed < 0 or type(cpus) is not int or (cpus < 1 and not rejected_before_job):
            raise ReviewEnvironmentError(f"runner manifest attempts[{index}] resource fields are invalid")
        exit_code = item["exit_code"]
        if not rejected_before_job and (not isinstance(exit_code, str) or not re.fullmatch(r"\d+:\d+", exit_code)):
            raise ReviewEnvironmentError(f"runner manifest attempts[{index}] exit_code is malformed")
        if item["attempt_class"] not in ("production", "diagnostic", "retry", "failed"):
            raise ReviewEnvironmentError(f"runner manifest attempts[{index}] attempt_class is invalid")
        refs = {}
        for label in (() if rejected_before_job else ("native_ref", "sacct_ref")):
            ref = item[label]
            if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"} or
                    not isinstance(ref.get("path"), str) or not HEX.fullmatch(str(ref.get("sha256", "")))):
                raise ReviewEnvironmentError(f"runner manifest attempts[{index}] {label} is malformed")
            artifact = artifact_index.get(ref["path"])
            if artifact is None or artifact.get("sha256") != ref["sha256"]:
                raise ReviewStaleError(f"runner manifest attempts[{index}] {label} is not bound to the current final tree")
            refs[label] = ref
        if rejected_before_job:
            cpu_seconds = 0
            total_cpu_seconds += cpu_seconds
            costs_by_stage[stage] = costs_by_stage.get(stage, 0)
            rows.append({"stage": stage, "job_id": None, "state": item["state"],
                         "attempt_class": item["attempt_class"], "elapsed_raw_seconds": 0,
                         "alloc_cpus": 0, "allocated_cpu_seconds": 0,
                         "native_ref": None, "sacct_ref": None,
                         "rejection_receipt": "runner-manifest-recorded; no Slurm job created"})
            continue
        raw = artifact_index[refs["sacct_ref"]["path"]].get("bytes_data")
        if not isinstance(raw, bytes):
            raise ReviewEnvironmentError(f"runner manifest attempts[{index}] sacct artifact is unavailable")
        try:
            reader = csv.DictReader(raw.decode("utf-8").splitlines(), delimiter="|")
            headers = reader.fieldnames or []
            jid_field = "JobIDRaw" if "JobIDRaw" in headers else "JobID" if "JobID" in headers else None
            if (jid_field is None or headers.count(jid_field) != 1 or
                    any(headers.count(column) != 1 for column in ("State", "ElapsedRaw", "AllocCPUS", "ExitCode")) or
                    ("JobIDRaw" in headers and "JobID" in headers)):
                raise ValueError("required parent fields missing or duplicated")
            sacct_rows = list(reader)
        except (UnicodeDecodeError, csv.Error, ValueError):
            raise ReviewEnvironmentError(f"runner manifest attempts[{index}] sacct table is malformed") from None
        for raw_row in sacct_rows:
            row_id = raw_row.get(jid_field)
            if not isinstance(row_id, str) or not (row_id in {job_id, f"{job_id}.batch", f"{job_id}.extern"} or
                                                       re.fullmatch(re.escape(job_id) + r"\.\d+", row_id)):
                raise ReviewEnvironmentError(f"runner manifest attempts[{index}] sacct includes foreign rows")
        parent_rows = [row for row in sacct_rows if row.get(jid_field) == job_id]
        if len(parent_rows) != 1:
            raise ReviewEnvironmentError(f"runner manifest attempts[{index}] requires exactly one parent sacct row")
        parent = parent_rows[0]
        source = (parent.get("State"), parent.get("ElapsedRaw"), parent.get("AllocCPUS"), parent.get("ExitCode"))
        claim = (item["state"], str(elapsed), str(cpus), exit_code)
        if source != claim or not elapsed.__str__().isdecimal() or not cpus.__str__().isdecimal():
            raise ReviewEnvironmentError(f"runner manifest attempts[{index}] differs from parent sacct values")
        if stage in PRODUCTION_STAGES and item["attempt_class"] == "production":
            if item["state"] != "COMPLETED" or exit_code != "0:0":
                raise ReviewEnvironmentError(f"production stage {stage} did not complete successfully")
            if production_native_refs is not None:
                expected_ref = production_native_refs.get(stage)
                if expected_ref is None or refs["native_ref"] != expected_ref:
                    raise ReviewEnvironmentError(f"production stage {stage} native_ref does not match candidate provenance")
            successful_production_stages.add(stage)
        cpu_seconds = elapsed * cpus
        total_cpu_seconds += cpu_seconds
        costs_by_stage[stage] = costs_by_stage.get(stage, 0) + cpu_seconds
        rows.append({"stage": stage, "job_id": job_id, "state": item["state"],
                     "attempt_class": item["attempt_class"], "elapsed_raw_seconds": elapsed,
                     "alloc_cpus": cpus, "allocated_cpu_seconds": cpu_seconds,
                     "native_ref": refs["native_ref"], "sacct_ref": refs["sacct_ref"]})
    missing = sorted(PRODUCTION_STAGES - successful_production_stages)
    if missing:
        raise ReviewStaleError("trusted runner manifest lacks successful production stages: " + ", ".join(missing))
    production_costs: dict[str, int] = {}
    for row in rows:
        if row["attempt_class"] == "production":
            production_costs[row["stage"]] = production_costs.get(row["stage"], 0) + row["allocated_cpu_seconds"]
    return {"schema": RUN_MANIFEST_SCHEMA, "sha256": digest, "run_id": value["run_id"],
            "attempts": rows, "costs_by_stage_cpu_seconds": costs_by_stage,
            "production_cost_by_stage_cpu_seconds": production_costs,
            "total_allocated_cpu_seconds": total_cpu_seconds,
            "total_allocated_cpu_hours": total_cpu_seconds / 3600.0}


def _validate_review_shape(value: dict[str, Any]) -> None:
    expected = {
        "schema", "case_id", "criteria_version", "policy_version", "reviewer",
        "reviewed_at_utc", "run_id", "verifier_sha256", "automatic_core_sha256",
        "artifact_manifest_sha256", "runner_manifest_sha256", "criteria",
    }
    if set(value) != expected or value.get("schema") != SCHEMA or value.get("case_id") != CASE_ID:
        raise ReviewEnvironmentError("trusted review schema or top-level fields are invalid")
    if value.get("policy_version") != POLICY_VERSION:
        raise ReviewEnvironmentError("trusted review policy version is unsupported")
    reviewer = value.get("reviewer")
    if not isinstance(reviewer, dict) or set(reviewer) != {"id", "role"} or not all(
            isinstance(reviewer.get(k), str) and reviewer[k].strip() for k in ("id", "role")):
        raise ReviewEnvironmentError("trusted review reviewer identity is malformed")
    timestamp = value.get("reviewed_at_utc")
    try:
        parsed_timestamp = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if isinstance(timestamp, str) else None
    except ValueError:
        parsed_timestamp = None
    if parsed_timestamp is None:
        raise ReviewEnvironmentError("trusted review timestamp must be ISO-8601 UTC")
    if not isinstance(value.get("run_id"), str) or not value["run_id"].strip():
        raise ReviewEnvironmentError("trusted review run_id is malformed")
    for field in ("verifier_sha256", "automatic_core_sha256", "artifact_manifest_sha256", "runner_manifest_sha256"):
        if not isinstance(value.get(field), str) or not HEX.fullmatch(value[field]):
            raise ReviewEnvironmentError(f"trusted review {field} is malformed")
    criteria = value.get("criteria")
    if not isinstance(criteria, dict) or set(criteria) != set(CRITERIA):
        raise ReviewEnvironmentError("trusted review must assess every frozen science criterion exactly once")
    for criterion, row in criteria.items():
        if not isinstance(row, dict) or set(row) != {"status", "rationale", "evidence_refs", "findings"}:
            raise ReviewEnvironmentError(f"trusted review criterion shape is invalid: {criterion}")
        if row.get("status") not in ("PASS", "FAIL", "REVIEW_REQUIRED"):
            raise ReviewEnvironmentError(f"trusted review criterion status is invalid: {criterion}")
        if not isinstance(row.get("rationale"), str) or not row["rationale"].strip():
            raise ReviewEnvironmentError(f"trusted review criterion lacks rationale: {criterion}")
        refs = row.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            raise ReviewEnvironmentError(f"trusted review criterion lacks evidence references: {criterion}")
        kinds = set()
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {"path", "sha256", "line_start", "line_end", "kind"}:
                raise ReviewEnvironmentError(f"trusted review evidence ref shape is invalid: {criterion}")
            if not isinstance(ref["path"], str) or not ref["path"] or not HEX.fullmatch(str(ref["sha256"])):
                raise ReviewEnvironmentError(f"trusted review evidence ref identity is invalid: {criterion}")
            if type(ref["line_start"]) is not int or type(ref["line_end"]) is not int or ref["line_start"] < 1 or ref["line_end"] < ref["line_start"]:
                raise ReviewEnvironmentError(f"trusted review evidence line range is invalid: {criterion}")
            if not isinstance(ref["kind"], str) or not ref["kind"].strip():
                raise ReviewEnvironmentError(f"trusted review evidence kind is invalid: {criterion}")
            kinds.add(ref["kind"])
        if not REQUIRED_EVIDENCE_KINDS[criterion].issubset(kinds):
            raise ReviewEnvironmentError(f"trusted review lacks criterion-specific evidence kinds: {criterion}")
        _validate_findings(criterion, row["findings"])


def _finite_decimal(value: Any, label: str) -> Decimal:
    if not isinstance(value, str):
        raise ReviewEnvironmentError(f"trusted review {label} must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ReviewEnvironmentError(f"trusted review {label} is not numeric") from None
    if not number.is_finite():
        raise ReviewEnvironmentError(f"trusted review {label} must be finite")
    return number


def _nonempty_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ReviewEnvironmentError(f"trusted review {label} must be nonempty text")


def _validate_findings(criterion: str, value: Any) -> None:
    """Require criterion-specific evidence fields, not free-text all-PASS rows."""
    if not isinstance(value, dict):
        raise ReviewEnvironmentError(f"trusted review findings are missing: {criterion}")
    if criterion == "structure_and_fixed_model":
        keys = {"atom_count", "basis_function_count", "model_matches_task", "structure_identity_supported",
                "runtime_identity_supported", "summary"}
        if set(value) != keys or type(value["atom_count"]) is not int or type(value["basis_function_count"]) is not int:
            raise ReviewEnvironmentError("trusted structure/model findings are malformed")
        for key in ("model_matches_task", "structure_identity_supported", "runtime_identity_supported"):
            if type(value[key]) is not bool:
                raise ReviewEnvironmentError(f"trusted structure/model finding {key} must be boolean")
        _nonempty_text(value["summary"], "structure/model summary")
    elif criterion == "optimizer_and_native_termination":
        if set(value) != {"stages", "summary"} or not isinstance(value["stages"], dict) or set(value["stages"]) != PRODUCTION_STAGES:
            raise ReviewEnvironmentError("trusted optimizer findings must cover all five production stages")
        for stage, item in value["stages"].items():
            if not isinstance(item, dict) or set(item) != {"terminal", "converged", "endpoint_supported", "summary"}:
                raise ReviewEnvironmentError(f"trusted optimizer finding is malformed: {stage}")
            if any(type(item[k]) is not bool for k in ("terminal", "converged", "endpoint_supported")):
                raise ReviewEnvironmentError(f"trusted optimizer finding flags are malformed: {stage}")
            _nonempty_text(item["summary"], f"optimizer summary for {stage}")
        _nonempty_text(value["summary"], "optimizer summary")
    elif criterion == "force_and_model_error_budget":
        if set(value) != {"thresholds_predeclared", "accuracy_basis", "controls", "residual_risks"}:
            raise ReviewEnvironmentError("trusted force/error-budget findings are malformed")
        if type(value["thresholds_predeclared"]) is not bool:
            raise ReviewEnvironmentError("trusted threshold declaration flag must be boolean")
        _nonempty_text(value["accuracy_basis"], "accuracy basis")
        if not isinstance(value["controls"], list) or not value["controls"]:
            raise ReviewEnvironmentError("trusted force/error budget must include measured controls")
        for index, control in enumerate(value["controls"]):
            required = {"control_id", "applies_to", "observed_value", "uncertainty", "threshold", "margin", "unit", "evidence_note"}
            if not isinstance(control, dict) or set(control) != required:
                raise ReviewEnvironmentError(f"trusted control record is malformed at index {index}")
            for field in ("control_id", "applies_to", "unit", "evidence_note"):
                _nonempty_text(control[field], f"control {index} {field}")
            for field in ("observed_value", "uncertainty", "threshold", "margin"):
                number = _finite_decimal(control[field], f"control {index} {field}")
                if field in ("uncertainty", "threshold") and number < 0:
                    raise ReviewEnvironmentError(f"trusted control {index} {field} cannot be negative")
        if not isinstance(value["residual_risks"], list) or any(not isinstance(x, str) for x in value["residual_risks"]):
            raise ReviewEnvironmentError("trusted residual_risks must be a text array")
    elif criterion == "state_identity_continuity":
        if set(value) != {"kernels", "summary"} or not isinstance(value["kernels"], dict) or set(value["kernels"]) != {"FULL", "STDA"}:
            raise ReviewEnvironmentError("trusted state-identity findings must cover FULL and STDA")
        for kernel, item in value["kernels"].items():
            if not isinstance(item, dict) or set(item) != {"steps_reviewed", "identity_supported", "near_crossings", "summary"}:
                raise ReviewEnvironmentError(f"trusted state-identity record is malformed: {kernel}")
            if type(item["steps_reviewed"]) is not int or item["steps_reviewed"] < 1 or type(item["identity_supported"]) is not bool:
                raise ReviewEnvironmentError(f"trusted state-identity flags are malformed: {kernel}")
            if not isinstance(item["near_crossings"], list):
                raise ReviewEnvironmentError(f"trusted near_crossings must be a list: {kernel}")
            _nonempty_text(item["summary"], f"state-identity summary for {kernel}")
        _nonempty_text(value["summary"], "state-identity summary")
    elif criterion == "native_screening_consistency_and_paper_comparison":
        if set(value) != {"recomputed_table_matches", "native_delta_assessment", "zero_zero_disposition",
                          "paper_comparison_summary", "table_precision_assessment"}:
            raise ReviewEnvironmentError("trusted screening-consistency findings are malformed")
        if type(value["recomputed_table_matches"]) is not bool:
            raise ReviewEnvironmentError("trusted recomputed_table_matches must be boolean")
        for field in ("native_delta_assessment", "paper_comparison_summary", "table_precision_assessment"):
            _nonempty_text(value[field], field)
        if value["zero_zero_disposition"] not in ("unavailable", "supported", "not_reported"):
            raise ReviewEnvironmentError("trusted zero-zero disposition is invalid")
    elif criterion == "measured_costs_and_failures":
        if set(value) != {"stage_cpu_hours", "all_attempts_cpu_hours", "attempts_included", "ledger_matches"}:
            raise ReviewEnvironmentError("trusted measured-cost findings are malformed")
        if not isinstance(value["stage_cpu_hours"], dict) or set(value["stage_cpu_hours"]) != PRODUCTION_STAGES:
            raise ReviewEnvironmentError("trusted measured costs must report each production stage")
        for stage, hours in value["stage_cpu_hours"].items():
            if _finite_decimal(hours, f"{stage} CPU hours") < 0:
                raise ReviewEnvironmentError(f"trusted {stage} CPU hours cannot be negative")
        if _finite_decimal(value["all_attempts_cpu_hours"], "all attempts CPU hours") < 0:
            raise ReviewEnvironmentError("trusted all-attempt CPU hours cannot be negative")
        if type(value["attempts_included"]) is not int or value["attempts_included"] < 5 or type(value["ledger_matches"]) is not bool:
            raise ReviewEnvironmentError("trusted cost-attempt findings are malformed")
    elif criterion == "screening_verdict_supported":
        if set(value) != {"conclusion", "thresholds_predeclared_before_comparison", "spectral_basis", "total_cost_considered", "decision_margin", "limitations"}:
            raise ReviewEnvironmentError("trusted screening-verdict findings are malformed")
        if value["conclusion"] not in ("positive", "negative", "inconclusive"):
            raise ReviewEnvironmentError("trusted screening conclusion is invalid")
        if type(value["thresholds_predeclared_before_comparison"]) is not bool or type(value["total_cost_considered"]) is not bool:
            raise ReviewEnvironmentError("trusted screening-verdict flags are malformed")
        _nonempty_text(value["spectral_basis"], "screening spectral basis")
        _finite_decimal(value["decision_margin"], "screening decision margin")
        if not isinstance(value["limitations"], list) or any(not isinstance(x, str) for x in value["limitations"]):
            raise ReviewEnvironmentError("trusted screening limitations must be a text array")


def evaluate_review(*, app_root: Path, review_path: str | None, review_sha256: str | None,
                    criteria_version: str, verifier_sha256: str,
                    automatic_core_sha256: str, artifact_manifest_sha256: str,
                    runner_manifest_sha256: str | None, run_id: str | None,
                    artifact_index: dict[str, dict[str, Any]],
                    runner_manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate the trusted review and return PASS/FAIL/REVIEW_REQUIRED.

    A missing review keeps science in human review; malformed trusted material
    is an environment error; a valid review bound to another run is stale.
    """
    value, review_digest = _read_trusted(review_path, review_sha256, app_root)
    if value is None:
        return {"status": "REVIEW_REQUIRED", "reason": "trusted independent science review is not configured"}
    _validate_review_shape(value)
    if not run_id or value.get("run_id") != run_id:
        raise ReviewStaleError("trusted review is not bound to the current runner run_id")
    expected_bindings = {
        "criteria_version": criteria_version,
        "verifier_sha256": verifier_sha256,
        "automatic_core_sha256": automatic_core_sha256,
        "artifact_manifest_sha256": artifact_manifest_sha256,
    }
    for key, expected in expected_bindings.items():
        if value.get(key) != expected:
            raise ReviewStaleError(f"trusted review binding differs from current {key}")
    if runner_manifest_sha256 is None or value.get("runner_manifest_sha256") != runner_manifest_sha256:
        raise ReviewStaleError("trusted review is not bound to the current trusted runner manifest")
    for criterion, row in value["criteria"].items():
        for ref in row["evidence_refs"]:
            rel = PurePosixPath(ref["path"])
            if (rel.is_absolute() or rel.as_posix() != ref["path"] or "\\" in ref["path"] or
                    any(part in ("", ".", "..") for part in ref["path"].split("/"))):
                raise ReviewEnvironmentError(f"trusted review evidence path is not canonical: {criterion}")
            artifact = artifact_index.get(ref["path"])
            if artifact is None or artifact.get("sha256") != ref["sha256"]:
                raise ReviewStaleError(f"trusted review evidence reference is stale: {criterion}")
            if ref["line_end"] > artifact.get("line_count", 0):
                raise ReviewEnvironmentError(f"trusted review evidence line range exceeds artifact: {criterion}")
        if row["status"] == "PASS":
            finding = row["findings"]
            # Keep this lazy: each criterion has a distinct, closed findings
            # schema, so eagerly building a dict would index unrelated fields.
            if criterion == "structure_and_fixed_model":
                contradictions = (finding["atom_count"] != 192 or finding["basis_function_count"] != 4848 or
                    not finding["model_matches_task"] or not finding["structure_identity_supported"] or
                    not finding["runtime_identity_supported"])
            elif criterion == "optimizer_and_native_termination":
                contradictions = any(not stage["terminal"] or not stage["converged"] or
                    not stage["endpoint_supported"] for stage in finding["stages"].values())
            elif criterion == "force_and_model_error_budget":
                contradictions = not finding["thresholds_predeclared"]
            elif criterion == "state_identity_continuity":
                contradictions = any(not item["identity_supported"] for item in finding["kernels"].values())
            elif criterion == "native_screening_consistency_and_paper_comparison":
                contradictions = not finding["recomputed_table_matches"]
            elif criterion == "measured_costs_and_failures":
                contradictions = not finding["ledger_matches"]
            else:
                contradictions = (not finding["thresholds_predeclared_before_comparison"] or
                                  not finding["total_cost_considered"])
                if finding["conclusion"] == "positive" and _finite_decimal(
                        finding["decision_margin"], "screening decision margin") < 0:
                    contradictions = True
            if contradictions:
                raise ReviewEnvironmentError(f"trusted review marks contradictory findings PASS: {criterion}")
    if runner_manifest is not None:
        finding = value["criteria"]["measured_costs_and_failures"]["findings"]
        expected_stage_hours = {stage: Decimal(runner_manifest["production_cost_by_stage_cpu_seconds"].get(stage, 0)) / Decimal(3600)
                                for stage in PRODUCTION_STAGES}
        for stage, expected in expected_stage_hours.items():
            if Decimal(finding["stage_cpu_hours"][stage]) != expected:
                raise ReviewEnvironmentError("trusted reviewed production costs contradict runner recomputation")
        expected_all = Decimal(runner_manifest["total_allocated_cpu_seconds"]) / Decimal(3600)
        if Decimal(finding["all_attempts_cpu_hours"]) != expected_all:
            raise ReviewEnvironmentError("trusted reviewed all-attempt cost contradicts runner recomputation")
        if finding["attempts_included"] != len(runner_manifest["attempts"]):
            raise ReviewEnvironmentError("trusted reviewed attempt count contradicts runner manifest")
    statuses = [row["status"] for row in value["criteria"].values()]
    result = {"schema": SCHEMA, "review_sha256": review_digest,
              "reviewer": value["reviewer"], "reviewed_at_utc": value["reviewed_at_utc"],
              "criteria": value["criteria"]}
    if "FAIL" in statuses:
        result["status"] = "FAIL"
    elif all(status == "PASS" for status in statuses):
        result["status"] = "PASS"
    else:
        result["status"] = "REVIEW_REQUIRED"
    return result
