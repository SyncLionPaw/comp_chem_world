"""Case 003 reference model. Hidden with the verifier; not a public input."""
from __future__ import annotations

import numpy as np

K = {
    "K11": 0.140125,
    "K12": -0.207118,
    "K13": 0.011290,
    "K21": 0.015908,
    "K22": 2.003940,
}
P0 = 0.10
ALPHA = 0.5
EPS0 = 8.8541878128e-12


def _roots(Kdict):
    a3 = Kdict["K13"] * Kdict["K22"]
    a2 = Kdict["K13"] + Kdict["K12"] * Kdict["K22"] + Kdict["K13"] * Kdict["K21"]
    a1 = Kdict["K12"] + Kdict["K11"] * Kdict["K22"] + Kdict["K12"] * Kdict["K21"] + Kdict["K22"]
    a0 = Kdict["K11"] * Kdict["K21"] + Kdict["K11"] + Kdict["K21"]
    ks = []
    for Q in np.roots([a3, a2, a1, a0]):
        s = np.sqrt(Q + 0j)
        ks.extend([s, -s])
    return sorted(ks, key=lambda k: (-k.imag, -k.real))


def lengths(Kdict=K):
    a3 = Kdict["K13"] * Kdict["K22"]
    a2 = Kdict["K13"] + Kdict["K12"] * Kdict["K22"] + Kdict["K13"] * Kdict["K21"]
    a1 = Kdict["K12"] + Kdict["K11"] * Kdict["K22"] + Kdict["K12"] * Kdict["K21"] + Kdict["K22"]
    a0 = Kdict["K11"] * Kdict["K21"] + Kdict["K11"] + Kdict["K21"]
    out = []
    for Q in np.roots([a3, a2, a1, a0]):
        kc = np.sqrt(Q + 0j)
        qr, qi = abs(kc.real), abs(kc.imag)
        out.append({
            "decay_A": (1.0 / qi) if qi > 1e-8 else None,
            "oscillation_A": (2.0 * np.pi / qr) if qr > 1e-8 else None,
        })
    mono = [row["decay_A"] for row in out if row["oscillation_A"] is None]
    osc = [row for row in out if row["oscillation_A"] is not None]
    return {
        "lambda_d1_A": float(min(row["decay_A"] for row in osc)),
        "lambda_o_A": float(osc[0]["oscillation_A"]),
        "lambda_d2_A": float(mono[0]),
    }


def energy(L, Kdict=K, n=2001):
    zL, zR = 0.0, float(L)
    ks = _roots(Kdict)
    left = [k for k in ks if k.imag > 1e-8]
    right = [k for k in ks if k.imag < -1e-8]
    order = left + right
    ratios = np.array([-1.0 / (1.0 + Kdict["K21"] + Kdict["K22"] * k * k) for k in order])
    anchor = np.array([zL] * 3 + [zR] * 3)
    t1, t2 = (1.0 - ALPHA) * P0, ALPHA * P0
    A = np.zeros((6, 6), dtype=complex)
    rhs = np.array([t1, -t1, 0.0, 0.0, t2, -t2], dtype=complex)
    for j in range(6):
        phase_L = np.exp(1j * order[j] * (zL - anchor[j]))
        phase_R = np.exp(1j * order[j] * (zR - anchor[j]))
        ik2 = (1j * order[j]) ** 2
        A[0, j] = phase_L
        A[1, j] = phase_R
        A[2, j] = ik2 * phase_L
        A[3, j] = ik2 * phase_R
        A[4, j] = ratios[j] * phase_L
        A[5, j] = ratios[j] * phase_R
    coeff, *_ = np.linalg.lstsq(A, rhs, rcond=None)
    if float(np.max(np.abs(A @ coeff - rhs))) > 1e-8:
        raise RuntimeError(f"boundary residual too large at L={L}")
    z = np.linspace(zL, zR, n)
    P1 = np.zeros_like(z, dtype=complex)
    P2 = np.zeros_like(z, dtype=complex)
    d1 = np.zeros_like(z, dtype=complex)
    d2p = np.zeros_like(z, dtype=complex)
    e1 = np.zeros_like(z, dtype=complex)
    for j in range(6):
        f = np.exp(1j * order[j] * (z - anchor[j]))
        ik = 1j * order[j]
        P1 += coeff[j] * f
        P2 += coeff[j] * ratios[j] * f
        d1 += coeff[j] * ik * f
        d2p += coeff[j] * ik ** 2 * f
        e1 += coeff[j] * ratios[j] * ik * f
    P1, P2, d1, d2p, e1 = (arr.real for arr in (P1, P2, d1, d2p, e1))
    density = (
        0.5 * (1.0 + Kdict["K11"]) * P1 ** 2
        + 0.5 * (1.0 + Kdict["K21"]) * P2 ** 2
        + P1 * P2
        + 0.5 * Kdict["K12"] * d1 ** 2
        + 0.5 * Kdict["K22"] * e1 ** 2
        + 0.5 * Kdict["K13"] * d2p ** 2
    )
    integrate = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    return float(integrate(density, z))


