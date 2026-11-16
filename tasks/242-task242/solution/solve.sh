#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '1e91746b64202540101fda6ed9f9d476d9393778d231f4b2a9d9f4e337c47c63'

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
