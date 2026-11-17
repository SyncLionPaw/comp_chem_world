#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '0e0163a09bac05c316b78b1ac4ea63cadea4bf30b7fb486e814aab785db94142'

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
# H4sICAAAAAAA/3NvbHV0aW9uLnRhcgDtV1mP2zYQ7rN+xdQtIgmR5NveHCqQpF7kKQk227y4hkBLI5uJLKok5V2n6H/vkLKyR7fZBkiDFtD3YFPkDGc4nItKFLXmouyzkhWHjxhVh+++NgaE2WRi/wm3/0fz0awdN/PD4Wwy/Q4GX12TO1ArzSSJ/xay/oPo9XqnvOQawwteZuICrB8orqBWvNwAlig3B8h4nqPEMkUFa8yFRKhQhkyLHZRC7ljBPzLjRxFt6PBdJaQGJjcVkwqDVO2D90qUwY7pbUAG11xpnionl8Rf0WTB13DkekOfThW3zNEzual3WOo35kt6/pMqYlmWsOO054YhL6taKzfQhwpjwx9I/K3mErP4XNZ4F4uoNfF8hoXFVWQVMGyKxMrYHCEqBMuU57GoEdp3DR8qHZlV148ksizReKk9nzYpVbxcOWQvyDTwEuTSVRorleTKXT124ILrLVxt5rnlHsNMuw9zY1TtZTpwN67/0M1VRFZ0fT8SFZaeD0xB/liKCxUXZEyPFqOfearPSDxZKfd9BzTfIcnPSWXtEenSNTNJRaJ9MDrRnFWKdlk9sTfNbzMIzYoE393JkWGhWbz0MGx5l4OV36czGr9IUlGX2l1ZPjRcLdXKIS9TEavoJJmXkdZ0TrJITKctE8V2VUFqFHRMI8cPslpa3yLNY3umZThchc1osCKnukzYWiVWnWRB2ibkm4nRIaY1b8cqj9YDu+77QYXsQ6JFYv9vknuGvlXTD3e8vPr6y8GCgpfIZKIKupLr29gB6Xrl6NGRVOJGolJ0Fs+qf9QpslvQlQlJl/fJZbg1NSs36BljkM38cOg/boha85mQIqfcmOUlXy3dz5jDXfUt1cPhfXRBu5u9mBt8xxnSlhWFuKCAWe4/zdrL3hu9iQF4Dvt7BD2NyapNkkmQnN/acl1nG9Q3CVcOhWxsnUWlW9yx2E2ZwsEkzJv8ZSJnP3IDShLGi0l+INb0sccsOdq1+SOKAlNN0wWFNoVu0nifufvjkXyj+nEMWCiEV6LEQNWVSVEqGZYqodtd84LrQ3zKiOJq0eQRymeS17tmiSwVNfkm2n3IuPTwktwiER9sqgkoy1BSUse847W0fbdNxW1quZB0zia32FSU1btKeUQdUOqmLeIRJYpfidL55/lftfVfYlWwQ6S2X7/GmKI+n07/rv4PxqPR7fo/mQ67+v8t8MP3/VrJ/pqXfQo/WDO1dRRqCLEWUPEKc8YL5+XibBH3fvTSDOiXXLhkO6ThoOf34MEDqC4yv+fgJaZQHfRWlBA+p2XDdq2x7EFbqtu1KDJSuRSlqct9pki06jc0hrqJhGvUmsJV9SsptI1g8tpjW0IjVRfE9QW+3+Fa/NNgj/9K+N8X/8PJeHg7/seDeRf/3wJfHP9heD0F2K/fnz97+zJ5+/qXsxcLasj+uJEUbMWDsII+NSxtlPZlXTppdVeKuE12bdFJmYafblGgKbrRLoOnT92zxSlt9+rFIjlbvHl9dp4sXp+6zvkWQW8lIrT9AFCpB9vahu37Bvfc9pjKvGvAvmuoLMNyGI3nj8az6cmjOf1OZ8MhhoNpAONoMpmNZoP5ZDKcjQk0PQvgJJqROw9m9H6dT0bzyZym56sIzk23R41/uGXF3ryrmlakkTGKyOsfmTg4OZlQNTwJwE6NRlPaYjI6OaHXs9mEDpJSV0IKopTUaDV9EjT9jIJhNIBcAWVfvaUH3CAaQaVAYkrCLDf1MTm/xCxMsSjg1bvF0SLHk5vkCoUgEdTAaWpVyQwkBLdsz4V8QrsiWUrQg08DmvaHXh5bGAKx7oSstoLa0EMAlWlxazpYKkotRQGm/7/qiSJ4Rlpoyt6Q33h52iYYtvSwKQW8p7jkOSeiQpQb2+wDNT6SVaJoHprOXbftNOVnfF/9sT50HH8qM9cdqysjHTp06NChQ4cOHTp06NChQ4cOHTp06NDh/4w/AeLHyr0AKAAA
