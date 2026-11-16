#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including report.md, geometry.xyz, result.json).
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Investigate the isolated NEO molecular model using ORCA and r2SCAN-3c.
"""Independent structural, native-evidence, and geometry checks for Case03."""
from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
import os
import re
import shlex
import sys
import types
from pathlib import Path, PurePosixPath

def _load_references():
    path = Path(__file__).with_name("refs.json")
    try:
        refs = json.loads(path.read_text(encoding="utf-8"))
        if refs.get("schema") != "case03-frozen-references/v1":
            raise ValueError("unsupported Case03 reference schema")
        inputs = refs["inputs"]
        if not isinstance(inputs, dict) or not inputs:
            raise ValueError("Case03 public input references are absent")
        hashes = {}
        for name, record in inputs.items():
            digest = record["sha256"]
            if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or record["runtime_path"] != f"assets/{name}"
                    or record["package_path"] != f"environment/assets/{name}"):
                raise ValueError("invalid Case03 public input reference")
            hashes[record["runtime_path"]] = digest
        limits = refs["resource_limits"]
        frequency = refs["frequency"]
        stability = refs["scf_stability"]
        if set(limits) != {"cores", "memory_gib", "wall_seconds", "study_cpu_seconds", "study_cpu_minutes"}:
            raise ValueError("Case03 resource limits are incomplete")
        if any(type(value) is not int or value <= 0 for value in limits.values()):
            raise ValueError("Case03 resource limits must be positive integers")
        if set(frequency) != {"expected_modes", "vibrational_mode_start_index", "clear_failure_below_cm-1", "unresolved_interval_cm-1", "failure_comparison", "unresolved_comparison"}:
            raise ValueError("Case03 frequency thresholds are incomplete")
        if set(stability) != {"expected_lowest_eigenvalues", "negative_eigenvalue_failure_threshold_eh", "failure_comparison", "exact_zero_status"}:
            raise ValueError("Case03 SCF stability thresholds are incomplete")
        mode_counts = (frequency["expected_modes"], frequency["vibrational_mode_start_index"], stability["expected_lowest_eigenvalues"])
        if any(type(value) is not int or value <= 0 for value in mode_counts):
            raise ValueError("Case03 mode counts and indexes must be positive integers")
        frequency_numbers = (frequency["clear_failure_below_cm-1"], *frequency["unresolved_interval_cm-1"])
        if (not isinstance(frequency["unresolved_interval_cm-1"], list)
                or len(frequency["unresolved_interval_cm-1"]) != 2
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in frequency_numbers)):
            raise ValueError("Case03 frequency thresholds must be finite numbers")
        stability_threshold = stability["negative_eigenvalue_failure_threshold_eh"]
        if type(stability_threshold) not in (int, float) or not math.isfinite(stability_threshold):
            raise ValueError("Case03 SCF stability threshold must be a finite number")
        energy_tolerance = refs["optimized_geometry_energy_tolerance_eh"]
        if type(energy_tolerance) not in (int, float) or not math.isfinite(energy_tolerance) or energy_tolerance <= 0:
            raise ValueError("Case03 energy tolerance must be a positive finite number")
        if frequency["failure_comparison"] != "<" or frequency["unresolved_comparison"] != "inclusive" or stability["failure_comparison"] != "<" or stability["exact_zero_status"] != "unresolved":
            raise ValueError("Case03 threshold comparison semantics are invalid")
        return refs, hashes, limits, frequency, stability, None
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return None, {}, {}, {}, {}, f"Case03 frozen references unavailable or invalid: {exc}"


CASE03_REFS, INPUT_HASHES, _RESOURCE_LIMITS, _FREQUENCY_RULES, _STABILITY_RULES, _REFERENCE_ERROR = _load_references()
ELEMENTS = {"H", "C", "N", "O"}
TASK_VERSION = "2.0"
HISTORICAL_RESULT_SHA256 = "4e4f5a019800c270364479ff6bbc38f4c18a68fb9632a916147ec3ec6f90714e"


class EnvironmentInvalid(Exception):
    pass


class ReviewRequired(Exception):
    pass


class ScientificFailure(Exception):
    pass


