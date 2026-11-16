#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the controller seal and completeness of the native run evidence.
# L3 Science: Diagnose silicon transport convergence.
"""Independent verifier for candidate output and root-exported evidence namespaces."""
import hashlib, json, math, os, sys
from pathlib import Path

APP=Path(os.environ.get('APP','/app')); LOGS=Path(os.environ.get('LOGS','/logs/verifier'))
TESTS=Path(os.environ.get('TESTS','/tests'))

def fail(message, status='ENVIRONMENT_ERROR_NO_REWARD'):
 LOGS.mkdir(parents=True,exist_ok=True)
 (LOGS/'reward.txt').unlink(missing_ok=True); (LOGS/'verification.json').unlink(missing_ok=True)
 doc={'schema':'case61-harbor-verdict/v1','status':status,'reason':message}
 (LOGS/'verification.json').write_text(json.dumps(doc,sort_keys=True,indent=2)+'\n')
 if status=='ENVIRONMENT_ERROR_NO_REWARD': return 2
 (LOGS/'reward.txt').write_text('0\n'); return 1

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()

def canonical_sha(value):
 data=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
 return hashlib.sha256(data).hexdigest()

def tree_manifest(root,prefix):
 result={}
 if root.is_symlink(): raise ValueError(f'{root} is a symlink')
 if not root.exists(): return result
 if not root.is_dir(): raise ValueError(f'{root} is not a directory')
 for path in sorted(root.rglob('*')):
  if path.is_symlink(): raise ValueError(f'symlink in {root}: {path}')
  if path.is_file():
   result[f'{prefix}/{path.relative_to(root).as_posix()}']={'bytes':path.stat().st_size,'sha256':sha(path)}
 return result

def _finite_number(value):
 if isinstance(value,bool) or type(value) not in (int,float): return None
 try: number=float(value)
 except (OverflowError,ValueError): return None
 return number if math.isfinite(number) else None

def _verify_evidence_packet(evidence,manifest):
 required={'evidence/followup-plan.json','evidence/transport.json','evidence/convergence.json'}
 if not required.issubset(manifest): raise ValueError('complete evidence packet lacks plan, transport, or convergence view')
 plan=json.loads((evidence/'followup-plan.json').read_text())
 if plan.get('schema')!='case06-v2-followup-plan/v1' or plan.get('selected_axis') not in {'coupled_fit_mesh','effective_window'}:
  raise ValueError('root-exported accepted follow-up plan is malformed')
 expected_runs={'mesh-1','mesh-2','mesh-3','window-2','followup-5','private-control'}
 if plan['selected_axis']=='coupled_fit_mesh': expected_runs.add('window-match-3')
 convergence=json.loads((evidence/'convergence.json').read_text())
 if (convergence.get('schema')!='case06-v2-convergence/v1' or
     not {'diagnosis_outcome','latest_comparisons','private_control_pair'}.issubset(convergence)):
  raise ValueError('root-exported convergence index is malformed')
 latest=convergence['latest_comparisons']
 if set(latest)!={'coupled_fit_mesh','effective_window'}:
  raise ValueError('root-exported convergence index lacks an axis')
 for axis,claim in latest.items():
  if not isinstance(claim,dict) or not isinstance(claim.get('parent_pair'),list) or len(claim['parent_pair'])!=2:
   raise ValueError(f'root-exported {axis} comparison lacks an ordered pair')
 if convergence.get('private_control_pair')!=['window-match-3' if 'window-match-3' in expected_runs else 'followup-5','private-control']:
  raise ValueError('root-exported private comparison pair is inconsistent with the accepted plan')
 transport=json.loads((evidence/'transport.json').read_text())
 if transport.get('schema')!='case06-rebuilt-transports/v1' or set(transport)!={'schema','runs','source_rebuild_sha256'}:
  raise ValueError('root-exported transport view schema is malformed')
 if set(transport['runs'])!=expected_runs or set(transport['source_rebuild_sha256'])!=expected_runs:
  raise ValueError('root-exported transport run coverage is incomplete')
 for run_id in sorted(expected_runs):
  run_path=evidence/'native'
  required_names={'execution.json','amset_settings.yaml','requested-settings.yaml','amset.log'}
  present={p.name for p in (run_path/run_id).iterdir() if p.is_file()}
  if not required_names.issubset(present): raise ValueError(f'native artifacts are incomplete for {run_id}')
  hdfs=list((run_path/run_id).glob('mesh_*.h5'))
  if len(hdfs)!=1: raise ValueError(f'native HDF count is invalid for {run_id}')
  for kind in ('native','rebuild'):
   supervisor=run_path/run_id/'supervisor'/kind/'type2-supervisor-status.json'
   if not supervisor.is_file() or supervisor.is_symlink():
    raise ValueError(f'{kind} supervisor evidence is missing for {run_id}')
  rebuild=evidence/'rebuild'/run_id/'trusted-rebuild.json'
  if rebuild.is_symlink() or not rebuild.is_file(): raise ValueError(f'trusted rebuild is missing for {run_id}')
  digest=transport['source_rebuild_sha256'].get(run_id)
  if not isinstance(digest,str) or digest.lower()!=sha(rebuild):
   raise ValueError(f'transport digest does not match unchanged rebuild bytes for {run_id}')
  doc=json.loads(rebuild.read_text()); values=doc.get('rebuild',{}).get('reconstructed_mobility_diagonals_cm2_per_Vs')
  channels=transport['runs'][run_id]
  if not isinstance(values,dict) or set(values)!={'overall','ADP','IMP'} or set(channels)!=set(values):
   raise ValueError(f'reconstructed transport channels are malformed for {run_id}')
  for channel in values:
   matrix=channels[channel]
   if (not isinstance(matrix,list) or len(matrix)!=6 or any(not isinstance(row,list) or len(row)!=1 or
       not isinstance(row[0],list) or len(row[0])!=3 for row in matrix)):
    raise ValueError(f'transport shape is not 6x1x3 for {run_id}/{channel}')
   for i in range(6):
    for j in range(3):
     actual=_finite_number(matrix[i][0][j]); expected=_finite_number(values[channel][i][0][j])
     if actual is None or expected is None or not math.isclose(actual,expected,rel_tol=1e-10,abs_tol=1e-14):
      raise ValueError(f'transport value differs from trusted rebuild for {run_id}/{channel}/{i}/{j}')

