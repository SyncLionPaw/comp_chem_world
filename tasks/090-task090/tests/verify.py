#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Compute hydration pressure with the variational boundary and frozen roughness average.
"""Score case 003 from a workspace that contains final/."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import numpy as np
from scipy.integrate import simpson, solve_bvp

sys.path.insert(0, str(Path(__file__).resolve().parent / "_support"))
from force_model import lengths, sharp_grid, sharp_pressure_table, smeared_grid, sign_changes, period_from_extrema  # noqa: E402

SPOTS = (6.0, 8.0, 10.0, 14.0)
SHARP_RTOL = 0.08
SMEARED_SPOTS = (10.0, 14.0)
SMEARED_RTOL = 0.20
PUBLIC_CONSTANTS_SHA256 = "7d2208e38098ab1edad4806b85911d7fc72bbd06a02c8e45576e468faa6c86f3"


def fail(layer, message):
    print(f"FAIL {layer}: {message}")
    return 1


def read_curve(path):
    try:
        data = np.genfromtxt(path, delimiter=",", names=True)
    except (ValueError, IndexError) as exc:
        raise ValueError(f"{path.name} is not a readable CSV: {exc}") from exc
    if not {"L_A", "Pi_Pa"}.issubset(set(data.dtype.names or ())):
        raise ValueError(f"{path.name} needs columns L_A, Pi_Pa")
    if data.ndim != 1 or data.size < 2:
        raise ValueError(f"{path.name} needs multiple data rows")
    try:
        x = np.asarray(data["L_A"], dtype=float)
        y = np.asarray(data["Pi_Pa"], dtype=float)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{path.name} contains a non-numeric CSV value: {exc}") from exc
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError(f"{path.name} contains a non-finite value")
    return x, y


def close(got, ref, rtol, name):
    if not np.isfinite(got) or not np.isfinite(ref):
        return f"{name}: non-finite value (got {got!r}, reference {ref!r})"
    scale = max(abs(ref), 1.0)
    if abs(got - ref) > rtol * scale:
        return f"{name}: got {got:.6e}, reference {ref:.6e}, relative tolerance {rtol}"
    return None


def collocation_energy(L, constants, ngrid=2001):
    """Independent BVP solution of the coupled Euler-Lagrange equations."""
    k = constants["kernel"]
    boundary = constants["boundary"]
    p0 = float(boundary["P0_C_per_m2"])
    alpha = float(boundary["alpha"])
    left1, right1 = (1.0 - alpha) * p0, -(1.0 - alpha) * p0
    left2, right2 = alpha * p0, -alpha * p0

    def ode(_z, y):
        return np.vstack((
            y[1], y[2], y[3],
            (k["K12"] * y[2] - (1.0 + k["K11"]) * y[0] - y[4]) / k["K13"],
            y[5],
            ((1.0 + k["K21"]) * y[4] + y[0]) / k["K22"],
        ))

    def bc(ya, yb):
        return np.array((ya[0] - left1, yb[0] - right1, ya[2], yb[2],
                         ya[4] - left2, yb[4] - right2))

    z = np.linspace(0.0, L, max(40, int(40 * L) + 1))
    y = np.zeros((6, len(z)))
    y[0] = left1 + (right1 - left1) * z / L
    y[1] = (right1 - left1) / L
    y[4] = left2 + (right2 - left2) * z / L
    y[5] = (right2 - left2) / L
    result = solve_bvp(ode, bc, z, y, tol=2.0e-10, max_nodes=30000)
    if not result.success:
        raise RuntimeError(f"independent collocation failed at L={L}: {result.message}")
    zz = np.linspace(0.0, L, ngrid)
    p1, dp1, d2p1, _d3p1, p2, dp2 = result.sol(zz)
    energy = constants["energy"]
    density = (
        0.5 * (1.0 + k["K11"]) * p1**2
        + 0.5 * (1.0 + k["K21"]) * p2**2
        + p1 * p2
        + 0.5 * k["K12"] * dp1**2
        + 0.5 * k["K22"] * dp2**2
        + 0.5 * k["K13"] * d2p1**2
    )
    return float(simpson(density, x=zz))


def collocation_pressure(L, constants, h=1.0e-3):
    eps0 = float(constants["energy"]["eps0_F_per_m"])
    return -((collocation_energy(L + h, constants) - collocation_energy(L - h, constants))
             / (2.0 * h)) / eps0


def main(argv):
    workspace = Path(argv[1] if len(argv) > 1 else ".")
    final = workspace / "final"
    required = ["force_sharp.csv", "force_smeared.csv", "analysis.json", "solver.log"]
    for name in required:
        if not (final / name).is_file():
            return finish(fail("L1", f"missing final/{name}"))
    try:
        sharp_x, sharp_y = read_curve(final / "force_sharp.csv")
        smear_x, smear_y = read_curve(final / "force_smeared.csv")
        analysis = json.loads((final / "analysis.json").read_text(encoding="utf-8"))
        log = (final / "solver.log").read_text(encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return finish(fail("L1", str(exc)))
    if not isinstance(analysis, dict):
        return finish(fail("L1", "analysis.json must contain an object"))
    scalar_keys = ("lambda_d1_A", "lambda_o_A", "lambda_d2_A", "oscillation_period_A",
                   "sharp_sign_changes_4_20", "smeared_sign_changes_5_20",
                   "smeared_sign_changes_10_20", "film_floor_A", "task_two_sigma_A",
                   "internal_sharp_start_A")
    for key in scalar_keys:
        if key not in analysis:
            return finish(fail("L1", f"analysis.json missing required {key}"))
        value = analysis[key]
        try:
            numeric_value = float(value)
        except (OverflowError, TypeError, ValueError):
            numeric_value = float("nan")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(numeric_value):
            return finish(fail("L1", f"analysis.json {key} must be a finite numeric scalar"))
    if sharp_x[0] > 2.0 + 1e-8 or sharp_x[-1] < 20.0 - 1e-8 or np.max(np.diff(sharp_x)) > 0.08 + 1e-10:
        return finish(fail("L2", "sharp grid must cover [2,20] Angstrom with every step at most 0.08"))
    if smear_x[0] > 5.0 + 1e-8 or smear_x[-1] < 20.0 - 1e-8 or np.max(np.diff(smear_x)) > 0.11 + 1e-10:
        return finish(fail("L2", "smeared grid must cover [5,20] Angstrom with every step at most 0.11"))
    if (len(sharp_x) < 100 or len(smear_x) < 100
            or np.any(np.diff(sharp_x) <= 0.0) or np.any(np.diff(smear_x) <= 0.0)):
        return finish(fail("L2", "sharp and smeared grids must contain at least 100 strictly increasing samples"))
    constants_path = workspace / "assets" / "model_constants.json"
    if not constants_path.is_file():
        return finish(fail("L1", "public model_constants.json is missing from the evaluation workspace"))
    import hashlib
    if hashlib.sha256(constants_path.read_bytes()).hexdigest() != PUBLIC_CONSTANTS_SHA256:
        return finish(fail("L1", "public model_constants.json differs from the audited task input"))
    numeric_log = {}
    for key in ("max_boundary_residual", "pressure_step_relative_change_at_0.40A",
                "quadrature_relative_change_at_0.40A", "energy_reproducibility_residual_at_8A"):
        match = re.search(rf"^{re.escape(key)}\s+([-+0-9.eE]+)\s*$", log, re.MULTILINE)
        if match is None:
            return finish(fail("L2", f"solver.log is missing numeric {key}"))
        try:
            numeric_log[key] = float(match.group(1))
        except ValueError:
            return finish(fail("L2", f"solver.log {key} is not numeric"))
        if not np.isfinite(numeric_log[key]) or numeric_log[key] < 0.0:
            return finish(fail("L2", f"solver.log {key} must be finite and non-negative"))
    if numeric_log["max_boundary_residual"] > 1.0e-8:
        return finish(fail("L3", "reported boundary residual exceeds 1e-8"))
    for key in ("pressure_step_relative_change_at_0.40A", "quadrature_relative_change_at_0.40A"):
        if numeric_log[key] > 1.0e-5:
            return finish(fail("L3", f"reported short-film convergence {key} exceeds 1e-5"))
    try:
        public_constants = json.loads(constants_path.read_text(encoding="utf-8"))
        independent = [(L, collocation_pressure(L, public_constants))
                       for L in (2.0, 6.0, 8.0, 10.0, 14.0, 20.0)]
    except (OSError, ValueError, KeyError, RuntimeError, np.linalg.LinAlgError) as exc:
        return finish(fail("L3", f"independent collocation check failed: {exc}"))
    for L, ref in independent:
        got = float(np.interp(L, sharp_x, sharp_y))
        message = close(got, ref, SHARP_RTOL, f"independent collocation pressure at {L:g} A")
        if message:
            return finish(fail("L3", message))
    ref_L, ref_P = sharp_grid()
    table = sharp_pressure_table()
    if float(table[0][0]) > 0.40 + 1e-8:
        return finish(fail("L2", "internal sharp table does not reach the 0.40 Angstrom film floor"))
    if abs(float(analysis.get("film_floor_A", float("nan"))) - 0.40) > 1e-8:
        return finish(fail("L3", "film floor does not preserve the 0.40 Angstrom task convention"))
    if abs(float(analysis.get("task_two_sigma_A", float("nan"))) - 2.5) > 1e-8:
        return finish(fail("L3", "roughness width does not preserve 2 sigma = 2.5 Angstrom"))
    if abs(float(analysis.get("internal_sharp_start_A", float("nan"))) - 0.40) > 1e-8:
        return finish(fail("L3", "analysis does not report the internal 0.40 Angstrom table"))
    expected_sharp = np.interp(sharp_x, ref_L, ref_P)
    sharp_peak = max(float(np.max(np.abs(expected_sharp))), 1.0)
    sharp_error = np.abs(sharp_y - expected_sharp)
    if float(np.max(sharp_error)) / sharp_peak > 0.012:
        return finish(fail("L3", f"sharp full-curve max normalized error {np.max(sharp_error)/sharp_peak:.4g} exceeds 0.012"))
    sharp_signs = sign_changes(sharp_x, sharp_y, 4.0, 20.0)
    if sharp_signs < 6:
        return finish(fail("L3", f"sharp force has {sharp_signs} sign changes on [4, 20]; expected at least 6"))
    period = period_from_extrema(sharp_x, sharp_y)
    if period is None or abs(period - 2.10) > 0.30:
        return finish(fail("L3", f"sharp oscillation period {period} A is outside 2.10 ± 0.30"))
    for key, expected in (("oscillation_period_A", period),
                          ("sharp_sign_changes_4_20", sharp_signs),
                          ("smeared_sign_changes_5_20", sign_changes(smear_x, smear_y, 5.0, 20.0)),
                          ("smeared_sign_changes_10_20", sign_changes(smear_x, smear_y, 10.0, 20.0))):
        if abs(float(analysis[key]) - float(expected)) > 1e-8:
            return finish(fail("L3", f"analysis.json {key} does not match the delivered curve"))
    poles = lengths()
    for key, tol in (("lambda_d1_A", 0.08), ("lambda_o_A", 0.08), ("lambda_d2_A", 0.08)):
        if key not in analysis:
            return finish(fail("L1", f"analysis.json missing {key}"))
        try:
            value = float(analysis[key])
        except (TypeError, ValueError):
            return finish(fail("L1", f"analysis.json {key} must be numeric"))
        message = close(value, poles[key], tol / max(abs(poles[key]), 1e-6), key)
        if message:
            return finish(fail("L3", message))
    sm_L, sm_P = smeared_grid(table=table)
    expected_smear = np.interp(smear_x, sm_L, sm_P)
    smear_peak = max(float(np.max(np.abs(expected_smear))), 1.0)
    smear_error = np.abs(smear_y - expected_smear)
    if float(np.max(smear_error)) / smear_peak > 0.015:
        return finish(fail("L3", f"smeared full-curve max normalized error {np.max(smear_error)/smear_peak:.4g} exceeds 0.015"))
    smear_signs = sign_changes(smear_x, smear_y, 10.0, 20.0)
    if smear_signs != 0:
        return finish(fail("L3", f"smeared force has {smear_signs} sign changes on [10, 20]; expected 0"))
    print("PASS")
    print(json.dumps({
        "sharp_sign_changes_4_20": sharp_signs,
        "period_A": period,
        "smeared_sign_changes_10_20": smear_signs,
        "poles": poles,
    }, indent=2))
    return finish(0)


def finish(code):
    logs = os.environ.get("BENCH_LOGS")
    if logs:
        out = Path(logs)
        out.mkdir(parents=True, exist_ok=True)
        reward = 1 if code == 0 else 0
        (out / "reward.txt").write_text(f"{reward}\n", encoding="utf-8")
        (out / "verification.json").write_text(json.dumps({
            "status": "PASS" if code == 0 else "FAIL", "reward": reward
        }) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
