from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRECTORIES = {".git", ".venv", "__pycache__"}
EXCLUDED_FILES = {".env", "images/base/uv", "output/tree-manifest.json"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if relative.as_posix() in EXCLUDED_FILES:
        return False
    return not any(part in EXCLUDED_DIRECTORIES or part.endswith(".backup") for part in relative.parts)


def build_manifest() -> dict[str, Any]:
    files: dict[str, Any] = {}
    for path in sorted(ROOT.rglob("*")):
        if not included(path):
            continue
        relative = path.relative_to(ROOT).as_posix()
        if path.is_symlink():
            files[relative] = {"type": "symlink", "target": path.readlink().as_posix()}
        elif path.is_file():
            files[relative] = {"type": "file", "size": path.stat().st_size, "sha256": sha256(path)}
    return {"version": 1, "root": ".", "files": files}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "tree-manifest.json")
    args = parser.parse_args()
    manifest = build_manifest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(f"Files: {len(manifest['files'])}")
    print(f"Manifest: {args.output}")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
