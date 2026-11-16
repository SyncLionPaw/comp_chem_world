# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Analyse CO2 structural fluctuations in water and potassium-containing interfacial trajectories.
from __future__ import annotations
'Translate the scientific verifier protocol to the CompChemBench grader contract.'
import json
import math
import os
from pathlib import Path
import subprocess
import sys

def _grade_entry():
    app = Path(os.environ.get('APP', '/app'))
    tests = Path(os.environ.get('TESTS', Path(__file__).resolve().parent))
    logs = Path(os.environ.get('LOGS', '/logs/verifier'))
    logs.mkdir(parents=True, exist_ok=True)
    reward_file = logs / 'reward.txt'
    reward_file.unlink(missing_ok=True)
    report_file = logs / 'verification.json'
    report_file.unlink(missing_ok=True)
    try:
        proc = subprocess.run([sys.executable, str(tests / 'verify.py'), str(app / 'final')], capture_output=True, text=True, timeout=540)
        (logs / 'verify.stdout.log').write_text(proc.stdout)
        (logs / 'verify.stderr.log').write_text(proc.stderr)
        result = json.loads(proc.stdout)
        if not isinstance(result, dict):
            raise ValueError('verifier result must be an object')
        status = result.get('status')
        reward = result.get('reward')
        if status in {'PASS', 'FAIL'}:
            expected = int(status == 'PASS')
            if type(reward) not in {int, float} or not math.isfinite(reward) or reward != expected or (proc.returncode != (0 if expected else 1)):
                raise ValueError('inconsistent scientific status/reward/exit code')
            report_file.write_text(json.dumps(result, ensure_ascii=False) + '\n')
            reward_file.write_text(str(expected) + '\n')
            print(json.dumps(result, ensure_ascii=False))
            return proc.returncode
        if status == 'REVIEW_REQUIRED' and proc.returncode == 2 and ('reward' not in result):
            report_file.write_text(json.dumps(result, ensure_ascii=False) + '\n')
            print(json.dumps(result, ensure_ascii=False))
            return 0
        elif status == 'ENVIRONMENT_ERROR' and proc.returncode == 2 and ('reward' not in result):
            result = {**result, 'scientific_status': status, 'status': 'ENV_INVALID'}
        else:
            raise ValueError('unknown/inconsistent verifier status or exit code')
    except Exception as exc:
        result = {'status': 'ENV_INVALID', 'error': type(exc).__name__ + ': ' + str(exc)}
    report_file.write_text(json.dumps(result, ensure_ascii=False) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    return 2
if __name__ == '__main__' and sys.argv[1:] == ['--grade']:
    raise SystemExit(_grade_entry())
'Complete verifier for the frozen finite-trajectory geometry task, not electronic charge.'
import csv, hashlib, json, math, os, sys
from pathlib import Path
"Replay analysis in the evaluator's isolated runtime; development uses trusted author code."
import json as _bench36_json, os as _bench36_os, re as _bench36_re, shutil as _bench36_shutil, subprocess as _bench36_subprocess, sys as _bench36_sys, tempfile as _bench36_tempfile
from pathlib import Path as _bench36_Path

def _bench36_replay(root, output, required, normalize_json=None, attachments=()):
    with _bench36_tempfile.TemporaryDirectory(prefix='local-analysis-replay-') as directory:
        work = _bench36_Path(directory)
        generated = work / 'result'
        tests = _bench36_Path(_bench36_os.environ.get('TESTS', root / 'tests'))
        command = [_bench36_sys.executable, str((output / 'analysis.py').resolve()), str((root / 'environment/assets').resolve()), str(generated)]
        env = {'PATH': _bench36_os.defpath, 'LANG': 'C.UTF-8', 'PYTHONHASHSEED': '0', 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
        for key in ['APP', 'TESTS']:
            if key in _bench36_os.environ:
                env[key] = _bench36_os.environ[key]
        try:
            execution = _bench36_subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=180)
        except _bench36_subprocess.TimeoutExpired:
            return {'status': 'FAIL', 'error': 'analysis replay timeout'}
        if execution.returncode:
            missing = _bench36_re.search("ModuleNotFoundError: No module named '([A-Za-z0-9_.]+)'", execution.stderr)
            if missing:
                return {'status': 'ENVIRONMENT_ERROR', 'error': 'analysis replay dependency unavailable: ' + missing.group(1)}
            return {'status': 'FAIL', 'error': 'analysis replay exited ' + str(execution.returncode)}
        for filename in required:
            if not (generated / filename).is_file():
                return {'status': 'FAIL', 'error': 'analysis replay did not produce ' + filename}
        for filename in required:
            if filename.endswith('.json'):
                try:
                    regenerated = _bench36_json.loads((generated / filename).read_text())
                    submitted = _bench36_json.loads((output / filename).read_text())
                    if normalize_json is not None:
                        regenerated = normalize_json(filename, regenerated)
                        submitted = normalize_json(filename, submitted)
                    if regenerated != submitted:
                        return {'status': 'FAIL', 'error': 'analysis replay differs from submitted ' + filename}
                except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
                    return {'status': 'FAIL', 'error': 'analysis replay invalid ' + filename + ': ' + type(exc).__name__ + ': ' + str(exc)}
        for filename in attachments:
            _bench36_shutil.copyfile(output / filename, generated / filename)
        try:
            check = _bench36_subprocess.run([_bench36_sys.executable, str(tests / 'verify.py'), str(generated), '--replay-result'], cwd=work, env=env, capture_output=True, text=True, timeout=180)
        except _bench36_subprocess.TimeoutExpired:
            return {'status': 'ENVIRONMENT_ERROR', 'error': 'nested evaluator timeout'}
        except OSError as exc:
            return {'status': 'ENVIRONMENT_ERROR', 'error': 'nested evaluator launch: ' + str(exc)}
        try:
            result = _bench36_json.loads(check.stdout)
        except ValueError:
            return {'status': 'ENVIRONMENT_ERROR', 'error': 'nested evaluator output unparseable'}
        if result.get('status') == 'ENVIRONMENT_ERROR':
            return result
        if check.returncode or result.get('status') != 'PASS':
            return {'status': 'FAIL', 'error': 'replayed scientific artifacts fail independent verification'}
    return {'status': 'PASS'}

def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()

def close(x, y, tol):
    return isinstance(x, (int, float)) and (not isinstance(x, bool)) and math.isfinite(x) and (abs(x - y) <= tol)
BLOCK_FIELDS = ('co_short_mean_A', 'co_long_mean_A', 'oco_mean_deg')

def block_values(block, context):
    if isinstance(block, dict):
        if set(block) != set(BLOCK_FIELDS):
            raise ValueError(context + ': block object must contain exactly ' + ', '.join(BLOCK_FIELDS))
        return [block[key] for key in BLOCK_FIELDS]
    if isinstance(block, list) and len(block) == 3:
        return block
    raise ValueError(context + ': block must be a three-number array or a named mean object')

def normalize_geometry_json(filename, data):
    if filename == 'summary.json':
        for name, row in data['systems'].items():
            blocks = row['block_means']
            if not isinstance(blocks, list) or len(blocks) != 5:
                raise ValueError(name + ': block_means must be a list of five blocks')
            row['block_means'] = [block_values(block, name + ': block ' + str(i)) for i, block in enumerate(blocks)]
    return data

def main():
    root = Path(os.environ.get('APP', Path(__file__).resolve().parents[1]))
    tests = Path(os.environ.get('TESTS', root / 'tests'))
    output = Path(sys.argv[1])
    try:
        import numpy
        import ase
        refs = json.loads((tests / 'refs.json').read_text())
        for rel, expected in refs['asset_hashes'].items():
            if sha(root / 'environment' / rel) != expected.removeprefix('sha256:'):
                raise RuntimeError('evaluation asset hash mismatch: ' + rel)
        ref = refs['reference']
        if sha(Path(__file__).resolve()) != refs['verifier_sha256']:
            raise RuntimeError('consolidated evaluator verifier hash mismatch')
    except Exception as exc:
        print(json.dumps({'status': 'ENVIRONMENT_ERROR', 'error': str(exc)}))
        return 2
    errors = []
    try:
        candidate = json.loads((output / 'summary.json').read_text())
        if set(candidate['systems']) != set(ref['summary']['systems']):
            errors.append('system set')
        for name, target in ref['summary']['systems'].items():
            row = candidate['systems'][name]
            for key, expected in target.items():
                if key == 'block_means':
                    actual = row[key]
                    if not isinstance(actual, list) or len(actual) != 5:
                        errors.append(name + ': block_means must be a list of five blocks')
                        continue
                    for i in range(5):
                        values = block_values(actual[i], name + ': block ' + str(i))
                        for j in range(3):
                            if not close(values[j], expected[i][j], 0.0001 if j < 2 else 0.01):
                                errors.append(name + ': block ' + str(i) + ': incorrect/nonfinite ' + BLOCK_FIELDS[j])
                elif key.startswith('n_'):
                    if type(row[key]) is not int or row[key] != expected:
                        errors.append(name + ': ' + key)
                elif not close(row[key], expected, 0.0001 if key.endswith('_A') else 0.01):
                    errors.append(name + ': ' + key)
        if candidate['conclusions'] != ref['summary']['conclusions'] or any((type(x) is not bool for x in candidate['conclusions'].values())):
            errors.append('structural conclusions')
        if candidate['interpretation'] != ref['summary']['interpretation'] or any((type(x) is not bool for x in candidate['interpretation'].values())):
            errors.append('geometry/electronic-charge/uncertainty inference')
        data = list(csv.DictReader((output / 'geometry.csv').open()))
        expected_rows = ref['rows']
        if len(data) != len(expected_rows):
            errors.append('sample count')
        else:
            for actual, expected in zip(data, expected_rows):
                if actual['system'] != expected[0] or int(actual['frame']) != expected[1]:
                    errors.append('frame identity')
                    break
                for field, target, tol in zip(['co_short_A', 'co_long_A', 'oco_deg'], expected[2:], [0.0001, 0.0001, 0.01]):
                    if not close(float(actual[field]), target, tol):
                        errors.append('per-frame geometry')
                        break
        for filename in ['analysis.py', 'report.md']:
            if not (output / filename).is_file() or (output / filename).stat().st_size == 0:
                errors.append('missing ' + filename)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        errors.append(type(exc).__name__ + ': ' + str(exc))
    if not errors and '--replay-result' not in sys.argv:
        result = _bench36_replay(root, output, ['geometry.csv', 'summary.json'], normalize_json=normalize_geometry_json, attachments=('analysis.py', 'report.md'))
        if result['status'] == 'ENVIRONMENT_ERROR':
            print(json.dumps(result))
            return 2
        if result['status'] != 'PASS':
            errors.append(result['error'])
    print(json.dumps({'status': 'FAIL' if errors else 'PASS', 'reward': 0 if errors else 1, 'errors': errors}, ensure_ascii=False))
    return 1 if errors else 0
if __name__ == '__main__':
    sys.exit(main())
