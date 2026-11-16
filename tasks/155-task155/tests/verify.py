#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: High-pressure SiO₂ equation of state and phase stability.
"""Case01 layered verifier. Exit: 0 PASS, 1 candidate FAIL, 2 evaluator ENV_ERROR."""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import io
import base64
import zlib
import math
import os
import sys
from pathlib import Path

try:
    import numpy as np
    from scipy.interpolate import PchipInterpolator, CubicSpline
except ImportError as exc:  # evaluator setup failure, never a candidate error
    print(f"ENV_ERROR: required scientific dependency unavailable: {exc}", file=sys.stderr)
    raise SystemExit(2)
csv.field_size_limit(sys.maxsize)
SCORING_REFS = {}
PRIVATE_PAYLOADS = {}

def private_bytes(label):
    item = PRIVATE_PAYLOADS[label]
    data = base64.b64decode(item["data"])
    if item["encoding"] == "zlib+base64": data = zlib.decompress(data)
    if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise EnvironmentError(f"corrupt encoded reference: {label}")
    return data

PHASE_NFU = {"low_quartz": 3, "coesite": 16, "stishovite": 2,
             "pbo2": 4, "rosiaite": 3, "pyrite": 4}
MODELS = ("ace", "dft")
EV_A3_TO_GPA = 160.21766208
HEADERS = {
    "normalized_eos.csv": ["phase", "model", "n_formula_units", "V_A3_per_fu", "E_eV_per_fu"],
    "eos_parameters.csv": ["phase", "model", "eos_form", "parameters_json", "n_points",
                           "fit_rmse_meV_per_atom", "fit_window_Vmin_A3_per_fu",
                           "fit_window_Vmax_A3_per_fu", "fit_valid"],
    "enthalpy.csv": ["phase", "model", "P_GPa", "V_A3_per_fu", "H_eV_per_fu",
                     "relative_H_meV_per_fu", "fit_valid", "relative_valid", "reason"],
    "crossings.csv": ["model", "phase_a", "phase_b", "P_low_GPa", "P_high_GPa",
                      "deltaH_uncertainty_meV_per_fu", "domain_basis", "reason"],
}
HEADERS["crossings.csv"] = ["model", "phase_a", "phase_b", "status", "P_low_GPa", "P_high_GPa",
                            "deltaH_uncertainty_meV_per_fu", "domain_basis", "reason"]


class CandidateFail(Exception):
    pass


class EnvironmentError(Exception):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def finite_number(value, label):
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise CandidateFail(f"{label}: expected finite number")
    if not math.isfinite(x):
        raise CandidateFail(f"{label}: nonfinite number")
    return x


def read_csv(path: Path, expected_header=None):
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise ValueError("missing header")
            if expected_header and reader.fieldnames != expected_header:
                raise ValueError(f"wrong header {reader.fieldnames!r}; expected {expected_header!r}")
            rows = list(reader)
    except Exception as exc:
        raise CandidateFail(f"unreadable {path.name}: {exc}") from exc
    if not rows:
        raise CandidateFail(f"{path.name}: no data rows")
    return rows


def load_reference(ref_dir: Path, suite_root: Path):
    refs=json.loads(((ref_dir / "refs.json") if ref_dir.is_dir() else (ref_dir.parent / "refs.json")).read_text(encoding="utf-8"))
    global PRIVATE_PAYLOADS
    PRIVATE_PAYLOADS=refs["_private_payloads"]
    def payload_json(label): return json.loads(private_bytes(label).decode("utf-8"))
    provenance=payload_json("private/provenance.json")
    for rel, expected in provenance.get("references", {}).items():
        label="source/"+rel; item=PRIVATE_PAYLOADS.get(label)
        if item is None or item.get("sha256")!=expected:
            raise EnvironmentError(f"reference source hash mismatch: {rel}")
        if item["encoding"]!="public-asset": private_bytes(label)
    for name, expected in provenance.get("reference_artifacts", {}).items():
        data=private_bytes("private/"+name)
        if hashlib.sha256(data).hexdigest()!=expected:
            raise EnvironmentError(f"derived reference artifact hash mismatch: {name}")
    crosscheck=payload_json("private/source-data-crosscheck.json")
    ref_text=private_bytes("private/legendre_reference.csv").decode("utf-8-sig")
    reader=csv.DictReader(io.StringIO(ref_text,newline=""))
    ref_rows=list(reader)
    if not ref_rows: raise EnvironmentError("empty encoded Legendre reference")
    return provenance,crosscheck,ref_rows


