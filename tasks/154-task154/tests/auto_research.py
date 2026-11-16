#!/usr/bin/env python3
"""Open research: validate evidence packaging, then require a bound independent review.

Packaging checks do not establish scientific correctness. No precomputed answer,
fixed COF model or reference workflow is required. Pending review awards no credit.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

CASE_ID = 'compchemworld/bench23-task-154'
VERSION = "auto-research-v1"
OUTPUT_DIR = 'final'
CRITERIA = {'research_design': 'Independent inputs, reproducible methods and suitable scientific comparisons.', 'executed_evidence': 'Traceable quantitative work, data and evidence with plans and historical work identified separately.', 'claim_scope': 'Reasoned claims, uncertainty, alternative explanations and a defensible stopping point.', 'refinement_validity': 'Assess identity, chemical plausibility, numerical validity and independent support for the refinement or bounded stop decision.'}
MAX_JSON = 2 * 1024 * 1024

class CandidateError(ValueError):
    pass

class ReviewError(ValueError):
    pass

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def unique_pairs(items):
    result = {}
    for k, v in items:
        if k in result:
            raise ValueError('duplicate JSON key')
        result[k] = v
    return result

def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
        raise ValueError('JSON file is unavailable, symlinked or exceeds 2 MiB')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON')))

def snapshot(final):
    if final.is_symlink() or not final.is_dir():
        raise CandidateError('final/ is missing or symlinked')
    rows = []
    size = 0
    for base, dirs, files in os.walk(final, followlinks=False):
        for name in dirs + files:
            p = Path(base) / name
            mode = p.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise CandidateError('research record contains a link or unsupported file type')
        for name in files:
            p = Path(base) / name
            size += p.stat().st_size
            if size > 8 * 1024**3 or len(rows) >= 20000:
                raise CandidateError('research record exceeds supported snapshot limits')
            rows.append({'path': p.relative_to(final).as_posix(), 'bytes': p.stat().st_size,
                         'sha256': sha(p)})
    return sorted(rows, key=lambda row: row['path'])

def evaluate(app):
    report = {'task_id': CASE_ID, 'criteria_version': VERSION, 'status': 'REVIEW_REQUIRED',
              'science_validated': False, 'problems': [],
              'scope': 'Open research; packaging checks are not scientific approval. '
                       'Scientific scoring awaits an independent review.'}
    try:
        final = app / OUTPUT_DIR
        rows = snapshot(final)
        index = {row['path']: row for row in rows}
        if not {'report.md', 'provenance.json'} <= index.keys():
            raise CandidateError('report.md and provenance.json are required')
        try:
            text = (final / 'report.md').read_text(encoding='utf-8')
        except (OSError, UnicodeError) as exc:
            raise CandidateError('report.md is not readable UTF-8') from exc
        if not text.strip():
            raise CandidateError('research report is empty')
        try:
            provenance = read_json(final / 'provenance.json')
        except (OSError, ValueError, UnicodeError) as exc:
            raise CandidateError('provenance.json is invalid: ' + str(exc)) from exc
        sources = provenance.get('sources') if isinstance(provenance, dict) else None
        if (not isinstance(sources, list) or not sources
                or any(not isinstance(s, (str, dict)) or not s for s in sources)):
            raise CandidateError('provenance must contain a nonempty sources list')
        claims = provenance.get('claims')
        if not isinstance(claims, list) or not claims:
            raise CandidateError('provenance must contain a nonempty claims list')
        for claim in claims:
            if (not isinstance(claim, dict) or not isinstance(claim.get('claim'), str)
                    or not claim['claim'].strip() or not isinstance(claim.get('evidence'), list)
                    or not claim['evidence'] or any(not isinstance(path, str) or path not in index
                    or not path.startswith('evidence/') for path in claim['evidence'])):
                raise CandidateError('claims must link findings to submitted evidence files')
        rubric_sha256 = canonical(CRITERIA)
        report.update(artifact_manifest_sha256=canonical(rows), artifact_manifest=rows, rubric=CRITERIA,
                      rubric_sha256=rubric_sha256, verifier_sha256=sha(Path(__file__)),
                      review_required=True)
        review_path = os.environ.get('CCB_OPEN_RESEARCH_REVIEW_FILE')
        review_digest = os.environ.get('CCB_OPEN_RESEARCH_REVIEW_SHA256')
        if not review_path and not review_digest:
            report['problems'].append('Independent scientific review is pending.')
            return report, 0
        if not review_path or not review_digest:
            raise ReviewError('trusted review path and hash must be configured together')
        path = Path(review_path)
        if not path.is_absolute() or path.is_relative_to(app) or path.resolve().is_relative_to(app.resolve()):
            raise ReviewError('review must be supplied outside candidate APP')
        if any(p.is_symlink() for p in [path, *path.parents]):
            raise ReviewError('trusted review path contains a symlink')
        if sha(path) != review_digest:
            raise ReviewError('trusted review hash mismatch')
        review = read_json(path)
        bindings = {'schema': 'compchemworld.independent-auto-research-review/v1',
                    'task_id': CASE_ID, 'criteria_version': VERSION,
                    'artifact_manifest_sha256': report['artifact_manifest_sha256'],
                    'rubric_sha256': rubric_sha256, 'verifier_sha256': report['verifier_sha256']}
        if not isinstance(review, dict) or any(review.get(k) != v for k, v in bindings.items()):
            raise ReviewError('trusted review is stale or has invalid identity bindings')
        if (not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip()
                or review.get('reviewer_kind') != 'human'):
            raise ReviewError('trusted review must identify an independent human reviewer')
        criteria = review.get('criteria')
        if not isinstance(criteria, dict) or set(criteria) != set(CRITERIA):
            raise ReviewError('trusted review does not assess every scientific criterion')
        for key, value in criteria.items():
            if (not isinstance(value, dict) or value.get('status') not in {'PASS', 'FAIL', 'UNRESOLVED'}
                    or not isinstance(value.get('finding'), str) or not value['finding'].strip()
                    or not isinstance(value.get('evidence'), list) or not value['evidence']
                    or any(not isinstance(p, str) or p not in index for p in value['evidence'])):
                raise ReviewError('trusted review finding or evidence references are invalid: ' + key)
        statuses = {value['status'] for value in criteria.values()}
        status = 'FAIL' if 'FAIL' in statuses else ('REVIEW_REQUIRED' if 'UNRESOLVED' in statuses else 'PASS')
        if review.get('status') != status:
            raise ReviewError('trusted review conclusion contradicts its criterion findings')
        report.update(status=status, science_validated=status == 'PASS',
                      review_required=status == 'REVIEW_REQUIRED', review_sha256=review_digest,
                      review=review)
        if status != "REVIEW_REQUIRED":
            report["reward"] = int(status == "PASS")
        return report, 0
    except CandidateError as exc:
        report.update(status='FAIL', reward=0)
        report['problems'].append(str(exc))
        return report, 0
    except (ReviewError, OSError, ValueError, UnicodeError) as exc:
        report.update(status='ENV_INVALID')
        report.pop('reward', None)
        report['problems'].append(str(exc))
        return report, 2

def main():
    app = Path(os.environ.get('APP', '/app'))
    logs = Path(os.environ.get('LOGS', '/logs/verifier'))
    if not logs.is_absolute() or logs.is_symlink():
        return 2
    logs.mkdir(parents=True, exist_ok=True)
    for name in ['reward.txt', 'reward.json', 'verification.json']:
        path = logs / name
        if path.is_symlink():
            return 2
        path.unlink(missing_ok=True)
    report, rc = evaluate(app)
    (logs / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    if 'reward' in report:
        (logs / 'reward.txt').write_text(str(report['reward']) + '\n')
    elif report['status'] == 'REVIEW_REQUIRED':
        (logs / 'reward.json').write_text('{}\n')
    print(json.dumps({'status': report['status'], 'science_validated': report['science_validated']}))
    return rc

if __name__ == '__main__':
    sys.exit(main())
