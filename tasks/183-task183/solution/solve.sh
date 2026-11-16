#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PKG="$(cd "$HERE/.." && pwd -P)"
APP="${APP:-$(pwd -P)}"
ASSETS="${CASE05_V2_ASSETS:-$PKG/environment/assets/public-inputs-v2}"
OUT="$APP/final/exploration/hb-graph.json"
TMP_SOLVER="$(mktemp "${TMPDIR:-/tmp}/task183-solve.XXXXXX.py")"
trap 'rm -f "$TMP_SOLVER"' EXIT
cat > "$TMP_SOLVER" <<'PY_SOLVER'
#!/usr/bin/env python3
"""Case05 v2 static hydrogen-bond network and tetrahedral-order analysis."""
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
BOX=12.4; N=192

def parse(path):
 out=[]; f=open(path); lines=iter(f)
 for line in lines:
  if line.strip()!='ITEM: TIMESTEP': raise ValueError('dump marker')
  step=int(next(lines));
  if next(lines).strip()!='ITEM: NUMBER OF ATOMS' or int(next(lines))!=N: raise ValueError('atom count')
  if next(lines).strip()!='ITEM: BOX BOUNDS xy xz yz pp pp pp': raise ValueError('box header')
  bounds=[list(map(float,next(lines).split())) for _ in range(3)]
  if any(len(x)!=3 or abs(x[2])>1e-9 or abs(x[1]-x[0]-BOX)>1e-8 for x in bounds): raise ValueError('cell')
  hdr=next(lines).split()
  if hdr[2:7]!=['id','type','x','y','z']: raise ValueError('atom columns')
  a=[next(lines).split() for _ in range(N)]; a.sort(key=lambda x:int(x[0]))
  ids=np.array([int(x[0]) for x in a]); typ=np.array([int(x[1]) for x in a]); xyz=np.array([[float(v) for v in x[2:5]] for x in a])
  if len(set(ids))!=N or sum(typ==1)!=64 or sum(typ==2)!=128: raise ValueError('types/ids')
  out.append((step,ids,typ,xyz))
 if len(out)!=201: raise ValueError('frame count')
 return out

def mic(v): return v-BOX*np.rint(v/BOX)
def analyze_frame(fr):
 step,ids,typ,pos=fr; om=typ==1; hm=typ==2; oi=ids[om]; hi=ids[hm]; o=pos[om]; h=pos[hm]
 # Deterministic H-to-O reconstruction, with an explicit ambiguity margin.
 d=mic(h[:,None,:]-o[None,:,:]); dist=np.sqrt((d*d).sum(2)); order=np.argsort(dist,axis=1,kind='stable'); near=order[:,0]; d1=dist[np.arange(128),near]; d2=dist[np.arange(128),order[:,1]]; gap=d2-d1
 owners={int(hi[k]):int(oi[near[k]]) for k in range(128)}
 assigned=np.bincount(near,minlength=64)
 mapping_ok=bool(np.all(d1<1.25) and np.all(gap>0.20) and np.all(assigned==2))
 if not mapping_ok: raise ValueError(f'frame {step} fails the frozen O-H mapping gate; refusing to write a result')
 # q for each O using four nearest other oxygen sites.
 oo=mic(o[:,None,:]-o[None,:,:]); rr=np.sqrt((oo*oo).sum(2)); np.fill_diagonal(rr,np.inf); q=[]
 for i in range(64):
  ix=sorted((j for j in range(64) if j!=i),key=lambda j:(rr[i,j],int(oi[j])))[:4]
  vec=oo[i,ix]; vec=vec/np.linalg.norm(vec,axis=1)[:,None]; c=[]
  for a in range(4):
   for b in range(a+1,4): c.append(float(np.dot(vec[a],vec[b])))
  q.append(1-3/8*sum((x+1/3)**2 for x in c))
 # LC-style static geometric bonds: each qualifying donor H forms a directed edge.
 hpos={int(i):pos[k] for k,i in enumerate(ids)}; directed=[]
 for donor in range(64):
  for hydrogen,owner in owners.items():
   if owner!=int(oi[donor]): continue
   v1=mic(hpos[hydrogen]-o[donor]);
   for acceptor in range(64):
    if acceptor==donor: continue
    v2=mic(o[acceptor]-o[donor]); r=float(np.linalg.norm(v2))
    if r>=3.5: continue
    cos=float(np.dot(v1,v2)/(np.linalg.norm(v1)*r)); angle=math.degrees(math.acos(max(-1,min(1,cos))))
    if angle<30: directed.append([int(oi[donor]),hydrogen,int(oi[acceptor])])
 pairs=sorted({tuple(sorted((x[0],x[2]))) for x in directed}); adj={int(i):set() for i in oi}
 for a,b in pairs: adj[a].add(b); adj[b].add(a)
 deg={str(k):sum(len(adj[int(i)])==k for i in oi) for k in range(64)}
 unseen=set(adj); comps=[]
 while unseen:
  root=min(unseen); stack=[root]; unseen.remove(root); size=0
  while stack:
   x=stack.pop(); size+=1
   for y in adj[x]&unseen: unseen.remove(y); stack.append(y)
  comps.append(size)
 qv=np.asarray(q,dtype=float)
 q_summary={'count':int(qv.size),'mean':float(np.mean(qv)),'population_std':float(np.std(qv,ddof=0)),'minimum':float(np.min(qv)),'median':float(np.median(qv)),'maximum':float(np.max(qv))}
 return {'step':step,'mapping_valid':mapping_ok,'mapping':[[h,owners[h]] for h in sorted(owners)],'max_nearest_OH_A':float(d1.max()),'min_nearest_second_gap_A':float(gap.min()),'directed_bonds':sorted(directed),'undirected_edges':[list(x) for x in pairs],'degree_histogram':deg,'component_sizes':sorted(comps,reverse=True),'q_by_oxygen':q,'q_summary':q_summary}

