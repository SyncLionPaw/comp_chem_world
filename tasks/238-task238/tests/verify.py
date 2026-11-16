#!/usr/bin/env python3
"""Run the packaged scientific verifier in a private temporary workspace."""
from pathlib import Path
import json, os, subprocess, sys, tempfile

def decode_bundle(source, target):
    import base64, hashlib, json
    digest = hashlib.sha256()
    with source.open('r', encoding='utf-8') as stream, target.open('wb') as output:
        header = []
        for line in stream:
            if line.strip() == '"chunks": [':
                metadata = json.loads(''.join(header) + '"chunks": []}')
                break
            header.append(line)
        else:
            raise ValueError('Missing reference payload')
        if metadata.get('encoding') != 'tar+gzip;base64':
            raise ValueError('Unsupported reference encoding')
        for line in stream:
            text = line.strip()
            if text == ']':
                break
            value = json.loads(text.removesuffix(','))
            if not isinstance(value, str):
                raise ValueError('Invalid reference block')
            data = base64.b64decode(value, validate=True)
            digest.update(data)
            output.write(data)
        else:
            raise ValueError('Incomplete reference payload')
        if stream.read().strip() != '}':
            raise ValueError('Invalid reference ending')
    if digest.hexdigest() != metadata.get('sha256'):
        raise ValueError('Reference archive integrity failure')

def unpack(archive, destination):
    import os, shutil, tarfile
    from pathlib import PurePosixPath
    with tarfile.open(archive, mode='r|gz') as bundle:
        for member in bundle:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or '..' in relative.parts or not relative.parts:
                raise ValueError('Unsafe reference path')
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                os.chmod(target, member.mode & 0o777)
            else:
                raise ValueError('Unsupported reference entry')

def link_if_available(target, candidates):
    if target.exists():
        return
    for candidate in candidates:
        candidate = Path(candidate)
        if candidate.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(candidate.resolve(), target_is_directory=candidate.is_dir())
            return

def validate_reference_manifest(source, reference_root, tests):
    """Validate the readable reference index against its original stored files."""
    import hashlib
    from pathlib import PurePosixPath
    header = []
    with source.open(encoding='utf-8') as stream:
        for line in stream:
            if line.strip() == '"chunks": [':
                break
            header.append(line)
        else:
            raise ValueError('Missing reference payload')
    manifest = json.loads(''.join(header) + '"chunks": []}')
    if manifest.get('schema') != 'scientific-verifier-reference-manifest':
        raise ValueError('Unsupported reference manifest')
    if not isinstance(manifest.get('case_id'), str) or not manifest['case_id']:
        raise ValueError('Missing scientific case identity')
    records = manifest.get('files')
    if not isinstance(records, list) or not records:
        raise ValueError('Missing reference file index')
    seen = set()
    for record in records:
        if not isinstance(record, dict) or record.get('storage') not in ('tests', 'packed'):
            raise ValueError('Invalid reference file record')
        relative = PurePosixPath(record.get('path', ''))
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise ValueError('Unsafe reference file index')
        key = (record['storage'], relative.as_posix())
        if key in seen:
            raise ValueError('Duplicate reference file index')
        seen.add(key)
        base = tests if record['storage'] == 'tests' else reference_root
        target = base.joinpath(*relative.parts)
        if target.is_symlink() or not target.is_file():
            raise ValueError('Missing reference file: ' + relative.as_posix())
        with target.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != record.get('sha256'):
            raise ValueError('Reference file integrity failure: ' + relative.as_posix())
    packed = {p.relative_to(reference_root).as_posix() for p in reference_root.rglob('*') if p.is_file()}
    indexed = {path for storage, path in seen if storage == 'packed'}
    if packed != indexed:
        raise ValueError('Reference payload and file index differ')
    for field in ('tolerances', 'reference_values'):
        definition = manifest.get(field)
        if not isinstance(definition, dict) or not isinstance(definition.get('sources'), list):
            raise ValueError('Missing scientific reference definitions: ' + field)
        for item in definition['sources']:
            if not isinstance(item, dict) or (item.get('storage'), item.get('path')) not in seen:
                raise ValueError('Reference definition points outside its file index')

def main():
    tests = Path(os.environ.get('TESTS', Path(__file__).parent)).resolve()
    app = Path(os.environ.get('APP', '/app')).resolve()
    logs = Path(os.environ.get('LOGS', '/logs/verifier')).resolve()
    logs.mkdir(parents=True, exist_ok=True)
    for name in ('reward.txt', 'reward.json'):
        (logs / name).unlink(missing_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='scientific-verifier-') as directory:
            root = Path(directory)
            archive = root / 'references.tar.gz'
            decode_bundle(tests / 'refs.json', archive)
            unpack(archive, root)
            archive.unlink()
            validate_reference_manifest(tests / 'refs.json', root, tests)
            source_case = tests.parent
            link_if_available(root / 'environment' / 'assets', [source_case / 'environment' / 'assets', app / 'environment' / 'assets'])
            for name in ('inputs', 'public', 'canonical-protocol.md', 'output-schema.json'):
                link_if_available(root / name, [app / name, source_case / name])
            environment = dict(os.environ, TESTS=str(root / 'tests'), INFRA_ROOT=str(root / 'tests'), APP=str(app), LOGS=str(logs), PYTHONDONTWRITEBYTECODE='1')
            for name, value in list(environment.items()):
                if value.startswith(str(tests) + '/'):
                    replacement = root / 'tests' / Path(value).relative_to(tests)
                    if replacement.exists():
                        environment[name] = str(replacement)
            result = subprocess.run(['bash', str(root / 'tests' / 'test.sh'), *sys.argv[1:]], env=environment)
            return result.returncode
    except Exception as error:
        for name in ('reward.txt', 'reward.json'):
            (logs / name).unlink(missing_ok=True)
        report = {'status': 'ENV_INVALID', 'scientific_status': 'UNRANKABLE', 'reward': None, 'eligible_for_success_ranking': False, 'message': str(error)}
        (logs / 'verify.json').write_text(json.dumps(report, indent=2) + '\n')
        print(str(error), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
