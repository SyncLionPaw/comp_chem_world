#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Crack-tip first crossings and experimental comparability.
"""Independent Case-07 physical-chain and fixed-quadrature interval certificate verifier."""
from __future__ import annotations

# interval_audit scientific verification
"""Independent numerical and interval audit for the conditional Case-07 model.

These kernels support the terminal-state verifier below. The interval routine uses
positive Gauss-Legendre weights and interval enclosures of the smooth model to
exclude roots or prove monotonicity. Floating-point and quadrature qualifications
are recorded in the output; it is not an IEEE formal proof.
"""
import csv as _audit_csv, math as _audit_math
from dataclasses import dataclass as _audit_dataclass
from pathlib import Path as _audit_Path
import numpy as _audit_np
_audit_KB = 8.617333262145e-05
_audit_EV_PER_J = 1.0 / 1.602176634e-19
_audit_J_M2_PER_EV_A2 = 16.02176634
_audit_L = 8.0

def _audit_read_csv(p):
    with _audit_Path(p).open(newline='', encoding='utf-8') as f:
        return list(_audit_csv.DictReader(f))


def _audit_quad(order):
    z, w = _audit_np.polynomial.legendre.leggauss(order)
    x = _audit_L * z
    w = _audit_L * w * _audit_np.exp(-x * x) / _audit_math.sqrt(_audit_math.pi)
    return (x, w)

def _audit_tail_error_bound(order, sigma, temp):
    ymax = _audit_math.pi * _audit_KB * temp / (2.0 * sigma)
    b = ymax / _audit_L
    rho = b + _audit_math.sqrt(1.0 + b * b)
    M = _audit_math.exp(ymax * ymax) / _audit_math.sqrt(_audit_math.pi)
    cheb = 16.0 * _audit_L * M * rho ** (-(2 * order - 1)) / (rho - 1.0)
    return cheb + _audit_math.erfc(_audit_L)

def _audit_logistic_vec(x):
    return 1.0 / (1.0 + _audit_np.exp(_audit_np.clip(x, -700.0, 700.0)))

def _audit_interp(x, points):
    pts = sorted(points)
    if x < pts[0][0] - 1e-14 or x > pts[-1][0] + 1e-14:
        return None
    x = min(max(x, pts[0][0]), pts[-1][0])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]

def _audit_minmax_interp(lo, hi, points):
    pts = sorted(points)
    vals = [_audit_interp(lo, pts), _audit_interp(hi, pts)]
    vals += [y for x, y in pts if lo < x < hi]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return (min(vals), max(vals))

def _audit_hill_nu(c11, c12, c44):
    bulk = (c11 + 2 * c12) / 3
    gv = (c11 - c12 + 3 * c44) / 5
    gr = 5 * (c11 - c12) * c44 / (4 * c44 + 3 * (c11 - c12))
    shear = (gv + gr) / 2
    return (3 * bulk - 2 * shear) / (2 * (3 * bulk + shear))

def _audit_pressure_slope_pa_per_mpa(r_m, theta, nu):
    return 2 * (1 + nu) * 1000000.0 / (3 * _audit_math.sqrt(2 * _audit_math.pi * r_m)) * _audit_math.cos(theta / 2)

def _audit_entropy(cb, c, temp, area):
    if c <= 0:
        xlogx = 0.0
    else:
        xlogx = c * _audit_math.log(c)
    one = 0.0 if c >= 1 else (1 - c) * _audit_math.log1p(-c)
    return _audit_KB * temp / area * _audit_J_M2_PER_EV_A2 * (-c * _audit_math.log(cb) + xlogx + one)

def _audit_entropy_prime(cb, c, temp, area):
    return _audit_KB * temp / area * _audit_J_M2_PER_EV_A2 * (_audit_math.log(c / (1 - c)) - _audit_math.log(cb))

