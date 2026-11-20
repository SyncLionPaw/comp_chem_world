"""Pack / unpack the single shared inputs archive (wheels + assets).

End users place one file at shared/inputs.tar.zst, then run:
  uv run init
  # or
  uv run init --inputs-only

Uses zstd (level 3, one thread) so the same blobs pack to the same bytes.

Maintainers can build a task-subset archive with pack-subset; recipients still
place it at shared/inputs.tar.zst and run the same `uv run init` path.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import zstandard as zstd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
SHARED = ROOT / "shared"
ARCHIVE = SHARED / "inputs.tar.zst"
LEGACY_INPUTS_XZ = SHARED / "inputs.tar.xz"
LEGACY_ASSET_ARCHIVE = SHARED / "asset-store.tar.xz"
ASSET_STORE = SHARED / "asset-store"
WHEELHOUSE = SHARED / "wheelhouse"
ASSET_MANIFEST = ASSET_STORE / "manifest.json"
WHEEL_MANIFEST = WHEELHOUSE / "manifest.json"
ASSET_STATE = ASSET_STORE / ".restore-state.json"
WHEEL_STATE = WHEELHOUSE / ".restore-state.json"
CHUNK_SIZE = 8 * 1024 * 1024
# Fixed level and one thread so the same blobs pack to the same bytes.
ZSTD_LEVEL = 3


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("files"), dict) or not isinstance(data.get("blobs"), dict):
        raise ValueError(f"Unsupported manifest: {path}")
    return data


def asset_blobs_ready(data: dict[str, Any]) -> bool:
    for digest, details in data["blobs"].items():
        blob = ASSET_STORE / f"{digest}.blob"
        if not blob.is_file() or blob.stat().st_size != details["size"] or sha256(blob) != digest:
            return False
    return True


def wheel_blobs_ready(data: dict[str, Any]) -> bool:
    for digest, details in data["blobs"].items():
        blob = WHEELHOUSE / f"{digest}.whl"
        if not blob.is_file() or blob.stat().st_size != details["size"] or sha256(blob) != digest:
            return False
    return True


def stores_ready() -> bool:
    if not ASSET_MANIFEST.is_file() or not WHEEL_MANIFEST.is_file():
        return False
    return asset_blobs_ready(read_json(ASSET_MANIFEST)) and wheel_blobs_ready(read_json(WHEEL_MANIFEST))


def assert_not_restored() -> None:
    if ASSET_STATE.exists() or WHEEL_STATE.exists():
        raise RuntimeError("Restore state exists; run 'uv run reset' before packing or unpacking inputs")


@contextmanager
def zstd_tar_writer(path: Path) -> Iterator[tarfile.TarFile]:
    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    raw = temporary.open("wb")
    compressor = zstd.ZstdCompressor(level=ZSTD_LEVEL, threads=0).stream_writer(raw)
    archive = tarfile.open(fileobj=compressor, mode="w|")
    try:
        yield archive
        archive.close()
        compressor.close()
        raw.close()
        temporary.replace(path)
    except BaseException:
        try:
            archive.close()
        except Exception:
            pass
        try:
            compressor.close()
        except Exception:
            pass
        raw.close()
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def zstd_tar_reader(path: Path) -> Iterator[tarfile.TarFile]:
    raw = path.open("rb")
    reader = zstd.ZstdDecompressor().stream_reader(raw)
    archive = tarfile.open(fileobj=reader, mode="r|*")
    try:
        yield archive
    finally:
        archive.close()
        reader.close()
        raw.close()


def add_file(archive: tarfile.TarFile, path: Path, arcname: str) -> None:
    st = path.stat()
    info = tarfile.TarInfo(name=arcname)
    info.size = st.st_size
    info.mtime = 0
    info.mode = 0o644
    with path.open("rb") as handle:
        archive.addfile(info, handle)


def write_manifest(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def filter_manifest(data: dict[str, Any], prefixes: list[str]) -> dict[str, Any]:
    from task_config_paths import matches_task_prefix

    files = {
        relative: digest
        for relative, digest in data["files"].items()
        if matches_task_prefix(relative, prefixes)
    }
    digests = set(files.values())
    missing = sorted(digest for digest in digests if digest not in data["blobs"])
    if missing:
        raise ValueError(f"Manifest files reference missing blobs: {missing[:5]}")
    blobs = {digest: data["blobs"][digest] for digest in sorted(digests)}
    return {"version": 1, "files": dict(sorted(files.items())), "blobs": blobs}


def task_prefixes_from_config(config_path: Path) -> list[str]:
    from task_config_paths import task_prefixes_from_config as parse

    return parse(config_path)


def pack_archive(assets: dict[str, Any], wheels: dict[str, Any], output: Path) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as raw:
        staging = Path(raw)
        asset_manifest = staging / "asset-manifest.json"
        wheel_manifest = staging / "wheel-manifest.json"
        write_manifest(asset_manifest, assets)
        write_manifest(wheel_manifest, wheels)
        with zstd_tar_writer(output) as archive:
            add_file(archive, asset_manifest, "asset-store/manifest.json")
            for digest in sorted(assets["blobs"]):
                add_file(archive, ASSET_STORE / f"{digest}.blob", f"asset-store/{digest}.blob")
            add_file(archive, wheel_manifest, "wheelhouse/manifest.json")
            for digest in sorted(wheels["blobs"]):
                add_file(archive, WHEELHOUSE / f"{digest}.whl", f"wheelhouse/{digest}.whl")
    print(
        f"Packed inputs: {len(assets['blobs'])} asset blobs + {len(wheels['blobs'])} wheels "
        f"({output.stat().st_size / (1024**2):.1f} MiB, zstd-{ZSTD_LEVEL}) -> {output}"
    )


def pack() -> None:
    assert_not_restored()
    assets = read_json(ASSET_MANIFEST)
    wheels = read_json(WHEEL_MANIFEST)
    if not asset_blobs_ready(assets):
        raise FileNotFoundError(f"Asset store incomplete under {ASSET_STORE}")
    if not wheel_blobs_ready(wheels):
        raise FileNotFoundError(f"Wheelhouse incomplete under {WHEELHOUSE}")
    pack_archive(assets, wheels, ARCHIVE)


def pack_subset(prefixes: list[str], output: Path) -> None:
    assert_not_restored()
    assets = read_json(ASSET_MANIFEST)
    wheels = read_json(WHEEL_MANIFEST)
    if not asset_blobs_ready(assets):
        raise FileNotFoundError(f"Asset store incomplete under {ASSET_STORE}")
    if not wheel_blobs_ready(wheels):
        raise FileNotFoundError(f"Wheelhouse incomplete under {WHEELHOUSE}")
    filtered_assets = filter_manifest(assets, prefixes)
    filtered_wheels = filter_manifest(wheels, prefixes)
    if not filtered_assets["files"] and not filtered_wheels["files"]:
        raise ValueError(f"No asset or wheel files matched prefixes: {prefixes}")
    pack_archive(filtered_assets, filtered_wheels, output)
    print(
        f"Subset covers {len(prefixes)} task prefixes; "
        f"{len(filtered_assets['files'])} asset files, {len(filtered_wheels['files'])} wheel files"
    )


def replace_store(store: Path, staging: Path, suffix: str) -> None:
    store.mkdir(parents=True, exist_ok=True)
    for path in store.glob(f"*{suffix}"):
        path.unlink()
    manifest = store / "manifest.json"
    manifest.unlink(missing_ok=True)
    shutil.move(str(staging / "manifest.json"), manifest)
    for path in staging.glob(f"*{suffix}"):
        shutil.move(str(path), store / path.name)


def extract_archive(archive_path: Path, staging: Path) -> None:
    if archive_path.suffix == ".zst" or archive_path.name.endswith(".tar.zst"):
        with zstd_tar_reader(archive_path) as archive:
            archive.extractall(staging, filter="data")
        return
    if archive_path.suffix == ".xz" or archive_path.name.endswith(".tar.xz"):
        with tarfile.open(archive_path, mode="r:xz") as archive:
            archive.extractall(staging, filter="data")
        return
    raise ValueError(f"Unsupported inputs archive type: {archive_path}")


def unpack_from(archive_path: Path) -> None:
    assert_not_restored()
    with tempfile.TemporaryDirectory(dir=SHARED) as raw:
        staging = Path(raw) / "inputs"
        staging.mkdir()
        extract_archive(archive_path, staging)
        asset_staging = staging / "asset-store"
        wheel_staging = staging / "wheelhouse"
        if not asset_staging.is_dir() or not wheel_staging.is_dir():
            raise ValueError(f"Archive must contain asset-store/ and wheelhouse/: {archive_path}")
        assets = read_json(asset_staging / "manifest.json")
        wheels = read_json(wheel_staging / "manifest.json")
        for digest, details in assets["blobs"].items():
            blob = asset_staging / f"{digest}.blob"
            if not blob.is_file() or blob.stat().st_size != details["size"] or sha256(blob) != digest:
                raise ValueError(f"Archive asset blob failed verification: {digest}")
        for digest, details in wheels["blobs"].items():
            blob = wheel_staging / f"{digest}.whl"
            if not blob.is_file() or blob.stat().st_size != details["size"] or sha256(blob) != digest:
                raise ValueError(f"Archive wheel blob failed verification: {digest}")
        replace_store(ASSET_STORE, asset_staging, ".blob")
        replace_store(WHEELHOUSE, wheel_staging, ".whl")
    if not stores_ready():
        raise RuntimeError("Unpacked inputs failed verification")
    from task_assets import write_ignore

    write_ignore(read_json(ASSET_MANIFEST)["files"])
    print(
        f"Unpacked inputs from {archive_path.name}: "
        f"{len(read_json(ASSET_MANIFEST)['blobs'])} asset blobs, "
        f"{len(read_json(WHEEL_MANIFEST)['blobs'])} wheels"
    )


def unpack() -> None:
    if not ARCHIVE.is_file():
        raise FileNotFoundError(f"Missing inputs archive: {ARCHIVE}")
    unpack_from(ARCHIVE)


def ensure() -> None:
    if stores_ready():
        print("Shared inputs already present (wheelhouse + asset-store).")
        return
    if ARCHIVE.is_file():
        print(f"Shared inputs incomplete; unpacking {ARCHIVE.name}...")
        unpack_from(ARCHIVE)
        return
    if LEGACY_INPUTS_XZ.is_file():
        print(f"Found legacy {LEGACY_INPUTS_XZ.name}; unpacking (prefer {ARCHIVE.name} next time)...")
        unpack_from(LEGACY_INPUTS_XZ)
        return
    if LEGACY_ASSET_ARCHIVE.is_file() and WHEEL_MANIFEST.is_file() and wheel_blobs_ready(read_json(WHEEL_MANIFEST)):
        print(f"Using legacy {LEGACY_ASSET_ARCHIVE.name}; prefer {ARCHIVE.name} going forward.")
        import task_assets

        task_assets.unpack()
        if stores_ready():
            return
    raise FileNotFoundError(
        "Shared inputs missing. Place the distributed archive at:\n"
        f"  {ARCHIVE}\n"
        "then re-run `uv run init` or `uv run init --inputs-only`.\n"
        "Maintainers build it with: python3 -I scripts/task_inputs.py pack"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pack", help="Pack the full shared inputs archive")
    sub.add_parser("unpack", help="Unpack shared/inputs.tar.zst into stores")
    sub.add_parser("ensure", help="Ensure stores exist, unpacking the archive if needed")

    subset = sub.add_parser(
        "pack-subset",
        help="Pack a task-subset inputs archive (still consumed via shared/inputs.tar.zst + uv run init)",
    )
    subset.add_argument(
        "--config",
        type=Path,
        help="Harbor job config whose tasks.path entries define the subset",
    )
    subset.add_argument(
        "--tasks",
        nargs="+",
        metavar="PATH",
        help="Task prefixes such as tasks/005-task005 (alternative to --config)",
    )
    subset.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output archive path (e.g. shared/inputs-local-a-selected-20.tar.zst)",
    )

    args = parser.parse_args()
    if args.command == "pack":
        pack()
    elif args.command == "unpack":
        unpack()
    elif args.command == "ensure":
        ensure()
    elif args.command == "pack-subset":
        if bool(args.config) == bool(args.tasks):
            raise SystemExit("pack-subset requires exactly one of --config or --tasks")
        prefixes = task_prefixes_from_config(args.config) if args.config else [p.rstrip("/") for p in args.tasks]
        for prefix in prefixes:
            if not prefix.startswith("tasks/"):
                raise SystemExit(f"Task path must start with tasks/: {prefix}")
        pack_subset(prefixes, args.output)
    else:
        raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
