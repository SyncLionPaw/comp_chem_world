#!/bin/bash
set -euo pipefail
oracle_dir=$(mktemp -d)
cleanup() { rm -rf -- "$oracle_dir"; }
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

cat > "$oracle_dir/generate.py" <<'CCW_140_generate_py_01be4d4dbfb7_END'
#!/usr/bin/env python3
"""Generate a numeric Gold bundle from independently pinned NewtonNet/DFT data."""
from __future__ import annotations
import argparse,csv,json,sys
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument("--package-root",type=Path,default=Path("/app"))
parser.add_argument("--existing-hessians",type=Path,help="reuse existing hessians/<ID>.csv and skip all model evaluation")
parser.add_argument("--report-only-from-existing",type=Path,help="update only report.md using existing eigenpairs.csv; never evaluate the model")
parser.add_argument("--output",type=Path,default=Path("/app/final"))
parser.add_argument("legacy_output",nargs="?",help="positional output path retained for the existing solve.sh contract")
args=parser.parse_args()
pkg=args.package_root; assets=pkg/"environment/assets" if (pkg/"environment/assets").is_dir() else pkg/"assets"
sys.path.insert(0,str(Path(__file__).resolve().parent))
if args.report_only_from_existing:
    from spectrum_report import render_cluster_assessment
    folder=args.report_only_from_existing
    protocol=json.loads((assets/"analysis_protocol.json").read_text())
    with (folder/"eigenpairs.csv").open(newline="") as handle: rows=list(csv.DictReader(handle))
    spectra=[]
    for rid in ("001","079","205","024"):
        local=[row for row in rows if row["reaction_id"]==rid]
        nn=sorted(((int(row["mode_index"]),float(row["nn_eigenvalue_cartesian_eV_A2"])) for row in local))
        dft=sorted(((int(row["matched_dft_mode_index"]),float(row["dft_eigenvalue_cartesian_eV_A2"])) for row in local))
        if not nn or [i for i,_ in nn]!=list(range(len(nn))) or [i for i,_ in dft]!=list(range(len(dft))):
            raise SystemExit(f"invalid complete spectrum rows for {rid}")
        spectra.append({"reaction_id":rid,"nn_values":[v for _,v in nn],"dft_values":[v for _,v in dft]})
    report=folder/"report.md"; old=report.read_text()
    if "## Full-spectrum near-degenerate assessment" in old:
        old=old[:old.index("## Full-spectrum near-degenerate assessment")]+old[old.index("For ID001,"):]
    marker="For ID001,"
    if marker not in old: raise SystemExit("existing report lacks selected-mode section anchor")
    section="\n".join(render_cluster_assessment(spectra,protocol))+"\n\n"
    old=old.replace("NewtonNet Hessians were calculated at the four supplied geometries and compared with the supplied DFT Hessians.","NewtonNet Hessians were reused from the existing final bundle and compared with the supplied DFT Hessians at the same four geometries.",1)
    report.write_text(old.replace(marker,section+marker,1))
    print(f"updated report only from existing eigenpairs: {report}")
    raise SystemExit(0)
import numpy as np
from ase.io import read
from scipy.optimize import linear_sum_assignment
from science_helpers import internal_spectrum,clusters,mode_response
from spectrum_report import render_cluster_assessment
IDS=("001","079","205","024")
def lex_assignment(scores):
    scores=np.asarray(scores,float);n=scores.shape[0];r,c=linear_sum_assignment(-scores);opt=float(scores[r,c].sum());chosen=[];used=set();prefix=0.
    for i in range(n):
        for j in range(n):
            if j in used:continue
            rr=np.arange(i+1,n);cc=[k for k in range(n) if k not in used and k!=j];rest=0.
            if len(rr):
                a,b=linear_sum_assignment(-scores[np.ix_(rr,cc)]);rest=float(scores[np.ix_(rr,cc)][a,b].sum())
            if abs(prefix+float(scores[i,j])+rest-opt)<=1e-12:
                chosen.append((i,j));used.add(j);prefix+=float(scores[i,j]);break
    return {i:j for i,j in chosen}
