#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '6f20997f6785e8763df18064f42ecae77418d00a6a0a3f8a0e798054079d8682'

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