# --- inlined tests/trusted_execution.py (sha256 27075aaa04b6958da2e9d7e58756b472046863d82f219c7ebc454c7b2ae8d557) ---
_TRUSTED_EXECUTION_SRC = r'''"""Shared helpers for the Case03 verifier.

This edition installs no operator execution context: the verifier scores the
candidate's own evidence and reports trusted_execution=UNVERIFIED. Only the
structural and numeric helpers below are used.
"""
from __future__ import annotations

import datetime as dt
import base64
import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_CASE_ID = "case03-convergence-recovery"
EXPECTED_TASK_VERSION = "2.0"
EXPECTED_MODEL = "ORCA 6.0.1 r2SCAN-3c gas-phase neutral singlet"
TERMINAL_STATES = {
    "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY",
    "PREEMPTED", "BOOT_FAIL", "DEADLINE", "SPECIAL_EXIT",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TrustedContextError(Exception):
    """The protected installation or operator context is invalid."""


class EvidenceMismatch(Exception):
    """Candidate evidence does not match the protected operator context."""


class EvidencePending(Exception):
    """The operator context is valid but still has an unsettled operation."""


def _positive_or_zero_int(value: Any, label: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise TrustedContextError(f"operator context {label} must be an integer")
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TrustedContextError(f"operator context {label} must be a relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value or str(path) != value:
        raise TrustedContextError(f"operator context {label} is not a canonical relative path")
    return value


def _expected_attempts(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    optimization = result.get("attempts")
    if not isinstance(optimization, list):
        raise EvidenceMismatch("candidate result has no attempt list")
    for attempt in optimization:
        if not isinstance(attempt, dict):
            raise EvidenceMismatch("candidate optimization attempt is malformed")
        row = _normalize_attempt(attempt, attempt.get("name"))
        rows.append(row)
    scientific = result.get("scientific_validation")
    if scientific is not None:
        if not isinstance(scientific, dict):
            raise EvidenceMismatch("candidate scientific_validation is malformed")
        for key in ("frequency", "stability"):
            record = scientific.get(key)
            if record is None:
                continue
            if not isinstance(record, dict):
                raise EvidenceMismatch(f"candidate {key} validation record is malformed")
            row = _normalize_attempt(record, record.get("attempt_name"))
            if row["native_input"] != record.get("native_input"):
                raise EvidenceMismatch(f"candidate {key} input path is inconsistent")
            if record.get("geometry_input"):
                row["geometry_input"] = record["geometry_input"]
            if record.get("native_hessian"):
                row["native_hessian"] = record["native_hessian"]
            rows.append(row)
    return rows


def _normalize_attempt(record: dict[str, Any], name: Any) -> dict[str, Any]:
    fields = {
        "name": name,
        "job_id": record.get("job_id"),
        "scheduler_state": record.get("slurm_state"),
        "allocated_cpus": record.get("allocated_cpus"),
        "elapsed_seconds": record.get("elapsed_seconds"),
        "memory_gib": record.get("memory_gib"),
        "wall_minutes": record.get("wall_minutes"),
        "native_input": record.get("native_input"),
        "native_output": record.get("native_output"),
        "scheduler_submission": record.get("scheduler_submission"),
        "scheduler_accounting_raw": record.get("scheduler_accounting_raw"),
        "slurm_accounting": record.get("slurm_accounting"),
    }
    if record.get("native_geometry_input"):
        fields["geometry_input"] = record["native_geometry_input"]
    charge = fields["allocated_cpus"] * max(1, (fields["elapsed_seconds"] + 59) // 60) \
        if type(fields["allocated_cpus"]) is int and type(fields["elapsed_seconds"]) is int else None
    fields["charged_cpu_minutes"] = charge
    fields["reserved_cpu_minutes"] = 0
    if any(value is None for key, value in fields.items()
           if key not in {"geometry_input", "charged_cpu_minutes"}):
        raise EvidenceMismatch(f"candidate {name!r} lacks complete attempt and scheduler fields")
    return fields


def _digest_in_app(app: Path, relative: str) -> str:
    path = app / relative
    lexical = app
    for part in PurePosixPath(relative).parts:
        lexical = lexical / part
        if lexical.is_symlink():
            raise EvidenceMismatch(f"candidate payload contains a symlink: {relative}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(app.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise EvidenceMismatch(f"candidate payload path is missing or escapes APP: {relative}") from exc
    if not resolved.is_file():
        raise EvidenceMismatch(f"candidate payload is not a regular file: {relative}")
    h = hashlib.sha256()
    with resolved.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _candidate_files(result: dict[str, Any]) -> dict[str, str]:
    entries = result.get("native_artifacts")
    if not isinstance(entries, list) or not entries:
        raise EvidenceMismatch("candidate native_artifacts is not a non-empty list")
    files: dict[str, str] = {}
    for row in entries:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise EvidenceMismatch("candidate native artifact manifest entry is malformed")
        try:
            path = _safe_relative(row["path"], "candidate native artifact path")
        except TrustedContextError as exc:
            raise EvidenceMismatch(str(exc)) from exc
        digest = row.get("sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest) or path in files:
            raise EvidenceMismatch(f"candidate native artifact entry is malformed or duplicated: {path}")
        files[path] = digest
    return files


'''
# --- inlined tests/candidate_provenance.py (sha256 5a963e8677c2f3d99dd4fe8904ae9d401d8d49a59f48c90391e9f2ee97b56d92) ---
_CANDIDATE_PROVENANCE_SRC = r'''"""Cross-check candidate-submitted scheduler provenance (not independent attestation)."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath


SCHEMA = "bench23-candidate-submission/v1"
ASSURANCE = "ARTIFACT_CROSSCHECKED_NOT_INDEPENDENTLY_CERTIFIED"
_JOB = re.compile(r"^[0-9]+$")
_ALLOC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


class CandidateProvenanceError(ValueError):
    pass


def _fail(message: str) -> None:
    raise CandidateProvenanceError(message)


def _strict_json(text: str) -> object:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value
    def finite(token):
        raise ValueError(f"non-finite JSON value: {token}")
    try:
        return json.loads(text, object_pairs_hook=unique, parse_constant=finite)
    except (TypeError, ValueError) as exc:
        _fail(f"invalid candidate JSON: {exc}")


def _safe_path(root: Path, item: object, indexed: dict[str, Path]) -> Path:
    if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
        _fail("candidate submission file reference must contain exactly path and sha256")
    rel, digest = item["path"], item["sha256"]
    if (not isinstance(rel, str) or not rel or not isinstance(digest, str)
            or not _HASH.fullmatch(digest)):
        _fail("candidate submission file reference has an invalid path or digest")
    posix = PurePosixPath(rel)
    if posix.is_absolute() or ".." in posix.parts or "\\" in rel or str(posix) != rel:
        _fail("candidate submission artifact path is not a safe relative path")
    path = root / rel
    cursor = root
    for part in posix.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _fail("candidate submission artifact paths cannot contain symlinks")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        _fail("candidate submission artifact is missing or escapes its root")
    if not resolved.is_file() or rel not in indexed or indexed[rel].resolve() != resolved:
        _fail("candidate submission artifact is not a regular indexed artifact")
    try:
        digest_actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError as exc:
        _fail(f"candidate submission artifact is unreadable: {rel} ({type(exc).__name__})")
    if digest_actual != digest:
        _fail(f"candidate submission artifact digest mismatch: {rel}")
    return resolved


def _exit(value: object) -> str:
    if type(value) is int and value >= 0:
        return f"{value}:0"
    if isinstance(value, str) and re.fullmatch(r"(?:0|[1-9][0-9]*):(?:0|[1-9][0-9]*)", value):
        return value
    _fail("exit_code must be a nonnegative integer or canonical code:signal text")


def _positive_int(value: object, label: str, *, zero: bool = False) -> int:
    if type(value) is not int or value < (0 if zero else 1):
        _fail(f"{label} must be an integer")
    return value


def _time(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        _fail(f"{label} must be a timezone-qualified ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(f"{label} must be a timezone-qualified ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(f"{label} must include a timezone")
    return parsed


def _raw_scheduler_record(path: Path, job_id: str) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="strict").strip()
    except (OSError, UnicodeError) as exc:
        _fail(f"scheduler raw log is unreadable: {type(exc).__name__}")
    try:
        value = _strict_json(text)
        if isinstance(value, dict):
            return value
    except (ValueError, json.JSONDecodeError):
        pass
    rows = [line.split("|") for line in text.splitlines() if line.strip()]
    if len(rows) < 2:
        _fail("scheduler raw log must contain a header and one allocation row")
    headers = [x.strip() for x in rows[0]]
    if len({header.casefold() for header in headers}) != len(headers):
        _fail("scheduler raw log contains duplicate headers")
    matches = [row for row in rows[1:] if row and row[0].strip() == job_id]
    if len(matches) != 1 or len(matches[0]) != len(headers):
        _fail("scheduler raw log must contain exactly one matching allocation row")
    return dict(zip(headers, (x.strip() for x in matches[0])))


def _raw_get(raw: dict, *names: str):
    present = [(name, raw[name]) for name in names if name in raw]
    if not present:
        return None
    def normalize(value):
        if "ExitCode" in names or "exit_code" in names:
            try:
                return _exit(value)
            except CandidateProvenanceError:
                return str(value).strip()
        if any(name in names for name in ("AllocCPUS", "allocated_cpus", "cpus", "AllocMemMB", "memory_mb", "AllocGPUS", "gpus")):
            return int(value) if type(value) is int or isinstance(value, str) and value.isdigit() else str(value).strip()
        if any(name in names for name in ("State", "state", "final_state")):
            return str(value).strip().upper()
        return str(value).strip() if value is not None else None
    if len({normalize(value) for _, value in present}) > 1:
        _fail(f"raw scheduler aliases conflict: {', '.join(name for name, _ in present)}")
    return present[0][1]


def _elapsed(value: object) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str):
        if value.isdigit():
            return int(value)
        match = re.fullmatch(r"(?:(\d+)-)?(\d{1,2}):(\d{2}):(\d{2})", value)
        if match:
            days, hours, minutes, seconds = match.groups()
            return (((int(days or 0) * 24 + int(hours)) * 60 + int(minutes)) * 60 + int(seconds))
    _fail("raw scheduler elapsed time has an unsupported format")


def _alloc_tres(value: object) -> tuple[int | None, int | None, int]:
    if not isinstance(value, str):
        return None, None, 0
    cpu_matches = re.findall(r"(?:^|,)cpu=(\d+)(?=,|$)", value)
    if len(set(cpu_matches)) > 1:
        _fail("raw scheduler AllocTRES contains conflicting CPU counts")
    mem_matches = re.findall(r"(?:^|,)mem=(\d+)([KMGTP])(?:i?B)?(?=,|$)", value, re.IGNORECASE)
    mem_values = {round(int(amount) * {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024**2, "P": 1024**3}[unit.upper()])
                  for amount, unit in mem_matches}
    if len(mem_values) > 1:
        _fail("raw scheduler AllocTRES contains conflicting memory values")
    gpu_aggregate = re.findall(r"(?:^|,)gres/gpu=(\d+)(?=,|$)", value, re.IGNORECASE)
    gpu_typed = re.findall(r"(?:^|,)gres/gpu:[A-Za-z0-9_.-]+=(\d+)(?=,|$)", value, re.IGNORECASE)
    gpu_generic = re.findall(r"(?:^|,)gpu=(\d+)(?=,|$)", value, re.IGNORECASE)
    gpu_counts = [*gpu_aggregate, *gpu_typed, *gpu_generic]
    if any(int(count) > 0 for count in gpu_counts):
        _fail("GPU allocations are outside the frozen CPU-only resource contract")
    gpu_matches = [*gpu_aggregate, *gpu_generic]
    if len(set(gpu_matches)) > 1:
        _fail("raw scheduler AllocTRES contains conflicting GPU totals")
    if gpu_aggregate and gpu_typed and int(gpu_aggregate[0]) != sum(map(int, gpu_typed)):
        _fail("raw scheduler AllocTRES GPU aggregate disagrees with typed GPU counts")
    if not gpu_matches:
        gpu_matches = gpu_typed
    if re.search(r"gpu|gres/gpu", value, re.IGNORECASE) and not gpu_matches:
        _fail("raw scheduler AllocTRES contains an unsupported GPU field")
    cpus = int(cpu_matches[0]) if cpu_matches else None
    memory_mb = next(iter(mem_values)) if mem_values else None
    return cpus, memory_mb, int(gpu_matches[0]) if gpu_matches else 0


def validate_submission(app: Path, result: dict, indexed: dict[str, Path]) -> list[str]:
    """Require cross-checkable records for every declared candidate allocation."""
    submission = result.get("candidate_submission")
    expected: dict[str, dict] = {}
    optimization_order: list[str] = []
    artifact_hashes = {item.get("path"): item.get("sha256") for item in result.get("native_artifacts", [])
                       if isinstance(item, dict)}
    attempts = result.get("attempts")
    if isinstance(attempts, list):
        for record in attempts:
            if isinstance(record, dict) and isinstance(record.get("job_id"), str):
                if not isinstance(record.get("native_output"), str) or not record["native_output"]:
                    _fail("every optimization attempt requires a hash-bound native_output")
                expected[record["job_id"]] = {"name": str(record.get("name", "")),
                    "state": record.get("slurm_state"), "cpus": record.get("allocated_cpus"),
                    "memory_mb": record.get("memory_gib", 0) * 1024 if type(record.get("memory_gib")) in (int, float) else None,
                    "wall_seconds": record.get("elapsed_seconds"), "native_output": record.get("native_output"),
                    "native_output_sha256": artifact_hashes.get(record.get("native_output"))}
                optimization_order.append(record["job_id"])
    scientific = result.get("scientific_validation")
    if isinstance(scientific, dict):
        for name in ("frequency", "stability"):
            record = scientific.get(name)
            if isinstance(record, dict) and isinstance(record.get("job_id"), str):
                if not isinstance(record.get("native_output"), str) or not record["native_output"]:
                    _fail(f"{name} validation requires a hash-bound native_output")
                expected[record["job_id"]] = {"name": str(record.get("attempt_name", name)),
                    "state": record.get("slurm_state"), "cpus": record.get("allocated_cpus"),
                    "memory_mb": record.get("memory_gib", 0) * 1024 if type(record.get("memory_gib")) in (int, float) else None,
                    "wall_seconds": record.get("elapsed_seconds"), "native_output": record.get("native_output"),
                    "native_output_sha256": artifact_hashes.get(record.get("native_output"))}
    ledger_snapshot = result.get("budget_snapshot")
    if isinstance(ledger_snapshot, dict) and isinstance(ledger_snapshot.get("path"), str):
        ledger_path = indexed.get(ledger_snapshot["path"])
        if ledger_path is not None:
            try:
                ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeError):
                ledger = {}
            extras = ledger.get("additional_billing_records", []) if isinstance(ledger, dict) else []
            if isinstance(extras, list):
                for record in extras:
                    if isinstance(record, dict) and isinstance(record.get("job_id"), str):
                        expected[record["job_id"]] = {"name": str(record.get("name", "additional-billing")),
                            "state": record.get("scheduler_state"), "cpus": record.get("allocated_cpus"),
                            "memory_mb": record.get("memory_gib", 0) * 1024 if type(record.get("memory_gib")) in (int, float) else None,
                            "wall_seconds": record.get("elapsed_seconds"), "native_output": None,
                            "native_output_sha256": None}

    if submission is None:
        _fail("candidate_submission is required, including an explicit no_remote_executions declaration")
    if not isinstance(submission, dict) or submission.get("schema") != SCHEMA:
        _fail("candidate_submission schema is unsupported")
    if ("status" in submission and submission["status"] != "CANDIDATE_SUBMITTED"
            or "assurance" in submission and submission["assurance"] != ASSURANCE):
        _fail("candidate submission contains contradictory grader-owned labels")
    order = submission.get("execution_order")
    if not isinstance(order, list):
        _fail("candidate_submission.execution_order must be an array")
    if submission.get("no_remote_executions") is True:
        if order or expected:
            _fail("no_remote_executions conflicts with declared allocation records")
        return ["candidate explicitly declared no remote executions"]
    if not expected:
        _fail("an empty execution_order requires no_remote_executions=true")
    if set(expected) != {item.get("job_id") for item in order if isinstance(item, dict)}:
        _fail("execution_order does not exactly cover result attempts and validation allocations")
    if len(order) != len(expected):
        _fail("execution_order contains duplicate or extra allocation records")
    seen_allocations: set[str] = set()
    seen_names: set[str] = set()
    checks = []
    starts: dict[str, datetime] = {}
    claimed_native_outputs: dict[str, str] = {}
    for item in order:
        if not isinstance(item, dict):
            _fail("execution_order entries must be objects")
        job_id = item.get("job_id")
        if not isinstance(job_id, str) or not _JOB.fullmatch(job_id):
            _fail("job_id must be a numeric non-array scheduler ID")
        allocation_id = item.get("allocation_id")
        name = item.get("attempt_name")
        if not isinstance(allocation_id, str) or not _ALLOC.fullmatch(allocation_id) or not isinstance(name, str) or not name:
            _fail("execution_order requires attempt_name and allocation_id")
        expected_job = expected.get(job_id)
        if not expected_job or expected_job["name"] != name:
            _fail("execution_order attempt/job identity differs from result.json")
        if allocation_id in seen_allocations or job_id in seen_names:
            _fail("execution_order repeats an allocation or job ID")
        seen_allocations.add(allocation_id); seen_names.add(job_id)
        files = item.get("files")
        required_files = {"receipt", "scheduler_record", "scheduler_raw_log", "batch_script", "stdout", "stderr"}
        if set(item) != {"attempt_name", "job_id", "allocation_id", "files"}:
            _fail("execution_order entries contain unsupported fields")
        if not isinstance(files, dict) or set(files) != required_files:
            _fail("execution_order files must index receipt, scheduler record/log, batch script, stdout, and stderr")
        paths = {key: _safe_path(app, ref, indexed) for key, ref in files.items()}
        try:
            receipt = _strict_json(paths["receipt"].read_text(encoding="utf-8"))
            record = _strict_json(paths["scheduler_record"].read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            _fail(f"receipt or scheduler_record is invalid JSON: {exc}")
        if not isinstance(receipt, dict) or not isinstance(record, dict):
            _fail("receipt and scheduler_record must be JSON objects")
        required = {"job_id", "scheduler", "allocation_id", "gpus", "cpus", "memory_mb", "wall_seconds", "exit_code", "batch_script_sha256"}
        if set(receipt) not in (required, required | {"native_outputs"}):
            _fail("receipt fields do not match the candidate allocation schema")
        native_outputs = receipt.get("native_outputs", [])
        if not isinstance(native_outputs, list):
            _fail("receipt.native_outputs must be a hash-indexed array")
        native_refs = []
        native_seen = set()
        for ref in native_outputs:
            native_path = _safe_path(app, ref, indexed)
            key = (ref["path"], ref["sha256"])
            if key in native_seen:
                _fail("receipt.native_outputs repeats a file reference")
            native_seen.add(key)
            native_refs.append(key)
        expected_output = expected_job.get("native_output")
        if expected_output is not None:
            if expected_output in claimed_native_outputs and claimed_native_outputs[expected_output] != job_id:
                _fail("one scientific native_output is claimed by multiple scheduler jobs")
            claimed_native_outputs[expected_output] = job_id
            expected_ref = (expected_output, expected_job.get("native_output_sha256"))
            stdout_ref = (files["stdout"]["path"], files["stdout"]["sha256"])
            if (expected_ref[1] is None or (stdout_ref != expected_ref and expected_ref not in native_refs)):
                _fail("job native_output is not bound by stdout or receipt.native_outputs")
        elif native_refs:
            _fail("an allocation without a declared native_output cannot add native_outputs")
        scheduler_required = required - {"batch_script_sha256"} | {"final_state", "start_time", "end_time", "raw_scheduler_log"}
        if set(record) != scheduler_required:
            _fail("scheduler_record fields do not match the candidate allocation schema")
        if (receipt["job_id"] != job_id or record["job_id"] != job_id
                or receipt["allocation_id"] != allocation_id or record["allocation_id"] != allocation_id
                or not isinstance(receipt["scheduler"], str) or not receipt["scheduler"]
                or record["scheduler"] != receipt["scheduler"]):
            _fail("receipt and scheduler_record identity fields disagree")
        if receipt["batch_script_sha256"] != files["batch_script"]["sha256"]:
            _fail("receipt batch script digest does not match its indexed batch script")
        if not isinstance(allocation_id, str) or not _ALLOC.fullmatch(allocation_id):
            _fail("allocation_id has array/step or unsupported syntax")
        for field, zero in (("gpus", True), ("cpus", False), ("memory_mb", False), ("wall_seconds", True)):
            expected_value = _positive_int(receipt[field], f"receipt.{field}", zero=zero)
            if _positive_int(record[field], f"scheduler_record.{field}", zero=zero) != expected_value:
                _fail(f"receipt and scheduler_record {field} disagree")
        if _exit(receipt["exit_code"]) != _exit(record["exit_code"]):
            _fail("receipt and scheduler_record exit codes disagree")
        if receipt["gpus"] != 0:
            _fail("receipt.gpus must be zero for the frozen CPU-only resource contract")
        if receipt["scheduler"] != "slurm":
            _fail("scheduler must be slurm for this task")
        if record["raw_scheduler_log"] != files["scheduler_raw_log"]:
            _fail("scheduler_record raw log reference differs from indexed scheduler_raw_log")
        raw = _raw_scheduler_record(paths["scheduler_raw_log"], job_id)
        raw_job = _raw_get(raw, "JobIDRaw", "job_id", "jobid")
        raw_state = _raw_get(raw, "State", "state", "final_state")
        raw_exit = _raw_get(raw, "ExitCode", "exit_code")
        raw_start = _raw_get(raw, "Start", "start_time")
        raw_end = _raw_get(raw, "End", "end_time")
        if str(raw_job) != job_id or raw_state != record["final_state"] or _exit(raw_exit) != _exit(record["exit_code"]):
            _fail("raw scheduler log identity, terminal state, or exit code disagrees")
        if expected_job["state"] is not None and raw_state != expected_job["state"]:
            _fail("raw scheduler state differs from the candidate's task result")
        if raw_start != record["start_time"] or raw_end != record["end_time"]:
            _fail("raw scheduler log timestamps disagree with scheduler_record")
        start, end = _time(record["start_time"], "start_time"), _time(record["end_time"], "end_time")
        elapsed = (end - start).total_seconds()
        if elapsed < 0 or abs(elapsed - receipt["wall_seconds"]) > 1:
            _fail("scheduler timestamps disagree with allocated wall_seconds")
        raw_elapsed = _raw_get(raw, "ElapsedRaw", "elapsed_seconds", "elapsed")
        raw_cpus = _raw_get(raw, "AllocCPUS", "allocated_cpus", "cpus")
        raw_gpus = _raw_get(raw, "gpus", "AllocGPUS")
        raw_tres = _raw_get(raw, "AllocTRES", "alloc_tres")
        tres_cpus, tres_memory, tres_gpus = _alloc_tres(raw_tres)
        effective_cpus = (raw_cpus if type(raw_cpus) is int else
                          int(raw_cpus) if isinstance(raw_cpus, str) and raw_cpus.isdigit() else tres_cpus)
        raw_memory = _raw_get(raw, "memory_mb", "AllocMemMB")
        effective_memory = (raw_memory if type(raw_memory) is int else
                            int(raw_memory) if isinstance(raw_memory, str) and raw_memory.isdigit() else tres_memory)
        normalized_cpus = (raw_cpus if type(raw_cpus) is int else
                           int(raw_cpus) if isinstance(raw_cpus, str) and raw_cpus.isdigit() else None)
        normalized_memory = (raw_memory if type(raw_memory) is int else
                             int(raw_memory) if isinstance(raw_memory, str) and raw_memory.isdigit() else None)
        normalized_gpus = (raw_gpus if type(raw_gpus) is int else
                           int(raw_gpus) if isinstance(raw_gpus, str) and raw_gpus.isdigit() else None)
        if ((normalized_cpus is not None and tres_cpus is not None and normalized_cpus != tres_cpus)
                or (normalized_memory is not None and tres_memory is not None and normalized_memory != tres_memory)
                or (normalized_gpus is not None and normalized_gpus != tres_gpus)):
            _fail("raw scheduler resource fields contradict their AllocTRES values")
        raw_alloc = _raw_get(raw, "AllocationID", "allocation_id")
        array_id = _raw_get(raw, "ArrayJobID", "array_job_id")
        if raw_alloc is not None and str(raw_alloc) not in ("", "N/A", allocation_id):
            _fail("raw scheduler AllocationID differs from the declared allocation")
        if array_id is not None and str(array_id) not in ("", "N/A", "0"):
            _fail("scheduler array allocation records are not supported")
        effective_gpus = tres_gpus
        if (raw_elapsed is None or _elapsed(raw_elapsed) != receipt["wall_seconds"]
                or effective_cpus != receipt["cpus"]
                or effective_memory is None or effective_memory != receipt["memory_mb"]
                or effective_gpus != receipt["gpus"]):
            _fail("raw scheduler resources or elapsed time disagree with the receipt")
        if (expected_job["cpus"] is not None and receipt["cpus"] != expected_job["cpus"]
                or expected_job["memory_mb"] is not None and receipt["memory_mb"] != expected_job["memory_mb"]
                or expected_job["wall_seconds"] is not None and receipt["wall_seconds"] != expected_job["wall_seconds"]):
            _fail("receipt resources exceed or disagree with result.json declarations")
        starts[job_id] = start
        checks.append(f"candidate allocation {job_id} record and indexed batch artifacts agree")
    ordered_optimization = [row["job_id"] for row in order if row["job_id"] in set(optimization_order)]
    if ordered_optimization != optimization_order:
        _fail("execution_order changes the declared sequential optimization/recovery order")
    if any(starts[a] > starts[b] for a, b in zip(optimization_order, optimization_order[1:])):
        _fail("scheduler timestamps contradict optimization/recovery order")
    return checks
'''

def _load_inlined_module(name: str, filename: str, source: str):
    """Load one of this verifier's inlined helpers in its own module namespace.

    ``__file__`` names the helper's original path in this tests directory, so helpers
    that resolve sibling files (for example ``refs.json``) keep working.
    """
    module = types.ModuleType(name)
    module.__file__ = str(Path(__file__).with_name(filename))
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    sys.modules[name] = module
    return module


trusted_execution = _load_inlined_module(
    "case03_trusted_execution", "trusted_execution.py", _TRUSTED_EXECUTION_SRC)
candidate_provenance = _load_inlined_module(
    "case03_candidate_provenance", "candidate_provenance.py", _CANDIDATE_PROVENANCE_SRC)


def scope_assertions_line(claims: dict) -> str:
    return ("Scope assertions: "
            f"local_model_only={str(claims['local_model_only']).lower()}; "
            f"experimental_bound_state_established={str(claims['experimental_bound_state_established']).lower()}; "
            f"global_tautomer_optimum_established={str(claims['global_tautomer_optimum_established']).lower()}; "
            f"recovery_exercised={str(claims['recovery_exercised']).lower()}")


