"""Build-time expansion of hash-checked, data-only scientific references."""
from pathlib import Path
import hashlib
import json
import shutil
import sys

source = Path('/opt/bench07-task')
sys.path.insert(0, str(source / 'tests'))
from harbor_runtime.references import load_bundle, _validate_docs_for_staging

target = Path('/tests')
shutil.copytree(source / 'tests', target)
for name, _record, data in _validate_docs_for_staging(load_bundle(source)):
    path = target / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
# Catch build-context path mistakes before a candidate is launched.
for rel, digest in json.loads((target / 'reference-hashes.json').read_text()).items():
    path = target / rel.removeprefix('tests/') if rel.startswith('tests/') else Path('/app') / rel
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f'private/public reference binding mismatch: {rel}')
for tree in (target, source):
    for path in tree.rglob('*'):
        if path.is_symlink():
            raise ValueError('private source contains a symlink')
        path.chmod(0o700 if path.is_dir() else 0o600)
    tree.chmod(0o700)
# Harbor executes the shell entry directly; all scientific private files remain 0600.
(target / 'test.sh').chmod(0o700)
