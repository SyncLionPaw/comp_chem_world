# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Hsp60 Catalytic Dyad Geometry and Apical Conformation.
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks


import csv
import os


class CandidateFail(ValueError):
    pass


class EnvironmentInvalid(RuntimeError):
    pass


INPUT_SHA256 = {
    "README_residue_numbering": "a1488c55ef353c6ae82a2f9d77c35a6dfc9929ac70a65081f098acb4156ea230",
    "corrmat_c0_WT.dat": "be3202d7235606d7e212b6baac5a26bc26a38c2c9a809a359f054bac28cf7bb0",
    "distmat_c0_WT.dat": "63d6042457f7fcc811fd24fb0cb2a2ac18185cc85bfdb28ed3831b42e6be2686",
    "corrmat_c0_V72I.dat": "881b191e61b3807565c83125ddcbb9d03840a855885582d3a732318128c3cd05",
    "distmat_c0_V72I.dat": "3f0f76ec7bb044b55783151835833341b2ca3d418cb1d9e388862cffc62a8b65",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def public_root(path: str, expected: dict[str, str]) -> dict[str, Path]:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise EnvironmentInvalid("public input root is absent or redirected")
    result: dict[str, Path] = {}
    for name, digest in expected.items():
        file = root / name
        if file.is_symlink() or not file.is_file():
            raise EnvironmentInvalid(f"required public input is absent or redirected: {name}")
        if sha256_file(file) != digest:
            raise EnvironmentInvalid(f"public input SHA-256 mismatch: {name}")
        result[name] = file
    return result


def real_output_dir(app: str) -> Path:
    root = Path(app)
    final = root / "final"
    if root.is_symlink() or not root.is_dir() or final.is_symlink() or not final.is_dir():
        raise CandidateFail("APP/final must be a real directory")
    return final


def require_files(final: Path, names: tuple[str, ...]) -> dict[str, Path]:
    result = {}
    for name in names:
        path = final / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise CandidateFail(f"required final deliverable is missing, empty, or redirected: {name}")
        result[name] = path
    return result


def read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
                raise CandidateFail(f"{path.name} is missing required columns: {sorted(required)}")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise CandidateFail(f"cannot parse {path.name}: {exc}") from exc
    if not rows:
        raise CandidateFail(f"{path.name} has no data rows")
    return rows


def finite_number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateFail(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise CandidateFail(f"{label} must be finite")
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateFail(f"cannot parse {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateFail(f"{path.name} must contain a JSON object")
    return value


def emit(logs: str, case_id: str, status: str, message: str, details: dict[str, Any] | None = None) -> int:
    root = Path(logs)
    root.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"case_id": case_id, "status": status, "message": message}
    if details:
        report["details"] = details
    if status in {"PASS", "FAIL"}:
        report["reward"] = 1.0 if status == "PASS" else 0.0
        (root / "reward.txt").write_text(f"{report['reward']:g}\n", encoding="ascii")
    else:
        (root / "reward.txt").unlink(missing_ok=True)
    (root / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return {"PASS": 0, "REVIEW_REQUIRED": 0, "FAIL": 1, "ENV_INVALID": 2}.get(status, 2)


CASE = "case-05-assembly-dyad"
INPUT_SHA256 = {
    "Fig_6b.dat": "d24858aa32c44d5b336af0c0a0570c7003554fae91a60fff578b374238b33c08",
    "Fig_8b.dat": "afee6f32ca1e2c3124f731d740625b9085b8ce8024e2d1cbda5c2d41b7ecf5f0",
    "data_dictionary.md": "63af59f0c928517b1b27bc9ffc8c241e426d12ea19c22bc8734310fe84f0f60a",
}
REFERENCE_SHA256 = "7986b43b146c4d34e0811caede7570670e74afc5001e37fcdfc0da638717ee09"
PROTONATIONS = ("AspAsp", "AshAsp", "AspAsh")
ASSEMBLIES = ("D", "F")
VARIANTS = ("WT", "V72I")
STAT_FIELDS = ("n", "mean", "std", "median", "q25", "q75")
NORMALIZATIONS = {"raw_count", "frequency", "probability_density", "radius_weighted_probability_density"}
RDF_EDGES = np.arange(0.0, 16.0001, 0.01)
CONTACT_CUTOFF = 4.35
GAMMA_CUTOFF = 120.0
D_OPEN_CUTOFF = 100.0
SHOULDERS = {"D": (4.6, 5.0), "F": (4.1, 4.7)}
SMOOTHING_SIGMA = (0.10, 0.15)
FEATURE_TOLERANCE = 0.0200001
_DATA_CACHE: dict[str, tuple[dict, dict, dict]] = {}


def stats(values: np.ndarray) -> dict[str, float | int]:
    clean = values[np.isfinite(values)]
    return {"n": int(clean.size), "mean": float(np.mean(clean)), "std": float(np.std(clean, ddof=1)),
            "median": float(np.median(clean)), "q25": float(np.quantile(clean, .25)), "q75": float(np.quantile(clean, .75))}


def strict_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise CandidateFail(f"{label} must be a numeric value, not a boolean")
    return finite_number(value, label)


def strict_json_number(value: Any, label: str) -> float:
    """Enforce a JSON number for findings.json without affecting CSV parsing."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateFail(f"{label} must be a JSON number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise CandidateFail(f"{label} must be a finite JSON number") from exc
    if not math.isfinite(result):
        raise CandidateFail(f"{label} must be a finite JSON number")
    return result


def strict_json_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise CandidateFail(f"{label} must be a JSON integer")
    return value


def require_object(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise CandidateFail(f"{label} must be an object")
    return value


def truth(values: np.ndarray, cutoff: float) -> float:
    return float(np.mean(values <= cutoff))


def direction(effect: float) -> str:
    if effect > 1e-12:
        return "higher"
    if effect < -1e-12:
        return "lower"
    return "equal"


def load_series(assets: dict[str, Path]) -> tuple[dict, dict, dict]:
    dictionary = assets["data_dictionary.md"].read_text(encoding="utf-8")
    must_say = ("同一文件里重复出现的表头对应不同面板", "Fig_6b.dat", "Fig_8b.dat", "AspAsh")
    if any(s not in dictionary for s in must_say):
        raise EnvironmentInvalid("pinned data dictionary no longer identifies the distinct D/F panel and protonation mapping")
    series: dict[tuple[str, str, str, str], np.ndarray] = {}
    frame_by_assembly = {}
    summary = {}
    for assembly, filename in (("D", "Fig_6b.dat"), ("F", "Fig_8b.dat")):
        try:
            frame = pd.read_csv(assets[filename], sep=r"\s+", header=0, na_values=["NaN"], engine="c")
        except Exception as exc:
            raise EnvironmentInvalid(f"pinned {filename} cannot be parsed: {exc}") from exc
        if frame.shape != (560000, 16):
            raise EnvironmentInvalid(f"pinned {filename} has unexpected shape {frame.shape}")
        frame_by_assembly[assembly] = frame
        for variant in VARIANTS:
            row_offset = 0 if variant == "WT" else 8
            for i, protonation in enumerate(PROTONATIONS):
                dcol, gcol = row_offset + 2 + 2 * i, row_offset + 3 + 2 * i
                for observable, col in (("delta", dcol), ("gamma", gcol)):
                    values = frame.iloc[:, col].to_numpy(dtype=float)
                    values = values[np.isfinite(values)]
                    if values.size < 1000:
                        raise EnvironmentInvalid(f"public {assembly}/{variant}/{protonation}/{observable} series is unexpectedly short")
                    key = (assembly, variant, protonation, observable)
                    series[key] = values
                    summary[key] = stats(values)
    return series, summary, frame_by_assembly


def close(got: Any, want: float, label: str, *, atol: float = 2e-6, rtol: float = 2e-6) -> None:
    value = strict_number(got, label)
    if not math.isclose(value, float(want), rel_tol=rtol, abs_tol=atol):
        raise CandidateFail(f"{label}={value} does not match recomputed value {want}")


def check_rows(rows: list[dict[str, str]], expected: dict[tuple, dict], key_fields: tuple[str, ...],
               numeric_fields: tuple[str, ...], label: str, text_fields: tuple[str, ...] = ()) -> None:
    actual = {}
    for row in rows:
        key = tuple(row.get(field, "") for field in key_fields)
        if key in actual or key not in expected:
            raise CandidateFail(f"{label} contains an unknown or duplicate row: {key}")
        actual[key] = row
    if set(actual) != set(expected):
        raise CandidateFail(f"{label} must cover {len(expected)} distinct rows; found {len(actual)}")
    for key, want in expected.items():
        row = actual[key]
        for field in numeric_fields:
            close(row.get(field), want[field], f"{label} {key} {field}")
        for field in text_fields:
            if row.get(field) != want[field]:
                raise CandidateFail(f"{label} {key} {field} must be {want[field]!r}, got {row.get(field)!r}")


def scientific_reference(series: dict, summaries: dict) -> dict[str, dict]:
    """Recompute all criteria from the pinned author frame data; never reads candidate summaries."""
    result: dict[str, dict] = {}
    # Mutation contrasts: matched within assembly and protonation; means and medians are both exposed.
    result["mutation_effects"] = {}
    for assembly in ASSEMBLIES:
        for protonation in PROTONATIONS:
            for observable in ("delta", "gamma"):
                ref = summaries[(assembly, "WT", protonation, observable)]
                target = summaries[(assembly, "V72I", protonation, observable)]
                for statistic in ("mean", "median"):
                    effect = target[statistic] - ref[statistic]
                    key = (assembly, protonation, observable, statistic)
                    result["mutation_effects"][key] = {
                        "assembly": assembly, "protonation": protonation, "observable": observable,
                        "statistic": statistic, "reference_variant": "WT", "target_variant": "V72I",
                        "reference_value": ref[statistic], "target_value": target[statistic], "effect": effect,
                        "units": "angstrom" if observable == "delta" else "degree", "conclusion": direction(effect),
                    }
    # Protonation contrasts: every singly protonated state against AspAsp, separately by variant/assembly.
    result["protonation_effects"] = {}
    for assembly in ASSEMBLIES:
        for variant in VARIANTS:
            for target_prot in ("AshAsp", "AspAsh"):
                for statistic in ("mean", "median"):
                    ref = summaries[(assembly, variant, "AspAsp", "delta")][statistic]
                    target = summaries[(assembly, variant, target_prot, "delta")][statistic]
                    effect = target - ref
                    key = (assembly, variant, target_prot, statistic)
                    result["protonation_effects"][key] = {
                        "assembly": assembly, "variant": variant, "reference_protonation": "AspAsp",
                        "target_protonation": target_prot, "observable": "delta", "statistic": statistic,
                        "reference_value": ref, "target_value": target, "effect": effect,
                        "units": "angstrom", "conclusion": direction(effect),
                    }
    # Local contact probabilities and matched mutation / protonation differences.
    result["local_contact_state"] = {}
    for assembly in ASSEMBLIES:
        for variant in VARIANTS:
            for protonation in PROTONATIONS:
                vals = series[(assembly, variant, protonation, "delta")]
                key = (assembly, variant, protonation)
                result["local_contact_state"][key] = {
                    "assembly": assembly, "variant": variant, "protonation": protonation,
                    "threshold_angstrom": CONTACT_CUTOFF, "probability_delta_le_threshold": truth(vals, CONTACT_CUTOFF),
                    "n": int(vals.size),
                }
    result["local_contact_differences"] = {}
    for assembly in ASSEMBLIES:
        for protonation in PROTONATIONS:
            wt = result["local_contact_state"][(assembly, "WT", protonation)]["probability_delta_le_threshold"]
            mut = result["local_contact_state"][(assembly, "V72I", protonation)]["probability_delta_le_threshold"]
            result["local_contact_differences"][("mutation", assembly, "", protonation, "WT", "V72I")] = {
                "contrast": "mutation", "assembly": assembly, "variant": "", "reference": "WT", "target": "V72I",
                "protonation": protonation, "effect": mut - wt, "conclusion": direction(mut - wt),
            }
        for variant in VARIANTS:
            aspasp = result["local_contact_state"][(assembly, variant, "AspAsp")]["probability_delta_le_threshold"]
            for protonation in ("AshAsp", "AspAsh"):
                target = result["local_contact_state"][(assembly, variant, protonation)]["probability_delta_le_threshold"]
                result["local_contact_differences"][("protonation", assembly, variant, protonation, "AspAsp", protonation)] = {
                    "contrast": "protonation", "assembly": assembly, "variant": variant,
                    "reference": "AspAsp", "target": protonation, "effect": target - aspasp,
                    "conclusion": direction(target - aspasp),
                }
    # Apical opening is measured directly from gamma, with the two reported criteria kept distinct.
    result["apical_context"] = {}
    for assembly in ASSEMBLIES:
        for variant in VARIANTS:
            for protonation in PROTONATIONS:
                vals = series[(assembly, variant, protonation, "gamma")]
                key = (assembly, variant, protonation)
                if assembly == "F":
                    fields = {"gamma_location_median_degree": float(np.median(vals)),
                              "fraction_gamma_gt_120_degree": float(np.mean(vals > GAMMA_CUTOFF)),
                              "cutoff_degree": GAMMA_CUTOFF, "cutoff_operator": ">"}
                else:
                    fields = {"gamma_location_median_degree": float(np.median(vals)),
                              "fraction_gamma_ge_100_degree": float(np.mean(vals >= D_OPEN_CUTOFF)),
                              "cutoff_degree": D_OPEN_CUTOFF, "cutoff_operator": ">="}
                result["apical_context"][key] = {"assembly": assembly, "variant": variant,
                                                  "protonation": protonation, "n": int(vals.size), **fields}
    # Pairwise association is descriptive only. Each group uses aligned finite pairs from the same author rows.
    result["delta_gamma_dependence"] = {}
    for assembly in ASSEMBLIES:
        for variant in VARIANTS:
            for protonation in PROTONATIONS:
                d = series[(assembly, variant, protonation, "delta")]
                g = series[(assembly, variant, protonation, "gamma")]
                n = min(d.size, g.size)
                d, g = d[:n], g[:n]
                keep = np.isfinite(d) & np.isfinite(g)
                coef = float(np.corrcoef(d[keep], g[keep])[0, 1])
                key = (assembly, variant, protonation)
                result["delta_gamma_dependence"][key] = {
                    "assembly": assembly, "variant": variant, "protonation": protonation,
                    "method": "Pearson", "n_paired": int(keep.sum()), "coefficient": coef,
                    "interpretation": "positive_association" if coef > 0 else "negative_association" if coef < 0 else "zero_association",
                }
    # Common radial-shape probe. Derivative minima distinguish a shoulder from a secondary peak.
    result["shape_features"] = {}
    edges = RDF_EDGES
    centers = (edges[:-1] + edges[1:]) / 2
    for assembly in ASSEMBLIES:
        low, high = SHOULDERS[assembly]
        for variant in VARIANTS:
            vals = series[(assembly, variant, "AspAsp", "delta")]
            density, _ = np.histogram(vals, bins=edges, density=True)
            shape = density / np.square(centers)
            for sigma in SMOOTHING_SIGMA:
                smoothed = gaussian_filter1d(shape, sigma=sigma / 0.01, mode="nearest")
                slope = np.gradient(smoothed, 0.01)
                local_minima, _ = find_peaks(-slope)
                feature_ix = [int(ix) for ix in local_minima if low <= centers[ix] <= high]
                candidates = [ix for ix in feature_ix if np.any(centers > centers[ix])]
                primary_ix = max(range(len(centers)), key=lambda ix: shape[ix] if centers[ix] > low else -np.inf)
                if not np.isfinite(shape[primary_ix]):
                    raise EnvironmentInvalid("shape probe produced no finite primary mode")
                key = (assembly, variant, f"{sigma:.2f}")
                result["shape_features"][key] = {
                    "assembly": assembly, "variant": variant, "sigma_angstrom": float(sigma),
                    "feature_window_low_angstrom": low, "feature_window_high_angstrom": high,
                    "feature_type": "local_minimum_of_radial_shape_slope",
                    "feature_positions_angstrom": [float(centers[ix]) for ix in feature_ix],
                    "feature_slope_values": [float(slope[ix]) for ix in feature_ix],
                    "primary_mode_angstrom": float(centers[primary_ix]),
                    "primary_mode_above_feature": bool(candidates and centers[primary_ix] > centers[candidates[0]]),
                    "raw_mass_feature_window": float(np.mean((vals >= low) & (vals <= high))),
                    "shoulder_present": bool(feature_ix),
                }
    return result


def candidate_row_map(findings: dict, field: str, keys: tuple[str, ...], numeric: tuple[str, ...], text: tuple[str, ...], expected: dict) -> None:
    rows = findings.get(field)
    if not isinstance(rows, list) or not rows:
        raise CandidateFail(f"findings.json {field} must be a non-empty array")
    # Rows may be supplied as JSON values, so apply the same strict typing as for CSV values.
    actual = {}
    for row in rows:
        if not isinstance(row, dict):
            raise CandidateFail(f"findings.json {field} rows must be objects")
        key = tuple(str(row.get(name, "")) for name in keys)
        if key in actual or key not in expected:
            raise CandidateFail(f"findings.json {field} contains an unknown or duplicate row: {key}")
        actual[key] = row
    if set(actual) != set(expected):
        raise CandidateFail(f"findings.json {field} must cover {len(expected)} distinct rows; found {len(actual)}")
    for key, want in expected.items():
        row = actual[key]
        for name in numeric:
            strict_json_number(row.get(name), f"{field} {key} {name}")
            close(row[name], want[name], f"{field} {key} {name}")
        if field == "local_contact_state":
            strict_json_int(row.get("n"), f"{field} {key} n")
        for name in text:
            if row.get(name) != want[name]:
                raise CandidateFail(f"{field} {key} {name} must be {want[name]!r}, got {row.get(name)!r}")


def candidate_selected_contrasts(findings: dict, field: str, keys: tuple[str, ...], expected: dict) -> None:
    rows = findings.get(field)
    base_keys = {key[:-1] for key in expected}
    if not isinstance(rows, list) or len(rows) != len(base_keys):
        raise CandidateFail(f"findings.json {field} must contain one matched row per required contrast ({len(base_keys)} rows)")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise CandidateFail(f"findings.json {field} rows must be objects")
        key = tuple(str(row.get(name, "")) for name in keys)
        statistic = row.get("statistic")
        if key not in base_keys or key in seen or statistic not in {"mean", "median"}:
            raise CandidateFail(f"findings.json {field} contains an unknown, duplicate, or unsupported statistic row: {(*key, statistic)}")
        seen.add(key)
        want = expected[(*key, statistic)]
        for name in ("reference_value", "target_value", "effect"):
            strict_json_number(row.get(name), f"{field} {key} {name}")
            close(row[name], want[name], f"{field} {key} {name}")
        for name in ("reference_variant", "target_variant", "reference_protonation", "target_protonation", "observable", "units", "conclusion"):
            if name in want and row.get(name) != want[name]:
                raise CandidateFail(f"{field} {key} {name} must be {want[name]!r}, got {row.get(name)!r}")


def check_shape_rows(rows: Any, expected: dict) -> None:
    if not isinstance(rows, list) or not rows:
        raise CandidateFail("findings.json shape_features must be a non-empty array")
    actual = {}
    for row in rows:
        if not isinstance(row, dict):
            raise CandidateFail("shape_features rows must be objects")
        key = (str(row.get("assembly", "")), str(row.get("variant", "")), f"{strict_json_number(row.get('sigma_angstrom'), 'shape sigma'):.2f}")
        if key in actual or key not in expected:
            raise CandidateFail(f"shape_features has unknown or duplicate row: {key}")
        actual[key] = row
    if set(actual) != set(expected):
        raise CandidateFail("shape_features must include D/F × WT/V72I at both smoothing scales")
    for key, want in expected.items():
        row = actual[key]
        for field in ("feature_window_low_angstrom", "feature_window_high_angstrom", "primary_mode_angstrom", "raw_mass_feature_window"):
            strict_json_number(row.get(field), f"shape_features {key} {field}")
            close(row.get(field), want[field], f"shape_features {key} {field}")
        if row.get("feature_type") != want["feature_type"] or row.get("shoulder_present") is not want["shoulder_present"] or row.get("primary_mode_above_feature") is not want["primary_mode_above_feature"]:
            raise CandidateFail(f"shape_features {key} morphology/type flags do not match the frozen probe")
        positions = row.get("feature_positions_angstrom")
        slopes = row.get("feature_slope_values")
        if not isinstance(positions, list) or not isinstance(slopes, list) or len(positions) != len(want["feature_positions_angstrom"]) or len(slopes) != len(want["feature_slope_values"]):
            raise CandidateFail(f"shape_features {key} must report every detected slope minimum and its slope")
        for i, (got, expected_value) in enumerate(zip(positions, want["feature_positions_angstrom"])):
            strict_json_number(got, f"shape_features {key} feature position {i}")
            close(got, expected_value, f"shape_features {key} feature position {i}", atol=FEATURE_TOLERANCE, rtol=0)
        for i, (got, expected_value) in enumerate(zip(slopes, want["feature_slope_values"])):
            strict_json_number(got, f"shape_features {key} feature slope {i}")
            close(got, expected_value, f"shape_features {key} feature slope {i}", atol=2e-6, rtol=2e-6)


def run(app: str, assets: str, logs: str) -> int:
    try:
        tests_dir = Path(__file__).resolve().parent
        basis_path = tests_dir / "refs.json"
        if basis_path.is_symlink() or not basis_path.is_file() or sha256_file(basis_path) != REFERENCE_SHA256:
            raise EnvironmentInvalid("frozen case-05 scientific reference basis is absent, redirected, or damaged")
        basis = json.loads(basis_path.read_text(encoding="utf-8"))
        if basis.get("schema") != "assembly-dyad/v1" or basis.get("criteria") != {
            "contact_threshold_angstrom": CONTACT_CUTOFF, "F_open_cutoff_degree": GAMMA_CUTOFF,
            "D_open_cutoff_degree": D_OPEN_CUTOFF, "shape_edges_angstrom": [0.0, 16.0, 0.01],
            "shape_smoothing_sigma_angstrom": list(SMOOTHING_SIGMA), "shape_method": "histogram probability density divided by r^2; gaussian_filter1d; np.gradient; scipy.signal.find_peaks(-slope)",
            "shape_windows_angstrom": {"D": list(SHOULDERS["D"]), "F": list(SHOULDERS["F"])},
            "shape_feature_tolerance_angstrom": FEATURE_TOLERANCE - 0.0000001,
        }:
            raise EnvironmentInvalid("frozen scientific basis schema or criteria do not match the verifier")
        inputs = public_root(assets, INPUT_SHA256)
        asset_key = str(Path(assets).resolve())
        cached = _DATA_CACHE.get(asset_key)
        if cached is None:
            series, summaries, frames = load_series(inputs)
            expected = scientific_reference(series, summaries)
            cached = (series, summaries, {"frames": frames, "expected": expected})
            _DATA_CACHE[asset_key] = cached
        series, summaries, cached_aux = cached
        expected = cached_aux["expected"]
        final = real_output_dir(app)
        out = require_files(final, ("distributions.csv", "rdf.csv", "findings.json", "report.md"))
        if out["report.md"].stat().st_size == 0:
            raise CandidateFail("report.md must contain a scientific analysis")
        try:
            report = out["report.md"].read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CandidateFail(f"report.md is not readable UTF-8 text: {exc}") from exc
        if not report.strip():
            raise CandidateFail("report.md must contain a scientific analysis")
        findings = load_json(out["findings.json"])
        if findings.get("schema") != "assembly-dyad/v1":
            raise CandidateFail("findings.json must declare schema assembly-dyad/v1")
        methods = findings.get("statistical_methods")
        if not isinstance(methods, list) or not methods or any(not isinstance(x, str) or not x.strip() for x in methods):
            raise CandidateFail("findings.json must state the chosen statistical methods")
        if findings.get("rdf_normalization") not in NORMALIZATIONS:
            raise CandidateFail("findings.json rdf_normalization must name one supported, independently recomputable definition")
        summary_rows = read_csv(out["distributions.csv"], {"assembly", "variant", "protonation", "observable", *STAT_FIELDS})
        summary_expected = {key: vals for key, vals in summaries.items()}
        check_rows(summary_rows, summary_expected, ("assembly", "variant", "protonation", "observable"), STAT_FIELDS,
                   "distributions.csv", ())
        rdf_rows = read_csv(out["rdf.csv"], {"assembly", "variant", "protonation", "bin_left", "bin_right", "count", "density"})
        grouped = {}
        for row in rdf_rows:
            key = (row["assembly"], row["variant"], row["protonation"])
            if key not in {(a, v, p) for a in ASSEMBLIES for v in VARIANTS for p in PROTONATIONS}:
                raise CandidateFail(f"rdf.csv contains an unknown group: {key}")
            left, right = strict_number(row["bin_left"], "bin_left"), strict_number(row["bin_right"], "bin_right")
            count, density = strict_number(row["count"], "count"), strict_number(row["density"], "density")
            if right <= left or count < 0 or int(count) != count or density < 0:
                raise CandidateFail(f"rdf.csv has invalid bounds/count/density for {key}")
            grouped.setdefault(key, []).append((left, right, int(count), density))
        if len(grouped) != 12:
            raise CandidateFail("rdf.csv must contain δ histograms for all 12 assembly/variant/protonation groups")
        normalization = findings["rdf_normalization"]
        for key, bins in grouped.items():
            bins.sort(key=lambda item: item[0])
            edges = np.asarray([bins[0][0]] + [entry[1] for entry in bins], dtype=float)
            if len(edges) != len(bins) + 1 or not np.allclose(np.diff(edges), np.diff(edges)[0], rtol=0, atol=1e-9):
                raise CandidateFail(f"rdf.csv bins are not uniform and contiguous for {key}")
            values = series[(*key, "delta")]
            if edges[0] > values.min() + 1e-9 or edges[-1] < values.max() - 1e-9:
                raise CandidateFail(f"rdf.csv bins do not cover the complete public δ range for {key}")
            # Compare counts exactly, except at bin boundaries: the same uniform grid built by
            # linspace and by this check's reconstruction from the reported decimal bounds differs
            # in the last bits, so a sample sitting exactly on a boundary may fall in either
            # adjacent bin. Only that ambiguity is allowed, bounded by the number of on-boundary
            # samples for each bin.
            counts, _ = np.histogram(values, bins=edges)
            submitted = np.array([x[2] for x in bins])
            ties = np.array([int(np.count_nonzero(np.isclose(values, edge, rtol=0, atol=1e-9)))
                             for edge in edges])
            slack = ties[:-1] + ties[1:]
            if np.any(np.abs(submitted - counts) > slack):
                raise CandidateFail(f"rdf.csv counts do not reproduce the pinned author values for {key}")
            n = values.size
            for left, right, count, got in bins:
                width = right - left
                want = {"raw_count": float(count), "frequency": count / n,
                        "probability_density": count / (n * width),
                        "radius_weighted_probability_density": ((left + right) / 2) * count / (n * width)}[normalization]
                if not math.isclose(got, want, rel_tol=2e-6, abs_tol=2e-8):
                    raise CandidateFail(f"rdf.csv density does not match declared {normalization} for {key}")
        # Required scientific claims are checked against matched, independently recomputed source series.
        candidate_selected_contrasts(findings, "mutation_effects", ("assembly", "protonation", "observable"), expected["mutation_effects"])
        candidate_selected_contrasts(findings, "protonation_effects", ("assembly", "variant", "target_protonation"), expected["protonation_effects"])
        candidate_row_map(findings, "local_contact_state", ("assembly", "variant", "protonation"),
                          ("threshold_angstrom", "probability_delta_le_threshold", "n"), (), expected["local_contact_state"])
        candidate_row_map(findings, "local_contact_differences", ("contrast", "assembly", "variant", "protonation", "reference", "target"),
                          ("effect",), ("reference", "conclusion"), expected["local_contact_differences"])
        apical = findings.get("apical_context")
        if not isinstance(apical, list) or len(apical) != len(expected["apical_context"]):
            raise CandidateFail("apical_context must cover all 12 direct gamma series")
        apical_seen = set()
        for row in apical:
            row = require_object(row, "apical_context row")
            key = (str(row.get("assembly", "")), str(row.get("variant", "")), str(row.get("protonation", "")))
            if key not in expected["apical_context"] or key in apical_seen:
                raise CandidateFail(f"apical_context contains an unknown or duplicate row: {key}")
            apical_seen.add(key)
            want = expected["apical_context"][key]
            strict_json_int(row.get("n"), f"apical_context {key} n")
            for field in ("gamma_location_median_degree", "n", "cutoff_degree"):
                strict_json_number(row.get(field), f"apical_context {key} {field}")
            close(row.get("gamma_location_median_degree"), want["gamma_location_median_degree"], f"apical_context {key} gamma_location_median_degree")
            close(row.get("n"), want["n"], f"apical_context {key} n")
            close(row.get("cutoff_degree"), want["cutoff_degree"], f"apical_context {key} cutoff_degree")
            fraction_field = "fraction_gamma_gt_120_degree" if key[0] == "F" else "fraction_gamma_ge_100_degree"
            strict_json_number(row.get(fraction_field), f"apical_context {key} {fraction_field}")
            close(row.get(fraction_field), want[fraction_field], f"apical_context {key} {fraction_field}")
            if row.get("cutoff_operator") != want["cutoff_operator"]:
                raise CandidateFail(f"apical_context {key} must use cutoff operator {want['cutoff_operator']}")
        candidate_row_map(findings, "delta_gamma_dependence", ("assembly", "variant", "protonation"),
                          ("n_paired", "coefficient"), ("method", "interpretation"), expected["delta_gamma_dependence"])
        for row in findings["delta_gamma_dependence"]:
            if isinstance(row, dict):
                strict_json_int(row.get("n_paired"), "delta_gamma_dependence n_paired")
        check_shape_rows(findings.get("shape_features"), expected["shape_features"])
        if not isinstance(findings.get("limitations"), list) or len(findings["limitations"]) < 1 or any(not isinstance(x, str) or not x.strip() for x in findings["limitations"]):
            raise CandidateFail("findings.json limitations must contain explanatory text")
        uncertainty = findings.get("uncertainty_provenance")
        if not isinstance(uncertainty, dict):
            raise CandidateFail("findings.json must declare structured uncertainty provenance")
        required_false = ("independent_replicates_available", "time_axis_available", "pooled_frame_spread_is_confidence_interval", "frames_treated_as_independent_samples")
        if any(uncertainty.get(field) is not False for field in required_false):
            raise CandidateFail("uncertainty_provenance must accurately mark absent replicate/time provenance and prohibit unsupported independence/CI claims")
        if findings.get("inference_status") != "descriptive_only":
            raise CandidateFail("findings.json must not claim unsupported inferential significance")
        return emit(logs, CASE, "PASS", "all distributions, δ histograms, matched mutation/protonation effects, local-contact probabilities, direct γ context, paired δ–γ dependence, and shoulder morphology reproduce the pinned author data and frozen scientific criteria", {
            "distribution_series_recomputed": len(summaries), "rdf_groups_recomputed": len(grouped),
            "mutation_effect_rows": len({key[:-1] for key in expected["mutation_effects"]}),
            "protonation_effect_rows": len({key[:-1] for key in expected["protonation_effects"]}),
            "shape_feature_rows": len(expected["shape_features"]), "reference_basis_sha256": REFERENCE_SHA256,
        })
    except EnvironmentInvalid as exc:
        return emit(logs, CASE, "ENV_INVALID", str(exc))
    except CandidateFail as exc:
        return emit(logs, CASE, "FAIL", str(exc))
    except Exception as exc:
        return emit(logs, CASE, "ENV_INVALID", f"verifier could not establish a safe complete result: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("app")
    parser.add_argument("--assets", required=True)
    parser.add_argument("--logs", required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.app, args.assets, args.logs))
