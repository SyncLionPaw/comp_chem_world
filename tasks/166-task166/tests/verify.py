#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Multistate CASSCF properties at two ethylene geometries.
"""Case-05 layered verifier: SA(3)-CASSCF(2,2) reproduction cross-check.

Exit codes: 0 PASS, 1 candidate FAIL, 2 evaluator ENV_ERROR.
Hidden reference: tests/refs.json (values from XAlkeneDB, same method).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import math
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path


class CandidateFail(Exception):
    pass


class ScientificCheckUnavailable(Exception):
    pass


TRUSTED_RUNNER_CONTEXT_PATH = Path("/trusted/runner-context.json")
TRUSTED_OPENMOLCAS_ROOT = Path("/trusted/case05-openmolcas")
RUNNER_CONTEXT_HASH_ENV = "CCB_CASE05_RUN_CONTEXT_SHA256"
TRUSTED_PYSCF_ROOT = Path("/trusted/case05-pyscf")
PYSCF_RUNNER_CONTEXT_HASH_ENV = "CCB_CASE05_PYSCF_RUN_CONTEXT_SHA256"
TRUSTED_PYSCF_FAILURE_ROOT = Path("/trusted/case05-pyscf-failure")
PYSCF_FAILURE_PROOF_HASH_ENV = "CCB_CASE05_PYSCF_FAILURE_PROOF_SHA256"
TRUSTED_PYSCF_REJECTION_ROOT = Path("/trusted/case05-pyscf-rejection")
PYSCF_REJECTION_PROOF_HASH_ENV = "CCB_CASE05_PYSCF_REJECTION_PROOF_SHA256"
# This gate applies only to the archived author-Gold replay route. Current
# protected local/scheduler receipt routes are validated by their live schemas.
CASE05_OPENMOLCAS_RUNNER_INTEGRATION = False
CASE05_TASK_CONFIG_SHA256 = "39d964735bcc99ea0742ebc83ad4975f36c7c6d5784c6586b4a17177c22890ec"
CASE05_INSTRUCTION_SHA256 = "8bc8107bb7890793cb39bf2b8deff41d11fc64ec56a47a51e807b626a6c6ff99"
CASE05_IMAGE_ID = "sha256:112509d5f553824edc7b83fa11d0fc32ead2be995ad1d4aa8f239f7fa115d8c3"
CASE05_AUTHOR_GOLD_ORIGIN_IMAGE_ID = "sha256:23ed5bc8eb5294792de4954453a734ccab6f81c829020b69dd3db234a2ef5b0c"
CASE05_NATIVE_PARSER_SHA256 = "19eaad48fd6a57b4238915ce8c74bc14f876bd840cdc2ac7a238cf6987d9d207"
CASE05_MOLDEN_AUDIT_SCRIPT_SHA256_LEGACY = "a70cad9e9b1ee4d2db87d8c57f9ff9944c6f0c940a9784facdc444f750b44cb6"
CASE05_A_SUBMISSION_MANIFEST_SHA256 = "PENDING_REAL_A_SUBMISSION"
CASE05_AUTHOR_GOLD_MANIFEST_SHA256 = "PENDING_REAL_A_B_QUALIFICATION"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_current_molden_audit_source(audit: dict) -> None:
    """Bind a Molden audit to this merged verifier's executed source bytes."""
    current_source = sha256(Path(__file__).resolve())
    if audit.get("audit_script_sha256") != current_source:
        raise CandidateFail("Molden audit was not produced by this merged verifier source")


def require_raw_output_declarations(summary: dict, required: set[str], program: str) -> None:
    declared = set(summary.get("raw_outputs", []))
    missing = sorted(required - declared)
    if missing:
        raise CandidateFail(f"summary.raw_outputs is missing {program} candidate files: {missing}")


