#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Quantify static hydrogen-bond networks and tetrahedral order in water.
"""Independent source-derived Case05 v2 verifier for mapping, HB graph and q."""
import argparse, hashlib, json, math, sys
from pathlib import Path
import numpy as np
class EvaluationError(Exception): pass

EXPECTED_REFS_SHA256 = "12de58b32235e0a61350d724688aafedbad86e69151d921acd3b5643914c6947"


def load_refs():
    path=Path(__file__).resolve().parent/"refs.json"
    try:
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=EXPECTED_REFS_SHA256: raise EvaluationError("trusted grading reference integrity check failed")
        refs=json.loads(raw.decode("utf-8"))
    except EvaluationError: raise
    except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise EvaluationError(f"trusted grading references unavailable: {exc}") from exc
    if not isinstance(refs,dict) or refs.get("schema")!="water-case-contract/v2": raise EvaluationError("trusted grading references have an unexpected schema")
    return refs

REFS=load_refs(); GRADE=REFS["grading"]; BOX=GRADE["box_A"]; N=GRADE["atom_count"]
EXPECTED_MANIFEST_SHA=GRADE["manifest_sha256"]
CONTRACT_VERSION=REFS["contract_version"]

def load(path):
 try: lines=Path(path).read_text(encoding='ascii').splitlines()
 except Exception as e: raise EvaluationError(f'reference read failed: {e}')
 out=[]; i=0
 try:
  while i<len(lines):
   if lines[i]!='ITEM: TIMESTEP': raise ValueError('timestep marker')
   step=int(lines[i+1]); i+=2
   if lines[i]!='ITEM: NUMBER OF ATOMS' or int(lines[i+1])!=GRADE['atom_count']: raise ValueError('atom count')
   i+=2
   if lines[i]!='ITEM: BOX BOUNDS xy xz yz pp pp pp': raise ValueError('box header')
   b=np.array([[float(y) for y in lines[i+j].split()] for j in (1,2,3)])
   if b.shape!=(3,3) or np.any(~np.isfinite(b)) or np.max(np.abs(b[:,2]))>GRADE["box_tilt_tolerance_A"] or np.max(np.abs(b[:,1]-b[:,0]-BOX))>GRADE["box_length_tolerance_A"]: raise ValueError('cell')
   i+=4
   if not lines[i].startswith('ITEM: ATOMS id type x y z'): raise ValueError('atom header')
   i+=1; rows=[x.split() for x in lines[i:i+N]]; i+=N
   rows.sort(key=lambda r:int(r[0])); ids=np.array([int(r[0]) for r in rows]); types=np.array([int(r[1]) for r in rows]); xyz=np.array([[float(v) for v in r[2:5]] for r in rows])
   if len(set(ids))!=N or np.any(~np.isfinite(xyz)) or np.count_nonzero(types==1)!=GRADE["oxygen_count"] or np.count_nonzero(types==2)!=GRADE["hydrogen_count"]: raise ValueError('atom data')
   out.append((step,ids,types,xyz))
  if len(out)!=GRADE['frames'] or [x[0] for x in out]!=list(range(GRADE['step_start'],GRADE['step_stop']+1,GRADE['step_interval'])): raise ValueError('frame sequence')
 except Exception as e: raise EvaluationError(f'reference trajectory invalid: {e}')
 return out

def mic(x): return x-BOX*np.rint(x/BOX)
def q_for(o,ids):
 delta=mic(o[None,:,:]-o[:,None,:]); r=np.sqrt(np.sum(delta*delta,axis=2)); np.fill_diagonal(r,np.inf); vals=[]
 for i in range(GRADE["oxygen_count"]):
  near=sorted((j for j in range(GRADE["oxygen_count"]) if j!=i),key=lambda j:(r[i,j],int(ids[j])))[:4]
  u=delta[i,near]/r[i,near,None]; s=0.
  for a in range(4):
   for b in range(a+1,4): s+=(np.dot(u[a],u[b])+1/3)**2
  vals.append(1-0.375*s)
 return vals

