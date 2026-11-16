#!/usr/bin/env python3
import csv, json, math, sys
from pathlib import Path

source, outdir = map(Path, sys.argv[1:3])
with source.open(newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))
rows = [r for r in rows if 2 <= int(r["N"]) <= 9]
branches = {"S_N1": ("omega_S_N1_cm1", "high"), "LB_highest": ("omega_LB_highest_cm1", "high")}
fits, table = {}, []
for label, (column, _) in branches.items():
    pts = [(int(r["N"]), float(r[column])) for r in rows if r.get(column)]
    basis = [math.sin((n - 1) * math.pi / (2 * n)) for n, _ in pts]
    bulk = sum(x * y for x, (_, y) in zip(basis, pts)) / sum(x * x for x in basis)
    fits[label] = bulk
    for n, observed in pts:
        table.append((n, label, observed, bulk * math.sin((n - 1) * math.pi / (2 * n))))
c, mu = 2.99792458e10, 3.0738408378142946e-6
alpha = [mu * (math.pi * c * fits[k]) ** 2 / 1e19 for k in ("S_N1", "LB_highest")]
result = {"omega_S_bulk_cm1": fits["S_N1"], "omega_LB_bulk_cm1": fits["LB_highest"], "alpha_parallel_e19": alpha[0], "alpha_perp_e19": alpha[1]}
outdir.mkdir(parents=True, exist_ok=True)
(outdir / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
with (outdir / "fit_table.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["N", "branch", "omega_exp_cm1", "omega_fit_cm1"]); w.writerows(table)