def canonical_sha(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def verify_candidate_rejection_proof() -> dict | None:
    """Validate host-sealed rejection proof, returning it only when fully bound."""
    expected_file_hash = os.environ.get(PYSCF_REJECTION_PROOF_HASH_ENV)
    if not expected_file_hash:
        if TRUSTED_PYSCF_REJECTION_ROOT.exists() or TRUSTED_PYSCF_REJECTION_ROOT.is_symlink():
            raise ScientificCheckUnavailable("protected candidate rejection proof mount lacks its runner digest")
        return None
    root = TRUSTED_PYSCF_REJECTION_ROOT
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_file_hash)
            or root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077
            or root.stat().st_mode & 0o222):
        raise ScientificCheckUnavailable("protected candidate rejection proof mount is unavailable or mutable")
    entries = list(root.iterdir())
    if {p.name for p in entries} != {"proof.json", "binding.json"} or any(p.is_symlink() for p in entries):
        raise ScientificCheckUnavailable("candidate rejection proof mount has an unexpected inventory")
    proof_path, binding_path = root / "proof.json", root / "binding.json"
    for path in (proof_path, binding_path):
        if path.stat().st_mode & 0o222 or not path.is_file():
            raise ScientificCheckUnavailable("candidate rejection proof contains a mutable or missing file")
    raw_proof = proof_path.read_bytes()
    if hashlib.sha256(raw_proof).hexdigest() != expected_file_hash:
        raise ScientificCheckUnavailable("candidate rejection proof does not match runner-injected digest")
    try:
        proof = json.loads(raw_proof)
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        context_raw = TRUSTED_RUNNER_CONTEXT_PATH.read_bytes()
        context = json.loads(context_raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScientificCheckUnavailable(f"candidate rejection proof/context is unreadable: {exc}") from exc
    if not all(isinstance(x, dict) for x in (proof, binding, context)):
        raise ScientificCheckUnavailable("candidate rejection proof/context must contain JSON objects")
    proof_sha = proof.pop("proof_sha256", None)
    binding_sha = binding.pop("binding_sha256", None)
    context_sha = hashlib.sha256(context_raw).hexdigest()
    artifact_manifest = context.get("artifact_manifest")
    if not isinstance(artifact_manifest, dict):
        raise ScientificCheckUnavailable("runner context does not contain a valid artifact manifest")
    manifest_sha = canonical_sha(artifact_manifest)
    reason_types = {
        "request_absent": "CandidateRequestAbsent",
        "invalid_request": "CandidateRequestError",
        "candidate_incomplete": "CandidateRequestError",
        "request_too_late": "CandidateDeadlineExceeded",
    }
    reason = proof.get("reason")
    predispatch_local = (proof.get("worker_terminated") is False
                         and proof.get("confirmed_dispatch") is False
                         and proof.get("dispatch_attempted") is False
                         and proof.get("candidate_stage") == "PREDISPATCH")
    terminal_local = (proof.get("worker_terminated") is True
                      and proof.get("confirmed_dispatch") is True
                      and proof.get("dispatch_attempted") is True
                      and proof.get("candidate_stage") == "TERMINAL_UNCOLLECTED"
                      and reason == "candidate_incomplete")
    local_broker_rejection = (proof.get("profile_id") == "case05-local-pyscf"
                              and proof.get("host_health") == "validated_local_broker"
                              and (predispatch_local or terminal_local))
    closure_sha = context.get("runtime_closure_sha256")
    standard_runtime_identity = (
        context.get("image_identity_kind") == "runtime-closure-sha256"
        and isinstance(closure_sha, str) and re.fullmatch(r"[0-9a-f]{64}", closure_sha) is not None
        and context.get("image_id") == "runtime-closure-sha256:" + closure_sha)
    historical_oci_identity = (isinstance(context.get("image_id"), str)
                               and re.fullmatch(r"sha256:[0-9a-f]{64}", context["image_id"]) is not None)
    if (proof_sha != canonical_sha(proof) or binding_sha != canonical_sha(binding)
            or proof.get("schema") != "case05/pyscf-candidate-rejection/v1"
            or proof.get("case_id") != "case-05" or reason not in reason_types
            or proof.get("host_error_type") != reason_types[reason]
            or (not local_broker_rejection and proof.get("host_health") != "validated_profile_and_terminal_worker")
            or (not local_broker_rejection and proof.get("worker_terminated") is not True)
            or (not local_broker_rejection and proof.get("confirmed_dispatch") is not False)
            or (not local_broker_rejection and proof.get("dispatch_attempted") is not False)
            or proof.get("unknown_submission") is not False
            or (proof.get("profile_id") != "case05-openmolcas" and not local_broker_rejection)
            or context.get("schema") not in {"compchembench.runner-context/v1", "compchembench.runner-context/v2"}
            or context.get("task_id") != "case-05"
            or context.get("task_config_sha256") != CASE05_TASK_CONFIG_SHA256
            or context.get("instruction_sha256") != CASE05_INSTRUCTION_SHA256
            or not (standard_runtime_identity or historical_oci_identity)
            or (standard_runtime_identity and (proof.get("image_identity_kind") != context.get("image_identity_kind")
                                               or proof.get("runtime_closure_sha256") != closure_sha))
            or context.get("artifact_manifest_sha256") != manifest_sha
            or proof.get("task_config_sha256") != context.get("task_config_sha256")
            or proof.get("instruction_sha256") != context.get("instruction_sha256")
            or proof.get("image_id") != context.get("image_id")
            or proof.get("run_id") != context.get("run_id")
            or proof.get("attempt_id") != context.get("attempt_id")
            or proof.get("runner_context_sha256") != context_sha
            or proof.get("runner_artifact_manifest_sha256") != manifest_sha
            or not isinstance(proof.get("nonce"), str) or len(proof["nonce"]) != 64
            or binding.get("schema") != "case05/pyscf-candidate-rejection-binding/v1"
            or binding.get("run_id") != proof.get("run_id")
            or binding.get("attempt_id") != proof.get("attempt_id")
            or binding.get("nonce") != proof.get("nonce")
            or binding.get("runner_context_sha256") != context_sha
            or binding.get("runner_artifact_manifest_sha256") != manifest_sha
            or binding.get("proof_file_sha256") != expected_file_hash):
        raise ScientificCheckUnavailable("candidate rejection proof is not bound to this trusted attempt/context")
    proof["proof_sha256"] = proof_sha
    return proof


def verify_execution_failure_proof() -> dict | None:
    """Validate root-sealed, same-attempt local execution failure evidence."""
    expected_hash = os.environ.get(PYSCF_FAILURE_PROOF_HASH_ENV)
    root = TRUSTED_PYSCF_FAILURE_ROOT
    if not expected_hash:
        if root.exists() or root.is_symlink():
            raise ScientificCheckUnavailable("trusted local execution failure proof lacks its runner digest")
        return None
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
            or root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077
            or root.stat().st_mode & 0o222 or root.stat().st_uid != 0
            or TRUSTED_PYSCF_REJECTION_ROOT.exists() or TRUSTED_PYSCF_REJECTION_ROOT.is_symlink()):
        raise ScientificCheckUnavailable("trusted local execution failure proof is unavailable or mutable")
    if {p.name for p in root.iterdir()} != {"proof.json", "binding.json"}:
        raise ScientificCheckUnavailable("trusted local execution failure proof has an unexpected inventory")
    proof_path, binding_path = root / "proof.json", root / "binding.json"
    for path in (proof_path, binding_path):
        info = path.lstat()
        if (path.is_symlink() or not path.is_file() or info.st_uid != 0 or info.st_nlink != 1
                or info.st_mode & 0o222 or info.st_size <= 0 or info.st_size > 32768):
            raise ScientificCheckUnavailable("trusted local execution failure proof contains an unsafe file")
    proof_raw = proof_path.read_bytes()
    if hashlib.sha256(proof_raw).hexdigest() != expected_hash:
        raise ScientificCheckUnavailable("trusted local execution failure proof digest mismatch")
    try:
        proof = json.loads(proof_raw.decode("utf-8"))
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        context_raw = TRUSTED_RUNNER_CONTEXT_PATH.read_bytes()
        context = json.loads(context_raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScientificCheckUnavailable(f"trusted local execution failure context is unreadable: {type(exc).__name__}") from exc
    if not all(isinstance(item, dict) for item in (proof, binding, context)):
        raise ScientificCheckUnavailable("trusted local execution failure records must be JSON objects")
    proof_sha = proof.pop("proof_sha256", None)
    binding_sha = binding.pop("binding_sha256", None)
    context_sha = hashlib.sha256(context_raw).hexdigest()
    manifest = context.get("artifact_manifest")
    if not isinstance(manifest, dict):
        raise ScientificCheckUnavailable("runner context lacks an artifact manifest for local failure")
    manifest_sha = canonical_sha(manifest)
    failure = proof.get("failure")
    failure_fields = {"schema", "attempt_id", "execution_id", "point", "stage", "error", "exit_code",
        "started_at_epoch", "finished_at_epoch", "runtime_identity", "resource_request", "driver_sha256",
        "geometry_sha256", "stdout_sha256", "stdout_bytes", "stderr_sha256", "stderr_bytes", "stderr_tail"}
    closure_sha = context.get("runtime_closure_sha256")
    if (proof_sha != canonical_sha(proof)
            or set(proof) != {"schema", "case_id", "failure", "host_health", "task_config_sha256",
                "instruction_sha256", "image_id", "image_identity_kind", "runtime_closure_sha256",
                "run_id", "attempt_id", "nonce", "runner_context_sha256", "runner_artifact_manifest_sha256"}
            or proof.get("schema") != "case05/pyscf-execution-failure-proof/v1"
            or proof.get("case_id") != "case-05" or proof.get("host_health") != "validated_local_broker"
            or context.get("schema") not in {"compchembench.runner-context/v1", "compchembench.runner-context/v2"}
            or context.get("task_id") != "case-05"
            or context.get("task_config_sha256") != CASE05_TASK_CONFIG_SHA256
            or context.get("instruction_sha256") != CASE05_INSTRUCTION_SHA256
            or context.get("image_identity_kind") != "runtime-closure-sha256"
            or not isinstance(closure_sha, str) or re.fullmatch(r"[0-9a-f]{64}", closure_sha) is None
            or context.get("image_id") != "runtime-closure-sha256:" + closure_sha
            or proof.get("task_config_sha256") != context.get("task_config_sha256")
            or proof.get("instruction_sha256") != context.get("instruction_sha256")
            or proof.get("image_id") != context.get("image_id")
            or proof.get("image_identity_kind") != context.get("image_identity_kind")
            or proof.get("runtime_closure_sha256") != closure_sha
            or proof.get("run_id") != context.get("run_id")
            or proof.get("attempt_id") != context.get("attempt_id")
            or not isinstance(proof.get("nonce"), str) or len(proof["nonce"]) != 64
            or proof.get("nonce") != context.get("nonce")
            or proof.get("runner_context_sha256") != context_sha
            or proof.get("runner_artifact_manifest_sha256") != manifest_sha
            or context.get("artifact_manifest_sha256") != manifest_sha
            or not isinstance(failure, dict) or set(failure) != failure_fields
            or failure.get("schema") != "case05/pyscf-execution-failure/v1"
            or failure.get("attempt_id") != proof.get("attempt_id")
            or failure.get("execution_id") != context.get("execution_id")
            or failure.get("point") not in {"A", "B"}
            or failure.get("stage") not in {"native_execution", "root_preparation"}
            or not isinstance(failure.get("error"), str) or len(failure["error"]) > 1024
            or (failure.get("exit_code") is not None and type(failure["exit_code"]) is not int)
            or failure.get("driver_sha256") != _legacy_pyscf_PINNED_RUN_POINT_SHA256
            or not isinstance(failure.get("runtime_identity"), dict)
            or not isinstance(failure.get("resource_request"), dict)
            or set(failure["resource_request"]) != {"cpus", "memory_gb", "wall_seconds", "accelerator", "gpu_count"}
            or any(type(failure["resource_request"].get(key)) is not int
                   for key in ("cpus", "memory_gb", "wall_seconds", "gpu_count"))
            or failure["resource_request"]["cpus"] < 1 or failure["resource_request"]["memory_gb"] < 1
            or not 1 <= failure["resource_request"]["wall_seconds"] <= 1200
            or failure["resource_request"]["accelerator"] != "cpu" or failure["resource_request"]["gpu_count"] != 0
            or (failure.get("started_at_epoch") is not None and
                (isinstance(failure["started_at_epoch"], bool) or not isinstance(failure["started_at_epoch"], (int, float))
                 or not math.isfinite(failure["started_at_epoch"])))
            or (failure.get("finished_at_epoch") is not None and
                (isinstance(failure["finished_at_epoch"], bool) or not isinstance(failure["finished_at_epoch"], (int, float))
                 or not math.isfinite(failure["finished_at_epoch"])))
            or type(failure.get("stdout_bytes")) is not int or failure["stdout_bytes"] < 0
            or type(failure.get("stderr_bytes")) is not int or failure["stderr_bytes"] < 0
            or not isinstance(failure.get("stderr_tail"), str) or len(failure["stderr_tail"]) > 2048
            or binding_sha != canonical_sha(binding)
            or binding != {"schema": "case05/pyscf-execution-failure-binding/v1", "run_id": proof.get("run_id"),
                "attempt_id": proof.get("attempt_id"), "nonce": proof.get("nonce"),
                "runner_context_sha256": context_sha, "runner_artifact_manifest_sha256": manifest_sha,
                "proof_file_sha256": expected_hash}):
        raise ScientificCheckUnavailable("trusted local execution failure proof is not bound to this attempt")
    for stream in ("stdout", "stderr"):
        digest = failure.get(stream + "_sha256")
        size = failure.get(stream + "_bytes")
        if ((digest is None and size != 0) or (digest is not None
                and (not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None))):
            raise ScientificCheckUnavailable("trusted local execution failure log digest is invalid")
    proof["proof_sha256"] = proof_sha
    return proof


def load_native_results(out: Path, reference_dir: Path | None) -> dict:
    """Parse native output without mixing PySCF and OpenMolcas provenance."""
    summary_path = out / "summary.json"
    if summary_path.is_file():
        try:
            summary_probe = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CandidateFail(f"summary.json is unreadable: {exc}") from exc
        program = str(summary_probe.get("program", ""))
        if program.lower().startswith("openmolcas"):
            raise ScientificCheckUnavailable("OpenMolcas evidence must use the dedicated A/B native path")
    NativeOutputError = _legacy_pyscf_NativeOutputError
    PINNED_RUN_POINT_SHA256 = _legacy_pyscf_PINNED_RUN_POINT_SHA256
    PINNED_SEEDED_RUN_POINT_SHA256 = _legacy_pyscf_PINNED_SEEDED_RUN_POINT_SHA256
    parse_native_log = _legacy_pyscf_parse_native_log
    parsed = {}
    for point in ("A", "B"):
        raw = out / "raw" / point
        needed = ("program.log", "result.json", "run_point.py", "geometry.xyz",
                  "input-hashes.txt", "output-hashes.txt", "exit-code.txt")
        missing = [name for name in needed if not (raw / name).is_file()]
        if missing:
            raise CandidateFail(f"{point}: missing native PySCF candidate files {missing}")
        if (raw / "exit-code.txt").read_text().strip() != "0":
            raise CandidateFail(f"{point}: native program exit code is nonzero")
        if reference_dir is None:
            raise ScientificCheckUnavailable("public geometry root not provided via --reference-dir")
        geometry_root = reference_dir.resolve()
        expected_geom = geometry_root / f"ethene_grid_{point}.xyz"
        if not expected_geom.is_file():
            expected_geom = geometry_root / "geometries" / f"ethene_grid_{point}.xyz"
        if not expected_geom.is_file():
            raise ScientificCheckUnavailable(f"public geometry unavailable under {geometry_root}")
        geom_hash = sha256(expected_geom)
        if sha256(raw / "geometry.xyz") != geom_hash:
            raise CandidateFail(f"{point}: native run geometry differs from public input")
        executed_script_hash = sha256(raw / "run_point.py")
        seed_path = raw / "initial_orbitals.npy"
        seeded = executed_script_hash == PINNED_SEEDED_RUN_POINT_SHA256
        if executed_script_hash != PINNED_RUN_POINT_SHA256 and not (point == "A" and seeded):
            raise CandidateFail(f"{point}: executed script differs from pinned case source")
        if seeded != seed_path.is_file():
            raise CandidateFail(f"{point}: seeded script and retained orbital seed do not agree")
        input_hashes = {}
        for line in (raw / "input-hashes.txt").read_text().splitlines():
            fields = line.split(maxsplit=1)
            if len(fields) == 2:
                input_hashes[Path(fields[1]).name] = fields[0]
        if input_hashes.get("run_point.py") != executed_script_hash or input_hashes.get(expected_geom.name) != geom_hash:
            raise CandidateFail(f"{point}: recorded input hashes do not match collected files")
        if seeded and input_hashes.get("initial_orbitals.npy") != sha256(seed_path):
            raise CandidateFail(f"{point}: recorded orbital-seed hash does not match collected input")
        if not seeded and "initial_orbitals.npy" in input_hashes:
            raise CandidateFail(f"{point}: unseeded run records an unexpected orbital seed")
        output_hashes = {}
        for line in (raw / "output-hashes.txt").read_text().splitlines():
            fields = line.split(maxsplit=1)
            if len(fields) == 2:
                output_hashes[Path(fields[1]).name] = fields[0]
        for name in ("program.log", "result.json"):
            if output_hashes.get(name) != sha256(raw / name):
                raise CandidateFail(f"{point}: recorded {name} hash does not match collected output")
        log = (raw / "program.log").read_text(encoding="utf-8", errors="replace")
        extract_pyscf_native_version(log)
        try:
            native = parse_native_log(raw / "program.log", point, expected_geom,
                                      raw / "run_point.py", seed_path if seeded else None)
        except NativeOutputError as exc:
            raise CandidateFail(f"{point}: native PySCF output validation failed: {exc}") from exc
        try:
            claimed = json.loads((raw / "result.json").read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CandidateFail(f"{point}: result.json is malformed: {exc}") from exc
        if claimed.get("point") != point or claimed.get("geometry_sha256") != geom_hash:
            raise CandidateFail(f"{point}: result.json identifies the wrong geometry")
        if claimed.get("initial_orbital_seed_sha256") != native["initial_orbital_seed_sha256"]:
            raise CandidateFail(f"{point}: result.json orbital seed differs from native execution")
        def agrees(actual, expected):
            if isinstance(expected, list):
                return (isinstance(actual, list) and len(actual) == len(expected)
                        and all(agrees(a, b) for a, b in zip(actual, expected)))
            try:
                value = float(actual)
            except (TypeError, ValueError):
                return False
            return math.isfinite(value) and abs(value - float(expected)) <= 5e-8
        for key, expected in (("energy_hartree", native["energy_hartree"]),
                              ("gradients_hartree_per_bohr", native["gradients_hartree_per_bohr"]),
                              ("force_norms_hartree_per_bohr", native["force_norms_hartree_per_bohr"]),
                              ("nac01_per_bohr", native["nac01_per_bohr"]),
                              ("nac01_norm_per_bohr", native["nac01_norm_per_bohr"])):
            if key not in claimed or not agrees(claimed[key], expected):
                raise CandidateFail(f"{point}: result.json {key} disagrees with native program output")
        parsed[point] = native

    actual_programs = {row.get("program") for row in parsed.values()}
    if len(actual_programs) != 1:
        raise CandidateFail("A/B native PySCF version banners do not match")
    require_declared_program_matches_native(summary_probe.get("program"), next(iter(actual_programs)))
    return parsed


def verify_pyscf_scheduler_evidence(receipt_root: Path, scheduler: dict, job_id: str,
                                   elapsed_seconds: int, partition: str,
                                   resources: dict[str, int]) -> dict[str, str]:
    """Parse host-captured Slurm submission, spool, and accounting evidence."""
    expected = {"submission.txt", "accounting.txt", "spooled-script.slurm"}
    evidence_dir = receipt_root / "evidence"
    observed = {p.name for p in evidence_dir.iterdir()}
    if observed != expected:
        raise ScientificCheckUnavailable("PySCF receipt lacks the exact scheduler evidence file set")
    evidence = {name: evidence_dir / name for name in expected}
    for path in evidence.values():
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o222:
            raise ScientificCheckUnavailable("PySCF scheduler evidence is missing, mutable, or redirected")
    hashes = {f"evidence/{name}": sha256(path) for name, path in evidence.items()}
    if scheduler.get("files") != hashes:
        raise ScientificCheckUnavailable("PySCF scheduler evidence hashes differ from the protected receipt")

    submit_text = evidence["submission.txt"].read_text(encoding="utf-8", errors="replace").strip()
    submit_match = re.fullmatch(r"Submitted batch job ([0-9]+)", submit_text)
    if not submit_match or submit_match.group(1) != job_id:
        raise ScientificCheckUnavailable("captured sbatch response does not identify the receipt job ID")

    spool = evidence["spooled-script.slurm"].read_text(encoding="utf-8", errors="replace")
    directives = {}
    for line in spool.splitlines():
        match = re.match(r"^\s*#SBATCH\s+--([A-Za-z0-9-]+)(?:[=\s]+)([^\s#]+)", line)
        if match:
            directives[match.group(1)] = match.group(2)
    if directives.get("cpus-per-task") != str(resources["cpus"]):
        raise ScientificCheckUnavailable("spooled Slurm script CPU count differs from the trusted request")
    spool_memory = re.fullmatch(r"([0-9]+)([kmgt])", directives.get("mem", "").lower())
    if spool_memory is None or int(spool_memory.group(1)) * {"k": 1024, "m": 1024**2,
            "g": 1024**3, "t": 1024**4}[spool_memory.group(2)] != resources["memory_gb"] * 1024**3:
        raise ScientificCheckUnavailable("spooled Slurm script memory differs from the trusted request")
    gres = directives.get("gres", "")
    gpu_match = re.fullmatch(r"(?:--)?(?:gres/)?gpu(?::[A-Za-z0-9_-]+)?(?::([0-9]+))?", gres)
    spool_gpu_count = int(gpu_match.group(1) or "1") if gpu_match else 0
    if spool_gpu_count != resources["gpu_count"]:
        raise ScientificCheckUnavailable("spooled Slurm script accelerator differs from the trusted request")
    time_limit = directives.get("time", "")
    time_parts = time_limit.split(":")
    try:
        if len(time_parts) == 3:
            limit_seconds = int(time_parts[0]) * 3600 + int(time_parts[1]) * 60 + int(time_parts[2])
        elif len(time_parts) == 2:
            limit_seconds = int(time_parts[0]) * 60 + int(time_parts[1])
        else:
            raise ValueError
    except ValueError as exc:
        raise ScientificCheckUnavailable("spooled Slurm script has an unreadable time limit") from exc
    if not 0 < limit_seconds <= 1200 or limit_seconds != resources["wall_seconds"] or elapsed_seconds > limit_seconds:
        raise ScientificCheckUnavailable("Slurm time limit differs from the fixed A/B science budget/request")

    accounting_text = evidence["accounting.txt"].read_text(encoding="utf-8", errors="replace")
    rows = list(csv.DictReader(accounting_text.splitlines(), delimiter="|"))
    matching_rows = [entry for entry in rows
                     if isinstance(entry.get("JobID"), str) and entry["JobID"].strip() == job_id]
    if len(matching_rows) != 1:
        raise ScientificCheckUnavailable("captured sacct record must contain exactly one row for the submitted job ID")
    row = matching_rows[0]
    if any(not isinstance(row.get(key), str) or not row[key].strip()
           for key in ("State", "ExitCode", "Elapsed", "Partition", "AllocCPUS", "ReqMem", "AllocTRES")):
        raise ScientificCheckUnavailable("captured sacct record has a missing or malformed required field")
    if (row["State"].strip() != "COMPLETED"
            or row.get("ExitCode", "").strip() != "0:0"
            or row.get("Elapsed", "").strip() == ""
            or row.get("AllocCPUS", "").strip() != str(resources["cpus"])
            or row.get("Partition", "").strip() != partition):
        raise ScientificCheckUnavailable("captured sacct record does not attest the completed requested allocation")
    accounting_elapsed = row["Elapsed"].strip().split("-")
    try:
        clock = accounting_elapsed[-1].split(":")
        if len(clock) != 3:
            raise ValueError
        measured_elapsed = int(clock[0]) * 3600 + int(clock[1]) * 60 + int(clock[2])
        if len(accounting_elapsed) == 2:
            measured_elapsed += int(accounting_elapsed[0]) * 86400
    except ValueError as exc:
        raise ScientificCheckUnavailable("captured sacct elapsed time is malformed") from exc
    if measured_elapsed != elapsed_seconds:
        raise ScientificCheckUnavailable("sacct elapsed time differs from the trusted receipt")
    requested_memory = row.get("ReqMem", "").strip().lower()
    memory_match = re.fullmatch(r"([0-9]+)([kmgt])(?:[cn])?", requested_memory)
    if memory_match is None:
        raise ScientificCheckUnavailable("captured sacct record has an unsupported ReqMem format")
    memory_bytes = int(memory_match.group(1)) * {"k": 1024, "m": 1024**2,
                                                 "g": 1024**3, "t": 1024**4}[memory_match.group(2)]
    if memory_bytes != resources["memory_gb"] * 1024**3:
        raise ScientificCheckUnavailable("captured sacct ReqMem differs from the trusted requested memory")
    alloc_tres = row.get("AllocTRES", "")
    tres_memory = re.search(r"(?:^|,)mem=([0-9]+)([KMGT])(?:,|$)", alloc_tres, re.IGNORECASE)
    tres_gpu = re.search(r"(?:^|,)(?:gres/)?gpu(?:/[^=,]+)?=([0-9]+)(?:,|$)", alloc_tres, re.IGNORECASE)
    if tres_memory is None or (tres_gpu is None and resources["gpu_count"] != 0):
        raise ScientificCheckUnavailable("captured sacct TRES omits requested memory or accelerator allocation")
    allocated_bytes = int(tres_memory.group(1)) * {"K": 1024, "M": 1024**2,
                                                   "G": 1024**3, "T": 1024**4}[tres_memory.group(2).upper()]
    captured_gpu_count = int(tres_gpu.group(1)) if tres_gpu else 0
    if allocated_bytes != resources["memory_gb"] * 1024**3 or captured_gpu_count != resources["gpu_count"]:
        raise ScientificCheckUnavailable("captured sacct TRES differs from trusted requested resources")
    return hashes


def verify_pyscf_local_execution(value: object) -> dict:
    """Validate a host-sealed local execution identity and its A/B budget."""
    keys = {"schema", "execution_id", "program_id", "version", "method_id",
            "runtime_identity", "runtime_identity_sha256", "resource_request",
            "started_at_epoch", "finished_at_epoch", "exit_code"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ScientificCheckUnavailable("trusted local execution identity has unknown or missing fields")
    runtime = value["runtime_identity"]
    runtime_keys = {"program_id", "version", "executable_sha256", "environment_sha256",
                    "source_sha256", "machine_id_sha256"}
    request = value["resource_request"]
    if (value["schema"] != "case05/local-execution/v1"
            or not isinstance(value["execution_id"], str)
            or re.fullmatch(r"[0-9a-f]{32}", value["execution_id"]) is None
            or not isinstance(value["program_id"], str)
            or re.fullmatch(r"pyscf-[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?", value["program_id"]) is None
            or value["program_id"] != f"pyscf-{value['version']}"
            or value["method_id"] != "SA3CAS22ccpVDZ"
            or value["exit_code"] != 0 or type(value["exit_code"]) is not int
            or not isinstance(runtime, dict) or set(runtime) != runtime_keys
            or runtime.get("program_id") != value["program_id"]
            or runtime.get("version") != value["version"]
            or value["runtime_identity_sha256"] != canonical_sha(runtime)
            or not isinstance(request, dict)
            or set(request) != {"cpus", "memory_gb", "wall_seconds", "accelerator", "gpu_count"}
            or any(type(request.get(k)) is not int for k in ("cpus", "memory_gb", "wall_seconds", "gpu_count"))
            or request["cpus"] < 1 or request["memory_gb"] < 1 or request["gpu_count"] < 0
            or not 1 <= request["wall_seconds"] <= 1200
            or not isinstance(request["accelerator"], str) or not request["accelerator"]
            or (request["accelerator"] == "cpu" and request["gpu_count"] != 0)
            or (request["accelerator"] != "cpu" and request["gpu_count"] < 1)):
        raise ScientificCheckUnavailable("trusted local program/method/resource identity is invalid")
    for name in ("executable_sha256", "environment_sha256", "source_sha256", "machine_id_sha256"):
        if not isinstance(runtime.get(name), str) or re.fullmatch(r"[0-9a-f]{64}", runtime[name]) is None:
            raise ScientificCheckUnavailable(f"trusted local runtime identity has invalid {name}")
    start, finish = value["started_at_epoch"], value["finished_at_epoch"]
    if (type(start) not in (int, float) or type(finish) not in (int, float)
            or not math.isfinite(float(start)) or not math.isfinite(float(finish))
            or finish < start or finish - start > request["wall_seconds"]
            or finish - start > 1200):
        raise ScientificCheckUnavailable("trusted local execution timestamps exceed the A/B wall budget")
    return value


def verify_pyscf_runtime_snapshot(runtime_snapshot: object, local_execution: dict,
                                  context: dict) -> None:
    """Validate the root-sealed runtime metadata bound to a local PySCF execution."""
    expected_runtime_keys = {"schema", "attempt_id", "execution_id", "requested_python", "executed_python",
                             "snapshot_closure_sha256", "snapshot_entries", "source_closure_sha256", "observed_python",
                             "observed_distributions", "executable_sha256", "environment_sha256", "manifest_sha256"}
    runtime_identity = local_execution["runtime_identity"]
    if (not isinstance(runtime_snapshot, dict) or set(runtime_snapshot) != expected_runtime_keys
            or runtime_snapshot.get("schema") != "case05/python-runtime-snapshot/v1"
            or runtime_snapshot.get("attempt_id") != context["attempt_id"]
            or runtime_snapshot.get("execution_id") != local_execution["execution_id"]
            or runtime_snapshot.get("executable_sha256") != runtime_identity["executable_sha256"]
            or runtime_snapshot.get("environment_sha256") != runtime_identity["environment_sha256"]
            or not isinstance(runtime_snapshot.get("snapshot_entries"), list)):
        raise ScientificCheckUnavailable("trusted runtime snapshot manifest does not bind this local execution")
    snapshot_sha = runtime_snapshot.get("snapshot_closure_sha256")
    entries = runtime_snapshot["snapshot_entries"]
    if ((snapshot_sha is None and entries)
            or (snapshot_sha is not None and (not isinstance(snapshot_sha, str)
                or re.fullmatch(r"[0-9a-f]{64}", snapshot_sha) is None
                or canonical_sha(entries) != snapshot_sha
                or not isinstance(runtime_snapshot.get("source_closure_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", runtime_snapshot["source_closure_sha256"]) is None))
            or (snapshot_sha is None and runtime_snapshot.get("source_closure_sha256") is not None)):
        raise ScientificCheckUnavailable("trusted runtime snapshot closure is malformed")
    if (not isinstance(runtime_snapshot.get("requested_python"), str)
            or not isinstance(runtime_snapshot.get("executed_python"), str)
            or (runtime_snapshot["requested_python"].startswith("/app/workspace/") and snapshot_sha is None)):
        raise ScientificCheckUnavailable("selected workspace runtime was not frozen before execution")
    packages = {"python": runtime_snapshot["observed_python"],
                "distributions": runtime_snapshot["observed_distributions"]}
    expected_environment = canonical_sha({"packages": packages, "snapshot_sha256": snapshot_sha})
    if expected_environment != runtime_identity["environment_sha256"]:
        raise ScientificCheckUnavailable("trusted runtime snapshot does not reproduce the captured environment digest")


def verify_pyscf_trusted_receipt(
    out: Path,
    *,
    context_path: Path = TRUSTED_RUNNER_CONTEXT_PATH,
    receipt_root: Path = TRUSTED_PYSCF_ROOT,
    context_digest: str | None = None,
) -> dict:
    """Verify a protected, same-attempt host receipt for PySCF A/B outputs.

    The runner context binds the submitted artifact set; the separate private
    receipt binds those exact files to the host-observed Slurm job. Candidate
    files and the legacy CASE05_TRUSTED_EXECUTION_RECEIPT variable are never
    trusted as execution provenance.
    """
    context_digest = context_digest or os.environ.get(PYSCF_RUNNER_CONTEXT_HASH_ENV, "")
    if not context_digest:
        raise ScientificCheckUnavailable(
            f"runner-owned PySCF context hash unavailable ({PYSCF_RUNNER_CONTEXT_HASH_ENV} is not set)")
    if (context_path.is_symlink() or not context_path.is_file() or context_path.stat().st_mode & 0o222
            or receipt_root.is_symlink() or not receipt_root.is_dir() or receipt_root.stat().st_mode & 0o077):
        raise ScientificCheckUnavailable("protected runner context or PySCF receipt mount is unavailable/mutable")
    if sha256(context_path) != context_digest:
        raise ScientificCheckUnavailable("reserved runner context hash differs from host-provided PySCF context hash")

    runtime_snapshot_path = Path("/trusted/case05-runtime-snapshot.json")
    runtime_snapshot = None
    if runtime_snapshot_path.exists() or runtime_snapshot_path.is_symlink():
        if (runtime_snapshot_path.is_symlink() or not runtime_snapshot_path.is_file()
                or runtime_snapshot_path.stat().st_mode & 0o222):
            raise ScientificCheckUnavailable("trusted Python runtime snapshot manifest is unavailable or mutable")
        try:
            runtime_snapshot = json.loads(runtime_snapshot_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ScientificCheckUnavailable(f"trusted Python runtime snapshot manifest is malformed: {exc}") from exc
        snapshot_digest = runtime_snapshot.pop("manifest_sha256", None)
        if snapshot_digest != canonical_sha(runtime_snapshot):
            raise ScientificCheckUnavailable("trusted Python runtime snapshot manifest digest is invalid")
        runtime_snapshot["manifest_sha256"] = snapshot_digest

    expected_names = {"receipt.json", "artifact-manifest.json", "binding.json", "evidence"}
    entries = list(receipt_root.iterdir())
    if ({p.name for p in entries} != expected_names
            or any(p.is_symlink() or (not p.is_dir() if p.name == "evidence" else not p.is_file()) for p in entries)):
        raise ScientificCheckUnavailable("protected PySCF receipt transport has an unexpected file inventory")
    evidence_dir = receipt_root / "evidence"
    if (evidence_dir.stat().st_mode & 0o077
            or any(p.is_symlink() or not p.is_file() for p in evidence_dir.iterdir())):
        raise ScientificCheckUnavailable("protected PySCF scheduler evidence directory is mutable or malformed")
    if (any(p.stat().st_mode & 0o222 for p in entries if p.is_file())
            or any(p.stat().st_mode & 0o222 for p in evidence_dir.iterdir())):
        raise ScientificCheckUnavailable("protected PySCF receipt transport contains a mutable file")
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
        receipt_path = receipt_root / "receipt.json"
        manifest_path = receipt_root / "artifact-manifest.json"
        binding_path = receipt_root / "binding.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScientificCheckUnavailable(f"trusted PySCF context/receipt transport is malformed: {exc}") from exc
    if not all(isinstance(value, dict) for value in (context, receipt, manifest, binding)):
        raise ScientificCheckUnavailable("trusted PySCF context/receipt transport must contain JSON objects")

    receipt_file_hash = sha256(receipt_path)
    receipt_hash = receipt.pop("receipt_sha256", None)
    manifest_hash = manifest.pop("manifest_sha256", None)
    binding_hash = binding.pop("binding_sha256", None)
    if (receipt_hash != canonical_sha(receipt) or manifest_hash != canonical_sha(manifest)
            or binding_hash != canonical_sha(binding)):
        raise ScientificCheckUnavailable("PySCF receipt, artifact manifest, or binding digest is invalid")

    runner_manifest = context.get("artifact_manifest")
    if (context.get("schema") not in {"compchembench.runner-context/v1", "compchembench.runner-context/v2"}
            or context.get("task_id") != "case-05"
            or context.get("task_config_sha256") != CASE05_TASK_CONFIG_SHA256
            or context.get("instruction_sha256") != CASE05_INSTRUCTION_SHA256
            or not isinstance(context.get("image_id"), str)
            or not ((context.get("image_identity_kind") == "runtime-closure-sha256"
                     and isinstance(context.get("runtime_closure_sha256"), str)
                     and re.fullmatch(r"[0-9a-f]{64}", context["runtime_closure_sha256"]) is not None
                     and context["image_id"] == "runtime-closure-sha256:" + context["runtime_closure_sha256"])
                    or (context["image_id"].startswith("sha256:") and len(context["image_id"]) == 71
                        and all(c in "0123456789abcdef" for c in context["image_id"][7:])))
            or not isinstance(context.get("run_id"), str) or not context["run_id"]
            or not isinstance(context.get("attempt_id"), str) or len(context["attempt_id"]) != 32
            or any(c not in "0123456789abcdef" for c in context["attempt_id"])
            or not isinstance(runner_manifest, dict)
            or context.get("artifact_manifest_sha256") != canonical_sha(runner_manifest)):
        raise ScientificCheckUnavailable("reserved CompChemBench context does not bind this PySCF case/attempt")
    if (not isinstance(runner_manifest.get("collected"), list)
            or not isinstance(runner_manifest.get("declared"), list)
            or not isinstance(runner_manifest.get("missing"), list)
            or runner_manifest["missing"]):
        raise ScientificCheckUnavailable("runner artifact manifest is incomplete or unsupported")

    context_files: dict[str, str] = {}
    for group in runner_manifest["collected"]:
        if not isinstance(group, dict) or not isinstance(group.get("files"), list):
            raise ScientificCheckUnavailable("runner artifact manifest contains a malformed collection")
        for item in group["files"]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ScientificCheckUnavailable("runner artifact manifest contains a malformed file entry")
            rel = Path(item["path"])
            if rel.is_absolute() or ".." in rel.parts or not isinstance(item.get("sha256"), str):
                raise ScientificCheckUnavailable("runner artifact manifest contains an unsafe or unhashed file")
            if item["path"].startswith("outputs/raw/"):
                raw_rel = item["path"][len("outputs/"):]
                raw_parts = Path(raw_rel).parts
                if (len(raw_parts) < 3 or raw_parts[0] != "raw" or raw_parts[1] not in {"A", "B"}
                        or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
                    raise ScientificCheckUnavailable(
                        "runner artifact manifest has an invalid protected raw A/B file record")
                if raw_rel in context_files:
                    raise ScientificCheckUnavailable(f"runner artifact manifest duplicates {item['path']}")
                context_files[raw_rel] = item["sha256"]

    actual_files: dict[str, str] = {}
    candidate_raw_fault = None
    raw_root = out / "raw"
    if raw_root.is_symlink() or not raw_root.is_dir():
        candidate_raw_fault = "candidate raw output tree is missing or redirected"
    else:
        for current, directories, files in os.walk(raw_root, followlinks=False):
            current_path = Path(current)
            if any((current_path / name).is_symlink() for name in directories):
                candidate_raw_fault = "candidate raw output tree contains a symlink directory"
            for name in files:
                path = current_path / name
                if path.is_symlink() or not path.is_file():
                    candidate_raw_fault = "candidate raw output tree contains a symlink or non-regular file"
                    continue
                actual_files[path.relative_to(out).as_posix()] = sha256(path)

    # First establish agreement among independently protected host records.
    # A mismatch in the mounted candidate copy is a candidate artifact fault,
    # while disagreement among the protected records is an evaluator error.
    if receipt.get("files") != context_files:
        raise ScientificCheckUnavailable("host receipt does not match the exact collected A/B hashes")
    backend = receipt.get("backend", "scheduler")
    slurm = receipt.get("slurm")
    if (receipt.get("schema") != "case05/pyscf-runner-receipt/v1"
            or receipt.get("case_id") != "case-05"
            or receipt.get("task_config_sha256") != context["task_config_sha256"]
            or receipt.get("instruction_sha256") != context["instruction_sha256"]
            or receipt.get("image_id") != context["image_id"]
            or receipt.get("run_id") != context["run_id"]
            or receipt.get("attempt_id") != context["attempt_id"]
            or receipt.get("runner_context_sha256") != context_digest
            or receipt.get("runner_artifact_manifest_sha256") != context["artifact_manifest_sha256"]
            or receipt.get("private_output_manifest_sha256") != manifest_hash):
        raise ScientificCheckUnavailable("trusted PySCF receipt is not bound to this attempt/context")
    scheduler_hashes: dict[str, str] = {}
    if backend == "scheduler":
        slurm_exit_ok = ((type(slurm.get("exit_code")) is int and slurm["exit_code"] == 0)
                         or slurm.get("exit_code") == "0:0") if isinstance(slurm, dict) else False
        if (not isinstance(slurm, dict) or not str(slurm.get("job_id", "")).isdigit()
                or slurm.get("state") != "COMPLETED" or not slurm_exit_ok
                or any(type(slurm.get(key)) is not int for key in ("cpus", "memory_gb", "gpu_count", "wall_seconds"))
                or slurm["cpus"] < 1 or slurm["memory_gb"] < 1
                or slurm["gpu_count"] < 0 or not 1 <= slurm["wall_seconds"] <= 1200
                or not isinstance(slurm.get("partition"), str) or not slurm["partition"]
                or type(slurm.get("elapsed_seconds")) is not int
                or not 0 <= slurm["elapsed_seconds"] <= min(1200, slurm["wall_seconds"])):
            raise ScientificCheckUnavailable("trusted PySCF receipt lacks a completed, budgeted scheduler allocation")
        scheduler_evidence = receipt.get("scheduler_evidence")
        if not isinstance(scheduler_evidence, dict) or scheduler_evidence.get("schema") != "case05/pyscf-slurm-evidence/v1":
            raise ScientificCheckUnavailable("trusted PySCF receipt lacks raw same-attempt Slurm evidence")
        scheduler_hashes = verify_pyscf_scheduler_evidence(
            receipt_root, scheduler_evidence, slurm["job_id"], slurm["elapsed_seconds"],
            slurm["partition"], slurm)
        local_execution = None
    elif backend == "local":
        local_execution = receipt.get("local_execution")
        if slurm is not None or receipt.get("scheduler_evidence") is not None:
            raise ScientificCheckUnavailable("local execution receipt must not claim scheduler evidence")
        local_execution = verify_pyscf_local_execution(local_execution)
        if context.get("image_identity_kind") == "runtime-closure-sha256":
            verify_pyscf_runtime_snapshot(runtime_snapshot, local_execution, context)
    else:
        raise ScientificCheckUnavailable("trusted PySCF receipt backend is unsupported")
    host_files = manifest.get("files")
    if not isinstance(host_files, dict) or host_files != {**context_files, **scheduler_hashes}:
        raise ScientificCheckUnavailable("protected manifest does not bind candidate A/B and raw Slurm evidence")
    points = receipt.get("points")
    if not isinstance(points, dict) or set(points) != {"A", "B"}:
        raise ScientificCheckUnavailable("trusted PySCF receipt does not attest both A/B points")
    if backend == "scheduler":
        if any(not isinstance(points[p], dict) or points[p].get("job_id") != slurm["job_id"]
               or points[p].get("state") != "COMPLETED"
               or not ((type(points[p].get("exit_code")) is int and points[p]["exit_code"] == 0)
                       or points[p].get("exit_code") == "0:0") for p in ("A", "B")):
            raise ScientificCheckUnavailable("trusted PySCF receipt does not bind both A/B points to its scheduler job")
    elif any(not isinstance(points[p], dict) or points[p].get("execution_id") != local_execution["execution_id"]
             or points[p].get("state") != "COMPLETED" or points[p].get("exit_code") != 0
             for p in ("A", "B")):
        raise ScientificCheckUnavailable("trusted PySCF receipt does not bind both A/B points to its local execution")
    if (receipt.get("host_context_sha256") != context_digest
            or binding.get("schema") != "case05/pyscf-runner-binding/v1"
            or binding.get("task_id") != "case-05"
            or binding.get("task_config_sha256") != context["task_config_sha256"]
            or binding.get("instruction_sha256") != context["instruction_sha256"]
            or binding.get("image_id") != context["image_id"]
            or binding.get("run_id") != context["run_id"]
            or binding.get("attempt_id") != context["attempt_id"]
            or binding.get("runner_context_sha256") != context_digest
            or binding.get("runner_artifact_manifest_sha256") != context["artifact_manifest_sha256"]
            or binding.get("private_output_manifest_sha256") != manifest_hash
            or binding.get("host_receipt_sha256") != receipt_file_hash):
        raise ScientificCheckUnavailable("PySCF host receipt is not bound to the reserved same-attempt context")
    if candidate_raw_fault:
        raise CandidateFail(candidate_raw_fault)
    if not actual_files or any(not rel.startswith(("raw/A/", "raw/B/")) for rel in actual_files):
        raise CandidateFail("candidate raw output must contain files only for points A and B")
    if context_files != actual_files:
        raise CandidateFail("candidate raw outputs differ from the host-collected artifact snapshot")
    return {"attempt_id": context["attempt_id"], "receipt_sha256": receipt_file_hash,
            "backend": backend, "job_id": slurm["job_id"] if backend == "scheduler" else None,
            "local_execution": local_execution}


def parse_openmolcas_points(out: Path, reference_dir: Path | None, summary: dict,
                           receipt_info: dict | None = None) -> dict:
    """Re-parse candidate A/B native files; audit JSON is never an authority."""
    if reference_dir is None:
        raise ScientificCheckUnavailable("public geometry root not provided via --reference-dir")
    om = _LEGACY_OPENMOLCAS_MODULE
    require_program_matches_execution(summary.get("program"), openmolcas=True)
    local_execution = receipt_info.get("local_execution") if isinstance(receipt_info, dict) else None
    local_backend = local_execution is not None
    if local_backend and summary.get("program") != f"OpenMolcas {local_execution['version']}":
        raise ScientificCheckUnavailable("summary OpenMolcas version differs from the trusted local runtime identity")
    expected_runtime_version = (local_execution["version"] if local_backend else
                                receipt_info.get("program_version") if isinstance(receipt_info, dict) else None)
    if not isinstance(expected_runtime_version, str):
        raise ScientificCheckUnavailable("trusted OpenMolcas capture omits the actual runtime version")
    if summary.get("program") != f"OpenMolcas {expected_runtime_version}":
        raise CandidateFail("summary OpenMolcas version differs from the trusted native execution")
    required_names = (("input.inp", "program.log", "program.err", "output-hashes.txt", "exit-code.txt")
                      if local_backend else
                      ("input.inp", "program.log", "program.err", "phase-marks.txt",
                       "output-hashes.txt", "exit-code.txt", "job-id.txt",
                       "spooled-script.slurm", "accounting.txt"))
    parsed = {}
    for point in ("A", "B"):
        raw = out / "raw" / point
        geom_name = f"ethene_grid_{point}.xyz"
        missing = [name for name in (*required_names, geom_name) if not (raw / name).is_file()]
        if missing:
            raise CandidateFail(f"{point}: missing per-point OpenMolcas evidence files {missing}")
        geom_root = reference_dir.resolve()
        expected_geom = geom_root / f"ethene_grid_{point}.xyz"
        if not expected_geom.is_file():
            expected_geom = geom_root / "geometries" / f"ethene_grid_{point}.xyz"
        if not expected_geom.is_file():
            raise ScientificCheckUnavailable(f"public geometry unavailable under {geom_root}")
        if sha256(raw / geom_name) != sha256(expected_geom):
            raise CandidateFail(f"{point}: native run geometry differs from the frozen public geometry")
        native_version = extract_openmolcas_native_version(
            (raw / "program.log").read_text(encoding="utf-8", errors="replace"))
        if native_version != expected_runtime_version:
            raise ScientificCheckUnavailable(f"{point}: OpenMolcas native version differs from trusted runtime")
        manifest = om.sha_manifest(raw / "output-hashes.txt")
        for name in ("input.inp", geom_name, "program.log", "program.err"):
            if manifest.get(name) != sha256(raw / name):
                raise CandidateFail(f"{point}: output hash manifest does not bind {name}")
        if (raw / "exit-code.txt").read_text().strip() != "0":
            raise CandidateFail(f"{point}: native OpenMolcas exit code is nonzero")
        if local_backend:
            job_id = None
            acct = None
            point_spool_limit = None
        else:
            job_id = (raw / "job-id.txt").read_text().strip()
            if not job_id.isdigit():
                raise CandidateFail(f"{point}: job-id.txt is invalid")
            try:
                acct = om.parse_accounting(raw / "accounting.txt", job_id)
                point_spool_limit = om.slurm_script_time_limit(raw / "spooled-script.slurm")
                if (not 1 <= point_spool_limit <= 1200
                        or acct["time_limit_seconds"] != point_spool_limit):
                    raise om.Unsupported("per-point Slurm wall request must be within the 1200-second science budget")
            except om.Unsupported as exc:
                raise CandidateFail(f"{point}: Slurm accounting is not a successful attempt: {exc}") from exc
        try:
            om.verify_input(raw / "input.inp", raw / geom_name)
        except om.Unsupported as exc:
            raise CandidateFail(f"{point}: OpenMolcas input differs from the frozen method: {exc}") from exc
        native = parse_openmolcas_native(
            om, raw / "input.inp", raw / geom_name, raw / "program.log",
            raw / "program.err", raw / "exit-code.txt", point)
        native["job_id"] = job_id
        native["accounting"] = acct
        native["spooled_script_sha256"] = (sha256(raw / "spooled-script.slurm") if not local_backend else None)
        parsed[point] = native
    return parsed


def parse_openmolcas_native(om, input_path: Path, geometry_path: Path, log_path: Path,
                            error_path: Path, exit_path: Path, point: str) -> dict:
    """Keep known failed calculations in candidate-failure, unknown formats in ENV."""
    try:
        return om.parse_point_native(input_path, geometry_path, log_path, error_path, exit_path, point)
    except om.ScientificFailure as exc:
        raise CandidateFail(f"{point}: native OpenMolcas calculation did not converge: {exc}") from exc
    except om.Unsupported as exc:
        raise ScientificCheckUnavailable(
            f"{point}: pinned OpenMolcas output format/response is unsupported: {exc}") from exc


def openmolcas_science_phase(path: Path, point: str) -> int:
    marks = {}
    for line in path.read_text().splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) != 2:
            raise CandidateFail(f"invalid {point} phase-mark line {line!r}")
        try:
            stamp = datetime.strptime(fields[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except ValueError as exc:
            raise CandidateFail(f"invalid {point} phase timestamp {line!r}") from exc
        if fields[1] in (f"{point}_science_start", f"{point}_science_end"):
            if fields[1] in marks:
                raise CandidateFail(f"duplicate {point} science phase marker {fields[1]}")
            marks[fields[1]] = stamp
    start, end = f"{point}_science_start", f"{point}_science_end"
    if set(marks) != {start, end} or marks[end] < marks[start]:
        raise CandidateFail(f"{point} science phase start/end markers are missing or invalid")
    return int(marks[end] - marks[start])


def validate_openmolcas_science_budget(prior_seconds: int, point_seconds: dict[str, int]) -> int:
    if (not isinstance(prior_seconds, int) or prior_seconds < 80
            or set(point_seconds) != {"A", "B"}
            or any(not isinstance(value, int) or value < 0 for value in point_seconds.values())):
        raise ScientificCheckUnavailable("trusted OpenMolcas receipt omits or invalidates the cumulative science clock")
    total = prior_seconds + point_seconds["A"] + point_seconds["B"]
    if total > 3600:
        raise CandidateFail("trusted OpenMolcas A/B science elapsed time exceeds the one-hour cumulative science budget")
    return total


def verify_openmolcas_local_receipt(out: Path, receipt: dict, context: dict,
                                    context_digest: str, captured_files: dict) -> dict:
    """Validate a protected local OpenMolcas execution without scheduler claims."""
    local = receipt.get("local_execution")
    local_keys = {"schema", "execution_id", "program_id", "version", "method_id",
                  "runtime_identity", "runtime_identity_sha256", "resource_request",
                  "started_at_epoch", "finished_at_epoch", "exit_code"}
    runtime = local.get("runtime_identity") if isinstance(local, dict) else None
    runtime_keys = {"program_id", "version", "executable_sha256", "environment_sha256",
                    "source_sha256", "machine_id_sha256", "native_parser_sha256"}
    request = local.get("resource_request") if isinstance(local, dict) else None
    if (receipt.get("schema") != "case05/openmolcas-runner-receipt/v1"
            or receipt.get("case_id") != "case-05"
            or receipt.get("attempt_id") != context.get("attempt_id")
            or receipt.get("runner_context_sha256") != context_digest
            or receipt.get("execution_mode") != "local"
            or any(key in receipt for key in ("partition", "node", "build", "scheduler_evidence"))
            or not isinstance(local, dict) or set(local) != local_keys
            or local.get("schema") != "case05/local-execution/v1"
            or not isinstance(local.get("execution_id"), str)
            or re.fullmatch(r"[0-9a-f]{32}", local["execution_id"]) is None
            or not isinstance(local.get("program_id"), str)
            or re.fullmatch(r"openmolcas-v?[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?", local["program_id"]) is None
            or local.get("program_id") != f"openmolcas-{local.get('version')}"
            or local.get("method_id") != "SA3CAS22ccpVDZ"
            or type(local.get("exit_code")) is not int or local["exit_code"] != 0
            or not isinstance(runtime, dict) or set(runtime) != runtime_keys
            or runtime.get("program_id") != local["program_id"]
            or runtime.get("version") != local["version"]
            or local.get("runtime_identity_sha256") != canonical_sha(runtime)
            or runtime.get("native_parser_sha256") != sha256(Path(_LEGACY_OPENMOLCAS_MODULE.__file__).resolve())
            or not isinstance(request, dict)
            or set(request) != {"cpus", "memory_gb", "wall_seconds", "accelerator", "gpu_count"}
            or any(type(request.get(key)) is not int for key in ("cpus", "memory_gb", "wall_seconds", "gpu_count"))
            or request["cpus"] < 1 or request["memory_gb"] < 1 or request["gpu_count"] < 0
            or not 1 <= request["wall_seconds"] <= 1200
            or not isinstance(request["accelerator"], str) or not request["accelerator"]
            or (request["accelerator"] == "cpu" and request["gpu_count"] != 0)
            or (request["accelerator"] != "cpu" and request["gpu_count"] < 1)):
        raise ScientificCheckUnavailable("trusted local OpenMolcas identity/method/resource record is invalid")
    for name in ("executable_sha256", "environment_sha256", "source_sha256", "machine_id_sha256"):
        if not isinstance(runtime.get(name), str) or re.fullmatch(r"[0-9a-f]{64}", runtime[name]) is None:
            raise ScientificCheckUnavailable(f"trusted local OpenMolcas runtime identity has invalid {name}")
    start, finish = local.get("started_at_epoch"), local.get("finished_at_epoch")
    if (type(start) not in (int, float) or type(finish) not in (int, float)
            or not math.isfinite(float(start)) or not math.isfinite(float(finish))
            or finish < start or finish - start > request["wall_seconds"] or finish - start > 1200):
        raise ScientificCheckUnavailable("trusted local OpenMolcas execution exceeds the A/B wall budget")
    required = {f"raw/{point}/{name}" for point in ("A", "B")
                for name in ("input.inp", "program.log", "program.err", "exit-code.txt",
                             "output-hashes.txt", f"ethene_grid_{point}.xyz")}
    if not isinstance(captured_files, dict) or not required <= set(captured_files):
        raise ScientificCheckUnavailable("trusted local OpenMolcas capture omits A/B native files")
    for rel, expected in captured_files.items():
        if not rel.startswith(("raw/A/", "raw/B/")):
            raise ScientificCheckUnavailable("local OpenMolcas capture includes non-science or scheduler files")
        target = out / rel
        if target.is_symlink() or not target.is_file() or sha256(target) != expected:
            raise ScientificCheckUnavailable(f"trusted local OpenMolcas capture hash differs for {rel}")
    for point in ("A", "B"):
        actual_version = extract_openmolcas_native_version(
            (out / f"raw/{point}/program.log").read_text(encoding="utf-8", errors="replace"))
        if actual_version != local["version"]:
            raise ScientificCheckUnavailable(f"local OpenMolcas {point} native version differs from trusted runtime identity")
        if (out / f"raw/{point}/exit-code.txt").read_text().strip() != "0":
            raise ScientificCheckUnavailable(f"local OpenMolcas {point} native exit code is not successful")
    points = receipt.get("points")
    if (not isinstance(points, dict) or set(points) != {"A", "B"}
            or any(not isinstance(points[p], dict)
                   or points[p].get("execution_id") != local["execution_id"]
                   or points[p].get("state") != "COMPLETED"
                   or points[p].get("exit_code") != 0 for p in ("A", "B"))):
        raise ScientificCheckUnavailable("local OpenMolcas A/B points do not bind the trusted execution ID")
    return {"attempt_id": context["attempt_id"], "receipt_sha256": sha256(TRUSTED_OPENMOLCAS_ROOT / "receipt.json"),
            "backend": "local", "local_execution": local}


def extract_openmolcas_native_version(log: str) -> str:
    """Read a version from the native executable path/version banner."""
    patterns = (
        r"(?im)^\s*MOLCAS_SOURCE\s*=\s*.*?OpenMolcas-(v?[0-9]+(?:\.[0-9]+){1,3})(?:[-/\s]|$)",
        r"(?im)^\s*OpenMolcas(?:\s+version)?\s*[:=]?\s*(v?[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?)\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, log)
        if match:
            version = match.group(1)
            return version if version.startswith("v") else f"v{version}"
    raise ScientificCheckUnavailable("native OpenMolcas version banner/path is missing or unsupported")


def validate_openmolcas_current_attempt_budget(point_seconds: dict[str, int]) -> int:
    if (set(point_seconds) != {"A", "B"}
            or any(type(value) is not int or value < 0 for value in point_seconds.values())):
        raise ScientificCheckUnavailable("trusted OpenMolcas capture lacks A/B science time")
    total = point_seconds["A"] + point_seconds["B"]
    if total > 1200:
        raise CandidateFail("OpenMolcas A/B science elapsed time exceeds the fixed 1200-second task budget")
    return total


def slurm_script_resources(path: Path) -> dict[str, object]:
    directives = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^\s*#SBATCH\s+--([A-Za-z0-9-]+)(?:[=\s]+)([^\s#]+)", line)
        if match:
            directives[match.group(1)] = match.group(2)
    cpus = directives.get("cpus-per-task")
    memory = directives.get("mem")
    gres = directives.get("gres", "")
    if not cpus or not cpus.isdigit() or not memory:
        raise ScientificCheckUnavailable("captured Slurm resource request is malformed")
    mem_match = re.fullmatch(r"([0-9]+)([KMGTP])(?:[cn])?", memory, re.I)
    if mem_match is None:
        raise ScientificCheckUnavailable("captured Slurm memory format is unsupported")
    memory_bytes = int(mem_match.group(1)) * {"k":1024,"m":1024**2,"g":1024**3,
                                               "t":1024**4,"p":1024**5}[mem_match.group(2).lower()]
    gpu_match = re.fullmatch(r"(?:--)?(?:gres/)?gpu(?::[A-Za-z0-9_-]+)?(?::([0-9]+))?", gres)
    gpu_count = int(gpu_match.group(1) or "1") if gpu_match else 0
    wall_seconds = _legacy_openmolcas_slurm_script_time_limit(path)
    return {"cpus": int(cpus), "memory_bytes": memory_bytes, "gpu_count": gpu_count,
            "wall_seconds": wall_seconds, "partition": directives.get("partition")}


def crosscheck_openmolcas_csv(native_results: dict, cells: dict, nac_map: dict) -> None:
    for point in ("A", "B"):
        native = native_results[point]
        energies = native["energies_hartree"]
        forces = native["gradient_frobenius_norms_hartree_per_bohr"]
        gap_evs = [0.0] + [(energies[i] - energies[i - 1]) * 27.211386245988 for i in (1, 2)]
        for idx, state in enumerate(("S0", "S1", "S2")):
            row = cells[(point, state)]
            values = (("energy_hartree", energies[idx]),
                      ("force_frobenius_norm_hartree_per_bohr", forces[idx]),
                      ("gap_to_lower_state_eV", gap_evs[idx]))
            for key, expected in values:
                actual = finite_float(row[key], f"{point}/{state} {key}")
                if abs(actual - expected) > 5e-8:
                    raise CandidateFail(f"{point}/{state}: CSV {key} disagrees with native OpenMolcas output")
        nac_value = finite_float(nac_map[point]["nac01_frobenius_norm"], f"{point} NAC norm")
        if abs(nac_value - native["nac01_frobenius_norm_per_bohr"]) > 5e-8:
            raise CandidateFail(f"{point}: CSV C01 norm disagrees with native OpenMolcas output")


def crosscheck_pyscf_csv(native_results: dict, cells: dict, nac_map: dict) -> None:
    """Require all published PySCF CSV quantities to match native parsed logs."""
    states = ("S0", "S1", "S2")
    for point in ("A", "B"):
        native = native_results[point]
        for idx, state in enumerate(states):
            row = cells[(point, state)]
            for key, expected in (
                ("energy_hartree", native["energy_hartree"][idx]),
                ("force_frobenius_norm_hartree_per_bohr", native["force_norms_hartree_per_bohr"][idx]),
            ):
                actual = finite_float(row[key], f"{point}/{state} {key}")
                if abs(actual - expected) > 5e-8:
                    raise CandidateFail(f"{point}/{state}: CSV {key} disagrees with native PySCF output")
        actual_nac = finite_float(nac_map[point]["nac01_frobenius_norm"], f"{point} NAC norm")
        if abs(actual_nac - native["nac01_norm_per_bohr"]) > 5e-8:
            raise CandidateFail(f"{point}: CSV C01 norm disagrees with native PySCF output")


def validate_nac_csv_contract(rows: list[dict]) -> dict[str, dict]:
    """Validate the public C01 table identity and unit before numeric scoring."""
    if len(rows) != 2:
        raise CandidateFail(f"nacs.csv must contain exactly two rows, got {len(rows)}")
    nac_map = {row["point_id"]: row for row in rows}
    if set(nac_map) != {"A", "B"}:
        raise CandidateFail("nacs.csv must cover points A and B exactly once")
    for point in ("A", "B"):
        row = nac_map[point]
        if row["coupling"] != "S1/S0" or row["unit"] != "1/Bohr":
            raise CandidateFail(f"{point}: nacs.csv coupling/unit must be S1/S0, 1/Bohr")
        if finite_float(row["nac01_frobenius_norm"], f"{point} NAC norm") < 0:
            raise CandidateFail(f"{point}: NAC norm must be nonnegative")
    return nac_map


def verify_openmolcas_trusted_receipt(out: Path, parsed: dict | None = None) -> dict:
    """Validate a protected same-attempt runner context and collected artifacts."""
    context_path = TRUSTED_RUNNER_CONTEXT_PATH
    receipt_root = TRUSTED_OPENMOLCAS_ROOT
    context_digest = os.environ.get(RUNNER_CONTEXT_HASH_ENV, "")
    if not context_digest:
        raise ScientificCheckUnavailable(f"runner-owned context hash unavailable ({RUNNER_CONTEXT_HASH_ENV} is not set)")
    if (context_path.is_symlink() or not context_path.is_file() or context_path.stat().st_mode & 0o222
            or receipt_root.is_symlink() or not receipt_root.is_dir() or receipt_root.stat().st_mode & 0o077):
        raise ScientificCheckUnavailable("protected runner context or OpenMolcas receipt mount is unavailable/mutable")
    if sha256(context_path) != context_digest:
        raise ScientificCheckUnavailable("reserved runner context hash differs from host-provided context hash")
    expected_root_files = {"receipt.json", "artifact-manifest.json", "binding.json"}
    observed_root_files = {p.name for p in receipt_root.iterdir() if p.is_file() or p.is_symlink()}
    if observed_root_files != expected_root_files or any(p.is_symlink() for p in receipt_root.iterdir()):
        raise ScientificCheckUnavailable("protected OpenMolcas receipt transport has an unexpected file inventory")
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
        receipt = json.loads((receipt_root / "receipt.json").read_text(encoding="utf-8"))
        manifest = json.loads((receipt_root / "artifact-manifest.json").read_text(encoding="utf-8"))
        binding = json.loads((receipt_root / "binding.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScientificCheckUnavailable(f"trusted OpenMolcas context/receipt transport is malformed: {exc}") from exc
    if not all(isinstance(value, dict) for value in (context, receipt, manifest, binding)):
        raise ScientificCheckUnavailable("trusted OpenMolcas context/receipt transport must contain JSON objects")
    for name in expected_root_files:
        if (receipt_root / name).stat().st_mode & 0o222:
            raise ScientificCheckUnavailable(f"protected OpenMolcas transport file is mutable: {name}")
    receipt_hash = receipt.pop("receipt_sha256", None)
    manifest_hash = manifest.pop("manifest_sha256", None)
    binding_hash = binding.pop("binding_sha256", None)
    if (receipt_hash != canonical_sha(receipt) or manifest_hash != canonical_sha(manifest)
            or binding_hash != canonical_sha(binding)):
        raise ScientificCheckUnavailable("runner receipt, artifact manifest, or same-attempt binding hash is invalid")
    # This is the host runner's standard context, not a case-specific schema.
    # Its artifact manifest authenticates the evaluator's collected submission
    # files; the protected OpenMolcas collector manifest below authenticates
    # remote A/B/build evidence and therefore has a distinct digest.
    runner_manifest = context.get("artifact_manifest")
    if (context.get("schema") not in {"compchembench.runner-context/v1",
                                      "compchembench.runner-context/v2"}
            or context.get("task_id") != "case-05"
            or context.get("task_config_sha256") != CASE05_TASK_CONFIG_SHA256
            or context.get("instruction_sha256") != CASE05_INSTRUCTION_SHA256
            or not isinstance(context.get("image_id"), str)
            or not context["image_id"].startswith("sha256:")
            or len(context["image_id"]) != 71
            or any(c not in "0123456789abcdef" for c in context["image_id"][7:])
            or not isinstance(context.get("run_id"), str) or not context["run_id"]
            or not isinstance(context.get("attempt_id"), str)
            or len(context["attempt_id"]) != 32
            or any(c not in "0123456789abcdef" for c in context["attempt_id"])
            or not isinstance(runner_manifest, dict)
            or context.get("artifact_manifest_sha256") != canonical_sha(runner_manifest)):
        raise ScientificCheckUnavailable("reserved CompChemBench runner context does not bind this canonical case/attempt")
    if (not isinstance(runner_manifest.get("declared"), list)
            or not isinstance(runner_manifest.get("collected"), list)
            or not isinstance(runner_manifest.get("missing"), list)):
        raise ScientificCheckUnavailable("standard runner artifact manifest has an unsupported structure")
    if (receipt.get("runner_context_sha256") != context_digest
            or receipt.get("runner_artifact_manifest_sha256") != context.get("artifact_manifest_sha256")
            or receipt.get("private_output_manifest_sha256") != manifest_hash
            or binding.get("schema") != "case05/openmolcas-runner-binding/v1"
            or binding.get("attempt_id") != context.get("attempt_id")
            or binding.get("runner_context_sha256") != context_digest
            or binding.get("runner_artifact_manifest_sha256") != context.get("artifact_manifest_sha256")
            or binding.get("private_output_manifest_sha256") != manifest_hash
            or binding.get("task_id") != context.get("task_id")
            or binding.get("task_config_sha256") != context.get("task_config_sha256")
            or binding.get("instruction_sha256") != context.get("instruction_sha256")
            or binding.get("image_id") != context.get("image_id")
            or binding.get("run_id") != context.get("run_id")
            or binding.get("host_receipt_sha256") != sha256(receipt_root / "receipt.json")):
        raise ScientificCheckUnavailable("OpenMolcas receipt is not bound to the reserved same-attempt runner context")
    manifest_files = manifest.get("files")
    captured_files = receipt.get("host_capture_file_hashes")
    if (not isinstance(manifest_files, dict) or not isinstance(captured_files, dict)
            or manifest_files != captured_files):
        raise ScientificCheckUnavailable("host artifact manifest differs from the captured attempt file inventory")
    if receipt.get("execution_mode") == "local":
        return verify_openmolcas_local_receipt(out, receipt, context, context_digest, captured_files)
    if receipt.get("execution_mode") == "author_gold_replay":
        source = receipt.get("source_attestation")
        qualification = receipt.get("qualification")
        jobs = source.get("jobs", {}) if isinstance(source, dict) else {}
        build = jobs.get("build", {}) if isinstance(jobs, dict) else {}
        job_a = jobs.get("A", {}) if isinstance(jobs, dict) else {}
        job_b = jobs.get("B", {}) if isinstance(jobs, dict) else {}
        evidence_sha256 = source.get("evidence_sha256", {}) if isinstance(source, dict) else {}
        source_a_job_id = source.get("a_submission_manifest_job_id") if isinstance(source, dict) else None
        expected_evidence_keys = (
            "build_spooled_script", "build_accounting", "build_remote_manifest", "build_local_manifest",
            "A_submission_manifest", "A_final_receipt", "A_remote_manifest", "A_local_manifest", "A_accounting",
            "A_spooled_script", "A_phase_marks", "A_output_manifest", "A_official_000_log",
            "A_molden", "A_orbital_review", "B_final_receipt", "B_remote_manifest",
            "B_local_manifest", "B_accounting", "B_spooled_script", "B_phase_marks",
            "B_output_manifest", "B_molden", "B_orbital_review", "native_parser", "molden_parser",
        )
        budget = qualification.get("science_budget", {}) if isinstance(qualification, dict) else {}
        installed = qualification.get("installed_identity", {}) if isinstance(qualification, dict) else {}
        if (receipt.get("host_dispatch") is not False
                or not isinstance(source, dict)
                or source.get("schema") != "case05/openmolcas-author-gold-source/v1"
                or source.get("image_id") != CASE05_AUTHOR_GOLD_ORIGIN_IMAGE_ID
                or source.get("source_attempt_id") != receipt.get("source_attempt_id")
                or source.get("source_attempt_id") == context.get("attempt_id")
                or receipt.get("source_attestation_sha256") != canonical_sha(source)
                or not isinstance(evidence_sha256, dict)
                or any(not isinstance(evidence_sha256.get(key), str)
                       or len(evidence_sha256[key]) != 64
                       or any(char not in "0123456789abcdef" for char in evidence_sha256[key])
                       for key in expected_evidence_keys)
                or receipt.get("author_gold_manifest_sha256") != CASE05_AUTHOR_GOLD_MANIFEST_SHA256
                or not isinstance(qualification, dict)
                or qualification.get("schema") != "case05/openmolcas-final-qualification/v1"
                or qualification.get("status") != "CASE05_QUALIFIED"
                or qualification.get("verified") is not True
                or qualification.get("reward_verification") is not False
                or qualification.get("provenance_sha256", {}).get("native_parser") != CASE05_NATIVE_PARSER_SHA256
                or qualification.get("official_000_assessment", {}).get("official_harness_check_status") != "PASS"
                or source.get("a_submission_manifest_sha256") != CASE05_A_SUBMISSION_MANIFEST_SHA256
                or qualification.get("provenance_sha256", {}).get("a_submission_manifest") != CASE05_A_SUBMISSION_MANIFEST_SHA256
                or not isinstance(source_a_job_id, str)
                or not source_a_job_id.isdigit()
                or source_a_job_id == "9789"
                or source.get("prior_failed_A") != {"job_id": "9789", "state": "FAILED",
                                                     "exit_code": "1:0", "a_science_seconds": 1}
                or build.get("job_id") != "9761" or build.get("state") != "FAILED"
                or build.get("exit_code") != "127:0" or build.get("installation_completed") is not True
                or build.get("installed_file_count") != 187
                or job_a.get("job_id") != source_a_job_id or job_a.get("state") != "COMPLETED"
                or job_b.get("state") != "COMPLETED"
                or not isinstance(job_a.get("partition"), str) or not job_a["partition"]
                or not isinstance(job_b.get("partition"), str) or not job_b["partition"]
                or not isinstance(job_a.get("node"), str) or not isinstance(job_b.get("node"), str)
                or job_a.get("allocated_cpus") != 4 or job_b.get("allocated_cpus") != 4
                or job_a.get("memory_gb") != 8 or job_b.get("memory_gb") != 8
                or job_a.get("gpu_count") != 1 or job_b.get("gpu_count") != 1
                or job_a.get("time_limit_seconds") != 1800 or job_b.get("time_limit_seconds") != 1200
                or qualification.get("jobs") != {"A": str(job_a.get("job_id", "")), "B": str(job_b.get("job_id", ""))}
                or budget.get("historical_science_seconds") != 80
                or budget.get("failed_9789_science_seconds") != 1
                or any(type(budget.get(key)) is not int
                       for key in ("a_science_seconds", "b_science_seconds", "cumulative_science_seconds"))
                or budget.get("cumulative_science_seconds", 3601) > 3600
                or budget.get("budget_seconds") != 3600
                or budget.get("cumulative_science_seconds") != 80 + 1 + budget.get("a_science_seconds", -1) + budget.get("b_science_seconds", -1)
                or installed.get("status") != "PINNED_187_FILES_UNCHANGED"
                or installed.get("entry_count") != 187
                or installed.get("baseline_sha256") != "ec96af0cba0328f333b1d5ec3b28a8673e796653085b810166c28a205803bfc1"
                or not isinstance(installed.get("before"), dict)
                or not isinstance(installed.get("after"), dict)
                or installed["before"].get("sha256") != installed["after"].get("sha256")):
            raise ScientificCheckUnavailable(
                "archived Gold replay does not preserve its distinct source attempt, 9761 build failure, and qualified A/B provenance")
        if not CASE05_OPENMOLCAS_RUNNER_INTEGRATION:
            raise ScientificCheckUnavailable(
                "case05 archived Gold evidence is structurally bound, but reward integration remains disabled pending real end-to-end verification")
        return {"attempt_id": context["attempt_id"], "source_attempt_id": source["source_attempt_id"],
                "receipt_sha256": sha256(receipt_path), "archived_gold_replay": True}
    expected_artifacts = {}
    receipt_path = receipt_root / "receipt.json"
    require_openmolcas_receipt_objects(receipt)
    if (receipt.get("schema") != "case05/openmolcas-runner-receipt/v1"
            or receipt.get("case_id") != "case-05"
            or receipt.get("attempt_id") != context.get("attempt_id")
            or not isinstance(receipt.get("program"), str)
            or re.fullmatch(r"OpenMolcas\s+v?[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?", receipt.get("program", "")) is None):
        raise ScientificCheckUnavailable("trusted receipt identity/schema does not attest this OpenMolcas attempt")
    source = receipt.get("source", {})
    om = _LEGACY_OPENMOLCAS_MODULE
    parser_file = Path(om.__file__).resolve()
    source_hashes = ("openmolcas_git_archive_sha256", "libxc_git_archive_sha256",
                     "wignernj_archive_sha256")
    if (not isinstance(source.get("openmolcas_tag"), str)
            or re.fullmatch(r"v?[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?", source["openmolcas_tag"]) is None
            or not isinstance(source.get("openmolcas_commit"), str)
            or re.fullmatch(r"[0-9a-f]{40,64}", source["openmolcas_commit"]) is None
            or any(not isinstance(source.get(key), str) or re.fullmatch(r"[0-9a-f]{64}", source[key]) is None
                   for key in source_hashes)
            or source.get("native_parser_sha256") != sha256(parser_file)):
        raise ScientificCheckUnavailable("trusted receipt source/parser identity is malformed or differs from the active native parser")
    receipt_version = receipt["program"].split(maxsplit=1)[1]
    if (source["openmolcas_tag"].removeprefix("v") != receipt_version.removeprefix("v")):
        raise ScientificCheckUnavailable("trusted OpenMolcas source tag and declared runtime version differ")
    build = receipt.get("build", {})
    if (build.get("state") != "COMPLETED" or build.get("exit_code") != 0
            or type(build.get("allocated_cpus")) is not int or build["allocated_cpus"] < 1
            or type(build.get("memory_gb")) is not int or build["memory_gb"] < 1
            or type(build.get("gpu_count")) is not int or build["gpu_count"] < 0
            or not isinstance(build.get("build_identity_sha256"), str)
            or len(build["build_identity_sha256"]) != 64
            or not isinstance(build.get("executable_sha256"), str)
            or len(build["executable_sha256"]) != 64
            or not isinstance(build.get("elapsed_seconds"), int)
            or type(build.get("time_limit_seconds")) is not int
            or not 1 <= build["time_limit_seconds"] <= 3600
            or build["elapsed_seconds"] > build["time_limit_seconds"]
            or build.get("official_smoke_normal_termination") is not True):
        raise ScientificCheckUnavailable("trusted receipt lacks successful common build and official smoke evidence")
    for point in ("A", "B"):
        p = receipt.get("points", {}).get(point, {})
        if (p.get("runner_attempt_id") != receipt["attempt_id"]
                or not str(p.get("job_id", "")).isdigit()
                or p.get("state") != "COMPLETED" or p.get("exit_code") != 0
                or type(p.get("allocated_cpus")) is not int or p["allocated_cpus"] < 1
                or type(p.get("memory_gb")) is not int or p["memory_gb"] < 1
                or type(p.get("gpu_count")) is not int or p["gpu_count"] < 0
                or p.get("build_identity_sha256") != build["build_identity_sha256"]
                or type(p.get("elapsed_seconds")) is not int
                or p.get("elapsed_seconds", -1) < 0):
            raise ScientificCheckUnavailable(f"trusted runner receipt does not attest successful {point} job/build identity")
        if not isinstance(p.get("scientific_elapsed_seconds"), int) or p["scientific_elapsed_seconds"] < 0:
            raise ScientificCheckUnavailable(f"trusted receipt lacks {point} scientific phase elapsed time")
        files = p.get("files")
        if not isinstance(files, dict):
            raise ScientificCheckUnavailable(f"trusted receipt lacks {point} artifact hashes")
        expected_artifacts.update(files)
        for name in ("input.inp", "program.log", "program.err", "output-hashes.txt", "exit-code.txt",
                     "job-id.txt", "spooled-script.slurm", "accounting.txt", "phase-marks.txt"):
            rel = f"raw/{point}/{name}"
            if files.get(rel) != sha256(out / rel):
                raise ScientificCheckUnavailable(f"trusted runner receipt does not bind {rel}")
        geom_rel = f"raw/{point}/ethene_grid_{point}.xyz"
        if files.get(geom_rel) != sha256(out / geom_rel):
            raise ScientificCheckUnavailable(f"trusted runner receipt does not bind {geom_rel}")
        if openmolcas_science_phase(out / "raw" / point / "phase-marks.txt", point) != p["scientific_elapsed_seconds"]:
            raise ScientificCheckUnavailable(f"runner receipt {point} science time differs from its phase markers")
        try:
            native_accounting = om.parse_accounting(out / f"raw/{point}/accounting.txt", str(p["job_id"]))
            native_spool_limit = om.slurm_script_time_limit(out / f"raw/{point}/spooled-script.slurm")
        except om.Unsupported as exc:
            raise ScientificCheckUnavailable(f"trusted {point} scheduler evidence is invalid: {exc}") from exc
        native_resources = slurm_script_resources(out / f"raw/{point}/spooled-script.slurm")
        if (native_accounting["state"] != "COMPLETED"
                or native_accounting["elapsed_seconds"] != p["elapsed_seconds"]
                or native_accounting["allocated_cpus"] != p["allocated_cpus"]
                or native_resources["cpus"] != p["allocated_cpus"]
                or native_resources["gpu_count"] != p["gpu_count"]
                or native_resources["memory_bytes"] < p["memory_gb"] * 1024**3
                or not 1 <= native_spool_limit <= 1200
                or native_spool_limit != native_accounting["time_limit_seconds"]
                or p.get("spooled_script_sha256") != sha256(out / f"raw/{point}/spooled-script.slurm")):
            raise ScientificCheckUnavailable(f"trusted {point} receipt does not match raw scheduler evidence")
        if parsed is not None and (
                p.get("job_id") != parsed[point]["job_id"]
                or p.get("spooled_script_sha256") != parsed[point]["spooled_script_sha256"]
                or p.get("elapsed_seconds") != parsed[point]["accounting"]["elapsed_seconds"]):
            raise ScientificCheckUnavailable(f"trusted receipt {point} scheduler binding differs from parsed native output")
    total = validate_openmolcas_science_budget(
        receipt.get("prior_scientific_elapsed_seconds"),
        {point: receipt["points"][point]["scientific_elapsed_seconds"] for point in ("A", "B")})
    receipt_files = receipt.get("build", {}).get("files")
    if not isinstance(receipt_files, dict) or not receipt_files:
        raise ScientificCheckUnavailable("trusted receipt lacks common build/official-smoke artifact hashes")
    for rel, expected in receipt_files.items():
        target = out / rel
        if not rel.startswith("raw/build/") or not target.is_file() or sha256(target) != expected:
            raise ScientificCheckUnavailable(f"trusted receipt common build artifact mismatch: {rel}")
    expected_artifacts.update(receipt_files)
    build_spool_rel = "raw/build/spooled-script.slurm"
    build_accounting_rel = "raw/build/accounting.txt"
    for rel in (build_spool_rel, build_accounting_rel, "raw/build/official-000.log",
                "raw/build/build-record.json", "raw/build/pymolcas", "raw/build/wignernj-v0.6.0.tar",
                "raw/build/wignernj-files.sha256"):
        if rel not in receipt_files:
            raise ScientificCheckUnavailable(f"trusted receipt omits common build artifact {rel}")
    if (not str(build.get("job_id", "")).isdigit()
            or build.get("spooled_script_sha256") != sha256(out / build_spool_rel)):
        raise ScientificCheckUnavailable("trusted receipt common build job/spool identity is invalid")
    try:
        build_accounting = om.parse_accounting(out / build_accounting_rel, str(build["job_id"]))
        build_spool_limit = om.slurm_script_time_limit(out / build_spool_rel)
    except om.Unsupported as exc:
        raise ScientificCheckUnavailable(f"trusted common build accounting is invalid: {exc}") from exc
    if build_accounting["state"] != "COMPLETED":
        raise ScientificCheckUnavailable("common OpenMolcas build job did not complete")
    if (build_accounting["elapsed_seconds"] != build["elapsed_seconds"]
            or build_accounting["time_limit_seconds"] != build["time_limit_seconds"]
            or build_spool_limit != build["time_limit_seconds"]
            or build.get("executable_sha256") != sha256(out / "raw/build/pymolcas")):
        raise ScientificCheckUnavailable("common build elapsed/executable hash differs from native Slurm evidence")
    smoke_text = (out / "raw/build/official-000.log").read_text(errors="replace")
    if "happy landing" not in smoke_text.lower():
        raise ScientificCheckUnavailable("official OpenMolcas test/standard/000.input lacks normal termination")
    try:
        build_record = json.loads((out / "raw/build/build-record.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ScientificCheckUnavailable(f"common build record is malformed: {exc}") from exc
    for key, expected in (("build_identity_sha256", build.get("build_identity_sha256")),
                          ("executable_sha256", build.get("executable_sha256")),
                          ("openmolcas_archive_sha256", source.get("openmolcas_git_archive_sha256")),
                          ("libxc_archive_sha256", source.get("libxc_git_archive_sha256")),
                          ("wignernj_archive_sha256", source.get("wignernj_archive_sha256"))):
        if build_record.get(key) != expected:
            raise ScientificCheckUnavailable(f"common build record {key} differs from trusted receipt/source pin")
    # Source archive bytes are matched to the trusted source manifest when
    # included in the capture; version labels themselves are not allowlists.
    if expected_artifacts != manifest_files:
        raise ScientificCheckUnavailable("host artifact manifest does not exactly cover the same A/B and build attempt")
    return {"attempt_id": receipt["attempt_id"], "receipt_sha256": sha256(receipt_path),
            "backend": "scheduler", "program_version": receipt_version,
            "cumulative_scientific_elapsed_seconds": total,
            "build_identity_sha256": build["build_identity_sha256"]}


def read_csv_rows(path: Path, expected_header: list[str]) -> list[dict]:
    if not path.is_file():
        raise CandidateFail(f"missing outputs file: {path.name}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise CandidateFail(f"{path.name} is empty")
        if [h.strip() for h in header] != expected_header:
            raise CandidateFail(f"{path.name} header mismatch: {header} != {expected_header}")
        rows = []
        for line_no, row in enumerate(reader, start=2):
            if not row:
                continue
            if len(row) != len(expected_header):
                raise CandidateFail(f"{path.name}:{line_no}: expected {len(expected_header)} fields, got {len(row)}")
            rows.append(dict(zip(expected_header, row)))
        return rows


def finite_float(raw: str, label: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise CandidateFail(f"{label}: invalid number {raw!r}") from exc
    if not math.isfinite(value):
        raise CandidateFail(f"{label}: value must be finite")
    return value


def verify_trusted_execution_before_science(out: Path, *, openmolcas_candidate: bool,
                                            preflight_only: bool = False) -> dict | None:
    """Check protected context/receipt/raw evidence before candidate science grading."""
    if preflight_only:
        return None
    if openmolcas_candidate:
        return verify_openmolcas_trusted_receipt(out, parsed=None)
    return verify_pyscf_trusted_receipt(out)


def trusted_openmolcas_route(candidate_program: object, *, preflight_only: bool) -> bool:
    """Protected mount inventory selects execution provenance before candidate claims."""
    if preflight_only:
        return str(candidate_program).lower().startswith("openmolcas")
    mounted = [root.exists() or root.is_symlink()
               for root in (TRUSTED_OPENMOLCAS_ROOT, TRUSTED_PYSCF_ROOT)]
    if sum(mounted) != 1:
        raise ScientificCheckUnavailable("exactly one protected native execution mount is required")
    return mounted[0]


def require_program_matches_execution(program: object, *, openmolcas: bool) -> None:
    expected = "openmolcas" if openmolcas else "pyscf"
    if not isinstance(program, str) or not program.lower().startswith(expected):
        raise CandidateFail(f"declared program does not match protected {expected} execution")
    if not re.fullmatch(rf"{expected}\s+[v]?[0-9]+(?:\.[0-9]+){{1,2}}(?:[-+][A-Za-z0-9.-]+)?", program.strip(), re.I):
        raise CandidateFail(f"declared program/version is malformed for protected {expected} execution")


def extract_pyscf_native_version(log: str) -> str:
    """Read the version from the recognized PySCF native-log banner."""
    match = re.search(r"^PySCF version ([0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?)$",
                      log, re.MULTILINE)
    if match is None:
        raise ScientificCheckUnavailable("native PySCF version banner is missing or unsupported")
    return match.group(1)


def require_declared_program_matches_native(declared: object, native_program: str) -> None:
    if not isinstance(declared, str) or declared.strip() != native_program:
        raise CandidateFail("summary program/version does not match the A/B native version banners")


def require_openmolcas_receipt_objects(receipt: dict) -> None:
    for key in ("source", "build", "points"):
        if not isinstance(receipt.get(key), dict):
            raise ScientificCheckUnavailable(f"protected OpenMolcas {key} must be an object")
    if set(receipt["points"]) != {"A", "B"} or any(
            not isinstance(value, dict) for value in receipt["points"].values()):
        raise ScientificCheckUnavailable("protected OpenMolcas points must contain A/B objects")


def _legacy_verify_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", nargs="?", default=".")
    parser.add_argument("--reference-dir", type=Path, default=None)
    parser.add_argument("--suite-root", type=Path, default=None)
    parser.add_argument("--preflight-only", action="store_true",
                        help="validate method and references only; never reports scientific PASS")
    args = parser.parse_args()

    out = Path(args.output_dir) / "outputs"
    tests_dir = Path(__file__).resolve().parent
    ref_path = tests_dir / "refs.json"
    try:
        expected_hash = "f37ff75ef151f77bcef451e7fe6540c66bcdb77bdd3c7089604554e0e457ddc4"
        if hashlib.sha256(ref_path.read_bytes()).hexdigest() != expected_hash:
            raise ValueError("hidden reference SHA-256 mismatch")
        reference = json.loads(ref_path.read_text(encoding="utf-8"))["points"]
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"ENV_ERROR: hidden reference unavailable or corrupt: {exc}", file=sys.stderr)
        return 2
    try:
        if not isinstance(reference, dict) or set(reference) != {"A", "B"}:
            raise ValueError("points must contain A and B")
        for point, ref in reference.items():
            if not isinstance(ref, dict):
                raise ValueError(f"{point}: point reference must be an object")
            if (len(ref["energy_hartree"]) != 3
                    or len(ref["forces_frobenius_norm_hartree_per_bohr"]) != 3
                    or len(ref["nacs_frobenius_norm_per_bohr"]) < 1):
                raise ValueError(f"{point}: reference arrays have wrong lengths")
            energy = [finite_float(x, f"reference {point} energy") for x in ref["energy_hartree"]]
            forces = [finite_float(x, f"reference {point} force") for x in ref["forces_frobenius_norm_hartree_per_bohr"]]
            nacs_ref = [finite_float(x, f"reference {point} NAC") for x in ref["nacs_frobenius_norm_per_bohr"]]
            gaps = [finite_float(ref["energy_gap_S10_eV"], f"reference {point} S10 gap"),
                    finite_float(ref["energy_gap_S21_eV"], f"reference {point} S21 gap")]
            if any(x < 0 for x in forces + nacs_ref + gaps):
                raise ValueError(f"{point}: reference norms and gaps must be nonnegative")
            ref["energy_hartree"], ref["forces_frobenius_norm_hartree_per_bohr"] = energy, forces
            ref["nacs_frobenius_norm_per_bohr"] = nacs_ref
            ref["energy_gap_S10_eV"], ref["energy_gap_S21_eV"] = gaps
            if not energy[0] < energy[1] < energy[2]:
                raise ValueError(f"{point}: reference states are not energy ordered")
    except (TypeError, ValueError, KeyError, CandidateFail) as exc:
        print(f"ENV_ERROR: hidden reference schema invalid: {exc}", file=sys.stderr)
        return 2

    try:
        failure = None if args.preflight_only else verify_execution_failure_proof()
        if failure is not None:
            detail = failure["failure"]
            raise ScientificCheckUnavailable(
                f"trusted local execution failed at {detail['point']}: {detail['error']} "
                f"(exit_code={detail['exit_code']})")
        rejection = None if args.preflight_only else verify_candidate_rejection_proof()
    except (ScientificCheckUnavailable, OSError, UnicodeError, ValueError, TypeError, KeyError, OverflowError, AttributeError, ImportError) as exc:
        print(f"ENV_ERROR: {exc}", file=sys.stderr)
        return 2
    if rejection is not None:
        print(f"FAIL: candidate did not provide an admissible protected request ({rejection['reason']})", file=sys.stderr)
        return 1
    try:
        openmolcas_candidate = trusted_openmolcas_route(
            None,
            preflight_only=args.preflight_only)
        receipt_info = verify_trusted_execution_before_science(
            out, openmolcas_candidate=openmolcas_candidate,
            preflight_only=args.preflight_only)
    except (ScientificCheckUnavailable, OSError, UnicodeError, ValueError, TypeError, KeyError, OverflowError, AttributeError, ImportError) as exc:
        print(f"ENV_ERROR: {exc}", file=sys.stderr)
        return 2
    if not out.is_dir():
        raise CandidateFail("missing outputs/")

    # ---------- L1: files ----------
    for name in ("casscf_results.csv", "nacs.csv", "convergence_report.md", "summary.json"):
        if not (out / name).is_file():
            raise CandidateFail(f"missing outputs/{name}")

    # ---------- L2: method summary ----------
    try:
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateFail(f"summary.json is unreadable: {exc}")
    for key in ("program", "active_space", "state_averaging", "basis", "converged", "raw_outputs", "caveats"):
        if key not in summary:
            raise CandidateFail(f"summary.json missing key: {key}")
    if not args.preflight_only:
        require_program_matches_execution(summary["program"], openmolcas=openmolcas_candidate)
    if str(summary.get("active_space", "")) not in ("(2,2)", "2,2", "(2e,2o)"):
        raise CandidateFail(f"active_space must be (2,2), got {summary.get('active_space')!r}")
    if (not isinstance(summary["converged"], dict)
            or set(summary["converged"]) != {"A", "B"}
            or any(type(v) is not bool or not v for v in summary["converged"].values())):
        raise CandidateFail("converged must be true for both A and B")
    if str(summary["basis"]).strip().lower() != "cc-pvdz":
        raise CandidateFail("basis must be cc-pVDZ")
    if not isinstance(summary["program"], str) or not summary["program"].strip():
        raise CandidateFail("program must name the CASSCF program and version")
    if not isinstance(summary["caveats"], list):
        raise CandidateFail("caveats must be a JSON list")
    state_avg = summary["state_averaging"]
    if not isinstance(state_avg, dict) or state_avg.get("states") != ["S0", "S1", "S2"]:
        raise CandidateFail("state_averaging must identify states S0/S1/S2 and equal weights")
    weights = state_avg.get("weights")
    if not isinstance(weights, list) or len(weights) != 3:
        raise CandidateFail("state_averaging.weights must contain three numbers")
    weights = [finite_float(x, "state_averaging weight") for x in weights]
    if any(abs(x - 1 / 3) > 1e-8 for x in weights):
        raise CandidateFail("state_averaging weights must each equal 1/3")
    if not isinstance(summary["raw_outputs"], list) or not summary["raw_outputs"]:
        raise CandidateFail("raw_outputs must list nonempty output files")
    for item in summary["raw_outputs"]:
        rel = Path(str(item))
        if rel.is_absolute() or ".." in rel.parts:
            raise CandidateFail(f"raw_outputs path must stay inside outputs/: {item!r}")
        cursor = out
        for part in rel.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise CandidateFail(f"raw_outputs path must not contain symlinks: {item!r}")
        resolved = (out / rel).resolve()
        try:
            resolved.relative_to(out.resolve())
        except ValueError:
            raise CandidateFail(f"raw_outputs path escapes outputs/: {item!r}")
        if not resolved.is_file() or resolved.is_symlink() or resolved.stat().st_size == 0:
            raise CandidateFail(f"raw_outputs must reference an existing nonempty regular file: {item!r}")
    report = (out / "convergence_report.md").read_text(encoding="utf-8")
    if not report.strip():
        raise CandidateFail("convergence_report.md must be nonempty")

    # ---------- L3: energies vs hidden reference ----------
    result_header = ["point_id", "state", "energy_hartree", "force_frobenius_norm_hartree_per_bohr",
                     "gap_to_lower_state_eV"]
    results = read_csv_rows(out / "casscf_results.csv", result_header)
    if len(results) != 6:
        raise CandidateFail(f"casscf_results.csv must contain exactly six rows, got {len(results)}")
    cells = {(r["point_id"], r["state"]): r for r in results}
    if set(cells) != {(p, s) for p in ("A", "B") for s in ("S0", "S1", "S2")}:
        raise CandidateFail("casscf_results must cover A/B x S0,S1,S2 exactly once")
    for point, ref in reference.items():
        ordered_energies = [finite_float(cells[(point, state)]["energy_hartree"], f"{point}/{state} energy")
                            for state in ("S0", "S1", "S2")]
        if not ordered_energies[0] < ordered_energies[1] < ordered_energies[2]:
            raise CandidateFail(f"{point}: state energies must be strictly increasing S0 < S1 < S2")
        for s_idx, state in enumerate(("S0", "S1", "S2")):
            row = cells[(point, state)]
            e_agent = finite_float(row["energy_hartree"], f"{point}/{state} energy")
            e_ref = ref["energy_hartree"][s_idx]
            if abs(e_agent - e_ref) > 0.002:
                raise CandidateFail(
                    f"{point}/{state}: energy {e_agent:.6f} Ha != reference {e_ref:.6f} Ha (tol 0.002 Ha)")
            f_agent = finite_float(row["force_frobenius_norm_hartree_per_bohr"], f"{point}/{state} force norm")
            if f_agent < 0:
                raise CandidateFail(f"{point}/{state}: force norm must be nonnegative")
            f_ref = ref["forces_frobenius_norm_hartree_per_bohr"][s_idx]
            if abs(f_agent - f_ref) > 0.05 * abs(f_ref):
                raise CandidateFail(
                    f"{point}/{state}: force norm {f_agent:.5f} != reference {f_ref:.5f} (rel tol 0.05)")
        gaps_ref = [0.0, ref["energy_gap_S10_eV"], ref["energy_gap_S21_eV"]]
        for s_idx, state in enumerate(("S0", "S1", "S2")):
            g_agent = finite_float(cells[(point, state)]["gap_to_lower_state_eV"], f"{point}/{state} gap")
            if g_agent < 0:
                raise CandidateFail(f"{point}/{state}: gap must be nonnegative")
            if s_idx > 0 and abs(g_agent - gaps_ref[s_idx]) > 0.002 * 27.211386245988:
                raise CandidateFail(f"{point}/{state}: gap {g_agent:.4f} eV != reference {gaps_ref[s_idx]:.4f} eV")
            if s_idx == 0 and abs(g_agent) > 1e-9:
                raise CandidateFail(f"{point}/S0: gap_to_lower_state_eV must be 0")
            expected_gap = 0.0 if s_idx == 0 else (ordered_energies[s_idx] - ordered_energies[s_idx - 1]) * 27.211386245988
            if abs(g_agent - expected_gap) > 0.05:
                raise CandidateFail(f"{point}/{state}: gap is inconsistent with adjacent reported energies")

    # ---------- L3: NAC magnitude ----------
    nac_header = ["point_id", "coupling", "nac01_frobenius_norm", "unit"]
    nacs = read_csv_rows(out / "nacs.csv", nac_header)
    nac_map = validate_nac_csv_contract(nacs)
    norms = {}
    for point in ("A", "B"):
        row = nac_map[point]
        value = finite_float(row["nac01_frobenius_norm"], f"{point} NAC norm")
        ref = reference[point]["nacs_frobenius_norm_per_bohr"][0]
        if abs(value - ref) > 0.35 * abs(ref):
            raise CandidateFail(f"{point}: |C01| {value:.4f} != reference {ref:.4f} (rel tol 0.35)")
        norms[point] = value
    def finite_json(value, path="summary"):
        if isinstance(value, float) and not math.isfinite(value):
            raise CandidateFail(f"{path}: JSON numbers must be finite")
        if isinstance(value, dict):
            for key, item in value.items():
                finite_json(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                finite_json(item, f"{path}[{index}]")
    finite_json(summary)
    if args.preflight_only:
        print("PRECHECK_PASS: method, files, and reference consistency checked; no native CASSCF execution verification")
        return 0
    if openmolcas_candidate:
        # Protected receipt mode selects local versus scheduler evidence. First
        # authenticate that capture, then parse its native files using the
        # version and parser identity it binds.
        receipt_info = verify_openmolcas_trusted_receipt(out)
        local_backend = receipt_info.get("backend") == "local"
        required_names = ("input.inp", f"ethene_grid_{point}.xyz", "program.log", "program.err",
                          "output-hashes.txt", "exit-code.txt") if local_backend else (
                          "input.inp", f"ethene_grid_{point}.xyz", "program.log", "program.err",
                          "output-hashes.txt", "exit-code.txt", "job-id.txt", "spooled-script.slurm",
                          "accounting.txt")
        required_openmolcas = {f"raw/{point}/{name}" for point in ("A", "B") for name in required_names}
        require_raw_output_declarations(summary, required_openmolcas, "OpenMolcas")
        native_results = parse_openmolcas_points(out, args.reference_dir, summary, receipt_info)
        # Published outputs must be byte-level numeric views of native A/B logs.
        crosscheck_openmolcas_csv(native_results, cells, nac_map)
        receipt_info = verify_openmolcas_trusted_receipt(out, native_results)
        if summary.get("attempt_id") != receipt_info["attempt_id"]:
            raise CandidateFail("summary attempt_id differs from the runner-owned attempt receipt")
        print("PASS: case-05 OpenMolcas A/B native outputs, runner receipt, and frozen scientific tolerances verified")
        return 0
    if not str(summary.get("program", "")).lower().startswith("pyscf"):
        raise ScientificCheckUnavailable(
            f"native verifier is not implemented for declared program {summary.get('program')!r}; scientific equivalence requires a dedicated parser")
    required_native = {f"raw/{point}/{name}" for point in ("A", "B")
                       for name in ("program.log", "result.json", "run_point.py", "geometry.xyz",
                                    "input-hashes.txt", "output-hashes.txt", "exit-code.txt")}
    require_raw_output_declarations(summary, required_native, "PySCF")
    native_results = load_native_results(out, args.reference_dir)
    local_execution = receipt_info.get("local_execution") if receipt_info else None
    if local_execution is not None:
        captured_program = f"PySCF {local_execution['version']}"
        if (any(row.get("program") != captured_program for row in native_results.values())
                or summary.get("program") != captured_program):
            raise ScientificCheckUnavailable(
                "trusted local runtime identity does not match the native A/B version and summary")

    # Reconcile published CSV values with quantities rebuilt from native PySCF tables.
    crosscheck_pyscf_csv(native_results, cells, nac_map)
    if summary.get("attempt_id") is not None and summary["attempt_id"] != receipt_info["attempt_id"]:
        raise CandidateFail("summary attempt_id differs from runner-owned PySCF receipt")
    print("PASS: case-05 PySCF A/B native outputs, protected same-attempt Slurm receipt, and frozen scientific tolerances verified")
    return 0

import argparse as _legacy_openmolcas_argparse
from datetime import datetime as _legacy_openmolcas_datetime, timezone as _legacy_openmolcas_timezone
import hashlib as _legacy_openmolcas_hashlib
import json as _legacy_openmolcas_json
import math as _legacy_openmolcas_math
import re as _legacy_openmolcas_re
import sys as _legacy_openmolcas_sys
from pathlib import Path as _legacy_openmolcas_Path

class _legacy_openmolcas_Unsupported(RuntimeError):
    pass

class _legacy_openmolcas_ScientificFailure(RuntimeError):
    """Recognized native evidence explicitly reports a failed science run."""
_legacy_openmolcas_OPENMOLCAS_SOURCE_SHA256 = '0e4da0afedc1491eeaa310b9be54de9e837ad08fa66e25cec26af53e1e290df6'
_legacy_openmolcas_LIBXC_SOURCE_SHA256 = '49bf74688dc80941594fffe1b53f9f47b30ddacd41bacaeb24f1b2b7d06fb1c3'
_legacy_openmolcas_WIGNERNJ_SOURCE_SHA256 = '504b30cd592eb99ababa8ad43d3058a260961ce5c0288162b34e2dd2c9668350'

def _legacy_openmolcas_sha256(path: _legacy_openmolcas_Path) -> str:
    h = _legacy_openmolcas_hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda : f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def _legacy_openmolcas_fnum(s: str) -> float:
    return float(s.replace('D', 'E').replace('d', 'e'))

def _legacy_openmolcas_sha_manifest(path: _legacy_openmolcas_Path) -> dict[str, str]:
    result = {}
    for line in path.read_text().splitlines():
        m = _legacy_openmolcas_re.fullmatch('([0-9a-fA-F]{64})\\s+\\*?(.*)', line.strip())
        if not m:
            raise _legacy_openmolcas_Unsupported(f'unrecognized output hash manifest line: {line!r}')
        result[_legacy_openmolcas_Path(m.group(2)).name] = m.group(1).lower()
    return result

def _legacy_openmolcas_read_xyz(path: _legacy_openmolcas_Path) -> tuple[list[str], list[list[float]]]:
    lines = path.read_text().splitlines()
    try:
        n = int(lines[0].strip())
        rows = lines[2:2 + n]
        if len(rows) != n:
            raise ValueError('truncated XYZ')
        (atoms, coords) = ([], [])
        for line in rows:
            fields = line.split()
            if len(fields) < 4:
                raise ValueError(f'invalid XYZ row {line!r}')
            atoms.append(fields[0].capitalize())
            coords.append([_legacy_openmolcas_fnum(x) for x in fields[1:4]])
    except (ValueError, IndexError) as exc:
        raise _legacy_openmolcas_Unsupported(f'cannot parse exact input geometry: {exc}') from exc
    return (atoms, coords)

def _legacy_openmolcas_native_input_geometry(text: str, atoms: list[str]) -> list[list[float]] | None:
    """Read the Gateway coordinates OpenMolcas actually consumed, in angstrom."""
    headers = list(_legacy_openmolcas_re.finditer('(?im)^\\s*Cartesian coordinates in angstrom\\s*:\\s*$', text))
    if not headers:
        return None
    rows = []
    for line in text[headers[0].end():].splitlines()[1:40]:
        match = _legacy_openmolcas_re.match('^\\s*(\\d+)\\s+([A-Za-z][A-Za-z0-9]*)\\s+([-+\\d.EeDd]+)\\s+([-+\\d.EeDd]+)\\s+([-+\\d.EeDd]+)', line)
        if match:
            rows.append((int(match.group(1)), match.group(2), [_legacy_openmolcas_fnum(match.group(i)) for i in (3, 4, 5)]))
            if len(rows) == len(atoms):
                break
    if len(rows) != len(atoms) or [r[0] for r in rows] != list(range(1, len(atoms) + 1)):
        raise _legacy_openmolcas_Unsupported('native Gateway coordinate table is incomplete or malformed')
    labels = [_legacy_openmolcas_re.sub('\\d+$', '', row[1]).capitalize() for row in rows]
    if labels != atoms:
        raise _legacy_openmolcas_Unsupported(f'native Gateway coordinate atom sequence differs: {labels}')
    return [row[2] for row in rows]

def _legacy_openmolcas_native_gradient_roots(text: str, expected_roots: list[int]) -> list[int]:
    """Bind runtime gradient tables to echoed ALASKA requests or source-format fixtures."""
    grad_markers = [m.start() for m in _legacy_openmolcas_re.finditer('Molecular gradients', text, _legacy_openmolcas_re.I)]
    module_starts = list(_legacy_openmolcas_re.finditer('(?im)^--- Start Module: (alaska|mclr)\\b', text))
    if not module_starts:
        roots_for_gradients = []
        previous_end = 0
        for marker in grad_markers:
            context = text[previous_end:marker]
            alaska_headers = list(_legacy_openmolcas_re.finditer('(?im)^\\s*&?ALASKA\\b.*$', context))
            if not alaska_headers:
                raise _legacy_openmolcas_Unsupported('native gradient lacks an adjacent ALASKA module header')
            active_context = context[alaska_headers[-1].start():]
            root_contexts = _legacy_openmolcas_re.findall('(?im)^\\s*Root\\s*=\\s*(\\d+)\\s*$', active_context)
            if len(root_contexts) != 1:
                raise _legacy_openmolcas_Unsupported('each native gradient must have exactly one adjacent ALASKA Root context')
            roots_for_gradients.append(int(root_contexts[0]))
            previous_end = marker + len('Molecular gradients')
        return roots_for_gradients
    input_match = _legacy_openmolcas_re.search('(?s)\\+\\+ ---------\\s+Input file\\s+---------\\s+\\n(.*?)\\n-- -+', text)
    if not input_match:
        raise _legacy_openmolcas_Unsupported('native OpenMolcas input echo is missing')
    echoed_roots = [int(x) for x in _legacy_openmolcas_re.findall('(?im)^\\s*Root\\s*=\\s*(\\d+)\\s*$', input_match.group(1))]
    if echoed_roots != expected_roots:
        raise _legacy_openmolcas_Unsupported(f'echoed ALASKA roots differ from verified requests: {echoed_roots}')
    if len(grad_markers) != len(expected_roots):
        raise _legacy_openmolcas_Unsupported(f'expected {len(expected_roots)} root gradient blocks, found {len(grad_markers)}')
    roots_for_gradients = []
    previous_end = 0
    for marker in grad_markers:
        segment = text[previous_end:marker]
        starts = [m.group(1).lower() for m in _legacy_openmolcas_re.finditer('(?im)^--- Start Module: (alaska|mclr)\\b', segment)]
        if starts != ['alaska', 'mclr', 'alaska']:
            raise _legacy_openmolcas_Unsupported(f'native gradient lacks one ALASKA/MCLR/ALASKA response chain: {starts}')
        if not _legacy_openmolcas_re.search('(?im)^--- Stop Module: mclr\\b.*_RC_ALL_IS_WELL_', segment):
            raise _legacy_openmolcas_Unsupported('native gradient MCLR response did not terminate normally')
        roots_for_gradients.append(expected_roots[len(roots_for_gradients)])
        previous_end = marker + len('Molecular gradients')
    return roots_for_gradients

def _legacy_openmolcas_parse_accounting(path: _legacy_openmolcas_Path, job_id: str) -> dict:
    lines = path.read_text().splitlines()
    if not lines:
        raise _legacy_openmolcas_Unsupported('sacct output is empty')
    headers = lines[0].split('|')
    columns = {name.strip().lower(): i for (i, name) in enumerate(headers)}
    required = ('jobid', 'state', 'elapsed', 'exitcode', 'alloccpus')
    if any((name not in columns for name in required)) or not {'timelimit', 'timelimitraw'} & columns.keys():
        raise _legacy_openmolcas_Unsupported('sacct output must include JobID/State/Elapsed/ExitCode/AllocCPUS/Timelimit')
    rows = []
    for line in lines[1:]:
        cols = line.split('|')
        if len(cols) > max(columns.values()) and cols[columns['jobid']].split('.')[0] == job_id:
            rows.append(cols)
    top = next((r for r in rows if r[columns['jobid']] == job_id), None)
    if top is None:
        raise _legacy_openmolcas_Unsupported(f'sacct record for job {job_id} is missing')
    state = top[columns['state']]
    elapsed = top[columns['elapsed']]
    exit_code = top[columns['exitcode']]
    raw_cpus = top[columns['alloccpus']]
    cpus = int(raw_cpus) if raw_cpus.isdigit() else None
    limit_col = columns.get('timelimit', columns.get('timelimitraw'))
    time_limit = top[limit_col]
    if state != 'COMPLETED' or exit_code != '0:0':
        raise _legacy_openmolcas_Unsupported(f'Slurm job did not complete cleanly: state={state}, exit={exit_code}')
    if cpus is None or cpus < 1:
        raise _legacy_openmolcas_Unsupported(f'invalid allocated CPU count: {raw_cpus!r}')
    elapsed_seconds = _legacy_openmolcas_parse_elapsed(elapsed)
    time_limit_seconds = _legacy_openmolcas_parse_elapsed(time_limit)
    if time_limit_seconds <= 0 or elapsed_seconds > time_limit_seconds:
        raise _legacy_openmolcas_Unsupported('sacct elapsed time exceeds its reported Slurm time limit')
    return {'job_id': job_id, 'state': state, 'elapsed': elapsed, 'elapsed_seconds': _legacy_openmolcas_parse_elapsed(elapsed), 'exit_code': exit_code, 'allocated_cpus': cpus, 'time_limit': time_limit, 'time_limit_seconds': time_limit_seconds}

def _legacy_openmolcas_slurm_script_time_limit(path: _legacy_openmolcas_Path) -> int:
    matches = _legacy_openmolcas_re.findall('(?m)^\\s*#SBATCH\\s+--time(?:=|\\s+)([^\\s#]+)', path.read_text())
    if len(matches) != 1:
        raise _legacy_openmolcas_Unsupported('spooled script must contain exactly one --time directive')
    try:
        return _legacy_openmolcas_parse_elapsed(matches[0])
    except (ValueError, TypeError) as exc:
        raise _legacy_openmolcas_Unsupported(f'unrecognized Slurm --time value {matches[0]!r}') from exc

def _legacy_openmolcas_parse_elapsed(value: str) -> int:
    day = 0
    if '-' in value:
        (d, value) = value.split('-', 1)
        day = int(d)
    parts = [int(x) for x in value.split(':')]
    if len(parts) == 3:
        (h, m, s) = parts
    elif len(parts) == 2:
        (h, m, s) = (0, parts[0], parts[1])
    else:
        raise _legacy_openmolcas_Unsupported(f'unrecognized Slurm elapsed time {value!r}')
    return day * 86400 + h * 3600 + m * 60 + s

def _legacy_openmolcas_read_hash_record(path: _legacy_openmolcas_Path, expected_name: str, expected_hash: str) -> None:
    line = path.read_text().strip()
    m = _legacy_openmolcas_re.fullmatch('([0-9a-fA-F]{64})\\s+\\*?(.*)', line)
    if not m or m.group(1).lower() != expected_hash.lower() or _legacy_openmolcas_Path(m.group(2)).name != expected_name:
        raise _legacy_openmolcas_Unsupported(f'hash receipt does not match {expected_name}')

def _legacy_openmolcas_parse_phase_file(path: _legacy_openmolcas_Path, point: str) -> dict:
    marks = {}
    for line in path.read_text().splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) != 2:
            raise _legacy_openmolcas_Unsupported(f'invalid phase timestamp: {line!r}')
        try:
            timestamp = _legacy_openmolcas_datetime.strptime(fields[0], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=_legacy_openmolcas_timezone.utc).timestamp()
        except ValueError as exc:
            raise _legacy_openmolcas_Unsupported(f'invalid phase timestamp: {line!r}') from exc
        marks[fields[1]] = timestamp
    required = ('libxc_build_start', 'libxc_build_end', 'openmolcas_build_start', 'openmolcas_build_end', 'official_smoke_start', 'official_smoke_end', f'{point}_science_start', f'{point}_science_end')
    missing = [x for x in required if x not in marks]
    if missing:
        raise _legacy_openmolcas_Unsupported(f'build phase timeline is incomplete: {missing}')
    pairs = {'libxc_build': ('libxc_build_start', 'libxc_build_end'), 'openmolcas_build': ('openmolcas_build_start', 'openmolcas_build_end'), 'official_smoke': ('official_smoke_start', 'official_smoke_end'), f'{point}_science': (f'{point}_science_start', f'{point}_science_end')}
    durations = {}
    for (label, (start, end)) in pairs.items():
        value = marks[end] - marks[start]
        if value < 0:
            raise _legacy_openmolcas_Unsupported(f'phase end precedes start: {label}')
        durations[label] = value
    return {'timestamps_utc': {k: v for (k, v) in marks.items()}, 'elapsed_seconds': durations}

def _legacy_openmolcas_native_rows_after(text: str, marker: str, natoms: int, occurrence: int=0) -> list[list[float]]:
    offsets = [m.start() for m in _legacy_openmolcas_re.finditer(_legacy_openmolcas_re.escape(marker), text, _legacy_openmolcas_re.I)]
    if occurrence >= len(offsets):
        raise _legacy_openmolcas_Unsupported(f'native block {marker!r} occurrence {occurrence + 1} is missing')
    stop = offsets[occurrence + 1] if occurrence + 1 < len(offsets) else len(text)
    tail = text[offsets[occurrence]:stop].splitlines()[1:120]
    rows = []
    row_pattern = _legacy_openmolcas_re.compile('^\\s*(.*?)\\s+([-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[EeDd][-+]?\\d+)?)\\s+([-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[EeDd][-+]?\\d+)?)\\s+([-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[EeDd][-+]?\\d+)?)\\s*$')
    for line in tail:
        match = row_pattern.match(line)
        if match and _legacy_openmolcas_re.match('^[A-Za-z]{1,2}', match.group(1).strip()):
            try:
                rows.append([_legacy_openmolcas_fnum(match.group(i)) for i in (2, 3, 4)])
            except ValueError:
                continue
            if len(rows) == natoms:
                break
        elif rows and ('Banner' in line or 'Happy Landing' in line):
            break
    if len(rows) != natoms:
        raise _legacy_openmolcas_Unsupported(f'native {marker!r} block has {len(rows)} atom rows, expected {natoms}')
    return rows

def _legacy_openmolcas_parse_native(log_path: _legacy_openmolcas_Path, xyz_path: _legacy_openmolcas_Path) -> dict:
    text = log_path.read_text(errors='strict')
    low = text.lower()
    if _legacy_openmolcas_re.search('\\bnot converged\\b', low):
        raise _legacy_openmolcas_ScientificFailure('native output explicitly reports nonconvergence')
    if 'error termination' in low:
        raise _legacy_openmolcas_ScientificFailure('native output explicitly reports error termination')
    if 'happy landing' not in low:
        raise _legacy_openmolcas_Unsupported('OpenMolcas normal-termination marker is missing')
    (atoms, coords) = _legacy_openmolcas_read_xyz(xyz_path)
    if atoms != ['C', 'C', 'H', 'H', 'H', 'H']:
        raise _legacy_openmolcas_Unsupported(f'unexpected case-05 geometry atom sequence: {atoms}')
    weight_lines = _legacy_openmolcas_re.findall('(?im)^\\s*weights\\s+((?:[-+\\d.eEdD]+\\s*){3})$', text)
    roots_lines = _legacy_openmolcas_re.findall('(?im)^\\s*CI roots used\\s+([\\d\\s]+)$', text)
    if not weight_lines or not roots_lines:
        raise _legacy_openmolcas_Unsupported('native CI root/weight table was not recognized')
    weights = [_legacy_openmolcas_fnum(x) for x in _legacy_openmolcas_re.findall('[-+]?\\d+(?:\\.\\d*)?(?:[EeDd][-+]?\\d+)?', weight_lines[-1])]
    roots = [int(x) for x in roots_lines[-1].split()]
    if roots != [1, 2, 3] or len(weights) != 3 or any((abs(w - 1 / 3) > 0.000501 for w in weights)):
        raise _legacy_openmolcas_Unsupported(f'native SA root/weight contract differs: roots={roots}, weights={weights}')
    energy_pairs = _legacy_openmolcas_re.findall('(?im)^\\s*(?:::)?\\s*RASSCF root number\\s+(\\d+)\\s+Total energy:\\s*([-+\\d.eEdD]+)', text)
    energy_by_root = {}
    for (root, val) in energy_pairs:
        energy_by_root[int(root)] = _legacy_openmolcas_fnum(val)
    if set(energy_by_root) != {1, 2, 3}:
        raise _legacy_openmolcas_Unsupported(f'three native RASSCF root energies not found: {sorted(energy_by_root)}')
    energies = [energy_by_root[i] for i in (1, 2, 3)]
    if not energies[0] < energies[1] < energies[2]:
        raise _legacy_openmolcas_Unsupported('native root energies are not in the requested lowest-root order')
    grad_markers = [m.start() for m in _legacy_openmolcas_re.finditer('Molecular gradients', text, _legacy_openmolcas_re.I)]
    if len(grad_markers) != 3:
        raise _legacy_openmolcas_Unsupported(f'expected 3 root gradient blocks, found {len(grad_markers)}')
    gradients = [_legacy_openmolcas_native_rows_after(text, 'Molecular gradients', len(atoms), i) for i in range(len(grad_markers))]
    roots_for_gradients = _legacy_openmolcas_native_gradient_roots(text, [1, 2, 3])
    if roots_for_gradients != [1, 2, 3]:
        raise _legacy_openmolcas_Unsupported(f'native ALASKA gradient root order differs from 1,2,3: {roots_for_gradients}')
    consumed_coords = _legacy_openmolcas_native_input_geometry(text, atoms)
    if consumed_coords is not None and any((abs(consumed_coords[i][j] - coords[i][j]) > 1e-06 for i in range(len(atoms)) for j in range(3))):
        raise _legacy_openmolcas_Unsupported('native Gateway coordinates differ from the submitted XYZ in angstrom')
    nac = _legacy_openmolcas_native_rows_after(text, 'Total derivative coupling', len(atoms))
    if text.lower().count('total derivative coupling') != 1:
        raise _legacy_openmolcas_Unsupported('expected one native C01 Total derivative coupling block')
    vector_norm = lambda vecs: _legacy_openmolcas_math.sqrt(sum((v * v for row in vecs for v in row)))
    module_format = bool(_legacy_openmolcas_re.search('(?im)^--- Start Module: (?:alaska|mclr)\\b', text))
    if module_format:
        rasscf_region = _legacy_openmolcas_re.search('(?is)RASSCF iterations: Energy and convergence statistics(.*?)(?:\\n\\s*\\+\\+|\\n\\s*--- Start Module:)', text)
        rasscf_convergence = bool(rasscf_region and _legacy_openmolcas_re.search('(?im)^\\s*Convergence after\\s+\\d+\\s+iterations\\s*$', rasscf_region.group(1)))
        mclr_converged = len(_legacy_openmolcas_re.findall('(?im)^\\s*Perturbation no:\\s*\\d+ converged in\\s+\\d+ steps\\.', text))
        if not rasscf_convergence or mclr_converged != 4:
            raise _legacy_openmolcas_Unsupported('native RASSCF or ALASKA/MCLR response convergence evidence is incomplete')
        conv = {'normal_termination_marker': 'Happy Landing' in text or 'Happy landing' in text, 'rasscf_convergence_marker_count': int(rasscf_convergence), 'mclr_perturbation_convergence_marker_count': mclr_converged, 'super_ci_nonconvergence_marker_count': len(_legacy_openmolcas_re.findall('Super-CI not converged', text, _legacy_openmolcas_re.I))}
    else:
        conv = {'normal_termination_marker': 'Happy Landing' in text or 'Happy landing' in text, 'ci_energy_convergence_marker_count': len(_legacy_openmolcas_re.findall('Convergence on CI energ', text, _legacy_openmolcas_re.I)), 'davidson_vector_convergence_marker_count': len(_legacy_openmolcas_re.findall('Convergence on Davidson expansion vector', text, _legacy_openmolcas_re.I)), 'super_ci_nonconvergence_marker_count': len(_legacy_openmolcas_re.findall('Super-CI not converged', text, _legacy_openmolcas_re.I))}
        if conv['ci_energy_convergence_marker_count'] == 0 or conv['davidson_vector_convergence_marker_count'] == 0:
            raise _legacy_openmolcas_Unsupported('RASSCF native CI/Davidson convergence markers are absent')
    if conv['super_ci_nonconvergence_marker_count']:
        raise _legacy_openmolcas_ScientificFailure('RASSCF Super-CI nonconvergence reported')
    return {'geometry': {'atoms': atoms, 'coordinates_angstrom': coords}, 'method': {'basis': 'cc-pVDZ', 'active_electrons': 2, 'active_orbitals': 2, 'inactive_orbitals': 7, 'spin_multiplicity': 1, 'roots': roots, 'weights_native_printed': weights, 'spin_evidence': 'RASSCF Spin=1 in the hashed input; the three native CI roots are eigenstates of this same singlet spin block.'}, 'energies_hartree': energies, 'gradients_hartree_per_bohr': gradients, 'gradient_roots_native_order': roots_for_gradients, 'gradient_frobenius_norms_hartree_per_bohr': [vector_norm(x) for x in gradients], 'nac01_definition': 'OpenMolcas ALASKA NAC 1 2; Total derivative coupling block <root 2|d root 1/dR>, including CSF term unless native input explicitly says NOCSF', 'nac01_per_bohr': nac, 'nac01_frobenius_norm_per_bohr': vector_norm(nac), 'convergence_evidence': conv}

def _legacy_openmolcas_verify_input(inp: _legacy_openmolcas_Path, xyz: _legacy_openmolcas_Path) -> dict:
    text = inp.read_text()
    if _legacy_openmolcas_re.search('(?im)^\\s*NOCSF\\b', text):
        raise _legacy_openmolcas_Unsupported('NOCSF is forbidden; C01 must use the frozen full-CSF convention')
    block_matches = list(_legacy_openmolcas_re.finditer('(?im)^\\s*&([A-Z0-9_]+)\\s*$', text))
    blocks = []
    for (index, match) in enumerate(block_matches):
        end = block_matches[index + 1].start() if index + 1 < len(block_matches) else len(text)
        blocks.append((match.group(1).upper(), text[match.end():end]))
    names = [name for (name, _) in blocks]
    if names.count('SCF') != 1 or names.count('RASSCF') != 1 or names.count('GATEWAY') != 1:
        raise _legacy_openmolcas_Unsupported('input must contain exactly one GATEWAY, SCF and RASSCF block')
    alaska = [body for (name, body) in blocks if name == 'ALASKA']
    if len(alaska) != 4:
        raise _legacy_openmolcas_Unsupported('input must contain exactly three root gradients and one C01 NAC ALASKA block')
    requested_roots = []
    for body in alaska:
        roots_here = _legacy_openmolcas_re.findall('(?im)^\\s*Root\\s*=\\s*(\\d+)\\s*$', body)
        if roots_here:
            if len(roots_here) != 1:
                raise _legacy_openmolcas_Unsupported('duplicate/conflicting Root directives in an ALASKA block')
            requested_roots.append(int(roots_here[0]))
    if requested_roots != [1, 2, 3]:
        raise _legacy_openmolcas_Unsupported(f'ALASKA root requests must be exactly 1,2,3 once each; got {requested_roots}')
    nac_blocks = [body for body in alaska if _legacy_openmolcas_re.search('(?im)^\\s*NAC\\s*$', body)]
    if len(nac_blocks) != 1 or _legacy_openmolcas_re.search('(?im)^\\s*1\\s+2\\s*$', nac_blocks[0]) is None:
        raise _legacy_openmolcas_Unsupported('input must request the full-CSF C01 NAC 1 2 exactly once')
    gateway_body = next((body for (name, body) in blocks if name == 'GATEWAY'))
    if _legacy_openmolcas_re.search('(?im)^\\s*Charge\\s*=', gateway_body):
        raise _legacy_openmolcas_Unsupported('GATEWAY Charge is invalid for the pinned OpenMolcas input protocol; set neutral charge in SCF')
    for (key, value) in (('Basis', 'cc-pVDZ'), ('Group', 'NoSym')):
        found = _legacy_openmolcas_re.findall(f'(?im)^\\s*{key}\\s*=\\s*(.*?)\\s*$', gateway_body)
        if found != [value]:
            raise _legacy_openmolcas_Unsupported(f'GATEWAY must specify {key}={value} exactly once; got {found}')
    for name in ('SCF', 'RASSCF'):
        body = next((body for (block_name, body) in blocks if block_name == name))
        if name == 'SCF':
            expected = {'Charge': '0'}
        else:
            expected = {'Spin': '1', 'NActEl': '2 0 0', 'Inactive': '7', 'Ras2': '2', 'CIroot': '3 3 1'}
        for (key, value) in expected.items():
            found = _legacy_openmolcas_re.findall(f'(?im)^\\s*{key}\\s*=\\s*(.*?)\\s*$', body)
            if found != [value]:
                raise _legacy_openmolcas_Unsupported(f'{name} must specify {key}={value} exactly once; got {found}')
    if _legacy_openmolcas_re.search('(?im)^\\s*&SCF\\s*$', text) is None:
        raise _legacy_openmolcas_Unsupported('input does not include closed-shell SCF before RASSCF')
    if _legacy_openmolcas_re.search('(?im)^\\s*UHF\\b', text):
        raise _legacy_openmolcas_Unsupported('input requests unrestricted SCF, inconsistent with the fixed singlet protocol')
    coord_ref = _legacy_openmolcas_re.search('(?im)^\\s*Coord\\s*=\\s*(\\S+)\\s*$', text)
    if not coord_ref or _legacy_openmolcas_Path(coord_ref.group(1)).name != xyz.name:
        raise _legacy_openmolcas_Unsupported('OpenMolcas input Coord does not identify the frozen case geometry')
    return {'basis': 'cc-pVDZ', 'charge': 0, 'spin_multiplicity': 1, 'active_electrons': 2, 'active_orbitals': 2, 'inactive_orbitals': 7, 'roots': [1, 2, 3], 'weights': [1 / 3] * 3, 'csf_correction': 'enabled'}

def _legacy_openmolcas_parse_point_native(inp: _legacy_openmolcas_Path, xyz: _legacy_openmolcas_Path, log: _legacy_openmolcas_Path, err: _legacy_openmolcas_Path | None=None, exit_code: _legacy_openmolcas_Path | None=None, expected_point: str | None=None) -> dict:
    """Parse one point's exact native input/output; no build or runner trust implied."""
    method = _legacy_openmolcas_verify_input(inp, xyz)
    if exit_code is not None and exit_code.read_text().strip() != '0':
        raise _legacy_openmolcas_Unsupported(f"{expected_point or 'point'} OpenMolcas exit code is nonzero")
    if err is not None:
        stderr = err.read_text(errors='replace')
        if stderr.strip() and _legacy_openmolcas_re.search('(?im)\\b(error|fatal|failed)\\b', stderr):
            raise _legacy_openmolcas_Unsupported('OpenMolcas stderr contains a failure marker')
    result = _legacy_openmolcas_parse_native(log, xyz)
    result['input_sha256'] = _legacy_openmolcas_sha256(inp)
    result['geometry_sha256'] = _legacy_openmolcas_sha256(xyz)
    result['native_log_sha256'] = _legacy_openmolcas_sha256(log)
    result['native_stderr_sha256'] = _legacy_openmolcas_sha256(err) if err is not None else None
    result['method'] = {**result['method'], **method}
    result['point_id'] = expected_point
    return result

def _legacy_openmolcas_main() -> int:
    ap = _legacy_openmolcas_argparse.ArgumentParser()
    ap.add_argument('--receipt', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--spooled-script', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--input', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--geometry', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--program-log', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--official-smoke-log', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--exit-code', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--accounting', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--phase-marks', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--source-archive-hash', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--libxc-archive-hash', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--wignernj-archive-hash', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--geometry-hash-record', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--output-hashes', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--molden-audit', type=_legacy_openmolcas_Path, required=True)
    ap.add_argument('--point', choices=('A', 'B'), default='A')
    ap.add_argument('--output', type=_legacy_openmolcas_Path, required=True)
    a = ap.parse_args()
    try:
        receipt = _legacy_openmolcas_json.loads(a.receipt.read_text())
        job_id = str(receipt['job_id'])
        if receipt.get('case_id') != 'case-05' or receipt.get('calculation', {}).get('method') != 'SA(3)-CASSCF(2,2)/cc-pVDZ':
            raise _legacy_openmolcas_Unsupported('submission receipt is not the pinned case-05 OpenMolcas experiment')
        source = receipt.get('source', {})
        if source.get('openmolcas_tag') != 'v26.06' or source.get('openmolcas_git_archive_sha256') != _legacy_openmolcas_OPENMOLCAS_SOURCE_SHA256 or source.get('libxc_tag') != '7.0.0' or (source.get('libxc_git_archive_sha256') != _legacy_openmolcas_LIBXC_SOURCE_SHA256) or (source.get('wignernj_tag') != 'v0.6.0') or (source.get('wignernj_commit') != '0c907ee4e726343e333be1d4c8663172da95cbe8') or (source.get('wignernj_archive_sha256') != _legacy_openmolcas_WIGNERNJ_SOURCE_SHA256):
            raise _legacy_openmolcas_Unsupported('source tag/archive hashes do not match the pinned OpenMolcas/Libxc source')
        trees = source.get('working_tree_at_2026_10_07_audit', {})
        if trees.get('openmolcas_status_porcelain_v1') != 'clean (including untracked files)' or trees.get('libxc_status_porcelain_v1') != 'clean (including untracked files)':
            raise _legacy_openmolcas_Unsupported('source working-tree cleanliness was not attested')
        if _legacy_openmolcas_sha256(a.spooled_script) != receipt.get('spooled_script_sha256'):
            raise _legacy_openmolcas_Unsupported('spooled Slurm script SHA does not match this attempt receipt')
        geom_hash = _legacy_openmolcas_sha256(a.geometry)
        if geom_hash != receipt.get('calculation', {}).get('public_geometry_sha256'):
            raise _legacy_openmolcas_Unsupported('frozen geometry SHA does not match this attempt receipt')
        acct = _legacy_openmolcas_parse_accounting(a.accounting, job_id)
        spool_limit_seconds = _legacy_openmolcas_slurm_script_time_limit(a.spooled_script)
        requested_build_seconds = receipt.get('source_build_and_test_budget', {}).get('requested_build_seconds')
        if requested_build_seconds != spool_limit_seconds or acct['time_limit_seconds'] != spool_limit_seconds or spool_limit_seconds <= 0 or (spool_limit_seconds > 3600):
            raise _legacy_openmolcas_Unsupported('requested build cap, spooled script, and sacct Timelimit do not agree within the fixed 1-hour build cap')
        if receipt.get('source', {}).get('wignernj_tag') != 'v0.6.0' or receipt.get('source', {}).get('wignernj_commit') != '0c907ee4e726343e333be1d4c8663172da95cbe8' or receipt.get('source', {}).get('wignernj_archive_sha256') != _legacy_openmolcas_WIGNERNJ_SOURCE_SHA256:
            raise _legacy_openmolcas_Unsupported('pinned libwignernj v0.6.0 source/archive identity is missing or invalid')
        phase = _legacy_openmolcas_parse_phase_file(a.phase_marks, a.point)
        phase_science_seconds = phase['elapsed_seconds'][f'{a.point}_science']
        prior_science_seconds = int(receipt.get('source_build_and_test_budget', {}).get('scientific_qc_elapsed_seconds_so_far', 0))
        if prior_science_seconds + phase_science_seconds > 3600:
            raise _legacy_openmolcas_Unsupported('cumulative scientific QC time exceeds the fixed one-hour budget')
        _legacy_openmolcas_read_hash_record(a.source_archive_hash, '-', _legacy_openmolcas_OPENMOLCAS_SOURCE_SHA256)
        _legacy_openmolcas_read_hash_record(a.libxc_archive_hash, '-', _legacy_openmolcas_LIBXC_SOURCE_SHA256)
        _legacy_openmolcas_read_hash_record(a.wignernj_archive_hash, '-', _legacy_openmolcas_WIGNERNJ_SOURCE_SHA256)
        _legacy_openmolcas_read_hash_record(a.geometry_hash_record, a.geometry.name, geom_hash)
        exit_code = a.exit_code.read_text().strip()
        if exit_code != '0':
            raise _legacy_openmolcas_Unsupported(f'build+smoke+A job exit code is {exit_code}')
        smoke = a.official_smoke_log.read_text(errors='strict')
        if 'happy landing' not in smoke.lower():
            raise _legacy_openmolcas_Unsupported('official test/standard/000.input lacks normal-termination marker')
        _legacy_openmolcas_verify_input(a.input, a.geometry)
        output_hashes = _legacy_openmolcas_sha_manifest(a.output_hashes)
        program_err = a.program_log.with_suffix('.err')
        for file in (a.input, a.program_log, program_err):
            if output_hashes.get(file.name) != _legacy_openmolcas_sha256(file):
                raise _legacy_openmolcas_Unsupported(f'native output manifest missing/mismatch for {file.name}')
        scientific = _legacy_openmolcas_parse_point_native(a.input, a.geometry, a.program_log, program_err, a.exit_code, a.point)
        if a.molden_audit:
            audit = _legacy_openmolcas_json.loads(a.molden_audit.read_text())
            if audit.get('status') != 'AUDIT_ONLY' or audit.get('geometry_sha256') != geom_hash:
                raise _legacy_openmolcas_Unsupported('Molden orbital audit does not bind to the same geometry')
            try:
                require_current_molden_audit_source(audit)
            except CandidateFail as exc:
                raise _legacy_openmolcas_Unsupported(str(exc)) from exc
            if float(audit.get('molden_geometry_max_abs_difference_angstrom', _legacy_openmolcas_math.inf)) > 0.0001:
                raise _legacy_openmolcas_Unsupported('Molden orbitals do not match the frozen geometry coordinates')
            molden_path = a.molden_audit.parent / str(audit.get('molden_file', ''))
            if not molden_path.is_file() or _legacy_openmolcas_sha256(molden_path) != audit.get('molden_sha256'):
                raise _legacy_openmolcas_Unsupported('Molden orbital audit input is missing or its hash does not match')
            if output_hashes.get(molden_path.name) != audit.get('molden_sha256'):
                raise _legacy_openmolcas_Unsupported('Molden file is not bound by the native run output manifest')
            active = [x for x in audit.get('orbitals', []) if x.get('rasscf_active_slot_candidate') in (1, 2)]
            if len(active) != 2:
                raise _legacy_openmolcas_Unsupported('Molden audit lacks both active-slot orbital records')
            if sorted((x['rasscf_active_slot_candidate'] for x in active)) != [1, 2]:
                raise _legacy_openmolcas_Unsupported('Molden active-slot candidates are duplicated or incomplete')
            subspace = audit.get('active_orbital_subspace', {})
            if subspace.get('active_mo_indices_1based') != [8, 9]:
                raise _legacy_openmolcas_Unsupported('Molden audit does not identify the two fixed RAS2 active slots')
            eigenvalues = subspace.get('active_pz_principal_projection_eigenvalues', [])
            if len(eigenvalues) != 2 or any((not isinstance(x, (int, float)) or not _legacy_openmolcas_math.isfinite(x) or x < -1e-08 or (x > 1.0 + 1e-06) for x in eigenvalues)):
                raise _legacy_openmolcas_Unsupported('Molden active-subspace pz projection diagnostics are malformed')
            scientific['active_orbital_identity_evidence'] = active
            scientific['active_orbital_subspace_diagnostic'] = subspace
            scientific['active_orbital_subspace_diagnostic_scope'] = 'Molden pz projections are diagnostic only and are not an energy, force, or NAC tolerance'
            scientific['molden_audit_sha256'] = _legacy_openmolcas_sha256(a.molden_audit)
        result = {'schema': 'case05.openmolcas-native-audit.v1', 'status': 'NATIVE_EVIDENCE_VALIDATED_CANDIDATE', 'attempt_id': f'case05-openmolcas-{job_id}-{a.point}', 'program': 'OpenMolcas v26.06', 'native_parser_schema': 'case05.openmolcas-native-audit.v1', 'scientific_tolerance_evaluation': 'not performed by this native parser; downstream verifier applies frozen tolerances', 'accounting': acct, 'phase_timing': phase, 'cumulative_scientific_qc_seconds': prior_science_seconds + phase_science_seconds, 'source': receipt['source'], 'files': {'submission_receipt': {'name': a.receipt.name, 'sha256': _legacy_openmolcas_sha256(a.receipt)}, 'spooled_script': {'name': a.spooled_script.name, 'sha256': _legacy_openmolcas_sha256(a.spooled_script)}, 'native_parser': {'name': _legacy_openmolcas_Path(__file__).name, 'sha256': _legacy_openmolcas_sha256(_legacy_openmolcas_Path(__file__).resolve())}, 'calculation_input': {'name': a.input.name, 'sha256': _legacy_openmolcas_sha256(a.input)}, 'geometry': {'name': a.geometry.name, 'sha256': geom_hash}, 'native_program_log': {'name': a.program_log.name, 'sha256': _legacy_openmolcas_sha256(a.program_log)}, 'native_program_stderr': {'name': program_err.name, 'sha256': _legacy_openmolcas_sha256(program_err)}, 'official_smoke_log': {'name': a.official_smoke_log.name, 'sha256': _legacy_openmolcas_sha256(a.official_smoke_log)}, 'job_exit_code': {'name': a.exit_code.name, 'sha256': _legacy_openmolcas_sha256(a.exit_code)}, 'slurm_accounting': {'name': a.accounting.name, 'sha256': _legacy_openmolcas_sha256(a.accounting)}, 'phase_marks': {'name': a.phase_marks.name, 'sha256': _legacy_openmolcas_sha256(a.phase_marks)}, 'openmolcas_source_archive_hash': {'name': a.source_archive_hash.name, 'sha256': _legacy_openmolcas_sha256(a.source_archive_hash)}, 'libxc_source_archive_hash': {'name': a.libxc_archive_hash.name, 'sha256': _legacy_openmolcas_sha256(a.libxc_archive_hash)}, 'geometry_hash_record': {'name': a.geometry_hash_record.name, 'sha256': _legacy_openmolcas_sha256(a.geometry_hash_record)}, 'output_hash_manifest': {'name': a.output_hashes.name, 'sha256': _legacy_openmolcas_sha256(a.output_hashes)}}, 'scientific_data': scientific}
        a.output.write_text(_legacy_openmolcas_json.dumps(result, indent=2) + '\n')
        print(f'NATIVE_CANDIDATE: {a.output}')
        return 0
    except _legacy_openmolcas_ScientificFailure as exc:
        print(f'SCIENTIFIC_FAIL: {exc}', file=_legacy_openmolcas_sys.stderr)
        return 1
    except (OSError, KeyError, TypeError, ValueError, _legacy_openmolcas_json.JSONDecodeError, _legacy_openmolcas_Unsupported) as exc:
        print(f'ENV2_UNSUPPORTED: {exc}', file=_legacy_openmolcas_sys.stderr)
        return 2

import hashlib as _legacy_pyscf_hashlib
import json as _legacy_pyscf_json
import math as _legacy_pyscf_math
import re as _legacy_pyscf_re
from pathlib import Path as _legacy_pyscf_Path
class _LegacyNumpyProxy:
    """Load NumPy only on the legacy native-PySCF route."""

    def __getattr__(self, name):
        return getattr(__import__("numpy"), name)


_legacy_pyscf_np = _LegacyNumpyProxy()

class _legacy_pyscf_NativeOutputError(ValueError):
    pass

def _legacy_pyscf__require(condition: bool, message: str) -> None:
    if not condition:
        raise _legacy_pyscf_NativeOutputError(message)

def _legacy_pyscf__vec_from_marker(log: str, marker: str, label: str) -> _legacy_pyscf_np.ndarray:
    matches = _legacy_pyscf_re.findall(f'^{_legacy_pyscf_re.escape(marker)}\\s*(\\[.*\\])\\s*$', log, _legacy_pyscf_re.M)
    _legacy_pyscf__require(len(matches) == 1, f'expected one {label} marker, found {len(matches)}')
    try:
        value = _legacy_pyscf_np.asarray(_legacy_pyscf_json.loads(matches[0]), dtype=float)
    except (_legacy_pyscf_json.JSONDecodeError, ValueError) as exc:
        raise _legacy_pyscf_NativeOutputError(f'invalid {label} marker array') from exc
    _legacy_pyscf__require(value.shape == (6, 3), f'{label} must be (6,3), got {value.shape}')
    _legacy_pyscf__require(bool(_legacy_pyscf_np.isfinite(value).all()), f'{label} contains nonfinite values')
    return value

def _legacy_pyscf__gradient_blocks(log: str) -> list[_legacy_pyscf_np.ndarray]:
    header = '--------------- StateAverageCASSCF gradients ---------------'
    blocks = []
    for segment in log.split(header)[1:]:
        rows = []
        for line in segment.splitlines():
            m = _legacy_pyscf_re.match('^\\s*(\\d+)\\s+[A-Z][a-z]?\\s+([-+0-9.eE]+)\\s+([-+0-9.eE]+)\\s+([-+0-9.eE]+)\\s*$', line)
            if m:
                rows.append([float(m.group(i)) for i in (2, 3, 4)])
                if len(rows) == 6:
                    break
        if len(rows) == 6:
            blocks.append(_legacy_pyscf_np.asarray(rows, dtype=float))
    return blocks
_legacy_pyscf_PINNED_RUN_POINT_SHA256 = '0c64aa5ecb6e3d05f5adc5ba5084a4de6089e35607970c7357d3c5539433c9ea'
_legacy_pyscf_PINNED_SEEDED_RUN_POINT_SHA256 = 'b47dc45d099a2f6c6ff5e2fec3a77b14163d8d1284c3b6395713a1abac24b717'

def _legacy_pyscf__read_xyz(path: _legacy_pyscf_Path) -> tuple[list[str], _legacy_pyscf_np.ndarray]:
    lines = path.read_text(encoding='utf-8').splitlines()
    try:
        n = int(lines[0])
    except (ValueError, IndexError) as exc:
        raise _legacy_pyscf_NativeOutputError(f'invalid reference geometry {path}') from exc
    rows = [line.split() for line in lines[2:2 + n]]
    if len(rows) != n or any((len(row) < 4 for row in rows)):
        raise _legacy_pyscf_NativeOutputError(f'truncated reference geometry {path}')
    return ([row[0] for row in rows], _legacy_pyscf_np.asarray([[float(x) for x in row[1:4]] for row in rows]))

def _legacy_pyscf_parse_native_log(log_path: _legacy_pyscf_Path, point: str, expected_geometry: _legacy_pyscf_Path, executed_script: _legacy_pyscf_Path, initial_seed: _legacy_pyscf_Path | None=None) -> dict:
    (log_path, expected_geometry, executed_script) = map(_legacy_pyscf_Path, (log_path, expected_geometry, executed_script))
    log = log_path.read_text(encoding='utf-8', errors='replace')
    geometry_sha = _legacy_pyscf_hashlib.sha256(expected_geometry.read_bytes()).hexdigest()
    version_match = _legacy_pyscf_re.search(r'PySCF version ([0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?)', log)
    if version_match is None:
        raise _legacy_pyscf_NativeOutputError('unsupported native PySCF version banner')
    native_version = version_match.group(1)
    _legacy_pyscf__require('basis = cc-pVDZ' in log, 'native output does not identify cc-pVDZ')
    _legacy_pyscf__require('CAS (1e+1e, 2o)' in log, 'native output does not identify CAS(2,2)')
    _legacy_pyscf__require('State-average over 3 states with weights [0.3333333333333333, 0.3333333333333333, 0.3333333333333333]' in log, 'native output does not establish equal-weight SA(3)')
    _legacy_pyscf__require('[INPUT] num. atoms = 6' in log and '[INPUT] num. electrons = 16' in log, 'native atom/electron count is not six-atom C2H4')
    _legacy_pyscf__require('[INPUT] charge = 0' in log and '[INPUT] spin (= nelec alpha-beta = 2S) = 0' in log, 'native molecular charge/spin records missing')
    (ref_symbols, ref_coords) = _legacy_pyscf__read_xyz(expected_geometry)
    native_coords = []
    native_symbols = []
    for line in log.splitlines():
        match = _legacy_pyscf_re.match('^\\[INPUT\\]\\s+(\\d+)\\s+([A-Z][a-z]?)\\s+([-+0-9.]+)\\s+([-+0-9.]+)\\s+([-+0-9.]+)\\s+AA\\b', line)
        if match:
            native_symbols.append(match.group(2))
            native_coords.append([float(match.group(i)) for i in (3, 4, 5)])
    native_coords = _legacy_pyscf_np.asarray(native_coords, dtype=float)
    _legacy_pyscf__require(native_symbols == ref_symbols and native_coords.shape == ref_coords.shape, 'native geometry atom order/count disagrees with public XYZ')
    _legacy_pyscf__require(float(_legacy_pyscf_np.max(_legacy_pyscf_np.abs(native_coords - ref_coords))) <= 5e-12, 'native log coordinates disagree with public XYZ')
    _legacy_pyscf__require('converged SCF energy =' in log, 'native RHF convergence record missing')
    _legacy_pyscf__require('1-step CASSCF converged in' in log, 'native CASSCF convergence record missing')
    _legacy_pyscf__require(log.count('Lagrange multiplier determination converged after') == 4, 'native gradient/NAC response convergence records incomplete')
    _legacy_pyscf__require('CASE05 COMPLETE' in log, 'execution did not reach normal completion')
    energy_sections = _legacy_pyscf_re.findall('CASCI energy for each state\\n((?:\\s+State \\d+ weight .*\\n){3})', log)
    _legacy_pyscf__require(bool(energy_sections), 'native final state energies missing')
    state_rows = _legacy_pyscf_re.findall('State (\\d+) weight ([0-9.]+)\\s+E = ([-+0-9.eE]+) S\\^2 = ([-+0-9.eE]+)', energy_sections[-1])
    _legacy_pyscf__require([int(row[0]) for row in state_rows] == [0, 1, 2], 'native roots are not S0/S1/S2 ordered')
    _legacy_pyscf__require(all((abs(float(row[1]) - 1 / 3) < 1e-06 and abs(float(row[3])) < 1e-07 for row in state_rows)), 'native roots are not three equal-weight singlets')
    energies = _legacy_pyscf_np.asarray([float(row[2]) for row in state_rows])
    _legacy_pyscf__require(bool(_legacy_pyscf_np.all(_legacy_pyscf_np.diff(energies) > 0)), 'native state energies not ordered')
    blocks = _legacy_pyscf__gradient_blocks(log)
    _legacy_pyscf__require(len(blocks) == 4, f'expected 3 state gradients plus 1 NAC response table, found {len(blocks)}')
    gradients = _legacy_pyscf_np.asarray(blocks[:3])
    gap = float(energies[1] - energies[0])
    _legacy_pyscf__require(gap > 0, 'S1-S0 energy gap must be positive')
    nac = blocks[3] / gap
    _legacy_pyscf__require(bool(_legacy_pyscf_np.isfinite(gradients).all() and _legacy_pyscf_np.isfinite(nac).all()), 'native response arrays nonfinite')
    printed_gradients = [_legacy_pyscf__vec_from_marker(log, f'CASE05 gradient state {i}:', f'gradient {i}') for i in range(3)]
    printed_nac = _legacy_pyscf__vec_from_marker(log, 'CASE05 full derivative coupling states 0/1:', 'NAC01')
    _legacy_pyscf__require(all((_legacy_pyscf_np.max(_legacy_pyscf_np.abs(printed_gradients[i] - gradients[i])) < 2e-08 for i in range(3))), 'script gradient arrays disagree with native PySCF gradient tables')
    _legacy_pyscf__require(float(_legacy_pyscf_np.max(_legacy_pyscf_np.abs(printed_nac - nac))) < 2e-07, 'script NAC array disagrees with native PySCF energy-weighted NAC response')
    executed_sha = _legacy_pyscf_hashlib.sha256(executed_script.read_bytes()).hexdigest()
    if executed_sha == _legacy_pyscf_PINNED_SEEDED_RUN_POINT_SHA256:
        _legacy_pyscf__require(point == 'A' and initial_seed is not None and initial_seed.is_file(), 'seeded calculation is allowed only for A and must retain its orbital seed')
        seed_sha = _legacy_pyscf_hashlib.sha256(initial_seed.read_bytes()).hexdigest()
        seed_markers = _legacy_pyscf_re.findall('^CASE05 INITIAL ORBITAL SEED SHA256:\\s*([0-9a-f]{64})\\s*$', log, _legacy_pyscf_re.M)
        _legacy_pyscf__require(seed_markers == [seed_sha], 'native log does not bind the retained initial-orbital seed')
        projections = _legacy_pyscf_re.findall('^CASE05 initial seeded active pi projections:\\s*(\\[.*\\])\\s*$', log, _legacy_pyscf_re.M)
        _legacy_pyscf__require(len(projections) == 1, 'seeded active-orbital projection record missing')
        try:
            seed_projection = _legacy_pyscf_np.asarray(_legacy_pyscf_json.loads(projections[0]), dtype=float)
        except (_legacy_pyscf_json.JSONDecodeError, ValueError) as exc:
            raise _legacy_pyscf_NativeOutputError('invalid seeded active-orbital projection record') from exc
        _legacy_pyscf__require(seed_projection.shape == (2,) and _legacy_pyscf_np.isfinite(seed_projection).all() and (float(_legacy_pyscf_np.min(seed_projection)) >= 0.9), 'seeded active orbitals fail the prespecified strong pi-character threshold')
        final_projection = _legacy_pyscf_re.findall('^CASE05 final active orbital pi projections:\\s*(\\[.*\\])\\s*$', log, _legacy_pyscf_re.M)
        _legacy_pyscf__require(len(final_projection) == 1, 'final active-orbital projection record missing')
        try:
            final_projection_values = _legacy_pyscf_np.asarray(_legacy_pyscf_json.loads(final_projection[0]), dtype=float)
        except (_legacy_pyscf_json.JSONDecodeError, ValueError) as exc:
            raise _legacy_pyscf_NativeOutputError('invalid final active-orbital projection record') from exc
        _legacy_pyscf__require(final_projection_values.shape == (2,) and _legacy_pyscf_np.isfinite(final_projection_values).all() and (float(_legacy_pyscf_np.min(final_projection_values)) >= 0.9), 'seeded final active orbitals fail the prespecified strong pi-character threshold')
    else:
        _legacy_pyscf__require(executed_sha == _legacy_pyscf_PINNED_RUN_POINT_SHA256, 'executed script differs from a pinned PySCF 2.14.0 case script')
        _legacy_pyscf__require(initial_seed is None, 'unseeded calculation unexpectedly contains an orbital seed')
    _legacy_pyscf__require(point in ('A', 'B'), 'unknown geometry point')
    return {'point': point, 'program': f'PySCF {native_version}', 'version': native_version, 'basis': 'cc-pVDZ', 'active_space': [2, 2], 'spin': 0, 'weights': [1 / 3] * 3, 'geometry_sha256': geometry_sha, 'energy_hartree': energies.tolist(), 'gradients_hartree_per_bohr': gradients.tolist(), 'force_norms_hartree_per_bohr': _legacy_pyscf_np.linalg.norm(gradients, axis=(1, 2)).tolist(), 'nac01_per_bohr': nac.tolist(), 'nac01_norm_per_bohr': float(_legacy_pyscf_np.linalg.norm(nac)), 'nac_response_native_energy_gap_hartree': gap, 'native_gradient_table_count': len(blocks), 'response_convergence_records': 4, 'execution_attestation': 'not supplied by native program.log; requires trusted runner receipt', 'executed_script_sha256': executed_sha, 'initial_orbital_seed_sha256': _legacy_pyscf_hashlib.sha256(initial_seed.read_bytes()).hexdigest() if initial_seed is not None else None}

def _legacy_pyscf_main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('log', type=_legacy_pyscf_Path)
    parser.add_argument('point', choices=('A', 'B'))
    parser.add_argument('geometry', type=_legacy_pyscf_Path)
    parser.add_argument('--executed-script', type=_legacy_pyscf_Path, required=True)
    args = parser.parse_args()
    result = _legacy_pyscf_parse_native_log(args.log, args.point, args.geometry, args.executed_script)
    print(_legacy_pyscf_json.dumps(result, indent=2))


# Static OpenMolcas parser surface used by the legacy verifier. The parser code above is part of this file.
from types import SimpleNamespace as _SimpleNamespace
_LEGACY_OPENMOLCAS_MODULE = _SimpleNamespace(
    __file__=__file__, __name__="parse_openmolcas",
    OPENMOLCAS_SOURCE_SHA256=_legacy_openmolcas_OPENMOLCAS_SOURCE_SHA256,
    LIBXC_SOURCE_SHA256=_legacy_openmolcas_LIBXC_SOURCE_SHA256,
    WIGNERNJ_SOURCE_SHA256=_legacy_openmolcas_WIGNERNJ_SOURCE_SHA256,
    Unsupported=_legacy_openmolcas_Unsupported,
    ScientificFailure=_legacy_openmolcas_ScientificFailure,
    sha_manifest=_legacy_openmolcas_sha_manifest,
    parse_accounting=_legacy_openmolcas_parse_accounting,
    slurm_script_time_limit=_legacy_openmolcas_slurm_script_time_limit,
    verify_input=_legacy_openmolcas_verify_input,
    parse_point_native=_legacy_openmolcas_parse_point_native,
)

import csv as _v2_csv
from dataclasses import dataclass as _v2_dataclass
import hashlib as _v2_hashlib
import io as _v2_io
import json as _v2_json
import math as _v2_math
import os as _v2_os
from pathlib import Path as _v2_Path, PurePosixPath as _v2_PurePosixPath
import re as _v2_re
import stat as _v2_stat
import sys as _v2_sys
import types as _v2_types
from typing import Any as _v2_Any, Mapping as _v2_Mapping
_v2_RESULT_SCHEMA = 'case05/pure-scoring-reader-result/v1'
_v2_STANDARD_RESULT_SCHEMA = 'case05/standard-runtime-scoring-reader-result/v1'
_v2_PLAN_SCHEMA = 'case05/native-plan/v2'
_v2_CONSUMPTION_SCHEMA = 'case05/dispatch-consumption/v1'
_v2_EVENT_SCHEMA = 'case05/dispatch-ledger-event/v1'
_v2_STATUS_SCHEMA = 'case05/pyscf-point-exit/v1'
_v2_OPENMOLCAS_STATUS_SCHEMA = 'case05/openmolcas-point-exit/v1'
_v2_METHOD_ID = 'SA3CAS22ccpVDZ'
_v2_PROGRAM_ID = 'pyscf-2.14.0'
_v2_PROGRAM_LABEL = 'PySCF 2.14.0'
_v2_PROGRAM_ID_RE = re.compile(r'^(?:pyscf|openmolcas)-v?[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?$')
_v2_OPENMOLCAS_PROGRAM_ID = 'openmolcas-v26.06'
_v2_OPENMOLCAS_PROGRAM_LABEL = 'OpenMolcas v26.06'
_v2_CASE_TASK_CONFIG_SHA256 = '39d964735bcc99ea0742ebc83ad4975f36c7c6d5784c6586b4a17177c22890ec'
_v2_CASE_RAW_INSTRUCTION_SHA256 = '8bc8107bb7890793cb39bf2b8deff41d11fc64ec56a47a51e807b626a6c6ff99'
_v2_CASE_EFFECTIVE_INSTRUCTION_SHA256 = '8bc8107bb7890793cb39bf2b8deff41d11fc64ec56a47a51e807b626a6c6ff99'
_v2_CASE_TEST_SH_SHA256 = '81b4e2a0fc7e2006fa7667c5748039364ee7060d33fb83503fc1f688fb06611a'
_v2_CASE_LEGACY_VERIFIER_SHA256 = 'c4c0194846d48153099d1a780034f8ca87f5af889762030c635f56f0cd08c596'
_v2_RUNTIME_IMAGE_ID_ENV = 'CCB_CASE05_RUNTIME_IMAGE_ID'
_v2_PINNED_READER_SHA256 = 'ef9596eba6c08c807277bce0c5d0f9baebee3f1b1fd90eb6723a33269c61c61d'
_v2_PINNED_OPENMOLCAS_MODULE_SHA256 = {'code/parse_openmolcas_v2.py': 'ab94cca927ec75216abcfe201c0bc8ac86bd61f18acfb893b91dda0287c5be1f', 'code/case25_case05_openmolcas_adapter.py': 'b7dd866ff677962e94c6053eb5f1d53a2f8367733ec3182f182241ce2dfe10c4', 'code/case25_case05_openmolcas_ao_provider.py': 'b25fdcfad996ca44f4663f8a28d5bfa53e22d099a30b19702a9b56b35ea09578', 'code/case25_case05_science_protocol.py': '693426041f40a522b6a2f07cecdfb1f0d23a12e541030de380c9699aa83b03ff'}
_v2_PINNED_OPENMOLCAS_STANDARD_BOOTSTRAP_SHA256 = 'a5ad3d4e8d672ba173f77f4e92d519ccd0f930f3c92361b00122c208f5608ed8'
_v2_PINNED_OPENMOLCAS_RUNTIME_CLOSURE_SHA256 = {'case25_case05_openmolcas_v2_launcher.py': '25d572373753226076c3e6a1d47a15d6a79bc842304cea5b024a0cf4a9d19958', 'case25_case05_openmolcas_point_v2.py': '50a42451e5e62b351672024bd906b33961e560d2ebd82628c447668e83c4baaf', 'case25_case05_openmolcas_native_parser_v2.py': 'ab94cca927ec75216abcfe201c0bc8ac86bd61f18acfb893b91dda0287c5be1f', 'case25_case05_openmolcas_ao_provider.py': 'b25fdcfad996ca44f4663f8a28d5bfa53e22d099a30b19702a9b56b35ea09578', 'case25_case05_openmolcas_adapter.py': 'b7dd866ff677962e94c6053eb5f1d53a2f8367733ec3182f182241ce2dfe10c4', 'case25_case05_science_protocol.py': '693426041f40a522b6a2f07cecdfb1f0d23a12e541030de380c9699aa83b03ff'}
_v2_PINNED_OPENMOLCAS_STANDARD_MODULE_SHA256 = {**_v2_PINNED_OPENMOLCAS_MODULE_SHA256, 'code/case25_case05_openmolcas_ao_provider.py': 'f5da919956185533ad57b4ff87b30a3df772d92577d54f2ba21bea1914801af3', 'code/case25_case05_science_protocol.py': '4d3a8373a2c08c43405565a7a5d046ad22d439346ac6b056f50cd6f66e97c66e'}
_v2_PINNED_OPENMOLCAS_STANDARD_RUNTIME_CLOSURE_SHA256 = {**_v2_PINNED_OPENMOLCAS_RUNTIME_CLOSURE_SHA256, 'case25_case05_openmolcas_ao_provider.py': 'f5da919956185533ad57b4ff87b30a3df772d92577d54f2ba21bea1914801af3', 'case25_case05_science_protocol.py': '4d3a8373a2c08c43405565a7a5d046ad22d439346ac6b056f50cd6f66e97c66e', 'case25_case05_openmolcas_point_v2.py': '40cf549bf03acf0d7eba95b3cc5f41858165c4ad38c6624d0c08b8e7502023c8'}
_v2_PINNED_OPENMOLCAS_STANDARD_EXPORTER_SOURCE_SHA256 = 'a213669db0856236539f50fb2a0562f562f1598ffae6c23e71d209ce099f305a'
_v2_PINNED_OPENMOLCAS_EXPORTER_SOURCE_SHA256 = 'e910a9b6f0c101c0ee42c4f56c9f0e5767390422e2a123ec6b16cdb58df17e90'
_v2_PINNED_OPENMOLCAS_EXPORTER_WRAPPER_SHA256 = '296b42b3e49bd3e6cfd96b1a62a2a286f4e89cba3ca368c2a76ee80a63241d63'
_v2_PINNED_OPENMOLCAS_EXPORTER_BINARY_SHA256 = '4ea5db96c66f38b5dfdd90ed4323f7798fbd7f8699c3fc7e668730c18fab62fb'
_v2_PINNED_OPENMOLCAS_BINARY_SHA256 = 'eae30a6f23b7444fbac1b6ea2e1a44e986206a086837cb997ce7d10b1dd57712'
_v2_OPENMOLCAS_BOHR_PER_ANGSTROM = 1.8897261254578281
_v2_REFERENCE_SHA256 = 'f37ff75ef151f77bcef451e7fe6540c66bcdb77bdd3c7089604554e0e457ddc4'
_v2_HARTREE_TO_EV = 27.211386245988
_v2_ENERGY_TOL_HARTREE = 0.002
_v2_FORCE_REL_TOL = 0.05
_v2_NAC_REL_TOL = 0.35
_v2_CSV_NATIVE_TOL = 5e-08
_v2__SHA_RE = _v2_re.compile('^[0-9a-f]{64}$')
_v2__ID_RE = _v2_re.compile('^[0-9a-f]{32}$')
_v2_PROOF_ROOT = _v2_Path('/trusted/case05-v2-scoring')
_v2_READER_SOURCE = _v2_Path('/scoring-code/case25_case05_scoring_reader.py')
_v2_PUBLIC_GEOMETRY_ROOT = _v2_Path('/app/inputs/geometries')
_v2_READER_MODULE_LIMIT = 2 * 1024 * 1024

class _v2_ScorerEnvironmentError(RuntimeError):
    """Reader material, trusted source, capture, or native result is unusable."""

class _v2_CandidateFailure(RuntimeError):
    """Candidate files or a well-formed calculation fail the frozen task."""

@_v2_dataclass(frozen=True)
class _v2_V2Decision:
    """Data-only outcome. It is not a runner verdict or reward authorization."""
    status: str
    message: str
    point_results: _v2_Mapping[str, _v2_Mapping[str, _v2_Any]] | None = None

def _v2__sha(raw: bytes) -> str:
    return _v2_hashlib.sha256(raw).hexdigest()

def _v2__canonical(value: _v2_Any) -> bytes:
    try:
        return _v2_json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError) as exc:
        raise _v2_ScorerEnvironmentError('trusted reader value is not canonical JSON') from exc

def _v2__strict_json(raw: bytes, label: str, *, candidate: bool=False) -> _v2_Any:

    def pairs(items):
        result = {}
        for (key, value) in items:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    try:
        return _v2_json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
    except (UnicodeError, _v2_json.JSONDecodeError, ValueError, RecursionError) as exc:
        error = _v2_CandidateFailure if candidate else _v2_ScorerEnvironmentError
        raise error(f'{label} is not strict UTF-8 JSON') from exc

def _v2__exact(value: _v2_Any, keys: set[str], label: str, *, env: bool=True) -> dict[str, _v2_Any]:
    error = _v2_ScorerEnvironmentError if env else _v2_CandidateFailure
    if not isinstance(value, dict) or set(value) != keys:
        raise error(f'{label} has missing or unknown fields')
    return value

def _v2__digest(value: _v2_Any, label: str) -> str:
    if not isinstance(value, str) or _v2__SHA_RE.fullmatch(value) is None:
        raise _v2_ScorerEnvironmentError(f'{label} is not a lowercase SHA-256 digest')
    return value

def _v2__required_module(parser_bytes: bytes) -> _v2_Any:
    if not isinstance(parser_bytes, bytes) or not parser_bytes or len(parser_bytes) > 2 * 1024 * 1024:
        raise _v2_ScorerEnvironmentError('pinned PySCF v2 parser bytes are missing or oversized')
    module = _v2_types.ModuleType('case05_pinned_parse_pyscf_v2')
    try:
        exec(compile(parser_bytes, '<pinned-case05-parser>', 'exec'), module.__dict__)
    except Exception as exc:
        raise _v2_ScorerEnvironmentError(f'pinned PySCF v2 parser is unavailable: {exc}') from exc
    return module

def _v2__required_openmolcas_modules(code: _v2_Any, *, standard_runtime: bool=False) -> tuple[tuple[_v2_Any, _v2_Any, _v2_Any, _v2_Any], dict[str, _v2_Any]]:
    """Load the exact approved OpenMolcas source closure without workspace imports."""
    if not isinstance(code, dict):
        raise _v2_ScorerEnvironmentError('OpenMolcas source closure is malformed')
    parser_path = 'code/case25_case05_openmolcas_native_parser_v2.py' if standard_runtime else 'code/parse_openmolcas_v2.py'
    module_pins = _v2_PINNED_OPENMOLCAS_STANDARD_MODULE_SHA256 if standard_runtime else _v2_PINNED_OPENMOLCAS_MODULE_SHA256
    expected_parser_sha = module_pins['code/parse_openmolcas_v2.py']
    paths = (parser_path, 'code/case25_case05_openmolcas_adapter.py', 'code/case25_case05_openmolcas_ao_provider.py', 'code/case25_case05_science_protocol.py')
    expected_hashes = dict(module_pins)
    if standard_runtime:
        expected_hashes.pop('code/parse_openmolcas_v2.py', None)
        expected_hashes[parser_path] = expected_parser_sha
    modules = {parser_path: 'compchembench.case25_case05_openmolcas_native_parser_v2', 'code/case25_case05_openmolcas_adapter.py': 'compchembench.case25_case05_openmolcas_adapter', 'code/case25_case05_openmolcas_ao_provider.py': 'compchembench.case25_case05_openmolcas_ao_provider', 'code/case25_case05_science_protocol.py': 'compchembench.case25_case05_science_protocol'}
    raw_by_path: dict[str, bytes] = {}
    for path in paths:
        raw = code.get(path)
        if not isinstance(raw, bytes) or not raw or len(raw) > _v2_READER_MODULE_LIMIT or (_v2__sha(raw) != expected_hashes[path]):
            raise _v2_ScorerEnvironmentError(f'approved OpenMolcas module is missing or changed: {path}')
        raw_by_path[path] = raw
    package_names = {'compchembench', *modules.values()}
    saved = {name: _v2_sys.modules.get(name) for name in package_names}
    try:
        for name in package_names:
            _v2_sys.modules.pop(name, None)
        package = _v2_types.ModuleType('compchembench')
        package.__path__ = []
        package.__package__ = 'compchembench'
        _v2_sys.modules['compchembench'] = package
        loaded: dict[str, _v2_Any] = {}
        by_path = {module_path: module_name for (module_path, module_name) in modules.items()}
        for path in ('code/case25_case05_science_protocol.py', 'code/case25_case05_openmolcas_adapter.py', 'code/case25_case05_openmolcas_ao_provider.py', parser_path):
            name = by_path[path]
            module = _v2_types.ModuleType(name)
            module.__file__ = f'<{path}>'
            module.__package__ = 'compchembench'
            _v2_sys.modules[name] = module
            try:
                exec(compile(raw_by_path[path], f'<{path}>', 'exec'), module.__dict__)
            except Exception as exc:
                raise _v2_ScorerEnvironmentError(f'approved OpenMolcas module cannot be loaded: {path}') from exc
            setattr(package, name.rsplit('.', 1)[-1], module)
            loaded[path] = module
        return ((loaded[parser_path], loaded['code/case25_case05_openmolcas_adapter.py'], loaded['code/case25_case05_openmolcas_ao_provider.py'], loaded['code/case25_case05_science_protocol.py']), saved)
    except Exception:
        for name in package_names:
            _v2_sys.modules.pop(name, None)
        for (name, previous) in saved.items():
            if previous is not None:
                _v2_sys.modules[name] = previous
        raise

def _v2__restore_openmolcas_modules(saved: dict[str, _v2_Any]) -> None:
    """Restore host modules after an OpenMolcas validation call."""
    names = set(saved)
    for name in names:
        _v2_sys.modules.pop(name, None)
    for (name, previous) in saved.items():
        if previous is not None:
            _v2_sys.modules[name] = previous

def _v2__read_local_regular(path: _v2_Path, *, limit: int) -> bytes:
    """Read a local code file through a no-follow directory-FD chain."""
    path = path if path.is_absolute() else _v2_Path.cwd() / path
    parts = path.parts
    if len(parts) < 2 or parts[0] != _v2_os.sep or any((part in {'', '.', '..'} for part in parts[1:])):
        raise _v2_ScorerEnvironmentError('local trusted code path is not canonical absolute path')
    directory_flags = _v2_os.O_RDONLY | getattr(_v2_os, 'O_DIRECTORY', 0) | getattr(_v2_os, 'O_NOFOLLOW', 0)
    leaf_flags = _v2_os.O_RDONLY | getattr(_v2_os, 'O_NOFOLLOW', 0) | getattr(_v2_os, 'O_NONBLOCK', 0)
    opened_dirs: list[int] = []
    fd = None
    try:
        current_fd = _v2_os.open(_v2_os.sep, directory_flags)
        opened_dirs.append(current_fd)
        for part in parts[1:-1]:
            current_fd = _v2_os.open(part, directory_flags, dir_fd=current_fd)
            opened_dirs.append(current_fd)
        fd = _v2_os.open(parts[-1], leaf_flags, dir_fd=current_fd)
        before = _v2_os.fstat(fd)
        if not _v2_stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise _v2_ScorerEnvironmentError('local trusted code is not a bounded regular file')
        chunks = []
        total = 0
        while True:
            chunk = _v2_os.read(fd, min(65536, limit + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise _v2_ScorerEnvironmentError('local trusted code exceeded its byte limit')
            chunks.append(chunk)
        after = _v2_os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or total != before.st_size:
            raise _v2_ScorerEnvironmentError('local trusted code changed while being read')
        return b''.join(chunks)
    except OSError as exc:
        raise _v2_ScorerEnvironmentError('local trusted code cannot be read safely') from exc
    finally:
        if fd is not None:
            try:
                _v2_os.close(fd)
            except OSError:
                pass
        for directory_fd in reversed(opened_dirs):
            try:
                _v2_os.close(directory_fd)
            except OSError:
                pass

def _v2__expected_source_modules(reader_result: dict[str, _v2_Any]) -> None:
    release = reader_result['source_release']
    pins = release['module_pins']
    code = reader_result['code']
    program_id = reader_result.get('identity', {}).get('program_id')
    if isinstance(program_id, str) and program_id.startswith('pyscf-'):
        role_paths = {'stdlib-reader': ('code/case25_case05_scoring_reader.py',), 'numpy-parser': ('code/parse_pyscf_v2.py',), 'scientific-scorer': ('code/verify_v2.py',)}
    elif program_id == _v2_OPENMOLCAS_PROGRAM_ID:
        standard_runtime = reader_result.get('schema') == _v2_STANDARD_RESULT_SCHEMA
        module_pins = _v2_PINNED_OPENMOLCAS_STANDARD_MODULE_SHA256 if standard_runtime else _v2_PINNED_OPENMOLCAS_MODULE_SHA256
        role_paths = {'stdlib-reader': ('code/case25_case05_scoring_reader.py',), 'numpy-parser': tuple(module_pins), 'scientific-scorer': ('code/verify_v2.py',)}
    else:
        raise _v2_ScorerEnvironmentError('source release names an unsupported Case05 program')
    if not isinstance(pins, list) or not isinstance(code, dict):
        raise _v2_ScorerEnvironmentError('source release module closure is malformed')
    expected = {(role, path) for (role, paths) in role_paths.items() for path in paths}
    rows = {}
    for row in pins:
        row = _v2__exact(row, {'role', 'path', 'bytes', 'sha256'}, 'module pin')
        role = row['role']
        key = (role, row['path'])
        if key not in expected or key in rows:
            raise _v2_ScorerEnvironmentError('source release module roles/paths are not the pinned closure')
        _v2__digest(row['sha256'], f'module {role} digest')
        if type(row['bytes']) is not int or row['bytes'] < 0:
            raise _v2_ScorerEnvironmentError(f'module {role} byte count is invalid')
        raw = code.get(row['path'])
        if not isinstance(raw, bytes) or len(raw) != row['bytes'] or _v2__sha(raw) != row['sha256']:
            raise _v2_ScorerEnvironmentError(f'source release module bytes differ: {role}')
        rows[key] = row
    if set(rows) != expected:
        raise _v2_ScorerEnvironmentError('source release module closure is incomplete')
    expected_hashes = {('stdlib-reader', 'code/case25_case05_scoring_reader.py'): _v2_PINNED_READER_SHA256}
    if isinstance(program_id, str) and program_id.startswith('pyscf-'):
        expected_hashes['numpy-parser', 'code/parse_pyscf_v2.py'] = '60d1ecb8003a2495e8ee2c276b33c034ca9ab43ff1ef6e01e9514f6ec868f489'
    else:
        expected_hashes.update({('numpy-parser', path): digest for (path, digest) in module_pins.items()})
    for (key, digest) in expected_hashes.items():
        if rows[key]['sha256'] != digest:
            raise _v2_ScorerEnvironmentError(f'pinned source digest changed for {key[0]}:{key[1]}')
    local_scorer = _v2__read_local_regular(_v2_Path(__file__), limit=2 * 1024 * 1024)
    scorer_row = rows['scientific-scorer', 'code/verify_v2.py']
    if _v2__sha(local_scorer) != scorer_row['sha256'] or len(local_scorer) != scorer_row['bytes']:
        raise _v2_ScorerEnvironmentError('staged scorer source differs from the running verifier')

def _v2__validate_context(reader_result: _v2_Any, *, expected_context_sha256: str, expected_image_id: _v2_Any) -> dict[str, _v2_Any]:
    keys = {'schema', 'identity', 'source_release', 'joins', 'runner_context', 'consumption_proof', 'completed_execution_receipt', 'capture_receipt', 'captured_binding', 'native_plan', 'artifacts', 'evidence', 'code'}
    result = _v2__exact(reader_result, keys, 'pure scoring reader result')
    if result['schema'] != _v2_RESULT_SCHEMA:
        raise _v2_ScorerEnvironmentError('unsupported pure scoring reader result schema')
    _v2__digest(expected_context_sha256, 'externally selected runner-context hash')
    identity = result['identity']
    identity_keys = {'case_path', 'program_id', 'profile_id', 'operation', 'attempt_id', 'run_id', 'request_id', 'challenge_nonce', 'runner_nonce_sha256'}
    identity = _v2__exact(identity, identity_keys, 'trusted execution identity')
    if not isinstance(identity['program_id'], str) or _v2_PROGRAM_ID_RE.fullmatch(identity['program_id']) is None or identity['operation'] != 'run-points' or (not isinstance(identity['case_path'], str)) or (not (identity['case_path'].endswith('/25_spainn-nonadiabatic-dynamics/task 166') or identity['case_path'].endswith('/25_spainn-nonadiabatic-dynamics/case-05') or identity['case_path'] in {'/bench/task 166', '/bench/case-05'})) or (not isinstance(identity['profile_id'], str)) or (not identity['profile_id']) or (not isinstance(identity['run_id'], str)) or (not identity['run_id']):
        raise _v2_ScorerEnvironmentError('trusted execution identity is outside the fixed Case05 v2 route')
    for name in ('attempt_id', 'request_id', 'challenge_nonce'):
        if not isinstance(identity[name], str) or _v2__ID_RE.fullmatch(identity[name]) is None:
            raise _v2_ScorerEnvironmentError(f'trusted {name} is malformed')
    if len({identity['attempt_id'], identity['request_id'], identity['challenge_nonce']}) != 3:
        raise _v2_ScorerEnvironmentError('trusted attempt, request, and challenge identifiers are not distinct')
    _v2__digest(identity['runner_nonce_sha256'], 'runner nonce digest')
    pins = result['source_release']
    _v2__exact(pins, {'schema', 'case_pins', 'host_source_pins', 'module_pins'}, 'source release')
    case_pins = _v2__exact(pins['case_pins'], {'case_path', 'task_config_sha256', 'instruction_sha256', 'effective_instruction_sha256', 'test_sh_sha256', 'verifier_sha256'}, 'case source pins')
    expected_case_pins = {'task_config_sha256': _v2_CASE_TASK_CONFIG_SHA256, 'instruction_sha256': _v2_CASE_RAW_INSTRUCTION_SHA256, 'effective_instruction_sha256': _v2_CASE_EFFECTIVE_INSTRUCTION_SHA256, 'test_sh_sha256': _v2_CASE_TEST_SH_SHA256, 'verifier_sha256': _v2__sha(_v2_Path(__file__).read_bytes())}
    if pins['schema'] != 'case05/source-release/v1' or case_pins['case_path'] != identity['case_path']:
        raise _v2_ScorerEnvironmentError('source release is not bound to this Case05 path')
    if any((case_pins.get(key) != value for (key, value) in expected_case_pins.items())):
        raise _v2_ScorerEnvironmentError('source release task, prompt, image-verifier, or test pin differs')
    host_pins = pins['host_source_pins']
    if not isinstance(host_pins, dict) or not host_pins:
        raise _v2_ScorerEnvironmentError('host source pins are absent')
    for (role, digest) in host_pins.items():
        if not isinstance(role, str) or not role:
            raise _v2_ScorerEnvironmentError('host source pin role is invalid')
        _v2__digest(digest, f'host source pin {role}')
    _v2__expected_source_modules(result)
    joins = result['joins']
    join_keys = {'consumption_id', 'consumption_event_sha256', 'before_ledger_sha256', 'after_ledger_sha256', 'current_ledger_sha256', 'permit_receipt_sha256', 'execution_binding_sha256', 'captured_stage_binding_sha256', 'native_plan_sha256', 'renderer_approval_sha256', 'rendered_upload_manifest_sha256', 'capture_receipt_sha256', 'completed_execution_receipt_sha256', 'final_context_sha256', 'final_artifact_manifest_sha256'}
    joins = _v2__exact(joins, join_keys, 'trust joins')
    if not isinstance(joins['consumption_id'], str) or not joins['consumption_id']:
        raise _v2_ScorerEnvironmentError('consumption ID is absent')
    for (key, value) in joins.items():
        if key != 'consumption_id':
            _v2__digest(value, f'join {key}')
    context = result['runner_context']
    if not isinstance(context, dict):
        raise _v2_ScorerEnvironmentError('runner context is malformed')
    actual_image_id = _v2_validate_runner_image_id(context.get('image_id'), expected_image_id)
    if context.get('task_id') != 'case-05' or context.get('attempt_id') != identity['attempt_id'] or context.get('run_id') != identity['run_id'] or (context.get('task_config_sha256') != _v2_CASE_TASK_CONFIG_SHA256) or (context.get('instruction_sha256') != _v2_CASE_EFFECTIVE_INSTRUCTION_SHA256) or (joins['final_context_sha256'] != expected_context_sha256):
        raise _v2_ScorerEnvironmentError('runner context does not match the frozen Case05 attempt/task')
    nonce = context.get('nonce')
    if not isinstance(nonce, str) or _v2__sha(nonce.encode('utf-8')) != identity['runner_nonce_sha256']:
        raise _v2_ScorerEnvironmentError('runner context nonce is not joined to execution identity')
    manifest = context.get('artifact_manifest')
    expected_artifacts = [{'source': '/app/outputs', 'destination': 'outputs', 'exclude': ''}]
    if not isinstance(manifest, dict) or set(manifest) != {'declared', 'collected', 'missing'} or manifest.get('declared') != expected_artifacts or (not isinstance(manifest.get('collected'), list)) or (not isinstance(manifest.get('missing'), list)) or (context.get('artifact_manifest_sha256') != _v2__sha(_v2__canonical(manifest))):
        raise _v2_ScorerEnvironmentError('runner context artifact manifest is malformed or unbound')
    return identity

def _v2_validate_runner_image_id(context_image_id: _v2_Any, runtime_image_id: _v2_Any) -> str:
    """Require the sealed proof image to match the host-injected actual ID."""
    if not isinstance(runtime_image_id, str) or _v2_re.fullmatch('sha256:[0-9a-f]{64}', runtime_image_id) is None:
        raise _v2_ScorerEnvironmentError('runner-selected actual image ID is unavailable')
    if context_image_id != runtime_image_id:
        raise _v2_ScorerEnvironmentError('runner context image ID differs from the actual grader image')
    return runtime_image_id

def _v2__validate_execution_joins(result: dict[str, _v2_Any], identity: dict[str, _v2_Any]) -> tuple[dict, dict, dict]:
    joins = result['joins']
    proof = _v2__exact(result['consumption_proof'], {'schema', 'ledger_schema', 'provider_id', 'profile_id', 'current_ledger_sha256', 'current_ledger_generation', 'event', 'event_sha256', 'after_ledger_sha256'}, 'consumption proof')
    if proof['schema'] != 'case05/consumption-proof/v1' or proof['ledger_schema'] != 'case05/dispatch-reservation-ledger/v2' or (not isinstance(proof['provider_id'], str)) or (not proof['provider_id']) or (proof['profile_id'] != identity['profile_id']) or (proof['current_ledger_sha256'] != joins['current_ledger_sha256']) or (type(proof['current_ledger_generation']) is not int) or (proof['after_ledger_sha256'] != joins['after_ledger_sha256']):
        raise _v2_ScorerEnvironmentError('consumption proof does not bind the selected current ledger')
    event = _v2__exact(proof['event'], {'schema', 'event_type', 'generation', 'committed_at_epoch', 'before_ledger_sha256', 'consumption'}, 'consumption event')
    if event['schema'] != 'case05/dispatch-ledger-event/v1' or event['event_type'] != 'CONSUME' or type(event['generation']) is not int or (type(event['committed_at_epoch']) is not int) or (_v2__sha(_v2__canonical(event)) != proof['event_sha256']) or (proof['event_sha256'] != joins['consumption_event_sha256']) or (event['before_ledger_sha256'] != joins['before_ledger_sha256']):
        raise _v2_ScorerEnvironmentError('consumption event hash/generation is inconsistent')
    consumption_keys = {'schema', 'consumption_id', 'reservation_id', 'attempt_id', 'run_id', 'request_id', 'challenge_nonce', 'runner_nonce_sha256', 'capability_receipt_sha256', 'observation_receipt_sha256', 'execution_binding_sha256', 'renderer_approval_sha256', 'rendered_upload_sha256', 'native_plan_sha256', 'program_id', 'operation', 'resources', 'charged_cpu_core_seconds', 'charged_wall_seconds', 'permit_receipt_sha256', 'source_pins', 'resource_policy_sha256', 'permit_expires_at_epoch', 'consumed_at_epoch', 'deadline_expires_monotonic', 'deadline_started_epoch', 'deadline_started_monotonic', 'answer_timeout_seconds', 'readiness_receipt_sha256', 'readiness_provider_code_sha256', 'readiness_provider_policy_sha256', 'readiness_expires_at_epoch'}
    consumption = _v2__exact(event['consumption'], consumption_keys, 'consumed reservation')
    expected_fields = {'schema': 'case05/dispatch-consumption/v1', 'consumption_id': joins['consumption_id'], 'attempt_id': identity['attempt_id'], 'run_id': identity['run_id'], 'request_id': identity['request_id'], 'challenge_nonce': identity['challenge_nonce'], 'runner_nonce_sha256': identity['runner_nonce_sha256'], 'program_id': identity['program_id'], 'operation': identity['operation'], 'execution_binding_sha256': joins['execution_binding_sha256'], 'native_plan_sha256': joins['native_plan_sha256'], 'renderer_approval_sha256': joins['renderer_approval_sha256'], 'rendered_upload_sha256': joins['rendered_upload_manifest_sha256'], 'permit_receipt_sha256': joins['permit_receipt_sha256']}
    if any((consumption.get(key) != value for (key, value) in expected_fields.items())):
        raise _v2_ScorerEnvironmentError('consumed reservation does not bind this attempt and plan')
    completed = _v2__exact(result['completed_execution_receipt'], {'schema', 'provider_id', 'provider_code_sha256', 'provider_policy_sha256', 'identity', 'consumption', 'execution', 'job', 'submission', 'terminal', 'evidence_manifest', 'evidence_manifest_sha256', 'source_release', 'source_release_sha256'}, 'completed execution receipt')
    completed_consumption = _v2__exact(completed['consumption'], {'consumption_id', 'reservation_id', 'event_generation', 'event_sha256', 'before_ledger_sha256', 'after_ledger_sha256', 'permit_receipt_sha256'}, 'completed receipt consumption')
    completed_execution = _v2__exact(completed['execution'], {'execution_binding_sha256', 'native_plan_sha256', 'renderer_approval_sha256', 'rendered_upload_manifest_sha256', 'capture_receipt_sha256', 'final_artifact_manifest_sha256'}, 'completed receipt execution')
    completed_job = _v2__exact(completed['job'], {'job_id', 'owner', 'workdir'}, 'completed receipt job')
    submission = _v2__exact(completed['submission'], {'evidence_kind', 'evidence_path', 'evidence_sha256', 'submitted_at_epoch'}, 'completed receipt submission')
    terminal = _v2__exact(completed['terminal'], {'evidence_path', 'evidence_sha256', 'completed_at_epoch'}, 'completed receipt terminal')
    _v2__digest(completed['provider_code_sha256'], 'completed provider code pin')
    _v2__digest(completed['provider_policy_sha256'], 'completed provider policy pin')
    _v2__digest(completed['evidence_manifest_sha256'], 'completed evidence manifest pin')
    _v2__digest(completed['source_release_sha256'], 'completed source release pin')
    if completed['schema'] != 'case05/completed-execution-join/v1' or completed['identity'] != identity or completed_consumption['consumption_id'] != joins['consumption_id'] or (completed_consumption['event_sha256'] != joins['consumption_event_sha256']) or (completed_consumption['before_ledger_sha256'] != joins['before_ledger_sha256']) or (completed_consumption['after_ledger_sha256'] != joins['after_ledger_sha256']) or (completed_consumption['permit_receipt_sha256'] != joins['permit_receipt_sha256']) or (completed_execution['execution_binding_sha256'] != joins['execution_binding_sha256']) or (completed_execution['native_plan_sha256'] != joins['native_plan_sha256']) or (completed_execution['renderer_approval_sha256'] != joins['renderer_approval_sha256']) or (completed_execution['rendered_upload_manifest_sha256'] != joins['rendered_upload_manifest_sha256']) or (completed_execution['capture_receipt_sha256'] != joins['capture_receipt_sha256']) or (completed_execution['final_artifact_manifest_sha256'] != joins['final_artifact_manifest_sha256']) or (completed_job['job_id'] != result['capture_receipt'].get('job', {}).get('job_id')) or (completed['provider_id'] != result['capture_receipt'].get('provider_id')) or (completed['provider_code_sha256'] != result['capture_receipt'].get('provider_code_sha256')) or (completed['provider_policy_sha256'] != result['capture_receipt'].get('provider_policy_sha256')) or (completed['source_release'] != result['source_release']) or (completed['source_release_sha256'] != _v2__sha(_v2__canonical(result['source_release']))) or (not isinstance(completed['evidence_manifest'], list)) or (not isinstance(submission['evidence_path'], str)) or (not isinstance(terminal['evidence_path'], str)) or (type(submission['submitted_at_epoch']) is not int) or (type(terminal['completed_at_epoch']) is not int) or (terminal['completed_at_epoch'] < submission['submitted_at_epoch']):
        raise _v2_ScorerEnvironmentError('completed receipt is not joined to the consumed attempt/capture')
    capture = result['capture_receipt']
    if not isinstance(capture, dict):
        raise _v2_ScorerEnvironmentError('capture receipt bytes/hash are inconsistent')
    if capture.get('schema') != 'case05/backend-capture-binding/v1' or capture.get('attempt_id') != identity['attempt_id'] or capture.get('request_id') != identity['request_id'] or (capture.get('challenge_nonce') != identity['challenge_nonce']) or (capture.get('program_id') != identity['program_id']) or (capture.get('profile_id') != identity['profile_id']) or (capture.get('execution_binding_sha256') != joins['execution_binding_sha256']) or (capture.get('native_plan_sha256') != joins['native_plan_sha256']) or (capture.get('rendered_upload_manifest_sha256') != joins['rendered_upload_manifest_sha256']) or (capture.get('final_artifact_manifest_sha256') != joins['final_artifact_manifest_sha256']):
        raise _v2_ScorerEnvironmentError('capture receipt identity does not match trusted joins')
    binding = result['captured_binding']
    plan = result['native_plan']
    if not isinstance(binding, dict) or not isinstance(plan, dict):
        raise _v2_ScorerEnvironmentError('captured binding or native plan is not an object')
    if binding.get('attempt_id') != identity['attempt_id'] or binding.get('request_id') != identity['request_id'] or binding.get('challenge_nonce') != identity['challenge_nonce'] or (binding.get('source_execution_binding_sha256') != joins['execution_binding_sha256']) or (not isinstance(joins['captured_stage_binding_sha256'], str)) or (binding.get('native_plan_sha256') != joins['native_plan_sha256']) or (binding.get('capture_receipt_sha256') != joins['capture_receipt_sha256']) or (binding.get('final_capture_artifact_manifest_sha256') != joins['final_artifact_manifest_sha256']) or (plan.get('schema') != _v2_PLAN_SCHEMA) or (plan.get('attempt_id') != identity['attempt_id']) or (plan.get('request_id') != identity['request_id']) or (plan.get('challenge_nonce') != identity['challenge_nonce']) or (plan.get('program_id') != identity['program_id']) or (plan.get('method_id') != _v2_METHOD_ID) or (not isinstance(plan.get('profile'), dict)) or (plan['profile'].get('profile_id') != identity['profile_id']):
        raise _v2_ScorerEnvironmentError('captured binding/native plan identity chain is inconsistent')
    if not isinstance(plan.get('geometry_sha256'), dict) or not isinstance(plan.get('geometry_xyz'), dict) or set(plan['geometry_sha256']) != {'A', 'B'} or (set(plan['geometry_xyz']) != {'A', 'B'}):
        raise _v2_ScorerEnvironmentError('native plan omits fixed A/B geometries')
    return (consumption, capture, plan)

def _v2__fixed_reference() -> tuple[dict[str, _v2_Any], dict[str, float]]:
    path = _v2_Path(__file__).resolve().with_name('refs.json')
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise _v2_ScorerEnvironmentError('frozen reference is unavailable') from exc
    if _v2__sha(raw) != _v2_REFERENCE_SHA256:
        raise _v2_ScorerEnvironmentError('frozen reference hash differs')
    value = _v2__strict_json(raw, 'frozen reference')
    points = value.get('points') if isinstance(value, dict) else None
    tolerances = value.get('tolerances') if isinstance(value, dict) else None
    expected_tolerances = {'energy_hartree': 0.002, 'force_relative': 0.05, 'nac_relative': 0.35, 'csv_native': 5e-08, 'gap_consistency_ev': 0.05}
    if not isinstance(points, dict) or set(points) != {'A', 'B'} or tolerances != expected_tolerances:
        raise _v2_ScorerEnvironmentError('frozen reference schema or tolerances are invalid')
    return (points, tolerances)

def _v2__safe_relative(value: _v2_Any, label: str) -> str:
    if not isinstance(value, str) or not value or '\\' in value:
        raise _v2_ScorerEnvironmentError(f'{label} path is invalid')
    path = _v2_PurePosixPath(value)
    if path.is_absolute() or any((part in {'', '.', '..'} for part in path.parts)):
        raise _v2_ScorerEnvironmentError(f'{label} path is unsafe')
    return path.as_posix()

def _v2__evidence_rows(result: dict[str, _v2_Any], capture: dict[str, _v2_Any], point: str, category: str) -> dict[str, bytes]:
    evidence = result['evidence']
    if not isinstance(evidence, dict):
        raise _v2_ScorerEnvironmentError('reader result evidence map is malformed')
    point_record = capture.get('points', {}).get(point)
    if not isinstance(point_record, dict) or category not in point_record:
        raise _v2_ScorerEnvironmentError(f'capture receipt lacks {point} {category}')
    rows = point_record[category]
    if not isinstance(rows, list):
        raise _v2_ScorerEnvironmentError(f'capture receipt {point} {category} must be a list')
    found: dict[str, bytes] = {}
    point_prefix = f'capture/{point}/'
    for row in rows:
        row = _v2__exact(row, {'path', 'bytes', 'sha256'}, f'{point} {category} file row')
        path = _v2__safe_relative(row['path'], f'{point} {category}')
        if not path.startswith(point_prefix):
            raise _v2_ScorerEnvironmentError(f'captured {point} {category} path is outside its point namespace')
        name = _v2__safe_relative(path[len(point_prefix):], f'{point} {category} relative path')
        raw = evidence.get(path)
        if name in found or not isinstance(raw, bytes) or type(row['bytes']) is not int or (row['bytes'] != len(raw)) or (_v2__sha(raw) != row['sha256']):
            raise _v2_ScorerEnvironmentError(f'captured {point} {category} bytes are invalid')
        found[name] = raw
    return found

def _v2__openmolcas_geometry(data: bytes, point: str, expected_sha: str) -> tuple[list[str], _v2_Any, _v2_Any]:
    try:
        import numpy as np
        lines = data.decode('ascii', 'strict').splitlines()
        if len(lines) != 8 or lines[0].strip() != '6':
            raise ValueError('invalid XYZ frame')
        (symbols, coordinates) = ([], [])
        for line in lines[2:]:
            fields = line.split()
            if len(fields) != 4:
                raise ValueError('invalid XYZ atom row')
            symbols.append(fields[0])
            coordinates.append([float(value) for value in fields[1:]])
        xyz = np.asarray(coordinates, dtype=float)
        if symbols != ['C', 'C', 'H', 'H', 'H', 'H'] or xyz.shape != (6, 3) or (not np.isfinite(xyz).all()) or (_v2__sha(data) != expected_sha) or (not np.array_equal(xyz, np.asarray([[float(value) for value in row.split()[1:]] for row in lines[2:]], dtype=float))):
            raise ValueError('geometry identity or values are invalid')
        return (symbols, xyz, xyz * _v2_OPENMOLCAS_BOHR_PER_ANGSTROM)
    except Exception as exc:
        raise _v2_ScorerEnvironmentError(f'trusted OpenMolcas {point} geometry is malformed') from exc

def _v2__call_openmolcas_ao_provider(provider: _v2_Any, *, result_schema: str, payload_bytes: bytes, scforb_bytes: bytes, expected_input_sha256: _v2_Mapping[str, str], expected_geometry_bohr: _v2_Any, expected_symbols: tuple[str, ...], expected_exporter_sha256: str, expected_stage_binding: _v2_Mapping[str, _v2_Any], expected_exporter_source_sha256: str) -> _v2_Any:
    """Call the schema-matched pinned AO provider without widening legacy API."""
    common = {'scforb_bytes': scforb_bytes, 'expected_input_sha256': expected_input_sha256, 'expected_geometry_bohr': expected_geometry_bohr, 'expected_symbols': expected_symbols, 'expected_exporter_sha256': expected_exporter_sha256, 'expected_stage_binding': expected_stage_binding}
    if result_schema == _v2_STANDARD_RESULT_SCHEMA:
        if expected_exporter_source_sha256 != _v2_PINNED_OPENMOLCAS_STANDARD_EXPORTER_SOURCE_SHA256:
            raise _v2_ScorerEnvironmentError('standard OpenMolcas AO source pin differs from current standard identity')
        return provider.validate_ao_export(payload_bytes, **common, expected_exporter_source_sha256=_v2_PINNED_OPENMOLCAS_STANDARD_EXPORTER_SOURCE_SHA256)
    if result_schema != _v2_RESULT_SCHEMA or expected_exporter_source_sha256 != _v2_PINNED_OPENMOLCAS_EXPORTER_SOURCE_SHA256:
        raise _v2_ScorerEnvironmentError('legacy OpenMolcas AO source pin differs from historical identity')
    return provider.validate_ao_export(payload_bytes, **common)

def _v2__openmolcas_derived_arrays(native: dict[str, _v2_Any], np: _v2_Any) -> dict[str, _v2_Any]:
    """Derive scoring observables only from independently parsed native arrays."""
    try:
        energies = np.asarray(native['energy_hartree'], dtype=float)
        gradients = np.asarray(native['gradients_hartree_per_bohr'], dtype=float)
        nac = np.asarray(native['nac01_per_bohr'], dtype=float)
        if energies.shape != (3,) or gradients.shape != (3, 6, 3) or nac.shape != (6, 3) or (not np.isfinite(energies).all()) or (not np.isfinite(gradients).all()) or (not np.isfinite(nac).all()) or (not np.all(np.diff(energies) > 0)):
            raise ValueError('fixed native array dimensions, finiteness, or root order differ')
        result = dict(native)
        result['force_norms_hartree_per_bohr'] = [float(np.linalg.norm(gradients[index])) for index in range(3)]
        result['nac01_norm_per_bohr'] = float(np.linalg.norm(nac))
        if not all((_v2_math.isfinite(value) for value in [*result['force_norms_hartree_per_bohr'], result['nac01_norm_per_bohr']])):
            raise ValueError('derived norms are nonfinite')
        return result
    except Exception as exc:
        raise _v2_ScorerEnvironmentError('independently parsed OpenMolcas arrays are malformed') from exc

def _v2__om_fixed_plan(plan: _v2_Any, identity: dict[str, _v2_Any], geometries: _v2_Mapping[str, bytes], protocol: _v2_Any, *, standard_context: dict[str, _v2_Any] | None=None) -> dict[str, _v2_Any]:
    if not isinstance(plan, dict) or plan.get('schema') != _v2_PLAN_SCHEMA:
        raise _v2_ScorerEnvironmentError('OpenMolcas native plan schema is invalid')
    if standard_context is None:
        profile = plan.get('profile')
        required_profile_keys = {'profile_id', 'cluster_id', 'ssh_target', 'account', 'partition', 'node', 'qos',
                                 'remote_attempt_root', 'python_executable', 'openmolcas_prefix',
                                 'ao_exporter_path', 'resources', 'profile_sha256'}
        if not isinstance(profile, dict) or set(profile) != required_profile_keys:
            raise _v2_ScorerEnvironmentError('protected legacy OpenMolcas runtime profile is missing or malformed')
        profile_payload = {key: value for key, value in profile.items() if key != 'profile_sha256'}
        profile_sha = _v2__sha(_v2__canonical(profile_payload))
        profile_path_fields = ('remote_attempt_root', 'python_executable', 'openmolcas_prefix', 'ao_exporter_path')
        if (profile.get('profile_id') != identity['profile_id'] or profile.get('profile_sha256') != profile_sha
                or any(not isinstance(profile.get(key), str) or not profile[key].startswith('/')
                       or not _v2_re.fullmatch(r'/[A-Za-z0-9_./-]+', profile[key])
                       or '..' in _v2_Path(profile[key]).parts for key in profile_path_fields)
                or profile.get('remote_attempt_root') in {'/', '.'}
                or not isinstance(profile.get('cluster_id'), str)
                or not _v2_re.fullmatch(r'[A-Za-z0-9_.@-]+', profile['cluster_id'])
                or not isinstance(profile.get('ssh_target'), str)
                or not _v2_re.fullmatch(r'[A-Za-z0-9_.@:-]+', profile['ssh_target'])
                or not isinstance(profile.get('qos'), str)
                or (profile['qos'] and not _v2_re.fullmatch(r'[A-Za-z0-9_.-]+', profile['qos']))):
            raise _v2_ScorerEnvironmentError('protected legacy OpenMolcas runtime profile failed its digest/path checks')
        resources = profile.get('resources')
        if (not isinstance(resources, dict) or set(resources) != {'cpu_cores', 'memory_gb', 'gpu_count',
                'wall_seconds', 'account', 'partition', 'node', 'science_gpu_use'}
                or resources.get('cpu_cores') != 4 or resources.get('memory_gb') != 8
                or resources.get('gpu_count') != 1 or resources.get('wall_seconds') != 1200
                or resources.get('science_gpu_use') is not False
                or resources.get('account') != profile.get('account')
                or resources.get('partition') != profile.get('partition')
                or resources.get('node') != profile.get('node')
                or not isinstance(profile.get('account'), str) or not profile['account']
                or not isinstance(profile.get('partition'), str) or not profile['partition']
                or (profile.get('node') and (not isinstance(profile['node'], str)
                    or not _v2_re.fullmatch(r'[A-Za-z0-9_.-]+', profile['node'])))):
            raise _v2_ScorerEnvironmentError('protected legacy OpenMolcas runtime resource envelope is invalid')
        if (plan.get('program_id') != _v2_OPENMOLCAS_PROGRAM_ID or plan.get('program_version') != _v2_OPENMOLCAS_PROGRAM_LABEL or plan.get('method_id') != _v2_METHOD_ID or (plan.get('attempt_id') != identity['attempt_id']) or (plan.get('request_id') != identity['request_id']) or (plan.get('challenge_nonce') != identity['challenge_nonce']) or (profile.get('profile_id') != identity['profile_id']) or (plan.get('remote_pymolcas') != profile['openmolcas_prefix'].rstrip('/') + '/pymolcas') or (plan.get('remote_ao_exporter') != profile['ao_exporter_path']) or (plan.get('remote_python') != profile['python_executable'])):
            raise _v2_ScorerEnvironmentError('OpenMolcas native plan differs from the trusted attempt or fixed method')
        if plan.get('resources') != resources:
            raise _v2_ScorerEnvironmentError('OpenMolcas native plan resources differ from the protected operator profile')
        expected_closure = dict(_v2_PINNED_OPENMOLCAS_RUNTIME_CLOSURE_SHA256)
        expected_remote_files = None
    else:
        snapshot = standard_context
        profile = snapshot.get('profile') if isinstance(snapshot, dict) else None
        programs = profile.get('programs') if isinstance(profile, dict) else None
        policy = programs.get(_v2_OPENMOLCAS_PROGRAM_ID) if isinstance(programs, dict) else None
        runtime_route = policy.get('runtime') if isinstance(policy, dict) else None
        source_pins = snapshot.get('source_pins') if isinstance(snapshot, dict) else None
        plan_profile = plan.get('profile')
        if not isinstance(runtime_route, dict) or not isinstance(policy, dict) or (not isinstance(source_pins, dict)) or (not isinstance(plan_profile, dict)) or (source_pins.get('openmolcas_bootstrap') != _v2_PINNED_OPENMOLCAS_STANDARD_BOOTSTRAP_SHA256) or (source_pins.get('openmolcas_exporter_source') != _v2_PINNED_OPENMOLCAS_STANDARD_EXPORTER_SOURCE_SHA256) or (plan.get('program_id') != _v2_OPENMOLCAS_PROGRAM_ID) or (plan.get('program_version') != _v2_OPENMOLCAS_PROGRAM_LABEL) or (plan.get('method_id') != _v2_METHOD_ID) or (plan.get('attempt_id') != identity['attempt_id']) or (plan.get('request_id') != identity['request_id']) or (plan.get('challenge_nonce') != identity['challenge_nonce']) or (plan_profile.get('profile_id') != identity['profile_id']) or (plan_profile.get('profile_sha256') != snapshot.get('profile_sha256')) or any((plan_profile.get(key) != value for (key, value) in runtime_route.items())) or (plan.get('remote_python') != runtime_route.get('python_executable')) or (plan.get('remote_pymolcas') != runtime_route.get('openmolcas_prefix', '').rstrip('/') + '/pymolcas') or (plan.get('remote_ao_exporter') != runtime_route.get('ao_exporter_path')) or (runtime_route.get('runtime_bootstrap_id') != 'ikkem-openmolcas-gcc12-mkl2024-v1'):
            raise _v2_ScorerEnvironmentError('OpenMolcas native plan differs from protected standard runtime identity')
        expected_closure = dict(_v2_PINNED_OPENMOLCAS_STANDARD_RUNTIME_CLOSURE_SHA256)
        expected_closure['case25_case05_openmolcas_bootstrap.py'] = _v2_PINNED_OPENMOLCAS_STANDARD_BOOTSTRAP_SHA256
        expected_remote_files = {**{f'runtime/python/compchembench/{name}': digest for (name, digest) in expected_closure.items()}, 'runtime/openmolcas_ao_exporter/ao_export.F90': _v2_PINNED_OPENMOLCAS_STANDARD_EXPORTER_SOURCE_SHA256, 'runtime/openmolcas_ao_exporter/export_json.py': _v2_PINNED_OPENMOLCAS_EXPORTER_WRAPPER_SHA256, runtime_route['ao_exporter_path']: policy['ao_exporter_sha256'], plan.get('remote_pymolcas'): policy['pymolcas_sha256']}
    required_points = ('geometry_sha256', 'geometry_xyz', 'config', 'canonical_inputs', 'raw_config_sha256', 'canonical_config_sha256', 'canonical_input_sha256')
    if any((not isinstance(plan.get(name), dict) or set(plan[name]) != {'A', 'B'} for name in required_points)):
        raise _v2_ScorerEnvironmentError('OpenMolcas native plan point declarations are incomplete')
    source = plan.get('source_pins')
    if not isinstance(source, dict):
        raise _v2_ScorerEnvironmentError('OpenMolcas native source pins are malformed')
    if source.get('python_closure_sha256') != expected_closure:
        raise _v2_ScorerEnvironmentError('OpenMolcas runtime source closure differs from its fixed pins')
    source_fields = {'driver_sha256': expected_closure['case25_case05_openmolcas_point_v2.py'], 'adapter_sha256': expected_closure['case25_case05_openmolcas_adapter.py'], 'provider_sha256': expected_closure['case25_case05_openmolcas_ao_provider.py'], 'parser_sha256': expected_closure['case25_case05_openmolcas_native_parser_v2.py'], 'exporter_source_sha256': _v2_PINNED_OPENMOLCAS_EXPORTER_SOURCE_SHA256 if standard_context is None else _v2_PINNED_OPENMOLCAS_STANDARD_EXPORTER_SOURCE_SHA256, 'exporter_wrapper_sha256': _v2_PINNED_OPENMOLCAS_EXPORTER_WRAPPER_SHA256, 'exporter_binary_sha256': _v2_PINNED_OPENMOLCAS_EXPORTER_BINARY_SHA256 if standard_context is None else standard_context['profile']['programs'][_v2_OPENMOLCAS_PROGRAM_ID]['ao_exporter_sha256'], 'pymolcas_sha256': _v2_PINNED_OPENMOLCAS_BINARY_SHA256 if standard_context is None else standard_context['profile']['programs'][_v2_OPENMOLCAS_PROGRAM_ID]['pymolcas_sha256']}
    for (name, expected) in source_fields.items():
        if source.get(name) != expected:
            raise _v2_ScorerEnvironmentError(f'OpenMolcas native plan source pin differs: {name}')
    for name in ('renderer_sha256', 'driver_sha256', 'adapter_sha256', 'exporter_source_sha256', 'exporter_wrapper_sha256', 'exporter_binary_sha256', 'pymolcas_sha256'):
        _v2__digest(source.get(name), f'OpenMolcas source pin {name}')
    remote_exporter = plan['remote_ao_exporter']
    remote_pymolcas = plan['remote_pymolcas']
    expected_remote_files = {**{f'runtime/python/compchembench/{name}': digest for (name, digest) in expected_closure.items()}, 'runtime/openmolcas_ao_exporter/ao_export.F90': source_fields['exporter_source_sha256'], 'runtime/openmolcas_ao_exporter/export_json.py': _v2_PINNED_OPENMOLCAS_EXPORTER_WRAPPER_SHA256, remote_exporter: source_fields['exporter_binary_sha256'], remote_pymolcas: source_fields['pymolcas_sha256']}
    if expected_remote_files is not None and plan.get('remote_required_files') != expected_remote_files:
        raise _v2_ScorerEnvironmentError('OpenMolcas required remote source closure differs from fixed pins')
    for point in ('A', 'B'):
        geom = geometries.get(point)
        expected_geom_sha = protocol.GEOMETRY_SHA256[point]
        if not isinstance(geom, bytes) or _v2__sha(geom) != expected_geom_sha or plan['geometry_sha256'][point] != expected_geom_sha or (plan['geometry_xyz'][point] != geom.decode('utf-8', 'strict')):
            raise _v2_ScorerEnvironmentError(f'OpenMolcas plan {point} geometry differs from frozen public bytes')
        config = _v2__strict_json(_v2__canonical(plan['config'][point]), f'{point} OpenMolcas configuration')
        try:
            config = protocol.validate_openmolcas_point_config(config, point_id=point)
            expected_canonical = protocol.generate_canonical_point_input(_v2_OPENMOLCAS_PROGRAM_ID, point, config)
        except Exception as exc:
            raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} controls are outside the fixed protocol') from exc
        if plan['config'][point] != config or plan['canonical_inputs'][point] != expected_canonical.decode('utf-8') or plan['raw_config_sha256'].get(point) is None or (plan['canonical_config_sha256'].get(point) != _v2__sha(_v2__canonical(config))) or (plan['canonical_input_sha256'].get(point) != _v2__sha(expected_canonical)):
            raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} canonical controls/input do not close')
        for name in (plan['raw_config_sha256'][point], plan['canonical_config_sha256'][point], plan['canonical_input_sha256'][point]):
            _v2__digest(name, f'OpenMolcas {point} input hash')
    return source

def _v2__om_point_files(result: dict[str, _v2_Any], capture: dict[str, _v2_Any], point: str) -> tuple[dict, dict, dict]:
    inputs = _v2__evidence_rows(result, capture, point, 'native_inputs')
    sources = _v2__evidence_rows(result, capture, point, 'source_files')
    outputs = _v2__evidence_rows(result, capture, point, 'raw_outputs')
    overlap = set(inputs) & set(sources) | set(inputs) & set(outputs) | set(sources) & set(outputs)
    if overlap:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} capture categories overlap')
    return (inputs, sources, outputs)

def _v2__om_file(inputs: dict, sources: dict, outputs: dict, name: str) -> bytes | None:
    present = [group[name] for group in (inputs, sources, outputs) if name in group]
    if len(present) > 1:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas capture duplicates {name}')
    return present[0] if present else None

def _v2__om_plan_controls(plan: dict, point: str, inputs: dict, outputs: dict, protocol: _v2_Any, adapter: _v2_Any) -> tuple[dict, dict, bytes, bytes]:
    config_raw = _v2__om_file(inputs, {}, outputs, 'configuration.json')
    plan_raw = _v2__om_file(inputs, {}, outputs, 'native-plan-v2.json')
    geom = _v2__om_file(inputs, {}, outputs, 'geometry.xyz')
    if config_raw is None or plan_raw is None or geom is None:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} raw plan/configuration/geometry is incomplete')
    if plan_raw != _v2__canonical(plan) or geom != plan['geometry_xyz'][point].encode('utf-8'):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} point input bytes do not match the sealed plan')
    config_obj = _v2__strict_json(config_raw, f'{point} OpenMolcas config')
    try:
        config = protocol.validate_openmolcas_point_config(config_obj, point_id=point)
    except Exception as exc:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} config is invalid') from exc
    if config != plan['config'][point] or config_raw != _v2__canonical(config):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} config bytes differ from plan')
    try:
        point_declaration = _v2__strict_json(plan['canonical_inputs'][point].encode('utf-8'), f'{point} canonical OpenMolcas plan')
        canonical = protocol.generate_canonical_point_input(_v2_OPENMOLCAS_PROGRAM_ID, point, config)
        if canonical != plan['canonical_inputs'][point].encode('utf-8'):
            raise ValueError('canonical input mismatch')
        if point_declaration.get('program_id') != _v2_OPENMOLCAS_PROGRAM_ID or point_declaration.get('method_id') != _v2_METHOD_ID or point_declaration.get('point_id') != point or (point_declaration.get('native_input_rendered') is not False) or (point_declaration.get('execution_enabled') is not False) or (point_declaration.get('openmolcas_controls') != config):
            raise ValueError('declaration fields mismatch')
    except Exception as exc:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} canonical plan declaration is invalid') from exc
    (symbols, _, _) = _v2__openmolcas_geometry(geom, point, plan['geometry_sha256'][point])
    stages = adapter.render_openmolcas_inputs(point, config, host_reordered_inporb_path=f"{plan['profile']['remote_attempt_root'].rstrip('/')}/{plan['attempt_id']}/{point}/orbitals/{point}/INPORB", trusted_orbital_root=f"{plan['profile']['remote_attempt_root'].rstrip('/')}/{plan['attempt_id']}/{point}/orbitals")
    scf_input = outputs.get('scf/scf.input')
    if scf_input is None:
        scf_input = inputs.get('scf/scf.input')
    if scf_input != stages.scf_stage.text:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} rendered SCF input differs from fixed controls')
    return (config, {'symbols': symbols, 'stages': stages}, config_raw, geom)

def _v2__validate_openmolcas_point(result: dict[str, _v2_Any], identity: dict[str, _v2_Any], capture: dict[str, _v2_Any], plan: dict[str, _v2_Any], point: str, geometries: _v2_Mapping[str, bytes], parser: _v2_Any, adapter: _v2_Any, provider: _v2_Any, protocol: _v2_Any, job_id: str) -> tuple[dict | None, str | None]:
    (inputs, sources, outputs) = _v2__om_point_files(result, capture, point)
    (config, plan_material, config_raw, geom) = _v2__om_plan_controls(plan, point, inputs, outputs, protocol, adapter)
    symbols = plan_material['symbols']
    (_, coords_angstrom, coords_bohr) = _v2__openmolcas_geometry(geom, point, plan['geometry_sha256'][point])
    raw_status = _v2__om_file(inputs, sources, outputs, 'execution-status.json')
    status_hash = _v2__om_file(inputs, sources, outputs, 'execution-status.sha256')
    collected_status = _v2__om_file(inputs, sources, outputs, 'collected-execution-status.json')
    exit_raw = _v2__om_file(inputs, sources, outputs, 'exit-code.txt')
    status_text = _v2__om_file(inputs, sources, outputs, 'status.txt')
    provenance_raw = _v2__om_file(inputs, sources, outputs, 'execution-provenance.json')
    result_raw = _v2__om_file(inputs, sources, outputs, 'native-result.json')
    out_hash_raw = _v2__om_file(inputs, sources, outputs, 'output-hashes.txt')
    input_hash_raw = _v2__om_file(inputs, sources, outputs, 'input-hashes.txt')
    expected_input_hash_raw = _v2__om_file(inputs, sources, outputs, 'expected-input-hashes.txt')
    if any((value is None for value in (raw_status, status_hash, collected_status, exit_raw, status_text, provenance_raw, out_hash_raw, input_hash_raw, expected_input_hash_raw))):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} lacks raw status or provenance files')
    if collected_status != raw_status or status_hash != f'{_v2__sha(raw_status)}  execution-status.json\n'.encode('ascii'):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} status copies/digest differ')
    status = _v2__strict_json(raw_status, f'{point} OpenMolcas status')
    status = _v2__exact(status, {'schema', 'point_id', 'status', 'exit_code', 'geometry_sha256', 'canonical_plan_sha256', 'driver_sha256', 'adapter_sha256', 'provider_sha256', 'parser_sha256', 'allocation_window_sha256', 'attempt_id', 'request_id', 'slurm_job_id', 'error_class', 'qualification'}, f'{point} OpenMolcas status')
    expected_plan_sha = _v2__sha(_v2__canonical(plan))
    source = plan['source_pins']
    if status['schema'] != _v2_OPENMOLCAS_STATUS_SCHEMA or status['point_id'] != point or status['geometry_sha256'] != plan['geometry_sha256'][point] or (status['canonical_plan_sha256'] != expected_plan_sha) or (status['driver_sha256'] != source['driver_sha256']) or (status['adapter_sha256'] != source['adapter_sha256']) or (status['provider_sha256'] != source['python_closure_sha256']['case25_case05_openmolcas_ao_provider.py']) or (status['parser_sha256'] != source['python_closure_sha256']['case25_case05_openmolcas_native_parser_v2.py']) or (status['attempt_id'] != identity['attempt_id']) or (status['request_id'] != identity['request_id']) or (status['slurm_job_id'] != job_id) or (status['qualification'] is not False):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} status is not bound to current plan/job')
    try:
        exit_code = int(exit_raw.decode('ascii', 'strict').strip())
    except (UnicodeError, ValueError) as exc:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} exit code is malformed') from exc
    receipt_point = capture['points'].get(point)
    if not isinstance(receipt_point, dict) or receipt_point.get('status') != status['status'] or receipt_point.get('exit_code') != exit_code or (status['exit_code'] != exit_code) or (status_text.decode('ascii', 'strict').strip() != status['status']):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} status copies disagree')
    expected_point_cwd = f"{plan['profile']['remote_attempt_root'].rstrip('/')}/{identity['attempt_id']}/{point}"
    if receipt_point.get('cwd') != expected_point_cwd or not isinstance(receipt_point.get('argv'), list) or (not all((isinstance(arg, str) for arg in receipt_point['argv']))):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} launcher provenance has wrong path/argv')
    expected_input_hashes = f'{_v2__sha(geom)}  geometry.xyz\n{_v2__sha(config_raw)}  configuration.json\n{expected_plan_sha}  native-plan-v2.json\n'.encode('ascii')
    if input_hash_raw != expected_input_hashes or expected_input_hash_raw != expected_input_hashes:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} input hash ledger does not close')
    if out_hash_raw == b'MISSING native-result.json\n':
        if exit_code == 0 or result_raw is not None:
            raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} missing-result marker contradicts status')
    elif result_raw is None or out_hash_raw != f'{_v2__sha(result_raw)}  native-result.json\n'.encode('ascii'):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} native result hash does not close')
    provenance = _v2__strict_json(provenance_raw, f'{point} OpenMolcas provenance')
    provenance = _v2__exact(provenance, {'schema', 'allocation_window', 'attempt_id', 'request_id', 'slurm_job_id', 'driver_sha256', 'adapter_sha256', 'provider_sha256', 'parser_sha256', 'geometry_sha256', 'canonical_plan_sha256', 'events', 'qualification'}, f'{point} OpenMolcas provenance')
    allocation = provenance['allocation_window']
    if provenance['schema'] != 'case05/openmolcas-execution-provenance/v1' or provenance['attempt_id'] != identity['attempt_id'] or provenance['request_id'] != identity['request_id'] or (provenance['slurm_job_id'] != job_id) or (provenance['driver_sha256'] != source['driver_sha256']) or (provenance['adapter_sha256'] != source['adapter_sha256']) or (provenance['provider_sha256'] != status['provider_sha256']) or (provenance['parser_sha256'] != status['parser_sha256']) or (provenance['geometry_sha256'] != status['geometry_sha256']) or (provenance['canonical_plan_sha256'] != expected_plan_sha) or (provenance['qualification'] is not False) or (not isinstance(allocation, dict)) or (allocation.get('profile_id') != plan['profile'].get('profile_id')) or (allocation.get('profile_sha256') != plan['profile'].get('profile_sha256')) or (allocation.get('receipt_sha256') != status['allocation_window_sha256']):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} provenance is not bound to current plan/allocation')
    allocation_raw = _v2__om_file(inputs, sources, outputs, 'allocation-window.json')
    if allocation_raw is None or _v2__sha(allocation_raw) != status['allocation_window_sha256']:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} allocation receipt bytes differ')
    window = _v2__strict_json(allocation_raw, f'{point} allocation window')
    if window.get('schema') != 'case05/openmolcas-allocation-window/v1' or window.get('attempt_id') != identity['attempt_id'] or window.get('slurm_job_id') != job_id or (window.get('profile_id') != plan['profile'].get('profile_id')) or (window.get('profile_sha256') != plan['profile'].get('profile_sha256')):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} allocation window has wrong identity')
    events = provenance['events']
    if not isinstance(events, list):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} provenance events are malformed')
    (scf_stdout, scf_stderr) = (outputs.get('scf/pymolcas.stdout'), outputs.get('scf/pymolcas.stderr'))
    if not isinstance(scf_stdout, bytes) or not isinstance(scf_stderr, bytes):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} SCF raw logs are missing')
    scf_stage = [e for e in events if isinstance(e, dict) and e.get('kind') == 'native-stage' and (e.get('stage') == 'SCF')]
    scf_process = [e for e in events if isinstance(e, dict) and e.get('kind') == 'pymolcas' and (e.get('stage') == 'SCF')]
    if len(scf_stage) != 1 or len(scf_process) != 1 or scf_stage[0].get('stdout_sha256') != _v2__sha(scf_stdout) or (scf_stage[0].get('stderr_sha256') != _v2__sha(scf_stderr)) or (scf_process[0].get('return_code') != scf_stage[0].get('return_code')) or (scf_process[0].get('cwd') != scf_stage[0].get('cwd')) or (scf_process[0].get('argv') != scf_stage[0].get('argv')):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} SCF raw logs differ from process provenance')
    expected_scf_cwd = f'{expected_point_cwd}/scf'
    expected_scf_argv = [plan.get('remote_pymolcas'), f'{expected_scf_cwd}/scf.input']
    if scf_stage[0].get('cwd') != expected_scf_cwd or scf_stage[0].get('argv') != expected_scf_argv:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} SCF command differs from the fixed plan')
    try:
        parser.parse_scf_status(scf_stdout, scf_stage[0].get('return_code'))
        scf_failure = None
    except parser.NativeLogScientificFailure as exc:
        scf_failure = exc
    except Exception as exc:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} SCF log is unparseable') from exc

    def verify_orbitals() -> tuple[_v2_Any, _v2_Any, _v2_Any, _v2_Any, bytes]:
        scforb = outputs.get('scf/ScfOrb')
        ao_raw = outputs.get('scf/ao-export.json')
        binding_raw = outputs.get('scf/ao-stage-binding.json')
        if not all((isinstance(value, bytes) and value for value in (scforb, ao_raw, binding_raw))):
            raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} lacks current raw ScfOrb/AO export material')
        run_hashes = scf_process[0].get('current_input_sha256')
        if not isinstance(run_hashes, dict) or set(run_hashes) != {'RUNFILE', 'ONEINT'}:
            raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} SCF source hashes are incomplete')
        input_sha = {'RUNFILE': run_hashes['RUNFILE'], 'ONEINT': run_hashes['ONEINT'], 'ScfOrb': _v2__sha(scforb), 'geometry': _v2__sha(geom), 'configuration': _v2__sha(config_raw)}
        for value in input_sha.values():
            _v2__digest(value, f'OpenMolcas {point} AO source hash')
        binding = _v2__strict_json(binding_raw, f'{point} AO stage binding')
        expected_binding = {'attempt_id': identity['attempt_id'], 'request_id': identity['request_id'], 'slurm_job_id': job_id, 'stage': 'SCF_AO_EXPORT', 'configuration_sha256': _v2__sha(config_raw), 'input_sha256': input_sha}
        if binding != expected_binding:
            raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} AO stage binding differs from raw inputs')
        ao_event = [e for e in events if isinstance(e, dict) and e.get('kind') == 'native-ao-export' and (e.get('stage') == 'SCF_AO_EXPORT')]
        (ao_stdout, ao_stderr) = (outputs.get('scf/ao-export.stdout'), outputs.get('scf/ao-export.stderr'))
        if len(ao_event) != 1 or not isinstance(ao_stdout, bytes) or (not isinstance(ao_stderr, bytes)) or (ao_event[0].get('export_sha256') != _v2__sha(ao_raw)) or (ao_event[0].get('stdout_sha256') != _v2__sha(ao_stdout)) or (ao_event[0].get('stderr_sha256') != _v2__sha(ao_stderr)) or (ao_event[0].get('return_code') != 0):
            raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} AO export differs from process provenance')
        (_, xyz, bohr) = _v2__openmolcas_geometry(geom, point, plan['geometry_sha256'][point])
        ao = _v2__call_openmolcas_ao_provider(provider, result_schema=result.get('schema'), payload_bytes=ao_raw, scforb_bytes=scforb, expected_input_sha256=input_sha, expected_geometry_bohr=bohr, expected_symbols=tuple(symbols), expected_exporter_sha256=source['exporter_binary_sha256'], expected_stage_binding=expected_binding, expected_exporter_source_sha256=_v2_PINNED_OPENMOLCAS_STANDARD_EXPORTER_SOURCE_SHA256 if result.get('schema') == _v2_STANDARD_RESULT_SCHEMA else _v2_PINNED_OPENMOLCAS_EXPORTER_SOURCE_SHA256)
        parsed_orb = adapter.parse_scf_orb_bytes(scforb)
        orbital_plan = adapter.plan_orbital_reordering(parsed_orb.coefficients, parsed_orb.occupations, ao.overlap, ao.local_pi_ao_indices_zero_based, config['active_orbitals'])
        current_inporb = outputs.get(f'orbitals/{point}/INPORB')
        if not isinstance(current_inporb, bytes) or not current_inporb:
            raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} current INPORB is missing')
        stage_binding_hash = _v2__sha(scf_stdout + ao_raw + scforb)
        basis_hash = _v2__sha(b'OpenMolcas-v26.06:cc-pVDZ:NoSym:48')
        serialized = adapter.serialize_reordered_inporb(parsed_orb, orbital_plan, overlap_matrix=ao.overlap, geometry_sha256=_v2__sha(geom), basis_sha256=basis_hash, configuration_sha256=_v2__sha(config_raw), rhf_receipt_sha256=stage_binding_hash)
        if serialized.payload != current_inporb:
            raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} INPORB does not reproduce from current SCF orbitals')
        return (ao, parsed_orb, orbital_plan, serialized, current_inporb)
    if scf_failure is not None:
        if status['status'] != 'SCIENCE_FAIL' or exit_code != 1 or status['error_class'] != type(scf_failure).__name__ or (result_raw is not None):
            raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} SCF failure contradicts point status')
        return (None, f'trusted OpenMolcas native calculation reported SCIENCE_FAIL at point {point}')
    if scf_stage[0].get('return_code') != 0:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} SCF exit code lacks typed scientific failure')
    try:
        (ao, parsed_orb, orbital_plan, serialized, current_inporb) = verify_orbitals()
    except Exception as exc:
        if status['status'] == 'SCIENCE_FAIL' and status['error_class'] == 'OpenMolcasAdapterError':
            if 'selected active orbitals lack local pi projection' in str(exc):
                if exit_code == 1 and result_raw is None:
                    return (None, f'trusted OpenMolcas native calculation reported SCIENCE_FAIL at point {point}')
        raise
    (rasscf_stdout, rasscf_stderr) = (outputs.get('rasscf/pymolcas.stdout'), outputs.get('rasscf/pymolcas.stderr'))
    if not isinstance(rasscf_stdout, bytes) or not isinstance(rasscf_stderr, bytes):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} RASSCF raw logs are missing')
    rasscf_stage = [e for e in events if isinstance(e, dict) and e.get('kind') == 'native-stage' and (e.get('stage') == 'RASSCF')]
    rasscf_process = [e for e in events if isinstance(e, dict) and e.get('kind') == 'pymolcas' and (e.get('stage') == 'RASSCF')]
    if len(rasscf_stage) != 1 or len(rasscf_process) != 1 or rasscf_stage[0].get('stdout_sha256') != _v2__sha(rasscf_stdout) or (rasscf_stage[0].get('stderr_sha256') != _v2__sha(rasscf_stderr)) or (rasscf_process[0].get('return_code') != rasscf_stage[0].get('return_code')) or (rasscf_stage[0].get('current_inporb_sha256') != _v2__sha(current_inporb)) or (rasscf_process[0].get('cwd') != rasscf_stage[0].get('cwd')) or (rasscf_process[0].get('argv') != rasscf_stage[0].get('argv')):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} RASSCF logs/INPORB differ from provenance')
    if status['status'] == 'SCIENCE_FAIL' and exit_code == 1 and (status['error_class'] == 'NativeLogScientificFailure') and (result_raw is None):
        try:
            parser.parse_rasscf_result(rasscf_stdout, point_id=point, geometry_sha256=plan['geometry_sha256'][point], canonical_plan_sha256=expected_plan_sha, atoms=symbols, coordinates_angstrom=coords_angstrom, return_code=rasscf_stage[0].get('return_code'))
        except parser.NativeLogScientificFailure:
            return (None, f'trusted OpenMolcas native calculation reported SCIENCE_FAIL at point {point}')
        except Exception as exc:
            raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} failure log is malformed') from exc
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} SCIENCE_FAIL contradicts normal RASSCF result')
    if status['status'] != 'PASS' or exit_code != 0 or status['error_class'] not in (None, '') or (rasscf_stage[0].get('return_code') != 0) or (result_raw is None):
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} status/result is inconsistent')
    if outputs.get('rasscf/rasscf.input') != plan_material['stages'].rasscf_stage.text:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} rendered RASSCF input differs from fixed controls')
    expected_rasscf_cwd = f'{expected_point_cwd}/rasscf'
    if rasscf_stage[0].get('cwd') != expected_rasscf_cwd or rasscf_stage[0].get('argv') != [plan.get('remote_pymolcas'), f'{expected_rasscf_cwd}/rasscf.input']:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} RASSCF command differs from the fixed plan')
    try:
        native = parser.parse_rasscf_result(rasscf_stdout, point_id=point, geometry_sha256=plan['geometry_sha256'][point], canonical_plan_sha256=expected_plan_sha, atoms=symbols, coordinates_angstrom=coords_angstrom, return_code=rasscf_stage[0].get('return_code'))
    except parser.NativeLogScientificFailure as exc:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} PASS contradicts native science failure: {exc}') from exc
    except Exception as exc:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} native RASSCF log is unparseable') from exc
    native = _v2__openmolcas_derived_arrays(native, parser.np)
    output = _v2__strict_json(result_raw, f'{point} OpenMolcas native result')
    required_result = set(native) - {'force_norms_hartree_per_bohr', 'nac01_norm_per_bohr'}
    required_result.add('host_orbital_plan')
    output = _v2__exact(output, required_result, f'{point} OpenMolcas native result')
    for key in required_result - {'host_orbital_plan'}:
        if key in {'energy_hartree', 'gradients_hartree_per_bohr', 'nac01_per_bohr', 'coordinates_angstrom', 'weights'}:
            if not parser.np.allclose(parser.np.asarray(output[key], dtype=float), parser.np.asarray(native[key], dtype=float), atol=1e-12, rtol=0):
                raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} result {key} differs from raw-log parse')
        elif output[key] != native[key]:
            raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} result {key} differs from raw-log parse')
    claimed_orbitals = output['host_orbital_plan']
    expected_orbitals = {'selected_active_mo_zero_based': list(orbital_plan.selected_active_mo_zero_based), 'inactive_mo_zero_based': list(orbital_plan.inactive_mo_zero_based), 'permutation_zero_based': list(orbital_plan.full_permutation_zero_based), 'pi_projection_by_original_mo': orbital_plan.pi_projection_by_original_mo.tolist(), 'inporb_sha256': serialized.sha256, 'execution_qualified': False}
    if claimed_orbitals != expected_orbitals:
        raise _v2_ScorerEnvironmentError(f'OpenMolcas {point} host orbital metadata differs from independent recomputation')
    return (native, None)

