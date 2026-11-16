#!/usr/bin/env python3
# 人工审核：自动检查结果供参考，科学结论需人工复核。
"""Case 07 typed evidence grader. Scientific approval is bound to a reviewer receipt."""
from __future__ import annotations
import hashlib, json, math, os, sys, copy, re
from pathlib import Path

APP=Path(os.environ.get('APP','/app'))
TESTS=Path(os.environ.get('TESTS','/tests'))
FINAL=APP/'final'
MAX=256*1024*1024
LOCAL_REPLAY_SOURCE_HASHES={
    'amset-supporting-data-v1.0.2':'508b3ec12193e64477a17484588a2b813efeaaec78fb52193ab4fb5eddb7407a',
    'nature-source-data-xlsx':'590c17695bd1c90277e3aa0584eba4f74ee868f7d9baccdd93ff270198f73220',
}
class CandidateFailure(Exception): pass
class InfraFailure(Exception): pass

def fail(msg): raise CandidateFailure(msg)
def infra(msg): raise InfraFailure(msg)
def finite(x):
    if not isinstance(x,(int,float)) or isinstance(x,bool): return False
    try:return math.isfinite(x)
    except (OverflowError,TypeError,ValueError):return False
def elapsed_seconds(value):
    if not isinstance(value,str) or not value:return None
    days=0;clock=value
    if '-' in value:
        daytext,clock=value.split('-',1)
        if not daytext.isdigit():return None
        days=int(daytext)
    bits=clock.split(':')
    if len(bits)!=3 or not all(b.isdigit() for b in bits):return None
    h,m,s=map(int,bits)
    if m>=60 or s>=60:return None
    return days*86400+h*3600+m*60+s
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def artifact_digest(final, ctx, remote_manifest_path):
    entries=[]
    for p in sorted(final.rglob('*')):
        if p.is_symlink(): fail('submission tree contains symlink')
        if p.is_file(): entries.append({'path':p.relative_to(final).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)})
        elif not p.is_dir(): fail('submission tree contains special file')
    payload=json.dumps(entries,sort_keys=True,separators=(',',':')).encode()
    tree=hashlib.sha256(payload).hexdigest()
    context_path=Path(os.environ.get('RUNNER_CONTEXT','/trusted/runner-context.json'))
    reconstruction=Path(os.environ.get('NATIVE_RECONSTRUCTION',context_path.parent/'native-reconstruction.json'))
    local_replay=Path(os.environ.get('LOCAL_REANALYSIS',context_path.parent/'local-reanalysis.json'))
    verifier=Path(__file__)
    if reconstruction.is_symlink() or not reconstruction.is_file():infra('trusted native reconstruction receipt missing during review binding')
    if verifier.is_symlink() or not verifier.is_file():infra('pinned verifier source missing during review binding')
    # Keep this formula byte-for-byte equivalent to review.py's host receipt
    # binding: candidate tree + collector manifest + immutable context + exact
    # verifier and reconstruction bytes.
    replay_sha=sha(local_replay) if local_replay.is_file() and not local_replay.is_symlink() else ''
    material=(tree+sha(remote_manifest_path)+sha(context_path)+sha(verifier)+sha(reconstruction)+replay_sha).encode()
    return hashlib.sha256(material).hexdigest(),entries
def read_json(p, infra_data=False):
    error=infra if infra_data else fail
    if p.is_symlink() or not p.is_file(): error(f'missing or redirected JSON: {p.name}')
    if p.stat().st_size>MAX: error(f'JSON too large: {p.name}')
    def pairs(items):
        d={}
        for k,v in items:
            if k in d: raise ValueError('duplicate key '+k)
            d[k]=v
        return d
    def constant(v): raise ValueError('nonfinite '+v)
    try:return json.loads(p.read_text(),object_pairs_hook=pairs,parse_constant=constant)
    except (OSError,UnicodeError,ValueError) as e:error(f'invalid {p.name}: {e}')

def load_science_review(path):
    if path.is_symlink(): infra('science review receipt path is redirected')
    if not path.is_file(): return None
    receipt=read_json(path,True)
    if not isinstance(receipt,dict): infra('science review receipt must be a JSON object')
    return receipt

def final_human_reviewer(review, evaluator_refs):
    source=review.get('review_source')
    if not isinstance(source,dict) or not isinstance(source.get('type'),str):
        infra('trusted reviewer execution record missing')
    if source['type']=='human_interactive':
        reviewer_id=review.get('reviewer_id')
        if (not isinstance(reviewer_id,str) or not reviewer_id.strip()
                or source.get('reviewer_id')!=reviewer_id):
            infra('human reviewer identity does not match the receipt reviewer_id')
        expected=evaluator_refs.get('reviewer_code_sha256')
        if not isinstance(expected,str) or source.get('review_script_sha256')!=expected:
            infra('human review script is not the evaluator-pinned version')
        return True
    if source['type'] in {'codex_exec','synthetic_protocol_control'}:
        return False
    infra('unrecognized reviewer execution source')

def receipt_adjudication(review, evaluator_refs):
    if not final_human_reviewer(review,evaluator_refs):
        return 'REVIEW_REQUIRED',None
    return review_verdict(review['checks'],review.get('approval'),True)
NUMERIC_TOLERANCES = None

def configure_numeric_contract(refs):
    global NUMERIC_TOLERANCES
    contract=refs.get('numeric_contract')
    tolerances=contract.get('tolerances') if isinstance(contract,dict) else None
    if (not isinstance(contract,dict) or contract.get('kind')!='research-selected-no-fixed-gold-v1' or
            contract.get('near_formula')!='abs(a-b)<=tol*max(1,abs(b))' or
            contract.get('reference_values')!='derived-from-the-submitted-research-scope-and-trusted-evidence' or
            not isinstance(tolerances,dict) or set(tolerances)!={'scaled_near_default','evidence_comparison'} or
            any(not finite(value) or value<=0 for value in tolerances.values())):
        infra('private numeric reference/tolerance contract is malformed')
    NUMERIC_TOLERANCES=tolerances
    return tolerances

def near(a,b,tol=None):
    if NUMERIC_TOLERANCES is None: infra('private numeric tolerance contract was not loaded')
    tolerance=NUMERIC_TOLERANCES['scaled_near_default'] if tol is None else tol
    return finite(a) and finite(b) and abs(a-b)<=tolerance*max(1,abs(b))
def safe_file(root, rel):
    p=Path(rel)
    if p.is_absolute() or '..' in p.parts or not p.parts: fail('unsafe evidence path')
    if root.is_symlink() or not root.is_dir(): fail('unsafe evidence root')
    out=root/p
    probe=root
    for part in p.parts:
        probe=probe/part
        if probe.is_symlink(): fail(f'evidence path traverses symlink: {rel}')
    if not out.is_file() or not out.resolve().is_relative_to(root.resolve()): fail(f'evidence file missing/escaped: {rel}')
    return out

def safe_label(value, label):
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,79}",value):
        fail(f"{label} must be a safe nonempty identifier")
    return value

def finite_json(value, label):
    if value is None or isinstance(value,(str,bool,int)):
        return
    if isinstance(value,float):
        if not math.isfinite(value): fail(f"{label} contains a non-finite value")
        return
    if isinstance(value,list):
        for item in value: finite_json(item,label)
        return
    if isinstance(value,dict):
        for key,item in value.items():
            if not isinstance(key,str): fail(f"{label} has a non-string key")
            finite_json(item,label)
        return
    fail(f"{label} contains an unsupported value type")

def finite_numeric(value, label):
    if finite(value): return
    if isinstance(value,list) and value:
        for item in value: finite_numeric(item,label)
        return
    fail(f"{label} must be a finite number or nonempty numeric array")

