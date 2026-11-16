"""This bench's independent Slurm collection and evidence sealing.

Scientific policy and evidence wire format are preserved from the provided runner.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
import time
import uuid

POLICY = "case05-candidate-v5-8"

LIMIT = 10 * 1024**3

STAGES = {"prep", "meoh-md", "mecn-md", *(f"qm-{c}" for c in "ABCDE")}

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""): h.update(block)
    return h.hexdigest()

def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

def remote(script: str, args=(), *, transport, timeout=60, output=None):
    cmd = transport.command(["python3", "-", *map(str, args)])
    result = subprocess.run(cmd, input=script.encode(), stdout=output or subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        # Remote errors may describe public calculations; never record SSH command/identity.
        raise RuntimeError("host SSH operation failed: " + result.stderr.decode(errors="replace")[-2000:])
    return result.stdout

SITE_SCRIPT = r'''import json,os,subprocess
from pathlib import Path

def run(argv):
 p=subprocess.run(argv,capture_output=True,text=True,timeout=30)
 if p.returncode: raise RuntimeError(p.stderr)
 return p.stdout.strip()
user=run(['id','-un']); home=str(Path.home())
account=run(['sacctmgr','-n','-P','show','user',user,'format=DefaultAccount']).strip('|')
parts=run(['sinfo','-h','-o','%P|%a']).splitlines()
if 'cpu*|up' not in parts and 'cpu|up' not in parts: raise RuntimeError('CPU partition unavailable')
if not account or '\n' in account: raise RuntimeError('default account ambiguous')
print(json.dumps(dict(user=user,home=home,account=account,partition='cpu')))
'''

JOBS_SCRIPT = r'''import datetime,json,os,subprocess,sys,time
root,prefix,user,begin,end=sys.argv[1:]; begin=float(begin);end=float(end)
fields=['JobIDRaw','JobName%256','User','Account','Partition','State','ExitCode','AllocCPUS','NNodes','ReqMem','Timelimit','Submit','Start','End','WorkDir%4096','ReqCPUS','ReqNodes','Reason%256','Eligible']
start=datetime.datetime.fromtimestamp(begin-60).strftime('%Y-%m-%dT%H:%M:%S')
p=subprocess.run(['sacct','-X','-n','-P','-u',user,'-S',start,'--format='+','.join(fields)],capture_output=True,text=True,timeout=30)
if p.returncode: raise RuntimeError(p.stderr)
rows=[]
for line in p.stdout.splitlines():
 f=line.split('|')
 if len(f)==20 and f[-1]=='': f.pop()
 if len(f)!=19: raise RuntimeError('malformed independent sacct row')
 if not f[0].isdigit(): continue
 name,wd=f[1],f[14]
 tagged=name.startswith(prefix); inside=wd==root or wd.startswith(root+'/')
 if not tagged and not inside: continue
 if f[2]!=user: raise RuntimeError('scheduler owner differs')
 def epoch(s):
  return datetime.datetime.fromisoformat(s).timestamp() if s not in ('Unknown','None','') else None
 submitted=epoch(f[11]); a=epoch(f[12]); b=epoch(f[13])
 rows.append(dict(job_id=f[0],job_name=name,user=f[2],account=f[3],partition=f[4],state=f[5].split()[0],exit_code=f[6],alloc_cpus=int(f[7]),nodes=int(f[8]),req_mem=f[9],time_limit=f[10],submit=f[11],start=f[12],end=f[13],workdir=wd,submit_epoch=submitted,start_epoch=a,end_epoch=b,tagged=tagged,inside=inside,req_cpus=int(f[15]),req_nodes=int(f[16]),reason=f[17],eligible=f[18],eligible_epoch=epoch(f[18])))
q=subprocess.run(['squeue','-h','-u',user,'-o','%i|%j|%Z'],capture_output=True,text=True,timeout=30)
if q.returncode: raise RuntimeError(q.stderr)
active=[]
for line in q.stdout.splitlines():
 f=line.split('|')
 if len(f)!=3: raise RuntimeError('malformed squeue row')
 if f[1].startswith(prefix) or f[2]==root or f[2].startswith(root+'/'):
  if not f[0].isdigit(): raise RuntimeError('non-parent allocation in attempt')
  active.append(f[0])
print(json.dumps(dict(raw_sacct=p.stdout,raw_squeue=q.stdout,active_ids=active,jobs=rows,queried_at_epoch=time.time())))
'''

def assess_jobs(rows: list[dict], root: str, prefix: str, site: dict, begin: float, end: float):
    violations = []
    for row in rows:
        stage = row['job_name'].removeprefix(prefix)
        scoped = (row['tagged'] and row['inside'] and stage in STAGES
                  and row['workdir'] == root + '/stages/' + stage
                  and row['user'] == site['user'] and row['account'] == site['account']
                  and row['partition'] == site['partition']
                  and row['submit_epoch'] is not None and begin-1 <= row['submit_epoch'] <= end+1)
        row.update(observed=True, in_answer=True, in_answer_interval=True, count_for_cap=True,
                   historical_source=False, resource_violations=[])
        if not scoped: violations.append('job escaped authorized scope: ' + row['job_id'])
        cpus, nodes = row['alloc_cpus'], row['nodes']
        # Never-running canceled jobs may have zero allocations; their requested values remain audited.
        requested_cpus, requested_nodes = row.get('req_cpus', cpus), row.get('req_nodes', nodes)
        if cpus > 4 or nodes > 1 or not 1 <= requested_cpus <= 4 or requested_nodes != 1:
            row['resource_violations'].append('CPU/node cap')
        mem = re.fullmatch(r'(\d+(?:\.\d+)?)([KMGTP]?)([cnCN]?)', row['req_mem'])
        if mem is None: raise RuntimeError('scheduler ReqMem cannot be interpreted')
        gib = float(mem[1]) * {'K':2**-20,'M':2**-10,'G':1,'T':2**10,'P':2**20,'':2**-30}[mem[2]]
        if mem[3].lower() == 'c': gib *= max(1, requested_cpus)
        if mem[3].lower() == 'n': gib *= max(1, requested_nodes)
        if gib <= 0 or gib > 8: row['resource_violations'].append('memory cap')
        parts = row['time_limit'].split(':')
        if len(parts) != 3 or '-' in parts[0]: row['resource_violations'].append('walltime cap')
        elif sum(int(p)*factor for p,factor in zip(parts,(3600,60,1))) > 1800:
            row['resource_violations'].append('walltime cap')
    if len(rows) > 8: violations.append('allocation cap exceeded')
    intervals = [(r['start_epoch'],r['end_epoch'],r['job_id']) for r in rows if r['start_epoch'] is not None and r['end_epoch'] is not None]
    if any(max(a,c)<min(b,d) for i,(a,b,_) in enumerate(intervals) for c,d,_ in intervals[i+1:]):
        violations.append('concurrent allocations')
    return violations

def environment_blockage(snapshot: dict, final_manifest: dict):
    """Use pre-cleanup scheduler evidence, never candidate claims or host cancellations."""
    scope = final_manifest['scope']
    rows = [dict(row) for row in snapshot['jobs']]
    if len({r['job_id'] for r in rows}) != len(rows):
        raise RuntimeError('duplicate pre-cleanup allocation')
    if {r['job_id'] for r in rows} != {r['job_id'] for r in final_manifest['jobs']}:
        raise RuntimeError('pre/post-cleanup allocation sets differ')
    if any('req_cpus' not in r or 'req_nodes' not in r for r in rows):
        raise RuntimeError('requested resource evidence missing')
    begin, end = scope['answer_started_at_epoch'], scope['answer_ended_at_epoch']
    site = {k: scope[k] for k in ('account', 'partition')}
    site['user'] = scope['authenticated_user']
    violations = assess_jobs(rows, scope['remote_attempt_root'], scope['job_name_prefix'], site, begin, end)
    if violations or final_manifest.get('resource_violations') or any(r['resource_violations'] for r in rows):
        return None  # Model resource/namespace violations must not be hidden by queue failures.
    external = {'NODE_FAIL', 'BOOT_FAIL', 'PREEMPTED', 'REVOKED'}
    for row in rows:
        if row['state'] in external:
            return 'HPC_ENVIRONMENT_FAILURE: ' + row['job_id'] + ' ' + row['state']
    observed = min(float(snapshot['queried_at_epoch']), float(end))
    if not math.isfinite(observed) or observed < begin:
        raise RuntimeError('invalid pre-cleanup observation time')
    total_wait = 0.0
    pending = []
    contributors = []
    terminal = {'COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY',
                'NODE_FAIL', 'BOOT_FAIL', 'PREEMPTED', 'REVOKED', 'DEADLINE'}
    for row in rows:
        submitted, started, ended = row['submit_epoch'], row['start_epoch'], row['end_epoch']
        if submitted is None or not math.isfinite(submitted) or submitted > observed:
            raise RuntimeError('invalid scheduler submit time')
        for label, value in (('start', started), ('end', ended)):
            if value is not None and (not math.isfinite(value) or value < submitted):
                raise RuntimeError('invalid scheduler ' + label + ' time')
        if row['state'] in terminal and ended is None:
            raise RuntimeError('terminal scheduler row missing end time')
        stop = min([observed] + [v for v in (started, ended) if v is not None])
        wait = stop - submitted
        total_wait += wait
        if wait > 0:
            contributors.append(row)
        if (started is None or started > observed) and (ended is None or ended > observed):
            pending.append((row, wait))
    if not pending:
        return None  # Completed/canceled waiting ends at its terminal timestamp.
    exceeded = [(r, wait) for r, wait in pending if wait >= 3600 or total_wait >= 14400]
    if not exceeded:
        return None
    # Audit eligibility for every wait contributing to a cumulative threshold.
    for row in contributors:
        reason = str(row.get('reason', '')).lower()
        if any(word in reason for word in ('dependency', 'held', 'begintime', 'invalidaccount', 'invalidqos')):
            return None  # Self-induced historical waiting must not mask model violations.
    for row in contributors:
        eligible = row.get('eligible_epoch')
        if eligible is None or not math.isfinite(eligible) or eligible > row['submit_epoch'] + 60:
            return 'QUEUE_WAIT_NOT_VERIFIED: eligibility/hold history needs review'
    for row, wait in exceeded:
        reason = str(row.get('reason', '')).lower()
        if reason not in {'priority', 'resources'}:
            return 'QUEUE_WAIT_NOT_VERIFIED: scheduler reason ' + str(row.get('reason'))
        return 'HPC_QUEUE_BLOCKED: compliant allocation ' + row['job_id'] + ' exhausted queue budget'
    return None

def close_jobs(root, prefix, site, begin, end, host_dir, *, transport):
    terminal = {'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'}
    snapshot = json.loads(remote(JOBS_SCRIPT,(root,prefix,site['user'],begin,end), transport=transport))
    write_json(host_dir/'scheduler-before-cleanup.json', snapshot)
    active = sorted(set(snapshot['active_ids']) | {r['job_id'] for r in snapshot['jobs'] if r['state'] not in terminal})
    if active:
        remote("import subprocess,sys\nsubprocess.run(['scancel',*sys.argv[1:]],check=True,timeout=30)\n", active, transport=transport)
        for _ in range(10):
            time.sleep(2)
            snapshot = json.loads(remote(JOBS_SCRIPT,(root,prefix,site['user'],begin,end), transport=transport))
            if not snapshot['active_ids'] and all(r['state'] in terminal for r in snapshot['jobs']) and set(active).issubset({r['job_id'] for r in snapshot['jobs']}): break
        else: raise RuntimeError('attempt jobs did not reach terminal state after cleanup')
    # Query twice after closure to catch accounting lag; no scientific jobs are submitted here.
    time.sleep(2)
    snapshot = json.loads(remote(JOBS_SCRIPT,(root,prefix,site['user'],begin,end), transport=transport))
    if snapshot['active_ids']: raise RuntimeError('attempt still has queued/running jobs')
    if len({r['job_id'] for r in snapshot['jobs']}) != len(snapshot['jobs']): raise RuntimeError('duplicate scheduler parent allocation')
    write_json(host_dir/'scheduler-final.json', snapshot)
    return snapshot['jobs']

def collect_native(root: str, target: Path, host_dir: Path, jobs: list[dict], *, transport):
    from .artifacts import _P04_EXPORT_SCRIPT, _safe_materialize_export
    parent, name = str(PurePosixPath(root).parent), PurePosixPath(root).name
    # Reuse the infra's no-follow descriptor walker and bounded tar validator.
    script = _P04_EXPORT_SCRIPT.replace("os.open('/app',", "os.open(" + repr(parent) + ",")
    archive = host_dir/'native-stream.tar'
    try:
        with archive.open('wb') as stream:
            remote(script,(json.dumps([name]),20000,LIMIT,LIMIT), transport=transport, timeout=3600,output=stream)
        if archive.stat().st_size > LIMIT + 64*1024**2: raise RuntimeError('remote stream exceeds cap')
        rows = _safe_materialize_export(archive,target,[name],max_entries=20000,max_file_bytes=LIMIT,max_total_bytes=LIMIT)
    finally:
        archive.unlink(missing_ok=True)
    files=[]
    for row in rows:
        if row['type'] != 'file': continue
        rel = PurePosixPath(row['path']).relative_to(name).as_posix()
        # Stage names themselves contain '-' (meoh-md, qm-A).
        job_ids = [r['job_id'] for r in jobs if str(PurePosixPath(root)/rel).startswith(r['workdir'].rstrip('/')+'/')]
        files.append(dict(path=row['path'],remote_relative_path=rel,bytes=row['bytes'],sha256=row['sha256'],observed_job_ids=job_ids))
    return files

def seal(task, run_dir, image, attempt, root, prefix, site, begin, end, artifact_rows, *, transport):
    host = run_dir/'bench03-host'; host.mkdir(mode=0o700,exist_ok=True)
    jobs = close_jobs(root,prefix,site,begin,end,host, transport=transport)
    violations = assess_jobs(jobs,root,prefix,site,begin,end)
    evidence = host/'remote-evidence'; evidence.mkdir()
    files = collect_native(root,evidence,host,jobs, transport=transport)
    scope = dict(complete=True,ssh_target='ikkem',authenticated_user=site['user'],account=site['account'],partition=site['partition'],
                 remote_attempt_root=root,job_name_prefix=prefix,answer_started_at_epoch=begin,answer_ended_at_epoch=end,
                 audit_boundary='All authenticated-user sacct parent rows matching the fresh prefix or attempt workdir; untagged jobs outside that namespace are not attributable.')
    manifest = dict(schema='compchembench.remote-evidence/v1',collection_status='complete',scope=scope,
                    resource_policy_id=POLICY,allocation_limit=8,max_concurrent_jobs=1,
                    observed_allocations_total=len(jobs),jobs=jobs,files=files,resource_violations=violations)
    write_json(evidence/'manifest.json',manifest)
    artifact_sha = hashlib.sha256(json.dumps(artifact_rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    context = dict(schema='compchembench.runner-context/v2',evidence_mode=POLICY,resource_policy_id=POLICY,
                   attempt_id=attempt,nonce=uuid.uuid4().hex,image_id=image,task_config_sha256=digest(task.path/'task.toml'),
                   instruction_sha256=digest(task.path/'instruction.md'),artifact_manifest_sha256=artifact_sha,
                   answer_started_at_epoch=begin,answer_ended_at_epoch=end,remote_evidence_scope=scope,
                   remote_evidence_manifest_sha256=digest(evidence/'manifest.json'))
    write_json(host/'runner-context.json',context)
    for path in host.rglob('*'):
        if path.is_file(): path.chmod(0o400)
    return host/'runner-context.json',evidence,context
