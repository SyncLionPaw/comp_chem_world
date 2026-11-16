#!/bin/sh
set -eu
app=${APP:-/app}
input=${INPUT_DIR:-$app/inputs}
output=$app/final
mkdir -p "$output"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
cat > "$work/fit.py" <<'ORACLE_PY'

import argparse,json
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser();p.add_argument('--input-dir',type=Path);p.add_argument('--output-dir',type=Path);a=p.parse_args()
lines=(a.input_dir/'naphthalene_radical_orca.esp').read_text().splitlines();n,m=map(int,lines[0].split()[:2])
x=np.array([list(map(float,s.split())) for s in lines[1:n+1]]);data=np.array([list(map(float,s.split())) for s in lines[n+1:n+1+m]])
xyz=(a.input_dir/'naphthalene_radical.xyz').read_text().splitlines()
if int(xyz[0])!=n or len(xyz)<n+2: raise ValueError('XYZ/ESP atom counts differ')
symbols=[s.split()[0] for s in xyz[2:n+2]]
xyz_angstrom=np.array([list(map(float,s.split()[1:4])) for s in xyz[2:n+2]])
if symbols!=['C']*10+['H']*8: raise ValueError('Unexpected XYZ atom order')
mapping_residual=float(np.max(np.abs(xyz_angstrom/0.529177210903-x)))
if mapping_residual>1e-6: raise ValueError(f'XYZ/ESP atom mapping mismatch: {mapping_residual:.6g} bohr')
A=1/np.linalg.norm(data[:,None,1:]-x[None,:,:],axis=2);V=data[:,0];mask=np.r_[np.ones(10),np.zeros(8)]
def J(q):return np.sum((A@q-V)**2)+.0005*np.sum(mask*(np.sqrt(q*q+.1**2)-.1))
q=np.full(n,1/n);logs=[]
for step in range(100):
 g=2*A.T@(A@q-V)+.0005*mask*q/np.sqrt(q*q+.1**2)
 H=2*A.T@A+np.diag(.0005*mask*.1**2/(q*q+.1**2)**1.5)
 residual=float(np.max(np.abs(g-g.mean())));logs.append(f'{step} J={J(q):.16g} projected_gradient={residual:.6g}')
 if residual<1e-10:break
 K=np.zeros((n+1,n+1));K[:n,:n]=H;K[n,:n]=1;K[:n,n]=1
 delta=np.linalg.solve(K,np.r_[-g,1-q.sum()])[:n];t=1.
 while J(q+t*delta)>J(q)+1e-4*t*g@delta:
  t*=.5
  if t<1e-10:raise RuntimeError('Line search failed')
 q+=t*delta
else:raise RuntimeError('Not converged')
a.output_dir.mkdir(parents=True,exist_ok=True)
(a.output_dir/'charges.json').write_text(json.dumps({'charge':1,'multiplicity':2,'charges':q.tolist(),'objective':float(J(q)),'esp_rmse_hartree_per_e':float(np.sqrt(np.mean((A@q-V)**2)))}))
(a.output_dir/'fit-input.json').write_text(json.dumps({'method':'Newton/KKT','a':.0005,'b':.1,'restrained_atoms':list(range(10)),'charge_constraint':1,'convergence_rule':'projected gradient <1e-10','mapping_check':'XYZ coordinates converted from angstrom to bohr and compared in unchanged atom order','mapping_max_residual_bohr':mapping_residual}))
(a.output_dir/'fit.log').write_text('\n'.join(logs)+'\nConverged\n')
(a.output_dir/'analysis.md').write_text(f"Fixed-geometry charge +1 doublet RESP fit using the original ESP/XYZ order. XYZ coordinates were converted from angstrom to bohr; the maximum atom-coordinate residual against the ESP atom list was {mapping_residual:.6g} bohr (limit 1e-6 bohr). ESP grid coordinates are bohr and potentials hartree/e. Newton/KKT converged at projected gradient {residual:.6g}; objective {J(q):.12g}, charge sum {q.sum():.12g} e. The hyperbolic restraint applies only to carbon.\n")
ORACLE_PY
cp "$work/fit.py" "$output/fit.py"
python3 "$work/fit.py" --input-dir "$input" --output-dir "$output"
