"""Read ikkem-slurm native states and exact sacct bytes; never execute a job.

Candidate files are evidence to review, not scheduler authentication. Missing
measurements/attempt authority never become PASS through this parser.
"""
from __future__ import annotations
import base64,csv,hashlib,json,math,re
from datetime import datetime
from pathlib import Path,PurePosixPath
FIELDS=('JobIDRaw','Partition','ReqTRES','AllocTRES','NodeList','Elapsed','MaxRSS','State','ExitCode')
TERMINAL={'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','PREEMPTED','NODE_FAIL'}
class RecordError(ValueError): pass
def read_json(p):
 def pairs(items):
  out={}
  for k,v in items:
   if k in out:raise RecordError('duplicate JSON key')
   out[k]=v
  return out
 return json.loads(p.read_text(),object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(RecordError('non-finite JSON value')))
def safe(root,relative):
 rel=PurePosixPath(relative) if isinstance(relative,str) else None
 if rel is None or rel.is_absolute() or not rel.parts or any(x in ('..','.') for x in rel.parts):raise RecordError('unsafe evidence path')
 p=root
 for part in rel.parts:
  p=p/part
  if p.is_symlink():raise RecordError('symlink evidence path')
 if not p.is_file():raise RecordError('missing evidence file: '+str(relative))
 return p
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def utc(s):
 t=datetime.fromisoformat(str(s).replace('Z','+00:00'))
 if t.tzinfo is None:raise RecordError('timestamp needs timezone')
 return t
def duration(s):
 m=re.fullmatch(r'(?:(\d+)-)?(\d+):(\d{2}):(\d{2})',s or '')
 if not m or int(m[3])>=60 or int(m[4])>=60:raise RecordError('invalid Slurm elapsed duration')
 return int(m[1] or 0)*86400+int(m[2])*3600+int(m[3])*60+int(m[4])
def gib(s):
 if s is None:return None
 m=re.fullmatch(r'(\d+(?:\.\d+)?)([KMGT]?)',str(s),re.I)
 if not m:raise RecordError('unknown Slurm memory unit')
 return float(m[1])*{'':1/2**30,'K':1/2**20,'M':1/2**10,'G':1,'T':1024}[m[2].upper()]
def receipt(r,jid):
 if not isinstance(r,dict) or r.get('receipt_schema')!='ikkem-slurm-sacct-receipt/v1':raise RecordError('native sacct receipt missing')
 try:raw=base64.b64decode(r['sacct_rows_base64'],validate=True);lines=raw.decode('utf-8','strict').splitlines()
 except (ValueError,UnicodeError,KeyError) as e:raise RecordError('invalid sacct source bytes') from e
 if hashlib.sha256(raw).hexdigest()!=r.get('sacct_rows_sha256') or len(lines)!=1:raise RecordError('sacct digest/row mismatch')
 row=lines[0].split('|')
 if len(row)!=9 or row[0]!=jid or not row[1].strip() or not row[7].strip() or not re.fullmatch(r'\d+:\d+',row[8].strip()):raise RecordError('sacct job identity/shape mismatch')
 for k,v in zip(FIELDS,row):
  if r.get(k)!=(v.strip() or None):raise RecordError('parsed sacct field conflicts with raw bytes: '+k)
 state=row[7].strip();state=re.sub(r' by \d+$','',state) if state.startswith('CANCELLED') else state
 if state not in TERMINAL:raise RecordError('allocation has no recognized terminal state')
 if state=='COMPLETED' and row[8].strip()!='0:0':raise RecordError('completed allocation has nonzero exit code')
 utc(r.get('captured_at'))
 tres={}
 for token in (r.get('AllocTRES') or '').split(','):
  if not token:continue
  k,sep,v=token.partition('=')
  if not sep or k in tres:raise RecordError('invalid allocation TRES')
  tres[k]=v
 if 'cpu' in tres and not str(tres['cpu']).isdigit():raise RecordError('allocated CPU count is malformed')
 cpus=int(tres['cpu']) if 'cpu' in tres else None;elapsed=duration(r['Elapsed']);memory=gib(r.get('MaxRSS'))
 if (cpus is not None and (cpus<0 or (elapsed and cpus==0))) or elapsed>28800:raise RecordError('invalid allocation CPU/wall accounting')
 if memory is not None and (not math.isfinite(memory) or memory<0):raise RecordError('observed MaxRSS is invalid')
 return {'job_id':jid,'cpus':cpus,'elapsed_seconds':elapsed,'core_hours':cpus*elapsed/3600 if cpus is not None else None,'maxrss_gib':memory,'state':state,'exit_code':r['ExitCode']}
