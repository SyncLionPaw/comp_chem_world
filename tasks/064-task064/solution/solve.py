#!/usr/bin/env python3
"""Recompute the public G4 single-record thermodynamic analysis."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

KB, T, KCAL = 0.00831446261815324, 300.0, 4.184


def analyze(d, burn, bins=72, edge_assignment="floor"):
    t, z, bias, wall = (d[k] for k in ("time_ps", "cyl_z_nm", "bias_kJ_mol", "funnelwall_bias_kJ_mol"))
    post = t >= burn
    eligible = post & (wall <= 10.0)
    histmask = eligible & (z >= 0.0) & (z < 1.8)
    if not histmask.any():
        raise ValueError("no records in public histogram range")
    beta = 1.0 / (KB * T)
    edges = np.linspace(0.0, 1.8, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2

    def fes(mask):
        x, v = z[mask], bias[mask]
        w = np.exp(beta * v - np.max(beta * v))
        if edge_assignment == "floor":
            ix = np.floor((x / 1.8) * bins).astype(int)
            hist = np.bincount(np.clip(ix, 0, bins - 1), weights=w, minlength=bins)
        elif edge_assignment == "floor_width":
            ix = np.floor(x / (1.8 / bins)).astype(int)
            hist = np.bincount(np.clip(ix, 0, bins - 1), weights=w, minlength=bins)
        elif edge_assignment == "histogram":
            hist, _ = np.histogram(x, bins=np.linspace(0.0, 1.8, bins + 1), weights=w)
        else:
            raise ValueError(f"unsupported bin edge assignment: {edge_assignment}")
        p = hist / hist.sum()
        f = np.full(bins, np.nan)
        occupied = p > 0
        f[occupied] = -np.log(p[occupied]) / beta
        f[occupied] -= np.min(f[occupied])
        unbound = (centers >= 1.5) & (centers < 1.8)
        bound = (centers >= 0.3) & (centers < 0.8)
        if not occupied[unbound].all() or not (bound & occupied).any():
            raise ValueError("required bins unsupported")
        wu = f[unbound].mean()
        integral = (1 / 1.660) * math.pi * 0.2**2 * np.nansum((1.8 / bins) * np.exp(-beta * (f[bound] - wu)))
        return p, f, -math.log(float(integral)) / beta

    p, f, dg = fes(histmask)
    t0, t1 = float(t[post][0]), float(t[-1])
    cuts = np.linspace(t0, t1, 6)
    blocks = []
    for i in range(5):
        bm = eligible & (t >= cuts[i]) & ((t <= cuts[i + 1]) if i == 4 else (t < cuts[i + 1]))
        fm = histmask & (t >= cuts[i]) & ((t <= cuts[i + 1]) if i == 4 else (t < cuts[i + 1]))
        _, _, b_dg = fes(fm)
        logw = beta * bias[bm]
        blocks.append({"block": i + 1, "time_start_ps": float(cuts[i]), "time_end_ps": float(cuts[i + 1]),
                       "eligible_rows": int(bm.sum()), "weight_sum_scaled": float(np.exp(logw - logw.max()).sum()),
                       "max_log_weight": float(logw.max()), "deltaG_kJ_mol": b_dg, "deltaG_kcal_mol": b_dg / KCAL})
    maxlog = max(b["max_log_weight"] for b in blocks)
    weights = np.array([b["weight_sum_scaled"] * np.exp(b["max_log_weight"] - maxlog) for b in blocks])
    values = np.array([b["deltaG_kcal_mol"] for b in blocks])
    prob = weights / weights.sum()
    neff = 1 / np.sum(prob**2)
    mu = float(prob @ values)
    sd = math.sqrt(float(prob @ ((values - mu) ** 2)) * neff / (neff - 1))
    framew = np.exp(beta * bias[eligible] - np.max(beta * bias[eligible]))
    frame_ess = float(framew.sum() ** 2 / np.sum(framew**2))
    return {"centers": centers, "p": p, "F": f, "dg": dg, "blocks": blocks,
            "mean": mu, "sd": sd, "se": sd / math.sqrt(neff), "block_ess": float(neff), "frame_ess": frame_ess,
            "rows": {"postburn": int(post.sum()), "wall": int(eligible.sum()), "histogram": int(histmask.sum())},
            "block_range_ps": (t0, t1), "single_replica_duration_ns": float(t[-1] / 1000)}


def main(asset_dir: Path, app: Path):
    source = asset_dir / "g4-thermodynamic-records.npz"
    provenance = json.loads((asset_dir / "record-provenance.json").read_text())
    with np.load(source, allow_pickle=False) as archive:
        d = {k: np.asarray(archive[k], dtype=np.float64) for k in archive.files}
        unique_npz_fields = tuple(archive.files)
    edge_assignment = sys.argv[3] if len(sys.argv) > 3 else "floor"
    baseline = analyze(d, 20000.0, edge_assignment=edge_assignment)
    alt = analyze(d, 10000.0, edge_assignment=edge_assignment)
    sensitivity_delta = float(alt["dg"] / KCAL - baseline["dg"] / KCAL)
    out = app
    out.mkdir(parents=True, exist_ok=True)
    with (out / "FES.csv").open("w", newline="", encoding="utf-8") as fobj:
        w = csv.writer(fobj)
        w.writerow(("z_nm", "probability", "F_kJ_mol", "F_kcal_mol"))
        for x, p, free in zip(baseline["centers"], baseline["p"], baseline["F"]):
            w.writerow((f"{x:.12g}", f"{p:.12g}", "" if not math.isfinite(free) else f"{free:.12g}", "" if not math.isfinite(free) else f"{free / KCAL:.12g}"))
    with (out / "blocks.csv").open("w", newline="", encoding="utf-8") as fobj:
        w = csv.DictWriter(fobj, fieldnames=baseline["blocks"][0].keys())
        w.writeheader()
        w.writerows(baseline["blocks"])
    public_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    k = lambda x: round(x, 12)
    therm = {"protocol": {"temperature_K": 300, "burn_in_ps": 20000, "wall_max_kJ_mol": 10, "z_range_nm": [0, 1.8], "bins": 72, "blocks": 5, "empty_bin_policy": "P=0; F=+infinity; zero integral contribution", "bin_edge_assignment": edge_assignment, "method": f"{edge_assignment} bin assignment; equal elapsed time blocks"},
             "source": {"path": "environment/assets/g4-thermodynamic-records.npz", "public_input_sha256": public_sha, "raw_source_sha256": provenance["sha256"]},
             "counts": baseline["rows"],
             "thermodynamics": {"deltaG_kcal_mol": k(baseline["dg"] / KCAL), "deltaG_kJ_mol": k(baseline["dg"]),
                                "weighted_block_mean_kcal_mol": k(baseline["mean"]), "weighted_block_mean_kJ_mol": k(baseline["mean"] * KCAL),
                                "weighted_block_sd_kcal_mol": k(baseline["sd"]), "weighted_block_formal_se_kcal_mol": k(baseline["se"]),
                                "frame_effective_sample_size": k(baseline["frame_ess"]), "block_effective_sample_size": k(baseline["block_ess"])} }
    (out / "thermodynamics.json").write_text(json.dumps(therm, indent=2) + "\n", encoding="utf-8")
    with (out / "sensitivity.csv").open("w", newline="", encoding="utf-8") as fobj:
        cols = ("variant", "changed_choice", "parameter_unit", "parameter_value", "deltaG_kcal_mol", "block_sd_kcal_mol", "block_formal_se_kcal_mol", "frame_ess", "block_ess", "interpretation")
        w = csv.DictWriter(fobj, fieldnames=cols)
        w.writeheader()
        w.writerow({"variant": "burnin_10000_ps", "changed_choice": "burn_in", "parameter_unit": "ps", "parameter_value": 10000,
                    "deltaG_kcal_mol": k(alt["dg"] / KCAL), "block_sd_kcal_mol": k(alt["sd"]), "block_formal_se_kcal_mol": k(alt["se"]),
                    "frame_ess": k(alt["frame_ess"]), "block_ess": k(alt["block_ess"]), "interpretation": "single-replica burn-in sensitivity; not a convergence proof"})
    (out / "sampling-decision.json").write_text(json.dumps({"supported_use": "postprocessing sensitivity for this one archived replica",
        "precision_claim": "descriptive block variation only; formal SE is not an iid confidence interval",
        "stop_or_continue": "do not claim convergence or independent-replica precision; continue sampling if a decision requires tighter uncertainty",
        "dominant_uncertainty": "time correlation, one-replica coverage, and sampling bias",
        "next_evidence": ["independent replicas", "time-resolved bias for every saved configuration", "predeclared convergence diagnostics"]}, indent=2) + "\n", encoding="utf-8")
    t0, t1 = baseline["block_range_ps"]
    maximum_gap = float(np.diff(d["time_ps"]).max())
    report = (
        "# G4 thermodynamic audit\n\n"
        f"Recomputed {len(d['time_ps'])} source rows; native stride is approximately 0.5 ps and the largest adjacent gap is {maximum_gap:.6f} ps. "
        "Biases and energies are kJ/mol, coordinates nm, and time ps. The analysis uses time ≥20,000 ps, funnel wall ≤10 kJ/mol, z in [0,1.8) nm, 72 bins, and the stated 0.2 nm funnel standard-state integral. "
        f"Changing only burn-in to 10,000 ps shifts ΔG by {sensitivity_delta:.5f} kcal/mol relative to the 20,000 ps baseline (absolute shift {abs(sensitivity_delta):.5f} kcal/mol; baseline weighted block SD {baseline['sd']:.5f}, formal block SE {baseline['se']:.5f} kcal/mol). This shift is smaller than either descriptive uncertainty scale, but that comparison does not establish convergence or precision. "
        "The trajectory is one replica; five time blocks are correlated and their formal SE is descriptive, not an iid confidence interval. This is not a reproduction of the paper's full multi-CV/multi-walker result.\n\n"
        f"The supplied public NPZ has {len(unique_npz_fields)} unique named arrays. Its source provenance records that duplicate raw OPES bias, rct, and nker columns were compared exactly and that the first acquired column was retained; the raw COLVAR is not included here, so this report relies on the supplied provenance for that source-column audit rather than claiming to repeat it. "
        f"Frame ESS uses the {baseline['rows']['wall']} post-burn funnel-wall-eligible rows before z selection; the FES uses {baseline['rows']['histogram']} rows in the z range. The five block weight sums use wall-eligible rows and cover five equal elapsed-time intervals from the first acquired post-burn point ({t0:.6f} ps) to the final source row ({t1:.6f} ps), which is included in the last block. "
        f"The reported block sums use local scaling L_i=Σexp(log w−m_i), with m_i=max(log w) for each block. To normalize across blocks, recover B_i=L_i·exp(m_i−M), M=max_i m_i, then use p_i=B_i/Σ_jB_j. "
        f"The record spans {baseline['single_replica_duration_ns']:.6f} ns and contains one acquired replica. The native PLUMED funnel geometry is in nm; it resolves the SI prose Å/nm typo in favor of the native input and supplied geometry.\n"
    )
    (out / "audit-report.md").write_text(report, encoding="utf-8")
    (out / "provenance.json").write_text(json.dumps({"public_input_sha256": public_sha, "raw_source_sha256": provenance["sha256"],
        "protocol_id": "decision03-fixed-baseline-v1", "scope": "one acquired complete G4 record; postprocessing only"}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
