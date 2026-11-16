#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Assessing short-prefix PaiNN/SHARC dynamics.
"""Case-04 v2 fail-closed scorer entrypoint (short-prefix execution decision).

This verifier deliberately does not import or reuse the retired 100 fs auditor.
The bounded runtime and independent scorer integration are implemented and
evaluable through the standard runner. A recorded standard-Oracle run exercised
the real same-attempt host path (Slurm Job 10040, two 10 fs prefixes); this is
reference evidence, not an independent Agent attempt. Scientific calibration
remains incomplete, and the single 2 x 10 fs run does not establish general
worst-case resource use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import stat
from pathlib import Path

"""Independent short-prefix SHARC audit for Bench25 case-04 v2.

This module is intentionally separate from the retired 100 fs native auditor.
It parses native text using the standard library and makes no lifetime claim.
"""

import hashlib
import json
import math
import re
import shlex
from pathlib import Path, PurePosixPath
from typing import Any

PLAN_SCHEMA = "bench25-case04-probe-plan/v3"
SEAL_SCHEMA = "bench25-case04-probe-plan-seal/v1"
RESULT_SCHEMA = "bench25-case04-probe-result/v1"
DECISION_SCHEMA = "bench25-case04-decision/v1"
DT_FS = 0.5
MAX_RESOURCE_WALL_SECONDS = 300
PROBE_RESOURCE_POLICY = {"max_time_limit_seconds": MAX_RESOURCE_WALL_SECONDS}
POOL_SHA256 = "96e52569ef2cf7a404a4a84a927a186fd6e510bf19a18088261c8c61a2176a4e"
MODEL_SHA256 = "a3b5db7ed33806ac6371ab6fd10511eb2aaf3580f42d2b13ea8e091294e80a87"
MODEL_SOURCE_SHA256 = "c09b8e3b711ab48d00e68c2222e08ed27b8c50cb42a75747a9ed0733385c3110"
MODEL_EXPORT_ADAPTER_SHA256 = "c45af95edf48dc49dd49439e609c676d0191166599a55fbd4968d942ea6f992c"
RUNTIME_ADAPTER_SHA256 = "8b00da02f268bbdcdbfc9d5d76d005489476b977924492f94af5c0e5129d98bf"
DB_SHA256 = "52cb7f039931cdb9f1082722ca127a1e3e89bd8c1b3bd0bcdea5a488e38c0a9d"
GRID_SHA256 = "c96d27459e77ab5220dddc407a9969425c3878ae1c6427838dc44c8f350a431b"
SHARC_SHA256 = "f47daa3b5c3be8a5946d9d802fab669a1d8e5eea57ce97141b030d1f9d2e6f65"
RISK_SET = {"energy_force_consistency", "nac_phase_continuity", "low_gap_coupling",
            "ood_coverage", "surface_hop_stability"}
RISK_COVERAGE_UNMEASURED = {name: False for name in sorted(RISK_SET)}
def _safe_remote_root(value: Any) -> str | None:
    """Accept a clean absolute host work root, bound by the protected receipt."""
    if not isinstance(value, str) or not value.startswith("/"):
        return None
    path = PurePosixPath(value)
    if ".." in path.parts or path.as_posix() != value.rstrip("/"):
        return None
    return value.rstrip("/")


def _scheduler_gpu_count(text: str) -> int:
    """Read GPU count from Slurm GRES/TRES text; no GPU means zero."""
    counts = []
    for match in re.finditer(r"(?:^|[, ])gres/gpu(?::[A-Za-z0-9_.-]+)?=([0-9]+)", text):
        counts.append(int(match.group(1)))
    if not counts:
        for match in re.finditer(r"(?:^|[, ])gpu(?::[A-Za-z0-9_.-]+)?:([0-9]+)(?:\([^)]*\))?(?=$|[, ])", text):
            counts.append(int(match.group(1)))
    return sum(counts)
PLAN_KEYS = {"schema", "model_sha256", "inference_model_sha256", "model_source_sha256", "ic_pool_sha256",
             "runtime_adapter_sha256",
             "trajectory_indices_zero_based", "duration_fs", "dt_fs",
             "energy_drift_threshold_ev", "risk_hypotheses", "stop_rules", "resource_request",
             "software_environment",
             "continue_or_stop_rule"}


class ProbeAuditError(ValueError):
    """Candidate evidence is malformed or scientifically inconsistent."""


class ProbeEnvironmentError(RuntimeError):
    """Trusted host/runtime evidence is missing or unavailable."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path, *, environment: bool = False) -> Any:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError("missing or redirected file")
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        error = ProbeEnvironmentError if environment else ProbeAuditError
        raise error(f"cannot read {path}: {exc}") from exc


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ProbeAuditError(f"{name} must be finite numeric data")
    return float(value)


def validate_plan(plan: Any) -> dict:
    if not isinstance(plan, dict) or set(plan) != PLAN_KEYS:
        raise ProbeAuditError("probe plan has missing or unsupported fields")
    if plan.get("schema") != PLAN_SCHEMA:
        raise ProbeAuditError("unsupported probe plan schema")
    resources = plan.get("resource_request")
    if (not isinstance(resources, dict)
            or set(resources) != {"cpus", "memory_gb", "wall_seconds", "accelerator", "gpu_count"}
            or any(type(resources.get(key)) is not int or resources[key] < 1
                   for key in ("cpus", "memory_gb", "wall_seconds"))
            or type(resources.get("gpu_count")) is not int or resources["gpu_count"] < 0
            or resources.get("accelerator") not in {"cpu", "gpu"}
            or (resources["accelerator"] == "cpu" and resources["gpu_count"] != 0)
            or (resources["accelerator"] == "gpu" and resources["gpu_count"] < 1)
            or resources["wall_seconds"] > PROBE_RESOURCE_POLICY["max_time_limit_seconds"]):
        raise ProbeAuditError("resource_request must contain positive resources and a supported accelerator within the 300-second task budget")
    software_environment = plan.get("software_environment")
    if (not isinstance(software_environment, dict) or not software_environment
            or any(not isinstance(name, str) or not name or not isinstance(version, str)
                   or not version.strip() or len(name) > 64 or len(version) > 128
                   for name, version in software_environment.items())):
        raise ProbeAuditError("software_environment must record software names and selected versions")
    for key, expected in (("model_sha256", MODEL_SHA256),
                          ("inference_model_sha256", "6365499f367fdba5d0299ec91632ddfd961fe695809dbed80f5e8ffbc85bc31c"),
                          ("model_source_sha256", MODEL_SOURCE_SHA256),
                          ("runtime_adapter_sha256", RUNTIME_ADAPTER_SHA256),
                          ("ic_pool_sha256", POOL_SHA256)):
        if plan.get(key) != expected:
            raise ProbeAuditError(f"probe plan {key} differs from the pinned baseline")
    indices = plan.get("trajectory_indices_zero_based")
    durations = plan.get("duration_fs")
    if (not isinstance(indices, list) or not 1 <= len(indices) <= 2
            or any(type(i) is not int or i not in range(40) for i in indices)
            or len(set(indices)) != len(indices)):
        raise ProbeAuditError("probe plan must select one or two unique fixed-pool indices")
    if not isinstance(durations, list) or len(durations) != len(indices):
        raise ProbeAuditError("duration_fs must align one-to-one with selected indices")
    for value in durations:
        t = _finite_number(value, "duration_fs")
        if not 5.0 <= t <= 10.0 or abs(t / DT_FS - round(t / DT_FS)) > 1e-9:
            raise ProbeAuditError("each probe duration must be 5–10 fs on the 0.5 fs grid")
    if _finite_number(plan.get("dt_fs"), "dt_fs") != DT_FS:
        raise ProbeAuditError("v2 nuclear timestep is fixed at 0.5 fs")
    threshold = _finite_number(plan.get("energy_drift_threshold_ev"), "energy_drift_threshold_ev")
    if threshold <= 0:
        raise ProbeAuditError("pre-result energy drift threshold must be positive")
    risks = plan.get("risk_hypotheses")
    if (not isinstance(risks, list) or not risks or len(set(risks)) != len(risks)
            or not set(risks) <= RISK_SET):
        raise ProbeAuditError("risk_hypotheses must be a non-empty subset of supported diagnostics")
    rules = plan.get("stop_rules")
    required_stops = {"driver_failure", "non_finite", "energy_drift", "identity_mismatch", "missing_records"}
    if (not isinstance(rules, dict) or set(rules) != required_stops
            or rules.get("driver_failure") != "stop"
            or rules.get("non_finite") != "stop"
            or rules.get("identity_mismatch") != "stop"
            or rules.get("missing_records") != "stop"
            or rules.get("energy_drift") not in {"stop", "diagnose"}):
        raise ProbeAuditError("stop_rules must use supported machine actions for every hard-stop event")
    decision = plan.get("continue_or_stop_rule")
    if (not isinstance(decision, dict)
            or set(decision) != {"continue_when", "otherwise"}
            or decision.get("continue_when") != ["all_runs_complete", "all_drifts_below_threshold", "all_risks_assessed"]
            or decision.get("otherwise") != "diagnose_or_stop"):
        raise ProbeAuditError("continue_or_stop_rule must match the machine-checkable v1 trigger contract")
    return plan


def validate_plan_seal(plan: dict, seal: Any, *, context: dict,
                       submitted_at: str | None = None) -> dict:
    """Validate a host-owned pre-submission plan seal against runner context."""
    validate_plan(plan)
    if not isinstance(seal, dict) or seal.get("schema") != SEAL_SCHEMA:
        raise ProbeEnvironmentError("host preregistration seal is missing or malformed")
    if seal.get("plan_sha256") != canonical_sha256(plan):
        raise ProbeEnvironmentError("host preregistration does not bind the candidate plan bytes")
    image_id = context.get("image_id") if isinstance(context, dict) else None
    closure_sha = context.get("runtime_closure_sha256") if isinstance(context, dict) else None
    if (not isinstance(image_id, str)
            or re.fullmatch(r"runtime-closure-sha256:[0-9a-f]{64}", image_id) is None
            or context.get("image_identity_kind") != "runtime-closure-sha256"
            or closure_sha != image_id.removeprefix("runtime-closure-sha256:")
            or seal.get("attempt_id") != context.get("attempt_id")
            or seal.get("run_id") != context.get("run_id")
            or seal.get("task_id") != "case-04"
            or seal.get("image_id") != image_id):
        raise ProbeEnvironmentError("host preregistration is cross-bound to a different attempt/task/image")
    if (seal.get("model_sha256") != plan["model_sha256"]
            or seal.get("inference_model_sha256") != plan["inference_model_sha256"]
            or seal.get("ic_pool_sha256") != plan["ic_pool_sha256"]):
        raise ProbeEnvironmentError("host preregistration model/pool pins differ from the frozen plan")
    if (seal.get("resource_request") != plan["resource_request"]
            or seal.get("resource_request_sha256") != canonical_sha256(plan["resource_request"])):
        raise ProbeEnvironmentError("host preregistration does not bind the planned resource request")
    try:
        _timestamp(seal.get("registered_at_utc"))
    except (TypeError, ValueError) as exc:
        raise ProbeEnvironmentError("host plan seal timestamp is malformed") from exc
    if seal.get("dispatch_count") != 0 or "slurm_submit_time_utc" in seal:
        raise ProbeEnvironmentError("pre-dispatch plan seal must precede and not claim a Slurm dispatch")
    return seal


