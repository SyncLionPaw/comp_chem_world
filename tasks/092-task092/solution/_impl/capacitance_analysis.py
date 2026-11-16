#!/usr/bin/env python3
"""Capacitance and Parsons--Zobel analysis for a case-005 solution family.

Input is a real author-generated sweep table with concentration, fixed surface
polarization, surface charge and potential. The curve stays parameterized by
surface charge through folds; it is never sorted by potential. For nonzero
Pbar, both the GC own-PZC and model-PZC conventions are reported.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

QE = 1.602176634e-19
KB = 1.380649e-23
EPS0 = 8.8541878128e-12
NA = 6.02214076e23


def _array(values, label):
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or x.size < 3 or not np.all(np.isfinite(x)):
        raise ValueError(f"{label} must be a finite 1-D array with at least 3 values")
    return x


def capacitance_curve(phi0_V, sigma0_C_m2):
    """Compute signed/absolute C along increasing sigma on one branch.

    Never sort by phi: a branch may fold and such sorting would connect
    different sigma intervals.  The returned phi/sigma retain sigma order.
    """
    phi = _array(phi0_V, "phi0_V")
    sigma = _array(sigma0_C_m2, "sigma0_C_m2")
    if phi.size != sigma.size:
        raise ValueError("potential and charge arrays must have the same length")
    order = np.argsort(sigma)
    phi, sigma = phi[order], sigma[order]
    if np.any(np.diff(sigma) <= 0):
        raise ValueError("surface charges must be distinct")
    dphi_dsigma = np.gradient(phi, sigma, edge_order=2)
    if np.any(~np.isfinite(dphi_dsigma)) or np.any(dphi_dsigma == 0):
        raise ValueError("branch has singular or non-finite local dphi/dsigma")
    signed = 1.0 / dphi_dsigma
    return phi, sigma, signed, np.abs(signed)


def gc_capacitance(concentration_mM, temperature_K, eps_b,
                   phi0_V=0.0):
    """Equation-35 GC capacitance in F/m^2, at the supplied potential."""
    c = np.asarray(concentration_mM, dtype=float)
    if np.any(~np.isfinite(c)) or np.any(c <= 0) or temperature_K <= 0 or eps_b <= 0:
        raise ValueError("concentration, temperature and eps_b must be positive and finite")
    # 1 mM = 1 mol/m^3, so the numeric concentration in mM is
    # already the number of mol per cubic metre.
    nb = c * NA
    kappa = np.sqrt(2 * QE**2 * nb / (EPS0 * eps_b * KB * temperature_K))
    c_d = EPS0 * eps_b * kappa
    vt = KB * temperature_K / QE
    return c_d * np.cosh(np.asarray(phi0_V, dtype=float) / (2.0 * vt))


def _linear_at_zero(x, y):
    order = np.argsort(x)
    x, y = x[order], y[order]
    exact = np.flatnonzero(np.isclose(x, 0.0, rtol=0.0, atol=1e-14))
    if exact.size:
        return float(y[exact[0]])
    right = np.searchsorted(x, 0.0)
    if right == 0 or right == x.size:
        raise ValueError("sweep must bracket sigma0=0 to determine the pzc")
    f = -x[right - 1] / (x[right] - x[right - 1])
    return float(y[right - 1] + f * (y[right] - y[right - 1]))


def analyze_sweep(rows, temperature_K, eps_b,
                  fit_concentrations_mM=None):
    """Analyze each fixed-(concentration, Pbar) branch and optional PZ fit.

    Required row keys: concentration_mM, Pbar_C_m2, sigma0_C_m2, phi0_V.
    If fit concentrations are supplied, each value must have one and only one
    branch at a common Pbar. The caller is responsible for choosing a
    scientifically justified concentration set and fit interval.
    """
    needed = ("concentration_mM", "Pbar_C_m2", "sigma0_C_m2", "phi0_V")
    clean = []
    for row in rows:
        clean.append({k: float(row[k]) for k in needed})
    if not clean:
        raise ValueError("sweep table is empty")
    keys = sorted({(r["concentration_mM"], r["Pbar_C_m2"]) for r in clean})
    branches = []
    pzc = []
    for concentration, pbar in keys:
        group = [r for r in clean if (r["concentration_mM"], r["Pbar_C_m2"]) == (concentration, pbar)]
        phi, sigma, dsdphi, cap = capacitance_curve(
            [r["phi0_V"] for r in group], [r["sigma0_C_m2"] for r in group])
        branches.append({"concentration_mM": concentration, "Pbar_C_m2": pbar,
                         "points": [{"phi0_V": float(a), "sigma0_C_m2": float(b),
                                     "d_sigma_d_phi_F_m2": float(d), "C_F_m2": float(c)}
                                    for a, b, d, c in zip(phi, sigma, dsdphi, cap)]})
        phi_pzc = _linear_at_zero(sigma, phi)
        c_pzc = _linear_at_zero(sigma, cap)
        pzc.append({"concentration_mM": concentration, "Pbar_C_m2": pbar,
                    "phi_pzc_V": phi_pzc, "C_pzc_F_m2": c_pzc})
    pz_results = []
    if fit_concentrations_mM is not None:
        selected = [float(c) for c in fit_concentrations_mM]
        if len(set(selected)) != len(selected) or len(selected) < 3:
            raise ValueError("PZ fit needs at least three distinct concentrations")
        matched = []
        for c in selected:
            candidates = [r for r in pzc if np.isclose(r["concentration_mM"], c, rtol=0, atol=1e-10)]
            if len(candidates) != 1:
                raise ValueError(f"expected one Pbar branch at {c:g} mM, found {len(candidates)}")
            matched.append(candidates[0])
        pbar_values = [r["Pbar_C_m2"] for r in matched]
        if not np.allclose(pbar_values, pbar_values[0], rtol=0, atol=1e-12):
            raise ValueError("PZ points must use a common fixed Pbar")
        cgc_own = gc_capacitance(np.array(selected), temperature_K, eps_b, 0.0)
        cgc_model_pzc = gc_capacitance(np.array(selected), temperature_K, eps_b,
                                       np.array([r["phi_pzc_V"] for r in matched]))
        y = 1.0 / np.array([r["C_pzc_F_m2"] for r in matched])
        for label, x in (("gc_own_pzc_phi0_zero", 1.0 / cgc_own),
                         ("gc_at_model_phi_pzc", 1.0 / cgc_model_pzc)):
            slope, intercept = np.polyfit(x, y, 1)
            residual = y - (slope * x + intercept)
            pz_results.append({"reference_convention": label,
                               "concentration_mM": selected,
                               "slope": float(slope),
                               "intercept_m2_per_F": float(intercept),
                               "rms_residual_m2_per_F": float(np.sqrt(np.mean(residual**2))),
                               "C_pzc_F_m2": [float(r["C_pzc_F_m2"]) for r in matched],
                               "phi_pzc_V": [float(r["phi_pzc_V"]) for r in matched]})
    return {"temperature_K": float(temperature_K), "eps_b": float(eps_b),
            "branches": branches, "pzc": pzc, "parsons_zobel_diagnostics": pz_results,
            "method": {"capacitance": "absolute derivative |d sigma0/d phi0| at fixed concentration and Pbar",
                       "pzc": "sigma0=0 on each branch; interpolate only if the sweep brackets zero",
                       "pzc_GC_reference": "report both phi0=0 GC and Eq.35 GC evaluated at physical model phi_pzc",
                       "fit_mask": "caller-supplied concentration list; no paper-specific fit mask inferred"}}


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _finite_float(value, label):
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(out):
        raise ValueError(f"{label} must be finite")
    return out


def _fit_line(x, y):
    x, y = _array(x, "fit x"), _array(y, "fit y")
    if x.size != y.size or x.size < 3 or np.ptp(x) == 0:
        raise ValueError("OLS needs at least three paired points with varying x")
    design = np.column_stack((x, np.ones_like(x)))
    coefficients, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    if rank != 2 or not np.all(np.isfinite(coefficients)):
        raise ValueError("OLS design is singular or non-finite")
    slope, intercept = map(float, coefficients)
    residual = y - (slope * x + intercept)
    return {"slope": slope, "intercept_m2_per_F": intercept,
            "rms_residual_m2_per_F": float(np.sqrt(np.mean(residual**2)))}


def _quadratic_dphi_dsigma(sigma, phi, at):
    """Three-neighbour parametric derivative, robust through a turning point."""
    sigma = np.asarray(sigma, dtype=float)
    phi = np.asarray(phi, dtype=float)
    if sigma.ndim != 1 or phi.shape != sigma.shape or sigma.size < 3:
        raise ValueError("coarse branch needs at least three paired sigma/phi samples")
    order = np.argsort(sigma)
    sigma, phi = sigma[order], phi[order]
    if np.any(np.diff(sigma) <= 0):
        raise ValueError("coarse sigma coordinates must be distinct")
    index = int(np.argmin(np.abs(sigma - at)))
    start = min(max(index - 1, 0), sigma.size - 3)
    xs, ys = sigma[start:start + 3], phi[start:start + 3]
    if abs(float(sigma[index]) - at) > 1e-11:
        raise ValueError("coarse derivative query must be an included sigma grid point")
    scale = float(np.max(np.abs(xs - at)))
    u = (xs - at) / scale
    a, b, _ = np.polynomial.polynomial.polyfit(u, ys, 2)
    return float(b / scale)


def _five_point_dphi_dsigma(phi_at_minus_2h, phi_at_minus_h,
                            phi_at_plus_h, phi_at_plus_2h, h):
    h = _finite_float(h, "h")
    if h <= 0:
        raise ValueError("h must be positive")
    values = [_finite_float(v, "near-PZ potential") for v in
              (phi_at_minus_2h, phi_at_minus_h, phi_at_plus_h, phi_at_plus_2h)]
    return float((values[0] - 8*values[1] + 8*values[2] - values[3]) / (12*h))


def _expected_level_sigmas(manifest):
    levels = manifest.get("grid_levels")
    if not isinstance(levels, dict) or set(levels) != {
            "coarse_curve", "near_pzc_h", "near_pzc_h2", "near_pzc_h4"}:
        raise ValueError("manifest must define coarse_curve and all three near-PZ levels")
    out = {}
    for name, spec in levels.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("sigma0_C_m2"), list):
            raise ValueError(f"manifest grid level {name} is malformed")
        values = np.asarray([_finite_float(x, f"{name}.sigma0_C_m2")
                             for x in spec["sigma0_C_m2"]], dtype=float)
        if values.ndim != 1 or len(values) < 3 or len(np.unique(values)) != len(values):
            raise ValueError(f"manifest grid level {name} must contain >=3 unique points")
        if not np.any(np.isclose(values, 0.0, rtol=0, atol=1e-14)):
            raise ValueError(f"manifest grid level {name} must contain sigma0=0")
        if name != "coarse_curve" and (not np.any(values < 0) or not np.any(values > 0)):
            raise ValueError(f"near-PZ level {name} must bracket zero")
        out[name] = values
    for name in ("near_pzc_h", "near_pzc_h2", "near_pzc_h4"):
        spec = levels[name]
        h = _finite_float(spec.get("h_C_m2"), f"{name}.h_C_m2")
        values = np.sort(out[name])
        expected = np.array([-2*h, -h, 0.0, h, 2*h])
        if h <= 0 or values.shape != expected.shape or not np.allclose(values, expected, rtol=0, atol=1e-12):
            raise ValueError(f"{name} must provide the five-point -2h,-h,0,h,2h stencil")
    h = [manifest["grid_levels"][name]["h_C_m2"]
         for name in ("near_pzc_h", "near_pzc_h2", "near_pzc_h4")]
    if not (h[0] > h[1] > h[2] > 0 and np.allclose(np.array(h[1:]), np.array(h[:-1])/2, rtol=0, atol=1e-14)):
        raise ValueError("near-PZ steps must halve at each level")
    return out


def validate_dataset(rows, manifest):
    """Validate the public sweep contract without trusting candidate metadata."""
    if manifest.get("schema_version") != "006-author-sweeps/v1":
        raise ValueError("unsupported sweep manifest schema")
    params = manifest.get("parameters")
    if not isinstance(params, dict):
        raise ValueError("manifest parameters must be an object")
    temperature = _finite_float(params.get("temperature_K"), "temperature_K")
    alpha = _finite_float(params.get("alpha"), "alpha")
    a_nm = _finite_float(params.get("cell_length_nm"), "cell_length_nm")
    k11, k21 = (_finite_float(params.get(k), k) for k in ("K11", "K21"))
    if temperature <= 0 or a_nm <= 0 or not 0 <= alpha <= 1 or k11 <= 0 or k21 <= 0:
        raise ValueError("manifest has invalid physical constants")
    levels = _expected_level_sigmas(manifest)
    branches = manifest.get("branch_matrix")
    if not isinstance(branches, list) or not branches:
        raise ValueError("manifest branch_matrix must be a non-empty list")
    expected = {}
    for branch in branches:
        if not isinstance(branch, dict):
            raise ValueError("branch_matrix rows must be objects")
        bid = branch.get("branch_id")
        if not isinstance(bid, str) or not bid or bid in expected:
            raise ValueError("branch_id values must be unique non-empty strings")
        c = _finite_float(branch.get("concentration_mM"), "concentration_mM")
        pbar = _finite_float(branch.get("Pbar_C_m2"), "Pbar_C_m2")
        if c <= 0:
            raise ValueError("concentration_mM must be positive")
        expected[bid] = (c, pbar)
    required = {"branch_id", "concentration_mM", "Pbar_C_m2", "grid_level",
                "sigma0_C_m2", "phi0_V"}
    data = {bid: {level: [] for level in levels} for bid in expected}
    seen = set()
    for number, row in enumerate(rows, start=2):
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError(f"row {number} is missing required columns")
        bid, level = row["branch_id"], row["grid_level"]
        if bid not in expected or level not in levels:
            raise ValueError(f"row {number} uses unknown branch or grid_level")
        c = _finite_float(row["concentration_mM"], f"row {number} concentration")
        pbar = _finite_float(row["Pbar_C_m2"], f"row {number} Pbar")
        sigma = _finite_float(row["sigma0_C_m2"], f"row {number} sigma")
        phi = _finite_float(row["phi0_V"], f"row {number} phi")
        ec, ep = expected[bid]
        if not np.isclose(c, ec, rtol=0, atol=1e-12) or not np.isclose(pbar, ep, rtol=0, atol=1e-12):
            raise ValueError(f"row {number} parameter values disagree with branch_id")
        if not np.any(np.isclose(levels[level], sigma, rtol=0, atol=1e-12)):
            raise ValueError(f"row {number} sigma is not in the declared grid")
        key = (bid, level, sigma)
        if key in seen:
            raise ValueError(f"duplicate branch_id/grid_level/sigma row: {key}")
        seen.add(key)
        data[bid][level].append({"sigma0_C_m2": sigma, "phi0_V": phi})
    for bid, branch_data in data.items():
        for level, target in levels.items():
            got = sorted(r["sigma0_C_m2"] for r in branch_data[level])
            if len(got) != len(target) or not np.allclose(got, np.sort(target), rtol=0, atol=1e-12):
                raise ValueError(f"branch {bid} grid {level} is incomplete or has extra rows")
    fit = manifest.get("fit")
    if not isinstance(fit, dict) or fit.get("fit_method") != "ordinary_least_squares_unweighted":
        raise ValueError("manifest must define the unweighted OLS fit protocol")
    fit_cs = [_finite_float(x, "primary_fit_c_mM") for x in fit.get("primary_concentrations_mM", [])]
    if len(fit_cs) < 3 or len(set(fit_cs)) != len(fit_cs):
        raise ValueError("primary fit concentration set must have >=3 unique values")
    return data, expected, levels, fit_cs


def validate_refinement(rows, manifest, expected, levels):
    """Validate real BVP-derived local derivative stencils at every center."""
    protocol = manifest.get("analysis_protocol", {}).get("curve_refinement")
    if not isinstance(protocol, dict) or not isinstance(protocol.get("levels"), dict):
        raise ValueError("manifest must publish the physical-curve refinement protocol")
    level_specs = protocol["levels"]
    if set(level_specs) != {"curve_h", "curve_h2", "curve_h3"}:
        raise ValueError("curve refinement must contain curve_h, curve_h2, and curve_h3")
    coarse_centers = np.sort(levels["coarse_curve"])
    expected_h = {"curve_h": 5e-4, "curve_h2": 2.5e-4, "curve_h3": 1.25e-4}
    for level, h in expected_h.items():
        spec = level_specs[level]
        if not isinstance(spec, dict) or not np.isclose(
                _finite_float(spec.get("h_C_m2"), f"{level}.h_C_m2"), h,
                rtol=0, atol=1e-14):
            raise ValueError(f"{level} h_C_m2 does not match the public contract")
    required = {"branch_id", "concentration_mM", "Pbar_C_m2",
                "center_sigma0_C_m2", "derivative_level", "h_C_m2",
                "offset_multiple", "sigma0_C_m2", "phi0_V"}
    result = {bid: {lev: {} for lev in expected_h} for bid in expected}
    seen = set()
    for number, row in enumerate(rows, 2):
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError(f"refinement row {number} is missing required columns")
        bid, level = row["branch_id"], row["derivative_level"]
        if bid not in expected or level not in expected_h:
            raise ValueError(f"refinement row {number} uses an unknown branch or level")
        c = _finite_float(row["concentration_mM"], f"refinement row {number} concentration")
        pbar = _finite_float(row["Pbar_C_m2"], f"refinement row {number} Pbar")
        center = _finite_float(row["center_sigma0_C_m2"], f"refinement row {number} center")
        h = _finite_float(row["h_C_m2"], f"refinement row {number} h")
        try:
            offset = int(row["offset_multiple"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"refinement row {number} offset_multiple must be integer") from exc
        sigma = _finite_float(row["sigma0_C_m2"], f"refinement row {number} sigma")
        phi = _finite_float(row["phi0_V"], f"refinement row {number} phi")
        ec, ep = expected[bid]
        if not np.isclose(c, ec, rtol=0, atol=1e-12) or not np.isclose(pbar, ep, rtol=0, atol=1e-12):
            raise ValueError(f"refinement row {number} parameter values disagree with branch_id")
        if not np.any(np.isclose(coarse_centers, center, rtol=0, atol=1e-12)):
            raise ValueError(f"refinement row {number} center is not on coarse curve grid")
        if not np.isclose(h, expected_h[level], rtol=0, atol=1e-14) or offset not in {-2, -1, 0, 1, 2}:
            raise ValueError(f"refinement row {number} has an invalid h or offset")
        if not np.isclose(sigma, center + offset*h, rtol=0, atol=1e-12):
            raise ValueError(f"refinement row {number} sigma does not match center and offset")
        key = (bid, level, center, offset)
        if key in seen:
            raise ValueError(f"duplicate refinement branch/level/center/offset row: {key}")
        seen.add(key)
        result[bid][level].setdefault(center, {})[offset] = phi
    required_keys = {(bid, level, float(center), offset)
                     for bid in expected for level in expected_h
                     for center in coarse_centers for offset in (-2, -1, 0, 1, 2)}
    if seen != required_keys:
        raise ValueError(f"refinement grid is incomplete or has extra rows ({len(seen)} vs {len(required_keys)})")
    # Reused values must identify the same physical sigma and potential at
    # their overlapping coordinates: h -> h2 at +/-h2 and h2 -> h3 at +/-h3.
    for bid in expected:
        for center in coarse_centers:
            for fine, coarse, fine_offset, coarse_offset in (("curve_h2", "curve_h", 2, 1),
                                                               ("curve_h3", "curve_h2", 2, 1)):
                fine_h = expected_h[fine]; coarse_h = expected_h[coarse]
                for sign in (-1, 1):
                    a = result[bid][fine][float(center)][sign * fine_offset]
                    b = result[bid][coarse][float(center)][sign * coarse_offset]
                    if not np.isclose(center + sign*fine_h*fine_offset, center + sign*coarse_h*coarse_offset,
                                      rtol=0, atol=1e-12):
                        raise ValueError("refinement overlap coordinates do not coincide")
                    if not np.isclose(a, b, rtol=0, atol=1e-12):
                        raise ValueError(f"refinement overlap potential mismatch at {bid} sigma={center + sign*fine_h:g}")
    return result, expected_h, coarse_centers


def _branch_metrics(rows_by_level, temperature_K, eps_b):
    coarse = sorted(rows_by_level["coarse_curve"], key=lambda r: r["sigma0_C_m2"])
    sigma = np.array([r["sigma0_C_m2"] for r in coarse])
    phi = np.array([r["phi0_V"] for r in coarse])
    if np.any(np.diff(sigma) <= 0):
        raise ValueError("coarse sigma grid must strictly increase")
    curve = []
    dphi_dsigma_values = []
    for s, v in zip(sigma, phi):
        derivative = _quadratic_dphi_dsigma(sigma, phi, float(s))
        if derivative == 0 or not math.isfinite(derivative):
            raise ValueError("coarse curve has a singular or non-finite local derivative")
        signed = 1.0 / derivative
        dphi_dsigma_values.append(derivative)
        curve.append({"sigma0_C_m2": float(s), "phi0_V": float(v),
                      "d_sigma_d_phi_F_m2": float(signed),
                      "C_F_m2": float(abs(signed))})
    turns = []
    for i, (left, right) in enumerate(zip(dphi_dsigma_values, dphi_dsigma_values[1:])):
        if left * right < 0:
            turns.append({"bracket_sigma0_C_m2": [float(sigma[i]), float(sigma[i+1])],
                          "derivative_sign": [int(np.sign(left)), int(np.sign(right))],
            "interpretation": "coarse-grid diagnostic interval only; does not locate the refined physical fold or imply stability"})
    zero = np.flatnonzero(np.isclose(sigma, 0.0, rtol=0, atol=1e-14))
    if zero.size != 1:
        raise ValueError("coarse curve must contain exactly one sigma0=0 point")
    phi_pzc = float(phi[zero[0]])
    c_by_level = {}
    signed_c_by_level = {}
    derivative_by_level = {}
    for level, h_key in (("near_pzc_h", "h"), ("near_pzc_h2", "h2"), ("near_pzc_h4", "h4")):
        stencil = sorted(rows_by_level[level], key=lambda r: r["sigma0_C_m2"])
        h = float(abs(stencil[3]["sigma0_C_m2"]))
        values = {round(r["sigma0_C_m2"], 14): r["phi0_V"] for r in stencil}
        deriv = _five_point_dphi_dsigma(values[round(-2*h, 14)], values[round(-h, 14)],
                                        values[round(h, 14)], values[round(2*h, 14)], h)
        if deriv == 0 or not math.isfinite(deriv):
            raise ValueError(f"{level} PZ derivative is singular or non-finite")
        signed_c_by_level[h_key] = float(1.0 / deriv)
        derivative_by_level[h_key] = float(deriv)
        c_by_level[h_key] = float(abs(signed_c_by_level[h_key]))
    h, h2, h4 = (c_by_level[name] for name in ("h", "h2", "h4"))
    diffs = [abs(h2-h), abs(h4-h2)]
    rel = [d / max(abs(h4), np.finfo(float).tiny) for d in diffs]
    a, b = diffs
    observed_order = None if a <= 1e-14 or b <= 1e-14 or a/b <= 0 else float(np.log2(a/b))
    return {"coarse_curve": curve, "turning_intervals": turns,
            "pzc": {"phi_pzc_V": phi_pzc, "C_by_level_F_m2": c_by_level,
                    "signed_d_sigma_d_phi_by_level_F_m2": signed_c_by_level,
                    "d_phi_d_sigma_by_level_V_per_C_m2": derivative_by_level,
                    "sign_by_level": {k: int(np.sign(v)) for k, v in derivative_by_level.items()},
                    "signed_response_sign_consistent": len({int(np.sign(v)) for v in derivative_by_level.values()}) == 1,
                    "has_negative_response": any(v < 0 for v in signed_c_by_level.values()),
                    "pzc_response_diagnostic": "signed differential response is reported; its sign alone does not establish fixed-voltage thermodynamic stability",
                    "chosen_level": "h4", "C_pzc_F_m2": h4,
                    "absolute_differences_F_m2": diffs,
                    "relative_differences": rel,
                    "observed_order_or_null": observed_order}}


def _fit_pz(points):
    x = [p["x_m2_per_F"] for p in points]
    y = [p["y_m2_per_F"] for p in points]
    return _fit_line(x, y)


def analyze_dataset(rows, refinement_rows, manifest):
    data, expected, levels, fit_cs = validate_dataset(rows, manifest)
    refinement, refinement_h, coarse_centers = validate_refinement(
        refinement_rows, manifest, expected, levels)
    params = manifest["parameters"]
    temperature = float(params["temperature_K"])
    eps_b = 1.0 + 1.0/float(params["K11"]) + 1.0/float(params["K21"])
    by_branch = {}
    for bid, (c, pbar) in expected.items():
        metrics = _branch_metrics(data[bid], temperature, eps_b)
        coarse_by_sigma = {round(r["sigma0_C_m2"], 12): r
                           for r in metrics["coarse_curve"]}
        physical_curve = []
        for center in coarse_centers:
            curve_item = {"sigma0_C_m2": float(center),
                          "phi0_V": coarse_by_sigma[round(float(center), 12)]["phi0_V"]}
            for level in refinement_h:
                refined_center = refinement[bid][level][float(center)][0]
                if not np.isclose(refined_center, curve_item["phi0_V"], rtol=0, atol=1e-12):
                    raise ValueError(f"{bid} {level} center potential disagrees with coarse exact-sigma row")
            for level, h in refinement_h.items():
                stencil = refinement[bid][level][float(center)]
                derivative = _five_point_dphi_dsigma(
                    stencil[-2], stencil[-1], stencil[1], stencil[2], h)
                if derivative == 0 or not math.isfinite(derivative):
                    raise ValueError(f"{bid} {level} has singular/non-finite local capacitance")
                signed = 1.0 / derivative
                curve_item[f"d_sigma_d_phi_{level}_F_m2"] = float(signed)
                curve_item[f"C_{level}_F_m2"] = float(abs(signed))
            fine = curve_item["C_curve_h3_F_m2"]
            coarse_derivative = coarse_by_sigma[round(float(center), 12)]["d_sigma_d_phi_F_m2"]
            curve_item["coarse_diagnostic_C_F_m2"] = coarse_by_sigma[round(float(center), 12)]["C_F_m2"]
            curve_item["coarse_relative_bias_vs_curve_h3"] = float(
                (curve_item["coarse_diagnostic_C_F_m2"] - fine) / fine)
            curve_item["relative_change_h_to_h2"] = float(
                (curve_item["C_curve_h2_F_m2"] - curve_item["C_curve_h_F_m2"]) / fine)
            curve_item["relative_change_h2_to_h3"] = float(
                (curve_item["C_curve_h3_F_m2"] - curve_item["C_curve_h2_F_m2"]) / fine)
            for level in ("curve_h", "curve_h2", "curve_h3"):
                curve_item[f"d_phi_d_sigma_{level}_V_per_C_m2"] = float(
                    1.0 / curve_item[f"d_sigma_d_phi_{level}_F_m2"])
            d1 = curve_item["d_phi_d_sigma_curve_h_V_per_C_m2"]
            d2 = curve_item["d_phi_d_sigma_curve_h2_V_per_C_m2"]
            d3 = curve_item["d_phi_d_sigma_curve_h3_V_per_C_m2"]
            curve_item["abs_d_phi_change_h_to_h2_V_per_C_m2"] = float(abs(d2-d1))
            curve_item["abs_d_phi_change_h2_to_h3_V_per_C_m2"] = float(abs(d3-d2))
            curve_item["d_phi_sign_consistent"] = bool(np.sign(d1) == np.sign(d2) == np.sign(d3))
            if not math.isfinite(coarse_derivative):
                raise ValueError(f"{bid} coarse diagnostic derivative is non-finite")
            physical_curve.append(curve_item)
        max_d3 = max(abs(x["d_phi_d_sigma_curve_h3_V_per_C_m2"]) for x in physical_curve)
        for point in physical_curve:
            point["relative_derivative_scale_h3"] = abs(point["d_phi_d_sigma_curve_h3_V_per_C_m2"]) / max_d3
            rel_change = abs(point["relative_change_h2_to_h3"])
            d3 = point["d_phi_d_sigma_curve_h3_V_per_C_m2"]
            delta = 2.0 * point["abs_d_phi_change_h2_to_h3_V_per_C_m2"]
            lo, hi = d3-delta, d3+delta
            contains_zero = lo <= 0.0 <= hi
            point["estimated_delta_d_phi_V_per_C_m2"] = float(delta)
            point["d_phi_interval_h3_V_per_C_m2"] = [float(lo), float(hi)]
            point["d_phi_interval_contains_zero"] = bool(contains_zero)
            if contains_zero:
                point["C_magnitude_interval_F_m2"] = [float(1.0/max(abs(lo),abs(hi))), None]
            else:
                point["C_magnitude_interval_F_m2"] = [float(1.0/max(abs(lo),abs(hi))),
                                                        float(1.0/min(abs(lo),abs(hi)))]
            if not point["d_phi_sign_consistent"] or contains_zero:
                point["numerical_resolution"] = "unresolved"
            elif rel_change > 0.01:
                point["numerical_resolution"] = "ill_conditioned"
            else:
                point["numerical_resolution"] = "resolved"
        fine_turns = []
        coarse_fine_sign_conflicts = []
        for i, (left, right) in enumerate(zip(physical_curve, physical_curve[1:])):
            dleft = left["d_phi_d_sigma_curve_h3_V_per_C_m2"]
            dright = right["d_phi_d_sigma_curve_h3_V_per_C_m2"]
            sleft, sright = int(np.sign(dleft)), int(np.sign(dright))
            if sleft != sright:
                fine_turns.append({"bracket_sigma0_C_m2": [left["sigma0_C_m2"], right["sigma0_C_m2"]],
                                   "derivative_sign_h3": [sleft, sright],
                                   "endpoint_resolution": [left["numerical_resolution"], right["numerical_resolution"]],
                                   "interpretation": "refined-center sign-change bracket; not an interpolated fold location"})
            coarse_left = coarse_by_sigma[round(left["sigma0_C_m2"], 12)]["d_sigma_d_phi_F_m2"]
            coarse_right = coarse_by_sigma[round(right["sigma0_C_m2"], 12)]["d_sigma_d_phi_F_m2"]
            if int(np.sign(coarse_left)) != sleft or int(np.sign(coarse_right)) != sright:
                coarse_fine_sign_conflicts.append({"interval_sigma0_C_m2": [left["sigma0_C_m2"], right["sigma0_C_m2"]],
                                                   "coarse_derivative_sign": [int(np.sign(coarse_left)), int(np.sign(coarse_right))],
                                                   "h3_derivative_sign": [sleft, sright]})
        metrics["physical_capacitance_curve"] = physical_curve
        metrics["fine_center_turning_brackets_h3"] = fine_turns
        metrics["coarse_fine_sign_conflicts"] = coarse_fine_sign_conflicts
        zero_curve = [x for x in physical_curve if abs(x["sigma0_C_m2"]) <= 1e-14]
        if len(zero_curve) != 1:
            raise ValueError(f"{bid} physical curve must contain exactly one sigma0=0 center")
        pzc = metrics["pzc"]
        zero = zero_curve[0]
        pzc["C_by_level_F_m2"]["h8"] = zero["C_curve_h3_F_m2"]
        pzc["signed_d_sigma_d_phi_by_level_F_m2"]["h8"] = zero["d_sigma_d_phi_curve_h3_F_m2"]
        pzc["d_phi_d_sigma_by_level_V_per_C_m2"]["h8"] = zero["d_phi_d_sigma_curve_h3_V_per_C_m2"]
        pzc["sign_by_level"]["h8"] = int(np.sign(zero["d_phi_d_sigma_curve_h3_V_per_C_m2"]))
        pzc["signed_response_sign_consistent"] = len(set(pzc["sign_by_level"].values())) == 1
        pzc["has_negative_response"] = any(x < 0 for x in pzc["signed_d_sigma_d_phi_by_level_F_m2"].values())
        pzc["chosen_level"] = "h8"
        pzc["C_pzc_F_m2"] = pzc["C_by_level_F_m2"]["h8"]
        hs=("h","h2","h4","h8")
        ordered=[pzc["C_by_level_F_m2"][key] for key in hs]
        pzc["absolute_differences_F_m2"]=[abs(b-a) for a,b in zip(ordered,ordered[1:])]
        pzc["relative_differences"]=[x/ordered[-1] for x in pzc["absolute_differences_F_m2"]]
        a,b=pzc["absolute_differences_F_m2"][-2:]
        pzc["observed_order_or_null"]=(None if min(a,b)<=1e-14 else float(np.log2(a/b)))
        by_branch[bid] = {"branch_id": bid, "concentration_mM": c,
                          "Pbar_C_m2": pbar, **metrics}
    pz = []
    pbars = sorted({pbar for _, pbar in expected.values()})
    for pbar in pbars:
        points = []
        for c in fit_cs:
            matches = [b for b in by_branch.values()
                       if np.isclose(b["concentration_mM"], c, rtol=0, atol=1e-12)
                       and np.isclose(b["Pbar_C_m2"], pbar, rtol=0, atol=1e-12)]
            if len(matches) != 1:
                raise ValueError(f"PZ fit requires exactly one {c:g} mM branch at Pbar={pbar:g}")
            b = matches[0]
            C = b["pzc"]["C_pzc_F_m2"]
            phi0 = b["pzc"]["phi_pzc_V"]
            CD0 = float(gc_capacitance(c, temperature, eps_b, 0.0))
            CDphi = float(gc_capacitance(c, temperature, eps_b, phi0))
            points.append({"c_mM": c, "phi_pzc_V": phi0, "C_pzc_F_m2": C,
                           "signed_C_pzc_F_m2": b["pzc"]["signed_d_sigma_d_phi_by_level_F_m2"]["h8"],
                           "d_phi_d_sigma_pzc_V_per_C_m2": b["pzc"]["d_phi_d_sigma_by_level_V_per_C_m2"]["h8"],
                           "C_D_F_m2": CD0, "x_m2_per_F": 1.0/CD0,
                           "y_m2_per_F": 1.0/C, "C_D_at_model_pzc_F_m2": CDphi,
                           "x_at_model_pzc_m2_per_F": 1.0/CDphi})
        points.sort(key=lambda p: p["c_mM"])
        main_fit = _fit_pz(points)
        loo = []
        for omit in points:
            subset = [p for p in points if p is not omit]
            loo.append({"omitted_c_mM": omit["c_mM"], **_fit_pz(subset)})
        neighbor = []
        for concentrations in manifest["fit"].get("neighbor_windows", []):
            selected = [_finite_float(c, "neighbor window concentration") for c in concentrations]
            subset = [p for p in points if any(np.isclose(p["c_mM"], c, rtol=0, atol=1e-12) for c in selected)]
            if len(subset) != len(selected):
                raise ValueError("neighbor fit window has a missing or repeated concentration")
            neighbor.append({"concentrations_mM": selected, **_fit_pz(subset)})
        alternative_points = [{**p, "x_m2_per_F": p["x_at_model_pzc_m2_per_F"]}
                              for p in points]
        pz.append({"Pbar_C_m2": pbar,
                   "reference_convention": "gc_own_pzc_phi0_zero",
                   "points": points, "primary_fit": main_fit,
                   "leave_one_out": loo, "neighbor_windows": neighbor,
                   "alternative_gc_at_model_pzc": {
                       "reference_convention": "gc_at_model_phi_pzc",
                       "points": alternative_points,
                       "fit": _fit_pz(alternative_points)}})
    return {"schema_version": "006-analysis-output/v1",
            "dataset": manifest["dataset"],
            "source_dataset_schema": manifest["schema_version"],
            "temperature_K": temperature, "alpha": float(params["alpha"]),
            "cell_length_nm": float(params["cell_length_nm"]), "eps_b": eps_b,
            "branches": list(by_branch.values()), "parsons_zobel": pz,
            "resolution_summary": {
                "curve_point_count": sum(len(b["physical_capacitance_curve"]) for b in by_branch.values()),
                "resolved_count": sum(p["numerical_resolution"] == "resolved" for b in by_branch.values() for p in b["physical_capacitance_curve"]),
                "ill_conditioned_count": sum(p["numerical_resolution"] == "ill_conditioned" for b in by_branch.values() for p in b["physical_capacitance_curve"]),
                "unresolved_count": sum(p["numerical_resolution"] == "unresolved" for b in by_branch.values() for p in b["physical_capacitance_curve"]),
                "delta_d_estimate": "2*abs(d_phi_d_sigma_h3-d_phi_d_sigma_h2); heuristic grid-difference indicator, not a rigorous bound",
                "zero_containment_rule": "unresolved if the indicated d_phi/d_sigma interval includes zero or signs disagree across h levels",
                "capacitance_interval": "reciprocal magnitude interval; upper is null/unbounded if the indicated derivative interval contains zero",
                "resolved_threshold_relative_C_change_h2_to_h3": 0.01},
            "method": {"coarse_curve_derivative": "invert local three-point quadratic dphi0/dsigma0 at each sigma sample; retain signed and absolute d_sigma/d_phi, and do not sort through a turning point",
                       "pzc": "use the exact sigma0=0 row on each fixed-(concentration,Pbar) branch",
            "pzc_derivative": "five-point central dphi0/dsigma0 at h=.001,.0005,.00025,.000125 C/m^2; C0=1/abs(dphi0/dsigma0); h8=.000125 is the finest public estimate",
                       "primary_pz_axis": "x=1/C_GC at its own PZC phi0=0; y=1/C_model at sigma0=0; unweighted OLS at fixed Pbar",
                       "secondary_pz_axis": "diagnostic x=1/C_GC evaluated at the model's physical phi_pzc",
                       "paper_figure_slopes": "not score targets; no claim of paper-exact Figure 8 fitting"}}


def write_outputs(result, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "analysis.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    with (outdir / "capacitance_curves.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["branch_id", "concentration_mM", "Pbar_C_m2", "sigma0_C_m2", "phi0_V",
                  "d_sigma_d_phi_curve_h_F_m2", "C_curve_h_F_m2",
                  "d_sigma_d_phi_curve_h2_F_m2", "C_curve_h2_F_m2",
                  "d_sigma_d_phi_curve_h3_F_m2", "C_curve_h3_F_m2",
                  "d_phi_d_sigma_curve_h_V_per_C_m2", "d_phi_d_sigma_curve_h2_V_per_C_m2",
                  "d_phi_d_sigma_curve_h3_V_per_C_m2", "abs_d_phi_change_h_to_h2_V_per_C_m2",
                  "abs_d_phi_change_h2_to_h3_V_per_C_m2", "d_phi_sign_consistent",
                  "estimated_delta_d_phi_V_per_C_m2", "d_phi_interval_lower_h3_V_per_C_m2",
                  "d_phi_interval_upper_h3_V_per_C_m2", "d_phi_interval_contains_zero",
                  "C_interval_lower_F_m2", "C_interval_upper_F_m2",
                  "relative_derivative_scale_h3", "numerical_resolution",
                  "coarse_diagnostic_C_F_m2", "coarse_relative_bias_vs_curve_h3",
                  "relative_change_h_to_h2", "relative_change_h2_to_h3"]
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for branch in result["branches"]:
            for point in branch["physical_capacitance_curve"]:
                writer.writerow({"branch_id": branch["branch_id"],
                                 "concentration_mM": branch["concentration_mM"],
                                 "Pbar_C_m2": branch["Pbar_C_m2"],
                                 **{k: v for k, v in point.items() if k in fields[3:]},
                                 "d_phi_interval_lower_h3_V_per_C_m2": point["d_phi_interval_h3_V_per_C_m2"][0],
                                 "d_phi_interval_upper_h3_V_per_C_m2": point["d_phi_interval_h3_V_per_C_m2"][1],
                                 "C_interval_lower_F_m2": point["C_magnitude_interval_F_m2"][0],
                                 "C_interval_upper_F_m2": point["C_magnitude_interval_F_m2"][1]})
    with (outdir / "parsons_zobel.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["Pbar_C_m2", "reference_convention", "c_mM", "phi_pzc_V",
                  "C_pzc_F_m2", "signed_C_pzc_F_m2", "d_phi_d_sigma_pzc_V_per_C_m2",
                  "C_D_F_m2", "x_m2_per_F", "y_m2_per_F",
                  "C_D_at_model_pzc_F_m2", "x_at_model_pzc_m2_per_F",
                  "primary_slope", "primary_intercept_m2_per_F", "primary_rms_residual_m2_per_F"]
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for fit in result["parsons_zobel"]:
            for point in fit["points"]:
                writer.writerow({"Pbar_C_m2": fit["Pbar_C_m2"],
                                 "reference_convention": fit["reference_convention"], **point,
                                 "primary_slope": fit["primary_fit"]["slope"],
                                 "primary_intercept_m2_per_F": fit["primary_fit"]["intercept_m2_per_F"],
                                 "primary_rms_residual_m2_per_F": fit["primary_fit"]["rms_residual_m2_per_F"]})
    summary = {"status": "analysis_complete", "dataset": result["dataset"],
               "branch_count": len(result["branches"]), "PZ_fit_count": len(result["parsons_zobel"]),
               "source_dataset_schema": result["source_dataset_schema"]}
    (outdir / "solver.log").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def analyze_files(input_csv: Path, refinement_csv: Path, manifest_path: Path, outdir: Path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_sha = manifest.get("source_csv_sha256")
    actual_sha = hashlib.sha256(Path(input_csv).read_bytes()).hexdigest()
    refinement_sha = manifest.get("analysis_protocol", {}).get("curve_refinement", {}).get("source_csv_sha256")
    actual_refinement_sha = hashlib.sha256(Path(refinement_csv).read_bytes()).hexdigest()
    if not isinstance(expected_sha, str) or expected_sha != actual_sha:
        raise ValueError("input CSV SHA-256 does not match its manifest")
    if not isinstance(refinement_sha, str) or refinement_sha != actual_refinement_sha:
        raise ValueError("refinement CSV SHA-256 does not match its manifest")
    result = analyze_dataset(read_csv(input_csv), read_csv(refinement_csv), manifest)
    write_outputs(result, outdir)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=Path("/app/assets/reference_sweeps.csv"))
    ap.add_argument("--refinement", type=Path, default=Path("/app/assets/curve_refinement.csv"))
    ap.add_argument("--manifest", type=Path, default=Path("/app/assets/analysis_contract.json"))
    ap.add_argument("--out", type=Path, default=Path("final"))
    args = ap.parse_args()
    analyze_files(args.input, args.refinement, args.manifest, args.out)


if __name__ == "__main__":
    main()
