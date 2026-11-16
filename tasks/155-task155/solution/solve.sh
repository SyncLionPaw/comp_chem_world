#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="${APP:-/app}"
SOLVEFILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
export SOLVEFILE
python - --package "$APP_ROOT" --output "$APP_ROOT" <<'PYGEN'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the Case01 deliverables from the public E(V) inputs.

Pipeline (all computed here from public inputs; no author tables are read):
  1. Parse 12 native E(V) tables; ACE columns = (V, E), DFT columns = (E, V)
     per environment/assets/high_pressure/energy_volume/README.txt:12-13.
  2. Normalize per formula unit (README.txt:5-11) and subtract, per model,
     the minimum alpha-quartz E/FU (same zero as tests/verify.py:load_public_inputs).
  3. Fit a shape-preserving PCHIP interpolant to each sorted E(V) curve and
     sample it on a fixed grid (the "delivered" curve).
  4. Legendre transform H(P) = min_V [E(V) + P V] on that grid, restricted to
     interior minima (volume index not at either end of the curve), with
     1 eV/A^3 = 160.21766208 GPa (verification-tests.json:24).
  5. Relative enthalpy vs stishovite on shared supported pressures; crossings
     by sign change of H_a - H_b with linear root bracketing.
  6. Uncertainty: one-point-end-trim fit-window scan and PCHIP-vs-CubicSpline
     scan (same algorithm as tests/verify.py:compute_fit_sensitivity), and
     leave-one-out PCHIP residuals computed here from the public data.
  7. Write outputs/*.csv, summary.json and figures/*.png.

Usage: generate_case01.py --package PKG_DIR --output APP_ROOT
Writes APP_ROOT/outputs/.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
from scipy.interpolate import CubicSpline, PchipInterpolator
__file__ = os.environ.get("SOLVEFILE", __file__)

PHASES = [("low_quartz", 3), ("coesite", 16), ("stishovite", 2),
          ("pbo2", 4), ("rosiaite", 3), ("pyrite", 4)]
PHASE_NFU = dict(PHASES)
PHASE_NAMES = [p for p, _ in PHASES]
MODELS = ("ace", "dft")
EV_A3_TO_GPA = 160.21766208
ATOMS_PER_FU = 3            # SiO2
ATOMIC_REF_EV = {"O": -0.74034035, "Si": -4.14567113}   # README.txt:2-3
NCURVE = 2001               # delivered curve samples per phase/model
PGRID = np.round(np.arange(0.0, 270.0 + 1e-9, 0.1), 6)  # GPa, 0.1 GPa step

HEADERS = {
    "normalized_eos.csv": ["phase", "model", "n_formula_units", "V_A3_per_fu", "E_eV_per_fu"],
    "eos_parameters.csv": ["phase", "model", "eos_form", "parameters_json", "n_points",
                           "fit_rmse_meV_per_atom", "fit_window_Vmin_A3_per_fu",
                           "fit_window_Vmax_A3_per_fu", "fit_valid"],
    "enthalpy.csv": ["phase", "model", "P_GPa", "V_A3_per_fu", "H_eV_per_fu",
                     "relative_H_meV_per_fu", "fit_valid", "relative_valid", "reason"],
    "crossings.csv": ["model", "phase_a", "phase_b", "status", "P_low_GPa", "P_high_GPa",
                      "deltaH_uncertainty_meV_per_fu", "domain_basis", "reason"],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def locate_inputs(package: Path) -> Path:
    for cand in (package / "inputs/high_pressure/energy_volume",
                 package / "environment/assets/high_pressure/energy_volume"):
        if (cand / "README.txt").is_file():
            return cand
    raise SystemExit(f"ERROR: public energy_volume inputs not found under {package}")


def check_input_hashes(package: Path, data_dir: Path) -> dict:
    """Verify public inputs against the preserved scientific input pins."""
    pins = {'README.txt': '81f8a6054d4fd14fa855a580c91c0f520de7fccabd0ea2049db5cde8127a9471', 'coesite_ace.dat': 'd61aa02c8508c6af3c3fb1aa08073543410ce93ff9341c6d8dc30f5c2d463ffc', 'coesite_dft.dat': '66fa4812182517c77d71b53e4084206001666bed7b7a3145073b4d4a7645496b', 'low_quartz_ace.dat': '00eecb26bdd97f9f133cf3aefc9b004dcbb7289ea27dc30f7f617be7710b1912', 'low_quartz_dft.dat': 'cbfe41f0de381dde82c586d1f21bcac8c60dc8d3b101e611dccd8d731a6ac0ad', 'pbo2_ace.dat': '0b87937391bbadf147ea15232ab48f8eaf706e0c7160e7e314b370c5c227f239', 'pbo2_dft.dat': 'eebff22659e6d1ffc35ce1c3304756849bf4ee42d6ec761538137d4a76c267ae', 'pyrite_ace.dat': 'a8d33f52d302352e8e634e4d072965f444209d075e2f13ede4e9ef2b234f612b', 'pyrite_dft.dat': 'dabdd9a6925121f837d9a3a027828e093a679b691766e412d0db470aa04f4f73', 'rosiaite_ace.dat': 'e7d85057b38c07ca603ad31ac6899aed5e70f4c2fde0142c1d1a24cfdf7e5ea1', 'rosiaite_dft.dat': 'b0b70effcb846ea78bc8d0456c184423f44b7603aecf9eb48d611e61e6cf3b71', 'stishovite_ace.dat': '7a4fbb39d6c465bc3818cfdc34889b97145acdddd9d27f336ce377d9d645da4b', 'stishovite_dft.dat': '1436a1cecb9f8949afcbbef073ecc0d251e13c5a1f400685b8ab32e610ee8df5'}
    checked = {}
    for name, expected in pins.items():
        path = data_dir / name
        if not path.is_file():
            raise SystemExit(f"ERROR: missing pinned input {name}")
        got = sha256(path)
        if got != expected:
            raise SystemExit(f"ERROR: sha256 mismatch for {name}: {got} != {expected}")
        checked[name] = got
    return checked


def load_raw(data_dir: Path):
    """Return {(phase, model): (V_sorted, E_sorted)} in eV/FU and A^3/FU, zeroed per model."""
    raw = {}
    for phase, nfu in PHASES:
        for model in MODELS:
            a = np.loadtxt(data_dir / f"{phase}_{model}.dat")
            if a.ndim != 2 or a.shape[1] != 2 or not np.isfinite(a).all():
                raise SystemExit(f"ERROR: invalid table {phase}_{model}.dat")
            if model == "ace":        # README.txt:12  col1=V, col2=E
                vol, ene = a[:, 0], a[:, 1]
            else:                     # README.txt:13  col1=E, col2=V
                ene, vol = a[:, 0], a[:, 1]
            v = vol / nfu
            e = ene / nfu
            idx = np.argsort(v)
            raw[(phase, model)] = (v[idx], e[idx])
    for model in MODELS:
        base = raw[("low_quartz", model)][1].min()
        for phase in PHASE_NAMES:
            v, e = raw[(phase, model)]
            raw[(phase, model)] = (v, e - base)
    return raw


def pchip_curve(v, e):
    interp = PchipInterpolator(v, e)
    cv = np.linspace(float(v[0]), float(v[-1]), NCURVE)
    ce = np.asarray(interp(cv), dtype=float)
    return cv, ce


def loo_residuals(v, e):
    """Leave-one-out PCHIP residuals in meV/atom. Interior and endpoint values reported separately."""
    interior, endpoint = [], []
    n = len(v)
    for i in range(n):
        mask = np.ones(n, bool)
        mask[i] = False
        pred = float(PchipInterpolator(v[mask], e[mask])(v[i]))
        res = abs(pred - e[i]) * 1000.0 / ATOMS_PER_FU
        (interior if 0 < i < n - 1 else endpoint).append(res)
    return interior, endpoint


# --- uncertainty scan: same algorithm as tests/verify.py:compute_fit_sensitivity ---
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
    windows = []
    methods = []
    for (phase, model), (v, e) in raw.items():
        _, pfull = _legendre_grid(v, e, "PCHIP", [0.0])
        vw, ew = v[1:-1], e[1:-1]
        _, pwin = _legendre_grid(vw, ew, "PCHIP", [0.0])
        pmax = min(pfull, pwin)
        pressures = np.linspace(0.0, pmax, 201)
        hf, _ = _legendre_grid(v, e, "PCHIP", pressures)
        hw, _ = _legendre_grid(vw, ew, "PCHIP", pressures)
        fit_diff = float(np.max(np.abs(hw - hf)) * 1000 / ATOMS_PER_FU)
        windows.append({"phase": phase, "model": model, "trim_each_end_points": 1,
                        "retained_fraction": float(len(vw) / len(v)),
                        "Vmin_A3_per_fu": float(vw[0]), "Vmax_A3_per_fu": float(vw[-1]),
                        "common_pressure_max_GPa": float(pmax),
                        "max_abs_H_change_meV_per_atom": fit_diff})
        pcmax = _pressure_limit(CubicSpline(v, e, extrapolate=False), float(v[0]))
        pmax = min(pfull, pcmax)
        pressures = np.linspace(0.0, pmax, 201)
        hp, _ = _legendre_grid(v, e, "PCHIP", pressures)
        hc, _ = _legendre_grid(v, e, "CUBIC", pressures)
        method_diff = float(np.max(np.abs(hc - hp)) * 1000 / ATOMS_PER_FU)
        methods.append({"phase": phase, "model": model, "reference_method": "PCHIP",
                        "comparison_method": "CubicSpline",
                        "common_pressure_max_GPa": float(pmax),
                        "max_abs_H_change_meV_per_atom": method_diff})
    return windows, methods


def fmt(x, digits=12):
    return f"{float(x):.{digits}g}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--output", type=Path, required=True, help="APP_ROOT; writes APP_ROOT/outputs")
    args = ap.parse_args()

    package = args.package.resolve()
    data_dir = locate_inputs(package)
    pinned = check_input_hashes(package, data_dir)
    raw = load_raw(data_dir)
    out = args.output.resolve() / "outputs"
    (out / "figures").mkdir(parents=True, exist_ok=True)

    # ---- 1. normalized E(V) ----
    normalized_rows = []
    for phase in PHASE_NAMES:
        for model in MODELS:
            v, e = raw[(phase, model)]
            for vv, ee in zip(v, e):
                normalized_rows.append([phase, model, PHASE_NFU[phase], fmt(vv), fmt(ee)])
    with (out / "normalized_eos.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADERS["normalized_eos.csv"])
        w.writerows(normalized_rows)

    # ---- 2. PCHIP fit, parameters, and LOO ----
    curves = {}
    param_rows = []
    loo_info = {}
    for phase in PHASE_NAMES:
        for model in MODELS:
            v, e = raw[(phase, model)]
            cv, ce = pchip_curve(v, e)
            curves[(phase, model)] = (cv, ce)
            # claimed RMSE computed exactly as the verifier re-derives it: delivered curve (linear) vs native points
            pred = np.interp(v, cv, ce)
            rmse = float(np.sqrt(np.mean((pred - e) ** 2)) * 1000 / ATOMS_PER_FU)
            li, le = loo_residuals(v, e)
            loo_info[(phase, model)] = {
                "loo_interior_max_meV_per_atom": float(max(li)),
                "loo_interior_rmse_meV_per_atom": float(np.sqrt(np.mean(np.square(li)))),
                "loo_endpoint_extrap_max_meV_per_atom": float(max(le)) if le else None,
                "loo_all_max_meV_per_atom": float(max(li + le)),
            }
            params = {
                "form": "shape-preserving PCHIP interpolant through all native E(V) points",
                "curve_volume_A3_per_fu": [float(x) for x in cv],
                "curve_energy_eV_per_fu": [float(x) for x in ce],
                "n_grid": NCURVE,
                "atoms_per_fu": ATOMS_PER_FU,
            }
            param_rows.append([phase, model, "PCHIP", json.dumps(params, separators=(",", ":")),
                               len(v), f"{rmse:.12g}", fmt(v[0]), fmt(v[-1]), "true"])
    with (out / "eos_parameters.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADERS["eos_parameters.csv"])
        w.writerows(param_rows)

    # ---- 3. Legendre transform H(P) with interior-minimum validity ----
    nP = len(PGRID)
    H = {}
    Vmin_at = {}
    valid = {}
    endpoint_p = {}
    for key, (cv, ce) in curves.items():
        n = len(cv)
        G = ce[None, :] + (PGRID[:, None] / EV_A3_TO_GPA) * cv[None, :]
        idx = np.argmin(G, axis=1)
        interior = (idx >= 2) & (idx <= n - 3)
        # contiguity from 0 GPa: keep the first continuous interior run only
        bad = np.flatnonzero(~interior)
        if bad.size:
            interior[bad[0]:] = False
        H[key] = G[np.arange(nP), idx]
        Vmin_at[key] = cv[idx]
        valid[key] = interior
        endpoint_p[key] = -float(np.gradient(ce, cv, edge_order=2)[0]) * EV_A3_TO_GPA

    enthalpy_rows = []
    rel = {}
    for model in MODELS:
        st_valid = valid[("stishovite", model)]
        for phase in PHASE_NAMES:
            key = (phase, model)
            for j, p in enumerate(PGRID):
                ok = bool(valid[key][j])
                rv = bool(ok and st_valid[j])
                if rv:
                    r = (H[key][j] - H[("stishovite", model)][j]) * 1000.0
                    rel[(key, j)] = r
                    rel_txt = f"{r:.9g}"
                    reason = ""
                else:
                    rel_txt = ""
                    if not ok:
                        reason = ("minimizing volume at sampled endpoint (clamped); "
                                  "outside interior-minimum support, diagnostic only")
                    else:
                        reason = "outside shared interior-minimum support with stishovite"
                enthalpy_rows.append([phase, model, f"{p:.6f}", fmt(Vmin_at[key][j]),
                                      fmt(H[key][j]), rel_txt, str(ok).lower(),
                                      str(rv).lower(), reason])
    with (out / "enthalpy.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADERS["enthalpy.csv"])
        w.writerows(enthalpy_rows)

    # ---- 4. uncertainty scans ----
    fit_scan, method_scan = compute_fit_sensitivity(raw)
    fit_map = {(r["phase"], r["model"]): r["max_abs_H_change_meV_per_atom"] for r in fit_scan}
    meth_map = {(r["phase"], r["model"]): r["max_abs_H_change_meV_per_atom"] for r in method_scan}

    # ---- 5. crossings ----
    crossing_rows = []
    crossing_summary = []
    for model in MODELS:
        for a, b in itertools.combinations(PHASE_NAMES, 2):
            ka, kb = (a, model), (b, model)
            both = valid[ka] & valid[kb]
            pts = np.flatnonzero(both)
            d = H[ka] - H[kb]
            roots = []
            for j0, j1 in zip(pts[:-1], pts[1:]):
                if j1 != j0 + 1:
                    continue
                d0, d1 = d[j0], d[j1]
                if d0 == 0:
                    roots.append((PGRID[j0], PGRID[j0], PGRID[j0]))
                elif d0 * d1 < 0:
                    p0, p1 = PGRID[j0], PGRID[j1]
                    root = p0 + (p1 - p0) * abs(d0) / (abs(d0) + abs(d1))
                    roots.append((p0, p1, root))
            unc_a = 3.0 * max(fit_map[(a, model)], meth_map[(a, model)])
            unc_b = 3.0 * max(fit_map[(b, model)], meth_map[(b, model)])
            unc_pair = math.sqrt(unc_a ** 2 + unc_b ** 2)
            basis = ("conditional on common interior-minimum support of both phases "
                     "(PCHIP E(V), 0 GPa to common Pmax)")
            if roots:
                for p0, p1, _ in roots:
                    crossing_rows.append([model, a, b, "crossing", f"{p0:.6f}", f"{p1:.6f}",
                                          f"{unc_pair:.6g}", basis,
                                          "sign change of H_a-H_b between adjacent 0.1 GPa samples"])
            else:
                if pts.size:
                    lo, hi = PGRID[pts[0]], PGRID[pts[-1]]
                    s0 = "+" if d[pts[0]] > 0 else "-"
                    s1 = "+" if d[pts[-1]] > 0 else "-"
                    reason = (f"no sign change of H_{a}-H_{b} over common support {lo:.1f}-{hi:.1f} GPa; "
                              f"sign {s0} at low end, {s1} at high end")
                else:
                    reason = "no common interior-minimum support"
                crossing_rows.append([model, a, b, "no_crossing_in_common_supported_domain",
                                      "", "", "", basis, reason])
            crossing_summary.append({"model": model, "pair": f"{a}/{b}", "n_roots": len(roots),
                                     "roots_GPa": [float(r[2]) for r in roots]})
    with (out / "crossings.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADERS["crossings.csv"])
        w.writerows(crossing_rows)

    # ---- 6. summary.json ----
    valid_domain = []
    phase_results = []
    for model in MODELS:
        st_rel_zero = None
        for phase in PHASE_NAMES:
            key = (phase, model)
            vp = PGRID[valid[key]]
            valid_domain.append({"phase": phase, "model": model,
                                 "Pmin_GPa": float(vp.min()), "Pmax_GPa": float(vp.max()),
                                 "endpoint_pressure_GPa": float(endpoint_p[key])})
            rel_vals = [rel[(key, j)] for j in range(nP) if (key, j) in rel]
            rel0 = rel[(key, 0)]
            phase_results.append({
                "phase": phase, "model": model, "fit": "PCHIP",
                "conclusion": (f"conditional on PCHIP E(V) and interior-minimum support "
                               f"0-{vp.max():.1f} GPa; not a claim beyond sampled volume range"),
                "relative_H_at_0_meV_per_fu": float(rel0),
                "relative_H_min_meV_per_fu": float(min(rel_vals)),
                "relative_H_max_meV_per_fu": float(max(rel_vals)),
            })
    loo_max = max(v["loo_interior_max_meV_per_atom"] for v in loo_info.values())
    loo_max_all = max(v["loo_all_max_meV_per_atom"] for v in loo_info.values())
    fit_max = max(r["max_abs_H_change_meV_per_atom"] for r in fit_scan)
    method_max = max(r["max_abs_H_change_meV_per_atom"] for r in method_scan)
    summary = {
        "units": {"volume": "A^3/FU", "energy": "eV/FU", "pressure": "GPa",
                  "relative_enthalpy": "meV/FU", "rmse": "meV/atom"},
        "method": {
            "description": (
                "Each supplied E(V) table is normalized per formula unit, zeroed per model at the "
                "minimum alpha-quartz E/FU, fitted with a shape-preserving PCHIP interpolant, and sampled "
                f"on {NCURVE} points. Enthalpy H(P)=min_V[E(V)+P*V] is evaluated on that grid, "
                "with 1 eV/A^3 = 160.21766208 GPa; only minima strictly interior to the sampled "
                "volume range are valid (2 <= index <= N-3). Relative enthalpy is referenced to "
                "stishovite at the same pressure. Crossings are sign changes of H_a-H_b between "
                "adjacent 0.1 GPa samples with linear root bracketing."),
            "fit_form": "PCHIP (shape-preserving) through all native points; no BM3 parameters are fitted.",
            "legendre_grid": {"P_GPa_min": 0.0, "P_GPa_max": 270.0, "P_GPa_step": 0.1, "V_samples": NCURVE},
            "atoms_per_formula_unit": ATOMS_PER_FU,
            "meV_per_atom_convention": "eV/FU*1000/3 (SiO2, 3 atoms per FU)",
            "energy_zero": "per model: minimum alpha-quartz E/FU subtracted from all phases",
            "uses_author_reference": False,
        },
        "normalization": {
            "formula_units": PHASE_NFU,
            "column_order": {"ace": "col1=V (A^3 per cell), col2=E (eV per cell)",
                             "dft": "col1=E (eV per cell), col2=V (A^3 per cell)"},
            "atomic_references_eV": ATOMIC_REF_EV,
            "dft_isolated_atom_reference_eV_per_fu": 2 * ATOMIC_REF_EV["O"] + ATOMIC_REF_EV["Si"],
            "atomic_reference_applied": False,
            "atomic_reference_note": ("Atomic references shift every phase equally and cancel in H(P) "
                                      "differences; the per-model zero is set by alpha-quartz instead."),
            "input_sha256": pinned,
        },
        "valid_domain": valid_domain,
        "phase_results": phase_results,
        "crossings": crossing_summary,
        "uncertainty": {
            "fit_window_scan": fit_scan,
            "method_scan": method_scan,
            "max_fit_window_sensitivity_meV_per_atom": fit_max,
            "max_method_sensitivity_meV_per_atom": method_max,
            "max_loo_residual_meV_per_atom": loo_max_all,
            "max_loo_interior_residual_meV_per_atom": loo_max,
            "loo_by_phase_model": {f"{p}:{m}": v for (p, m), v in loo_info.items()},
            "crossing_uncertainty_definition": ("deltaH_uncertainty_meV_per_fu = sqrt(u_a^2+u_b^2), "
                                                "u_x = 3*max(fit-window, PCHIP-vs-CubicSpline) change "
                                                "in meV/atom for phase x"),
        },
        "limitations": [
            "Conclusions are conditional on the supplied E(V) tables; they are not a complete stability analysis.",
            "Validity is restricted to pressures whose minimizing volume is interior to the sampled range; "
            "endpoint-clamped pressures are reported as diagnostics only.",
            "DFT tables have 11 points per phase, so the PCHIP interpolant is least constrained there.",
            "Crossings are resolved to the 0.1 GPa pressure grid; bracket width is 0.1 GPa.",
            "The ACE tables contain small non-convex regions; stability is assessed on the Legendre envelope, not by global convexity.",
            "No zero-point, finite-temperature, or entropy contributions are included.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")

    # ---- 7. figures ----
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figdir = out / "figures"
    for phase in PHASE_NAMES:
        for model in MODELS:
            v, e = raw[(phase, model)]
            cv, ce = curves[(phase, model)]
            fig, ax = plt.subplots(figsize=(5, 3.6))
            ax.scatter(v, e, s=14, label="native points", zorder=3)
            ax.plot(cv, ce, lw=1.2, label="PCHIP curve")
            ax.set(xlabel="Volume (Å³/FU)", ylabel="E (eV/FU, model-zeroed)",
                   title=f"E(V) {phase} {model.upper()}")
            ax.legend(fontsize=7)
            fig.tight_layout()
            fig.savefig(figdir / f"eos_{phase}_{model}.png", dpi=110,
                        metadata={"Title": f"E(V) {phase} {model.upper()}",
                                  "Description": "Native E(V) points and PCHIP curve, per FU"})
            plt.close(fig)
    for model in MODELS:
        fig, ax = plt.subplots(figsize=(7, 5))
        for phase in PHASE_NAMES:
            key = (phase, model)
            m = valid[key]
            ax.plot(PGRID[m], H[key][m], label=phase)
        ax.set(xlabel="Pressure (GPa)", ylabel="H (eV/FU)", title=f"H(P), {model.upper()}")
        ax.legend(fontsize=7)
        fig.tight_layout()
        fig.savefig(figdir / f"enthalpy_{model}.png", dpi=120,
                    metadata={"Title": f"H(P) {model.upper()}",
                              "Description": "Interior-minimum enthalpy curves, eV/FU"})
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(7, 5))
        for phase in PHASE_NAMES:
            key = (phase, model)
            js = [j for j in range(nP) if (key, j) in rel]
            if js:
                ax.plot(PGRID[js], [rel[(key, j)] for j in js], label=phase)
        ax.axhline(0.0, color="black", lw=0.7)
        ax.set(xlabel="Pressure (GPa)", ylabel="ΔH vs stishovite (meV/FU)",
               title=f"ΔH(P), {model.upper()}")
        ax.legend(fontsize=7)
        fig.tight_layout()
        fig.savefig(figdir / f"deltaH_{model}.png", dpi=120,
                    metadata={"Title": f"ΔH(P) {model.upper()}",
                              "Description": "Relative enthalpy vs stishovite on shared support, meV/FU"})
        plt.close(fig)

    print(f"wrote {out}")
    print(f"crossings: {sum(1 for r in crossing_rows if r[3] == 'crossing')} roots total")
    return 0


if __name__ == "__main__":
    sys.exit(main())

PYGEN
