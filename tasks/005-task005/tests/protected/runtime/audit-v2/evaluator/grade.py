#!/usr/bin/env python3
"""Protected audit-v2 grader; keep outside every participant environment/archive."""
from __future__ import annotations
import argparse, csv, hashlib, json, math, re, stat, tempfile, zipfile
from pathlib import Path, PurePosixPath

HERE=Path(__file__).resolve().parent
PKG=HERE.parents[1]
PROJECT=PKG.parents[1]
REF=json.loads((HERE/'reference.json').read_text())

def fail(msg): raise ValueError(msg)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def parse_json(path):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d: fail(f'duplicate JSON key: {k}')
            d[k]=v
        return d
    return json.loads(Path(path).read_text(),object_pairs_hook=pairs,parse_constant=lambda x:fail(f'nonfinite JSON number: {x}'))
def native_energy(p):
    t=p.read_text(errors='replace')
    vals=re.findall(r'FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)',t)
    if 'ORCA TERMINATED NORMALLY' not in t or not vals: fail(f'no valid native energy in {p}')
    v=float(vals[-1])
    if not math.isfinite(v): fail(f'nonfinite native energy: {p}')
    return v
def native_frequencies(p):
    t=p.read_text(errors='replace')
    sec=t.split('VIBRATIONAL FREQUENCIES',1)[-1].split('NORMAL MODES',1)[0]
    f=[float(x) for x in re.findall(r'^\s*\d+:\s*(-?\d+\.\d+)\s+cm\*\*-1',sec,re.M)]
    if 'ORCA TERMINATED NORMALLY' not in t or len(f)!=51: fail(f'invalid native frequency evidence: {p}')
    return f
def tree_hash(files):
    h=hashlib.sha256()
    for name,digest in sorted(files.items()): h.update(f'{name}\0{digest}\n'.encode())
    return h.hexdigest()

def source_rows(): return list(csv.DictReader((HERE/'source-manifest.csv').open()))
def verify_reference_sources():
    rows=source_rows()
    # Original local/native bytes and the read-only copied remote monomer SP logs must match private pins.
    for r in rows:
        cp=r.get('private_copy_path','')
        if not cp: fail(f'missing private copy path for {r["evidence_id"]}')
        p=PROJECT/cp
        if not p.is_file() or sha(p)!=r['sha256']: fail(f'private source digest mismatch {cp}')
    cases=REF['cases']; valid=next((cid for cid,v in cases.items() if v['kind']=='valid_reconstruction'),None)
    if not valid: fail('private reference has no valid reconstruction case')
    vr=cases[valid]; vals={}
    complete=[r for r in rows if r['case_kind']=='complete']
    for r in complete:
        if r['role']!='uniform single-point output': continue
        p=PROJECT/r['private_copy_path']; energy=native_energy(p)
        if r['candidate_id']: vals[r['candidate_id']]=energy
        elif '/nucleophile/' in r['private_source_path']: vals['nucleophile']=energy
        elif '/substrate/' in r['private_source_path']: vals['substrate']=energy
    if set(vals)!={'nucleophile','substrate',*vr['route_mapping'].keys()}: fail('native reference does not identify exactly four SP energies')
    bars={rid:(vals[rid]-vals['substrate']-vals['nucleophile'])*REF['policy']['hartree_to_kcal_mol'] for rid in vr['route_mapping']}
    for rid,b in bars.items():
        if not math.isfinite(b) or abs(b-vr['expected_barriers_kcal_mol'][rid])>1e-8: fail(f'private expected barrier not derivable from pinned native SP output: {rid}')
    if sorted(bars,key=bars.get)!=vr['expected_ranking']: fail('private expected rank not derivable from native energies')
    if (max(bars.values())-min(bars.values())<REF['policy']['near_degeneracy_kcal_mol']) is not vr['expected_near_degenerate']: fail('private tie flag inconsistent with native energies')
    # Native fact checks behind typed fault cases.
    bykind={k:[r for r in rows if r['case_kind']==k] for k in ('failed-opt','soft-mode','missing-irc','mixed-sp')}
    failed=next(PROJECT/r['private_copy_path'] for r in bykind['failed-opt'] if r['role']=='transition-structure optimization output')
    ft=failed.read_text(errors='replace')
    if 'ORCA TERMINATED NORMALLY' not in ft or 'The optimization did not converge but reached the maximum number of' not in ft: fail('failed-Opt reference no longer matches native output')
    soft=next(PROJECT/r['private_copy_path'] for r in bykind['soft-mode'] if r['role']=='frequency output')
    sf=native_frequencies(soft); negative=[x for x in sf if x<0]
    if len(negative)!=1 or abs(negative[0])>=REF['policy']['soft_mode_abs_cm-1_below']: fail('soft-mode reference no longer matches native frequencies')
    missing=bykind['missing-irc']
    if sum(r['role']=='IRC output' for r in missing)!=1 or not any(r['direction']=='forward' and r['role']=='IRC output' for r in missing): fail('missing-IRC reference lacks one-direction evidence')
    oldouts=[PROJECT/r['private_copy_path'] for r in bykind['mixed-sp'] if r['role'] in ('substrate single-point output','nucleophile single-point output')]
    newins=[PROJECT/r['private_copy_path'] for r in bykind['mixed-sp'] if r['role']=='transition-structure single-point input']
    if len(oldouts)!=2 or len(newins)!=2: fail('mixed-SP reference evidence incomplete')
    if not all('RIJ-COSX (HFX calculated with COS-X)).... on' in p.read_text(errors='replace') for p in oldouts): fail('mixed-SP old monomer logs no longer confirm RIJCOSX')
    if not all(('NoRI' in p.read_text(errors='replace') and 'NoCOSX' in p.read_text(errors='replace')) for p in newins): fail('mixed-SP TS inputs no longer confirm NoRI/NoCOSX')

