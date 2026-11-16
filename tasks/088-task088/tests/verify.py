#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Compute the bulk SPC/E water response from a fresh MD production run.
"""Case01 adapter for candidate-native structural, provenance and science checks.

The default route cross-checks candidate-submitted execution artifacts and
requires an evaluator-generated freshness window. This is not scheduler-origin
attestation. Explicit evaluator receipt and historical archive routes remain.
"""
from __future__ import annotations
import argparse
import contextlib
import datetime as dt
import importlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

HERE=Path(__file__).resolve().parent
VERIFIER=HERE/'_support'/'verifier'

class RuntimeUnavailable(RuntimeError):
    pass

class UnsafeLogPath(RuntimeError):
    pass


def _regular_external_file(value:str, candidate:Path, expected_attempt:str|None=None)->Path:
    raw=Path(value).expanduser().absolute()
    if raw.is_symlink(): raise RuntimeUnavailable('trusted execution receipt must not be a symlink')
    cursor=Path(raw.anchor)
    for part in raw.parts[1:]:
        cursor=cursor/part
        if cursor.is_symlink(): raise RuntimeUnavailable('trusted execution receipt path contains a symlink')
    path=raw.resolve(strict=True)
    if path.is_relative_to(candidate.resolve()):
        raise RuntimeUnavailable('trusted execution receipt must be outside the candidate submission')
    try: mode=path.stat().st_mode
    except OSError as exc: raise RuntimeUnavailable(f'cannot inspect trusted execution receipt: {exc}') from exc
    if not stat.S_ISREG(mode): raise RuntimeUnavailable('trusted execution receipt must be a regular file')
    def unique_object(pairs):
        out={}
        for key,val in pairs:
            if key in out: raise ValueError(f'duplicate JSON key: {key}')
            out[key]=val
        return out
    def finite_float(value):
        number=float(value)
        if not math.isfinite(number): raise ValueError(f'non-finite JSON number: {value}')
        return number
    try:
        doc=json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=unique_object,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'non-finite JSON constant: {value}')),
                       parse_float=finite_float)
    except Exception as exc: raise RuntimeUnavailable(f'trusted execution receipt is malformed JSON: {exc}') from exc
    if not isinstance(doc,dict) or doc.get('schema')!='case01-trusted-execution-receipt-v1' or not isinstance(doc.get('source_files'),dict):
        raise RuntimeUnavailable('trusted execution receipt must be a JSON object with the supported schema and source_files object')
    if expected_attempt is not None or doc.get('issuer') is not None:
        if not expected_attempt:
            raise RuntimeUnavailable('issuer-bound receipt requires evaluator-supplied CASE01_EXPECTED_ATTEMPT_ID')
        if doc.get('attempt_id')!=expected_attempt:
            raise RuntimeUnavailable('receipt attempt_id does not match this evaluator attempt')
    return path