def _v2__validate_openmolcas_native_and_status(result: dict[str, _v2_Any], identity: dict[str, _v2_Any], capture: dict[str, _v2_Any], plan: dict[str, _v2_Any], public_geometries: _v2_Mapping[str, bytes]) -> tuple[dict, str | None]:
    (modules, saved) = _v2__required_openmolcas_modules(result.get('code'), standard_runtime=result.get('schema') == _v2_STANDARD_RESULT_SCHEMA)
    (parser, adapter, provider, protocol) = modules
    try:
        source = _v2__om_fixed_plan(plan, identity, public_geometries, protocol, standard_context=result.get('standard_runtime_context') if result.get('schema') == _v2_STANDARD_RESULT_SCHEMA else None)
        evidence = result.get('evidence')
        if not isinstance(evidence, dict):
            raise _v2_ScorerEnvironmentError('OpenMolcas reader evidence is malformed')
        runtime_closure = dict(_v2_PINNED_OPENMOLCAS_STANDARD_RUNTIME_CLOSURE_SHA256) if result.get('schema') == _v2_STANDARD_RESULT_SCHEMA else dict(_v2_PINNED_OPENMOLCAS_RUNTIME_CLOSURE_SHA256)
        if result.get('schema') == _v2_STANDARD_RESULT_SCHEMA:
            runtime_closure['case25_case05_openmolcas_bootstrap.py'] = _v2_PINNED_OPENMOLCAS_STANDARD_BOOTSTRAP_SHA256
        for (name, digest) in runtime_closure.items():
            path = f'capture/runtime/python/compchembench/{name}'
            raw = evidence.get(path)
            if not isinstance(raw, bytes) or _v2__sha(raw) != digest:
                raise _v2_ScorerEnvironmentError(f'OpenMolcas captured runtime source is missing or changed: {name}')
        if not isinstance(capture.get('job'), dict):
            raise _v2_ScorerEnvironmentError('OpenMolcas capture lacks scheduler job identity')
        job_id = capture['job'].get('job_id')
        if not isinstance(job_id, str) or not job_id.isdigit():
            raise _v2_ScorerEnvironmentError('OpenMolcas capture has invalid scheduler job identity')
        (native, failure) = ({}, None)
        windows = []
        for point in ('A', 'B'):
            files = _v2__om_point_files(result, capture, point)
            allocation = _v2__om_file(*files, 'allocation-window.json')
            windows.append(allocation)
            (parsed, point_failure) = _v2__validate_openmolcas_point(result, identity, capture, plan, point, public_geometries, parser, adapter, provider, protocol, job_id)
            if parsed is not None:
                native[point] = parsed
            if point_failure is not None and failure is None:
                failure = point_failure
        if not isinstance(windows[0], bytes) or windows[0] != windows[1]:
            raise _v2_ScorerEnvironmentError('OpenMolcas A/B do not share one allocation window')
        if failure is not None:
            return (native, failure)
        return (native, None)
    finally:
        _v2__restore_openmolcas_modules(saved)

