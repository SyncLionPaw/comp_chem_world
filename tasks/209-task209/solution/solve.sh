#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '182bf44e4e5fc914fa00ca78f3a82cd53619218a5ecd46bc5bb0b7cd9cdfcb14'

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
