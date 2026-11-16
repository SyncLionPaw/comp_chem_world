#!/usr/bin/env python3
# 人工审核：自动检查结果供参考，科学结论需人工复核。
"""Open-research contract scorer.

This scorer verifies evidence structure, file integrity, selected numerical
claims, declared resource accounting, and a bounded tensor rotation constraint.
It does not score overall scientific truth or task success.
"""
import hashlib
import json
import math
import os
import re
import sys
import zipfile
from urllib.parse import urlparse
from pathlib import Path

import numpy as np

PACKAGE = Path(__file__).resolve().parents[1]
FINAL = Path(os.environ.get("APP", "/app/final"))


class InfrastructureError(Exception):
    pass


class SubmissionError(Exception):
    pass


def load_contract():
    path = Path(__file__).resolve().parent / "refs.json"
    try:
        contract = json.loads(path.read_text())
        if not isinstance(contract, dict) or contract.get("scientific_gold") is not None:
            raise ValueError("scientific_gold must remain null")
        targets = contract.get("required_target_ids")
        limits = contract.get("resource_limits")
        audit = contract.get("automatic_audit_score")
        constraint = contract.get("scientific_constraint")
        if not isinstance(targets, list) or not targets or any(not isinstance(x, str) or not x for x in targets) or len(set(targets)) != len(targets):
            raise ValueError("required_target_ids must be unique nonempty strings")
        if not isinstance(limits, dict) or not isinstance(audit, dict) or not isinstance(constraint, dict):
            raise ValueError("resource, audit, or scientific-constraint contract is missing")
        required_limits = {"gpu_count", "gpu_memory_gb", "gpu_hours", "cpu_cores", "memory_gib"}
        if set(limits) != required_limits or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in limits.values()):
            raise ValueError("resource limits are malformed")
        maximum = audit.get("maximum")
        tolerance = constraint.get("absolute_tolerance")
        tensor_targets = constraint.get("target_ids")
        if isinstance(maximum, bool) or not isinstance(maximum, (int, float)) or not math.isfinite(maximum) or not 0 <= maximum <= 1:
            raise ValueError("automatic audit maximum is malformed")
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError("scientific constraint tolerance is malformed")
        if not isinstance(tensor_targets, list) or any(x not in targets for x in tensor_targets):
            raise ValueError("tensor constraint target IDs are malformed")
        return contract
    except Exception as exc:
        raise InfrastructureError(f"scoring contract missing or malformed: {exc}") from exc


def fail(message):
    raise SubmissionError(message)


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def no_constant(token):
    raise ValueError("nonfinite JSON number: " + token)


def load_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object,
                           parse_constant=no_constant)
        def finite_tree(item):
            if isinstance(item, dict):
                for child in item.values():
                    finite_tree(child)
            elif isinstance(item, list):
                for child in item:
                    finite_tree(child)
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("nonfinite JSON number")
        finite_tree(value)
        return value
    except (UnicodeError, ValueError) as exc:
        fail(f"cannot read valid JSON {path.name}: {exc}")


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        fail(f"{label} must be a nonempty string")
    return value.strip()


