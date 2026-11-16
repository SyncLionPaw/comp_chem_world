"""Bound external human review for Bench28 scientific outcomes."""
import hashlib, json, os, math
from pathlib import Path

class ReviewInvalid(ValueError):
    pass

def _pairs(rows):
    out={}
    for k,v in rows:
        if k in out: raise ReviewInvalid('duplicate JSON key')
        out[k]=v
    return out

def _sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

def _manifest(app, artifact_paths):
    rows=[]
    for rel in artifact_paths:
        target=app/rel
        if target.is_symlink(): raise ReviewInvalid('declared submission artifact is symlinked')
        if not target.exists(): continue
        candidates=[target] if target.is_file() else sorted(target.rglob('*'))
        for p in candidates:
            if p.is_symlink(): raise ReviewInvalid('declared submission artifact contains symlink')
            if p.is_dir(): continue
            if not p.is_file(): raise ReviewInvalid('submission contains unsupported file')
            rows.append({'path':p.relative_to(app).as_posix(),'bytes':p.stat().st_size,'sha256':_sha(p)})
    return sorted(rows,key=lambda x:x['path'])

def apply_review(result, app, tests, task_id, criteria, artifact_paths):
    """Set a formal reward only from a fully bound human review."""
    result=dict(result)
    if 'reward' in result:
        result['artifact_score']=result.pop('reward')
    try:
        rows=_manifest(Path(app), artifact_paths)
    except (OSError,ValueError,TypeError) as exc:
        result['status']='ENV_INVALID'; result['reward']=None; result['review_error']=str(exc); return result
    manifest_sha=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    rubric_sha=hashlib.sha256(json.dumps(criteria,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    bindings={'schema':'compchemworld.independent-auto-research-review/v1','task_id':'compchemworld/'+task_id,
        'criteria_version':'bench28-human-review-v1','refs_sha256':_sha(Path(tests)/'refs.json'),'rubric_sha256':rubric_sha,
        'verifier_sha256':hashlib.sha256((_sha(Path(__file__).resolve().parent/'verify.py')+_sha(Path(__file__).resolve())).encode()).hexdigest(),
        'artifact_manifest_sha256':manifest_sha}
    result['review_request']={**bindings,'submission_manifest':rows,'rubric':criteria,'artifact_paths':artifact_paths,
        'required_criteria':list(criteria),'reviewer_kind':'human',
        'operator_instructions':'An independent human reviewer must inspect the bound submission and rubric. Place the review JSON in the existing verifier log directory and set CCB_OPEN_RESEARCH_REVIEW_FILE=/logs/verifier/operator-review.json plus its SHA256; this directory is mounted read-write for the verifier and remains outside candidate APP.'}
    result['human_review_required']=True
    result['overall_science_status']='INCONCLUSIVE'
    result['scientific_success']=None
    result['execution_attested']=False
    result['source_truth_verified']=False
    result['reward']=None
    path_value=os.environ.get('CCB_OPEN_RESEARCH_REVIEW_FILE','').strip()
    digest=os.environ.get('CCB_OPEN_RESEARCH_REVIEW_SHA256','').strip()
    if not path_value and not digest:
        result['status']='REVIEW_REQUIRED'
        return result
    try:
        if not path_value or not digest: raise ReviewInvalid('review path and hash are required together')
        path=Path(path_value)
        if not path.is_absolute() or path.resolve().is_relative_to(Path(app).resolve()): raise ReviewInvalid('review must be outside submission')
        if any(p.is_symlink() for p in (path,*path.parents)): raise ReviewInvalid('review path contains symlink')
        if _sha(path)!=digest: raise ReviewInvalid('review digest mismatch')
        review=json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=_pairs,parse_constant=lambda x: (_ for _ in ()).throw(ReviewInvalid('nonfinite JSON')))
        if not isinstance(review,dict) or any(review.get(k)!=v for k,v in bindings.items()): raise ReviewInvalid('review binding mismatch')
        if review.get('reviewer_kind')!='human' or not isinstance(review.get('reviewer'),str) or not review['reviewer'].strip(): raise ReviewInvalid('independent human reviewer identity required')
        assessed=review.get('criteria')
        if not isinstance(assessed,dict) or set(assessed)!=set(criteria): raise ReviewInvalid('all rubric criteria must be assessed')
        paths={r['path'] for r in rows}
        for key,row in assessed.items():
            if (not isinstance(row,dict) or row.get('status') not in ('PASS','FAIL','UNRESOLVED')
                or not isinstance(row.get('finding'),str) or not row['finding'].strip()
                or not isinstance(row.get('evidence'),list) or not row['evidence']
                or any(not isinstance(p,str) or p not in paths for p in row['evidence'])):
                raise ReviewInvalid('criterion finding or evidence reference invalid: '+key)
        states={row['status'] for row in assessed.values()}
        status='FAIL' if 'FAIL' in states else ('REVIEW_REQUIRED' if 'UNRESOLVED' in states else 'PASS')
        if review.get('status')!=status: raise ReviewInvalid('review conclusion contradicts criteria')
        result['human_review']=review
        result['review_sha256']=digest
        if status=='REVIEW_REQUIRED':
            result['status']='REVIEW_REQUIRED'
            return result
        result['status']=status
        result['overall_science_status']=status
        result['scientific_success']=(status=='PASS')
        result['reward']=1 if status=='PASS' else 0
        result['human_review_required']=False
        return result
    except (OSError,ValueError,TypeError) as exc:
        result['status']='ENV_INVALID'
        result['review_error']=str(exc)
        return result
