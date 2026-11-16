#!/usr/bin/env bash
set -euo pipefail
APP="${APP:-/app}"
exec python3 - --case "$APP" --out "$APP" <<'PY_ANALYZE'
#!/usr/bin/env python3
"""Recompute a retrospective force-reference audit from the included records."""
import argparse, hashlib, json, math, re
from pathlib import Path
import numpy as np
HARTREE_EV=27.211386245988
FORCE_AU=HARTREE_EV/0.529177210903
LIMITS={'energy_abs_eV_per_atom':1e-4,'force_component_rmse_eV_A':.01,'max_atom_force_vector_delta_eV_A':.05}
THRESHOLD=.15

def digest(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()

def parse_native(log,xyz):
 t=log.read_text(errors='replace')
 atoms=[line.split()[0] for line in xyz.read_text().splitlines()[2:] if line.split()]
 en=re.findall(r'^\s*ENERGY\|\s+Total FORCE_EVAL\s*\(\s*QS\s*\)\s+energy\s+\[a\.u\.\]\s*:\s*([^\s]+)',t,re.M)
 if len(en)!=1 or t.count('ATOMIC FORCES in [a.u.]')!=1 or t.count('SCF run converged')!=1 or t.count('PROGRAM ENDED AT')!=1 or re.search(r'SCF run NOT converged|ABORT|FATAL ERROR',t,re.I):
  return {'valid':False,'reason':'nonconverged, incomplete or ambiguous native result'}
 lines=t[t.index('ATOMIC FORCES in [a.u.]'):].splitlines()[1:]; rows=[]
 for line in lines:
  p=line.split()
  if len(p)>=6 and p[0].isdigit() and p[1].isdigit():
   try: rows.append((int(p[0]),p[2],*[float(x) for x in p[3:6]]))
   except ValueError: return {'valid':False,'reason':'nonnumeric force row'}
   if len(rows)>304:break
  elif rows:break
 if len(rows)!=304 or [r[0] for r in rows]!=list(range(1,305)) or [r[1] for r in rows]!=atoms:
  return {'valid':False,'reason':'force rows do not match ordered XYZ atoms'}
 f=np.array([r[2:] for r in rows],dtype=float)*FORCE_AU; e=float(en[0])*HARTREE_EV
 if not np.isfinite(f).all() or not math.isfinite(e):return {'valid':False,'reason':'nonfinite native value'}
 geom='\n'.join(x.strip() for x in xyz.read_text().splitlines()[2:])+'\n'
 return {'valid':True,'energy_eV':e,'forces':f,'elements':atoms,'geometry_hash':hashlib.sha256(geom.encode()).hexdigest()}

def parse_input(path,xyz):
 t=path.read_text(errors='strict')
 def one(pattern,cast=str):
  found=re.findall(pattern,t,re.I|re.M)
  if len(found)!=1: raise ValueError(f'{path.name}: expected one setting {pattern}')
  return cast(found[0])
 cell=re.search(r'&CELL\b(.*?)&END\s+CELL',t,re.I|re.S)
 if not cell: raise ValueError(f'{path.name}: missing CELL')
 vectors={}
 for axis in ('A','B','C'):
  found=re.findall(r'^\s*'+axis+r'\s+([-+0-9.eEdD]+)\s+([-+0-9.eEdD]+)\s+([-+0-9.eEdD]+)\s*$',cell.group(1),re.I|re.M)
  if len(found)!=1: raise ValueError(f'{path.name}: invalid CELL {axis}')
  vectors[axis]=[float(x.replace('D','E').replace('d','e')) for x in found[0]]
 xc=re.search(r'&XC_FUNCTIONAL\s+([A-Za-z0-9_-]+)',t,re.I)
 pp=re.search(r'&PAIR_POTENTIAL\s+(.*?)&END\s+PAIR_POTENTIAL',t,re.I|re.S)
 if not xc or not pp: raise ValueError(f'{path.name}: method not fully parseable')
 disp=re.search(r'^\s*TYPE\s+(\S+)',pp.group(1),re.I|re.M);ref=re.search(r'^\s*REFERENCE_FUNCTIONAL\s+(\S+)',pp.group(1),re.I|re.M)
 inc=one(r'^\s*@INCLUDE\s+(\S+)\s*$'); coord=path.parent/inc
 if not coord.is_file() or coord.resolve().parent!=path.parent.resolve(): raise ValueError(f'{path.name}: unsafe/missing coordinate include')
 return {'method':one(r'^\s*METHOD\s+(Quickstep)\s*$'),'xc_functional':xc.group(1).upper(),
  'dispersion':disp.group(1).upper() if disp else None,'dispersion_reference':ref.group(1).upper() if ref else None,
  'cutoff_Ry':one(r'^\s* CUTOFF\s+(\S+)\s*$',float),'rel_cutoff_Ry':one(r'^\s* REL_CUTOFF\s+(\S+)\s*$',float),
  'eps_scf':one(r'^\s* EPS_SCF\s+(\S+)\s*$',float),'max_scf':one(r'^\s* MAX_SCF\s+(\d+)\s*$',int),
  'cell_vectors_A':vectors,'periodic':'XYZ' if re.search(r'^\s*PERIODIC\s+XYZ\s*$',t,re.I|re.M) else 'other',
  'coordinate_include_sha256':digest(coord),'ordered_coordinate_sha256':digest(xyz),'atom_count':sum(bool(x.split()) for x in xyz.read_text().splitlines()[2:])}

def metric(ref,pred):
 d=pred-ref
 return {'force_component_rmse_eV_A':float(np.sqrt(np.mean(d*d))),
         'max_atom_vector_eV_A':float(np.max(np.linalg.norm(d,axis=-1)))}

def pair(a,b):
 d=b['forces']-a['forces']
 vals={'energy_abs_eV_per_atom':abs(b['energy_eV']-a['energy_eV'])/304,
       'force_component_rmse_eV_A':float(np.sqrt(np.mean(d*d))),
       'max_atom_force_vector_delta_eV_A':float(np.max(np.linalg.norm(d,axis=1)))}
 return {'metrics':vals,'gates':{k:vals[k]<=v for k,v in LIMITS.items()},'same_geometry':a['geometry_hash']==b['geometry_hash']}

def scheduler_receipt(directory):
 files=sorted(directory.glob('slurm-sacct*.txt'))
 if not files:return None
 lines=[x.strip() for x in files[0].read_text(errors='replace').splitlines() if x.strip()]
 if len(lines)<2:return {'receipt':files[0].name,'status':'unparsed'}
 header=lines[0].split('|');row=lines[1].split('|')
 if len(header)!=len(row):return {'receipt':files[0].name,'status':'unparsed'}
 data=dict(zip(header,row))
 return {'receipt':files[0].name,'state':data.get('State'),'exit_code':data.get('ExitCode')}

def summarize_cell(cell, posthoc=False):
 frames=[r for r in cell['frames'] if r['counted_as_verified_hit']]; n=len(frames)
 if not n:return {'valid_n':0,'per_model_mean_rmse_eV_A':None,'per_model_max_frame_vector_eV_A':None,'ensemble_mean_rmse_eV_A':None,'ensemble_max_frame_vector_eV_A':None}
 return {'valid_n':n,
         'per_model_mean_rmse_eV_A':[float(np.mean([r['per_model'][m]['force_component_rmse_eV_A'] for r in frames])) for m in range(4)],
         'per_model_max_frame_vector_eV_A':[float(max(r['per_model'][m]['max_atom_vector_eV_A'] for r in frames)) for m in range(4)],
         'ensemble_mean_rmse_eV_A':float(np.mean([r['ensemble']['force_component_rmse_eV_A'] for r in frames])),
         'ensemble_max_frame_vector_eV_A':float(max(r['ensemble']['max_atom_vector_eV_A'] for r in frames)),
         'frame_hit_count':sum(bool(r['hit']) for r in frames)}

def classify_decision(pairs, verified_frames, cross_setting_geometry_count):
 cross=[p for p in pairs if p.get('settings_differ') is True and p.get('valid') is True and p.get('process_verified') is True]
 if any(not all(p['gates'].values()) for p in cross):return 'REFERENCE_SENSITIVE'
 if len(cross)<2 or verified_frames<20 or cross_setting_geometry_count<2:return 'INSUFFICIENT_EVIDENCE'
 return 'REFERENCE_ADEQUATE'

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--case',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();c=a.case.resolve()
 manifest=json.loads((c/'inputs/public-input-manifest.json').read_text()); hashes=[]
 for x in manifest['files']:
  p=c/x['path'];ok=p.is_file() and p.stat().st_size==x['size_bytes'] and digest(p)==x['sha256'];hashes.append(ok)
  if not ok:raise SystemExit('public input integrity failure: '+x['path'])
 selection=json.loads((c/'inputs/pool/selection.json').read_text()); poolmeta=json.loads((c/'inputs/pool/candidate-pool.json').read_text()); predmeta=json.loads((c/'inputs/pool/predictions.json').read_text())
 pool=np.load(c/'inputs/pool/candidate-pool.npz',allow_pickle=False); pred=np.load(c/'inputs/pool/predictions.npz',allow_pickle=False)
 pool_sha=digest(c/'inputs/pool/candidate-pool.npz');pred_sha=digest(c/'inputs/pool/predictions.npz')
 if poolmeta.get('npz_sha256')!=pool_sha or predmeta.get('candidate_pool_sha256')!=pool_sha or predmeta.get('npz_sha256')!=pred_sha:raise SystemExit('pool/prediction binding failure')
 original_pool_meta_sha=next(x.get('source_sha256') for x in manifest['files'] if x['path']=='inputs/pool/candidate-pool.json')
 if selection.get('pool_sha256')!=pool_sha or selection.get('predictions_sha256')!=pred_sha or selection.get('pool_metadata_sha256')!=original_pool_meta_sha:raise SystemExit('frozen selection source binding failure')
 canonical=json.dumps({k:v for k,v in selection.items() if k!='selection_sha256'},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
 if hashlib.sha256(canonical).hexdigest()!=selection.get('selection_sha256'):raise SystemExit('selection canonical hash failure')
 forces=pred['force_eV_A']; frames=pred['frame_index']
 if forces.shape!=(4,1600,304,3) or not np.array_equal(frames,np.arange(1600)) or pool['coords_A'].shape!=(1600,304,3):raise SystemExit('pool/model/frame axes mismatch')
 # Verify selected XYZ coordinate and ordered-element identity against the frozen pool.
 selected={r['selection_id']:r for r in selection['selected_20']}; focus_frame=int(selected['L01']['frame_index']); type_map=predmeta['deepmd_type_map']; allrecords={}; ledger=[]
 v1_events=[json.loads(x) for x in (c/'inputs/ledgers/v1-attempt-ledger.jsonl').read_text().splitlines()]
 v1_by={}
 for ev in v1_events:v1_by.setdefault(ev.get('attempt_id'),[]).append(ev)
 v1=c/'inputs/native/v1/attempts'
 for d in sorted(v1.iterdir()):
  if not d.is_dir() or not (d/'attempt.json').exists():continue
  aid=d.name; meta=json.loads((d/'attempt.json').read_text()); log=d/(aid+'.out'); xyz=d/(aid+'.xyz'); n=parse_native(log,xyz); setting=parse_input(d/(aid+'.inp'),xyz)
  if meta.get('attempt_id')!=aid or meta.get('input_sha256')!=digest(d/(aid+'.inp')):raise SystemExit('attempt identity/input hash mismatch '+aid)
  declared=meta.get('setting',{})
  for key in ('cutoff_Ry','rel_cutoff_Ry','eps_scf','max_scf'):
   if key not in declared or float(declared[key])!=float(setting[key]):raise SystemExit('attempt metadata/input setting mismatch '+aid+'/'+key)
  exits=list(d.glob('engine-exit*.txt')); engine=int(exits[0].read_text().strip()) if len(exits)==1 and exits[0].read_text().strip() in {'0','1','2'} else None
  evs=v1_by.get(aid,[]); starts=[x for x in evs if x.get('event')=='START']; finishes=[x for x in evs if x.get('event')=='FINISH']
  coord_sources=[x['coordinate_include_sha256'] for x in evs if x.get('coordinate_include_sha256')]
  if len(starts)!=1 or len(finishes)>1 or starts[0].get('attempt_input_sha256')!=meta.get('input_sha256') or (coord_sources and any(x!=setting['coordinate_include_sha256'] for x in coord_sources)) or meta.get('coordinate_include_sha256')!=setting['coordinate_include_sha256']:raise SystemExit('v1 ledger binding mismatch '+aid)
  if finishes and (finishes[0].get('engine_exit_code')!=engine or finishes[0].get('engine_exit_record_sha256')!=digest(exits[0])):raise SystemExit('v1 engine/ledger mismatch '+aid)
  proc='verified_success' if finishes and engine==0 else 'verified_failure' if finishes else 'unknown'
  if n['valid']:
   if meta.get('geometry_sha256')!=digest(xyz):raise SystemExit('attempt frozen-XYZ hash mismatch '+aid)
   ix=int(meta['frame_index']); row=next((item for item in selected.values() if item['frame_index']==ix),None)
   if not np.allclose(np.array([[float(z) for z in l.split()[1:4]] for l in xyz.read_text().splitlines()[2:]]),pool['coords_A'][ix],atol=1e-8,rtol=0):raise SystemExit('XYZ/pool coordinate mismatch '+aid)
   symbols=n['elements']; expected=[type_map[int(z)] for z in pool['type_ids_0based']]
   if symbols!=expected:raise SystemExit('XYZ/pool atom-type map mismatch '+aid)
  allrecords[aid]={**n,'frame_index':meta.get('frame_index'),'category':meta.get('category'),'process':proc,'engine':engine,'setting':setting}
  ledger.append({'attempt_id':aid,'population':'original_v1','frame_index':meta.get('frame_index'),'category':meta.get('category'),'native_status':'native_valid' if n['valid'] else 'native_failed_or_unusable','engine_status':'exit_0' if engine==0 else 'nonzero_exit' if engine is not None else 'no_exit_record','process_status':proc,'workflow_scheduler_status':scheduler_receipt(d),'engine_exit_present':bool(exits),'geometry_hash':n.get('geometry_hash'),'setting':setting,'reason':n.get('reason')})
 v2=c/'inputs/native/v2'
 op_events=[json.loads(x) for x in (c/'inputs/ledgers/v2-operator-budget-events-public.jsonl').read_text().splitlines()]
 v2_events=[json.loads(x) for x in (c/'inputs/ledgers/v2-attempt-events-public.jsonl').read_text().splitlines()]
 v2_by={}
 for ev in v2_events:v2_by.setdefault(ev.get('attempt_id'),[]).append(ev)
 scheduler_by_attempt={}
 for ev in op_events:
  if ev.get('attempt_id') and ev.get('scheduler_state'):
   scheduler_by_attempt[ev['attempt_id']]={'state':ev['scheduler_state'],'exit_code':ev.get('scheduler_exit_code')}
 for aid in ('D1','D2','B01','S01'):
  d=v2/aid;meta=json.loads((d/'attempt.json').read_text());n=parse_native(d/(aid+'.out'),d/(aid+'.xyz'));setting=parse_input(d/(aid+'.inp'),d/(aid+'.xyz'));exits=list(d.glob('engine-exit*.txt'));engine=int(exits[0].read_text().strip()) if len(exits)==1 and exits[0].read_text().strip() in {'0','1','2'} else None
  declared=meta.get('setting',{})
  for key in ('cutoff_Ry','rel_cutoff_Ry','eps_scf','max_scf'):
   if key not in declared or float(declared[key])!=float(setting[key]):raise SystemExit('attempt metadata/input setting mismatch '+aid+'/'+key)
  evs=v2_by.get(aid,[]);starts=[x for x in evs if x.get('event')=='START'];finishes=[x for x in evs if x.get('event')=='FINISH']
  if meta.get('attempt_id')!=aid or meta.get('input_sha256')!=digest(d/(aid+'.inp')) or len(starts)!=1 or len(finishes)!=1 or starts[0].get('v2_input_sha256')!=meta.get('input_sha256') or starts[0].get('coordinate_include_sha256')!=setting['coordinate_include_sha256'] or meta.get('coordinate_include_sha256')!=setting['coordinate_include_sha256']:raise SystemExit('v2 ledger binding mismatch '+aid)
  if finishes[0].get('engine_exit_code')!=engine or finishes[0].get('engine_exit_record_sha256')!=digest(exits[0]):raise SystemExit('v2 engine/ledger mismatch '+aid)
  proc='verified_success' if engine==0 else 'verified_failure'
  if n['valid']:
   if meta.get('geometry_sha256')!=digest(d/(aid+'.xyz')):raise SystemExit('attempt frozen-XYZ hash mismatch '+aid)
   ix=int(meta['frame_index']); expected=[type_map[int(z)] for z in pool['type_ids_0based']]
   xyz=d/(aid+'.xyz'); coords=np.array([[float(z) for z in l.split()[1:4]] for l in xyz.read_text().splitlines()[2:]])
   if not np.allclose(coords,pool['coords_A'][ix],atol=1e-8,rtol=0) or n['elements']!=expected:raise SystemExit('v2 geometry/pool mapping mismatch '+aid)
  allrecords[aid]={**n,'frame_index':meta.get('frame_index'),'category':meta.get('category'),'process':proc,'engine':engine,'setting':setting}
  ledger.append({'attempt_id':aid,'population':'later_v2','frame_index':meta.get('frame_index'),'category':meta.get('category'),'native_status':'native_valid' if n['valid'] else 'native_failed_or_unusable','engine_status':'exit_0' if engine==0 else 'nonzero_exit' if engine is not None else 'no_exit_record','process_status':proc,'workflow_scheduler_status':scheduler_by_attempt.get(aid,{'state':'not_recorded_in_terminal_projection'}),'engine_exit_present':bool(exits),'geometry_hash':n.get('geometry_hash'),'setting':setting,'reason':n.get('reason')})
 pairs=[]
 for left,right in [('D1','L01'),('D1','R01'),('B01','S01')]:
  keys=('method','xc_functional','dispersion','dispersion_reference','cutoff_Ry','rel_cutoff_Ry','eps_scf','max_scf','cell_vectors_A','periodic')
  different=any(allrecords[left]['setting'][k]!=allrecords[right]['setting'][k] for k in keys)
  p=pair(allrecords[left],allrecords[right]);native_valid=allrecords[left]['valid'] and allrecords[right]['valid'];process_verified=native_valid and allrecords[left]['process']=='verified_success' and allrecords[right]['process']=='verified_success'
  pair_geometry_hashes=sorted({allrecords[left]['geometry_hash'],allrecords[right]['geometry_hash']})
  pairs.append({'left':left,'right':right,'left_setting':allrecords[left]['setting'],'right_setting':allrecords[right]['setting'],'settings_differ':different,'valid':native_valid,'process_verified':process_verified,'left_native_status':'native_valid' if allrecords[left]['valid'] else 'native_failed_or_unusable','right_native_status':'native_valid' if allrecords[right]['valid'] else 'native_failed_or_unusable','left_process_status':allrecords[left]['process'],'right_process_status':allrecords[right]['process'],'comparison_scope':'process_verified_native_pair' if process_verified else 'native_diagnostic_process_unverified','geometry_hashes':pair_geometry_hashes,'unique_geometry_count':len(pair_geometry_hashes),**p})
 ensemble=forces.mean(axis=0); frame_metrics={}; strata={}; chosen=selection['selected_20'];
 for r in chosen:
  aid=r['selection_id'];key=f"{r['temperature_K']}|{r['trajectory']}|{r['category']}";s=strata.setdefault(key,{'temperature_K':r['temperature_K'],'trajectory':r['trajectory'],'category':r['category'],'selected_n':0,'process_verified_n':0,'missing_status_n':0,'hits':0,'frames':[]});s['selected_n']+=1
  rec=allrecords[aid];ix=int(r['frame_index']);native_valid=bool(rec['valid']);process_verified=native_valid and rec['process']=='verified_success'
  per=[metric(rec['forces'],forces[m,ix]) for m in range(4)] if native_valid else None;ens=metric(rec['forces'],ensemble[ix]) if native_valid else None;hit=bool(ens and ens['force_component_rmse_eV_A']>=THRESHOLD)
  row={'attempt_id':aid,'selection_id':r['selection_id'],'frame_index':ix,'temperature_K':r['temperature_K'],'trajectory':r['trajectory'],'category':r['category'],'native_status':'native_valid' if native_valid else 'native_failed_or_unusable','process_status':rec['process'],'per_model':per,'ensemble':ens,'hit':hit,'counted_as_verified_hit':process_verified};s['frames'].append(row)
  if process_verified:s['process_verified_n']+=1;s['hits']+=int(hit);frame_metrics[aid]=row
  else:s['missing_status_n']+=1
 for s in strata.values():
  n=s['selected_n'];m=s['missing_status_n'];h=s['hits'];s['conditional_selected_set_hit_bounds']=[h/n,(h+m)/n];s['summary']=summarize_cell(s)
 # Preserve L01's numeric-only analysis while keeping its process status unknown.
 l01=allrecords['L01']; lrow=selected['L01']; lmet={'attempt_id':'L01','selection_id':lrow['selection_id'],'frame_index':focus_frame,'per_model':[metric(l01['forces'],forces[m,focus_frame]) for m in range(4)],'ensemble':metric(l01['forces'],ensemble[focus_frame]),'process_status':l01['process'],'counted_as_verified_hit':False}
 nvalid=len([x for x in allrecords.values() if x['process']=='verified_success' and x['valid']]); geometry_count=len({x['geometry_hash'] for x in allrecords.values() if x.get('geometry_hash')})
 posthoc_strata={};posthoc_frames={}
 for r in chosen:
  aid='D1' if r['selection_id']=='L01' else r['selection_id']; key=f"{r['temperature_K']}|{r['trajectory']}|{r['category']}"
  s=posthoc_strata.setdefault(key,{'temperature_K':r['temperature_K'],'trajectory':r['trajectory'],'category':r['category'],'selected_n':0,'process_verified_n':0,'missing_status_n':0,'hits':0,'frames':[]});s['selected_n']+=1
  rec=allrecords[aid]
  ix=int(r['frame_index']);native_valid=bool(rec['valid']);process_verified=native_valid and rec['process']=='verified_success'
  per=[metric(rec['forces'],forces[m,ix]) for m in range(4)] if native_valid else None;ens=metric(rec['forces'],ensemble[ix]) if native_valid else None;hit=bool(ens and ens['force_component_rmse_eV_A']>=THRESHOLD)
  row={'attempt_id':aid,'selection_id':r['selection_id'],'frame_index':ix,'temperature_K':r['temperature_K'],'trajectory':r['trajectory'],'category':r['category'],'native_status':'native_valid' if native_valid else 'native_failed_or_unusable','process_status':rec['process'],'per_model':per,'ensemble':ens,'hit':hit,'counted_as_verified_hit':process_verified};s['frames'].append(row)
  if process_verified:s['process_verified_n']+=1;s['hits']+=int(hit);posthoc_frames[aid]=row
 for s in posthoc_strata.values():
  n=s['selected_n'];s['missing_status_n']=n-s['process_verified_n'];s['conditional_selected_set_hit_bounds']=[s['hits']/n,(s['hits']+s['missing_status_n'])/n];s['summary']=summarize_cell(s,True)
 random_means={};risk_means={}
 for key,cell in strata.items():
  trajectory=cell['trajectory']; pair_key=(cell['temperature_K'],trajectory)
  (risk_means if cell['category']=='risk' else random_means)[pair_key]=cell['summary']['ensemble_mean_rmse_eV_A']
 random_risk=[{'population':'original_intent','temperature_K':temp,'trajectory':traj,'random_mean_rmse_eV_A':random_means[(temp,traj)],'risk_mean_rmse_eV_A':risk_means[(temp,traj)],'risk_minus_random_eV_A':risk_means[(temp,traj)]-random_means[(temp,traj)]} for temp,traj in sorted(set(random_means)&set(risk_means))]
 d1metrics=[metric(allrecords['D1']['forces'],forces[m,focus_frame]) for m in range(4)];r01metrics=[metric(allrecords['R01']['forces'],forces[m,focus_frame]) for m in range(4)]
 d1ensemble=metric(allrecords['D1']['forces'],ensemble[focus_frame]);r01ensemble=metric(allrecords['R01']['forces'],ensemble[focus_frame])
 d1ranked=sorted(((row['ensemble']['force_component_rmse_eV_A'],aid) for aid,row in posthoc_frames.items()),key=lambda z:(-z[0],z[1]))
 counterfactual=[(rmse,aid) for rmse,aid in d1ranked if aid!='D1']+[(r01ensemble['force_component_rmse_eV_A'],'D1/R01-counterfactual')]
 counterfactual.sort(key=lambda z:(-z[0],z[1]))
 risk_scores=[(x['risk_score_eV_A'],x['selection_id']) for x in chosen];risk_scores.sort(key=lambda z:(-z[0],z[1]))
 d1_rank=next(i+1 for i,x in enumerate(d1ranked) if x[1]=='D1');alt_rank=next(i+1 for i,x in enumerate(counterfactual) if x[1]=='D1/R01-counterfactual');risk_rank=next(i+1 for i,x in enumerate(risk_scores) if x[1]=='L01')
 alternative_sensitivity={'frame_index':focus_frame,'same_geometry':all(allrecords[a]['geometry_hash']==allrecords['D1']['geometry_hash'] for a in ('L01','R01','B01','S01')),'D1_model_metrics':d1metrics,'R01_model_metrics':r01metrics,'D1_ensemble':d1ensemble,'R01_ensemble':r01ensemble,'ensemble_rmse_change_eV_A':r01ensemble['force_component_rmse_eV_A']-d1ensemble['force_component_rmse_eV_A'],'hit_threshold_eV_A':THRESHOLD,'D1_hit':d1ensemble['force_component_rmse_eV_A']>=THRESHOLD,'R01_hit':r01ensemble['force_component_rmse_eV_A']>=THRESHOLD,'hit_flip':(d1ensemble['force_component_rmse_eV_A']>=THRESHOLD)!=(r01ensemble['force_component_rmse_eV_A']>=THRESHOLD),'selected_frame_error_rank_descending_D1':d1_rank,'selected_frame_error_rank_descending_R01_counterfactual':alt_rank,'frozen_model_disagreement_risk_score':selected['L01']['risk_score_eV_A'],'frozen_selection_risk_rank_descending':risk_rank,'frozen_selection_rank_changes_with_reference':False,'note':'Only the selected frame reference is changed; the frozen model-disagreement score and category are reference-independent.'}
 cross_rows=[p for p in pairs if p['valid'] and p['process_verified'] and p['settings_differ']]
 cross_setting_geometry_count=len({g for p in cross_rows for g in p['geometry_hashes']})
 decision=classify_decision(pairs,len(posthoc_frames),cross_setting_geometry_count)
 sensitive=any(not all(p['gates'].values()) for p in cross_rows)
 sufficient=(not sensitive and len(posthoc_frames)>=20 and cross_setting_geometry_count>=2 and len(cross_rows)>=2)
 overall='REFERENCE_ADEQUATE' if sufficient else 'INSUFFICIENT_EVIDENCE'
 original_missing=sum(s['missing_status_n'] for s in strata.values());original_selected=sum(s['selected_n'] for s in strata.values());original_verified=sum(s['process_verified_n'] for s in strata.values());original_hits=sum(s['hits'] for s in strata.values())
 v1_starts=[x for x in v1_events if x.get('event')=='START'];v1_finishes=[x for x in v1_events if x.get('event')=='FINISH'];v1_recoveries=[x for x in v1_events if x.get('event')=='RECOVERY']
 v2_starts=[x for x in v2_events if x.get('event')=='START'];v2_finishes=[x for x in v2_events if x.get('event')=='FINISH']
 operator_counts={event:sum(x.get('event')==event for x in op_events) for event in sorted({x.get('event') for x in op_events})}
 operator_charged_jobs={x.get('job_id') for x in op_events if x.get('job_id') and x.get('operator_slot_charged')==1}
 operator_unknown_charge_jobs={x.get('job_id') for x in op_events if x.get('job_id') and x.get('operator_slot_charged') is None and x.get('event') in {'SUBMISSION_ACCEPTED','POSTHOC_SUBMISSION_DISCOVERED'}}
 v1_nonzero=[x for x in v1_finishes if x.get('engine_exit_code') not in (None,0)]
 reason_items=[{'code':'cross_setting_pair_failure' if sensitive else 'no_cross_setting_pair_failure','evidence':[p['left']+'/'+p['right'] for p in cross_rows if not all(p['gates'].values())] if sensitive else [p['left']+'/'+p['right'] for p in cross_rows],'summary':'Parsed input settings and recomputed numerical gates determine the local comparison finding.'},
  {'code':'retrospective_selection','evidence':['L02-L20','D1'],'summary':'The selected comparison population is assembled retrospectively from the declared source evidence.'}]
 if cross_setting_geometry_count<2:reason_items.append({'code':'shared_or_limited_geometry','evidence':[p['left']+'/'+p['right'] for p in cross_rows],'summary':'Eligible cross-setting pairs do not span two distinct native geometries.'})
 if allrecords['L01']['process']=='unknown':reason_items.append({'code':'l01_process_status_unknown','evidence':['L01'],'summary':'One selected original-intent record lacks verified-success process status.'})
 sensitivity_pairs=[p['left']+'/'+p['right'] for p in cross_rows if not all(p['gates'].values())]
 plan1_codes=['cross_setting_sensitivity' if sensitivity_pairs else 'cross_setting_comparison']
 if cross_setting_geometry_count<2:plan1_codes.append('limited_geometry_support')
 plan1_evidence=sorted(set(sensitivity_pairs or [p['left']+'/'+p['right'] for p in cross_rows]))+['cross_setting_unique_geometry_count']
 plan2_codes=['stratum_coverage']
 if original_missing:plan2_codes.append('missing_label_uncertainty')
 evidence_plan=[
  {'rank':1,'gap_codes':plan1_codes,'action':f'Review parsed method sensitivity for the selected frame {focus_frame} and decide what additional geometry support would resolve the comparison.','gap':'Cross-setting evidence must be interpreted with its geometry coverage.','reason':'Use only pair metrics and parsed settings; repeated geometry does not add independent support.','stop':'Do not generalize or authorize new labels until method differences and acceptance criteria are reviewed.','budget_axis':'analysis_only','evidence_basis':plan1_evidence},
  {'rank':2,'gap_codes':plan2_codes,'action':'Inspect random/risk coverage and missing-label bounds in each temperature/trajectory cell.','gap':'The selected population may not represent the full pool.','reason':'Cell summaries and missingness bounds show where evidence is sparse or unknown.','stop':'Stop expansion if source identity or process status remains unresolved.','budget_axis':'existing_evidence_only','evidence_basis':['original_four_strata_category_metrics','posthoc_four_strata_category_metrics','missingness_bounds']},
  {'rank':3,'gap_codes':['budget_authorization_boundary'],'action':'If separately authorized, propose a prospectively frozen panel spanning the unresolved evidence gaps.','gap':'The original label-intent cap and later operator-attempt cap are separate accounting axes.','reason':'The current analysis does not authorize new calculations.','stop':'Do not submit work without separate authorization and a revised budget ledger.','budget_axis':'separate_authorization_required','evidence_basis':['original_28_intent_cap','later_54_operator_cap']}]
 limitation_items=[{'code':'retrospective_evidence','evidence':['original_population','retrospective_population']},
  {'code':'prediction_arrays_not_replayed','evidence':['inputs/pool/predictions.npz']},
  {'code':'no_pool_wide_accuracy_claim','evidence':['inputs/pool/selection.json']}]
 if len(chosen)<pool['coords_A'].shape[0]:limitation_items.append({'code':'selected_panel_smaller_than_pool','evidence':['inputs/pool/selection.json','inputs/pool/candidate-pool.npz']})
 if cross_setting_geometry_count<2:limitation_items.append({'code':'limited_cross_setting_geometry_support','evidence':['cross_setting_unique_geometry_count']})
 if original_missing:limitation_items.append({'code':'selected_process_status_incomplete','evidence':[x['attempt_id'] for x in ledger if x['population']=='original_v1' and x['attempt_id'] in selected and x['process_status']!='verified_success']})
 scope_claims={'prospective_compliance':False,'production_accuracy':False,'pool_wide_accuracy':False,'independent_sampling':False}
 audit={'schema':'case03-finite-evidence-audit/v1','input_integrity':{'verified_files':sum(hashes),'file_count':len(hashes),'all_verified':all(hashes)},'ledger_disclosure':'field_projection_not_full_source_ledger','ledger_disclosure_note':'The v1/v2 event streams are public field projections, not complete original ledgers; source hashes and projection mappings are in the public input manifest.','attempt_ledger':ledger,'attempt_count':len(ledger),'unique_native_geometry_count':geometry_count,'cross_setting_unique_geometry_count':cross_setting_geometry_count,
 'original_population':{'ids':[f'L{i:02d}' for i in range(1,21)],'process_verified_n':original_verified,'unknown_process_ids':[x['attempt_id'] for x in ledger if x['population']=='original_v1' and x['process_status']=='unknown'],'missingness_hit_bounds':[original_hits/original_selected,(original_hits+original_missing)/original_selected],'scope':'original process-status set; unverified selected labels remain in denominator'},
 'retrospective_population':{'ids':[f'L{i:02d}' for i in range(2,21)]+['D1'],'process_verified_n':len(posthoc_frames),'retrospective':True,'prospective_freeze_claim':False},'L01_numeric_only_metrics':lmet,'pair_comparisons':pairs,'alternative_label_sensitivity':alternative_sensitivity,'original_four_strata_category_metrics':strata,'posthoc_four_strata_category_metrics':posthoc_strata,'random_risk_within_stratum_comparison':random_risk,'frame_metrics_by_original_process_verified_attempt':frame_metrics,'frame_metrics_by_retrospective_attempt':posthoc_frames,
 'accounting':{'original_quantum_label_intent_cap':int(re.search(r'quantum_label_intents:\s*(\d+)',(c/'inputs/policy/original-compute-budget.yaml').read_text()).group(1)),'v1_quantum_starts':len({x.get('attempt_id') for x in v1_starts}),'v1_finish_events':len(v1_finishes),'v1_nonzero_engine_finish_events':len(v1_nonzero),'v1_recovery_events':len(v1_recoveries),'v1_recovery_wrapper_failure_events':sum(x.get('wrapper_exit_code') not in (None,0) for x in v1_recoveries),'v2_science_starts':len({x.get('attempt_id') for x in v2_starts}),'v2_finish_events':len(v2_finishes),'combined_science_starts':len({x.get('attempt_id') for x in v1_starts}|{x.get('attempt_id') for x in v2_starts}),'later_operator_budget_cap':int(re.search(r'ceiling was (\d+) cumulative attempts',(c/'inputs/policy/later-operator-budget-rule.md').read_text()).group(1)),'operator_event_counts':operator_counts,'operator_prestart_failure_events':operator_counts.get('SUBMISSION_TERMINAL_PRESTART_FAILURE',0),'operator_slot_charge_event_count':sum(x.get('operator_slot_charged')==1 for x in op_events),'operator_slot_charged_unique_jobs':len(operator_charged_jobs),'operator_slot_charge_unknown_unique_jobs':len(operator_unknown_charge_jobs),'operator_slot_charge_unique_job_bounds':[len(operator_charged_jobs),len(operator_charged_jobs)+len(operator_unknown_charge_jobs)],'operator_jobs_with_id':len({x.get('job_id') for x in op_events if x.get('job_id')}),'accounting_axes_separate':True,'prospective_compliance_claim':False},
 'decision':{'type':decision,'local_numerical_finding':'REFERENCE_SENSITIVE' if sensitive else 'NO_COUNTEREXAMPLE','overall_reference_sufficiency':overall,'reasons':reason_items},'scope_claims':scope_claims,
 'next_evidence_plan':evidence_plan,'limitations':limitation_items}
 out=a.out.resolve();out.mkdir(parents=True,exist_ok=True);(out/'audit.json').write_text(json.dumps(audit,indent=2,sort_keys=True,allow_nan=False)+'\n')
 priorities='\n'.join(f"{item['rank']}. {item['action']} (`{item['budget_axis']}`; evidence: {', '.join(item['evidence_basis'] )})" for item in evidence_plan)
 (out/'decision.md').write_text(f"# Decision\n\nLocal comparison: `{decision}`\n\nOverall reference sufficiency: `{overall}`\n\nDistinct native geometries in the audit records: `{geometry_count}`; eligible cross-setting pair endpoints cover `{cross_setting_geometry_count}` distinct geometries.\n\nThe label-sensitivity calculation uses frame {focus_frame} selected for L01. See `audit.json` for parsed settings, pair-level geometry overlap, per-frame and stratum calculations, missingness bounds, separate budget axes, and risk-ranking results.\n\n## Next evidence priorities\n\n{priorities}\n")
if __name__=='__main__':main()
PY_ANALYZE
