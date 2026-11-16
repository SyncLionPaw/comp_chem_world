#!/bin/bash
set -euo pipefail
oracle_dir=$(mktemp -d)
cleanup() { rm -rf -- "$oracle_dir"; }
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

cat > "$oracle_dir/generate.py" <<'CCW_138_generate_py_8290f94b037f_END'
#!/usr/bin/env python3
"""Build the canonical case-01 scientific Gold from the pinned evaluator."""
from __future__ import annotations
import csv, json, sys, hashlib
from pathlib import Path
import numpy as np
from ase.io import read

assets=Path("/app/assets")
sys.path.insert(0,"/opt/compchembench")
from newtonnet_evaluator import NewtonNetEvaluator
out=Path(sys.argv[1]) if len(sys.argv)>1 else Path("/app/final")
out.mkdir(parents=True,exist_ok=True); (out/"hessians").mkdir(exist_ok=True)
atoms_list=read(str(assets/"case01_ts_geometries_001_000.extxyz"),index=":",format="extxyz")
calc=NewtonNetEvaluator(assets/"best_model_state.tar",assets/"newtonnet_model_spec.yml")
def xyhash(pos): return hashlib.sha256(json.dumps(np.asarray(pos,float).tolist(),separators=(",",":"),allow_nan=False).encode()).hexdigest()
calls=[]
plan={"schema":"case01-validation-plan/v1","finite_difference_step_angstrom":1e-4,"translation_vector_angstrom":[0.1,0.03,0.02],"rotation_degrees":90,"components":[]}
def log(rid,purpose,kind,pos): calls.append({"geometry_id":rid,"purpose":purpose,"call_type":kind,"coordinates_sha256":xyhash(pos)})
def rotation_matrix_z(angle):
    if angle==90:return np.array([[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]])
    theta=np.deg2rad(angle);c=np.cos(theta);s=np.sin(theta)
    return np.array([[c,-s,0.],[s,c,0.],[0.,0.,1.]])
bundle={"schema":"case01-efh/v1","geometry_order":["001","000"],"units":{"energy":"eV","force":"eV/angstrom","hessian":"eV/angstrom^2"},"unit_conversion_kcal_per_mol_A2":23.06055,"geometries":{},"model_calls":{"hessian_calls":4,"energy_force_calls":30}}
diag=[]
for rid,a in zip(("001","000"),atoms_list):
    n=len(a); x=a.positions.copy(); center=x.mean(axis=0)
    base=calc.evaluate(a,hessian=True)
    log(rid,"base_H","H",x)
    rb=rotation_matrix_z(plan["rotation_degrees"])
    rot=a.copy(); rot.positions=(x-center)@rb.T+center
    rr=calc.evaluate(rot,hessian=True)
    log(rid,"rotated_H","H",rot.positions)
    trans=a.copy(); trans.positions=x+np.array(plan["translation_vector_angstrom"])
    tr=calc.evaluate(trans,hessian=False)
    log(rid,"translated_EF","EF",trans.positions)
    rbig=np.kron(np.eye(n),rb); cov=rbig@base.hessian_eV_A2@rbig.T
    item={"energy_unit":"eV","force_unit":"eV/angstrom","hessian_unit":"eV/angstrom^2","energy_eV":base.energy_eV,"forces_eV_A":base.forces_eV_A.tolist(),"translated_energy_eV":tr.energy_eV,"translated_forces_eV_A":tr.forces_eV_A.tolist(),"rotated_energy_eV":rr.energy_eV,"rotated_forces_eV_A":rr.forces_eV_A.tolist()}
    bundle["geometries"][rid]=item
    np.savetxt(out/"hessians"/f"{rid}.csv",base.hessian_eV_A2,delimiter=",",fmt="%.17g")
    np.savetxt(out/"hessians"/f"{rid}_rotated.csv",rr.hessian_eV_A2,delimiter=",",fmt="%.17g")
    for atom,axis,ai in ((0,"x",0),(n//2,"y",1),(n-1,"z",2)):
        plan["components"].append({"geometry_id":rid,"atom_index":atom,"axis":axis})
        flat=3*atom+ai; xp=x.copy(); xm=x.copy(); xp.flat[flat]+=1e-4; xm.flat[flat]-=1e-4
        ap=a.copy(); am=a.copy(); ap.positions=xp; am.positions=xm
        ep=calc.evaluate(ap,hessian=False); em=calc.evaluate(am,hessian=False)
        log(rid,f"{atom}:{axis}_energy_plus","EF",xp);log(rid,f"{atom}:{axis}_energy_minus","EF",xm)
        grad=abs(base.forces_eV_A.flat[flat]+(ep.energy_eV-em.energy_eV)/(2e-4))
        fp=calc.evaluate(ap,hessian=False); fm=calc.evaluate(am,hessian=False)
        log(rid,f"{atom}:{axis}_force_plus","EF",xp);log(rid,f"{atom}:{axis}_force_minus","EF",xm)
        col=-(fp.forces_eV_A-fm.forces_eV_A).ravel()/(2e-4)
        hres=float(np.max(np.abs(base.hessian_eV_A2[:,flat]-col)))
        diag.append({"geometry_id":rid,"component":f"{atom}:{axis}","energy_gradient_residual":f"{grad:.17g}","force_hessian_residual":f"{hres:.17g}","translation_delta_eV":f"{tr.energy_eV-base.energy_eV:.17g}","rotation_h_covariance_max_abs_eV_A2":f"{np.max(np.abs(rr.hessian_eV_A2-cov)):.17g}"})
(out/"efh.json").write_text(json.dumps(bundle,indent=2,allow_nan=False)+"\n")
(out/"validation_plan.json").write_text(json.dumps(plan,indent=2,allow_nan=False)+"\n")
with (out/"diagnostics.csv").open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(diag[0])); w.writeheader(); w.writerows(diag)
with (out/"model_call_log.csv").open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(calls[0]));w.writeheader();w.writerows(calls)
(out/"report.md").write_text("""# Case 01 Gold result\n\nFixed NewtonNet checkpoint replay in double precision on CPU. Units are eV, eV/Å and eV/Å². The analytic Hessian was compared with central differences at the six specified Cartesian components (h=1e-4 Å). Translation and proper 90° z rotation tests were replayed independently. The conversion is 1 eV/Å² = 23.06055 kcal/mol/Å².\n\nThis Gold is a computational reference for the frozen two-geometry scope; it does not imply broader model qualification.\n""")
CCW_138_generate_py_8290f94b037f_END
test "$(sha256sum "$oracle_dir/generate.py" | cut -d ' ' -f 1)" = "8290f94b037f2c1d8eb575e314490ab846b52e73c319200c856cd5170a76e679"

chmod 0444 "$oracle_dir"/*.py
python "$oracle_dir/generate.py" /app/final
