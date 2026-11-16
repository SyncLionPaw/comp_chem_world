#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Fine-tuning nonadiabatic couplings without losing physical symmetries.
"""Case03 v2 verifier.

Public preflight validates only candidate-authored/public artifact structure.
Scientific grading is available only to the trusted host runner, which passes
an attempt ID whose immutable evidence lives below the canonical private root.
This module never reads private labels or row-level score data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
import types
from pathlib import Path, PurePosixPath
from typing import Any

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ENV = 2
CASE_ROOT = Path(__file__).resolve().parents[1]
# Harbor restores root-sealed artifacts into this reserved path before grading.
TRUSTED_PRIVATE_MOUNT = Path("/trusted/case03-private")
LOCAL_PRIVATE_ROOT = CASE_ROOT / "environment/assets/harbor/private-case03"
PINNED_TASK_CONFIG_SHA256 = "61b7aa71df99f3bca15d45ec157130e737d41dcfb1010946af4b1a9b4bdf0b5b"
PINNED_RAW_INSTRUCTION_CONTENT_SHA256 = "adf4848e996a98e93ab275114ccc8ffcb2f6e6a83f123047c7785c1bf917b848"
PINNED_INSTRUCTION_SHA256 = "adf4848e996a98e93ab275114ccc8ffcb2f6e6a83f123047c7785c1bf917b848"  # legacy parsed-content test alias; distinct from raw file bytes
PINNED_EFFECTIVE_PROMPT_SHA256 = "adf4848e996a98e93ab275114ccc8ffcb2f6e6a83f123047c7785c1bf917b848"
LEGACY_IMAGE_ID = "sha256:112509d5f553824edc7b83fa11d0fc32ead2be995ad1d4aa8f239f7fa115d8c3"
PINNED_PRIVATE_SOURCE_CLOSURE_SHA256 = "10d0afa9bb4e81ea887cffd3c8d7c4ec20d9d8284e40ca5c834e6dbc4eafda19"
PINNED_PROFILE_SHA256 = "23305e8c0d625fbc6884f2830583e0f4fbab1b087d0962c821f14da063b964b9"
PINNED_PRIVATE_SOURCE_FILES = {
    "score_case03_v2_once.py": "29a9c538c7a1761fd8bed3cda8cfe5171a0e7af0b90689d00dd345fb4ef8fa00",
    "score_redesign_trusted.py": "b3305875faed0b360a86f7f4f5a52558d0a5d3dd024231c42a36e29daa04742f",
    "case03_v2_protocol.py": "7b1c95ba0e02284d067b3de4821960ab6a0ef24f8f28c24b0321eecd55c9f52e",
    "case03_v2_public_diagnostics.py": "0b606a2ffa4e8fc499cbd78f726471d5ef3f3c7d633a8abc3f96b8e7054dbc94",
}
PINNED_REFERENCE_POLICY_SHA256 = "10af8f3c349d7ca9325cba3c0c00d2c5cc925d45c46b9bc95da87145f6978bf7"
PINNED_TEMPLATE_SHA256 = "e997251219b205efb8c0004ddd8d8401c89a8e8e45f5cde9400b75a36a67e179"
PINNED_BASELINE_SHA256 = "840834c2b94fc2efdb7c454f11a60f5af3bee917f12594e90ad6a82b3155ecc5"
FINAL_FILES = {"hypothesis.json", "strategy_request.json", "training_report.json",
               "model_state_dict.pt", "final_decision.json"}
TRAINING_FILES = FINAL_FILES - {"final_decision.json"}
PHASE_FILES = {"hypothesis": {"hypothesis.json"},
               "training": TRAINING_FILES,
               "final": FINAL_FILES}
MAX_BYTES = {"hypothesis.json": 32 * 1024, "strategy_request.json": 64 * 1024,
             "training_report.json": 256 * 1024, "model_state_dict.pt": 512 * 1024 * 1024,
             "final_decision.json": 32 * 1024}


class CandidateError(ValueError):
    """Candidate-controlled output violates the declared v2 protocol."""


class EnvironmentError(RuntimeError):
    """Trusted host context or evidence is missing, invalid, or inconsistent."""


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def finite_float(token: str) -> float:
        value = float(token)
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return value

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_float=finite_float,
                           parse_constant=lambda _x: (_ for _ in ()).throw(ValueError("non-finite JSON number")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CandidateError(f"{label} is not strict finite JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateError(f"{label} root must be an object")
    return value


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_reference_policy(path: Path | None = None) -> dict[str, Any]:
    """Load only the reviewed current-v2 science and runtime policy."""
    path = path or Path(__file__).with_name("refs.json")
    try:
        raw = path.read_bytes()
        value = _strict_json(raw, "refs.json")
    except Exception as exc:
        raise EnvironmentError(f"trusted refs.json is unavailable or malformed: {exc}") from exc
    if _canonical_json_sha(value) != PINNED_REFERENCE_POLICY_SHA256:
        raise EnvironmentError("trusted refs.json canonical policy digest differs from its reviewed pin")
    expected_top = {"schema", "source_pins", "dataset", "experiment", "resources",
                    "public_diagnosis", "statistics", "scientific_guards", "tolerances"}
    if set(value) != expected_top or value.get("schema") != "case03-reference-policy/v2":
        raise EnvironmentError("trusted refs.json schema/fields are not the reviewed v2 policy")
    pins = value["source_pins"]
    if (not isinstance(pins, dict)
            or pins.get("task_config_sha256") != PINNED_TASK_CONFIG_SHA256
            or pins.get("profile_sha256") != PINNED_PROFILE_SHA256
            or pins.get("scorer_source_closure_sha256") != PINNED_PRIVATE_SOURCE_CLOSURE_SHA256
            or pins.get("scorer_source_files") != PINNED_PRIVATE_SOURCE_FILES
            or pins.get("template_sha256") != PINNED_TEMPLATE_SHA256
            or pins.get("baseline_sha256") != PINNED_BASELINE_SHA256):
        raise EnvironmentError("trusted refs.json source pins differ from the active v2 verifier pins")
    return value


def _private_root(*, require_root_seal: bool = False) -> Path:
    if require_root_seal:
        if TRUSTED_PRIVATE_MOUNT.is_symlink() or not TRUSTED_PRIVATE_MOUNT.is_dir():
            raise EnvironmentError("root-sealed Case03 private artifact is unavailable")
        st = TRUSTED_PRIVATE_MOUNT.lstat()
        parent = TRUSTED_PRIVATE_MOUNT.parent.lstat()
        if (st.st_uid != 0 or st.st_mode & 0o222 or parent.st_uid != 0 or parent.st_mode & 0o222):
            raise EnvironmentError("root-sealed Case03 private artifact is writable")
        return TRUSTED_PRIVATE_MOUNT
    if LOCAL_PRIVATE_ROOT.is_dir() and not LOCAL_PRIVATE_ROOT.is_symlink():
        return LOCAL_PRIVATE_ROOT
    raise EnvironmentError("canonical readonly Case03 private root is not mounted")


def _verify_pinned_private_sources(private_root: Path) -> None:
    manifest: dict[str, str] = {}
    for name, expected_sha in PINNED_PRIVATE_SOURCE_FILES.items():
        path = private_root / name
        try:
            st = path.lstat()
            if not stat.S_ISREG(st.st_mode) or path.is_symlink() or st.st_nlink != 1:
                raise EnvironmentError(f"trusted source is not a regular single-link file: {name}")
            actual_sha = _sha(path.read_bytes())
        except OSError as exc:
            raise EnvironmentError(f"pinned trusted source is unavailable: {name}") from exc
        if actual_sha != expected_sha:
            raise EnvironmentError(f"pinned trusted source digest changed: {name}")
        manifest[name] = actual_sha
    if _canonical_json_sha(manifest) != PINNED_PRIVATE_SOURCE_CLOSURE_SHA256:
        raise EnvironmentError("pinned private source-closure digest is inconsistent")


def _canonical_json_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    return _sha(raw)


def _read_output_set(output_dir: Path, expected: set[str]) -> dict[str, bytes]:
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise CandidateError("candidate outputs path must be a real directory")
    try:
        names = {entry.name for entry in output_dir.iterdir()}
    except OSError as exc:
        raise CandidateError(f"cannot list candidate outputs: {exc}") from exc
    if names != expected:
        raise CandidateError(f"output inventory mismatch: expected {sorted(expected)}, found {sorted(names)}")
    result: dict[str, bytes] = {}
    for name in sorted(expected):
        path = output_dir / name
        try:
            st = path.lstat()
            if (not stat.S_ISREG(st.st_mode) or path.is_symlink() or st.st_nlink != 1
                    or st.st_size <= 0 or st.st_size > MAX_BYTES[name]):
                raise CandidateError(f"unsafe, empty, linked, or oversized candidate artifact: {name}")
            raw = path.read_bytes()
            if len(raw) != st.st_size or len(raw) > MAX_BYTES[name]:
                raise CandidateError(f"candidate artifact changed while being read: {name}")
            result[name] = raw
        except OSError as exc:
            raise CandidateError(f"cannot read candidate artifact {name}: {exc}") from exc
    return result


def _check_hash(value: Any, field: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise CandidateError(f"{field} must be a lowercase SHA-256")


def validate_public_outputs(output_dir: Path, phase: str = "final",
                            reference_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Check public schemas and bindings without reading private host evidence."""
    refs = reference_policy or load_reference_policy()
    if phase not in PHASE_FILES:
        raise CandidateError("phase must be hypothesis, training, or final")
    files = _read_output_set(output_dir, PHASE_FILES[phase])
    hypothesis = _strict_json(files["hypothesis.json"], "hypothesis.json")
    h_fields = {"schema", "case_id", "baseline_sha256", "model", "intervention",
                "primary_stratum", "expected_delta_sign", "application_scope", "public_evidence",
                "decision_policy_id", "predeclared_stop_condition", "primary_risk"}
    if set(hypothesis) != h_fields:
        raise CandidateError("hypothesis.json fields differ from the v2 allowlist")
    experiment = refs["experiment"]
    if (hypothesis.get("schema") != "case03-hypothesis/v2" or hypothesis.get("case_id") != "case-03"
            or hypothesis.get("model") != experiment["model"]
            or hypothesis.get("intervention") != experiment["intervention"]
            or hypothesis.get("primary_stratum") not in set(experiment["primary_strata"])
            or hypothesis.get("expected_delta_sign") not in {"positive", "negative", "uncertain"}
            or hypothesis.get("application_scope") not in {"COM_centered_only", "arbitrary_origin"}
            or hypothesis.get("decision_policy_id") != experiment["decision_policy_id"]
            or hypothesis.get("predeclared_stop_condition") != experiment["predeclared_stop_condition"]
            or hypothesis.get("primary_risk") not in set(experiment["primary_risks"])
            or hypothesis.get("baseline_sha256") != refs["source_pins"]["baseline_sha256"]):
        raise CandidateError("hypothesis is outside the frozen v2 experiment scope")
    _check_hash(hypothesis.get("baseline_sha256"), "hypothesis.baseline_sha256")
    evidence = hypothesis.get("public_evidence")
    if not isinstance(evidence, dict) or set(evidence) != {
            "split", "rule_id", "n", "baseline_primary_nac_mae_au",
            "baseline_all_validation_nac_mae_au", "diagnosis"}:
        raise CandidateError("hypothesis public_evidence fields differ from the v2 allowlist")
    expected_rule = (refs["public_diagnosis"]["low_gap_rule"] if hypothesis["primary_stratum"] == "low_gap"
                     else refs["public_diagnosis"]["geometry_ood_rule"])
    if (evidence.get("split") != refs["dataset"]["trainval_split_rule"] or evidence.get("rule_id") != expected_rule
            or type(evidence.get("n")) is not int or evidence["n"] <= 0
            or evidence.get("diagnosis") not in {"enriched", "not_enriched"}):
        raise CandidateError("hypothesis public split/stratum fields are invalid")
    for key in ("baseline_primary_nac_mae_au", "baseline_all_validation_nac_mae_au"):
        value = evidence.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise CandidateError(f"hypothesis public metric {key} must be finite")

    if phase == "hypothesis":
        return {"status": "PUBLIC_PREFLIGHT_PASS", "phase": phase, "checked": ["hypothesis.json"]}

    request = _strict_json(files["strategy_request.json"], "strategy_request.json")
    report = _strict_json(files["training_report.json"], "training_report.json")
    request_fields = {"schema", "case_id", "attempt_id", "nonce", "hypothesis_sha256", "lock_sha256",
                      "model", "baseline_sha256", "intervention", "primary_stratum", "primary_metric",
                      "phase_loss", "seed", "template_sha256", "scorer_source_sha256",
                      "scorer_source_closure_sha256", "scorer_image_digest", "resource_request",
                      "resource_request_sha256"}
    if set(request) != request_fields or request.get("schema") != "case03-strategy-request/v3" or request.get("case_id") != "case-03":
        raise CandidateError("strategy_request.json fields/schema differ from resource-planned v3")
    resources = request.get("resource_request")
    caps = refs["resources"]
    if (not isinstance(resources, dict)
            or set(resources) != {"cpus", "memory_gb", "wall_seconds", "accelerator", "gpu_count"}
            or any(type(resources.get(key)) is not int or resources[key] < 1
                   for key in ("cpus", "memory_gb", "wall_seconds"))
            or resources["wall_seconds"] > caps["slurm_wall_seconds"]
            or type(resources.get("gpu_count")) is not int or resources["gpu_count"] < 0
            or resources.get("accelerator") not in {"cpu", "gpu"}
            or (resources["accelerator"] == "cpu" and resources["gpu_count"] != 0)
            or (resources["accelerator"] == "gpu" and resources["gpu_count"] < 1)
            or request.get("resource_request_sha256") != _canonical_json_sha(resources)):
        raise CandidateError("resource request is malformed, over the scientific wall budget, or not hash-bound")
    for key in ("hypothesis_sha256", "lock_sha256", "baseline_sha256", "template_sha256",
                "scorer_source_sha256", "scorer_source_closure_sha256"):
        _check_hash(request.get(key), f"strategy_request.{key}")
    if (request.get("hypothesis_sha256") != _sha(files["hypothesis.json"])
            or request.get("baseline_sha256") != hypothesis.get("baseline_sha256")
            or request.get("model") != experiment["model"]
            or request.get("primary_stratum") != hypothesis.get("primary_stratum")
            or request.get("intervention") != {"name": experiment["intervention"], "parameters": {}}
            or request.get("primary_metric") != experiment["primary_metric"]
            or request.get("phase_loss") != experiment["phase_loss"]
            or request.get("seed") != experiment["seed"]
            or request.get("template_sha256") != refs["source_pins"]["template_sha256"]
            or request.get("scorer_source_sha256") != refs["source_pins"]["scorer_source_files"]["score_case03_v2_once.py"]
            or request.get("scorer_source_closure_sha256") != refs["source_pins"]["scorer_source_closure_sha256"]
            or not isinstance(request.get("scorer_image_digest"), str)
            or re.fullmatch(r"runtime-closure-sha256:[0-9a-f]{64}", request["scorer_image_digest"]) is None):
        raise CandidateError("strategy request does not bind the public hypothesis or fixed v2 strategy")
    report_fields = {"schema", "case_id", "attempt_id", "lock_sha256", "nonce", "hypothesis_sha256",
                     "strategy_request_sha256", "job_id", "source_sha256", "template_sha256",
                     "baseline_sha256", "model", "intervention", "primary_stratum",
                     "scorer_source_sha256", "scorer_source_closure_sha256", "scorer_image_digest",
                     "trainval_sha256", "heldout_geometry_sha256", "public_manifest_sha256",
                     "monotonic_started_ns", "monotonic_ended_ns", "training_seconds", "launch_count",
                     "checkpoint_epoch", "validation_metric", "trainable_parameter_names",
                     "trainable_parameter_count", "frozen_parameter_sha256_before",
                     "frozen_parameter_sha256_after", "output_sha256"}
    if set(report) != report_fields or report.get("schema") != "case03-training-report/v2" or report.get("case_id") != "case-03":
        raise CandidateError("training_report.json fields/schema differ from v2")
    for key in ("lock_sha256", "hypothesis_sha256", "strategy_request_sha256", "source_sha256",
                "template_sha256", "baseline_sha256", "scorer_source_sha256", "scorer_source_closure_sha256",
                "trainval_sha256", "heldout_geometry_sha256", "public_manifest_sha256",
                "frozen_parameter_sha256_before", "frozen_parameter_sha256_after", "output_sha256"):
        _check_hash(report.get(key), f"training_report.{key}")
    seconds = report.get("training_seconds")
    validation_metric = report.get("validation_metric")
    job_id = report.get("job_id")
    attempt_id = report.get("attempt_id")
    nonce = report.get("nonce")
    start, end = report.get("monotonic_started_ns"), report.get("monotonic_ended_ns")
    parameter_names = report.get("trainable_parameter_names")
    if (not isinstance(attempt_id, str) or not attempt_id
            or not isinstance(nonce, str) or not nonce
            or not isinstance(job_id, str) or not job_id
            or report.get("attempt_id") != request.get("attempt_id") or report.get("nonce") != request.get("nonce")
            or report.get("hypothesis_sha256") != request.get("hypothesis_sha256")
            or report.get("lock_sha256") != request.get("lock_sha256")
            or report.get("strategy_request_sha256") != _sha(files["strategy_request.json"])
            or report.get("baseline_sha256") != request.get("baseline_sha256")
            or report.get("template_sha256") != request.get("template_sha256")
            or report.get("model") != experiment["model"] or report.get("intervention") != experiment["intervention"]
            or report.get("primary_stratum") != request.get("primary_stratum")
            or report.get("output_sha256") != _sha(files["model_state_dict.pt"])
            or type(report.get("launch_count")) is not int or report["launch_count"] != 1
            or type(report.get("checkpoint_epoch")) is not int or report["checkpoint_epoch"] < 1
            or type(report.get("trainable_parameter_count")) is not int
            or not isinstance(parameter_names, list)
            or any(not isinstance(name, str) or not name for name in parameter_names)
            or report["trainable_parameter_count"] != len(parameter_names)
            or len(set(parameter_names)) != len(parameter_names)
            or report.get("trainval_sha256") != refs["source_pins"]["trainval_sha256"]
            or report.get("heldout_geometry_sha256") != refs["source_pins"]["heldout_geometry_sha256"]
            or report.get("public_manifest_sha256") != refs["source_pins"]["public_manifest_sha256"]
            or type(start) is not int or type(end) is not int or end <= start
            or isinstance(validation_metric, bool) or not isinstance(validation_metric, (int, float))
            or not math.isfinite(validation_metric)
            or isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds)
            or not 0 < seconds <= refs["resources"]["training_seconds"]
            or abs(seconds - (end - start) / 1e9) > refs["tolerances"]["training_clock_consistency_seconds"]):
        raise CandidateError("training report does not match the one-run locked training output")

    if phase == "training":
        return {"status": "PUBLIC_PREFLIGHT_PASS", "phase": phase,
                "checked": sorted(TRAINING_FILES)}

    decision = _strict_json(files["final_decision.json"], "final_decision.json")
    expected_decision_fields = {
        "schema", "case_id", "attempt_id", "hypothesis_sha256", "lock_sha256", "aggregate_sha256",
        "reported_primary_n", "reported_mean_delta_baseline_minus_tuned_au", "reported_percentile_95_ci_au",
        "reported_energy_output_max_abs_delta_ha", "reported_force_output_max_abs_delta_ha_per_bohr",
        "reported_gap_output_max_abs_delta_ha", "finding", "action", "reason_codes",
        "prior_prediction_assessment", "acknowledged_primary_risk", "claim_scope", "limitations",
        "next_computation", "next_computation_budget_minutes"}
    if set(decision) != expected_decision_fields or decision.get("schema") != "case03-final-decision/v2":
        raise CandidateError("final_decision.json fields/schema differ from v2")
    for key in ("hypothesis_sha256", "lock_sha256", "aggregate_sha256"):
        _check_hash(decision.get(key), f"final_decision.{key}")
    return {"status": "PUBLIC_PREFLIGHT_PASS", "phase": phase,
            "checked": sorted(FINAL_FILES), "note": "host receipt and scientific rubric not checked"}


