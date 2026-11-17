#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '75ea6938274bd9706c38a9532302185b9482e5a1360ba88cb060135267b718e7'

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