def number(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        fail(f"{label} must be a finite JSON number")
    if positive and value <= 0:
        fail(f"{label} must be positive")
    return float(value)


def relfile(root, rel):
    text(rel, "artifact path")
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or "\\" in rel:
        fail(f"artifact path must be relative and contained: {rel}")
    candidate = root / p
    # Reject symlink components, including links that currently resolve inside.
    cursor = root
    for part in p.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            fail(f"symlink artifact paths are not accepted: {rel}")
    resolved = candidate.resolve()
    base = root.resolve()
    if resolved != base and base not in resolved.parents:
        fail(f"artifact path escapes submission: {rel}")
    if not resolved.is_file() or resolved.stat().st_size == 0:
        fail(f"artifact is missing or empty: {rel}")
    return resolved


def records(obj, field):
    value = obj.get(field)
    if not isinstance(value, list):
        fail(f"{field} must be an array")
    ids = set()
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            fail(f"{field}[{i}] must be an object")
        ident = text(item.get("id"), f"{field}[{i}].id")
        if ident in ids:
            fail(f"duplicate {field} id: {ident}")
        ids.add(ident)
    return value, ids


def array_from_artifact(path, key):
    try:
        if path.suffix.lower() == ".npz":
            with np.load(path, allow_pickle=False) as data:
                if key not in data.files:
                    fail(f"array key {key!r} missing from {path.name}")
                array = np.asarray(data[key], dtype=np.float64)
        elif path.suffix.lower() == ".npy":
            if key not in ("values", "array"):
                fail(".npy arrays use key 'values' or 'array'")
            array = np.asarray(np.load(path, allow_pickle=False), dtype=np.float64)
        else:
            fail("numeric array artifacts must be .npz or .npy")
    except (zipfile.BadZipFile, EOFError) as exc:
        fail(f"numeric array artifact is corrupt: {path.name}: {exc}")
    if array.size == 0 or not np.isfinite(array).all():
        fail(f"array {key!r} is empty or nonfinite")
    return array


def compute_metric(evaluation, artifact_paths):
    metric = text(evaluation.get("metric"), "evaluation.metric")
    text(evaluation.get("calculation"), "evaluation.calculation")
    text(evaluation.get("unit"), "evaluation.unit")
    aid = text(evaluation.get("artifact_id"), "evaluation.artifact_id")
    if aid not in artifact_paths:
        fail(f"numeric evaluation references unknown artifact {aid}")
    path = artifact_paths[aid]
    reported = number(evaluation.get("value"), "evaluation.value")
    if metric in {"rmse", "mae", "r2"}:
        ref = array_from_artifact(path, text(evaluation.get("reference_key"), "reference_key"))
        pred = array_from_artifact(path, text(evaluation.get("prediction_key"), "prediction_key"))
        if ref.shape != pred.shape or ref.size < 2:
            fail("paired numerical arrays must have matching shapes and at least two values")
        r, p = ref.ravel(), pred.ravel()
        if metric == "rmse":
            calculated = float(np.sqrt(np.mean((p-r) ** 2)))
        elif metric == "mae":
            calculated = float(np.mean(np.abs(p-r)))
        else:
            denom = float(np.sum((r-np.mean(r)) ** 2))
            if denom <= 0:
                fail("R2 reference array has zero variance")
            calculated = float(1.0 - np.sum((p-r) ** 2) / denom)
    elif metric in {"mean", "std", "l2_norm", "relative_difference"}:
        values = array_from_artifact(path, text(evaluation.get("values_key"), "values_key"))
        values = values.ravel()
        if metric == "mean":
            calculated = float(np.mean(values))
        elif metric == "std":
            calculated = float(np.std(values, ddof=0))
        elif metric == "l2_norm":
            calculated = float(np.linalg.norm(values))
        else:
            reference = number(evaluation.get("reference_value"), "reference_value")
            if reference == 0:
                fail("relative_difference reference_value cannot be zero")
            calculated = float(abs(np.mean(values)-reference) / abs(reference))
    else:
        # Research-selected values that do not fit the finite supported list
        # remain manual-review evidence and earn no automatic numerical points.
        return None, "manual_only_metric"
    tolerance = number(evaluation.get("absolute_tolerance", 1e-8), "absolute_tolerance")
    if tolerance < 0 or tolerance > 1e-8 or not math.isclose(reported, calculated, rel_tol=1e-7, abs_tol=tolerance):
        fail(f"evaluation {evaluation.get('id')} reported {reported:g}; recomputed {calculated:g}")
    return calculated, "recomputed"


def constraint_array(path, key):
    """Load real numeric data without the coercions allowed by legacy metrics."""
    try:
        if path.suffix.lower() == ".npz":
            with np.load(path, allow_pickle=False) as data:
                if key not in data.files:
                    fail(f"array key {key!r} missing from {path.name}")
                source = np.asarray(data[key])
        elif path.suffix.lower() == ".npy":
            if key not in ("values", "array"):
                fail(".npy arrays use key 'values' or 'array'")
            source = np.asarray(np.load(path, allow_pickle=False))
        else:
            fail("scientific constraint artifacts must be .npz or .npy")
    except (zipfile.BadZipFile, EOFError) as exc:
        fail(f"scientific constraint artifact is corrupt: {path.name}: {exc}")
    if source.dtype.kind not in "iuf" or source.size == 0 or not np.isfinite(source).all():
        fail(f"scientific constraint array {key!r} must contain finite real numeric values")
    with np.errstate(over="ignore", invalid="ignore"):
        result = np.asarray(source, dtype=np.float64)
    if not np.isfinite(result).all():
        fail(f"scientific constraint array {key!r} is outside float64 range")
    return result


def compute_scientific_constraint(evaluation, artifact_paths):
    """Recompute one submitted rank-1/rank-2 rotation covariance check."""
    if evaluation.get("constraint") != "tensor_rotation_covariance":
        fail("unsupported scientific constraint")
    target = evaluation.get("target_id")
    if target not in TENSOR_CONSTRAINT_TARGETS:
        fail("tensor rotation constraint target_id must identify a rank-1 or rank-2 target")
    aid = text(evaluation.get("artifact_id"), "evaluation.artifact_id")
    if aid not in artifact_paths:
        fail(f"scientific constraint references unknown artifact {aid}")
    text(evaluation.get("unit"), "evaluation.unit")
    path = artifact_paths[aid]
    keys = {name: text(evaluation.get(name), f"evaluation.{name}") for name in (
        "original_key", "rotated_key", "rotation_key",
        "original_positions_key", "rotated_positions_key")}
    original = constraint_array(path, keys["original_key"])
    rotated = constraint_array(path, keys["rotated_key"])
    rotation = constraint_array(path, keys["rotation_key"])
    positions = constraint_array(path, keys["original_positions_key"])
    rotated_positions = constraint_array(path, keys["rotated_positions_key"])
    expected_shape = (3,) if target == "rank1_dipole" else (3, 3)
    if original.shape != expected_shape or rotated.shape != expected_shape:
        fail(f"{target} original and rotated arrays must have shape {expected_shape}")
    if rotation.shape != (3, 3):
        fail("rotation_key array must have shape (3, 3)")
    if positions.ndim != 2 or positions.shape[1:] != (3,) or positions.shape[0] < 1:
        fail("original_positions_key must have shape (N, 3), N >= 1")
    if rotated_positions.shape != positions.shape:
        fail("rotated positions must match the original (N, 3) shape and atom ordering")

    tol = SCIENTIFIC_CONSTRAINT_TOLERANCE
    with np.errstate(over="ignore", invalid="ignore"):
        orthogonality_error = float(np.max(np.abs(rotation.T @ rotation - np.eye(3))))
        determinant = float(np.linalg.det(rotation))
    if not math.isfinite(orthogonality_error) or orthogonality_error > tol:
        fail("rotation_key must be orthogonal")
    if not math.isfinite(determinant) or abs(determinant - 1.0) > tol:
        fail("rotation_key must be a proper rotation with determinant +1")

    position_scale = float(np.max(np.abs(positions)))
    if position_scale == 0.0:
        if np.any(rotated_positions != 0.0):
            fail("zero original geometry cannot produce nonzero rotated coordinates")
        return {"evaluation_id": evaluation["id"], "target_id": target,
                "status": "UNVERIFIED", "reason": "geometry has no resolvable nonzero scale",
                "normalized_max_abs_error": None}
    if position_scale < np.finfo(float).tiny:
        rotated_position_scale = float(np.max(np.abs(rotated_positions)))
        if rotated_position_scale > 4.0 * position_scale:
            fail("rotated coordinates exceed the scale possible under a proper rotation")
        return {"evaluation_id": evaluation["id"], "target_id": target,
                "status": "UNVERIFIED", "reason": "geometry has no resolvable nonzero scale",
                "normalized_max_abs_error": None}
    with np.errstate(over="ignore", invalid="ignore"):
        expected_positions = (positions / position_scale) @ rotation.T
        observed_positions = rotated_positions / position_scale
        geometry_error = float(np.max(np.abs(observed_positions - expected_positions)))
    if not math.isfinite(geometry_error):
        fail("rotated geometry comparison produced a nonfinite value")
    if geometry_error > tol:
        fail("rotated_positions_key does not match the declared rotation and atom ordering")
    geometry_distinguishability = float(np.max(np.abs(expected_positions - positions / position_scale)))
    if not math.isfinite(geometry_distinguishability):
        fail("normalized geometry comparison produced a nonfinite value")
    geometry_uninformative = geometry_distinguishability <= tol

    original_scale = float(np.max(np.abs(original)))
    if original_scale == 0.0:
        if np.any(rotated != 0.0):
            return {"evaluation_id": evaluation["id"], "target_id": target,
                    "status": "FAIL", "reason": "zero original tensor cannot produce nonzero rotated components",
                    "normalized_max_abs_error": None}
        return {"evaluation_id": evaluation["id"], "target_id": target,
                "status": "UNVERIFIED", "reason": "original tensor has no resolvable nonzero scale",
                "normalized_max_abs_error": None}
    if original_scale < np.finfo(float).tiny:
        rotated_scale = float(np.max(np.abs(rotated)))
        if rotated_scale > 4.0 * original_scale:
            return {"evaluation_id": evaluation["id"], "target_id": target,
                    "status": "FAIL", "reason": "rotated tensor scale exceeds the bound under a proper rotation",
                    "normalized_max_abs_error": None}
        return {"evaluation_id": evaluation["id"], "target_id": target,
                "status": "UNVERIFIED", "reason": "original tensor has no resolvable nonzero scale",
                "normalized_max_abs_error": None}
    with np.errstate(over="ignore", invalid="ignore"):
        original_scaled = original / original_scale
        rotated_scaled = rotated / original_scale
        if target == "rank1_dipole":
            expected_scaled = rotation @ original_scaled
        else:
            expected_scaled = rotation @ original_scaled @ rotation.T
        distinguishability = float(np.max(np.abs(expected_scaled - original_scaled)))
        residual = float(np.max(np.abs(rotated_scaled - expected_scaled)))
    if not math.isfinite(distinguishability) or not math.isfinite(residual):
        return {"evaluation_id": evaluation["id"], "target_id": target,
                "status": "FAIL", "reason": "normalized tensor comparison is nonfinite",
                "normalized_max_abs_error": None}
    if residual > tol:
        return {"evaluation_id": evaluation["id"], "target_id": target,
                "status": "FAIL", "reason": "rotated tensor violates covariance",
                "normalized_max_abs_error": residual}
    if distinguishability <= tol or geometry_uninformative:
        return {"evaluation_id": evaluation["id"], "target_id": target,
                "status": "UNVERIFIED",
                "reason": ("geometry is unchanged at the declared rotation" if geometry_uninformative
                           else "this rotation and tensor do not distinguish the covariance relation"),
                "normalized_max_abs_error": residual}
    return {"evaluation_id": evaluation["id"], "target_id": target,
            "status": "PASS", "reason": "rotation covariance recomputed",
            "normalized_max_abs_error": residual}


def resource_score(executions, artifact_paths, known_ids):
    """Check declared resource budgets and report the bounded local evidence tier."""
    if not executions:
        return 0.0, "INSUFFICIENT_EVIDENCE", "NO_EXECUTION_EVIDENCE"
    seen_local = False
    selected_count = 0
    selected_complete = False
    verified = True
    total_gpu_hours = 0.0
    for run in executions:
        if not isinstance(run, dict):
            fail("execution entries must be objects")
        mode = text(run.get("resource_mode"), "execution.resource_mode")
        status = run.get("status")
        role = run.get("role")
        exit_code = run.get("exit_code")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int) or not 0 <= exit_code <= 255:
            fail(f"execution {run.get('id')} exit_code must be an integer from 0 through 255")
        if (status == "completed" and exit_code != 0) or (status == "failed" and exit_code == 0):
            fail(f"execution {run.get('id')} status conflicts with exit_code")
        if role not in {"selected_result", "retry", "postprocess", "other"}:
            fail(f"execution {run.get('id')} has unsupported role")
        if status not in {"completed", "failed", "cancelled"}:
            verified = False
        if role == "selected_result":
            selected_count += 1
            selected_complete = status == "completed" and run.get("exit_code") == 0
        elif status == "completed" and run.get("exit_code") != 0:
            verified = False
        for field in ("input_artifact_ids", "output_artifact_ids", "evidence_ids"):
            refs = run.get(field)
            if not isinstance(refs, list) or any(x not in artifact_paths for x in refs):
                fail(f"execution {run.get('id')} has invalid {field}")
            if not refs:
                verified = False
        cores = number(run.get("cpu_cores"), "execution.cpu_cores", positive=True)
        memory = number(run.get("memory_gib"), "execution.memory_gib", positive=True)
        gpus = number(run.get("gpu_count", 0), "execution.gpu_count")
        gpu_memory = number(run.get("gpu_memory_gb", 0), "execution.gpu_memory_gb")
        gpu_hours = number(run.get("allocated_gpu_hours", 0), "execution.allocated_gpu_hours")
        if min(gpus, gpu_memory, gpu_hours) < 0:
            fail("resource declarations cannot be negative")
        if cores > RESOURCE_LIMITS["cpu_cores"] or memory > RESOURCE_LIMITS["memory_gib"]:
            fail("declared execution exceeds CPU or memory budget")
        if gpus > RESOURCE_LIMITS["gpu_count"] or gpu_memory > RESOURCE_LIMITS["gpu_memory_gb"]:
            fail("declared execution exceeds GPU count or memory budget")
        total_gpu_hours += gpu_hours
        if total_gpu_hours > RESOURCE_LIMITS["gpu_hours"]:
            fail("aggregate declared GPU allocation exceeds budget")
        if mode == "declared_local_only":
            seen_local = True
            if gpus != 0 or gpu_memory != 0 or gpu_hours != 0:
                verified = False
            elapsed = number(run.get("elapsed_seconds"), "execution.elapsed_seconds", positive=True)
            aid = text(run.get("timing_artifact_id"), "execution.timing_artifact_id")
            if aid not in artifact_paths:
                fail("local execution must reference a timing artifact")
            log = artifact_paths[aid].read_text(encoding="utf-8", errors="replace")
            match = re.search(r"Elapsed \(wall clock\) time[^\n]*:\s*(\d+(?::\d+){1,2}(?:\.\d+)?)\s*$", log, re.M)
            if not match:
                fail("local timing artifact lacks GNU time -v elapsed wall clock record")
            pieces = match.group(1).split(":")
            try:
                if len(pieces) == 3:
                    logged = int(pieces[0])*3600 + int(pieces[1])*60 + float(pieces[2])
                elif len(pieces) == 2:
                    logged = int(pieces[0])*60 + float(pieces[1])
                else:
                    fail("unrecognized GNU time elapsed format")
            except ValueError:
                fail("unrecognized GNU time elapsed format")
            seconds = pieces[-1]
            fractional_digits = len(seconds.split(".", 1)[1]) if "." in seconds else 0
            rounding_tolerance = 0.5 * (10 ** -fractional_digits)
            if not math.isclose(logged, elapsed, rel_tol=0, abs_tol=rounding_tolerance):
                fail("declared elapsed time disagrees with timing log")
            exit_match = re.search(r"Exit status:\s*(\d+)", log)
            rss_match = re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", log)
            command_match = re.search(r"Command being timed:\s*['\"](.+?)['\"]\s*$", log, re.M)
            command = text(run.get("command"), "execution.command")
            if not exit_match or int(exit_match.group(1)) != run.get("exit_code"):
                fail("execution exit code disagrees with GNU time record")
            if not rss_match or int(rss_match.group(1)) > memory * 1024 * 1024:
                fail("GNU time maximum resident memory is missing or exceeds declared memory")
            if not command_match or command_match.group(1) != command:
                fail("execution command disagrees with GNU time record")
        elif mode == "slurm_accounted":
            # Submitted scheduler records are not independently authenticated;
            # they do not earn verified resource points.
            verified = False
        else:
            fail(f"unsupported resource_mode: {mode}")
    if selected_count > 1:
        fail("at most one execution may be marked selected_result")
    if selected_count == 1 and not selected_complete:
        return 0.0, "FAILED", "SELECTED_EXECUTION_FAILED"
    if not verified or not selected_complete:
        return 0.0, "INSUFFICIENT_EVIDENCE", "DECLARED_BUT_UNVERIFIED"
    return (0.05, "VERIFIED", "DECLARED_LOCAL_ONLY") if seen_local else (0.0, "INSUFFICIENT_EVIDENCE", "NO_EXECUTION_EVIDENCE")


