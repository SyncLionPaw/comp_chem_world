#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = 'b2f37a64d410c92e6d99a417e1e9b16b5a905b087a85f62b94d57302d17a38a3'

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
