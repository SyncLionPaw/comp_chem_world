#!/usr/bin/env python3
"""Run Case01 structural, native-execution, and independent-science checks."""
from __future__ import annotations
import argparse, csv, json, math
from pathlib import Path

def _safe_file(root:Path, rel:str):
    p=root/rel
    cur=root
    if root.is_symlink(): raise ValueError('submission root is a symlink')
    for part in Path(rel).parts:
        cur=cur/part
        if cur.is_symlink(): raise ValueError(f'symlink path is not accepted: {rel}')
    if not p.is_file() or not p.resolve().is_relative_to(root.resolve()): raise ValueError(f'missing/unsafe artifact: {rel}')
    return p

def check_l1(root:Path):
    root=Path(root); errors=[]
    try:
        # The public final-output contract requires these three files. Native
        # provenance is audited at L2 so its absence is not misreported as an
        # L1 output-format failure.
        for rel in ['final/chi_k.csv','final/observables.json','final/md_production.log']:
            _safe_file(root,rel)
        with (root/'final/chi_k.csv').open(newline='') as f:
            reader=csv.DictReader(f); required={'k_A^-1','chi_parallel'}
            if not required.issubset(reader.fieldnames or []): raise ValueError('missing curve columns')
            rows=list(reader)
        if len(rows)<2: raise ValueError('insufficient curve rows')
        ks=[]
        data=json.loads((root/'final/observables.json').read_text()); obs=data.get('observables',data)
        method=data.get('method',{})
        if not isinstance(method,dict): raise ValueError('method metadata must be an object')
        for row in rows:
            k,x=[float(row[c]) for c in ('k_A^-1','chi_parallel')]
            if 'chi_95_low' in row and 'chi_95_high' in row: lo,hi=float(row['chi_95_low']),float(row['chi_95_high'])
            elif 'chi_interval_low' in row and 'chi_interval_high' in row:
                confidence=float(row['confidence_level'])
                if not 0<confidence<1: raise ValueError('invalid curve confidence level')
                lo,hi=float(row['chi_interval_low']),float(row['chi_interval_high'])
            else:
                se=float(row.get('chi_SE',row.get('chi_bootstrap_SE','nan')))
                if not math.isfinite(se) or se<0: raise ValueError('invalid curve uncertainty')
                if not (row.get('uncertainty_method') or method.get('uncertainty_method') or method.get('bootstrap')):
                    raise ValueError('curve SE lacks a declared uncertainty method')
                lo,hi=x-se,x+se
            if not all(math.isfinite(v) for v in (k,x,lo,hi)) or k<0 or lo>hi: raise ValueError('invalid curve value/interval')
            ks.append(k)
        if abs(ks[0])>1e-10 or any(b<=a for a,b in zip(ks,ks[1:])) or ks[-1]<5.8: raise ValueError('curve range/order invalid')
        for name in ['eps_w','k_min_A^-1','chi_min','k_max_A^-1','delta_k_A^-1']:
            entry=obs[name]; est=float(entry['estimate'])
            if 'ci_95' in entry:
                ci=entry['ci_95']; lo,hi=(ci['low_95'],ci['high_95']) if isinstance(ci,dict) else ci
            elif 'interval' in entry:
                confidence=float(entry['confidence_level'])
                if not 0<confidence<1: raise ValueError('invalid confidence level')
                lo,hi=entry['interval']
            else:
                se=float(entry.get('bootstrap_SE',entry.get('SE',entry.get('standard_error'))))
                declared=entry.get('uncertainty_method') or method.get('uncertainty_method') or method.get('bootstrap')
                if not math.isfinite(se) or se<0 or not declared: raise ValueError('invalid/undefined standard error')
                lo,hi=est-se,est+se
            if not all(math.isfinite(float(v)) for v in [est,lo,hi]) or float(lo)>float(hi): raise ValueError('invalid '+name)
    except (ValueError,KeyError,TypeError,OSError) as e: errors.append(str(e))
    return {'L1':'FAIL' if errors else 'PASS','errors':errors}

def compose_result(l1:dict, *, l1_only=False, scored:dict|None=None):
    result={'structural_status':l1['L1'],'L1':l1['L1'],'L2':'NOT_EVALUATED','L3':'NOT_EVALUATED',
      'scientific_acceptance':'NOT_EVALUATED','implementation_coverage':'L1_ONLY' if l1_only else 'L1_L2_L3_CANDIDATE_NATIVE_RECOMPUTATION',
      'coverage_scope':'Verifier implementation status only; not Case01 evidence-coverage status.','errors':list(l1['errors'])}
    if l1_only or l1['L1']!='PASS' or scored is None: return result
    result['L2']=scored.get('native_audit',{}).get('status','ERROR')
    result['L3']=scored.get('L3','ERROR')
    result['scientific_acceptance']=scored.get('scientific_acceptance','FAIL')
    result['native_audit']=scored.get('native_audit')
    result['independently_recomputed_gates']=scored.get('independently_recomputed_gates')
    result['candidate_comparison']=scored.get('candidate_comparison')
    result['uncertainty_audit']=scored.get('uncertainty_audit')
    result['errors'].extend(scored.get('errors',[]))
    return result

def check(root:Path, *, l1_only=False, gmx='gmx', trusted_execution_receipt:Path|None=None,
          workdir:Path|None=None, historical_archive:dict|None=None):
    root=Path(root)
    l1=check_l1(root)
    if l1_only or l1['L1']!='PASS': return compose_result(l1,l1_only=l1_only)
    from science_score import score_submission
    scored=score_submission(root,gmx,workdir,trusted_execution_receipt,historical_archive=historical_archive)
    return compose_result(l1,scored=scored)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('submission',type=Path)
    ap.add_argument('--gmx',default='gmx'); ap.add_argument('--trusted-execution-receipt',type=Path)
    ap.add_argument('--workdir',type=Path); ap.add_argument('--l1-only',action='store_true',help='Run structural checks only; does not claim L2/L3 verification.')
    a=ap.parse_args(); r=check(a.submission,l1_only=a.l1_only,gmx=a.gmx,trusted_execution_receipt=a.trusted_execution_receipt,workdir=a.workdir)
    print(json.dumps(r,indent=2)); raise SystemExit(0 if r['scientific_acceptance']=='PASS' or a.l1_only and r['L1']=='PASS' else 2)