def score():
    global RESOURCE_LIMITS, AUTO_MAX, REQUIRED_TARGETS
    global SCIENTIFIC_CONSTRAINT_TOLERANCE, TENSOR_CONSTRAINT_TARGETS
    contract = load_contract()
    RESOURCE_LIMITS = contract["resource_limits"]
    AUTO_MAX = contract["automatic_audit_score"]["maximum"]
    REQUIRED_TARGETS = set(contract["required_target_ids"])
    SCIENTIFIC_CONSTRAINT_TOLERANCE = contract["scientific_constraint"]["absolute_tolerance"]
    TENSOR_CONSTRAINT_TARGETS = set(contract["scientific_constraint"]["target_ids"])
    root = FINAL.resolve()
    submission = load_json(relfile(root, "research.json"))
    if not isinstance(submission, dict):
        fail("research.json must be a JSON object")
    if text(submission.get("question"), "question").strip() == "":
        fail("question is required")

    claims, claim_ids = records(submission, "claims")
    sources, source_ids = records(submission, "sources")
    artifacts, artifact_ids = records(submission, "artifacts")
    evaluations, evaluation_ids = records(submission, "evaluations")
    executions, execution_ids = records(submission, "executions")
    if not claims:
        fail("at least one research claim is required")
    known = claim_ids | source_ids | artifact_ids | evaluation_ids | execution_ids
    if len(known) != sum(map(len, (claim_ids, source_ids, artifact_ids, evaluation_ids, execution_ids))):
        fail("record IDs must be globally unique")

    # Each required scientific target must be addressed in the submission
    # index. This checks traceability only: it does not certify the claim or
    # turn a self-reported conclusion into scientific success.
    target_rows, target_ids = records(submission, "target_coverage")
    if target_ids & known:
        fail("target IDs must not collide with evidence record IDs")
    if target_ids != REQUIRED_TARGETS:
        missing = sorted(REQUIRED_TARGETS - target_ids)
        extra = sorted(target_ids - REQUIRED_TARGETS)
        fail(f"target_coverage must contain the six required target IDs; missing={missing}, extra={extra}")
    coverage_status = {}
    for row in target_rows:
        target = row["id"]
        state = row.get("status")
        if state not in {"supports", "contradicts", "insufficient"}:
            fail(f"target {target} status must be supports, contradicts, or insufficient")
        refs = {
            "claim_ids": claim_ids,
            "evaluation_ids": evaluation_ids,
            "artifact_ids": artifact_ids,
        }
        for field, allowed in refs.items():
            values = row.get(field)
            if not isinstance(values, list) or not values or any(value not in allowed for value in values):
                fail(f"target {target} must reference existing {field}")
        coverage_status[target] = state
    artifact_paths = {}
    artifacts_complete = True
    for item in artifacts:
        aid = item["id"]
        path = relfile(root, item.get("path"))
        expected = text(item.get("sha256"), f"artifact {aid}.sha256").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected) or sha256(path) != expected:
            fail(f"artifact hash mismatch: {aid}")
        text(item.get("role"), f"artifact {aid}.role")
        artifact_paths[aid] = path
    source_links = 0
    for item in sources:
        identifier = text(item.get("url") or item.get("doi"), f"source {item['id']} url/doi")
        if item.get("url"):
            parsed = urlparse(identifier)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                fail(f"source {item['id']} URL must be an absolute http(s) URL")
        elif not re.match(r"^10\.\d{4,9}/\S+$", identifier):
            fail(f"source {item['id']} DOI has invalid syntax")
        text(item.get("acquisition_note"), f"source {item['id']}.acquisition_note")
        aid = text(item.get("local_artifact"), f"source {item['id']}.local_artifact")
        if aid not in artifact_paths:
            fail(f"source {item['id']} references missing local_artifact")
        expected = text(item.get("sha256"), f"source {item['id']}.sha256").lower()
        if sha256(artifact_paths[aid]) != expected:
            fail(f"source {item['id']} bytes do not match sha256")
        source_links += 1

    numeric = []
    scientific_constraints = []
    for item in evaluations:
        kind = text(item.get("kind"), f"evaluation {item['id']}.kind")
        refs = item.get("evidence_ids")
        if not isinstance(refs, list) or not refs or any(x not in known for x in refs):
            fail(f"evaluation {item['id']} must reference known evidence_ids")
        if not (set(refs) & (source_ids | artifact_ids)):
            fail(f"evaluation {item['id']} must cite a source or artifact")
        if kind == "numeric":
            value, state = compute_metric(item, artifact_paths)
            numeric.append((item, value, state))
        elif kind == "qualitative":
            text(item.get("description"), f"evaluation {item['id']}.description")
        elif kind == "scientific_constraint":
            artifact_id = text(item.get("artifact_id"), f"evaluation {item['id']}.artifact_id")
            if artifact_id not in refs:
                fail(f"scientific constraint {item['id']} must cite its artifact_id in evidence_ids")
            scientific_constraints.append(compute_scientific_constraint(item, artifact_paths))
        else:
            fail(f"unsupported evaluation kind: {kind}")

    for claim in claims:
        text(claim.get("statement"), f"claim {claim['id']}.statement")
        text(claim.get("scope"), f"claim {claim['id']}.scope")
        text(claim.get("limitations"), f"claim {claim['id']}.limitations")
        if claim.get("conclusion") not in {"supports", "contradicts", "insufficient"}:
            fail(f"claim {claim['id']} has unsupported conclusion")
        refs = claim.get("evidence_ids")
        if not isinstance(refs, list) or not refs or any(x not in known for x in refs):
            fail(f"claim {claim['id']} must reference known evidence_ids")
        if not (set(refs) & evaluation_ids):
            fail(f"claim {claim['id']} must cite an evaluation")

    for row in target_rows:
        target_claims = set(row["claim_ids"])
        target_evals = set(row["evaluation_ids"])
        target_artifacts = set(row["artifact_ids"])
        for item in evaluations:
            if item["id"] in target_evals and item.get("kind") == "scientific_constraint" \
                    and item.get("target_id") != row["id"]:
                fail(f"target {row['id']} cannot reference a scientific constraint for another target")
        source_artifacts = {item["id"]: item.get("local_artifact") for item in sources}
        target_sources = {source_id for source_id, artifact_id in source_artifacts.items()
                          if artifact_id in target_artifacts}
        if not any(target_evals.intersection(item.get("evidence_ids", [])) for item in claims
                   if item["id"] in target_claims):
            fail(f"target {row['id']} claims do not cite a listed evaluation")
        if not any((target_artifacts | target_sources).intersection(item.get("evidence_ids", []))
                   for item in evaluations if item["id"] in target_evals):
            fail(f"target {row['id']} evaluations do not cite its source or artifact evidence")
        target_checks = [check for check in scientific_constraints if check["target_id"] == row["id"]]
        if target_checks:
            check_evaluations = {check["evaluation_id"] for check in target_checks}
            if not check_evaluations.issubset(target_evals):
                fail(f"target {row['id']} must list each matching scientific constraint evaluation")
            for check in target_checks:
                item = next(evaluation for evaluation in evaluations if evaluation["id"] == check["evaluation_id"])
                aid = item["artifact_id"]
                if aid not in target_artifacts:
                    fail(f"target {row['id']} must list each constraint artifact")
                if not any(item["id"] in claim.get("evidence_ids", []) for claim in claims
                           if claim["id"] in set(row["claim_ids"])):
                    fail(f"target {row['id']} claims must directly cite its scientific constraint evaluation")
    constraint_status_by_target = {}
    for target in TENSOR_CONSTRAINT_TARGETS:
        checks = [check for check in scientific_constraints if check["target_id"] == target]
        if not checks:
            constraint_status_by_target[target] = "UNVERIFIED"
        elif any(check["status"] == "FAIL" for check in checks):
            constraint_status_by_target[target] = "FAIL"
        elif any(check["status"] == "PASS" for check in checks):
            constraint_status_by_target[target] = "PASS"
        else:
            constraint_status_by_target[target] = "UNVERIFIED"

    source_artifact_ok = bool(artifacts) and bool(sources) and all(
        item.get("local_artifact") in artifact_paths for item in sources)
    claim_refs = [set(claim.get("evidence_ids", [])) for claim in claims]
    evaluation_refs = [set(evaluation.get("evidence_ids", [])) for evaluation in evaluations]
    traceability_ok = (source_artifact_ok and bool(evaluations) and
        all(any(source["id"] in refs for refs in evaluation_refs) for source in sources) and
        all(any(evaluation["id"] in refs for refs in claim_refs) for evaluation in evaluations) and
        all(any(ref in source_ids or ref in evaluation_ids for ref in refs) for refs in claim_refs))
    integrity_score = (0.05 if source_artifact_ok else 0.0) + (0.10 if traceability_ok else 0.0)
    numeric_score = 0.30 if any(state == "recomputed" for _, _, state in numeric) else 0.0
    resource_points, execution_status, resource_status = resource_score(executions, artifact_paths, known)
    auto = min(AUTO_MAX, integrity_score + numeric_score + resource_points)
    return {"status": "REVIEW_REQUIRED", "exit_code": 0,
            "automatic_audit_score": round(auto, 6), "automatic_audit_score_max": AUTO_MAX,
            "construction_status": "DRAFT",
            "evaluation_coverage": "PARTIAL",
            "research_success": "INCONCLUSIVE",
            "checked_claims": [{"claim_id": claim_id,
                                "scope": "record linkage and submission-wide integrity; supported arithmetic and resource checks where applicable"}
                               for claim_id in sorted(claim_ids)],
            "unverified_claims": sorted(claim_ids),
            "target_coverage": [{"id": target, "submitted_status": coverage_status[target],
                                 "scientific_status": "UNVERIFIED"}
                                for target in sorted(REQUIRED_TARGETS)],
            "target_constraint_status": [{"id": target, "status": constraint_status_by_target[target],
                                          "reason": ("NO_TARGET_CONSTRAINT_EVIDENCE" if not any(
                                              check["target_id"] == target for check in scientific_constraints)
                                              else "submitted constraint checks summarized below")}
                                         for target in sorted(TENSOR_CONSTRAINT_TARGETS)],
            "scientific_constraint_checks": scientific_constraints,
            "scientific_review_status": "PENDING",
            "scientific_conclusion_verified": False,
            "execution_evidence_status": execution_status,
            "execution_verification_scope": "submitted_evidence_self_consistency",
            "trusted_execution_provenance": "NOT_ESTABLISHED",
            "score_components": {"source_artifact_integrity": round(integrity_score, 6),
                                 "numeric_recomputation": round(numeric_score, 6),
                                 "resource_accounting": round(resource_points, 6)},
            "resource_evidence_status": resource_status,
            "evaluations": [{"id": item["id"], "state": state, "recomputed_value": val}
                            for item, val, state in numeric],
            "limitations": ["Automatic checks verify submitted bytes and calculations, not source authenticity, scientific relevance, or scientific truth.",
                            "Scientific review and independently verified execution/accounting provenance remain pending."]}


