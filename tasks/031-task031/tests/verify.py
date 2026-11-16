#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Interaction Hierarchy and Modularity of Acidic Tracts.
"""Self-contained local verifier: deterministic checks, local replay, and scoring.

The verifier re-runs the submitted analysis.py against the public inputs, compares
the regenerated outputs, and applies the frozen scientific criteria to award the
reward. Evaluator-held replay/assessment receipts, when both are supplied, replace
the local replay; a submission that fails any check scores zero, not REVIEW_REQUIRED.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

TESTS = Path(os.environ.get('TESTS', Path(__file__).resolve().parent)).resolve()
APP = Path(os.environ.get('APP', TESTS.parent)).resolve()
ASSETS = APP / 'environment' / 'assets'
VERSION = 'local-science-verifier/3.1-case-03-tracts'
FILES = ['pmf.csv', 'interventions.json', 'analysis.py', 'report.md']


class ScientificFailure(ValueError):
    pass


class EvaluationError(ValueError):
    pass


def canonical_tract_matrix(matrix, error_type=ValueError):
    """Accept canonical or `mut`-suffixed outer mutant keys; keep tract axes exact."""
    axes = ('A0', 'A1', 'A2')
    if not isinstance(matrix, dict):
        raise error_type('tract_response.matrix must be an object')
    result = {}
    for key, row in matrix.items():
        canonical = key[:-3] if key in ('A0mut', 'A1mut', 'A2mut') else key
        if canonical not in axes or canonical in result:
            raise error_type('tract_response.matrix has unknown or ambiguous mutant rows')
        if not isinstance(row, dict) or set(row) != set(axes):
            raise error_type('tract_response.matrix rows must be keyed exactly A0, A1, A2')
        result[canonical] = row
    if set(result) != set(axes):
        raise error_type('tract_response.matrix must contain A0, A1, A2 mutant rows')
    return result



def numeric_table(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))

def numeric_close(actual, expected, label, atol=1e-7, rtol=1e-5):
    actual = float(actual)
    if not math.isfinite(actual) or abs(actual - expected) > atol + rtol * abs(expected):
        raise ValueError(label + ': serialized value does not match recomputation')

def numeric_interval(value, label):
    low, high = map(float, value)
    if not math.isfinite(low + high) or low >= high:
        raise ValueError(label + ': invalid interval')
    return low, high

def numeric_coordinate_rows(rows, key, label):
    result = []
    seen = set()
    for row in rows:
        try:
            coordinate = float(row[key])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(label + ': coordinate must be numeric') from error
        if not math.isfinite(coordinate):
            raise ValueError(label + ': coordinate must be finite')
        if coordinate in seen:
            raise ValueError(label + ': duplicate coordinate')
        seen.add(coordinate)
        result.append((coordinate, row))
    return sorted(result, key=lambda item: item[0])

def numeric_aligned_rows(input_rows, output_rows, key, label):
    inputs = numeric_coordinate_rows(input_rows, key, label + ' input')
    outputs = numeric_coordinate_rows(output_rows, key, label + ' output')
    if len(inputs) != len(outputs):
        raise ValueError(label + ': output must preserve every input bin')
    aligned = []
    for (expected, source), (_, output) in zip(inputs, outputs):
        numeric_close(output[key], expected, label + ' coordinate')
        aligned.append((source, output))
    return aligned

def numeric_case03_interval(value, label):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(label + ': expected a JSON-encoded two-number array') from error
        if (not isinstance(value, list) or len(value) != 2
                or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)):
            raise ValueError(label + ': expected a JSON array containing exactly two numbers')
    return numeric_interval(value, label)

def numeric_tracts(s, assets, checked, pending):
    raw = numeric_table(assets / 'tracts_WT.csv')
    pmf = numeric_table(s / 'pmf.csv')
    aligned = numeric_aligned_rows(raw, pmf, 'r_A', 'PMF radius grid')
    for r, v in aligned:
        for tract in ('A0', 'A1', 'A2'):
            g = float(r[tract])
            value = v[tract + '_kcalmol']
            if g == 0:
                if value.strip():
                    raise ValueError('g=0 requires blank PMF')
            else:
                expected = -.00198720425864083 * 300 * math.log(g)
                try:
                    numeric_close(value, expected, 'PMF kcal/mol transform')
                except ValueError:
                    if (not math.isfinite(expected) or not isinstance(value, str)
                            or value.strip() != format(expected, '.6f')):
                        raise
    result = json.loads((s / 'interventions.json').read_text())
    lo, hi = numeric_case03_interval(result['window_A'], 'PD first-shell window')
    rows = [r for r in numeric_table(assets / 'mutants_PD.csv') if lo <= float(r['r_A']) <= hi]
    if len(rows) < 3:
        raise ValueError('PD window has insufficient bins')
    for condition in ('WT', 'A0mut', 'A1mut', 'A2mut'):
        peak = max(rows, key=lambda r: float(r[condition]))
        for field, expected in (('r_A', float(peak['r_A'])), ('height', float(peak[condition])),
                                ('author_error', float(peak[condition + '_author_error']))):
            numeric_close(result['PD_peaks'][condition][field], expected, condition + ' peak ' + field)
    response = result.get('tract_response', {})
    if response.get('metric') == 'relative_peak_change':
        lo, hi = numeric_case03_interval(response['window_A'], 'tract response window')
        baseline = {t: max(float(r[t]) for r in raw if lo <= float(r['r_A']) <= hi) for t in ('A0','A1','A2')}
        if min(baseline.values()) <= 0:
            raise ValueError('relative response needs positive WT peak')
        matrix = canonical_tract_matrix(response.get('matrix'))
        for mutant in ('A0', 'A1', 'A2'):
            for tract in ('A0', 'A1', 'A2'):
                mutant_rows = numeric_table(assets / ('mutants_' + tract + '.csv'))
                peak = max(float(r[mutant + 'mut']) for r in mutant_rows if lo <= float(r['r_A']) <= hi)
                numeric_close(matrix[mutant][tract], (peak - baseline[tract]) / baseline[tract], 'tract response')
        checked.append('declared relative-peak response matrix')
    else:
        pending.append('custom tract-response metric needs independent replay')
    checked.extend(['PMF transform and units', 'declared-window PD peaks and reported author error'])
    pending.extend(['first-shell window validity and sensitivity', 'A2 effect and A0/A1 uncertainty overlap',
                    'rank significance and pair-PMF interpretation'])

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def canonical_sha(value):
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def strict_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    def bad(value):
        raise ValueError('nonfinite JSON number: ' + value)
    def floating(value):
        number = float(value)
        if not math.isfinite(number):
            bad(value)
        return number
    if Path(path).stat().st_size > 32 * 1024 * 1024:
        raise ValueError('JSON exceeds evaluator resource limit')
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs,
                      parse_constant=bad, parse_float=floating)


def manifest(root):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ScientificFailure('submission/replay root must be a regular directory')
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ScientificFailure('symlink/escaping submission file')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha(path)
        elif not path.is_dir():
            raise ScientificFailure('nonregular submission entry')
    return result


def require(condition, message):
    if not condition:
        raise ScientificFailure(message)


def prose(value, label):
    require(isinstance(value, str) and bool(value.strip()), label + ' is missing/nontext')


def prose_or_summary(value, label):
    if isinstance(value, str) and value.strip():
        return
    require(isinstance(value, dict) and isinstance(value.get('summary'), str)
            and bool(value['summary'].strip()), label + ' is missing/nontext')


def evaluator_file(path, submission):
    path = Path(path).absolute()
    if not path.is_file() or path.is_symlink() or path.resolve().is_relative_to(submission.resolve()):
        raise EvaluationError('receipt must be an evaluator-controlled regular file outside submission')
    for ancestor in path.parents:
        if ancestor.is_symlink():
            raise EvaluationError('symlink in evaluator receipt path')
    return path


def preflight():
    try:
        refs = strict_json(TESTS / 'refs.json')
        case = refs['case_id']
        if refs.get('schema') != 'bench05-local-science-refs/v2':
            raise EvaluationError('unsupported refs schema')
        if case != 'case-03-tracts':
            raise EvaluationError('unknown task identity')
        if set(refs['asset_hashes']) != {'assets/mutants_A2.csv', 'assets/mutants_PD.csv', 'assets/mutants_A1.csv', 'assets/tracts_WT.csv', 'assets/mutants_A0.csv'}:
            raise EvaluationError('wrong or incomplete public input manifest')
        for rel, checksum in refs['asset_hashes'].items():
            path = APP / 'environment' / rel
            if not path.is_file() or sha(path) != checksum.removeprefix('sha256:'):
                raise EvaluationError('evaluator input missing/corrupt: ' + rel)
        rubric = refs['rubric']
        criteria = [c['criterion'] for c in refs['criteria'] if c['necessary']]
        if rubric['case_id'] != case or set(rubric['criteria']) != set(criteria):
            raise EvaluationError('rubric does not cover exactly the frozen necessary criteria')
        policy = {k: refs[k] for k in ('case_id', 'asset_hashes', 'source_provenance', 'criteria', 'rubric', 'grading_mode')}
        if refs.get('policy_sha256') != canonical_sha(policy):
            raise EvaluationError('task policy digest mismatch')
        import numpy
        import scipy
        return refs, rubric
    except EvaluationError:
        raise
    except Exception as error:
        raise EvaluationError('invalid evaluator resources/dependencies: ' + str(error)) from error


def structure(case, final):
    require(case == 'case-03-tracts', 'unsupported task identity')
    for name in FILES:
        require((final / name).is_file() and (final / name).stat().st_size > 0,
                'missing/empty required output: ' + name)
        if name.endswith('.json'):
            require(isinstance(strict_json(final / name), dict), name + ' must be an object')
        if name.endswith('.csv'):
            with (final / name).open() as stream:
                reader = csv.DictReader(stream)
                require(reader.fieldnames and len(reader.fieldnames) == len(set(reader.fieldnames)),
                        'duplicate/missing CSV header: ' + name)
                require(len(list(reader)) > 0, 'empty CSV: ' + name)
    obj = strict_json(final / 'interventions.json')
    prose_or_summary(obj.get('supported_rank'), 'supported_rank')
    prose(obj.get('uncertainty_definition'), 'uncertainty_definition')
    require(isinstance(obj.get('indistinguishable_contrasts'), list), 'unresolved contrasts required')


def numbers(case, final):
    require(case == 'case-03-tracts', 'unsupported task identity')
    checked, pending = [], []
    numeric_tracts(final, ASSETS, checked, pending)
    return checked, pending


def compare_outputs(case, final, replay):
    """Compare scientifically meaningful values, allowing row order and float precision."""
    def normalize_output_command(value):
        import shlex
        try:
            tokens = shlex.split(value)
        except ValueError:
            return None
        found = 0
        for index, token in enumerate(tokens):
            if token == '--output-dir':
                if index + 1 >= len(tokens) or tokens[index + 1] not in {'/app/final', '/app/replay-output'}:
                    return None
                tokens[index + 1] = '<REPLAY_OUTPUT_ROOT>'
                found += 1
            elif token.startswith('--output-dir='):
                path = token.split('=', 1)[1]
                if path not in {'/app/final', '/app/replay-output'}:
                    return None
                tokens[index:index + 1] = ['--output-dir', '<REPLAY_OUTPUT_ROOT>']
                found += 1
        return tuple(tokens) if found == 1 else None
    def compare(a, b, path=()):
        if path == ('tract_response', 'matrix'):
            try:
                a = canonical_tract_matrix(a)
                b = canonical_tract_matrix(b)
            except ValueError:
                return False
        if path == ('provenance', 'command') and isinstance(a, str) and isinstance(b, str):
            if a == b:
                return True
            left, right = normalize_output_command(a), normalize_output_command(b)
            return left is not None and left == right
        if isinstance(a, bool) or isinstance(b, bool):
            return type(a) is type(b) and a == b
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return math.isfinite(float(a)) and math.isfinite(float(b)) and math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-7)
        if isinstance(a, dict) and isinstance(b, dict):
            return a.keys() == b.keys() and all(compare(a[k], b[k], path + (k,)) for k in a)
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(compare(x, y, path + (i,)) for i, (x, y) in enumerate(zip(a, b)))
        return type(a) is type(b) and a == b
    for name in FILES:
        if name in ['analysis.py', 'report.md']:
            continue  # Code is pinned separately; prose is reviewed, not byte-matched.
        path = replay / name
        require(path.is_file() and not path.is_symlink(), 'replay did not produce ' + name)
        if name.endswith('.json'):
            require(compare(strict_json(final / name), strict_json(path)), 'analysis replay JSON differs: ' + name)
        elif name.endswith('.csv'):
            def read(file):
                with file.open() as stream:
                    rows = list(csv.DictReader(stream))
                for row in rows:
                    for key, value in row.items():
                        if value is None:
                            raise ScientificFailure('malformed CSV row')
                        try:
                            row[key] = float(value)
                        except ValueError:
                            pass
                return sorted(rows, key=lambda row: tuple((k, str(v)) for k, v in sorted(row.items())))
            a, b = read(final / name), read(path)
            # Sorting scientific keys avoids ordering by slightly different float strings.
            require(compare(a, b), 'analysis replay CSV differs: ' + name)


def check_replay(path, final, case, refs, files):
    receipt_path = evaluator_file(path, final)
    receipt = strict_json(receipt_path)
    if receipt.get('schema_version') != 'local-replay/v1' or receipt.get('case_id') != case:
        raise EvaluationError('invalid replay receipt identity')
    if receipt.get('submission_files') != files or receipt.get('input_hashes') != refs['asset_hashes']:
        raise EvaluationError('replay receipt belongs to different submission/inputs')
    if receipt.get('analysis_sha256') != files['analysis.py']:
        raise EvaluationError('replayed analysis identity differs')
    mode = receipt.get('mode')
    if mode not in ['author_reference', 'candidate_evaluation']:
        raise EvaluationError('unknown replay provenance')
    if mode == 'candidate_evaluation' and receipt.get('isolation') != 'isolated_data_only_runtime':
        raise EvaluationError('candidate replay must be isolated from evaluator resources')
    if not receipt.get('execution_id') or not receipt.get('command'):
        raise EvaluationError('replay execution identity/command missing')
    if receipt.get('exit_code') != 0:
        raise ScientificFailure('submitted analysis execution failed')
    replay = receipt_path.parent / receipt['output_path']
    if not replay.resolve().is_relative_to(receipt_path.parent.resolve()) or replay.resolve().is_relative_to(final.resolve()):
        raise EvaluationError('replay artifacts must be separate evaluator-held files')
    if manifest(replay) != receipt.get('output_files'):
        raise EvaluationError('replay artifacts changed after receipt')
    compare_outputs(case, final, replay)
    return receipt_path, mode


def check_review_data(assessment, replay_sha256, final, refs, rubric, files):
    expected = {'schema_version': 'local-science-assessment/v1', 'case_id': refs['case_id'],
                'submission_files': files, 'input_hashes': refs['asset_hashes'],
                'rubric_sha256': canonical_sha(rubric), 'replay_receipt_sha256': replay_sha256}
    for key, value in expected.items():
        if assessment.get(key) != value:
            raise EvaluationError('scientific assessment binding differs: ' + key)
    reviewer = assessment.get('reviewer', {})
    if not reviewer.get('id') or not reviewer.get('role') or not assessment.get('reviewed_at'):
        raise EvaluationError('scientific reviewer attribution/time missing')
    preflight = assessment.get('preflight', {})
    for key in ['evaluation_stage_controlled', 'references_reviewed', 'execution_and_code_reviewed', 'method_neutrality_checked']:
        if preflight.get(key) is not True:
            raise EvaluationError('incomplete scientific assessment: ' + key)
    judgments = assessment.get('judgments', {})
    if set(judgments) != set(rubric['criteria']):
        raise EvaluationError('scientific assessment criterion coverage differs')
    failures = []
    for criterion, judgment in judgments.items():
        if judgment.get('verdict') not in ['PASS', 'FAIL'] or not str(judgment.get('rationale', '')).strip():
            raise EvaluationError('missing criterion judgment/reason: ' + criterion)
        citations = judgment.get('evidence', [])
        if not citations:
            raise EvaluationError('criterion lacks exact submission evidence: ' + criterion)
        for citation in citations:
            relative = citation.get('path', '')
            if relative not in files or citation.get('sha256') != files[relative]:
                raise EvaluationError('criterion evidence binding differs: ' + criterion)
            quote = citation.get('quote')
            if not isinstance(quote, str) or not quote.strip() or quote not in (final / relative).read_text():
                raise EvaluationError('criterion citation is not present in assessed text: ' + criterion)
        if judgment['verdict'] == 'FAIL':
            failures.append(criterion + ': ' + judgment['rationale'])
    return failures


def check_review(path, replay_path, final, refs, rubric, files):
    review_path = evaluator_file(path, final)
    assessment = strict_json(review_path)
    return check_review_data(assessment, sha(replay_path), final, refs, rubric, files)


def check_approval(approval, final, refs, rubric, files):
    if approval.get('schema') != 'bench05-local-oracle-approval/v1':
        raise EvaluationError('invalid Oracle approval schema')
    expected = {'case_id': refs['case_id'], 'policy_sha256': refs['policy_sha256'],
                'verifier_sha256': sha(TESTS / 'verify.py'),
                'test_entry_sha256': sha(TESTS / 'test.sh'), 'submission_files': files}
    for key, value in expected.items():
        if approval.get(key) != value:
            raise EvaluationError('Oracle approval binding differs: ' + key)
    replay = approval.get('replay', {})
    required = ('execution_id', 'image_id', 'command', 'exit_code', 'analysis_sha256',
                'input_hashes', 'submission_files', 'output_files', 'isolation')
    if any(key not in replay or replay[key] is None for key in required):
        raise EvaluationError('Oracle approval replay attestation is incomplete')
    if type(replay.get('exit_code')) is not int or replay['exit_code'] != 0:
        raise EvaluationError('Oracle approval replay did not exit successfully')
    if (not isinstance(replay['execution_id'], str) or not replay['execution_id'].strip()
            or not isinstance(replay['image_id'], str) or not replay['image_id'].strip()
            or not isinstance(replay['command'], list) or not replay['command']
            or not all(isinstance(part, str) and part for part in replay['command'])
            or replay['isolation'] != 'isolated_data_only_runtime'):
        raise EvaluationError('Oracle approval replay identity/command/isolation is invalid')
    outputs = {name: digest for name, digest in files.items() if name != 'analysis.py'}
    if (replay.get('input_hashes') != refs['asset_hashes']
            or replay.get('submission_files') != files
            or replay.get('analysis_sha256') != files.get('analysis.py')
            or replay.get('output_files') != outputs):
        raise EvaluationError('Oracle approval replay output/input binding differs')
    reviewer = approval.get('reviewer', {})
    preflight = approval.get('preflight', {})
    if not reviewer.get('id') or not reviewer.get('role') or not approval.get('reviewed_at'):
        raise EvaluationError('Oracle reviewer attribution/time missing')
    assessment = {'schema_version': 'local-science-assessment/v1', 'case_id': refs['case_id'],
                  'submission_files': files, 'input_hashes': refs['asset_hashes'],
                  'rubric_sha256': canonical_sha(rubric),
                  'replay_receipt_sha256': canonical_sha(replay), 'reviewer': reviewer,
                  'reviewed_at': approval['reviewed_at'], 'preflight': preflight,
                  'judgments': approval.get('judgments', {})}
    failures = check_review_data(assessment, assessment['replay_receipt_sha256'],
                                 final, refs, rubric, files)
    require(not failures, '; '.join(failures))
    return replay


def local_replay(final, workdir):
    """Re-run the submitted analysis against the public inputs and compare its outputs."""
    import subprocess
    command = [sys.executable, str(final / 'analysis.py'),
               '--input-dir', str(ASSETS), '--output-dir', str(workdir)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=600,
                                   cwd=str(workdir))
    except subprocess.TimeoutExpired:
        raise ScientificFailure('analysis replay exceeded the local time limit')
    if completed.returncode != 0:
        raise ScientificFailure('analysis replay failed: ' + completed.stderr[-800:])


def science(case, final):
    """Frozen scientific criteria: attenuation hierarchy, self-response modularity, report obligations."""
    require(case == 'case-03-tracts', 'unsupported task identity')
    obj = strict_json(final / 'interventions.json')
    heights = {key: float(value['height']) for key, value in obj['PD_peaks'].items()}
    require(heights['A2mut'] < heights['A0mut'] and heights['A2mut'] < heights['A1mut']
            and heights['A0mut'] < heights['WT'] and heights['A1mut'] < heights['WT'],
            'neutralization must attenuate the PD first shell, with A2 the largest nominal effect')
    response = obj.get('tract_response')
    matrix = canonical_tract_matrix(response.get('matrix') if isinstance(response, dict) else None,
                                    ScientificFailure)
    for mutant in ('A0', 'A1', 'A2'):
        row = matrix[mutant]
        require(float(row[mutant]) <= 0.0,
                'self-neutralization must not increase the matching tract correlation')
    report = (final / 'report.md').read_text().lower()
    require('binding free energy' in report or '结合自由能' in report,
            'report must state the pair-PMF/free-energy caveat')
    require('error' in report or '误差' in report,
            'report must discuss the unresolved error semantics')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--submission', type=Path, required=True)
    parser.add_argument('--replay', type=Path)
    parser.add_argument('--assessment', type=Path)
    args = parser.parse_args(argv)
    result = {'verifier_version': VERSION, 'implementation': 'implemented',
              'runtime_bound': False, 'qualification': 'not_granted'}
    try:
        refs, rubric = preflight()
        case = refs['case_id']
        final = args.submission / 'final' if (args.submission / 'final').is_dir() else args.submission
        files = manifest(final)
        try:
            structure(case, final)
            checked, specialized = numbers(case, final)
        except (ScientificFailure, ValueError, KeyError, TypeError, AttributeError,
                OverflowError, OSError, UnicodeError, RecursionError, csv.Error) as error:
            raise ScientificFailure(str(error)) from error
        result.update(case_id=case, checked=checked, layers=['L1', 'deterministic numerical checks'])
        if not args.replay or not args.assessment:
            workdir = Path(tempfile.mkdtemp(prefix='local-replay-'))
            try:
                local_replay(final, workdir)
                compare_outputs(case, final, workdir)
            finally:
                shutil.rmtree(workdir, ignore_errors=True)
            checked.append('local analysis replay')
            science(case, final)
            checked.append('deterministic scientific criteria')
            result.update(status='PASS', scientific_pass=True, reward=1,
                          layers=['L1 complete deliverables', 'L2 local analysis replay',
                                  'L3 deterministic scientific criteria'],
                          criteria_passed=list(rubric['criteria']))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        # A submission root may contain final/ plus other Agent-owned files.
        # Reject receipts from that entire root, not merely from final/.
        evaluator_file(args.replay, args.submission)
        evaluator_file(args.assessment, args.submission)
        replay_path, mode = check_replay(args.replay, final, case, refs, files)
        result['evaluation_mode'] = mode
        failures = check_review(args.assessment, replay_path, final, refs, rubric, files)
        require(not failures, '; '.join(failures))
        result.update(status='PASS', scientific_pass=True, reward=1,
                      layers=['L1 complete deliverables', 'L2 replay and reviewed execution', 'L3 all evidence-backed criteria'],
                      criteria_passed=list(rubric['criteria']))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except ScientificFailure as error:
        result.update(status='FAIL', scientific_pass=False, reward=0, errors=[str(error)])
        print(json.dumps(result, ensure_ascii=False))
        return 1
    except Exception as error:
        result.update(status='ENVIRONMENT_ERROR', scientific_pass=False, errors=[type(error).__name__ + ': ' + str(error)])
        print(json.dumps(result, ensure_ascii=False))
        return 2


def grade_main():
    import contextlib, io
    logs = Path(os.environ['LOGS'])
    app = Path(os.environ['APP']).resolve()
    report = {}
    try:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(['--submission', str(app)])
        report = json.loads(buffer.getvalue())
        if report.get('status') == 'ENVIRONMENT_ERROR':
            report['status'] = 'INFRA_ERROR'
        expected = {'PASS': (0, 1), 'FAIL': (1, 0), 'INFRA_ERROR': (2, None)}
        if report.get('status') not in expected:
            raise EvaluationError('unknown verifier status')
        code, reward = expected[report['status']]
        if rc != code or report.get('reward') != reward:
            raise EvaluationError('inconsistent verifier status, exit code or reward')
        logs.mkdir(parents=True, exist_ok=True)
        (logs/'stdout.log').write_text(json.dumps(report,ensure_ascii=False)+'\n')
        (logs/'stderr.log').write_text('')
        (logs/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        if 'reward' in report:
            (logs/'reward.txt').write_text(str(report['reward'])+'\n')
        else:
            (logs/'reward.txt').unlink(missing_ok=True)
        print(json.dumps(report,ensure_ascii=False))
        return rc
    except Exception as error:
        logs.mkdir(parents=True, exist_ok=True)
        report={'status':'INFRA_ERROR','scientific_pass':False,'errors':[type(error).__name__+': '+str(error)]}
        (logs/'stdout.log').write_text(json.dumps(report,ensure_ascii=False)+'\n')
        (logs/'stderr.log').write_text('')
        (logs/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        (logs/'reward.txt').unlink(missing_ok=True)
        print(json.dumps(report,ensure_ascii=False))
        return 2


def entrypoint():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--grade', action='store_true')
    known, rest = parser.parse_known_args()
    return grade_main() if known.grade else main(rest)


if __name__ == '__main__':
    sys.exit(entrypoint())

