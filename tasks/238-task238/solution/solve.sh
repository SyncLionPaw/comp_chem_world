#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '4b214bb78f9789472c7cd30eb868a174a74c6504eed74fb7fff858412579a293'

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
