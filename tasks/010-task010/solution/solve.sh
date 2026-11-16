#!/usr/bin/env bash
set -euo pipefail
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
cat > "$work_dir/solve.py" <<'CCB_SOLVE_PY'
#!/usr/bin/env python3
"""Solve the published Gaussian absorption model and finite-spectrum sensitivity."""
from __future__ import annotations

import argparse
import csv
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import numpy as np

K_B_EV_K = 8.617333262145e-5
T_GRID = (300.0, 400.0)
CB_GRID = (1e-6, 1e-5, 1e-4, 1e-3, 2.6e-3, 5.8e-3)
Q_GRID = (0.001, 0.01, 0.05)
N_GRID = (25, 50, 100)
REPLICATES = 512
BASE_SEED = 175501


def load_parameters(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return [{"alloy": r["alloy"], "sigma": float(r["sigma_eV"]), "Ebar": float(r["Ebar_eV"])}
                for r in csv.DictReader(f)]


@lru_cache(maxsize=8)
def _legendre(order: int) -> tuple[np.ndarray, np.ndarray]:
    z, w = np.polynomial.legendre.leggauss(order)
    z.setflags(write=False); w.setflags(write=False)
    return z, w


@lru_cache(maxsize=8)
def gauss_nodes(order: int) -> tuple[np.ndarray, np.ndarray]:
    z, w = _legendre(order)
    x = z * 9.0
    weights = w * 9.0 * np.exp(-x*x) / math.sqrt(math.pi)
    return x, weights


@lru_cache(maxsize=64)
def gauss_nodes_interval(order: int, left: float, right: float) -> tuple[np.ndarray, np.ndarray]:
    z, w = _legendre(order)
    half = 0.5 * (right-left)
    x = half*z + 0.5*(right+left)
    weights = half*w*np.exp(-x*x)/math.sqrt(math.pi)
    return x, weights


def occupation(x: np.ndarray, eta: float, sigma: float, T: float) -> np.ndarray:
    y = (sigma*x - eta) / (K_B_EV_K*T)
    return 1.0 / (1.0 + np.exp(np.clip(y, -700.0, 700.0)))


def solve_eta(cb: float, sigma: float, T: float, order: int) -> tuple[float, float, float, float]:
    x, w = gauss_nodes(order)
    lo, hi = -3.0, 3.0
    for _ in range(100):
        mid = (lo + hi) * 0.5
        val = float(np.dot(w, occupation(x, mid, sigma, T)))
        if val < cb:
            lo = mid
        else:
            hi = mid
    eta = (lo + hi) * 0.5
    c = occupation(x, eta, sigma, T)
    integral = float(np.dot(w, c))
    mean_x = float(np.dot(w, x*c) / integral)
    return eta, integral, abs(integral-cb), mean_x


def x_quantile(q: float) -> float:
    # exp(-x^2)/sqrt(pi) is a normal law with mathematical sigma=1/sqrt(2).
    from statistics import NormalDist
    return NormalDist().inv_cdf(q) / math.sqrt(2.0)


def sample_roots(x_samples: np.ndarray, cb: float, sigma: float, T: float) -> np.ndarray:
    lo = np.full(x_samples.shape[0], -3.0)
    hi = np.full(x_samples.shape[0], 3.0)
    for _ in range(64):
        mid = (lo + hi) * 0.5
        y = (sigma*x_samples - mid[:, None]) / (K_B_EV_K*T)
        occ = 1.0 / (1.0 + np.exp(np.clip(y, -700.0, 700.0)))
        val = occ.mean(axis=1)
        below = val < cb
        lo = np.where(below, mid, lo)
        hi = np.where(below, hi, mid)
    return 0.5*(lo+hi)


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def calculate(source: Path, outdir: Path) -> dict:
    params = load_parameters(source)
    outdir.mkdir(parents=True, exist_ok=True)
    closures, tails, finite = [], [], []
    max_cb_residual = 0.0
    max_eta_quadrature_delta = 0.0
    max_tail_quadrature_delta = 0.0
    summary = {}
    for ia, p in enumerate(params):
        alloy_summary = {}
        for T in T_GRID:
            for cb in CB_GRID:
                eta, integral, residual, mean_x = solve_eta(cb, p["sigma"], T, 1024)
                eta_low, _, _, _ = solve_eta(cb, p["sigma"], T, 512)
                quad_delta = abs(eta-eta_low)
                max_cb_residual = max(max_cb_residual, residual)
                max_eta_quadrature_delta = max(max_eta_quadrature_delta, quad_delta)
                closures.append({
                    "alloy":p["alloy"], "T_K":int(T), "Cb_fraction":cb,
                    "eta_eV_mu_minus_Ebar":f"{eta:.12g}", "bulk_integral":f"{integral:.12g}",
                    "residual":f"{residual:.5g}", "quadrature_error":f"{quad_delta:.5g}",
                    "mu_energy_zero_convention":"eta=mu-Ebar; common unknown Ebar+EZP zero absorbed; no absolute mu asserted",
                })
                alloy_summary[f"{int(T)}K_{cb:g}"] = {"eta_eV":eta,"integral":integral,"mean_occupied_x":mean_x}
                x, w = gauss_nodes(1024)
                occ = occupation(x, eta, p["sigma"], T)
                for q in Q_GRID:
                    xq = x_quantile(q)
                    xt, wt = gauss_nodes_interval(1024, -9.0, xq)
                    below_integral = float(np.dot(wt, occupation(xt, eta, p["sigma"], T)))
                    xt_low, wt_low = gauss_nodes_interval(512, -9.0, xq)
                    below_low = float(np.dot(wt_low, occupation(xt_low, eta, p["sigma"], T)))
                    tail_quad_delta = abs(below_integral-below_low)
                    max_tail_quadrature_delta = max(max_tail_quadrature_delta,tail_quad_delta)
                    tails.append({
                        "alloy":p["alloy"],"T_K":int(T),"Cb_fraction":cb,"q":q,
                        "E_q_eV":f"{p['Ebar']+p['sigma']*xq:.12g}",
                        "occupation_below_Eq":f"{below_integral:.12g}",
                        "occupied_fraction_below_Eq":f"{below_integral/cb:.12g}",
                        "enrichment_ratio":f"{below_integral/(cb*q):.12g}",
                        "tail_integral_quadrature_delta_512_1024":f"{tail_quad_delta:.5g}",
                        "mean_occupied_energy_eV":f"{p['Ebar']+p['sigma']*mean_x:.12g}",
                    })
                for N in N_GRID:
                    seed_payload=f"{BASE_SEED}|{p['alloy']}|{int(T)}|{cb:.12g}|{N}".encode()
                    seed=int.from_bytes(hashlib.sha256(seed_payload).digest()[:4],"big")
                    rng=np.random.default_rng(seed)
                    xs=rng.normal(0.0,1/math.sqrt(2.0),(REPLICATES,N))
                    sample_eta=sample_roots(xs,cb,p["sigma"],T)
                    sample_bias=sample_eta-eta
                    for q in Q_GRID:
                        xq=x_quantile(q)
                        y=(p["sigma"]*xs-sample_eta[:,None])/(K_B_EV_K*T)
                        occ_s=1/(1+np.exp(np.clip(y,-700.0,700.0)))
                        fraction=(occ_s*(xs<=xq)).sum(axis=1)/occ_s.sum(axis=1)
                        eta_q=np.quantile(sample_bias,[.05,.5,.95])
                        frac_q=np.quantile(fraction,[.05,.5,.95])
                        half_eta=np.quantile(sample_bias[:REPLICATES//2],[.05,.5,.95])
                        half_frac=np.quantile(fraction[:REPLICATES//2],[.05,.5,.95])
                        second_eta=np.quantile(sample_bias[REPLICATES//2:],[.05,.5,.95])
                        second_frac=np.quantile(fraction[REPLICATES//2:],[.05,.5,.95])
                        finite.append({
                            "alloy":p["alloy"],"T_K":int(T),"Cb_fraction":cb,"N":N,"q":q,
                            "exact_P_no_tail_sample":f"{(1-q)**N:.12g}","replicates":REPLICATES,
                            "seed":seed,"eta_bias_interval_eV":json.dumps([float(x) for x in eta_q]),
                            "tail_occupied_fraction_sampling_interval":json.dumps([float(x) for x in frac_q]),
                            "half_batch_interval_endpoint_difference_eta_eV":f"{float(np.max(np.abs(half_eta-second_eta))):.12g}",
                            "half_batch_interval_endpoint_difference_tail_fraction":f"{float(np.max(np.abs(half_frac-second_frac))):.12g}",
                            "simulation_label":"hypothetical IID finite spectrum; not deposited site energies",
                        })
        summary[p["alloy"]]=alloy_summary
    write_csv(outdir/"concentration_closure.csv",closures)
    write_csv(outdir/"tail_enrichment.csv",tails)
    write_csv(outdir/"finite_sampling.csv",finite)
    result={
        "source":source.as_posix(),"source_width_convention":"E-Ebar=sigma*x; density exp(-x^2)/sqrt(pi); mathematical std=sigma/sqrt(2)",
        "energy_zero":"eta=mu-Ebar; if the same zero-point offset shifts Ebar and mu, eta and occupancy are invariant; no absolute mu claim",
        "kB_eV_K":K_B_EV_K,"T_K":T_GRID,"Cb_fraction":CB_GRID,"q":Q_GRID,"N":N_GRID,
        "MC_replicates":REPLICATES,"seed_scheme":f"SHA256({BASE_SEED}|alloy|T|Cb|N) first 32 bits",
        "quadrature":"Gauss-Legendre on x in [-9,9], 512/1024 order difference reported",
        "maximum_absolute_Cb_residual":max_cb_residual,
        "maximum_eta_512_1024_quadrature_delta_eV":max_eta_quadrature_delta,
        "maximum_tail_integral_512_1024_quadrature_delta":max_tail_quadrature_delta,
        "MC_interval_interpretation":"Sampling quantiles across hypothetical IID replicas, not confidence intervals for a source parameter; half-batch endpoint differences summarize finite replicate precision.",
        "rows":{"concentration_closure":len(closures),"tail_enrichment":len(tails),"finite_sampling":len(finite)},
        "limitations":["Finite ensembles are explicitly hypothetical IID Gaussian samples, not 295 reconstructed alloy sites.","The mean/width input is the published bulk probability model, not site-resolved DFT output.","ZP energy is absorbed into a common eta zero; absolute mu is not identified by these inputs."],
        "solutions":summary,
    }
    (outdir/"inference.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    return result


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",type=Path,required=True)
    ap.add_argument("--outdir",type=Path,required=True)
    args=ap.parse_args()
    result = calculate(args.source,args.outdir)
    import hashlib, shutil
    source_path=Path(__file__).resolve(); source_out=args.outdir/"calculation_source.py"
    shutil.copyfile(source_path,source_out)
    def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    outputs={p.name:digest(p) for p in args.outdir.iterdir() if p.is_file() and p.name not in {"calculation_source.py","run_metadata.json"}}
    metadata={"schema":"compchemworld-calculation-run/v1","command":"python calculation_source.py --source <public-input> --outdir <output-dir>","calculation_source_sha256":digest(source_out),"input":{"logical_name":args.source.name,"sha256":digest(args.source)},"output_sha256":outputs,"python":__import__("platform").python_version(),"execution_context":"local CPU calculation; this receipt does not assert independent author DFT execution"}
    (args.outdir/"run_metadata.json").write_text(json.dumps(metadata,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
CCB_SOLVE_PY
python3 "$work_dir/solve.py" --source /app/assets/absorption_distribution_fig2a.csv --outdir /app/final
