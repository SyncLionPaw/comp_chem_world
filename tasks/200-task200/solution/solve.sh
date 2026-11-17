#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '3505d3da071336212fba948bb1b5b761cb75280e50ccf3561aa8886dfa604d9d'

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