@_audit_dataclass
class _audit_PathModel:
    condition: dict
    scenario: tuple
    x: _audit_np.ndarray
    w: _audit_np.ndarray
    eta: float
    eta_lo: float
    eta_hi: float
    occupancy_error: float
    derivative_error: float
    float_margin: float
    sigma: float
    temp: float
    cb: float
    alpha: float
    beta: float
    area: float
    site_a: _audit_np.ndarray
    gf_points: list
    usf_lower: list
    usf_upper: list
    coeff: str
    gamma_mode: str

    def occupancies(self, K):
        kb = _audit_KB * self.temp
        return _audit_logistic_vec((self.sigma * self.x[None, :] - self.eta - self.site_a[:, None] * K) / kb) @ self.w

    def site_bounds(self, Klo, Khi):
        kb = _audit_KB * self.temp
        qlo = _audit_logistic_vec((self.sigma * self.x[None, :] - self.eta_lo - self.site_a[:, None] * Klo) / kb) @ self.w
        qhi = _audit_logistic_vec((self.sigma * self.x[None, :] - self.eta_hi - self.site_a[:, None] * Khi) / kb) @ self.w
        return (_audit_np.maximum(0.0, qlo - self.occupancy_error), _audit_np.minimum(1.0, qhi + self.occupancy_error))

    def coverage_bounds(self, Klo, Khi):
        lo, hi = self.site_bounds(Klo, Khi)
        cl = (float(_audit_np.mean(lo[:9])), float(_audit_np.mean(hi[:9])))
        cs = (min(1.0, 1.5 * cl[0]), min(1.0, 1.5 * cl[1]))
        ce = (float(_audit_np.mean(lo[9:])), float(_audit_np.mean(hi[9:])))
        return (cl, cs, ce)

    def occupancy_derivatives(self, Klo, Khi):
        kb = _audit_KB * self.temp
        q0 = _audit_logistic_vec((self.sigma * self.x[None, :] - self.eta_lo - self.site_a[:, None] * Klo) / kb)
        q1 = _audit_logistic_vec((self.sigma * self.x[None, :] - self.eta_hi - self.site_a[:, None] * Khi) / kb)
        qlo = _audit_np.maximum(0.0, _audit_np.minimum(q0, q1) - self.occupancy_error)
        qhi = _audit_np.minimum(1.0, _audit_np.maximum(q0, q1) + self.occupancy_error)
        p0 = qlo * (1 - qlo)
        p1 = qhi * (1 - qhi)
        pmin = _audit_np.minimum(p0, p1)
        pmax = _audit_np.where((qlo <= 0.5) & (qhi >= 0.5), 0.25, _audit_np.maximum(p0, p1))
        scale = self.site_a / kb
        err = scale * self.derivative_error
        return (_audit_np.maximum(0.0, scale * (pmin @ self.w) - err), scale * (pmax @ self.w) + err)

    def coverage(self, K):
        c = self.occupancies(K)
        return (float(_audit_np.mean(c[:9])), min(1.0, 1.5 * float(_audit_np.mean(c[:9]))), float(_audit_np.mean(c[9:])))

    def cover_deriv(self, Klo, Khi):
        lo, hi = self.occupancy_derivatives(Klo, Khi)
        (_, _), (cslow, cshi), (cemitlo, cemithi) = self.coverage_bounds(Klo, Khi)
        dcl = (float(_audit_np.mean(lo[:9])), float(_audit_np.mean(hi[:9])))
        dce = (float(_audit_np.mean(lo[9:])), float(_audit_np.mean(hi[9:])))
        if cslow >= 1.0:
            dcs = (0.0, 0.0)
        elif cshi >= 1.0:
            dcs = (0.0, 1.5 * dcl[1])
        else:
            dcs = (1.5 * dcl[0], 1.5 * dcl[1])
        return ((cslow, cshi), (cemitlo, cemithi), dcs, dce)

    def residual(self, K, event):
        cc, cs, ce = self.coverage(K)
        if event == 'KIc':
            ge = _audit_interp(cs, self.gf_points)
            if ge is None:
                return float('nan')
            g = ge + _audit_entropy(self.cb, cs, self.temp, self.area)
            return self.alpha * g - 1000 * K * K
        gp = self.usf_lower if event == 'KIe_lower' else self.usf_upper
        val = _audit_interp(ce, gp)
        if val is None:
            return float('nan')
        return self.beta * val - 1000 * K * K

    def coverage_knots(self, event):
        if event == 'KIc':
            targets = [x for x, _ in self.gf_points]
            targets = [x / 1.5 for x in targets if x < 1.5]
            targets += [2 / 3]
            idx = slice(0, 9)
            fn = lambda k: self.coverage(k)[0]
        else:
            targets = [x for x, _ in self.usf_lower]
            idx = slice(9, 12)
            fn = lambda k: self.coverage(k)[2]
        vals = [0.0, 3.0]
        for t in sorted(set(targets)):
            f0 = fn(0) - t
            f1 = fn(3) - t
            if f0 == 0:
                vals.append(0.0)
            elif f1 == 0:
                vals.append(3.0)
            elif f0 * f1 < 0:
                a, b = (0.0, 3.0)
                for _ in range(64):
                    m = (a + b) / 2
                    if (fn(m) - t) * f0 <= 0:
                        b = m
                    else:
                        a = m
                vals.append((a + b) / 2)
        return sorted(set(vals))

    def gamma_slope_interval(self, lo, hi, event):
        if event == 'KIc':
            pts = self.gf_points
            _, coverage_lohi, _ = self.coverage_bounds(lo, hi)
            coverage_lo, coverage_hi = coverage_lohi
        else:
            pts = self.usf_lower if event == 'KIe_lower' else self.usf_upper
            _, _, ce = self.coverage_bounds(lo, hi)
            coverage_lo, coverage_hi = ce
        slopes = []
        for (x0, y0), (x1, y1) in zip(sorted(pts), sorted(pts)[1:]):
            if x1 >= coverage_lo - 1e-14 and x0 <= coverage_hi + 1e-14 and (x1 > x0):
                slopes.append((y1 - y0) / (x1 - x0))
        if not slopes:
            return (0.0, 0.0)
        return (min(slopes), max(slopes))

    def cover_deriv_bounds_only(self, lo, hi):
        (slo, shi), (elo, ehi), dcs, dce = self.cover_deriv(lo, hi)
        return (slo, shi, elo, ehi)

    def residual_bounds(self, lo, hi, event):
        (_, _), (slo, shi), (elo, ehi) = self.coverage_bounds(lo, hi)
        if event == 'KIc':
            gb = _audit_minmax_interp(slo, shi, self.gf_points)
            if gb is None:
                return None
            cstar = self.cb / (1 + self.cb)
            sb = [_audit_entropy(self.cb, slo, self.temp, self.area), _audit_entropy(self.cb, shi, self.temp, self.area)]
            if slo <= cstar <= shi:
                sb.append(_audit_entropy(self.cb, cstar, self.temp, self.area))
            kpart = (-1000 * hi * hi, -1000 * lo * lo)
            raw = (self.alpha * (gb[0] + min(sb)) + kpart[0], self.alpha * (gb[1] + max(sb)) + kpart[1])
            err = 64 * _audit_np.finfo(float).eps * max(1.0, abs(self.alpha * (gb[0] + min(sb))), abs(self.alpha * (gb[1] + max(sb))), 1000 * hi * hi)
            return (raw[0] - err, raw[1] + err)
        gp = self.usf_lower if event == 'KIe_lower' else self.usf_upper
        gb = _audit_minmax_interp(elo, ehi, gp)
        if gb is None:
            return None
        raw = (self.beta * gb[0] - 1000 * hi * hi, self.beta * gb[1] - 1000 * lo * lo)
        err = 64 * _audit_np.finfo(float).eps * max(1.0, abs(self.beta * gb[0]), abs(self.beta * gb[1]), 1000 * hi * hi)
        return (raw[0] - err, raw[1] + err)

    def derivative_bounds(self, lo, hi, event):
        (_, _), (slo, shi), (elo, ehi) = self.coverage_bounds(lo, hi)
        _, _, dcs, dce = self.cover_deriv(lo, hi)
        if event == 'KIc':
            if slo >= 1.0:
                return (-2000 * hi - 64 * _audit_np.finfo(float).eps * max(1.0, 2000 * hi), -2000 * lo + 64 * _audit_np.finfo(float).eps * max(1.0, 2000 * lo))
            slopes = self.gamma_slope_interval(lo, hi, event)
            c0 = max(slo, 1e-300)
            c1 = min(shi, 1 - 1e-15)
            if c0 >= 1 or c1 <= 0:
                return (-_audit_math.inf, _audit_math.inf)
            sp = (_audit_entropy_prime(self.cb, c0, self.temp, self.area), _audit_entropy_prime(self.cb, c1, self.temp, self.area))
            A = (slopes[0] + sp[0], slopes[1] + sp[1])
            products = [A[0] * dcs[0], A[0] * dcs[1], A[1] * dcs[0], A[1] * dcs[1]]
            q = (self.alpha * min(products) - 2000 * hi, self.alpha * max(products) - 2000 * lo)
            if shi >= 1 - 1e-14 and slo < 1 and (dcs[1] > 0):
                q = (q[0], _audit_math.inf)
            err = 64 * _audit_np.finfo(float).eps * max(1.0, abs(q[0]), abs(q[1]))
            return (q[0] - err, q[1] + err)
        slopes = self.gamma_slope_interval(lo, hi, event)
        products = [slopes[0] * dce[0], slopes[0] * dce[1], slopes[1] * dce[0], slopes[1] * dce[1]]
        raw = (self.beta * min(products) - 2000 * hi, self.beta * max(products) - 2000 * lo)
        err = 64 * _audit_np.finfo(float).eps * max(1.0, abs(raw[0]), abs(raw[1]))
        return (raw[0] - err, raw[1] + err)

