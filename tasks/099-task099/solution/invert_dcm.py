#!/usr/bin/env python3
import csv, json, math, sys
from collections import defaultdict
from pathlib import Path

assets, outdir = map(Path, sys.argv[1:3])
c=2.99792458e10; u=1.66053906660e-27
mm=95.95*u; mx=32.065*u; mred=mm*mx/(mm+2*mx)
def read(path,omega_col):
    data=defaultdict(list)
    with path.open(newline="",encoding="utf-8") as f:
        for r in csv.DictReader(f): data[r["N"].strip()].append((float(r["P_GPa"]),float(r[omega_col])))
    return data
e1=read(assets/"public_e2g1_vs_p.csv","omega_E2g1_cm1")
e2=read(assets/"public_e2g2_vs_p.csv","omega_cm1")
def linreg(points):
    xm=sum(x for x,y in points)/len(points); ym=sum(y for x,y in points)/len(points)
    den=sum((x-xm)**2 for x,y in points); return sum((x-xm)*(y-ym) for x,y in points)/den
cb_map=defaultdict(dict); cw_map=defaultdict(dict); ratio_map=defaultdict(dict); rows=[]
for n, p2 in e2.items():
    for p,nu2 in p2:
        matches=[(p1,nu1) for p1,nu1 in e1.get(n,[]) if abs(p1-p)<=0.25]
        if not matches: continue
        p1,nu1=min(matches,key=lambda item:abs(item[0]-p))
        w1=(2*math.pi*c*nu1)**2; w2=(2*math.pi*c*nu2)**2
        b=(w1+w2)*mx/2; cc=w1*w2*mx*(mm+2*mx)/8; disc=b*b-4*cc
        cb=(b-math.sqrt(disc))/2
        cw=(w1*w2*mm*mx/4)/cb
        base=cw/(2*mred)+cb/mx; root=math.sqrt(base*base-4*cw*cb/(mm*mx))
        back1=math.sqrt(base+root)/(2*math.pi*c); back2=math.sqrt(base-root)/(2*math.pi*c)
        ratio=cb/cw; key=f"{p:g}"
        cb_map[n][key]=cb;cw_map[n][key]=cw;ratio_map[n][key]=ratio
        rows.append([n,p,cb,cw,ratio,nu1,nu2,back1,back2])
slopes_b={};slopes_w={}
for n in cb_map:
    ptsb=[(float(p),v) for p,v in cb_map[n].items()]; ptsw=[(float(p),v) for p,v in cw_map[n].items()]
    slopes_b[n]=linreg(ptsb);slopes_w[n]=linreg(ptsw)
result={"Cs_b":dict(cb_map),"Cs_w":dict(cw_map),"ratio_Cs_b_over_Cs_w":dict(ratio_map),"dCs_b_dP":slopes_b,"dCs_w_dP":slopes_w,
"physical_root_rationale":"The DCM quadratic has two positive roots for the breathing coupling. Select the smaller positive root for Cs_b because the larger root is the nonphysical branch; derive Cs_w from the product invariant and verify by back-substitution into both eigenfrequencies.",
"pairing_rule":"For every pressure listed in E2g2, pair the E2g1 source point with minimum absolute pressure difference, accepting only differences up to 0.25 GPa. Keep the E2g2 pressure as the table pressure and report the selected measured E2g1 pressure's observed frequency."}
outdir.mkdir(parents=True,exist_ok=True)
(outdir/"results.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
with (outdir/"dcm_table.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.writer(f);w.writerow(["N","P_GPa","Cs_b","Cs_w","ratio","omega_E2g1_cm1","omega_E2g2_cm1","omega_E2g1_back_cm1","omega_E2g2_back_cm1"]);w.writerows(rows)