def frame_values(fr):
 step,ids,types,xyz=fr; oi=ids[types==1]; hi=ids[types==2]; o=xyz[types==1]; h=xyz[types==2]
 dx=mic(o[:,None,:]-h[None,:,:]); dist=np.sqrt(np.sum(dx*dx,axis=2)).T
 sorted_ix=np.argsort(dist,axis=1,kind='stable'); owner_idx=sorted_ix[:,0]; d1=dist[np.arange(GRADE["hydrogen_count"]),owner_idx]; d2=dist[np.arange(GRADE["hydrogen_count"]),sorted_ix[:,1]]; gap=d2-d1
 cnt=np.bincount(owner_idx,minlength=GRADE["oxygen_count"]); mapping={int(hid):int(oi[j]) for hid,j in zip(hi,owner_idx)}
 valid=bool(np.all(d1<REFS["mapping_gate"]["nearest_OH_A_exclusive"]) and np.all(gap>REFS["mapping_gate"]["nearest_second_gap_A_exclusive_min"]) and np.all(cnt==2))
 # H positions keyed by atom ID, donor O determined by gated mapping.
 h_xyz={int(a):xyz[k] for k,a in enumerate(ids)}; directed=[]
 for donor in range(GRADE["oxygen_count"]):
  hs=[hid for hid in hi if mapping[int(hid)]==int(oi[donor])]
  for hid in hs:
   vh=mic(h_xyz[int(hid)]-o[donor]); vh/=np.linalg.norm(vh)
   for acceptor in range(GRADE["oxygen_count"]):
    if donor==acceptor: continue
    oa=mic(o[acceptor]-o[donor]); roo=np.linalg.norm(oa)
    if roo<REFS["hydrogen_bond"]["OO_A_exclusive_max"] and math.degrees(math.acos(float(np.clip(np.dot(vh,oa/roo),-1,1))))<REFS["hydrogen_bond"]["angle_deg_exclusive_max"]:
     directed.append([int(oi[donor]),int(hid),int(oi[acceptor])])
 directed.sort(); edges=sorted({tuple(sorted((a,c))) for a,_,c in directed}); graph={int(x):set() for x in oi}
 for a,b in edges: graph[a].add(b);graph[b].add(a)
 deg={str(k):sum(len(graph[x])==k for x in graph) for k in range(GRADE["oxygen_count"])}
 left=set(graph); comps=[]
 while left:
  todo=[min(left)];left.remove(todo[0]);n=0
  while todo:
   x=todo.pop();n+=1
   for y in list(graph[x]&left): left.remove(y);todo.append(y)
  comps.append(n)
 qvals=q_for(o,oi); qarr=np.asarray(qvals,dtype=float)
 q_summary={'count':int(qarr.size),'mean':float(np.mean(qarr)),'population_std':float(np.std(qarr,ddof=0)),'minimum':float(np.min(qarr)),'median':float(np.median(qarr)),'maximum':float(np.max(qarr))}
 return {'step':step,'mapping_valid':valid,'mapping':[[int(a),mapping[int(a)]] for a in sorted(hi)],'max_nearest_OH_A':float(max(d1)),'min_nearest_second_gap_A':float(min(gap)),'directed_bonds':directed,'undirected_edges':[list(x) for x in edges],'degree_histogram':deg,'component_sizes':sorted(comps,reverse=True),'q_by_oxygen':qvals,'q_summary':q_summary}

def finite_number(value):
 if type(value) not in (int,float): return False
 try: return math.isfinite(value)
 except (OverflowError,TypeError): return False

def integer_list(value, width=None):
 return (isinstance(value,list) and (width is None or len(value)==width)
         and all(type(x) is int for x in value))

def number_vector(value, length):
 return isinstance(value,list) and len(value)==length and all(finite_number(x) for x in value)

