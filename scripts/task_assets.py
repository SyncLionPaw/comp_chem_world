from __future__ import annotations

import hashlib
import json
import shutil
import stat
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import zstandard as zstd

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks"
STORE = ROOT / "shared" / "asset-store"
ARCHIVE = ROOT / "shared" / "asset-store.tar.zst"
LEGACY_ARCHIVE = ROOT / "shared" / "asset-store.tar.xz"
ZSTD_LEVEL = 3
MANIFEST = STORE / "manifest.json"
STATE = STORE / ".restore-state.json"
IGNORE = TASKS / ".gitignore"
# All environment/assets are managed. Large test/solution files only (keep check
# scripts and replay logic in-tree).
ASSETS_MIN_SIZE = 0
TESTS_MIN_SIZE = 1024 * 1024
SOLUTION_MIN_SIZE = 1024 * 1024
CHUNK_SIZE = 8 * 1024 * 1024
# Host/runtime junk that must never be compacted into the shared store (mount write-back etc.).
POLLUTION_NAMES = {".DS_Store", "reward.txt", "reward.json", "verification.json"}
POLLUTION_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", ".git"}
POLLUTION_SUFFIXES = {".pyc", ".pyo"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def task_names() -> set[str]:
    return {directory.name for directory in TASKS.iterdir() if directory.is_dir()}


def path_for(relative: str, names: set[str] | None = None) -> Path:
    parts = Path(relative).parts
    known = names if names is not None else task_names()
    if (
        Path(relative).is_absolute()
        or ".." in parts
        or len(parts) < 4
        or parts[0] != "tasks"
        or parts[1] not in known
        or not (parts[2:4] == ("environment", "assets") or parts[2] in ("tests", "solution"))
        or parts[-1] == "Dockerfile"
        or Path(relative).suffix == ".whl"
    ):
        raise ValueError(f"Invalid managed asset path: {relative}")
    path = ROOT / relative
    if not path.parent.resolve().is_relative_to(TASKS.resolve()) or path.is_symlink():
        raise ValueError(f"Symlink in managed asset path: {relative}")
    return path


def eligible(relative: str, size: int) -> bool:
    parts = Path(relative).parts
    if parts[2:4] == ("environment", "assets"):
        return size >= ASSETS_MIN_SIZE
    if parts[2] == "tests":
        return size >= TESTS_MIN_SIZE
    if parts[2] == "solution":
        return size >= SOLUTION_MIN_SIZE
    return False


def pollution_reason(relative: str) -> str | None:
    parts = Path(relative).parts
    name = parts[-1]
    if name in POLLUTION_NAMES:
        return f"generated name {name}"
    if Path(name).suffix in POLLUTION_SUFFIXES:
        return f"generated suffix {Path(name).suffix}"
    hit = POLLUTION_DIRS.intersection(parts)
    if hit:
        return f"generated directory {sorted(hit)[0]}"
    return None


def assert_not_pollution(relative: str) -> None:
    reason = pollution_reason(relative)
    if reason:
        raise ValueError(f"Refusing to manage pollution under assets/tests/solution ({reason}): {relative}")


def readonly_mode(mode: int) -> int:
    # Clear write bits so restored host trees cannot absorb container write-back.
    return stat.S_IMODE(mode) & ~0o222


def iter_candidates(names: set[str]) -> Iterator[tuple[Path, str, int]]:
    for path in TASKS.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.suffix == ".whl":
            continue
        relative = path.relative_to(ROOT).as_posix()
        try:
            path_for(relative, names)
        except ValueError:
            continue
        assert_not_pollution(relative)
        size = path.stat().st_size
        if eligible(relative, size):
            yield path, relative, size


def read_manifest() -> dict[str, Any]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("files"), dict) or not isinstance(data.get("blobs"), dict):
        raise ValueError(f"Unsupported asset manifest: {MANIFEST}")
    return data


def blob_path(digest: str) -> Path:
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"Invalid asset digest: {digest}")
    return STORE / f"{digest}.blob"


def verify_store(data: dict[str, Any]) -> None:
    names = task_names()
    for relative, digest in data["files"].items():
        path_for(relative, names)
        if digest not in data["blobs"]:
            raise ValueError(f"Asset has no blob metadata: {relative}")
    for digest, details in data["blobs"].items():
        blob = blob_path(digest)
        if not blob.is_file() or blob.stat().st_size != details["size"] or sha256(blob) != digest:
            raise ValueError(f"Missing or changed shared asset: {blob}")


