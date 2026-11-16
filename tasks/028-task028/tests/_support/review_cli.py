"""Evaluator-only preparation and signing of an exact-snapshot Case28 review."""
import argparse
import base64
import importlib.util
import json
import shutil
from pathlib import Path


def load_verifier(task):
    spec = importlib.util.spec_from_file_location('case28_review_verifier', task / 'tests/verify.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def prepare(task, final, bundle, source_job=None):
    # A fresh evaluator-owned copy preserves the original attempt and task.
    if bundle.exists():
        raise ValueError('Bundle already exists; use a new directory')
    if final.is_symlink() or not final.is_dir():
        raise ValueError('Final must be a real directory')
    verifier = load_verifier(task)
    verifier.validate_evaluator_inputs(task / 'tests', final)
    provenance, manifest = verifier.validate_submission(final)
    bundle.mkdir(parents=True, mode=0o700)
    shutil.copytree(task, bundle / 'task 28', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(final, bundle / 'final', symlinks=True)
    # Bind bytes after copying, including files beyond the three declared outputs.
    if verifier.candidate_manifest(bundle / 'final') != manifest:
        raise ValueError('Candidate changed during preparation; discard bundle and retry')
    refs = json.loads((task / 'tests/refs.json').read_text())
    draft = {
        'schema_version': verifier.ASSESSMENT_SCHEMA, 'case_id': verifier.CASE_ID,
        'status': 'COMPLETE', 'rubric_sha256': verifier.digest(task / 'tests/protected/review-rubric.json'),
        'candidate_manifest': manifest,
        'candidate_manifest_sha256': __import__('hashlib').sha256(canonical(manifest)).hexdigest(),
        'reference_integrity': {'source_digest': refs['source_digest'],
            'evaluator_sources': {x['path']: x['sha256'] for x in refs['evaluator_sources']}},
        'reviewer': {'id': '', 'role': '', 'reviewed_at': ''},
        'judgments': {name: {'verdict': None, 'reason': '', 'evidence_paths': [], 'evidence_notes': []}
                      for name in verifier.REVIEW_CRITERIA},
        'trusted_receipts': [],
        'execution_authentication': {run['id']: {'status': None, 'reason': '', 'evidence_paths': []}
                                     for run in provenance['executions'] if run['kind'] == 'new_computation'},
        'preflight': {name: None for name in ('reference_integrity_verified',
            'verifier_isolated_from_candidate_processes', 'resources_independently_accounted',
            'other_case_and_evaluator_isolation_verified', 'candidate_manifest_bound',
            'docker_environment_smoke_verified')},
    }
    if source_job is not None and not (source_job / 'config.json').is_file():
        raise ValueError('Source job must be a recorded Harbor job directory')
    write_json(bundle / 'review-draft.json', draft)
    write_json(bundle / 'bundle.json', {'status': 'AWAITING_INDEPENDENT_REVIEW',
        'original_task': str(task.resolve()), 'original_final': str(final.resolve()),
        'candidate_manifest_sha256': draft['candidate_manifest_sha256']})


def task_manifest(task):
    import hashlib
    result = {}
    for path in sorted(task.rglob('*')):
        rel = path.relative_to(task).as_posix()
        if path.is_symlink():
            raise ValueError('Unsafe symlink in evaluator task: ' + rel)
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        if (rel in {'tests/protected/review-assessment.json', 'tests/protected/review-public-key.pem'}
                or rel.startswith('tests/protected/receipt-snapshots/')):
            continue
        if path.is_file():
            result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def evaluator_key(path, bundle):
    if path.is_symlink() or not path.is_file() or path.resolve().is_relative_to(bundle.resolve()):
        raise ValueError('Supply the evaluator public key from outside the review bundle')
    public = path.read_bytes()
    return public, 'sha256:' + __import__('hashlib').sha256(public).hexdigest()


def finalize(bundle, review, private_key, trusted_task=None, *, public_key):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    task, final = bundle / 'task 28', bundle / 'final'
    # The trust anchor is chosen by the evaluator, never by editable bundle
    # metadata or by Python code shipped inside the review bundle.
    trusted_task = trusted_task or Path(__file__).resolve().parents[2]
    if (bundle.is_symlink() or not bundle.is_dir() or task.is_symlink() or not task.is_dir()
            or final.is_symlink() or not final.is_dir()
            or task.resolve() == trusted_task.resolve()
            or not task.resolve().is_relative_to(bundle.resolve())
            or not final.resolve().is_relative_to(bundle.resolve())):
        raise ValueError('Review bundle must contain separate real task and final directories')
    if any('__pycache__' in f.parts or f.suffix == '.pyc' for f in task.rglob('*')):
        raise ValueError('Review bundle contains executable bytecode caches')
    if task_manifest(task) != task_manifest(trusted_task):
        raise ValueError('Review bundle task differs from the evaluator trusted task')
    verifier = load_verifier(trusted_task)
    assessment = verifier.json_no_duplicates(review, environment=True)
    if assessment.get('status') != 'COMPLETE' or 'signature' in assessment:
        raise ValueError('Supply a complete, unsigned independent assessment')
    private_key = private_key.resolve(strict=True)
    if private_key.is_relative_to(bundle.resolve()) or private_key.is_relative_to(trusted_task.resolve()):
        raise ValueError('Keep the evaluator private key outside the task and review bundle')
    key = serialization.load_pem_private_key(private_key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('Reviewer key must be Ed25519')
    public, pin = evaluator_key(public_key, bundle)
    key_bytes = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pinned = serialization.load_pem_public_key(public)
    if key_bytes != pinned.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw):
        raise ValueError('Signing key does not match the evaluator public key')
    assessment['signature'] = base64.b64encode(key.sign(canonical(assessment))).decode('ascii')
    protected = task / 'tests/protected/review-assessment.json'
    previous = protected.read_bytes()
    bundled_public = protected.with_name('review-public-key.pem')
    created_public = False
    try:
        with bundled_public.open('xb') as stream:
            created_public = True
            stream.write(public)
        write_json(protected, assessment)
        result = verifier.verify(final, task / 'tests', review_key_sha256=pin)
        if result['status'] not in ('PASS', 'FAIL') or result.get('scientific_review') == 'candidate contract/evidence failure':
            raise ValueError('Review not finalized: ' + json.dumps(result, ensure_ascii=False))
        # A signature alone does not establish scientific merit; normal verifier
        # checks every criterion, receipt, reference and exact candidate manifest.
        if not result.get('reviewer'):
            raise ValueError('Review was not accepted by the scientific assessment path')
    except BaseException:
        protected.write_bytes(previous)
        if created_public:
            bundled_public.unlink(missing_ok=True)
        raise
    write_json(bundle / 'review-verification.json', result)
    write_json(bundle / 'bundle.json', {'status': 'REVIEWED', 'scientific_status': result['status'],
        'reward': result['reward'], 'candidate_manifest_sha256': assessment['candidate_manifest_sha256'],
        'trusted_task': str(trusted_task.resolve()),
        'trusted_task_manifest_sha256': __import__('hashlib').sha256(canonical(task_manifest(trusted_task))).hexdigest()})


def regrade(bundle, source_job, trusted_task, *, public_key):
    """Revalidate immediately before a native Harbor regrade; never execute bundle code."""
    import subprocess
    import tempfile
    task = bundle / 'task 28'
    final = bundle / 'final'
    if (bundle.is_symlink() or task.is_symlink() or final.is_symlink()
            or not task.is_dir() or not final.is_dir()
            or task.resolve() == trusted_task.resolve()):
        raise ValueError('Unsafe review bundle directories')
    if any('__pycache__' in f.parts or f.suffix == '.pyc' for f in task.rglob('*')):
        raise ValueError('Review bundle contains executable bytecode caches')
    if task_manifest(task) != task_manifest(trusted_task):
        raise ValueError('Task changed after review; refusing native regrade')
    verifier = load_verifier(trusted_task)
    public, pin = evaluator_key(public_key, bundle)
    result = verifier.verify(final, task / 'tests', review_key_sha256=pin)
    if result['status'] not in ('PASS', 'FAIL') or not result.get('reviewer'):
        raise ValueError('Signed independent review is not final or no longer matches candidate')
    # Fresh evaluator-only launch snapshot. Only assessment/receipt data comes
    # from the checked bundle; all executable task bytes come from trusted_task.
    launch = Path(tempfile.mkdtemp(prefix='regrade-', dir=bundle))
    sealed = launch / 'task 28'
    shutil.copytree(trusted_task, sealed, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(task / 'tests/protected/review-assessment.json', sealed / 'tests/protected/review-assessment.json')
    (sealed / 'tests/protected/review-public-key.pem').write_bytes(public)
    receipts = task / 'tests/protected/receipt-snapshots'
    if receipts.exists():
        shutil.copytree(receipts, sealed / 'tests/protected/receipt-snapshots', dirs_exist_ok=True)
    # Regenerate from the evaluator-chosen original job, ignoring editable config.
    tasks = {}
    for path in source_job.glob('*/result.json'):
        trial = json.loads(path.read_text())
        name = trial.get('task_name')
        original = trial.get('config', {}).get('task', {}).get('path')
        if name and original:
            tasks[name] = sealed.resolve() if verifier.CASE_ID in name else Path(original).resolve()
    if not any(verifier.CASE_ID in name for name in tasks):
        raise ValueError('Source job has no recorded Case28 trial')
    config = {'job_name': launch.name, 'jobs_dir': str(bundle.resolve() / 'jobs'),
        'source_jobs': [{'action': 'regrade', 'type': 'local', 'path': str(source_job.resolve())}],
        'tasks': [{'path': str(path)} for path in tasks.values()],
        'n_concurrent_trials': 1, 'retry': {'max_retries': 0},
        'verifier': {'env': {'CCB_CASE08_REVIEW_KEY_SHA256': pin}}}
    for path in sealed.rglob('*'):
        if path.is_file():
            path.chmod(0o444)
    config_path = launch / 'regrade-config.json'
    write_json(config_path, config)
    # Use the installed Harbor entrypoint directly; no agent or computation rerun.
    import sys
    sibling = Path(sys.executable).parent / 'harbor'
    executable = str(sibling) if sibling.is_file() else shutil.which('harbor')
    if executable is None:
        raise ValueError('Harbor is not available in the current Python environment')
    subprocess.run([executable, 'run', '-c', str(config_path)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--task', type=Path, default=Path(__file__).resolve().parents[2])
    prep.add_argument('--final', type=Path, required=True)
    prep.add_argument('--bundle', type=Path, required=True)
    prep.add_argument('--source-job', type=Path, help='Recorded Harbor job containing this attempt')
    done = commands.add_parser('finalize')
    done.add_argument('--bundle', type=Path, required=True)
    done.add_argument('--review', type=Path, required=True)
    done.add_argument('--private-key', type=Path, required=True)
    done.add_argument('--task', type=Path, default=Path(__file__).resolve().parents[2],
                      help='Evaluator-chosen trusted frozen task; never taken from bundle metadata')
    replay = commands.add_parser('regrade')
    replay.add_argument('--bundle', type=Path, required=True)
    replay.add_argument('--source-job', type=Path, required=True)
    replay.add_argument('--task', type=Path, default=Path(__file__).resolve().parents[2])
    for command in (done, replay):
        command.add_argument('--public-key', type=Path, required=True, help='Evaluator public key outside the bundle')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.task, args.final, args.bundle, args.source_job)
    elif args.command == 'finalize':
        finalize(args.bundle, args.review, args.private_key, args.task, public_key=args.public_key)
    else:
        regrade(args.bundle, args.source_job, args.task, public_key=args.public_key)


if __name__ == '__main__':
    main()