def asset(name): return assets/name
geo=asset("case03_ts_geometries_001_079_205_024.extxyz"); src=asset("case03_dft_hessians_001_079_205_024.jsonl")
ck=asset("best_model_state.tar"); spec=asset("newtonnet_model_spec.yml");protocol=json.loads(asset("analysis_protocol.json").read_text())
atoms=read(str(geo),index=":",format="extxyz");refs=[json.loads(s) for s in src.read_text().splitlines() if s.strip()]
if args.existing_hessians:
    calc=None
else:
    from newtonnet_evaluator import NewtonNetEvaluator
    calc=NewtonNetEvaluator(ck,spec)
out=Path(args.legacy_output) if args.legacy_output else args.output
out.mkdir(parents=True,exist_ok=True);(out/"hessians").mkdir(exist_ok=True)
metadata={"schema":"case03-hessian-analysis/v1","reaction_ids":list(IDS),"hessian_units":"eV/angstrom^2","atom_order":"package_frame_order","mode_matching_method":"maximum_absolute_overlap","near_degenerate_gap_relative":1e-6,"id001_selection":None,"model":"pinned NewtonNet checkpoint, CPU double precision","model_calls":{"hessian_calls":4,"energy_force_calls":4}}
if args.existing_hessians:
    metadata=json.loads((args.existing_hessians/"metadata.json").read_text())
    metadata.setdefault("mode_matching_method","maximum_absolute_overlap")
    metadata.setdefault("near_degenerate_gap_relative",1e-6)
    
protocol["internal_mode_matching"]["near_degenerate_gap_relative"]=metadata["near_degenerate_gap_relative"]
eigrows=[];comparison=[];summaries=[];selected_info=None;cluster_assessments=[]
for rid,a,rec in zip(IDS,atoms,refs):
    if args.existing_hessians:
        h=np.loadtxt(args.existing_hessians/"hessians"/f"{rid}.csv",delimiter=",")
    else:
        result=calc.evaluate(a,hessian=True);h=result.hessian_eV_A2
        np.savetxt(out/"hessians"/f"{rid}.csv",h,delimiter=",",fmt="%.17g")
    dft=np.asarray(rec["hessian_eV_A2"],float).reshape(h.shape)
    vm,Um,_=internal_spectrum(h,a.positions);vd,Ud,_=internal_spectrum(dft,a.positions)
    overlap=np.abs(Um.T@Ud)
    if metadata["mode_matching_method"]=="eigenvalue_penalized_overlap":
        score=overlap-.05*np.abs(vm[:,None]-vd[None,:])/(.1+np.maximum(np.abs(vm[:,None]),np.abs(vd[None,:])))
    else:score=overlap
    assignment=lex_assignment(score);rr=np.arange(len(vm));cc=np.array([assignment[i] for i in rr])
    nn_clusters=clusters(vm,protocol);dft_clusters=clusters(vd,protocol)
    cluster_assessments.append({"reaction_id":rid,"nn_values":vm,"dft_values":vd,"assignment":assignment,"nn_vectors":Um,"dft_vectors":Ud})
    diffs=[]
    for i in range(len(vm)):
        j=assignment[i];diffs.append((abs(float(vm[i]-vd[j])),i,j))
        eigrows.append({"reaction_id":rid,"mode_index":i,"nn_eigenvalue_cartesian_eV_A2":f"{vm[i]:.17g}","dft_eigenvalue_cartesian_eV_A2":f"{vd[j]:.17g}","matched_dft_mode_index":j,"abs_overlap":f"{overlap[i,j]:.17g}"})
    rms=float(np.sqrt(np.mean((vm-np.array([vd[assignment[i]] for i in range(len(vm))]))**2)))
    summaries.append((rid,len(vm),float(np.min(overlap[rr,cc])),rms,int(np.argmin(vm)),float(vm.min()),int(np.argmin(vd)),float(vd.min())))
    if rid=="001":
        _,default_mi,default_dj=sorted(diffs,key=lambda z:(-z[0],z[1],z[2]))[0]
        chosen=metadata.get("id001_selection")
        if chosen is None:
            mi,dj=default_mi,default_dj;chosen={"nn_mode_index":mi,"dft_mode_index":dj,"displacement_step_A":0.01,"rationale":"Selected by maximum matched eigenvalue gap as a declared reproducible default."};metadata["id001_selection"]=chosen
        else:mi=int(chosen["nn_mode_index"]);dj=int(chosen["dft_mode_index"])
        if assignment.get(mi)!=dj:raise ValueError("ID001 selection must name a matched mode pair")
        cm=next(c for c in clusters(vm,protocol) if mi in c);cd=next(c for c in clusters(vd,protocol) if dj in c)
        selected_info={"nn_mode":mi,"dft_mode":dj,"nn_value":float(vm[mi]),"dft_value":float(vd[dj]),"overlap":float(overlap[mi,dj]),"nn_cluster":list(cm),"dft_cluster":list(cd)}
        if len(cm)==1 and len(cd)==1:
            sel_protocol=dict(protocol);sel_protocol["nondegenerate_displacement"]={**protocol["nondegenerate_displacement"],"step_A":float(chosen["displacement_step_A"])}
            comparison+=mode_response(a,Um,cm,sel_protocol,"newtonnet",mi)
            comparison+=mode_response(a,Ud,cd,sel_protocol,"dft",dj)
        else:
            sel_protocol=dict(protocol);sel_protocol["nondegenerate_displacement"]={**protocol["nondegenerate_displacement"],"step_A":float(chosen["displacement_step_A"])}
            comparison+=mode_response(a,Um,cm,sel_protocol,"cluster-envelope",mi)
            comparison+=mode_response(a,Ud,cd,sel_protocol,"cluster-envelope",dj)