def _audit_bisect_eta(cb, sigma, temp, x, w):
    kb = _audit_KB * temp

    def q(eta):
        return float(_audit_logistic_vec((sigma * x - eta) / kb) @ w)
    a, b = (-3.0, 3.0)
    for _ in range(90):
        m = (a + b) / 2
        if q(m) < cb:
            a = m
        else:
            b = m
    return (a + b) / 2

def _audit_eta_enclosure(cb, sigma, temp, x, w, order):
    bound = _audit_tail_error_bound(order, sigma, temp)
    float_margin = 2e-14
    total = bound + float_margin
    kb = _audit_KB * temp

    def q(eta):
        return float(_audit_logistic_vec((sigma * x - eta) / kb) @ w)

    def solve(target, choose_left):
        if target <= 0:
            return -100.0
        if target >= 1:
            return 100.0
        lo, hi = (-5.0, 5.0)
        for _ in range(90):
            mid = (lo + hi) / 2
            if q(mid) < target:
                lo = mid
            else:
                hi = mid
        return lo if choose_left else hi
    return (solve(cb - total, True), solve(cb + total, False), total, float_margin)

def _audit_isolate_roots(model, event, max_depth=26):
    certs = []
    roots = []
    unresolved = []

    def cert(a, b, kind, bounds, deriv=None, sa=None, sb=None, root_interval=None):
        certs.append({'K_interval': [a, b], 'kind': kind, 'residual_bounds': bounds, 'derivative_bounds': deriv, 'endpoint_signs': [sa, sb] if sa is not None and sb is not None else None, 'endpoint_residual_bounds': [model.residual_bounds(a, a, event), model.residual_bounds(b, b, event)], 'root_interval': root_interval})

    def point_sign(k):
        b = model.residual_bounds(k, k, event)
        if b is None:
            return 0
        if b[0] > 0:
            return 1
        if b[1] < 0:
            return -1
        return 0

    def refine_bracket(a, b, sa, sb):
        while b - a > 1e-08:
            m = (a + b) / 2
            left = model.residual_bounds(a, m, event)
            right = model.residual_bounds(m, b, event)
            left_has = left is not None and left[0] <= 0 <= left[1]
            right_has = right is not None and right[0] <= 0 <= right[1]
            if left_has and (not right_has):
                b = m
                sb = point_sign(b)
            elif right_has and (not left_has):
                a = m
                sa = point_sign(a)
            elif left_has and right_has:
                sm = point_sign(m)
                if sm == sa:
                    a = m
                    sa = sm
                elif sm == sb:
                    b = m
                    sb = sm
                else:
                    break
            else:
                break
        return (a, b)

    def walk(a, b, depth):
        bounds = model.residual_bounds(a, b, event)
        if bounds is None:
            unresolved.append({'K_interval': [a, b], 'reason': 'coverage_outside_source_domain', 'residual_bounds': None})
            return
        if bounds[0] > 0 or bounds[1] < 0:
            cert(a, b, 'range_excludes_zero', bounds)
            return
        deriv = model.derivative_bounds(a, b, event)
        monotone = deriv[0] > 0 or deriv[1] < 0
        if monotone:
            sa, sb = (point_sign(a), point_sign(b))
            if sa * sb < 0:
                left, right = refine_bracket(a, b, sa, sb)
                if right - left <= 1e-08:
                    roots.append((left, right, 'derivative_interval_proves_unique_root'))
                    cert(a, b, 'unique_sign_change_root', bounds, deriv, sa, sb, [left, right])
                    return
                unresolved.append({'K_interval': [left, right], 'reason': 'root_bracket_not_reduced_below_1e-8', 'residual_bounds': model.residual_bounds(left, right, event), 'derivative_bounds': deriv})
                return
            if sa and sb and (sa == sb):
                cert(a, b, 'monotone_same_sign_no_root', bounds, deriv, sa, sb)
                return
        if depth >= max_depth:
            unresolved.append({'K_interval': [a, b], 'reason': 'zero_in_interval_bound_without_uniqueness', 'residual_bounds': bounds, 'derivative_bounds': deriv})
            return
        m = (a + b) / 2
        walk(a, m, depth + 1)
        walk(m, b, depth + 1)
    knots = model.coverage_knots(event)
    for a, b in zip(knots, knots[1:]):
        walk(a, b, 0)
    roots.sort(key=lambda r: r[0])
    dedup = []
    for root in roots:
        if dedup and root[0] <= dedup[-1][1] + 1e-10:
            dedup[-1] = (min(dedup[-1][0], root[0]), max(dedup[-1][1], root[1]), 'overlapping_certified_knot_root')
        else:
            dedup.append(root)
    return (dedup, certs, unresolved)