def _v2__validate_native_and_status(result: dict[str, _v2_Any], identity: dict[str, _v2_Any], capture: dict[str, _v2_Any], plan: dict[str, _v2_Any], public_geometries: _v2_Mapping[str, bytes]) -> tuple[dict, str | None]:
    if identity.get('program_id') == _v2_OPENMOLCAS_PROGRAM_ID:
        return _v2__validate_openmolcas_native_and_status(result, identity, capture, plan, public_geometries)
    parser = _v2__required_module(result['code']['code/parse_pyscf_v2.py'])
    native: dict[str, _v2_Any] = {}
    failure = None
    driver_sha = plan.get('source_pins', {}).get('driver_sha256') if isinstance(plan.get('source_pins'), dict) else None
    adapter_sha = plan.get('source_pins', {}).get('adapter_sha256') if isinstance(plan.get('source_pins'), dict) else None
    for (label, value) in (('driver', driver_sha), ('adapter', adapter_sha)):
        _v2__digest(value, f'native plan {label} pin')
    job = capture.get('job')
    job_id = job.get('job_id') if isinstance(job, dict) else None
    if not isinstance(job_id, str) or not job_id.isdigit():
        raise _v2_ScorerEnvironmentError('capture has no scheduler job identity')
    evidence = result['evidence']
    for point in ('A', 'B'):
        geom = public_geometries.get(point)
        expected_geom_sha = parser.GEOMETRY_SHA256[point]
        if not isinstance(geom, bytes) or _v2__sha(geom) != expected_geom_sha:
            raise _v2_ScorerEnvironmentError(f'public {point} geometry differs from the frozen geometry pin')
        if plan['geometry_sha256'].get(point) != expected_geom_sha:
            raise _v2_ScorerEnvironmentError(f'native plan {point} geometry hash differs from frozen geometry')
        try:
            plan_geom = plan['geometry_xyz'][point].encode('utf-8')
        except (AttributeError, UnicodeError) as exc:
            raise _v2_ScorerEnvironmentError(f'native plan {point} geometry is invalid') from exc
        if plan_geom != geom:
            raise _v2_ScorerEnvironmentError(f'native plan {point} geometry differs from public bytes')
        inputs = _v2__evidence_rows(result, capture, point, 'native_inputs')
        sources = _v2__evidence_rows(result, capture, point, 'source_files')
        outputs = _v2__evidence_rows(result, capture, point, 'raw_outputs')
        if inputs.get('geometry.xyz') != geom:
            raise _v2_ScorerEnvironmentError(f'captured {point} native geometry differs from public input')
        if 'canonical-plan.json' not in inputs:
            raise _v2_ScorerEnvironmentError(f'captured {point} canonical plan input is missing')
        sealed_input = plan.get('canonical_inputs')
        if not isinstance(sealed_input, dict) or not isinstance(sealed_input.get(point), str) or sealed_input[point].encode('utf-8') != inputs['canonical-plan.json']:
            raise _v2_ScorerEnvironmentError(f'captured {point} canonical input bytes differ from the sealed native plan')
        try:
            point_plan = _v2__strict_json(inputs['canonical-plan.json'], f'{point} canonical plan')
        except _v2_ScorerEnvironmentError:
            raise
        if not isinstance(point_plan, dict):
            raise _v2_ScorerEnvironmentError(f'captured {point} canonical plan is not an object')
        plan_geometry_sha = point_plan.get('geometry_sha256', expected_geom_sha)
        if point_plan.get('schema') != 'case05/canonical-point-input/v1' or point_plan.get('point_id') != point or point_plan.get('method_id') != _v2_METHOD_ID or (plan_geometry_sha != expected_geom_sha) or (point_plan.get('geometry_file') != 'geometry.xyz') or ('geometry_sha256' in point_plan and point_plan.get('geometry_sha256') != expected_geom_sha) or (point_plan.get('geometry_unit') != 'Angstrom') or (point_plan.get('charge') != 0) or (point_plan.get('spin') != 0) or (point_plan.get('basis') != 'cc-pVDZ') or (point_plan.get('active_space') != {'electrons': 2, 'orbitals': 2, 'inactive_orbitals': 7}) or (point_plan.get('state_averaging') != {'states': ['S0', 'S1', 'S2'], 'weights': [1 / 3, 1 / 3, 1 / 3]}) or (point_plan.get('gradient_states') != [0, 1, 2]) or (point_plan.get('nac_pairs_zero_based') != [[0, 1]]) or (point_plan.get('restart_policy') != 'none') or (point_plan.get('external_orbitals') is not False) or (not isinstance(point_plan.get('active_orbitals'), dict)) or (not isinstance(point_plan.get('scf'), dict)) or (not isinstance(point_plan.get('casscf'), dict)) or (not isinstance(point_plan.get('response'), dict)):
            expected_fields = {'schema': 'case05/canonical-point-input/v1', 'point_id': point, 'method_id': _v2_METHOD_ID, 'geometry_file': 'geometry.xyz', 'geometry_unit': 'Angstrom', 'charge': 0, 'spin': 0, 'basis': 'cc-pVDZ', 'active_space': {'electrons': 2, 'orbitals': 2, 'inactive_orbitals': 7}, 'state_averaging': {'states': ['S0', 'S1', 'S2'], 'weights': [1 / 3, 1 / 3, 1 / 3]}, 'gradient_states': [0, 1, 2], 'nac_pairs_zero_based': [[0, 1]], 'restart_policy': 'none', 'external_orbitals': False}
            mismatches = [name for (name, value) in expected_fields.items() if point_plan.get(name) != value]
            if 'geometry_sha256' in point_plan and point_plan.get('geometry_sha256') != expected_geom_sha:
                mismatches.append('geometry_sha256')
            for name in ('active_orbitals', 'scf', 'casscf', 'response'):
                if not isinstance(point_plan.get(name), dict):
                    mismatches.append(name)
            raise _v2_ScorerEnvironmentError(f'captured {point} canonical input differs from fixed method/geometry: ' + ', '.join(mismatches or ['structured fields']))
        sealed_config = plan.get('config', {}).get(point) if isinstance(plan.get('config'), dict) else None
        if not isinstance(sealed_config, dict) or any((point_plan.get(key) != sealed_config.get(key) for key in ('scf', 'casscf', 'response', 'active_orbitals'))):
            raise _v2_ScorerEnvironmentError(f'captured {point} controls/orbitals differ from sealed native plan')
        if sources.get('run_point_v2.py') is None or _v2__sha(sources['run_point_v2.py']) != driver_sha or sources.get('case05_pyscf_adapter.py') is None or (_v2__sha(sources['case05_pyscf_adapter.py']) != adapter_sha):
            raise _v2_ScorerEnvironmentError(f'captured {point} source bytes differ from native plan pins')
        status_raw = outputs.get('execution-status.json')
        exit_raw = outputs.get('exit-code.txt')
        result_raw = outputs.get('result.json')
        if status_raw is None or exit_raw is None:
            raise _v2_ScorerEnvironmentError(f'captured {point} lacks status or exit code')
        status = _v2__strict_json(status_raw, f'{point} execution status')
        status_keys = {'schema', 'point_id', 'geometry_sha256', 'canonical_plan_sha256', 'driver_sha256', 'adapter_sha256', 'attempt_id', 'request_id', 'slurm_job_id', 'status', 'exit_code', 'error_class'}
        status = _v2__exact(status, status_keys, f'{point} execution status')
        if status['schema'] != _v2_STATUS_SCHEMA or status['point_id'] != point or status['geometry_sha256'] != expected_geom_sha or (status['canonical_plan_sha256'] != _v2__sha(inputs['canonical-plan.json'])) or (status['driver_sha256'] != driver_sha) or (status['adapter_sha256'] != adapter_sha) or (status['attempt_id'] != identity['attempt_id']) or (status['request_id'] != identity['request_id']) or (status['slurm_job_id'] != job_id):
            raise _v2_ScorerEnvironmentError(f'captured {point} execution status is not bound to this job/plan')
        point_receipt = capture['points'].get(point)
        if not isinstance(point_receipt, dict):
            raise _v2_ScorerEnvironmentError(f'capture receipt omits {point}')
        if point_receipt.get('status') != status['status'] or point_receipt.get('exit_code') != status['exit_code'] or type(status['exit_code']) is not int:
            raise _v2_ScorerEnvironmentError(f'captured {point} status disagrees with its receipt')
        argv = point_receipt.get('argv')
        expected_argv = [plan.get('remote_python'), '-u', 'run_point_v2.py', point, 'geometry.xyz', 'canonical-plan.json', 'result.json']
        if not isinstance(argv, list) or not all((isinstance(arg, str) for arg in argv)) or argv != expected_argv:
            raise _v2_ScorerEnvironmentError(f'captured {point} argv does not match the sealed driver command')
        try:
            exit_code = int(exit_raw.decode('ascii').strip())
        except (UnicodeError, ValueError) as exc:
            raise _v2_ScorerEnvironmentError(f'captured {point} exit-code is malformed') from exc
        if exit_code != status['exit_code']:
            raise _v2_ScorerEnvironmentError(f'captured {point} exit-code disagrees with status')
        if status['status'] == 'SCIENCE_FAIL' and exit_code == 1 and (status['error_class'] == 'ScientificCalculationFailure'):
            if result_raw is not None:
                try:
                    parser.parse_native_result(result_raw, expected_point=point, expected_geometry_sha256=expected_geom_sha, expected_plan_sha256=_v2__sha(inputs['canonical-plan.json']), expected_geometry_bytes=geom)
                except parser.NativeScientificFailure:
                    pass
                except Exception as exc:
                    raise _v2_ScorerEnvironmentError(f'captured {point} SCIENCE_FAIL has malformed native result: {exc}') from exc
                else:
                    raise _v2_ScorerEnvironmentError(f'captured {point} SCIENCE_FAIL contradicts a successful native result')
            failure = f'trusted native calculation reported SCIENCE_FAIL at point {point}'
            continue
        if status['status'] != 'PASS' or exit_code != 0 or status['error_class'] not in (None, ''):
            raise _v2_ScorerEnvironmentError(f'captured {point} status is unknown or internally inconsistent')
        if result_raw is None:
            raise _v2_ScorerEnvironmentError(f'captured {point} PASS status has no native result')
        try:
            expected_controls = point_plan.get('controls')
            if not isinstance(expected_controls, dict):
                expected_controls = {key: point_plan.get(key) for key in ('scf', 'casscf', 'response')}
            expected_scf = expected_controls.get('scf')
            expected_casscf = expected_controls.get('casscf')
            expected_response = expected_controls.get('response')
            parsed_result = _v2__strict_json(result_raw, f'{point} native result')
            if not isinstance(expected_scf, dict) or not isinstance(expected_casscf, dict) or (not isinstance(expected_response, dict)) or (parsed_result.get('scf_controls') != expected_scf) or (parsed_result.get('casscf_controls') != expected_casscf) or any((parsed_result.get('response_controls', {}).get(key) != expected_response.get(key) for key in ('conv_tol', 'max_cycles'))):
                raise _v2_ScorerEnvironmentError(f'captured {point} result controls differ from the protected plan')
            native[point] = parser.parse_native_result(result_raw, expected_point=point, expected_geometry_sha256=expected_geom_sha, expected_plan_sha256=_v2__sha(inputs['canonical-plan.json']), expected_geometry_bytes=geom)
        except parser.NativeScientificFailure as exc:
            raise _v2_ScorerEnvironmentError(f'captured {point} PASS status contradicts native science failure: {exc}') from exc
        except (parser.NativeEnvironmentError, parser.NativeFormatError, Exception) as exc:
            raise _v2_ScorerEnvironmentError(f'captured {point} native result is unusable: {exc}') from exc
    return (native, failure)

