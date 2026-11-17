#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '6cfa864caa9bf0e67d248fa4a580c895fb97373c24e65235683d15e460a78538'

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
