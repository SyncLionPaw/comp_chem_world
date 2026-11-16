#!/usr/bin/env python3
"""Exercise Gold reanalysis and fail-closed candidate evidence checks."""
from __future__ import annotations
import hashlib,json,os,shutil,subprocess,sys,tempfile
import datetime
from pathlib import Path
import execution_contract
TESTS=Path(__file__).resolve().parent
TASK=TESTS.parent
GOLD=Path(os.environ.get('APP','/private/tmp/bench15-case06-reanalysis-20261031'))
ASSETS=TASK/'environment/assets'
def sha(data): return hashlib.sha256(data).hexdigest()
def refresh(engine):
    rows=[]
    for p in sorted(engine.rglob('*')):
        if p.is_file() and p.name!='SHA256SUMS': rows.append(f'{sha(p.read_bytes())}  ./{p.relative_to(engine).as_posix()}\n')
    (engine/'SHA256SUMS').write_text(''.join(rows),encoding='ascii')
def invoke(root,logs):
    env=os.environ.copy();env.update({'APP':str(root),'CCB_PUBLIC_ASSETS':str(ASSETS),'LOGS':str(logs)})
    p=subprocess.run([sys.executable,str(TESTS/'verify.py')],env=env,text=True,capture_output=True)
    return p.returncode,json.loads((logs/'verification.json').read_text())
def attempt(label,mutator,reason):
    with tempfile.TemporaryDirectory(prefix='bench15-attack-') as tmp:
        root=Path(tmp);shutil.copytree(GOLD/'final',root/'final');mutator(root/'final')
        if (root/'final/engine_io').is_dir(): refresh(root/'final/engine_io')
        rc,result=invoke(root,root/'logs')
        if rc!=1 or result.get('status')!='FAIL' or result.get('reward')!=0: raise AssertionError(f'{label}: expected FAIL/reward 0, got {rc} {result}')
        if reason not in result.get('reason',''): raise AssertionError(f'{label}: expected {reason!r}, got {result.get("reason")!r}')
        print(f'PASS rejected {label}: {result["reason"]}')
def first(final,name): return next((final/'engine_io/runs').rglob(name))
def remove_receipt(final): first(final,'execution-receipt.json').unlink()
def nan_record(final):
    p=first(final,'scheduler_record.json');d=json.loads(p.read_text());d['walltime_limit_seconds']=float('nan');p.write_text(json.dumps(d))
def nonobject_record(final): first(final,'scheduler_record.json').write_text('null\n')
def wrong_job(final):
    p=final/'engine_io/run_manifest.json';d=json.loads(p.read_text());d['main'][0]['job_id']='99999999';p.write_text(json.dumps(d))
def wrong_script_hash(final):
    p=first(final,'execution-receipt.json');d=json.loads(p.read_text());d['batch_script_sha256']='0'*64;p.write_text(json.dumps(d))
def wrong_native_hash(final):
    p=first(final,'run.slurm');p.write_bytes(p.read_bytes()+b'\n# changed\n')
def wrong_science(final):
    p=final/'raman_modes.json';d=json.loads(p.read_text());d['branches']['A1g'][0]['frequency_cm-1']+=10;p.write_text(json.dumps(d))
def nan_science(final):
    p=final/'phonons.json';d=json.loads(p.read_text());d['points'][0]['PSTRESS_kbar']=float('nan');p.write_text(json.dumps(d))
def empty(final): shutil.rmtree(final)
if __name__=='__main__':
    t=datetime.datetime(2026,10,31,tzinfo=datetime.timezone.utc)
    execution_contract._check_nonoverlap([('a',t,t+datetime.timedelta(seconds=10)),('b',t+datetime.timedelta(seconds=10),t+datetime.timedelta(seconds=20))])
    print('PASS adjacent fresh allocations accepted')
    try: execution_contract._check_nonoverlap([('a',t,t+datetime.timedelta(seconds=11)),('b',t+datetime.timedelta(seconds=10),t+datetime.timedelta(seconds=20))])
    except execution_contract.EvidenceFail: print('PASS overlapping fresh allocations rejected')
    else: raise AssertionError('overlapping fresh allocations were accepted')
    logs=Path(tempfile.mkdtemp(prefix='bench15-gold-log-'))
    rc,result=invoke(GOLD,logs)
    expected={'execution_kind':'ARCHIVAL_NATIVE_REANALYSIS','fresh_execution':'NOT_RUN','job_ids':['3899378','3899465','3899500','3899529','3899591']}
    if rc!=0 or result.get('status')!='PASS' or result.get('execution_provenance')!=expected: raise SystemExit(f'Gold reanalysis failed: {result}')
    print('PASS Gold raw VASP reanalysis; fresh execution explicitly NOT_RUN')
    cases=[
      ('missing receipt',remove_receipt,'candidate execution evidence missing'),
      ('NaN scheduler JSON',nan_record,'malformed candidate execution JSON'),
      ('non-object scheduler JSON',nonobject_record,'malformed candidate execution JSON'),
      ('wrong job ID',wrong_job,'job_id contradicts the raw run'),
      ('wrong script hash',wrong_script_hash,'receipt/job/allocation/script identity mismatch'),
      ('wrong pinned native hash',wrong_native_hash,'submitted native evidence differs from trusted byte-pinned history'),
      ('wrong scientific value',wrong_science,'branch frequency does not equal raw'),
      ('NaN scientific value',nan_science,'cannot read valid JSON'),
      ('empty output',empty,'final/ is missing'),
    ]
    for label,mutator,reason in cases: attempt(label,mutator,reason)
