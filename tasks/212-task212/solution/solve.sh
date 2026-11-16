#!/usr/bin/env bash
set -euo pipefail
exec python3 -B - "${BASH_SOURCE[0]}" "$@" <<'PY'
import tarfile
EXPECTED = '8f3650f20fed90d74633277779337b210b14a5ee80d7af07fe2bc3cdfcae273b'

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
# yK074vJPxHlyGtKBZr2MGj8iFPJqBZsaLkYfyYIsHhXZVyxBqtBY3cuLqe//8uoCgV+zvls85yF8z9iybp0I9DyM8XAdgNjhh8F34WMbz5q3NalbzvF4y4QB3zFRmtdiwbae+reztklsLhPSsp0jyJZNQALdMMgVra0+RO120h65knPYpcWtKCIQWCy7YbeIMfPxwsIEFuZMtESjTENnRZ2GHklBU6AmF5ftQrnVnMZciZFn2GUhaTmkIOAflHhtuzo+I51z3luVshCdLXOd8NUq9EMuKwOnleQO6Qy8XoSAF5qbsOoqpAGwbShGiiin32cTqrfbTirdXCCpqyZuTKzIslxATecElfvsLHIWrhRDoCutADLZlig6H4sSeI4FMSxURRKHZmK8IQPWp89Ro38EIFDMFXxxOkmgYUwFb4HKApJYTeEoWS3Ip5S1KGrmWCOpKq3J4YgHsVDtmUJ48erGi7BojRX7RIY0Ig7M2X4DBg0MupdhIKO+cMA0Hdj/JVWsYfQD65PznEKVRqmGKAutJ01USi//rBk7kNO3Ou03OZ5NqFeidmpIc0CU3H9A9EHEhA3NSimGovjJZteqCFXM6368bmmeMBGVyRcly+7SiyKXoJqprbnbRijQypHL4xEAeHz80XnsIVBrKwENUrIap8GNEE6LF0SNNsojGyBjpM1sDMbvD9T8yMBT/17ryAQz82hqG9NrT+6apArJjW/xjKCr8kEKxdkMeveZiTsEsw6lsHwPTygWaDHUXcNizZFeenGSRlTE/y6JIIYNEhHmH0UhQ0lpEwYi+WXSYCOnlbDhkH4jvtVQd9RJXKJa4zcPazy1rAJhfRBuLvWJgfW+PC4R+YC8EV/byEI5tPdIHLAL0PQR1wD+NcqhN57aa6CjIH8lrY1k3xbck2YM/Mp4VJ9y6UoKo7CYHhbLFKCfHTsxq3FAjkecH9TUVXgOFFcyKZHqBfXgBoKDUg/NK+j7FdXrqGy/cief/0rnK7AhgcpC3osr6HIlXAwCUIy7GYSdhH/6LJtQLyQVVrvWtCpCkIBq79c8C/6i69Mkv2XRlTm/32DN5kKve9pcVayoO8D0a/ze/XyGKPoTSiRVEp1IrZbiI4VjD9LpPe7pKL7CWQj6uhyG4qowVGjPjk1Ky5tIw3J14gSdpIdO1NoiheeRsjzxqEDfPNgMYhoQBBUYxVReVmyEeURrhNUat/B7C7938HsHv3v4lZpXQ4CRB9x1Q4P4uRM/e/xpVXar7w3HwCfcdZkNDBi9Y+OBGgfUuNcb7yRNe2tx4sOKuQbgrAJQoVMTa6C7JcgDdrgnZOx7q5N2K0k7nEJHs7TQs4gF2Xhe5tarkpsZ5hjFFzpVBu73OAQV3jHzNfS2mPhqpaowyTGDWMZhoa1uHY+WrU9d6u939K8/5U5Mvpyql/K7gNpb4nxK0aoqvPFLFW1zXoqvBjQA488DoI9ZPgtgogO4B/aJPvj89OBOzJPm5zTXD2dYD9fD9XA9XA/Xw/VwPVwP18P1cD1cD9f/xes/ATvXLwwAUAAA
