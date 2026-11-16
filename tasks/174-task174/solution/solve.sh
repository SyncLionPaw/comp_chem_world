#!/bin/sh
set -eu
APP_DIR=${APP:-/app}
ASSETS="$APP_DIR/environment/assets"
mkdir -p "$APP_DIR/final"
PYTHON=${PYTHON:-python3}
PYTHONDONTWRITEBYTECODE=1 "$PYTHON" - "$ASSETS" "$APP_DIR/final/environments.json" <<'PY'
import csv, json, math, re, sys
from pathlib import Path
import numpy as np
assets, output = map(Path, sys.argv[1:])
units = (assets / "literature" / "units.txt").read_text()
temp_match = re.search(r"temperature_K\s+([0-9.eE+-]+)", units)
if not temp_match:
    raise ValueError("temperature missing from units.txt")
temperature = float(temp_match.group(1))
unit_map = {}
for line in units.splitlines():
    match = re.match(r"\s*(\S+)\s+r_unit\s+(\S+)", line)
    if match:
        unit_map[match.group(1)] = match.group(2).lower()
k_b = 0.00198720425864083  # kcal mol^-1 K^-1
rdf_path = assets / "li_li_rdf_this_work.csv"
rows = []
with rdf_path.open(newline="") as handle:
    for row in csv.reader(handle, delimiter=";"):
        if len(row) >= 2:
            try: rows.append((float(row[0].strip()) / 100.0, float(row[1].strip())))
            except ValueError: continue
if not rows: raise ValueError("author RDF contains no numeric samples")
r, g = map(np.asarray, zip(*rows))
def sampled_min(mask):
    ix = np.flatnonzero(mask)
    if not len(ix): raise ValueError("RDF has no samples in a required range")
    i = ix[np.argmin(g[ix])]
    return float(r[i])
contact = (r > 2.2) & (r < 2.8)
if not contact.any(): raise ValueError("no author contact-peak samples")
i_peak = np.flatnonzero(contact)[np.argmax(g[contact])]
well = (r > 2.2) & (r < 2.7) & (g > 1e-8)
saddle = (r > 2.7) & (r < 3.3) & (g > 1e-8)
if not well.any() or not saddle.any(): raise ValueError("insufficient positive RDF samples for PMF barrier")
f_well = -k_b * temperature * np.log(g[well])
f_saddle = -k_b * temperature * np.log(g[saddle])
barrier = float(np.max(f_saddle) - np.min(f_well))
qualifying, any_match = [], False
for path in sorted((assets / "literature").glob("*")):
    if path.name == "units.txt" or path.name not in unit_map: continue
    raw=[]
    for line in path.read_text().splitlines():
        cols = line.split()
        if len(cols) < 2: continue
        try: raw.append((float(cols[0]), float(cols[1])))
        except ValueError: continue
    if not raw: continue
    factor = {"angstrom":1.0, "ang":1.0, "nm":10.0, "nanometer":10.0}.get(unit_map[path.name])
    if factor is None: raise ValueError(f"unsupported distance unit for {path.name}")
    grouped={}
    for x,y in raw: grouped.setdefault(x*factor,[]).append(y)
    curve=sorted((x, sum(ys)/len(ys)) for x,ys in grouped.items())
    peaks=[]
    for j in range(1,len(curve)-1):
        x,y=curve[j]
        if y > curve[j-1][1] and y >= curve[j+1][1] and x < 3.0 and y >= 0.6:
            peaks.append((x,y))
    if peaks: qualifying.append(path.name)
    for x,y in peaks:
        if abs(x-float(r[i_peak])) <= .1 and abs(y-float(g[i_peak])) <= .2*float(g[i_peak]): any_match=True
result={"r_first_maximum_A":float(r[i_peak]),"g_first_maximum":float(g[i_peak]),"r_boundary_I_II_A":sampled_min((r>2.7)&(r<3.3)),"r_boundary_II_III_A":sampled_min((r>3.6)&(r<4.5)),"barrier_I_II_kcal_mol":barrier,"barrier_comparable_to_kT":0.5 <= barrier/(k_b*temperature) <= 2.0,"curves_with_maximum_below_3A_and_g_at_least_0.6":qualifying,"any_literature_curve_matches_aimd_peak_near_2.5A":any_match}
output.write_text(json.dumps(result,indent=2)+"\n")
PY