def _safe_private_file(attempt: Path, name: str) -> bytes:
    path = attempt / name
    try:
        st = path.lstat()
        if (not stat.S_ISREG(st.st_mode) or path.is_symlink() or st.st_nlink != 1
                or st.st_mode & 0o222):
            raise EnvironmentError(f"trusted attempt file is not immutable/regular: {name}")
        return path.read_bytes()
    except OSError as exc:
        raise EnvironmentError(f"trusted attempt evidence is unavailable: {name}") from exc


def _validate_runner_context(context: dict[str, Any]) -> None:
    if (context.get("schema") not in {"compchembench.runner-context/v1", "compchembench.runner-context/v2"}
            or not isinstance(context.get("attempt_id"), str)
            or re.fullmatch(r"[0-9a-f]{32}", context["attempt_id"]) is None
            or not isinstance(context.get("nonce"), str) or len(context["nonce"]) < 40
            or not isinstance(context.get("run_id"), str) or not context["run_id"]
            or context.get("task_id") not in {"case-03", "case03"}
            or context.get("execution_backend") not in {"local", "scheduler"}
            or not isinstance(context.get("execution_id"), str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}", context["execution_id"]) is None
            or context.get("task_config_sha256") != PINNED_TASK_CONFIG_SHA256
            or context.get("instruction_sha256") != PINNED_EFFECTIVE_PROMPT_SHA256
            or context.get("image_identity_kind") != "runtime-closure-sha256"
            or not isinstance(context.get("runtime_closure_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", context["runtime_closure_sha256"]) is None
            or context.get("image_id") != "runtime-closure-sha256:" + context.get("runtime_closure_sha256", "")
            or not isinstance(context.get("artifact_manifest"), dict)
            or context.get("artifact_manifest_sha256") != _canonical_json_sha(context["artifact_manifest"])):
        raise EnvironmentError("host runner context identity or artifact manifest is invalid")


def _load_runner_context() -> tuple[dict[str, Any], bytes]:
    context_path = Path("/trusted/runner-context.json")
    try:
        st = context_path.lstat()
        if (not stat.S_ISREG(st.st_mode) or context_path.is_symlink() or st.st_nlink != 1
                or st.st_uid != 0 or st.st_mode & 0o222 or st.st_size <= 0 or st.st_size > 2 * 1024 * 1024):
            raise EnvironmentError("root-sealed runner context is not an immutable regular file")
        raw = context_path.read_bytes()
    except OSError as exc:
        raise EnvironmentError("root-sealed runner context is unavailable") from exc
    try:
        context = _strict_json(raw, "runner-context.json")
    except CandidateError as exc:
        raise EnvironmentError("host runner context is not valid strict JSON") from exc
    _validate_runner_context(context)
    return context, raw


def _check_runner_artifact_binding(context: dict[str, Any], files: dict[str, bytes]) -> None:
    """Require this runner's immutable artifact snapshot to contain exact outputs."""
    manifest = context.get("artifact_manifest")
    collected = manifest.get("collected") if isinstance(manifest, dict) else None
    if not isinstance(collected, list):
        raise EnvironmentError("runner artifact manifest has no collected file inventory")
    records: dict[str, dict[str, Any]] = {}
    for entry in collected:
        if not isinstance(entry, dict) or not isinstance(entry.get("files"), list):
            raise EnvironmentError("runner artifact manifest contains malformed collected entries")
        for record in entry["files"]:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise EnvironmentError("runner artifact manifest contains malformed file records")
            rel = Path(record["path"])
            if rel.is_absolute() or ".." in rel.parts or not rel.parts:
                raise EnvironmentError("runner artifact manifest contains an unsafe path")
            if rel.as_posix() in records:
                raise EnvironmentError("runner artifact manifest repeats a path")
            records[rel.as_posix()] = record
    for name, raw in files.items():
        record = records.get(f"outputs/{name}")
        if (record is None or record.get("sha256") != _sha(raw)
                or record.get("bytes") != len(raw)):
            raise EnvironmentError(f"current runner artifact snapshot does not bind outputs/{name}")


def _validate_public_diagnostics_policy(diagnostics: dict[str, Any], refs: dict[str, Any]) -> None:
    dataset, experiment, pins, diagnosis = (
        refs["dataset"], refs["experiment"], refs["source_pins"], refs["public_diagnosis"])
    if (diagnostics.get("schema") != "case03-public-validation-diagnostics/v1"
            or diagnostics.get("source") != "trusted_public_train_validation_recompute"
            or diagnostics.get("model") != experiment["model"]
            or diagnostics.get("intervention") != experiment["intervention"]
            or diagnostics.get("split") != dataset["trainval_split_rule"]
            or diagnostics.get("baseline_sha256") != pins["baseline_sha256"]
            or diagnostics.get("trainval_sha256") != pins["trainval_sha256"]
            or diagnostics.get("geometry_ood_rule") != diagnosis["geometry_ood_rule"]):
        raise EnvironmentError("trusted public diagnostics differ from refs.json protocol identities")
    threshold = diagnostics.get("low_gap_threshold_ha_train_only")
    low_gap, geometry_ood = diagnostics.get("low_gap"), diagnostics.get("geometry_ood")
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or abs(threshold - diagnosis["low_gap_threshold_ha_train_only"])
            > diagnosis["low_gap_threshold_abs_tolerance_ha"]
            or not isinstance(low_gap, dict) or type(low_gap.get("n")) is not int or low_gap["n"] <= 0
            or not isinstance(geometry_ood, dict) or type(geometry_ood.get("n")) is not int
            or geometry_ood["n"] != round(dataset["validation_rows"] * diagnosis["geometry_ood_validation_fraction"])
            or diagnostics.get("public_labels_only") is not True):
        raise EnvironmentError("trusted public diagnostic rules or counts differ from refs.json")


