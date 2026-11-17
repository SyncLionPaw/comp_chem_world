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
