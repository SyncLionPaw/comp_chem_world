#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="${APP:-/app}"
SOLVEFILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
export SOLVEFILE
export CASE_PACKAGE="$APP_ROOT"
python - "$APP_ROOT/outputs" <<'PYGEN'
#!/usr/bin/env python3
"""Build a full Case02 positive candidate from the public Gibbs tables."""
from __future__ import annotations
import csv, json, math, os, sys
from pathlib import Path
import numpy as np

__file__=os.environ.get("SOLVEFILE", __file__)
SCRIPT_PATH=Path(__file__).resolve()
ROOT=SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents)>3 else Path("/app")
OUT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/"acceptance/local-completion/case-02/positive/outputs"
PKG=Path(os.environ.get("CASE_PACKAGE", ROOT/"packages/case-02")).resolve()
INPUT_ROOT=next((candidate for candidate in (PKG/"inputs", PKG/"environment"/"assets", Path("/app/inputs")) if candidate.is_dir()), None)
if INPUT_ROOT is None:
    raise SystemExit("ERROR: public phase-diagram inputs are unavailable")
PHASES=("alpha_quartz", "beta_quartz", "coesite", "cristobalite", "melt", "tridymite", "tridymite_low")
GRID_HEADER=["T_K", "P_bar", "valid_phases", "G_min_meV_per_atom", "stable_phase", "reason"]
BOUNDARY_HEADER=["boundary_id", "phase_a", "phase_b", "T_K", "P_bar", "kind", "valid_overlap", "uncertainty_bar", "basis", "reason"]
SENS_HEADER=["perturbation_meV_per_atom", "perturbed_phase", "sign", "boundary_id", "phase_a", "phase_b", "T_K", "nominal_P_bar", "perturbed_P_bar", "delta_P_bar", "valid_overlap", "ambiguous_domain", "reason"]
P=np.arange(0.,50000.1,100.)

def canonical_pair(a,b): return tuple(sorted((a,b)))

