#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = 'ec933db733969d7adb1cd9bd452ea3c02f3437a7ddd7c42aea3aae0bdb8e987c'

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
# iI97IJVuLNyHqaMYFRgnY2VA3sR48PL/r8FMd7CzdvvHucLn3M7t3M7t3M7t3M7t3M7t3M7t3M7t3M7t3M7t52z/BkE+/OYAUAAA
