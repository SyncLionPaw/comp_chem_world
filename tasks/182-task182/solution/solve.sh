#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PKG="$(cd "$HERE/.." && pwd -P)"
APP="${APP:-$(pwd -P)}"
ASSETS="${CASE04_V2_ASSETS:-$PKG/environment/assets/public-inputs-v2}"
OUT="$APP/final/exploration/rdf-analysis.json"
TMP_SOLVER="$(mktemp "${TMPDIR:-/tmp}/task182-solve.XXXXXX.py")"
trap 'rm -f "$TMP_SOLVER"' EXIT
cat > "$TMP_SOLVER" <<'PY_SOLVER'
#!/usr/bin/env python3
"""Generate Case04 v2 descriptive RDF/CN analysis from the pinned nonblind dumps."""
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
DR=0.05; RMAX=6.2; RCUT=3.55; N_O=64; BOX=12.4

def load_dump(path):
    frames=[]
    with open(path,encoding='ascii') as f:
      while True:
        line=f.readline()
        if not line: break
        if line.strip()!='ITEM: TIMESTEP': raise ValueError('bad dump timestep marker')
        step=int(f.readline());
        if f.readline().strip()!='ITEM: NUMBER OF ATOMS': raise ValueError('bad atom marker')
        n=int(f.readline());
        if n!=192 or f.readline().strip()!='ITEM: BOX BOUNDS xy xz yz pp pp pp': raise ValueError('atom count or box header mismatch')
        bounds=[list(map(float,f.readline().split())) for _ in range(3)]
        if any(len(x)!=3 or abs(x[2])>1e-10 for x in bounds): raise ValueError('non-orthogonal/invalid box')
        lengths=np.array([bounds[i][1]-bounds[i][0] for i in range(3)])
        if not np.allclose(lengths,BOX,atol=1e-10): raise ValueError('unexpected cell')
        header=f.readline().strip().split()
        if header[:2]!=['ITEM:','ATOMS'] or header[2:7]!=['id','type','x','y','z']: raise ValueError('unsupported atom fields')
        atoms=[]
        for _ in range(n):
          a=f.readline().split(); atoms.append((int(a[0]),int(a[1]),[float(x) for x in a[2:5]]))
        atoms.sort(); ids=np.array([a[0] for a in atoms]); types=np.array([a[1] for a in atoms]); xyz=np.array([a[2] for a in atoms])
        if len(set(ids))!=192 or np.count_nonzero(types==1)!=64 or np.count_nonzero(types==2)!=128: raise ValueError('atom identity/type mismatch')
        frames.append((step,ids,types,xyz,lengths))
    if len(frames)!=201 or frames[0][0]!=0 or frames[-1][0]!=20000: raise ValueError('trajectory is incomplete')
    return frames

def curve(frames):
    edges=np.arange(0.0,RMAX+DR/2,DR); shell=(4*math.pi/3)*(edges[1:]**3-edges[:-1]**3); hist=np.zeros(len(shell),dtype=np.int64); pair_count=0
    for _,_,types,xyz,L in frames:
      o=xyz[types==1]; d=o[:,None,:]-o[None,:,:]; d-=L*np.rint(d/L); dist=np.sqrt(np.sum(d*d,axis=2)); ii,jj=np.triu_indices(len(o),1); x=dist[ii,jj]; x=x[x<RMAX]; hist+=np.histogram(x,bins=edges)[0]; pair_count+=len(ii)
    vol=float(np.prod(frames[0][4])); g=hist*vol/(pair_count*shell)
    return edges,shell,hist,g

