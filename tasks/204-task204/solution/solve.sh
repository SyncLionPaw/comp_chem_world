#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '96627967f9ff63f7bc186397ebd9e7b2a9ae5b42720121e2fb1c3bb5b73bf84c'

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
