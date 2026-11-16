#!/usr/bin/env bash
set -euo pipefail
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/task75-solution.XXXXXX")"
# Keep extracted sources available until execution and any HPC staging/collection finish.
trap 'rm -rf -- "$work_dir"' EXIT
cat > "$work_dir/solve.py" <<'TASK_SOURCE_SOLVE_PY'
#!/usr/bin/env python3
"""Author-data reference construction for case 05; emits artifacts without private expected values."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

ASSEMBLIES = ("D", "F")
VARIANTS = ("WT", "V72I")
PROTONATIONS = ("AspAsp", "AshAsp", "AspAsh")
STAT_FIELDS = ("n", "mean", "std", "median", "q25", "q75")
CONTACT = 4.35
SIGMAS = (0.10, 0.15)
WINDOWS = {"D": (4.6, 5.0), "F": (4.1, 4.7)}


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def load(assets: Path):
    series = {}
    stats = {}
    for assembly, filename in (("D", "Fig_6b.dat"), ("F", "Fig_8b.dat")):
        frame = pd.read_csv(assets / filename, sep=r"\s+", header=0, na_values=["NaN"], engine="c")
        for variant in VARIANTS:
            offset = 0 if variant == "WT" else 8
            for i, protonation in enumerate(PROTONATIONS):
                for obs, col in (("delta", offset + 2 + i * 2), ("gamma", offset + 3 + i * 2)):
                    values = frame.iloc[:, col].to_numpy(dtype=float)
                    values = values[np.isfinite(values)]
                    key = (assembly, variant, protonation, obs)
                    series[key] = values
                    stats[key] = {"n": len(values), "mean": float(values.mean()), "std": float(values.std(ddof=1)),
                                  "median": float(np.median(values)), "q25": float(np.quantile(values, .25)),
                                  "q75": float(np.quantile(values, .75))}
    return series, stats


def compare_delta(a: float, b: float) -> str:
    return "higher" if b - a > 1e-12 else "lower" if b - a < -1e-12 else "equal"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("assets", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--statistic", choices=("mean", "median"), default="mean")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    series, stats = load(args.assets)
    distributions = []
    for key, summary in stats.items():
        distributions.append({"assembly": key[0], "variant": key[1], "protonation": key[2], "observable": key[3], **summary})
    write_csv(args.out / "distributions.csv", ["assembly", "variant", "protonation", "observable", *STAT_FIELDS], distributions)

    rdf = []
    edges = np.arange(0.0, 16.0001, 0.01)
    for assembly in ASSEMBLIES:
        for variant in VARIANTS:
            for protonation in PROTONATIONS:
                values = series[(assembly, variant, protonation, "delta")]
                counts, _ = np.histogram(values, bins=edges)
                n = len(values)
                widths = np.diff(edges)
                for left, right, count, width in zip(edges[:-1], edges[1:], counts, widths):
                    rdf.append({"assembly": assembly, "variant": variant, "protonation": protonation,
                                "bin_left": left, "bin_right": right, "count": int(count),
                                "density": float(count / n / width)})
    write_csv(args.out / "rdf.csv", ["assembly", "variant", "protonation", "bin_left", "bin_right", "count", "density"], rdf)

    mutation_effects = []
    for assembly in ASSEMBLIES:
        for protonation in PROTONATIONS:
            for observable in ("delta", "gamma"):
                wt = stats[(assembly, "WT", protonation, observable)][args.statistic]
                mut = stats[(assembly, "V72I", protonation, observable)][args.statistic]
                mutation_effects.append({"assembly": assembly, "protonation": protonation, "observable": observable,
                                         "statistic": args.statistic, "reference_variant": "WT", "target_variant": "V72I",
                                         "reference_value": wt, "target_value": mut, "effect": mut - wt,
                                         "units": "angstrom" if observable == "delta" else "degree",
                                         "conclusion": compare_delta(wt, mut)})
    protonation_effects = []
    for assembly in ASSEMBLIES:
        for variant in VARIANTS:
            for target in ("AshAsp", "AspAsh"):
                ref = stats[(assembly, variant, "AspAsp", "delta")][args.statistic]
                val = stats[(assembly, variant, target, "delta")][args.statistic]
                protonation_effects.append({"assembly": assembly, "variant": variant, "reference_protonation": "AspAsp",
                                            "target_protonation": target, "observable": "delta", "statistic": args.statistic,
                                            "reference_value": ref, "target_value": val, "effect": val - ref,
                                            "units": "angstrom", "conclusion": compare_delta(ref, val)})

    local_state = []
    for assembly in ASSEMBLIES:
        for variant in VARIANTS:
            for protonation in PROTONATIONS:
                v = series[(assembly, variant, protonation, "delta")]
                local_state.append({"assembly": assembly, "variant": variant, "protonation": protonation,
                                    "threshold_angstrom": CONTACT, "probability_delta_le_threshold": float(np.mean(v <= CONTACT)), "n": len(v)})
    local_map = {(r["assembly"], r["variant"], r["protonation"]): r["probability_delta_le_threshold"] for r in local_state}
    local_diff = []
    for assembly in ASSEMBLIES:
        for protonation in PROTONATIONS:
            effect = local_map[(assembly, "V72I", protonation)] - local_map[(assembly, "WT", protonation)]
            local_diff.append({"contrast": "mutation", "assembly": assembly, "variant": "", "protonation": protonation,
                               "reference": "WT", "target": "V72I", "effect": effect, "conclusion": "higher" if effect > 1e-12 else "lower" if effect < -1e-12 else "equal"})
        for variant in VARIANTS:
            for target in ("AshAsp", "AspAsh"):
                effect = local_map[(assembly, variant, target)] - local_map[(assembly, variant, "AspAsp")]
                local_diff.append({"contrast": "protonation", "assembly": assembly, "variant": variant, "protonation": target,
                                   "reference": "AspAsp", "target": target, "effect": effect, "conclusion": "higher" if effect > 1e-12 else "lower" if effect < -1e-12 else "equal"})

    apical = []
    correlations = []
    for assembly in ASSEMBLIES:
        for variant in VARIANTS:
            for protonation in PROTONATIONS:
                g = series[(assembly, variant, protonation, "gamma")]
                row = {"assembly": assembly, "variant": variant, "protonation": protonation,
                       "gamma_location_median_degree": float(np.median(g)), "n": len(g)}
                if assembly == "F":
                    row.update({"cutoff_degree": 120.0, "cutoff_operator": ">", "fraction_gamma_gt_120_degree": float(np.mean(g > 120.0))})
                else:
                    row.update({"cutoff_degree": 100.0, "cutoff_operator": ">=", "fraction_gamma_ge_100_degree": float(np.mean(g >= 100.0))})
                apical.append(row)
                d = series[(assembly, variant, protonation, "delta")]
                n = min(len(d), len(g))
                d, g = d[:n], g[:n]
                good = np.isfinite(d) & np.isfinite(g)
                coefficient = float(np.corrcoef(d[good], g[good])[0, 1])
                correlations.append({"assembly": assembly, "variant": variant, "protonation": protonation,
                                     "method": "Pearson", "n_paired": int(good.sum()), "coefficient": coefficient,
                                     "interpretation": "positive_association" if coefficient > 0 else "negative_association" if coefficient < 0 else "zero_association"})

    shape_rows = []
    centers = (edges[:-1] + edges[1:]) / 2
    for assembly in ASSEMBLIES:
        low, high = WINDOWS[assembly]
        for variant in VARIANTS:
            vals = series[(assembly, variant, "AspAsp", "delta")]
            density, _ = np.histogram(vals, bins=edges, density=True)
            radial = density / centers**2
            for sigma in SIGMAS:
                smooth = gaussian_filter1d(radial, sigma=sigma / 0.01, mode="nearest")
                slope = np.gradient(smooth, 0.01)
                minima, _ = find_peaks(-slope)
                inds = [int(i) for i in minima if low <= centers[i] <= high]
                primary_ix = max(range(len(centers)), key=lambda i: radial[i] if centers[i] > low else -np.inf)
                shape_rows.append({"assembly": assembly, "variant": variant, "sigma_angstrom": sigma,
                                   "feature_window_low_angstrom": low, "feature_window_high_angstrom": high,
                                   "feature_type": "local_minimum_of_radial_shape_slope",
                                   "feature_positions_angstrom": [float(centers[i]) for i in inds],
                                   "feature_slope_values": [float(slope[i]) for i in inds],
                                   "primary_mode_angstrom": float(centers[primary_ix]),
                                   "primary_mode_above_feature": bool(inds and centers[primary_ix] > centers[inds[0]]),
                                   "raw_mass_feature_window": float(np.mean((vals >= low) & (vals <= high))),
                                   "shoulder_present": bool(inds)})

    findings = {
        "schema": "assembly-dyad/v1",
        "rdf_normalization": "probability_density",
        "statistical_methods": [f"Per-series mean, sample standard deviation, median, and quartiles from all finite author frame values; matched {args.statistic} contrasts.",
                                "Local-contact probability is the fraction of raw delta values <=4.35 angstrom.",
                                "Apical opening is summarized directly from gamma; paired Pearson correlations are descriptive only.",
                                "Shoulder morphology uses a 0-16 angstrom 0.01-A histogram probability density divided by r^2, Gaussian smoothing, the radial-shape slope, and every local slope minimum in the stated interval."],
        "inference_status": "descriptive_only",
        "uncertainty_provenance": {
            "independent_replicates_available": False,
            "time_axis_available": False,
            "pooled_frame_spread_is_confidence_interval": False,
            "frames_treated_as_independent_samples": False,
        },
        "limitations": ["The author files provide per-monomer frame values but no independent replicate identifiers or time axis; quartiles describe spread and are not confidence intervals.",
                        "The Pearson coefficients are descriptive associations among paired frames, not independent-sample tests or evidence that delta causes gamma."],
        "mutation_effects": mutation_effects,
        "protonation_effects": protonation_effects,
        "local_contact_state": local_state,
        "local_contact_differences": local_diff,
        "apical_context": apical,
        "delta_gamma_dependence": correlations,
        "shape_features": shape_rows,
    }
    (args.out / "findings.json").write_text(json.dumps(findings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = """# Case 05 author-data analysis\n\nThe 24 distribution rows and 12 δ histograms retain the distinct D double-ring and F football panels, all WT/V72I states, and all three protonation states. All listed effects are matched within assembly and protonation (mutation) or within assembly and variant (protonation); their signs come from the supplied values.\n\nThe RDF normalization is probability density: each histogram count divided by the finite sample count and bin width. The local contact state is the empirical probability of raw δ ≤ 4.35 Å. F apical context reports median γ and the direct fraction above 120°. D context reports median γ and the direct fraction at or above 100°, including AshAsp as a separate descriptive state. Neither γ is inferred from δ.\n\nFor AspAsp shoulder morphology, the common probe uses 0–16 Å bins at 0.01 Å, probability density p(r), radial shape p(r)/r², Gaussian smoothing with σ=0.10 and 0.15 Å, and the numerical slope. Every local minimum of that slope in D 4.6–5.0 Å or F 4.1–4.7 Å is reported. This operational shoulder feature is distinct from a secondary peak and from the raw probability mass in the interval.\n\nUncertainty is represented by the empirical quartiles and standard deviation of the pooled finite author frames. The files do not provide independent replicate labels or a time axis, so these spreads are not confidence intervals and the paired Pearson coefficients are descriptive only. The main-text Fig. 8b values control this analysis; supplementary Fig. 17 contains a differing mutant γ interpretation and is retained as a literature discrepancy rather than merged with these values.\n"""
    (args.out / "report.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
TASK_SOURCE_SOLVE_PY

python3 "$work_dir/solve.py" /app/assets /app/final --statistic mean "$@"
