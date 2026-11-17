#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = 'b31715d920a71f22995ffb203989285222317548829a50fbd0596510189c26a5'

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
