# 人工审核：自动检查结果供参考，科学结论需人工复核。
from __future__ import annotations

"""Normalize Case 06 outcomes to Harbor rewards and explicit pending-review metrics."""
import json, math, os, subprocess, sys
from pathlib import Path

def _grade_entry():
    app = Path(os.environ.get('APP', '/app')).resolve()
    tests = Path(os.environ.get('TESTS', Path(__file__).resolve().parent)).resolve()
    logs = Path(os.environ.get('LOGS', '/logs/verifier')).resolve()
    logs.mkdir(parents=True, exist_ok=True)
    reward = logs / 'reward.txt'
    pending_metrics = logs / 'reward.json'
    report_path = logs / 'verification.json'
    reward.unlink(missing_ok=True)
    pending_metrics.unlink(missing_ok=True)
    report_path.unlink(missing_ok=True)
    try:
        proc = subprocess.run([sys.executable, str(tests / 'verify.py'), str(app / 'final')], cwd=app, capture_output=True, text=True, timeout=600, env={**os.environ, 'TESTS': str(tests), 'APP': str(app)})
        (logs / 'verify.stdout.log').write_text(proc.stdout, encoding='utf-8')
        (logs / 'verify.stderr.log').write_text(proc.stderr, encoding='utf-8')
        report = json.loads(proc.stdout)
        if type(report) is not dict:
            raise ValueError('verifier report must be a JSON object')
        status = report.get('status')
        r = report.get('reward')
        if status == 'PASS' and proc.returncode == 0 and (type(r) in (int, float)) and math.isfinite(r) and (r == 1):
            reward.write_text('1\n')
            accepted = report
            rc = 0
        elif status == 'FAIL' and proc.returncode == 1 and (type(r) in (int, float)) and math.isfinite(r) and (r == 0):
            reward.write_text('0\n')
            accepted = report
            rc = 1
        elif status == 'REVIEW_REQUIRED' and proc.returncode == 0 and ('reward' not in report):
            # A named workflow metric is not a scientific score or a PASS.
            # Harbor accepts reward.json without a scalar 'reward' field.
            pending_metrics.write_text(json.dumps({'review_required': 1}) + '\n')
            accepted = {**report, 'harbor_metrics': {'review_required': 1}}
            rc = 0
        elif status == 'ENVIRONMENT_ERROR' and proc.returncode == 2 and ('reward' not in report):
            accepted = {'status': 'ENV_INVALID', 'error': report.get('error', 'trusted environment failed')}
            rc = 2
        else:
            raise ValueError('verifier status/reward/exit code mismatch')
    except Exception as exc:
        accepted = {'status': 'ENV_INVALID', 'error': type(exc).__name__ + ': ' + str(exc)}
        rc = 2
    report_path.write_text(json.dumps(accepted, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(accepted, ensure_ascii=False, sort_keys=True))
    return rc

import hashlib
import re
from pathlib import PurePosixPath, PureWindowsPath

EXPECTED_REFS_SHA256 = "9a36a705486e900d22b2125c4c83469131f04e65cf6a3f5cc914216abbf4f2bc"


class SubmissionError(Exception):
    pass


class EnvironmentInvalid(Exception):
    pass


def _pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('non-finite JSON number')
    return value


def _reject_constant(text):
    raise ValueError('invalid JSON numeric constant: ' + text)


def strict_json_bytes(data):
    return json.loads(data.decode('utf-8'), object_pairs_hook=_pairs_no_duplicates,
                      parse_float=_finite_float, parse_constant=_reject_constant)


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def valid_sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def safe_relative_path(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise SubmissionError('manifest path must be a normalized relative POSIX path')
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or posix.as_posix() != value:
        raise SubmissionError('unsafe manifest path: ' + value)
    if any(part in ('', '.', '..') for part in posix.parts):
        raise SubmissionError('unsafe manifest path: ' + value)
    return value


def inventory_sha256(files):
    payload = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def load_private_refs(tests):
    path = Path(tests) / 'refs.json'
    if path.is_symlink() or not path.is_file() or sha256_file(path) != EXPECTED_REFS_SHA256:
        raise EnvironmentInvalid('private refs.json is missing, unsafe, or has a SHA-256 mismatch')
    try:
        refs = strict_json_bytes(path.read_bytes())
    except Exception as exc:
        raise EnvironmentInvalid('private refs.json is malformed') from exc
    if not isinstance(refs, dict) or set(refs) != {'schema', 'rubric', 'approved_reviews'} or refs['schema'] != 'mechanism-research-evaluator-refs/v1':
        raise EnvironmentInvalid('private refs schema or fields are invalid')
    rubric = refs['rubric']
    if not isinstance(rubric, dict):
        raise EnvironmentInvalid('private rubric is malformed')
    criteria = rubric.get('science_criteria')
    if not isinstance(criteria, list) or len(criteria) != 8 or any(
        not isinstance(c, dict) or set(c) != {'id', 'description'} or
        not isinstance(c['id'], str) or not c['id'].strip() or
        not isinstance(c['description'], str) or not c['description'].strip() for c in criteria
    ) or len({c['id'] for c in criteria}) != 8:
        raise EnvironmentInvalid('private rubric must define eight unique criteria')
    if (rubric.get('required_artifacts') != ['report.md', 'research.json', 'provenance.json'] or
        rubric.get('requires_supporting_artifact') is not True):
        raise EnvironmentInvalid('private rubric completeness contract is invalid')
    reviews = refs['approved_reviews']
    if not isinstance(reviews, list):
        raise EnvironmentInvalid('approved_reviews must be an array')
    criteria_ids = {c['id'] for c in criteria}
    review_fields = {'review_id', 'reviewer', 'reviewed_on', 'decision', 'rationale', 'candidate_inventory_sha256', 'candidate_files', 'criteria'}
    seen = set()
    for review in reviews:
        if not isinstance(review, dict) or set(review) != review_fields:
            raise EnvironmentInvalid('private review record has invalid fields')
        if not isinstance(review['review_id'], str) or not review['review_id'].strip() or review['review_id'] in seen:
            raise EnvironmentInvalid('private review ids must be non-empty and unique')
        seen.add(review['review_id'])
        who = review['reviewer']
        if not isinstance(who, dict) or set(who) != {'name', 'independent_of_candidate'} or not isinstance(who['name'], str) or not who['name'].strip() or who['independent_of_candidate'] is not True:
            raise EnvironmentInvalid('private review must identify an independent reviewer')
        if any(not isinstance(review[k], str) or not review[k].strip() for k in ('reviewed_on', 'rationale')):
            raise EnvironmentInvalid('private review date/rationale must be non-empty')
        if review['decision'] not in ('PASS', 'FAIL', 'UNVERIFIED'):
            raise EnvironmentInvalid('private review decision is invalid')
        bound = review['candidate_files']
        if not isinstance(bound, dict):
            raise EnvironmentInvalid('review candidate_files must be an object')
        for name, digest in bound.items():
            try:
                safe_relative_path(name)
            except SubmissionError as exc:
                raise EnvironmentInvalid('private review includes unsafe path') from exc
            if not valid_sha(digest):
                raise EnvironmentInvalid('private review includes invalid file hash')
        if not valid_sha(review['candidate_inventory_sha256']) or inventory_sha256(bound) != review['candidate_inventory_sha256']:
            raise EnvironmentInvalid('private review inventory digest is malformed')
        criterion_rows = review['criteria']
        if not isinstance(criterion_rows, dict) or set(criterion_rows) != criteria_ids:
            raise EnvironmentInvalid('private review must cover all eight science criteria')
        statuses = []
        for key, row in criterion_rows.items():
            if not isinstance(row, dict) or set(row) != {'status', 'rationale'} or row['status'] not in ('PASS', 'FAIL', 'UNVERIFIED') or not isinstance(row['rationale'], str) or not row['rationale'].strip():
                raise EnvironmentInvalid('private criterion review is malformed: ' + key)
            statuses.append(row['status'])
        if review['decision'] == 'PASS' and any(s != 'PASS' for s in statuses):
            raise EnvironmentInvalid('PASS review must pass every criterion')
        if review['decision'] == 'FAIL' and 'FAIL' not in statuses:
            raise EnvironmentInvalid('FAIL review must explicitly fail a criterion')
        if review['decision'] == 'UNVERIFIED' and 'FAIL' in statuses:
            raise EnvironmentInvalid('UNVERIFIED review conflicts with a failed criterion')
    return refs


def scan_candidate(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise SubmissionError('submission directory is missing or is a symlink')
    files = {}
    def walk_error(exc):
        raise SubmissionError('cannot inspect submission tree: ' + str(exc))
    for current, directories, names in os.walk(root, followlinks=False, onerror=walk_error):
        base = Path(current)
        for name in directories:
            path = base / name
            if path.is_symlink() or not path.is_dir():
                raise SubmissionError('submission contains unsafe directory: ' + path.relative_to(root).as_posix())
        for name in names:
            path = base / name
            rel = path.relative_to(root).as_posix()
            safe_relative_path(rel)
            if path.is_symlink() or not path.is_file():
                raise SubmissionError('submission contains unsafe file: ' + rel)
            try:
                files[rel] = sha256_file(path)
            except OSError as exc:
                raise SubmissionError('cannot read submitted file: ' + rel) from exc
    return files


def require_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise SubmissionError(name + ' must be a non-empty string')


def validate_candidate(root, refs):
    actual = scan_candidate(root)
    rubric = refs['rubric']
    for rel in rubric['required_artifacts']:
        if rel not in actual:
            raise SubmissionError('missing required artifact: ' + rel)
    try:
        report = (Path(root) / 'report.md').read_text(encoding='utf-8')
    except Exception as exc:
        raise SubmissionError('report.md is not valid UTF-8') from exc
    if not report.strip():
        raise SubmissionError('report.md is empty')
    try:
        research = strict_json_bytes((Path(root) / 'research.json').read_bytes())
        provenance = strict_json_bytes((Path(root) / 'provenance.json').read_bytes())
    except Exception as exc:
        raise SubmissionError('research.json or provenance.json is malformed') from exc
    if not isinstance(research, dict):
        raise SubmissionError('research.json must be a JSON object')
    for field in ('research_question', 'approach'):
        require_text(research.get(field), 'research.json.' + field)
    findings = research.get('findings')
    if not isinstance(findings, list) or not findings:
        raise SubmissionError('research.json.findings must be a non-empty array')
    decision = research.get('decision')
    if not isinstance(decision, dict):
        raise SubmissionError('research.json.decision must be an object')
    require_text(decision.get('status'), 'research.json.decision.status')
    require_text(decision.get('rationale'), 'research.json.decision.rationale')
    for field in ('uncertainties', 'limitations'):
        value = research.get(field)
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise SubmissionError('research.json.' + field + ' must be an array of strings')
    if not isinstance(provenance, dict):
        raise SubmissionError('provenance.json must be a JSON object')
    sources = provenance.get('sources')
    if not isinstance(sources, list) or not sources:
        raise SubmissionError('provenance.json.sources must be a non-empty array')
    source_ids = set()
    for source in sources:
        if not isinstance(source, dict):
            raise SubmissionError('each provenance source must be an object')
        for field in ('id', 'citation', 'locator', 'retrieved_on'):
            require_text(source.get(field), 'provenance source.' + field)
        if source['id'] in source_ids:
            raise SubmissionError('provenance source ids must be unique')
        source_ids.add(source['id'])
    for i, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise SubmissionError(f'finding {i} must be an object')
        require_text(finding.get('claim'), f'finding {i}.claim')
        require_text(finding.get('status'), f'finding {i}.status')
        ids = finding.get('evidence_ids')
        if not isinstance(ids, list) or not ids or any(not isinstance(x, str) or x not in source_ids for x in ids):
            raise SubmissionError(f'finding {i}.evidence_ids must reference listed sources')
    declared = provenance.get('files')
    if not isinstance(declared, dict) or 'provenance.json' in declared:
        raise SubmissionError('provenance.files must map other files and exclude itself')
    for rel in declared:
        safe_relative_path(rel)
    if set(declared) != set(actual) - {'provenance.json'}:
        raise SubmissionError('provenance file inventory does not match submitted files')
    for rel, record in declared.items():
        if not isinstance(record, dict) or not {'sha256', 'origin', 'role'} <= set(record):
            raise SubmissionError('file record requires sha256, origin, and role: ' + rel)
        if not valid_sha(record['sha256']) or record['sha256'] != actual[rel]:
            raise SubmissionError('file SHA-256 mismatch: ' + rel)
        require_text(record['origin'], 'file origin: ' + rel)
        require_text(record['role'], 'file role: ' + rel)
    supporting=set(actual)-set(rubric['required_artifacts'])
    if not supporting:
        raise SubmissionError('submission requires a supporting evidence artifact')
    return actual


def evaluate_review(refs, inventory):
    digest = inventory_sha256(inventory)
    matches = [r for r in refs['approved_reviews']
               if r['candidate_inventory_sha256'] == digest and r['candidate_files'] == inventory]
    if not matches:
        return {'status': 'REVIEW_REQUIRED', 'verification_coverage': 'SUBMISSION_INTEGRITY',
                'oracle_status': 'ORACLE_NOT_PROVIDED', 'scientific_status': 'SCIENTIFIC_REVIEW_REQUIRED',
                'error': 'complete submission has no approved review matching its full file inventory'}
    if len(matches) != 1:
        raise EnvironmentInvalid('multiple private reviews match the same candidate inventory')
    review = matches[0]
    if review['decision'] == 'UNVERIFIED':
        return {'status': 'REVIEW_REQUIRED', 'verification_coverage': 'SUBMISSION_INTEGRITY',
                'oracle_status': 'ORACLE_NOT_PROVIDED', 'scientific_status': 'UNVERIFIED',
                'error': 'matching independent review did not establish a science decision'}
    if review['decision'] == 'FAIL':
        failed = [key for key, row in review['criteria'].items() if row['status'] == 'FAIL']
        return {'status': 'FAIL', 'reward': 0, 'verification_coverage': 'INDEPENDENT_SCIENCE_REVIEW',
                'oracle_status': 'SCIENTIFIC_REVIEW_COMPLETE', 'failed_criteria': failed,
                'errors': [review['criteria'][key]['rationale'] for key in failed]}
    return {'status': 'PASS', 'reward': 1, 'verification_coverage': 'INDEPENDENT_SCIENCE_REVIEW',
            'oracle_status': 'SCIENTIFIC_REVIEW_PASS', 'review_id': review['review_id']}


def main():
    if len(sys.argv) != 2:
        print(json.dumps({'status': 'ENVIRONMENT_ERROR', 'error': 'usage: verify.py OUTPUT_DIR'}))
        return 2
    tests = Path(os.environ.get('TESTS', Path(__file__).resolve().parent)).resolve()
    try:
        refs = load_private_refs(tests)
        inventory = validate_candidate(Path(sys.argv[1]), refs)
        result = evaluate_review(refs, inventory)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result['status'] in ('PASS', 'REVIEW_REQUIRED') else 1
    except SubmissionError as exc:
        print(json.dumps({'status': 'FAIL', 'reward': 0, 'verification_coverage': 'SUBMISSION_INTEGRITY',
                          'errors': [str(exc)]}, ensure_ascii=False, sort_keys=True))
        return 1
    except EnvironmentInvalid as exc:
        print(json.dumps({'status': 'ENVIRONMENT_ERROR', 'error': str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as exc:
        print(json.dumps({'status': 'ENVIRONMENT_ERROR', 'error': type(exc).__name__ + ': ' + str(exc)},
                         ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == '__main__':
    if sys.argv[1:] == ['--grade']:
        raise SystemExit(_grade_entry())
    raise SystemExit(main())