def load_public_inputs(package: Path, input_root: Path | None = None):
    base = input_root or package
    candidates = (base / "inputs/high_pressure/energy_volume",
                  base / "environment/assets/high_pressure/energy_volume",
                  base / "assets/high_pressure/energy_volume")
    data_dir = next((candidate for candidate in candidates if (candidate / "README.txt").is_file()), candidates[0])
    readme = data_dir / "README.txt"
    if not readme.is_file():
        raise EnvironmentError("missing public energy_volume README")
    raw = {}
    for phase, nfu in PHASE_NFU.items():
        for model in MODELS:
            path = data_dir / f"{phase}_{model}.dat"
            if not path.is_file():
                raise EnvironmentError(f"missing public input {path}")
            try:
                a = np.loadtxt(path)
            except Exception as exc:
                raise EnvironmentError(f"corrupt public input {path.name}: {exc}") from exc
            if a.ndim != 2 or a.shape[1] != 2 or len(a) < 4 or not np.isfinite(a).all():
                raise EnvironmentError(f"invalid public input table {path.name}")
            if model == "ace":
                energy, volume = a[:, 1], a[:, 0]
            else:
                energy, volume = a[:, 0], a[:, 1]
            v = volume / nfu
            e = energy / nfu
            idx = np.argsort(v)
            raw[(phase, model)] = (v[idx], e[idx])
    for model in MODELS:
        base_e = raw[("low_quartz", model)][1].min()
        for phase in PHASE_NFU:
            v, e = raw[(phase, model)]
            raw[(phase, model)] = (v, e - base_e)
    return raw


def _pressure_limit(interp, vmin):
    return max(0.0, -float(interp.derivative()(vmin)) * EV_A3_TO_GPA)


def _legendre_grid(v, e, method, pressures, ngrid=6001):
    interp = PchipInterpolator(v, e) if method == "PCHIP" else CubicSpline(v, e, extrapolate=False)
    vg = np.linspace(float(v[0]), float(v[-1]), ngrid)
    eg = np.asarray(interp(vg), dtype=float)
    h = np.empty(len(pressures), dtype=float)
    for i, p in enumerate(pressures):
        h[i] = np.min(eg + (float(p) / EV_A3_TO_GPA) * vg)
    return h, _pressure_limit(interp, float(v[0]))


def compute_fit_sensitivity(raw):
    """Numerically scan EOS fit windows and PCHIP/CubicSpline H(P) differences.

    Differences are reported in meV/atom on each comparison's shared interior
    pressure support. The same deterministic calculation is used by the scorer
    to check the candidate's uncertainty fields.
    """
    windows=[]; methods=[]
    for (phase, model), (v, e) in raw.items():
        full, pfull = _legendre_grid(v, e, "PCHIP", [0.0])
        # One source point is trimmed from both ends. This is ~98% of ACE data
        # and 82% of the DFT data, exposing fit-window sensitivity without
        # turning the scan into a different sparse-data problem.
        if len(v) < 5:
            raise EnvironmentError(f"too few native E(V) points for fit-window scan: {phase}/{model}")
        vw, ew = v[1:-1], e[1:-1]
        _, pwin = _legendre_grid(vw, ew, "PCHIP", [0.0])
        pmax = min(pfull, pwin)
        pressures = np.linspace(0.0, pmax, 201)
        hf, _ = _legendre_grid(v, e, "PCHIP", pressures)
        hw, _ = _legendre_grid(vw, ew, "PCHIP", pressures)
        fit_diff = float(np.max(np.abs(hw-hf))*1000/3)
        windows.append({"phase":phase,"model":model,"trim_each_end_points":1,
                        "retained_fraction":float(len(vw)/len(v)),"Vmin_A3_per_fu":float(vw[0]),
                        "Vmax_A3_per_fu":float(vw[-1]),"common_pressure_max_GPa":float(pmax),
                        "max_abs_H_change_meV_per_atom":fit_diff})
        pcmax = _pressure_limit(CubicSpline(v,e,extrapolate=False),float(v[0]))
        pmax = min(pfull,pcmax)
        pressures=np.linspace(0.0,pmax,201)
        hp,_=_legendre_grid(v,e,"PCHIP",pressures)
        hc,_=_legendre_grid(v,e,"CUBIC",pressures)
        method_diff=float(np.max(np.abs(hc-hp))*1000/3)
        methods.append({"phase":phase,"model":model,"reference_method":"PCHIP","comparison_method":"CubicSpline",
                        "common_pressure_max_GPa":float(pmax),"max_abs_H_change_meV_per_atom":method_diff})
    return windows, methods


def parse_finite_array(obj, key, label):
    arr = obj.get(key)
    if not isinstance(arr, list) or len(arr) < 20:
        raise CandidateFail(f"{label}: {key} must be a numeric curve with >=20 samples")
    vals = np.asarray([finite_number(x, f"{label}.{key}") for x in arr], float)
    return vals


def verify_normalized(rows, raw):
    groups = {}
    for i, row in enumerate(rows, 1):
        phase, model = row.get("phase"), row.get("model")
        if phase not in PHASE_NFU or model not in MODELS:
            raise CandidateFail(f"normalized_eos.csv row {i}: unknown phase/model")
        key = (phase, model)
        if key not in groups:
            groups[key] = []
        nfu = finite_number(row.get("n_formula_units"), f"normalized row {i} n_formula_units")
        v = finite_number(row.get("V_A3_per_fu"), f"normalized row {i} volume")
        e = finite_number(row.get("E_eV_per_fu"), f"normalized row {i} energy")
        if nfu != PHASE_NFU[phase]:
            raise CandidateFail(f"{key}: wrong formula-unit count {nfu}")
        groups[key].append((v, e))
    if set(groups) != {(p, m) for p in PHASE_NFU for m in MODELS}:
        raise CandidateFail("normalized_eos.csv must cover all six phases × ACE/DFT")
    for key, (vref, eref) in raw.items():
        got = sorted(groups[key])
        gv, ge = np.asarray(got).T
        if len(gv) != len(vref):
            raise CandidateFail(f"{key}: normalized row count {len(gv)} != input {len(vref)}")
        if np.max(np.abs(gv - vref)) > float(SCORING_REFS["volume_per_formula_unit_tolerance_A3"]):
            raise CandidateFail(f"{key}: V/FU indicates a column-order or formula-unit error")
        if np.max(np.abs(ge - eref)) > float(SCORING_REFS["energy_volume_per_formula_unit_tolerance"]):
            raise CandidateFail(f"{key}: normalized E/FU or per-model energy zero is incorrect")