def _v2__candidate_artifact(artifacts: _v2_Any, filename: str, *, allow_empty: bool=False) -> bytes:
    if not isinstance(artifacts, dict):
        raise _v2_CandidateFailure('candidate artifact map is malformed')
    suffix = f'outputs/{filename}'
    matches = [raw for (path, raw) in artifacts.items() if isinstance(path, str) and (path == suffix or path.endswith('/' + suffix))]
    if len(matches) != 1 or not isinstance(matches[0], bytes) or (not allow_empty and (not matches[0])):
        raise _v2_CandidateFailure(f'candidate artifact outputs/{filename} is missing, empty, or ambiguous')
    return matches[0]

def _v2__candidate_summary(artifacts: dict[str, bytes], *, expected_program: str=_v2_PROGRAM_LABEL) -> tuple[dict[str, _v2_Any], dict[str, bytes]]:
    summary_raw = _v2__candidate_artifact(artifacts, 'summary.json')
    summary = _v2__strict_json(summary_raw, 'candidate summary', candidate=True)
    if not isinstance(summary, dict):
        raise _v2_CandidateFailure('summary.json must be an object')
    required = {'program', 'active_space', 'state_averaging', 'basis', 'converged', 'raw_outputs', 'caveats'}
    if not required.issubset(summary):
        raise _v2_CandidateFailure('summary.json lacks required fixed-method fields')
    if summary.get('program') != expected_program or str(summary.get('active_space', '')) not in {'(2,2)', '2,2', '(2e,2o)'} or str(summary.get('basis', '')).strip().lower() != 'cc-pvdz':
        raise _v2_CandidateFailure('candidate summary method declaration differs from frozen protocol')
    state = summary.get('state_averaging')
    if not isinstance(state, dict) or state.get('states') != ['S0', 'S1', 'S2'] or (not isinstance(state.get('weights'), list)) or (len(state['weights']) != 3):
        raise _v2_CandidateFailure('candidate summary state averaging is malformed')
    try:
        weights = [float(x) for x in state['weights']]
    except (TypeError, ValueError, OverflowError) as exc:
        raise _v2_CandidateFailure('candidate state weights are invalid') from exc
    if any((not _v2_math.isfinite(x) or abs(x - 1 / 3) > 1e-08 for x in weights)):
        raise _v2_CandidateFailure('candidate state weights differ from equal SA(3)')
    if not isinstance(summary.get('converged'), dict) or set(summary['converged']) != {'A', 'B'} or any((type(value) is not bool or not value for value in summary['converged'].values())):
        raise _v2_CandidateFailure('candidate summary must report both points converged')
    if not isinstance(summary.get('raw_outputs'), list) or not isinstance(summary.get('caveats'), list):
        raise _v2_CandidateFailure('candidate summary raw_outputs/caveats are malformed')
    if any((not isinstance(item, str) for item in summary['raw_outputs'])) or any((not isinstance(item, str) for item in summary['caveats'])):
        raise _v2_CandidateFailure('candidate summary raw_outputs/caveats entries must be strings')
    for path in summary['raw_outputs']:
        _v2__candidate_relative_path(path, 'summary.raw_outputs')
    return (summary, artifacts)

