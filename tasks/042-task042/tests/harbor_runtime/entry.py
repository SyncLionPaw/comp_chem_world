"""Harbor terminal grading: native checks followed by bound independent review."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tomllib
import tempfile
import shutil
import stat

PUBLIC_LOGS = Path(os.environ.get("LOGS", "/logs/verifier"))
PRIVATE_LOGS = Path(tempfile.mkdtemp(prefix="bench07-private-grade-"))
os.environ["LOGS"] = str(PRIVATE_LOGS)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harbor_runtime.review import run_review
from harbor_runtime.pure_helpers import _manifest_outputs, json_hash
from harbor_runtime.references import normalized_protocol


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    path.chmod(0o600)


def terminal_reward(report):
    """Infrastructure/pending states never become a scientific zero or pass."""
    status, reward = report.get('status'), report.get('reward')
    if status == 'PASS' and reward == 1:
        return 1
    if status == 'FAIL' and reward == 0:
        return 0
    return None


def apply_review(initial, review):
    """Same necessary-criterion conjunction as each existing private review gate."""
    result = dict(initial)
    failed = any(row['verdict'] == 'FAIL' for row in review['criteria'])
    result.update(status='FAIL' if failed else 'PASS', reward=0 if failed else 1,
                  review=review, review_sha256=json_hash(review),
                  grading_route='harbor-native-checks-and-independent-scientific-review')
    return result


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def materialize_training_checkpoint_aliases(source_app, private_logs):
    """Snapshot the app and materialize only direct, local checkpoint aliases."""
    source_app = Path(source_app)
    private_logs = Path(private_logs)
    normalized_app = private_logs / 'normalized-app'
    if normalized_app.exists() or normalized_app.is_symlink():
        raise ValueError('normalized app destination already exists')
    shutil.copytree(source_app, normalized_app, symlinks=True)
    trace = normalized_app / 'training-trace'
    records = []
    if trace.is_symlink():
        raise ValueError('training-trace directory cannot be a symlink')
    if trace.exists():
        if not trace.is_dir():
            raise ValueError('training-trace is not a directory')
        for current, dirnames, filenames in os.walk(trace, followlinks=False):
            current_path = Path(current)
            for dirname in dirnames:
                directory = current_path / dirname
                if directory.is_symlink():
                    raise ValueError(f'training-trace directory alias is not permitted: {directory.relative_to(normalized_app)}')
            for filename in filenames:
                alias = current_path / filename
                if not alias.is_symlink():
                    continue
                relative = alias.relative_to(trace)
                raw_target = os.readlink(alias)
                if (os.path.isabs(raw_target) or len(relative.parts) != 1
                        or not alias.name.startswith('model.ckpt')):
                    raise ValueError(f'checkpoint alias must be a relative direct child of training-trace: {relative}')
                target = alias.parent / raw_target
                if target.parent != trace or target.name in {'', '.', '..'}:
                    raise ValueError(f'checkpoint alias target is outside training-trace: {relative} -> {raw_target}')
                try:
                    target_info = target.lstat()
                except OSError as exc:
                    raise ValueError(f'broken or inaccessible checkpoint alias: {relative} -> {raw_target}') from exc
                if (stat.S_ISLNK(target_info.st_mode) or not stat.S_ISREG(target_info.st_mode)
                        or not target.name.startswith('model.ckpt')):
                    raise ValueError(f'checkpoint alias target is not a direct regular checkpoint file: {relative} -> {raw_target}')
                size = target_info.st_size
                source_hash = _file_sha256(target)
                alias.unlink()
                digest = hashlib.sha256()
                copied = 0
                with target.open('rb') as reader, alias.open('xb') as writer:
                    for block in iter(lambda: reader.read(1024 * 1024), b''):
                        writer.write(block)
                        digest.update(block)
                        copied += len(block)
                alias_hash = digest.hexdigest()
                if copied != size or alias_hash != source_hash:
                    raise ValueError(f'checkpoint alias copy verification failed: {relative}')
                records.append({
                    'alias_path': str(relative),
                    'raw_link_target': raw_target,
                    'resolved_target': str(target.relative_to(trace)),
                    'sha256': alias_hash,
                    'size': copied,
                })
    return normalized_app, records


def main():
    # A Linux-owned parent protects Harbor's Desktop host bind from UID65534.
    parent = PUBLIC_LOGS.parent
    info = parent.lstat()
    if parent != Path('/logs') or parent.is_symlink() or info.st_uid != 0 or info.st_mode & 0o777 != 0o700:
        raise RuntimeError('Harbor log parent must be immutable root-owned mode 0700')
    app = Path(os.environ.get('APP', '/app'))
    tests = Path(os.environ.get('TESTS', '/tests'))
    logs = Path(os.environ.get('LOGS', '/logs/verifier'))
    for path in (app, tests, logs):
        if path.is_symlink():
            raise ValueError('unsafe grader root symlink')
    logs.mkdir(parents=True, exist_ok=True)
    logs.chmod(0o700)
    reward_path = logs / 'reward.txt'
    if reward_path.is_symlink():
        raise ValueError('unsafe reward path')
    reward_path.unlink(missing_ok=True)
    scoring_app, alias_records = materialize_training_checkpoint_aliases(app, PRIVATE_LOGS)
    source = Path('/opt/bench07-task')
    config = tomllib.loads((source / 'task.toml').read_text())
    metadata = config['metadata']
    metadata = dict(metadata, requirements={'inputs': metadata.get('inputs', [])})
    # The trusted verifier defaults to Agent policy even for a reference run.
    # An operator may explicitly select oracle mode; candidate files cannot do so.
    mode = os.environ.get('CCB_ANSWER_MODE', 'agent')
    if mode not in {'agent', 'oracle'}:
        raise ValueError('unsupported trusted answer mode')
    native_env = {key: os.environ[key] for key in ('PATH',) if key in os.environ}
    native_env.update(APP=str(scoring_app), TESTS=str(tests), LOGS=str(logs), HOME='/tmp',
                      CCB_ANSWER_MODE=mode, PYTHONDONTWRITEBYTECODE='1',
                      PYTHONNOUSERSITE='1', TF_CPP_MIN_LOG_LEVEL='2',
                      OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    report_path = logs / ('scoring-report.json' if metadata['case_id'] ==
                          'reline-02-density' else 'verification.json')

    def native(label):
        report_path.unlink(missing_ok=True)
        proc = subprocess.run([sys.executable, str(tests / 'verify.py'), '--runner'],
                              cwd=scoring_app, env=native_env, capture_output=True, text=True, timeout=360)
        (logs / f'{label}.stdout').write_text(proc.stdout)
        (logs / f'{label}.stderr').write_text(proc.stderr)
        if not report_path.is_file() or report_path.is_symlink():
            raise RuntimeError(f'native verifier produced no structured report (exit {proc.returncode})')
        report = json.loads(report_path.read_text())
        if proc.returncode not in {0, 1} or report.get('status') not in {'PASS', 'FAIL', 'REVIEW_REQUIRED'}:
            raise RuntimeError(f'native verifier error: {report.get("status")} (exit {proc.returncode})')
        write_json(logs / f'{label}.json', report)
        return report

    report = native('native-initial')
    protocol_bytes, protocol, _ = normalized_protocol(source)
    reported_manifest = report.get('submission_manifest')
    alias_rows = {row.get('path'): row for row in reported_manifest if isinstance(row, dict)} if isinstance(reported_manifest, list) else {}
    write_json(PRIVATE_LOGS / 'checkpoint-alias-normalization.json', {
        'source_app': str(app),
        'normalized_app': str(scoring_app),
        'normalized_manifest_sha256': report.get('submission_manifest_sha256'),
        'aliases': [
            {**record, 'source_path': str(app / 'training-trace' / record['alias_path']),
             'normalized_manifest_entry': alias_rows.get('training-trace/' + record['alias_path'])}
            for record in alias_records
        ],
    })
    reward = terminal_reward(report)
    if report.get('status') == 'REVIEW_REQUIRED':
        reward_path.unlink(missing_ok=True)
        before = _manifest_outputs(protocol['expected_outputs'], scoring_app)
        if report.get('submission_manifest') != before or report.get('submission_manifest_sha256') != json_hash(before):
            raise RuntimeError('native manifest does not match collected Harbor artifacts')
        confirmed = native('native-confirmation')
        if confirmed.get('status') != 'REVIEW_REQUIRED' or confirmed.get('submission_manifest') != before:
            raise RuntimeError('native review eligibility changed on confirmation')
        completed = run_review(tests, scoring_app, logs, source, None, confirmed)
        if completed is not None:
            review, invocation = completed
            if _manifest_outputs(protocol['expected_outputs'], scoring_app) != before:
                raise RuntimeError('submission changed after review')
            if (review['protocol_sha256'] != hashlib.sha256(protocol_bytes).hexdigest()
                    or review['submission_manifest_sha256'] != json_hash(before)):
                raise RuntimeError('independent review binding mismatch')
            write_json(logs / 'scientific-review.json', review)
            write_json(logs / 'judge-invocation.json', invocation)
            report = apply_review(confirmed, review)
            reward = terminal_reward(report)
        else:
            report = dict(confirmed, reward=None,
                          review={'reason': 'Independent review is unavailable, inconclusive or invalid; see review-error.json.'})
    write_json(logs / 'verification.json', report)
    if reward is None:
        # Unresolved REVIEW / pending states: emit 0 so Harbor records a score
        # instead of RewardFileNotFoundError (truthful eval, not agent capability).
        report = dict(report, reward=0)
        write_json(logs / 'verification.json', report)
        reward_path.write_text('0\n')
        reward_path.chmod(0o600)
        print('REVIEW_REQUIRED: independent scientific review remains unresolved; reward=0')
        return 0
    reward_path.write_text(f'{reward}\n')
    reward_path.chmod(0o600)
    print(f'{report["status"]}: reward={reward}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        logs = Path(os.environ.get('LOGS', '/logs/verifier'))
        if not logs.is_symlink():
            logs.mkdir(parents=True, exist_ok=True)
            write_json(logs / 'harbor-error.json', {'status': 'INFRA_ERROR', 'reward': 0,
                       'error': f'{type(exc).__name__}: {exc}'})
            (logs / 'reward.txt').write_text('0\n')
            (logs / 'reward.txt').chmod(0o600)
        print('INFRA_ERROR: see harbor-error.json; reward=0', file=sys.stderr)
        raise SystemExit(2)

    finally:
        # Docker Desktop host bind mounts do not provide Linux UID isolation.
        # Keep live scoring state in native tmpfs; export only after replay ends.
        if not PUBLIC_LOGS.is_symlink():
            PUBLIC_LOGS.mkdir(parents=True, exist_ok=True)
            (PUBLIC_LOGS / 'reward.txt').unlink(missing_ok=True)
            (PUBLIC_LOGS / 'reward.json').unlink(missing_ok=True)
            for artifact in PRIVATE_LOGS.iterdir():
                if artifact.is_file() and not artifact.is_symlink():
                    shutil.copyfile(artifact, PUBLIC_LOGS / artifact.name)
        shutil.rmtree(PRIVATE_LOGS)