def verify_parameters(rows, raw, provenance):
    keyed = {}
    for i, row in enumerate(rows, 1):
        key = (row.get("phase"), row.get("model"))
        if key not in {(p, m) for p in PHASE_NFU for m in MODELS} or key in keyed:
            raise CandidateFail(f"eos_parameters.csv row {i}: unknown or repeated phase/model")
        keyed[key] = row
    if set(keyed) != {(p, m) for p in PHASE_NFU for m in MODELS}:
        raise CandidateFail("eos_parameters.csv must contain all six phases × ACE/DFT")
    for key, row in keyed.items():
        v, e = raw[key]
        n_points_value = finite_number(row.get("n_points"), f"{key} n_points")
        if not n_points_value.is_integer():
            raise CandidateFail(f"{key}: n_points must be an integer")
        lo = finite_number(row.get("fit_window_Vmin_A3_per_fu"), f"{key} Vmin")
        hi = finite_number(row.get("fit_window_Vmax_A3_per_fu"), f"{key} Vmax")
        if lo < v.min() - 1e-7 or hi > v.max() + 1e-7 or hi <= lo:
            raise CandidateFail(f"{key}: fit window exceeds finite source V range")
        fit_mask = (v >= lo - 1e-8) & (v <= hi + 1e-8)
        expected_n = int(fit_mask.sum())
        if int(n_points_value) != expected_n or expected_n < math.ceil(float(SCORING_REFS["fit_window_minimum_source_fraction"]) * len(v)):
            raise CandidateFail(f"{key}: fit-window n_points must be exact and cover >=80% of source points")
        rmse = finite_number(row.get("fit_rmse_meV_per_atom"), f"{key} fit RMSE")
        if rmse < 0:
            raise CandidateFail(f"{key}: negative fit RMSE")
        try:
            params = json.loads(row.get("parameters_json", ""))
        except Exception as exc:
            raise CandidateFail(f"{key}: parameters_json invalid: {exc}") from exc
        if not isinstance(params, dict):
            raise CandidateFail(f"{key}: parameters_json must be an object")
        cv = parse_finite_array(params, "curve_volume_A3_per_fu", str(key))
        ce = parse_finite_array(params, "curve_energy_eV_per_fu", str(key))
        if len(cv) != len(ce) or np.any(np.diff(cv) <= 0):
            raise CandidateFail(f"{key}: EOS curve arrays must be same-length and V-sorted")
        if cv[0] < lo - 1e-7 or cv[-1] > hi + 1e-7:
            raise CandidateFail(f"{key}: reported curve extends outside fit window")
        mask = fit_mask
        pred = np.interp(v[mask], cv, ce)
        actual_rmse = float(np.sqrt(np.mean((pred - e[mask]) ** 2)) * 1000 / 3)
        if abs(actual_rmse - rmse) > max(float(SCORING_REFS["fit_rmse_report_tolerance_meV_per_atom_floor"]), float(SCORING_REFS["fit_rmse_report_tolerance_relative_fraction"]) * max(actual_rmse, rmse)):
            raise CandidateFail(f"{key}: claimed fit RMSE does not match the delivered curve")
        limit = provenance["fit_diagnostics"][key[0]][key[1]]["fit_residual_ceiling_meV_per_atom"]
        # The phase/model-specific ceiling is the larger of a shape-preserving
        # leave-one-out estimate and an all-data BM3 residual; it accepts either
        # an accurate spline or the paper's BM3 family without a blanket limit.
        if actual_rmse > float(limit) * float(SCORING_REFS["fit_residual_calibration_multiplier"]) + float(SCORING_REFS["fit_residual_calibration_offset_meV_per_atom"]):
            raise CandidateFail(f"{key}: EOS residual {actual_rmse:.4g} exceeds calibrated {limit:.4g} meV/atom")
        if row.get("fit_valid", "").strip().lower() not in {"true", "yes", "1"}:
            raise CandidateFail(f"{key}: fit_valid must be true for the declared finite fit window")
        curve_min = int(np.argmin(ce))
        if curve_min in (0, len(ce)-1):
            raise CandidateFail(f"{key}: EOS minimum is clamped to curve endpoint")
        # Some native ACE tables have small numerical non-convex regions.
        # Physical stability is therefore assessed by the stable Legendre
        # envelope below, rather than by imposing global convexity on E(V).
    return keyed


