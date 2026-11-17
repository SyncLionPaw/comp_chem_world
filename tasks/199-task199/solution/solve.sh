#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '54915cf69e6297fe502c32822477cf40afcbdc84c6cd6f043b11838b89e1e9ef'

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
