#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = 'e560d2f4e32aeb0844906587c72d39f5fcbc916c868026ed4441b3bca33a07a6'

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