def _verify_local_execution_receipt(receipt: dict[str, Any], attempt: Path,
                                    state: dict[str, Any], lock: dict[str, Any]) -> None:
    """Verify a runner-owned local execution envelope and its immutable raw closure."""
    request = lock.get("resource_request")
    actual = receipt.get("actual_resources")
    environment = receipt.get("software_environment")
    try:
        started, ended = receipt["execution_started_unix_ns"], receipt["execution_ended_unix_ns"]
        registered = state["preregistered_at_unix_ns"]
    except (KeyError, TypeError) as exc:
        raise EnvironmentError("local execution receipt lacks protected timing anchors") from exc
    elapsed = (ended - started) / 1e9 if type(started) is int and type(ended) is int else -1
    expected = (None if not isinstance(request, dict) else {
        "cpus": request.get("cpus"), "memory_gb": request.get("memory_gb"),
        "gpu_count": request.get("gpu_count"), "wall_seconds": request.get("wall_seconds"),
        "elapsed_seconds": receipt.get("execution_elapsed_seconds")})
    env_sha = hashlib.sha256(json.dumps(environment, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode()).hexdigest() if isinstance(environment, dict) else None
    if (type(registered) is not int or started < registered or ended < started
            or not isinstance(request, dict) or not isinstance(actual, dict) or actual != expected
            or type(receipt.get("execution_elapsed_seconds")) not in (int, float)
            or not math.isfinite(float(receipt["execution_elapsed_seconds"]))
            or receipt["execution_elapsed_seconds"] < 0 or elapsed > request.get("wall_seconds", 0)
            or elapsed > 1200
            or abs(float(receipt["execution_elapsed_seconds"]) - elapsed) > 1.0
            or not isinstance(environment, dict) or not environment
            or receipt.get("software_environment_sha256") != env_sha):
        raise EnvironmentError("local execution timing/resources/software do not match the sealed request")
    evidence_raw = _safe_private_file(attempt, "evidence-manifest.json")
    if hashlib.sha256(evidence_raw).hexdigest() != receipt.get("evidence_manifest_sha256"):
        raise EnvironmentError("local execution evidence manifest digest mismatch")
    try:
        evidence = json.loads(evidence_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EnvironmentError("local execution evidence manifest is malformed") from exc
    expected_evidence = {"executed_source", "stdout", "stderr", "input_manifest"}
    if (not isinstance(evidence, dict) or evidence.get("schema") != "case03-v2-local-execution-evidence/v1"
            or evidence.get("attempt_id") != receipt.get("attempt_id")
            or not isinstance(evidence.get("files"), dict)
            or set(evidence["files"]) != expected_evidence):
        raise EnvironmentError("local execution evidence closure is incomplete")
    names = set()
    captured_bytes = {}
    for name, item in evidence["files"].items():
        rel = item.get("path") if isinstance(item, dict) else None
        digest = item.get("sha256") if isinstance(item, dict) else None
        path = PurePosixPath(rel) if isinstance(rel, str) else None
        if (not isinstance(name, str) or not name or path is None or path.is_absolute()
                or any(part in {"", ".", ".."} for part in path.parts)
                or path.parts[0] != "execution-capture"
                or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
            raise EnvironmentError("local execution evidence entry is malformed")
        target = attempt.joinpath(*path.parts)
        try:
            target.resolve(strict=True).relative_to(attempt.resolve(strict=True))
            stat_result = target.lstat()
            raw = target.read_bytes()
        except (OSError, ValueError) as exc:
            raise EnvironmentError("local raw evidence is unavailable or escapes the attempt") from exc
        if (not stat.S_ISREG(stat_result.st_mode) or target.is_symlink() or stat_result.st_nlink != 1
                or stat_result.st_mode & 0o222 or hashlib.sha256(raw).hexdigest() != digest):
            raise EnvironmentError("local raw evidence is mutable, redirected, or hash-mismatched")
        captured_bytes[name] = raw
        expected_digest_key = {"executed_source": "source_sha256", "stdout": "stdout_sha256",
                               "stderr": "stderr_sha256", "input_manifest": "input_manifest_sha256"}[name]
        if digest != receipt.get(expected_digest_key):
            raise EnvironmentError(f"local {name} evidence does not match the protected execution receipt")
        names.add(path.as_posix())
    capture_root = attempt / "execution-capture"
    actual_names = set()
    for candidate in capture_root.rglob("*"):
        if candidate.is_symlink():
            raise EnvironmentError("local execution closure contains a symlink")
        if candidate.is_file():
            actual_names.add(candidate.relative_to(attempt).as_posix())
        elif not candidate.is_dir():
            raise EnvironmentError("local execution closure contains a special file")
    if actual_names != names:
        raise EnvironmentError("local execution receipt does not close over every captured raw file")
    try:
        input_manifest = json.loads(captured_bytes["input_manifest"])
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
        raise EnvironmentError("local input manifest is missing or malformed") from exc
    expected_inputs = {key: lock.get(key) for key in (
        "baseline_sha256", "source_sha256", "template_sha256", "trainval_sha256",
        "heldout_geometry_sha256", "public_manifest_sha256")}
    if (input_manifest != {"schema": "case03-v2-local-input-manifest/v1",
                           "inputs": expected_inputs}
            or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
                   for value in expected_inputs.values())):
        raise EnvironmentError("local input manifest differs from frozen scientific input hashes")
    if receipt.get("execution_manifest_sha256") != hashlib.sha256(evidence_raw).hexdigest():
        raise EnvironmentError("local execution manifest is not bound by the terminal receipt")


def verify_trusted_attempt(output_dir: Path, context: dict[str, Any],
                           private_root: Path | None = None,
                           reference_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Recheck a fully sealed same-attempt bundle; never reads private row data."""
    refs = reference_policy or load_reference_policy()
    attempt_id = context.get("attempt_id") if isinstance(context, dict) else None
    if not isinstance(attempt_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{8,64}", attempt_id) is None:
        raise EnvironmentError("host runner attempt ID is malformed")
    try:
        private_root = private_root or _private_root()
        _verify_pinned_private_sources(private_root)
        protocol_path = private_root / "case03_v2_protocol.py"
        protocol = types.ModuleType("case03_v2_protocol_verified")
        protocol.__file__ = str(protocol_path)
        exec(compile(protocol_path.read_bytes(), str(protocol_path), "exec"), protocol.__dict__)
    except Exception as exc:
        raise EnvironmentError("canonical trusted Case03 v2 protocol is unavailable") from exc
    attempt_root = private_root / "runner-attempts"
    attempt = attempt_root / attempt_id
    try:
        attempt = protocol._safe_attempt_dir(attempt)
        state = protocol._read_state(attempt)
    except Exception as exc:
        raise EnvironmentError(f"trusted same-attempt context is unavailable: {exc}") from exc
    if state.get("phase") != "GRADED" or state.get("scoring_invocations") != 1:
        raise EnvironmentError("trusted attempt is not a completed one-score GRADED transaction")

    files = _read_output_set(output_dir, FINAL_FILES)
    private_names = {name: name for name in FINAL_FILES}
    for public_name, private_name in private_names.items():
        private_bytes = _safe_private_file(attempt, private_name)
        if files[public_name] != private_bytes:
            raise CandidateError(f"candidate artifact differs from the sealed same-attempt bytes: {public_name}")

    hypothesis_raw = _safe_private_file(attempt, "hypothesis.json")
    request_raw = _safe_private_file(attempt, "strategy_request.json")
    report_raw = _safe_private_file(attempt, "training_report.json")
    weights_raw = _safe_private_file(attempt, "model_state_dict.pt")
    decision_raw = _safe_private_file(attempt, "final_decision.json")
    lock = protocol._read_json(attempt / "strategy-lock.json")
    try:
        request = protocol.strict_json(request_raw)
        report = protocol.strict_json(report_raw)
        diagnostics = protocol._read_json(attempt / "public-diagnostics.json")
        _validate_public_diagnostics_policy(diagnostics, refs)
        hypothesis = protocol.validate_hypothesis_bytes(hypothesis_raw, diagnostics)
        expected_request = protocol.build_strategy_request(lock)
    except protocol.V2CandidateError as exc:
        raise CandidateError(str(exc)) from exc
    except Exception as exc:
        raise EnvironmentError(f"frozen H/R/report context is invalid: {exc}") from exc
    training_policy = refs["resources"]
    if (lock.get("training", {}).get("max_training_seconds") != training_policy["training_seconds"]
            or lock.get("training", {}).get("total_budget_seconds") != training_policy["whole_attempt_seconds"]):
        raise EnvironmentError("host training lock differs from the pinned v2 training/whole-attempt caps")
    if request != expected_request:
        raise EnvironmentError("host-generated strategy request differs from the frozen lock")
    if lock.get("scorer_image_digest") != context.get("image_id"):
        raise EnvironmentError("sealed attempt image differs from host runner identity")
    if (context.get("nonce") != lock.get("nonce")
            or context.get("attempt_id") != lock.get("attempt_id")
            or context.get("task_id") not in {"case-03", "case03"}):
        raise EnvironmentError("sealed host attempt does not match this runner context identity")
    _check_runner_artifact_binding(context, files)
    if (protocol.sha256_bytes(hypothesis_raw) != state.get("hypothesis_sha256")
            or protocol.sha256_bytes(request_raw) != state.get("strategy_request_sha256")
            or protocol.sha256_bytes(report_raw) != state.get("training_report_sha256")
            or protocol.sha256_bytes(weights_raw) != state.get("weights_sha256")
            or protocol.sha256_bytes(decision_raw) != state.get("final_decision_sha256")
            or lock.get("lock_sha256") != state.get("lock_sha256")):
        raise EnvironmentError("sealed attempt state digests do not match its artifacts")

    receipt_raw = _safe_private_file(attempt, "attempt-receipt.json")
    receipt = protocol.strict_json(receipt_raw)
    if protocol.sha256_bytes(receipt_raw) != state.get("receipt_sha256"):
        raise EnvironmentError("terminal host receipt digest differs from the attempt state")
    backend = receipt.get("backend")
    if (receipt.get("schema") != "case03-v2-attempt-receipt/v3"
            or backend not in {"local", "scheduler"}
            or backend != context.get("execution_backend")
            or receipt.get("execution_id") != context.get("execution_id")):
        raise EnvironmentError("trusted execution identity differs from runner context")
    if backend == "scheduler" and (receipt.get("slurm_state") != "COMPLETED"
            or receipt.get("slurm_exit_code") not in ("0:0", 0, "0")):
        raise EnvironmentError("same-attempt scheduler evidence is not terminal success")
    if backend == "local" and (receipt.get("terminal_status") != "COMPLETED"
            or receipt.get("execution_exit_code") != 0):
        raise EnvironmentError("same-attempt local execution is not terminal success")
    expected_receipt_pins = {
        "schema": "case03-v2-attempt-receipt/v3", "backend": backend,
        "execution_id": context.get("execution_id"), "attempt_id": attempt_id,
        "nonce": lock.get("nonce"),
        "hypothesis_sha256": state.get("hypothesis_sha256"),
        "strategy_request_sha256": state.get("strategy_request_sha256"),
        "training_report_sha256": state.get("training_report_sha256"),
        "weights_sha256": state.get("weights_sha256"),
        "source_sha256": lock.get("source_sha256"), "template_sha256": lock.get("template_sha256"),
        "resource_request": lock.get("resource_request"),
        "resource_request_sha256": protocol.sha256_bytes(protocol.canonical_bytes(lock.get("resource_request"))),
    }
    if any(receipt.get(key) != value for key, value in expected_receipt_pins.items()):
        raise EnvironmentError("terminal execution receipt does not bind the frozen artifacts and lock")
    if backend == "local":
        _verify_local_execution_receipt(receipt, attempt, state, lock)
    else:
        if receipt.get("slurm_state") != "COMPLETED" or receipt.get("slurm_exit_code") not in ("0:0", 0, "0"):
            raise EnvironmentError("same-attempt Slurm evidence is not terminal success")
        expected_receipt_pins = {
            "schema": "case03-v2-attempt-receipt/v3", "attempt_id": attempt_id,
            "nonce": lock.get("nonce"),
            "hypothesis_sha256": state.get("hypothesis_sha256"),
            "strategy_request_sha256": state.get("strategy_request_sha256"),
            "training_report_sha256": state.get("training_report_sha256"),
            "weights_sha256": state.get("weights_sha256"),
            "source_sha256": lock.get("source_sha256"), "template_sha256": lock.get("template_sha256"),
            "resource_request": lock.get("resource_request"),
            "resource_request_sha256": protocol.sha256_bytes(protocol.canonical_bytes(lock.get("resource_request"))),
        }
        if any(receipt.get(key) != value for key, value in expected_receipt_pins.items()):
            raise EnvironmentError("terminal Slurm receipt does not bind the frozen artifacts and lock")
        remote_root = receipt.get("remote_attempt_root")
        remote_path = PurePosixPath(remote_root) if isinstance(remote_root, str) else None
        if (remote_path is None or not remote_path.is_absolute() or ".." in remote_path.parts
                or remote_path.name != attempt_id or remote_path.as_posix() != remote_root):
            raise EnvironmentError("terminal receipt has no safe attempt-specific host work path")

        evidence_raw = _safe_private_file(attempt, "evidence-manifest.json")
        if protocol.sha256_bytes(evidence_raw) != receipt.get("evidence_manifest_sha256"):
            raise EnvironmentError("terminal evidence manifest digest mismatch")
        evidence = protocol.strict_json(evidence_raw)
        expected_evidence_keys = {"slurm_script", "spool_script", "stdout", "stderr", "sacct",
                                  "running_allocation"}
        if (evidence.get("schema") != "case03-v2-training-evidence/v1"
                or evidence.get("attempt_id") != attempt_id
                or set(evidence.get("files", {})) != expected_evidence_keys):
            raise EnvironmentError("terminal training evidence manifest is incomplete")
        receipt_file_digests = {
            "slurm_script": "slurm_script_sha256", "spool_script": "slurm_spool_script_sha256",
            "stdout": "stdout_sha256", "stderr": "stderr_sha256", "sacct": "sacct_record_sha256",
            "running_allocation": "gpu_allocation_evidence_sha256",
        }
        captured_evidence: dict[str, bytes] = {}
        for key, item in evidence["files"].items():
            rel = item.get("path") if isinstance(item, dict) else None
            digest = item.get("sha256") if isinstance(item, dict) else None
            if (not isinstance(rel, str) or Path(rel).is_absolute() or ".." in Path(rel).parts
                    or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
                raise EnvironmentError("terminal training evidence file entry is malformed")
            path = private_root / rel
            try:
                path.resolve(strict=True).relative_to(private_root.resolve(strict=True))
                st = path.lstat()
                if not stat.S_ISREG(st.st_mode) or path.is_symlink() or st.st_nlink != 1:
                    raise EnvironmentError("terminal training evidence path is unsafe")
                if _sha(path.read_bytes()) != digest:
                    raise EnvironmentError("terminal training evidence digest mismatch")
                captured_evidence[key] = path.read_bytes()
            except (OSError, ValueError) as exc:
                raise EnvironmentError("terminal training evidence path is unavailable/outside private root") from exc
            if receipt.get(receipt_file_digests[key]) != digest:
                raise EnvironmentError(f"terminal receipt and manifest disagree for {key}")
        if captured_evidence["slurm_script"] != captured_evidence["spool_script"]:
            raise EnvironmentError("submitted Slurm script differs from the captured scheduler spool")
        try:
            sacct_rows = [line.split("|") for line in captured_evidence["sacct"].decode("utf-8").splitlines() if line]
        except UnicodeDecodeError as exc:
            raise EnvironmentError("terminal four-column sacct record is not UTF-8") from exc
        if (len(sacct_rows) != 1 or len(sacct_rows[0]) != 9
                or sacct_rows[0][1:3] != ["COMPLETED", "0:0"]
                or not sacct_rows[0][3].isdigit()
                or sacct_rows[0][0] != str(receipt.get("job_id"))
                or int(sacct_rows[0][3]) != receipt.get("slurm_elapsed_seconds")):
            raise EnvironmentError("raw terminal sacct record is not one matching resource-bearing COMPLETED/0:0 row")
        resources = lock["resource_request"]
        req_mem = re.fullmatch(r"([0-9]+)G[nNcC]?", sacct_rows[0][5])
        tres = dict(item.split("=", 1) for item in sacct_rows[0][6].split(",") if "=" in item)
        actual_gpu_count = (int(tres["gres/gpu"]) if "gres/gpu" in tres else
                            sum(int(value) for key, value in tres.items()
                                if key.startswith("gres/gpu:")) if any(key.startswith("gres/gpu:") for key in tres)
                            else 0)
        if (not req_mem or int(sacct_rows[0][4]) != resources["cpus"]
                or int(req_mem.group(1)) != resources["memory_gb"]
                or not sacct_rows[0][7] or not sacct_rows[0][8]
                or tres.get("cpu") != str(resources["cpus"])
                or tres.get("mem") not in {f"{resources['memory_gb']}G", f"{resources['memory_gb']}Gn"}
                or actual_gpu_count != resources["gpu_count"]):
            raise EnvironmentError("raw scheduler resource allocation differs from the prelaunch request")
        allocation_raw = captured_evidence["running_allocation"]
        try:
            expected_remote_root = remote_root
            allocation = protocol.validate_running_gpu_allocation(
                allocation_raw, job_id=str(receipt.get("job_id")),
                job_name="c03v2-" + attempt_id[:20], user=None,
                workdir=expected_remote_root,
                resource_request=resources)
        except Exception as exc:
            raise EnvironmentError(f"same-attempt RUNNING allocation evidence is invalid: {exc}") from exc
        if sacct_rows[0][7:9] != [allocation["partition"], allocation["account"]]:
            raise EnvironmentError("raw sacct account/partition differ from same-job running allocation")
        if allocation["work_dir"] != remote_root:
            raise EnvironmentError("same-job running allocation work path differs from the protected receipt")
        expected_scheduler_resources = {"cpus": resources["cpus"], "memory_gb": resources["memory_gb"],
            "gpu_count": resources["gpu_count"], "partition": allocation["partition"], "account": allocation["account"],
            "wall_seconds": resources["wall_seconds"],
            "gpu_allocation_source": "scontrol_running_job_resource_fields",
            "gpu_allocation_evidence_sha256": protocol.sha256_bytes(allocation_raw),
            "gpu_node": allocation["node"]}
        if (receipt.get("gpu_allocation_evidence_sha256") != protocol.sha256_bytes(allocation_raw)
                or receipt.get("gpu_node") != allocation["node"]
                or receipt.get("scheduler_resources") != expected_scheduler_resources):
            raise EnvironmentError("receipt scheduler resource/wall evidence differs from the accepted request")

    score_receipt = protocol._read_json(attempt / "score-receipt.json")
    try:
        score_receipt_sha = protocol._validate_score_receipt(score_receipt, attempt, lock, state)
    except Exception as exc:
        raise EnvironmentError(f"trusted private score receipt/source closure is invalid: {exc}") from exc
    aggregate_raw = _safe_private_file(attempt, "aggregate.json")
    aggregate = protocol.strict_json(aggregate_raw)
    if (_sha(aggregate_raw) != state.get("aggregate_sha256")
            or score_receipt_sha != aggregate.get("score_receipt_sha256")):
        raise EnvironmentError("trusted sanitized aggregate does not match its score receipt/state")
    try:
        if abs(float(score_receipt["scoring_seconds"]) - float(aggregate["scoring_seconds"])) > refs["tolerances"]["score_duration_consistency_seconds"]:
            raise EnvironmentError("score duration differs from refs.json consistency tolerance")
        protocol.validate_aggregate(aggregate, lock, state)
        private_report = protocol._read_json(attempt / "private-score-report.json")
        _validate_aggregate_reference_policy(aggregate, refs, private_report)
        projected = protocol.aggregate_from_scorer_report(
            private_report, lock, receipt, score_receipt, attempt)
        nonprojection_fields = {"aggregate_sha256", "elapsed_before_decision_seconds", "budget_guard_pass"}
        for key, value in projected.items():
            if key not in nonprojection_fields and aggregate.get(key) != value:
                raise EnvironmentError(f"sanitized aggregate differs from trusted scorer projection: {key}")
        rubric = protocol.grade_final_decision(decision_raw, hypothesis, lock, aggregate,
                                               protocol.sha256_bytes(aggregate_raw))
        expected_action = ("adopt_restricted" if rubric.get("finding") == "improved"
                           and rubric.get("guards_pass") is True
                           and hypothesis.get("application_scope") == refs["experiment"]["adoption_scope"]
                           else refs["experiment"]["fallback_action"])
        if rubric.get("action") != expected_action:
            raise EnvironmentError("trusted final action differs from the refs.json adoption policy")
    except protocol.V2CandidateError as exc:
        raise CandidateError(str(exc)) from exc
    except Exception as exc:
        raise EnvironmentError(f"trusted aggregate or decision evidence is invalid: {exc}") from exc
    saved_rubric = protocol._read_json(attempt / "decision-rubric.json")
    for key, value in rubric.items():
        if saved_rubric.get(key) != value:
            raise EnvironmentError("saved host decision rubric differs from independent recomputation")
    if (saved_rubric.get("guards_pass") is not True
            or saved_rubric.get("whole_attempt_budget_pass") is not True
            or state.get("graded") is not True):
        raise CandidateError("measured scientific or runtime guard failed")
    return {"status": "PASS", "reward": 1.0, "finding": rubric["finding"],
            "action": rubric["action"], "primary_stratum": lock["strategy"]["primary_stratum"],
            "n": aggregate["n"], "aggregate_sha256": state["aggregate_sha256"]}


def _validate_aggregate_reference_policy(aggregate: dict[str, Any], refs: dict[str, Any],
                                         private_report: dict[str, Any]) -> None:
    """Recheck the scorer aggregate against the reviewed public policy values."""
    stats = refs["statistics"]
    resources = refs["resources"]
    guards = refs["scientific_guards"]
    if (type(aggregate.get("n")) is not int
            or aggregate["n"] < stats["minimum_primary_sample_count"]
            or aggregate.get("bootstrap_replicates") != stats["bootstrap_replicates"]
            or aggregate.get("bootstrap_seed") != stats["bootstrap_seed"]
            or aggregate.get("budget_cap_seconds") != resources["whole_attempt_seconds"]):
        raise EnvironmentError("trusted aggregate count, bootstrap or budget differs from refs.json")
    expected_delta = float(aggregate["baseline_primary_nac_mae_au"]) - float(aggregate["tuned_primary_nac_mae_au"])
    if abs(float(aggregate["mean_delta_baseline_minus_tuned_au"]) - expected_delta) > refs["tolerances"]["aggregate_delta_abs_au"]:
        raise EnvironmentError("trusted aggregate paired delta differs from refs.json tolerance")
    paired = private_report.get("models", {}).get("painn", {}).get("paired_primary_nac_delta", {})
    if paired.get("paired_unit") != stats["paired_unit"]:
        raise EnvironmentError("trusted primary comparison unit differs from refs.json")
    expected_guards = {
        "energy_guard_pass": aggregate["energy_output_max_abs_delta_ha"] <= guards["energy_output_max_abs_delta_ha"],
        "force_guard_pass": aggregate["force_output_max_abs_delta_ha_per_bohr"] <= guards["force_output_max_abs_delta_ha_per_bohr"],
        "gap_guard_pass": aggregate["gap_output_max_abs_delta_ha"] <= guards["gap_output_max_abs_delta_ha"],
        "rotation_guard_pass": aggregate["rotation_nac_residual_max_abs_per_bohr"] <= guards["rotation_nac_residual_max_abs_per_bohr"],
        "permutation_guard_pass": aggregate["permutation_nac_residual_max_abs_per_bohr"] <= guards["permutation_nac_residual_max_abs_per_bohr"],
        "origin_term_guard_pass": aggregate["translation_origin_term_residual_max_abs_ha_per_bohr"] <= guards["translation_origin_term_residual_max_abs_ha_per_bohr"],
        "budget_guard_pass": aggregate["elapsed_before_decision_seconds"] <= resources["whole_attempt_seconds"],
    }
    if any(aggregate.get(key) is not expected for key, expected in expected_guards.items()):
        raise EnvironmentError("trusted aggregate scientific/runtime guard results differ from refs.json")


def verify_candidate_rejection(output_dir: Path, context: dict[str, Any],
                               context_sha256: str, private_root: Path) -> dict[str, Any] | None:
    """Return a zero-reward FAIL only for host-sealed, current-attempt rejection proof."""
    attempt_id = context.get("attempt_id")
    if not isinstance(attempt_id, str) or re.fullmatch(r"[0-9a-f]{32}", attempt_id) is None:
        raise EnvironmentError("host runner attempt ID is malformed")
    rejection_root = private_root / "runner-rejections"
    receipt_path = rejection_root / f"{attempt_id}.receipt.json"
    if not receipt_path.exists() and not receipt_path.is_symlink():
        return None
    _verify_pinned_private_sources(private_root)
    receipt_raw = _safe_private_file(rejection_root, receipt_path.name)
    try:
        receipt = _strict_json(receipt_raw, "candidate-rejection receipt")
    except CandidateError as exc:
        raise EnvironmentError("candidate-rejection receipt is malformed") from exc
    expected = {
        "schema": "case03-v2-candidate-rejection-receipt/v1",
        "attempt_id": attempt_id, "nonce": context.get("nonce"),
        "run_id": context.get("run_id"), "task_id": "case-03",
        "task_config_sha256": PINNED_TASK_CONFIG_SHA256,
        "instruction_sha256": PINNED_EFFECTIVE_PROMPT_SHA256,
        "image_id": context.get("image_id"), "profile_id": "bench25-case03-v2-author-gold",
        "scorer_source_closure_sha256": PINNED_PRIVATE_SOURCE_CLOSURE_SHA256,
        "runner_context_sha256": context_sha256,
        "artifact_manifest_sha256": context.get("artifact_manifest_sha256"),
        "event_path": f"runner-rejections/{attempt_id}.event.json",
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise EnvironmentError("candidate-rejection proof does not match this runner context and pins")
    if receipt.get("profile_sha256") != PINNED_PROFILE_SHA256:
        raise EnvironmentError("candidate-rejection profile digest differs from the reviewed profile")
    health = receipt.get("broker_health")
    if health != {"started": True, "running": False, "fatal_error": None, "host_error_count": 0}:
        raise EnvironmentError("candidate-rejection proof records an unhealthy host")
    reasons = {"HYPOTHESIS_REJECTED", "FINAL_DECISION_REJECTED", "ARTIFACT_INVENTORY_REJECTED",
               "TYPED_PROTOCOL_REJECTED", "DUPLICATE_OR_PHASE_REJECTED", "TRAINING_BUDGET_OVERRUN"}
    if receipt.get("reason_code") not in reasons:
        raise EnvironmentError("candidate-rejection reason is not allowlisted")
    event_path = private_root / receipt["event_path"]
    event_raw = _safe_private_file(event_path.parent, event_path.name)
    if _sha(event_raw) != receipt.get("event_sha256"):
        raise EnvironmentError("candidate-rejection event digest differs from its receipt")
    try:
        event = _strict_json(event_raw, "candidate-rejection event")
    except CandidateError as exc:
        raise EnvironmentError("candidate-rejection event is malformed") from exc
    snapshot = receipt.get("candidate_inventory")
    manifest_outputs = _context_output_records_for_rejection(context)
    if (event.get("schema") != "case03-v2-candidate-rejection-event/v1"
            or event.get("attempt_id") != attempt_id or event.get("nonce") != context.get("nonce")
            or event.get("reason_code") != receipt.get("reason_code")
            or event.get("phase") != receipt.get("phase")
            or event.get("state_sha256") != receipt.get("state_sha256")
            or not isinstance(event.get("request_id"), str)
            or re.fullmatch(r"[0-9a-f]{32}", event["request_id"]) is None
            or not isinstance(event.get("request_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", event["request_sha256"]) is None
            or event.get("candidate_error_class") not in {"CandidateRPCError", "Case03V2CandidateError",
                "V2CandidateError", "CandidateError", "ClientCandidateError", "RunnerOutputInventory",
                "TrustedBudgetEvidence", "JSONDecodeError"}
            or event.get("candidate_inventory") != snapshot.get("files")
            or event.get("candidate_names_sha256") != snapshot.get("names_sha256")
            or receipt.get("manifest_outputs") != manifest_outputs):
        raise EnvironmentError("candidate-rejection event, manifest, and receipt do not close")
    if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("names"), list)
            or snapshot.get("names") != sorted(snapshot["names"])
            or snapshot.get("names_sha256") != _sha(json.dumps(
                snapshot["names"], ensure_ascii=False, separators=(",", ":")).encode())
            or not isinstance(snapshot.get("files"), dict)):
        raise EnvironmentError("candidate-rejection inventory snapshot is malformed")
    if sorted(snapshot["files"]) != snapshot["names"]:
        raise EnvironmentError("candidate-rejection inventory names differ from file record keys")
    if set(snapshot["files"]) != set(snapshot["names"]):
        raise EnvironmentError("candidate-rejection inventory names and file records differ")
    for name, record in snapshot["files"].items():
        if not isinstance(record, dict):
            raise EnvironmentError("candidate-rejection file record is malformed")
        if record.get("status") == "READABLE":
            manifest_record = manifest_outputs.get(name)
            if manifest_record != {"sha256": record.get("sha256"), "bytes": record.get("bytes")}:
                raise EnvironmentError("candidate-rejection snapshot is not bound by the runner artifact manifest")
        elif record.get("status") == "UNSAFE_OR_UNREADABLE":
            if name in manifest_outputs:
                raise EnvironmentError("runner manifest claims unreadable candidate output bytes")
        elif record.get("status") != "UNEXPECTED_NAME":
            raise EnvironmentError("candidate-rejection file snapshot has an unknown status")
    inventory_defect = (set(snapshot["names"]) != FINAL_FILES
                        or any(record.get("status") != "READABLE" for record in snapshot["files"].values())
                        or set(manifest_outputs) != FINAL_FILES)
    if receipt["reason_code"] == "ARTIFACT_INVENTORY_REJECTED" and not inventory_defect:
        raise EnvironmentError("inventory rejection has no measured candidate inventory defect")
    try:
        actual = {entry.name for entry in output_dir.iterdir()}
    except OSError as exc:
        raise EnvironmentError("candidate output directory is unavailable") from exc
    if actual != set(snapshot["names"]):
        raise CandidateError("candidate output inventory differs from host-sealed rejection snapshot")
    for name, record in snapshot["files"].items():
        path = output_dir / name
        if record.get("status") == "READABLE":
            try:
                st = path.lstat()
                raw = path.read_bytes()
            except OSError as exc:
                raise CandidateError(f"candidate artifact changed after host rejection: {name}") from exc
            if (not stat.S_ISREG(st.st_mode) or path.is_symlink() or st.st_nlink != 1
                    or len(raw) != record.get("bytes") or _sha(raw) != record.get("sha256")):
                raise CandidateError(f"candidate artifact changed after host rejection: {name}")
    return {"status": "FAIL", "reward": 0.0,
            "reason_code": receipt["reason_code"], "finding": "candidate_rejected"}


def _context_output_records_for_rejection(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    collected = context.get("artifact_manifest", {}).get("collected")
    if not isinstance(collected, list):
        raise EnvironmentError("runner context has no collected file inventory")
    result: dict[str, dict[str, Any]] = {}
    for entry in collected:
        if not isinstance(entry, dict) or not isinstance(entry.get("files"), list):
            raise EnvironmentError("runner artifact manifest is malformed")
        for item in entry["files"]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise EnvironmentError("runner artifact manifest file record is malformed")
            path = Path(item["path"])
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise EnvironmentError("runner artifact manifest path is unsafe")
            if path.parts[0] == "outputs":
                if len(path.parts) != 2 or path.parts[1] in result:
                    raise EnvironmentError("runner artifact manifest repeats an output path")
                result[path.parts[1]] = {"sha256": item.get("sha256"), "bytes": item.get("bytes")}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", nargs="?", default=".")
    parser.add_argument("--phase", choices=sorted(PHASE_FILES), default="final")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--reference-file", type=Path, default=Path(__file__).with_name("refs.json"))
    args = parser.parse_args()
    output_dir = Path(args.output_dir).absolute()
    try:
        refs = load_reference_policy(args.reference_file)
        if args.preflight_only:
            result = validate_public_outputs(output_dir / "outputs", args.phase, refs)
            print(json.dumps(result, sort_keys=True))
            return EXIT_PASS
        context, context_raw = _load_runner_context()
        # The CLI is the reward-bearing path; it accepts only the runner's
        # dedicated readonly private bind. Local helper calls are test-only.
        private_root = _private_root(require_root_seal=True)
        _verify_pinned_private_sources(private_root)
        output_path = output_dir / "outputs"
        result = verify_candidate_rejection(output_path, context, _sha(context_raw), private_root)
        if result is None:
            result = verify_trusted_attempt(output_path, context, private_root=private_root,
                                            reference_policy=refs)
        print(json.dumps(result, sort_keys=True))
        return EXIT_FAIL if result.get("status") == "FAIL" else EXIT_PASS
    except CandidateError as exc:
        print(f"CANDIDATE_FAIL: {exc}", file=sys.stderr)
        return EXIT_FAIL
    except (EnvironmentError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ENV_ERROR: {exc}", file=sys.stderr)
        return EXIT_ENV


if __name__ == "__main__":
    raise SystemExit(main())