def store_ready() -> bool:
    if not MANIFEST.is_file():
        return False
    try:
        verify_store(read_manifest())
        return True
    except (ValueError, OSError):
        return False


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_ignore(files: dict[str, str]) -> None:
    listed_paths = sorted(
        relative.removeprefix("tasks/")
        for relative in files
        if "/tests/" in relative or "/solution/" in relative
    )
    for relative in listed_paths:
        if any(char in relative for char in ("\n", "\r", "*", "?", "[", "]", "!", "#", "\\")):
            raise ValueError(f"Cannot express asset path in .gitignore: {relative}")
    lines = [
        "# Restored by uv run init from shared/asset-store/\n",
        "# All environment/assets are managed; large test and solution files listed below.\n",
        "*/environment/assets/\n",
    ]
    lines.extend(f"/{relative}\n" for relative in listed_paths)
    IGNORE.write_text("".join(lines), encoding="utf-8")


def ensure_blob(path: Path, digest: str, size: int, mode: int, blobs: dict[str, Any]) -> None:
    # Content-addressed: identical bytes may arrive with different modes (e.g. 0o600 vs 0o644).
    # Keep the first recorded mode; only size/hash must agree.
    if digest in blobs:
        details = blobs[digest]
        if details["size"] != size:
            raise ValueError(f"Equal-content assets have conflicting size: {path}")
        blob = blob_path(digest)
        if blob.exists() and (blob.stat().st_size != size or sha256(blob) != digest):
            raise ValueError(f"Existing shared asset conflicts: {blob}")
        return
    blob = blob_path(digest)
    if blob.exists():
        if blob.stat().st_size != size or sha256(blob) != digest:
            raise ValueError(f"Existing shared asset conflicts: {blob}")
    else:
        blob.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, blob)
        blob.chmod(mode)
    blobs[digest] = {"size": size, "mode": mode}


def compact() -> None:
    if STATE.exists():
        raise RuntimeError("Restore state exists; run 'uv run reset' (or task_assets.py clean) before compacting")
    previous = read_manifest() if MANIFEST.exists() else {"version": 1, "files": {}, "blobs": {}}
    if MANIFEST.exists():
        verify_store(previous)
    files = dict(previous["files"])
    blobs = dict(previous["blobs"])
    names = task_names()
    added = 0
    for path, relative, size in iter_candidates(names):
        digest = sha256(path)
        mode = stat.S_IMODE(path.stat().st_mode)
        if relative in files:
            if files[relative] != digest:
                raise ValueError(f"Managed asset differs from manifest: {path}")
            continue
        ensure_blob(path, digest, size, mode, blobs)
        files[relative] = digest
        added += 1

    data = {"version": 1, "files": files, "blobs": blobs}
    referenced = set(files.values())
    data["blobs"] = {digest: blobs[digest] for digest in referenced}
    verify_store(data)
    write_json(MANIFEST, data)
    write_ignore(files)

    removed = 0
    for relative, digest in files.items():
        path = path_for(relative, names)
        if not path.exists():
            continue
        if sha256(path) != digest:
            raise ValueError(f"Refusing to remove modified managed asset: {path}")
        path.unlink()
        removed += 1

    for blob in STORE.glob("*.blob"):
        if blob.stem not in referenced:
            blob.unlink()

    print(
        f"Compacted assets: {added} new paths, {removed} removed from tasks; "
        f"{len(files)} mappings -> {len(referenced)} blobs."
    )


def prepare() -> None:
    data = ensure_store()
    if STATE.exists():
        raise RuntimeError("Restore state exists; run 'uv run reset' (or task_assets.py clean) first")
    names = task_names()
    created: list[str] = []
    write_json(STATE, {"version": 1, "created": created})
    try:
        for relative, digest in sorted(data["files"].items()):
            path = path_for(relative, names)
            if path.exists():
                if sha256(path) != digest:
                    raise ValueError(f"Refusing to overwrite changed asset: {path}")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
                temporary = Path(file.name)
            try:
                shutil.copy2(blob_path(digest), temporary)
                temporary.chmod(readonly_mode(data["blobs"][digest]["mode"]))
                if sha256(temporary) != digest:
                    raise ValueError(f"Restored asset failed hash verification: {path}")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            created.append(relative)
            write_json(STATE, {"version": 1, "created": created})
    except Exception:
        clean()
        raise
    print(f"Restored {len(created)} asset paths from {len(data['blobs'])} shared blobs.")


def clean() -> None:
    if not STATE.exists():
        print("No prepared assets to clean.")
        return
    data = read_manifest()
    state = json.loads(STATE.read_text(encoding="utf-8"))
    names = task_names()
    for relative in state["created"]:
        path = path_for(relative, names)
        if relative not in data["files"]:
            raise ValueError(f"Unknown restored asset path: {relative}")
        if path.exists():
            if sha256(path) != data["files"][relative]:
                raise ValueError(f"Refusing to remove modified restored asset: {path}")
            path.unlink()
    STATE.unlink()
    print(f"Removed {len(state['created'])} prepared asset paths.")