def validate_candidate_types(got):
 """Validate public JSON scalar/container types before source-derived comparisons."""
 if not isinstance(got,dict): return False
 if type(got.get('schema')) is not str or type(got.get('contract_version')) is not str: return False
 hashes=got.get('source_sha256')
 if not isinstance(hashes,list) or len(hashes)!=GRADE["replica_count"] or any(type(x) is not str for x in hashes): return False
 mr=got.get('mapping_rule')
 if not isinstance(mr,dict) or not finite_number(mr.get('nearest_OH_max_A')) or not finite_number(mr.get('nearest_vs_second_gap_min_A')) or type(mr.get('hydrogens_per_oxygen')) is not int or type(mr.get('failure')) is not str: return False
 hb=got.get('hydrogen_bond_rule')
 if not isinstance(hb,dict) or not finite_number(hb.get('OO_max_A_exclusive')) or not finite_number(hb.get('angle_between_Od_to_H_and_Od_to_Oa_deg_max_exclusive')): return False
 if any(type(hb.get(k)) is not str for k in ('pbc','directed_edges','undirected_graph')) or type(got.get('q_rule')) is not str: return False
 reps=got.get('replicas')
 if not isinstance(reps,list) or len(reps)!=GRADE["replica_count"]: return False
 for rep in reps:
  if not isinstance(rep,dict): return False
  frames=rep.get('frames')
  if not isinstance(frames,list) or len(frames)!=GRADE["frames"]: return False
  for frame in frames:
   if not isinstance(frame,dict) or type(frame.get('step')) is not int or type(frame.get('mapping_valid')) is not bool: return False
   for key in ('mapping','directed_bonds','undirected_edges'):
    rows=frame.get(key)
    width={'mapping':2,'directed_bonds':3,'undirected_edges':2}[key]
    if not isinstance(rows,list) or any(not integer_list(row,width) for row in rows): return False
   for key in ('max_nearest_OH_A','min_nearest_second_gap_A'):
    if not finite_number(frame.get(key)): return False
   degrees=frame.get('degree_histogram')
   if not isinstance(degrees,dict) or any(type(k) is not str or type(v) is not int for k,v in degrees.items()): return False
   if not integer_list(frame.get('component_sizes')) or not number_vector(frame.get('q_by_oxygen'),GRADE['oxygen_count']): return False
   summary=frame.get('q_summary')
   if not isinstance(summary,dict) or type(summary.get('count')) is not int: return False
   if any(not finite_number(summary.get(k)) for k in ('mean','population_std','minimum','median','maximum')): return False
  audit=rep.get('mapping_audit')
  if not isinstance(audit,dict): return False
  if any(type(audit.get(k)) is not int for k in ('frame_count','invalid_frames','hydrogen_assignment_changes_vs_first_frame')): return False
  if any(not finite_number(audit.get(k)) for k in ('max_nearest_OH_A','minimum_nearest_second_gap_A')): return False
 limits=got.get('interpretation_limits')
 return isinstance(limits,list) and all(type(x) is str for x in limits)

def close(a,b,tol=GRADE["mapping_value_tolerance"]):
 try:
  x=np.asarray(a,dtype=float);y=np.asarray(b,dtype=float)
  return x.shape==y.shape and np.all(np.isfinite(x)) and np.max(np.abs(x-y),initial=0)<=tol
 except Exception: return False