def main():
    try:
        result = score()
        print(json.dumps(result, allow_nan=False, sort_keys=True))
        return 0
    except InfrastructureError as exc:
        print(json.dumps({"status": "ENV_ERROR", "exit_code": 2, "reward": None,
                          "construction_status": "DRAFT", "evaluation_coverage": "PARTIAL",
                          "research_success": "INCONCLUSIVE", "evaluation_error": True,
                          "reason": str(exc)}, allow_nan=False, sort_keys=True))
        return 2
    except SubmissionError as exc:
        print(json.dumps({"status": "FAIL", "exit_code": 1, "reward": 0,
                          "construction_status": "DRAFT", "evaluation_coverage": "PARTIAL",
                          "research_success": "INCONCLUSIVE",
                          "reason": str(exc)}, allow_nan=False, sort_keys=True))
        return 1
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        print(json.dumps({"status": "FAIL", "exit_code": 1, "reward": 0,
                          "construction_status": "DRAFT", "evaluation_coverage": "PARTIAL",
                          "research_success": "INCONCLUSIVE",
                          "reason": f"malformed submission: {exc}"}, allow_nan=False, sort_keys=True))
        return 1
    except OSError as exc:
        print(json.dumps({"status": "ENV_ERROR", "exit_code": 2, "reward": None,
                          "construction_status": "DRAFT", "evaluation_coverage": "PARTIAL",
                          "research_success": "INCONCLUSIVE", "evaluation_error": True,
                          "reason": f"evaluation I/O error: {exc}"}, allow_nan=False, sort_keys=True))
        return 2
    except Exception as exc:
        print(json.dumps({"status": "ENV_ERROR", "exit_code": 2, "reward": None,
                          "construction_status": "DRAFT", "evaluation_coverage": "PARTIAL",
                          "research_success": "INCONCLUSIVE", "evaluation_error": True,
                          "reason": f"unexpected verifier error: {type(exc).__name__}: {exc}"},
                         allow_nan=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