def main():
 LOGS.mkdir(parents=True,exist_ok=True)
 (LOGS/'reward.txt').unlink(missing_ok=True); (LOGS/'verification.json').unlink(missing_ok=True)
 refs=TESTS/'refs.json'; seal=APP/'controller-seal/receipt.json'
 try:
  r=json.loads(refs.read_text()); threshold=r['numeric_contract']['relative_change']['threshold']
  if r.get('case_id')!='case-06-scattering-convergence' or threshold!=0.02:
   return fail('invalid independent reference contract')
 except Exception: return fail('private reference file unavailable or invalid')
 if seal.is_symlink() or not seal.is_file(): return fail('trusted collect-stage controller seal is missing')
 try:
  doc=json.loads(seal.read_text())
  if doc.get('schema')!='case06-native-seal/v1': return fail('controller seal schema mismatch')
  candidate=doc.get('candidate_manifest'); evidence_manifest=doc.get('evidence_manifest')
  if (not isinstance(candidate,dict) or not isinstance(evidence_manifest,dict) or
      canonical_sha(candidate)!=doc.get('candidate_manifest_sha256') or
      canonical_sha(evidence_manifest)!=doc.get('evidence_manifest_sha256')):
   return fail('candidate/evidence namespace manifest digest mismatch')
  actual_candidate=tree_manifest(APP/'final','final')
  actual_evidence=tree_manifest(APP/'controller-seal/evidence','evidence')
  if actual_candidate!=candidate: return fail('candidate output namespace changed after collection')
  if actual_evidence!=evidence_manifest: return fail('root evidence namespace changed after collection')
  status=doc.get('status'); score=doc.get('reward'); phase=doc.get('phase')
  if status=='ENVIRONMENT_ERROR_NO_REWARD':
   return fail(doc.get('reason','trusted collect stage reported an environment error'))
  if phase!='FINALIZED':
   if status=='INCOMPLETE' and score==0.0: return fail(doc.get('reason','scientific session did not finalize'),'FAIL')
   if status=='FAIL' and score==0.0 and doc.get('evidence_status') in {'DIAGNOSTIC_ONLY','EMPTY'}:
    return fail(doc.get('reason','scientific work was incomplete'),'FAIL')
   return fail('non-finalized receipt has an inconsistent status or evidence state')
  if doc.get('evidence_status')!='AUTHENTICATED_COMPLETE':
   return fail('finalized session lacks an authenticated complete evidence packet')
  required={'final/report.json','final/private-control-response.json','final/report.md'}
  if not required.issubset(candidate): return fail('required candidate report outputs are missing','FAIL')
  _verify_evidence_packet(APP/'controller-seal/evidence',evidence_manifest)
  if status=='PASS' and score==1.0: pass
  elif status=='FAIL' and score==0.0: pass
  else: return fail('trusted collect-stage grade is missing or inconsistent')
  verdict={'schema':'case61-harbor-verdict/v1','status':status,'reward':score,
           'diagnosis_outcome':doc.get('diagnosis_outcome'),'reason':doc.get('reason'),
           'trusted_session_id':doc.get('session_id'),'facts_sha256':doc.get('facts_sha256'),
           'candidate_manifest_sha256':doc.get('candidate_manifest_sha256'),
           'evidence_manifest_sha256':doc.get('evidence_manifest_sha256')}
  (LOGS/'verification.json').write_text(json.dumps(verdict,sort_keys=True,indent=2)+'\n')
  (LOGS/'reward.txt').write_text(f'{score:g}\n'); print(json.dumps(verdict,sort_keys=True))
  return 0 if score>0 else 1
 except Exception as e: return fail('sealed evidence validation failed: '+type(e).__name__+': '+str(e))

if __name__=='__main__': raise SystemExit(main())