def _timestamp(value: Any):
    from datetime import datetime
    if not isinstance(value, str):
        raise ValueError("timestamp is not a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed


def _native_rows(path: Path, expected_columns: int) -> list[list[float]]:
    if path.is_symlink() or not path.is_file():
        raise ProbeAuditError(f"native trace is missing or redirected: {path}")
    rows: list[list[float]] = []
    for n, raw in enumerate(path.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        try:
            row = [float(token.replace("D", "E").replace("d", "e")) for token in raw.split()]
        except ValueError as exc:
            raise ProbeAuditError(f"non-numeric native row {path}:{n}") from exc
        if len(row) != expected_columns or not all(math.isfinite(x) for x in row):
            raise ProbeAuditError(f"native row {path}:{n} has wrong shape or non-finite data")
        rows.append(row)
    return rows


def _load_fixed_ic(pool_path: Path, index: int) -> dict:
    """Load the pinned public pool entry; never accept candidate-supplied IC data."""
    if pool_path.is_symlink() or not pool_path.is_file() or sha256(pool_path) != POOL_SHA256:
        raise ProbeEnvironmentError("fixed public initial-condition pool is missing, redirected, or has the wrong hash")
    pool = load_json(pool_path, environment=True)
    entries = pool.get("initial_conditions") if isinstance(pool, dict) else None
    if not isinstance(entries, list) or len(entries) != 40 or not 0 <= index < len(entries):
        raise ProbeEnvironmentError("pinned IC pool has an unexpected shape or index")
    ic = entries[index]
    if (not isinstance(ic, dict) or ic.get("state_label") != "S1"
            or ic.get("state_mch_1based") != 2
            or ic.get("symbols") != ["C"] * 4 + ["H"] * 8):
        raise ProbeEnvironmentError("pinned initial condition is not the expected 12-atom S1 MCH entry")
    return ic


def _parse_sharc_input(path: Path, *, duration_fs: float) -> dict[str, list[str]]:
    if path.is_symlink() or not path.is_file():
        raise ProbeEnvironmentError("retained SHARC input is missing or redirected")
    directives: dict[str, list[str]] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
        try:
            fields = shlex.split(line, comments=True, posix=True)
        except ValueError as exc:
            raise ProbeEnvironmentError(f"retained SHARC input quoting is malformed at line {line_no}") from exc
        if not fields or fields[0].startswith("#"):
            continue
        key = fields[0].lower()
        if key in directives:
            raise ProbeEnvironmentError(f"retained SHARC input repeats directive {key} at line {line_no}")
        directives[key] = fields[1:]
    exact = {
        "geomfile": ["geom"], "veloc": ["external"], "velocfile": ["veloc"],
        "nstates": ["3", "0", "0"], "actstates": ["3", "0", "0"],
        "state": ["2", "mch"], "stepsize": ["0.5"], "nsubsteps": ["25"],
        "surf": ["sharc"], "coupling": ["nacdr"], "nogradcorrect": [],
        "ekincorrect": ["parallel_vel"], "decoherence_scheme": ["edc"],
        "select_directly": [], "output_format": ["ascii"], "notrack_phase": [],
    }
    for key, value in exact.items():
        if directives.get(key) != value:
            raise ProbeEnvironmentError(f"retained SHARC input has unexpected {key} directive")
    try:
        tmax = float(directives["tmax"][0])
    except (KeyError, IndexError, ValueError) as exc:
        raise ProbeEnvironmentError("retained SHARC input lacks numeric tmax") from exc
    if len(directives.get("tmax", [])) != 1 or not math.isclose(tmax, duration_fs, rel_tol=0, abs_tol=1e-9):
        raise ProbeEnvironmentError("retained SHARC input tmax differs from the preregistered duration")
    return directives


def _compare_initial_files(run_dir: Path, ic: dict) -> None:
    """Compare actual SHARC geometry and velocities with the selected pool values."""
    geom_path, veloc_path = run_dir / "geom", run_dir / "veloc"
    for path in (geom_path, veloc_path):
        if path.is_symlink() or not path.is_file():
            raise ProbeEnvironmentError(f"initial-condition file is missing or redirected: {path.name}")
    geom_rows = []
    for line_no, line in enumerate(geom_path.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
        fields = line.split()
        if len(fields) != 6:
            raise ProbeEnvironmentError(f"SHARC geom row {line_no} must have six COLUMBUS fields")
        try:
            geom_rows.append((fields[0], int(fields[1]), [float(x) for x in fields[2:5]], float(fields[5])))
        except ValueError as exc:
            raise ProbeEnvironmentError(f"SHARC geom row {line_no} is malformed") from exc
    symbols = ic["symbols"]
    atomic_numbers = [6 if symbol == "C" else 1 for symbol in symbols]
    coords = ic.get("positions_bohr")
    masses = ic.get("masses_u")
    velocities = ic.get("velocities_atomic_units")
    if len(geom_rows) != 12 or not isinstance(coords, list) or not isinstance(masses, list):
        raise ProbeEnvironmentError("pinned IC geometry/mass shape is invalid")
    for n, (row, symbol, z, xyz, mass) in enumerate(zip(geom_rows, symbols, atomic_numbers, coords, masses)):
        got_symbol, got_z, got_xyz, got_mass = row
        if got_symbol != symbol or got_z != z or len(xyz) != 3:
            raise ProbeEnvironmentError(f"SHARC geom atom identity differs from fixed pool at atom {n}")
        if (max(abs(a - float(b)) for a, b in zip(got_xyz, xyz)) > 6e-10
                or abs(got_mass - float(mass)) > 6e-8):
            raise ProbeEnvironmentError(f"SHARC geom coordinates/mass differ from fixed pool at atom {n}")
    vel_rows = []
    for line_no, line in enumerate(veloc_path.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
        fields = line.split()
        if len(fields) != 3:
            raise ProbeEnvironmentError(f"SHARC veloc row {line_no} must contain 3 atomic-unit values")
        try:
            vel_rows.append([float(x) for x in fields])
        except ValueError as exc:
            raise ProbeEnvironmentError(f"SHARC veloc row {line_no} is malformed") from exc
    if (len(vel_rows) != 12 or not isinstance(velocities, list)
            or any(len(row) != 3 for row in velocities)):
        raise ProbeEnvironmentError("SHARC velocity shape differs from fixed pool")
    if max(abs(a - float(b)) for row_a, row_b in zip(vel_rows, velocities)
           for a, b in zip(row_a, row_b)) > 6e-14:
        raise ProbeEnvironmentError("SHARC atomic velocities differ from fixed pool")


def audit_native_run(run_dir: Path, *, index: int, duration_fs: float,
                     drift_threshold_ev: float, host_receipt: dict,
                     ic_pool_path: Path | None = None,
                     drift_calibration_ready: bool = False,
                     stop_on_energy_drift: bool = False) -> dict:
    """Audit a bounded real native trace; malformed receipts are environment errors."""
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise ProbeEnvironmentError("host-captured probe run directory is missing or redirected")
    if not isinstance(host_receipt, dict) or host_receipt.get("pool_index_zero_based") != index:
        raise ProbeEnvironmentError("host run receipt does not bind the planned fixed-pool index")
    if host_receipt.get("model_sha256") != MODEL_SHA256 or host_receipt.get("ic_pool_sha256") != POOL_SHA256:
        raise ProbeEnvironmentError("host run receipt model/pool identity does not match the fixed baseline")
    if host_receipt.get("source_database_sha256") != DB_SHA256:
        raise ProbeEnvironmentError("host run receipt does not bind the public training DB")
    backend = host_receipt.get("backend")
    if backend == "scheduler":
        if host_receipt.get("slurm_job_id") is None or not str(host_receipt["slurm_job_id"]).isdigit():
            raise ProbeEnvironmentError("host run receipt lacks a valid Slurm job ID")
    elif (backend != "local" or not isinstance(host_receipt.get("execution_id"), str)
          or host_receipt.get("execution_id") == ""):
        raise ProbeEnvironmentError("host run receipt lacks a trusted local execution identity")
    for name, key in (("geom", "geom_sha256"), ("veloc", "veloc_sha256"), ("input", "input_sha256")):
        expected = host_receipt.get(key)
        path = run_dir / name
        if (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)
                or path.is_symlink() or not path.is_file()):
            raise ProbeEnvironmentError(f"host receipt lacks authentic initial {name} input evidence")
        if sha256(path) != expected:
            raise ProbeEnvironmentError(f"initial {name} hash differs from host receipt")
    if ic_pool_path is None:
        ic_pool_path = Path("/app/inputs/pilot-baseline/initial_conditions/a03_equiv_s1_40.json")
    fixed_ic = _load_fixed_ic(ic_pool_path, index)
    _compare_initial_files(run_dir, fixed_ic)
    _parse_sharc_input(run_dir / "input", duration_fs=duration_fs)
    job_terminal = host_receipt.get("terminal_status")
    job_exit = host_receipt.get("job_exit_code")
    if job_terminal not in {"COMPLETED", "FAILED", "TIMEOUT", "OUT_OF_MEMORY", "CANCELLED"}:
        raise ProbeEnvironmentError("host receipt lacks a terminal execution state")
    if type(job_exit) is not int:
        raise ProbeEnvironmentError("host receipt lacks the integer execution exit code")
    resource = host_receipt.get("resources")
    request = host_receipt.get("resource_request")
    if (not isinstance(request, dict)
            or set(request) != {"cpus", "memory_gb", "wall_seconds", "accelerator", "gpu_count"}
            or any(type(request.get(key)) is not int or request[key] < 1
                   for key in ("cpus", "memory_gb", "wall_seconds"))
            or type(request.get("gpu_count")) is not int or request["gpu_count"] < 0
            or request.get("accelerator") not in {"cpu", "gpu"}
            or (request["accelerator"] == "cpu" and request["gpu_count"] != 0)
            or (request["accelerator"] == "gpu" and request["gpu_count"] < 1)
            or request["wall_seconds"] > PROBE_RESOURCE_POLICY["max_time_limit_seconds"]):
        raise ProbeEnvironmentError("host receipt does not bind a well-formed resource request")
    required_resource = {"elapsed_seconds", "max_rss_kib", "allocated_cpus", "requested_memory",
                         "gpu_count", "time_limit_seconds"}
    if backend == "scheduler":
        required_resource |= {"node_list", "account", "qos", "partition"}
    if not isinstance(resource, dict) or not required_resource <= set(resource):
        raise ProbeEnvironmentError("host run receipt lacks actual resource fields")
    if (type(resource.get("elapsed_seconds")) is not int or resource["elapsed_seconds"] < 0
            or type(resource.get("allocated_cpus")) is not int or resource["allocated_cpus"] < 0
            or type(resource.get("gpu_count")) is not int
            or type(resource.get("time_limit_seconds")) is not int
            or resource["time_limit_seconds"] <= 0
            or resource["time_limit_seconds"] != request["wall_seconds"]
            or not isinstance(resource.get("max_rss_kib"), str)
            or (backend == "scheduler" and not isinstance(resource.get("node_list"), str))
            or not isinstance(resource.get("requested_memory"), str)):
        raise ProbeEnvironmentError("host execution resources are malformed")
    memory_match = re.fullmatch(r"([0-9]+)G[nNcC]?", resource["requested_memory"])
    expected_resources = {"allocated_cpus": request["cpus"],
                          "gpu_count": request["gpu_count"],
                          "time_limit_seconds": request["wall_seconds"]}
    if memory_match is None or int(memory_match.group(1)) != request["memory_gb"]:
        raise ProbeEnvironmentError("host requested memory differs from the sealed resource request")
    try:
        started_at = _timestamp(host_receipt.get("started_at_utc"))
        ended_at = _timestamp(host_receipt.get("ended_at_utc"))
    except (TypeError, ValueError) as exc:
        raise ProbeEnvironmentError("host execution start/end timestamps are malformed") from exc
    elapsed_from_clock = (ended_at - started_at).total_seconds()
    if abs(elapsed_from_clock - resource["elapsed_seconds"]) > 1.0:
        raise ProbeEnvironmentError("protected execution elapsed time disagrees with its start/end timestamps")
    for key, expected in expected_resources.items():
        if resource.get(key) != expected:
            raise ProbeEnvironmentError(f"host Slurm resource {key} differs from the sealed request")
    if backend == "scheduler":
        for key in ("account", "qos", "partition", "node_list"):
            if not isinstance(resource.get(key), str) or not resource[key]:
                raise ProbeEnvironmentError(f"host Slurm resource {key} is missing")
    for key in (("allocated_cpus", "node_list", "requested_memory", "account", "qos",
                 "partition", "gpu_count", "time_limit_seconds") if backend == "scheduler" else
                ("allocated_cpus", "requested_memory", "gpu_count", "time_limit_seconds")):
        if resource.get(key) != host_receipt.get(key):
            raise ProbeEnvironmentError(f"host resource receipt disagrees on {key}")
    if backend == "scheduler":
        work_root = _safe_remote_root(host_receipt.get("work_dir"))
        if (work_root is None
                or not isinstance(host_receipt.get("job_name"), str)
                or re.fullmatch(r"case04-probe-[A-Za-z0-9-]{1,80}", host_receipt["job_name"]) is None):
            raise ProbeEnvironmentError("Slurm job work directory/name is malformed")
    energy_path = run_dir / "output_data/energy.out"
    surface_path = run_dir / "output_data/coeff_class_diag.out"
    expec_path = run_dir / "output_data/expec.out"
    for path, key in ((energy_path, "energy_sha256"), (surface_path, "surface_sha256"),
                      (expec_path, "expec_sha256")):
        expected = host_receipt.get(key)
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ProbeEnvironmentError(f"host receipt lacks {key}")
        try:
            actual_hash = sha256(path)
        except OSError as exc:
            raise ProbeEnvironmentError(f"host-captured native file is unavailable: {path.name}") from exc
        if actual_hash != expected:
            raise ProbeEnvironmentError(f"host-captured native file hash mismatch: {path.name}")
    energy = _native_rows(energy_path, 7)
    surface = _native_rows(surface_path, 5)
    expec = _native_rows(expec_path, 13)
    if not energy or len(energy) != len(surface) or len(energy) != len(expec):
        raise ProbeAuditError("native energy, surface, and expectation records are empty or misaligned")
    expected_intervals = int(round(duration_fs / DT_FS))
    expected_times = [n * DT_FS for n in range(expected_intervals + 1)]
    actual_times = [row[0] for row in energy]
    if len(actual_times) > len(expected_times) or any(
            abs(a - b) > 1e-6 for a, b in zip(actual_times, expected_times)):
        raise ProbeAuditError("native trace time grid differs from the preregistered 0.5 fs prefix")
    if any(abs(row[0] - expected_times[n]) > 1e-6 for n, row in enumerate(surface)):
        raise ProbeAuditError("native population time grid differs from the energy trace")
    if any(abs(row[0] - expected_times[n]) > 1e-6 for n, row in enumerate(expec)):
        raise ProbeAuditError("native state-energy time grid differs from the energy trace")
    if len(energy) != len(surface):
        raise ProbeAuditError("native energy/surface trace grid lengths differ")
    if any(max(abs(energy_row[column] - expec_row[column]) for column in range(1, 4)) > 1e-6
           for energy_row, expec_row in zip(energy, expec)):
        raise ProbeAuditError("native energy and expectation files disagree on Ekin/Epot/Etot")
    driver_rc = host_receipt.get("driver_exit_code")
    if type(driver_rc) is not int:
        raise ProbeEnvironmentError("host receipt lacks the actual integer driver exit code")
    native_prefix_complete = len(energy) == len(expected_times)
    condition_trace_complete = native_prefix_complete and driver_rc == 0
    pop = [row[2:5] for row in surface]
    for row in pop:
        if any(x < -1e-8 or x > 1.0 + 1e-8 for x in row) or abs(sum(row) - 1.0) > 1e-6:
            raise ProbeAuditError("native state populations leave [0,1] or do not sum to one")
        if sum(abs(x - 1.0) < 1e-7 for x in row) != 1 or sum(abs(x) < 1e-7 for x in row) != 2:
            raise ProbeAuditError("this SHARC configuration requires one-hot active-surface populations")
    if any(abs(row[1] - 1.0) > 1e-7 for row in surface):
        raise ProbeAuditError("native surface population sum column differs from one")
    if any(abs(a - b) > 1e-6 for a, b in zip(pop[0], (0.0, 1.0, 0.0))):
        raise ProbeAuditError("initial active surface is not the preregistered S1 state")
    identity_error = max(abs(row[3] - row[1] - row[2]) for row in energy)
    if identity_error > 1e-7:
        raise ProbeAuditError("native Etot differs from Ekin + Epot")
    drift = max(abs(row[3] - energy[0][3]) for row in energy)
    gaps_10 = [abs(row[5] - row[4]) for row in expec]
    gaps_21 = [abs(row[6] - row[5]) for row in expec]
    min_adjacent_gap = min(gaps_10 + gaps_21)
    low_gap_cutoff_ev = 0.2
    low_gap_records = sum(gap <= low_gap_cutoff_ev for gap in gaps_10 + gaps_21)
    active_surfaces = [max(range(3), key=lambda state: row[2 + state]) for row in surface]
    hop_count = sum(a != b for a, b in zip(active_surfaces, active_surfaces[1:]))
    if job_terminal == "COMPLETED" and job_exit != 0:
        raise ProbeEnvironmentError("sacct reports COMPLETED with a nonzero parent exit code")
    drift_exceeded = drift > drift_threshold_ev
    scheduler_failed = job_terminal != "COMPLETED" or job_exit != 0
    # Calibration readiness is deliberately not a failure trigger. It only
    # gates a positive reliability/continue decision; a skipped condition
    # needs an observed execution failure or a preregistered hard-stop event.
    # A later parent-job failure must not retroactively turn an earlier
    # condition into a stop-rule trigger. Keep native completeness, condition
    # hard-stop, and whole-job success as distinct facts.
    complete = condition_trace_complete and not scheduler_failed
    stop_rule_trigger = (not condition_trace_complete
                         or (drift_exceeded and stop_on_energy_drift))
    return {
        "pool_index_zero_based": index, "execution_backend": backend,
        "execution_id": host_receipt["execution_id"],
        "planned_duration_fs": float(duration_fs), "observed_end_fs": actual_times[-1],
        "dt_fs": DT_FS, "native_records": len(energy), "complete": complete,
        "native_prefix_complete": native_prefix_complete,
        "condition_trace_complete": condition_trace_complete,
        "job_successful": not scheduler_failed,
        "status": "complete" if complete else "censored_trace",
        "energy_sha256": sha256(energy_path), "surface_sha256": sha256(surface_path),
        "max_total_energy_drift_ev": drift, "drift_threshold_ev": float(drift_threshold_ev),
        "energy_identity_max_abs_ev": identity_error,
        "initial_population_s0_s1_s2": pop[0],
        "drift_below_candidate_threshold": drift <= drift_threshold_ev,
        "observed_trigger": (not condition_trace_complete or drift_exceeded),
        "stop_rule_trigger": stop_rule_trigger,
        "terminal_status": job_terminal, "execution_exit_code": job_exit,
        "audited_risk_coverage": {
            # Computing total-energy diagnostics does not exercise model-force
            # accuracy; this risk remains only partially observed until forces
            # are emitted and independently compared to the fixed reference.
            "energy_force_consistency": False,
            "nac_phase_continuity": False,
            "low_gap_coupling": low_gap_records > 0,
            "ood_coverage": False,
            "surface_hop_stability": hop_count > 0,
        },
        "audited_risk_metrics": {
            "energy_force_consistency": {
                "energy_identity_max_abs_ev": identity_error,
                "max_total_energy_drift_ev": drift,
                "energy_diagnostics_computed": True,
                "force_error": "not_sampled",
                "risk_pressure_sampled": False,
                "energy_sha256": sha256(energy_path),
            },
            "nac_phase_continuity": {"status": "not_sampled", "reason": "no NAC output requested"},
            "low_gap_coupling": {
                "minimum_adjacent_state_gap_ev": min_adjacent_gap,
                "records_at_or_below_0_2_ev": low_gap_records,
                "pair_time_samples_at_or_below_cutoff": low_gap_records,
                "pair_time_sample_count": 2 * len(expec),
                "time_rows_with_any_gap_at_or_below_cutoff": sum(
                    a <= low_gap_cutoff_ev or b <= low_gap_cutoff_ev
                    for a, b in zip(gaps_10, gaps_21)),
                "record_count": len(expec), "cutoff_ev": low_gap_cutoff_ev,
                "risk_pressure_sampled": low_gap_records > 0,
                "expec_sha256": sha256(expec_path),
            },
            "ood_coverage": {"status": "not_sampled", "reason": "no frozen training-support descriptor"},
            "surface_hop_stability": {
                "active_surface_switches": hop_count,
                "active_surface_indices_zero_based": active_surfaces,
                "risk_pressure_sampled": hop_count > 0,
                "surface_sha256": sha256(surface_path),
            },
        },
        "reliable_for_planned_prefix": (drift_calibration_ready and complete
                                           and drift <= drift_threshold_ev),
        "censored_reason": (None if complete else host_receipt.get("censored_reason", "driver_or_trace_incomplete")),
        "lifetime_claim": None,
    }


def audit_driver_failed_before_trace(run_dir: Path, *, index: int, duration_fs: float,
                                     host_receipt: dict,
                                     ic_pool_path: Path | None = None) -> dict:
    """Retain a failed attempted condition that produced no native records."""
    if host_receipt.get("driver_exit_code") == 0:
        raise ProbeEnvironmentError("driver_failed_before_trace requires a nonzero driver exit")
    if ic_pool_path is None:
        ic_pool_path = Path("/app/inputs/pilot-baseline/initial_conditions/a03_equiv_s1_40.json")
    for name, key in (("geom", "geom_sha256"), ("veloc", "veloc_sha256"), ("input", "input_sha256")):
        path = run_dir / name
        expected = host_receipt.get(key)
        if (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)
                or path.is_symlink() or not path.is_file() or sha256(path) != expected):
            raise ProbeEnvironmentError(f"failed condition lacks authentic {name} input evidence")
    ic = _load_fixed_ic(ic_pool_path, index)
    _compare_initial_files(run_dir, ic)
    _parse_sharc_input(run_dir / "input", duration_fs=duration_fs)
    for rel in ("output_data/energy.out", "output_data/coeff_class_diag.out"):
        path = run_dir / rel
        if path.exists() or path.is_symlink():
            raise ProbeEnvironmentError("driver_failed_before_trace contradicts retained native output")
    for key in ("driver_stdout_sha256", "driver_stderr_sha256"):
        if not isinstance(host_receipt.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", host_receipt[key]):
            raise ProbeEnvironmentError("failed condition lacks hashed driver logs")
    return {
        "pool_index_zero_based": index,
        "execution_backend": host_receipt.get("backend"),
        "execution_id": host_receipt.get("execution_id"),
        "planned_duration_fs": float(duration_fs),
        "observed_end_fs": None,
        "dt_fs": DT_FS,
        "native_records": 0,
        "complete": False,
        "native_prefix_complete": False,
        "condition_trace_complete": False,
        "job_successful": (host_receipt.get("terminal_status") == "COMPLETED"
                            and host_receipt.get("job_exit_code") == 0),
        "status": "driver_failed_before_trace",
        "energy_sha256": None,
        "surface_sha256": None,
        "max_total_energy_drift_ev": None,
        "drift_threshold_ev": float(host_receipt["drift_threshold_ev"]),
        "energy_identity_max_abs_ev": None,
        "initial_population_s0_s1_s2": None,
        "drift_below_candidate_threshold": False,
        "observed_trigger": True,
        "stop_rule_trigger": True,
        "terminal_status": host_receipt.get("terminal_status"),
        "execution_exit_code": host_receipt.get("job_exit_code"),
        "audited_risk_coverage": dict(RISK_COVERAGE_UNMEASURED),
        "reliable_for_planned_prefix": False,
        "censored_reason": host_receipt.get("censored_reason") or "driver_failed_before_trace",
        "lifetime_claim": None,
    }


def validate_host_capture(trusted_root: Path, *, context: dict,
                          plan: dict) -> tuple[dict, dict]:
    """Verify a one-dispatch scheduler capture and per-condition run closure."""
    require_trusted_probe_mount(trusted_root)
    plan_obj = load_json(trusted_root / "candidate-plan.json", environment=True)
    seal = load_json(trusted_root / "preregistration.json", environment=True)
    execution = load_json(trusted_root / "execution.json", environment=True)
    if canonical_sha256(plan_obj) != canonical_sha256(plan):
        raise ProbeEnvironmentError("protected host plan differs from submitted candidate plan")
    validate_plan_seal(plan_obj, seal, context=context)
    if not isinstance(execution, dict) or execution.get("schema") != "bench25-case04-probe-execution/v3":
        raise ProbeEnvironmentError("host execution receipt is missing or malformed")
    backend = execution.get("backend")
    execution_id = execution.get("execution_id")
    if (backend not in {"local", "scheduler"} or backend != context.get("execution_backend")
            or not isinstance(execution_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}", execution_id) is None
            or execution_id != context.get("execution_id")):
        raise ProbeEnvironmentError("protected execution backend or ID differs from the runner context")
    if (execution.get("plan_sha256") != canonical_sha256(plan)
            or execution.get("attempt_id") != context.get("attempt_id")
            or execution.get("run_id") != context.get("run_id")
            or execution.get("dispatch_count") != 1):
        raise ProbeEnvironmentError("host execution capture differs from the preregistered attempt")
    software_environment = execution.get("software_environment")
    if (not isinstance(software_environment, dict) or not software_environment
            or software_environment != plan.get("software_environment")
            or execution.get("software_environment_sha256") != canonical_sha256(software_environment)):
        raise ProbeEnvironmentError("protected execution software versions differ from the preregistered environment")
    try:
        started_at = _timestamp(execution.get("started_at_utc"))
        ended_at = _timestamp(execution.get("ended_at_utc"))
        if started_at < _timestamp(seal["registered_at_utc"]) or ended_at < started_at:
            raise ProbeEnvironmentError("execution timestamps precede preregistration or are reversed")
        elapsed_from_clock = (ended_at - started_at).total_seconds()
        elapsed_seconds = execution.get("elapsed_seconds")
        if (type(elapsed_seconds) is not int or elapsed_seconds < 0
                or abs(elapsed_from_clock - elapsed_seconds) > 1.0):
            raise ProbeEnvironmentError("protected execution elapsed time disagrees with its timestamps")
        if elapsed_from_clock > MAX_RESOURCE_WALL_SECONDS:
            raise ProbeAuditError("protected execution exceeded the 300-second scientific attempt budget")
        resources = execution.get("resources")
        request = plan.get("resource_request")
        required_resources = {"elapsed_seconds", "max_rss_kib", "allocated_cpus", "requested_memory",
                              "gpu_count", "time_limit_seconds"}
        if backend == "scheduler":
            required_resources |= {"node_list", "account", "qos", "partition"}
        memory = resources.get("requested_memory") if isinstance(resources, dict) else None
        match = re.fullmatch(r"([0-9]+)G[nNcC]?", memory) if isinstance(memory, str) else None
        if (not isinstance(resources, dict) or not required_resources <= set(resources)
                or not isinstance(request, dict) or match is None
                or int(match.group(1)) != request["memory_gb"]
                or type(resources.get("elapsed_seconds")) is not int
                or abs(resources["elapsed_seconds"] - elapsed_seconds) > 1
                or resources.get("allocated_cpus") != request["cpus"]
                or resources.get("gpu_count") != request["gpu_count"]
                or resources.get("time_limit_seconds") != request["wall_seconds"]):
            raise ProbeEnvironmentError("protected execution resource summary differs from its sealed request")
        for key in ("allocated_cpus", "requested_memory", "gpu_count", "time_limit_seconds"):
            if execution.get(key) != resources.get(key):
                raise ProbeEnvironmentError(f"protected execution top-level {key} differs from resource summary")
        if backend == "scheduler":
            submitted_at = _timestamp(execution.get("slurm_submit_time_utc"))
            registered_at = _timestamp(seal["registered_at_utc"])
            if submitted_at < registered_at or submitted_at > started_at:
                raise ProbeEnvironmentError("Slurm submission predates preregistration or follows execution start")
    except (TypeError, ValueError, KeyError) as exc:
        raise ProbeEnvironmentError("host execution timestamps are invalid") from exc
    scheduler_keys = {"spool", "sacct", "scontrol"}
    scheduler_files = execution.get("files")
    rows = execution.get("runs")
    if backend == "scheduler":
        if not isinstance(scheduler_files, dict) or set(scheduler_files) != scheduler_keys:
            raise ProbeEnvironmentError("host execution scheduler file set is incomplete or contains extras")
    elif scheduler_files != {}:
        raise ProbeEnvironmentError("local execution must not claim scheduler capture files")
    indices = plan.get("trajectory_indices_zero_based")
    durations = plan.get("duration_fs")
    if (not isinstance(rows, list) or len(rows) != len(indices)
            or [row.get("pool_index_zero_based") if isinstance(row, dict) else None for row in rows] != indices):
        raise ProbeEnvironmentError("host execution must account for every preregistered condition in order")
    row_keys = {"pool_index_zero_based", "duration_fs", "status", "driver_exit_code",
                "capture_relative_path", "files", "file_sha256", "stop_trigger_index", "censored_reason"}
    base = trusted_root / "capture"
    actual_names: set[str] = set()

    def check_file(key: str, rel: object, expected: object) -> str:
        if not isinstance(rel, str):
            raise ProbeEnvironmentError("host execution file paths must be strings")
        p = PurePosixPath(rel)
        if p.is_absolute() or any(part in {"", ".", ".."} for part in p.parts):
            raise ProbeEnvironmentError("host execution manifest contains unsafe paths")
        target = base.joinpath(*p.parts)
        parent = base
        for part in p.parts[:-1]:
            parent = parent / part
            if parent.is_symlink():
                raise ProbeEnvironmentError("protected execution evidence traverses a symlink")
        if target.is_symlink() or not target.is_file():
            raise ProbeEnvironmentError(f"protected execution file is missing or redirected: {key}")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected) or sha256(target) != expected:
            raise ProbeEnvironmentError(f"protected execution file hash mismatch: {key}")
        actual_names.add(p.as_posix())
        return p.as_posix()

    scheduler_sha = execution.get("file_sha256")
    if backend == "scheduler":
        if not isinstance(scheduler_sha, dict) or set(scheduler_sha) != scheduler_keys:
            raise ProbeEnvironmentError("host execution scheduler hashes are incomplete or contain extras")
        for key, rel in scheduler_files.items():
            check_file(key, rel, scheduler_sha.get(key))
    elif scheduler_sha != {}:
        raise ProbeEnvironmentError("local execution must not claim scheduler file hashes")

    for position, (row, index, duration) in enumerate(zip(rows, indices, durations)):
        if not isinstance(row, dict) or set(row) != row_keys or row.get("duration_fs") != duration:
            raise ProbeEnvironmentError("host run record fields differ from the fixed v2 schema or planned duration")
        status = row.get("status")
        if status == "not_started_due_stop_rule":
            if (position == 0 or row.get("driver_exit_code") is not None
                    or row.get("capture_relative_path") is not None
                    or row.get("files") != {} or row.get("file_sha256") != {}
                    or row.get("censored_reason") != "not_started_due_stop_rule"
                    or row.get("stop_trigger_index") not in indices[:position]):
                raise ProbeEnvironmentError("not-started condition lacks an earlier fixed-index stop trigger")
            continue
        if status == "not_started_due_scheduler_failure":
            if (position == 0 or row.get("driver_exit_code") is not None
                    or row.get("capture_relative_path") is not None
                    or row.get("files") != {} or row.get("file_sha256") != {}
                    or row.get("stop_trigger_index") is not None
                    or row.get("censored_reason") != "parent_job_failure"
                    or (execution.get("terminal_status") == "COMPLETED"
                        and execution.get("job_exit_code") == 0)):
                raise ProbeEnvironmentError("scheduler-failure omission lacks a real failed parent job")
            continue
        if status not in {"traced", "driver_failed_before_trace"}:
            raise ProbeEnvironmentError("host run record has an unsupported per-condition status")
        if type(row.get("driver_exit_code")) is not int:
            raise ProbeEnvironmentError("host run record lacks the actual integer driver exit code")
        rel_run = row.get("capture_relative_path")
        if (not isinstance(rel_run, str) or PurePosixPath(rel_run).is_absolute()
                or any(part in {"", ".", ".."} for part in rel_run.split("/"))):
            raise ProbeEnvironmentError("host run capture directory is unsafe")
        expected_dir = f"runs/ic-{index:02d}"
        if rel_run != expected_dir:
            raise ProbeEnvironmentError("host run capture directory is not the canonical fixed-index location")
        per_file_keys = ({"geom", "veloc", "input", "driver_stdout", "driver_stderr"}
                         if status == "driver_failed_before_trace" else
                         {"geom", "veloc", "input", "energy", "surface", "expec",
                          "driver_stdout", "driver_stderr"})
        row_files = row.get("files")
        row_hashes = row.get("file_sha256")
        if (not isinstance(row_files, dict) or set(row_files) != per_file_keys
                or not isinstance(row_hashes, dict) or set(row_hashes) != per_file_keys):
            raise ProbeEnvironmentError("host run native/log file set is incomplete or contains extras")
        for name, rel in row_files.items():
            basename = {"driver_stdout": "driver.stdout", "driver_stderr": "driver.stderr"}.get(name, name)
            if name == "energy":
                expected_rel = f"{rel_run}/output_data/energy.out"
            elif name == "surface":
                expected_rel = f"{rel_run}/output_data/coeff_class_diag.out"
            elif name == "expec":
                expected_rel = f"{rel_run}/output_data/expec.out"
            else:
                expected_rel = f"{rel_run}/{basename}"
            if rel != expected_rel:
                raise ProbeEnvironmentError("host run file path differs from its canonical index-scoped location")
            check_file(f"run-{index:02d}:{name}", rel, row_hashes.get(name))
        if status == "driver_failed_before_trace" and row["driver_exit_code"] == 0:
            raise ProbeEnvironmentError("driver_failed_before_trace has a zero driver exit code")
        if status == "traced" and row["driver_exit_code"] != 0 and row.get("censored_reason") in (None, ""):
            raise ProbeEnvironmentError("failed traced run must preserve its failure/censor reason")

    observed_names: set[str] = set()
    for candidate in base.rglob("*"):
        if candidate.is_symlink():
            raise ProbeEnvironmentError("protected execution capture contains a symlink")
        if candidate.is_file():
            observed_names.add(candidate.relative_to(base).as_posix())
        elif not candidate.is_dir():
            raise ProbeEnvironmentError("protected execution capture contains a special file")
    if observed_names != actual_names:
        raise ProbeEnvironmentError("protected execution capture has undeclared or missing files")

    # The outer manifest itself is pinned and must cover exactly the files above.
    manifest = trusted_root / "manifest.sha256"
    manifest_sha = execution.get("manifest_sha256")
    if not isinstance(manifest_sha, str) or sha256(manifest) != manifest_sha:
        raise ProbeEnvironmentError("protected execution manifest digest mismatch")
    manifest_rows = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        fields = line.split("  ", 1)
        if len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{64}", fields[0]):
            raise ProbeEnvironmentError("protected execution manifest is malformed")
        manifest_rows.append((fields[1], fields[0]))
    if ({name for name, _ in manifest_rows} != actual_names or len(manifest_rows) != len(actual_names)
            or len(set(actual_names)) != len(actual_names)):
        raise ProbeEnvironmentError("protected execution manifest file set differs from its receipt")
    for name, digest in manifest_rows:
        if sha256(base / name) != digest:
            raise ProbeEnvironmentError("protected execution manifest member hash mismatch")
    if backend == "scheduler":
        spool = base / scheduler_files["spool"]
        if sha256(spool) != execution.get("spool_sha256"):
            raise ProbeEnvironmentError("actual Slurm spool does not match execution identity")
        _validate_spool(spool, execution)
        _validate_sacct(base / scheduler_files["sacct"], execution)
        _validate_scontrol(base / scheduler_files["scontrol"], execution)
    else:
        if (execution.get("slurm_job_id") is not None
                or execution.get("slurm_submit_time_utc") is not None
                or execution.get("spool_sha256") is not None):
            raise ProbeEnvironmentError("local execution receipt must not claim scheduler-only fields")
    return seal, execution


def _validate_sacct(path: Path, execution: dict) -> None:
    raw = path.read_text(encoding="utf-8", errors="strict").splitlines()
    jid = str(execution.get("slurm_job_id", ""))
    rows = [line.split("|") for line in raw if line.strip() and line.split("|", 1)[0] == jid]
    if len(rows) != 1:
        raise ProbeEnvironmentError("sacct capture must contain exactly one parent row for the registered job")
    row = rows[0]
    if len(row) != 9 or row[0] != jid or row[1] != execution.get("job_name"):
        raise ProbeEnvironmentError("sacct parent row identity/shape differs from execution receipt")
    if row[2] not in {"COMPLETED", "FAILED", "TIMEOUT", "OUT_OF_MEMORY", "CANCELLED"}:
        raise ProbeEnvironmentError("sacct parent row has an unsupported terminal state")
    try:
        rc = int(row[3].split(":", 1)[0])
        elapsed = int(row[4])
        cpus = int(row[5])
    except (ValueError, IndexError) as exc:
        raise ProbeEnvironmentError("sacct exit/time/resource fields are malformed") from exc
    if (row[2] != execution.get("terminal_status") or rc != execution.get("job_exit_code")
            or elapsed != execution.get("elapsed_seconds") or cpus != execution.get("allocated_cpus")
            or row[6] != execution.get("requested_memory") or row[7] != execution.get("max_rss")
            or row[8] != execution.get("node_list")):
        raise ProbeEnvironmentError("sacct row differs from protected execution resource receipt")


def _validate_scontrol(path: Path, execution: dict) -> None:
    raw = path.read_text(encoding="utf-8", errors="strict")
    expected = {
        "JobId": str(execution.get("slurm_job_id")), "JobName": execution.get("job_name"),
        "WorkDir": execution.get("work_dir"), "Partition": execution.get("partition"),
        "NodeList": execution.get("node_list"), "Account": execution.get("account"),
        "QOS": execution.get("qos"), "NumCPUs": str(execution.get("allocated_cpus")),
        "MinMemoryNode": execution.get("requested_memory"),
        "Command": execution.get("command"),
    }
    for key, value in expected.items():
        if not value or re.search(rf"(?:^|\s){re.escape(key)}={re.escape(str(value))}(?:\s|$)", raw) is None:
            raise ProbeEnvironmentError(f"scontrol capture does not bind {key}")
    request = execution.get("resource_request")
    if not isinstance(request, dict):
        raise ProbeEnvironmentError("protected execution receipt lacks its resource request")
    gres_fields = " ".join(re.findall(r"(?:^|\s)(?:TresPerNode|Gres|GRES|AllocTRES)=([^\s]+)", raw))
    if _scheduler_gpu_count(gres_fields) != request.get("gpu_count"):
        raise ProbeEnvironmentError("scontrol GPU allocation differs from the sealed resource request")
    limit_match = re.search(r"(?:^|\s)TimeLimit=([^\s]+)(?:\s|$)", raw)
    if not limit_match:
        raise ProbeEnvironmentError("scontrol capture lacks the submitted time limit")
    try:
        pieces = [int(piece) for piece in limit_match.group(1).split(":")]
        if len(pieces) == 3:
            seconds = pieces[0] * 3600 + pieces[1] * 60 + pieces[2]
        elif len(pieces) == 2:
            seconds = pieces[0] * 60 + pieces[1]
        else:
            raise ValueError("unsupported time format")
    except ValueError as exc:
        raise ProbeEnvironmentError("scontrol time limit is malformed") from exc
    if (seconds != execution.get("time_limit_seconds")
            or seconds > PROBE_RESOURCE_POLICY["max_time_limit_seconds"]):
        raise ProbeEnvironmentError("scontrol time limit differs from the sealed request")
    command = execution.get("command")
    work_root = _safe_remote_root(execution.get("work_dir"))
    if (work_root is None or not isinstance(command, str)
            or not command.startswith(work_root + "/")
            or ".." in PurePosixPath(command).parts or not command.endswith(".sbatch")
            or execution.get("command_sha256") != execution.get("spool_sha256")):
        raise ProbeEnvironmentError("Slurm command is outside the receipt-bound work tree or differs from captured spool")


def _validate_spool(path: Path, execution: dict) -> None:
    """Require the captured submitted script itself to honor the bounded policy."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        match = re.fullmatch(r"#SBATCH\s+--([a-z-]+)=(\S+)\s*", line)
        if not match:
            continue
        name, value = match.groups()
        if name in values:
            raise ProbeEnvironmentError(f"spooled Slurm script repeats resource directive {name}")
        values[name] = value
    request = execution.get("resource_request")
    if (not isinstance(request, dict) or request.get("accelerator") not in {"cpu", "gpu"}
            or type(request.get("gpu_count")) is not int):
        raise ProbeEnvironmentError("protected execution receipt lacks a resource request")
    work_root = _safe_remote_root(execution.get("work_dir"))
    if work_root is None:
        raise ProbeEnvironmentError("protected execution receipt has no safe work root")
    expected = {
        "job-name": execution.get("job_name"), "partition": execution.get("partition"),
        "nodes": "1", "ntasks": "1", "cpus-per-task": str(request["cpus"]),
        "mem": f"{request['memory_gb']}G", "account": execution.get("account"),
        "qos": execution.get("qos"), "chdir": work_root,
    }
    if _scheduler_gpu_count(values.get("gres", "")) != request["gpu_count"]:
        raise ProbeEnvironmentError("spooled GPU request differs from the sealed resource request")
    for name, value in expected.items():
        if values.get(name) != value:
            raise ProbeEnvironmentError(f"spooled Slurm script does not pin expected {name}")
    try:
        raw_limit = values["time"]
        fields = [int(part) for part in raw_limit.split(":")]
        if len(fields) == 3:
            seconds = fields[0] * 3600 + fields[1] * 60 + fields[2]
        elif len(fields) == 2:
            seconds = fields[0] * 60 + fields[1]
        else:
            raise ValueError("unsupported time format")
    except (KeyError, ValueError) as exc:
        raise ProbeEnvironmentError("spooled Slurm script has a malformed time limit") from exc
    if (seconds != execution.get("time_limit_seconds") or seconds != request.get("wall_seconds")
            or seconds > PROBE_RESOURCE_POLICY["max_time_limit_seconds"]):
        raise ProbeEnvironmentError("spooled Slurm script differs from the sealed time limit")
    for name in ("output", "error"):
        value = values.get(name, "")
        if (not value.startswith(work_root + "/") or ".." in PurePosixPath(value).parts
                or "%j" not in value):
            raise ProbeEnvironmentError(f"spooled Slurm {name} path is outside the receipt-bound work tree")


def _decision_evidence_summary(runs: list[dict]) -> list[dict]:
    summary = []
    for row in runs:
        metrics = row.get("audited_risk_metrics", {}) if isinstance(row, dict) else {}
        low = metrics.get("low_gap_coupling", {}) if isinstance(metrics, dict) else {}
        hops = metrics.get("surface_hop_stability", {}) if isinstance(metrics, dict) else {}
        summary.append({
            "pool_index_zero_based": row.get("pool_index_zero_based"),
            "native_records": row.get("native_records"),
            "observed_end_fs": row.get("observed_end_fs"),
            "complete": row.get("complete"),
            "max_total_energy_drift_ev": row.get("max_total_energy_drift_ev"),
            "energy_sha256": row.get("energy_sha256"),
            "surface_sha256": row.get("surface_sha256"),
            "expec_sha256": low.get("expec_sha256"),
            "minimum_adjacent_state_gap_ev": low.get("minimum_adjacent_state_gap_ev"),
            "pair_time_samples_at_or_below_cutoff": low.get("pair_time_samples_at_or_below_cutoff"),
            "active_surface_switches": hops.get("active_surface_switches"),
        })
    return summary


_DECISION_ACTIONS = {
    "execution_incomplete": ("execution_integrity", "reconcile_or_repair_execution"),
    "force_accuracy_not_sampled": ("energy_force_consistency", "validate_force_accuracy"),
    "nac_phase_not_sampled": ("nac_phase_continuity", "probe_nac_phase_continuity"),
    "low_gap_coupling_not_sampled": ("low_gap_coupling", "probe_low_gap_couplings"),
    "ood_support_not_sampled": ("ood_coverage", "measure_training_support_distance"),
    "hop_stability_not_sampled": ("surface_hop_stability", "probe_surface_hop_stability"),
    "energy_drift_exceeded": ("energy_force_consistency", "stop_and_diagnose_energy_drift"),
}


def _audited_risk_status(runs: list[dict], risk: str) -> str:
    metric_rows = [row.get("audited_risk_metrics", {}).get(risk, {}) for row in runs]
    if any(item.get("assessment_complete") is True for item in metric_rows if isinstance(item, dict)):
        return "investigated"
    observed = False
    for item in metric_rows:
        if not isinstance(item, dict):
            continue
        if risk == "energy_force_consistency":
            observed |= item.get("energy_diagnostics_computed") is True
        elif risk == "low_gap_coupling":
            observed |= type(item.get("minimum_adjacent_state_gap_ev")) in (float, int)
        elif risk == "surface_hop_stability":
            observed |= isinstance(item.get("active_surface_indices_zero_based"), list)
    return "partially_investigated" if observed else "not_assessed"


def _expected_resources(execution: dict) -> dict:
    return {
        "execution_backend": execution.get("backend"),
        "execution_id": execution.get("execution_id"),
        "slurm_job_id": (str(execution.get("slurm_job_id"))
                         if execution.get("backend") == "scheduler" else None),
        "terminal_status": execution.get("terminal_status"),
        "job_exit_code": execution.get("job_exit_code"),
        "elapsed_seconds": execution.get("elapsed_seconds"),
        "allocated_cpus": execution.get("allocated_cpus"),
        "requested_memory": execution.get("requested_memory"),
        "max_rss": execution.get("max_rss"),
        "node_list": execution.get("node_list") if execution.get("backend") == "scheduler" else None,
        "account": execution.get("account") if execution.get("backend") == "scheduler" else None,
        "qos": execution.get("qos") if execution.get("backend") == "scheduler" else None,
        "partition": execution.get("partition") if execution.get("backend") == "scheduler" else None,
        "gpu_count": execution.get("gpu_count"),
        "time_limit_seconds": execution.get("time_limit_seconds"),
        "software_environment": execution.get("software_environment"),
        "software_environment_sha256": execution.get("software_environment_sha256"),
    }


def validate_decision(decision: Any, *, result: dict,
                      whole_job_success: bool | None = None,
                      execution: dict | None = None) -> dict:
    if not isinstance(decision, dict) or decision.get("schema") != DECISION_SCHEMA:
        raise ProbeAuditError("decision.json has the wrong schema")
    if decision.get("decision") not in {"continue", "diagnose", "stop"}:
        raise ProbeAuditError("decision must be continue, diagnose, or stop")
    if decision.get("s1_100fs_lifetime_fs", object()) is not None:
        raise ProbeAuditError("short-prefix work cannot report a finite 100 fs lifetime")
    if decision.get("lifetime_identifiability") != "not_identifiable_from_short_prefix":
        raise ProbeAuditError("100 fs lifetime identifiability must be stated explicitly")
    if not isinstance(result, dict):
        raise ProbeAuditError("probe result must be a JSON object")
    if decision.get("plan_sha256") != result.get("plan_sha256"):
        raise ProbeAuditError("decision is not bound to the actual registered plan")
    risks = decision.get("risk_findings")
    if (not isinstance(risks, dict) or set(risks) != RISK_SET
            or any(not isinstance(v, dict) or v.get("status") not in
                   {"investigated", "partially_investigated", "not_assessed"} for v in risks.values())):
        raise ProbeAuditError("decision must cover all five risk families with an explicit assessment status")
    runs = result.get("runs") if isinstance(result, dict) else None
    if not isinstance(runs, list) or not runs:
        raise ProbeAuditError("decision requires the complete audited run set")
    for risk in RISK_SET:
        expected_status = _audited_risk_status(runs, risk)
        if risks[risk] != {"status": expected_status}:
            raise ProbeAuditError(f"risk {risk} status differs from independent metric coverage")
    if execution is not None:
        if not isinstance(decision.get("rationale"), str) or not decision["rationale"].strip():
            raise ProbeAuditError("decision requires a concise evidence-based rationale")
        if not isinstance(decision.get("limitations"), list) or not decision["limitations"]:
            raise ProbeAuditError("decision must state its evidence limitations")
        if decision.get("probe_result_sha256") != canonical_sha256(result):
            raise ProbeAuditError("decision probe_result_sha256 differs from the independently audited result")
        if decision.get("evidence_summary") != _decision_evidence_summary(runs):
            raise ProbeAuditError("decision evidence summary differs from audited native metrics")
        if decision.get("actual_resources") != _expected_resources(execution):
            raise ProbeAuditError("decision resource summary differs from protected Slurm accounting")
        reason = decision.get("reason_code")
        expected = _DECISION_ACTIONS.get(reason)
        if expected is None:
            raise ProbeAuditError("decision reason_code is not in the fixed evidence/action vocabulary")
        if (decision.get("priority_risk"), decision.get("next_action")) != expected:
            raise ProbeAuditError("decision risk/action pair does not match its fixed reason code")
        metric_sets = [row.get("audited_risk_metrics", {}) for row in runs if isinstance(row, dict)]
        supported_reason = False
        if reason == "execution_incomplete":
            supported_reason = whole_job_success is False or any(
                row.get("complete") is not True for row in runs if isinstance(row, dict))
        elif reason == "energy_drift_exceeded":
            supported_reason = any(
                isinstance(metrics, dict)
                and type((item := metrics.get("energy_force_consistency", {})).get("max_total_energy_drift_ev")) in (int, float)
                and type(item.get("max_total_energy_drift_ev")) is not bool
                and type(row.get("drift_threshold_ev")) in (int, float)
                and item["max_total_energy_drift_ev"] > row["drift_threshold_ev"]
                for row, metrics in zip(runs, metric_sets) if isinstance(row, dict))
        elif reason == "force_accuracy_not_sampled":
            supported_reason = any(m.get("energy_force_consistency", {}).get("force_error") == "not_sampled"
                                   for m in metric_sets if isinstance(m, dict))
        elif reason == "nac_phase_not_sampled":
            supported_reason = any(m.get("nac_phase_continuity", {}).get("status") == "not_sampled"
                                   for m in metric_sets if isinstance(m, dict))
        elif reason == "low_gap_coupling_not_sampled":
            supported_reason = any(
                isinstance(m.get("low_gap_coupling"), dict)
                and type(m["low_gap_coupling"].get("minimum_adjacent_state_gap_ev")) in (int, float)
                and m.get("nac_phase_continuity", {}).get("status") == "not_sampled"
                for m in metric_sets if isinstance(m, dict))
        elif reason == "ood_support_not_sampled":
            supported_reason = any(m.get("ood_coverage", {}).get("status") == "not_sampled"
                                   for m in metric_sets if isinstance(m, dict))
        elif reason == "hop_stability_not_sampled":
            supported_reason = any(
                isinstance(m.get("surface_hop_stability", {}).get("active_surface_indices_zero_based"), list)
                and m["surface_hop_stability"].get("active_surface_switches") == 0
                for m in metric_sets if isinstance(m, dict))
        if not supported_reason:
            raise ProbeAuditError("decision reason_code is not supported by the independently audited metrics")
        if reason.endswith("not_sampled") and decision["decision"] != "diagnose":
            raise ProbeAuditError("an unsampled risk requires a diagnose decision")
    if decision["decision"] == "continue":
        coverage = [row.get("audited_risk_coverage") for row in runs if isinstance(row, dict)]
        all_risks_covered = (len(coverage) == len(runs) and bool(coverage)
                             and all(isinstance(item, dict) and set(item) == RISK_SET
                                     and all(item[name] is True for name in RISK_SET)
                                     for item in coverage))
        if (whole_job_success is not True
                or not all(isinstance(row, dict) and row.get("complete") is True
                    and row.get("reliable_for_planned_prefix") is True
                    and row.get("drift_below_candidate_threshold") is True
                    and row.get("observed_trigger") is not True for row in runs)
                or not all_risks_covered
                or any(risks[name]["status"] == "not_assessed" for name in RISK_SET)):
            raise ProbeAuditError("continue is forbidden when any run is incomplete/unreliable or risks remain unassessed")
    else:
        observed_trigger = any(
            isinstance(row, dict) and row.get("observed_trigger") is True for row in runs)
        audited_missing = False
        for name in RISK_SET:
            coverage = [row.get("audited_risk_coverage") for row in runs if isinstance(row, dict)]
            if (not coverage or any(not isinstance(item, dict) or set(item) != RISK_SET
                                    or any(type(item[key]) is not bool for key in RISK_SET)
                                    for item in coverage)):
                raise ProbeAuditError("risk decision lacks auditor-derived diagnostic coverage")
            measured = any(item[name] for item in coverage)
            status = risks[name]["status"]
            audited_missing |= not measured
        execution_failure = whole_job_success is False
        if decision["decision"] == "stop" and not (observed_trigger or execution_failure):
            raise ProbeAuditError("stop requires an independently observed execution or diagnostic trigger")
        if decision["decision"] == "diagnose" and not (observed_trigger or audited_missing or execution_failure):
            raise ProbeAuditError("diagnose requires an observed trigger or auditor-confirmed coverage gap")
    return decision


def is_audited_stop_trigger(row: Any) -> bool:
    """Whether a recomputed prior condition authorizes a stop-rule skip."""
    return isinstance(row, dict) and row.get("stop_rule_trigger") is True


def require_prior_stop_trigger(trigger_index: Any, prior_rows: list[dict]) -> None:
    """Reject an omitted condition unless prior audited evidence hit a hard stop."""
    if not any(row.get("pool_index_zero_based") == trigger_index
               and is_audited_stop_trigger(row) for row in prior_rows
               if isinstance(row, dict)):
        raise ProbeEnvironmentError(
            "not-started condition has no independently audited preregistered stop trigger")


def require_trusted_probe_mount(path: Path) -> None:
    """Require immutable root-owned receipts rehydrated by the guarded grader."""
    try:
        parent = path.parent.lstat()
        root = path.lstat()
    except OSError as exc:
        raise ProbeEnvironmentError("protected case04 probe receipt bundle is unavailable") from exc
    if (path.is_symlink() or not path.is_dir() or parent.st_uid != 0 or parent.st_mode & 0o222
            or root.st_uid != 0 or root.st_mode & 0o222):
        raise ProbeEnvironmentError("protected case04 probe receipt bundle is writable or redirected")
    required = ("preregistration.json", "execution.json", "manifest.sha256")
    for name in required:
        p = path / name
        try: st = p.lstat()
        except OSError as exc: raise ProbeEnvironmentError(f"protected probe bundle lacks host file {name}") from exc
        if p.is_symlink() or not p.is_file() or st.st_uid != 0 or st.st_nlink != 1 or st.st_mode & 0o222:
            raise ProbeEnvironmentError(f"protected probe file {name} is not immutable root-owned data")


CALIBRATION_READY = False
TRUSTED_ROOT = Path("/trusted/case04-probe")
RUNNER_CONTEXT_PATH = Path("/trusted/runner-context.json")
PROFILE_ID = "bench25-case04-agent-selected-v1"
READINESS_SCHEMA = "bench25-case04-probe-readiness/v2"


def _load_scientific_refs() -> dict:
    path = Path(__file__).resolve().with_name("refs.json")
    refs = load_json(path, environment=True)
    if not isinstance(refs, dict) or refs.get("schema") != "bench25-case04-scientific-refs/v1":
        raise ProbeEnvironmentError("scientific refs are missing or malformed")
    p = refs.get("probe_policy")
    expected = {"dt_fs": DT_FS, "fixed_pool_size": 40, "fixed_ic_pool_sha256": POOL_SHA256,
                "fixed_model_sha256": MODEL_SHA256, "model_source_sha256": MODEL_SOURCE_SHA256,
                "runtime_adapter_sha256": RUNTIME_ADAPTER_SHA256,
                "fixed_training_db_sha256": DB_SHA256}
    if not isinstance(p, dict) or p.get("schema") != PLAN_SCHEMA or any(p.get(k) != v for k,v in expected.items()):
        raise ProbeEnvironmentError("scientific refs differ from active probe policy")
    if p.get("duration_fs") != {"minimum": 5.0, "maximum": 10.0}:
        raise ProbeEnvironmentError("scientific refs duration policy differs")
    t = refs.get("native_tolerances")
    active_tolerances = {"time_grid_fs": 1e-6, "energy_consistency": 1e-6, "population_bounds": 1e-8,
                         "population_sum": 1e-6, "one_hot_population": 1e-7, "surface_sum": 1e-7,
                         "initial_population": 1e-6, "kinetic_potential_identity_ev": 1e-7}
    if not isinstance(t, dict) or t != active_tolerances:
        raise ProbeEnvironmentError("scientific refs tolerances are missing or invalid")
    if refs.get("limitations") != {"probe_is_short_prefix_only": True, "candidate_energy_drift_threshold_is_preregistered_positive_value": True, "no_fixed_candidate_drift_threshold": True}:
        raise ProbeEnvironmentError("scientific refs scope limitations differ")
    return refs


def _candidate_bundle(outputs: Path) -> tuple[dict, dict, dict]:
    _load_scientific_refs()
    plan = load_json(outputs / "probe-plan.json")
    result = load_json(outputs / "probe-result.json")
    decision = load_json(outputs / "decision.json")
    return validate_plan(plan), result, decision


def _validate_readiness(trusted_root: Path, context: dict) -> dict:
    readiness = load_json(trusted_root / "readiness.json", environment=True)
    required = {"schema", "attempt_id", "run_id", "task_id", "image_id", "profile_id",
                "runner_context_sha256", "executor_started", "dispatch_available", "finalized",
                "infrastructure_error", "dispatch_state", "execution_backend", "execution_id"}
    if not isinstance(readiness, dict) or set(readiness) != required:
        raise ProbeEnvironmentError("host readiness receipt has the wrong schema")
    raw_context = RUNNER_CONTEXT_PATH.read_bytes()
    expected_image_id = context.get("image_id", "")
    closure_sha = context.get("runtime_closure_sha256", "")
    if (context.get("image_identity_kind") != "runtime-closure-sha256"
            or re.fullmatch(r"runtime-closure-sha256:[0-9a-f]{64}", expected_image_id) is None
            or closure_sha != expected_image_id.removeprefix("runtime-closure-sha256:")):
        raise ProbeEnvironmentError("root-captured Case04 runtime closure identity is unavailable")
    if (readiness.get("schema") != READINESS_SCHEMA
            or readiness.get("attempt_id") != context.get("attempt_id")
            or readiness.get("run_id") != context.get("run_id")
            or readiness.get("task_id") != "case-04"
            or readiness.get("image_id") != expected_image_id
            or context.get("image_id") != expected_image_id
            or readiness.get("profile_id") != PROFILE_ID
            or readiness.get("execution_backend") not in {"local", "scheduler"}
            or readiness.get("execution_backend") != context.get("execution_backend")
            or not isinstance(readiness.get("execution_id"), str)
            or readiness.get("execution_id") != context.get("execution_id")
            or readiness.get("runner_context_sha256") != hashlib.sha256(raw_context).hexdigest()
            or readiness.get("executor_started") is not True
            or readiness.get("finalized") is not True
            or type(readiness.get("dispatch_available")) is not bool):
        raise ProbeEnvironmentError("host readiness receipt is malformed or cross-bound")
    error = readiness.get("infrastructure_error")
    if error is not None and (not isinstance(error, str) or not error):
        raise ProbeEnvironmentError("host readiness infrastructure error is malformed")
    if error or not readiness["dispatch_available"]:
        raise ProbeEnvironmentError("case04 host broker/dispatch infrastructure is unavailable")
    state = readiness.get("dispatch_state")
    allowed = {"NOT_DISPATCHED", "SUBMIT_CLAIMED", "OUTCOME_UNKNOWN", "SUBMITTED",
               "PENDING", "RUNNING", "COMPLETING", "COMPLETED", "FAILED", "TIMEOUT",
               "OUT_OF_MEMORY", "CANCELLED", "REJECTED"}
    if state not in allowed:
        raise ProbeEnvironmentError("host readiness dispatch state is invalid")
    return readiness


def _require_readiness_mount(path: Path) -> None:
    try:
        parent=path.parent.lstat(); root=path.lstat(); readiness=(path/"readiness.json").lstat()
    except OSError as exc:
        raise ProbeEnvironmentError("protected case04 readiness bundle is unavailable") from exc
    if (path.is_symlink() or not path.is_dir() or parent.st_uid != 0 or parent.st_mode & 0o222
            or root.st_uid != 0 or root.st_mode & 0o222 or stat.S_ISLNK(readiness.st_mode)
            or not stat.S_ISREG(readiness.st_mode) or readiness.st_uid != 0
            or readiness.st_nlink != 1 or readiness.st_mode & 0o222):
        raise ProbeEnvironmentError("protected case04 readiness bundle is writable or redirected")


def validate_v2(outputs: Path, *, preflight_only: bool = False) -> dict:
    """Validate schema fixtures or audit protected same-attempt host evidence."""
    if preflight_only:
        plan, result, decision = _candidate_bundle(outputs)
        if not isinstance(result, dict) or result.get("schema") != "bench25-case04-probe-result/v1":
            raise ProbeAuditError("probe-result.json has the wrong schema")
        if not isinstance(decision, dict) or decision.get("schema") != DECISION_SCHEMA:
            raise ProbeAuditError("decision.json has the wrong schema")
        plan_hash = canonical_sha256(plan)
        if result.get("plan_sha256") != plan_hash:
            raise ProbeAuditError("probe-result.json is not bound to probe-plan.json")
        runs = result.get("runs")
        if (not isinstance(runs, list)
                or [row.get("pool_index_zero_based") for row in runs if isinstance(row, dict)]
                   != plan["trajectory_indices_zero_based"]
                or len(runs) != len(plan["trajectory_indices_zero_based"])):
            raise ProbeAuditError("probe-result run set/order differs from probe-plan.json")
        # Schema-only mode checks stated lifetime limits and risk coverage, but
        # never runs candidate native output through a reward-bearing path.
        validate_decision(decision, result=result)
        return {"status": "PRECHECK_PASS_SCHEMA_ONLY_NO_REWARD", "mode": "SCHEMA_ONLY"}

    # Runtime readiness takes precedence over candidate-controlled scientific
    # content. The host-owned readiness receipt distinguishes a healthy broker
    # with no candidate submission (FAIL) from an unavailable transport (ENV).
    _require_readiness_mount(TRUSTED_ROOT)
    context = load_json(RUNNER_CONTEXT_PATH, environment=True)
    readiness = _validate_readiness(TRUSTED_ROOT, context)
    if readiness["dispatch_state"] == "NOT_DISPATCHED":
        raise ProbeAuditError("candidate completed without preregistering and submitting its bounded probe")
    if readiness["dispatch_state"] in {"SUBMIT_CLAIMED", "OUTCOME_UNKNOWN", "SUBMITTED",
                                        "PENDING", "RUNNING", "COMPLETING"}:
        raise ProbeEnvironmentError("same-attempt probe has no terminal protected capture yet")
    if readiness["dispatch_state"] == "REJECTED":
        raise ProbeAuditError("candidate probe submission was rejected by the healthy host broker")
    require_trusted_probe_mount(TRUSTED_ROOT)
    # Authenticate the host-owned preregistration, scheduler bytes, native-file
    # closure, and resource capture before comparing any candidate outputs.
    plan, candidate_result, decision = _candidate_bundle(outputs)
    _, execution = validate_host_capture(TRUSTED_ROOT, context=context, plan=plan)
    request = plan["resource_request"]
    if (execution.get("resource_request") != request
            or execution.get("resource_request_sha256") != canonical_sha256(request)):
        raise ProbeEnvironmentError("terminal execution receipt does not bind the preregistered resource request")
    if readiness["dispatch_state"] != execution.get("terminal_status"):
        raise ProbeEnvironmentError("host readiness terminal state differs from protected execution capture")
    if not isinstance(candidate_result, dict) or candidate_result.get("schema") != RESULT_SCHEMA:
        raise ProbeAuditError("probe-result.json has the wrong schema")
    if candidate_result.get("plan_sha256") != canonical_sha256(plan):
        raise ProbeAuditError("probe-result.json is not bound to the protected registered plan")
    if not isinstance(decision, dict) or decision.get("schema") != DECISION_SCHEMA:
        raise ProbeAuditError("decision.json has the wrong schema")
    runs = execution.get("runs")
    indices = plan["trajectory_indices_zero_based"]
    if not isinstance(runs, list) or [row.get("pool_index_zero_based") for row in runs] != indices:
        raise ProbeEnvironmentError("host execution run set/order differs from the sealed plan")
    recomputed = []
    for row, idx, duration in zip(runs, indices, plan["duration_fs"]):
        if row.get("status") in {"not_started_due_stop_rule", "not_started_due_scheduler_failure"}:
            status = row["status"]
            trigger = row.get("stop_trigger_index")
            if status == "not_started_due_stop_rule":
                require_prior_stop_trigger(trigger, recomputed)
            elif (execution.get("terminal_status") == "COMPLETED"
                  and execution.get("job_exit_code") == 0):
                raise ProbeEnvironmentError("not-started condition has no failed parent Slurm job")
            recomputed.append({
                "pool_index_zero_based": idx, "execution_backend": execution["backend"],
                "execution_id": execution["execution_id"],
                "planned_duration_fs": float(duration), "observed_end_fs": None,
                "dt_fs": 0.5, "native_records": 0, "complete": False,
                "native_prefix_complete": False, "condition_trace_complete": False,
                "job_successful": (execution["terminal_status"] == "COMPLETED"
                                   and execution["job_exit_code"] == 0),
                "status": status, "energy_sha256": None,
                "surface_sha256": None, "max_total_energy_drift_ev": None,
                "drift_threshold_ev": plan["energy_drift_threshold_ev"],
                "energy_identity_max_abs_ev": None, "initial_population_s0_s1_s2": None,
                "drift_below_candidate_threshold": False,
                "observed_trigger": False,
                "stop_rule_trigger": False,
                "terminal_status": execution["terminal_status"],
                "execution_exit_code": execution["job_exit_code"],
                "audited_risk_coverage": dict(RISK_COVERAGE_UNMEASURED),
                "reliable_for_planned_prefix": False,
                "censored_reason": row["censored_reason"], "lifetime_claim": None,
                "stop_trigger_index": trigger,
            })
            continue
        rel = row.get("capture_relative_path")
        if not isinstance(rel, str) or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise ProbeEnvironmentError("host run capture path is unsafe")
        capture = TRUSTED_ROOT / "capture" / rel
        row_hashes = row["file_sha256"]
        host_receipt = {
            **execution,
            "driver_exit_code": row["driver_exit_code"],
            "geom_sha256": row_hashes["geom"],
            "veloc_sha256": row_hashes["veloc"],
            "input_sha256": row_hashes["input"],
            "energy_sha256": row_hashes.get("energy"),
            "surface_sha256": row_hashes.get("surface"),
            "expec_sha256": row_hashes.get("expec"),
            "driver_stdout_sha256": row_hashes["driver_stdout"],
                "driver_stderr_sha256": row_hashes["driver_stderr"],
                "pool_index_zero_based": idx,
                "model_sha256": plan["model_sha256"],
                "ic_pool_sha256": plan["ic_pool_sha256"],
                "source_database_sha256": DB_SHA256,
                "drift_threshold_ev": plan["energy_drift_threshold_ev"],
            "stop_on_energy_drift": plan["stop_rules"]["energy_drift"] == "stop",
            "censored_reason": row.get("censored_reason"),
        }
        if row["status"] == "driver_failed_before_trace":
            audit = audit_driver_failed_before_trace(
                capture, index=idx, duration_fs=duration, host_receipt=host_receipt,
                ic_pool_path=Path("/app/inputs/pilot-baseline/initial_conditions/a03_equiv_s1_40.json"))
        else:
            audit = audit_native_run(capture, index=idx, duration_fs=duration,
                                     drift_threshold_ev=plan["energy_drift_threshold_ev"],
                                     host_receipt=host_receipt,
                                     ic_pool_path=Path("/app/inputs/pilot-baseline/initial_conditions/a03_equiv_s1_40.json"),
                                     stop_on_energy_drift=plan["stop_rules"]["energy_drift"] == "stop")
        recomputed.append(audit)
    whole_job_success = (execution["terminal_status"] == "COMPLETED"
                         and execution["job_exit_code"] == 0
                         and (execution["ended_at_utc"] and execution["started_at_utc"])
                         and (_timestamp(execution["ended_at_utc"])
                              - _timestamp(execution["started_at_utc"])).total_seconds()
                             <= MAX_RESOURCE_WALL_SECONDS
                         and all(row["complete"] for row in recomputed))
    for row in recomputed:
        row["whole_job_success"] = whole_job_success
    if candidate_result.get("runs") != recomputed:
        raise ProbeAuditError("probe-result.json differs from whole-job completion audit")
    validate_decision(decision, result=candidate_result, whole_job_success=whole_job_success,
                      execution=execution)
    return {"status": "PROBE_AUDIT_PASS_NO_LONG_TIME_CLAIM", "n_attempted": len(recomputed),
            "all_prefixes_complete": all(row["native_prefix_complete"] for row in recomputed),
            "whole_job_success": whole_job_success}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", nargs="?", default=".")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    outputs = Path(args.output_dir).resolve() / "outputs"
    try:
        result = validate_v2(outputs, preflight_only=args.preflight_only)
        print(json.dumps(result, sort_keys=True))
        if args.preflight_only:
            print("PRECHECK_PASS_SCHEMA_ONLY_NO_REWARD")
        return 0
    except ProbeAuditError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except (ProbeEnvironmentError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ENV_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
