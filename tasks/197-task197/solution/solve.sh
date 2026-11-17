#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '6c623e009aaf9afb814fa6486bb83ff7493ab00f37151bbc70dcd211b6ae4440'

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