def peak_min(edges,g):
    centers=(edges[:-1]+edges[1:])/2; pi=np.where((centers>=2.4)&(centers<=3.1))[0]; peak=int(pi[np.argmax(g[pi])]); sm=np.convolve(g,np.ones(3)/3,mode='valid'); smcent=centers[1:-1]; candidates=np.where((smcent>=3.0)&(smcent<=4.0)&(np.arange(len(sm))>peak-1))[0]
    mins=[int(i) for i in candidates if i>0 and i+1<len(sm) and sm[i]<=sm[i-1] and sm[i]<sm[i+1]]
    if not mins: raise ValueError('first post-peak local minimum not found in fixed window')
    mi=mins[0]; cutoff_edge=float(edges[int(round((smcent[mi]+DR/2)/DR))]);
    if abs(cutoff_edge-RCUT)>1e-9: raise ValueError(f'locked data cutoff changed: {cutoff_edge}')
    return float(centers[peak]),float(smcent[mi]),cutoff_edge

def result_for(frames,edges,shell,peak,minimum,cutoff,label):
    center=(edges[:-1]+edges[1:])/2; cutoff_n=int(round(cutoff/DR));
    g_hist=[]
    for t0,t1,tag in [(0,20000,'all'),(0,10000,'early_0_5ps'),(10100,20000,'late_5_10ps')]:
      sel=[fr for fr in frames if t0<=fr[0]<=t1]
      h=np.zeros(len(shell),dtype=np.int64); pairs=0
      for _,_,types,xyz,L in sel:
        o=xyz[types==1]; d=o[:,None,:]-o[None,:,:]; d-=L*np.rint(d/L); rr=np.sqrt(np.sum(d*d,axis=2)); i,j=np.triu_indices(64,1); x=rr[i,j]; x=x[x<RMAX]; h+=np.histogram(x,bins=edges)[0]; pairs+=len(i)
      g=h*np.prod(frames[0][4])/(pairs*shell); cn=float((63/np.prod(frames[0][4]))*np.sum(g[:cutoff_n]*shell[:cutoff_n]))
      g_hist.append({'segment':tag,'frame_count':len(sel),'time_ps':[t0*.0005,t1*.0005],'g_r':g.tolist(),'cn_first_shell':cn})
    return {'replica':label,'bin_edges_A':edges.tolist(),'bin_centers_A':center.tolist(),'segments':g_hist,'first_peak_A':peak,'first_smoothed_minimum_A':minimum,'first_shell_cutoff_A':cutoff}

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(); p.add_argument('--assets-dir',type=Path,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args()
 manifest=json.loads((a.assets_dir/'trajectory-manifest.json').read_text()); allframes=[]; raw={}
 for i,row in enumerate(manifest['trajectory_files']):
  f=a.assets_dir/row['path']; h=sha(f)
  if h!=row['sha256']: raise SystemExit(f'asset SHA mismatch: {row["path"]}')
  frames=load_dump(f); raw[str(i)]=h; allframes.append(frames)
 pooled=[x for fs in allframes for x in fs]; edges,shell,h,g=curve(pooled); peak,minimum,cutoff=peak_min(edges,g)
 out={'schema':'case04-rdf-analysis/v2','contract_version':'2.0','source_sha256':raw,'method':{'dr_A':DR,'rmax_A':RMAX,'normalization':'finite_N_unordered_OO_pairs','first_peak_window_A':[2.4,3.1],'minimum_smoothing':'centered_3_bin_arithmetic_mean','first_minimum_window_A':[3.0,4.0],'cutoff_bin_edge_A':cutoff,'coordination_density':'(N_O-1)/V'},'bin_edges_A':edges.tolist(),'pooled_first_peak_A':peak,'pooled_first_smoothed_minimum_A':minimum,'replicas':[result_for(fs,edges,shell,peak,minimum,cutoff,f'replica-{i:02d}') for i,fs in enumerate(allframes)],'interpretation_limits':['two 10 ps historical trajectories only','5 ps segments and replicas are descriptive; no independent standard error claim','no claim of equilibration or sampling convergence','integral to 6.2 A is cumulative neighbor count, not first-shell coordination','historical member-0-driven MD; no new simulation or independent DFT utility claim']}
 a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
if __name__=='__main__': main()

PY_SOLVER
python3 -I "$TMP_SOLVER" --assets-dir "$ASSETS" --output "$OUT"
