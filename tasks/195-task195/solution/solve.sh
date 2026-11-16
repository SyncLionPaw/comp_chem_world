#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '407dbdeafd93da463d0c2b6c979a189e2a1db228870b4bd19baa19d7eee2356c'

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
