#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '3ce6306c1708b798866b340c9c94e0c8aa3c184218868dcdcd12be553c0aebda'

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