def _audit_build_model(cond, scenario, assets, x, w, order):
    density = {r['alloy']: r for r in _audit_read_csv(assets / 'absorption_distribution_fig2a.csv')}
    elastic = {r['alloy']: r for r in _audit_read_csv(assets / 'elastic_constants_fig2a.csv')}
    a0 = {r['alloy']: float(r['a0_A']) for r in _audit_read_csv(assets / 'lattice_parameters_A0.csv')}
    coords = {}
    for r in _audit_read_csv(assets / 'task11_crack_site_coordinates.csv'):
        coords.setdefault(r['alloy'], []).append((int(r['site_column']), float(r['r_A']), float(r['theta_rad'])))
    gfall = {}
    for r in _audit_read_csv(assets / 'gamma_f_fig2b_digitized.csv'):
        gfall.setdefault(r['alloy'], []).append((float(r['C_surface']), float(r['gamma_F_mean_J_m2']), float(r['gamma_F_low_J_m2']), float(r['gamma_F_high_J_m2'])))
    usfall = {}
    for r in _audit_read_csv(assets / 'gamma_usf_fig2c_parameters.csv'):
        usfall.setdefault(r['alloy'], []).append((float(r['coverage_Cusf']), float(r['gamma_usf_mean_mJ_m2']), float(r['gamma_usf_std_DFT_mJ_m2'])))
    name, tref, width, area_band, gfband = scenario
    alloy = cond['alloy']
    temp = cond['T']
    cb = cond['Cb']
    sig = float(density[alloy]['sigma_eV']) * (_audit_math.sqrt(2) if width == 'caption_sd' else 1.0)
    eta = _audit_bisect_eta(cb, sig, temp, x, w)
    el = elastic[alloy]
    nu = _audit_hill_nu(float(el['C11_GPa']), float(el['C12_GPa']), float(el['C44_GPa']))
    aa = []
    for _, rA, theta in sorted(coords[alloy]):
        psl = _audit_pressure_slope_pa_per_mpa(rA * 1e-10, theta, nu)
        aa.append(psl * 2.8e-30 * _audit_EV_PER_J)
    gpoints = []
    area = fcc_area = float(_audit_math.sqrt(3) * a0[alloy] ** 2 / 4)
    for cs, gm, gl, gh in gfall[alloy]:
        gv = {'center': gm, 'low': gl, 'high': gh}[gfband]
        sref = _audit_entropy(0.0058, cs, tref, fcc_area)
        gpoints.append((cs, gv - sref))
    upoints = []
    lpoints = []
    usf = usfall[alloy]
    for c, mean, std in usf:
        spread = std * _audit_math.sqrt(108 / area_band)
        upoints.append((c, mean / 1000))
        lpoints.append((c, (mean - spread) / 1000))
    alpha = float(el['alpha_GPa'])
    beta = float(el['beta_GPa'])
    if order == 768:
        eta_lo, eta_hi, Bocc, float_margin = _audit_eta_enclosure(cb, sig, temp, x, w, order)
    else:
        eta_lo = eta_hi = eta
        Bocc = 0.0
        float_margin = 0.0
    analytic = max(0.0, Bocc - float_margin)
    deriv_error = 0.5 * max(0.0, analytic - _audit_math.erfc(_audit_L)) + 0.25 * _audit_math.erfc(_audit_L) + float_margin
    return _audit_PathModel(cond, scenario, x, w, eta, eta_lo, eta_hi, Bocc, deriv_error, float_margin, sig, temp, cb, alpha, beta, fcc_area, _audit_np.asarray(aa), gpoints, lpoints, upoints, '', gfband)

def _audit_scenario_list():
    return [('baseline', 300.0, 'printed_scale', 50.0, 'center'), ('Tref400', 400.0, 'printed_scale', 50.0, 'center'), ('caption_width', 300.0, 'caption_sd', 50.0, 'center'), ('area30', 300.0, 'printed_scale', 30.0, 'center'), ('area70', 300.0, 'printed_scale', 70.0, 'center'), ('gammaF_low', 300.0, 'printed_scale', 50.0, 'low'), ('gammaF_high', 300.0, 'printed_scale', 50.0, 'high')]

def _audit_make_conditions(assets):
    exp = _audit_read_csv(assets / 'task13_experiment_conditions.csv')
    cs = [{'condition': f"fig3-panel-{r['panel_row']}-{r['panel_col']}", 'alloy': r['alloy'], 'Cb': int(r['Cb_appm_as_printed']) / 1000000.0, 'T': float(r['T_K_model_reference']), 'panel_row': int(r['panel_row']), 'panel_col': int(r['panel_col'])} for r in exp]
    alloys = sorted({r['alloy'] for r in _audit_read_csv(assets / 'absorption_distribution_fig2a.csv')})
    for a in alloys:
        for T in (300.0, 400.0):
            cs.append({'condition': f'common-{a}-Cb5800-T{int(T)}', 'alloy': a, 'Cb': 0.0058, 'T': T, 'panel_row': 0, 'panel_col': 0})
    return cs

make_conditions = _audit_make_conditions
scenario_list = _audit_scenario_list
build_model = _audit_build_model
quad = _audit_quad
isolate_roots = _audit_isolate_roots
interp = _audit_interp
entropy = _audit_entropy

import argparse, csv, hashlib, json, math
from pathlib import Path
import numpy as np

def read_csv(path):
    with path.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def sha(path):return 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
def source_interval_matches(observed, expected):
    """Compare source interval values, allowing equivalent JSON formatting."""
    try:
        values = [json.loads(raw) for raw in (observed, expected)]
        if any(not isinstance(v, list) or len(v) != 2 for v in values):
            return False
        if any(type(x) not in (int, float) or not math.isfinite(x)
               for v in values for x in v):
            return False
        return values[0] == values[1]
    except (TypeError, ValueError, OverflowError):
        return False

def classify_from_roots(kc,kl,ku):
    if kc is None:return 'no_cleavage_crossing_in_[0,3]'
    if kl is None or ku is None:return 'domain_incomplete'
    if kc[1]<kl[0]:return 'embrittled'
    if kc[0]>ku[1]:return 'not_embrittled'
    return 'uncertain'

def finite(row,keys):
    for key in keys:
        try:v=float(row[key])
        except Exception as e:raise AssertionError(f'{key} is not numeric') from e
        if not math.isfinite(v):raise AssertionError(f'{key} is non-finite')
    return [float(row[k]) for k in keys]

def _interval_contains(candidate, independent, label):
    if not isinstance(candidate,(list,tuple)) or len(candidate)!=2 or independent is None or len(independent)!=2:
        raise AssertionError(label+' enclosure is missing')
    got=[float(x) for x in candidate]; want=[float(x) for x in independent]
    if any(not math.isfinite(x) for x in got+want) or got[0]>got[1] or want[0]>want[1]:
        raise AssertionError(label+' enclosure is malformed')
    if got[0]>want[0]+max(1e-14,abs(want[0])*1e-11) or got[1]<want[1]-max(1e-14,abs(want[1])*1e-11):
        raise AssertionError(label+' enclosure is not conservative')
    return got