def verify_enthalpy(rows, curves, raw, provenance):
    grouped = {}
    for i, row in enumerate(rows, 1):
        key = (row.get("phase"), row.get("model"))
        if key not in curves:
            raise CandidateFail(f"enthalpy row {i}: unknown phase/model")
        p = finite_number(row.get("P_GPa"), f"enthalpy row {i} pressure")
        v = finite_number(row.get("V_A3_per_fu"), f"enthalpy row {i} volume")
        h = finite_number(row.get("H_eV_per_fu"), f"enthalpy row {i} H")
        valid = row.get("fit_valid", "").strip().lower() in {"true", "1", "yes"}
        rvalid = row.get("relative_valid", "").strip().lower() in {"true", "1", "yes"}
        if valid:
            cv, ce = curves[key]
            if v <= cv[0] + (cv[1]-cv[0]) or v >= cv[-1] - (cv[-1]-cv[-2]):
                raise CandidateFail(f"{key} at {p:g} GPa: minimizing V outside delivered fit curve")
            vin, _ = raw[key]
            if v < vin.min() or v > vin.max():
                raise CandidateFail(f"{key} at {p:g} GPa: minimizing V outside sampled input support")
            ev = float(np.interp(v, cv, ce))
            expected_h = ev + (p / EV_A3_TO_GPA) * v
            if abs(h - expected_h) > 2e-5:
                raise CandidateFail(f"{key} at {p:g} GPa: H != E(V)+PV using 1 eV/A3={EV_A3_TO_GPA} GPa")
            # Check stationarity against the delivered E(V) curve; a stable
            # method may interpolate differently, so the tolerance is tied to
            # the reported grid resolution rather than author-specific code.
            dense = np.linspace(cv[0], cv[-1], 2000)
            val = np.interp(dense, cv, ce) + p / EV_A3_TO_GPA * dense
            if val.min() < expected_h - float(SCORING_REFS["enthalpy_legendre_minimum_tolerance_eV_per_fu"]):
                raise CandidateFail(f"{key} at {p:g} GPa: selected volume is not the stable Legendre minimum")
        rel = row.get("relative_H_meV_per_fu", "").strip()
        if rvalid:
            finite_number(rel, f"enthalpy row {i} relative H")
            if row.get("reason", "").strip():
                raise CandidateFail(f"enthalpy row {i}: reason must be empty for valid relative H")
        elif rel or not row.get("reason", "").strip():
            raise CandidateFail(f"enthalpy row {i}: unsupported relative H requires blank value plus reason")
        grouped.setdefault(key, []).append((p, v, h, valid, float(rel) if rvalid else None, row.get("reason", "").strip()))
    if set(grouped) != set(curves):
        raise CandidateFail("enthalpy.csv must cover all phases × models")
    for key, data in grouped.items():
        if len(data) < 20:
            raise CandidateFail(f"{key}: enthalpy curve needs >=20 pressure samples")
        data.sort()
        pressures = np.asarray([r[0] for r in data], float)
        if abs(float(pressures[0])) > 1e-8:
            raise CandidateFail(f"{key}: enthalpy support must start at 0 GPa")
        if np.any(np.diff(pressures) <= 0):
            raise CandidateFail(f"{key}: duplicate or unsorted pressures")
        if np.max(np.diff(pressures)) > 0.5 + 1e-9:
            raise CandidateFail(f"{key}: pressure grid gap >0.5 GPa cannot support crossing enumeration")
        support = np.asarray([r[3] for r in data], bool)
        if support.sum() < 20 or not bool(support[0]):
            raise CandidateFail(f"{key}: no non-null supported H(P) curve")
        pmax = float(pressures[support].max())
        refp = provenance["phase_model_pressure_support_gpa"][key[0]][key[1]]
        cv, ce = curves[key]
        endpoint_pressure = -float(np.gradient(ce, cv, edge_order=2)[0]) * EV_A3_TO_GPA
        if not refp or pmax < 0.9 * float(refp[1]):
            raise CandidateFail(f"{key}: declared supported pressure range does not match finite-volume source range")
        if pmax > endpoint_pressure + 0.5:
            raise CandidateFail(f"{key}: fit_valid pressure exceeds the compression-end slope of its EOS curve")
        if not np.all(support[:int(support.sum())]) or np.any(support[int(support.sum()):]):
            raise CandidateFail(f"{key}: fit_valid must be one continuous low-to-high pressure support interval")
    return grouped