def verify() -> None:
    data = ensure_store()
    names = task_names()
    restored = 0
    for relative, digest in data["files"].items():
        path = path_for(relative, names)
        if path.exists():
            if sha256(path) != digest:
                raise ValueError(f"Asset path does not match manifest: {path}")
            restored += 1
    print(
        f"Verified {len(data['files'])} asset mappings and {len(data['blobs'])} blobs; "
        f"{restored} paths currently restored."
    )


@contextmanager
def zstd_tar_writer(path: Path) -> Iterator[tarfile.TarFile]:
    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    raw = temporary.open("wb")
    compressor = zstd.ZstdCompressor(level=ZSTD_LEVEL, threads=-1).stream_writer(raw)
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


def pack() -> None:
    data = read_manifest()
    verify_store(data)
    if STATE.exists():
        raise RuntimeError("Restore state exists; run 'uv run reset' before packing")
    STORE.mkdir(parents=True, exist_ok=True)
    with zstd_tar_writer(ARCHIVE) as archive:
        st = MANIFEST.stat()
        info = tarfile.TarInfo(name="manifest.json")
        info.size = st.st_size
        info.mtime = int(st.st_mtime)
        info.mode = stat.S_IMODE(st.st_mode)
        with MANIFEST.open("rb") as handle:
            archive.addfile(info, handle)
        for digest in sorted(data["blobs"]):
            blob = blob_path(digest)
            size = data["blobs"][digest]["size"]
            st = blob.stat()
            if st.st_size != size:
                raise FileNotFoundError(f"Blob changed or vanished during pack: {blob}")
            info = tarfile.TarInfo(name=f"{digest}.blob")
            info.size = size
            info.mtime = int(st.st_mtime)
            info.mode = stat.S_IMODE(st.st_mode)
            with blob.open("rb") as handle:
                archive.addfile(info, handle)
    print(
        f"Packed {len(data['blobs'])} blobs ({ARCHIVE.stat().st_size / (1024**2):.1f} MiB, zstd-{ZSTD_LEVEL}) -> {ARCHIVE}"
    )


def unpack_archive(archive_path: Path) -> None:
    if STATE.exists():
        raise RuntimeError("Restore state exists; run 'uv run reset' before unpacking")
    STORE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=STORE.parent) as raw:
        staging = Path(raw) / "asset-store"
        staging.mkdir()
        if archive_path.name.endswith(".tar.zst"):
            raw_file = archive_path.open("rb")
            reader = zstd.ZstdDecompressor().stream_reader(raw_file)
            archive = tarfile.open(fileobj=reader, mode="r|*")
            try:
                archive.extractall(staging, filter="data")
            finally:
                archive.close()
                reader.close()
                raw_file.close()
        else:
            with tarfile.open(archive_path, mode="r:xz") as archive:
                archive.extractall(staging, filter="data")
        manifest = staging / "manifest.json"
        if not manifest.is_file():
            raise ValueError(f"Archive is missing manifest.json: {archive_path}")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("files"), dict) or not isinstance(data.get("blobs"), dict):
            raise ValueError(f"Unsupported asset archive manifest: {archive_path}")
        for digest, details in data["blobs"].items():
            blob = staging / f"{digest}.blob"
            if not blob.is_file() or blob.stat().st_size != details["size"] or sha256(blob) != digest:
                raise ValueError(f"Archive blob failed verification: {digest}")
        if MANIFEST.exists() or any(STORE.glob("*.blob")):
            for path in STORE.glob("*.blob"):
                path.unlink()
            MANIFEST.unlink(missing_ok=True)
        shutil.move(str(manifest), MANIFEST)
        for digest in data["blobs"]:
            shutil.move(str(staging / f"{digest}.blob"), blob_path(digest))
        write_ignore(data["files"])
    verify_store(read_manifest())
    print(f"Unpacked {len(data['blobs'])} blobs from {archive_path}")


def unpack() -> None:
    if ARCHIVE.is_file():
        unpack_archive(ARCHIVE)
        return
    if LEGACY_ARCHIVE.is_file():
        unpack_archive(LEGACY_ARCHIVE)
        return
    raise FileNotFoundError(f"Missing asset archive: {ARCHIVE}")


def ensure_store() -> dict[str, Any]:
    if store_ready():
        return read_manifest()
    if ARCHIVE.is_file() or LEGACY_ARCHIVE.is_file():
        name = ARCHIVE.name if ARCHIVE.is_file() else LEGACY_ARCHIVE.name
        print(f"Asset store incomplete; unpacking {name}...")
        unpack()
        return read_manifest()
    raise FileNotFoundError(
        f"Asset store incomplete and archive missing. Expected blobs under {STORE} or {ARCHIVE}"
    )


def main() -> None:
    commands = {
        "compact": compact,
        "prepare": prepare,
        "clean": clean,
        "verify": verify,
        "pack": pack,
        "unpack": unpack,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        raise SystemExit("Usage: task_assets.py {compact|prepare|clean|verify|pack|unpack}")
    commands[sys.argv[1]]()


if __name__ == "__main__":
    main()