def validate_scope_claims(result: dict, report: str) -> list[str]:
    claims = result.get("scope_claims")
    if "scope_claims" not in result:
        raise ReviewRequired("structured scope_claims are absent; v1 scope declarations are not accepted by task version 2.0")
    required = {"local_model_only", "experimental_bound_state_established",
                "global_tautomer_optimum_established", "recovery_exercised"}
    if not isinstance(claims, dict) or set(claims) != required:
        raise ValueError("scope_claims must contain exactly the four frozen Boolean assertions")
    if any(type(claims[key]) is not bool for key in required):
        raise ValueError("scope_claims values must be JSON Booleans")
    if claims["local_model_only"] is not True:
        raise ScientificFailure("scope claim exceeds the supplied local molecular model")
    if claims["experimental_bound_state_established"] is not False:
        raise ScientificFailure("the frozen evidence does not establish the experimental bound state")
    if claims["global_tautomer_optimum_established"] is not False:
        raise ScientificFailure("the frozen evidence does not establish a global tautomer optimum")
    if claims["recovery_exercised"] is not result.get("recovery_exercised"):
        raise ValueError("scope recovery_exercised assertion disagrees with the result and native attempt list")
    line = scope_assertions_line(claims)
    marker = "Scope assertions:"
    marker_count = report.count(marker)
    if marker_count:
        marked_lines = [row.strip() for row in report.splitlines() if marker in row]
        if marker_count != 1 or marked_lines != [line]:
            raise ValueError("optional scope-assertion line must appear once and match result.json")
    return ["structured scope assertions are consistent with the report and native recovery state"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def cif_loops(path: Path) -> list[list[dict[str, str]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    loops = []
    i = 0
    while i < len(lines):
        if lines[i].strip() != "loop_":
            i += 1
            continue
        i += 1
        headers = []
        while i < len(lines) and lines[i].lstrip().startswith("_"):
            headers.append(lines[i].strip())
            i += 1
        rows = []
        while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith("#") and lines[i].strip() != "loop_" and not lines[i].lstrip().startswith("_"):
            fields = shlex.split(lines[i], posix=True)
            if len(fields) != len(headers):
                raise EnvironmentInvalid("CCD CIF contains a wrapped or malformed atom/bond row")
            rows.append(dict(zip(headers, fields)))
            i += 1
        loops.append(rows)
    return loops


def parse_xyz(path: Path) -> tuple[list[str], list[tuple[float, float, float]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        n = int(lines[0].strip())
    except Exception as exc:
        raise ValueError(f"{path.name}: invalid XYZ atom count") from exc
    if n < 1 or len(lines) != n + 2:
        raise ValueError(f"{path.name}: declared atom count does not match coordinate rows")
    symbols, coords = [], []
    for line in lines[2:]:
        f = line.split()
        if len(f) != 4 or f[0] not in ELEMENTS:
            raise ValueError(f"{path.name}: invalid XYZ atom row")
        xyz = tuple(float(x) for x in f[1:])
        if not all(math.isfinite(x) for x in xyz):
            raise ValueError(f"{path.name}: non-finite coordinate")
        symbols.append(f[0]); coords.append(xyz)
    return symbols, coords


def xyz_distance(a, b) -> float:
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


def same_oriented_geometry(a, b, tolerance: float = 1e-3) -> bool:
    """Compare atom-ordered geometries modulo translation/proper rotation."""
    if len(a) != len(b) or len(a) < 4:
        return False
    for i in range(len(a)):
        for j in range(i):
            if abs(xyz_distance(a[i], a[j]) - xyz_distance(b[i], b[j])) > tolerance:
                return False
    def volume(points, ids):
        p0, p1, p2, p3 = (points[i] for i in ids)
        x = tuple(p0[k] - p3[k] for k in range(3))
        y = tuple(p1[k] - p3[k] for k in range(3))
        z = tuple(p2[k] - p3[k] for k in range(3))
        return (x[0] * (y[1] * z[2] - y[2] * z[1])
                - x[1] * (y[0] * z[2] - y[2] * z[0])
                + x[2] * (y[0] * z[1] - y[1] * z[0]))
    for ids in itertools.combinations(range(len(a)), 4):
        va, vb = volume(a, ids), volume(b, ids)
        if abs(va) > 1e-3:
            return abs(va - vb) <= tolerance
    return False


def extract_orca_final_xyz(text: str) -> tuple[list[str], list[tuple[float, float, float]]]:
    lines = text.splitlines()
    sections = []
    for i, line in enumerate(lines):
        if "CARTESIAN COORDINATES (ANGSTROEM)" not in line.upper():
            continue
        symbols, coords = [], []
        for row in lines[i+1:]:
            fields = row.split()
            if not fields or set(row.strip()) == {"-"}:
                if symbols:
                    break
                continue
            if len(fields) != 4 or fields[0] not in ELEMENTS:
                if symbols:
                    break
                continue
            try:
                xyz = tuple(float(x) for x in fields[1:])
            except ValueError:
                if symbols:
                    break
                continue
            if not all(math.isfinite(x) for x in xyz):
                break
            symbols.append(fields[0]); coords.append(xyz)
        if symbols:
            sections.append((symbols, coords))
    if not sections:
        raise ValueError("hash-verified ORCA output contains no Cartesian Angstrom coordinate block")
    return sections[-1]


def optimizer_convergence_table(text: str) -> dict[str, tuple[float, float, bool]]:
    matches = list(re.finditer(r"Geometry convergence", text, re.I))
    if not matches:
        raise ValueError("native ORCA output has no geometry convergence table")
    section = text[matches[-1].start():]
    aliases = {
        "energy_change": "Energy change", "rms_gradient": "RMS gradient",
        "max_gradient": "MAX gradient", "rms_step": "RMS step", "max_step": "MAX step",
    }
    result = {}
    for key, label in aliases.items():
        pattern = rf"(?im)^\s*{re.escape(label)}\s+([-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?)\s+([-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?)\s+(YES|NO)\s*$"
        rows = re.findall(pattern, section)
        if len(rows) != 1:
            raise ValueError(f"native ORCA final convergence table must contain exactly one {label} row; found {len(rows)}")
        value, tolerance, passed = rows[0]
        result[key] = (float(value), float(tolerance), passed == "YES")
    return result


def parse_supported_opt_input(text: str) -> dict[str, object]:
    """Parse the small, public ORCA optimization-input grammar used by v2.

    Supported: one `! r2SCAN-3c Opt TightSCF` directive, optional harmless
    comments/spacing, one `%maxcore N`, one `%pal nprocs N end`, one `%geom`
    block containing only `MaxIter N`, and one `* xyzfile 0 1 PATH` record.
    Unknown instructions and duplicate blocks/keywords are unresolved syntax.
    """
    lines = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("$"):
            raise ReviewRequired("ORCA $-directives and job wrappers are outside the published finite input grammar")
        lines.append(line)
    directives = [x for x in lines if x.startswith("!")]
    if len(directives) != 1 or re.sub(r"\s+", " ", directives[0][1:].strip()).casefold() != "r2scan-3c opt tightscf":
        raise ReviewRequired("ORCA optimization input uses unsupported or duplicate method directives")
    maxcore, pal, geom, coord = [], [], [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("!"):
            i += 1; continue
        if re.match(r"(?i)^%maxcore\b", line):
            maxcore.append(line); i += 1; continue
        if re.match(r"(?i)^%pal\b", line):
            pal.append(line); i += 1; continue
        if re.match(r"(?i)^%geom\s*$", line):
            body = []
            i += 1
            while i < len(lines) and lines[i].casefold() != "end":
                body.append(lines[i]); i += 1
            if i == len(lines):
                raise ReviewRequired("ORCA %geom block is unterminated")
            geom.append(body); i += 1; continue
        if line.startswith("*"):
            coord.append(line); i += 1; continue
        raise ReviewRequired(f"unsupported ORCA optimization instruction: {line}")
    if len(maxcore) != 1 or len(pal) != 1 or len(geom) != 1 or len(coord) != 1:
        raise ReviewRequired("ORCA optimization input has missing or duplicate supported declarations")
    mc = re.fullmatch(r"(?i)%maxcore\s+(\d+)", maxcore[0])
    pp = re.fullmatch(r"(?i)%pal\s+nprocs\s+(\d+)\s+end", pal[0])
    if not mc or not pp:
        raise ReviewRequired("ORCA %maxcore/%pal declaration is outside the supported syntax")
    geom_keywords = {}
    for row in geom[0]:
        match = re.fullmatch(r"(?i)MaxIter\s+(\d+)", row)
        if not match or "maxiter" in geom_keywords:
            raise ReviewRequired("ORCA %geom contains an unknown or duplicate instruction")
        geom_keywords["maxiter"] = int(match.group(1))
    if "maxiter" not in geom_keywords:
        raise ReviewRequired("ORCA %geom omits MaxIter")
    xyz = re.fullmatch(r"(?i)\*\s+xyzfile\s+(-?\d+)\s+(\d+)\s+(\S+)\s*", coord[0])
    if not xyz:
        raise ReviewRequired("ORCA coordinate declaration is outside the supported xyzfile syntax")
    if int(xyz.group(1)) != 0 or int(xyz.group(2)) != 1:
        raise ScientificFailure("ORCA input changed the fixed conditional neutral-singlet state")
    return {"method": "r2scan-3c opt tightscf", "maxcore": int(mc.group(1)),
            "nprocs": int(pp.group(1)), "maxiter": geom_keywords["maxiter"],
            "charge": int(xyz.group(1)), "multiplicity": int(xyz.group(2)),
            "coordinate_file": xyz.group(3)}


def final_single_point_energy(text: str, label: str) -> float:
    matches = re.findall(r"(?im)^\s*FINAL SINGLE POINT ENERGY\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)\s*$", text)
    if not matches:
        raise ReviewRequired(f"{label} native output lacks a parseable FINAL SINGLE POINT ENERGY")
    energy = float(matches[-1])
    if not math.isfinite(energy):
        raise ReviewRequired(f"{label} native final energy is non-finite")
    return energy


def parse_frequency_modes(text: str, expected_count: int | None = None) -> list[tuple[int, float]]:
    expected_count = expected_count if expected_count is not None else _FREQUENCY_RULES["expected_modes"]
    headers = list(re.finditer(r"VIBRATIONAL FREQUENCIES", text, re.I))
    if not headers:
        raise ReviewRequired("native frequency output has no VIBRATIONAL FREQUENCIES section")
    section = text[headers[-1].end():]
    modes = []
    for line in section.splitlines():
        match = re.match(r"^\s*(\d+)\s*:\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)\s+cm\*\*-1\b", line, re.I)
        if match:
            modes.append((int(match.group(1)), float(match.group(2))))
        elif modes and re.search(r"NORMAL MODES|IR SPECTRUM|RAMAN SPECTRUM", line, re.I):
            break
    if len(modes) != expected_count or [i for i, _ in modes] != list(range(expected_count)):
        raise ReviewRequired(f"frequency evidence must contain {expected_count} sequential modes; found {len(modes)} rows")
    if not all(math.isfinite(freq) for _, freq in modes):
        raise ReviewRequired("frequency list contains a non-finite mode")
    return modes


def parse_hessian_frequencies(text: str, expected_count: int | None = None) -> list[float]:
    expected_count = expected_count if expected_count is not None else _FREQUENCY_RULES["expected_modes"]
    section = re.search(r"(?ms)^\$vibrational_frequencies\s*\n(.*?)(?=^\$|\Z)", text)
    if not section:
        raise ReviewRequired("native ORCA .hess file has no vibrational-frequency section")
    lines = section.group(1).splitlines()
    if not lines or not re.fullmatch(r"\s*\d+\s*", lines[0]) or int(lines[0].strip()) != expected_count:
        raise ReviewRequired(f"native ORCA .hess frequency count is not {expected_count}")
    modes = []
    for line in lines[1:]:
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 2 or not fields[0].isdigit():
            raise ReviewRequired("native ORCA .hess indexed-frequency row is malformed")
        try:
            index = int(fields[0]); value = float(fields[1].replace("D", "E").replace("d", "e"))
        except ValueError as exc:
            raise ReviewRequired("native ORCA .hess indexed-frequency row is malformed") from exc
        modes.append((index, value))
    if [i for i, _ in modes] != list(range(expected_count)) or not all(math.isfinite(x) for _, x in modes):
        raise ReviewRequired(f"native ORCA .hess must contain {expected_count} finite indexed frequencies; found {len(modes)} rows")
    values = [value for _, value in modes]
    matrix = re.search(r"(?ms)^\$hessian\s*\n\s*(\d+)\s*\n(.*?)(?=^\$|\Z)", text)
    if not matrix or int(matrix.group(1)) != expected_count:
        raise ReviewRequired(f"native ORCA .hess file lacks the complete {expected_count}-coordinate Hessian section")
    hessian = [[None] * expected_count for _ in range(expected_count)]
    columns = []
    for line in matrix.group(2).splitlines():
        fields = line.split()
        if not fields:
            continue
        # ORCA writes the matrix in column blocks: an integer column header,
        # followed by indexed rows with one value per active column.
        if all(re.fullmatch(r"\d+", x) for x in fields):
            candidate = [int(x) for x in fields]
            if candidate and all(0 <= x < expected_count for x in candidate) and len(candidate) <= 6:
                columns = candidate
                continue
        if not columns or not re.fullmatch(r"\d+", fields[0]):
            raise ReviewRequired("native ORCA .hess matrix contains an unrecognized row/header")
        row = int(fields[0])
        if not 0 <= row < expected_count or len(fields) != len(columns) + 1:
            raise ReviewRequired("native ORCA .hess matrix row dimensions are inconsistent")
        for column, token in zip(columns, fields[1:]):
            try:
                value = float(token.replace("D", "E").replace("d", "e"))
            except ValueError as exc:
                raise ReviewRequired("native ORCA .hess matrix has a malformed value") from exc
            if not math.isfinite(value) or hessian[row][column] is not None:
                raise ReviewRequired("native ORCA .hess matrix has a non-finite or duplicate element")
            hessian[row][column] = value
    if any(value is None for row in hessian for value in row):
        raise ReviewRequired("native ORCA .hess matrix is incomplete")
    if any(abs(hessian[i][j] - hessian[j][i]) > 1e-7 for i in range(expected_count) for j in range(i)):
        raise ReviewRequired("native ORCA .hess matrix is not symmetric")
    return values


def parse_hessian_atoms(text: str) -> tuple[list[str], list[tuple[float, float, float]]]:
    section = re.search(r"(?ms)^\$atoms\s*\n(.*?)(?=^\$|\Z)", text)
    if not section:
        raise ReviewRequired("native ORCA .hess file has no atom-coordinate section")
    lines = section.group(1).splitlines()
    if not lines or not lines[0].strip().isdigit():
        raise ReviewRequired("native ORCA .hess atom count is malformed")
    count = int(lines[0].strip())
    symbols, coords = [], []
    for line in lines[1:]:
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 5 or fields[0] not in ELEMENTS:
            raise ReviewRequired("native ORCA .hess atom row is malformed")
        try:
            mass, xyz = float(fields[1]), tuple(float(x.replace("D", "E").replace("d", "e")) for x in fields[2:])
        except ValueError as exc:
            raise ReviewRequired("native ORCA .hess atom row is malformed") from exc
        if not math.isfinite(mass) or mass <= 0 or not all(math.isfinite(x) for x in xyz):
            raise ReviewRequired("native ORCA .hess atom row contains non-finite coordinates or mass")
        symbols.append(fields[0]); coords.append(xyz)
    if len(symbols) != count:
        raise ReviewRequired(f"native ORCA .hess declares {count} atoms but contains {len(symbols)} rows")
    return symbols, coords


def classify_frequency_modes(modes: list[tuple[int, float]], expected_count: int | None = None) -> None:
    expected_count = expected_count if expected_count is not None else _FREQUENCY_RULES["expected_modes"]
    if len(modes) != expected_count or [i for i, _ in modes] != list(range(expected_count)):
        raise ReviewRequired(f"frequency evidence must contain {expected_count} sequential modes")
    trans = [freq for _, freq in modes[:6]]
    vibrational = [freq for _, freq in modes[_FREQUENCY_RULES["vibrational_mode_start_index"] - 1:]]
    if any(x != 0.0 for x in trans):
        raise ReviewRequired("projected translational/rotational modes must be printed as zero by the preregistered ProjectTR protocol")
    failure_threshold = _FREQUENCY_RULES["clear_failure_below_cm-1"]
    unresolved_low, unresolved_high = _FREQUENCY_RULES["unresolved_interval_cm-1"]
    strongly_imaginary = [x for x in vibrational if x < failure_threshold]
    numerically_ambiguous = [x for x in vibrational if unresolved_low <= x <= unresolved_high]
    if strongly_imaginary:
        raise ScientificFailure(f"frequency analysis found a clear imaginary vibrational mode ({min(strongly_imaginary):.2f} cm-1)")
    if numerically_ambiguous:
        raise ReviewRequired("frequency analysis contains a small negative or zero mode; retain INCONCLUSIVE pending the preregistered tighter recheck")


def parse_stability_eigenvalues(text: str) -> list[float]:
    """Parse the numbered three-root block printed by ORCA 6.0.1."""
    sections = list(re.finditer(r"(?im)^\s*WAVEFUNCTION STABILITY ANALYSIS\s*$", text))
    if not sections:
        raise ReviewRequired("native SCF output lacks the ORCA wavefunction-stability analysis section")
    start = sections[-1].end()
    end_match = re.search(r"(?im)^\s*TOTAL SCF ENERGY\s*$", text[start:])
    block = text[start:start + end_match.start()] if end_match else text[start:]
    if not re.search(r"(?im)^\s*\*\*\*\s*CONVERGENCE OF RESIDUAL NORM REACHED\s*\*\*\*\s*$", block):
        raise ReviewRequired("native SCF stability eigensolver did not report residual-norm convergence")
    header = re.search(r"(?im)^\s*The eigenvalues of the stability matrix:\s*$", block)
    if not header:
        raise ReviewRequired("native SCF stability section lacks the ORCA stability-matrix eigenvalue table")
    values = []
    for line in block[header.end():].splitlines():
        if not line.strip():
            if values:
                break
            continue
        match = re.fullmatch(r"\s*E\(\s*(\d+)\s*\)\s*=\s*([-+]?(?:\d+\.\d*|\.\d+)(?:[Ee][-+]?\d+)?)\s+Eh\s*", line, re.I)
        if not match:
            if values:
                break
            continue
        root = int(match.group(1))
        if root != len(values):
            raise ReviewRequired("ORCA stability eigenvalue roots are missing, duplicated, or out of order")
        values.append(float(match.group(2)))
    if len(values) != 3:
        raise ReviewRequired("native SCF stability analysis must print exactly the three requested indexed roots")
    residuals = re.findall(r"(?im)^\s*Maximum residual norm\s*:\s*([-+]?(?:\d+\.\d*|\.\d+)(?:[Ee][-+]?\d+)?)\s*$", block)
    if not residuals or not math.isfinite(float(residuals[-1])):
        raise ReviewRequired("native SCF stability analysis lacks a finite final maximum residual norm")
    return values


def parse_stability_conclusion(text: str) -> str:
    sections = list(re.finditer(r"(?im)^\s*WAVEFUNCTION STABILITY ANALYSIS\s*$", text))
    if not sections:
        raise ReviewRequired("native SCF output lacks the ORCA wavefunction-stability analysis section")
    start = sections[-1].end()
    end_match = re.search(r"(?im)^\s*TOTAL SCF ENERGY\s*$", text[start:])
    block = text[start:start + end_match.start()] if end_match else text[start:]
    conclusions = re.findall(r"(?im)^\s*The stability analysis shows that the wavefunction is (stable|unstable)\s*$", block)
    if len(conclusions) != 1:
        raise ReviewRequired("native SCF stability analysis lacks one unambiguous stable/unstable conclusion")
    return conclusions[0].lower()


def require_restricted_closed_shell_reference(text: str) -> None:
    """Bind the default ORCA RHF type to the neutral singlet DFT reference."""
    hftypes = re.findall(r"(?im)^\s*Hartree-Fock type\s+HFTyp\s+\.\.\.\.\s+(\w+)\s*$", text)
    charges = re.findall(r"(?im)^\s*Total Charge\s+Charge\s+\.\.\.\.\s+([-+]?\d+)\s*$", text)
    multiplicities = re.findall(r"(?im)^\s*Multiplicity\s+Mult\s+\.\.\.\.\s+(\d+)\s*$", text)
    method = re.findall(r"(?im)^\s*Density Functional\s+Method\s+\.\.\.\.\s+([^\n]+)$", text)
    functionals = re.findall(r"(?im)^\s*Functional name\s+\.\.\.\.\s+([^\n]+)$", text)
    if (len(hftypes) != 1 or hftypes[0].upper() not in {"RHF", "RKS"}
            or charges != ["0"] or multiplicities != ["1"]
            or len(method) != 1 or "DFT" not in method[0].upper()
            or not any("Re-regularized SCAN exchange" in value for value in functionals)
            or not any("Re-regularized SCAN correlation" in value for value in functionals)):
        raise ReviewRequired("native ORCA settings do not establish a restricted neutral-singlet r2SCAN DFT reference")


def classify_stability_eigenvalues(values: list[float]) -> None:
    if len(values) != _STABILITY_RULES["expected_lowest_eigenvalues"] or not all(math.isfinite(x) for x in values):
        raise ReviewRequired("SCF stability evidence must contain three finite lowest eigenvalues")
    if any(x < _STABILITY_RULES["negative_eigenvalue_failure_threshold_eh"] for x in values):
        raise ScientificFailure(f"SCF stability analysis found a negative eigenvalue ({min(values):.8g} Eh)")
    if any(x == _STABILITY_RULES["negative_eigenvalue_failure_threshold_eh"] for x in values):
        raise ReviewRequired("SCF stability analysis contains a zero eigenvalue; sign is numerically unresolved")


def source_contract(app: Path) -> tuple[dict[str, dict], list[dict], dict[str, tuple[float, float, float]], dict]:
    assets = app / "assets"
    for relative, expected in INPUT_HASHES.items():
        p = app / relative
        if p.is_symlink() or not p.is_file() or sha256(p) != expected:
            raise EnvironmentInvalid(f"declared public source is missing, redirected, or hash-mismatched: {relative}")
    loops = cif_loops(assets / "NEO.cif")
    atom_rows = next((r for r in loops if r and "_chem_comp_atom.atom_id" in r[0]), None)
    bond_rows = next((r for r in loops if r and "_chem_comp_bond.atom_id_1" in r[0]), None)
    if not atom_rows or not bond_rows or len(atom_rows) != 29:
        raise EnvironmentInvalid("NEO CCD source atom/bond tables are missing or malformed")
    atoms = {}
    coords = {}
    for row in atom_rows:
        name = row["_chem_comp_atom.atom_id"]
        atoms[name] = {"element": row["_chem_comp_atom.type_symbol"], "charge": row["_chem_comp_atom.charge"],
                       "stereo": row["_chem_comp_atom.pdbx_stereo_config"]}
        coords[name] = tuple(float(row[f"_chem_comp_atom.model_Cartn_{axis}"]) for axis in "xyz")
    bonds = [{"a": r["_chem_comp_bond.atom_id_1"], "b": r["_chem_comp_bond.atom_id_2"],
              "order": r["_chem_comp_bond.value_order"]} for r in bond_rows]
    if len(bonds) != 30 or any(b["a"] not in atoms or b["b"] not in atoms for b in bonds):
        raise EnvironmentInvalid("NEO CCD bond table is inconsistent")
    pdb_atoms = {}
    for line in (assets / "1BR5_NEO_A_500.pdb").read_text().splitlines():
        if line.startswith("HETATM") and line[17:20] == "NEO" and line[21] == "A" and line[22:26].strip() == "500":
            name = line[12:16].strip()
            pdb_atoms[name] = {"element": line[76:78].strip(),
                               "xyz": tuple(float(line[i:i+8]) for i in (30, 38, 46))}
    if len(pdb_atoms) != 18 or any(atoms[n]["element"] != pdb_atoms[n]["element"] for n in pdb_atoms):
        raise EnvironmentInvalid("declared 1BR5 NEO A 500 heavy-atom identity input is malformed")
    return atoms, bonds, coords, pdb_atoms


def _input_file_checks(app: Path) -> list[str]:
    a_symbols, _ = parse_xyz(app / "assets/1br5_candidate.xyz")
    expected = {"C": 9, "H": 11, "N": 5, "O": 4}
    counts = {e: a_symbols.count(e) for e in expected}
    if len(a_symbols) != 29 or counts != expected:
        raise EnvironmentInvalid(f"candidate XYZ element inventory differs from declared NEO formula: {counts}")
    return ["public-input hashes and NEO formula agree"]


def resolve_inside(root: Path, relative: str) -> Path:
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts or not relative:
        raise ValueError(f"artifact path must be relative and may not contain '..': {relative!r}")
    if root.is_symlink():
        raise ValueError("artifact root may not be a symlink")
    lexical = root
    for part in p.parts:
        lexical = lexical / part
        if lexical.is_symlink():
            raise ValueError(f"artifact path contains a symlink: {relative}")
    target = lexical.resolve(strict=True)
    if root.resolve() not in target.parents or not target.is_file():
        raise ValueError(f"artifact is missing, redirected, or outside /app: {relative}")
    return target


def validate_attempt_energy(attempt: dict, attempts: list[dict], native_energy: float,
                           final_convergence: dict) -> None:
    """Only the accepted final geometry is bound to final_convergence energy."""
    if attempt is not attempts[-1]:
        return
    final_energy = final_convergence.get("final_energy_Eh")
    if (type(final_energy) not in (int, float) or not math.isfinite(final_energy)
            or abs(native_energy - float(final_energy)) > 1e-6):
        raise ValueError(f"{attempt['name']} native final energy contradicts the frozen optimized-state energy")


def validate_recovery_geometry_chain(attempts: list[dict], artifacts: dict[str, Path]) -> None:
    """Bind each recovery's starting XYZ to the preceding native final geometry."""
    for previous, current in zip(attempts, attempts[1:]):
        geometry_path = current.get("native_geometry_input")
        if not isinstance(geometry_path, str) or geometry_path not in artifacts:
            raise ReviewRequired(f"{current['name']} lacks a hash-verified starting geometry linked to the preceding attempt")
        input_text = artifacts[current["native_input"]].read_text(errors="replace")
        xyz_ref = re.search(r"(?im)^\s*\*\s*xyzfile\s+0\s+1\s+(\S+)\s*$", input_text)
        if not xyz_ref or Path(xyz_ref.group(1)).name != Path(geometry_path).name:
            raise ValueError(f"{current['name']} ORCA input does not name its hash-verified recovery geometry")
        symbols, coords = parse_xyz(artifacts[geometry_path])
        prior_symbols, prior_coords = extract_orca_final_xyz(
            artifacts[previous["native_output"]].read_text(errors="replace"))
        if (symbols != prior_symbols or len(coords) != len(prior_coords)
                or any(xyz_distance(a, b) > 1.0e-3 for a, b in zip(coords, prior_coords))):
            raise ValueError(f"{current['name']} starting geometry is not the preceding attempt's native final geometry")


def initial_candidate_geometry_artifact(native_input: str, coordinate_name: str,
                                        artifacts: dict[str, Path], public_candidate: Path) -> Path:
    """Bind the initial xyzfile to its own manifest-listed stage artifact."""
    reference = PurePosixPath(coordinate_name)
    if reference.is_absolute() or not reference.parts or ".." in reference.parts:
        raise ValueError("initial ORCA xyzfile reference must be a safe relative path")
    input_path = PurePosixPath(native_input)
    if input_path.is_absolute() or ".." in input_path.parts or not input_path.parts:
        raise ValueError("initial ORCA input path is not a safe manifest path")
    same_stage = (input_path.parent / reference).as_posix()
    if same_stage in artifacts:
        return artifacts[same_stage]
    # Historical inputs used input.xyz without a same-stage manifest entry.
    # Keep that narrow path only when the public source is the unique fallback.
    if reference.name in {"input.xyz", "1br5_candidate.xyz"}:
        legacy_matches = [path for rel, path in artifacts.items()
                          if PurePosixPath(rel).name == reference.name
                          and ("geometry" in rel or "input_xyz" in rel)]
        if not legacy_matches:
            return public_candidate
        if len(legacy_matches) == 1:
            return legacy_matches[0]
    raise ValueError("initial xyzfile does not resolve to one same-stage manifest artifact")


def load_manifest(app: Path, result: dict) -> tuple[dict[str, Path], list[str]]:
    entries = result.get("native_artifacts")
    if not isinstance(entries, list) or not entries:
        raise ValueError("result.json native_artifacts must be a non-empty list")
    found, messages = {}, []
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
            raise ValueError("malformed native-artifact manifest entry")
        path = resolve_inside(app, item["path"])
        if sha256(path) != item["sha256"]:
            raise ValueError(f"native artifact SHA-256 mismatch: {item['path']}")
        if item["path"] in found:
            raise ValueError(f"duplicate native artifact: {item['path']}")
        found[item["path"]] = path
        messages.append(f"hash verified: {item['path']}")
    return found, messages


def validate_l1(app: Path) -> tuple[list[str], dict, dict]:
    result_path = app / "result.json"
    try:
        preliminary = json.loads(result_path.read_text())
    except Exception as exc:
        raise ValueError("result.json is missing or malformed") from exc
    safe_stop_declared = "safe_stop" in preliminary
    required = ["report.md", "result.json"]
    if not safe_stop_declared:
        required.extend(("geometry.xyz", "atom_mapping.json"))
    missing = [x for x in required if not (app / x).is_file() or (app / x).is_symlink()]
    if missing:
        raise ValueError(f"missing required deliverables: {', '.join(missing)}")
    result = preliminary
    mapping_path = app / "atom_mapping.json"
    if safe_stop_declared and not mapping_path.exists():
        mapping = {"schema": "case03-atom-map/v2", "safe_stop_without_final_model": True}
    else:
        mapping = json.loads(mapping_path.read_text())
    result.setdefault("task_version", TASK_VERSION)
    result.setdefault("schema", "case03-result/v2")
    mapping.setdefault("schema", "case03-atom-map/v2")
    if (result.get("task_version") != TASK_VERSION or result.get("schema") != "case03-result/v2"
            or mapping.get("schema") != "case03-atom-map/v2"):
        raise ValueError("unsupported result or atom-mapping schema")
    result.setdefault("evaluation_scope", {
            "model": "ORCA 6.0.1 r2SCAN-3c gas-phase neutral singlet",
            "recovery_attempts_max": 2,
            "native_authenticity": "unverified",
            "recovery_coverage": "finite-normal-stop-only"})
    if result.get("evaluation_scope") != {
            "model": "ORCA 6.0.1 r2SCAN-3c gas-phase neutral singlet",
            "recovery_attempts_max": 2,
            "native_authenticity": "unverified",
            "recovery_coverage": "finite-normal-stop-only"}:
        raise ValueError("evaluation_scope does not match the self-contained Case03 v2 contract")
    if result.get("decision") not in {"accept", "reject"}:
        raise ValueError("decision must be accept or reject")
    if safe_stop_declared and result.get("decision") != "reject":
        raise ValueError("safe_stop evidence requires decision=reject")
    for term in ("engine", "method", "charge_spin", "connectivity_source", "convergence_thresholds", "attempts", "recovery_exercised", "native_artifacts"):
        if term not in result:
            raise ValueError(f"result.json missing required field: {term}")
    for term, object_field in (("engine", "name"), ("method", "description")):
        value = result[term]
        valid_text = isinstance(value, str) and bool(value.strip())
        valid_object = (isinstance(value, dict) and isinstance(value.get(object_field), str)
                        and bool(value[object_field].strip()))
        if not (valid_text or valid_object):
            raise ValueError(f"result.json {term} must be a nonempty string or contain a nonempty {object_field}")
    source = result["connectivity_source"]
    if not isinstance(source, str) or not source.strip():
        raise ValueError("result.json connectivity_source must be a nonempty string")
    if not isinstance(result["recovery_exercised"], bool) or not isinstance(result["attempts"], list):
        raise ValueError("result.json recovery_exercised/attempts has wrong type")
    charge_spin = result.get("charge_spin")
    if (not isinstance(charge_spin, dict)
            or type(charge_spin.get("charge")) is not int or charge_spin["charge"] != 0
            or type(charge_spin.get("multiplicity")) is not int or charge_spin["multiplicity"] != 1
            or not isinstance(charge_spin.get("rationale"), str) or not charge_spin["rationale"].strip()):
        raise ValueError("conditional charge 0/singlet choice and a nonempty rationale must be explicit")
    thresholds = result.get("convergence_thresholds")
    if not isinstance(thresholds, list) or not thresholds or any(
            not isinstance(t, dict) or not isinstance(t.get("name"), str) or not t["name"].strip()
            or (type(t.get("value")) is not int
                and (type(t.get("value")) is not float or not math.isfinite(t["value"])))
            or not isinstance(t.get("unit"), str) or not t["unit"].strip() for t in thresholds):
        raise ValueError("convergence thresholds must have named numeric values and explicit units")
    report = (app / "report.md").read_text()
    if not report.strip():
        raise ValueError("report.md must be nonempty")
    if not isinstance(result.get("scope_limitations"), str) or not result["scope_limitations"].strip():
        raise ReviewRequired("scope_limitations are absent; model boundaries are not documented")
    validate_scope_claims(result, report)
    return ["required outputs and frozen scientific fields are present"], result, mapping


SAFE_STOP_STATES = {
    "scheduler_failed": "FAILED",
    "scheduler_timeout": "TIMEOUT",
    "scheduler_cancelled": "CANCELLED",
    "scheduler_out_of_memory": "OUT_OF_MEMORY",
}


def validate_safe_stop(app: Path, result: dict, artifacts: dict[str, Path]) -> list[str]:
    """Verify an abnormal no-final-model stop without requiring fabricated geometry."""
    stop = result.get("safe_stop")
    if not isinstance(stop, dict) or set(stop) != {
            "schema", "reason_code", "attempt_name", "observed_terminal_state", "no_final_model"}:
        raise ReviewRequired("safe_stop does not match the published no-final-model schema")
    state = SAFE_STOP_STATES.get(stop.get("reason_code"))
    if (stop.get("schema") != "case03-safe-stop/v1" or stop.get("attempt_name") != "initial"
            or stop.get("no_final_model") is not True or state is None
            or stop.get("observed_terminal_state") != state):
        raise ReviewRequired("safe_stop reason and observed scheduler terminal state do not match")
    if (app / "geometry.xyz").exists() or (app / "geometry.xyz").is_symlink():
        raise ValueError("safe_stop claims no final model but geometry.xyz is present")
    attempts = result.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != 1 or attempts[0].get("name") != "initial":
        raise ReviewRequired("safe_stop supports only the initial terminal event and no recovery")
    attempt = attempts[0]
    if (attempt.get("job_id") is None or str(attempt.get("slurm_state")) != state
            or attempt.get("normal_termination") is not False or attempt.get("converged") is not False
            or attempt.get("next_action") is not None or attempt.get("native_geometry_input") is not None):
        raise ReviewRequired("safe_stop attempt flags do not describe its declared abnormal terminal event")
    if "final_convergence" in result or "scientific_validation" in result:
        raise ValueError("no-final-model safe_stop must omit final_convergence and scientific_validation")
    cpus, elapsed = attempt.get("allocated_cpus"), attempt.get("elapsed_seconds")
    wall, memory = attempt.get("wall_minutes"), attempt.get("memory_gib")
    if (type(cpus) is not int or cpus < 1 or type(elapsed) is not int
            or elapsed < 0 or type(wall) is not int or wall < 1
            or elapsed > wall * 60 or type(memory) is not int or memory < 1):
        raise ValueError("safe_stop resource declaration is malformed")
    roles = {item.get("path"): item.get("role") for item in result.get("native_artifacts", []) if isinstance(item, dict)}
    if "final_geometry" in roles.values():
        raise ValueError("safe_stop cannot declare a final_geometry artifact")
    required = {"native_input": "engine_input", "native_output": "engine_output",
                "scheduler_submission": "scheduler_submission", "scheduler_accounting_raw": "scheduler_accounting_raw",
                "slurm_accounting": "scheduler_accounting"}
    for field, role in required.items():
        path = attempt.get(field)
        if not isinstance(path, str) or path not in artifacts or roles.get(path) != role:
            raise ReviewRequired(f"safe_stop lacks manifest-listed {role} evidence")
    output = artifacts[attempt["native_output"]].read_text(errors="replace")
    if "ORCA TERMINATED NORMALLY" in output.upper() or re.search(r"THE OPTIMIZATION HAS CONVERGED", output, re.I):
        raise ValueError("safe_stop contradicts native ORCA successful termination evidence")
    if not re.search(r"(?m)^\s*" + re.escape(str(attempt["job_id"])) + r"(?:;[^\s]+)?\s*$",
                     artifacts[attempt["scheduler_submission"]].read_text(errors="replace")):
        raise ValueError("safe_stop job ID is absent from preserved sbatch response")
    parsed = json.loads(artifacts[attempt["slurm_accounting"]].read_text())
    if (not isinstance(parsed, dict) or str(parsed.get("job_id")) != str(attempt["job_id"])
            or parsed.get("state") != state or type(parsed.get("allocated_cpus")) is not int
            or parsed.get("allocated_cpus") != cpus or type(parsed.get("elapsed_seconds")) is not int
            or parsed.get("elapsed_seconds") != elapsed):
        raise ValueError("safe_stop structured Slurm receipt contradicts the declared terminal event")
    raw = [line.split("|") for line in artifacts[attempt["scheduler_accounting_raw"]].read_text(errors="replace").splitlines()]
    matching = [row for row in raw if row and row[0].strip() == str(attempt["job_id"])]
    if len(matching) != 1 or len(matching[0]) != 4:
        raise ReviewRequired("safe_stop requires exactly one four-column native sacct record")
    raw_state, raw_elapsed, raw_cpus = matching[0][1].strip().split()[0], matching[0][2].strip(), matching[0][3].strip()
    if raw_state != state or not raw_elapsed.isdigit() or not raw_cpus.isdigit() or int(raw_elapsed) != elapsed or int(raw_cpus) != cpus:
        raise ValueError("safe_stop raw sacct output contradicts its terminal state or allocation")
    snapshot = result.get("budget_snapshot")
    budget_roles = {p for p, role in roles.items() if role == "budget_ledger"}
    if (not isinstance(snapshot, dict) or set(snapshot) != {"path", "charged_cpu_minutes", "reserved_cpu_minutes", "limit_cpu_minutes"}
            or snapshot.get("path") not in artifacts or snapshot.get("path") not in budget_roles):
        raise ReviewRequired("safe_stop requires a manifest-listed shared budget ledger")
    ledger = json.loads(artifacts[snapshot["path"]].read_text())
    rows = ledger.get("attempts") if isinstance(ledger, dict) else None
    charge = cpus * max(1, (elapsed + 59) // 60)
    if (ledger.get("schema") != "case03-budget/v1" or type(ledger.get("limit_cpu_minutes")) is not int
            or not isinstance(rows, list) or len(rows) != 1 or ledger.get("additional_billing_records", [])
            or type(snapshot.get("limit_cpu_minutes")) is not int
            or type(snapshot.get("reserved_cpu_minutes")) is not int or snapshot.get("reserved_cpu_minutes") != 0
            or type(snapshot.get("charged_cpu_minutes")) is not int or snapshot.get("charged_cpu_minutes") != charge):
        raise ReviewRequired("safe_stop budget ledger is missing, unsettled, or outside the frozen charge contract")
    row = rows[0]
    if (not isinstance(row, dict) or set(row) != {"name", "job_id", "state", "scheduler_state", "allocated_cpus",
                                                   "elapsed_seconds", "charged_cpu_minutes", "reserved_cpu_minutes"}
            or str(row.get("job_id")) != str(attempt["job_id"]) or row.get("name") != "initial"
            or row.get("state") != "settled" or row.get("scheduler_state") != state
            or type(row.get("allocated_cpus")) is not int or row.get("allocated_cpus") != cpus
            or type(row.get("elapsed_seconds")) is not int or row.get("elapsed_seconds") != elapsed
            or type(row.get("charged_cpu_minutes")) is not int or row.get("charged_cpu_minutes") != charge
            or type(row.get("reserved_cpu_minutes")) is not int or row.get("reserved_cpu_minutes") != 0):
        raise ValueError("safe_stop ledger row does not reconcile with raw terminal scheduler evidence")
    return ["no-final-model stop verified from terminal scheduler evidence and reconciled budget"]


def validate_l2(app: Path, result: dict, artifacts: dict[str, Path]) -> list[str]:
    attempts = result["attempts"]
    names = [a.get("name") for a in attempts if isinstance(a, dict)]
    expected_order = ["initial", "recovery-1", "recovery-2"][:len(names)]
    if names != expected_order or not 1 <= len(attempts) <= 3:
        raise ValueError("attempt sequence must be initial followed by zero to two ordered recoveries")
    if result["recovery_exercised"] != (len(attempts) > 1):
        raise ValueError("recovery_exercised disagrees with the actual attempt list")
    engine = result.get("engine", {})
    if engine.get("name", "").lower() != "orca" or engine.get("version") != "6.0.1":
        raise ValueError("runtime contract requires the located ORCA 6.0.1 RELEASE executable")
    attempt_tolerances: dict[str, float] = {}
    parsed_inputs: list[dict[str, object]] = []
    native_tables: list[dict[str, tuple[float, float, bool]]] = []
    job_ids: set[str] = set()
    for attempt_index, attempt in enumerate(attempts):
        is_final_attempt = attempt_index == len(attempts) - 1
        cores = attempt.get("allocated_cpus")
        elapsed = attempt.get("elapsed_seconds")
        if type(cores) is not int or cores < 1 or type(elapsed) is not int or elapsed < 0:
            raise ValueError(f"{attempt['name']} has invalid Slurm allocation or elapsed wall time")
        wall_minutes = attempt.get("wall_minutes")
        if type(wall_minutes) is not int or wall_minutes < 1 or elapsed > wall_minutes * 60:
            raise ValueError(f"{attempt['name']} exceeded or omitted its declared Slurm wall-time")
        if type(attempt.get("memory_gib")) is not int or attempt["memory_gib"] < 1:
            raise ValueError(f"{attempt['name']} is missing its memory declaration")
        if not attempt.get("job_id") or not attempt.get("slurm_state") or not attempt.get("reason"):
            raise ValueError(f"{attempt['name']} lacks a Slurm job ID or terminal state")
        if str(attempt["job_id"]) in job_ids:
            raise ValueError("scientific attempts reuse a Slurm job ID")
        job_ids.add(str(attempt["job_id"]))
        if attempt.get("slurm_state") != "COMPLETED":
            raise ValueError(f"{attempt['name']} was not a completed Slurm job")
        if not is_final_attempt and attempt.get("normal_termination") is not True:
            raise ReviewRequired("automated recovery scoring currently requires a normal-terminated intermediate ORCA optimization")
        native_input = attempt.get("native_input")
        if native_input not in artifacts:
            raise ValueError(f"{attempt['name']} native engine input is absent from the artifact manifest")
        accounting_path = attempt.get("slurm_accounting")
        if accounting_path not in artifacts:
            raise ValueError(f"{attempt['name']} Slurm accounting file is absent from native_artifacts")
        accounting = json.loads(artifacts[accounting_path].read_text())
        if (str(accounting.get("job_id")) != str(attempt["job_id"])
                or accounting.get("state") != attempt["slurm_state"]
                or accounting.get("allocated_cpus") != cores
                or accounting.get("elapsed_seconds") != elapsed):
            raise ValueError(f"{attempt['name']} reported scheduler accounting contradicts result.json")
        submission_path = attempt.get("scheduler_submission")
        accounting_raw_path = attempt.get("scheduler_accounting_raw")
        if submission_path not in artifacts or accounting_raw_path not in artifacts:
            raise ValueError(f"{attempt['name']} lacks raw sbatch/sacct output in its artifact manifest")
        submission_text = artifacts[submission_path].read_text(errors="replace")
        if not re.search(rf"(?m)^\s*{re.escape(str(attempt['job_id']))}(?:;[^\s]+)?\s*$", submission_text):
            raise ValueError(f"{attempt['name']} job ID is not present in the preserved sbatch response")
        raw_rows = [line.split("|") for line in artifacts[accounting_raw_path].read_text(errors="replace").splitlines()]
        raw_row = next((r for r in raw_rows if len(r) >= 4 and r[0].strip() == str(attempt["job_id"])), None)
        if not raw_row or raw_row[1].strip().split()[0] != attempt["slurm_state"] or not raw_row[2].strip().isdigit() or int(raw_row[2].strip()) != elapsed or not raw_row[3].strip().isdigit() or int(raw_row[3].strip()) != cores:
            raise ValueError(f"{attempt['name']} accounting JSON does not match preserved raw sacct output")
        native = attempt.get("native_output")
        if native not in artifacts:
            raise ValueError(f"{attempt['name']} output is absent from native_artifacts")
        log = artifacts[native].read_text(errors="replace")
        normal = "ORCA TERMINATED NORMALLY" in log.upper()
        converged = bool(re.search(r"THE OPTIMIZATION HAS CONVERGED|OPTIMIZATION CONVERGED", log, re.I))
        if not re.search(r"Program\s+Version\s+6\.0\.1\s+-\s+RELEASE\s+-?", log):
            raise ValueError(f"{attempt['name']} hash-verified ORCA output lacks the pinned engine version banner")
        if attempt.get("normal_termination") is not normal or attempt.get("converged") is not converged:
            raise ValueError(f"{attempt['name']} convergence flags contradict its hash-verified native ORCA output")
        table = optimizer_convergence_table(log)
        if converged != all(row[2] for row in table.values()):
            raise ValueError(f"{attempt['name']} ORCA optimizer marker contradicts its final convergence table")
        native_tables.append(table)
        native_energy = final_single_point_energy(log, attempt["name"])
        # Intermediate recovery attempts can end at a different geometry and
        # therefore a different energy. Bind final_convergence to the accepted
        # geometry only, or a genuine recovery could never be represented.
        validate_attempt_energy(attempt, attempts, native_energy, result.get("final_convergence", {}))
        input_text = artifacts[native_input].read_text(errors="replace")
        parsed = parse_supported_opt_input(input_text)
        if (parsed["nprocs"] < 1 or parsed["maxcore"] < 1 or parsed["nprocs"] > cores
                or parsed["maxcore"] * parsed["nprocs"] > attempt["memory_gib"] * 1024):
            raise ValueError(f"{attempt['name']} native ORCA process/memory controls exceed its reported allocation")
        parsed_inputs.append(parsed)
        declared = {str(x.get("name")): x for x in result.get("convergence_thresholds", []) if isinstance(x, dict)}
        units = {"energy_change": "Eh", "rms_gradient": "Eh/bohr", "max_gradient": "Eh/bohr",
                 "rms_step": "bohr", "max_step": "bohr", "max_cycles": "cycles"}
        final_values = result.get("final_convergence", {})
        values = {"energy_change": "energy_change_Eh", "rms_gradient": "rms_gradient_Eh_per_bohr",
                  "max_gradient": "max_gradient_Eh_per_bohr", "rms_step": "rms_step_bohr", "max_step": "max_step_bohr"}
        for key, (_value, native_tol, passed) in table.items():
            item = declared.get(key)
            if (item is None or item.get("unit") != units[key] or type(item.get("value")) not in (int, float)
                    or not math.isfinite(item["value"])):
                raise ValueError(f"reported {key} tolerance is missing or malformed")
            if (key in attempt_tolerances
                    and native_tol > attempt_tolerances[key] + max(1e-12, abs(attempt_tolerances[key]) * 1e-7)):
                raise ValueError(f"{attempt['name']} widens the preregistered {key} convergence tolerance")
            if is_final_attempt:
                if abs(float(item["value"]) - native_tol) > max(1e-12, abs(native_tol) * 1e-7):
                    raise ValueError(f"reported {key} tolerance differs from the final native ORCA convergence table")
                if not passed:
                    raise ValueError(f"native ORCA final convergence table marks {key} as not converged")
                if (type(final_values.get(values[key])) not in (int, float)
                        or not math.isfinite(final_values[values[key]])
                        or abs(float(final_values[values[key]]) - _value) > 5e-8):
                    raise ValueError(f"reported final {key} value differs from the native ORCA convergence table")
            attempt_tolerances[key] = native_tol
        max_cycles = declared.get("max_cycles")
        if parsed["maxiter"] < 1:
            raise ValueError(f"{attempt['name']} native input lacks a positive ORCA MaxIter")
        if is_final_attempt:
            if (not max_cycles or max_cycles.get("unit") != units["max_cycles"]
                    or type(max_cycles.get("value")) is not int
                    or max_cycles["value"] != parsed["maxiter"]):
                raise ValueError("reported max_cycles differs from the final native ORCA MaxIter input")
    for idx, current in enumerate(attempts[1:], start=1):
        previous = attempts[idx - 1]
        prior_table = native_tables[idx - 1]
        failed = [name for name, row in prior_table.items() if not row[2]]
        action = previous.get("next_action")
        evidence = action.get("evidence", {}) if isinstance(action, dict) else {}
        if (not isinstance(action, dict)
                or previous.get("slurm_state") != "COMPLETED" or previous.get("normal_termination") is not True
                or previous.get("converged") is not False or not failed
                or action.get("kind") != "extend_optimizer_iterations"
                or evidence.get("native_output") != previous.get("native_output")
                or evidence.get("failed_criteria") != failed):
            raise ReviewRequired("recovery trigger is not a normal-terminated, native-table-confirmed nonconvergence")
        old, new = parsed_inputs[idx - 1], parsed_inputs[idx]
        for key in ("method", "charge", "multiplicity"):
            if old[key] != new[key]:
                raise ReviewRequired(f"recovery changed frozen scientific ORCA control: {key}")
        if new["maxiter"] <= old["maxiter"]:
            raise ReviewRequired("recovery MaxIter must strictly increase")
        if current.get("native_geometry_input") not in artifacts:
            raise ReviewRequired("recovery is missing its hash-bound starting geometry")
        geometry_path = current["native_geometry_input"]
        xyz_ref = re.search(r"(?im)^\s*\*\s*xyzfile\s+0\s+1\s+(\S+)\s*$", artifacts[current["native_input"]].read_text(errors="replace"))
        if not xyz_ref or Path(xyz_ref.group(1)).name != Path(geometry_path).name:
            raise ValueError(f"{current['name']} ORCA input does not name its hash-verified recovery geometry")
        symbols, coords = parse_xyz(artifacts[geometry_path])
        prior_symbols, prior_coords = extract_orca_final_xyz(artifacts[previous["native_output"]].read_text(errors="replace"))
        if symbols != prior_symbols or len(coords) != len(prior_coords) or any(xyz_distance(a,b) > 1e-3 for a,b in zip(coords,prior_coords)):
            raise ValueError(f"{current['name']} starting geometry is not the preceding attempt's native final geometry")
    if attempts[0].get("native_geometry_input"):
        raise ValueError("initial geometry must be bound directly to the listed public candidate")
    initial_parsed = parsed_inputs[0]
    initial_input = attempts[0].get("native_input")
    if initial_input not in artifacts:
        raise ValueError("initial optimization input is absent from the hash-verified artifact manifest")
    initial_geometry = initial_candidate_geometry_artifact(
        initial_input, str(initial_parsed["coordinate_file"]), artifacts,
        app / "assets/1br5_candidate.xyz")
    src_symbols, src_coords = parse_xyz(app / "assets/1br5_candidate.xyz")
    in_symbols, in_coords = parse_xyz(initial_geometry)
    if src_symbols != in_symbols or len(src_coords) != len(in_coords) or any(xyz_distance(a,b) > 1e-6 for a,b in zip(src_coords,in_coords)):
        raise ValueError("initial ORCA xyzfile differs from the public candidate atom order or coordinates")
    roles = {item.get("role") for item in result["native_artifacts"] if isinstance(item, dict)}
    if not {"input", "reference", "ccd_source", "pdb_source", "engine_input", "engine_output", "scheduler_submission", "scheduler_accounting_raw", "scheduler_accounting", "final_geometry"}.issubset(roles):
        raise ValueError("native artifact manifest must cover public sources, engine input/output, raw submission/accounting, parsed accounting, and final geometry")
    final_native_path = attempts[-1].get("native_output")
    if final_native_path not in artifacts:
        raise ValueError("final native ORCA output is missing")
    native_symbols, native_xyz = extract_orca_final_xyz(artifacts[final_native_path].read_text(errors="replace"))
    final_symbols, final_xyz = parse_xyz(app / "geometry.xyz")
    if native_symbols != final_symbols or len(native_xyz) != len(final_xyz) or any(xyz_distance(a, b) > 1.0e-3 for a, b in zip(native_xyz, final_xyz)):
        raise ValueError("geometry.xyz differs from final coordinates printed in the hash-verified ORCA output")
    if attempts[-1].get("converged") is not True:
        raise ValueError("the final attempt has no native convergence evidence")
    if attempts[-1].get("normal_termination") is not True:
        raise ValueError("the final attempt lacks native ORCA normal-termination evidence")
    validate_recovery_geometry_chain(attempts, artifacts)
    if result.get("charge_spin", {}).get("charge") != 0 or result.get("charge_spin", {}).get("multiplicity") != 1:
        raise ValueError("selected state differs from the conditional neutral singlet source contract; explain and revise case before scoring")
    return ["attempt order, shared CPU-time cap, native hashes, terminal state, and convergence markers are coherent"]


def validation_job_receipt(name: str, record: dict, artifacts: dict[str, Path],
                           artifact_roles: dict[str, str]) -> tuple[str, int]:
    if not isinstance(record, dict) or record.get("attempt_name") != name:
        raise ReviewRequired(f"{name} native receipt is missing or mislabeled")
    exact_keys = {"attempt_name", "job_id", "slurm_state", "allocated_cpus", "memory_gib", "wall_minutes",
                  "elapsed_seconds", "native_input", "native_output", "geometry_input",
                  "scheduler_submission", "scheduler_accounting_raw", "slurm_accounting",
                  "collection_budget_snapshot"}
    if name == "freq-validation":
        exact_keys |= {"native_hessian", "mode_count", "trans_rot_mode_count"}
    else:
        exact_keys |= {"lowest_eigenvalues_hartree", "analysis_space"}
    if set(record) != exact_keys:
        raise ReviewRequired(f"{name} receipt keys do not match the published schema")
    required = ("job_id", "slurm_state", "allocated_cpus", "memory_gib", "wall_minutes", "elapsed_seconds",
                "native_input", "native_output", "geometry_input", "scheduler_submission",
                "scheduler_accounting_raw", "slurm_accounting")
    if any(field not in record for field in required):
        raise ReviewRequired(f"{name} receipt lacks resource or native-artifact fields")
    if record["slurm_state"] != "COMPLETED":
        raise ReviewRequired(f"{name} Slurm record is not COMPLETED")
    cpus, elapsed, wall = record["allocated_cpus"], record["elapsed_seconds"], record["wall_minutes"]
    memory = record.get("memory_gib")
    if (type(cpus) is not int or cpus < 1 or type(elapsed) is not int
            or elapsed < 0 or type(wall) is not int or wall < 1
            or elapsed > wall * 60 or type(memory) is not int or memory < 1):
        raise ValueError(f"{name} resource record is malformed")
    paths = {field: record[field] for field in required if field.startswith("native_") or field.startswith("scheduler_") or field == "geometry_input" or field == "slurm_accounting"}
    if name == "freq-validation":
        hessian_path = record.get("native_hessian")
        if not isinstance(hessian_path, str) or hessian_path not in artifacts:
            raise ReviewRequired("frequency receipt lacks its hash-verified native ORCA .hess file")
    if any(value not in artifacts for value in paths.values()):
        raise ReviewRequired(f"{name} receipt points to artifacts absent from the native manifest")
    prefix = "validation_frequency" if name == "freq-validation" else "validation_stability"
    role_fields = {"native_input": f"{prefix}_native_input", "native_output": f"{prefix}_native_output",
                   "geometry_input": f"{prefix}_geometry_input", "scheduler_submission": f"{prefix}_scheduler_submission",
                   "scheduler_accounting_raw": f"{prefix}_scheduler_accounting_raw",
                   "slurm_accounting": f"{prefix}_slurm_accounting",
                   "collection_budget_snapshot": f"{prefix}_budget_snapshot"}
    if name == "freq-validation":
        role_fields["native_hessian"] = "native_hessian"
    for field, role in role_fields.items():
        path = record.get(field)
        if not isinstance(path, str) or path not in artifacts or artifact_roles.get(path) != role:
            raise ReviewRequired(f"{name} field {field} lacks its hash-verified manifest role {role}")
    accounting = json.loads(artifacts[record["slurm_accounting"]].read_text())
    if (str(accounting.get("job_id")) != str(record["job_id"]) or accounting.get("state") != "COMPLETED"
            or accounting.get("allocated_cpus") != cpus or accounting.get("elapsed_seconds") != elapsed):
        raise ValueError(f"{name} structured Slurm accounting contradicts its receipt")
    submission = artifacts[record["scheduler_submission"]].read_text(errors="replace")
    if not re.search(rf"(?m)^\s*{re.escape(str(record['job_id']))}(?:;[^\s]+)?\s*$", submission):
        raise ValueError(f"{name} Slurm job ID is absent from the preserved sbatch response")
    rows = [line.split("|") for line in artifacts[record["scheduler_accounting_raw"]].read_text(errors="replace").splitlines()]
    raw = next((row for row in rows if len(row) >= 4 and row[0].strip() == str(record["job_id"])), None)
    if not raw or raw[1].strip().split()[0] != "COMPLETED" or not raw[2].strip().isdigit() or int(raw[2]) != elapsed or not raw[3].strip().isdigit() or int(raw[3]) != cpus:
        raise ValueError(f"{name} raw sacct record contradicts its settled allocation")
    return str(record["native_output"]), cpus * max(1, (elapsed + 59) // 60)


def validate_budget_ledger(ledger: dict, snapshot: dict, attempts: list[dict],
                           validation_records: tuple[dict, dict], artifacts: dict[str, Path] | None = None,
                           artifact_roles: dict[str, str] | None = None) -> int:
    """Reconcile every submitted science job to one strictly typed ledger row."""
    rows = ledger.get("attempts")
    if (ledger.get("schema") != "case03-budget/v1" or type(ledger.get("limit_cpu_minutes")) is not int
            or not isinstance(rows, list)
            or type(snapshot.get("limit_cpu_minutes")) is not int
            or type(snapshot.get("reserved_cpu_minutes")) is not int
            or snapshot["reserved_cpu_minutes"] != 0):
        raise ValueError("shared budget snapshot is malformed or over-reserved")
    charged = 0
    reserved_total = 0
    by_job: dict[str, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("shared budget ledger contains a malformed attempt row")
        charge, reserved = row.get("charged_cpu_minutes", 0), row.get("reserved_cpu_minutes", 0)
        if type(charge) is not int or charge < 0 or type(reserved) is not int or reserved < 0:
            raise ValueError("shared budget ledger charges and reservations must be nonnegative JSON integers")
        if row.get("state") == "settled" and reserved != 0:
            raise ValueError("settled shared budget ledger rows must release their reservation")
        if row.get("state") in {"reserved", "submission_unknown"}:
            raise ReviewRequired("shared budget ledger contains an unsettled or submission-unknown Slurm allocation")
        charged += charge
        reserved_total += reserved
        if row.get("job_id") is not None:
            by_job.setdefault(str(row["job_id"]), []).append(row)
    if any(len(items) != 1 for items in by_job.values()):
        raise ValueError("shared budget ledger repeats a Slurm job ID")
    declared_charge = snapshot.get("charged_cpu_minutes")
    if (type(declared_charge) is not int or declared_charge != charged
            or reserved_total != snapshot["reserved_cpu_minutes"]):
        raise ValueError("shared budget snapshot total disagrees with its settled attempt records")

    def require_settled_record(record: dict, purpose: str, name: str,
                               cpus: int, elapsed: int) -> None:
        job_id = str(record["job_id"])
        matches = by_job.get(job_id, [])
        expected_charge = cpus * max(1, (elapsed + 59) // 60)
        if len(matches) != 1:
            raise ValueError(f"{name} is absent or duplicated in the shared budget ledger")
        row = matches[0]
        # Both helper generations are archived: optimization rows use name and
        # settled scheduler_state; typed validation rows also set purpose.
        if (row.get("state") != "settled" or row.get("scheduler_state") != "COMPLETED"
                or row.get("name") != name or row.get("purpose") not in (None, purpose)
                or type(row.get("allocated_cpus")) is not int or row["allocated_cpus"] != cpus
                or type(row.get("elapsed_seconds")) is not int or row["elapsed_seconds"] != elapsed
                or type(row.get("charged_cpu_minutes")) is not int
                or row["charged_cpu_minutes"] != expected_charge
                or type(row.get("reserved_cpu_minutes")) is not int or row["reserved_cpu_minutes"] != 0):
            raise ValueError(f"{name} ledger entry does not match its actual scheduler allocation and elapsed time")

    for attempt in attempts:
        require_settled_record(attempt, "optimization", attempt["name"],
                               attempt["allocated_cpus"], attempt["elapsed_seconds"])
    for name, record in zip(("freq-validation", "stability-validation"), validation_records):
        require_settled_record(record, "scientific_validation", name,
                               record["allocated_cpus"], record["elapsed_seconds"])
    expected_ids = {str(x["job_id"]) for x in attempts}
    expected_ids.update(str(x["job_id"]) for x in validation_records)
    artifacts = artifacts or {}
    artifact_roles = artifact_roles or {}
    extras = ledger.get("additional_billing_records", [])
    if not isinstance(extras, list):
        raise ValueError("additional_billing_records must be an array")
    for record in extras:
        extra_keys = {"job_id", "state", "scheduler_state", "allocated_cpus", "elapsed_seconds",
                      "charged_cpu_minutes", "reserved_cpu_minutes", "scheduler_accounting_raw",
                      "scheduler_submission", "wall_minutes", "memory_gib"}
        if not isinstance(record, dict) or set(record) != extra_keys:
            raise ReviewRequired("additional billing record lacks raw scheduler evidence and charge fields")
        if not isinstance(record.get("job_id"), str) or not record["job_id"].strip():
            raise ReviewRequired("additional billing job_id must be a nonempty string")
        job = record["job_id"]
        if job in expected_ids:
            raise ValueError("additional billing record reuses a scientific or validation job ID")
        expected_ids.add(job)
        matches = by_job.get(job, [])
        if len(matches) != 1:
            raise ValueError("additional billing record is absent or duplicated in the task ledger")
        row = matches[0]
        raw_path = record["scheduler_accounting_raw"]
        if (not isinstance(raw_path, str) or raw_path not in artifacts
                or artifact_roles.get(raw_path) != "scheduler_accounting_raw"):
            raise ReviewRequired("additional billing record has no manifest-listed raw sacct path")
        submission_path = record["scheduler_submission"]
        if (not isinstance(submission_path, str) or submission_path not in artifacts
                or artifact_roles.get(submission_path) != "scheduler_submission"):
            raise ReviewRequired("additional billing record has no manifest-listed sbatch response")
        if not re.search(rf"(?m)^\s*{re.escape(job)}(?:;[^\s]+)?\s*$",
                         artifacts[submission_path].read_text(errors="replace")):
            raise ReviewRequired("additional billing job ID is absent from its preserved sbatch response")
        raw_rows = [line.split("|") for line in artifacts[raw_path].read_text(errors="replace").splitlines()]
        matching = [r for r in raw_rows if r and r[0].strip() == job]
        if len(matching) != 1 or len(matching[0]) != 4:
            raise ReviewRequired("additional billing job must have one four-column raw sacct record")
        parsed_job, parsed_state, parsed_elapsed, parsed_cpus = [part.strip() for part in matching[0]]
        parsed_state = parsed_state.split()[0] if parsed_state else ""
        if (not parsed_elapsed.isdigit() or not parsed_cpus.isdigit()
                or parsed_state != "COMPLETED"):
            raise ReviewRequired("additional billing raw sacct record is not a settled supported allocation")
        cpus, elapsed = int(parsed_cpus), int(parsed_elapsed)
        wall, memory = record.get("wall_minutes"), record.get("memory_gib")
        if (cpus < 1 or elapsed < 0
                or type(wall) is not int or wall < 1 or elapsed > wall * 60
                or type(memory) is not int or memory < 1):
            raise ValueError("additional billing allocation record is malformed")
        expected_charge = cpus * max(1, (elapsed + 59) // 60)
        for obj in (record, row):
            if (obj.get("state") != "settled" or obj.get("scheduler_state") != parsed_state
                    or type(obj.get("allocated_cpus")) is not int or obj["allocated_cpus"] != cpus
                    or type(obj.get("elapsed_seconds")) is not int or obj["elapsed_seconds"] != elapsed
                    or type(obj.get("charged_cpu_minutes")) is not int
                    or obj["charged_cpu_minutes"] != expected_charge
                    or type(obj.get("reserved_cpu_minutes")) is not int
                    or obj.get("reserved_cpu_minutes", 0) != 0):
                raise ValueError("additional billing entry does not equal independently parsed raw sacct allocation and recomputed charge")
    if set(by_job) != expected_ids:
        raise ValueError("task ledger contains an unlinked job or omits an explicit task billing record")
    return charged


def validate_scientific_validation(app: Path, result: dict, artifacts: dict[str, Path]) -> tuple[list[str], int]:
    validation = result.get("scientific_validation")
    if not isinstance(validation, dict):
        raise ReviewRequired("frequency and SCF stability native evidence is not yet available")
    if set(validation) != {"model", "frequency", "stability"}:
        raise ReviewRequired("scientific_validation keys do not match the published schema")
    model = validation.get("model", {})
    if not isinstance(model, dict) or set(model) != {"method", "charge", "multiplicity", "geometry_sha256"}:
        raise ReviewRequired("scientific_validation.model keys do not match the published schema")
    geometry_path = app / "geometry.xyz"
    geometry_hash = sha256(geometry_path)
    if (model.get("method") != "r2SCAN-3c" or model.get("charge") != 0 or model.get("multiplicity") != 1
            or model.get("geometry_sha256") != geometry_hash):
        raise ValueError("scientific validations are not bound to the frozen method, state, and final optimized geometry")
    artifact_roles = {item.get("path"): item.get("role") for item in result.get("native_artifacts", [])
                      if isinstance(item, dict)}
    frequencies = validation.get("frequency")
    stability = validation.get("stability")
    freq_output_path, freq_charge = validation_job_receipt("freq-validation", frequencies, artifacts, artifact_roles)
    stab_output_path, stab_charge = validation_job_receipt("stability-validation", stability, artifacts, artifact_roles)
    validation_ids = {str(frequencies["job_id"]), str(stability["job_id"])}
    if len(validation_ids) != 2 or validation_ids & {str(a.get("job_id")) for a in result.get("attempts", [])}:
        raise ValueError("scientific and validation jobs must have unique Slurm job IDs")
    freq_input = artifacts[frequencies["native_input"]].read_text(errors="replace")
    stability_input = artifacts[stability["native_input"]].read_text(errors="replace")
    for name, record, input_text in (("freq-validation", frequencies, freq_input), ("stability-validation", stability, stability_input)):
        if not re.search(r"(?i)r2SCAN-3c", input_text) or not re.search(r"(?im)^\s*\*\s*xyzfile\s+0\s+1\s+", input_text):
            raise ValueError(f"{name} native input differs from the frozen r2SCAN-3c neutral-singlet model")
        pal = re.findall(r"(?im)^\s*%pal\s+nprocs\s+(\d+)\s+end\s*$", input_text)
        maxcore = re.findall(r"(?im)^\s*%maxcore\s+(\d+)\s*$", input_text)
        if (len(pal) != 1 or int(pal[0]) < 1 or int(pal[0]) > record["allocated_cpus"]
                or (maxcore and (len(maxcore) != 1 or int(maxcore[0]) < 1
                                 or int(maxcore[0]) * int(pal[0]) > record["memory_gib"] * 1024))):
            raise ValueError(f"{name} native ORCA process/memory controls exceed its reported allocation")
        in_symbols, in_coords = parse_xyz(artifacts[record["geometry_input"]])
        out_symbols, out_coords = parse_xyz(geometry_path)
        if in_symbols != out_symbols or len(in_coords) != len(out_coords) or any(xyz_distance(a, b) > 1e-6 for a, b in zip(in_coords, out_coords)):
            raise ValueError(f"{name} was not calculated at the hash-bound final optimized geometry")
        output = artifacts[record["native_output"]].read_text(errors="replace")
        if not re.search(r"Program\s+Version\s+6\.0\.1\s+-\s+RELEASE\s+-?", output) or "ORCA TERMINATED NORMALLY" not in output.upper():
            raise ReviewRequired(f"{name} native output lacks the pinned ORCA banner or normal termination")
        optimized_energy = result.get("final_convergence", {}).get("final_energy_Eh")
        validation_energy = final_single_point_energy(output, name)
        if not isinstance(optimized_energy, (int, float)) or not math.isfinite(optimized_energy):
            raise ReviewRequired("optimized-state reference energy is missing or non-finite")
        if abs(validation_energy - float(optimized_energy)) > 1e-6:
            raise ScientificFailure(f"{name} final SCF energy differs from the optimized-state reference by more than 1e-6 Eh")
        native_symbols, native_coords = extract_orca_final_xyz(output)
        if native_symbols != out_symbols or any(xyz_distance(a, b) > 1e-3 for a, b in zip(native_coords, out_coords)):
            raise ValueError(f"{name} native output geometry differs from the validated final geometry")
    if not re.search(r"(?i)\bFREQ\b", freq_input) or re.search(r"(?i)\bOPT\b", freq_input):
        raise ValueError("frequency job input must request frequencies at the fixed optimized geometry without re-optimizing")
    if not re.search(r"(?is)%freq\s+.*?ProjectTR\s+true", freq_input):
        raise ValueError("frequency input must explicitly freeze the preregistered ProjectTR=true protocol")
    freq_log = artifacts[freq_output_path].read_text(errors="replace")
    source_symbols, _source_xyz = parse_xyz(app / "assets/1br5_candidate.xyz")
    expected_mode_count = 3 * len(source_symbols)
    modes = parse_frequency_modes(freq_log, expected_mode_count)
    hess_text = artifacts[frequencies["native_hessian"]].read_text(errors="replace")
    hess_modes = parse_hessian_frequencies(hess_text, expected_mode_count)
    if any(abs(hess_modes[i] - modes[i][1]) > 0.02 for i in range(expected_mode_count)):
        raise ValueError("ORCA .hess frequencies disagree with the native frequency table")
    hess_symbols, hess_coords_bohr = parse_hessian_atoms(hess_text)
    bohr_to_angstrom = 0.529177210903
    hess_coords = [tuple(x * bohr_to_angstrom for x in xyz) for xyz in hess_coords_bohr]
    if hess_symbols != out_symbols or not same_oriented_geometry(hess_coords, out_coords):
        raise ValueError("ORCA .hess atom labels/coordinates differ from the hash-bound final optimized geometry")
    if frequencies.get("mode_count") != expected_mode_count or frequencies.get("trans_rot_mode_count") != 6:
        raise ValueError("frequency receipt mode count must equal 3N and report six projected rigid modes")
    classify_frequency_modes(modes, expected_mode_count)
    if not re.search(r"(?i)STABPerform\s+true", stability_input) or not re.search(r"(?i)STABRestartUHFifUnstable\s+false", stability_input):
        raise ValueError("stability input must request analysis and disable automatic state-changing restart")
    if not re.search(r"(?i)STABNRoots\s+3", stability_input):
        raise ReviewRequired("stability input must explicitly request three roots")
    if re.search(r"(?i)\bOPT\b|\bFREQ\b", stability_input):
        raise ValueError("SCF stability analysis must be a separate single-point-like calculation")
    if re.search(r"(?i)STAB(?:ORBWIN|EWIN)\b", stability_input):
        raise ValueError("stability input must not narrow the preregistered default orbital/energy window")
    if re.search(r"(?i)\bRI-JK\b", stability_input):
        raise ValueError("ORCA stability analysis does not support RI-JK")
    stab_log = artifacts[stab_output_path].read_text(errors="replace")
    require_restricted_closed_shell_reference(stab_log)
    eigenvalues = parse_stability_eigenvalues(stab_log)
    declared = stability.get("lowest_eigenvalues_hartree")
    if (not isinstance(declared, list) or len(declared) != 3
            or any(not isinstance(a, (int, float)) or not math.isfinite(a) for a in declared)):
        raise ReviewRequired("stability receipt lacks three finite lowest eigenvalues parsed from the native log")
    if any(abs(a-b) > 1e-7 for a, b in zip(declared, eigenvalues)):
        raise ValueError("reported lowest stability eigenvalues do not match the parsed native ORCA eigenvalue block")
    classify_stability_eigenvalues(eigenvalues)
    if parse_stability_conclusion(stab_log) != "stable":
        raise ReviewRequired("native ORCA stability conclusion does not support a positive-eigenvalue stable reference")
    if stability.get("analysis_space") != "RKS_to_UKS":
        raise ReviewRequired("SCF stability analysis space was not explicitly declared")
    if not all(math.isfinite(x) for x in eigenvalues):
        raise ReviewRequired("SCF stability eigenvalue block is incomplete or non-finite")
    budget = result.get("budget_snapshot")
    if not isinstance(budget, dict) or budget.get("path") not in artifacts or budget.get("path") not in {
            entry.get("path") for entry in result.get("native_artifacts", []) if isinstance(entry, dict) and entry.get("role") == "budget_ledger"}:
        raise ReviewRequired("validation result lacks the hash-verified shared CPU-minute ledger snapshot")
    ledger = json.loads(artifacts[budget["path"]].read_text())
    charged = validate_budget_ledger(ledger, budget, result.get("attempts", []),
                                     (frequencies, stability), artifacts, artifact_roles)
    required_current = sum(
        record["allocated_cpus"] * max(1, (record["elapsed_seconds"] + 59) // 60)
        for record in [*result.get("attempts", []), frequencies, stability]
    )
    if charged < required_current:
        raise ValueError("shared ledger omits one or more submitted optimization/validation allocations")
    return [f"native {expected_mode_count}-mode (3N) frequency analysis and three-root SCF stability analysis passed"], freq_charge + stab_charge


def validate_l3(app: Path, atoms: dict, bonds: list[dict], cif_coords: dict, pdb_atoms: dict,
                mapping: dict) -> list[str]:
    input_symbols, input_xyz = parse_xyz(app / "assets/1br5_candidate.xyz")
    out_symbols, out_xyz = parse_xyz(app / "geometry.xyz")
    if out_symbols != input_symbols:
        raise ValueError("geometry.xyz must preserve the atom count, elements, and row order of the supplied candidate")
    heavy = mapping.get("heavy_atoms")
    hydrogens = mapping.get("hydrogen_assignments")
    if not isinstance(heavy, list) or len(heavy) != 18 or not isinstance(hydrogens, list) or len(hydrogens) != 11:
        raise ValueError("mapping requires 18 heavy-atom correspondences and 11 separately reported hydrogen assignments")
    seen_rows, seen_ids = set(), set()
    row_for = {}
    for item in heavy:
        row = item.get("xyz_row"); name = item.get("ccd_atom_id"); pdb_name = item.get("pdb_atom_name")
        if type(row) is not int or not 1 <= row <= 18 or name not in atoms or name not in pdb_atoms or pdb_name != name:
            raise ValueError("heavy-atom map contains an invalid row, CCD ID, or PDB atom name")
        if row in seen_rows or name in seen_ids or atoms[name]["element"] != input_symbols[row-1] or pdb_atoms[name]["element"] != input_symbols[row-1]:
            raise ValueError("heavy-atom mapping is not bijective and element-consistent")
        if xyz_distance(input_xyz[row-1], cif_coords[name]) > 1.6:
            raise ValueError(f"heavy-atom map does not match the source coordinates for XYZ row {row}")
        seen_rows.add(row); seen_ids.add(name); row_for[name] = row
    if seen_rows != set(range(1, 19)) or seen_ids != {n for n, a in atoms.items() if a["element"] != "H"}:
        raise ValueError("heavy-atom mapping does not cover the CCD/PDB heavy-atom inventory")
    hrows = set()
    for item in hydrogens:
        row, parent = item.get("xyz_row"), item.get("parent_atom_id")
        if type(row) is not int or not 19 <= row <= 29 or row in hrows or input_symbols[row-1] != "H" or parent not in seen_ids:
            raise ValueError("hydrogen assignment row or parent is invalid")
        distance = xyz_distance(input_xyz[row-1], input_xyz[row_for[parent]-1])
        declared = item.get("distance_angstrom")
        if (type(declared) not in (int, float) or not math.isfinite(declared)
                or abs(declared-distance) > 0.03 or not 0.72 <= distance <= 1.35):
            raise ValueError(f"hydrogen row {row} attachment is inconsistent with its input geometry")
        optimized_distance = xyz_distance(out_xyz[row-1], out_xyz[row_for[parent]-1])
        if not 0.72 <= optimized_distance <= 1.35:
            raise ValueError(f"optimized hydrogen row {row} no longer retains its mapped {parent}-H attachment: {optimized_distance:.3f} A")
        if item.get("confidence") not in {"high", "medium", "low"} or not item.get("interpretation"):
            raise ValueError(f"hydrogen row {row} lacks confidence or tautomer context")
        hrows.add(row)
    if hrows != set(range(19, 30)):
        raise ValueError("hydrogen assignments do not cover all 11 input hydrogen rows")
    row_by_name = {x["ccd_atom_id"]: x["xyz_row"]-1 for x in heavy}
    for bond in bonds:
        a, b = bond["a"], bond["b"]
        if atoms[a]["element"] == "H" or atoms[b]["element"] == "H":
            continue
        d = xyz_distance(out_xyz[row_by_name[a]], out_xyz[row_by_name[b]])
        if not 0.90 <= d <= 2.20:
            raise ValueError(f"gross heavy-atom connectivity distortion at {a}-{b}: {d:.3f} A")
    # Retain the known NEO stereocentres relative to the supplied starting geometry.
    neighbors = {name: set() for name in atoms}
    for bond in bonds:
        neighbors[bond["a"]].add(bond["b"]); neighbors[bond["b"]].add(bond["a"])
    h_parent = {x["parent_atom_id"]: x["xyz_row"]-1 for x in hydrogens}
    for center in ("C16", "C26"):
        refs = sorted(neighbors[center])
        if len(refs) != 4 or any(n not in row_by_name and n not in atoms for n in refs):
            continue
        mapped_rows = []
        for n in refs:
            if atoms[n]["element"] == "H":
                if center not in h_parent:
                    raise ValueError(f"stereocenter {center} lacks its attached-H mapping")
                mapped_rows.append(h_parent[center])
            else:
                mapped_rows.append(row_by_name[n])
        def volume(coords, ids):
            vs = [coords[i] for i in ids]
            ax = [vs[i][0]-vs[3][0] for i in range(3)]
            ay = [vs[i][1]-vs[3][1] for i in range(3)]
            az = [vs[i][2]-vs[3][2] for i in range(3)]
            return ax[0]*(ay[1]*az[2]-az[1]*ay[2])-ay[0]*(ax[1]*az[2]-az[1]*ax[2])+az[0]*(ax[1]*ay[2]-ay[1]*ax[2])
        start_ids = [row_for[n]-1 if atoms[n]["element"] != "H" else h_parent[center] for n in refs]
        out_v, start_v = volume(out_xyz, mapped_rows), volume(input_xyz, start_ids)
        if abs(out_v) < 0.1 or abs(start_v) < 0.1 or out_v * start_v <= 0:
            raise ValueError(f"stereocenter {center} is inverted or degenerate relative to the supplied geometry")
    return ["heavy-atom mapping, skeleton bond lengths, stereocentre retention, and input hydrogen attachment topology passed for the declared model"]


def _evaluate_candidate(app: Path) -> dict:
    result_path = app / "result.json"
    evidence_origin = ("historical_archive_replay"
                      if result_path.is_file() and not result_path.is_symlink()
                      and sha256(result_path) == HISTORICAL_RESULT_SHA256
                      else "candidate_submission")
    coverage = {
        "status": "PARTIAL",
        "trusted_execution": "UNVERIFIED",
        "gaps": ["no independent execution cross-check is installed in this edition",
                 "recovery-path suite coverage has not been established by a genuine trajectory"],
        "evidence_origin": evidence_origin,
    }
    levels = {"preflight": {"status": "PASS", "checks": []}, "L1": {"status": "NOT_RUN", "checks": []},
              "L2": {"status": "NOT_RUN", "checks": []}, "L3": {"status": "NOT_RUN", "checks": []},
              "scientific_validation": {"status": "NOT_RUN", "checks": []}}
    try:
        levels["preflight"]["checks"] = _input_file_checks(app)
        atoms, bonds, cif_coords, pdb_atoms = source_contract(app)
    except Exception as exc:
        levels["preflight"] = {"status": "ENV_INVALID", "checks": [str(exc)]}
        return {"status": "ENV_INVALID", "reward": None, "levels": levels, "message": "public evaluation inputs or source contract are damaged",
                "decision_mode": "automatic", "human_signoff_required": False, "evidence_status": "insufficient",
                "candidate_evidence_status": "INCONCLUSIVE", "decision_correctness": "INCONCLUSIVE",
                "scientific_success": "INCONCLUSIVE", "evaluation_coverage": coverage}
    try:
        checks, result, mapping = validate_l1(app)
        levels["L1"] = {"status": "PASS", "checks": checks}
        artifacts, checks = load_manifest(app, result)
        if "safe_stop" in result:
            levels["L2"] = {"status": "PASS", "checks": validate_safe_stop(app, result, artifacts) + checks}
            return {"status": "REVIEW_REQUIRED", "reward": None, "levels": levels,
                    "message": "A native abnormal stop was reconciled; no final model exists, so scientific success is unresolved.",
                    "decision_mode": "automatic", "human_signoff_required": False,
                    "evidence_status": "verified_safe_stop_no_final_model",
                    "candidate_evidence_status": "INCONCLUSIVE", "decision_correctness": "INCONCLUSIVE",
                    "scientific_success": "INCONCLUSIVE", "evaluation_coverage": coverage}
        levels["L2"] = {"status": "PASS", "checks": validate_l2(app, result, artifacts) + checks}
        levels["L3"] = {"status": "PASS", "checks": validate_l3(app, atoms, bonds, cif_coords, pdb_atoms, mapping)}
        try:
            checks, validation_cpu_minutes = validate_scientific_validation(app, result, artifacts)
            levels["scientific_validation"] = {"status": "PASS", "checks": checks + [f"validation jobs charged {validation_cpu_minutes} CPU-min from actual Slurm allocation"]}
        except ReviewRequired as exc:
            levels["scientific_validation"] = {"status": "INCONCLUSIVE", "checks": [str(exc)]}
            return {"status": "REVIEW_REQUIRED", "reward": None, "levels": levels,
                    "message": "Automatic evidence is incomplete or numerically unresolved for the frozen conditional molecular model.",
                    "decision_mode": "automatic", "human_signoff_required": False, "evidence_status": "insufficient",
                    "candidate_evidence_status": "INCONCLUSIVE", "decision_correctness": "INCONCLUSIVE",
                    "scientific_success": "INCONCLUSIVE", "evaluation_coverage": coverage}
        except ScientificFailure as exc:
            levels["scientific_validation"] = {"status": "FAIL", "checks": [str(exc)]}
            rejected = result.get("decision") == "reject"
            return {"status": "FAIL", "reward": 0.0, "levels": levels, "message": str(exc),
                    "decision_mode": "automatic", "human_signoff_required": False, "evidence_status": "supported_scientific_failure",
                    "candidate_evidence_status": "FAIL", "decision_correctness": "PASS" if rejected else "FAIL",
                    "scientific_success": "FAIL", "evaluation_coverage": coverage}
    except ReviewRequired as exc:
        levels["scientific_validation"] = {"status": "INCONCLUSIVE", "checks": [str(exc)]}
        return {"status": "REVIEW_REQUIRED", "reward": None, "levels": levels, "message": str(exc),
                "decision_mode": "automatic", "human_signoff_required": False, "evidence_status": "insufficient",
                "candidate_evidence_status": "INCONCLUSIVE", "decision_correctness": "INCONCLUSIVE",
                "scientific_success": "INCONCLUSIVE", "evaluation_coverage": coverage}
    except (ValueError, OSError, UnicodeError) as exc:
        layer = "L1" if levels["L1"]["status"] == "NOT_RUN" else "L2" if levels["L2"]["status"] == "NOT_RUN" else "L3" if levels["L3"]["status"] == "NOT_RUN" else "scientific_validation"
        levels[layer] = {"status": "FAIL", "checks": [str(exc)]}
        return {"status": "FAIL", "reward": 0.0, "levels": levels, "message": str(exc),
                "decision_mode": "automatic", "human_signoff_required": False, "evidence_status": "submission_integrity_failure",
                "candidate_evidence_status": "FAIL", "decision_correctness": "FAIL",
                "scientific_success": "INCONCLUSIVE", "evaluation_coverage": coverage}
    decision_ok = result.get("decision") == "accept"
    if not decision_ok:
        return {"status": "FAIL", "reward": 0.0, "levels": levels,
                "message": "Native evidence supports scientific acceptance, but the submitted decision is reject.",
                "decision_mode": "automatic", "human_signoff_required": False, "evidence_status": "decision_contradicts_candidate_evidence",
                "candidate_evidence_status": "PASS", "decision_correctness": "FAIL",
                "scientific_success": "PASS", "evaluation_coverage": coverage}
    return {"status": "PASS", "reward": 1.0, "levels": levels,
            "message": "All required native scientific checks pass for the declared candidate model. Evaluation coverage and trusted execution are reported separately.",
            "decision_mode": "automatic", "human_signoff_required": False, "evidence_status": "complete_candidate_evidence",
            "candidate_evidence_status": "PASS", "decision_correctness": "PASS",
            "scientific_success": "PASS", "evaluation_coverage": coverage}


def _trusted_installation_error(message: str) -> dict:
    return {"status": "ENV_INVALID", "reward": None, "levels": {"trusted_execution": {"status": "ENV_INVALID", "checks": [message]}},
            "message": "The operator-only Case03 execution context is damaged or not installed as a trusted read-only mount.",
            "decision_mode": "automatic", "human_signoff_required": False,
            "evidence_status": "invalid_trusted_execution_installation",
            "candidate_evidence_status": "INCONCLUSIVE", "decision_correctness": "INCONCLUSIVE",
            "scientific_success": "INCONCLUSIVE", "trusted_execution": "INVALID",
            "evaluation_coverage": {"status": "PARTIAL", "trusted_execution": "INVALID",
                                    "gaps": ["operator-only execution context is invalid"]}}


def _trusted_mismatch(message: str) -> dict:
    return {"status": "FAIL", "reward": 0.0,
            "levels": {"trusted_execution": {"status": "FAIL", "checks": [message]}},
            "message": "Candidate evidence does not match the operator-bound Case03 execution.",
            "decision_mode": "automatic", "human_signoff_required": False,
            "evidence_status": "trusted_execution_binding_mismatch",
            "candidate_evidence_status": "FAIL", "decision_correctness": "FAIL",
            "scientific_success": "INCONCLUSIVE", "trusted_execution": "FAIL",
            "evaluation_coverage": {"status": "PARTIAL", "trusted_execution": "FAIL",
                                    "gaps": ["candidate payload or job records differ from the operator context"]}}


def _apply_trust_gate(outcome: dict, trust_state: str, checks: list[str] | None = None) -> dict:
    outcome = dict(outcome)
    coverage = dict(outcome.get("evaluation_coverage", {}))
    coverage["trusted_execution"] = trust_state
    gaps = list(coverage.get("gaps", []))
    trust_gap = "no independent execution cross-check is installed in this edition"
    fixture_gap = "explicit in-memory test fixture cannot authenticate a benchmark run"
    if trust_state == "UNVERIFIED" and trust_gap not in gaps:
        gaps.insert(0, trust_gap)
    elif trust_state == "TEST_FIXTURE_ONLY" and fixture_gap not in gaps:
        gaps.insert(0, fixture_gap)
    elif trust_state == "VERIFIED":
        gaps = [gap for gap in gaps if gap != trust_gap]
    if outcome.get("status") == "ENV_INVALID":
        outcome["reward"] = None
        coverage["status"] = "PARTIAL"
        coverage["gaps"] = gaps
        outcome["trusted_execution"] = trust_state
        outcome["evaluation_coverage"] = coverage
        outcome["levels"] = dict(outcome.get("levels", {}))
        outcome["levels"].setdefault("trusted_execution", {"status": trust_state, "checks": checks or []})
        return outcome
    if outcome.get("status") == "FAIL":
        coverage["status"] = "PARTIAL"
        coverage["gaps"] = gaps
        outcome["trusted_execution"] = trust_state
        outcome["evaluation_coverage"] = coverage
        outcome["levels"] = dict(outcome.get("levels", {}))
        outcome["levels"].setdefault("trusted_execution", {"status": trust_state, "checks": checks or []})
        return outcome
    if trust_state == "UNVERIFIED":
        # No operator context is installed in this edition: the candidate's own evidence is
        # scored, and the report records that no independent execution cross-check ran.
        coverage["status"] = "PARTIAL"
        outcome["levels"] = dict(outcome.get("levels", {}))
        outcome["levels"]["trusted_execution"] = {"status": "UNVERIFIED", "checks": checks or ["independent execution cross-check not installed"]}
    elif trust_state == "TEST_FIXTURE_ONLY":
        coverage["status"] = "PARTIAL"
        outcome.update(status="REVIEW_REQUIRED", evidence_status="test_fixture_only",
                       message="The explicit context fixture exercises the consumer only; it cannot authenticate or score a benchmark run.")
        outcome["reward"] = None
        outcome["levels"] = dict(outcome.get("levels", {}))
        outcome["levels"]["trusted_execution"] = {"status": "TEST_FIXTURE_ONLY", "checks": checks or []}
    else:
        outcome["levels"] = dict(outcome.get("levels", {}))
        outcome["levels"]["trusted_execution"] = {"status": "VERIFIED", "checks": checks or []}
    coverage["gaps"] = gaps
    outcome["trusted_execution"] = trust_state
    outcome["evaluation_coverage"] = coverage
    return outcome


def evaluate(app: Path) -> dict:
    """Score the candidate's own evidence and cross-check its submitted artifacts.

    No operator execution context is installed in this edition, so no independent
    execution cross-check runs and the report records trusted_execution=UNVERIFIED.
    """
    if _REFERENCE_ERROR:
        return {"status": "ENV_INVALID", "reward": None, "levels": {}, "message": _REFERENCE_ERROR,
                "decision_mode": "automatic", "human_signoff_required": False, "evidence_status": "insufficient",
                "candidate_evidence_status": "INCONCLUSIVE", "decision_correctness": "INCONCLUSIVE",
                "scientific_success": "INCONCLUSIVE", "evaluation_coverage": {"status": "PARTIAL",
                    "trusted_execution": "UNVERIFIED", "gaps": ["frozen references are unavailable or invalid"]}}

    outcome = _evaluate_candidate(app)
    # Preserve the frozen historical archive's existing review-only behavior.
    if outcome.get("evaluation_coverage", {}).get("evidence_origin") == "historical_archive_replay":
        return _apply_trust_gate(outcome, "UNVERIFIED")
    if (outcome.get("status") == "ENV_INVALID"
            or outcome.get("levels", {}).get("preflight", {}).get("status") != "PASS"
            or outcome.get("levels", {}).get("L1", {}).get("status") not in ("PASS", "NOT_RUN")):
        return _apply_trust_gate(outcome, "UNVERIFIED")
    try:
        result = candidate_provenance._strict_json((app / "result.json").read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError("result.json must be a JSON object")
        indexed = {item["path"]: resolve_inside(app, item["path"])
                   for item in result.get("native_artifacts", [])
                   if isinstance(item, dict) and isinstance(item.get("path"), str)}
        checks = candidate_provenance.validate_submission(app, result, indexed)
    except candidate_provenance.CandidateProvenanceError as exc:
        failed = dict(outcome)
        failed.update(status="FAIL", reward=0.0, evidence_status="candidate_submission_provenance_mismatch",
                      message=str(exc))
        failed["levels"] = dict(failed.get("levels", {}))
        failed["levels"]["candidate_submission_provenance"] = {"status": "FAIL", "checks": [str(exc)]}
        failed["candidate_submission_provenance"] = {"status": "FAIL", "checks": [str(exc)]}
        failed["trusted_execution"] = "UNVERIFIED"
        return failed
    except (OSError, ValueError, KeyError, TypeError) as exc:
        failed = dict(outcome)
        failed.update(status="FAIL", reward=0.0, evidence_status="candidate_submission_provenance_mismatch",
                      message=f"candidate submission provenance is malformed: {exc}",
                      trusted_execution="UNVERIFIED")
        failed["levels"] = dict(failed.get("levels", {}))
        failed["levels"]["candidate_submission_provenance"] = {"status": "FAIL", "checks": [str(exc)]}
        failed["candidate_submission_provenance"] = {"status": "FAIL", "checks": [str(exc)]}
        return failed
    outcome = dict(outcome)
    outcome["candidate_submission_provenance"] = {
        "status": "ARTIFACT_CROSSCHECKED",
        "assurance": candidate_provenance.ASSURANCE,
        "checks": checks,
    }
    outcome["trusted_execution"] = "UNVERIFIED"
    outcome["levels"] = dict(outcome.get("levels", {}))
    outcome["levels"]["candidate_submission_provenance"] = {"status": "ARTIFACT_CROSSCHECKED", "checks": checks}
    return outcome


def main() -> int:
    app = Path(os.environ.get("APP", "/app")); logs = Path(os.environ.get("LOGS", "/logs/verifier"))
    logs.mkdir(parents=True, exist_ok=True)
    reward = logs / "reward.txt"
    if reward.exists(): reward.unlink()
    try:
        outcome = evaluate(app)
    except Exception as exc:
        outcome = {"status": "ENV_INVALID", "reward": None, "levels": {}, "message": f"verifier infrastructure error: {type(exc).__name__}: {exc}",
                   "decision_mode": "automatic", "human_signoff_required": False, "evidence_status": "insufficient",
                   "candidate_evidence_status": "INCONCLUSIVE", "decision_correctness": "INCONCLUSIVE",
                   "scientific_success": "INCONCLUSIVE", "evaluation_coverage": {"status": "PARTIAL",
                       "trusted_execution": "UNVERIFIED", "gaps": ["fixed trusted operator context is not installed or could not be verified",
                       "recovery-path suite coverage has not been established by a genuine trajectory"]}}
    # No-reward outcomes omit reward from the serialized verification record.
    # Keep reward=None in evaluate() for in-process callers, and omit it only
    # from the serialized runner report when no score is available.
    report = dict(outcome)
    if report.get("reward") is None:
        report.pop("reward", None)
    (logs / "verification.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if outcome["reward"] is not None:
        reward.write_text(f"{outcome['reward']:g}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return {"PASS": 0, "REVIEW_REQUIRED": 0, "FAIL": 1, "ENV_INVALID": 2}.get(outcome["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