def _definite_sign(bounds):
    if bounds[0]>0:return 1
    if bounds[1]<0:return -1
    return 0

def validate_interval_certificate(cert,reported_roots,reported_segments,unresolved_segments,
                                  independent_roots,model,event,key):
    """Validate any sound partition, without requiring the scorer's own subdivision tree."""
    if not isinstance(cert,list) or any(not isinstance(seg,dict) for seg in cert):
        raise AssertionError('certificate_details must be a JSON array of objects')
    if isinstance(reported_segments,bool) or int(reported_segments)!=len(cert) or int(unresolved_segments)!=0:
        raise AssertionError('certificate segment accounting mismatch')
    if not cert:raise AssertionError('certificate does not cover [0,3]')
    intervals=[]
    for seg in cert:
        raw=seg.get('K_interval')
        if not isinstance(raw,(list,tuple)) or len(raw)!=2:raise AssertionError('certificate K interval is malformed')
        lo,hi=map(float,raw)
        if not (math.isfinite(lo) and math.isfinite(hi) and 0<=lo<hi<=3):raise AssertionError('certificate K interval is outside [0,3] or unordered')
        intervals.append((lo,hi))
    if abs(intervals[0][0])>1e-12 or abs(intervals[-1][1]-3)>1e-10:raise AssertionError('certificate does not cover [0,3]')
    for (_,end),(start,_) in zip(intervals,intervals[1:]):
        if abs(end-start)>1e-10:raise AssertionError('certificate segments have a gap/overlap')
    roots=[]
    for raw in reported_roots:
        if not isinstance(raw,(list,tuple)) or len(raw)!=2:raise AssertionError('root intervals must be finite ordered enclosures')
        lo,hi=map(float,raw)
        if not (math.isfinite(lo) and math.isfinite(hi) and 0<=lo<=hi<=3 and hi-lo<=1e-8):raise AssertionError('root intervals must be finite ordered enclosures inside [0,3]')
        roots.append((lo,hi))
    if len(roots)!=len(independent_roots):raise AssertionError('root count mismatch: '+str(key))
    for got,want in zip(roots,independent_roots):
        if max(abs(got[i]-float(want[i])) for i in (0,1))>1e-8:raise AssertionError('root enclosure mismatch: '+str(key))
    if sum(seg.get('kind')=='unique_sign_change_root' for seg in cert)!=len(independent_roots):
        raise AssertionError('unique-root bracket proof count mismatch')
    allowed={'range_excludes_zero','monotone_same_sign_no_root','unique_sign_change_root'}
    matched_reported_roots=set()
    for seg,(lo,hi) in zip(cert,intervals):
        kind=seg.get('kind')
        if kind not in allowed:raise AssertionError('unresolved or unsupported segment kind')
        independent=model.residual_bounds(lo,hi,event)
        rb=_interval_contains(seg.get('residual_bounds'),independent,'residual')
        if kind=='range_excludes_zero' and not (rb[0]>0 or rb[1]<0):
            raise AssertionError('range certificate does not exclude zero')
        db=None; dind=None
        if kind in {'monotone_same_sign_no_root','unique_sign_change_root'}:
            dind=model.derivative_bounds(lo,hi,event)
            db=_interval_contains(seg.get('derivative_bounds'),dind,'derivative')
            if not (db[0]>0 or db[1]<0):raise AssertionError('derivative certificate does not establish monotonicity')
        if kind in {'monotone_same_sign_no_root','unique_sign_change_root'}:
            ep=seg.get('endpoint_residual_bounds')
            if not isinstance(ep,(list,tuple)) or len(ep)!=2:raise AssertionError('certificate endpoint residual bounds missing')
            independent_ep=[model.residual_bounds(lo,lo,event),model.residual_bounds(hi,hi,event)]
            checked_ep=[_interval_contains(got,want,'endpoint residual') for got,want in zip(ep,independent_ep)]
            signs=[_definite_sign(x) for x in independent_ep]
            if [_definite_sign(x) for x in checked_ep]!=signs:
                raise AssertionError('endpoint residual bounds do not establish their declared signs')
            declared=seg.get('endpoint_signs')
            if not isinstance(declared,(list,tuple)) or len(declared)!=2 or [int(x) for x in declared]!=signs or 0 in signs:
                raise AssertionError('endpoint signs disagree with independent endpoint bounds')
            if kind=='unique_sign_change_root' and signs[0]*signs[1]>=0:
                raise AssertionError('unique root bracket lacks independently verified sign change')
            if kind=='monotone_same_sign_no_root' and signs[0]*signs[1]<=0:
                raise AssertionError('same-sign root exclusion has opposing endpoint signs')
        if kind=='unique_sign_change_root':
            bracket=seg.get('root_interval')
            if not isinstance(bracket,(list,tuple)) or len(bracket)!=2:raise AssertionError('root bracket missing')
            blo,bhi=map(float,bracket)
            if not (math.isfinite(blo) and math.isfinite(bhi) and lo<=blo<=bhi<=hi and bhi-blo<=1e-8):
                raise AssertionError('root bracket width/domain invalid')
            matches=[i for i,(rlo,rhi) in enumerate(roots)
                     if max(abs(blo-rlo),abs(bhi-rhi))<=1e-12]
            if len(matches)!=1 or matches[0] in matched_reported_roots:
                raise AssertionError('each certified root must match exactly one reported root interval')
            matched_reported_roots.add(matches[0])
            if not (rb[0]<=0<=rb[1]):raise AssertionError('root segment residual enclosure excludes zero')
            if not any(blo<=float(root[0])+1e-12 and bhi>=float(root[1])-1e-12 for root in independent_roots):
                # A narrower/shifted reported enclosure is admissible only when independent
                # endpoint enclosures prove an actual sign-changing root in that bracket.
                bracket_ep=[model.residual_bounds(blo,blo,event),model.residual_bounds(bhi,bhi,event)]
                bracket_signs=[_definite_sign(x) for x in bracket_ep]
                if 0 in bracket_signs or bracket_signs[0]*bracket_signs[1]>=0:
                    raise AssertionError('root bracket does not enclose the independent root or a proven sign change')
    if matched_reported_roots!=set(range(len(roots))):
        raise AssertionError('reported root intervals are not matched one-to-one to certified roots')
    return roots

