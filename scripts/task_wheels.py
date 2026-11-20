from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from task_config_paths import matches_task_prefix
TASKS = ROOT / "tasks"
STORE = ROOT / "shared" / "wheelhouse"
MANIFEST = STORE / "manifest.json"
STATE = STORE / ".restore-state.json"
CHUNK_SIZE = 8 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest() -> dict[str, Any]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("files"), dict):
        raise ValueError(f"Unsupported wheel manifest: {MANIFEST}")
    return data


def blob_path(digest: str) -> Path:
    return STORE / f"{digest}.whl"


def verify_store(data: dict[str, Any]) -> None:
    for digest, details in data["blobs"].items():
        path = blob_path(digest)
        if not path.is_file():
            raise FileNotFoundError(f"Missing shared wheel blob: {path}")
        if path.stat().st_size != details["size"] or sha256(path) != digest:
            raise ValueError(f"Wheel blob failed size/hash verification: {path}")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def compact() -> None:
    wheels = sorted(TASKS.rglob("*.whl"))
    if STATE.exists():
        raise RuntimeError(f"Restore state exists; clean restored wheels first: {STATE}")
    if MANIFEST.exists():
        previous = load_manifest()
        verify_store(previous)
        files = dict(previous["files"])
        blobs = dict(previous["blobs"])
    else:
        files: dict[str, str] = {}
        blobs: dict[str, dict[str, int]] = {}
    if not wheels:
        if MANIFEST.exists():
            print(f"Shared store already has {len(files)} paths as {len(blobs)} verified blobs.")
            return
        raise FileNotFoundError(f"No wheel files found under {TASKS}")

    for wheel in wheels:
        digest = sha256(wheel)
        relative = wheel.relative_to(ROOT).as_posix()
        files[relative] = digest
        blobs[digest] = {"size": wheel.stat().st_size}
        blob = blob_path(digest)
        if blob.exists():
            if blob.stat().st_size != wheel.stat().st_size or sha256(blob) != digest:
                raise ValueError(f"Existing wheel blob conflicts with source: {blob}")
        else:
            blob.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(wheel, blob)

    referenced_blobs = set(files.values())
    data = {
        "version": 1,
        "files": files,
        "blobs": {digest: blobs[digest] for digest in referenced_blobs},
    }
    verify_store(data)
    write_json(MANIFEST, data)
    for wheel in wheels:
        wheel.unlink()
    for blob in STORE.glob("*.whl"):
        if blob.stem not in referenced_blobs:
            blob.unlink()
    print(f"Stored {len(wheels)} wheel paths as {len(referenced_blobs)} verified blobs.")


def prepare(prefixes: list[str] | None = None) -> None:
    data = load_manifest()
    verify_store(data)
    if STATE.exists():
        raise RuntimeError(f"Restore state already exists; run 'uv run reset' first: {STATE}")
    created: list[str] = []
    mode = "subset" if prefixes else "all"
    write_json(STATE, {"version": 1, "mode": mode, "created": created})
    selected = {
        relative: digest
        for relative, digest in data["files"].items()
        if prefixes is None or matches_task_prefix(relative, prefixes)
    }
    try:
        for relative, digest in sorted(selected.items()):
            destination = ROOT / relative
            if not destination.is_relative_to(TASKS) or destination.suffix != ".whl" or destination.is_symlink():
                raise ValueError(f"Invalid wheel path in manifest: {relative}")
            source = blob_path(digest)
            if destination.exists():
                if sha256(destination) != digest:
                    raise ValueError(f"Refusing to overwrite differing file: {destination}")
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, destination)
            except OSError:
                with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as file:
                    temporary = Path(file.name)
                try:
                    shutil.copy2(source, temporary)
                    if sha256(temporary) != digest:
                        raise ValueError(f"Restored wheel failed hash verification: {destination}")
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
            # Keep restored wheels read-only so Docker mount write-back cannot dirty assets/.
            destination.chmod(0o444)
            created.append(relative)
            write_json(STATE, {"version": 1, "mode": mode, "created": created})
    except Exception:
        clean()
        raise
    scope = f"{len(prefixes)} task prefixes" if prefixes else "all tasks"
    print(
        f"Restored {len(created)} wheel paths from {len(data['blobs'])} blobs "
        f"({scope}; {len(selected)} matching mappings)."
    )


def clean() -> None:
    if not STATE.exists():
        print("No prepared wheel files to clean.")
        return
    state = json.loads(STATE.read_text(encoding="utf-8"))
    data = load_manifest()
    for relative in state.get("created", []):
        path = ROOT / relative
        digest = data["files"].get(relative)
        if not path.is_relative_to(TASKS) or digest is None:
            raise ValueError(f"Invalid restore state path: {relative}")
        if path.exists():
            if sha256(path) != digest:
                raise ValueError(f"Refusing to remove modified restored wheel: {path}")
            path.unlink()
    STATE.unlink()
    print(f"Removed {len(state.get('created', []))} prepared wheel paths.")


def verify() -> None:
    data = load_manifest()
    verify_store(data)
    restored = 0
    for relative, digest in data["files"].items():
        path = ROOT / relative
        if path.exists():
            if sha256(path) != digest:
                raise ValueError(f"Wheel path does not match manifest: {path}")
            restored += 1
    print(f"Verified {len(data['files'])} wheel mappings and {len(data['blobs'])} unique blobs; {restored} paths currently restored.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage shared task wheels.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("compact", "clean", "verify"):
        sub.add_parser(name)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument(
        "--prefix",
        action="append",
        default=[],
        metavar="PATH",
        help="Only restore paths under this task prefix (repeatable), e.g. tasks/005-task005",
    )
    args = parser.parse_args()
    if args.command == "prepare":
        prefixes = [p.rstrip("/") for p in args.prefix] or None
        prepare(prefixes)
    elif args.command == "compact":
        compact()
    elif args.command == "clean":
        clean()
    elif args.command == "verify":
        verify()
    else:
        raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