def remote_evidence(context_path):
    if context_path.is_symlink() or context_path.parent.is_symlink(): infra('runner context path is redirected')
    ctx=read_json(context_path,True)
    if ctx.get('schema')!='compchembench.runner-context/v2' or ctx.get('task_id')!='case-07-holy-grail': infra('runner context is not host-issued case07 v2')
    if not isinstance(ctx.get('nonce'),str) or len(ctx['nonce'])<40: infra('host attempt nonce missing')
    attempt=ctx.get('attempt_id')
    if not isinstance(attempt,str) or len(attempt)!=32: infra('host attempt id malformed')
    root=context_path.parent/'remote-evidence'; mp=root/'manifest.json'
    if mp.is_symlink() or not mp.is_file(): infra('host remote evidence manifest missing')
    if sha(mp)!=ctx.get('remote_evidence_manifest_sha256'): infra('host remote evidence manifest hash mismatch')
    man=read_json(mp,True)
    if man.get('schema')!='compchembench.remote-evidence/v1' or man.get('attempt_id')!=attempt or man.get('collection_status')!='complete': infra('remote collection incomplete or wrong attempt')
    if ctx.get('remote_evidence_scope')!=man.get('scope') or not isinstance(man.get('jobs'),list): infra('remote scope/job ledger mismatch')
    if not isinstance(man.get('files'),list): infra('trusted file inventory missing')
    jobs={}
    for j in man['jobs']:
        if not isinstance(j,dict): infra('malformed trusted Slurm row')
        jid=j.get('job_id')
        if not isinstance(jid,(str,int)) or not str(jid).isdigit() or str(jid) in jobs: infra('trusted Slurm job ID malformed/duplicate')
        if not isinstance(j.get('state'),str) or not isinstance(j.get('exit_code'),str) or not isinstance(j.get('elapsed'),str) or not isinstance(j.get('alloc_cpus'),(str,int)):
            infra('trusted Slurm accounting fields malformed')
        if 'resource_policy_violation' in j and not isinstance(j['resource_policy_violation'],bool):
            infra('trusted resource-policy status malformed')
        try:
            cpus=int(j['alloc_cpus'])
        except (ValueError,TypeError): infra('trusted Slurm CPU allocation malformed')
        if cpus<=0 or elapsed_seconds(j['elapsed']) is None: infra('trusted Slurm resource/time fields malformed')
        jobs[str(jid)]=j
    files={}
    for row in man.get('files',[]):
        if not isinstance(row,dict) or not isinstance(row.get('path'),str): infra('malformed remote file record')
        if row['path'] in files: infra('duplicate remote file record')
        try: p=safe_file(root,row['path'])
        except CandidateFailure as e: infra('trusted remote snapshot path invalid: '+str(e))
        if p.stat().st_size!=row.get('bytes') or sha(p)!=row.get('sha256'): infra('trusted remote evidence bytes/hash mismatch')
        files[row['path']]=row
    return ctx,man,jobs,files,root

def trusted_sealed_sha(context_path, filename):
    """Bind root-generated receipts to the artifact transferred by Harbor."""
    manifest_path=context_path.parent/'trusted-manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():infra('root collector trust manifest missing or redirected')
    manifest=read_json(manifest_path,True)
    if (manifest.get('schema')!='case07-root-seal/v1' or
            manifest.get('attempt_id') is None or
            manifest.get('runner_context_sha256')!=sha(context_path)):
        infra('root collector trust manifest is not bound to this runner context')
    ctx=read_json(context_path,True)
    if manifest.get('attempt_id')!=ctx.get('attempt_id'):
        infra('root collector trust manifest belongs to another attempt')
    rows=manifest.get('files')
    row=rows.get(filename) if isinstance(rows,dict) else None
    path=context_path.parent/filename
    if (not isinstance(row,dict) or path.is_symlink() or not path.is_file() or
            row.get('bytes')!=path.stat().st_size or row.get('sha256')!=sha(path)):
        infra('trusted root receipt differs from the collector seal: '+filename)
    return row['sha256']

def validate_native(final, jobs, files, eroot):
    path=final/'native/manifest.json'
    if not path.exists(): return None,{}
    manifest=read_json(path)
    if manifest.get('schema')!='case07-native-evidence/v1': fail('native manifest schema unsupported')
    adapter_id=manifest.get('adapter_id');adapter_version=manifest.get('adapter_version')
    if not isinstance(adapter_id,str) or not adapter_id or not isinstance(adapter_version,str) or not adapter_version:
        fail('native-to-transport adapter identity/version missing')
    runs=manifest.get('runs')
    if not isinstance(runs,list): fail('native manifest runs must be a list')
    seen=set(); records={}
    for r in runs:
        if not isinstance(r,dict): fail('invalid native run record')
        rid=safe_label(r.get('run_id'),'native run_id')
        mat=safe_label(r.get('material'),'native material');stage=safe_label(r.get('stage'),'native stage')
        jid=str(r.get('slurm_job_id',''))
        if rid in seen: fail('duplicate native run_id')
        seen.add(rid)
        if not isinstance(r.get('software'),dict) or not isinstance(r['software'].get('name'),str) or not isinstance(r['software'].get('version'),str) or not isinstance(r.get('method_id'),str): fail(f'native method/software identity missing: {rid}')
        job=jobs.get(jid)
        if not job: fail(f'no host-observed Slurm job for {rid}')
        if job.get('resource_policy_violation') is True: fail(f'native run {rid} exceeds the frozen case07 resource policy')
        if not str(job.get('state','')).upper().startswith('COMPLETED') or str(job.get('exit_code','')) not in {'0:0','0'}: fail(f'native job {jid} did not complete cleanly')
        if job.get('in_answer_interval') is not True: fail(f'native job {jid} is outside host answer interval')
        if not isinstance(job.get('material'),str) or not isinstance(job.get('stage'),str) or not isinstance(job.get('conditions'),list): infra(f'collector-frozen job classification missing: {jid}')
        if job['material']!=mat or job['stage']!=stage: fail(f'native run material/stage disagree with collector-frozen declaration: {jid}')
        ev=r.get('files')
        if not isinstance(ev,list) or not ev: fail(f'no native output files for {rid}')
        has_input=False;has_output=False
        for x in ev:
            if not isinstance(x,dict): fail('bad native file link')
            remote_path=x.get('remote_evidence_path');row=files.get(remote_path)
            if row is None or x.get('sha256')!=row.get('sha256'): fail(f'native output not in trusted snapshot: {remote_path}')
            if str(row.get('job_id'))!=jid: fail(f'native file belongs to a different Slurm job: {remote_path}')
            p=safe_file(eroot,remote_path)
            if x.get('role') in {'input','structure','settings'}: has_input=True
            if x.get('role') in {'output','native_result','transport'} and p.stat().st_size>0: has_output=True
        if not has_input or not has_output: fail(f'run {rid} lacks linked inputs or native outputs')
        coverage=r.get('conditions',[])
        if not isinstance(coverage,list): fail(f'native run conditions must be a list: {rid}')
        host_conditions=job['conditions']
        for condition in coverage+host_conditions:
            if not isinstance(condition,dict): fail(f'condition must be an object: {rid}')
            finite_json(condition,f'conditions for {rid}')
        if any(condition not in host_conditions for condition in coverage):
            fail(f'native run conditions disagree with collector-frozen declaration: {rid}')
        try: cpus=int(job.get('alloc_cpus'))
        except (ValueError,TypeError): cpus=0
        if cpus<=0 or elapsed_seconds(job.get('elapsed')) is None: fail(f'Slurm allocation/time missing for {rid}')
        records[rid]={'run_id':rid,'material':mat,'stage':stage,'conditions':coverage,'files':ev,
                      'software':r['software'],'method_id':r['method_id'],'slurm_job_id':jid,'job':job}
    return manifest,records

