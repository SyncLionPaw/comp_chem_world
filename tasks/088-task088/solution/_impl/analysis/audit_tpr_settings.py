#!/usr/bin/env python3
"""Audit native GROMACS TPR settings using `gmx dump`; no MD is run."""
import argparse, hashlib, json, re, subprocess
from pathlib import Path

def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for c in iter(lambda:f.read(4*1024*1024),b""): h.update(c)
    return h.hexdigest()

def audit(text, kind):
    patterns={
      "integrator":r"^\s*integrator\s*=\s*(\S+)", "dt_ps":r"^\s*dt\s*=\s*([\d.eE+-]+)",
      "nsteps":r"^\s*nsteps\s*=\s*(\d+)", "tcoupl":r"^\s*tcoupl\s*=\s*(\S+)",
      "ref_t_K":r"^\s*ref-t\s*[:=]\s*([\d.eE+-]+)", "tau_t_ps":r"^\s*tau-t\s*[:=]\s*([\d.eE+-]+)",
      "pcoupl":r"^\s*pcoupl\s*=\s*(\S+)", "coulombtype":r"^\s*coulombtype\s*=\s*(\S+)",
      "rcoulomb_nm":r"^\s*rcoulomb\s*=\s*([\d.eE+-]+)", "rvdw_nm":r"^\s*rvdw\s*=\s*([\d.eE+-]+)",
      "pbc":r"^\s*pbc\s*=\s*(\S+)", "nstxout_compressed":r"^\s*nstxout-compressed\s*=\s*(\d+)",
      "nstenergy":r"^\s*nstenergy\s*=\s*(\d+)", "vdwtype":r"^\s*vdw-type\s*=\s*(\S+)",
      "vdw_modifier":r"^\s*vdw-modifier\s*=\s*(\S+)", "epsilon_r":r"^\s*epsilon-r\s*=\s*([\d.eE+-]+)",
      "epsilon_surface":r"^\s*epsilon-surface\s*=\s*([\d.eE+-]+)",
      "settle_geometry_nm":r"functype\[\d+\]=SETTLE,\s*doh=\s*([\d.eE+-]+),\s*dhh=\s*([\d.eE+-]+)"}
    got={}
    for key,pat in patterns.items():
      m=re.search(pat,text,re.M|re.I)
      if m:
        v=m.groups();
        if key=="settle_geometry_nm": got[key]=[float(v[0]),float(v[1])]
        else:
          v=v[0]; got[key]=float(v) if key in {"dt_ps","ref_t_K","tau_t_ps","rcoulomb_nm","rvdw_nm","epsilon_r","epsilon_surface"} else (int(v) if key in {"nsteps","nstxout_compressed","nstenergy"} else v)
    if kind=="production":
      expected={"integrator":"md","dt_ps":.002,"nsteps":10000000,"tcoupl":"V-rescale","ref_t_K":300.,"tau_t_ps":.5,"pcoupl":"No","coulombtype":"PME","rcoulomb_nm":.9,"rvdw_nm":.9,"pbc":"xyz","nstxout_compressed":500,"vdwtype":"Cut-off","vdw_modifier":"Potential-shift","epsilon_r":1.,"epsilon_surface":0.,"settle_geometry_nm":[.1,.1633]}
    elif kind=="em": expected={"integrator":"steep","pbc":"xyz","coulombtype":"PME"}
    else: raise ValueError(kind)
    def same(g,v):
      if isinstance(v,float): return isinstance(g,(int,float)) and abs(g-v)<=1e-7
      if isinstance(v,list): return isinstance(g,list) and len(g)==len(v) and all(abs(a-b)<=1e-7 for a,b in zip(g,v))
      return str(g).lower()==str(v).lower()
    misses={k:{"observed":got.get(k),"expected":v} for k,v in expected.items() if k not in got or not same(got[k],v)}
    return {"schema":"case01-tpr-settings-v1","kind":kind,"observed":got,"expected":expected,"failures":misses,"status":"PASS" if not misses else "FAIL"}

def main():
    p=argparse.ArgumentParser(); p.add_argument("tpr",type=Path); p.add_argument("--gmx",default="gmx"); p.add_argument("--kind",choices=["production","em"],required=True); p.add_argument("--json",type=Path,required=True); p.add_argument("--dump",type=Path,required=True); a=p.parse_args()
    r=subprocess.run([a.gmx,"dump","-s",str(a.tpr)],capture_output=True,text=True,check=True)
    a.dump.parent.mkdir(parents=True,exist_ok=True); a.dump.write_text(r.stdout+r.stderr)
    result=audit(r.stdout,a.kind); result["tpr_sha256"]=sha(a.tpr); result["dump_sha256"]=sha(a.dump)
    a.json.parent.mkdir(parents=True,exist_ok=True); a.json.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    if result["status"]!="PASS": raise SystemExit(2)
if __name__=="__main__": main()
