#!/bin/bash
set -euo pipefail
oracle_dir=$(mktemp -d)
cleanup() { rm -rf -- "$oracle_dir"; }
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

cat > "$oracle_dir/generate.py" <<'CCW_143_generate_py_e3c6761f9e41_END'
#!/usr/bin/env python3
"""Generate a fresh, bounded case06 Gold path and its directional call ledger."""
from __future__ import annotations
import csv, json, sys, time
import hashlib, os
from pathlib import Path
import numpy as np
from ase.io import read, write

pkg=Path("/app");assets=pkg/"assets";sys.path.insert(0,"/opt/compchembench")
from newtonnet_evaluator import NewtonNetEvaluator,projected_internal_spectrum
import networkx as nx, subprocess, tempfile
def obabel_graph(atoms):
    with tempfile.TemporaryDirectory() as td:
        xyz=Path(td)/"g.xyz";sdf=Path(td)/"g.sdf"
        xyz.write_text(str(len(atoms))+"\nendpoint\n"+"\n".join(f"{z} {x:.12f} {y:.12f} {q:.12f}" for z,(x,y,q) in zip(atoms.get_chemical_symbols(),atoms.positions))+"\n")
        subprocess.run(["obabel","-ixyz",str(xyz),"-osdf","-O",str(sdf)],check=True,capture_output=True,text=True)
        lines=sdf.read_text().splitlines();i=next(i for i,x in enumerate(lines) if "V2000" in x);na=int(lines[i][:3]);nb=int(lines[i][3:6]);g=nx.Graph()
        for j in range(na):g.add_node(j,element=lines[i+1+j][31:34].strip())
        for j in range(i+1+na,i+1+na+nb):
            row=lines[j];g.add_edge(int(row[:3])-1,int(row[3:6])-1,order=int(row[6:9]))
        canonical={"elements":[g.nodes[k]["element"] for k in range(na)],"edges":sorted([min(a,b),max(a,b),d["order"]] for a,b,d in g.edges(data=True))}
        digest=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(",",":")).encode()).hexdigest();return g,digest
def iso(a,b):return nx.is_isomorphic(a,b,node_match=lambda x,y:x["element"]==y["element"])
out=Path("/app/final");out.mkdir(parents=True,exist_ok=True)
method_id=os.environ.get("CASE06_METHOD_ID","pr-plus-conjugate-gradient/v1")
if method_id not in ("pr-plus-conjugate-gradient/v1","steepest-descent/v1"):raise SystemExit("unsupported CASE06_METHOD_ID")
ts=read(str(assets/"case06_reference_ts.xyz"));reactant=read(str(assets/"case06_original_zenodo_000_R.xyz"));product=read(str(assets/"case06_original_zenodo_000_P.xyz"))
calc=NewtonNetEvaluator(assets/"best_model_state.tar",assets/"newtonnet_model_spec.yml")
t0=time.monotonic();base=calc.evaluate(ts,hessian=True);spectrum=projected_internal_spectrum(base.hessian_eV_A2,ts.positions)
mode=spectrum["lowest_internal_mode_cartesian"].reshape((-1,3)).copy();mode/=np.linalg.norm(mode,axis=1).max()
np.savetxt(out/"hessian.csv",base.hessian_eV_A2,delimiter=",",fmt="%.17g")
(out/"ts.xyz").write_text((assets/"case06_reference_ts.xyz").read_text())
(out/"ts_properties.json").write_text(json.dumps({"energy_unit":"eV","force_unit":"eV/angstrom","energy_eV":base.energy_eV,"forces_eV_A":base.forces_eV_A.tolist()},indent=2)+"\n")
with (out/"hessian_eigenvalues.csv").open("w",newline="") as f:
    w=csv.writer(f);w.writerow(["mode_index","eigenvalue_eV_A2"]);w.writerows((i,f"{v:.17g}") for i,v in enumerate(spectrum["internal_eigenvalues_eV_A2"]))