def _v2__candidate_relative_path(value: _v2_Any, label: str) -> str:
    try:
        return _v2__safe_relative(value, label)
    except _v2_ScorerEnvironmentError as exc:
        raise _v2_CandidateFailure(f'candidate {label} path is unsafe') from exc

def _v2__parse_candidate_csv(artifacts: dict[str, bytes]) -> tuple[dict, dict]:
    try:
        result_raw = _v2__candidate_artifact(artifacts, 'casscf_results.csv')
        nac_raw = _v2__candidate_artifact(artifacts, 'nacs.csv')
        report_raw = _v2__candidate_artifact(artifacts, 'convergence_report.md')
        result_rows = list(_v2_csv.DictReader(_v2_io.StringIO(result_raw.decode('utf-8', 'strict'))))
        nac_rows = list(_v2_csv.DictReader(_v2_io.StringIO(nac_raw.decode('utf-8', 'strict'))))
        report = report_raw.decode('utf-8', 'strict')
    except (UnicodeError, _v2_csv.Error, OSError) as exc:
        raise _v2_CandidateFailure(f'candidate output table/report is malformed: {exc}') from exc
    required_results = {'point_id', 'state', 'energy_hartree', 'force_frobenius_norm_hartree_per_bohr', 'gap_to_lower_state_eV'}
    if not result_rows or set(result_rows[0]) != required_results or len(result_rows) != 6 or (not nac_rows) or (set(nac_rows[0]) != {'point_id', 'coupling', 'nac01_frobenius_norm', 'unit'}) or (len(nac_rows) != 2) or (not report.strip()):
        raise _v2_CandidateFailure('candidate tables have wrong headers, row counts, or empty report')
    if any((set(row) != required_results or any((value is None for value in row.values())) for row in result_rows)) or any((set(row) != {'point_id', 'coupling', 'nac01_frobenius_norm', 'unit'} or any((value is None for value in row.values())) for row in nac_rows)):
        raise _v2_CandidateFailure('candidate CSV contains missing or extra row cells')
    cells = {}
    for row in result_rows:
        (point, state) = (row['point_id'], row['state'])
        if point not in {'A', 'B'} or state not in {'S0', 'S1', 'S2'} or (point, state) in cells:
            raise _v2_CandidateFailure('casscf_results.csv has duplicate/unknown point-state rows')
        cells[point, state] = row
    if set(cells) != {(p, s) for p in ('A', 'B') for s in ('S0', 'S1', 'S2')}:
        raise _v2_CandidateFailure('casscf_results.csv must cover A/B by S0/S1/S2')
    nac_map = {}
    for row in nac_rows:
        point = row['point_id']
        if point not in {'A', 'B'} or point in nac_map:
            raise _v2_CandidateFailure('nacs.csv has duplicate or unknown points')
        if row['coupling'] != 'S1/S0' or row['unit'] != '1/Bohr':
            raise _v2_CandidateFailure('nacs.csv must report C01 in 1/Bohr')
        nac_map[point] = row
    if set(nac_map) != {'A', 'B'}:
        raise _v2_CandidateFailure('nacs.csv must cover A and B')
    return (cells, nac_map)

