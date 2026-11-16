#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '1e6bbf0b7ac40278267ae5e924b8830ba67e8c4153bb9bb70cdd99bac0bf01f3'

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