trace=[];paths={};total_h=1;total_ef=1
events=[]
def log_event(direction,event,step,attempt,call_type,atoms,result):
    coords=np.asarray(atoms.positions,float).tolist()
    digest=hashlib.sha256(json.dumps(coords,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    events.append({"sequence":len(events),"direction":direction,"event_type":event,"step_index":step,"line_search_attempt":attempt,"call_type":call_type,"coordinates_sha256":digest,"positions_json":json.dumps(coords,separators=(",",":"),allow_nan=False),"energy_eV":f"{result.energy_eV:.17g}","fmax_eV_A":f"{np.max(np.linalg.norm(result.forces_eV_A,axis=1)):.17g}"})
log_event("forward","ts_hessian",-1,0,"H",ts,base)
for sign,name in ((+1,"forward"),(-1,"reverse")):
    started=time.monotonic();ef_count=0
    current_atoms=ts.copy();current_atoms.positions=ts.positions+sign*.035*mode
    current=calc.evaluate(current_atoms,hessian=False);ef_count+=1;log_event(name,"seed",0,0,"EF",current_atoms,current)
    frames=[ts.copy(),current_atoms.copy()];prev_force=prev_direction=None;accepted=0;status="step_limit"
    for _ in range(120):
        forces=current.forces_eV_A
        if np.max(np.linalg.norm(forces,axis=1))<=.05:status="force_threshold";break
        if prev_force is None or method_id=="steepest-descent/v1":search=forces.copy()
        else:
            y=forces-prev_force;beta=max(0.,float(np.sum(forces*y)/max(float(np.sum(prev_force*prev_force)),1e-20)))
            search=forces+beta*prev_direction
            if float(np.sum(forces*search))<=0.:search=forces.copy()
        atom_norm=np.linalg.norm(search,axis=1).max();scale=min(.08/max(atom_norm,1e-20),.25/max(atom_norm,1e-20))
        disp=search*scale;work=float(np.sum(forces*disp));found=None
        for attempt in range(24):
            trial=current_atoms.copy();trial.positions=current_atoms.positions+disp
            proposed=calc.evaluate(trial,hessian=False);ef_count+=1
            accepted_this=proposed.energy_eV<=current.energy_eV-min(1e-8,1e-4*work)
            log_event(name,"accepted_trial" if accepted_this else "rejected_trial",accepted+1,attempt,"EF",trial,proposed)
            if accepted_this:found=(trial,proposed);break
            disp*=.5;work*=.5
        if found is None:status="line_search_failed";break
        prev_force=forces.copy();prev_direction=disp/scale if scale else search
        current_atoms,current=found;frames.append(current_atoms.copy());accepted+=1
    write(str(out/f"irc_{name}.xyz"),frames,format="extxyz",append=False)
    paths[name]=frames;end_fmax=float(np.max(np.linalg.norm(current.forces_eV_A,axis=1)))
    trace.append({"scope":name,"ef_calls":ef_count+(1 if name=="forward" else 0),"h_calls":1 if name=="forward" else 0,"accepted_steps":accepted,"walltime_s":time.monotonic()-started,"stop_status":status,"endpoint_fmax_eV_A":end_fmax})
    total_ef+=ef_count
trace.append({"scope":"total","ef_calls":sum(x["ef_calls"] for x in trace),"h_calls":sum(x["h_calls"] for x in trace),"accepted_steps":sum(x["accepted_steps"] for x in trace),"walltime_s":sum(x["walltime_s"] for x in trace),"stop_status":"combined"})
with (out/"execution_trace.csv").open("w",newline="") as f:
    fields=["scope","ef_calls","h_calls","accepted_steps","walltime_s","stop_status","endpoint_fmax_eV_A"]
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(trace)
with (out/"model_event_log.csv").open("w",newline="") as f:
    fields=["sequence","direction","event_type","step_index","line_search_attempt","call_type","coordinates_sha256","positions_json","energy_eV","fmax_eV_A"]
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(events)
rg,_=obabel_graph(reactant);pg,_=obabel_graph(product);cls={"schema":"case06-endpoint-classification/v1","method_id":method_id,"algorithm_id":"backtracked-"+method_id.replace("/v1", "")+"/v1","algorithm":"backtracked "+method_id,"coordinate_metric":"unweighted_cartesian","pair_connects_R_P":False}
for name,frames in paths.items():
    g,digest=obabel_graph(frames[-1]);mr=iso(g,rg);mp=iso(g,pg)
    cls[name]={"match_R":mr,"match_P":mp,"endpoint_graph_sha256":digest,"stop_status":trace[0 if name=="forward" else 1]["stop_status"],"accepted_steps":trace[0 if name=="forward" else 1]["accepted_steps"]}
cls["pair_connects_R_P"] = bool((cls["forward"]["match_R"] and cls["reverse"]["match_P"]) or (cls["forward"]["match_P"] and cls["reverse"]["match_R"]))
if cls["forward"]["match_P"] and cls["reverse"]["match_P"] and not cls["forward"]["match_R"] and not cls["reverse"]["match_R"]:cls["identity_outcome"]="both_endpoints_match_product_no_reactant"
elif (cls["forward"]["match_R"] and cls["reverse"]["match_P"]) or (cls["forward"]["match_P"] and cls["reverse"]["match_R"]):cls["identity_outcome"]="connects_reactant_to_product"
elif cls["forward"]["match_R"] and cls["reverse"]["match_R"]:cls["identity_outcome"]="both_endpoints_match_reactant"
elif any(cls[d]["match_R"] or cls[d]["match_P"] for d in ("forward","reverse")):cls["identity_outcome"]="partial_template_match"
else:cls["identity_outcome"]="neither_endpoint_matches_templates"
(out/"graph_classification.json").write_text(json.dumps(cls,indent=2)+"\n")
(out/"report.md").write_text(f"""# Case 06 Gold result

Selected method_id: {method_id}. Starting TS: E={base.energy_eV:.9f} eV, max force={np.max(np.linalg.norm(base.forces_eV_A,axis=1)):.6f} eV/Å, projected internal modes below the frozen threshold={int(np.count_nonzero(spectrum["internal_eigenvalues_eV_A2"] < -1.0/23.06055))}. Both fresh unweighted Cartesian downhill paths began at opposite signs of that mode and stopped according to the frozen force-threshold or step-limit rule. Forward status={trace[0]['stop_status']} after {trace[0]['accepted_steps']} accepted steps; reverse status={trace[1]['stop_status']} after {trace[1]['accepted_steps']}. E/F counters include the start, accepted and rejected line-search evaluations; the starting H call is attributed to the forward scope. Saved frames are not optimization-step counts.

Using Open Babel 3.1.1 XYZ bond perception and element-preserving NetworkX VF2, the independently checked endpoint result is forward.match_R={cls['forward']['match_R']}, forward.match_P={cls['forward']['match_P']}, reverse.match_R={cls['reverse']['match_R']}, reverse.match_P={cls['reverse']['match_P']}.

pair_connects_R_P: {str(cls['pair_connects_R_P']).lower()}
identity_outcome: {cls['identity_outcome']}

Forward endpoint: R={cls["forward"]["match_R"]}, P={cls["forward"]["match_P"]}; reverse endpoint: R={cls["reverse"]["match_R"]}, P={cls["reverse"]["match_P"]}. The classification reports only these graph matches and does not establish broader chemical identity.
""")
print(json.dumps({"gold_final":str(out),"ef_calls":trace[-1]["ef_calls"],"h_calls":trace[-1]["h_calls"],"accepted_steps":{"forward":trace[0]["accepted_steps"],"reverse":trace[1]["accepted_steps"]},"wall_s":time.monotonic()-t0},indent=2))
CCW_143_generate_py_e3c6761f9e41_END
test "$(sha256sum "$oracle_dir/generate.py" | cut -d ' ' -f 1)" = "e3c6761f9e4176a3e2c4ca638f2b852579c9aff3d71a5e840e52bbf175129261"

chmod 0444 "$oracle_dir"/*.py
python "$oracle_dir/generate.py"
