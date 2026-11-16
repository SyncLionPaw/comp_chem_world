#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '7ec7e2f32d9317391c111e6997d8520a053f762bd9c49b36d4930fd645d519db'

from pathlib import Path
import base64, hashlib, os, shutil, subprocess, sys, tempfile

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

script = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='reference-solution-') as directory:
    temporary = Path(directory)
    archive = temporary / 'solution.tar.gz'
    digest = hashlib.sha256()
    with script.open() as source, archive.open('wb') as output:
        for line in source:
            if line.rstrip() == '# SOLUTION_DATA':
                break
        else:
            raise ValueError('Reference solution payload missing')
        for line in source:
            if not line.startswith('# '):
                raise ValueError('Invalid reference solution payload')
            data = base64.b64decode(line[2:].strip(), validate=True)
            digest.update(data)
            output.write(data)
    if digest.hexdigest() != EXPECTED:
        raise ValueError('Reference solution archive integrity failure')
    in_container = script.parent == Path('/solution')
    root = Path('/') if in_container else temporary / 'workspace'
    root.mkdir(exist_ok=True)
    backup = temporary / 'entry.sh'
    if in_container:
        shutil.copy2(script, backup)
    try:
        unpack(archive, root)
        result = subprocess.run(['bash', str(root / 'solution' / 'solve.sh'), *sys.argv[2:]], env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    finally:
        if in_container:
            # Only remove files from this reference payload, not user outputs.
            with tarfile.open(archive, 'r:gz') as bundle:
                paths = sorted([root / x.name for x in bundle.getmembers() if x.isfile()], key=lambda p: len(p.parts), reverse=True)
            for path in paths:
                path.unlink(missing_ok=True)
            for path in sorted(script.parent.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                if path.is_dir():
                    try: path.rmdir()
                    except OSError: pass
            shutil.copy2(backup, script)
    raise SystemExit(result.returncode)

PY
# SOLUTION_DATA
# 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
