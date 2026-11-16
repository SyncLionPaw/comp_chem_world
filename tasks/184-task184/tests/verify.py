#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Diagnose displacement information in wrapped water trajectories.
"""Independent Case06 verifier for wrapped MIC displacement diagnostics and D identifiability."""
import argparse,hashlib,json,math,sys
from pathlib import Path
import numpy as np
class EvaluationError(Exception): pass

EXPECTED_REFS_SHA256 = "a7442589af6a2c7e2f28ba65bcccb099185a149634bb47eabd8322a086bf8478"


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

REFS=load_refs(); GRADE=REFS["grading"]; BOX=GRADE["box_A"]
EXPECTED_MANIFEST_SHA=GRADE["manifest_sha256"]
CONTRACT_VERSION=REFS["contract_version"]

def read(path):
 try: lines=Path(path).read_text(encoding='ascii').splitlines()
 except Exception as e:raise EvaluationError(str(e))
 out=[];i=0
 try:
  while i<len(lines):
   if lines[i]!='ITEM: TIMESTEP':raise ValueError('marker')
   step=int(lines[i+1]);i+=2
   if lines[i]!='ITEM: NUMBER OF ATOMS' or int(lines[i+1])!=GRADE['atom_count']:raise ValueError('atoms')
   i+=2
   if lines[i]!='ITEM: BOX BOUNDS xy xz yz pp pp pp':raise ValueError('box')
   b=np.array([[float(v) for v in lines[i+j].split()] for j in (1,2,3)])
   if b.shape!=(3,3) or np.any(~np.isfinite(b)) or np.max(np.abs(b[:,2]))>GRADE["box_tilt_tolerance_A"] or np.max(np.abs(b[:,1]-b[:,0]-BOX))>GRADE["box_length_tolerance_A"]:raise ValueError('cell')
   i+=4;hdr=lines[i].split()
   if hdr[2:7]!=['id','type','x','y','z'] or any(x in hdr for x in ('ix','iy','iz')):raise ValueError('expected wrapped coordinates without image flags')
   i+=1;rows=[x.split() for x in lines[i:i+GRADE["atom_count"]]];i+=GRADE["atom_count"];rows.sort(key=lambda r:int(r[0]))
   ids=np.array([int(r[0]) for r in rows]);types=np.array([int(r[1]) for r in rows]);xyz=np.array([[float(v) for v in r[2:5]] for r in rows])
   if len(set(ids))!=GRADE["atom_count"] or np.any(~np.isfinite(xyz)) or np.count_nonzero(types==1)!=GRADE["oxygen_count"] or np.count_nonzero(types==2)!=GRADE["hydrogen_count"]:raise ValueError('identity/coordinates')
   out.append((step,ids,types,xyz))
  if len(out)!=GRADE["frames"] or [f[0] for f in out]!=list(range(GRADE["step_start"],GRADE["step_stop"]+1,GRADE["step_interval"])):raise ValueError('frame sequence')
 except Exception as e:raise EvaluationError(f'invalid trusted trajectory: {e}')
 return out

