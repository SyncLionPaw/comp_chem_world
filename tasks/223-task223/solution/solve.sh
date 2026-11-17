#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '486dc8ebae0b335470df7dd575f11080723d9289d9910895705265ac6d81e439'

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
