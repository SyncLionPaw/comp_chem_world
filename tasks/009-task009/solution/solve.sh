#!/usr/bin/env bash
set -euo pipefail
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
cat > "$work_dir/solve.py" <<'CCB_SOLVE_PY'
#!/usr/bin/env python3
"""Reference calculations for published USF coverage statistics and area transport."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import NormalDist

N = 9
SOURCE_AREA = 108.0
AREAS = (30.0, 50.0, 70.0, 108.0)


def read_source(path: Path) -> dict[str, list[dict[str, float]]]:
    data: dict[str, list[dict[str, float]]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            data.setdefault(row["alloy"], []).append({
                "coverage": float(row["coverage_Cusf"]),
                "mean": float(row["gamma_usf_mean_mJ_m2"]),
                "sigma": float(row["gamma_usf_std_DFT_mJ_m2"]),
                "area": float(row["area_A2"]),
            })
    for alloy, rows in data.items():
        rows.sort(key=lambda r: r["coverage"])
        if len(rows) != 3 or any(r["area"] != SOURCE_AREA for r in rows):
            raise ValueError(f"unexpected source grid for {alloy}")
    return data


def contrast_sd_bounds(coeff: list[float], sigmas: list[float]) -> tuple[float, float]:
    terms = [abs(a) * s for a, s in zip(coeff, sigmas)]
    maximum = sum(terms)
    minimum = max(0.0, 2.0 * max(terms, default=0.0) - maximum)
    return minimum, maximum


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def calculate(source: Path, outdir: Path) -> dict:
    data = read_source(source)
    outdir.mkdir(parents=True, exist_ok=True)
    response = []
    area_rows = []
    claims = {}
    for alloy, rows in data.items():
        means = [r["mean"] for r in rows]
        raw_sigma = [r["sigma"] for r in rows]
        contrasts = {
            "delta_0_to_05": ([0.0, 0.5], means[1] - means[0], [ -1.0, 1.0, 0.0]),
            "delta_05_to_1": ([0.5, 1.0], means[2] - means[1], [0.0, -1.0, 1.0]),
            "delta_0_to_1": ([0.0, 1.0], means[2] - means[0], [-1.0, 0.0, 1.0]),
            "curvature_mu1_minus2mu05_plusmu0": ([0.0, 0.5, 1.0], means[0] - 2 * means[1] + means[2], [1.0, -2.0, 1.0]),
        }
        for name, (coverages, value, coeff) in contrasts.items():
            for convention, conv_factor, se_denominator in (("reported_ddof0_population", math.sqrt(N / (N - 1)), math.sqrt(N)),
                                                             ("reported_ddof1_sample", 1.0, math.sqrt(N))):
                sigmas = [s * conv_factor for s in raw_sigma]
                min_sd, max_sd = contrast_sd_bounds(coeff, sigmas)
                independent_sd = math.sqrt(sum((a * s) ** 2 for a, s in zip(coeff, sigmas)))
                rounding = 0.5 * sum(abs(x) for x in coeff)
                independent_se = independent_sd / se_denominator
                worst_se = max_sd / se_denominator
                response.append({
                    "alloy": alloy, "contrast": name, "coverage_coefficients": json.dumps(coeff),
                    "mean_contrast_mJ_m2": f"{value:.12g}",
                    "spread_convention": convention,
                    "sample_variance_SE_denominator":f"sqrt({N})",
                    "SE_independent_mJ_m2": f"{independent_se:.12g}",
                    "SE_unknown_covariance_min_mJ_m2": f"{min_sd / math.sqrt(N):.12g}",
                    "SE_unknown_covariance_max_mJ_m2": f"{worst_se:.12g}",
                    "normal95_independent_interval_mJ_m2": json.dumps([value-1.96*independent_se-rounding,value+1.96*independent_se+rounding]),
                    "normal95_unknown_covariance_envelope_mJ_m2": json.dumps([value-1.96*worst_se-rounding,value+1.96*worst_se+rounding]),
                    "source_anchor_rounding_bound_mJ_m2": str(rounding),
                    "sign_robust_under_worst_covariance_and_rounding": str(value-1.96*worst_se-rounding>0 or value+1.96*worst_se+rounding<0).lower(),
                    "source_n": N,
                })
        for r in rows:
            for area in AREAS:
                factor = math.sqrt(SOURCE_AREA / area)
                pop_sigma = r["sigma"] * factor
                sample_if_ddof0 = r["sigma"] * math.sqrt(N / (N - 1)) * factor
                row = {
                    "alloy": alloy, "coverage": r["coverage"], "area_A2": area,
                    "mean_mJ_m2": r["mean"],
                    "mean_estimation_SE_if_reported_ddof0_mJ_m2": f"{r['sigma']/math.sqrt(N-1):.12g}",
                    "mean_estimation_SE_if_reported_ddof1_mJ_m2": f"{r['sigma']/math.sqrt(N):.12g}",
                    "spread_if_reported_ddof0_sample_corrected_mJ_m2": f"{sample_if_ddof0:.12g}",
                    "spread_if_reported_ddof1_sample_mJ_m2": f"{pop_sigma:.12g}",
                    "scale_factor_from_108A2": f"{factor:.12g}",
                    "source_precision_mJ_m2": 0.5,
                    "Gaussian_model_domain_flag": "conditional extrapolation from 108 A2 ensemble; disclose negative tail",
                }
                for convention, sd in [("ddof0", sample_if_ddof0), ("ddof1", pop_sigma)]:
                    for q in (0.05, 0.50, 0.95):
                        z = NormalDist().inv_cdf(q)
                        row[f"quantile_{int(q*100):02d}_{convention}_mJ_m2"] = f"{r['mean'] + z*sd:.12g}"
                    row[f"P_gamma_nonpositive_{convention}"] = f"{0.5*math.erfc(r['mean']/(sd*math.sqrt(2.0))):.12g}"
                area_rows.append(row)
        # The hardening sign is invariant to ddof/covariance; uncertainty is not.
        claims[alloy] = {
            "mean_0_to_1_change_mJ_m2": means[2] - means[0],
            "mean_monotone_increasing": means[0] < means[1] < means[2],
            "curvature_mJ_m2": means[0] - 2 * means[1] + means[2],
            "source_sigmas_mJ_m2": raw_sigma,
            "sigma_interpretation": "Both ddof interpretations retained; unknown cross-coverage covariance bounds reported.",
        }
    robust_hardening = all((rows[2]["mean"]-rows[0]["mean"]) > 0 for rows in data.values())
    ranking_pairs = []
    alloys = sorted(data)
    for coverage in (0.0, 0.5, 1.0):
        for i, a1 in enumerate(alloys):
            for a2 in alloys[i+1:]:
                r1 = next(r for r in data[a1] if r["coverage"] == coverage)
                r2 = next(r for r in data[a2] if r["coverage"] == coverage)
                difference = r1["mean"]-r2["mean"]
                for convention, factor in (("reported_ddof0_population",math.sqrt(N/(N-1))),
                                           ("reported_ddof1_sample",1.0)):
                    se_max=(r1["sigma"]*factor+r2["sigma"]*factor)/math.sqrt(N)
                    rounding=1.0
                    low,high=difference-1.96*se_max-rounding,difference+1.96*se_max+rounding
                    ranking_pairs.append({
                        "coverage":coverage,"alloy_a":a1,"alloy_b":a2,
                        "mean_difference_a_minus_b_mJ_m2":difference,"spread_convention":convention,
                        "unknown_cross_alloy_covariance_plugin95_envelope_mJ_m2":[low,high],
                        "conditional_rank_resolved":low>0 or high<0,
                        "interpretation":"Gaussian plug-in envelope under unknown pair covariance; not an exact confidence interval.",
                    })
    curvature_summary = {
        alloy: {
            "curvature_mJ_m2": rows[0]["mean"]-2*rows[1]["mean"]+rows[2]["mean"],
            "interpretation": "Nonlinearity sign is not claimed unless its uncertainty envelope excludes zero; inspect response.csv under both ddof conventions."
        } for alloy, rows in data.items()
    }
    adjacent_ranks = []
    for coverage in (0.0, 0.5, 1.0):
        ordered = sorted(((alloy, next(r for r in rows if r["coverage"] == coverage))
                          for alloy, rows in data.items()), key=lambda item: item[1]["mean"])
        for edge, ((lower, lo), (upper, hi)) in enumerate(zip(ordered, ordered[1:]), 1):
            difference = hi["mean"] - lo["mean"]
            for convention, factor in (("reported_ddof0_population", math.sqrt(N/(N-1))),
                                       ("reported_ddof1_sample", 1.0)):
                se_ind = math.hypot(lo["sigma"]*factor, hi["sigma"]*factor)/math.sqrt(N)
                se_worst = (lo["sigma"]+hi["sigma"])*factor/math.sqrt(N)
                rounding = 1.0
                low = difference - 1.96*se_worst - rounding
                high = difference + 1.96*se_worst + rounding
                adjacent_ranks.append({
                    "coverage": coverage, "adjacent_rank_edge": edge,
                    "alloy_high": upper, "alloy_low": lower,
                    "mean_difference_high_minus_low_mJ_m2": difference,
                    "source_ddof_interpretation": convention,
                    "SE_independent_mJ_m2": se_ind,
                    "SE_worst_covariance_mJ_m2": se_worst,
                    "source_rounding_bound_mJ_m2": rounding,
                    "conditional_interval_low_high_mJ_m2": json.dumps([low, high]),
                    "rank_robust_or_unresolved": "robust_under_worst_covariance_plugin95" if low > 0 else "unresolved",
                    "interpretation": "Conditional n=9 Gaussian plug-in envelope; not an exact 95% confidence guarantee.",
                })
    assert len(adjacent_ranks) == 30
    write_csv(outdir / "ranking.csv", adjacent_ranks, list(adjacent_ranks[0]))
    write_csv(outdir / "response.csv", response, list(response[0]))
    write_csv(outdir / "area_transport.csv", area_rows, list(area_rows[0]))
    result = {
        "source": source.as_posix(), "n_independent_sqs_per_anchor": N,
        "source_area_A2": SOURCE_AREA, "areas_A2": AREAS,
        "units": "gamma and spread in mJ/m^2; area in A^2",
        "equations": {
            "area_spread": "sigma_A=sigma_108*sqrt(108/A)",
            "contrast_variance": "a^T Cov a; unknown covariance bounded over PSD correlation matrices",
            "quantile": "mean + Phi^-1(q)*sigma_A",
            "normal_interval": "The 95% contrast envelopes are plug-in normal approximations, not exact confidence intervals; n=9 and unknown ddof/covariance remain explicit.",
        },
        "limitations": [
            "The nine source configurations are independent SQS configurations at a half-partial displacement, not path images.",
            "The source does not state ddof or cross-coverage covariance; neither is inferred from the means and spreads.",
            "Area transport is a finite-loop model extrapolation, not a new DFT result.",
            "Source +/-0.5 mJ/m^2 printed precision is kept separate from sample dispersion and covariance.",
        ],
        "claims": claims,
        "scientific_inference": {
            "published_means_monotonically_harden_all_six": robust_hardening,
            "published_mean_rankings_by_coverage": {
                str(cov): [a for a, _ in sorted(((a, next(r["mean"] for r in rows if r["coverage"]==cov)) for a,rows in data.items()),key=lambda x:x[1])]
                for cov in (0.0,0.5,1.0)
            },
            "pairwise_rank_comparisons":ranking_pairs,
            "curvature": curvature_summary,
            "rank_uncertainty": f"{sum(bool(r['conditional_rank_resolved']) for r in ranking_pairs)} of {len(ranking_pairs)} pairwise comparisons exclude zero under the stated Gaussian plug-in/worst-covariance envelope; the remainder are unresolved. These are conditional approximations, not exact confidence guarantees."
        },
        "rows": {"response": len(response), "area_transport": len(area_rows), "ranking": len(adjacent_ranks)},
    }
    (outdir / "inference.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    result = calculate(args.source, args.outdir)
    import hashlib, shutil
    source_path = Path(__file__).resolve()
    source_out = args.outdir / "calculation_source.py"
    shutil.copyfile(source_path, source_out)
    def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    outputs = {p.name: digest(p) for p in args.outdir.iterdir() if p.is_file() and p.name not in {"calculation_source.py", "run_metadata.json"}}
    metadata = {
        "schema": "compchemworld-calculation-run/v1",
        "command": "python calculation_source.py --source <public-input> --outdir <output-dir>",
        "calculation_source_sha256": digest(source_out),
        "input": {"logical_name": Path(args.source).name, "sha256": digest(Path(args.source))},
        "output_sha256": outputs,
        "python": __import__("platform").python_version(),
        "execution_context": "local CPU calculation; this receipt does not assert independent author DFT execution",
    }
    (args.outdir / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
CCB_SOLVE_PY
python3 "$work_dir/solve.py" --source /app/assets/gamma_usf_fig2c_parameters.csv --outdir /app/final
