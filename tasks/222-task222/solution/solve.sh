#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# case-06 reference solution: Henderson-Hasselbalch fitting from pre-generated
# λ trajectories.
#
# Reference solution.  NOT agent-visible.  It exists so the verifier can be
# calibrated with a solution that is known to be correct, and so that the case
# can be regression-tested without any model involvement.
#
#   Usage: solve.sh [output_dir]
#          (default output_dir: $OUT, else /app/final)
#
# The analysis is deliberately implemented with the Python standard library
# only, so the gold path runs in any container regardless of whether numpy /
# scipy are present.  numpy + scipy.optimize.curve_fit are listed as available
# to the agent and produce equivalent numbers; the verifier does not care which
# route the agent takes.
# ---------------------------------------------------------------------------
set -euo pipefail

OUT="${1:-${OUT:-/app/final}}"
PKG="${APP:-/app}"
mkdir -p "$OUT"

python3 - "$PKG" "$OUT" <<'PY'
import json
import math
import os
import re
import sys

pkg, out = sys.argv[1], sys.argv[2]
TRAJ = os.path.join(pkg, "environment", "assets", "lambda_trajectories")

PH_RANGES = {
    "asp": [1.00, 1.75, 2.50, 3.25, 4.00, 4.75, 5.50, 6.25, 7.00],
    "glu": [2.00, 2.75, 3.50, 4.25, 5.00, 5.75, 6.50, 7.25, 8.00],
    "his": [4.00, 4.75, 5.50, 6.25, 7.00, 7.75, 8.50, 9.25, 10.00],
}
N_REPLICAS = 3
LAMBDA_PROT = 0.2      # λ < 0.2  -> protonated
LAMBDA_DEPROT = 0.8    # λ > 0.8  -> deprotonated


def parse_xvg(path):
    """Return the λ column of a 2-column GROMACS .xvg file."""
    lam = []
    with open(path) as fh:
        for line in fh:
            if not line or line[0] in "#@":
                continue
            parts = line.split()
            if len(parts) >= 2:
                lam.append(float(parts[1]))
    if not lam:
        raise RuntimeError("no data parsed from %s" % path)
    return lam


def s_deprotonated(lam):
    """Population fraction in the deprotonated basin.

    Frames with an intermediate λ (0.2 <= λ <= 0.8) are excluded from both
    counts; with the symmetric λ distribution this is the unbiased estimator of
    the deprotonated population (unbiased estimator of the deprotonated population).
    """
    n_prot, n_deprot, _ = state_counts(lam)
    if n_prot + n_deprot == 0:
        return 0.5
    return n_deprot / float(n_prot + n_deprot)


def state_counts(lam):
    """Frame counts in the three regimes fixed by the case definition."""
    n_prot = sum(1 for x in lam if x < LAMBDA_PROT)
    n_deprot = sum(1 for x in lam if x > LAMBDA_DEPROT)
    return n_prot, n_deprot, len(lam) - n_prot - n_deprot


def hh(ph, pka):
    """Henderson-Hasselbalch deprotonated fraction S(pH; pKa)."""
    return 1.0 / (1.0 + 10.0 ** (pka - ph))


def fit_pka(ph_list, s_list):
    """1-D nonlinear least squares fit of pKa by golden-section search.

    Returns (pKa, std_err).  The standard error is the usual nonlinear
    least-squares covariance estimate  var = sigma^2 / sum_k (dS/dpKa)^2  with
    dS/dpKa = -ln(10) * S * (1 - S) and sigma^2 = SSE / (n - 1), which is the
    analytic equivalent of the diagonal of the covariance matrix returned by
    scipy.optimize.curve_fit for a single free parameter.
    """
    def sse(x):
        return sum((hh(p, x) - s) ** 2 for p, s in zip(ph_list, s_list))

    gr = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = min(ph_list) - 3.0, max(ph_list) + 3.0
    c, d = b - gr * (b - a), a + gr * (b - a)
    fc, fd = sse(c), sse(d)
    for _ in range(300):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - gr * (b - a)
            fc = sse(c)
        else:
            a, c, fc = c, d, fd
            d = a + gr * (b - a)
            fd = sse(d)
        if b - a < 1e-12:
            break
    pka = 0.5 * (a + b)

    n = len(ph_list)
    sse_min = sse(pka)
    sigma2 = sse_min / (n - 1) if n > 1 else 0.0
    ln10 = math.log(10.0)
    jac2 = sum((ln10 * hh(p, pka) * (1.0 - hh(p, pka))) ** 2 for p in ph_list)
    stderr = math.sqrt(sigma2 / jac2) if jac2 > 0 else float("nan")
    return pka, stderr, sse_min


results = []
titration_rows = []

for residue in ("asp", "glu", "his"):
    ph_list = PH_RANGES[residue]
    means, sems = [], []
    counts = []
    for ph in ph_list:
        replica_s = []
        n_prot = n_inter = n_deprot = 0
        for replica in range(1, N_REPLICAS + 1):
            path = os.path.join(TRAJ, "%s_ph%.2f_replica%d.xvg" % (residue, ph, replica))
            lam = parse_xvg(path)
            replica_s.append(s_deprotonated(lam))
            prot, deprot, inter = state_counts(lam)
            n_prot += prot
            n_deprot += deprot
            n_inter += inter
        mean = sum(replica_s) / len(replica_s)
        if len(replica_s) > 1:
            var = sum((x - mean) ** 2 for x in replica_s) / (len(replica_s) - 1)
            sem = math.sqrt(var / len(replica_s))
        else:
            sem = 0.0
        means.append(mean)
        sems.append(sem)
        counts.append((n_prot, n_inter, n_deprot))

    pka, stderr, _ = fit_pka(ph_list, means)
    ci_lower = pka - 1.96 * stderr
    ci_upper = pka + 1.96 * stderr

    results.append({
        "residue": residue,
        "pKa": round(pka, 4),
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "pka_std_err": round(stderr, 5),
        "n_ph_points": len(ph_list),
        "n_replicas": N_REPLICAS,
    })

    for ph, mean, sem, (n_prot, n_inter, n_deprot) in zip(ph_list, means, sems, counts):
        titration_rows.append((residue, ph, mean, sem, hh(ph, pka),
                               n_prot, n_inter, n_deprot))

with open(os.path.join(out, "pka_results.json"), "w") as fh:
    json.dump(results, fh, indent=2)
    fh.write("\n")

with open(os.path.join(out, "titration_curves.csv"), "w") as fh:
    fh.write("residue,pH,S_deprot_mean,S_deprot_sem,S_fit,"
             "n_protonated,n_intermediate,n_deprotonated\n")
    for row in titration_rows:
        residue, ph, mean, sem, fit, n_prot, n_inter, n_deprot = row
        fh.write("%s,%.2f,%.6f,%.6f,%.6f,%d,%d,%d\n"
                 % (residue, ph, mean, sem, fit, n_prot, n_inter, n_deprot))

for r in results:
    sys.stderr.write("fitted pKa %-3s = %.3f  (95%% CI %.3f - %.3f)\n"
                     % (r["residue"], r["pKa"], r["ci_lower"], r["ci_upper"]))
PY

echo "solve.sh: wrote pka_results.json + titration_curves.csv to $OUT"
