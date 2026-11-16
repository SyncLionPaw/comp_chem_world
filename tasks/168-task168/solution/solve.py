#!/usr/bin/env python3
"""Reference solution for case-02 (oracle replay material).

Reads the bundled a2f-unstrained.csv and writes eliashberg-results.json
into argv[1] (default ./final-out).
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

CM1_TO_K = 1.4387768775


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "final-out").resolve()
    out.mkdir(parents=True, exist_ok=True)
    asset = Path("/app/assets/a2f-unstrained.csv")
    if not asset.is_file():
        asset = Path(__file__).resolve().parent.parent / "environment" / "assets" / "a2f-unstrained.csv"

    omega, a2f = [], []
    with asset.open() as fh:
        for row in csv.reader(fh):
            if not row or row[0].lstrip().startswith("#") or row[0].strip() == "omega_cm1":
                continue
            omega.append(float(row[0]))
            a2f.append(float(row[1]))
    omega = np.asarray(omega)
    a2f = np.asarray(a2f)

    y = a2f / omega
    lam = 2.0 * float(np.trapezoid(y, omega))
    wlog_cm1 = math.exp(2.0 * float(np.trapezoid(y * np.log(omega), omega)) / lam)

    mid_omega = (omega[:-1] + omega[1:]) / 2
    mid_y = (a2f[:-1] + a2f[1:]) / (2 * mid_omega)
    widths = np.diff(omega)
    mid_lambda = 2 * float(np.dot(widths, mid_y))
    mid_omega_log = math.exp(2 * float(np.dot(widths, mid_y * np.log(mid_omega))) / mid_lambda)

    def tc(mu):
        return (wlog_cm1 * CM1_TO_K / 1.2) * math.exp(-1.04 * (1.0 + lam) / (lam - mu * (1.0 + 0.62 * lam)))

    bands = {}
    for lo, hi, key in [(0.0, 200.0, "lambda_0_200_cm1"), (200.0, 300.0, "lambda_200_300_cm1"),
                        (300.0, 360.0, "lambda_300_360_cm1"), (360.0, 450.0, "lambda_360_450_cm1")]:
        m = (omega > lo) & (omega <= hi)
        bands[key] = 2.0 * float(np.trapezoid(a2f[m] / omega[m], omega[m]))
    m = omega > 450.0
    bands["lambda_above_450_cm1"] = 2.0 * float(np.trapezoid(a2f[m] / omega[m], omega[m]))

    tc16, tc10 = tc(0.16), tc(0.10)
    ratio = tc10 / tc16
    result = {
        "lambda": round(lam, 5),
        "integration_check": {"trapezoid_lambda": lam, "trapezoid_omega_log_cm1": wlog_cm1,
                              "midpoint_lambda": mid_lambda, "midpoint_omega_log_cm1": mid_omega_log},
        "omega_log_cm1": round(wlog_cm1, 3),
        "omega_log_K": round(wlog_cm1 * CM1_TO_K, 3),
        "tc_mu016_K": round(tc16, 4),
        "tc_mu01_K": round(tc10, 4),
        "mu_star_sensitivity": {
            "ratio_tc_mu01_over_mu016": round(ratio, 5),
            "ad_surrogate_le_10pct_supported": bool(ratio <= 1.10),
            "sensitivity_note": (
                "On this spectrum (lambda = 1.90) the Allen-Dynes sensitivity to mu* is "
                "fixed by the formula: Tc(mu*=0.10)/Tc(mu*=0.16) = 1.163, i.e. a ~16% "
                "increase, which exceeds the paper's stated 'at most ~10%'. The paper's "
                "statement refers to its isotropic Migdal-Eliashberg solution on the "
                "authors' own data, a different observable and grid; on the provided "
                "data this scalar Allen-Dynes surrogate does not reproduce a <=10% ratio; this does not test or refute the paper’s anisotropic Migdal-Eliashberg result."
            ),
        },
        "decomposition": {k: round(v, 5) for k, v in bands.items()},
    }
    (out / "eliashberg-results.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out / 'eliashberg-results.json'}: lambda={lam:.4f} "
          f"omega_log={wlog_cm1:.2f} cm-1 Tc16={tc16:.2f} K ratio={ratio:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
