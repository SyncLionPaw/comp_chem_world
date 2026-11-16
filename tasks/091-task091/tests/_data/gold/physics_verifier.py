"""Independent diagnostics for public-grid Poisson--Fermi profiles.

The verifier derives closure, boundary data, charge integration and PDE
residuals from the submitted fields. Finite-difference limits are calibrated
against the declared 0.05-A public sampling and must be interpreted together
with the full-grid private reference comparison in ``tests/verify.py``.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

QE = 1.602176634e-19
KB = 1.380649e-23
EPS0 = 8.8541878128e-12
NA = 6.02214076e23

REQUIRED = ("z_A", "phi_V", "P1_C_m2", "P2_C_m2",
            "n_plus_m3", "n_minus_m3")
DEFAULT_K = {"K11": 0.140125, "K12": -0.207118,
             "K13": 0.011290, "K21": 0.015908, "K22": 2.003940}


def read_profile(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or any(name not in rows[0] for name in REQUIRED):
        raise ValueError("profile is empty or lacks required columns")
    arrays = {name: np.asarray([float(row[name]) for row in rows]) for name in REQUIRED}
    if any(not np.all(np.isfinite(value)) for value in arrays.values()):
        raise ValueError("profile contains non-finite values")
    if np.any(np.diff(arrays["z_A"]) <= 0):
        raise ValueError("z_A must be strictly increasing")
    return arrays


def _wall_derivative(values, z_A, order):
    # Fit a local polynomial in scaled coordinates for stable wall derivatives
    # on either uniform or adaptive meshes.
    count = min(11, len(z_A))
    x = (z_A[:count] - z_A[0]) / max(z_A[count - 1] - z_A[0], 1e-12)
    degree = min(6, count - 1)
    coeff = np.polynomial.polynomial.polyfit(x, values[:count], degree)
    scale_m = (z_A[count - 1] - z_A[0]) * 1.0e-10
    return float(np.polynomial.polynomial.polyder(coeff, m=order)[0] / scale_m**order)


def _far_derivative(values, z_A, order):
    rev_z = np.asarray(z_A)[-1] - np.asarray(z_A)[::-1]
    return _wall_derivative(np.asarray(values)[::-1], rev_z, order) * (-1)**order


def verify_profile(profile, parameters):
    """Return an auditable report; thresholds are numerical, not paper fits."""
    f = {name: np.asarray(profile[name], dtype=float) for name in REQUIRED}
    z = f["z_A"]
    if z.ndim != 1 or len(z) < 21 or any(a.shape != z.shape for a in f.values()):
        raise ValueError("profile columns must be equal-length 1-D arrays with >=21 rows")
    if any(np.any(~np.isfinite(a)) for a in f.values()) or np.any(np.diff(z) <= 0):
        raise ValueError("profile contains non-finite values or non-increasing coordinates")
    p = parameters
    if not np.isclose(z[0], 0.0, rtol=0.0, atol=1e-10):
        raise ValueError("z_A must start at the physical wall z=0")
    scalar_keys = ("concentration_mM", "cell_length_nm", "temperature_K",
                   "alpha", "Pbar_C_m2", "sigma0_C_m2")
    if any(key not in p or not np.isfinite(float(p[key])) for key in scalar_keys):
        raise ValueError("all physical parameters must be present and finite")
    if (float(p["concentration_mM"]) <= 0 or float(p["cell_length_nm"]) <= 0
            or float(p["temperature_K"]) <= 0 or not 0 <= float(p["alpha"]) <= 1):
        raise ValueError("concentration, cell length and temperature must be positive; alpha must be in [0,1]")
    k = {name: float(p.get(name, value)) for name, value in DEFAULT_K.items()}
    if any(not np.isfinite(value) for value in k.values()) or any(
            k[name] <= 0 for name in ("K11", "K13", "K21", "K22")):
        raise ValueError("kernel parameters must be finite and stable")
    c_mol_m3 = float(p["concentration_mM"])
    nb = c_mol_m3 * NA
    a_m = float(p["cell_length_nm"]) * 1e-9
    if 2.0 * nb * a_m**3 >= 1.0:
        raise ValueError("bulk lattice occupancy 2*n_b*a^3 must be below one")
    temp = float(p["temperature_K"])
    psi = QE * f["phi_V"] / (KB * temp)
    if np.any(np.abs(psi) > 80.0):
        raise ValueError("dimensionless potential outside supported range |Psi|<=80")
    denom = 1.0 + 2.0 * nb * a_m**3 * (np.cosh(psi) - 1.0)
    expected_plus = nb * np.exp(-psi) / denom
    expected_minus = nb * np.exp(psi) / denom
    closure_err = max(float(np.max(np.abs(f["n_plus_m3"] - expected_plus) /
                                   np.maximum(expected_plus, nb * 1e-12))),
                      float(np.max(np.abs(f["n_minus_m3"] - expected_minus) /
                                   np.maximum(expected_minus, nb * 1e-12))))
    occupancy = a_m**3 * (f["n_plus_m3"] + f["n_minus_m3"])
    alpha, pbar = float(p["alpha"]), float(p["Pbar_C_m2"])
    p1_target, p2_target = (1.0 - alpha) * pbar, alpha * pbar
    wall_p1_rel = abs(f["P1_C_m2"][0] - p1_target) / max(abs(pbar), 0.1)
    wall_p2_rel = abs(f["P2_C_m2"][0] - p2_target) / max(abs(pbar), 0.1)
    phi_prime = _wall_derivative(f["phi_V"], z, 1)
    p1_second = _wall_derivative(f["P1_C_m2"], z, 2)
    wall_disp = EPS0 * phi_prime
    expected_disp = pbar - float(p["sigma0_C_m2"])
    disp_err = abs(wall_disp - expected_disp) / max(abs(expected_disp), 0.1)
    nat_err = abs(p1_second) / max(abs(pbar), 0.1) * 1e-20
    charge = QE * (f["n_plus_m3"] - f["n_minus_m3"])
    trapz = getattr(np, "trapezoid", np.trapz)
    integrated = float(trapz(charge, z * 1e-10))
    sigma = float(p["sigma0_C_m2"])
    neutrality_rel = abs(sigma + integrated) / max(abs(sigma), 0.1)
    eps_bulk = 1.0 + 1.0 / k["K11"] + 1.0 / k["K21"]
    kappa = np.sqrt(2 * QE**2 * nb / (EPS0 * eps_bulk * KB * temp))
    lambda_gc_A = 1e10 / kappa
    if z[-1] < 8.0 * lambda_gc_A:
        raise ValueError("profile domain must extend at least eight GC screening lengths")
    dx = np.diff(z)
    if not np.allclose(dx, dx[0], rtol=1e-6, atol=1e-12):
        raise ValueError("independent PDE residual check requires an approximately uniform z grid")
    if np.max(dx) > 0.25:
        raise ValueError("maximum grid spacing 0.25 A required to resolve the oscillatory modes")
    dz = float(dx[0]) * 1e-10
    deriv = lambda values: np.gradient(values, dz, edge_order=2)
    phi_z = deriv(f["phi_V"])
    phi_zz = deriv(phi_z)
    p1_z = deriv(f["P1_C_m2"])
    p1_zz = deriv(p1_z)
    p1_4 = deriv(deriv(p1_zz))
    p2_z = deriv(f["P2_C_m2"])
    p2_zz = deriv(p2_z)
    # K12/K22 and K13 are expressed in the paper in Angstrom powers.
    k12_m2, k22_m2, k13_m4 = k["K12"] * 1e-20, k["K22"] * 1e-20, k["K13"] * 1e-40
    terms_poisson = np.stack((EPS0 * phi_zz, -p1_z, -p2_z,
                              QE * (f["n_plus_m3"] - f["n_minus_m3"])))
    terms_p1 = np.stack((k["K11"] * f["P1_C_m2"], -k12_m2 * p1_zz,
                         k13_m4 * p1_4, EPS0 * phi_z))
    terms_p2 = np.stack((k["K21"] * f["P2_C_m2"], -k22_m2 * p2_zz,
                         EPS0 * phi_z))
    # Repeated numpy.gradient stencils lose accuracy at the first/last two
    # points. Keep the scored region close to the wall and overlap the wall
    # polynomial-fit region; report the actual coverage coordinates.
    trim = 4
    if len(z) <= 2 * trim + 8:
        raise ValueError("profile is too short for independent interior PDE residuals")
    near_end = min(len(z) - trim, int(np.searchsorted(z, 10.0)) + 1)
    if near_end <= trim + 8:
        raise ValueError("profile does not resolve the requested near-wall PDE band")
    all_interior = slice(trim, -trim)
    near_wall_band = slice(trim, near_end)
    def rel_res(terms, selection):
        values = np.sum(terms, axis=0)[selection]
        scales = np.sum(np.abs(terms), axis=0)[selection]
        return float(np.sqrt(np.mean(values**2)) /
                     max(np.sqrt(np.mean(scales**2)), 1e-30))
    poisson_pde_rel = rel_res(terms_poisson, all_interior)
    p1_pde_rel = rel_res(terms_p1, all_interior)
    p2_pde_rel = rel_res(terms_p2, all_interior)
    poisson_near_rel = rel_res(terms_poisson, near_wall_band)
    p1_near_rel = rel_res(terms_p1, near_wall_band)
    p2_near_rel = rel_res(terms_p2, near_wall_band)
    far_p1_prime_rel = (abs(_far_derivative(f["P1_C_m2"], z, 1))
                        * lambda_gc_A * 1e-10 / max(abs(pbar), 0.1))
    checks = {
        "lattice_gas_closure_relative_max": closure_err,
        "site_occupancy_max": float(np.max(occupancy)),
        "wall_P1_relative_error": float(wall_p1_rel),
        "wall_P2_relative_error": float(wall_p2_rel),
        "wall_displacement_relative_error": float(disp_err),
        "wall_P1_second_scaled": float(nat_err),
        "electroneutrality_relative_residual": float(neutrality_rel),
        "poisson_equation_relative_rms_residual_interior": poisson_pde_rel,
        "P1_equation_relative_rms_residual_interior": p1_pde_rel,
        "P2_equation_relative_rms_residual_interior": p2_pde_rel,
        "Poisson_equation_relative_rms_residual_near_wall": poisson_near_rel,
        "P1_equation_relative_rms_residual_near_wall": p1_near_rel,
        "P2_equation_relative_rms_residual_near_wall": p2_near_rel,
        "PDE_scored_z_interval_A": [float(z[trim]), float(z[-trim - 1])],
        "PDE_near_wall_band_A": [float(z[trim]), float(z[near_end - 1])],
        "maximum_grid_spacing_A": float(np.max(dx)),
        "domain_in_GC_lengths": float(z[-1] / lambda_gc_A),
        "far_field_P1_prime_scaled": float(far_p1_prime_rel),
        "far_field_abs_phi_V": float(abs(f["phi_V"][-1])),
        "far_field_abs_P1_C_m2": float(abs(f["P1_C_m2"][-1])),
        "far_field_abs_P2_C_m2": float(abs(f["P2_C_m2"][-1])),
    }
    passed = {
        "closure": closure_err <= 2e-5,
        "occupancy": float(np.max(occupancy)) <= 1.0 + 2e-6,
        "wall_modes": max(wall_p1_rel, wall_p2_rel) <= 2e-5,
        # The first two observables are differentiated from tabulated output;
        # these bounds cover the measured public-grid finite-difference error.
        "wall_displacement": disp_err <= 5e-3,
        "natural_wall_curvature": nat_err <= 5e-3,
        # Trapezoidal integration over the 0.05-A output grid has up to
        # 2.2e-3 relative error on the verified 1/10-mM matrix.
        "electroneutrality": neutrality_rel <= 5e-3,
        "poisson_equation": max(poisson_pde_rel, poisson_near_rel) <= 2e-2,
        "P1_equation": max(p1_pde_rel, p1_near_rel) <= 2e-2,
        "P2_equation": max(p2_pde_rel, p2_near_rel) <= 2e-2,
        "far_field": (abs(f["phi_V"][-1]) <= 1e-4 and
                      abs(f["P1_C_m2"][-1]) <= 1e-7 and
                      abs(f["P2_C_m2"][-1]) <= 1e-7 and
                      far_p1_prime_rel <= 2e-5),
    }
    return {"status": "PASS" if all(passed.values()) else "FAIL",
            "reward": 1.0 if all(passed.values()) else 0.0,
            "checks": checks, "passed": passed,
            "scope": "PDE residual coverage is z[4]..z[-5], with the near-wall band z[4]..10 A reported separately; the first/last 4 grid points are unchecked and convergence in this strip is not yet established; no published-figure fit claim"}