def runtime_preflight(env:dict[str,str], candidate:Path)->tuple[str,Path|dict]:
    """Check evaluator-supplied execution evidence and the local runtime."""
    receipt_value=env.get('CASE01_TRUSTED_EXECUTION_RECEIPT')
    archive_context=None
    if env.get('CASE01_AUTHOR_ARCHIVE_CONTEXT'):
        if receipt_value:
            raise RuntimeUnavailable('historical author context and fresh execution receipt cannot be combined')
        try:
            from historical_archive import load_author_context
            archive_context=load_author_context(env)
        except Exception as exc:
            raise RuntimeUnavailable(f'evaluator historical archive context failed validation: {exc}') from exc
        receipt=archive_context
    elif receipt_value:
        receipt=_regular_external_file(receipt_value,candidate,env.get('CASE01_EXPECTED_ATTEMPT_ID'))
    else:
        raise RuntimeUnavailable('fresh execution requires an evaluator-supplied external trusted receipt')
    requested=env.get('CASE01_GMX','gmx')
    gmx=shutil.which(requested)
    if not gmx:
        raise RuntimeUnavailable(f'GROMACS executable is unavailable: {requested}')
    try:
        version=subprocess.run([gmx,'--version'],capture_output=True,text=True,timeout=30,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise RuntimeUnavailable(f'cannot query GROMACS runtime: {exc}') from exc
    output=(version.stdout+'\n'+version.stderr).strip()
    if version.returncode!=0 or 'GROMACS' not in output.upper():
        raise RuntimeUnavailable('GROMACS --version failed or returned no recognizable version')
    for module in ('numpy','MDAnalysis','scipy'):
        try: importlib.import_module(module)
        except Exception as exc: raise RuntimeUnavailable(f'required analysis dependency {module} is unavailable: {type(exc).__name__}: {exc}') from exc
    return gmx,receipt


def classify_result(result:dict)->tuple[str,int,str]:
    """Map verifier layers to PASS/FAIL/ERROR without rewarding incomplete runs."""
    if not isinstance(result,dict): return 'ERROR',2,'verifier returned a non-object result'
    if result.get('provenance_status')=='FAIL':
        return 'FAIL',1,'candidate execution evidence is missing or internally inconsistent; science was not evaluated'
    # An actual native GROMACS TPR with an MD production duration below the
    # unchanged 20 ns science threshold is a confirmed science-gate failure,
    # even when unrelated tiny-trajectory diagnostics cannot complete.
    audit=result.get('native_audit')
    facts=audit.get('native_facts',{}) if isinstance(audit,dict) else {}
    settings=facts.get('tpr_settings',{}) if isinstance(facts,dict) else {}
    if isinstance(settings,dict) and str(settings.get('integrator','')).lower()=='md':
        steps=settings.get('nsteps'); dt_ps=settings.get('dt_ps')
        if (type(steps) is int and steps>0 and type(dt_ps) in (int,float)
                and math.isfinite(float(dt_ps)) and float(dt_ps)>0
                and steps*float(dt_ps)<20_000):
            return 'FAIL',1,'native production TPR is an MD run shorter than the required 20 ns; native diagnostics are preserved'
    l1=result.get('L1')
    if l1=='FAIL': return 'FAIL',1,'candidate failed structural/output-contract checks'
    if l1!='PASS': return 'ERROR',2,f'unexpected L1 state: {l1!r}'
    audit=result.get('native_audit')
    native_status=audit.get('status') if isinstance(audit,dict) else None
    l2=result.get('L2',native_status)
    l3=result.get('L3')
    acceptance=result.get('scientific_acceptance')
    if native_status=='ERROR' or l2=='ERROR' or l3=='ERROR':
        return 'ERROR',2,'native or independent-science verifier could not complete'
    if l3=='UNSUPPORTED_EVIDENCE' or result.get('scientific_acceptance')=='NOT_EVALUATED':
        return 'ERROR',2,'candidate method is outside the independently auditable verifier coverage; no scientific reward was issued'
    if l2=='FAIL' or native_status=='FAIL' or l3 in ('FAIL','BLOCKED_NATIVE_AUDIT') or acceptance=='FAIL':
        return 'FAIL',1,'candidate failed native or independent scientific acceptance'
    if l2=='PASS' and native_status=='PASS' and l3=='PASS' and acceptance=='PASS':
        return 'PASS',0,'L1 structure, L2 native audit, and L3 independent science checks passed'
    return 'ERROR',2,f'incomplete or unsupported verifier states: L2={l2!r}, L3={l3!r}, acceptance={acceptance!r}'


def _safe_log_dir(path:Path)->Path:
    path=path.absolute()
    cursor=Path(path.anchor)
    for part in path.parts[1:]:
        cursor=cursor/part
        if cursor.is_symlink(): raise UnsafeLogPath('verifier log path may not traverse a symlink')
    path.mkdir(parents=True,exist_ok=True)
    if path.is_symlink() or not path.is_dir(): raise OSError('verifier log path is not a regular directory')
    return path

def _remove_safe_verdict_nodes(logs:Path)->list[str]:
    """Unlink regular files, links and FIFOs without opening special nodes."""
    invalid=[]
    for name in ('reward.txt','verification.json','verifier-error.json'):
        p=logs/name
        try: mode=p.lstat().st_mode
        except FileNotFoundError: continue
        if stat.S_ISLNK(mode) or stat.S_ISREG(mode) or stat.S_ISFIFO(mode): p.unlink()
        else: invalid.append(name)
    return invalid

def _clear_stale_verdict(log_dir:Path)->None:
    """Remove prior-run outputs before any operation that can error or time out."""
    logs=_safe_log_dir(log_dir)
    invalid=_remove_safe_verdict_nodes(logs)
    if invalid: raise OSError('verifier output is not a regular file: '+', '.join(invalid))


def _public_summary(result:dict)->dict:
    """Keep useful verdict details while omitting trusted receipt contents/paths."""
    fields=('L1','L2','L3','scientific_acceptance','implementation_coverage','coverage_scope')
    out={k:result[k] for k in fields if k in result}
    for key in ('provenance_status','provenance_scope','evidence_basis','independent_scheduler_attested',
                'execution_origin_attested','scheduler','job_id','allocated_cpus','allocated_gpus',
                'allocated_memory_mb','walltime_limit_seconds','observed_elapsed_seconds',
                'production_length_ns','freshness_status','evaluation_started_at_utc','limitation'):
        if key in result: out[key]=result[key]
    audit=result.get('native_audit')
    if isinstance(audit,dict):
        facts=audit.get('native_facts',{})
        out['native_audit']={'status':audit.get('status'),'errors':audit.get('errors',[]),
          'fresh_execution_status':facts.get('fresh_execution_status'),
          'historical_archive_status':facts.get('historical_archive_status'),
          'historical_reference_job_id':facts.get('historical_reference_job_id'),
          'checks':facts.get('checks'), 'receipt_schema':facts.get('receipt_schema'),
          'receipt_interpretation':('candidate consistency compatibility bridge; accounting_verified is not scheduler attestation'
             if result.get('evidence_basis')=='candidate-artifact-consistency' else 'evaluator-supplied or historical evidence route')}
    gates=result.get('independently_recomputed_gates')
    if isinstance(gates,dict):
        out['independently_recomputed_gates']={k:gates.get(k) for k in ('scientific_status','passed','total')}
    comp=result.get('candidate_comparison')
    if isinstance(comp,dict): out['candidate_comparison_pass']=result.get('candidate_comparison_pass')
    ua=result.get('uncertainty_audit')
    if isinstance(ua,dict): out['uncertainty_audit']={'status':ua.get('status'),'errors':ua.get('errors',[]),'unsupported_evidence':ua.get('unsupported_evidence',[])}
    out['errors']=result.get('errors',[])
    return out


def _diagnostic_text(value)->str|None:
    """Bound diagnostic text and remove path-like substrings before persistence."""
    if not isinstance(value,str): return None
    text=value.replace('\x00','')[:1000]
    if (re.search(r'(?<![A-Za-z0-9_.-])/(?![0-9])',text)
        or re.search(r'(?<![A-Za-z0-9_.-])(?:[A-Za-z0-9_.-]+/){2,}[A-Za-z0-9_.-]+',text)
        or re.search(r'\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.(?:json|xtc|tpr|edr|cpt|gro|mdp|top|log|npz|csv)\b',text,re.I)
        or re.search(r'\b[A-Za-z]:\\',text)):
        return '[path-bearing diagnostic redacted]'
    text=re.sub(r'(?:(?:[A-Za-z]:)?[/\\])[^\s\"\'<>]+','[redacted-path]',text)
    text=re.sub(r'\b(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\b','[redacted-path]',text)
    return text[:500]

def _diagnostic_int(value):
    return value if type(value) is int and value>=0 else None

def _diagnostic_number(value):
    if type(value) not in (int,float): return None
    number=float(value)
    return number if math.isfinite(number) else None

def _diagnostic_counts(values)->dict|None:
    if not isinstance(values,(list,tuple)) or not values or any(_diagnostic_int(x) is None for x in values): return None
    counts=[int(x) for x in values]
    return {'blocks':len(counts),'total':sum(counts),'minimum':min(counts),'maximum':max(counts)}

def _error_diagnostics(result:dict|None)->dict|None:
    """Persist only bounded numeric-gate facts, never curves, paths, or receipt data."""
    if not isinstance(result,dict): return None
    extraction=result.get('candidate_method_reextraction')
    if not isinstance(extraction,dict): return None
    out={}
    status=_diagnostic_text(extraction.get('status'))
    if status: out['status']=status
    errors=extraction.get('errors')
    if isinstance(errors,list):
        safe=[_diagnostic_text(item) for item in errors[:4]]
        out['errors']=[item for item in safe if item is not None]
    coverage=_diagnostic_text(extraction.get('coverage_scope')) or _diagnostic_text(result.get('coverage_scope'))
    if coverage: out['coverage_scope']=coverage

    gate=extraction.get('numerical_gate')
    if isinstance(gate,dict):
        gate_out={}
        for key in ('mesh_per_bin_pass','selected_direct_probe_pass','high_k_direct_precision_unresolved',
                    'high_k_direct_accuracy_claimed','high_k_direct_gate_applied','passed'):
            value=gate.get(key)
            if type(value) is bool: gate_out[key]=value
        for key in ('max_mesh_relative_upper','max_selected_probe_relative_upper',
                    'max_all_selected_probe_relative_upper','max_high_k_direct_relative_upper'):
            value=_diagnostic_number(gate.get(key))
            if value is not None: gate_out[key]=value
        for key in ('mesh_limit_rule','selected_probe_limit_rule'):
            value=_diagnostic_text(gate.get(key))
            if value: gate_out[key]=value
        if gate_out: out['numerical_gate']=gate_out

    sampling=extraction.get('sampling')
    if isinstance(sampling,dict):
        sampling_out={}
        for key in ('native_frames','selected_frames','block_count','paired_frame_count'):
            value=_diagnostic_int(sampling.get(key))
            if value is not None: sampling_out[key]=value
        for key in ('counts_per_block','paired_counts_per_block'):
            value=_diagnostic_counts(sampling.get(key))
            if value is not None: sampling_out[key+'_summary']=value
        partial=sampling.get('partial_final_block')
        if type(partial) is bool: sampling_out['partial_final_block']=partial
        if sampling_out: out['sampling']=sampling_out

    reporting=extraction.get('reporting')
    if isinstance(reporting,dict):
        reporting_out={}
        mesh=reporting.get('primary_mesh')
        if type(mesh) is int and mesh>0: reporting_out['primary_mesh']=mesh
        centers=reporting.get('bin_centers_A^-1')
        if isinstance(centers,(list,tuple)) and all(_diagnostic_number(x) is not None for x in centers):
            reporting_out['bin_count']=len(centers)
        width=_diagnostic_number(reporting.get('bin_width_A^-1'))
        if width is not None: reporting_out['bin_width_A^-1']=width
        center=_diagnostic_text(reporting.get('center_convention'))
        if center: reporting_out['center_convention']=center
        if reporting_out: out['reporting']=reporting_out
    return out or None


def write_verdict(log_dir:Path,status:str,code:int,message:str,result:dict|None=None)->None:
    logs=_safe_log_dir(log_dir)
    reward=logs/'reward.txt'; verification=logs/'verification.json'; error=logs/'verifier-error.json'
    if code==2:
        invalid=_remove_safe_verdict_nodes(logs)
        if 'verifier-error.json' in invalid: return
        error_doc={'status':'ERROR','message':_diagnostic_text(message) or 'verifier could not complete'}
        if isinstance(result,dict):
            for key in ('provenance_status','provenance_scope','evidence_basis','independent_scheduler_attested',
                        'execution_origin_attested','freshness_status','scientific_acceptance','L1','L2','L3'):
                if key in result: error_doc[key]=result[key]
        diagnostics=_error_diagnostics(result)
        if diagnostics is not None: error_doc['diagnostics']=diagnostics
        try: error.write_text(json.dumps(error_doc,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        except Exception: pass
        return
    for p in (reward,verification,error):
        try: mode=p.lstat().st_mode
        except FileNotFoundError: continue
        if not stat.S_ISREG(mode): raise OSError(f'verifier output is not a regular file: {p.name}')
    error.unlink(missing_ok=True)
    report={'status':status,'reward':int(status=='PASS'),'message':message}
    if result is not None: report.update(_public_summary(result))
    rendered=json.dumps(report,indent=2,allow_nan=False)+'\n'
    reward.write_text(f'{int(status=="PASS")}\n',encoding='utf-8')
    verification.write_text(rendered,encoding='utf-8')


def verify_candidate(submission:Path, log_dir:Path, env:dict[str,str]|None=None,
                     checker=None, preflight:Callable|None=None)->tuple[int,dict]:
    env=dict(os.environ if env is None else env); submission=Path(submission).absolute()
    try:
        candidate_path=submission.resolve(strict=False); log_path=Path(log_dir).absolute().resolve(strict=False)
        if candidate_path==log_path or candidate_path in log_path.parents or log_path in candidate_path.parents:
            raise UnsafeLogPath('verifier log path must not overlap the candidate submission')
        _clear_stale_verdict(log_dir)
        cursor=Path(submission.anchor)
        for part in submission.parts[1:]:
            cursor=cursor/part
            if cursor.is_symlink(): raise RuntimeUnavailable('candidate submission path may not traverse a symlink')
        if not submission.is_dir(): raise RuntimeUnavailable('candidate submission directory is missing')
        sys.path.insert(0,str(VERIFIER))
        if checker is None: checker=importlib.import_module('check_submission')
        # Structural failures are candidate failures and need no scientific runtime.
        l1=checker.check_l1(submission)
        if l1.get('L1')=='FAIL':
            result={'L1':'FAIL','L2':'NOT_EVALUATED','L3':'NOT_EVALUATED','scientific_acceptance':'FAIL','errors':l1.get('errors',[])}
            status,code,message=classify_result(result); write_verdict(log_dir,status,code,message,result)
            return code,result
        if l1.get('L1')!='PASS': raise RuntimeUnavailable(f'unexpected structural verifier status: {l1.get("L1")!r}')
        runtime_check=preflight or runtime_preflight
        explicit = bool(env.get('CASE01_AUTHOR_ARCHIVE_CONTEXT') or env.get('CASE01_TRUSTED_EXECUTION_RECEIPT'))
        with contextlib.ExitStack() as stack:
            adapter_public={}
            if not explicit:
                try:
                    sys.path.insert(0,str(HERE/'_support'))
                    from candidate_provenance import CandidateEvidenceError, CandidateEvidenceUnsupported, prepare
                    eval_started_at=env.get('CASE01_EVAL_STARTED_AT_UTC')
                    if eval_started_at:
                        try: parsed_start=dt.datetime.fromisoformat(eval_started_at.replace('Z','+00:00'))
                        except ValueError as exc: raise RuntimeUnavailable('evaluator freshness window is malformed') from exc
                        if parsed_start.tzinfo is None or parsed_start > dt.datetime.now(dt.timezone.utc):
                            raise RuntimeUnavailable('evaluator freshness window must be timezone-qualified and not in the future')
                    bridge_root=Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='case01-candidate-evidence-')))
                    receipt,adapter_public=prepare(submission,bridge_root,eval_started_at)
                    env['CASE01_TRUSTED_EXECUTION_RECEIPT']=str(receipt)
                    receipt_doc=json.loads(receipt.read_text(encoding='utf-8'))
                    env['CASE01_EXPECTED_ATTEMPT_ID']=receipt_doc['attempt_id']
                except CandidateEvidenceUnsupported as exc:
                    result={'L1':'PASS','L2':'NOT_EVALUATED','L3':'UNSUPPORTED_EVIDENCE',
                            'scientific_acceptance':'NOT_EVALUATED','provenance_status':'UNSUPPORTED',
                            'provenance_scope':'candidate-artifact-consistency',
                            'evidence_basis':'candidate-artifact-consistency',
                            'independent_scheduler_attested':False,'execution_origin_attested':False,
                            'freshness_status':'NOT_VERIFIED',
                            'errors':[str(exc)]}
                    status,code,message=classify_result(result)
                    write_verdict(log_dir,status,code,message,result)
                    return code,result
                except CandidateEvidenceError as exc:
                    result={'L1':'PASS','L2':'NOT_EVALUATED','L3':'NOT_EVALUATED',
                            'scientific_acceptance':'NOT_EVALUATED','provenance_status':'FAIL',
                            'provenance_scope':'candidate-artifact-consistency',
                            'evidence_basis':'candidate-artifact-consistency',
                            'independent_scheduler_attested':False,'execution_origin_attested':False,
                            'errors':[str(exc)]}
                    status,code,message=classify_result(result)
                    write_verdict(log_dir,status,code,message,result)
                    return code,result
            gmx,receipt=runtime_check(env,submission)
            if isinstance(receipt,dict):
                result=checker.check(submission,l1_only=False,gmx=gmx,historical_archive=receipt,workdir=None)
            else:
                result=checker.check(submission,l1_only=False,gmx=gmx,trusted_execution_receipt=receipt,workdir=None)
            if adapter_public:
                result.update(adapter_public)
            status,code,message=classify_result(result)
            if code==2 and result.get('errors'): message+=': '+'; '.join(map(str,result['errors'][:4]))
            write_verdict(log_dir,status,code,message,result)
            return code,result
    except UnsafeLogPath as exc:
        print(f'verifier ERROR: {exc}',file=sys.stderr)
        return 2,{'status':'ERROR','errors':[str(exc)]}
    except RuntimeUnavailable as exc:
        msg=str(exc)
        try: write_verdict(log_dir,'ERROR',2,msg)
        except Exception: pass
        return 2,{'status':'ERROR','errors':[msg]}
    except Exception as exc:
        msg=f'{type(exc).__name__}: {exc}'
        try: write_verdict(log_dir,'ERROR',2,msg)
        except Exception: pass
        return 2,{'status':'ERROR','errors':[msg]}


def main(argv=None)->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('submission',nargs='?',type=Path,default=Path(os.environ.get('APP','/app')))
    ap.add_argument('--logs',type=Path,default=Path(os.environ.get('BENCH_LOGS','/logs/verifier')))
    ns=ap.parse_args(argv)
    code,_=verify_candidate(ns.submission,ns.logs)
    return code

if __name__=='__main__': raise SystemExit(main())