def main():
 p=argparse.ArgumentParser();p.add_argument('--assets-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 man=json.loads((a.assets_dir/'trajectory-manifest.json').read_text()); reps=[]; shas=[]
 for row in man['trajectory_files']:
  f=a.assets_dir/row['path']; sha=hashlib.sha256(f.read_bytes()).hexdigest()
  if sha!=row['sha256']: raise SystemExit('asset hash mismatch')
  frames=parse(f); results=[analyze_frame(fr) for fr in frames]
  ref=results[0]['mapping']; changed=sum(sum(x[1]!=dict(ref)[x[0]] for x in fr['mapping']) for fr in results)
  reps.append({'frames':results,'mapping_audit':{'frame_count':len(results),'invalid_frames':sum(not x['mapping_valid'] for x in results),'hydrogen_assignment_changes_vs_first_frame':changed,'max_nearest_OH_A':max(x['max_nearest_OH_A'] for x in results),'minimum_nearest_second_gap_A':min(x['min_nearest_second_gap_A'] for x in results)}});shas.append(sha)
 out={'schema':'case05-static-network-q/v2','contract_version':'2.0','source_sha256':shas,'mapping_rule':{'nearest_OH_max_A':1.25,'nearest_vs_second_gap_min_A':0.20,'hydrogens_per_oxygen':2,'failure':'scientific FAIL closed'},'hydrogen_bond_rule':{'OO_max_A_exclusive':3.5,'angle_between_Od_to_H_and_Od_to_Oa_deg_max_exclusive':30,'pbc':'orthorhombic MIC','directed_edges':'one per qualifying donor H and acceptor','undirected_graph':'deduplicate oxygen pair'},'q_rule':'1-3/8 sum over six pairs among four nearest other O of (cos(psi)+1/3)^2; preserve negative values','replicas':reps,'interpretation_limits':['geometric molecular mapping is reconstructed and gated, not an external topology','static networks only; no hydrogen-bond lifetime claim','descriptive historical nonblind trajectories; no new simulation','q and HB outputs do not establish equilibrium or experimental agreement']}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':main()
PY_SOLVER
python3 -I "$TMP_SOLVER" --assets-dir "$ASSETS" --output "$OUT"