def validate_evidence_index(final, index, jobs, files, eroot, native_manifest, native_runs, reconstruction, local_replay=None):
    if not isinstance(index,dict) or index.get('schema')!='case07-evidence-index/v1':
        fail('evidence-index schema must be case07-evidence-index/v1')
    sources=index.get('sources');claims=index.get('claims');comparisons=index.get('comparisons')
    executions=index.get('executions');cost=index.get('cost');reasoning=index.get('reasoning')
    if not isinstance(sources,list) or not isinstance(claims,list) or not claims or not isinstance(comparisons,list):
        fail('evidence-index needs sources, quantitative claims, and a comparison list')
    if not isinstance(executions,list) or not isinstance(cost,list) or not isinstance(reasoning,dict):
        fail('evidence-index execution/cost/reasoning fields are malformed')
    source_by_id={}; remote_source_jobs={}
    replay_source_by_id={}
    if isinstance(local_replay,dict):
        replay_source_by_id={row['source_id']:row for row in local_replay.get('sources',[]) if isinstance(row,dict)}
    replay_result_by_id={row['result_id']:row for row in local_replay.get('results',[]) if isinstance(row,dict)} if isinstance(local_replay,dict) else {}
    for source in sources:
        if not isinstance(source,dict): fail('source record must be an object')
        sid=safe_label(source.get('source_id'),'source_id')
        if sid in source_by_id: fail('duplicate source_id')
        kind=safe_label(source.get('kind'),'source kind')
        location=source.get('path_or_citation')
        if not isinstance(location,str) or not location.strip(): fail(f'source {sid} needs a path or citation')
        finite_json(source,f'source {sid}')
        actual_job=None
        if location.startswith('final/'):
            rel=location[len('final/'):]
            p=safe_file(final,rel)
            if source.get('sha256')!=sha(p): fail(f'source hash mismatch: {sid}')
        elif location.startswith('remote-evidence/'):
            rel=location[len('remote-evidence/'):]
            row=files.get(rel)
            if row is None or source.get('sha256')!=row.get('sha256'):
                fail(f'remote source does not match trusted collector bytes: {sid}')
            p=safe_file(eroot,rel)
            if sha(p)!=source.get('sha256'): infra(f'trusted remote source bytes changed: {sid}')
            actual_job=str(row.get('job_id'))
        elif source.get('sha256') is not None:
            if not isinstance(source['sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',source['sha256']): fail(f'source SHA-256 malformed: {sid}')
        source_by_id[sid]=source
        if actual_job is not None: remote_source_jobs[sid]=actual_job
    claim_by_id={}
    for claim in claims:
        if not isinstance(claim,dict): fail('claim must be an object')
        cid=safe_label(claim.get('claim_id'),'claim_id')
        if cid in claim_by_id: fail('duplicate claim_id')
        for key in ('statement','observable','unit'):
            if not isinstance(claim.get(key),str) or not claim[key].strip(): fail(f'claim {cid} missing {key}')
        finite_numeric(claim.get('value'),f'claim {cid} value')
        if not isinstance(claim.get('conditions'),dict): fail(f'claim {cid} conditions must be an object')
        finite_json(claim['conditions'],f'claim conditions {cid}')
        refs=claim.get('source_refs')
        if not isinstance(refs,list) or not refs or any(ref not in source_by_id for ref in refs): fail(f'claim {cid} has missing/invalid source references')
        replay_refs=claim.get('replay_refs',[])
        if not isinstance(replay_refs,list) or any(not isinstance(ref,str) for ref in replay_refs): fail(f'claim {cid} replay_refs malformed')
        claim_by_id[cid]=claim
    comparison_ids=set(); numeric_checks=0; metric_recomputed=set()
    def model_values(comp):
        models=comp.get('models')
        if not isinstance(models,list) or len(models)<2: fail('comparison needs at least two model/result rows')
        values={}
        for model in models:
            if not isinstance(model,dict): fail('comparison model row must be an object')
            mid=safe_label(model.get('model_id'),'comparison model_id')
            if mid in values or not finite(model.get('value')): fail('comparison model IDs must be unique with finite values')
            refs=model.get('execution_refs',[])
            if not isinstance(refs,list) or any(not isinstance(ref,str) for ref in refs): fail(f'comparison model {mid} execution_refs malformed')
            claim_refs=model.get('claim_refs')
            if not isinstance(claim_refs,list) or not claim_refs or any(not isinstance(ref,str) for ref in claim_refs):
                fail(f'comparison model {mid} must reference quantitative claims')
            values[mid]=float(model['value'])
        return values
    for comp in comparisons:
        if not isinstance(comp,dict): fail('comparison must be an object')
        cid=safe_label(comp.get('comparison_id'),'comparison_id')
        if cid in comparison_ids: fail('duplicate comparison_id')
        comparison_ids.add(cid)
        if not isinstance(comp.get('observable'),str) or not isinstance(comp.get('unit'),str) or not isinstance(comp.get('conditions'),dict): fail(f'comparison {cid} lacks observable/unit/conditions')
        finite_json(comp['conditions'],f'comparison conditions {cid}')
        refs=comp.get('source_refs')
        if not isinstance(refs,list) or not refs or any(ref not in source_by_id for ref in refs): fail(f'comparison {cid} has missing/invalid source references')
        values=model_values(comp)
        for model in comp['models']:
            linked=[claim_by_id.get(ref) for ref in model['claim_refs']]
            if any(claim is None for claim in linked): fail(f'comparison {cid} references an unknown quantitative claim')
            for claim in linked:
                if (claim.get('observable')!=comp['observable'] or claim.get('unit')!=comp['unit']
                        or claim.get('conditions')!=comp['conditions'] or not near(claim.get('value'),model['value'],NUMERIC_TOLERANCES['evidence_comparison'])):
                    fail(f'comparison {cid} model value disagrees with its referenced claims')
        metric=comp.get('metric')
        if not isinstance(metric,dict) or not isinstance(metric.get('name'),str) or not isinstance(metric.get('definition'),str) or not finite(metric.get('value')):
            fail(f'comparison {cid} needs a numeric metric with a definition')
        name=metric['name'].lower(); computed=None
        if name in {'absolute_difference','signed_difference','relative_difference','percent_difference','ratio'}:
            left_id=metric.get('model_a',metric.get('numerator_model_id'))
            right_id=metric.get('model_b',metric.get('denominator_model_id'))
            if left_id not in values or right_id not in values: fail(f'comparison {cid} metric does not identify its two model rows')
            a,b=values[left_id],values[right_id]
            if name=='absolute_difference': computed=abs(a-b)
            elif name=='signed_difference': computed=a-b
            elif name=='ratio':
                if b==0: fail(f'comparison {cid} ratio denominator is zero')
                computed=a/b
            elif name in {'relative_difference','percent_difference'}:
                if b==0: fail(f'comparison {cid} relative-difference denominator is zero')
                computed=abs(a-b)/abs(b)*(100 if name=='percent_difference' else 1)
            if computed is not None and not near(metric['value'],computed,NUMERIC_TOLERANCES['evidence_comparison']):
                fail(f'comparison {cid} metric does not match its declared definition')
            if computed is not None:
                numeric_checks+=1
                metric_recomputed.add(cid)
    execution_ids=set(); execution_by_id={}; verified_hpc_jobs=set(); unverified_routes=[]; host_native_ok=True
    native_by_job={}
    for run in native_runs.values(): native_by_job.setdefault(run['slurm_job_id'],[]).append(run)
    for execution in executions:
        if not isinstance(execution,dict): fail('execution record must be an object')
        eid=safe_label(execution.get('execution_id'),'execution_id')
        if eid in execution_ids: fail('duplicate execution_id')
        execution_ids.add(eid)
        execution_by_id[eid]=execution
        kind=execution.get('kind')
        if kind not in {'hpc_native','local_reanalysis'}: fail(f'unsupported execution kind: {kind}')
        sw=execution.get('software')
        if not isinstance(sw,dict) or not isinstance(sw.get('name'),str) or not isinstance(sw.get('version'),str): fail(f'execution {eid} needs software name/version')
        conditions=execution.get('conditions',{})
        if not isinstance(conditions,dict): fail(f'execution {eid} conditions must be an object')
        finite_json(conditions,f'execution conditions {eid}')
        for key in ('input_refs','output_refs'):
            refs=execution.get(key)
            if not isinstance(refs,list) or any(ref not in source_by_id for ref in refs): fail(f'execution {eid} {key} does not resolve to sources')
        job_ids=execution.get('claimed_job_ids',[])
        if not isinstance(job_ids,list) or any(not isinstance(job,str) or not job.isdigit() for job in job_ids): fail(f'execution {eid} claimed_job_ids malformed')
        if kind=='hpc_native':
            method_class=execution.get('method_class')
            if method_class is not None and (not isinstance(method_class,str) or not method_class.strip()):
                fail(f'HPC execution {eid} method_class must be a non-empty string when provided')
            if not job_ids: fail(f'HPC execution {eid} must identify claimed Slurm jobs')
            for jid in job_ids:
                job=jobs.get(jid)
                if job is None: fail(f'HPC execution {eid} claims a job outside trusted accounting: {jid}')
                if job.get('resource_policy_violation') is True or not str(job.get('state','')).upper().startswith('COMPLETED') or str(job.get('exit_code','')) not in {'0:0','0'} or job.get('in_answer_interval') is not True:
                    fail(f'HPC execution {eid} has an unsuccessful/out-of-scope job: {jid}')
                if jid not in native_by_job: fail(f'HPC execution {eid} lacks native input/output links for job {jid}')
                if not any(remote_source_jobs.get(ref)==jid for ref in execution['input_refs']): fail(f'HPC execution {eid} lacks a host-linked input source for job {jid}')
                if not any(remote_source_jobs.get(ref)==jid for ref in execution['output_refs']): fail(f'HPC execution {eid} lacks a host-linked output source for job {jid}')
                verified_hpc_jobs.add(jid)
            if not isinstance(native_manifest,dict): host_native_ok=False
        else:
            # Candidate declarations never authenticate local execution. A separate
            # host replay receipt is required before this route can support full credit.
            unverified_routes.append(eid)
    for comp in comparisons:
        for model in comp['models']:
            refs=model.get('execution_refs',[])
            if any(ref not in execution_ids for ref in refs):
                fail(f"comparison {comp['comparison_id']} references an unknown execution")
            # Quantitative results used in model comparisons must be tied to an
            # execution whenever the claim itself declares one. External
            # reference claims may remain citation-backed and execution-free.
            for claim_id in model['claim_refs']:
                claim=claim_by_id[claim_id]
                declared=claim.get('execution_refs',[])
                if not isinstance(declared,list) or any(ref not in execution_ids for ref in declared):
                    fail(f"claim {claim_id} execution_refs are malformed or unresolved")
                if declared and not set(declared).intersection(refs):
                    fail(f"comparison model {model['model_id']} omits a claim-linked execution")
                if declared:
                    linked_hpc={ref for ref in declared if execution_by_id[ref].get('kind')=='hpc_native'}
                    linked_outputs={source_id for ref in linked_hpc for source_id in execution_by_id[ref].get('output_refs',[])}
                    if linked_hpc and not linked_outputs.intersection(claim.get('source_refs',[])):
                        fail(f"claim {claim_id} does not cite output evidence from its execution")
    reconstruction_rows=reconstruction.get('runs',[]) if isinstance(reconstruction,dict) else []
    host_rebuilt_jobs=set()
    synthetic_reconstruction=(reconstruction.get('status')=='protocol_control'
        and reconstruction.get('source')=='synthetic_protocol_control'
        and os.environ.get('CASE07_PROTOCOL_TEST_ONLY')=='1')
    for row in reconstruction_rows:
        if isinstance(row,dict) and row.get('status')=='rebuilt':
            host_rebuilt_jobs.add(str(row.get('job_id')))
            if synthetic_reconstruction:
                continue
            identity=row.get('method_identity')
            if not isinstance(identity,dict) or not isinstance(identity.get('method_class'),str) or not identity['method_class'].strip():
                infra('rebuilt native run lacks a trusted method identity')
            points=row.get('reconstructed_points')
            if not isinstance(points,list): infra('rebuilt native run lacks reconstructed points')
            for point in points:
                if not isinstance(point,dict) or point.get('method_class')!=identity['method_class']:
                    infra('reconstructed point method identity disagrees with its run')
    if synthetic_reconstruction:
        host_rebuilt_jobs.update(verified_hpc_jobs)
    if verified_hpc_jobs and not verified_hpc_jobs.issubset(host_rebuilt_jobs): host_native_ok=False
    verified_claims=set(); verified_claim_executions={}; verified_claim_local_execs={}; reconstruction_gaps=[]
    for claim_id,claim in claim_by_id.items():
        declared=claim.get('execution_refs',[])
        replay_refs=claim.get('replay_refs',[])
        if replay_refs:
            if local_replay is not None and len(replay_refs)==1 and replay_refs[0] in replay_result_by_id:
                replay_row=replay_result_by_id[replay_refs[0]]
                replay_sources=replay_row.get('source_refs',[])
                linked_local=[eid for eid in declared if execution_by_id.get(eid,{}).get('kind')=='local_reanalysis']
                source_rows_match=True
                for source_id in replay_sources:
                    candidate_source=source_by_id.get(source_id);trusted_source=replay_source_by_id.get(source_id)
                    if (candidate_source is None or trusted_source is None or
                            candidate_source.get('sha256')!=trusted_source.get('sha256') or
                            candidate_source.get('kind')!=trusted_source.get('kind')):
                        source_rows_match=False;break
                plan_sources=[sid for sid in (linked_local and execution_by_id[linked_local[0]].get('input_refs',[]) or [])
                    if source_by_id.get(sid,{}).get('path_or_citation')=='final/reanalysis-plan.json'
                    and source_by_id[sid].get('sha256')==local_replay.get('plan_sha256')]
                replay_value_ok=(finite(replay_row.get('value')) and near(claim.get('value'),replay_row.get('value'),NUMERIC_TOLERANCES['evidence_comparison'])
                    and claim.get('observable')==replay_row.get('observable') and claim.get('unit')==replay_row.get('unit')
                    and claim.get('conditions')==replay_row.get('conditions'))
                refs_ok=set(replay_sources).issubset(set(claim.get('source_refs',[])))
                inputs_ok=bool(linked_local) and all(set(replay_sources).issubset(set(execution_by_id[eid].get('input_refs',[]))) for eid in linked_local)
                if not source_rows_match or not refs_ok or not plan_sources or not inputs_ok:
                    reconstruction_gaps.append(claim_id)
                elif not replay_value_ok:
                    fail(f'claim {claim_id} disagrees with evaluator-replayed public-source quantity')
                else:
                    verified_claims.add(claim_id)
                    verified_claim_local_execs[claim_id]=set(linked_local)
            else:
                reconstruction_gaps.append(claim_id)
        if not declared: continue
        matched_values=[]
        for execution_id in declared:
            execution=execution_by_id.get(execution_id)
            if not isinstance(execution,dict) or execution.get('kind')!='hpc_native': continue
            for jid in execution.get('claimed_job_ids',[]):
                job_runs=native_by_job.get(jid,[])
                for run in job_runs:
                    for rebuilt in reconstruction_rows:
                        if not isinstance(rebuilt,dict) or rebuilt.get('status')!='rebuilt' or str(rebuilt.get('job_id'))!=jid:
                            continue
                        if run['run_id'] not in rebuilt.get('candidate_run_ids',[]): continue
                        method_identity=rebuilt.get('method_identity')
                        trusted_method=method_identity.get('method_class') if isinstance(method_identity,dict) else None
                        declared_method=execution.get('method_class')
                        if not synthetic_reconstruction and (declared_method is None or declared_method!=trusted_method):
                            # Method identity is required to make a reconstructed
                            # quantity useful in a comparison. A missing declaration
                            # is incomplete evidence; an explicit contradiction is a
                            # false execution claim.
                            if not synthetic_reconstruction and declared_method is not None:
                                fail(f'execution {execution_id} method_class disagrees with trusted native settings/HDF')
                            if not synthetic_reconstruction: continue
                        trusted_sources={
                            source.get('path'):source.get('sha256')
                            for source in rebuilt.get('source_files',[]) if isinstance(source,dict)
                        }
                        source_bound=any(
                            remote_source_jobs.get(source_id)==jid
                            and source_by_id[source_id].get('path_or_citation','').startswith('remote-evidence/')
                            and source_by_id[source_id]['path_or_citation'][len('remote-evidence/'): ] in trusted_sources
                            and trusted_sources[source_by_id[source_id]['path_or_citation'][len('remote-evidence/'): ]]==source_by_id[source_id].get('sha256')
                            for source_id in claim.get('source_refs',[])
                        )
                        if not source_bound: continue
                        for point in rebuilt.get('reconstructed_points',[]):
                            if not isinstance(point,dict): continue
                            if point.get('run_id')!=run['run_id'] or str(point.get('job_id'))!=jid: continue
                            if not synthetic_reconstruction and point.get('method_class')!=trusted_method:
                                infra('native reconstruction point lost its trusted method identity')
                            if point.get('observable')!=claim.get('observable') or point.get('unit')!=claim.get('unit'): continue
                            if isinstance(point.get('conditions'),dict):
                                point_conditions=point['conditions']
                                conditions_match=bool(claim.get('conditions')) and point_conditions==claim.get('conditions')
                            else:
                                point_conditions={key:point[key] for key in ('material','stage','doping_cm3','temperature_K') if key in point}
                                expected_conditions=claim.get('conditions',{})
                                required={'material','doping_cm3','temperature_K'}
                                if not isinstance(expected_conditions,dict) or not required.issubset(expected_conditions): continue
                                conditions_match=all(key in point_conditions and point_conditions[key]==value
                                    for key,value in expected_conditions.items() if key!='axis')
                            expected_conditions=claim.get('conditions',{})
                            if not conditions_match: continue
                            if 'axis' in expected_conditions:
                                axes=point.get('axes')
                                if not isinstance(axes,dict) or expected_conditions['axis'] not in axes: continue
                                value=axes[expected_conditions['axis']]
                            else:
                                value=point.get('value')
                            if finite(value): matched_values.append((float(value),execution_id))
        if len(matched_values)==1:
            trusted_value, trusted_execution = matched_values[0]
            if not near(claim.get('value'),trusted_value,NUMERIC_TOLERANCES['evidence_comparison']):
                fail(f'claim {claim_id} disagrees with the evaluator-reconstructed native value')
            verified_claims.add(claim_id)
            verified_claim_executions[claim_id]={trusted_execution}
        else:
            reconstruction_gaps.append(claim_id)
    trusted_comparisons=[]; trusted_comparison_jobs=set()
    trusted_local_executions=set()
    for comp in comparisons:
        comp_claims=[claim_id for model in comp['models'] for claim_id in model['claim_refs']]
        claim_execution_ok=all(
            claim_id in verified_claims and (
                (bool(verified_claim_executions.get(claim_id)) and set(model.get('execution_refs',[])).issuperset(verified_claim_executions[claim_id]))
                or (bool(verified_claim_local_execs.get(claim_id)) and set(model.get('execution_refs',[])).issuperset(verified_claim_local_execs[claim_id]))
            )
            for model in comp['models'] for claim_id in model['claim_refs']
        )
        claim_ids_distinct=len(comp_claims)==len(set(comp_claims))
        if (comp['comparison_id'] in metric_recomputed and comp_claims and claim_ids_distinct
                and claim_execution_ok):
            linked_jobs={
                jid for model in comp['models'] for execution_id in model.get('execution_refs',[])
                for jid in execution_by_id.get(execution_id,{}).get('claimed_job_ids',[])
                if jid in verified_hpc_jobs
            }
            if linked_jobs:
                trusted_comparisons.append(comp['comparison_id'])
                trusted_comparison_jobs.update(linked_jobs)
            local_execs={eid for model in comp['models'] for claim_id in model['claim_refs']
                for eid in verified_claim_local_execs.get(claim_id,set())}
            if local_execs and all(execution_by_id[eid].get('kind')=='local_reanalysis' for eid in local_execs):
                if not linked_jobs: trusted_comparisons.append(comp['comparison_id'])
                trusted_local_executions.update(local_execs)
    cost_ids=set(); excluded=set(); own_cost_verified=False
    for row in cost:
        if not isinstance(row,dict): fail('cost row must be an object')
        scope=row.get('work_scope');hardware=row.get('hardware');origin=row.get('origin','slurm_observed')
        if not isinstance(scope,str) or not scope.strip(): fail('cost rows need a work scope')
        if origin=='reported_historical_cost':
            refs=row.get('source_refs')
            if not isinstance(refs,list) or not refs or any(ref not in source_by_id for ref in refs): fail('reported historical cost needs resolvable source references')
            reported=row.get('reported_values')
            # Historical costs are optional context and never authenticate the
            # submitter's current resource use. Only apply the strict numeric
            # check when the row explicitly claims the registered Figure 2b
            # mapping; other cited historical sources remain unverified context.
            if reported is None:
                continue
            if not isinstance(reported,list): fail('reported historical cost values must be a list when provided')
            figure2b_results={rid:result for rid,result in replay_result_by_id.items()
                if isinstance(result.get('conditions'),dict)
                and result['conditions'].get('source_sheet')=='Figure 2b'
                and result.get('observable') in {'reported_historical_cost','reported_relative_error_vs_dfpt_wannier'}}
            for item in reported:
                if not isinstance(item,dict): fail('reported historical cost row must be an object')
                replay_refs=item.get('replay_refs',[])
                source_cells=item.get('source_cells')
                claims_figure2b=(isinstance(source_cells,str) and source_cells.startswith('Figure 2b!'))
                if isinstance(replay_refs,list) and set(replay_refs).intersection(figure2b_results):
                    claims_figure2b=True
                if not claims_figure2b:
                    # A number from an unregistered source cannot be promoted
                    # by a citation or self-declared selector; keep it as
                    # narrative context and require a supported route for full
                    # quantitative credit.
                    continue
                if (not isinstance(replay_refs,list) or len(replay_refs)!=2
                        or any(ref not in figure2b_results for ref in replay_refs)):
                    fail('Figure 2b historical cost values need two registered evaluator replay references')
                if not isinstance(item.get('method'),str): fail('Figure 2b historical cost row identity malformed')
                cost_result,error_result=(replay_result_by_id[ref] for ref in replay_refs)
                conditions=cost_result.get('conditions')
                if (cost_result.get('observable')!='reported_historical_cost' or cost_result.get('unit')!='core_hours'
                        or error_result.get('observable')!='reported_relative_error_vs_dfpt_wannier' or error_result.get('unit')!='%'
                        or error_result.get('conditions')!=conditions or not isinstance(conditions,dict)
                        or conditions.get('source_sheet')!='Figure 2b' or conditions.get('method_label')!=item['method']
                        or conditions.get('materials_scope')!='Ba2BiAu and NbFeSb average'):
                    fail('reported historical cost replay references have incompatible source quantity/scope')
                expected_cells=f"Figure 2b!B{conditions['source_row']}:C{conditions['source_row']}"
                if (item.get('source_cells')!=expected_cells or not finite(item.get('total_core_hours'))
                        or not finite(item.get('relative_error_percent'))
                        or not near(item['total_core_hours'],cost_result['value'],NUMERIC_TOLERANCES['evidence_comparison'])
                        or not near(item['relative_error_percent'],error_result['value'],NUMERIC_TOLERANCES['evidence_comparison'])):
                    fail('reported historical cost values do not match the evaluator-replayed workbook cells')
                if not set(cost_result.get('source_refs',[])).issubset(refs) or not set(error_result.get('source_refs',[])).issubset(refs):
                    fail('reported historical cost row omits replayed source provenance')
            # Historical source cost can be discussed, but it does not attest this
            # attempt's resource use.
            continue
        if origin in {'host_local_replay','evaluator_derived'}:
            if local_replay is None: reconstruction_gaps.append('local_replay_cost');continue
            exec_id=row.get('execution_id');usage=local_replay.get('resource_usage',{})
            expected_receipt=os.environ.get('LOCAL_REANALYSIS_SHA256')
            if exec_id not in trusted_local_executions or row.get('job_ids')!=[]:
                fail('local replay cost does not match evaluator resource receipt')
            if row.get('replay_receipt_sha256') is not None and row.get('replay_receipt_sha256')!=expected_receipt:
                fail('local replay cost cites a different host receipt')
            if row.get('elapsed_seconds') is not None and (not finite(row['elapsed_seconds']) or not near(row['elapsed_seconds'],usage.get('wall_seconds'),NUMERIC_TOLERANCES['evidence_comparison'])):
                fail('declared local replay elapsed differs from evaluator receipt')
            if row.get('core_hours') is not None and (not finite(row['core_hours']) or not near(row['core_hours'],usage.get('cpu_seconds')/3600,NUMERIC_TOLERANCES['evidence_comparison'])):
                fail('declared local replay CPU time differs from evaluator receipt')
            if hardware is not None and hardware!=usage.get('hardware_fingerprint'):
                fail('declared local replay hardware differs from evaluator receipt')
            own_cost_verified=True
            continue
        if origin!='slurm_observed': fail('unsupported cost origin')
        ids=row.get('job_ids')
        if hardware is None or not isinstance(ids,list) or any(not isinstance(j,str) or not j.isdigit() for j in ids):
            fail('cost rows need work scope, hardware, and job IDs')
        if len(set(ids))!=len(ids) or cost_ids.intersection(ids): fail('cost job IDs must be unique across cost rows')
        if any(j not in jobs for j in ids): fail('cost row references a job outside host accounting')
        elapsed=0;cores=0;fingerprints=set()
        for jid in ids:
            job=jobs[jid];seconds=elapsed_seconds(job.get('elapsed'))
            if seconds is None: infra(f'invalid host elapsed for cost job {jid}')
            cpus=int(job['alloc_cpus']);elapsed+=seconds;cores+=seconds*cpus
            fingerprint=job.get('hardware_fingerprint')
            if not isinstance(fingerprint,str) or not fingerprint: infra(f'host hardware fingerprint missing for {jid}')
            fingerprints.add(fingerprint)
        declared_elapsed=row.get('elapsed_seconds');declared_core=row.get('core_hours')
        if ids and (not finite(declared_elapsed) or not near(declared_elapsed,elapsed,NUMERIC_TOLERANCES['evidence_comparison'])
                    or not finite(declared_core) or not near(declared_core,cores/3600,NUMERIC_TOLERANCES['evidence_comparison'])):
            fail('cost totals do not match host Slurm elapsed and allocated CPU hours')
        if ids:
            if isinstance(hardware,str): declared_hardware={hardware}
            elif isinstance(hardware,list) and all(isinstance(x,str) for x in hardware): declared_hardware=set(hardware)
            else: fail('cost hardware must be a fingerprint or list of fingerprints')
            if declared_hardware!=fingerprints:
                fail('cost hardware does not match the host allocation fingerprints')
            own_cost_verified=True
        cost_ids.update(ids)
        exclusions=row.get('exclusions',[])
        if not isinstance(exclusions,list): fail('cost exclusions must be a list')
        for item in exclusions:
            if not isinstance(item,dict) or not isinstance(item.get('job_id'),str) or not isinstance(item.get('reason'),str) or not item['reason'].strip():
                fail('cost exclusions must identify a job and explain why it is excluded')
            if item['job_id'] not in jobs: fail('cost exclusion references a job outside host accounting')
            if item['job_id'] in cost_ids or item['job_id'] in excluded: fail('cost job is both accounted and excluded')
            excluded.add(item['job_id'])
    all_host_jobs=set(jobs)
    if cost_ids & excluded: fail('cost job is both accounted and excluded')
    # A candidate-provided empty job list cannot authenticate its own execution
    # cost. Historical publication costs need an evaluator-parsed source replay;
    # until that receipt exists, they are context, not a substitute for observed
    # work performed for this submission.
    cost_verified=(own_cost_verified
        and all_host_jobs.issubset(cost_ids|excluded) and verified_hpc_jobs.issubset(cost_ids))
    reasoning_ok=all(isinstance(reasoning.get(key),str) and bool(reasoning[key].strip()) for key in ('claim_scope','uncertainty','limitations'))
    report=(final/'report.md').read_text(errors='replace')
    reasoning_ok=reasoning_ok and bool(report.strip())
    unverified_routes=[route for route in unverified_routes if route not in trusted_local_executions]
    return {'claim_count':len(claims),'comparison_count':len(comparisons),'verified_numeric_comparisons':numeric_checks,
            'all_comparisons_verified':bool(comparisons) and len(trusted_comparisons)==len(comparisons),
            'execution_verified':bool(trusted_comparison_jobs or trusted_local_executions) and host_native_ok and not unverified_routes,
            'verified_hpc_job_ids':sorted(verified_hpc_jobs,key=int),'unverified_local_routes':unverified_routes,
            'verified_numeric_claim_ids':sorted(verified_claims),'unreconstructed_claim_ids':sorted(reconstruction_gaps),
            'verified_comparison_ids':trusted_comparisons,
            'cost_verified':cost_verified,'reasoning_complete':reasoning_ok,
            'host_native_rebuilt':host_native_ok,'adapter_limited':bool(verified_hpc_jobs) and (not host_native_ok or bool(reconstruction_gaps) or not verified_claims),
            'reconstruction_classification':reconstruction.get('classification') if isinstance(reconstruction,dict) else None,
            'source_count':len(sources),'arithmetic_valid_count':numeric_checks,
            'verified_numeric_comparisons':len(trusted_comparisons)}

def expected_native_reconstruction_classification(rows, receipt_status):
    row_classes={row.get('classification') for row in rows}
    if 'candidate_invalid' in row_classes:
        return 'candidate_invalid'
    if 'evaluator_capability_gap' in row_classes:
        return 'evaluator_capability_gap'
    if not rows and receipt_status=='partial':
        return 'evaluator_capability_gap'
    return 'complete'

def validate_native_reconstruction(ctx, final, context_path, remote_manifest_path, files, eroot, evaluator_refs):
    path=Path(os.environ.get('NATIVE_RECONSTRUCTION',context_path.parent/'native-reconstruction.json'))
    if path.is_symlink() or not path.is_file():infra('trusted native reconstruction receipt missing')
    expected=trusted_sealed_sha(context_path,'native-reconstruction.json')
    if os.environ.get('CASE07_PROTOCOL_TEST_ONLY')=='1' and expected is None:expected=sha(path)
    if not isinstance(expected,str) or len(expected)!=64 or sha(path)!=expected:infra('native reconstruction receipt hash is not host-bound')
    receipt=read_json(path,True)
    supplied=receipt.get('receipt_sha256')
    body={k:v for k,v in receipt.items() if k!='receipt_sha256'}
    canonical=json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if not isinstance(supplied,str) or hashlib.sha256(canonical).hexdigest()!=supplied:infra('native reconstruction receipt self-digest mismatch')
    if receipt.get('status')=='protocol_control' and receipt.get('source')=='synthetic_protocol_control' and os.environ.get('CASE07_PROTOCOL_TEST_ONLY')=='1':
        if receipt.get('attempt_id')!=ctx.get('attempt_id') or receipt.get('runner_context_sha256')!=sha(context_path):infra('synthetic protocol receipt binding mismatch')
        return receipt
    if receipt.get('schema')!='case07.native-reconstruction/v1' or receipt.get('attempt_id')!=ctx.get('attempt_id') or receipt.get('runner_context_sha256')!=sha(context_path):
        infra('native reconstruction receipt is bound to another attempt/context')
    if receipt.get('remote_manifest_sha256')!=sha(remote_manifest_path):infra('native reconstruction remote manifest binding mismatch')
    if receipt.get('candidate_artifact_tree_sha256')!=_artifact_tree_sha(final):infra('native reconstruction candidate artifact tree binding mismatch')
    native=final/'native/manifest.json'
    if native.exists() or native.is_symlink():
        if native.is_symlink() or not native.is_file() or receipt.get('candidate_native_manifest_sha256')!=sha(native):
            infra('native reconstruction candidate manifest binding mismatch')
    elif receipt.get('candidate_native_manifest_sha256') is not None or receipt.get('runs') not in (None,[]):
        infra('native reconstruction receipt claims candidate native evidence that is absent')
    adapter=receipt.get('adapter')
    if not isinstance(adapter,dict) or not isinstance(adapter.get('id'),str) or not all(isinstance(adapter.get(k),str) and len(adapter[k])==64 for k in ('source_sha256','wrapper_sha256')):
        infra('trusted native reconstruction adapter identity/hash missing')
    registry=evaluator_refs.get('native_adapter_registry')
    if not isinstance(registry,list):infra('evaluator native-adapter registry missing')
    pinned=[entry for entry in registry if isinstance(entry,dict) and entry.get('id')==adapter.get('id')]
    if len(pinned)!=1:
        # A scientifically equivalent but unsupported format requires a trusted
        # evaluator adapter; a narrative-only review cannot upgrade it to PASS.
        infra('native reconstruction adapter is not registered by this evaluator')
    if adapter.get('source_sha256')!=pinned[0].get('source_sha256') or adapter.get('wrapper_sha256')!=pinned[0].get('wrapper_sha256'):
        infra('native reconstruction code does not match evaluator-pinned adapter sources')
    rows=receipt.get('runs')
    if not isinstance(rows,list):infra('native reconstruction run list missing')
    if receipt.get('classification') not in {'complete','candidate_invalid','evaluator_capability_gap'}:
        infra('native reconstruction capability classification is missing or unsupported')
    for row in rows:
        if not isinstance(row,dict) or row.get('status') not in {'rebuilt','partial'}:infra('native reconstruction run status malformed')
        if row.get('status')=='rebuilt':
            if row.get('classification')!='complete':infra('rebuilt native run classification is malformed')
            if not isinstance(row.get('source_files'),list) or not row['source_files']:infra('rebuilt run has no source hash list')
            for source in row['source_files']:
                if not isinstance(source,dict) or source.get('path') not in files or files[source['path']].get('sha256')!=source.get('sha256'):
                    infra('reconstruction source bytes are not bound to trusted collector inventory')
                if str(files[source['path']].get('job_id'))!=str(row.get('job_id')):infra('reconstruction source belongs to another Slurm job')
        elif row.get('classification') not in {'candidate_invalid','evaluator_capability_gap'}:
            infra('partial native run classification is malformed')
    expected_class=expected_native_reconstruction_classification(rows,receipt.get('status'))
    if receipt.get('classification')!=expected_class:
        infra('native reconstruction top-level classification disagrees with run records')
    return receipt

def validate_local_reanalysis(ctx, final, context_path, evaluator_refs):
    path=Path(os.environ.get('LOCAL_REANALYSIS',context_path.parent/'local-reanalysis.json'))
    if not path.exists() and not path.is_symlink(): return None
    if path.is_symlink() or not path.is_file():infra('trusted local-reanalysis receipt path is redirected or malformed')
    expected=trusted_sealed_sha(context_path,'local-reanalysis.json')
    if not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected) or sha(path)!=expected:
        infra('trusted local-reanalysis receipt is not host-registry bound')
    receipt=read_json(path,True)
    supplied=receipt.get('receipt_sha256');body={k:v for k,v in receipt.items() if k!='receipt_sha256'}
    canonical=json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if not isinstance(supplied,str) or hashlib.sha256(canonical).hexdigest()!=supplied:infra('local-reanalysis receipt self-digest mismatch')
    status=receipt.get('status')
    if receipt.get('schema')!='case07.local-reanalysis/v1' or status not in {'complete','candidate_invalid','unsupported_capability'}:
        infra('local-reanalysis receipt schema/status invalid')
    if receipt.get('attempt_id')!=ctx.get('attempt_id') or receipt.get('runner_context_sha256')!=sha(context_path):infra('local-reanalysis receipt belongs to another attempt/context')
    plan=safe_file(final,'reanalysis-plan.json')
    if receipt.get('plan_sha256')!=sha(plan) or receipt.get('candidate_artifact_tree_sha256')!=_artifact_tree_sha(final):infra('local-reanalysis receipt is not bound to the frozen plan/artifact tree')
    parser_pin=evaluator_refs.get('local_reanalysis_parser_sha256') or os.environ.get('LOCAL_REANALYSIS_PARSER_SHA256')
    if not isinstance(parser_pin,str) or receipt.get('parser_sha256')!=parser_pin:infra('local-reanalysis parser is not pinned by evaluator refs')
    if receipt.get('source_audit_sha256')!='1765e0b2f15ac163b7bf9b0e3840816047e7cf160a90c7f7c6de27e1f8cea9e1':infra('local-reanalysis source mapping audit hash is not pinned')
    sources=receipt.get('sources');results=receipt.get('results')
    if not isinstance(sources,list) or not isinstance(results,list):infra('local-reanalysis receipt source/result rows malformed')
    if status=='complete' and (not sources or not results):infra('complete local-reanalysis receipt lacks source/result rows')
    if status!='complete' and (sources or results):infra('non-complete local-reanalysis receipt contains untrusted result rows')
    source_ids={}
    for source in sources:
        if not isinstance(source,dict):infra('local-reanalysis source row malformed')
        sid=safe_label(source.get('source_id'),'replay source_id');catalog=source.get('catalog_id')
        if sid in source_ids or catalog not in LOCAL_REPLAY_SOURCE_HASHES or source.get('sha256')!=LOCAL_REPLAY_SOURCE_HASHES[catalog]:infra('local-reanalysis source is not in evaluator allowlist')
        source_ids[sid]=source
    result_ids={}
    for row in results:
        if not isinstance(row,dict):infra('local-reanalysis result row malformed')
        rid=safe_label(row.get('result_id'),'replay result_id')
        if rid in result_ids or not finite(row.get('value')):infra('local-reanalysis result identity/value malformed')
        if not isinstance(row.get('observable'),str) or not row['observable'] or not isinstance(row.get('unit'),str) or not row['unit'] or not isinstance(row.get('conditions'),dict):infra('local-reanalysis result dimensions malformed')
        refs=row.get('source_refs')
        if not isinstance(refs,list) or not refs or any(ref not in source_ids for ref in refs):infra('local-reanalysis result source links malformed')
        finite_json(row['conditions'],'local-reanalysis result conditions')
        result_ids[rid]=row
    usage=receipt.get('resource_usage')
    if not isinstance(usage,dict) or not finite(usage.get('wall_seconds')) or usage['wall_seconds']<0 or not finite(usage.get('cpu_seconds')) or usage['cpu_seconds']<0 or not isinstance(usage.get('hardware_fingerprint'),str):infra('local-reanalysis resource receipt malformed')
    return receipt