def _v2__num(row: dict[str, str], key: str, label: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise _v2_CandidateFailure(f'{label} is not numeric') from exc
    if not _v2_math.isfinite(value):
        raise _v2_CandidateFailure(f'{label} is non-finite')
    return value

def _v2__candidate_native_binding(artifacts: dict[str, bytes], summary: dict[str, _v2_Any], result: dict[str, _v2_Any], capture: dict[str, _v2_Any]) -> None:
    raw_outputs = summary['raw_outputs']
    if not isinstance(raw_outputs, list) or any((not isinstance(path, str) for path in raw_outputs)):
        raise _v2_CandidateFailure('summary.raw_outputs must be a list of path strings')
    normalized_paths = [_v2__candidate_relative_path(path, 'summary.raw_outputs') for path in raw_outputs]
    if len(set(normalized_paths)) != len(normalized_paths):
        raise _v2_CandidateFailure('summary.raw_outputs has duplicate paths')
    if result['identity']['program_id'] == _v2_OPENMOLCAS_PROGRAM_ID:
        expected_paths: set[str] = set()
        for point in ('A', 'B'):
            protected = _v2__evidence_rows(result, capture, point, 'raw_outputs')
            for (relative, raw) in protected.items():
                path = f'raw/{point}/{relative}'
                expected_paths.add(path)
                artifact = _v2__candidate_artifact(artifacts, path, allow_empty=True)
                if artifact != raw:
                    raise _v2_CandidateFailure(f'candidate {path} differs from host-captured bytes')
        if set(normalized_paths) != expected_paths:
            raise _v2_CandidateFailure('summary.raw_outputs does not exactly cover captured OpenMolcas point files')
        if any((not path.startswith(('raw/A/', 'raw/B/')) for path in normalized_paths)):
            raise _v2_CandidateFailure('summary.raw_outputs contains a path outside raw/A or raw/B')
        return
    for point in ('A', 'B'):
        protected = _v2__evidence_rows(result, capture, point, 'raw_outputs')
        needed = {'result.json', 'program.log', 'run_point_v2.py', 'geometry.xyz', 'input-hashes.txt', 'output-hashes.txt', 'exit-code.txt', 'program.stderr', 'execution-status.json'}
        if not needed.issubset(protected):
            raise _v2_ScorerEnvironmentError(f'protected {point} capture lacks required native files')
        for name in needed:
            relative = f'raw/{point}/{name}'
            if relative not in raw_outputs:
                raise _v2_CandidateFailure(f'summary.raw_outputs omits {relative}')
            artifact = _v2__candidate_artifact(artifacts, relative, allow_empty=True)
            if artifact != protected[name]:
                raise _v2_CandidateFailure(f'candidate {relative} differs from host-captured bytes')
    for relative in normalized_paths:
        if not relative.startswith(('raw/A/', 'raw/B/')):
            raise _v2_CandidateFailure('summary.raw_outputs contains a path outside raw/A or raw/B')
        _v2__candidate_artifact(artifacts, relative, allow_empty=True)

def _v2__candidate_vs_native(cells: dict, nac_map: dict, native: dict) -> None:
    states = ('S0', 'S1', 'S2')
    for point in ('A', 'B'):
        energies = native[point]['energy_hartree']
        force_norms = native[point]['force_norms_hartree_per_bohr']
        for (index, state) in enumerate(states):
            row = cells[point, state]
            values = {'energy_hartree': energies[index], 'force_frobenius_norm_hartree_per_bohr': force_norms[index], 'gap_to_lower_state_eV': 0.0 if index == 0 else (energies[index] - energies[index - 1]) * _v2_HARTREE_TO_EV}
            for (key, expected) in values.items():
                actual = _v2__num(row, key, f'{point}/{state}/{key}')
                if abs(actual - expected) > tolerances['csv_native']:
                    raise _v2_CandidateFailure(f'{point}/{state} {key} differs from protected native result')
        nac = _v2__num(nac_map[point], 'nac01_frobenius_norm', f'{point} NAC norm')
        if abs(nac - native[point]['nac01_norm_per_bohr']) > tolerances['csv_native']:
            raise _v2_CandidateFailure(f'{point} NAC norm differs from protected native result')

def _v2__reference_check(cells: dict, nac_map: dict, native: dict, reference: dict[str, _v2_Any]) -> None:
    for point in ('A', 'B'):
        ref = reference[point]
        energies = native[point]['energy_hartree']
        forces = native[point]['force_norms_hartree_per_bohr']
        if not energies[0] < energies[1] < energies[2]:
            raise _v2_CandidateFailure(f'{point} native energies are not ordered S0 < S1 < S2')
        for (index, state) in enumerate(('S0', 'S1', 'S2')):
            if abs(energies[index] - ref['energy_hartree'][index]) > tolerances['energy_hartree']:
                raise _v2_CandidateFailure(f'{point}/{state} energy differs from frozen reference')
            expected_force = ref['forces_frobenius_norm_hartree_per_bohr'][index]
            if abs(forces[index] - expected_force) > tolerances['force_relative'] * abs(expected_force):
                raise _v2_CandidateFailure(f'{point}/{state} force norm differs from frozen reference')
            gap = 0.0 if index == 0 else (energies[index] - energies[index - 1]) * _v2_HARTREE_TO_EV
            ref_gap = 0.0 if index == 0 else ref['energy_gap_S10_eV'] if index == 1 else ref['energy_gap_S21_eV']
            if index > 0 and abs(gap - ref_gap) > tolerances['energy_hartree'] * _v2_HARTREE_TO_EV:
                raise _v2_CandidateFailure(f'{point}/{state} energy gap differs from frozen reference')
            candidate_gap = _v2__num(cells[point, state], 'gap_to_lower_state_eV', f'{point}/{state} gap')
            if abs(candidate_gap - gap) > 0.05:
                raise _v2_CandidateFailure(f'{point}/{state} candidate gap is inconsistent with native energies')
        nac_norm = native[point]['nac01_norm_per_bohr']
        ref_nac = ref['nacs_frobenius_norm_per_bohr'][0]
        if abs(nac_norm - ref_nac) > tolerances['nac_relative'] * abs(ref_nac):
            raise _v2_CandidateFailure(f'{point} C01 NAC norm differs from frozen reference')

def _v2_verify_reader_result(reader_result: _v2_Any, *, expected_context_sha256: str, expected_image_id: _v2_Any, public_geometries: _v2_Mapping[str, bytes] | None=None) -> _v2_V2Decision:
    """Verify candidate files/native calculations represented in a reader result.

    ``reader_result`` must be the exact return from the pinned offline reader.
    This function itself is pure over that material plus immutable case files;
    it does not issue a reward or authenticate an arbitrary mapping as a reader.
    """
    try:
        if isinstance(reader_result, dict) and reader_result.get('schema') == _v2_STANDARD_RESULT_SCHEMA:
            identity = _v2__validate_standard_context(reader_result, expected_context_sha256=expected_context_sha256, expected_image_id=expected_image_id)
            (capture, plan) = _v2__validate_standard_execution_joins(reader_result, identity)
        else:
            identity = _v2__validate_context(reader_result, expected_context_sha256=expected_context_sha256, expected_image_id=expected_image_id)
            (_consumption, capture, plan) = _v2__validate_execution_joins(reader_result, identity)
        if plan.get('geometry_sha256') != {point: _v2_hashlib.sha256((public_geometries or _v2__local_geometry_bytes())[point]).hexdigest() for point in ('A', 'B')}:
            raise _v2_ScorerEnvironmentError('native plan geometry set differs from frozen public geometries')
        geometries = dict(public_geometries or _v2__local_geometry_bytes())
        (native, trusted_failure) = _v2__validate_native_and_status(reader_result, identity, capture, plan, geometries)
        (reference, tolerances) = _v2__fixed_reference()
        if trusted_failure is not None:
            return _v2_V2Decision('FAIL', trusted_failure)
        artifacts = reader_result['artifacts']
        if not isinstance(artifacts, dict):
            raise _v2_CandidateFailure('candidate artifact collection is malformed')
        expected_program = _v2_OPENMOLCAS_PROGRAM_LABEL if identity['program_id'].startswith('openmolcas-') else 'PySCF ' + identity['program_id'].removeprefix('pyscf-')
        (summary, artifacts) = _v2__candidate_summary(artifacts, expected_program=expected_program)
        if summary.get('attempt_id') is not None and summary['attempt_id'] != identity['attempt_id']:
            raise _v2_CandidateFailure('candidate summary attempt_id differs from protected attempt')
        _v2__candidate_native_binding(artifacts, summary, reader_result, capture)
        (cells, nac_map) = _v2__parse_candidate_csv(artifacts)
        _v2__candidate_vs_native(cells, nac_map, native)
        _v2__reference_check(cells, nac_map, native, reference)
        return _v2_V2Decision('PASS', 'native, candidate, and frozen-reference checks passed', native)
    except _v2_CandidateFailure as exc:
        return _v2_V2Decision('FAIL', str(exc))
    except _v2_ScorerEnvironmentError as exc:
        return _v2_V2Decision('ENV_ERROR', str(exc))
    except Exception as exc:
        return _v2_V2Decision('ENV_ERROR', f'unexpected scorer/protected-material error: {exc}')

def _v2__validate_standard_context(reader_result: _v2_Any, *, expected_context_sha256: str, expected_image_id: _v2_Any) -> dict[str, _v2_Any]:
    """Validate the independently read standard-runtime identity envelope."""
    keys = {'schema', 'identity', 'standard_runtime', 'standard_joins', 'runner_context', 'standard_runtime_context', 'standard_observation', 'reservation', 'consumption', 'standard_execution', 'capture_receipt', 'captured_binding', 'native_plan', 'stage_manifest', 'artifacts', 'evidence', 'code'}
    result = _v2__exact(reader_result, keys, 'standard scoring reader result')
    if result['schema'] != _v2_STANDARD_RESULT_SCHEMA:
        raise _v2_ScorerEnvironmentError('unsupported standard scoring reader result schema')
    _v2__digest(expected_context_sha256, 'externally selected final runner-context hash')
    identity = _v2__exact(result['identity'], {'case_path', 'case_id', 'program_id', 'profile_id', 'operation', 'attempt_id', 'run_id', 'request_id', 'challenge_nonce', 'runner_nonce_sha256', 'image_id', 'task_config_sha256', 'effective_instruction_sha256', 'context_sha256'}, 'standard scoring identity')
    if identity['case_id'] != 'case-05' or not isinstance(identity['program_id'], str) or _v2_PROGRAM_ID_RE.fullmatch(identity['program_id']) is None or identity['operation'] != 'run-points' or (identity['profile_id'] != 'case05-openmolcas') or (not isinstance(identity['case_path'], str)) or (not (identity['case_path'].endswith('/25_spainn-nonadiabatic-dynamics/task 166') or identity['case_path'].endswith('/25_spainn-nonadiabatic-dynamics/case-05') or identity['case_path'] in {'/bench/task 166', '/bench/case-05'})) or (identity['task_config_sha256'] != _v2_CASE_TASK_CONFIG_SHA256) or (identity['effective_instruction_sha256'] != _v2_CASE_EFFECTIVE_INSTRUCTION_SHA256):
        raise _v2_ScorerEnvironmentError('standard runtime identity is outside the frozen Case05 route')
    for name in ('attempt_id', 'request_id', 'challenge_nonce'):
        if not isinstance(identity[name], str) or _v2__ID_RE.fullmatch(identity[name]) is None:
            raise _v2_ScorerEnvironmentError(f'standard {name} is malformed')
    for name in ('runner_nonce_sha256', 'task_config_sha256', 'effective_instruction_sha256', 'context_sha256'):
        _v2__digest(identity[name], f'standard identity {name}')
    if len({identity['attempt_id'], identity['request_id'], identity['challenge_nonce']}) != 3:
        raise _v2_ScorerEnvironmentError('standard attempt/request/challenge identifiers are not distinct')
    actual_image_id = _v2_validate_runner_image_id(identity['image_id'], expected_image_id)
    proof = _v2__exact(result['standard_runtime'], {'schema', 'context_sha256', 'image_id', 'task_config_sha256', 'effective_instruction_sha256', 'run_id', 'attempt_id', 'nonce_sha256', 'public_inputs_sha256', 'profile_sha256', 'source_closure_sha256', 'program_id', 'observation_sha256', 'observation_context_sha256', 'resource_request', 'resource_request_sha256', 'accepted_resources'}, 'standard runtime proof')
    for name in ('context_sha256', 'task_config_sha256', 'effective_instruction_sha256', 'nonce_sha256', 'public_inputs_sha256', 'profile_sha256', 'source_closure_sha256', 'observation_sha256', 'observation_context_sha256'):
        _v2__digest(proof[name], f'standard proof {name}')
    request = proof['resource_request']
    if not isinstance(request, dict) or set(request) != {'cpus', 'memory_gb', 'wall_seconds', 'accelerator', 'gpu_count'} or any((type(request.get(key)) is not int for key in ('cpus', 'memory_gb', 'wall_seconds', 'gpu_count'))) or any(request[key] < 1 for key in ('cpus', 'memory_gb', 'wall_seconds')) or request['wall_seconds'] > 1200 or request['gpu_count'] < 0 or not isinstance(request['accelerator'], str) or not request['accelerator'] or (request['accelerator'] == 'cpu' and request['gpu_count'] != 0) or (request['accelerator'] != 'cpu' and request['gpu_count'] < 1) or (proof['resource_request_sha256'] != _v2__sha(_v2__canonical(request))):
        raise _v2_ScorerEnvironmentError('standard runtime resource request is invalid or unbound')
    accepted = proof['accepted_resources']
    if not isinstance(accepted, dict) or accepted.get('cpu_cores') != request['cpus'] or accepted.get('memory_gb') != request['memory_gb'] or (accepted.get('wall_seconds') != request['wall_seconds']) or (accepted.get('gpu_count') != request['gpu_count']) or not isinstance(accepted.get('partition'), str) or not isinstance(accepted.get('account'), str) or not isinstance(accepted.get('node'), str):
        raise _v2_ScorerEnvironmentError('accepted standard resources differ from the request')
    if proof['schema'] != 'case05/standard-runtime-proof/v1' or proof['image_id'] != actual_image_id or proof['task_config_sha256'] != identity['task_config_sha256'] or (proof['effective_instruction_sha256'] != identity['effective_instruction_sha256']) or (proof['nonce_sha256'] != identity['runner_nonce_sha256']) or (proof['attempt_id'] != identity['attempt_id']) or (proof['run_id'] != identity['run_id']) or (proof['program_id'] != identity['program_id']) or (proof['context_sha256'] != identity['context_sha256']):
        raise _v2_ScorerEnvironmentError('standard runtime proof does not bind the selected identity')
    runner = result['runner_context']
    if not isinstance(runner, dict) or runner.get('schema') != 'compchembench.runner-context/v2' or runner.get('dispatch_state') != 'CONSUMED' or (runner.get('task_id') != 'case-05') or (runner.get('attempt_id') != identity['attempt_id']) or (runner.get('run_id') != identity['run_id']) or (runner.get('image_id') != actual_image_id) or (runner.get('task_config_sha256') != identity['task_config_sha256']) or (runner.get('instruction_sha256') != identity['effective_instruction_sha256']) or (_v2__sha(str(runner.get('nonce', '')).encode('utf-8')) != identity['runner_nonce_sha256']) or (runner.get('case05_standard_runtime') != proof) or ('case05_standard_rejection' in runner):
        raise _v2_ScorerEnvironmentError('final standard runner context differs from the selected image/attempt')
    manifest = runner.get('artifact_manifest')
    declared = [{'source': '/app/outputs', 'destination': 'outputs', 'exclude': ''}]
    if not isinstance(manifest, dict) or set(manifest) != {'declared', 'collected', 'missing'} or manifest.get('declared') != declared or (not isinstance(manifest.get('collected'), list)) or (not isinstance(manifest.get('missing'), list)) or (runner.get('artifact_manifest_sha256') != _v2__sha(_v2__canonical(manifest))):
        raise _v2_ScorerEnvironmentError('standard runner artifact manifest is malformed or unbound')
    joins = _v2__exact(result['standard_joins'], {'reservation_sha256', 'consumption_sha256', 'permit_sha256', 'execution_binding_sha256', 'stage_manifest_sha256', 'native_plan_sha256', 'rendered_upload_manifest_sha256', 'capture_receipt_sha256', 'completed_execution_receipt_sha256', 'final_context_sha256', 'final_artifact_manifest_sha256'}, 'standard scoring joins')
    for (name, digest) in joins.items():
        _v2__digest(digest, f'standard join {name}')
    if joins['final_context_sha256'] != expected_context_sha256:
        raise _v2_ScorerEnvironmentError('standard final context differs from the external context digest')
    snapshot = result['standard_runtime_context']
    if not isinstance(snapshot, dict) or snapshot.get('schema') != 'case05/standard-runtime-context/v1' or _v2__sha(_v2__canonical(snapshot) + b'\n') != proof['context_sha256'] or (snapshot.get('identity', {}).get('attempt_id') != identity['attempt_id']) or (snapshot.get('identity', {}).get('run_id') != identity['run_id']) or (snapshot.get('identity', {}).get('image_id') != actual_image_id) or (snapshot.get('identity', {}).get('task_config_sha256') != identity['task_config_sha256']) or (snapshot.get('identity', {}).get('instruction_sha256') != identity['effective_instruction_sha256']) or (_v2__sha(str(snapshot.get('identity', {}).get('nonce', '')).encode('utf-8')) != identity['runner_nonce_sha256']) or (snapshot.get('source_closure_sha256') != proof['source_closure_sha256']) or (snapshot.get('public_inputs_sha256') != proof['public_inputs_sha256']) or (snapshot.get('profile_sha256') != proof['profile_sha256']):
        raise _v2_ScorerEnvironmentError('standard protected context snapshot differs from its proof')
    obs = result['standard_observation']
    if not isinstance(obs, dict) or obs.get('context_sha256') != proof['context_sha256'] or obs.get('observation_context_sha256') != proof['observation_context_sha256'] or (obs.get('program_id') != identity['program_id']) or (obs.get('attempt_id') != identity['attempt_id']) or (obs.get('runner_nonce_sha256') != identity['runner_nonce_sha256']) or (obs.get('challenge', {}).get('request_id') != identity['request_id']) or (obs.get('challenge', {}).get('challenge_nonce') != identity['challenge_nonce']):
        raise _v2_ScorerEnvironmentError('standard backend observation differs from protected identity')
    return identity

def _v2__validate_standard_execution_joins(result: dict[str, _v2_Any], identity: dict[str, _v2_Any]) -> tuple[dict, dict]:
    """Select already reader-validated standard capture and native plan objects."""
    capture = result['capture_receipt']
    plan = result['native_plan']
    if not isinstance(capture, dict) or capture.get('schema') != 'case05/standard-backend-capture-binding/v1' or capture.get('identity', {}).get('attempt_id') != identity['attempt_id'] or (capture.get('identity', {}).get('program_id') != identity['program_id']) or (capture.get('identity', {}).get('challenge_nonce') != identity['challenge_nonce']) or (capture.get('context_sha256') != identity['context_sha256']) or (capture.get('reservation_sha256') != result['standard_joins']['reservation_sha256']) or (capture.get('consumption_sha256') != result['standard_joins']['consumption_sha256']) or (capture.get('execution_binding_sha256') != result['standard_joins']['execution_binding_sha256']) or (capture.get('native_plan_sha256') != result['standard_joins']['native_plan_sha256']) or (capture.get('resource_request') != result['standard_runtime'].get('resource_request')) or (capture.get('resource_request_sha256') != result['standard_runtime'].get('resource_request_sha256')) or (capture.get('accepted_resources') != result['standard_runtime'].get('accepted_resources')) or (capture.get('final_artifact_manifest_sha256') != result['runner_context'].get('artifact_manifest_sha256')):
        raise _v2_ScorerEnvironmentError('standard capture receipt is not joined to the runtime proof')
    if not isinstance(plan, dict) or plan.get('schema') != _v2_PLAN_SCHEMA or plan.get('attempt_id') != identity['attempt_id'] or (plan.get('request_id') != identity['request_id']) or (plan.get('challenge_nonce') != identity['challenge_nonce']) or (plan.get('program_id') != identity['program_id']) or (plan.get('method_id') != _v2_METHOD_ID) or (plan.get('profile', {}).get('profile_id') != identity['profile_id']) or (plan.get('resource_request') != result['standard_runtime'].get('resource_request')) or (plan.get('resource_request_sha256') != result['standard_runtime'].get('resource_request_sha256')) or (plan.get('resources') != result['standard_runtime'].get('accepted_resources')):
        raise _v2_ScorerEnvironmentError('standard native plan is not joined to this runtime attempt')
    evidence = result['evidence']
    code = result['code']
    artifacts = result['artifacts']
    if not all((isinstance(value, dict) for value in (evidence, code, artifacts))):
        raise _v2_ScorerEnvironmentError('standard reader result projections are malformed')
    parser_path = 'code/parse_pyscf_v2.py'
    if identity['program_id'].startswith('pyscf-'):
        parser_bytes = code.get(parser_path)
        if not isinstance(parser_bytes, bytes) or _v2__sha(parser_bytes) != '60d1ecb8003a2495e8ee2c276b33c034ca9ab43ff1ef6e01e9514f6ec868f489':
            raise _v2_ScorerEnvironmentError('standard PySCF parser differs from the reviewed native source')
    if identity['program_id'].startswith('openmolcas-'):
        required_openmolcas_paths = {'code/case25_case05_openmolcas_native_parser_v2.py', 'code/case25_case05_openmolcas_adapter.py', 'code/case25_case05_openmolcas_ao_provider.py', 'code/case25_case05_science_protocol.py'}
        required_openmolcas_paths.add('code/case25_case05_openmolcas_bootstrap.py')
        if any((not isinstance(code.get(path), bytes) for path in required_openmolcas_paths)):
            raise _v2_ScorerEnvironmentError('standard OpenMolcas source closure is incomplete')
        _v2__validate_standard_openmolcas_bootstrap_source(result['standard_runtime_context'], code)
    return (capture, plan)

def _v2__validate_standard_openmolcas_bootstrap_source(snapshot: _v2_Any, code: _v2_Any) -> None:
    """Bind the captured standard bootstrap module to the protected context pin."""
    pins = snapshot.get('source_pins') if isinstance(snapshot, dict) else None
    raw = code.get('code/case25_case05_openmolcas_bootstrap.py') if isinstance(code, dict) else None
    expected = _v2_PINNED_OPENMOLCAS_STANDARD_BOOTSTRAP_SHA256
    if not isinstance(pins, dict) or pins.get('openmolcas_bootstrap') != expected or (not isinstance(raw, bytes)) or (_v2__sha(raw) != expected):
        raise _v2_ScorerEnvironmentError('standard OpenMolcas bootstrap differs from protected source pins')

def _v2__local_geometry_bytes() -> dict[str, bytes]:
    root = _v2_Path(__file__).resolve().parent.parent / 'inputs' / 'geometries'
    try:
        return {point: (root / f'ethene_grid_{point}.xyz').read_bytes() for point in ('A', 'B')}
    except OSError as exc:
        raise _v2_ScorerEnvironmentError('frozen public geometries are unavailable') from exc

def _v2__load_mounted_reader() -> _v2_Any:
    raw = _v2__read_local_regular(_v2_READER_SOURCE, limit=_v2_READER_MODULE_LIMIT)
    if _v2__sha(raw) != _v2_PINNED_READER_SHA256:
        raise _v2_ScorerEnvironmentError('mounted scoring reader differs from its frozen source pin')
    module = _v2_types.ModuleType('case05_frozen_scoring_reader')
    try:
        exec(compile(raw, '<frozen-case05-scoring-reader>', 'exec'), module.__dict__)
    except Exception as exc:
        raise _v2_ScorerEnvironmentError(f'mounted scoring reader cannot be loaded: {exc}') from exc
    read = getattr(module, 'read_scoring_transport', None)
    if not callable(read):
        raise _v2_ScorerEnvironmentError('mounted scoring reader lacks read_scoring_transport')
    return module

def _v2_main(argv: list[str] | None=None) -> int:
    """Offline mounted CLI. It prints status only and never assigns reward."""
    args = list(_v2_sys.argv[1:] if argv is None else argv)
    if args:
        print('ENV_ERROR: verify_v2 takes no candidate-controlled arguments')
        return 2
    try:
        publication_sha = _v2_os.environ.get('CCB_CASE05_V2_SCORING_MANIFEST_SHA256')
        context_sha = _v2_os.environ.get('CCB_CASE05_V2_RUN_CONTEXT_SHA256')
        expected_image_id = _v2_os.environ.get(_v2_RUNTIME_IMAGE_ID_ENV)
        _v2__digest(publication_sha, 'external scoring publication digest')
        _v2__digest(context_sha, 'external runner-context digest')
        reader = _v2__load_mounted_reader()
        reader_result = reader.read_scoring_transport(_v2_PROOF_ROOT, expected_publication_sha256=publication_sha, expected_context_sha256=context_sha, expected_image_id=expected_image_id)
        geometries = {point: _v2__read_local_regular(_v2_PUBLIC_GEOMETRY_ROOT / f'ethene_grid_{point}.xyz', limit=1024 * 1024) for point in ('A', 'B')}
        decision = _v2_verify_reader_result(reader_result, expected_context_sha256=context_sha, expected_image_id=expected_image_id, public_geometries=geometries)
        if decision.status == 'PASS':
            print(f'PASS: {decision.message}')
            return 0
        if decision.status == 'FAIL':
            print(f'FAIL: {decision.message}')
            return 1
        print(f'ENV_ERROR: {decision.message}')
        return 2
    except Exception as exc:
        print(f'ENV_ERROR: {type(exc).__name__}: {exc}')
        return 2

import importlib.util as _rejection_importlib
import hashlib as _rejection_hashlib
import json as _rejection_json
import os as _rejection_os
from pathlib import Path as _rejection_Path
import re as _rejection_re
import stat as _rejection_stat
import sys as _rejection_sys
_rejection_PROOF_ROOT = _rejection_Path('/trusted/case05-v2-rejection')
_rejection_READER_PATH = _rejection_Path('/scoring-code/case25_case05_rejection_reader.py')
_rejection_SCORER_PATH = _rejection_Path(__file__).resolve()
_rejection_PUBLICATION_ENV = 'CCB_CASE05_V2_REJECTION_MANIFEST_SHA256'
_rejection_CONTEXT_ENV = 'CCB_CASE05_V2_RUN_CONTEXT_SHA256'
_rejection_IMAGE_ENV = 'CCB_CASE05_RUNTIME_IMAGE_ID'
_rejection_PINNED_READER_SHA256 = '038b1ab60653393f07e87f44a20e7a0515680a458e8ff3f0e5d7dc804f444244'
_rejection__SHA = _rejection_re.compile('[0-9a-f]{64}\\Z')

def _rejection__read_local_regular(path: _rejection_Path, *, limit: int, require_readonly: bool=True) -> bytes:
    """Read an immutable trusted source through a no-follow directory-FD chain."""
    if not path.is_absolute():
        raise RuntimeError('trusted source path must be absolute')
    parts = path.parts
    if len(parts) < 2 or parts[0] != _rejection_os.sep or any((part in {'', '.', '..'} for part in parts[1:])):
        raise RuntimeError('trusted source path is not canonical')
    directory_flags = _rejection_os.O_RDONLY | getattr(_rejection_os, 'O_DIRECTORY', 0) | getattr(_rejection_os, 'O_NOFOLLOW', 0)
    leaf_flags = _rejection_os.O_RDONLY | getattr(_rejection_os, 'O_NOFOLLOW', 0) | getattr(_rejection_os, 'O_NONBLOCK', 0)
    opened_dirs: list[int] = []
    fd = -1
    try:
        current_fd = _rejection_os.open(_rejection_os.sep, directory_flags)
        opened_dirs.append(current_fd)
        for part in parts[1:-1]:
            current_fd = _rejection_os.open(part, directory_flags, dir_fd=current_fd)
            opened_dirs.append(current_fd)
        fd = _rejection_os.open(parts[-1], leaf_flags, dir_fd=current_fd)
        before = _rejection_os.fstat(fd)
        if not _rejection_stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or (require_readonly and before.st_mode & 146) or (before.st_size > limit):
            raise RuntimeError('trusted source has unsafe type, link count, mode, or size')
        chunks = []
        total = 0
        while True:
            chunk = _rejection_os.read(fd, min(65536, limit + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise RuntimeError('trusted source exceeded its size bound')
            chunks.append(chunk)
        after = _rejection_os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or total != before.st_size:
            raise RuntimeError('trusted source changed while being read')
        return b''.join(chunks)
    except OSError as exc:
        raise RuntimeError('trusted source cannot be read safely') from exc
    finally:
        if fd >= 0:
            _rejection_os.close(fd)
        for directory_fd in reversed(opened_dirs):
            _rejection_os.close(directory_fd)

def _rejection__reader_module():
    """Load only the hash-pinned reader projection supplied by the trusted runner."""
    raw = _rejection__read_local_regular(_rejection_READER_PATH, limit=2 * 1024 * 1024)
    if _rejection_hashlib.sha256(raw).hexdigest() != _rejection_PINNED_READER_SHA256:
        raise RuntimeError('trusted rejection reader differs from its reviewed source pin')
    module = _rejection_importlib.util.module_from_spec(_rejection_importlib.util.spec_from_file_location('case05_v2_rejection_reader', _rejection_READER_PATH))
    exec(compile(raw, str(_rejection_READER_PATH), 'exec'), module.__dict__)
    return (module, raw)

def _rejection__check_sealed_source_files(expected_publication_sha256: str, imported_reader_raw: bytes, running_scorer_raw: bytes, projection_scorer_raw: bytes) -> None:
    """After reader validation, bind its immutable code members to executed bytes."""
    publication_raw = _rejection__read_local_regular(_rejection_PROOF_ROOT / 'publication.json', limit=8 * 1024 * 1024)
    if _rejection_hashlib.sha256(publication_raw).hexdigest() != expected_publication_sha256:
        raise RuntimeError('verified publication changed before source binding')

    def pairs(items):
        result = {}
        for (key, value) in items:
            if key in result:
                raise ValueError('duplicate publication key')
            result[key] = value
        return result
    publication = _rejection_json.loads(publication_raw.decode('utf-8', 'strict'), object_pairs_hook=pairs)
    source_pins = publication.get('source_pins') if isinstance(publication, dict) else None
    if not isinstance(source_pins, dict):
        raise RuntimeError('verified publication source pins are unavailable')
    sealed_reader = _rejection__read_local_regular(_rejection_PROOF_ROOT / 'reader-code.py', limit=2 * 1024 * 1024)
    sealed_scorer = _rejection__read_local_regular(_rejection_PROOF_ROOT / 'scorer-code.py', limit=2 * 1024 * 1024)
    digest = _rejection_hashlib.sha256
    if running_scorer_raw != projection_scorer_raw or sealed_reader != imported_reader_raw or sealed_scorer != running_scorer_raw or (source_pins.get('rejection-reader') != digest(imported_reader_raw).hexdigest()) or (source_pins.get('verify-rejection-v2') != digest(running_scorer_raw).hexdigest()):
        raise RuntimeError('sealed reader or scorer source differs from the code that was executed')

def _rejection__running_scorer_bytes() -> bytes:
    """Read the executed script path, separately from its trusted code projection."""
    return _rejection__read_local_regular(_rejection_Path(__file__).absolute(), limit=2 * 1024 * 1024, require_readonly=False)

def _rejection__verify_scorer_projection(running_scorer_raw: bytes, projection_scorer_raw: bytes) -> None:
    if running_scorer_raw != projection_scorer_raw:
        raise RuntimeError('executed rejection scorer differs from its trusted scoring-code projection')

def _rejection_main() -> int:
    publication_sha = _rejection_os.environ.get(_rejection_PUBLICATION_ENV)
    context_sha = _rejection_os.environ.get(_rejection_CONTEXT_ENV)
    expected_image_id = _rejection_os.environ.get(_rejection_IMAGE_ENV)
    if not isinstance(publication_sha, str) or _rejection__SHA.fullmatch(publication_sha) is None or (not isinstance(context_sha, str)) or (_rejection__SHA.fullmatch(context_sha) is None) or (not isinstance(expected_image_id, str)) or (_rejection_re.fullmatch('sha256:[0-9a-f]{64}', expected_image_id) is None):
        print('ENV_INVALID: selected rejection proof lacks valid host identity', file=_rejection_sys.stderr)
        return 2
    try:
        (reader, reader_raw) = _rejection__reader_module()
        result = reader.read_standard_pre_dispatch_rejection(_rejection_PROOF_ROOT, expected_publication_sha256=publication_sha, expected_context_sha256=context_sha, expected_image_id=expected_image_id)
        if not isinstance(result, dict) or result.get('schema') != 'case05/standard-runtime-rejection-reader/v1' or result.get('verdict') != 'REJECTED' or (result.get('peer_grade') != 'FAIL0') or (result.get('scientific_computation') is not False):
            raise RuntimeError('trusted rejection reader returned an unsupported verdict')
        running_scorer_raw = _rejection__running_scorer_bytes()
        projection_scorer_raw = _rejection__read_local_regular(_rejection_SCORER_PATH, limit=2 * 1024 * 1024)
        _rejection__verify_scorer_projection(running_scorer_raw, projection_scorer_raw)
        _rejection__check_sealed_source_files(publication_sha, reader_raw, running_scorer_raw, projection_scorer_raw)
        print(_rejection_json.dumps({'status': 'FAIL0', 'reason_code': result.get('reason_code'), 'attempt_id': result.get('attempt_id')}, sort_keys=True, separators=(',', ':')))
        return 1
    except Exception as exc:
        print(f'ENV_INVALID: trusted rejection proof could not be verified: {exc}', file=_rejection_sys.stderr)
        return 2



# Static Molden audit implementation used for the fixed active-orbital diagnostics.
import argparse as _molden_argparse
import hashlib as _molden_hashlib
import json as _molden_json
import re as _molden_re
import sys as _molden_sys
from pathlib import Path as _molden_Path
_molden_np = _LegacyNumpyProxy()

def _molden_sha256(path: _molden_Path) -> str:
    h = _molden_hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def _molden_read_xyz(path: _molden_Path) -> tuple[list[str], _molden_np.ndarray]:
    lines = path.read_text().splitlines()
    n = int(lines[0].strip())
    rows = lines[2:2 + n]
    if len(rows) != n:
        raise ValueError('truncated XYZ geometry')
    symbols, xyz = ([], [])
    for row in rows:
        fields = row.split()
        if len(fields) < 4:
            raise ValueError(f'invalid XYZ row: {row!r}')
        symbols.append(fields[0].capitalize())
        xyz.append([float(v) for v in fields[1:4]])
    return (symbols, _molden_np.asarray(xyz))

def _molden_element_symbol(label: object) -> str:
    match = _molden_re.match('([A-Za-z]+)', str(label))
    return match.group(1).capitalize() if match else str(label).capitalize()

def _molden_carbon_pz_ao_indices(labels: list[tuple]) -> list[int]:
    """Accept PySCF labels like ``C`` and Molden-derived ``C1`` centers."""
    indices = []
    for i, label in enumerate(labels):
        center = str(label[1]) if len(label) > 1 else ''
        element = _molden_element_symbol(center)
        shell = str(label[2]).lower() if len(label) > 2 else ''
        component = str(label[3]).lower() if len(label) > 3 else ''
        if element.upper() == 'C' and shell.endswith('p') and (component in {'z', '0'}):
            indices.append(i)
    return indices

def _molden_audit_active_subspace(overlap: _molden_np.ndarray, active_coeff: _molden_np.ndarray, pz_indices: list[int], center_indices: list[list[int]]) -> dict:
    ssub = overlap[_molden_np.ix_(pz_indices, pz_indices)]
    pz_projector = overlap[:, pz_indices] @ _molden_np.linalg.solve(ssub, overlap[_molden_np.ix_(pz_indices, _molden_np.arange(overlap.shape[0]))])
    active_gram = active_coeff.T.conj() @ overlap @ active_coeff
    gram_eig = _molden_np.linalg.eigvalsh(active_gram)
    active_pz = active_coeff.T.conj() @ pz_projector @ active_coeff
    active_pz_eig = _molden_np.linalg.eigvalsh(active_pz)
    center_traces = []
    for center_id, idx in enumerate(center_indices):
        block = overlap[_molden_np.ix_(idx, idx)]
        pcenter = overlap[:, idx] @ _molden_np.linalg.solve(block, overlap[_molden_np.ix_(idx, _molden_np.arange(overlap.shape[0]))])
        center_traces.append({'carbon_order': center_id, 'projected_weight_trace_over_active_subspace': float(_molden_np.real(_molden_np.trace(active_coeff.T.conj() @ pcenter @ active_coeff)))})
    checks = {'active_orbital_count_is_two': active_coeff.shape[1] == 2, 'active_mos_s_orthonormal': bool(_molden_np.max(_molden_np.abs(gram_eig - 1.0)) <= 1e-06), 'active_projector_rank_is_two': bool(_molden_np.min(active_pz_eig) > 1e-08), 'both_active_directions_are_pz_dominated': bool(_molden_np.min(active_pz_eig) >= 0.8), 'both_carbon_centers_contribute': bool(all((x['projected_weight_trace_over_active_subspace'] >= 0.5 for x in center_traces)))}
    return {'active_gram_eigenvalues': [float(x) for x in gram_eig], 'active_pz_projector_matrix': _molden_np.asarray(active_pz).real.tolist(), 'active_pz_principal_projection_eigenvalues': [float(x) for x in active_pz_eig], 'carbon_center_projection_traces': center_traces, 'checks': checks, 'status': 'PI_SUBSPACE_COMPATIBLE' if all(checks.values()) else 'PI_SUBSPACE_NOT_ESTABLISHED', 'identity_scope': 'joint two-orbital subspace only; no unique pi/pi-star phase assignment'}

def _molden_unpack_molden_load_result(result: object) -> tuple[object, object, object, object, dict[str, object]]:
    """Normalize PySCF's 2.14 four/six-item Molden loader return forms.

    PySCF 2.14 appends irrep and spin metadata for some Molden files. The
    orbital audit consumes the same molecule/energy/coefficient/occupation
    objects in either form; the metadata is recorded as shape-only provenance.
    """
    if not isinstance(result, (tuple, list)) or len(result) not in {4, 6}:
        count = len(result) if isinstance(result, (tuple, list)) else 'non-sequence'
        raise ValueError(f'unsupported PySCF molden.load return shape: {count} items')
    mol, mo_energy, mo_coeff, mo_occ = result[:4]
    metadata: dict[str, object] = {'return_item_count': len(result)}
    if len(result) == 6:
        irrep_labels, spins = result[4:]
        metadata['irrep_label_channel_count'] = len(irrep_labels) if irrep_labels is not None else None
        metadata['spin_metadata_channel_count'] = len(spins) if spins is not None else None
    else:
        metadata['irrep_label_channel_count'] = None
        metadata['spin_metadata_channel_count'] = None
    return (mol, mo_energy, mo_coeff, mo_occ, metadata)

def _molden_normalize_molden_orbitals(mo_energy: object, mo_coeff: object, mo_occ: object, n_ao: int) -> tuple[_molden_np.ndarray, _molden_np.ndarray, _molden_np.ndarray, dict[str, object]]:
    """Use alpha spatial orbitals after requiring matching alpha/beta data."""
    members = (mo_energy, mo_coeff, mo_occ)
    spin_pairs = all((isinstance(item, (tuple, list)) and len(item) == 2 for item in members))
    if any((isinstance(item, (tuple, list)) for item in members)) and (not spin_pairs):
        raise ValueError('PySCF Molden spin metadata is incomplete across energy/coefficient/occupation arrays')
    if not spin_pairs:
        energy, coeff, occ = (_molden_np.asarray(item) for item in members)
        if coeff.ndim != 2 or coeff.shape[0] != n_ao or energy.ndim != 1 or (occ.ndim != 1):
            raise ValueError('Molden orbital arrays have incompatible dimensions')
        return (energy, coeff, occ, {'spin_resolved': False})
    e_alpha, e_beta = (_molden_np.asarray(x) for x in mo_energy)
    c_alpha, c_beta = (_molden_np.asarray(x) for x in mo_coeff)
    o_alpha, o_beta = (_molden_np.asarray(x) for x in mo_occ)
    if c_alpha.ndim != 2 or c_beta.shape != c_alpha.shape or c_alpha.shape[0] != n_ao or (e_alpha.ndim != 1) or (e_beta.shape != e_alpha.shape) or (o_alpha.ndim != 1) or (o_beta.shape != o_alpha.shape) or (e_alpha.shape[0] != c_alpha.shape[1]) or (o_alpha.shape[0] != c_alpha.shape[1]):
        raise ValueError('PySCF alpha/beta Molden orbital arrays have incompatible dimensions')
    differences = {'max_abs_energy_hartree': float(_molden_np.max(_molden_np.abs(e_alpha - e_beta))), 'max_abs_coefficient': float(_molden_np.max(_molden_np.abs(c_alpha - c_beta))), 'max_abs_occupation': float(_molden_np.max(_molden_np.abs(o_alpha - o_beta)))}
    tolerances = {'energy_hartree': 1e-07, 'coefficient': 1e-07, 'occupation': 1e-07}
    consistent = differences['max_abs_energy_hartree'] <= tolerances['energy_hartree'] and differences['max_abs_coefficient'] <= tolerances['coefficient'] and (differences['max_abs_occupation'] <= tolerances['occupation'])
    audit = {'spin_resolved': True, 'spatial_orbital_count': int(c_alpha.shape[1]), 'spin_orbital_record_count': int(2 * c_alpha.shape[1]), 'alpha_beta_max_abs_differences': differences, 'alpha_beta_consistency_tolerances': tolerances, 'alpha_beta_consistent': bool(consistent), 'projection_spin_channel': 'alpha; beta independently compared against the same spatial orbitals'}
    if not consistent:
        raise ValueError(f'PySCF alpha/beta spatial orbitals disagree beyond tolerance: {differences}')
    return (e_alpha, c_alpha, o_alpha, audit)

def _molden_main() -> int:
    from pyscf import __version__ as pyscf_version
    from pyscf.tools import molden
    ap = _molden_argparse.ArgumentParser()
    ap.add_argument('molden_file', type=_molden_Path)
    ap.add_argument('--geometry', type=_molden_Path, required=True, help='Exact XYZ geometry file used by the OpenMolcas calculation')
    ap.add_argument('--inactive', type=int, default=7, help='RASSCF inactive orbital count; labels expected active slots only')
    ap.add_argument('--output', type=_molden_Path)
    args = ap.parse_args()
    if pyscf_version != '2.14.0':
        raise SystemExit(f'DIAGNOSTIC_ERROR: expected PySCF 2.14.0, found {pyscf_version}')
    path = args.molden_file.resolve()
    try:
        mol, mo_energy_raw, mo_coeff_raw, mo_occ_raw, load_api = _molden_unpack_molden_load_result(molden.load(str(path), verbose=0))
    except ValueError as exc:
        raise SystemExit(f'DIAGNOSTIC_ERROR: {exc}') from exc
    overlap = _molden_np.asarray(mol.intor('int1e_ovlp'))
    labels = mol.ao_labels(fmt=False)
    pz = _molden_carbon_pz_ao_indices(labels)
    if len(pz) < 2:
        raise SystemExit(f'DIAGNOSTIC_ERROR: expected carbon pz AOs from both carbons, found {len(pz)}: {pz}')
    xyz_symbols, xyz_coords = _molden_read_xyz(args.geometry)
    molden_symbols = [_molden_element_symbol(mol.atom_symbol(i)) for i in range(mol.natm)]
    molden_coords = _molden_np.asarray(mol.atom_coords(unit='Angstrom'))
    if xyz_symbols != molden_symbols or xyz_coords.shape != molden_coords.shape:
        raise SystemExit('DIAGNOSTIC_ERROR: Molden atom list/order differs from frozen XYZ')
    max_xyz_error = float(_molden_np.max(_molden_np.abs(xyz_coords - molden_coords)))
    if max_xyz_error > 0.0001:
        raise SystemExit(f'DIAGNOSTIC_ERROR: Molden geometry differs from frozen XYZ by {max_xyz_error:.3g} Angstrom')
    if _molden_np.max(_molden_np.abs(molden_coords[:, 2] - molden_coords[0, 2])) > 0.0001:
        raise SystemExit('DIAGNOSTIC_ERROR: fixed pz audit requires the frozen planar-xy geometry')
    ssub = overlap[_molden_np.ix_(pz, pz)]
    if _molden_np.linalg.cond(ssub) > 10000000000.0:
        raise SystemExit('DIAGNOSTIC_ERROR: carbon-pz AO overlap block is singular')
    try:
        energies, coeff, occ, spin_audit = _molden_normalize_molden_orbitals(mo_energy_raw, mo_coeff_raw, mo_occ_raw, overlap.shape[0])
    except ValueError as exc:
        raise SystemExit(f'DIAGNOSTIC_ERROR: {exc}') from exc
    if coeff.ndim != 2 or coeff.shape[0] != overlap.shape[0]:
        raise SystemExit('DIAGNOSTIC_ERROR: Molden coefficient/AO dimensions disagree')
    if coeff.shape[1] <= args.inactive + 1 or len(occ) != coeff.shape[1] or len(energies) != coeff.shape[1]:
        raise SystemExit('DIAGNOSTIC_ERROR: Molden lacks expected two active MOs or consistent energies/occupations')
    projections = []
    for j in range(coeff.shape[1]):
        c = coeff[:, j]
        v = overlap[_molden_np.ix_(pz, _molden_np.arange(overlap.shape[0]))] @ c
        value = float(_molden_np.real(_molden_np.vdot(v, _molden_np.linalg.solve(ssub, v))))
        projections.append(value)
    records = [{'molden_mo_index_1based': i + 1, 'energy_hartree': float(energies[i]), 'occupation': float(occ[i]), 'carbon_pz_projector_weight': projections[i], 'rasscf_active_slot_candidate': i + 1 - args.inactive if args.inactive < i + 1 <= args.inactive + 2 else None} for i in range(coeff.shape[1])]
    carbon_centers = sorted({int(labels[i][0]) for i in pz})
    if len(carbon_centers) != 2:
        raise SystemExit(f'DIAGNOSTIC_ERROR: expected exactly two carbon centers with pz AOs, found {carbon_centers}')
    center_info = []
    for center in carbon_centers:
        idx = [i for i in pz if int(labels[i][0]) == center]
        center_info.append((center, idx, overlap[_molden_np.ix_(idx, idx)]))
    if min((len(x[1]) for x in center_info)) < 2 or len({len(x[1]) for x in center_info}) != 1:
        raise SystemExit('DIAGNOSTIC_ERROR: carbon pz radial-shell AO sets are incomplete or asymmetric')
    for j, record in enumerate(records):
        center_weights = []
        for center, idx, block in center_info:
            b = overlap[_molden_np.ix_(idx, _molden_np.arange(overlap.shape[0]))] @ coeff[:, j]
            q = _molden_np.linalg.solve(block, b)
            center_weights.append(float(_molden_np.real(_molden_np.vdot(b, q))))
        record['carbon_pz_projection_weight_by_atom'] = center_weights
        record['phase_labeling_warning'] = 'individual active-orbital phase/bonding labels are not a gate because equal-weight SA roots may rotate a degenerate active space'
    active_indices = [args.inactive, args.inactive + 1]
    active_coeff = coeff[:, active_indices]
    subspace = _molden_audit_active_subspace(overlap, active_coeff, pz, [[i for i in pz if int(labels[i][0]) == c] for c in carbon_centers])
    subspace.update({'active_mo_indices_1based': [x + 1 for x in active_indices]})
    result = {'status': 'AUDIT_ONLY', 'audit_script_sha256': _molden_sha256(_molden_Path(__file__).resolve()), 'molden_file': path.name, 'molden_sha256': _molden_sha256(path), 'geometry_file': args.geometry.name, 'geometry_sha256': _molden_sha256(args.geometry.resolve()), 'pyscf_version': pyscf_version, 'molden_load_api': load_api, 'spin_orbital_consistency': spin_audit, 'n_ao': int(overlap.shape[0]), 'n_mo': int(coeff.shape[1]), 'carbon_pz_ao_indices_zero_based': pz, 'carbon_pz_ao_count': len(pz), 'molden_geometry_max_abs_difference_angstrom': max_xyz_error, 'projection_definition': 'c^H S[:,I] (S[I,I])^-1 S[I,:] c; I includes all carbon pz radial-shell AOs on both carbon centers', 'active_orbital_subspace': subspace, 'active_slot_candidates_assuming_seven_inactive': [8, 9], 'orbitals': records, 'warning': 'Orbital indices are candidates only. Interpret the joint active-space projector and native RASSCF record; individual SA orbitals can rotate, so no unique pi/pi-star phase labels are assigned.'}
    rendered = _molden_json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered)
    else:
        _molden_sys.stdout.write(rendered)
    return 0

def _legacy_entrypoint() -> int:
    try:
        return _legacy_verify_main()
    except CandidateFail as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except ScientificCheckUnavailable as exc:
        print(f"ENV_ERROR: {exc}", file=sys.stderr)
        return 2
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
        print(f"FAIL: malformed candidate output: {exc}", file=sys.stderr)
        return 1

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--route", choices=("legacy", "v2", "rejection", "molden-audit", "openmolcas-native"), default="legacy")
    route_args, remaining = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    if route_args.route == "legacy":
        sys.argv = [sys.argv[0], *remaining]
        return _legacy_entrypoint()
    if route_args.route == "v2":
        if remaining:
            print("ENV_ERROR: v2 route does not accept candidate-controlled arguments", file=sys.stderr)
            return 2
        return _v2_main([])
    if route_args.route == "molden-audit":
        sys.argv = [sys.argv[0], *remaining]
        return _molden_main()
    if route_args.route == "openmolcas-native":
        sys.argv = [sys.argv[0], *remaining]
        return _legacy_openmolcas_main()
    if remaining:
        print("ENV_INVALID: rejection route does not accept candidate-controlled arguments", file=sys.stderr)
        return 2
    return _rejection_main()

if __name__ == "__main__":
    raise SystemExit(main())
