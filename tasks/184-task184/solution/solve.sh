#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PKG="$(cd "$HERE/.." && pwd -P)"
APP="${APP:-$(pwd -P)}"
ASSETS="${CASE06_V2_ASSETS:-$PKG/environment/assets/public-inputs-v2}"
OUT="$APP/final/exploration/displacement-diagnostics.json"
TMP_SOLVER="$(mktemp "${TMPDIR:-/tmp}/task184-solve.XXXXXX.py")"
trap 'rm -f "$TMP_SOLVER"' EXIT
cat > "$TMP_SOLVER" <<'PY_SOLVER'
#!/usr/bin/env python3
"""Case06 v2: wrapped-coordinate displacement diagnostics; never fit a diffusion constant."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
BOX=12.4

def load(path):
 out=[]; f=open(path,encoding='ascii')
 while True:
  line=f.readline()
  if not line:break
  if line.strip()!='ITEM: TIMESTEP':raise ValueError('timestep marker')
  step=int(f.readline())
  if f.readline().strip()!='ITEM: NUMBER OF ATOMS' or int(f.readline())!=192:raise ValueError('atom count')
  if f.readline().strip()!='ITEM: BOX BOUNDS xy xz yz pp pp pp':raise ValueError('box header')
  b=[list(map(float,f.readline().split())) for _ in range(3)]
  if any(len(x)!=3 or abs(x[2])>1e-9 or abs(x[1]-x[0]-BOX)>1e-8 for x in b):raise ValueError('cell')
  h=f.readline().split()
  if h[2:7]!=['id','type','x','y','z'] or any(x in h for x in ['ix','iy','iz']):raise ValueError('expected wrapped xyz without image flags')
  a=[f.readline().split() for _ in range(192)];a.sort(key=lambda x:int(x[0]))
  ids=np.array([int(x[0]) for x in a]);typ=np.array([int(x[1]) for x in a]);pos=np.array([[float(v) for v in x[2:5]] for x in a])
  if len(set(ids))!=192 or not np.isfinite(pos).all() or (typ==1).sum()!=64 or (typ==2).sum()!=128:raise ValueError('atom identities/coordinates')
  out.append((step,ids,typ,pos))
 if len(out)!=201 or [x[0] for x in out]!=list(range(0,20001,100)):raise ValueError('frame sequence')
 return out

def diagnostics(frames):
 ids0=frames[0][1][frames[0][2]==1]; prev=frames[0][3][frames[0][2]==1]; unwrapped=prev.copy(); rows=[]; crossings=0; max_step=0.; max_component=0.; max_pair=None
 for fi,(step,ids,types,pos) in enumerate(frames):
  oxygen_ids=ids[types==1]; current=pos[types==1]
  if not np.array_equal(oxygen_ids,ids0):raise ValueError('oxygen ID/order changed')
  if fi:
   raw=current-prev; delta=raw-BOX*np.rint(raw/BOX); nwrap=np.abs(raw)>BOX/2; crossings+=int(nwrap.sum())
   lengths=np.linalg.norm(delta,axis=1); k=int(np.argmax(lengths));
   if lengths[k]>max_step:max_step=float(lengths[k]);max_pair={'from_step':frames[fi-1][0],'to_step':step,'oxygen_id':int(ids0[k]),'wrapped_delta_A':raw[k].tolist(),'mic_delta_A':delta[k].tolist()}
   max_component=max(max_component,float(np.max(np.abs(delta))))
   unwrapped+=delta;prev=current
  dr=unwrapped-frames[0][3][frames[0][2]==1]; msd=float(np.mean(np.sum(dr*dr,axis=1)))
  rows.append({'step':step,'time_ps':step*.0005,'mic_path_msd_from_frame0_A2':msd})
 # One concrete lattice-alias witness for the first sampled interval and first O.
 a=frames[0][3][frames[0][2]==1][0];b=frames[1][3][frames[1][2]==1][0];raw=b-a;mic=raw-BOX*np.rint(raw/BOX);alt=mic+np.array([BOX,0.,0.])
 witness={'oxygen_id':int(ids0[0]),'from_step':frames[0][0],'to_step':frames[1][0],'wrapped_delta_A':raw.tolist(),'mic_reconstruction_A':mic.tolist(),'equally_periodic_alternative_A':alt.tolist(),'mic_length_A':float(np.linalg.norm(mic)),'alternative_length_A':float(np.linalg.norm(alt)),'same_wrapped_endpoint':bool(np.allclose((a+alt-b)-BOX*np.rint((a+alt-b)/BOX),0,atol=1e-10,rtol=0))}
 return {'frames':rows,'sampling':{'frames':len(frames),'interval_fs':50,'duration_ps':10,'oxygen_count':64,'cell_A':[BOX]*3,'coordinates':'wrapped x/y/z','image_flags_present':False},'summary':{'adjacent_MIC_vector_max_A':max_step,'adjacent_MIC_component_max_A':max_component,'wrapped_components_reduced_by_MIC_count':crossings,'max_step_witness':max_pair},'ambiguity_witness':witness}

def main():
 p=argparse.ArgumentParser();p.add_argument('--assets-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();man=json.loads((a.assets_dir/'trajectory-manifest.json').read_text());reps=[];sha=[]
 for ent in man['trajectory_files']:
  f=a.assets_dir/ent['path'];s=hashlib.sha256(f.read_bytes()).hexdigest()
  if s!=ent['sha256']:raise SystemExit('asset hash mismatch')
  frames=load(f);reps.append(diagnostics(frames));sha.append(s)
 out={'schema':'case06-wrapped-displacement-diagnostic/v2','contract_version':'2.0','source_sha256':sha,'displacement_method':'frame-to-frame orthorhombic MIC increments summed from frame 0; minimum-image path diagnostic only','diffusion_assessment':{'status':'D_not_identifiable','value_A2_per_ps':None,'reason':'wrapped coordinates contain no image flags; each sampled endpoint pair admits additional lattice-vector displacements, so true unwrapped MSD and its long-time slope are not determined'},'replicas':reps,'interpretation_limits':['the reported MIC path is one minimum-image reconstruction, not the validated unwrapped MSD','no diffusion coefficient is fitted or reported','no image flags or velocity bound resolve winding ambiguity between 50 fs samples','two historical nonblind trajectories; descriptive only','no new MD or model inference']}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':main()
PY_SOLVER
python3 -I "$TMP_SOLVER" --assets-dir "$ASSETS" --output "$OUT"