def pressure(L, h=1e-3, n=2001):
    if L - h <= 0.0:
        raise ValueError(f"central difference at L={L} with h={h} leaves the film")
    return -((energy(L + h, n=n) - energy(L - h, n=n)) / (2.0 * h)) / EPS0


# Internal table used by the roughness integral. The public sharp curve still
# starts at 2 Angstrom; samples between the film floor and 2 Angstrom must
# not be replaced by Pi(2 Angstrom).
INTERNAL_LO_A = 0.40
PUBLIC_LO_A = 2.0
TABLE_HI_A = 20.0
TABLE_STEP_A = 0.02
_TABLES = {}


def sharp_pressure_table(lo=INTERNAL_LO_A, hi=TABLE_HI_A, step=TABLE_STEP_A, h=1e-3, n=2001):
    key = (round(lo, 6), round(hi, 6), round(step, 6), h, n)
    if key not in _TABLES:
        Ls = np.round(np.arange(lo, hi + step / 2.0, step), 10)
        _TABLES[key] = (Ls, np.array([pressure(float(L), h=h, n=n) for L in Ls]))
    return _TABLES[key]


def sharp_grid():
    Ls, Vs = sharp_pressure_table()
    mask = Ls >= PUBLIC_LO_A - 1e-12
    return Ls[mask], Vs[mask]


def _gauss(L, sigma, nnode=48):
    """Task Gaussian, not Equation 19.

    The density is exp(-x^2 / (2 sigma^2)) on [0, L/2], centered at 0.
    sigma is a standard deviation. A task width of 2*sigma = 2.5 Angstrom
    is not the paper's roughness width.
    """
    xg, wg = np.polynomial.legendre.leggauss(nnode)
    half = L / 2.0
    x = 0.5 * half * (xg + 1.0)
    w = 0.5 * half * wg
    g = np.exp(-0.5 * (x / sigma) ** 2)
    return x, w * g / np.sum(w * g)


def smeared_grid(two_sigma=2.5, floor=0.40, table=None):
    """Average Pi(L - rho1 - rho2). Retained films are interpolated, never clamped up to 2 Angstrom.

    two_sigma is twice the task-convention standard deviation, not Equation 19's 2*delta.
    """
    if table is None:
        Ls, Vs = sharp_pressure_table()
    else:
        Ls, Vs = table
    if float(Ls[0]) > floor + 1e-8:
        raise ValueError(
            f"sharp table starts at {float(Ls[0])} Angstrom, above the film floor {floor}"
        )
    sigma = two_sigma / 2.0
    Lg = np.round(np.arange(5.0, 20.0 + 1e-9, 0.10), 10)
    out = []
    for L in Lg:
        _rho, w = _gauss(float(L), sigma)
        sep = L - _rho[:, None] - _rho[None, :]
        weight = w[:, None] * w[None, :]
        keep = sep >= floor
        weight = np.where(keep, weight, 0.0)
        norm = float(weight.sum())
        if norm <= 0.0:
            raise RuntimeError(f"no smearing weight remains at L={L}")
        if np.any(keep & (sep > Ls[-1] + 1e-8)):
            raise ValueError("film thicker than the computed sharp table")
        val = np.interp(sep, Ls, Vs)
        out.append(float(np.sum(weight * val) / norm))
    return Lg, np.array(out)


def sign_changes(x, y, lo, hi):
    mask = (x >= lo) & (x <= hi)
    signs = np.sign(y[mask])
    signs = signs[signs != 0]
    if len(signs) < 2:
        return 0
    return int(np.sum(signs[1:] * signs[:-1] < 0))


def period_from_extrema(x, y, lo=4.0, hi=16.0):
    mask = (x >= lo) & (x <= hi)
    xx, yy = x[mask], y[mask]
    extrema = []
    for i in range(1, len(yy) - 1):
        if (yy[i] - yy[i - 1]) * (yy[i + 1] - yy[i]) < 0:
            extrema.append(xx[i])
    if len(extrema) < 3:
        return None
    return float(2.0 * np.median(np.diff(extrema)))