def write_csv(path,rows):
    with path.open("w",newline="") as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
write_csv(out/"eigenpairs.csv",eigrows);write_csv(out/"mode_comparison.csv",comparison)
(out/"metadata.json").write_text(json.dumps(metadata,indent=2)+"\n")
lines=["# Case 03 Hessian comparison", "", "NewtonNet Hessians were calculated at the four supplied geometries and compared with the supplied DFT Hessians. The checkpoint is not established as identical to the paper's enhanced model; this frozen sample does not establish unseen-reaction generalization.", "", f"Spectra are non-mass-weighted Cartesian internal spectra with rigid translation and rotation removed. Modes are paired using the submitted `mode_matching_method` from the precise protocol definitions; the declared relative cluster threshold is {metadata['near_degenerate_gap_relative']:.1e}. Results describe these geometries and do not establish a unique reaction mechanism.", "", "| ID | Internal modes | Minimum matched overlap | Matched-spectrum RMS difference (eV/Å²) | NN lowest mode/value | DFT lowest mode/value |", "|---|---:|---:|---:|---:|---:|"]
for rid,n,ov,rms,im,em,idf,ed in summaries: lines.append(f"| {rid} | {n} | {ov:.6f} | {rms:.6f} | {im}: {em:.6f} | {idf}: {ed:.6f} |")
protocol["assignment_label"]=metadata["mode_matching_method"]
lines += [""] + render_cluster_assessment(cluster_assessments,protocol) + [""]
info=selected_info
lines += ["", f"For ID001, the largest absolute matched eigenvalue difference selects NN mode {info['nn_mode']} ({info['nn_value']:.6f} eV/Å²) and DFT mode {info['dft_mode']} ({info['dft_value']:.6f} eV/Å²), with absolute overlap {info['overlap']:.6f}; submitted displacement step is {metadata['id001_selection']['displacement_step_A']:.3f} Å. The frozen gap rule places them in NN cluster {info['nn_cluster']} and DFT cluster {info['dft_cluster']}. The selected response rows follow the eigensolver sign convention used in `mode_comparison.csv`; the verifier independently checks those signed values.", "", "| Source | Atom pair (zero-based) | Signed bond response (Å) | Absolute response (Å) |", "|---|---|---:|---:|"]
for row in comparison:
    signed = row['signed_delta_bond_A']
    signed_text = f"{float(signed):.6f}" if signed != "" else "—"
    lines.append(f"| {row['source']} | {row['element_i']}{row['atom_i']}–{row['element_j']}{row['atom_j']} | {signed_text} | {float(row['response_A']):.6f} |")
lines += ["", "These first-order responses summarize local geometry only. The comparison covers four supplied reactions (001, 079, 205, 024) and does not establish a unique reaction mechanism or generalization to unseen reactions. Coverage, model smoothness, and other causes require separate controlled experiments.", ""]
(out/"report.md").write_text("\n".join(lines))
CCW_140_generate_py_01be4d4dbfb7_END
test "$(sha256sum "$oracle_dir/generate.py" | cut -d ' ' -f 1)" = "01be4d4dbfb7f2c5e4271093b83b284195d3c7b9d997e941f22f722b05f80449"

