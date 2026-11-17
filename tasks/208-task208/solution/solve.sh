#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '5262ece8878ede2b50ce7e88462b20963c2983b63c5c7f6e9cd63290642ecbf3'

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
# 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
# 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
