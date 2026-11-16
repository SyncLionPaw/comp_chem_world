"""Validate candidate-submitted execution evidence without runner host context."""
from __future__ import annotations
import base64,csv,datetime,hashlib,json,math,re
from pathlib import Path,PurePosixPath
class EvidenceFail(Exception): pass
def _sha(b): return hashlib.sha256(b).hexdigest()
def _json(p):
    try:
        value=json.loads(p.read_text(encoding='utf-8'),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite')))
        if not isinstance(value,dict): raise ValueError('JSON root is not an object')
        return value
    except Exception as e: raise EvidenceFail('malformed candidate execution JSON') from e
def _beneath(root,rel):
    if not isinstance(rel,str) or not rel: raise EvidenceFail('execution path missing')
    q=PurePosixPath(rel)
    if q.is_absolute() or q.as_posix()!=rel or any(x in {'','.','..'} for x in q.parts): raise EvidenceFail('unsafe execution path')
    p=root.joinpath(*q.parts);cur=root
    for part in q.parts:
        cur=cur/part
        if cur.is_symlink(): raise EvidenceFail('symlink in candidate execution evidence')
    if not p.is_file(): raise EvidenceFail('candidate execution evidence missing: '+rel)
    return p
def _duration(text):
    m=re.fullmatch(r'(?:(\d+)-)?(\d{2}):(\d{2}):(\d{2})',text or '')
    if not m: raise EvidenceFail('malformed raw scheduler time limit')
    d,h,mn,s=(int(x or 0) for x in m.groups())
    if h>23 or mn>59 or s>59: raise EvidenceFail('raw scheduler time limit out of range')
    return d*86400+h*3600+mn*60+s
def _check_nonoverlap(intervals):
    ordered=sorted(intervals,key=lambda row:row[1])
    for previous,current in zip(ordered,ordered[1:]):
        if current[1]<previous[2]: raise EvidenceFail('fresh allocations overlap despite the single-concurrent-job policy')
def _sacct(path):
    rows={}
    for line in path.read_text(encoding='utf-8').splitlines():
        f=line.split('|')
        if len(f)!=15 or not re.fullmatch(r'\d{1,24}',f[0]) or f[0] in rows: raise EvidenceFail('malformed/duplicate raw scheduler record')
        rows[f[0]]=f
    return rows
def _sums(engine):
    path=engine/'SHA256SUMS'
    try: lines=path.read_text(encoding='ascii').splitlines()
    except Exception as e: raise EvidenceFail('engine_io SHA256SUMS missing') from e
    listed={}
    for line in lines:
        m=re.fullmatch(r'([0-9a-f]{64})  \.?/?(.+)',line)
        if not m: raise EvidenceFail('malformed engine SHA256SUMS row')
        rel=m.group(2); q=PurePosixPath(rel)
        if q.is_absolute() or any(x in {'','.','..'} for x in q.parts) or rel in listed or rel=='SHA256SUMS': raise EvidenceFail('unsafe/duplicate engine checksum path')
        listed[rel]=m.group(1)
    actual={p.relative_to(engine).as_posix():p for p in engine.rglob('*') if p.is_file() and p!=path}
    if set(actual)!=set(listed) or any(_sha(p.read_bytes())!=listed[r] for r,p in actual.items()): raise EvidenceFail('engine_io SHA256SUMS mismatch')
def verify(candidate,manifest,seen_jobs,refs):
    engine=candidate/'engine_io'
    needed=('execution-order.json','resources/sacct.raw.psv','resources/resource_summary.tsv','resources/job_ids.txt','resources/allocation_cpu_hours_total.txt')
    for rel in needed:
        p=engine/rel
        if p.is_symlink() or not p.is_file(): raise EvidenceFail('missing candidate execution evidence '+rel)
    _sums(engine)
    runs=[*manifest['main'],*manifest['controls']];ids=[r.get('job_id') for r in runs]
    if len(ids)!=len(set(ids)) or set(ids)!=seen_jobs or any(not isinstance(j,str) or not re.fullmatch(r'\d{1,24}',j) for j in ids): raise EvidenceFail('run manifest job identity mismatch')
    arms=_json(engine/'execution-order.json').get('required_arms')
    expected=[{'role':r.get('role','main'),'job_id':r['job_id'],'pressure_GPa':r['pressure_GPa'],'directory':r['directory'],**({'name':r['name']} if r.get('role')=='control' else {})} for r in runs]
    order=_json(engine/'execution-order.json')
    if order.get('schema')!='bench15-execution-order/v1' or arms!=expected: raise EvidenceFail('execution-order omits or alters a required arm')
    scheduler=_sacct(engine/'resources/sacct.raw.psv')
    if set(scheduler)!=seen_jobs: raise EvidenceFail('raw scheduler job set differs from submitted arms')
    archival=manifest.get('execution_kind')=='ARCHIVAL_NATIVE_REANALYSIS'
    pin_b64=refs.get('historical_native_manifest_b64')
    if archival:
        try: pin=base64.b64decode(pin_b64,validate=True)
        except Exception as e: raise EvidenceFail('pinned historical native manifest unavailable') from e
        if _sha(pin)!=refs.get('historical_native_manifest_sha256'): raise EvidenceFail('pinned historical native manifest hash mismatch')
        try: native=json.loads(pin.decode('utf-8'),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite')))
        except Exception as e: raise EvidenceFail('pinned historical native manifest is malformed') from e
        inventory=native.get('files')
        if not isinstance(inventory,dict) or manifest.get('fresh_execution')!='NOT_RUN': raise EvidenceFail('archival reanalysis provenance is malformed')
        source_note=_json(_beneath(engine,'historical-native-source.json'))
        if (source_note.get('schema')!='bench15-case06-reanalysis-source/v1'
            or source_note.get('source_manifest_sha256')!=_sha(pin)
            or source_note.get('fresh_execution')!='NOT_RUN'
            or manifest.get('execution_kind')!='ARCHIVAL_NATIVE_REANALYSIS'):
            raise EvidenceFail('archival native source provenance is inconsistent')
        for rel,row in inventory.items():
            dst=candidate/rel
            if not isinstance(rel,str) or not isinstance(row,dict) or not re.fullmatch(r'[0-9a-f]{64}',row.get('sha256','')) or type(row.get('bytes')) is not int: raise EvidenceFail('historical native inventory row malformed')
            if dst.is_symlink() or not dst.is_file(): raise EvidenceFail('submitted native science file missing')
            data=dst.read_bytes()
            if len(data)!=row['bytes'] or _sha(data)!=row['sha256']: raise EvidenceFail('submitted native evidence differs from trusted byte-pinned history')
    summary=[];fresh_intervals=[]
    for run in runs:
        jid=run['job_id']; f=scheduler[jid]
        _,job_name,account,partition,qos,work,state,exit_code=f[:8]
        try: cpus,nodes,elapsed=map(int,f[8:11]);mem,limit=f[11:13];reqcpus,reqnodes=map(int,f[13:15])
        except Exception as e: raise EvidenceFail('malformed raw scheduler resource fields') from e
        if state!='COMPLETED' or exit_code!='0:0' or nodes!=1 or reqnodes!=1 or cpus!=reqcpus: raise EvidenceFail('raw scheduler record is not one completed allocation')
        mem_match=re.fullmatch(r'(\d+)(?:Gn?|G)',mem)
        limit_s=_duration(limit)
        if (not 1<=cpus<=16 or elapsed<1 or elapsed>limit_s or not mem_match or not 1<=int(mem_match.group(1))<=60
            or (archival and limit_s>1800) or (not archival and (cpus not in {4,8,12,16} or not 60<=limit_s<=1200 or limit_s%60))):
            raise EvidenceFail('raw scheduler allocation exceeds the reviewed Case06 resource envelope')
        requested=run.get('resources')
        if (not isinstance(requested,dict) or type(requested.get('cpus')) is not int
            or type(requested.get('memory_gib')) is not int or type(requested.get('walltime_seconds')) is not int
            or requested!={'cpus':reqcpus,'memory_gib':int(mem_match.group(1)),'walltime_seconds':_duration(limit)}):
            raise EvidenceFail('run manifest resources disagree with raw Slurm request')
        rel=run.get('directory');q=PurePosixPath(rel or '')
        if not rel or q.is_absolute() or q.as_posix()!=rel or any(x in {'','.','..'} for x in q.parts): raise EvidenceFail('unsafe run directory')
        run_dir=engine.joinpath(*q.parts);cur=engine
        for part in q.parts:
            cur=cur/part
            if cur.is_symlink(): raise EvidenceFail('symlink in run directory')
        if not run_dir.is_dir(): raise EvidenceFail('run directory missing')
        for name in ('run.slurm','batch.stdout','batch.stderr','vasp.stdout','vasp.stderr'):
            _beneath(run_dir,name)
        receipt=_json(_beneath(run_dir,'execution-receipt.json'));record=_json(_beneath(run_dir,'scheduler_record.json'))
        batch_sha=_sha((run_dir/'run.slurm').read_bytes())
        if (receipt.get('schema')!='bench15-execution-receipt/v1' or record.get('schema')!='bench15-scheduler-record/v1'
            or receipt.get('job_id')!=jid or record.get('job_id')!=jid or receipt.get('scheduler')!='Slurm'
            or receipt.get('allocation_id')!=record.get('allocation_id') or receipt.get('allocation_id')!=jid
            or receipt.get('exit_code')!=exit_code or record.get('exit_code')!=exit_code
            or record.get('job_name')!=job_name or record.get('account')!=account
            or record.get('partition')!=partition or record.get('qos')!=qos or record.get('work_dir')!=work
            or receipt.get('batch_script_sha256')!=batch_sha or record.get('batch_script_sha256')!=batch_sha): raise EvidenceFail('receipt/job/allocation/script identity mismatch')
        resources={'cpus':cpus,'gpus':0,'memory_bytes':int(mem_match.group(1))*1024**3,'wall_seconds':elapsed}
        if any(type(v) is not int for v in resources.values()) or resources['cpus']<1 or resources['memory_bytes']<1 or resources['wall_seconds']<1: raise EvidenceFail('raw scheduler resource values are not positive integers')
        for obj in (receipt.get('resources'),record.get('resources')):
            if not isinstance(obj,dict) or set(obj)!=set(resources) or any(type(v) is not int for v in obj.values()): raise EvidenceFail('receipt resource fields must be exact integers')
        if (receipt.get('resources')!=resources or record.get('resources')!=resources or record.get('final_state')!=state
            or record.get('exit_code')!=exit_code or record.get('nodes')!=1 or record.get('array_job') is not False
            or record.get('walltime_limit_seconds')!=_duration(limit)): raise EvidenceFail('receipt resources/state disagree with raw scheduler record')
        if archival:
            if receipt.get('execution_kind')!='ARCHIVAL_NATIVE_REANALYSIS' or record.get('execution_kind')!='ARCHIVAL_NATIVE_REANALYSIS' or record.get('timestamps')!='NOT_AVAILABLE_IN_HISTORICAL_SOURCE': raise EvidenceFail('archival scope/timestamp limitation is not explicit')
        else:
            if receipt.get('execution_kind')!='CANDIDATE_EXECUTION': raise EvidenceFail('candidate execution receipt kind mismatch')
            try:
                start=datetime.datetime.fromisoformat(record['started_at'].replace('Z','+00:00'))
                end=datetime.datetime.fromisoformat(record['ended_at'].replace('Z','+00:00'))
            except Exception as e: raise EvidenceFail('candidate scheduler timestamps missing or malformed') from e
            if start.utcoffset() is None or end.utcoffset() is None: raise EvidenceFail('candidate scheduler timestamps require explicit time zones')
            if (end-start).total_seconds()!=elapsed: raise EvidenceFail('scheduler timestamp span differs from elapsed walltime')
            fresh_intervals.append((jid,start.astimezone(datetime.timezone.utc),end.astimezone(datetime.timezone.utc)))
        summary.append((jid,job_name,cpus,elapsed,state,cpus*elapsed/3600))
    with (engine/'resources/resource_summary.tsv').open(encoding='utf-8',newline='') as stream: rows=list(csv.DictReader(stream,delimiter='\t'))
    if len(rows)!=len(summary): raise EvidenceFail('resource summary row count mismatch')
    for row,raw in zip(rows,summary):
        allocated=row.get('AllocCPUS',row.get('AllocatedCPUS'))
        if (row.get('JobID'),row.get('JobName'),allocated,row.get('ElapsedRaw_s'),row.get('State'))!=(raw[0],raw[1],str(raw[2]),str(raw[3]),raw[4]): raise EvidenceFail('resource summary differs from raw scheduler evidence')
        try: cpu=float(row['AllocatedCPU_h'])
        except Exception as e: raise EvidenceFail('resource CPU hour malformed') from e
        if not math.isfinite(cpu) or abs(cpu-raw[5])>1.1e-6: raise EvidenceFail('resource summary CPU hours mismatch')
    reserved_wall=sum(_duration(scheduler[x[0]][12]) for x in summary)
    allocated_cpu_seconds=sum(x[2]*x[3] for x in summary)
    reserved_cpu_seconds=sum(x[2]*_duration(scheduler[x[0]][12]) for x in summary)
    if reserved_wall>38400 or allocated_cpu_seconds>921600 or reserved_cpu_seconds>921600: raise EvidenceFail('aggregate Case06 allocation budget exceeded')
    if (engine/'resources/job_ids.txt').read_text().split()!=ids: raise EvidenceFail('job_ids.txt differs from run manifest')
    try: total=float((engine/'resources/allocation_cpu_hours_total.txt').read_text().split()[0])
    except Exception as e: raise EvidenceFail('total CPU hours malformed') from e
    want=sum(x[2]*x[3] for x in summary)/3600
    if not math.isfinite(total) or abs(total-want)>1.1e-6: raise EvidenceFail('total CPU hours mismatch')
    if not archival: _check_nonoverlap(fresh_intervals)
    return {'execution_kind':'ARCHIVAL_NATIVE_REANALYSIS' if archival else 'CANDIDATE_EXECUTION','fresh_execution':'NOT_RUN' if archival else 'RUN','job_ids':ids}