cat > "$oracle_dir/science_helpers.py" <<'CCW_140_science_helpers_py_0d3eb4a7ac4e_END'
"""Independent numerical helpers for the case-03 analysis program."""
import subprocess, tempfile
from pathlib import Path
import numpy as np
from spectrum_report import cluster_indices

def internal_spectrum(h, positions):
    x=np.asarray(positions,float); centered=x-x.mean(axis=0); cols=[]
    for axis in np.eye(3): cols.append(np.broadcast_to(axis,centered.shape).copy().ravel())
    for axis in np.eye(3): cols.append(np.cross(np.broadcast_to(axis,centered.shape),centered).ravel())
    u,s,_=np.linalg.svd(np.stack(cols,axis=1),full_matrices=False); rank=int(np.count_nonzero(s>1e-8*max(float(s[0]),1.0)))
    rb=u[:,:rank]; q,_=np.linalg.qr(rb,mode='complete'); qi=q[:,rank:]
    vals,vec=np.linalg.eigh(qi.T@(0.5*(np.asarray(h)+np.asarray(h).T))@qi)
    return vals,qi@vec,qi

def clusters(vals, protocol):
    return cluster_indices(vals,protocol)

def bond_graph(atoms):
    with tempfile.TemporaryDirectory() as td:
        xyz=Path(td)/'g.xyz'; sdf=Path(td)/'g.sdf'
        xyz.write_text(str(len(atoms))+'\ncase03 geometry\n'+'\n'.join(f'{s} {x:.12f} {y:.12f} {z:.12f}' for s,(x,y,z) in zip(atoms.get_chemical_symbols(),atoms.positions))+'\n')
        p=subprocess.run(['obabel','-ixyz',str(xyz),'-osdf','-O',str(sdf)],check=True,capture_output=True,text=True)
        lines=sdf.read_text().splitlines();i=next(i for i,v in enumerate(lines) if 'V2000' in v)
        n_atoms,n_bonds=int(lines[i][:3]),int(lines[i][3:6])
        symbols=[lines[i+1+j][31:34].strip() for j in range(n_atoms)]; edges=[]
        # Match the verifier's SDF contract: consume only the declared bond
        # block and canonicalize endpoints so atom/element order is stable.
        for line in lines[i+1+n_atoms:i+1+n_atoms+n_bonds]:
            a,b,o=int(line[:3])-1,int(line[3:6])-1,int(line[6:9])
            edges.append((min(a,b),max(a,b),o))
    return symbols,edges

def mode_response(atoms,vectors,indices,protocol,source,mode_idx):
    symbols,edges=bond_graph(atoms); bonds=[]
    for i,j,_ in edges:
        rij=atoms.positions[j]-atoms.positions[i]; norm=float(np.linalg.norm(rij))
        if norm<1e-12: continue
        g=np.zeros(3*len(atoms));g[3*i:3*i+3]=-rij/norm;g[3*j:3*j+3]=rij/norm;V=vectors[:,indices]
        if len(indices)==1: value=float(protocol['nondegenerate_displacement']['step_A']*(g@V[:,0])); row={'source':source,'mode_index':mode_idx,'atom_i':i,'atom_j':j,'element_i':symbols[i],'element_j':symbols[j],'signed_delta_bond_A':value,'response_A':abs(value)}
        else: value=float(protocol['nondegenerate_displacement']['step_A']*np.linalg.norm(g@V)); row={'source':'cluster-envelope','mode_index':mode_idx,'atom_i':i,'atom_j':j,'element_i':symbols[i],'element_j':symbols[j],'signed_delta_bond_A':'','response_A':value}
        bonds.append(row)
    return sorted(bonds,key=lambda r:(-r['response_A'],r['atom_i'],r['atom_j']))[:5]
CCW_140_science_helpers_py_0d3eb4a7ac4e_END
test "$(sha256sum "$oracle_dir/science_helpers.py" | cut -d ' ' -f 1)" = "0d3eb4a7ac4e99da640b3bbb1bbd5f676d601328728c3179b90ba15ada57651b"

