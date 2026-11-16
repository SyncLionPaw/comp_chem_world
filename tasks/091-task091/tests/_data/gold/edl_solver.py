#!/usr/bin/env python3
"""Coupled nonlocal Poisson--Fermi double-layer solver (sharp interface).

This module solves the equations in JPCC 2023, Eqs. 26--29 on a semi-infinite
domain truncated at ``z_max_A``.  The coordinate is measured in Angstrom,
which matches the published K12/K13 units (A^2/A^4).  The surface conditions
are the variational conditions used for Bench 14: fixed mode values,
the natural condition P1''(0)=0, and eps0*phi'(0)=Pbar-sigma0.  In particular,
P1'(0) and the bound surface charge are outputs of the solution, not inputs.

The case API uses a declared author-side reconstruction of the Figure 6
roughness operator: each sharp field, including the nonlinear ion densities,
is averaged separately over the normalized half-space Eq. 19 wall-position
distribution. It does not infer ion densities from the averaged potential.
This implementation is not claimed to reproduce any unpublished averaging
details from the paper.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy.integrate import solve_bvp

QE = 1.602176634e-19
KB = 1.380649e-23
EPS0 = 8.8541878128e-12
NA = 6.02214076e23
K_PUBLISHED = {"K11": 0.140125, "K12": -0.207118,
               "K13": 0.011290, "K21": 0.015908, "K22": 2.003940}
P_SCALE = 0.1                 # C m^-2; numerical scale only, not a fit


@dataclass(frozen=True)
class Parameters:
    concentration_mM: float = 1.0
    sigma0_C_m2: float = 0.1
    Pbar_C_m2: float = 0.05
    alpha: float = 0.5
    temperature_K: float = 300.0  # reproducible author-side pilot; not a paper caption value
    cell_length_nm: float = 0.8
    z_max_A: float = 3000.0
    initial_step_A: float = 0.25
    K11: float = K_PUBLISHED["K11"]
    K12: float = K_PUBLISHED["K12"]
    K13: float = K_PUBLISHED["K13"]
    K21: float = K_PUBLISHED["K21"]
    K22: float = K_PUBLISHED["K22"]

    def validate(self) -> None:
        vals = asdict(self)
        if not all(np.isfinite(float(v)) for v in vals.values()):
            raise ValueError("all model inputs must be finite")
        if self.concentration_mM <= 0 or self.temperature_K <= 0 or self.cell_length_nm <= 0:
            raise ValueError("concentration, temperature, and cell length must be positive")
        if not 0.0 <= self.alpha <= 1.0:
            raise ValueError("alpha must lie in [0, 1]")
        if self.z_max_A <= 0 or self.initial_step_A <= 0:
            raise ValueError("domain and initial mesh spacing must be positive")
        if self.K13 <= 0 or self.K22 <= 0 or self.K11 <= 0 or self.K21 <= 0:
            raise ValueError("K11, K13, K21, and K22 must be positive")


def lattice_gas(phi_V: np.ndarray, p: Parameters) -> tuple[np.ndarray, np.ndarray]:
    """Return n+ and n- in m^-3 using the normalized bulk-reservoir closure."""
    nb = p.concentration_mM * 1.0e-3 * 1000.0 * NA
    a = p.cell_length_nm * 1.0e-9
    xi = nb * a**3
    psi = np.clip(QE * np.asarray(phi_V) / (KB * p.temperature_K), -80.0, 80.0)
    # Algebraically stable form of D=1+2 xi (cosh(psi)-1).
    den = (1.0 - 2.0 * xi) * np.exp(-psi) + xi * (1.0 + np.exp(-2.0 * psi))
    n_plus = nb * np.exp(-2.0 * psi) / den
    n_minus = nb / den
    return n_plus, n_minus


def eps_bulk(p: Parameters) -> float:
    """Long-wavelength dielectric constant implied by the two-mode kernel."""
    return 1.0 + 1.0 / p.K11 + 1.0 / p.K21


def linearized_screening_modes(p: Parameters) -> list[complex]:
    """Return decaying inverse lengths from the full small-field coupled ODE.

    The Gouy--Chapman length is the k->0 dielectric-limit reference. At finite
    electrolyte concentration the gradient terms in K12/K13/K22 can shift
    the actual asymptotic mode; the tail fit must be compared with this root,
    not forced onto the GC value.
    """
    nb = p.concentration_mM * 1.0e-3 * 1000.0 * NA
    a_m = p.cell_length_nm * 1.0e-9
    n_site = 1.0 / a_m**3
    vt = KB * p.temperature_K / QE
    beta = EPS0 * vt / (P_SCALE * 1.0e-10)
    gamma1 = EPS0 * vt / ((1.0e-10)**2 * QE * n_site)
    gamma2 = P_SCALE / (1.0e-10 * QE * n_site)
    xi = nb / n_site
    s = np.poly1d([1.0, 0.0])
    A1 = p.K11 - p.K12 * s**2 + p.K13 * s**4
    A2 = p.K21 - p.K22 * s**2
    B = gamma1 * s**2 - 2.0 * xi
    # For exp(-s z), both polarization equations contain -beta*s*psi;
    # Poisson contributes +gamma2*s*(p1+p2) - 2*xi*psi.
    characteristic = A1 * (A2 * B + beta * gamma2 * s**2) + beta * gamma2 * A2 * s**2
    roots = np.roots(characteristic.coeffs)
    return sorted((complex(r) for r in roots if r.real > 1.0e-8), key=lambda r: r.real)


def gc_profile(z_A: np.ndarray, p: Parameters) -> np.ndarray:
    """Analytic dilute-ion Gouy--Chapman tail with kernel eps_bulk."""
    nb = p.concentration_mM * 1.0e-3 * 1000.0 * NA
    vt = KB * p.temperature_K / QE
    eps_b = eps_bulk(p)
    kappa = np.sqrt(2.0 * QE**2 * nb / (EPS0 * eps_b * KB * p.temperature_K))
    z_m = np.asarray(z_A) * 1.0e-10
    # This is the conventional GC solution for the declared surface charge.
    # For a structured-water solution its amplitude need not match the far
    # tail; the decay length remains the strict analytic comparison.
    arg = np.clip(p.sigma0_C_m2 / np.sqrt(8.0 * EPS0 * eps_b * KB * p.temperature_K * nb), -100, 100)
    psi0 = 2.0 * np.arcsinh(arg)
    return 4.0 * vt * np.arctanh(np.tanh(psi0 / 4.0) * np.exp(-kappa * z_m))


class DoubleLayer:
    """Solve the sharp-interface system with fourth-order collocation."""

    def __init__(self, parameters: Parameters):
        parameters.validate()
        self.p = parameters
        self.L_m = 1.0e-10  # one Angstrom in metres
        self.VT = KB * parameters.temperature_K / QE
        self.nb = parameters.concentration_mM * 1.0e-3 * 1000.0 * NA
        self.a_m = parameters.cell_length_nm * 1.0e-9
        self.n_site = 1.0 / self.a_m**3
        self.beta = EPS0 * self.VT / (P_SCALE * self.L_m)
        self.gamma1 = EPS0 * self.VT / (self.L_m**2 * QE * self.n_site)
        self.gamma2 = P_SCALE / (self.L_m * QE * self.n_site)
        self.psi_prime_wall = ((parameters.Pbar_C_m2 - parameters.sigma0_C_m2)
                               * self.L_m / (EPS0 * self.VT))
        self.continuation = 1.0

    def ode(self, x_A: np.ndarray, y: np.ndarray) -> np.ndarray:
        p = self.p
        p1, p1x, p1xx, p1xxx, p2, p2x, psi, psix = y
        # x is in Angstrom; the published K12 and K13 are in A^2 and A^4.
        p1xxxx = (p.K12 * p1xx - p.K11 * p1 - self.beta * psix) / p.K13
        p2xx = (p.K21 * p2 + self.beta * psix) / p.K22
        phi = self.VT * psi
        n_plus, n_minus = lattice_gas(phi, p)
        charge_scaled = QE * (n_plus - n_minus) / (QE * self.n_site)
        psixx = (self.gamma2 * (p1x + p2x) - charge_scaled) / self.gamma1
        return np.vstack((p1x, p1xx, p1xxx, p1xxxx,
                          p2x, p2xx, psix, psixx))

    def boundary(self, ya: np.ndarray, yb: np.ndarray) -> np.ndarray:
        p = self.p
        p1_wall = self.continuation * (1.0 - p.alpha) * p.Pbar_C_m2 / P_SCALE
        p2_wall = self.continuation * p.alpha * p.Pbar_C_m2 / P_SCALE
        # Natural variational condition P1''(0)=0.  The far-boundary set is
        # P1=P1'=P2=phi=0; the eighth condition is the Neumann field at z=0.
        return np.array([
            ya[0] - p1_wall,
            ya[2],
            ya[4] - p2_wall,
            ya[7] - self.continuation * self.psi_prime_wall,
            yb[0], yb[1], yb[4], yb[6],
        ])

    def initial_guess(self, x_A: np.ndarray) -> np.ndarray:
        p = self.p
        p1w = (1.0 - p.alpha) * p.Pbar_C_m2 / P_SCALE
        p2w = p.alpha * p.Pbar_C_m2 / P_SCALE
        # Smooth decays seed continuation; BVP conditions enforce the exact
        # natural wall condition and the correct far-field values.
        l1, l2, lp = 4.0, 12.0, 100.0
        p1 = p1w * np.exp(-x_A / l1)
        p2 = p2w * np.exp(-x_A / l2)
        # GC-scale wall potential is a much better continuation seed than
        # extrapolating the vacuum field over an entire diffuse-layer length.
        charge = self.p.sigma0_C_m2
        gc_arg = charge / np.sqrt(8.0 * EPS0 * eps_bulk(p) * KB * p.temperature_K * self.nb)
        psi0 = 2.0 * np.arcsinh(gc_arg)
        psi0 *= self.continuation
        psi = psi0 * np.exp(-x_A / lp)
        return np.vstack((p1, -p1 / l1, np.zeros_like(x_A), -p1 / l1**3,
                          p2, -p2 / l2, psi, -psi / lp))

    def solve(self, tol: float = 2e-5, max_nodes: int = 30000, verbose: int = 0):
        x = np.arange(0.0, self.p.z_max_A + self.p.initial_step_A * 0.5,
                      self.p.initial_step_A)
        result = None
        # Ramp the surface data from the trivial bulk state.  This is important
        # for the nonlinear lattice-gas response at high wall fields.
        for lam in (0.05, 0.15, 0.35, 0.65, 1.0):
            self.continuation = lam
            if result is None:
                y = self.initial_guess(x)
            else:
                x, y = result.x, result.y
            result = solve_bvp(self.ode, self.boundary, x, y, tol=tol,
                               max_nodes=max_nodes, verbose=verbose)
            if not result.success:
                raise RuntimeError(f"BVP continuation lambda={lam:g} failed: "
                                   f"status={result.status}: {result.message}")
        self.result = result
        return result

    def profile(self, n_points: int | None = None,
                z_A: np.ndarray | None = None) -> dict[str, np.ndarray]:
        if not hasattr(self, "result"):
            raise RuntimeError("call solve() before profile()")
        if n_points is not None and z_A is not None:
            raise ValueError("supply either n_points or z_A, not both")
        x = (self.result.x if n_points is None and z_A is None else
             np.asarray(z_A, dtype=float) if z_A is not None else
             np.linspace(0, self.p.z_max_A, n_points))
        if x.ndim != 1 or x.size < 2 or np.any(~np.isfinite(x)) or np.any(np.diff(x) <= 0):
            raise ValueError("profile coordinates must be a finite increasing 1-D array")
        if x[0] < 0.0 or x[-1] > self.p.z_max_A:
            raise ValueError("profile coordinates fall outside the solved domain")
        y = self.result.sol(x)
        phi = y[6] * self.VT
        n_plus, n_minus = lattice_gas(phi, self.p)
        return {"z_A": x, "phi_V": phi, "P1_C_m2": y[0] * P_SCALE,
                "P1_prime_C_m3": y[1] * P_SCALE / self.L_m,
                "P1_second_C_m4": y[2] * P_SCALE / self.L_m**2,
                "P2_C_m2": y[4] * P_SCALE,
                "P2_prime_C_m3": y[5] * P_SCALE / self.L_m,
                "n_plus_m3": n_plus, "n_minus_m3": n_minus,
                "site_occupancy": self.a_m**3 * (n_plus + n_minus)}

    def functional_energy(self, x_A=None, y=None, state_function=None,
                          quadrature_order: int = 16) -> float:
        """Fixed-sigma bulk-subtracted grand functional in J/m^2.

        The potential is evaluated at its stationary/maximizing solution;
        this is not a joint minimization over phi and polarization.
        """
        if not hasattr(self, "result"):
            raise RuntimeError("call solve() before functional_energy()")
        if state_function is not None and (x_A is not None or y is not None):
            raise ValueError("state_function cannot be combined with sampled x_A/y")
        x = self.result.x if x_A is None else np.asarray(x_A, dtype=float)
        if np.any(np.diff(x) <= 0) or x.ndim != 1 or x.size < 2:
            raise ValueError("functional mesh must be an increasing 1-D grid")
        if y is not None:
            state = np.asarray(y, dtype=float)
            if state.shape != (8, x.size):
                raise ValueError("functional state must have shape (8, len(x_A))")
            from scipy.interpolate import CubicHermiteSpline
            state_function = CubicHermiteSpline(x, state,
                np.gradient(state, x, axis=1, edge_order=2), axis=1)
        if state_function is None:
            state_function = self.result.sol
        p = self.p
        k12, k22, k13 = p.K12 * 1e-20, p.K22 * 1e-20, p.K13 * 1e-40
        gx, gw = np.polynomial.legendre.leggauss(int(quadrature_order))
        midpoint = 0.5 * (x[:-1] + x[1:])
        halfwidth = 0.5 * np.diff(x)
        xq = (midpoint[:, None] + halfwidth[:, None] * gx[None, :]).ravel()
        weights = (halfwidth[:, None] * gw[None, :] * self.L_m).ravel()
        state = state_function(xq)
        p1, p1x, p1xx, _, p2, p2x, psi, psix = state
        p1 = p1 * P_SCALE; p1x = p1x * P_SCALE / self.L_m
        p1xx = p1xx * P_SCALE / self.L_m**2
        p2 = p2 * P_SCALE; p2x = p2x * P_SCALE / self.L_m
        phix = psix * self.VT / self.L_m
        gradient = (p.K11 * p1**2 + k12 * p1x**2 + k13 * p1xx**2
                    + p.K21 * p2**2 + k22 * p2x**2) / (2.0 * EPS0)
        electrostatic = -0.5 * EPS0 * phix**2 + (p1 + p2) * phix
        dimless = np.clip(psi * QE * self.VT / (KB * p.temperature_K), -80.0, 80.0)
        lattice_log = np.log1p(2.0 * self.nb * self.a_m**3
                               * (np.cosh(dimless) - 1.0))
        ionic = -KB * p.temperature_K / self.a_m**3 * lattice_log
        integrand = gradient + electrostatic + ionic
        wall_phi = float(state_function(np.array([0.0]))[6][0] * self.VT)
        return float(np.dot(weights, integrand) + p.sigma0_C_m2 * wall_phi)

    def reduced_energy_combination(self, components: list[dict],
                                   tol: float = 2e-7) -> tuple[float, float]:
        """Evaluate Omega after re-solving the nonlinear Poisson/ion saddle.

        Each component uses a max-abs-normalized admissible polarization mode
        (P1, P2, or both). P1'(0) is allowed to vary; P1''(0)=0 is tested as
        a natural stationarity condition on the solved state.
        """
        if not components:
            raise ValueError("at least one polarization perturbation is required")
        p, x, base = self.p, self.result.x, self.result.sol
        cache = []
        sample_x = np.linspace(0.0, p.z_max_A, max(4097, int(p.z_max_A * 20) + 1))
        for component in components:
            mode = component["mode"]
            ell = float(component["length_A"])
            wave = float(component.get("wave_number_A_inv", 0.0))
            amp = float(component["amplitude_C_m2"]) / P_SCALE
            if mode not in ("P1", "P2", "mixed") or ell <= 0 or not np.isfinite(amp + wave):
                raise ValueError("invalid polarization perturbation component")
            def shape(coords, ell=ell, wave=wave):
                coords = np.asarray(coords)
                t = coords / ell
                exp = np.exp(-t)
                co, si = np.cos(wave * coords), np.sin(wave * coords)
                h = exp * co
                hp = exp * (-co / ell - wave * si)
                hpp = exp * ((1.0 / ell**2 - wave**2) * co
                             + 2.0 * wave / ell * si)
                return t * h, h / ell + t * hp, 2.0 * hp / ell + t * hpp
            norm = float(np.max(np.abs(shape(sample_x)[0])))
            cache.append((mode, amp / norm, shape))

        def deltas(coords):
            values = [np.zeros_like(np.asarray(coords), dtype=float) for _ in range(6)]
            for mode, amp, shape in cache:
                v, d1, d2 = shape(coords)
                if mode in ("P1", "mixed"):
                    values[0] += amp * v
                    values[1] += amp * d1
                    values[2] += amp * d2
                if mode in ("P2", "mixed"):
                    values[3] += amp * v
                    values[4] += amp * d1
            return values

        def ode(coords, electro):
            base_y = base(coords)
            delta = deltas(coords)
            psi, psix = electro
            nplus, nminus = lattice_gas(self.VT * psi, p)
            charge_scaled = (nplus - nminus) / self.n_site
            psixx = (self.gamma2 * (base_y[1] + base_y[5] + delta[1] + delta[4])
                     - charge_scaled) / self.gamma1
            return np.vstack((psix, psixx))

        def boundary(ya, yb):
            return np.array([ya[1] - self.psi_prime_wall, yb[0]])

        poisson = solve_bvp(ode, boundary, x, self.result.y[6:8].copy(),
                            tol=tol, max_nodes=40000)
        if not poisson.success:
            raise RuntimeError(f"perturbation Poisson saddle failed: {poisson.message}")

        def trial_state(coords):
            trial = base(coords).copy()
            delta = deltas(coords)
            trial[0] += delta[0]; trial[1] += delta[1]; trial[2] += delta[2]
            trial[4] += delta[3]; trial[5] += delta[4]
            trial[6:8] = poisson.sol(coords)
            return trial
        return (self.functional_energy(state_function=trial_state),
                float(np.max(poisson.rms_residuals)))

    def reduced_energy_perturbation(self, mode: str, length_A: float,
                                    amplitude_C_m2: float, wave_number_A_inv: float = 0.0,
                                    tol: float = 2e-7) -> tuple[float, float]:
        return self.reduced_energy_combination([{"mode": mode, "length_A": length_A,
            "amplitude_C_m2": amplitude_C_m2,
            "wave_number_A_inv": wave_number_A_inv}], tol=tol)

    def stationarity_diagnostics(self, amplitudes_C_m2=(4e-4, 2e-4),
                                 poisson_tol: float = 2e-7) -> dict:
        """Projected reduced-energy gradient/Hessian in six admissible modes.

        The six-mode matrix includes off-diagonal P1/P2 couplings. It tests
        only the declared finite-dimensional subspace and is not a global
        minimum proof.
        """
        base_energy = self.functional_energy()
        gc = self.checks()["analytic_GC_debye_length_A"]
        directions = []
        for mode in ("P1", "P2"):
            directions.extend([
                {"mode": mode, "length_A": 2.0, "wave_number_A_inv": 0.0},
                {"mode": mode, "length_A": 2.0, "wave_number_A_inv": 3.0},
                {"mode": mode, "length_A": gc / 2.0, "wave_number_A_inv": 0.0},
            ])
        amplitudes = [abs(float(a)) for a in amplitudes_C_m2]
        if len(amplitudes) != 2 or min(amplitudes) <= 0 or amplitudes[0] <= amplitudes[1]:
            raise ValueError("stability amplitudes must be two positive values in descending order")
        gradients, hessians, residuals = [], [], []
        for amplitude in amplitudes:
            grad = np.zeros(len(directions))
            hessian = np.zeros((len(directions), len(directions)))
            for i, direction in enumerate(directions):
                ep, rp = self.reduced_energy_perturbation(**direction,
                    amplitude_C_m2=amplitude, tol=poisson_tol)
                em, rm = self.reduced_energy_perturbation(**direction,
                    amplitude_C_m2=-amplitude, tol=poisson_tol)
                grad[i] = (ep - em) / (2 * amplitude)
                hessian[i, i] = (ep + em - 2 * base_energy) / amplitude**2
                residuals.extend((rp, rm))
            for i in range(len(directions)):
                for j in range(i + 1, len(directions)):
                    vals = []
                    for si, sj in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                        e, res = self.reduced_energy_combination([
                            {**directions[i], "amplitude_C_m2": si * amplitude},
                            {**directions[j], "amplitude_C_m2": sj * amplitude}], tol=poisson_tol)
                        vals.append(e); residuals.append(res)
                    cross = (vals[0] - vals[1] - vals[2] + vals[3]) / (4 * amplitude**2)
                    hessian[i, j] = hessian[j, i] = cross
            gradients.append(grad); hessians.append(hessian)
        hcoarse, hfine = hessians
        eig_coarse, eig_fine = np.linalg.eigvalsh(hcoarse), np.linalg.eigvalsh(hfine)
        h_error = 2.0 * float(np.linalg.norm(hfine - hcoarse, ord=2))
        grad_error = float(np.max(np.abs(gradients[1] - gradients[0])))
        positive_resolved = bool(eig_fine[0] > h_error)
        stationary_resolved = bool(np.max(np.abs(gradients[1])) <= 1e-3
                                   and grad_error <= 1e-3)
        return {"fixed_sigma_functional_energy_J_m2": base_energy,
                "functional_convention": "bulk-subtracted fixed-sigma grand functional; phi solved at stationary/maximizing saddle",
                "stability_scope": "six-mode projected reduced Hessian; finite admissible local test only, not a proof of global minimum",
                "basis": [{**d, "wall_value_zero": True, "normalization": "maximum absolute shape equals one"}
                          for d in directions],
                "amplitudes_C_m2": amplitudes,
                "reduced_gradient_V_by_amplitude": [g.tolist() for g in gradients],
                "reduced_hessian_J_m2_per_C_m2_sq_by_amplitude": [h.tolist() for h in hessians],
                "hessian_eigenvalues_by_amplitude": [eig_coarse.tolist(), eig_fine.tolist()],
                "hessian_spectral_error_estimate": h_error,
                "gradient_max_abs_fine_V": float(np.max(np.abs(gradients[-1]))),
                "gradient_max_amplitude_difference_V": grad_error,
                "poisson_rms_residual_max": max(residuals),
                "projected_minimum_resolved": positive_resolved,
                "stationarity_resolved": stationary_resolved,
                "all_tested_local_directions_nonnegative": positive_resolved and stationary_resolved}

    def checks(self) -> dict:
        f = self.profile()
        p = self.p
        z_m = f["z_A"] * self.L_m
        charge_density = QE * (f["n_plus_m3"] - f["n_minus_m3"])
        trapz = getattr(np, "trapezoid", np.trapz)
        integrated_charge = float(trapz(charge_density, z_m))
        total_charge = p.sigma0_C_m2 + integrated_charge
        charge_abs = abs(total_charge)
        rel_to_sigma = (charge_abs / abs(p.sigma0_C_m2)
                        if abs(p.sigma0_C_m2) > 1.0e-12 else None)
        wall_field = EPS0 * self.VT / self.L_m * self.result.sol(0.0)[7]
        lambda_gc_A = float(np.sqrt(EPS0 * eps_bulk(p) * KB * p.temperature_K /
                                    (2 * QE**2 * self.nb)) * 1e10)
        modes = linearized_screening_modes(p)
        slow_mode = modes[0]
        tail_z = np.linspace(3.0 * lambda_gc_A, 7.0 * lambda_gc_A, 161)
        tail_phi = self.result.sol(tail_z)[6] * self.VT
        valid = np.isfinite(tail_phi) & (np.abs(tail_phi) > np.finfo(float).tiny)
        if np.count_nonzero(valid) < 10 or np.any(np.sign(tail_phi[valid]) != np.sign(tail_phi[valid][0])):
            tail_lambda_A, tail_fit_r2 = float("nan"), float("nan")
        else:
            coef = np.polyfit(tail_z[valid], np.log(np.abs(tail_phi[valid])), 1)
            fitted = np.polyval(coef, tail_z[valid])
            tail_lambda_A = float(-1.0 / coef[0])
            tail_fit_r2 = float(1.0 - np.sum((np.log(np.abs(tail_phi[valid])) - fitted)**2)
                                / np.sum((np.log(np.abs(tail_phi[valid]))
                                          - np.mean(np.log(np.abs(tail_phi[valid]))))**2))
        return {
            "solver_success": bool(self.result.success),
            "solver_rms_residual_max": float(np.max(self.result.rms_residuals)),
            "boundary_residual_max": float(np.max(np.abs(self.boundary(
                self.result.y[:, 0], self.result.y[:, -1])))),
            "wall_natural_P1_second_C_m4": float(f["P1_second_C_m4"][0]),
            "wall_surface_displacement_C_m2": float(p.Pbar_C_m2 - wall_field),
            "wall_surface_charge_input_C_m2": p.sigma0_C_m2,
            "integrated_mobile_charge_C_m2": integrated_charge,
            "electroneutrality_residual_C_m2": total_charge,
            "electroneutrality_relative_to_input_charge": rel_to_sigma,
            "electroneutrality_relative_to_Pscale": charge_abs / P_SCALE,
            "occupancy_max": float(np.max(f["site_occupancy"])),
            "occupancy_bound_pass": bool(np.max(f["site_occupancy"]) <= 1.0 + 1e-7),
            "eps_bulk": eps_bulk(p),
            "analytic_GC_debye_length_A": lambda_gc_A,
            "linearized_modes_inverse_A": [[float(r.real), float(r.imag)] for r in modes],
            "linearized_slowest_decay_length_A": float(1.0 / slow_mode.real),
            "linearized_slowest_period_A": float(2.0 * np.pi / abs(slow_mode.imag))
                if abs(slow_mode.imag) > 1.0e-10 else None,
            "far_field_fit_window_A": [3.0 * lambda_gc_A, 7.0 * lambda_gc_A],
            "far_field_fit_length_A": tail_lambda_A,
            "far_field_fit_r_squared": tail_fit_r2,
            "far_field_fit_relative_deviation": abs(tail_lambda_A / lambda_gc_A - 1.0)
                if np.isfinite(tail_lambda_A) else float("nan"),
            "far_field_fit_vs_coupled_mode_relative_deviation": abs(tail_lambda_A * slow_mode.real - 1.0)
                if np.isfinite(tail_lambda_A) else float("nan"),
            "domain_A": float(self.p.z_max_A),
            "adaptive_nodes": int(self.result.x.size),
        }


def write_result(solver: DoubleLayer, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    f = solver.profile(n_points=3001)
    with (out_dir / "dl_profiles_sharp.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["z_A", "phi_V", "P1_C_m2", "P1_prime_C_m3",
                         "P1_second_C_m4", "P2_C_m2", "n_plus_m3", "n_minus_m3",
                         "site_occupancy"])
        writer.writerows(zip(*f.values()))
    payload = {"parameters": asdict(solver.p), "checks": solver.checks(),
               "boundary_contract": {
                   "wall": ["P1=(1-alpha)Pbar", "P2=alpha*Pbar", "P1''=0",
                            "eps0*phi'=Pbar-sigma0"],
                   "far": ["P1=0", "P1'=0", "P2=0", "phi=0"],
                   "P1_prime_wall_is_solved": True,
                   "bound_surface_charge_is_derived": True,
               },
               "scope": "sharp-interface coupled BVP; no Figure 5/6 parameter calibration or smearing claim"}
    (out_dir / "analysis.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _gc_length_A(concentration_mM: float, temperature_K: float) -> float:
    nb = float(concentration_mM) * NA  # mM -> mol/m^3 -> ions/m^3
    eps_b = 1.0 + 1.0 / K_PUBLISHED["K11"] + 1.0 / K_PUBLISHED["K21"]
    return float(np.sqrt(EPS0 * eps_b * KB * temperature_K /
                         (2.0 * QE**2 * nb)) * 1e10)


def run_request(input_path: Path, output_dir: Path) -> dict:
    """Solve all conditions in the public API and write full sharp/smeared profiles.

    The input is user-controlled and is also used by private off-grid probes.
    Output rows are sampled uniformly through the full, input-declared domain;
    they are not lookup-table references.
    """
    from smearing import average_continuous_profile, average_shifted_profile

    request = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if request.get("schema") != "bench14.edl.request/v1":
        raise ValueError("unsupported request schema")
    shared = request["shared_parameters"]
    numerics = request["numerics"]
    rough = request["roughness"]
    variational = request.get("functional_stability", {"include": False})
    conditions = request["conditions"]
    if not isinstance(conditions, list) or not conditions:
        raise ValueError("request must contain at least one condition")
    step = float(numerics["output_step_A"])
    initial_step = float(numerics["initial_mesh_step_A"])
    domain_lengths = float(numerics["domain_gc_lengths"])
    round_up = float(numerics["round_domain_up_A"])
    rough_step = float(rough.get("integration_step_A", 0.0125))
    if step <= 0 or initial_step <= 0 or domain_lengths < 8 or round_up <= 0:
        raise ValueError("invalid mesh/domain settings")
    if not np.isfinite(rough_step) or rough_step <= 0:
        raise ValueError("roughness integration step must be finite and positive")
    if len({str(row["run_id"]) for row in conditions}) != len(conditions):
        raise ValueError("run_id values must be unique")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    columns = ["run_id", "concentration_mM", "Pbar_C_m2", "sigma0_C_m2",
               "temperature_K", "alpha", "cell_length_nm", "z_A", "phi_V",
               "P1_C_m2", "P1_prime_C_m3", "P1_second_C_m4", "P2_C_m2",
               "P2_prime_C_m3", "n_plus_m3", "n_minus_m3", "site_occupancy",
               "liquid_fraction", "rho1_wall_C_m3", "rho_total_wall_C_m3"]
    analysis = {"schema": "bench14.edl.analysis/v1", "conditions": [],
                "author_reconstruction": True,
                "field_semantics": {
                    "P1_prime_C_m3": "rough table is the Eq.19 weighted mean of sharp local P1' at z-ell, not d(mean(P1))/dz",
                    "P2_prime_C_m3": "rough table is the Eq.19 weighted mean of sharp local P2' at z-ell, not d(mean(P2))/dz",
                    "P1_second_C_m4": "rough table is the Eq.19 weighted mean of sharp local P1'' at z-ell",
                    "rho1_wall_C_m3": "original sharp-wall -P1'(0), repeated as condition metadata; not rough averaged-interface charge",
                    "rho_total_wall_C_m3": "original sharp-wall -(P1'+P2')(0), repeated as condition metadata; not rough averaged-interface charge",
                    "rough_fields": "the local sharp fields listed here are convolved independently; they are not asserted to satisfy the sharp-interface PDE after convolution"},
                "roughness": {"equation": "Eq.19 half-space wall-position density",
                              "mean_A": rough["mean_A"], "delta_A": rough["delta_A"],
                              "integration_step_A": rough_step,
                              "quadrature_order": int(rough["quadrature_order"]),
                              "near_wall_continuous_until_A": float(rough.get("continuous_direct_until_A", 30.0)),
                              "near_wall_panel_A": float(rough.get("continuous_panel_A", 0.05)),
                              "near_wall_gauss_order": int(rough.get("continuous_gauss_order", 8)),
                              "interpretation": "independently convolve each sharp field, including n+ and n-; do not apply ion closure to averaged phi"}}
    log = ["Bench 14 case 005 coupled Poisson-Fermi solutions"]
    start_all = time.perf_counter()
    sharp_path = output_dir / "dl_profiles_sharp.csv"
    smear_path = output_dir / "dl_profiles_smeared.csv"
    with sharp_path.open("w", newline="", encoding="utf-8") as sharp_stream, \
         smear_path.open("w", newline="", encoding="utf-8") as smear_stream:
        sharp_writer, smear_writer = csv.DictWriter(sharp_stream, fieldnames=columns), \
                                     csv.DictWriter(smear_stream, fieldnames=columns)
        sharp_writer.writeheader(); smear_writer.writeheader()
        for condition in conditions:
            c = float(condition["concentration_mM"])
            gc_A = _gc_length_A(c, float(shared["temperature_K"]))
            z_max = np.ceil(domain_lengths * gc_A / round_up) * round_up
            p = Parameters(concentration_mM=c,
                sigma0_C_m2=float(shared["sigma0_C_m2"]),
                Pbar_C_m2=float(condition["Pbar_C_m2"]),
                alpha=float(shared["alpha"]),
                temperature_K=float(shared["temperature_K"]),
                cell_length_nm=float(shared["cell_length_nm"]),
                **{key: float(value) for key, value in shared["kernel_constants"].items()},
                z_max_A=float(z_max), initial_step_A=initial_step)
            solver = DoubleLayer(p)
            started = time.perf_counter()
            result = solver.solve(tol=float(numerics["bvp_tolerance"]))
            z = np.linspace(0.0, p.z_max_A,
                            int(round(p.z_max_A / step)) + 1)
            fields = solver.profile(z_A=z)
            rho1 = -float(fields["P1_prime_C_m3"][0])
            rho_total = -(float(fields["P1_prime_C_m3"][0])
                          + float(fields["P2_prime_C_m3"][0]))
            rough_z = np.linspace(0.0, p.z_max_A,
                int(round(p.z_max_A / rough_step)) + 1)
            rough_source = solver.profile(z_A=rough_z)
            rough_fields = {key: rough_source[key] for key in (
                "phi_V", "P1_C_m2", "P1_prime_C_m3", "P1_second_C_m4",
                "P2_C_m2", "P2_prime_C_m3", "n_plus_m3", "n_minus_m3",
                "site_occupancy")}
            smeared = average_shifted_profile(z, rough_z, rough_fields,
                mean_A=float(rough["mean_A"]), delta_A=float(rough["delta_A"]),
                quadrature_order=int(rough["quadrature_order"]))
            direct_end = float(rough.get("continuous_direct_until_A", 30.0))
            near_mask = z <= direct_end
            if np.any(near_mask):
                direct = average_continuous_profile(
                    z[near_mask], lambda x: solver.profile(z_A=x),
                    mean_A=float(rough["mean_A"]), delta_A=float(rough["delta_A"]),
                    panel_A=float(rough.get("continuous_panel_A", 0.05)),
                    quadrature_order=int(rough.get("continuous_gauss_order", 8)))
                for key in rough_fields:
                    smeared[key][near_mask] = direct[key]
            common = {"run_id": condition["run_id"], "concentration_mM": c,
                "Pbar_C_m2": p.Pbar_C_m2, "sigma0_C_m2": p.sigma0_C_m2,
                "temperature_K": p.temperature_K, "alpha": p.alpha,
                "cell_length_nm": p.cell_length_nm, "rho1_wall_C_m3": rho1,
                "rho_total_wall_C_m3": rho_total}
            for i, zi in enumerate(z):
                sharp_writer.writerow({**common, "z_A": zi,
                    "liquid_fraction": 1.0, **{k: v[i] for k, v in fields.items()
                        if k != "z_A"}})
                smear_writer.writerow({**common, "z_A": zi,
                    "liquid_fraction": smeared["liquid_fraction"][i],
                    **{k: smeared[k][i] for k in rough_fields}})
            checks = solver.checks()
            energy_order = int(numerics.get("functional_quadrature_order", 16))
            energy_coarse = solver.functional_energy(quadrature_order=max(4, energy_order // 2))
            energy_fine = solver.functional_energy(quadrature_order=energy_order)
            stability = None
            if variational.get("include", False):
                stability = solver.stationarity_diagnostics(
                    amplitudes_C_m2=variational["amplitudes_C_m2"],
                    poisson_tol=float(numerics["poisson_tolerance"]))
            entry = {"run_id": condition["run_id"], "parameters": asdict(p),
                     "rho1_wall_C_m3": rho1, "rho_total_wall_C_m3": rho_total,
                     "checks": checks, "bvp": {"success": bool(result.success),
                         "adaptive_nodes": int(result.x.size),
                         "rms_residual_max": float(np.max(result.rms_residuals))},
                     "fixed_sigma_functional_energy_J_m2": energy_fine,
                     "functional_quadrature_order": energy_order,
                     "functional_energy_quadrature_difference_J_m2": energy_fine - energy_coarse,
                     "stationarity": stability,
                     "output_points": int(z.size),
                     "runtime_seconds": time.perf_counter() - started}
            analysis["conditions"].append(entry)
            log.append(f"{condition['run_id']}: c={c:g} mM Pbar={p.Pbar_C_m2:g} C/m2 "
                       f"zmax={p.z_max_A:g} A nodes={result.x.size} "
                       f"RMS={np.max(result.rms_residuals):.4g} "
                       f"charge_rel={checks['electroneutrality_relative_to_input_charge']:.4g} "
                       f"Omega={energy_fine:.10g} J/m2 "
                       f"stability={None if stability is None else stability['all_tested_local_directions_nonnegative']} "
                       f"runtime={entry['runtime_seconds']:.3f}s")
    analysis["runtime_seconds_total"] = time.perf_counter() - start_all
    analysis["input_sha256"] = __import__("hashlib").sha256(
        Path(input_path).read_bytes()).hexdigest()
    (output_dir / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    log.append(f"all conditions completed in {analysis['runtime_seconds_total']:.3f}s")
    (output_dir / "solver.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    return analysis


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path,
                    help="JSON request following bench14.edl.request/v1")
    ap.add_argument("--output-dir", type=Path, default=Path("final"))
    ap.add_argument("--concentration-mM", type=float, default=1.0)
    ap.add_argument("--sigma0", type=float, default=0.1, help="surface charge [C/m^2]")
    ap.add_argument("--Pbar", type=float, default=0.05, help="surface polarization [C/m^2]")
    ap.add_argument("--alpha", type=float, default=0.5)
    ap.add_argument("--temperature-K", type=float, default=300.0,
                    help="explicit author-side pilot default; not frozen by Fig. 5/6 caption")
    ap.add_argument("--z-max-A", type=float, default=3000.0)
    ap.add_argument("--step-A", type=float, default=0.25)
    ap.add_argument("--output", type=Path, default=Path("final"))
    args = ap.parse_args()
    if args.input is not None:
        report = run_request(args.input, args.output_dir)
        print(json.dumps({"conditions": len(report["conditions"]),
                          "runtime_seconds_total": report["runtime_seconds_total"]}, indent=2))
        return
    params = Parameters(concentration_mM=args.concentration_mM,
                        sigma0_C_m2=args.sigma0, Pbar_C_m2=args.Pbar,
                        alpha=args.alpha, temperature_K=args.temperature_K,
                        z_max_A=args.z_max_A, initial_step_A=args.step_A)
    solver = DoubleLayer(params)
    solver.solve(verbose=1)
    write_result(solver, args.output)


if __name__ == "__main__":
    main()
