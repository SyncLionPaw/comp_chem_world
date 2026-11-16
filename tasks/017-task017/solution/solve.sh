#!/bin/sh
set -eu
app=${APP:-/app}
input=${INPUT_DIR:-$app/inputs}
output=$app/final
mkdir -p "$output"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
cat > "$work/extract.py" <<'ORACLE_PY'
"""Actual periodic geometry extraction. Independent native-data processing."""
from pathlib import Path
import argparse,json,shutil
import numpy as np,parmed
from scipy.io import netcdf_file
p=argparse.ArgumentParser();p.add_argument('--input-dir',type=Path);p.add_argument('--output-dir',type=Path);a=p.parse_args();out=a.output_dir;out.mkdir(parents=True,exist_ok=True);(out/'clusters').mkdir(exist_ok=True)
top=parmed.load_file(str(a.input_dir/'water_solvated.prmtop'));residues=[[x.idx for x in r.atoms] for r in top.residues]
with netcdf_file(str(a.input_dir/'water_solvated-qmmmnvt.netcdf'),mmap=False) as f:
 xyz=f.variables['coordinates'][:].copy();cells=f.variables['cell_lengths'][:].copy();times=f.variables['time'][:].copy()
frames=[]
def reconstruct(ids,x,L):
 result={ids[0]:x[ids[0]].copy()};queue=[ids[0]];allowed=set(ids)
 while queue:
  i=queue.pop(0)
  for neighbor in top.atoms[i].bond_partners:
   j=neighbor.idx
   if j in allowed and j not in result:
    delta=x[j]-x[i];result[j]=result[i]+delta-L*np.floor(delta/L+.5);queue.append(j)
 return np.array([result[i] for i in ids])
for frame in range(0,100,10):
 x=xyz[frame].astype(float);L=cells[frame];solute=reconstruct(residues[0],x,L);center=solute.mean(0);chosen=[0]
 for rid,indices in enumerate(residues[1:],1):
  differences=x[indices,None,:]-solute[None,:,:];differences-=L*np.floor(differences/L+.5)
  if np.min(np.linalg.norm(differences,axis=-1))<=4:chosen.append(rid)
 ids=[];coords=[]
 for rid in chosen:
  indexes=residues[rid];molecule=reconstruct(indexes,x,L);molecule-=L*np.floor((molecule[0]-center)/L+.5);ids.extend(indexes);coords.extend(molecule-center)
 elems=[parmed.periodic_table.Element[top.atoms[i].atomic_number] for i in ids];name=f'clusters/frame-{frame:03d}.xyz'
 (out/name).write_text(str(len(ids))+'\n\n'+'\n'.join(e+' '+' '.join(f'{v:.8f}' for v in row) for e,row in zip(elems,coords))+'\n')
 frames.append({'frame':frame,'time_ps':float(times[frame]),'file':name,'atom_indices':ids})
(out/'selection.json').write_text(json.dumps({'frames':frames,'sampling':{'source_span_ps':float(times[-1]-times[0]),'selected_span_ps':float(times[90]-times[0]),'independent_equilibrium_samples':False,'purpose':'geometric_extraction_validation'}},indent=2)+'\n')
(out/'analysis.md').write_text('实际按每帧盒长和最小周期距离选整分子；用于几何验证，不能推断独立平衡采样。\n');shutil.copyfile(__file__,out/'extract.py')
ORACLE_PY
cp "$work/extract.py" "$output/extract.py"
python3 "$work/extract.py" --input-dir "$input" --output-dir "$output"