def load_public():
    fits={p:{} for p in PHASES}
    for phase in PHASES:
        with (INPUT_ROOT/"phase_diagram"/phase/"fit_gibbs_energy.csv").open(encoding="utf-8-sig",newline="") as f:
            reader=csv.DictReader(f)
            for row in reader:
                if not row.get("temperature","").strip(): continue
                t=int(float(row["temperature"]))
                coeff=np.fromstring(row["polypara"].strip().strip("[]"),sep=" ")
                fits[phase][t]={"lo":float(row["min_pressure"]),"hi":float(row["max_pressure"]),"std":float(row["std"]),"maxdev":float(row["maxdev"]),"coeff":coeff}
    return fits

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    fits=load_public()
    gridpath=OUT/"phase_grid.csv"
    grid_transitions=[]
    winners_by_t={}
    with gridpath.open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(GRID_HEADER)
        for t in range(601,4000):
            gs=np.full((len(PHASES),len(P)),np.nan)
            for i,phase in enumerate(PHASES):
                fit=fits[phase].get(t)
                if fit is None: continue
                mask=(P>=fit["lo"])&(P<=fit["hi"])
                gs[i,mask]=np.polyval(fit["coeff"],P[mask])*1000.
            active=np.isfinite(gs)
            count=active.sum(axis=0)
            masked=np.where(active,gs,np.inf)
            winner_idx=np.argmin(masked,axis=0)
            win=np.array([PHASES[i] if count[j] else "" for j,i in enumerate(winner_idx)],dtype=object)
            mins=np.min(masked,axis=0)
            for j,p in enumerate(P):
                phases=";".join(PHASES[i] for i in range(len(PHASES)) if active[i,j])
                if phases:
                    w.writerow((t,int(p),phases,f"{mins[j]:.12g}",win[j],""))
                else:
                    w.writerow((t,int(p),"","","","no phase has a source temperature row with a pressure window covering this point"))
            winners_by_t[t]=(gs,active,win)
            prev=None
            for j,name in enumerate(win):
                if not name:
                    prev=None; continue
                if prev is not None and name!=prev:
                    ia,ib=PHASES.index(prev),PHASES.index(name)
                    overlap=bool(active[ia,j-1] and active[ib,j-1] and active[ia,j] and active[ib,j])
                    basis=("grid_bracket; shared-valid Gibbs crossing" if overlap else
                           "support-window edge; winner changes as a phase enters/leaves valid mask")
                    grid_transitions.append({"t":t,"a":prev,"b":name,"p":float((P[j-1]+P[j])/2),"overlap":overlap,"basis":basis})
                prev=name
    bpath=OUT/"boundaries.csv"
    bhead=BOUNDARY_HEADER
    boundary_rows=[]
    for k,r in enumerate(grid_transitions,1):
        unc=100.0
        if r["overlap"]:
            fa=fits[r["a"]][r["t"]]; fb=fits[r["b"]][r["t"]]
            slope=abs(float(np.polyval(np.polyder(fa["coeff"]-fb["coeff"]),r["p"])))
            unc=max(50.0,50.0+math.hypot(max(fa["std"],fa["maxdev"]),max(fb["std"],fb["maxdev"]))/slope)
        boundary_rows.append([f"grid-{k:05d}",r["a"],r["b"],r["t"],f"{r['p']:.6f}",
                              "crossing" if r["overlap"] else "support_edge",str(r["overlap"]).lower(),
                              f"{unc:.12g}",r["basis"],"Half 100-bar grid interval plus quadrature of max(std,maxdev) Gibbs errors propagated through |dΔG/dP|; support edge reports lattice bracket"])
    # The paper's separate alpha/beta quartz estimates have 15 rows, and the
    # author convention fits their mean over all rows then plots only the
    # requested pressure interval.
    ab=np.loadtxt(INPUT_ROOT/"phase_diagram/alpha_quartz_beta_quartz.txt")
    abcoef=np.polyfit(ab[:,0]/10000.,ab[:,1:].mean(axis=1),1)
    for p in np.arange(2800.,32400.1,100.):
        boundary_rows.append([f"alpha-beta-{int(p):05d}","alpha_quartz","beta_quartz",f"{np.polyval(abcoef,p/10000.):.6f}",
                              f"{p:.6f}","alpha_beta_line","true","100","all-15-row two-estimate mean regression",
                              "experimental/simulation transition estimates; separate from Gibbs-polynomial envelope"])
    with bpath.open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(bhead); w.writerows(boundary_rows)
    senshead=SENS_HEADER
    sensrows=[]
    crossing_groups={}
    for r in grid_transitions:
        if r["overlap"]: crossing_groups.setdefault(canonical_pair(r["a"],r["b"]),[]).append(r)
    for pair,records in sorted(crossing_groups.items()):
        records=sorted(records,key=lambda x:x["t"]); nominal=records[len(records)//2]
        t=nominal["t"]; fit_a=fits[pair[0]][t]; fit_b=fits[pair[1]][t]
        lo=max(fit_a["lo"],fit_b["lo"]); hi=min(fit_a["hi"],fit_b["hi"])
        delta=np.asarray(fit_a["coeff"])-np.asarray(fit_b["coeff"])
        rootlist=np.roots(delta)
        roots=sorted(float(x.real) for x in rootlist if abs(x.imag)<1e-5 and lo<=x.real<=hi)
        p0=min(roots,key=lambda x:abs(x-nominal["p"])) if roots else nominal["p"]
        bid=next(x[0] for x in boundary_rows if x[1:3]==[nominal["a"],nominal["b"]] and x[3]==t and x[5] in ("crossing","support_edge"))
        for shift in (0.1,2.,5.):
            for phase in pair:
                for sign in (-1,1):
                    offset_ev=sign*shift/1000.
                    ca=np.asarray(fit_a["coeff"],float).copy(); cb=np.asarray(fit_b["coeff"],float).copy()
                    if phase==pair[0]: ca[-1]+=offset_ev
                    else: cb[-1]+=offset_ev
                    roots=np.roots(ca-cb)
                    roots=sorted(float(x.real) for x in roots if abs(x.imag)<1e-5 and lo<=x.real<=hi)
                    if roots:
                        pp=min(roots,key=lambda x:abs(x-p0)); overlap="true"
                        vals=[]
                        for other in PHASES:
                            ff=fits[other].get(t)
                            if ff is not None and ff["lo"]<=pp<=ff["hi"]:
                                vals.append((float(np.polyval(ff["coeff"],pp)),other))
                        pairg=min(float(np.polyval(ca,pp)),float(np.polyval(cb,pp)))
                        ambiguous=any(val<pairg-0.00005 for val,other in vals if other not in pair)
                        reason="root within perturbed shared pressure window; third-phase envelope checked"
                    else:
                        pp=""; overlap="false"; ambiguous=True
                        reason="perturbed pair has no real root inside its common pressure window; domain ambiguity flagged"
                    dp=(pp-p0) if pp!="" else ""
                    sensrows.append([shift,phase,"+" if sign>0 else "-",bid,pair[0],pair[1],t,f"{p0:.8g}",f"{pp:.8g}" if pp!="" else "",f"{dp:.8g}" if dp!="" else "",overlap,str(ambiguous).lower(),reason])
    with (OUT/"sensitivity.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(senshead); w.writerows(sensrows)
    # Compact but explicit phase/support coverage summary.
    stable={}
    stable_aggregate={ph:{"grid_points":0,"tmin":10**9,"tmax":-1,"pmin":10**9,"pmax":-1} for ph in PHASES}
    for t,(_,active,win) in winners_by_t.items():
        for ph in PHASES:
            idx=PHASES.index(ph)
            js=np.flatnonzero(active[idx]&(win==ph))
            if len(js):
                stable[f"{ph}:{t}"]=[int(P[js[0]]),int(P[js[-1]])]
                d=stable_aggregate[ph]; d["grid_points"]+=int(len(js)); d["tmin"]=min(d["tmin"],t); d["tmax"]=max(d["tmax"],t); d["pmin"]=min(d["pmin"],int(P[js[0]])); d["pmax"]=max(d["pmax"],int(P[js[-1]]))
    stable_domains=[{"phase":ph,"grid_points":d["grid_points"],"T_K":[d["tmin"],d["tmax"]],"P_bar":[d["pmin"],d["pmax"]]} for ph,d in stable_aggregate.items() if d["grid_points"]]
    estimate_gap=np.abs(ab[:,1]-ab[:,2])
    summary={"units":{"pressure":"bar","temperature":"K","gibbs":"meV/atom"},
      "method":{"polynomial_order":"descending cubic to constant","source_energy_unit":"eV/atom","mask_rule":"temperature row exists and min_pressure <= P <= max_pressure","description":"Independent vectorized evaluation of each public cubic Gibbs polynomial on the full integer-K / 100-bar lattice; invalid pressure windows masked before lower-envelope selection."},
      "valid_domain":{"temperature_K":[601,3999],"pressure_bar":[0,50000]},
      "stable_domains":{"phase_pressure_extent_by_temperature_bar":stable,"by_phase_aggregate":stable_domains},
      "boundaries":{"count":len(boundary_rows),"grid_reference_count":len(grid_transitions),"grid_transition_count":len(grid_transitions),"alpha_beta_line_count":sum(r[5]=="alpha_beta_line" for r in boundary_rows)},
      "sensitivity":{"perturbation_meV_per_atom":[0.1,2.0,5.0],"row_count":len(sensrows),"representative_crossing_pair_count":len(crossing_groups),"description":"Constant Gibbs offsets applied separately to each side of median-temperature shared-valid envelope crossings; roots solved from perturbed cubics inside common windows and rechecked against lower valid third phases."},
      "alpha_beta_treatment":{"source_columns":"pressure_bar,transition_estimate_1_K,transition_estimate_2_K","fit_rows":15,"fit_basis":"all_15_rows","fit_slope_K_per_GPa":float(abcoef[0]),"fit_intercept_K":float(abcoef[1]),"mean_abs_estimate_gap_K":float(np.mean(estimate_gap)),"max_abs_estimate_gap_K":float(np.max(estimate_gap)),"fit_method":"least-squares linear fit to the mean of both unlabeled estimates across all 15 rows; plot clipped to 2759–32400 bar"},
      "limitations":["Each input polynomial is used only on its row-specific min/max pressure window; no extrapolated phase contributes to the lower envelope.","Grid boundaries carry 100 bar lattice-bracket uncertainty and are not sub-grid exact coexistence pressures.","Source Data Fig. 2 and author accurate-transition trajectories are finite-temperature transition estimates from different workflows and are compared only in overlapping phase, temperature, and pressure domains.","The alpha/beta estimates are unlabeled by initial phase; their mean regression is reported without assigning either column to a starting structure."]}
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (OUT/"figures").mkdir(parents=True,exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9,6))
    from matplotlib.colors import BoundaryNorm, ListedColormap
    cmap=ListedColormap([plt.get_cmap("tab10")(i) for i in range(len(PHASES))])
    norm=BoundaryNorm(np.arange(-.5,len(PHASES)+.5,1),cmap.N)
    z=np.full((3999-601+1,len(P)),-1,dtype=int)
    for t,(_,_,ww) in winners_by_t.items():
        z[t-601]=[PHASES.index(v) if v else -1 for v in ww]
    ax.imshow(z,origin="lower",aspect="auto",extent=(P[0],P[-1],600.5,3999.5),interpolation="nearest",cmap=cmap,norm=norm)
    # Plot the separate all-row alpha/beta regression inside its stated domain.
    pp=np.linspace(2759,32400,300)
    ax.plot(pp,np.polyval(abcoef,pp/10000.),color="black",linewidth=1.5,label="α/β mean-estimate fit")
    handles=[plt.Line2D([0],[0],color=cmap(i),lw=5,label=ph) for i,ph in enumerate(PHASES)]
    handles.append(plt.Line2D([0],[0],color="black",lw=1.5,label="α/β mean-estimate fit"))
    ax.legend(handles=handles,fontsize=7,ncol=2,loc="upper left")
    ax.set(xlim=(0,50000),ylim=(601,3999),xlabel="Pressure (bar)",ylabel="Temperature (K)",title="SiO₂ finite-window Gibbs lower envelope")
    fig.tight_layout(); fig.savefig(OUT/"figures/phase_map.png",dpi=140); plt.close(fig)
    print(f"wrote {OUT}: 1,702,899 grid points, {len(grid_transitions)} switches, {len(boundary_rows)} boundary rows, {len(sensrows)} sensitivity rows")

if __name__=="__main__": main()

PYGEN