def verify_relative_enthalpies(enthalpy, reference_rows, provenance):
    reference = {}
    for row in reference_rows:
        if row["fit_valid"].lower() != "true":
            continue
        key = (row["phase"], row["model"])
        reference.setdefault(key, []).append((float(row["P_GPa"]),
                                               float(row["relative_H_vs_stishovite_meV_per_fu"])))
    for key, rows in enthalpy.items():
        model, phase = key[1], key[0]
        st_rows = {r[0]: r for r in enthalpy[("stishovite", model)]}
        relative_count = 0
        for p, _, h, valid, rel, reason in rows:
            base = st_rows.get(p)
            expected_valid = bool(valid and base and base[3])
            if expected_valid:
                if rel is None or abs(rel - (h - base[2]) * 1000) > float(SCORING_REFS["enthalpy_relative_identity_tolerance_meV_per_fu"]):
                    raise CandidateFail(f"{key} at {p:g} GPa: relative_H != H(phase)-H(stishovite)")
                relative_count += 1
            elif rel is not None:
                raise CandidateFail(f"{key} at {p:g} GPa: relative H reported outside shared support")
        if relative_count < 20:
            raise CandidateFail(f"{key}: insufficient non-null relative-H coverage in shared support")
        if phase == "stishovite":
            continue
        ref = np.asarray(reference.get(key, []), float)
        if len(ref) < 2:
            continue
        st = np.asarray(reference.get(("stishovite", model), []), float)
        if len(st) < 2:
            continue
        fit_i = provenance["fit_diagnostics"][phase][model]["fit_residual_ceiling_meV_per_atom"]
        fit_s = provenance["fit_diagnostics"]["stishovite"][model]["fit_residual_ceiling_meV_per_atom"]
        tolerance = 3.0 * math.sqrt(float(fit_i) ** 2 + float(fit_s) ** 2) * 1.25 + 0.5
        for p, _, _, valid, rel, _ in rows:
            if not valid or rel is None:
                continue
            pmin = max(ref[:, 0].min(), st[:, 0].min())
            pmax = min(ref[:, 0].max(), st[:, 0].max())
            if p < pmin or p > pmax:
                continue
            expected = float(np.interp(p, ref[:, 0], ref[:, 1]))
            if abs(rel - expected) > tolerance:
                raise CandidateFail(f"{key} at {p:g} GPa: relative enthalpy differs from independent E(V) transform by >{tolerance:.3g} meV/FU")


def _roots(rows_a, rows_b):
    a = {x[0]: x for x in rows_a}
    b = {x[0]: x for x in rows_b}
    common = sorted(set(a) & set(b))
    points = [(p, a[p][2]-b[p][2]) for p in common if a[p][3] and b[p][3]]
    roots = []
    for (p0, d0), (p1, d1) in zip(points, points[1:]):
        if d0 == 0:
            roots.append((p0, p0, p0))
        elif d0 * d1 < 0:
            root = p0 + (p1-p0) * abs(d0) / (abs(d0)+abs(d1))
            roots.append((p0, p1, root))
    if points and points[-1][1] == 0:
        roots.append((points[-1][0], points[-1][0], points[-1][0]))
    dedup = []
    for r in roots:
        if not dedup or abs(r[2] - dedup[-1][2]) > 1e-7:
            dedup.append(r)
    return dedup, points


