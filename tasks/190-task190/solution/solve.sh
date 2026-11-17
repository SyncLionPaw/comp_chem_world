#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '41041acc17412ab4d1013d4963f6db7f08b5907caf3d0349706b0a68a71aaed2'

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