def extract_bundle(src,tmp):
    src=Path(src)
    if src.is_dir(): root=src.resolve()
    else:
        with zipfile.ZipFile(src) as z:
            for info in z.infolist():
                name=PurePosixPath(info.filename); mode=(info.external_attr>>16)&0o170000
                if name.is_absolute() or '..' in name.parts or mode==stat.S_IFLNK: fail(f'unsafe bundle path: {info.filename}')
                if any(x in name.parts for x in ('evaluator','archive','core-final','gold','grader')): fail(f'private path in public archive: {info.filename}')
            z.extractall(tmp)
        root=Path(tmp).resolve()
    if any(p.is_symlink() for p in root.rglob('*')): fail('symlink in participant tree')
    return root

def verify_bundle(root,bundle_file=None):
    manifest=parse_json(root/'bundle-manifest.json')
    listed={x['path']:x['sha256'] for x in manifest['files']}
    actual={p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file() and p.name!='bundle-manifest.json'}
    if actual!=listed: fail('participant bundle manifest mismatch')
    th=tree_hash(actual)
    if th!=REF.get('participant_tree_sha256'): fail('participant tree does not match protected release pin')
    if bundle_file and not Path(bundle_file).is_dir() and sha(Path(bundle_file))!=REF.get('participant_bundle_sha256'): fail('ZIP does not match protected release pin')
    expected_cases=set(REF['cases']); index=parse_json(root/'challenge-index.json')
    if set(index.get('case_ids',[]))!=expected_cases or len(index.get('case_ids',[]))!=len(expected_cases): fail('public challenge index differs from protected case list')
    rows=source_rows()
    expected_paths={r['participant_path']:r['sha256'] for r in rows}
    for rel,digest in expected_paths.items():
        p=root/rel
        if not p.is_file() or sha(p)!=digest: fail(f'participant native evidence differs from protected source: {rel}')
    return root

