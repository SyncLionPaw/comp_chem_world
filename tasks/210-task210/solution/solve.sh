#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '0b59531e2f98d09398b2208ede735b8b91bf3d704ae9ac19025b013198a99ee2'

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
