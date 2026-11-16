#!/usr/bin/env bash
set -euo pipefail
# Portable reference solve. Label queries must pass through the runner-owned
# oracle relay; this script cannot access private labels or sign AL attestations.
# CASE07_* names and case07-v2 schemas are the historical protocol of old
# case-07; the active package is case-06.
APP_ROOT=${CASE07_APP_ROOT:-/app}
INPUT="$APP_ROOT/inputs/v2"
OUT="$APP_ROOT/outputs"
PYTHON=${PYTHON:-python3}
START_SECONDS=$SECONDS

# Single-file reference implementations for the workflow stages.
assemble() {
  "$PYTHON" - "$@" <<'PY_ASSEMBLE'
#!/usr/bin/env python3
"""Assemble pool or revealed oracle frames without altering atom order/geometry."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();s=p.add_subparsers(dest='mode',required=True)
a=s.add_parser('pool');a.add_argument('--root',type=Path,required=True);a.add_argument('--manifest',type=Path,required=True);a.add_argument('--out',type=Path,required=True)
b=s.add_parser('training');b.add_argument('--files',nargs='+',type=Path,required=True);b.add_argument('--out',type=Path,required=True);b.add_argument('--allowed-ids',type=Path,required=True)
x=p.parse_args()
if x.mode=='pool':
 m=json.loads(x.manifest.read_text());chunks=[]
 for e in m['entries']:
  if e['phase']!='pool':continue
  f=(x.root/e['path']).resolve(strict=True)
  if not f.is_relative_to(x.root.resolve()) or hashlib.sha256(f.read_bytes()).hexdigest()!=e['geometry_sha256']:raise SystemExit('ERROR: public pool geometry hash/path mismatch')
  chunks.append(f.read_bytes())
 x.out.parent.mkdir(parents=True,exist_ok=True);x.out.write_bytes(b''.join(chunks));print(json.dumps({'frames':len(chunks),'sha256':hashlib.sha256(x.out.read_bytes()).hexdigest()}))
else:
 try:
  from ase.io import read,write
 except ImportError as e: raise SystemExit(f'ERROR: ASE unavailable: {e}')
 allow=set(x.allowed_ids.read_text().splitlines()); seen=set(); frames=[]
 for file in x.files:
  for i,atoms in enumerate(read(str(file),index=':',format='extxyz')):
   ident=atoms.info.get('queried_id',atoms.info.get('id'))
   if not ident or ident not in allow or ident in seen:raise SystemExit(f'ERROR: unapproved/duplicate training ID {ident}')
   if 'dft_energy' not in atoms.info or 'dft_forces' not in atoms.arrays:raise SystemExit('ERROR: frame lacks E/F labels')
   seen.add(ident);atoms.info['queried_id']=ident;frames.append(atoms)
 if seen!=allow:raise SystemExit(f'ERROR: missing authorized labels: {sorted(allow-seen)}')
 x.out.parent.mkdir(parents=True,exist_ok=True);write(str(x.out),frames,format='extxyz')
 print(json.dumps({'frames':len(frames),'ids':sorted(seen),'sha256':hashlib.sha256(x.out.read_bytes()).hexdigest()}))
PY_ASSEMBLE
}
fit_committee() {
#!/usr/bin/env bash
set -euo pipefail
TRAIN=${1:?usage: fit_committee.sh LABELLED.extxyz ROUND_DIR ROUND_INDEX SEED_ONLY_REFERENCE.extxyz CUMULATIVE_IDS}
ROUND_DIR=${2:?}
ROUND=${3:?must be 0, 1, or 2}
REFERENCE=${4:?seed-only reference extxyz is required}
TRAIN_IDS=${5:?cumulative training IDs are required}
QUERY=${CASE07_QUERY_CLIENT:-}
[[ -x "$QUERY" ]] || { echo 'ERROR: runner-authorized CASE07_QUERY_CLIENT fit relay is required' >&2; exit 2; }
[[ -f "$TRAIN" && -f "$REFERENCE" && -f "$TRAIN_IDS" ]] || { echo 'ERROR: training, reference, and ID inputs must exist' >&2; exit 2; }
PYTHON=${PYTHON:-python3}
[[ "$ROUND" =~ ^[012]$ ]] || { echo 'ERROR: round must be 0,1,2' >&2; exit 2; }
mkdir -p "$ROUND_DIR"
train_sha=$(shasum -a 256 "$TRAIN" | awk '{print $1}')
for member in 1 2 3; do
  seed=$((7000 + ROUND * 100 + member * 17))
  "$QUERY" fit-member --training-data "$TRAIN" --training-ids "$TRAIN_IDS" --reference-data "$REFERENCE" --output-dir "$ROUND_DIR/member-$member" --round "$ROUND" --member "$member" --seed "$seed"
 done
"$PYTHON" - "$ROUND_DIR" "$ROUND" "$TRAIN" "$train_sha" <<'PY_FIT_MANIFEST'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]);rnd=int(sys.argv[2]);training=Path(sys.argv[3]);training_sha=sys.argv[4]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
members=[]
for i in range(1,4):
 d=root/f'member-{i}'; m=json.loads((d/'manifest.json').read_text())
 for name in ('potential.yaml','potential.yace'):
  if sha(d/name)!=m['native_yaml_sha256' if name.endswith('.yaml') else 'yace_sha256']:
   raise SystemExit(f'ERROR: model hash mismatch: {d/name}')
 if m['training_sha256']!=training_sha: raise SystemExit('ERROR: member train set hash mismatch')
 members.append({'member_id':f'r{rnd}-m{i}','seed':m['seed'],'model_yaml':f'member-{i}/potential.yaml','model_yace':f'member-{i}/potential.yace','model_sha256':m['yace_sha256'],'backend_manifest_sha256':sha(d/'manifest.json'),'training_sha256':training_sha,'timing':m['timing']})
if len({x['model_sha256'] for x in members})!=3: raise SystemExit('ERROR: committee models are not byte-distinct')
(root/'committee.json').write_text(json.dumps({'schema':'case07-v2-committee/v1','round':rnd,'trainer':'ICAMS/python-ace PACEMAKER/PyACE','training_path':str(training.resolve()),'training_sha256':training_sha,'members':members},indent=2)+'\n')
PY_FIT_MANIFEST

}
rank_candidates() {
  "$PYTHON" - "$@" <<'PY_RANK_CANDIDATES'
#!/usr/bin/env python3
"""Rank public Case07 geometries by the frozen three-model force disagreement."""
from __future__ import annotations
import argparse,hashlib,json,math,os,subprocess,sys,tempfile
from pathlib import Path
import numpy as np
from ase.io import read,write

FORBIDDEN=('dft_energy','dft_forces','dft_free_energy','charge_bader','charge_ddec3','charge_ddec6','dft_stress','dft_virials')
def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def read_json(path:Path):return json.loads(path.read_text())
def force_disagreement(forces):
    """Frozen v2 score: sqrt of mean sample variance over force components."""
    stack=np.stack(forces)
    if stack.ndim!=3 or stack.shape[0]<2 or not np.isfinite(stack).all():raise ValueError('committee force array must be finite [members,atoms,3]')
    return float(np.sqrt(np.mean(np.var(stack,axis=0,ddof=1))))

def pairwise_force_disagreement(forces):
    """Independent sample-variance identity over all member pairs."""
    stack=np.stack(forces);n=stack.shape[0]
    if n<2 or not np.isfinite(stack).all():raise ValueError('committee force array must contain finite members')
    pair_sum=np.zeros(stack.shape[1:],dtype=float)
    for i in range(n):
        for j in range(i+1,n):pair_sum+=(stack[i]-stack[j])**2
    return float(np.sqrt(np.mean(pair_sum/(n*(n-1)))))

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('input_root',type=Path);p.add_argument('pool',type=Path);p.add_argument('committee',type=Path);p.add_argument('output',type=Path);p.add_argument('queried_ids',type=Path)
 p.add_argument('--diagnostic-limit-per-domain',type=int,default=0,help='author-only bounded prediction slice; creates incomplete ranking that trusted oracle will reject')
 p.add_argument('--diagnostic-unbound-models',action='store_true',help='author-only historical model evaluation; skips candidate-fit lineage binding and can never be used by solve.sh')
 a=p.parse_args();root=a.input_root.resolve(strict=True);pool=a.pool.resolve(strict=True);committee_path=a.committee.resolve(strict=True);out=a.output.resolve();queried_path=a.queried_ids.resolve(strict=True)
 if a.diagnostic_limit_per_domain<0:raise SystemExit('ERROR: diagnostic limit must be nonnegative')
 if a.diagnostic_unbound_models and not a.diagnostic_limit_per_domain:raise SystemExit('ERROR: unbound historical models are permitted only with an explicit bounded diagnostic slice')
 manifest_path=root/'geometry-manifest.json';manifest=read_json(manifest_path)
 if manifest.get('schema')!='case07-v2-public-geometry-manifest/v1' or manifest.get('geometry_count')!=132:raise SystemExit('ERROR: unsupported frozen public geometry manifest')
 entries=manifest.get('entries',[]);byid={e.get('id'):e for e in entries}
 if len(byid)!=132 or len(entries)!=132:raise SystemExit('ERROR: public geometry manifest IDs are not unique')
 declared_pool={e['id']:e for e in entries if e.get('phase')=='pool'}
 if len(declared_pool)!=120:raise SystemExit('ERROR: frozen public pool must contain 120 frames')
 # Verify every public source byte and prohibit labels before accepting the assembled pool.
 for e in entries:
  src=(root/e['path']).resolve(strict=True)
  if not src.is_relative_to(root) or sha(src)!=e.get('geometry_sha256'):raise SystemExit('ERROR: public geometry source hash/path mismatch: '+str(e.get('id')))
  raw=src.read_text()
  if any(field in raw for field in FORBIDDEN):raise SystemExit('ERROR: private label field in public geometry: '+str(e.get('id')))
 frames=read(str(pool),index=':',format='extxyz')
 if len(frames)!=120:raise SystemExit(f'ERROR: assembled pool must have 120 frames, got {len(frames)}')
 actual_ids=[]
 for frame in frames:
  ident=frame.info.get('id');entry=declared_pool.get(ident)
  if entry is None or ident in actual_ids or frame.info.get('domain')!=entry.get('domain'):raise SystemExit('ERROR: pool ID/domain missing, duplicate, or outside frozen manifest')
  # Compare ordered geometry through the exact backend digest after validating the public file bytes.
  actual_ids.append(ident)
 if set(actual_ids)!=set(declared_pool):raise SystemExit('ERROR: assembled pool does not contain the complete frozen pool')
 queried=queried_path.read_text().splitlines()
 if not queried or len(queried)!=len(set(queried)):raise SystemExit('ERROR: queried ID ledger is empty or duplicated')
 if any(x not in byid for x in queried):raise SystemExit('ERROR: queried ID is outside the public geometry manifest')
 # Diagnostic mode reduces model evaluations only after the complete pool passed byte/identity checks.
 working_frames=frames
 if a.diagnostic_limit_per_domain:
  grouped={}
  for f in frames:grouped.setdefault(f.info['domain'],[]).append(f)
  working_frames=[]
  for domain in sorted(grouped):working_frames.extend(sorted(grouped[domain],key=lambda f:f.info['id'])[:a.diagnostic_limit_per_domain])
 stage=int(read_json(committee_path).get('round',-1));round_no=stage+1
 if stage not in (0,1):raise SystemExit('ERROR: a query may only be ranked from committee round 0 or 1')
 doc=read_json(committee_path);members=doc.get('members',[])
 if doc.get('schema')!='case07-v2-committee/v1' or len(members)!=3:
  raise SystemExit('ERROR: committee schema/member count invalid')
 if not a.diagnostic_unbound_models and doc.get('training_sha256')!=sha(Path(doc['training_path']).resolve(strict=True)):
  raise SystemExit('ERROR: candidate committee training binding invalid')
 models=[];model_hashes=[]
 for m in members:
  model=(committee_path.parent/m['model_yace']).resolve(strict=True)
  if not model.is_relative_to(committee_path.parent.resolve()) or sha(model)!=m.get('model_sha256'):raise SystemExit('ERROR: committee YACE path/hash mismatch')
  if not a.diagnostic_unbound_models and m.get('training_sha256')!=doc.get('training_sha256'):raise SystemExit('ERROR: committee member training hash mismatch')
  models.append((m,model));model_hashes.append(sha(model))
 if len(set(model_hashes))!=3:raise SystemExit('ERROR: committee members must be byte-distinct')
 predictions=[]
 query=os.environ.get('CASE07_QUERY_CLIENT','')
 if a.diagnostic_limit_per_domain or a.diagnostic_unbound_models:raise SystemExit('ERROR: diagnostic-only rankings cannot run in the official solve')
 if not query:raise SystemExit('ERROR: trusted prediction relay is unavailable')
 official_rpc=True
 if official_rpc:
  app=Path(os.environ.get('CASE07_APP_ROOT','/app')).resolve(strict=True)
  try:
   pool_rel=pool.relative_to(app).as_posix()
  except ValueError as exc:
   raise SystemExit('ERROR: RPC ranking pool must remain inside the mounted APP') from exc
  if pool_rel!='outputs/pool/candidate-pool.extxyz':
   raise SystemExit('ERROR: RPC ranking requires the canonical complete public pool path')
  if not os.access(query,os.X_OK):raise SystemExit('ERROR: runner-authorized CASE07_QUERY_CLIENT is not executable')
  python=os.environ.get('PYTHON',sys.executable)
  for i,(member,model) in enumerate(models):
   try:model_rel=model.relative_to(app).as_posix()
   except ValueError as exc:raise SystemExit('ERROR: committee model is outside APP') from exc
   target=app/f'outputs/predictions/round-{stage}/member-{i+1}.json'
   target.parent.mkdir(parents=True,exist_ok=True)
   target_rel=target.relative_to(app).as_posix()
   proc=subprocess.run([query,'predict','--model',model_rel,'--structures',pool_rel,'--output',target_rel],
       stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=3600,env=os.environ.copy())
   if proc.returncode or not target.is_file():raise SystemExit('ERROR: trusted RPC prediction failed: '+proc.stderr[-1200:])
   pred=read_json(target)
   if (pred.get('model_sha256')!=model_hashes[i] or pred.get('structures_sha256')!=sha(pool)
       or pred.get('frame_count')!=len(working_frames) or pred.get('model_path')!=model_rel
       or pred.get('structures_path')!=pool_rel):raise SystemExit('ERROR: RPC prediction output identity/hash/count mismatch')
   predictions.append(pred)
 rows=[]
 for i,frame in enumerate(working_frames):
  ident=frame.info['id'];forces=[np.asarray(d['predictions'][i]['forces_eV_per_angstrom'],float) for d in predictions]
  geometry=[d['predictions'][i]['geometry_sha256'] for d in predictions];counts=[d['predictions'][i]['atom_count'] for d in predictions]
  if len(set(geometry))!=1 or len(set(counts))!=1 or counts[0]!=len(frame) or any(f.shape!=(len(frame),3) or not np.isfinite(f).all() for f in forces):raise SystemExit('ERROR: native model force geometry/order mismatch')
  # Match verify_v2.py and oracle_client.py exactly: sqrt(mean(sample variance)) over force components.
  score=force_disagreement(forces)
  pairwise=pairwise_force_disagreement(forces)
  if not math.isclose(score,pairwise,rel_tol=1e-12,abs_tol=1e-14):raise SystemExit('ERROR: pairwise sample-variance identity failed')
  if not math.isfinite(score):raise SystemExit('ERROR: non-finite committee disagreement')
  rows.append({'id':ident,'domain':frame.info['domain'],'geometry_sha256':declared_pool[ident]['geometry_sha256'],'force_disagreement_eV_per_A':score,'eligible_for_selection':ident not in set(queried)})
 rows.sort(key=lambda x:(x['domain'],-x['force_disagreement_eV_per_A'],x['id']))
 domain_rank=0;prior_domain=None
 for row in rows:
  if row['domain']!=prior_domain:prior_domain=row['domain'];domain_rank=0
  domain_rank+=1;row['rank_within_domain']=domain_rank
 selected=[]
 for domain in sorted({x['domain'] for x in rows}):
  eligible=[x for x in rows if x['domain']==domain and x['eligible_for_selection']]
  if not eligible:raise SystemExit(f'ERROR: no unqueried structures remain in {domain}')
  selected.append(eligible[0])
 result={'schema':'case07-v2-selection/v1','round':round_no,'pool_sha256':sha(pool),'committee_sha256':sha(committee_path),'model_sha256':model_hashes,'ranked':rows,'selected':selected}
 if a.diagnostic_unbound_models:result['diagnostic_only']='historical model ranking; no candidate fit-lineage assertion; intentionally incomplete pool score cannot be attested'
 request={'phase':f'round-{round_no}','ids':[x['id'] for x in selected]}
 out.parent.mkdir(parents=True,exist_ok=True);tmp=out.with_suffix(out.suffix+'.tmp');tmp.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');os.replace(tmp,out)
 req=out.with_suffix('.request.json');tmp=req.with_suffix(req.suffix+'.tmp');tmp.write_text(json.dumps(request,indent=2)+'\n');os.replace(tmp,req)
 print(json.dumps({'status':'RANKED','round':round_no,'candidate_count':len(rows),'selected_ids':request['ids'],'selection_sha256':sha(out),'request_sha256':sha(req)}))
if __name__=='__main__':main()
PY_RANK_CANDIDATES
}
update_ids() {
  "$PYTHON" - "$@" <<'PY_UPDATE_IDS'
#!/usr/bin/env python3
"""Append only the six newly authorized round IDs to cumulative training IDs."""
import json,os,sys,tempfile
from pathlib import Path
DOMAINS={'amorphous','amorphous_silicon','crystalline','high_pressure','mixed','surfaces'}
if len(sys.argv)!=4:raise SystemExit('usage: update_ids.py OUTPUT_IDS PREVIOUS_IDS ROUND_REQUEST.json')
out,previous,request=map(Path,sys.argv[1:]);prev=previous.read_text().splitlines();doc=json.loads(request.read_text());phase=doc.get('phase')
if phase not in ('round-1','round-2'):raise SystemExit('ERROR: query phase must be round-1 or round-2')
expected_prior=12 if phase=='round-1' else 18
if len(prev)!=expected_prior or len(prev)!=len(set(prev)):raise SystemExit(f'ERROR: previous ID list must contain {expected_prior} unique IDs')
new=doc.get('ids')
if not isinstance(new,list) or len(new)!=6 or any(not isinstance(x,str) for x in new):raise SystemExit('ERROR: each active-learning round must add six IDs')
if len(set(new))!=6 or set(new)&set(prev):raise SystemExit('ERROR: new IDs are duplicated or were already queried')
try:domains=[next(d for d in DOMAINS if x.startswith(d+'-pool-')) for x in new]
except StopIteration:raise SystemExit('ERROR: query IDs must be public candidate-pool IDs')
if set(domains)!=DOMAINS:raise SystemExit('ERROR: round must query exactly one candidate per domain')
if out.resolve()==previous.resolve():raise SystemExit('ERROR: cumulative IDs must not overwrite the previous frozen list')
out.parent.mkdir(parents=True,exist_ok=True)
with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=out.parent,prefix=out.name+'.',delete=False) as f:
 f.write('\n'.join(prev+new)+'\n');tmp=Path(f.name)
os.replace(tmp,out)
print(json.dumps({'status':'IDS_UPDATED','phase':phase,'prior_count':len(prev),'added_count':len(new),'total_count':len(prev)+len(new)}))
PY_UPDATE_IDS
}
finalize() {
  "$PYTHON" - "$@" <<'PY_FINALIZE'
#!/usr/bin/env python3
"""Freeze candidate-stage artifacts; independent grader verifies every hash."""
import datetime,hashlib,json,sys
from pathlib import Path
case=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
input_root=case/'inputs/v2'
if not input_root.is_dir(): input_root=case/'environment/assets/v2'
manifest_path=input_root/'geometry-manifest.json'
manifest=json.loads(manifest_path.read_text())
receipts=[json.loads(x) for x in (out/'oracle-query-receipts.jsonl').read_text().splitlines() if x.strip()]
expected=[('seed',12),('round-1',6),('round-2',6)]
if [(r.get('phase'),r.get('count')) for r in receipts]!=expected:raise SystemExit('ERROR: query receipts are missing, reordered, or wrong budget')
budget_path=out/'active-budget-receipt.json'
if not budget_path.is_file():raise SystemExit('ERROR: trusted active-budget receipt is missing')
budget=json.loads(budget_path.read_text())
if budget.get('schema')!='case07-v2-active-budget-receipt/v1' or type(budget.get('cumulative_active_seconds')) is not int or not 0<=budget['cumulative_active_seconds']<=43200:
 raise SystemExit('ERROR: trusted active-budget receipt has invalid schema/runtime')
if budget.get('budget_scope')=='independent-evaluation/v1' and (not budget.get('attempt_id') or not budget.get('private_history_sha256')):
 raise SystemExit('ERROR: independent-evaluation receipt lacks its protected attempt/history binding')
budget_sha=sha(budget_path)
models=[]
for rnd in range(3):
 cp=out/f'models/round-{rnd}/committee.json'
 d=json.loads(cp.read_text())
 if d.get('round')!=rnd or len(d.get('members',[]))!=3:raise SystemExit(f'ERROR: round {rnd} committee incomplete')
 models.append({'path':str(cp.relative_to(out)),'sha256':sha(cp),'member_sha256':[m['model_sha256'] for m in d['members']]})
stop={'schema':'case07-v2-stop-decision/v1','reason':'completed two fixed active-learning rounds; candidate-side completion claim subject to independent replay',
 'rounds_completed':2,'query_counts':{'seed':12,'round-1':6,'round-2':6,'total':24,'new_dft_attempts':0},
 'oracle_receipt_sha256':[r['receipt_sha256'] for r in receipts], 'frozen_committees':models,
 'active_elapsed_seconds':budget['cumulative_active_seconds'],'active_budget_receipt_sha256':budget_sha,
 'decision_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}
if budget.get('budget_scope')=='independent-evaluation/v1':
 stop.update({'budget_scope':budget['budget_scope'],'attempt_id':budget['attempt_id']})
(out/'stop_decision.json').write_text(json.dumps(stop,indent=2)+'\n')
provenance={'schema':'case07-v2-provenance/v1','case_id':'case-06','legacy_case_id':'case-07','protocol':'case07-v2',
 'public_geometry_manifest_sha256':sha(manifest_path),
 'source_dataset_sha256':manifest['source_dataset_sha256'],'trainer':'ICAMS/python-ace PACEMAKER + PyACE',
 'members_per_stage':3,'stages':[0,1,2],'oracle_receipt_sha256':[r['receipt_sha256'] for r in receipts],
 'active_budget_receipt_sha256':budget_sha,
 'units':{'energy':'eV; assigned from published extxyz/VASP context (not embedded per frame)','force':'eV/angstrom; assigned from published extxyz/VASP context (not embedded per frame)'},
 'new_dft_attempts':0,'query_count':24,'family_independence':'UNKNOWN_NOT_ASSESSED',
 'l3_threshold_status':'NOT_PREREGISTERED','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}
if budget.get('budget_scope')=='independent-evaluation/v1':
 provenance.update({'budget_scope':budget['budget_scope'],'attempt_id':budget['attempt_id']})
(out/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
print(json.dumps({'status':'CANDIDATE_PHASES_FROZEN','stop_decision_sha256':sha(out/'stop_decision.json'),'provenance_sha256':sha(out/'provenance.json')}))
PY_FINALIZE
}

check_active_budget() {
  if (( SECONDS - START_SECONDS >= 43200 )); then
    echo 'ERROR: case06 active runtime exceeded the hard 12-hour limit' >&2
    exit 2
  fi
}
QUERY=${CASE07_QUERY_CLIENT:-}
[[ -x "$QUERY" ]] || { echo 'ERROR: runner-authorized CASE07_QUERY_CLIENT relay is not available' >&2; exit 2; }
# Fail closed before creating outputs, starting the active clock, or releasing seed labels.
"$QUERY" --help >/dev/null || { echo 'ERROR: CASE07_QUERY_CLIENT is not a usable trusted relay' >&2; exit 2; }
"$QUERY" fit-member --help >/dev/null || { echo 'ERROR: trusted query relay lacks the protected fit-member interface' >&2; exit 2; }
"$QUERY" attest-selection --help >/dev/null || { echo 'ERROR: trusted query relay lacks selection attestation' >&2; exit 2; }
"$QUERY" query --help >/dev/null || { echo 'ERROR: trusted query relay lacks the private-label query interface' >&2; exit 2; }
"$QUERY" budget-check --help >/dev/null || { echo 'ERROR: trusted query relay lacks cumulative active-budget accounting' >&2; exit 2; }
MANIFEST="$INPUT/geometry-manifest.json"
[[ -r "$MANIFEST" ]] || { echo 'ERROR: canonical public v2 geometry manifest is missing or unreadable' >&2; exit 2; }
mkdir -p "$OUT/labels" "$OUT/training" "$OUT/models" "$OUT/selections" "$OUT/pool"
# Validate the fixed public seed request before the trusted relay opens a run.
"$PYTHON" - "$MANIFEST" "$OUT/seed-request.json" <<'PY'
import json,sys
from pathlib import Path
m=json.loads(Path(sys.argv[1]).read_text())
entries=m.get('entries')
if not isinstance(entries,list): raise SystemExit('ERROR: geometry manifest has no entries list')
ids=[x['id'] for x in entries if isinstance(x,dict) and x.get('phase')=='seed']
if len(ids)!=12 or len(set(ids))!=12 or len({x.rsplit('-seed-',1)[0] for x in ids})!=6:
    raise SystemExit('ERROR: canonical seed manifest must bind 12 unique IDs across six domains')
Path(sys.argv[2]).write_text(json.dumps({'phase':'seed','ids':ids},indent=2)+'\n')
PY
"$PYTHON" - "$OUT/seed-request.json" "$OUT/training/round-0.ids" <<'PY'
import json,sys
open(sys.argv[2],'w').write('\n'.join(json.load(open(sys.argv[1]))['ids'])+'\n')
PY
# Start the trusted budget/ledger run only after all static public inputs validate.
"$QUERY" begin-run
date +%s > "$OUT/active-start-epoch.txt"
"$QUERY" query --request "$OUT/seed-request.json" --output "$OUT/labels/seed.extxyz" | tee -a "$OUT/oracle-query-receipts.jsonl"
check_active_budget
assemble training --files "$OUT/labels/seed.extxyz" --out "$OUT/training/round-0.extxyz" --allowed-ids "$OUT/training/round-0.ids"
cp "$OUT/training/round-0.extxyz" "$OUT/training/seed-only-reference.extxyz"
fit_committee "$OUT/training/round-0.extxyz" "$OUT/models/round-0" 0 "$OUT/training/seed-only-reference.extxyz" "$OUT/training/round-0.ids"
check_active_budget
assemble pool --root "$INPUT" --manifest "$MANIFEST" --out "$OUT/pool/candidate-pool.extxyz"
for round in 1 2; do
  prev=$((round-1)); selection="$OUT/selections/round-$round.json"
  rank_candidates "$INPUT" "$OUT/pool/candidate-pool.extxyz" "$OUT/models/round-$prev/committee.json" "$selection" "$OUT/training/round-$prev.ids"
  # Only a trusted runner can validate/replay predictions and pin this attestation.
  "$QUERY" attest-selection --round "$round" --selection "$selection" --committee "$OUT/models/round-$prev/committee.json" --training-data "$OUT/training/round-$prev.extxyz" --training-ids "$OUT/training/round-$prev.ids" --pool "$OUT/pool/candidate-pool.extxyz"
  check_active_budget
  "$QUERY" query --request "$OUT/selections/round-$round.request.json" --output "$OUT/labels/round-$round.extxyz" | tee -a "$OUT/oracle-query-receipts.jsonl"
  check_active_budget
  cat "$OUT/training/round-$prev.extxyz" "$OUT/labels/round-$round.extxyz" > "$OUT/training/combined.tmp.extxyz"
  mv "$OUT/training/combined.tmp.extxyz" "$OUT/training/round-$round.extxyz"
  update_ids "$OUT/training/round-$round.ids" "$OUT/training/round-$prev.ids" "$OUT/selections/round-$round.request.json"
  fit_committee "$OUT/training/round-$round.extxyz" "$OUT/models/round-$round" "$round" "$OUT/training/seed-only-reference.extxyz" "$OUT/training/round-$round.ids"
  check_active_budget
done
"$QUERY" budget-check --limit-active-seconds 43200 --receipt-out "$OUT/active-budget-receipt.json"
finalize "$APP_ROOT" "$OUT"
echo CASE07_V2_REFERENCE_SOLUTION_COMPLETE
