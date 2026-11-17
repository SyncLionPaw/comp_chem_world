#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '14d18648ac2bf912be299fd36fb1f364ec0d1b7f8cb475acaf17e34243d30df7'

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