def preflight(app,tests):
    try:refs=json.loads((tests/'refs.json').read_text(encoding='utf8'))
    except Exception as e:raise RuntimeError(f'integrity failure: refs.json: {type(e).__name__}') from e
    if not isinstance(refs,dict) or refs.get('case_id')!='case-07':raise RuntimeError('integrity failure: refs.json case/schema')
    for group,base in ((refs.get('asset_hashes',{}),app),(refs.get('grader_reference_hashes',{}),tests)):
        if not isinstance(group,dict) or (base==app and not group):raise RuntimeError('integrity failure: empty public input hash manifest')
        for rel,digest in group.items():
            if not isinstance(rel,str) or not isinstance(digest,str) or not digest.startswith('sha256:'):
                raise RuntimeError('integrity failure: malformed hash manifest entry')
            p=base/rel.removeprefix('tests/') if base==tests else base/rel
            try:actual=sha(p)
            except Exception as e:raise RuntimeError(f'integrity failure: {rel}: {type(e).__name__}') from e
            if actual!=digest:raise RuntimeError(f'integrity failure: {rel}: hash mismatch')
        subdir='references' if base==tests else 'assets'
        expected={str(p.relative_to(base)) for p in (base/subdir).rglob('*') if p.is_file()}
        actual={name.removeprefix('tests/') for name in group} if base==tests else set(group)
        if actual!=expected:raise RuntimeError('integrity failure: incomplete or extra input hash manifest')
    tables=refs.get('reference_tables')
    required_tables={'task13_fig3_first_crossing_intervals.csv':24,'task13_fig3_panel_inventory_reference.csv':16,'task13_wada_ni_condition_intervals.csv':4}
    if not isinstance(tables,dict) or set(tables)!=set(required_tables):raise RuntimeError('integrity failure: reference tables missing or extra')
    for name,count in required_tables.items():
        rows=tables[name]
        if not isinstance(rows,list) or len(rows)!=count or not all(isinstance(row,dict) for row in rows):raise RuntimeError('integrity failure: malformed reference table '+name)
        digest='sha256:'+hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if refs.get('reference_table_hashes',{}).get(name)!=digest:raise RuntimeError('integrity failure: reference table hash '+name)
    return refs

