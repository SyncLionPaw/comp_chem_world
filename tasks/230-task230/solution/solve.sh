#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = 'e2a4eddb8110f42bf6f7f80639723991df066bb9546ece86298e76c56bc43f15'

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