def verify(app,assets):
 try:
  manifest_bytes=(assets/'trajectory-manifest.json').read_bytes()
  if hashlib.sha256(manifest_bytes).hexdigest()!=EXPECTED_MANIFEST_SHA: raise EvaluationError('reference manifest SHA mismatch')
  man=json.loads(manifest_bytes); groups=[]; hashes=[]
  for entry in man['trajectory_files']:
   path=assets/entry['path']; sha=hashlib.sha256(path.read_bytes()).hexdigest()
   if sha!=entry['sha256']: raise EvaluationError('pinned trajectory SHA mismatch')
   groups.append(load(path));hashes.append(sha)
 except EvaluationError: raise
 except Exception as e: raise EvaluationError(f'reference manifest unavailable/invalid: {e}')
 try: got=json.loads((app/'final/relabel/network-analysis.json').read_text())
 except Exception: return False,'candidate output missing or malformed'
 if not isinstance(got,dict) or got.get('schema')!='case05-static-network-q/v2' or got.get('contract_version')!=CONTRACT_VERSION: return False,'schema/version mismatch'
 if not validate_candidate_types(got): return False,'candidate JSON field types or shapes do not match the public schema'
 try:
  if got.get('source_sha256')!=hashes: return False,'source hash mismatch'
  if got.get('mapping_rule')!={'nearest_OH_max_A':REFS['mapping_gate']['nearest_OH_A_exclusive'],'nearest_vs_second_gap_min_A':REFS['mapping_gate']['nearest_second_gap_A_exclusive_min'],'hydrogens_per_oxygen':REFS['mapping_gate']['H_per_O'],'failure':'scientific FAIL closed'}: return False,'mapping rule mismatch'
  hb=got.get('hydrogen_bond_rule',{})
  if hb.get('OO_max_A_exclusive')!=REFS['hydrogen_bond']['OO_A_exclusive_max'] or hb.get('angle_between_Od_to_H_and_Od_to_Oa_deg_max_exclusive')!=REFS['hydrogen_bond']['angle_deg_exclusive_max'] or hb.get('pbc')!='orthorhombic MIC' or hb.get('directed_edges')!='one per qualifying donor H and acceptor' or hb.get('undirected_graph')!='deduplicate oxygen pair': return False,'HB definition mismatch'
  if got.get('q_rule')!='1-3/8 sum over six pairs among four nearest other O of (cos(psi)+1/3)^2; preserve negative values': return False,'q rule mismatch'
  if len(got.get('replicas',[]))!=2: return False,'replica count mismatch'
  for i,(frames,rep) in enumerate(zip(groups,got['replicas'])):
   expected=[frame_values(fr) for fr in frames]; supplied=rep.get('frames',[])
   if len(supplied)!=GRADE["frames"]: return False,'frame count mismatch'
   for a,b in zip(supplied,expected):
    for key in ['step','mapping_valid','mapping','directed_bonds','undirected_edges','degree_histogram','component_sizes']:
     if a.get(key)!=b[key]: return False,f'{key} mismatch'
    for key in ['max_nearest_OH_A','min_nearest_second_gap_A']:
     if not close(a.get(key),b[key],GRADE["mapping_value_tolerance"]): return False,f'{key} mismatch'
    if not close(a.get('q_by_oxygen'),b['q_by_oxygen'],GRADE["mapping_value_tolerance"]): return False,'q values mismatch'
    summary=a.get('q_summary')
    if not isinstance(summary,dict) or set(summary)!={'count','mean','population_std','minimum','median','maximum'} or type(summary.get('count')) is not int or summary['count']!=GRADE["oxygen_count"]: return False,'q distribution summary fields/count mismatch'
    for key in ['mean','population_std','minimum','median','maximum']:
     if not close(summary.get(key),b['q_summary'][key],GRADE["mapping_value_tolerance"]): return False,'q distribution summary mismatch'
   first={int(h):int(o) for h,o in expected[0]['mapping']}; changed=sum(sum(int(o)!=first[int(h)] for h,o in fr['mapping']) for fr in expected)
   audit=rep.get('mapping_audit',{})
   expected_audit={'frame_count':GRADE['frames'],'invalid_frames':sum(not x['mapping_valid'] for x in expected),'hydrogen_assignment_changes_vs_first_frame':changed,'max_nearest_OH_A':max(x['max_nearest_OH_A'] for x in expected),'minimum_nearest_second_gap_A':min(x['min_nearest_second_gap_A'] for x in expected)}
   for key,value in expected_audit.items():
    if isinstance(value,float):
     if not close(audit.get(key),value): return False,'mapping audit mismatch'
    elif audit.get(key)!=value:return False,'mapping audit mismatch'
   if expected_audit['invalid_frames']>0:raise EvaluationError('trusted reference fails the frozen molecule-mapping gate')
  limits=got.get('interpretation_limits',[])
  if not isinstance(limits,list) or not limits or any(type(x) is not str or not x.strip() for x in limits): return False,'nonempty interpretation limits are required'
  return True,'source-derived molecule mapping, HB geometry network, and q values verified'
 except EvaluationError:
  raise
 except Exception as e: return False,f'candidate output invalid: {e}'

def main():
 p=argparse.ArgumentParser();p.add_argument('--app-dir',type=Path,required=True);p.add_argument('--assets-dir',type=Path,required=True);a=p.parse_args()
 try: ok,msg=verify(a.app_dir,a.assets_dir)
 except EvaluationError as e: print(json.dumps({'status':'ERROR','task_status':'NOT_EVALUATED','science_status':'INCONCLUSIVE','reward':None,'message':str(e)}));return 2
 result={'status':'PASS' if ok else 'FAIL','task_status':'COMPLETED_VALIDATION' if ok else 'FAILED_REQUIREMENTS','science_status':'PASS' if ok else 'FAIL','reward':1 if ok else 0,'message':msg};print(json.dumps(result));return 0 if ok else 1
if __name__=='__main__':sys.exit(main())
