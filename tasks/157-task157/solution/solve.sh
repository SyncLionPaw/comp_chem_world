#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="${1:-${APP:-/app}}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INPUT_ROOT="$APP_ROOT/inputs"
if [[ ! -d "$INPUT_ROOT" ]]; then INPUT_ROOT="$SCRIPT_DIR/../environment/assets"; fi
export CASE_INPUTS="$INPUT_ROOT"
python3 - "$APP_ROOT/outputs" <<'PYCODE'
#!/usr/bin/env python3
"""Compute α-quartz slab surface metrics from the deposited public extxyz files."""
from __future__ import annotations
import csv, json, math, os, re, sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ORIENTATIONS = ("001", "011", "100_alpha", "100_beta", "101")
FACTOR = 16.02176634
RMSE_MAX = 0.004
CLEAVED_INPUT_ROUNDING_HALF_WIDTH = 0.0005
EXPECTED_COUNTS = {"001": 4, "011": 9, "100_alpha": 7, "100_beta": 6, "101": 9}

default_inputs = Path(__file__).resolve().parent / "environment" / "assets"
case = Path(os.environ.get("CASE_INPUTS", default_inputs)).resolve()
if not case.is_dir():
    case = Path("/app/inputs")
if (case / "inputs").is_dir():
    case = case / "inputs"
out = Path(sys.argv[1] if len(sys.argv) > 1 else "/app/outputs").resolve()
surf_root = case / "surfaces/alpha_quartz"