def state_file(p):
 s=read_json(p);jid=str(s.get('job_id',''))
 if s.get('backend')!='slurm' or not re.fullmatch(r'\d+',jid):raise RecordError('state has no exact Slurm root job ID')
 plan=s.get('plan',{});summary=s.get('plan_summary');h=s.get('plan_sha256')
 if not isinstance(summary,dict) or hashlib.sha256(json.dumps(summary,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=h or plan.get('plan_sha256')!=h or plan.get('summary')!=summary:raise RecordError('native plan binding mismatch')
 for key in ('host','workdir'):
  if not s.get(key) or s[key]!=plan.get(key) or s[key]!=summary.get(key):raise RecordError('native plan '+key+' mismatch')
 if not isinstance(plan.get('script'),str) or hashlib.sha256(plan['script'].encode()).hexdigest()!=s.get('script_sha256') or summary.get('script_sha256')!=s.get('script_sha256'):raise RecordError('native script binding mismatch')
 facts=receipt(s.get('receipt'),jid)
 if s.get('resources',{}).get('partition')!=s['receipt']['Partition']:raise RecordError('plan and scheduler partitions disagree')
 if utc(s.get('submitted_at'))>utc(s['receipt']['captured_at']):raise RecordError('terminal receipt predates submission')
 facts['submitted_at']=s['submitted_at'];facts['observed_at']=s['receipt']['captured_at']
 return facts
def directory(root,relative):
 d=root/relative
 if not d.exists():return {'status':'NOT_PRESENT','jobs':[]}
 if d.is_symlink() or not d.is_dir():raise RecordError('native state directory is unsafe')
 paths=sorted(d.glob('*.json'))
 if not paths:raise RecordError('empty native Slurm state directory')
 jobs=[state_file(safe(root,str(p.relative_to(root)))) for p in paths]
 ids=[x['job_id'] for x in jobs]
 if len(set(ids))!=len(ids):raise RecordError('duplicate root job IDs')
 return {'status':'REVIEW_REQUIRED','jobs':jobs,'allocated_core_hours':sum(x['core_hours'] for x in jobs) if all(x['core_hours'] is not None for x in jobs) else None,'known_allocated_core_hours':sum(x['core_hours'] for x in jobs if x['core_hours'] is not None),'source_authentication':'not established by candidate files','reason':'native Slurm bytes parsed; complete attempt, concurrency, memory/scratch and source authority require independent review'}
def audit_execution(final,report,record):
 try:
  if not re.fullmatch(r'[0-9a-f]{32}',str(record.get('attempt_id',''))) or record.get('attempt_id')!=report.get('attempt_id'):raise RecordError('attempt identity mismatch')
  start,end=utc(record.get('attempt_started_at_utc')),utc(record.get('report_submitted_at_utc'))
  if end<start:raise RecordError('attempt duration is negative')
  result=directory(final,'native_outputs/slurm');jobs=record.get('jobs')
  if result['status']=='NOT_PRESENT' or not isinstance(jobs,list) or len(jobs)!=len(result['jobs']):raise RecordError('execution ledger does not list every native state')
  states={j['job_id']:j for j in result['jobs']};seen=set();stages=set();owned_files=set();stage_jobs={}
  for j in jobs:
   path=safe(final,j.get('state_file'));facts=state_file(path);jid=str(j.get('job_id',''))
   if jid!=facts['job_id'] or jid not in states or jid in seen or path.parent!=final/'native_outputs/slurm':raise RecordError('allocation/state binding mismatch')
   seen.add(jid)
   if utc(facts['submitted_at'])<start or utc(facts['observed_at'])>end:raise RecordError('attempt does not contain native observations')
   paths=j.get('stage_paths',[])
   if not isinstance(paths,list) or any(not isinstance(x,str) for x in paths):raise RecordError('stage_paths must be a string array')
   if stages.intersection(paths):raise RecordError('one native stage is assigned to multiple allocations')
   stages.update(paths);stage_jobs.update({x:jid for x in paths})
   for item in j.get('native_files',[]):
    f=safe(final,item.get('path'))
    if sha(f)!=item.get('sha256'):raise RecordError('native output digest mismatch')
    owned_files.add(item['path'])
  required={x['stage_path'] for x in report.get('execution_stages',[])}
  if not required or not required<=stages:raise RecordError('scientific stages lack Slurm allocation bindings')
  for decl in report.get('execution_stages',[]):
   stage=decl['stage_path'];job=states[stage_jobs[stage]]
   native=read_json(safe(final,decl.get('receipt_path')))
   if str(native.get('job_id',''))!=job['job_id']:raise RecordError('native scientific stage and Slurm job ID disagree')
   lo,hi=utc(native.get('started_at_utc')),utc(native.get('ended_at_utc'))
   if hi<lo or lo<utc(job['submitted_at']) or hi>utc(job['observed_at']):raise RecordError('native scientific stage timing lies outside recorded job observations')
   # A completed native stage may precede a later failed/cancelled allocation;
   # retain the scheduler failure and let native science checks assess the stage.
  for stage in required:
   rel=PurePosixPath(stage)
   if rel.is_absolute() or '..' in rel.parts or not (final/stage).is_dir() or not (final/stage).resolve().is_relative_to(final.resolve()):raise RecordError('unsafe or missing scientific stage directory')
   for f in (final/stage).rglob('*'):
    if f.is_file() and str(f.relative_to(final)) not in owned_files:raise RecordError('scientific stage file missing from native digest inventory')
  rows=list(csv.DictReader((final/'resource_usage.csv').open()))
  if len(rows)!=len(states) or {x['job_id'] for x in rows}!=set(states):raise RecordError('resource rows do not cover allocations')
  for row in rows:
   f=states[row['job_id']]
   for key,value,tol in [('allocated_cores',f['cpus'],0),('allocated_core_hours',f['core_hours'],0.05)]:
    if value is None:
     if row.get(key):raise RecordError('unknown allocation measurement cannot use requested resources')
     continue
    v=float(row[key])
    if not math.isfinite(v) or abs(v-value)>tol:raise RecordError('resource table disagrees with native allocation')
   for key in ('peak_memory_gib','scratch_gib'):
    if row.get(key):
     v=float(row[key])
     if not math.isfinite(v) or v<0:raise RecordError('memory/scratch measurement is invalid')
   if f['maxrss_gib'] is None and row.get('peak_memory_gib'):raise RecordError('unknown MaxRSS cannot be replaced by requested memory')
   if f['maxrss_gib'] is not None and (not row.get('peak_memory_gib') or abs(float(row['peak_memory_gib'])-f['maxrss_gib'])>0.01):raise RecordError('MaxRSS projection mismatch')
  result.update(attempt_id=record['attempt_id'],transport='ikkem-slurm',job_count=len(states),elapsed_attempt_seconds=(end-start).total_seconds())
  return result
 except (RecordError,OSError,ValueError,TypeError,KeyError) as e:return {'status':'FAIL','reason':str(e),'transport':'ikkem-slurm','job_count':0}