def _artifact_tree_sha(final):
    entries=[]
    for p in sorted(final.rglob('*')):
        if p.is_symlink():fail('submission tree contains symlink')
        if p.is_file():entries.append({'path':p.relative_to(final).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)})
        elif not p.is_dir():fail('submission tree contains special file')
    payload=json.dumps(entries,sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(payload).hexdigest()

def calculate(index, final, jobs, files, eroot, native_manifest, native_runs, reconstruction, local_replay=None):
    return validate_evidence_index(final,index,jobs,files,eroot,native_manifest,native_runs,reconstruction,local_replay)

def grade(final, tests):
    # Evaluator protocol is pinned; the public package exposes no private answer inputs.
    task=read_json(tests/'refs.json',True)
    if not isinstance(task,dict) or task.get('case_id')!='case-07-holy-grail' or not isinstance(task.get('native_adapter_registry'),list):
        infra('case07 evaluator refs are missing/invalid')
    if task.get('public_input_hashes',{}) not in ({},None):
        infra('evaluator refs still expose precomputed public science inputs')
    configure_numeric_contract(task)
    if final.is_symlink() or not final.is_dir(): fail('submission final directory missing or redirected')
    for name in ('evidence-index.json','report.md'):
        p=safe_file(final,name)
        if not p.stat().st_size: fail(f'{name} is empty')
    evidence_index=read_json(final/'evidence-index.json')
    context_path=Path(os.environ.get('RUNNER_CONTEXT','/trusted/runner-context.json'))
    ctx,rem,jobs,files,eroot=remote_evidence(context_path)
    seal_path=context_path.parent/'trusted-manifest.json'
    seal=read_json(seal_path,True)
    if seal.get('candidate_artifact_error'):
        fail('invalid candidate artifact tree: '+str(seal['candidate_artifact_error']))
    if (seal.get('candidate_artifact_tree_sha256')!=_artifact_tree_sha(final) or
            seal.get('attempt_id')!=ctx.get('attempt_id')):
        infra('root collector seal does not match the frozen candidate artifact tree')
    native_manifest,native_runs=validate_native(final,jobs,files,eroot)
    reconstruction=validate_native_reconstruction(ctx,final,context_path,context_path.parent/'remote-evidence'/'manifest.json',files,eroot,task)
    local_replay=validate_local_reanalysis(ctx,final,context_path,task)
    if isinstance(local_replay,dict) and local_replay.get('status')=='candidate_invalid':
        fail('candidate local-reanalysis plan or transform is invalid')
    metrics=calculate(evidence_index,final,jobs,files,eroot,native_manifest,native_runs,reconstruction,local_replay)
    if metrics.get('verified_hpc_job_ids') and (native_manifest is None or not native_runs):
        fail('candidate claims trusted HPC execution without a native run manifest')
    reconstruction_class=metrics.get('reconstruction_classification')
    if reconstruction_class=='candidate_invalid':
        fail('candidate native execution records are incomplete or contradict trusted run facts')
    if reconstruction_class=='evaluator_capability_gap':
        infra('registered evaluator adapter cannot independently reconstruct the submitted method/layout')
    # Reviewer receipts are host-side, artifact-bound and criterion-by-criterion. Missing candidate work is FAIL;
    # absent adjudication means partial evidence, never an invented scientific PASS.
    receipt_path=Path(os.environ.get('SCIENCE_REVIEW','/trusted/science-review.json'))
    review=load_science_review(receipt_path)
    if review is None: return None,'REVIEW_REQUIRED: quantitative evidence is structurally valid; human scientific review is pending'
    digest,entries=artifact_digest(final,ctx,context_path.parent/'remote-evidence'/'manifest.json')
    if review.get('schema')!='case07-science-review/v1' or review.get('attempt_id')!=ctx.get('attempt_id') or review.get('artifact_digest')!=digest: infra('science review receipt is not bound to this attempt and complete artifact snapshot')
    if review.get('verifier_sha256')!=sha(TESTS/'verify.py'): infra('science review used a different verifier')
    checks=review.get('checks')
    names={'research_scope_and_methods','independent_accuracy_basis','comparison_fairness','execution_and_numerical_reliability','cost_boundary','uncertainty_and_applicability','conclusion_supported_by_evidence'}
    if not isinstance(checks,dict) or set(checks)!=names: infra('science review criteria incomplete')
    for key,v in checks.items():
        if not isinstance(v,dict) or not isinstance(v.get('outcome'),str) or v.get('outcome') not in {'pass','fail','limited'} or not isinstance(v.get('reason'),str) or not v['reason'].strip() or not isinstance(v.get('evidence_ids'),list) or not v['evidence_ids']:
            infra('review criteria require an outcome, substantive reason and evidence IDs: '+key)
        for evidence_id in v['evidence_ids']:
            if not isinstance(evidence_id,str) or not _review_evidence_exists(evidence_id,final,eroot,files): infra('review references evidence absent from frozen artifacts: '+str(evidence_id))
    if not isinstance(review.get('reviewer_id'),str) or not review['reviewer_id'] or not isinstance(review.get('evidence_ids'),list): infra('reviewer identity/evidence list missing')
    decision,score=receipt_adjudication(review,task)
    if decision=='REVIEW_REQUIRED':
        if review['review_source']['type']!='human_interactive':
            return None,'REVIEW_REQUIRED: an AI or protocol receipt cannot complete Task 61 human adjudication'
        return None,'REVIEW_REQUIRED: human scientific review is limited or inconclusive'
    if decision=='FAIL': return score,'FAIL: trusted scientific review found missing required evidence or a conclusion contradicted by the data'
    if decision!='PASS':infra('review adjudication returned an unsupported state')
    if (not metrics.get('execution_verified') or not metrics.get('cost_verified')
            or not metrics.get('reasoning_complete') or metrics.get('verified_numeric_comparisons',0)<1
            or not metrics.get('all_comparisons_verified')):
        return 0.0,'FAIL: required execution, cost, reasoning, or independent numeric reconstruction is incomplete'
    if metrics.get('adapter_limited'):infra('evaluator adapter capability is insufficient for this otherwise supported execution')
    return 1.0,'PASS: independently checked evidence, execution, costs, uncertainty and conclusion have trusted review'

def review_verdict(checks, approval, qualified_reviewer):
    outcomes=[row.get('outcome') for row in checks.values()]
    if 'fail' in outcomes:
        return 'FAIL',0.0
    if 'limited' in outcomes:
        return 'REVIEW_REQUIRED',None
    if outcomes and all(value=='pass' for value in outcomes) and approval=='approved' and qualified_reviewer:
        return 'PASS',1.0
    return 'REVIEW_REQUIRED',None

def _review_evidence_exists(evidence_id,final,eroot,files):
    if evidence_id.startswith('remote-evidence/'):
        rel=evidence_id[len('remote-evidence/'):]
        if rel=='manifest.json':
            path=eroot/'manifest.json'
            context=Path(os.environ.get('RUNNER_CONTEXT','/trusted/runner-context.json'))
            try:
                ctx=read_json(context,True)
                return path.is_file() and not path.is_symlink() and sha(path)==ctx.get('remote_evidence_manifest_sha256')
            except (InfraFailure,OSError):return False
        return rel in files
    if evidence_id=='native-reconstruction.json':
        context=Path(os.environ.get('RUNNER_CONTEXT','/trusted/runner-context.json'))
        path=Path(os.environ.get('NATIVE_RECONSTRUCTION',context.parent/'native-reconstruction.json'))
        expected=os.environ.get('NATIVE_RECONSTRUCTION_SHA256')
        try:
            ctx=read_json(context,True)
            expected=expected or ctx.get('native_reconstruction_sha256')
            return path.is_file() and not path.is_symlink() and isinstance(expected,str) and sha(path)==expected
        except (InfraFailure,OSError):return False
    if evidence_id=='trusted/local-reanalysis.json':
        context=Path(os.environ.get('RUNNER_CONTEXT','/trusted/runner-context.json'))
        path=Path(os.environ.get('LOCAL_REANALYSIS',context.parent/'local-reanalysis.json'))
        expected=os.environ.get('LOCAL_REANALYSIS_SHA256')
        try:
            ctx=read_json(context,True)
            if (path.is_symlink() or not path.is_file() or not isinstance(expected,str)
                    or not re.fullmatch(r'[0-9a-f]{64}',expected) or sha(path)!=expected):
                return False
            receipt=read_json(path,True)
            return (receipt.get('schema')=='case07.local-reanalysis/v1'
                    and receipt.get('attempt_id')==ctx.get('attempt_id')
                    and receipt.get('runner_context_sha256')==sha(context)
                    and receipt.get('candidate_artifact_tree_sha256')==_artifact_tree_sha(final))
        except (InfraFailure,OSError,CandidateFailure):return False
    if evidence_id.startswith('final/'):
        rel=evidence_id[len('final/'):]
    else: rel=evidence_id
    try:return safe_file(final,rel).is_file()
    except (CandidateFailure,TypeError):return False

def main():
    try:
        reward,msg=grade(FINAL,TESTS)
        if reward==1:status,rc='PASS',0
        elif reward==0:status,rc='FAIL',1
        elif reward is None:status,rc='REVIEW_REQUIRED',0
        else:infra('grader returned an unsupported score value')
    except CandidateFailure as e: reward,msg,status,rc=0,str(e),'FAIL',1
    except InfraFailure as e: reward,msg,status,rc=None,str(e),'ENVIRONMENT_ERROR',2
    except OSError as e: reward,msg,status,rc=None,'evaluator/trusted snapshot I/O failure: '+str(e),'ENVIRONMENT_ERROR',2
    except (TypeError,KeyError,AttributeError,OverflowError) as e: reward,msg,status,rc=None,'evaluator could not safely classify malformed evidence: '+str(e),'ENVIRONMENT_ERROR',2
    verdict={'status':status,'reward':reward,'message':msg}
    print(json.dumps(verdict,ensure_ascii=False))
    logs=Path(os.environ.get('LOGS','/logs/verifier'));logs.mkdir(parents=True,exist_ok=True)
    (logs/'verification.json').write_text(json.dumps(verdict,ensure_ascii=False,indent=2)+'\n')
    (logs/'reward.json').unlink(missing_ok=True)
    if reward is None:
        (logs/'reward.txt').unlink(missing_ok=True)
        if status == 'REVIEW_REQUIRED':
            # Harbor accepts an empty metrics object for a completed, unscored trial.
            (logs/'reward.json').write_text('{}\n')
    else:
        (logs/'reward.txt').write_text(f'{reward}\n')
    raise SystemExit(rc)
if __name__=='__main__':main()