def parse_xyz(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    n = int(lines[0].strip())
    lattice = re.search(r'Lattice="([^"]+)"', lines[1])
    energy = re.search(r"(?:^|\s)energy=([-+0-9.eE]+)", lines[1])
    if not lattice or not energy:
        raise SystemExit(f"missing Lattice or energy metadata: {path}")
    cell = np.asarray([float(x) for x in lattice.group(1).split()], float).reshape(3, 3)
    symbols, xyz = [], []
    for line in lines[2:2+n]:
        row = line.split()
        symbols.append(row[0]); xyz.append([float(x) for x in row[1:4]])
    if len(symbols) != n:
        raise SystemExit(f"atom count mismatch: {path}")
    normal = np.cross(cell[0], cell[1]); area = float(np.linalg.norm(normal))
    if area <= 0:
        raise SystemExit(f"invalid in-plane area: {path}")
    xyz = np.asarray(xyz, float)
    return {"file": path.name, "N": n, "Si": symbols.count("Si"), "O": symbols.count("O"),
            "energy": float(energy.group(1)), "cell": cell, "area": area,
            "span": float(np.ptp(xyz @ (normal / area)))}

def fit(data):
    n = np.asarray([x["N"] for x in data], float)
    e = np.asarray([x["energy"] for x in data], float)
    slope, intercept = np.polyfit(n, e, 1)
    resid = e - (slope*n + intercept)
    rmse = float(np.sqrt(np.mean(resid**2)))
    if len(n) > 2:
        s2 = float(np.sum(resid**2)/(len(n)-2))
        sxx = float(np.sum((n-n.mean())**2))
        se_intercept = math.sqrt(s2*(1/len(n) + n.mean()**2/sxx))
    else:
        se_intercept = 0.0
    return float(slope), float(intercept), rmse, se_intercept

slabs = {}
for orientation in ORIENTATIONS:
    paths = sorted((surf_root/orientation).glob("surface.*.xyz"), key=lambda p: int(p.stem.split(".")[1]))
    rows = [parse_xyz(p) for p in paths]
    if len(rows) != EXPECTED_COUNTS[orientation]:
        raise SystemExit(f"{orientation}: expected {EXPECTED_COUNTS[orientation]} slabs; found {len(rows)}")
    rows.sort(key=lambda r: r["N"])
    slabs[orientation] = rows

cleaved = {}
with (case/"cleaved_dft_surface_energies.csv").open(encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        cleaved[row["orientation"]] = float(row["gamma_cleaved_eV_per_A2"])
if set(cleaved) != set(ORIENTATIONS):
    raise SystemExit("cleaved input does not cover all five orientations")

out.mkdir(parents=True, exist_ok=True); (out/"figures").mkdir(exist_ok=True)
def write_csv(name, header, rows):
    with (out/name).open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=header); w.writeheader(); w.writerows(rows)

audit=[]; fit_rows=[]; energies={}; uncertainty={}; areas={}; audit_summary={}
for ori, rows in slabs.items():
    area_values=[r["area"] for r in rows]
    if max(area_values)-min(area_values)>1e-6:
        raise SystemExit(f"{ori}: in-plane area changes through slab series")
    area=area_values[0]; areas[ori]=area
    for r in rows:
        if r["Si"]*2 != r["O"] or r["Si"]+r["O"] != r["N"]:
            raise SystemExit(f"{ori}/{r['file']}: composition is not stoichiometric SiO2")
        audit.append({"orientation":ori,"slab_file":r["file"],"N_atoms":r["N"],"N_Si":r["Si"],"N_O":r["O"],
            "area_A2":f"{r['area']:.12g}","atomic_span_A":f"{r['span']:.12g}",
            "cell_vectors_A":json.dumps(r["cell"].tolist(),separators=(",",":")),"stoichiometry":"Si:O=1:2",
            "geometry_note":"stoichiometric SiO2; area=|a x b|; atomic span is max-minus-min projection along surface normal"})
    audit_summary[ori]={"n_slabs":len(rows),"N_atoms":[r["N"] for r in rows],"stoichiometry":"Si:O=1:2","area_A2":area}
    stats={}
    for k in range(3,len(rows)+1):
        m,b,rmse,se_b=fit(rows[-k:]); stats[k]=(m,b,rmse,se_b)
        if rmse<=RMSE_MAX:
            fit_rows.append({"orientation":ori,"reconstruction":"relaxed_from_slab",
              "window_files":json.dumps([r["file"] for r in rows[-k:]],separators=(",",":")),
              "window_N_min":min(r["N"] for r in rows[-k:]),"window_N_max":max(r["N"] for r in rows[-k:]),
              "slope_eV_per_atom":f"{m:.15g}","intercept_eV":f"{b:.15g}","residual_RMSE_eV":f"{rmse:.15g}",
              "n_points":k,"fit_assumptions":"OLS E_cell vs N_atoms on a contiguous thick-slab tail; symmetric two-face slab; mu=slope; gamma=intercept/(2A)"})
    if 3 not in stats or 4 not in stats or stats[3][2]>RMSE_MAX or stats[4][2]>RMSE_MAX:
        raise SystemExit(f"{ori}: last-3/last-4 slab fits fail RMSE threshold")
    gamma_by_k={k:stats[k][1]/(2*area) for k in stats if stats[k][2]<=RMSE_MAX}
    drift=max(gamma_by_k.values())-min(gamma_by_k.values())
    g=stats[3][1]/(2*area)
    uncertainty[ori]=max(drift,stats[3][3]/(2*area))
    energies[ori]={"gamma":g,"slope":stats[3][0],"drop":cleaved[ori]-g,"drift":drift}

cleaved_order=sorted(ORIENTATIONS,key=lambda o:cleaved[o])
relaxed_order=sorted(ORIENTATIONS,key=lambda o:energies[o]["gamma"])

def classify_order(order, values, uncertainty_for_pair):
    tied=set()
    for left,right in zip(order,order[1:]):
        if abs(values[left]-values[right]) <= uncertainty_for_pair(left,right) + 1e-12:
            tied.update((left,right))
    labels={ori:("near_degenerate" if ori in tied else f"rank_{idx}")
            for idx,ori in enumerate(order,1)}
    return labels,tied

cleaved_labels,cleaved_tied=classify_order(
    cleaved_order,cleaved,
    lambda _a,_b: 2*CLEAVED_INPUT_ROUNDING_HALF_WIDTH)
relaxed_values={o:energies[o]["gamma"] for o in ORIENTATIONS}
# Conservative comparison budget combines source rounding with the relaxed
# tail-fit spread; this is a cross-stage ranking allowance, not fit uncertainty alone.
relaxed_labels,relaxed_tied=classify_order(
    relaxed_order,relaxed_values,
    lambda a,b: 2*CLEAVED_INPUT_ROUNDING_HALF_WIDTH+uncertainty[a]+uncertainty[b])
changed_order={o for o in ORIENTATIONS if cleaved_order.index(o)!=relaxed_order.index(o)}
uncertainty_overlapping=cleaved_tied | relaxed_tied
rank_change_near_degenerate=changed_order & uncertainty_overlapping
rank_change_robust=bool(changed_order - uncertainty_overlapping)
cleaved_near=[o for o in cleaved_order if o in cleaved_tied]
relaxed_near=[o for o in relaxed_order if o in relaxed_tied]
if changed_order and not rank_change_robust:
    rank_change_confidence=("ordering differences are confined to uncertainty-overlapping adjacent orientations: "
                            + ", ".join(o for o in ORIENTATIONS if o in rank_change_near_degenerate))
elif changed_order:
    rank_change_confidence=("at least one ordering difference lies outside the declared uncertainty-overlap intervals")
else:
    rank_change_confidence=("orientation order is unchanged between the computed cleaved and relaxed values")
surface_rows=[];surface_summary={};effects={}
for ori in ORIENTATIONS:
    area=areas[ori]; g=energies[ori]["gamma"]; c=cleaved[ori]; u=uncertainty[ori]
    surface_rows.extend([
      {"orientation":ori,"reconstruction":"cleaved_published_input","area_A2":f"{area:.12g}","gamma_eV_per_A2":f"{c:.15g}","gamma_J_per_m2":f"{c*FACTOR:.15g}","uncertainty_eV_per_A2":f"{CLEAVED_INPUT_ROUNDING_HALF_WIDTH:.15g}","uncertainty_J_per_m2":f"{CLEAVED_INPUT_ROUNDING_HALF_WIDTH*FACTOR:.12g}","bulk_reference":"not_applicable (published cleaved value)","converged":"not_applicable","decision":cleaved_labels[ori],"reason":"published cleaved energy from public input; no cleaved geometry supplied"},
      {"orientation":ori,"reconstruction":"relaxed_from_slab","area_A2":f"{area:.12g}","gamma_eV_per_A2":f"{g:.15g}","gamma_J_per_m2":f"{g*FACTOR:.15g}","uncertainty_eV_per_A2":f"{u:.15g}","uncertainty_J_per_m2":f"{u*FACTOR:.15g}","bulk_reference":f"last-3 E(N) slope mu={energies[ori]['slope']:.12g} eV/atom","converged":"true","decision":relaxed_labels[ori],"reason":f"last-3 E(N) fit; valid-window gamma drift={energies[ori]['drift']:.8g} eV/A^2; uncertainty=max(drift, intercept standard error/(2A))"}
    ])
    surface_summary[ori]={"gamma_relaxed_eV_per_A2":g,"gamma_cleaved_eV_per_A2":c,"relaxation_energy_drop_eV_per_A2":c-g,"uncertainty_eV_per_A2":u,"area_A2":area}
    effects[ori]={"drop_eV_per_A2":c-g,"drop_J_per_m2":(c-g)*FACTOR,"significant":c-g>u+CLEAVED_INPUT_ROUNDING_HALF_WIDTH}
write_csv("orientation_audit.csv",["orientation","slab_file","N_atoms","N_Si","N_O","area_A2","atomic_span_A","cell_vectors_A","stoichiometry","geometry_note"],audit)
write_csv("slab_fit.csv",["orientation","reconstruction","window_files","window_N_min","window_N_max","slope_eV_per_atom","intercept_eV","residual_RMSE_eV","n_points","fit_assumptions"],fit_rows)
write_csv("surface_energy.csv",["orientation","reconstruction","area_A2","gamma_eV_per_A2","gamma_J_per_m2","uncertainty_eV_per_A2","uncertainty_J_per_m2","bulk_reference","converged","decision","reason"],surface_rows)
summary={"method":{"fit":"orientation-specific ordinary least-squares E_cell=N*mu+intercept on contiguous thick-slab tails","surface_energy":"gamma=intercept/(2A), with A=|a cross b| and two equivalent faces","conversion_eV_per_A2_to_J_per_m2":FACTOR,"geometry":"surface normal is the normalized cross product of the first two cell vectors; atomic span is max-minus-min projection"},
 "orientation_audit":audit_summary,"bulk_reference":{o:{"mu_eV_per_atom":energies[o]["slope"],"method":"orientation-specific last-3 thick-slab E(N) slope"} for o in ORIENTATIONS},
 "surface_energy":surface_summary,"reconstruction_effect":effects,
 "ranking":{"cleaved_low_to_high":cleaved_order,"relaxed_low_to_high":relaxed_order,"cleaved_near_degenerate":cleaved_near,"relaxed_near_degenerate":relaxed_near,"rank_change_robust":rank_change_robust,"rank_change_near_degenerate":[o for o in ORIENTATIONS if o in rank_change_near_degenerate],"rank_change_confidence":rank_change_confidence},
 "uncertainty":{"relaxed_surface_energy_eV_per_A2":uncertainty,"cleaved_rounding_half_width_eV_per_A2":CLEAVED_INPUT_ROUNDING_HALF_WIDTH,"basis":"cleaved-source rounding interval; relaxed uncertainty is the maximum of the full valid thick-window gamma range and last-3 intercept standard error divided by twice the surface area"},
 "figure_panels":["orientation_specific_E_N_fits","cleaved_vs_relaxed_surface_energy"],
 "limitations":["cleaved atomic geometries were not supplied; only published cleaved energy values are compared","surface energies are symmetric two-face slab averages","near-degeneracy and ranking are classified from computed energies and the declared source-rounding and fit-window uncertainty intervals"]}
(out/"summary.json").write_text(json.dumps(summary,indent=2,allow_nan=False)+"\n",encoding="utf-8")
fig,(ax,gax)=plt.subplots(1,2,figsize=(12,5),gridspec_kw={"width_ratios":[1.65,1]})
colors=plt.rcParams["axes.prop_cycle"].by_key()["color"]
for i,ori in enumerate(ORIENTATIONS):
    rows=slabs[ori]; m,b,_,_=fit(rows[-3:]); n=np.array([r["N"] for r in rows]); e=np.array([r["energy"] for r in rows])
    ax.scatter(n,e,label=ori,color=colors[i]); nn=np.linspace(n[-3],n[-1],80); ax.plot(nn,m*nn+b,color=colors[i],linestyle="--")
ax.set(xlabel="Slab atom count N",ylabel="Total slab energy E (eV)",title="Orientation-specific E(N) fits (dashed)");ax.grid(alpha=.2);ax.legend(title="Orientation",fontsize=8)
x=np.arange(len(ORIENTATIONS));width=.36
cj=np.array([cleaved[o]*FACTOR for o in ORIENTATIONS]);rj=np.array([energies[o]["gamma"]*FACTOR for o in ORIENTATIONS])
axerr=np.array([uncertainty[o]*FACTOR for o in ORIENTATIONS])
gax.bar(x-width/2,cj,width,yerr=np.full(5,CLEAVED_INPUT_ROUNDING_HALF_WIDTH*FACTOR),label="Cleaved input",color="#8aa6c1",capsize=2)
gax.bar(x+width/2,rj,width,yerr=axerr,label="Relaxed from slabs",color="#d58a61",capsize=2)
gax.set_xticks(x,ORIENTATIONS,rotation=30,ha="right");gax.set_ylabel("Surface energy γ (J/m²)");gax.set_title("Cleaved and relaxed comparison");gax.grid(axis="y",alpha=.2);gax.legend(fontsize=8)
fig.tight_layout();fig.savefig(out/"figures/thickness_fit.png",dpi=180);plt.close(fig)
print(f"computed {sum(map(len,slabs.values()))} slabs; wrote outputs under {out}")

PYCODE
