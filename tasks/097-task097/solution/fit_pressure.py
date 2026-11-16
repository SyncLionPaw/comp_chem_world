#!/usr/bin/env python3
import csv, json, math, sys
from collections import defaultdict
from pathlib import Path

assets, outdir = map(Path, sys.argv[1:3])
def read(name):
    with (assets / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
def load(name):
    out = defaultdict(list)
    for r in read(name):
        if r["N"].strip().lower() == "bulk": continue
        out[int(r["N"])].append((float(r["P_GPa"]), float(r["omega_cm1"])))
    return out
def fit(series, lo, hi):
    pts = [(p, y) for p, y in series if lo <= p <= hi]
    if len(pts) < 2: return None
    xs, ys = zip(*pts); xm, ym = sum(xs)/len(xs), sum(ys)/len(ys)
    den = sum((x-xm)**2 for x in xs)
    slope = sum((x-xm)*(y-ym) for x,y in pts)/den
    intercept = ym-slope*xm
    resid = [y-(slope*x+intercept) for x,y in pts]
    se = math.sqrt((sum(e*e for e in resid)/max(len(pts)-2,1))/den)
    return {"slope":slope,"intercept":intercept,"n_points":len(pts),"se":se}
s, lb = load("public_s_n1_vs_p.csv"), load("public_lb_nnminus1_vs_p.csv")
primary, alternate = (1.,8.), (0.,6.3)
fs = {n:fit(v,*primary) for n,v in s.items()}; fl = {n:fit(v,*primary) for n,v in lb.items()}
fs = {n:v for n,v in fs.items() if v}; fl = {n:v for n,v in fl.items() if v}
ss={n:v["slope"] for n,v in fs.items()}; ls={n:v["slope"] for n,v in fl.items()}
shared=sorted(set(ss)&set(ls)); first=None
for a,b in zip(shared,shared[1:]):
    d0,d1=ss[a]-ls[a],ss[b]-ls[b]
    if d0==0: first=a; break
    if d0*d1<0: first=b if d1>0 else a; break
# Continuous crossing from independent zero-intercept MCM fits of the measured slopes.
snum=sden=lnum=lden=0.
for n,v in fs.items():
    if n in range(2,10):
        q=math.cos(math.pi/(2*n)); sden+=q*q; snum+=q*v["slope"]
for n,v in fl.items():
    if n in (2,4,5,6,7,8,9):
        q=math.sin(math.pi/(2*n)); lden+=q*q; lnum+=q*v["slope"]
cont=math.pi/(2*math.atan2(snum/sden,lnum/lden))
alt_s={str(n):fit(v,*alternate)["slope"] for n,v in s.items() if fit(v,*alternate)}
result={
 "domega_dP_S_cm1_per_GPa":{str(n):v["slope"] for n,v in fs.items()},
 "domega_dP_LB_cm1_per_GPa":{str(n):v["slope"] for n,v in fl.items()},
 "pressure_window_GPa":{"pmin":primary[0],"pmax":primary[1]},
 "window_sensitivity":{"alt_window":{"pmin":alternate[0],"pmax":alternate[1]},"slopes_S":alt_s},
 "crossover_N_continuous":cont,
 "crossover_N_integer_first_observed_reversal":first,
 "crossover_continuous_method":"mcm",
 "n3_LB_status":{"available_in_packaged_data":bool(lb.get(3)),"imputed":False}}
outdir.mkdir(parents=True,exist_ok=True)
(outdir/"results.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
with (outdir/"slope_fits.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.writer(f);w.writerow(["N","branch","slope","intercept","n_points","se"])
    for label,fits in (("S_N1",fs),("LB_N,N-1",fl)):
        for n,v in sorted(fits.items()):w.writerow([n,label,v["slope"],v["intercept"],v["n_points"],v["se"]])