def verify_crossings(rows, enthalpy, reference_rows, provenance):
    keyed = {}
    for i, row in enumerate(rows, 1):
        model, a, b = row.get("model"), row.get("phase_a"), row.get("phase_b")
        if model not in MODELS or a not in PHASE_NFU or b not in PHASE_NFU or a == b:
            raise CandidateFail(f"crossings row {i}: invalid model/phase pair")
        if list(PHASE_NFU).index(a) > list(PHASE_NFU).index(b):
            a, b = b, a
        status = row.get("status", "").strip()
        if status not in {"crossing", "no_crossing_in_common_supported_domain"}:
            raise CandidateFail(f"crossings row {i}: invalid status")
        keyed.setdefault((model, a, b), []).append((row, status))
    expected_pairs = {(m, a, b) for m in MODELS for a, b in itertools.combinations(PHASE_NFU, 2)}
    if set(keyed) != expected_pairs:
        raise CandidateFail("crossings.csv must enumerate every phase pair for both ACE and DFT")

    refmap = {}
    for row in reference_rows:
        if row["fit_valid"].lower() == "true":
            refmap.setdefault((row["phase"], row["model"]), []).append(
                (float(row["P_GPa"]), float(row["H_eV_per_fu"])))
    for model, a, b in sorted(expected_pairs):
        root_rows, common = _roots(enthalpy[(a, model)], enthalpy[(b, model)])
        entries = keyed[(model, a, b)]
        crossings = sorted((x[0] for x in entries if x[1] == "crossing"), key=lambda r: finite_number(r.get("P_low_GPa"), "crossing P_low"))
        nones = [x[0] for x in entries if x[1] != "crossing"]
        # Independently enumerate crossings of the E(V)-derived reference
        # inside the candidate's shared supported interval. This prevents a
        # candidate from hiding expected roots by labeling every pair
        # "no-crossing" or by reporting only one of several roots.
        candidate_a = [r[0] for r in enthalpy[(a, model)] if r[3]]
        candidate_b = [r[0] for r in enthalpy[(b, model)] if r[3]]
        shared_lo = max(min(candidate_a), min(candidate_b))
        shared_hi = min(max(candidate_a), max(candidate_b))
        ra_all = [(float(r["P_GPa"]), 0.0, float(r["H_eV_per_fu"]), True, None, "")
                  for r in reference_rows if r["model"] == model and r["phase"] == a and r["fit_valid"].lower() == "true"
                  and shared_lo <= float(r["P_GPa"]) <= shared_hi]
        rb_all = [(float(r["P_GPa"]), 0.0, float(r["H_eV_per_fu"]), True, None, "")
                  for r in reference_rows if r["model"] == model and r["phase"] == b and r["fit_valid"].lower() == "true"
                  and shared_lo <= float(r["P_GPa"]) <= shared_hi]
        reference_roots, _ = _roots(ra_all, rb_all)
        if len(root_rows) != len(reference_roots):
            raise CandidateFail(f"{model} {a}/{b}: candidate reports {len(root_rows)} crossings but independent E(V) reference has {len(reference_roots)} within shared support")
        if len(crossings) != len(root_rows) or (root_rows and nones) or (not root_rows and len(nones) != 1):
            raise CandidateFail(f"{model} {a}/{b}: crossing rows do not enumerate all supported roots/no-root result")
        for row, (plo, phi, proot) in zip(crossings, root_rows):
            lo = finite_number(row.get("P_low_GPa"), f"{model} {a}/{b} crossing lower P")
            hi = finite_number(row.get("P_high_GPa"), f"{model} {a}/{b} crossing upper P")
            unc = finite_number(row.get("deltaH_uncertainty_meV_per_fu"), f"{model} {a}/{b} uncertainty")
            if unc <= 0 or hi < lo or hi-lo > float(SCORING_REFS["crossing_bracket_max_width_GPa"]) + 1e-8 or lo < plo-1e-8 or hi > phi+1e-8:
                raise CandidateFail(f"{model} {a}/{b}: crossing bracket must be narrow and supported")
            if abs((lo+hi)/2 - proot) > max(float(SCORING_REFS["crossing_midpoint_tolerance_floor_GPa"]), hi-lo):
                raise CandidateFail(f"{model} {a}/{b}: crossing bracket misses delivered H(P) root")
            if "conditional" not in row.get("domain_basis", "").lower() and "all-six" not in row.get("domain_basis", "").lower():
                raise CandidateFail(f"{model} {a}/{b}: domain_basis must distinguish conditional from all-six scope")
            # Compare the crossing with the independent E(V) transform only
            # where both source curves have interior minima. Near-tangent roots
            # use the propagated phase-specific EOS uncertainty as a P band.
            ra = np.asarray(refmap.get((a, model), []), float)
            rb = np.asarray(refmap.get((b, model), []), float)
            if len(ra) and len(rb):
                lo_ref, hi_ref = max(ra[:,0].min(), rb[:,0].min()), min(ra[:,0].max(), rb[:,0].max())
                if lo_ref <= hi_ref:
                    grid = np.arange(lo_ref, hi_ref+0.05, 0.1)
                    dh = np.interp(grid, ra[:,0], ra[:,1]) - np.interp(grid, rb[:,0], rb[:,1])
                    ref_roots = [grid[i] + 0.1*abs(dh[i])/(abs(dh[i])+abs(dh[i+1]))
                                 for i in range(len(grid)-1) if dh[i]*dh[i+1] < 0]
                    if ref_roots:
                        nearest = min(abs(proot-r) for r in ref_roots)
                        ta = provenance["fit_diagnostics"][a][model]["fit_residual_ceiling_meV_per_atom"]
                        tb = provenance["fit_diagnostics"][b][model]["fit_residual_ceiling_meV_per_atom"]
                        ref_vals = np.interp(np.asarray(ref_roots), grid, dh)
                        idx = int(np.argmin(abs(np.asarray(ref_roots)-proot)))
                        slope = abs((dh[min(len(dh)-1, max(1, int(round((ref_roots[idx]-grid[0])/.1))+1))] - dh[max(0, int(round((ref_roots[idx]-grid[0])/.1))-1)]) / 0.2)
                        p_tol = max(float(SCORING_REFS["crossing_reference_tolerance_floor_GPa"]), 3*math.sqrt(ta*ta+tb*tb)*float(SCORING_REFS["crossing_reference_tolerance_multiplier"])/max(slope, 1e-6))
                        if nearest > p_tol:
                            raise CandidateFail(f"{model} {a}/{b}: crossing shifts {nearest:.3g} GPa beyond propagated {p_tol:.3g} GPa basis")
        if nones:
            row = nones[0]
            if row.get("P_low_GPa", "").strip() or row.get("P_high_GPa", "").strip() or not row.get("reason", "").strip():
                raise CandidateFail(f"{model} {a}/{b}: no-crossing record needs empty pressures and a reason")


def load_scoring_refs(tests: Path):
    needed=("volume_per_formula_unit_tolerance_A3","energy_volume_per_formula_unit_tolerance","fit_rmse_report_tolerance_meV_per_atom_floor","fit_rmse_report_tolerance_relative_fraction","fit_residual_calibration_multiplier","fit_residual_calibration_offset_meV_per_atom","enthalpy_legendre_minimum_tolerance_eV_per_fu","enthalpy_relative_identity_tolerance_meV_per_fu","crossing_bracket_max_width_GPa","crossing_midpoint_tolerance_floor_GPa","fit_window_minimum_source_fraction","crossing_reference_tolerance_multiplier","crossing_reference_tolerance_floor_GPa")
    try:
        refs=json.loads((tests/"refs.json").read_text(encoding="utf-8"))
        if not isinstance(refs,dict) or not set(needed).issubset(refs) or not isinstance(refs.get("_private_payloads"),dict): raise ValueError("missing scoring references or encoded closure")
        if any(isinstance(refs[k], bool) or not isinstance(refs[k], (int, float)) or not math.isfinite(float(refs[k])) or float(refs[k]) < 0 for k in needed): raise ValueError("scoring references must be finite nonnegative numbers")
        return refs
    except Exception as exc: raise EnvironmentError(f"tests/refs.json missing or malformed: {exc}") from exc

