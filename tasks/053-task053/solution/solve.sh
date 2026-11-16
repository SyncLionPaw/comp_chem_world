#!/usr/bin/env bash
set -euo pipefail
ASSETS="${ASSETS:-/app/environment/assets}"
OUT="${OUTPUT_DIR:-/app/final}"
while (($#)); do
  case "$1" in
    --assets) ASSETS="$2"; shift 2 ;;
    --output-dir) OUT="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
mkdir -p "$OUT"
WORK="$(mktemp -d)"
cleanup() { status=$?; trap - EXIT; rm -rf "$WORK"; exit "$status"; }
trap cleanup EXIT
cat > "$WORK/evaluate.py" <<'CCW_TASK53_EVALUATE_PY_EOF'
#!/usr/bin/env python3
"""Evaluate the fixed two-model static mechanics input without a native engine."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

H = 1.0e-4
A = 5.431
SIGMA = 0.4
LAMBDA = 100.0
R0 = 0.5

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read_snapshot(path: Path):
    lines=path.read_text().splitlines()
    count=int(next(line.split()[0] for line in lines if line.strip().endswith("atoms")))
    bounds=[]
    for axis in "xyz":
        row=next(line.split() for line in lines if line.strip().endswith(axis+"lo "+axis+"hi"))
        bounds.append((float(row[0]),float(row[1])))
    start=next(i for i,line in enumerate(lines) if line.strip().startswith("Atoms"))+1
    rows=[]
    for line in lines[start:]:
        if not line.strip():
            if rows: break
            continue
        f=line.split()
        if len(f)>=5 and f[0].isdigit(): rows.append((int(f[0]),np.array([float(v) for v in f[2:5]])))
    rows.sort(key=lambda row:row[0])
    if len(rows)!=count or [r[0] for r in rows]!=list(range(1,count+1)):
        raise ValueError("snapshot must contain each atom ID exactly once")
    cell=np.diag([hi-lo for lo,hi in bounds])
    return np.asarray([r[1] for r in rows]),cell

def geometry(x,cell):
    """Smooth diamond-environment Q and its Cartesian derivative."""
    x=np.asarray(x,dtype=float)
    raw=(x[None,:,:]-x[:,None,:])@np.linalg.inv(cell)
    frac=raw-np.rint(raw)
    rij=frac@cell
    d2=np.einsum("ija,ija->ij",rij,rij)
    motif=np.array([
        [[1,1,1],[-1,-1,1],[1,-1,-1],[-1,1,-1]],
        [[1,-1,1],[-1,1,1],[1,1,-1],[-1,-1,-1]],
    ],dtype=float)*(A/4)
    radius=np.linalg.norm(motif,axis=2).max()+3*SIGMA
    mask=(d2>100*np.finfo(float).eps)&(d2<radius**2)
    kval=[]; deriv=[]
    for template in motif:
        delta=rij[:,:,None,:]-template[None,None,:,:]
        e=np.exp(-np.einsum("ijta,ijta->ijt",delta,delta)/(4*SIGMA**2))
        kval.append((e*mask[:,:,None]).sum(axis=(1,2))/4)
        deriv.append((-(e[:,:,:,None]*delta).sum(axis=2)/(8*SIGMA**2))*mask[:,:,None])
    kval=np.stack(kval,axis=1)
    logits=LAMBDA*kval
    top=logits.max(axis=1,keepdims=True)
    weights=np.exp(logits-top);weights/=weights.sum(axis=1,keepdims=True)
    local=(top[:,0]+np.log(np.exp(logits-top).sum(axis=1)))/LAMBDA
    u=local/R0;u12=u**12
    q=float(np.sum(u12/(1+u12)))
    dqds=12*u**11/(R0*(1+u12)**2)
    pairgrad=weights[:,0,None,None]*deriv[0]+weights[:,1,None,None]*deriv[1]
    term=dqds[:,None,None]*pairgrad
    dqdx=term.sum(axis=0)-term.sum(axis=1)
    return q,dqdx,(rij,term)

def energy_gain(q,p):
    w1=np.asarray(p["w1"],dtype=float).reshape(-1)
    b1=np.asarray(p["b1"],dtype=float).reshape(-1)
    w2=np.asarray(p["w2"],dtype=float).reshape(-1)
    if not (len(w1)==len(b1)==len(w2)==8): raise ValueError("frozen model must contain eight hidden units")
    scale=float(p["input_scale"])
    if not np.isfinite(scale) or scale<=0: raise ValueError("model input_scale must be finite and positive")
    z=np.tanh((q-float(p["input_center"]))/scale*w1+b1)
    e=float(np.dot(z,w2)+float(np.asarray(p["b2"],dtype=float).reshape(-1)[0]))
    d=float(np.dot(w2*(1-z*z),w1)/scale)
    return e,d

def evaluate(x,cell,p):
    q,dqdx,(rij,term)=geometry(x,cell)
    energy,dedq=energy_gain(q,p)
    force=-dedq*dqdx
    # W_ab = -dE/d(epsilon_ab), with x' = x F.T and cell' = cell F.T.
    virial=-dedq*np.einsum("cja,cjb->ab",term,rij)
    return q,energy,dedq,force,virial

def evaluate_case(snapshot_path:Path,models_path:Path):
    x,cell=read_snapshot(snapshot_path)
    doc=json.loads(models_path.read_text())
    models=doc.get("models")
    if doc.get("schema")!="case05-frozen-nn-prototypes/v1" or not isinstance(models,list) or len(models)!=2:
        raise ValueError("expected exactly two frozen model definitions")
    results=[]
    for model in models:
        p=model["parameters"]
        q,e,dedq,force,virial=evaluate(x,cell,p)
        coords=[]
        for atom_id in (1,54,109):
            for axis in range(3):
                xp,xm=x.copy(),x.copy();xp[atom_id-1,axis]+=H;xm[atom_id-1,axis]-=H
                ep=evaluate(xp,cell,p)[1];em=evaluate(xm,cell,p)[1]
                fd=-(ep-em)/(2*H)
                coords.append({"atom_id":atom_id,"axis":axis,"analytic_force_eV_per_A":float(force[atom_id-1,axis]),"finite_difference_eV_per_A":fd})
        strains=[]
        for a in range(3):
            for b in range(3):
                plus=np.eye(3);minus=np.eye(3);plus[a,b]+=H;minus[a,b]-=H
                ep=evaluate(x@plus.T,cell@plus.T,p)[1]
                em=evaluate(x@minus.T,cell@minus.T,p)[1]
                fd=-(ep-em)/(2*H)
                strains.append({"a":a,"b":b,"analytic_W_eV":float(virial[a,b]),"finite_difference_W_eV":fd})
        parameter_hash=hashlib.sha256(json.dumps(p,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
        results.append({"model_id":model["model_id"],"parameter_sha256":parameter_hash,"Q":q,
            "bias_energy_eV":e,"dVdQ_eV_per_Q":dedq,"force_eV_per_A_atom_id_order":force.tolist(),
            "virial_eV_row_a_column_b":virial.tolist(),"diagnostics":{"coordinate_probes":coords,"strain_probes":strains,
            "net_force_eV_per_A":force.sum(axis=0).tolist()}})
    return {"schema":"case05-archived-mechanics-result/v1","case_id":"case-05-archived-mechanics-v2",
        "atoms":len(x),"cell_A":cell.tolist(),"input_sha256":{"snapshot.data":sha(snapshot_path),"models.json":sha(models_path)},
        "models":results,"claim_codes":["ARCHIVED_STATIC_MECHANICS","NO_NEW_NATIVE_RUN","GLOBAL_ENERGY_FEEDBACK_UNESTABLISHED"]}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshot",type=Path,required=True)
    ap.add_argument("--models",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    result=evaluate_case(args.snapshot.resolve(),args.models.resolve())
    args.output.resolve().parent.mkdir(parents=True,exist_ok=True)
    args.output.resolve().write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"case_id":result["case_id"],"models":len(result["models"]),"status":"MECHANICS_COMPUTED"},sort_keys=True))

if __name__=="__main__":main()
CCW_TASK53_EVALUATE_PY_EOF
install -m 0555 "$WORK/evaluate.py" "$OUT/evaluate.py"
python3 "$OUT/evaluate.py" --snapshot "$ASSETS/snapshot.data" --models "$ASSETS/models.json" --output "$OUT/result.json"
