#!/usr/bin/env bash
set -euo pipefail

mkdir -p /app/outputs /app/workspace
cat > /app/outputs/runtime-request.json <<'JSON'
{
  "schema": "case05-local-runtime-request/v1",
  "python_executable": "/opt/case05-runtime/bin/python",
  "resource_request": {
    "cpus": 2,
    "memory_gb": 8,
    "wall_seconds": 1200,
    "accelerator": "cpu",
    "gpu_count": 0
  }
}
JSON
chmod 0600 /app/outputs/runtime-request.json

cat > /app/workspace/case05_submit.py <<'PY'
import csv
import json
import os
from pathlib import Path
import secrets
import stat
import socket
import sys
import time

OUT = Path('/app/outputs')
INBOX = Path('/run/ccb-hpc')
attempt_env = os.environ.get('CCB_BENCH25_ATTEMPT_ID', '')
identity_path = Path('/run/bench25-capture/public-attempt.json')
fd = os.open(identity_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
with os.fdopen(fd, 'rb') as stream:
    before = os.fstat(stream.fileno())
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
            or before.st_mode & 0o222 or before.st_nlink != 1 or before.st_size > 4096):
        raise RuntimeError('root-published attempt identity is unsafe')
    identity_raw = stream.read(4097)
    after = os.fstat(stream.fileno())
if (len(identity_raw) != before.st_size or before.st_size > 4096
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
    raise RuntimeError('root-published attempt identity changed while being read')
identity = json.loads(identity_raw.decode('utf-8'))
attempt = identity.get('attempt_id') if set(identity) == {'schema', 'attempt_id', 'run_id'} and identity.get('schema') == 'bench25/public-attempt/v1' else ''
run_id = identity.get('run_id', '')
if (len(attempt) != 32 or any(ch not in '0123456789abcdef' for ch in attempt)
        or len(run_id) != 32 or any(ch not in '0123456789abcdef' for ch in run_id)
        or (attempt_env and attempt_env != attempt)):
    raise RuntimeError('root-published attempt identity is invalid or mismatched')

def rpc(operation):
    request_id = secrets.token_hex(16)
    request = {'schema':'case05-harbor-rpc-request/v1','request_id':request_id,
               'attempt_id':attempt,'operation':operation,'payload':{}}
    target = INBOX / (request_id + '.request.json')
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write((json.dumps(request,sort_keys=True,separators=(',',':'))+'\n').encode())
        stream.flush(); os.fsync(stream.fileno())
    response = INBOX / (request_id + '.response.json')
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        if response.exists():
            value=json.loads(response.read_text())
            if value.get('request_id')!=request_id or value.get('attempt_id')!=attempt:
                raise RuntimeError('typed response identity mismatch')
            if value.get('status')=='ENV2': raise RuntimeError('trusted local backend unavailable')
            return value['payload']
        time.sleep(.05)
    raise TimeoutError('typed host operation did not respond')

registered=rpc('register')
if registered.get('status')!='REGISTERED': raise RuntimeError('root did not preregister the A/B inputs')
submitted=rpc('submit')
if submitted.get('execution_backend')!='local': raise RuntimeError('unexpected execution backend')
deadline=time.monotonic()+1200
while time.monotonic()<deadline:
    state=rpc('status')
    if state.get('status')=='COMPLETED': break
    if state.get('status')=='ENV2': raise RuntimeError('local runtime execution is unavailable')
    time.sleep(1)
else: raise TimeoutError('root execution exceeded the requested wall budget')
collected=rpc('collect')
if collected.get('status')!='RAW_CAPTURE_READY': raise RuntimeError('root did not freeze native A/B outputs')

raw=OUT/'raw'
points={p:json.loads((raw/p/'result.json').read_text()) for p in ('A','B')}
with (OUT/'casscf_results.csv').open('w',newline='') as stream:
    writer=csv.writer(stream);writer.writerow(['point_id','state','energy_hartree','force_frobenius_norm_hartree_per_bohr','gap_to_lower_state_eV'])
    for point,result in points.items():
        for index,energy in enumerate(result['energy_hartree']):
            gap=0.0 if index==0 else (energy-result['energy_hartree'][index-1])*27.211386245988
            writer.writerow([point,f'S{index}',energy,result['force_norms_hartree_per_bohr'][index],gap])
with (OUT/'nacs.csv').open('w',newline='') as stream:
    writer=csv.writer(stream);writer.writerow(['point_id','coupling','nac01_frobenius_norm','unit'])
    for point,result in points.items():writer.writerow([point,'S1/S0',result['nac01_norm_per_bohr'],'1/Bohr'])

inventory=collected['files']
paths=[row['path'] for row in inventory]
for name in ('A','B'):
    required={f'raw/{name}/{file}' for file in ('run_point.py','geometry.xyz','program.log','program.err','result.json','exit-code.txt','input-hashes.txt','output-hashes.txt')}
    if not required.issubset(paths):raise RuntimeError('root capture omitted native evidence')
(OUT/'convergence_report.md').write_text(
    '# Convergence and native evidence\n\n'
    f"Program: PySCF {points['A']['version']} (version banner and result captured by the root runner).\n\n"
    'Both geometries report successful RHF, state-averaged CASSCF, gradient response, and NAC response. '
    'The active space is (2,2); three singlet roots use equal 1/3 weights and cc-pVDZ. '
    'The native logs contain the SCF/CASSCF iteration traces and convergence thresholds. '
    'The fixed driver selects active orbitals by the declared pi-projection rule and checks the final projection. '
    'No root-flip correction is inferred from a summary; consult each native log for the actual iteration details.\n\n'
    'Native files: '+', '.join(paths)+'\n')
summary={'program':f"PySCF {points['A']['version']}",'active_space':'(2,2)',
 'state_averaging':{'states':['S0','S1','S2'],'weights':[1/3,1/3,1/3]},
 'basis':'cc-pVDZ','converged':{'A':points['A']['converged'],'B':points['B']['converged']},
 'raw_outputs':paths,'caveats':['Two fixed geometries do not establish convergence reliability outside this execution.']}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
PY
chmod 0600 /app/workspace/case05_submit.py
exec ccb-capture -- /opt/case05-runtime/bin/python -I /app/workspace/case05_submit.py