def index_for(root,cid): return {r['evidence_id']:r for r in csv.DictReader((root/'cases'/cid/'evidence-index.csv').open())}
def _same_json_value(a,b):
    # JSON booleans are not numeric aliases (True must never compare equal to 1).
    if isinstance(a,bool) or isinstance(b,bool): return type(a) is bool and type(b) is bool and a is b
    if isinstance(a,(int,float)) and isinstance(b,(int,float)):
        return (not isinstance(a,float) or math.isfinite(a)) and (not isinstance(b,float) or math.isfinite(b)) and a==b
    if isinstance(a,dict) and isinstance(b,dict):
        return set(a)==set(b) and all(_same_json_value(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):
        return len(a)==len(b) and all(_same_json_value(x,y) for x,y in zip(a,b))
    return type(a) is type(b) and a==b

def coalesce_observations(response):
    by_id={}; ordered=[]
    for observation in response['observations']:
        key=observation['observation_id']
        if key not in by_id:
            merged=dict(observation); merged['evidence']=list(observation['evidence'])
            by_id[key]=merged; ordered.append(merged)
        else:
            by_id[key]['evidence'].extend(observation['evidence'])
    response['observations']=ordered
    return response

def validate_submission(obj,cid):
    if not isinstance(obj,dict): return 'response must be a JSON object'
    allowed={'case_id','decision','issues','observations','barriers_kcal_mol','ranking','near_degenerate','confidence','major_product_claim','claim_assessments','reason'}
    if set(obj)-allowed: return 'unknown response keys'
    if obj.get('case_id')!=cid: return 'case_id mismatch'
    if obj.get('decision') not in ('accept','reject','insufficient_evidence'): return 'invalid decision'
    issues=obj.get('issues')
    choices={'none','opt_not_converged','imaginary_mode_unresolved','missing_irc','inconsistent_sp_protocol','overconfident_major'}
    if not isinstance(issues,list) or any(not isinstance(x,str) or x not in choices for x in issues) or len(set(issues))!=len(issues): return 'invalid issues array'
    if 'none' in issues and len(issues)!=1: return 'none cannot be combined with another issue'
    ca=obj.get('claim_assessments')
    if not isinstance(ca,dict) or any(not isinstance(k,str) or v not in ('supported','contradicted','underdetermined') for k,v in ca.items()): return 'invalid claim assessments'
    obs=obj.get('observations')
    if not isinstance(obs,list): return 'observations must be a list'
    ids={}
    for x in obs:
        if not isinstance(x,dict) or set(x)!={'observation_id','value','evidence'} or not isinstance(x['observation_id'],str): return 'invalid observation type/shape'
        oid=x['observation_id']
        if oid in ids and not _same_json_value(ids[oid],x['value']): return 'conflicting duplicate observation id'
        ids.setdefault(oid,x['value'])
        if not isinstance(x['evidence'],list) or not x['evidence']: return 'each observation needs native evidence citations'
        for cite in x['evidence']:
            if not isinstance(cite,dict) or set(cite)!={'path','sha256'} or not isinstance(cite['path'],str) or not isinstance(cite['sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',cite['sha256']): return 'invalid observation citation'
    barriers=obj.get('barriers_kcal_mol')
    if 'barriers_kcal_mol' in obj:
        if not isinstance(barriers,dict) or any(not isinstance(k,str) or isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for k,v in barriers.items()): return 'invalid/nonfinite barrier values'
    ranking=obj.get('ranking')
    if 'ranking' in obj and (not isinstance(ranking,list) or any(not isinstance(x,str) for x in ranking) or len(set(ranking))!=len(ranking)): return 'invalid ranking'
    near=obj.get('near_degenerate')
    if near is not None and type(near) is not bool: return 'near_degenerate must be boolean or null'
    conf=obj.get('confidence')
    if 'confidence' in obj and conf not in ('low','moderate','high','unrated'): return 'invalid confidence'
    major=obj.get('major_product_claim')
    if major is not None and type(major) is not bool: return 'major_product_claim must be boolean or null'
    if 'reason' in obj and not isinstance(obj['reason'],str): return 'reason must be a string'
    return None

def citation_ids(root,cid,response):
    idx=index_for(root,cid); good=set(); invalid=0; seen=set()
    citations=[]; seen_cites=set()
    for ob in response['observations']:
        local=set()
        for cite in ob['evidence']:
            key=(cite['path'],cite['sha256'])
            if key in local: continue
            local.add(key)
            if key not in seen_cites: citations.append(cite); seen_cites.add(key)
    for item in citations:
        path=item['path']; digest=item['sha256']; pp=PurePosixPath(path)
        if pp.is_absolute() or '..' in pp.parts: invalid+=1; continue
        if path in seen: invalid+=1; continue
        seen.add(path)
        row=next((r for r in idx.values() if r['relative_path']==path and r['sha256']==digest),None)
        target=(root/path).resolve()
        if root not in target.parents or not target.is_file() or sha(target)!=digest: invalid+=1; continue
        if row is not None: good.add(row['evidence_id'])
        elif path==f'cases/{cid}/evidence-index.csv' and digest==sha(target): good.add('metadata-index')
        else: invalid+=1
    return good,invalid,len(citations)

def compare_observations(root,cid,response):
    expected=REF['cases'][cid].get('observations',[])
    got={x['observation_id']:x for x in response['observations']}
    if not set(x['observation_id'] for x in expected).issubset(got): return 0.0,False,[],0.0
    idx=index_for(root,cid); ok=0; issues=[]; cited_required=0; total_required=0
    for exp in expected:
        item=got[exp['observation_id']]; val=item['value']; ref=exp['value']; kind=exp['kind']
        if kind=='irc_direction_inventory':
            value_ok=type(val) is list and val==ref
        elif kind=='sp_protocol_signature' and isinstance(ref,dict) and isinstance(val,dict):
            required=set(ref)-{'job_type'}
            value_ok=required.issubset(val) and set(val).issubset(set(ref))
            if value_ok:
                for key in required:
                    a,b=val[key],ref[key]
                    if key=='ri_jcosx_enabled': value_ok=value_ok and type(a) is bool and a is b
                    elif key=='solvent_model':
                        canonical=lambda x: 'smd' if x.strip().casefold() in ('smd','cpcm with smd','cpcm+smd') else x.strip().casefold()
                        value_ok=value_ok and isinstance(a,str) and canonical(a)==canonical(b)
                    else: value_ok=value_ok and isinstance(a,str) and ''.join(a.casefold().split())==''.join(b.casefold().split())
                if 'job_type' in val: value_ok=value_ok and isinstance(val['job_type'],str) and val['job_type'].strip().casefold()==ref['job_type'].strip().casefold()
        elif isinstance(ref,bool): value_ok=type(val) is bool and val is ref
        elif isinstance(ref,(int,float)) and not isinstance(ref,bool):
            value_ok=type(val) in (int,float) and math.isfinite(val) and abs(float(val)-float(ref)) <= (exp.get('tolerance') or 0.0)
        else: value_ok=type(val) is type(ref) and val==ref
        required=set(exp['evidence_ids']); cited=set()
        for c in item['evidence']:
            row=next((r for r in idx.values() if r['relative_path']==c['path'] and r['sha256']==c['sha256']),None)
            if row: cited.add(row['evidence_id'])
            elif c['path']==f'cases/{cid}/evidence-index.csv' and c['sha256']==sha(root/c['path']): cited.add('metadata-index')
        total_required+=len(required); cited_required+=len(required & cited)
        citation_ok=bool(required) and required.issubset(cited)
        if value_ok and citation_ok: ok+=1
        else: issues.append(exp['observation_id'])
    return (25.0*ok/max(1,len(expected))), ok==len(expected), issues, (cited_required/max(1,total_required))

def score_case(root,cid,response,err=None):
    expected=REF['cases'][cid]
    if err: return {'case_id':cid,'score':0.0,'error':err,'parts':{},'passed':False}
    decision=20.0 if response['decision']==expected['expected_decision'] else 0.0
    expissues=set(expected['expected_issues']); gotissues=set(response['issues'])
    if not expissues and not gotissues: issue=10.0
    elif expissues:
        precision=len(gotissues&expissues)/len(gotissues) if gotissues else 0.0
        recall=len(gotissues&expissues)/len(expissues)
        issue=10.0*(2*precision*recall/(precision+recall) if precision+recall else 0.0)
    else: issue=0.0
    native_obs,obs_ok,obs_issues,obs_citation_coverage=compare_observations(root,cid,response)
    cited,bad,totalcites=citation_ids(root,cid,response)
    critical=set(expected['critical_evidence_ids'])
    # Citation score is based on the public per-observation source selectors; the
    # protected critical-role list is diagnostic only, not an extra hidden hurdle.
    cite=max(0.0,10.0*obs_citation_coverage-min(10.0,bad*2.0))
    claims=response['claim_assessments']; exclaims=expected['expected_claim_assessments']
    claim=15.0*sum(claims.get(k)==v for k,v in exclaims.items())/max(1,len(exclaims))
    quant=0.0; quantitative_ok=False
    if expected['kind']=='valid_reconstruction':
        barriers=response.get('barriers_kcal_mol',{}); eb=expected['expected_barriers_kcal_mol']
        barrier_ok=isinstance(barriers,dict) and set(barriers)==set(eb) and all(not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v) and abs(v-eb[k])<=REF['policy']['barrier_tolerance_kcal_mol'] for k,v in barriers.items())
        if barrier_ok: quant+=8
        rank_ok=response.get('ranking')==expected['expected_ranking']
        if rank_ok: quant+=4
        tie_ok=response.get('near_degenerate') is expected['expected_near_degenerate']
        if tie_ok: quant+=3
        confidence=response.get('confidence')
        # Confidence labels are not graded: they are qualitative judgments, not a
        # reproducible threshold or a substitute for the cited native evidence.
        if confidence in ('low','moderate','high','unrated') or confidence is None: quant+=2.5
        major_ok=response.get('major_product_claim') is not True
        if major_ok: quant+=2.5
        quantitative_ok=barrier_ok and rank_ok and tie_ok and major_ok
    else:
        quantitative_ok=(not response.get('barriers_kcal_mol') and not response.get('ranking') and response.get('near_degenerate') is None and response.get('major_product_claim') is not True)
        # Experimental-product confidence is inapplicable to diagnostic evidence cases.
        # Its optional value must not change their score or pass state.
        if quantitative_ok: quant=20.0
    total=round(decision+issue+cite+claim+quant+native_obs,2)
    # A response that skips the required native-fact observations cannot pass by
    # guessing labels or copying a barrier table.
    if not obs_ok: total=min(total,49.0)
    passed=(decision==20 and issue==10 and claim==15 and quantitative_ok and obs_ok and bad==0)
    # Wrong primary decision caps the case score so secondary formatting cannot mask the scientific error.
    if decision==0: total=min(total,49.0)
    return {'case_id':cid,'score':total,'parts':{'decision':decision,'typed_issues':round(issue,2),'citations':round(cite,2),'claim_assessments':claim,'quantitation_and_calibration':quant,'native_observations':round(native_obs,2)},'invalid_citation_count':bad,'missing_native_observations':obs_issues,'uncited_optional_evidence_ids':sorted(critical-cited),'passed':passed}

def grade(bundle,submissions):
    verify_reference_sources()
    with tempfile.TemporaryDirectory(prefix='audit-v2-') as td:
        root=verify_bundle(extract_bundle(bundle,td),bundle)
        index=parse_json(root/'challenge-index.json'); results=[]
        for cid in index['case_ids']:
            p=Path(submissions)/f'{cid}.json'
            try:
                response=parse_json(p) if p.is_file() else None
                err='missing submission' if response is None else validate_submission(response,cid)
                if err is None: coalesce_observations(response)
            except Exception as e: response=None;err=f'invalid submission: {e}'
            results.append(score_case(root,cid,response,err))
        total=round(sum(r['score'] for r in results)/max(1,len(results)),2)
        passed=all(r.get('passed') is True for r in results)
        return {'audit_version':'audit-v2','case_count':len(results),'total_score_percent':total,'full_pass':passed,'per_case':results}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--bundle',required=True);ap.add_argument('--submissions',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    result=grade(a.bundle,a.submissions);Path(a.out).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'total_score_percent':result['total_score_percent'],'full_pass':result['full_pass'],'case_count':result['case_count']}))
if __name__=='__main__':main()
