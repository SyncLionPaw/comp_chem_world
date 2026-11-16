#!/usr/bin/env python3
"""Offline-only case05 evidence parsers and fail-closed scoring interface.

This module validates the frozen NPT/NVE/COM shape and computes diagnostics.
It does not implement or imply a trusted HPC runner, frozen scientific gold,
mode tolerances, or an enabled dispatch route.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

CASE_ID = "case-05-few-layer-md-mode-assignment"
PROFILE_ID = "bench15-few-layer-md"
TASK_VERSION = "case05-full-md-v1"
OFFLINE_SCHEMA = "case05-offline-mock/v1"
ALLOWED_SELECTIONS = {(2, 24101), (2, 24201), (3, 34101), (3, 34201), (6, 64101), (6, 64201)}
GENERATOR_SHA256 = "61347576651fde2ac586372afda3dc9f7a093ed564129073d8aa5acdb187d8f9"
CANDIDATE_HASHES = {
    (2, 24101): {"manifest": "23f77f707b9866860c48b487f59802dcde8ec9b78a2df94a29167651a4eb6576", "data": "37b93137d11bfa153989b8e13fdc5a6f3a10c93053ef7640dec0691d83108df7", "deletion_map": "47a2340076935ca4da3c5afc89f1d35f996a6fcc373aa439cc52d0d7e3fedc67", "input": "b199aa459696786c5d2223c762b859289e5be73bea877612f855fa009b731ffa"},
    (2, 24201): {"manifest": "24022c13b3e72edaff217c5f9144d4505341e697e26dd401c5a5a4c614119bfa", "data": "37b93137d11bfa153989b8e13fdc5a6f3a10c93053ef7640dec0691d83108df7", "deletion_map": "47a2340076935ca4da3c5afc89f1d35f996a6fcc373aa439cc52d0d7e3fedc67", "input": "91dff51e62964359db3d5a91e692d40309d19610062ff0e81ee457c9427d117b"},
    (3, 34101): {"manifest": "cf4e1720ff7b4243f6cd0eb96e3a420aec8547d6a6978e1a34e4c97c3d85a602", "data": "4af09f506925b7a9e844a845f026eeb3c0019cd6ec00db7324f9931e07b9fe0d", "deletion_map": "1892b7d6d43049cfe68d4b69234737f7f8ac2ece418b227bf6103a10d6e00b36", "input": "fef8c269a7dede525d4b947f68c8575b587e00e8a0299ddf812889399af531f5"},
    (3, 34201): {"manifest": "6b6fb8ec6a750191ac9d603f54c15a63abd04f09d08ba058c832e14d6988a4e6", "data": "4af09f506925b7a9e844a845f026eeb3c0019cd6ec00db7324f9931e07b9fe0d", "deletion_map": "1892b7d6d43049cfe68d4b69234737f7f8ac2ece418b227bf6103a10d6e00b36", "input": "683b828d8eb3739600e99d16358409dfa9c5a8094fb5153a1e59bf8fc4ba0752"},
    (6, 64101): {"manifest": "4781398500608b1c569ba8dc7561c9a080b3c6be5bf2ae1c10995013ec7eb463", "data": "5e3792e96c85da2b88c6bf56070ad16eaea6915f906d086e1f30e69ae6516547", "deletion_map": "f88d8c595b9f4669e7575e48872df01cd9b50ad0014e7159bbacac595d2e2833", "input": "eda28114fb9f26a42069688edf0d98cfc10a9e2e118ae3bee4a1fec77e9c9b1b"},
    (6, 64201): {"manifest": "5732cb0e3d431a78d3baa71ac6d81a45fa12cfebd5bcceda10d86af89478fec3", "data": "5e3792e96c85da2b88c6bf56070ad16eaea6915f906d086e1f30e69ae6516547", "deletion_map": "f88d8c595b9f4669e7575e48872df01cd9b50ad0014e7159bbacac595d2e2833", "input": "031fbc86d44a042357289c684e7f3909f21bc24a8712d72c4f0840fe140a1901"},
}
POTENTIAL_SHA256 = {
    "MoS.rebomos": "d2da7e66c62043f1669866c6cf88fd6b509e322917b8d9af12e3cc6459e5cfae",
    "MoS.rebomos.rebo-only": "386c98d410711d7cd47ff257cbd897cad5eaea06e0e18b1f694a9855185f8611",
    "TMD.ILP": "fd3f7fa6b7e7a98ea50a34ecc355d38e43a833300e37ce379721e3c8484d304d",
}
EXPECTED_SOURCE_SHA256 = "4c305ceaa6dd3175586af19cd1599b0924c6ef28bc499711547750f07bf61824"
KB_EV_PER_K = 8.617333262145e-5

_SOURCE_FILE = Path(__file__).resolve()
_PACKAGE = next((parent for parent in _SOURCE_FILE.parents if (parent / 'task.toml').is_file()), _SOURCE_FILE.parent)
_REPO = next((parent for parent in _PACKAGE.parents if (parent / 'acceptance').is_dir() and (parent / 'packages').is_dir()), _PACKAGE.parent)
_HPC_CANDIDATES = _REPO / "acceptance/hpc/case-05-few-layer-md-mode-assignment/candidate-md"
_MD_DIR = _PACKAGE / "md"
if str(_MD_DIR) not in sys.path:
    sys.path.insert(0, str(_MD_DIR))
try:
    from formal_driver import verify_inputs as _verify_candidate_inputs
except ImportError:  # package can be inspected before the formal driver exists
    _verify_candidate_inputs = None


class EvidenceError(ValueError):
    """Raised when a local evidence payload violates the declared contract."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_numeric_table(path: Path, columns: int, label: str) -> np.ndarray:
    path = Path(path)
    if not path.is_file():
        raise EvidenceError(f"missing {label}: {path.name}")
    rows: list[list[float]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        try:
            row = [float(token) for token in text.split()]
        except ValueError as exc:
            raise EvidenceError(f"{label}:{lineno}: nonnumeric row") from exc
        if len(row) != columns:
            raise EvidenceError(f"{label}:{lineno}: expected {columns} columns, found {len(row)}")
        if not all(math.isfinite(x) for x in row):
            raise EvidenceError(f"{label}:{lineno}: NaN or infinite value")
        if not row[0].is_integer():
            raise EvidenceError(f"{label}:{lineno}: step must be an integer")
        rows.append(row)
    if not rows:
        raise EvidenceError(f"{label}: empty numeric body")
    return np.asarray(rows, dtype=np.float64)


def exact_step_contract(table: np.ndarray, start: int, stop: int, interval: int, label: str) -> None:
    expected = np.arange(start, stop + 1, interval, dtype=np.int64)
    actual = table[:, 0].astype(np.int64)
    if not np.array_equal(actual, expected):
        raise EvidenceError(
            f"{label}: expected {len(expected)} exact steps {start}..{stop} by {interval}; "
            f"got {len(actual)} rows {actual[0]}..{actual[-1]}"
        )



def native_normalization_mapping(path: Path, columns: int, initial_step: int, stop_step: int, interval: int, label: str) -> dict[str, Any]:
    """Describe the only permitted initial-sample removal for native fix ave/time files."""
    native = read_numeric_table(path, columns, label)
    exact_step_contract(native, initial_step, stop_step, interval, f"{label}_native")
    if len(native) < 2:
        raise EvidenceError(f"{label}: native payload lacks post-initial samples")
    canonical = native[1:, 0]
    return {
        "source_file": Path(path).name,
        "source_sha256": sha256(Path(path)),
        "native_rows": int(len(native)),
        "native_initial_step": int(native[0, 0]),
        "canonical_rows": int(len(canonical)),
        "canonical_step_start": int(canonical[0]),
        "canonical_step_end": int(canonical[-1]),
        "canonical_step_interval": int(interval),
        "mapping": "drop exactly the single validated initial fix ave/time sample; preserve native file unchanged",
    }


def parse_equilibration_monitor(path: Path, n_layers: int) -> tuple[np.ndarray, list[str]]:
    """Validate native 251-row monitor and return the 250 post-initial samples."""
    native = read_numeric_table(path, n_layers + 5, "equilibration_monitor")
    exact_step_contract(native, 0, 250000, 1000, "equilibration_monitor_native")
    table = native[1:, :]
    if np.any(native[:, n_layers + 1] <= 0.0) or np.any(native[:, n_layers + 2] <= 0.0):
        raise EvidenceError("equilibration_monitor: nonpositive lx/ly")
    all_gaps = np.diff(native[:, 1 : n_layers + 1], axis=1)
    if np.any(all_gaps <= 0.0):
        raise EvidenceError("equilibration_monitor: layer order/gap failed during the 250 ps equilibration")
    names = [*(f"zCOM_layer{layer}" for layer in range(1, n_layers + 1)), "lx", "ly", "temperature_K", "potential_energy_eV"]
    return table, names


def parse_layer_com(path: Path, n_layers: int) -> np.ndarray:
    """Validate native 50,001-row COM and return the 50,000 post-initial samples."""
    native = read_numeric_table(path, 1 + 3 * n_layers, "layer_com_native")
    exact_step_contract(native, 250000, 300000, 1, "layer_com_native")
    table = native[1:, :]
    if np.any(np.diff(native[:, 3::3], axis=1) <= 0.0):
        raise EvidenceError("layer_com: layer order/gap failed during production")
    return table


def summarize_equilibrium(monitor: np.ndarray, n_layers: int, n_atoms: int) -> dict[str, Any]:
    if monitor.shape != (250, n_layers + 5):
        raise EvidenceError("equilibration monitor shape changed after parsing")
    selected = monitor[-100:, :]
    steps = selected[:, 0]
    lx, ly = selected[:, n_layers + 1], selected[:, n_layers + 2]
    temperature, pe = selected[:, n_layers + 3], selected[:, n_layers + 4]
    values: dict[str, np.ndarray] = {
        "temperature_K": temperature,
        "area_A2": lx * ly,
        "potential_energy_eV_per_atom": pe / n_atoms,
    }
    z = selected[:, 1 : n_layers + 1]
    for i in range(n_layers):
        values[f"zCOM_layer{i + 1}_A"] = z[:, i]
    for i in range(n_layers - 1):
        gap = z[:, i + 1] - z[:, i]
        if np.any(gap <= 0.0):
            raise EvidenceError(f"equilibration monitor: layer order/gap failed at pair {i + 1}")
        values[f"layer_gap_{i + 1}_{i + 2}_A"] = gap

    block_rows: list[dict[str, Any]] = []
    block_means: dict[str, list[float]] = {key: [] for key in values}
    block_labels: list[dict[str, int]] = []
    for b in range(5):
        begin, end = b * 20, (b + 1) * 20
        block_labels.append({"step_start": int(steps[begin]), "step_end": int(steps[end - 1])})
        means: dict[str, float] = {}
        for key, series in values.items():
            mean = float(np.mean(series[begin:end]))
            means[key] = mean
            block_means[key].append(mean)
        block_rows.append({**block_labels[-1], "means": means})

    summaries: dict[str, Any] = {}
    midpoints_ps = np.asarray([(b["step_start"] + b["step_end"]) * 0.0005 for b in block_labels])
    for key, series in values.items():
        bm = np.asarray(block_means[key], dtype=np.float64)
        slope = float(np.polyfit(midpoints_ps, bm, 1)[0])
        sd = float(np.std(bm, ddof=1))
        summaries[key] = {
            "mean_over_last_100ps": float(np.mean(series)),
            "sample_sd_over_last_100ps": float(np.std(series, ddof=1)),
            "five_block_mean_sd": sd,
            "five_block_mean_sem": sd / math.sqrt(5.0),
            "ols_slope_per_ps_of_five_block_means": slope,
            "interpretation": "diagnostic_only; no frozen acceptance threshold",
        }
    return {
        "status": "DIAGNOSTIC_ONLY",
        "window_step_range": [151000, 250000],
        "window_rows": 100,
        "block_rows": 20,
        "blocks": block_rows,
        "metrics": summaries,
        "temperature_target_K": 300.0,
        "criteria_frozen": False,
    }


def theil_sen_slope(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or len(x) != len(y):
        raise EvidenceError("need at least two matched samples for drift fit")
    slopes = []
    for i in range(len(x) - 1):
        delta = x[i + 1 :] - x[i]
        slopes.extend(((y[i + 1 :] - y[i]) / delta).tolist())
    if not slopes or not all(math.isfinite(v) for v in slopes):
        raise EvidenceError("nonfinite robust drift fit")
    return float(np.median(np.asarray(slopes, dtype=np.float64)))


def parse_stage_markers(log_text: str) -> list[tuple[str, int]]:
    marker = re.compile(r"^C05_STAGE\s+(minimization_start|minimization_end|equilibration_start|equilibration_end|production_start|production_end)\s+([0-9]+)\s*$", re.MULTILINE)
    found = [(name, int(step)) for name, step in marker.findall(log_text)]
    expected_names = ["minimization_start", "minimization_end", "equilibration_start", "equilibration_end", "production_start", "production_end"]
    if [x[0] for x in found] != expected_names:
        raise EvidenceError("native log: stage markers missing, duplicated, or out of order")
    if found[2:] != [("equilibration_start", 0), ("equilibration_end", 250000), ("production_start", 250000), ("production_end", 300000)]:
        raise EvidenceError("native log: NPT/NVE stage boundaries differ from the full protocol")
    return found


def parse_thermo_by_stage(log_text: str, n_atoms: int) -> dict[str, list[dict[str, float]]]:
    """Parse only native thermo tables inside exact printed stage boundaries."""
    markers = parse_stage_markers(log_text)
    del markers
    required = {"step", "time", "temp", "poteng", "kineng", "toteng", "atoms"}
    stage: str | None = None
    header: list[str] | None = None
    out: dict[str, list[dict[str, float]]] = {"equilibration": [], "production": []}
    for raw in log_text.splitlines():
        line = raw.strip()
        m = re.fullmatch(r"C05_STAGE\s+(equilibration_start|equilibration_end|production_start|production_end)\s+[0-9]+", line)
        if m:
            name = m.group(1)
            if name.endswith("_start"):
                stage = name.removesuffix("_start")
            else:
                stage = None
            header = None
            continue
        if stage is None:
            continue
        tokens = line.split()
        normalized = [token.lower() for token in tokens]
        if required.issubset(set(normalized)) and normalized[0] == "step":
            header = normalized
            continue
        if header is None:
            continue
        try:
            vals = [float(x) for x in tokens]
        except ValueError:
            header = None
            continue
        if len(vals) != len(header):
            header = None
            continue
        if not all(math.isfinite(x) for x in vals):
            raise EvidenceError(f"native {stage} thermo table contains NaN/Inf")
        row = dict(zip(header, vals))
        if not row["step"].is_integer() or not row["atoms"].is_integer():
            raise EvidenceError(f"native {stage} thermo step/atom count is not integer")
        if int(row["atoms"]) != n_atoms:
            raise EvidenceError(f"native {stage} thermo atom count changed")
        out[stage].append(row)
    if not out["equilibration"] or not out["production"]:
        raise EvidenceError("native log has stage markers but lacks numeric thermo tables")
    for label, rows, start, stop in (("equilibration", out["equilibration"], 0, 250000), ("production", out["production"], 250000, 300000)):
        steps = np.asarray([row["step"] for row in rows])
        expected = np.arange(start, stop + 1, 1000, dtype=np.float64)
        if not np.array_equal(steps, expected):
            raise EvidenceError(f"native {label} thermo must contain {len(expected)} rows at 1000-step intervals")
        times = np.asarray([row["time"] for row in rows], dtype=np.float64)
        if not np.allclose(times, steps * 0.001, rtol=0.0, atol=1e-8):
            raise EvidenceError(f"native {label} thermo time does not match the declared 1 fs timestep and reset origin")
        if label == "production" and not math.isclose(float(times[-1] - times[0]), 50.0, rel_tol=0.0, abs_tol=1e-8):
            raise EvidenceError("native production thermo must span exactly 50 ps")
    return out


def summarize_nve_drift(rows: list[dict[str, float]], n_atoms: int) -> dict[str, Any]:
    if len(rows) != 51:
        raise EvidenceError("NVE thermo must have 51 rows including steps 250000 and 300000")
    steps = np.asarray([row["step"] for row in rows], dtype=np.float64)
    times = np.asarray([row["time"] for row in rows], dtype=np.float64)
    energy = np.asarray([row["toteng"] for row in rows], dtype=np.float64)
    expected = np.arange(250000, 300001, 1000, dtype=np.float64)
    if not np.array_equal(steps, expected):
        raise EvidenceError("NVE thermo steps must be 250000..300000 by 1000")
    if not np.all(np.diff(times) > 0.0) or not math.isclose(float(times[-1] - times[0]), 50.0, abs_tol=1e-8):
        raise EvidenceError("NVE thermo time must span exactly 50 ps with increasing samples")
    slope_ols = float(np.polyfit(times, energy, 1)[0])
    slope_ts = theil_sen_slope(times, energy)
    delta = float(energy[-1] - energy[0])
    thermal_scale = n_atoms * KB_EV_PER_K * 300.0
    return {
        "status": "DIAGNOSTIC_ONLY",
        "step_range": [250000, 300000],
        "samples": len(rows),
        "time_span_ps": float(times[-1] - times[0]),
        "total_energy_start_eV": float(energy[0]),
        "total_energy_end_eV": float(energy[-1]),
        "total_energy_delta_eV": delta,
        "total_energy_peak_to_peak_eV": float(np.ptp(energy)),
        "ols_slope_eV_per_ps": slope_ols,
        "theil_sen_slope_eV_per_ps": slope_ts,
        "delta_eV_per_atom": delta / n_atoms,
        "delta_over_N_kBT": delta / thermal_scale,
        "criteria_frozen": False,
        "normalization": {"atoms": n_atoms, "temperature_K": 300.0, "kB_eV_per_K": KB_EV_PER_K},
    }


def validate_candidate_bundle(bundle: Path, n: int, seed: int) -> dict[str, Any]:
    """Validate one bundle against the locally reviewed immutable registry."""
    if (n, seed) not in ALLOWED_SELECTIONS:
        raise EvidenceError("candidate identity is outside the six fixed N/seed pairs")
    bundle = Path(bundle)
    if bundle.name != f"N{n}-seed{seed}":
        raise EvidenceError("candidate directory identity does not match selected N/seed")
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        raise EvidenceError(f"fixed offline candidate is missing: N{n}/seed{seed}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixed = CANDIDATE_HASHES[(n, seed)]
    if manifest.get("N") != n or manifest.get("seed") != seed:
        raise EvidenceError(f"N{n}/seed{seed} manifest identity does not match the fixed route")
    observed_hashes = {
        "manifest": sha256(manifest_path),
        "data": sha256(bundle / manifest.get("data_file", "")),
        "deletion_map": sha256(bundle / manifest.get("duplicate_removal_map", "")),
        "input": sha256(bundle / manifest.get("input_file", "")),
    }
    if observed_hashes != fixed:
        raise EvidenceError(f"N{n}/seed{seed} differs from the frozen offline candidate hashes")
    if manifest.get("template_revision") != 7 or manifest.get("velocity_creation", {}).get("mode") != "loop local":
        raise EvidenceError(f"N{n}/seed{seed} does not match the reviewed revision-7 velocity protocol")
    try:
        hashes, _ = _verify_candidate_inputs(bundle, manifest)
    except Exception as exc:
        raise EvidenceError(f"N{n}/seed{seed} input bundle failed integrity: {exc}") from exc
    for key, expected in POTENTIAL_SHA256.items():
        if manifest.get("potential_sha256", {}).get(key) != expected:
            raise EvidenceError(f"N{n}/seed{seed} potential hash does not match the fixed route")
    if manifest.get("atoms") != n * 3534:
        raise EvidenceError(f"N{n}/seed{seed} atom count differs from fixed route")
    return {"N": n, "seed": seed, "manifest_sha256": observed_hashes["manifest"], "data_sha256": hashes["data"], "deletion_map_sha256": observed_hashes["deletion_map"], "input_sha256": hashes["md_input"]}


def validate_fixed_candidate_assets() -> dict[str, Any]:
    """Validate all six offline input bundles against immutable local hashes."""
    if _verify_candidate_inputs is None:
        raise EvidenceError("formal input verifier is unavailable")
    generator = _PACKAGE / "md/prepare_md.py"
    if sha256(generator) != GENERATOR_SHA256:
        raise EvidenceError("fixed prepare_md.py generator hash mismatch")
    source = _PACKAGE / "environment/assets/6L_MoS2_origin"
    if sha256(source) != EXPECTED_SOURCE_SHA256:
        raise EvidenceError("fixed original source hash mismatch")
    found = [
        validate_candidate_bundle(_HPC_CANDIDATES / f"N{n}-seed{seed}", n, seed)
        for n, seed in sorted(ALLOWED_SELECTIONS)
    ]
    return {"schema": OFFLINE_SCHEMA, "candidate_count": len(found), "candidates": found, "dispatch_enabled": False}


def validate_offline_typed_request(request: dict[str, Any]) -> dict[str, Any]:
    """Validate a closed local mock route; it can never submit remote work."""
    allowed = {"schema", "case_id", "profile_id", "task_version", "selection", "idempotency_key", "resume_checkpoint_id"}
    if not isinstance(request, dict):
        raise EvidenceError("request must be an object")
    unknown = set(request) - allowed
    missing = allowed - {"resume_checkpoint_id"} - set(request)
    if unknown:
        raise EvidenceError(f"request contains forbidden fields: {sorted(unknown)}")
    if missing:
        raise EvidenceError(f"request is missing required fields: {sorted(missing)}")
    if request["schema"] != OFFLINE_SCHEMA or request["case_id"] != CASE_ID or request["profile_id"] != PROFILE_ID or request["task_version"] != TASK_VERSION:
        raise EvidenceError("offline request identity does not match the fixed case profile")
    selection = request["selection"]
    if not isinstance(selection, dict) or set(selection) != {"N", "seed"}:
        raise EvidenceError("selection must contain only N and seed")
    n, seed = selection["N"], selection["seed"]
    if type(n) is not int or type(seed) is not int or (n, seed) not in ALLOWED_SELECTIONS:
        raise EvidenceError("selection is outside the six frozen N/seed pairs")
    key = request["idempotency_key"]
    if not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{32,64}", key) is None:
        raise EvidenceError("idempotency_key must be 32..64 lowercase hex characters")
    if request.get("resume_checkpoint_id") is not None:
        raise EvidenceError("resume checkpoints require a host-owned bound route and are unavailable in offline mock")
    assets = validate_fixed_candidate_assets()
    selected = next(x for x in assets["candidates"] if x["N"] == n and x["seed"] == seed)
    return {
        "schema": OFFLINE_SCHEMA,
        "status": "MOCK_VALIDATED_DISPATCH_DISABLED",
        "dispatch_enabled": False,
        "trust_established": False,
        "selection": {"N": n, "seed": seed},
        "idempotency_key": key,
        "selected_manifest_sha256": selected["manifest_sha256"],
        "selected_input_sha256": selected["input_sha256"],
        "candidate_registry_count": assets["candidate_count"],
    }


def attempt_visibility(*, request_sent: bool, submit_ack: bool | None, job_id: str | None, scheduler_state: str | None) -> str:
    """Keep known-job visibility loss distinct from an uncertain submit ACK."""
    if job_id is not None:
        return scheduler_state if scheduler_state is not None else "UNKNOWN"
    if request_sent and submit_ack is None:
        return "AMBIGUOUS"
    if request_sent and submit_ack is False:
        return "NOT_SUBMITTED"
    if request_sent and submit_ack is True:
        return "ERROR_MISSING_JOB_ID"
    return "NOT_SUBMITTED"


def host_receipt_adapter(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Fail closed until a centrally approved runner receipt adapter is bound."""
    raise EvidenceError("HOST_RECEIPT_ADAPTER_UNBOUND: offline mock evidence cannot establish host trust")


def score_pending(*, host_receipt: Any = None, frozen_reference: Any = None) -> dict[str, Any]:
    """No scientific reward can be issued before runner binding and frozen gold."""
    return {"status": "ERROR", "error_code": "HOST_RECEIPT_ADAPTER_UNBOUND", "pending_requirements": ["centrally bound trusted runner receipt adapter", "frozen scientific reference"], "reward": None, "scientific_score": None, "dispatch_enabled": False}


def analyze_synthetic_tables(monitor: np.ndarray, com: np.ndarray, thermo_log: str, n_layers: int, n_atoms: int) -> dict[str, Any]:
    """Pure parser/diagnostic path for synthetic fixtures; no runner trust."""
    exact_step_contract(monitor, 1000, 250000, 1000, "equilibration_monitor")
    exact_step_contract(com, 250001, 300000, 1, "layer_com")
    if n_layers not in (2, 3, 6) or n_atoms != 3534 * n_layers:
        raise EvidenceError("synthetic input N/atom count is outside the fixed case protocol")
    if monitor.shape != (250, n_layers + 5) or com.shape != (50000, 1 + 3 * n_layers):
        raise EvidenceError("synthetic table shape does not match exact full-run contract")
    if not np.all(np.isfinite(monitor)) or not np.all(np.isfinite(com)):
        raise EvidenceError("synthetic input contains NaN or infinite values")
    if not np.all(monitor[:, 0] == np.floor(monitor[:, 0])) or not np.all(com[:, 0] == np.floor(com[:, 0])):
        raise EvidenceError("synthetic step column must contain exact integers")
    stages = parse_thermo_by_stage(thermo_log, n_atoms)
    from analyze_modes import mode_records
    order = list(range(1, n_layers + 1))
    mode_result = mode_records(com[:, 0].astype(np.int64), com[:, 1:].reshape(50000, n_layers, 3), 1.0, order)
    return {
        "evidence_class": "SYNTHETIC_OFFLINE_ONLY",
        "dispatch_enabled": False,
        "trusted_hpc": False,
        "equilibrium": summarize_equilibrium(monitor, n_layers, n_atoms),
        "nve_drift": summarize_nve_drift(stages["production"], n_atoms),
        "mode_diagnostics": mode_result,
        "reward": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    request = sub.add_parser("validate-mock-request")
    request.add_argument("request_json", type=Path)
    score = sub.add_parser("score")
    score.add_argument("--reference", type=Path)
    score.add_argument("--candidate", type=Path)
    score.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "validate-mock-request":
        try:
            result = validate_offline_typed_request(json.loads(args.request_json.read_text(encoding="utf-8")))
        except Exception as exc:
            print(json.dumps({"status": "REJECTED", "error": str(exc), "dispatch_enabled": False, "trust_established": False}, indent=2))
            return 2
        print(json.dumps(result, indent=2))
        return 0
    result = score_pending()
    serialized = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
