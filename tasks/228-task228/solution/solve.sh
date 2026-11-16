#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '5cf47ec1861be7c39c6518c7e9658afb2106769940b0ab032bac6aa436792ea2'

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
