#!/usr/bin/env python3
"""Build valid lambda.x stdin from the actual QE PH output and structure.

Uses spglib only for the symmetry multiplicity of the full q mesh. Every PH
lambda file is matched by its own q header to one and only one representative;
any mismatch aborts rather than inventing a weight or file order.
"""
from __future__ import annotations
import argparse, math, re
from pathlib import Path
import numpy as np
import spglib

def parse_structure(path: Path):
    text=path.read_text()
    cm=re.search(r"(?im)^\s*CELL_PARAMETERS\s*(?:\(([^)]*)\)|\{([^}]*)\}|(\w+))\s*\n((?:\s*[-+0-9.eEdD]+\s+[-+0-9.eEdD]+\s+[-+0-9.eEdD]+\s*\n){3})",text)
    if not cm: raise ValueError("cannot parse CELL_PARAMETERS")
    unit=next(x for x in cm.groups()[:3] if x is not None).strip().lower()
    scale={"angstrom":1.0,"ang":1.0,"bohr":0.529177210903}.get(unit)
    if scale is None: raise ValueError("CELL_PARAMETERS alat is unsupported without celldm(1)")
    cell=np.array([[float(v.replace("d","e").replace("D","e"))*scale for v in line.split()] for line in cm.group(4).strip().splitlines()])
    pm=re.search(r"(?im)^\s*ATOMIC_POSITIONS\s*\(([^)]*)\)\s*\n((?:\s*[A-Za-z]+\s+[-+0-9.eEdD]+\s+[-+0-9.eEdD]+\s+[-+0-9.eEdD]+[^\n]*\n)+)",text)
    if not pm or pm.group(1).strip().lower()!="crystal": raise ValueError("helper requires ATOMIC_POSITIONS (crystal)")
    species=[]; coords=[]
    for line in pm.group(2).splitlines():
        p=line.split(); species.append(p[0]); coords.append([float(x.replace("d","e").replace("D","e")) for x in p[1:4]])
    numbers=[74 if x=="W" else 7 if x=="N" else 0 for x in species]
    if 0 in numbers: raise ValueError("unexpected element in crystal positions")
    return cell,np.asarray(coords),numbers

def read_ph_file(path):
    lines=path.read_text().splitlines()
    if not lines: raise ValueError(f"empty PH output {path}")
    values=lines[0].split()
    if len(values)<3: raise ValueError(f"missing q vector in {path}")
    return np.array([float(x.replace("d","e").replace("D","e")) for x in values[:3]])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--scf",type=Path,default=Path("scf.in")); ap.add_argument("--elph-root",type=Path,default=Path("elph_dir"))
    ap.add_argument("--mesh",nargs=3,type=int,default=(4,4,1)); ap.add_argument("--emax-thz",type=float,default=40.0)
    ap.add_argument("--degaussq-thz",type=float,default=.20); ap.add_argument("--ngaussq",type=int,default=1)
    ap.add_argument("--outdir",type=Path,default=Path(".")); a=ap.parse_args()
    out=a.outdir.resolve(); out.mkdir(parents=True,exist_ok=True)
    # Never leave a previous mapping usable after the current PH outputs fail validation.
    for name in ("lambda.in", "lambda-mu010.in"):
        stale=out/name
        if stale.exists(): stale.unlink()
    if a.emax_thz<=0 or a.degaussq_thz<=0 or a.ngaussq not in (0,1): raise ValueError("invalid lambda.x broadening settings")
    cell,positions,numbers=parse_structure(a.scf); mesh=tuple(a.mesh)
    mapping,addresses=spglib.get_ir_reciprocal_mesh(mesh,(cell,positions,numbers),is_shift=(0,0,0),is_time_reversal=True,symprec=1e-5)
    reps=sorted(set(int(i) for i in mapping)); weights={r:int(np.count_nonzero(mapping==r)) for r in reps}
    full_frac=np.mod(addresses/np.array(mesh),1.0)
    reciprocal=2*np.pi*np.linalg.inv(cell).T
    alat=float(np.linalg.norm(cell[0]))
    files=sorted(a.elph_root.rglob("elph.inp_lambda.*"),key=lambda p:int(p.name.rsplit(".",1)[-1]))
    if len(files)!=len(reps): raise ValueError(f"PH lambda file count {len(files)} differs from structure-symmetry irreducible q count {len(reps)}")
    rows=[]; used=set()
    for f in files:
        q_tpiba=read_ph_file(f)
        # QE prints Cartesian q in units of 2*pi/alat; convert to reciprocal
        # crystal coordinates, locate its full-grid point, then use QE/spglib's
        # symmetry mapping to obtain the orbit weight independent of rep choice.
        q_cart=q_tpiba*(2*np.pi/alat)
        q_frac=np.mod(q_cart@np.linalg.inv(reciprocal),1.0)
        grid_matches=[]
        for index,q0 in enumerate(full_frac):
            delta=q_frac-q0; delta-=np.rint(delta)
            if float(np.max(np.abs(delta)))<1e-5: grid_matches.append(index)
        if len(grid_matches)!=1: raise ValueError(f"QE Cartesian q={q_tpiba.tolist()} maps to {len(grid_matches)} full-grid points")
        r=int(mapping[grid_matches[0]])
        if r in used: raise ValueError(f"multiple PH files map to irreducible q representative {r}")
        used.add(r); rows.append((q_tpiba,weights[r],f))
    if used!=set(reps) or sum(w for _,w,_ in rows)!=math.prod(mesh): raise ValueError("q coverage or irreducible weights do not sum to full mesh")
    cwd=Path.cwd().resolve()
    for mu,name in ((.16,"lambda.in"),(.10,"lambda-mu010.in")):
        lines=[f"{a.emax_thz:.8g} {a.degaussq_thz:.8g} {a.ngaussq}",str(len(rows))]
        lines += ["%.10f %.10f %.10f %d"%(q[0],q[1],q[2],w) for q,w,_ in rows]
        lines += [f.resolve().relative_to(cwd).as_posix() for _,_,f in rows]
        lines.append(f"{mu:.2f}"); (out/name).write_text("\n".join(lines)+"\n")
    print(f"lambda.x inputs written for {len(rows)} PH q points; irreducible weights sum to {sum(w for _,w,_ in rows)}")

if __name__=="__main__":
    try: main()
    except Exception as exc: raise SystemExit(f"ERROR: refusing to write lambda.x input: {exc}")