def verify(app,tests,final):
    refs=preflight(app,tests)
    # Missing answer artifacts are candidate failures; corrupt grader/public data was handled above.
    required=('forward_curves.csv','first_crossings.csv','source_comparison.csv','ni_comparison.csv','prediction_limits.json','calculation_source.py','model.py','interval_audit.py','run_metadata.json')
    for name in required:
        if not (final/name).is_file():raise AssertionError('missing required output: '+name)
    # Reject an unsupported certainty claim before the expensive independent
    # interval recomputation.  These are structured scientific scope fields,
    # not prose substring checks.
    limits=json.loads((final/'prediction_limits.json').read_text())
    if not isinstance(limits,dict):raise AssertionError('prediction_limits.json must be a JSON object')
    required_limitations={'engineering_floating_point_margin_not_outward_rounded',
      'analytic_quadrature_tail_bound_is_model_assumption_dependent',
      'piecewise_linear_interpolants_from_digitized_source_data'}
    if limits.get('certificate_type')!='fixed_quadrature_refinement_only':raise AssertionError('unsupported numerical certificate type')
    if limits.get('formal_directed_rounding_ieee_proof') is not False or limits.get('formal_proof_scope')!='not_claimed':raise AssertionError('numerical proof scope is overstated')
    if not isinstance(limits.get('numerical_limitations'),list) or any(not isinstance(x,str) for x in limits['numerical_limitations']) or not required_limitations.issubset(set(limits['numerical_limitations'])):raise AssertionError('numerical certificate limitations are incomplete')
    meta=json.loads((final/'run_metadata.json').read_text())
    if not isinstance(meta,dict):raise AssertionError('run_metadata.json must be a JSON object')
    if not isinstance(meta.get('calculation_sources'),list) or any(not isinstance(x,dict) or not isinstance(x.get('name'),str) or not isinstance(x.get('sha256'),str) for x in meta['calculation_sources']):raise AssertionError('calculation_sources must be an array of objects with string name and sha256')
    if meta.get('schema')!='compchemworld-calculation-run/v1':raise AssertionError('calculation run metadata schema mismatch')
    for src in meta.get('calculation_sources',[]):
        p=final/src.get('name','')
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=str(src.get('sha256','')).removeprefix('sha256:'):raise AssertionError('calculation source hash mismatch')
    if {x.get('name') for x in meta.get('calculation_sources',[])}!={'calculation_source.py','model.py','interval_audit.py'}:raise AssertionError('all executable calculation components must be declared')
    assets=app/'assets'
    input_hashes=meta.get('inputs',{})
    if not isinstance(input_hashes,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in input_hashes.items()):raise AssertionError('inputs must be a string-to-string JSON object')
    actual_inputs={p.name:sha(p) for p in assets.iterdir() if p.is_file()}
    if input_hashes!={k:v.removeprefix('sha256:') for k,v in actual_inputs.items()}:raise AssertionError('run metadata must hash every public input exactly')
    curves=read_csv(final/'forward_curves.csv'); crossings=read_csv(final/'first_crossings.csv')
    comp=read_csv(final/'source_comparison.csv'); ni=read_csv(final/'ni_comparison.csv')
    conditions=make_conditions(assets); scenarios=scenario_list()
    elastic={r['alloy']:r for r in read_csv(assets/'elastic_constants_fig2a.csv')}
    expected_curve_n=len(conditions)*len(scenarios)*301
    if len(curves)!=expected_curve_n:raise AssertionError(f'forward curve row count: expected {expected_curve_n}')
    # CSV decimal round-tripping and numpy.linspace can differ by one ulp.
    # The declared K grid is 0.01 MPa sqrt(m), so compare its canonical 12dp key.
    ckeys=[(r['condition'],r['scenario'],round(float(r['Kapp']),12)) for r in curves]
    if len(set(ckeys))!=len(curves):raise AssertionError('duplicate forward curve points')
    curve_idx={(r['condition'],r['scenario'],round(float(r['Kapp']),12)):r for r in curves}
    expected_cross={(c['condition'],s[0],e) for c in conditions for s in scenarios for e in ('KIc','KIe_lower','KIe_upper_athermal_mean')}
    cidx={(r['condition'],r['scenario'],r['event']):r for r in crossings}
    if len(cidx)!=len(crossings) or set(cidx)!=expected_cross:raise AssertionError('first-crossing key domain is incomplete or duplicated')
    cert_rows=read_csv(final/'interval-audit/first_root_interval_certificates.csv')
    cert768=[r for r in cert_rows if int(r['quadrature_order'])==768]
    certidx={(r['condition'],r['scenario'],r['event']):r for r in cert768}
    if len(certidx)!=len(cert768) or set(certidx)!=expected_cross:raise AssertionError('GL768 interval-certificate key domain is incomplete or duplicated')
    # Check the forward physical identities for every emitted row, including unit conversions.
    for r in curves:
        eta,cC,ce,cS=finite(r,['eta','Ccleave','Cemit','CS'])
        if not (0<=cC<=1 and 0<=ce<=1):raise AssertionError('coverage outside [0,1]')
        if abs(cS-min(1,1.5*cC))>2e-8:raise AssertionError('surface coverage relation mismatch')
        if r['domain_state']=='valid':
            gE,gS,gF,gmean,gspread,kic,kiel,kiu=finite(r,['gammaE','gammaS','gammaF','gammausf_mean','gammausf_spread','KIc','KIe_lower','KIe_upper_athermal_mean'])
            if abs(gF-(gE+gS))>2e-8:raise AssertionError('gammaF energy sum mismatch')
            par=elastic[r['alloy']];alpha=float(par['alpha_GPa']);beta=float(par['beta_GPa'])
            wantc=math.sqrt(alpha*gF/1000);wantlo=math.sqrt(beta*(gmean-gspread)/1000);wanthi=math.sqrt(beta*gmean/1000)
            if abs(kic-wantc)>2e-6 or abs(kiel-wantlo)>2e-6 or abs(kiu-wanthi)>2e-6:raise AssertionError('KI units/formula mismatch')
        elif r['domain_state']!='invalid_negative_energy':raise AssertionError('unknown physical-domain state')
    # Recompute all certified roots from public inputs with independent GL768 interval enclosures.
    x,w=quad(768); x192,w192=quad(192); expected_roots={}; expected_models={}
    for cond in conditions:
        for scenario in scenarios:
            model=build_model(cond,scenario,assets,x,w,768)
            model192=build_model(cond,scenario,assets,x192,w192,192)
            for K in np.linspace(0,3,301):
                ckey=(cond['condition'],scenario[0],round(float(K),12)); actual=curve_idx.get(ckey)
                if actual is None:raise AssertionError('missing forward model point '+str(ckey))
                def derived(m):
                    cl,cs,ce=m.coverage(float(K)); ge=interp(cs,m.gf_points); gs=entropy(m.cb,cs,m.temp,m.area)
                    gm=interp(ce,m.usf_upper); gl=interp(ce,m.usf_lower); gf=None if ge is None else ge+gs
                    if gf is None or gm is None or gl is None or gf<0 or gl<0:return {'eta':m.eta,'Ccleave':cl,'CS':cs,'Cemit':ce,'domain_state':'invalid_negative_energy'}
                    return {'eta':m.eta,'Ccleave':cl,'CS':cs,'Cemit':ce,'gammaE':ge,'gammaS':gs,'gammaF':gf,'gammausf_mean':gm,'gammausf_spread':gm-gl,'KIc':math.sqrt(m.alpha*gf/1000),'KIe_lower':math.sqrt(m.beta*gl/1000),'KIe_upper_athermal_mean':math.sqrt(m.beta*gm/1000),'domain_state':'valid'}
                hi=derived(model); low=derived(model192)
                if actual['domain_state']!=hi['domain_state']:raise AssertionError('forward model domain mismatch '+str(ckey))
                if hi['domain_state']=='valid':
                    for field in ('eta','Ccleave','CS','Cemit','gammaE','gammaS','gammaF','gammausf_mean','gammausf_spread','KIc','KIe_lower','KIe_upper_athermal_mean'):
                        got=float(actual[field]); v768=float(hi[field]); v192=float(low[field]); tol=abs(v768-v192)+max(2e-7,2e-7*abs(v768))
                        if abs(got-v768)>tol:raise AssertionError(f'forward {field} differs from independently recomputed GL768 value at {ckey}')
                else:
                    for field in ('eta','Ccleave','CS','Cemit'):
                        if abs(float(actual[field])-float(hi[field]))>2e-7:raise AssertionError('invalid-domain forward model field mismatch')
            for event in ('KIc','KIe_lower','KIe_upper_athermal_mean'):
                roots,segments,unresolved=isolate_roots(model,event,26)
                expected_roots[(cond['condition'],scenario[0],event)]=(roots,segments,unresolved)
                expected_models[(cond['condition'],scenario[0],event)]=model
    for key,crossing in cidx.items():
        r=certidx[key]
        roots,segments,unresolved=expected_roots[key]
        if unresolved:raise AssertionError('independent interval refinement did not resolve entire domain: '+str(key))
        candidate_roots=json.loads(r['root_intervals_MPa_sqrt_m'])
        cert=json.loads(r['certificate_details'])
        validate_interval_certificate(cert,candidate_roots,r['certificate_segments'],
                                      r['unresolved_segments'],roots,expected_models[key],key[2],key)
        if r['status'] not in {'certified_all_roots_and_first','certified_no_root_on_[0,3]'}:raise AssertionError('certificate status is not complete')
        if roots:
            reported=json.loads(crossing['Kapp_root_or_interval'])
            if max(abs(float(reported[i])-candidate_roots[0][i]) for i in (0,1))>1e-8 or not crossing['first_root_certificate']:raise AssertionError('reported event is not first certified root')
        elif not crossing['no_root_in_scan_reason'].startswith('certified no root in [0,3]'):raise AssertionError('no-root case lacks bounded-domain declaration')
    crossing_rows=read_csv(final/'first_crossings.csv')
    expected_crossing_keys={(c['condition'],s[0],e) for c in conditions for s in scenarios for e in ('KIc','KIe_lower','KIe_upper_athermal_mean')}
    crossing_idx={(r['condition'],r['scenario'],r['event']):r for r in crossing_rows}
    if len(crossing_idx)!=len(crossing_rows) or set(crossing_idx)!=expected_crossing_keys:raise AssertionError('first-crossing event/classification key domain is incomplete or duplicated')
    for (condition,scenario,event),row in crossing_idx.items():
        roots_for=lambda e: json.loads(certidx[(condition,scenario,e)]['root_intervals_MPa_sqrt_m'])
        first=lambda e: roots_for(e)[0] if roots_for(e) else None
        expected_class=classify_from_roots(first('KIc'),first('KIe_lower'),first('KIe_upper_athermal_mean'))
        if row['classification']!=expected_class:raise AssertionError('first-crossing classification disagrees with certified root intervals')
    source_roots=refs['reference_tables']['task13_fig3_first_crossing_intervals.csv']
    panel_labels=refs['reference_tables']['task13_fig3_panel_inventory_reference.csv']
    if len(comp)!=24 or len(source_roots)!=24:raise AssertionError('expected 24 source-panel event comparisons')
    labels={(int(r['panel_row']),int(r['panel_col'])):r for r in panel_labels}
    event_map={'Kc':'KIc','Ke_lower':'KIe_lower','Ke_earliest':'KIe_lower','Ke_upper':'KIe_upper_athermal_mean'}
    compidx={(r['panel'],r['model_event']):r for r in comp}
    if len(compidx)!=len(comp):raise AssertionError('duplicate source comparison key')
    for obs in source_roots:
        panel=f"fig3-panel-{obs['panel_row']}-{obs['panel_col']}";event=event_map[obs['crossing_kind']]
        record=compidx.get((panel,event))
        if record is None:raise AssertionError('source-root comparison missing '+panel+'/'+event)
        srcint=list(map(float,json.loads(obs['Kapp_interval_MPa_sqrt_m'])))
        gotint=list(map(float,json.loads(record['source_root_interval_MPa_sqrt_m'])))
        if max(abs(a-b) for a,b in zip(srcint,gotint))>1e-10:raise AssertionError('source observation interval mismatch')
        lab=labels[(int(obs['panel_row']),int(obs['panel_col']))]
        if record['source_experiment_class']!=lab['experimental_class_as_printed'] or record['source_theory_class']!=lab['source_theory_class_as_printed']:
            raise AssertionError('experimental and theoretical source classes must be independently reported as printed')
        roots=json.loads(certidx[(panel,'baseline',event)]['root_intervals_MPa_sqrt_m'])
        if not roots:raise AssertionError('source event has no independently calculated model root')
        modint=list(map(float,json.loads(record['model_root_interval_MPa_sqrt_m'])))
        if max(abs(a-b) for a,b in zip(roots[0],modint))>1e-8:raise AssertionError('source comparison does not report the model first root')
        overlap=max(roots[0][0],srcint[0])<=min(roots[0][1],srcint[1])
        if str(record['interval_overlap']).lower()!=str(overlap).lower():raise AssertionError('source interval overlap mismatch')
        baseline=[json.loads(certidx[(panel,'baseline',e)]['root_intervals_MPa_sqrt_m']) for e in ('KIc','KIe_lower','KIe_upper_athermal_mean')]
        cls=classify_from_roots(*(z[0] if z else None for z in baseline))
        if record['model_class']!=cls:raise AssertionError('source comparison model class disagrees with certified root ordering')
    ni_refs=refs['reference_tables']['task13_wada_ni_condition_intervals.csv']
    if len(ni)!=4 or len(ni_refs)!=4:raise AssertionError('expected four independent Ni source groups')
    niidx={r['charging_pressure_MPa']:r for r in ni}
    for src in ni_refs:
        got=niidx.get(src['charging_pressure_MPa'])
        if got is None:raise AssertionError('missing Ni pressure group')
        wtlo,wthi=map(float,json.loads(src['lattice_cH1_wt_ppm_interval']))
        def atppm(wtppm):
            wt=wtppm*1e-6;return 1e6*(58.6934*wt/(1.00794*(1-wt)+58.6934*wt))
        expected=[math.floor(atppm(wtlo)*10)/10,math.ceil(atppm(wthi)*10)/10]
        reported=json.loads(got['lattice_cH1_atppm_recomputed'])
        if max(abs(float(a)-b) for a,b in zip(reported,expected))>1e-9:raise AssertionError('Ni wtppm-to-atppm conversion mismatch')
        for key,source_key in {'lattice_cH1_wtppm':'lattice_cH1_wt_ppm_interval','RRA':'RRA_interval_Fig5-16','MTS_MPa':'MTS_MPa_interval_Fig5-16','fracture_context':'Fig5-17_fracture_observation'}.items():
            matches=(got[key]==src[source_key] if key=='fracture_context'
                     else source_interval_matches(got[key],src[source_key]))
            if not matches:raise AssertionError('Ni source observation changed: '+key)
        if 'no Ni' not in got['out_of_domain_reason'] and 'No Ni' not in got['out_of_domain_reason']:raise AssertionError('Ni threshold must remain out of domain')
    if limits.get('ni_scope')!='out_of_domain_no_ki_threshold':raise AssertionError('Ni applicability boundary is missing or overstated')
    # Output hashes are checked after scoring outputs were complete.
    output_hashes=meta.get('outputs',{})
    if not isinstance(output_hashes,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in output_hashes.items()):raise AssertionError('outputs must be a string-to-string JSON object')
    for name,digest in output_hashes.items():
        if name in {'run_metadata.json'}:continue
        p=final/name
        if not p.is_file() or sha(p).removeprefix('sha256:')!=digest:raise AssertionError('run output hash mismatch: '+name)
    return {'status':'PASS','reward':1,'curve_rows':len(curves),'certified_events':len(cidx),'interval_engine':'GL768 fixed quadrature interval refinement','unresolved_segments':0}

def main():
    p=argparse.ArgumentParser();p.add_argument('--app-dir',type=Path,required=True);p.add_argument('--tests-dir',type=Path,required=True);p.add_argument('--final-dir',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    try:r=verify(a.app_dir,a.tests_dir,a.final_dir);code=0
    except RuntimeError as e:r={'status':'ENV_INVALID','reward':None,'reason':str(e)};code=2
    except (AssertionError,KeyError,ValueError,TypeError,OSError,json.JSONDecodeError) as e:r={'status':'FAIL','reward':0,'reason':f'{type(e).__name__}: {e}'};code=1
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2));raise SystemExit(code)
if __name__=='__main__':main()