def mic(x):return x-BOX*np.rint(x/BOX)
def calc(frames):
 ids=frames[0][1][frames[0][2]==1];prev=frames[0][3][frames[0][2]==1].copy();unwrapped=prev.copy();rows=[];wraps=0;maxvec=0.;maxcomp=0.;witness=None
 for n,(step,allids,typ,pos) in enumerate(frames):
  cur=pos[typ==1];curids=allids[typ==1]
  if not np.array_equal(curids,ids):raise EvaluationError('oxygen identity/order changed')
  if n:
   raw=cur-prev;delta=mic(raw);wraps+=int(np.count_nonzero(np.abs(raw)>BOX/2));norm=np.sqrt(np.sum(delta*delta,axis=1));j=int(np.argmax(norm))
   if norm[j]>maxvec:maxvec=float(norm[j]);witness={'from_step':frames[n-1][0],'to_step':step,'oxygen_id':int(ids[j]),'wrapped_delta_A':raw[j].tolist(),'mic_delta_A':delta[j].tolist()}
   maxcomp=max(maxcomp,float(np.max(np.abs(delta))));unwrapped+=delta;prev=cur
  diff=unwrapped-frames[0][3][frames[0][2]==1]
  rows.append({'step':step,'time_ps':step*GRADE["time_ps_per_step"],'mic_path_msd_from_frame0_A2':float(np.mean(np.sum(diff*diff,axis=1)))})
 a=frames[0][3][frames[0][2]==1][0];b=frames[1][3][frames[1][2]==1][0];raw=b-a;d=mic(raw);alt=d+np.array([BOX,0,0]);mod=a+alt-b;mod=mic(mod)
 return {'frames':rows,'sampling':{'frames':GRADE['frames'],'interval_fs':GRADE['step_interval']//2,'duration_ps':10,'oxygen_count':GRADE['oxygen_count'],'cell_A':[BOX]*3,'coordinates':'wrapped x/y/z','image_flags_present':False},'summary':{'adjacent_MIC_vector_max_A':maxvec,'adjacent_MIC_component_max_A':maxcomp,'wrapped_components_reduced_by_MIC_count':wraps,'max_step_witness':witness},'ambiguity_witness':{'oxygen_id':int(ids[0]),'from_step':0,'to_step':100,'wrapped_delta_A':raw.tolist(),'mic_reconstruction_A':d.tolist(),'equally_periodic_alternative_A':alt.tolist(),'mic_length_A':float(np.linalg.norm(d)),'alternative_length_A':float(np.linalg.norm(alt)),'same_wrapped_endpoint':bool(np.allclose(mod,0,atol=GRADE["endpoint_tolerance"],rtol=0))}}

def valid_alias_witness(w,frames):
 try:
  if not isinstance(w,dict) or type(w.get('oxygen_id')) is not int or type(w.get('from_step')) is not int or type(w.get('to_step')) is not int: return False
  if w['from_step']>=w['to_step']: return False
  by_step={fr[0]:fr for fr in frames}
  if w['from_step'] not in by_step or w['to_step'] not in by_step: return False
  positions=[]
  for step in (w['from_step'],w['to_step']):
   _,ids,typ,pos=by_step[step]; idx=np.where((ids==w['oxygen_id'])&(typ==1))[0]
   if len(idx)!=1:return False
   positions.append(pos[int(idx[0])])
  raw=positions[1]-positions[0]; disp=mic(raw)
  alt=np.asarray(w.get('equally_periodic_alternative_A'),dtype=float)
  if alt.shape!=(3,) or not np.isfinite(alt).all():return False
  if not close(w.get('wrapped_delta_A'),raw) or not close(w.get('mic_reconstruction_A'),disp):return False
  winding=(alt-disp)/BOX; lattice=np.rint(winding)
  if not np.allclose(winding,lattice,atol=GRADE["witness_tolerance"],rtol=0) or not np.any(lattice!=0):return False
  endpoint=mic(positions[0]+alt-positions[1])
  mic_length=float(np.linalg.norm(disp));alt_length=float(np.linalg.norm(alt))
  if np.linalg.norm(endpoint)>GRADE["value_tolerance"] or abs(mic_length-alt_length)<=GRADE["value_tolerance"]:return False
  return w.get('same_wrapped_endpoint') is True and close(w.get('mic_length_A'),mic_length) and close(w.get('alternative_length_A'),alt_length)
 except Exception:return False

def close(a,b,tol=GRADE["value_tolerance"]):
 try:
  x=np.asarray(a,dtype=float);y=np.asarray(b,dtype=float)
  return x.shape==y.shape and np.isfinite(x).all() and np.max(np.abs(x-y),initial=0)<=tol
 except Exception:return False

def max_witness_matches(got,frames,expected_max):
 try:
  keys={'from_step','to_step','oxygen_id','wrapped_delta_A','mic_delta_A'}
  if not isinstance(got,dict) or set(got)!=keys:return False
  if any(type(got.get(k)) is not int for k in ('from_step','to_step','oxygen_id')):return False
  if got['to_step']-got['from_step']!=GRADE['step_interval']:return False
  by_step={fr[0]:fr for fr in frames}
  if got['from_step'] not in by_step or got['to_step'] not in by_step:return False
  f0,f1=by_step[got['from_step']],by_step[got['to_step']]
  ix=np.where((f0[1]==got['oxygen_id'])&(f0[2]==1))[0]
  jx=np.where((f1[1]==got['oxygen_id'])&(f1[2]==1))[0]
  if len(ix)!=1 or len(jx)!=1:return False
  raw=f1[3][int(jx[0])]-f0[3][int(ix[0])];delta=mic(raw)
  return (close(got['wrapped_delta_A'],raw) and close(got['mic_delta_A'],delta)
          and abs(float(np.linalg.norm(delta))-expected_max)<=GRADE["value_tolerance"])
 except Exception:return False

def finite_number(value):
 if type(value) not in (int,float): return False
 try: return math.isfinite(value)
 except (OverflowError,TypeError): return False

def number_vector(value,length):
 return isinstance(value,list) and len(value)==length and all(finite_number(x) for x in value)

def validate_candidate_types(got):
 """Validate closed public JSON types before trajectory calculations/comparisons."""
 if not isinstance(got,dict) or set(got)!={'schema','contract_version','source_sha256','displacement_method','diffusion_assessment','replicas','interpretation_limits'}: return False
 if type(got.get('schema')) is not str or type(got.get('contract_version')) is not str or type(got.get('displacement_method')) is not str: return False
 hashes=got.get('source_sha256')
 if not isinstance(hashes,list) or len(hashes)!=GRADE["replica_count"] or any(type(x) is not str for x in hashes): return False
 da=got.get('diffusion_assessment')
 if not isinstance(da,dict) or set(da)!={'status','value_A2_per_ps','reason'}: return False
 if type(da.get('status')) is not str or da.get('value_A2_per_ps') is not None or type(da.get('reason')) is not str: return False
 reps=got.get('replicas')
 if not isinstance(reps,list) or len(reps)!=GRADE["replica_count"]: return False
 for rep in reps:
  if not isinstance(rep,dict) or set(rep)!={'frames','sampling','summary','ambiguity_witness'}: return False
  sampling=rep.get('sampling')
  if not isinstance(sampling,dict) or set(sampling)!={'frames','interval_fs','duration_ps','oxygen_count','cell_A','coordinates','image_flags_present'}: return False
  if any(type(sampling.get(k)) is not int for k in ('frames','interval_fs','duration_ps','oxygen_count')): return False
  if not number_vector(sampling.get('cell_A'),3) or type(sampling.get('coordinates')) is not str or type(sampling.get('image_flags_present')) is not bool: return False
  rows=rep.get('frames')
  if not isinstance(rows,list) or len(rows)!=GRADE["frames"]: return False
  for row in rows:
   if not isinstance(row,dict) or set(row)!={'step','time_ps','mic_path_msd_from_frame0_A2'}: return False
   if type(row.get('step')) is not int or not finite_number(row.get('time_ps')) or not finite_number(row.get('mic_path_msd_from_frame0_A2')): return False
  summary=rep.get('summary')
  if not isinstance(summary,dict) or set(summary)!={'adjacent_MIC_vector_max_A','adjacent_MIC_component_max_A','wrapped_components_reduced_by_MIC_count','max_step_witness'}: return False
  if not finite_number(summary.get('adjacent_MIC_vector_max_A')) or not finite_number(summary.get('adjacent_MIC_component_max_A')) or type(summary.get('wrapped_components_reduced_by_MIC_count')) is not int: return False
  witness=summary.get('max_step_witness')
  if not isinstance(witness,dict) or set(witness)!={'from_step','to_step','oxygen_id','wrapped_delta_A','mic_delta_A'}: return False
  if any(type(witness.get(k)) is not int for k in ('from_step','to_step','oxygen_id')) or not number_vector(witness.get('wrapped_delta_A'),3) or not number_vector(witness.get('mic_delta_A'),3): return False
  alias=rep.get('ambiguity_witness')
  if not isinstance(alias,dict) or set(alias)!={'oxygen_id','from_step','to_step','wrapped_delta_A','mic_reconstruction_A','equally_periodic_alternative_A','mic_length_A','alternative_length_A','same_wrapped_endpoint'}: return False
  if any(type(alias.get(k)) is not int for k in ('oxygen_id','from_step','to_step')) or type(alias.get('same_wrapped_endpoint')) is not bool: return False
  if any(not number_vector(alias.get(k),3) for k in ('wrapped_delta_A','mic_reconstruction_A','equally_periodic_alternative_A')): return False
  if any(not finite_number(alias.get(k)) for k in ('mic_length_A','alternative_length_A')): return False
 limits=got.get('interpretation_limits')
 return isinstance(limits,list) and all(type(x) is str for x in limits)

def check(app,assets):
 try:
  manifest_bytes=(assets/'trajectory-manifest.json').read_bytes()
  if hashlib.sha256(manifest_bytes).hexdigest()!=EXPECTED_MANIFEST_SHA:raise EvaluationError('reference manifest SHA mismatch')
  man=json.loads(manifest_bytes);groups=[];hashes=[]
  for ent in man['trajectory_files']:
   path=assets/ent['path'];h=hashlib.sha256(path.read_bytes()).hexdigest()
   if h!=ent['sha256']:raise EvaluationError('reference trajectory SHA mismatch')
   groups.append(read(path));hashes.append(h)
 except EvaluationError:raise
 except Exception as e:raise EvaluationError(f'reference manifest error: {e}')
 try:got=json.loads((app/'final/validation/displacement-assessment.json').read_text())
 except Exception:return False,'candidate output missing or malformed'
 if not isinstance(got,dict) or got.get('schema')!='case06-wrapped-displacement-diagnostic/v2' or got.get('contract_version')!=CONTRACT_VERSION:return False,'schema/version mismatch'
 if not validate_candidate_types(got):return False,'candidate JSON types or shapes do not match the public schema'
 if set(got)!={'schema','contract_version','source_sha256','displacement_method','diffusion_assessment','replicas','interpretation_limits'}:return False,'unexpected or missing top-level fields'
 if got.get('source_sha256')!=hashes:return False,'source hash mismatch'
 if got.get('displacement_method')!='frame-to-frame orthorhombic MIC increments summed from frame 0; minimum-image path diagnostic only':return False,'displacement method mismatch'
 da=got.get('diffusion_assessment',{})
 if not isinstance(da,dict) or set(da)!={'status','value_A2_per_ps','reason'}:return False,'diffusion assessment fields mismatch'
 if da.get('status')!='D_not_identifiable' or da.get('value_A2_per_ps') is not None:return False,'must withhold numerical D'
 reason=da.get('reason','')
 if not isinstance(reason,str) or not reason.strip():return False,'a nonempty identifiability explanation is required'
 reps=got.get('replicas',[])
 if len(reps)!=GRADE["replica_count"]:return False,'replica count'
 for actual,frames in zip(reps,groups):
  if not isinstance(actual,dict) or set(actual)!={'frames','sampling','summary','ambiguity_witness'}:return False,'replica fields mismatch'
  exp=calc(frames)
  if not isinstance(actual.get('sampling'),dict) or set(actual['sampling'])!={'frames','interval_fs','duration_ps','oxygen_count','cell_A','coordinates','image_flags_present'}:return False,'sampling fields mismatch'
  if actual.get('sampling')!=exp['sampling']:return False,'sampling/wrapped-image metadata mismatch'
  rows=actual.get('frames',[])
  if not isinstance(rows,list) or len(rows)!=GRADE["frames"]:return False,'per-frame MIC-path analysis is required'
  for a,b in zip(rows,exp['frames']):
   if not isinstance(a,dict) or set(a)!={'step','time_ps','mic_path_msd_from_frame0_A2'}:return False,'frame fields mismatch'
   if type(a.get('step')) is not int or a.get('step')!=b['step'] or not close(a.get('time_ps'),b['time_ps'],GRADE["value_tolerance"]) or not close(a.get('mic_path_msd_from_frame0_A2'),b['mic_path_msd_from_frame0_A2'],GRADE["value_tolerance"]):return False,'MIC-path displacement array mismatch'
  s=actual.get('summary',{})
  if not isinstance(s,dict) or set(s)!={'adjacent_MIC_vector_max_A','adjacent_MIC_component_max_A','wrapped_components_reduced_by_MIC_count','max_step_witness'}:return False,'summary fields mismatch'
  for key in ['adjacent_MIC_vector_max_A','adjacent_MIC_component_max_A']:
   if not close(s.get(key),exp['summary'][key],GRADE["value_tolerance"]):return False,'adjacent MIC summary mismatch'
  if (s.get('wrapped_components_reduced_by_MIC_count')!=exp['summary']['wrapped_components_reduced_by_MIC_count']
      or not max_witness_matches(s.get('max_step_witness'),frames,exp['summary']['adjacent_MIC_vector_max_A'])):return False,'MIC wrap-event/witness mismatch'
  aw=actual.get('ambiguity_witness',{})
  if not isinstance(aw,dict) or set(aw)!={'oxygen_id','from_step','to_step','wrapped_delta_A','mic_reconstruction_A','equally_periodic_alternative_A','mic_length_A','alternative_length_A','same_wrapped_endpoint'}:return False,'ambiguity witness fields mismatch'
  if not valid_alias_witness(aw,frames):return False,'lattice ambiguity witness is not a source-derived sampled endpoint alias'
 # Reject numeric diffusion claims anywhere, even if hidden under an added field.
 def find_claim(obj):
  if isinstance(obj,dict):
   for k,v in obj.items():
    key=k.lower()
    if ('diffusion' in key or key in {'d','d_value','diffusion_coefficient'}) and isinstance(v,(int,float)) and not isinstance(v,bool): return True
    if find_claim(v):return True
  elif isinstance(obj,list):return any(find_claim(x) for x in obj)
  return False
 if find_claim(got):return False,'numeric diffusion coefficient is not identifiable and must not be reported'
 limits=got.get('interpretation_limits',[])
 if not isinstance(limits,list) or not limits or any(type(x) is not str or not x.strip() for x in limits):return False,'nonempty interpretation limits are required'
 return True,'wrapped MIC diagnostics and non-identifiability evidence verified; no D estimate accepted'

def main():
 p=argparse.ArgumentParser();p.add_argument('--app-dir',type=Path,required=True);p.add_argument('--assets-dir',type=Path,required=True);a=p.parse_args()
 try:ok,msg=check(a.app_dir,a.assets_dir)
 except EvaluationError as e:print(json.dumps({'status':'ERROR','task_status':'NOT_EVALUATED','science_status':'INCONCLUSIVE','reward':None,'message':str(e)}));return 2
 except Exception as e:ok,msg=False,f'candidate submission invalid: {e}'
 result={'status':'PASS' if ok else 'FAIL','task_status':'COMPLETED_VALIDATION' if ok else 'FAILED_REQUIREMENTS','science_status':'PASS' if ok else 'FAIL','reward':1 if ok else 0,'message':msg};print(json.dumps(result));return 0 if ok else 1
if __name__=='__main__':sys.exit(main())