def run(output: Path, package: Path, ref_dir: Path, suite_root: Path, input_root: Path | None = None):
    global SCORING_REFS
    SCORING_REFS=load_scoring_refs(package/"tests")
    provenance, crosscheck, ref_rows = load_reference(ref_dir, suite_root)
    raw = load_public_inputs(package, input_root)
    out = output / "outputs"
    if not out.is_dir():
        raise CandidateFail("missing outputs/")
    summary_path = out / "summary.json"
    if not summary_path.is_file():
        raise CandidateFail("missing outputs/summary.json")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CandidateFail(f"invalid summary.json: {exc}") from exc
    if not isinstance(summary, dict) or not {"units", "method", "valid_domain", "phase_results", "uncertainty"}.issubset(summary):
        raise CandidateFail("summary.json missing required science fields")
    units = summary["units"]
    if not isinstance(units, dict) or units.get("volume") != "A^3/FU" or units.get("energy") != "eV/FU" or units.get("pressure") != "GPa":
        raise CandidateFail("summary.units must state volume=A^3/FU, energy=eV/FU, pressure=GPa")
    if not isinstance(summary["method"], dict) or not summary["method"].get("description"):
        raise CandidateFail("summary.method needs a reproducible method description")
    for name, header in HEADERS.items():
        if not (out / name).is_file():
            raise CandidateFail(f"missing outputs/{name}")
    normalized = read_csv(out / "normalized_eos.csv", HEADERS["normalized_eos.csv"])
    params = read_csv(out / "eos_parameters.csv", HEADERS["eos_parameters.csv"])
    hrows = read_csv(out / "enthalpy.csv", HEADERS["enthalpy.csv"])
    crossings = read_csv(out / "crossings.csv", HEADERS["crossings.csv"])
    verify_normalized(normalized, raw)
    fit_rows = verify_parameters(params, raw, provenance)
    curves = {}
    for key, row in fit_rows.items():
        parsed = json.loads(row["parameters_json"])
        curves[key] = (np.asarray(parsed["curve_volume_A3_per_fu"], float),
                       np.asarray(parsed["curve_energy_eV_per_fu"], float))
    hgroup = verify_enthalpy(hrows, curves, raw, provenance)
    verify_relative_enthalpies(hgroup, ref_rows, provenance)
    verify_crossings(crossings, hgroup, ref_rows, provenance)
    expected_groups = {f"{p}:{m}" for p in PHASE_NFU for m in MODELS}
    phase_results = summary["phase_results"]
    if not isinstance(phase_results, list) or {f"{x.get('phase')}:{x.get('model')}" for x in phase_results if isinstance(x, dict)} != expected_groups:
        raise CandidateFail("summary.phase_results must contain exactly six phases × two models")
    phase_map = {(x.get("phase"), x.get("model")): x for x in phase_results if isinstance(x, dict)}
    for key, record in phase_map.items():
        if not record.get("conclusion") or "conditional" not in str(record["conclusion"]).lower():
            raise CandidateFail(f"summary.phase_results {key} must state a conditional, support-bounded conclusion")
        rel_rows = [r for r in hgroup[key] if r[4] is not None and abs(r[0]) < 1e-8]
        if len(rel_rows) != 1:
            raise CandidateFail(f"{key}: need one supported P=0 relative-enthalpy value")
        rel_values = [r[4] for r in hgroup[key] if r[4] is not None]
        expected_fields = {
            "relative_H_at_0_meV_per_fu": rel_rows[0][4],
            "relative_H_min_meV_per_fu": min(rel_values),
            "relative_H_max_meV_per_fu": max(rel_values),
        }
        for field, expected in expected_fields.items():
            got = finite_number(record.get(field), f"summary.phase_results {key} {field}")
            if abs(got - expected) > 0.51:
                raise CandidateFail(f"summary.phase_results {key} {field} does not match enthalpy.csv")
    domain = summary["valid_domain"]
    if not isinstance(domain, list) or len(domain) != len(expected_groups):
        raise CandidateFail("summary.valid_domain must report each phase/model support interval")
    domain_map = {(x.get("phase"), x.get("model")): x for x in domain if isinstance(x, dict)}
    for key, rows_for_key in hgroup.items():
        valid_p = [r[0] for r in rows_for_key if r[3]]
        record = domain_map.get(key)
        if not valid_p or not record:
            raise CandidateFail(f"summary.valid_domain missing supported curve {key}")
        lo, hi = finite_number(record.get("Pmin_GPa"), f"{key} Pmin"), finite_number(record.get("Pmax_GPa"), f"{key} Pmax")
        if abs(lo-min(valid_p)) > 1e-6 or abs(hi-max(valid_p)) > 1e-6:
            raise CandidateFail(f"summary.valid_domain disagrees with enthalpy.csv for {key}")
    unc = summary["uncertainty"]
    if not isinstance(unc, dict) or not all(isinstance(unc.get(k), (int, float)) and math.isfinite(float(unc[k])) and float(unc[k]) >= 0
                                            for k in ("max_fit_window_sensitivity_meV_per_atom", "max_loo_residual_meV_per_atom", "max_method_sensitivity_meV_per_atom")):
        raise CandidateFail("summary.uncertainty must quantify finite nonnegative fit-window, LOO, and method sensitivity")
    # Compare reported LOO uncertainty against independently derived diagnostics.
    loo_max = max(provenance["fit_diagnostics"][p][m]["loocv_pchip_max_abs_meV_per_atom"] for p in PHASE_NFU for m in MODELS)
    if float(unc["max_loo_residual_meV_per_atom"]) + 1e-8 < loo_max:
        raise CandidateFail("summary under-reports the independently computed maximum LOO residual")
    if float(unc["max_fit_window_sensitivity_meV_per_atom"]) <= 0 or float(unc["max_method_sensitivity_meV_per_atom"]) <= 0:
        raise CandidateFail("fit-window and method sensitivity must be measured, not omitted as zero")
    expected_windows, expected_methods = compute_fit_sensitivity(raw)
    for field, expected_rows in (("fit_window_scan", expected_windows), ("method_scan", expected_methods)):
        got_rows = unc.get(field)
        if not isinstance(got_rows, list) or len(got_rows) != len(expected_rows):
            raise CandidateFail(f"summary.uncertainty.{field} must contain all 12 measured phase/model comparisons")
        key_fields = ("phase", "model")
        expected_map = {(r["phase"], r["model"]): r for r in expected_rows}
        got_map = {}
        for row in got_rows:
            if not isinstance(row, dict):
                raise CandidateFail(f"summary.uncertainty.{field} rows must be objects")
            key = tuple(row.get(k) for k in key_fields)
            if key not in expected_map or key in got_map:
                raise CandidateFail(f"summary.uncertainty.{field} has unknown or duplicate phase/model")
            got_map[key] = row
        for key, expected in expected_map.items():
            got = got_map[key]
            for name, value in expected.items():
                if name in key_fields:
                    if got.get(name) != value:
                        raise CandidateFail(f"summary.uncertainty.{field} {key} {name} mismatch")
                elif isinstance(value, (int, float)):
                    observed = finite_number(got.get(name), f"uncertainty.{field} {key} {name}")
                    if abs(observed - float(value)) > max(1e-7, abs(float(value))*2e-6):
                        raise CandidateFail(f"summary.uncertainty.{field} {key} {name} is not supported by the public E(V) scan")
                elif got.get(name) != value:
                    raise CandidateFail(f"summary.uncertainty.{field} {key} {name} mismatch")
    fit_max = max(r["max_abs_H_change_meV_per_atom"] for r in expected_windows)
    method_max = max(r["max_abs_H_change_meV_per_atom"] for r in expected_methods)
    if abs(float(unc["max_fit_window_sensitivity_meV_per_atom"]) - fit_max) > max(1e-7, fit_max*2e-6):
        raise CandidateFail("reported fit-window sensitivity does not match the actual one-point-end-trim scan")
    if abs(float(unc["max_method_sensitivity_meV_per_atom"]) - method_max) > max(1e-7, method_max*2e-6):
        raise CandidateFail("reported method sensitivity does not match the PCHIP/CubicSpline scan")
    required_figures = [*(f"eos_{p}_{m}.png" for p in PHASE_NFU for m in MODELS),
                        "enthalpy_ace.png", "enthalpy_dft.png", "deltaH_ace.png", "deltaH_dft.png"]
    figdir = out / "figures"
    for name in required_figures:
        p = figdir / name
        if not p.is_file():
            raise CandidateFail(f"missing required scientific figure {name}")
        try:
            from PIL import Image
            with p.open("rb") as f:
                signature = f.read(8)
            if signature != b"\x89PNG\r\n\x1a\n":
                raise CandidateFail(f"invalid scientific PNG: {p.name}")
            with Image.open(p) as im:
                im.verify()
            with Image.open(p) as im:
                rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)
                if float(rgb.std()) < 5.0:
                    raise CandidateFail(f"scientific figure appears blank: {p.name}")
        except OSError as exc:
            raise CandidateFail(f"unreadable scientific figure {p.name}: {exc}")
        except ImportError as exc:
            raise EnvironmentError(f"Pillow required for PNG verification: {exc}")
    return "L1/L2/L3 PASS: input normalization, finite-domain EOS, thermodynamic consistency, supported relative enthalpy and crossings verified"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", nargs="?", default=".")
    parser.add_argument("--reference-dir", type=Path)
    parser.add_argument("--suite-root", type=Path)
    parser.add_argument("--input-root", type=Path)
    args = parser.parse_args()
    package = Path(__file__).resolve().parents[1]
    suite = args.suite_root or Path(__file__).resolve().parents[3]
    ref_dir = args.reference_dir or Path(os.environ.get("P2B_REFERENCE_ROOT", suite / "author/local-reference/references")) / "case-01"
    try:
        app = Path(args.output_dir).resolve()
        raw_root = args.input_root or (app if (app / "inputs").is_dir() else package)
        input_root = raw_root.resolve()
        if not input_root.is_dir():
            raise EnvironmentError("input root is missing or is not a directory")
        print(run(app, package, ref_dir.resolve(), suite.resolve(), input_root))
        return 0
    except CandidateFail as exc:
        print(f"FAIL: {exc}")
        return 1
    except EnvironmentError as exc:
        print(f"ENV_ERROR: {exc}")
        return 2
    except Exception as exc:
        print(f"ENV_ERROR: unexpected evaluator/reference error: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