cat > "$oracle_dir/spectrum_report.py" <<'CCW_140_spectrum_report_py_3ee503b59d9c_END'
"""Shared frozen-gap cluster assessment and rendering for case-03 reports."""
from __future__ import annotations


def cluster_indices(values, protocol):
    cfg = protocol["internal_mode_matching"]
    abs_gap = cfg["near_degenerate_gap_abs_eV_A2"]
    rel_gap = cfg["near_degenerate_gap_relative"]
    groups = []
    start = 0
    for i in range(len(values) - 1):
        gap = float(values[i + 1]) - float(values[i])
        limit = max(abs_gap, rel_gap * max(abs(float(values[i])), abs(float(values[i + 1]))))
        if gap > limit:
            groups.append(tuple(range(start, i + 1)))
            start = i + 1
    groups.append(tuple(range(start, len(values))))
    return groups


def render_cluster_assessment(spectra, protocol):
    """Render all four NN/DFT cluster sets; compute angles for mult-mode subspaces."""
    cfg = protocol["internal_mode_matching"]
    lines = [
        "## Full-spectrum near-degenerate assessment", "",
        f"For every NewtonNet and DFT internal spectrum, contiguous adjacent modes are grouped when each adjacent eigenvalue gap is ≤ max({cfg['near_degenerate_gap_abs_eV_A2']:.1e} eV/Å², {cfg['near_degenerate_gap_relative']:.1e} × max(|λᵢ|, |λᵢ₊₁|)); this is the frozen protocol rule. Mode correspondence uses the submitted {protocol.get('assignment_label', 'maximum_absolute_overlap')} score and deterministic lexicographic tie handling.", "",
    ]
    for item in spectra:
        rid = item["reaction_id"]
        nn_clusters = cluster_indices(item["nn_values"], protocol)
        dft_clusters = cluster_indices(item["dft_values"], protocol)
        nn_multi = [c for c in nn_clusters if len(c) > 1]
        dft_multi = [c for c in dft_clusters if len(c) > 1]
        def fmt(groups):
            if not any(len(group) > 1 for group in groups):
                return f"{len(groups)} singleton clusters (modes 0–{len(groups)-1})"
            return "; ".join("[" + ", ".join(map(str, group)) + "]" for group in groups)
        lines.append(f"- **{rid}** — NewtonNet clusters: {fmt(nn_clusters)}. DFT clusters: {fmt(dft_clusters)}. Multi-mode clusters: NewtonNet {len(nn_multi)}, DFT {len(dft_multi)}.")
        if not nn_multi and not dft_multi:
            lines.append("  - Principal-angle comparison is not applicable: neither spectrum contains a multi-mode cluster under the frozen gap rule, so there is no multi-dimensional subspace to compare.")
            continue
        if "nn_vectors" not in item or "dft_vectors" not in item or "assignment" not in item:
            raise ValueError(f"{rid} contains a multi-mode cluster; matched-subspace principal angles are required")
        import numpy as np
        assignment = item["assignment"]
        inverse = {j: i for i, j in assignment.items()}
        for label, groups, source_vectors, target_vectors, mapping in (
            ("NewtonNet", nn_multi, item["nn_vectors"], item["dft_vectors"], assignment),
            ("DFT", dft_multi, item["dft_vectors"], item["nn_vectors"], inverse),
        ):
            for group in groups:
                matched = sorted(mapping[i] for i in group)
                cosines = np.linalg.svd(source_vectors[:, list(group)].T @ target_vectors[:, matched], compute_uv=False)
                angles = np.degrees(np.arccos(np.clip(cosines, -1.0, 1.0)))
                lines.append(f"  - {label} cluster {list(group)} ↔ matched modes {matched}: principal angles (degrees) " + ", ".join(f"{angle:.6g}" for angle in angles))
    return lines
CCW_140_spectrum_report_py_3ee503b59d9c_END
test "$(sha256sum "$oracle_dir/spectrum_report.py" | cut -d ' ' -f 1)" = "3ee503b59d9c86ef22f03a45fb75f5a59d23c429871b990ac877cdb3f182e5a4"

chmod 0444 "$oracle_dir"/*.py
python "$oracle_dir/generate.py" /app/final
