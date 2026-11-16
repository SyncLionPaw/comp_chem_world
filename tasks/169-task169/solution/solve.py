#!/usr/bin/env python3
"""Reference solution for case-03 (oracle replay material).

Reads the bundled a2f-tuning-series.csv, computes the full tuning report and
writes tuning-report.json into argv[1] (default ./final-out).
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

CM1_TO_K = 1.4387768775
SOFT_OMEGA = 12.0
SOFT_THRESHOLD = 0.30


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "final-out").resolve()
    out.mkdir(parents=True, exist_ok=True)
    asset = Path("/app/assets/a2f-tuning-series.csv")
    if not asset.is_file():
        asset = Path(__file__).resolve().parent.parent / "environment" / "assets" / "a2f-tuning-series.csv"

    data: dict[str, list[tuple[float, float]]] = {}
    with asset.open() as fh:
        for row in csv.reader(fh):
            if not row or row[0].lstrip().startswith("#") or row[0].strip() == "series_id":
                continue
            data.setdefault(row[0].strip(), []).append((float(row[1]), float(row[2])))

    members = []
    refs = {}
    for sid, rows in data.items():
        arr = np.array(sorted(rows), dtype=float)
        omega, a2f = arr[:, 0], arr[:, 1]
        y = a2f / omega
        lam = 2.0 * float(np.trapezoid(y, omega))
        wlog = math.exp(2.0 * float(np.trapezoid(y * np.log(omega), omega)) / lam)

        def tc(mu):
            return (wlog * CM1_TO_K / 1.2) * math.exp(-1.04 * (1.0 + lam) / (lam - mu * (1.0 + 0.62 * lam)))

        m_soft = omega < SOFT_OMEGA
        soft = 2.0 * float(np.trapezoid(a2f[m_soft] / omega[m_soft], omega[m_soft])) / lam
        proxy_safe = soft <= SOFT_THRESHOLD
        refs[sid] = dict(lam=lam, wlog=wlog, soft=soft, proxy_safe=proxy_safe,
                         tc16=tc(0.16), tc10=tc(0.10))
        members.append({
            "series_id": sid,
            "lambda": round(lam, 4),
            "omega_log_cm1": round(wlog, 2),
            "soft_mode_risk": not proxy_safe,
            "proxy_safe": proxy_safe,
            "tc_mu016_K": round(tc(0.16), 3) if proxy_safe else None,
            "tc_mu01_K": round(tc(0.10), 3) if proxy_safe else None,
            "soft_lambda_fraction_below_12cm1": round(soft, 4),
        })

    proxy_safe_holes = sorted(float(m["series_id"].split("_")[1].rstrip("h").replace("p", "."))
                              for m in members if m["series_id"].startswith("hole_") and m["proxy_safe"])
    risk_holes = sorted(float(m["series_id"].split("_")[1].rstrip("h").replace("p", "."))
                        for m in members if m["series_id"].startswith("hole_") and m["soft_mode_risk"])
    bracket = [proxy_safe_holes[-1], risk_holes[0]] if proxy_safe_holes and risk_holes else None

    e1 = refs["electron_1p0e"]["tc16"]
    report = {
        "members": members,
        "trends": {
            "compression_reduces_lambda": refs["strain_-2p0pct"]["lam"] < refs["strain_0p0pct"]["lam"],
            "compression_raises_omega_log": refs["strain_-2p0pct"]["wlog"] > refs["strain_0p0pct"]["wlog"],
            "expansion_1pct_lambda": round(refs["strain_+1p0pct"]["lam"], 4),
            "hole_doping_raises_lambda": refs["hole_0p10h"]["lam"] > refs["strain_0p0pct"]["lam"],
            "hole_soft_mode_risk_bracket": bracket,
            "electron_1p0e_tc_mu016_K": round(e1, 3),
            "electron_doping_tc_in_paper_range": bool(0.3 <= e1 <= 1.7),
        },
        "extreme_coupling": {
            "series_id": "strain_+1p0pct",
            "lambda_value": round(refs["strain_+1p0pct"]["lam"], 4),
            "exceeds_known_materials": True,
            "quantitative_tc_reliable": False,
            "rationale": (
                "This is a synthetic scalar alpha2F reconstruction, not raw anisotropic "
                "Eliashberg or converged phonon evidence for the material. Its lambda=3.5 "
                "exceeds the paper-cited comparison value 2.6, and the low-frequency "
                "weight is a screening signal only. Therefore the Allen-Dynes number is "
                "a model calculation on this input, not a quantitatively established Tc "
                "for real W2N3; the supplied data do not prove a phonon instability or "
                "that Migdal theory has failed."
            ),
        },
        "notes": "The supplied positive-frequency alpha2F spectra do not contain phonon eigenvalues "
                 "or imaginary modes. soft_mode_risk and proxy_safe are screening labels from the "
                 "specified low-frequency spectral-weight proxy, not proof of dynamical stability "
                 "or instability. Allen-Dynes Tc is omitted where the proxy flags risk. The hole "
                 "bracket is the interval between sampled proxy-safe and risk members, not a "
                 "measured instability threshold. The spectra are synthetic reconstructions; "
                 "published mu* ranges use anisotropic Eliashberg calculations and are not a direct "
                 "validation target for this scalar Allen-Dynes reconstruction.",
    }
    (out / "tuning-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out / 'tuning-report.json'}: {len(members)} members, "
          f"bracket={bracket}, lambda(+1%)={refs['strain_+1p0pct']['lam']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
