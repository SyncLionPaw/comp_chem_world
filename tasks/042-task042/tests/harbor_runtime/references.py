"""Pure-data reference helpers for packed Bench 07 grader fixtures.

This module has no package, network, process, or scientific-analysis dependencies.
"""
from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Iterator

BUNDLE_SCHEMA = "compchembench.reference-data/v1"
REFS_RELATIVE = "tests/refs.json"
MAX_CONTAINER_BYTES = 128 * 1024 * 1024
MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_DOCUMENT_BYTES = 512 * 1024 * 1024
_MEDIA_TYPES = {
    ".json": "application/json",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".npz": "application/x-npz",
}
_ALLOWED_ENCODING = {".pdf": "base64", ".npz": "base64"}
_TOP_LEVEL_FILES = {"assessment-protocol.json", "reference-hashes.json", "review-rubric.md"}
_EVIDENCE_EXTENSIONS = set(_MEDIA_TYPES)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ReferenceDataError(ValueError):
    """Raised when reference data is malformed or unsafe to stage."""


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReferenceDataError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _json_loads(data: bytes | str, label: str):
    try:
        return json.loads(data, object_pairs_hook=_reject_duplicate_keys)
    except ReferenceDataError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise ReferenceDataError(f"invalid JSON in {label}: {exc}") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _json_pointer_unescape(value: str) -> str:
    # RFC 6901 requires ~1 to be replaced before ~0.
    return value.replace("~1", "/").replace("~0", "~")


def _safe_relative(raw: str, *, allow_embedded: bool = False) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise ReferenceDataError(f"invalid relative path: {raw!r}")
    path = PurePosixPath(raw)
    if (path.is_absolute() or path.as_posix() != raw
            or any(part in {"", ".", ".."} for part in path.parts)):
        raise ReferenceDataError(f"unsafe relative path: {raw!r}")
    if allow_embedded and path.parts[0] == "_embedded":
        return path
    if path.parts[0] == "evidence" and len(path.parts) == 2 and path.suffix.lower() in _EVIDENCE_EXTENSIONS:
        return path
    if path.parts[0] == "automatic" and len(path.parts) == 2 and path.suffix.lower() == ".json":
        return path
    if len(path.parts) == 1 and raw in _TOP_LEVEL_FILES:
        return path
    raise ReferenceDataError(f"reference path is outside the data allowlist: {raw!r}")


def _lstat_regular(path: Path, *, label: str, private_source: bool = False) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ReferenceDataError(f"cannot stat {label}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ReferenceDataError(f"{label} must be a regular non-symlink file")
    if info.st_nlink != 1:
        raise ReferenceDataError(f"{label} must not have hard links")
    mode = stat.S_IMODE(info.st_mode)
    if mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX):
        raise ReferenceDataError(f"{label} has unsafe special mode bits")
    if mode & 0o022:
        raise ReferenceDataError(f"{label} is group- or world-writable")
    if private_source and mode & 0o700 != 0o600 and mode & 0o700 != 0o700:
        raise ReferenceDataError(f"{label} has unsupported owner mode")
    return info


def _read_regular(path: Path, *, label: str, limit: int, private_source: bool = False) -> bytes:
    before = _lstat_regular(path, label=label, private_source=private_source)
    if before.st_size > limit:
        raise ReferenceDataError(f"{label} exceeds the {limit}-byte size limit")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise ReferenceDataError(f"{label} changed to an unsafe file while opening")
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ReferenceDataError(f"{label} changed while opening")
            data = stream.read(limit + 1)
    except OSError as exc:
        raise ReferenceDataError(f"cannot read {label}: {exc}") from exc
    if len(data) > limit:
        raise ReferenceDataError(f"{label} exceeds the {limit}-byte size limit")
    after = path.lstat()
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
        raise ReferenceDataError(f"{label} changed while being read")
    return data


def _refs_path(task_root: Path | str) -> Path:
    root = Path(task_root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ReferenceDataError("task root must be a real directory")
    tests = root / "tests"
    if tests.is_symlink() or not tests.is_dir():
        raise ReferenceDataError("tests must be a real directory")
    return tests / "refs.json"


def load_bundle(task_root: Path | str) -> dict:
    """Read the packed refs file and enforce its top-level bundle schema."""
    refs_path = _refs_path(task_root)
    raw = _read_regular(refs_path, label="tests/refs.json", limit=MAX_CONTAINER_BYTES)
    bundle = _json_loads(raw, "tests/refs.json")
    if not isinstance(bundle, dict) or bundle.get("reference_bundle_schema") != BUNDLE_SCHEMA:
        raise ReferenceDataError("unsupported or missing reference bundle schema")
    if not isinstance(bundle.get("scientific_values"), dict):
        raise ReferenceDataError("scientific_values must be a JSON object")
    documents = bundle.get("documents")
    if not isinstance(documents, dict):
        raise ReferenceDataError("documents must be a JSON object")
    for name in documents:
        _safe_relative(name)
    return bundle


def document_pointer(name: str) -> str:
    """Return the virtual JSON Pointer for one packed data document."""
    _safe_relative(name)
    return f"{REFS_RELATIVE}#/documents/{_json_pointer_escape(name)}"


def document_bytes(task_root: Path | str, name: str) -> bytes:
    """Decode one allowlisted data document and verify its byte count and SHA-256."""
    bundle = load_bundle(task_root)
    documents = bundle["documents"]
    if name not in documents:
        raise ReferenceDataError(f"document is not present in the reference bundle: {name!r}")
    _safe_relative(name)
    record = documents[name]
    if not isinstance(record, dict):
        raise ReferenceDataError(f"document metadata must be an object: {name!r}")
    if record.get("runtime_path") != name:
        raise ReferenceDataError(f"runtime_path must match its bundle key: {name!r}")
    suffix = PurePosixPath(name).suffix.lower()
    expected_encoding = _ALLOWED_ENCODING.get(suffix, "utf-8")
    if record.get("encoding") != expected_encoding:
        raise ReferenceDataError(f"unsupported encoding for {name!r}")
    if record.get("media_type") != _MEDIA_TYPES[suffix]:
        raise ReferenceDataError(f"unexpected media type for {name!r}")
    if not isinstance(record.get("kind"), str) or not record["kind"].strip():
        raise ReferenceDataError(f"missing document kind for {name!r}")
    expected_size = record.get("size")
    expected_hash = record.get("sha256")
    if type(expected_size) is not int or not 0 <= expected_size <= MAX_DOCUMENT_BYTES:
        raise ReferenceDataError(f"invalid document size for {name!r}")
    if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
        raise ReferenceDataError(f"invalid document SHA-256 for {name!r}")
    encoded = record.get("data")
    if not isinstance(encoded, str):
        raise ReferenceDataError(f"document data must be a string: {name!r}")
    if expected_encoding == "base64":
        try:
            data = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
            raise ReferenceDataError(f"invalid base64 document data: {name!r}") from exc
    else:
        try:
            data = encoded.encode("utf-8", errors="strict")
            data.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ReferenceDataError(f"invalid UTF-8 document data: {name!r}") from exc
    if len(data) != expected_size:
        raise ReferenceDataError(f"document size mismatch for {name!r}")
    if _sha256(data) != expected_hash:
        raise ReferenceDataError(f"document SHA-256 mismatch for {name!r}")
    return data


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _document_name_from_old_path(raw: str, bundle: dict) -> str | None:
    if raw == REFS_RELATIVE:
        return None
    candidates = []
    if raw.startswith("tests/"):
        candidates.append(raw[len("tests/"):])
    candidates.append(raw)
    for candidate in candidates:
        if candidate in bundle["documents"]:
            return candidate
    return None


def normalized_protocol(task_root: Path | str) -> tuple[bytes, dict, dict]:
    """Load the original protocol and normalize only acquired-data locations."""
    bundle = load_bundle(task_root)
    raw = document_bytes(task_root, "assessment-protocol.json")
    protocol = _json_loads(raw, "assessment-protocol.json")
    if not isinstance(protocol, dict):
        raise ReferenceDataError("assessment protocol must be a JSON object")
    effective = json.loads(json.dumps(protocol, ensure_ascii=False, allow_nan=False))
    mapping = {
        "scope": "Only verification_basis.acquired_paths locations are normalized; scientific values, numeric policies, criteria, and raw protocol bytes are unchanged.",
        "source_protocol_sha256": _sha256(raw),
        "acquired_paths": [],
    }
    for criterion in effective.get("criteria", []):
        if not isinstance(criterion, dict):
            continue
        basis = criterion.get("verification_basis")
        if not isinstance(basis, dict) or not isinstance(basis.get("acquired_paths"), list):
            continue
        normalized = []
        for old in basis["acquired_paths"]:
            if not isinstance(old, str):
                normalized.append(old)
                continue
            targets = []
            if old == REFS_RELATIVE:
                targets = [f"{REFS_RELATIVE}#/scientific_values"]
            else:
                document_name = _document_name_from_old_path(old, bundle)
                if document_name is not None:
                    targets.append(document_pointer(document_name))
                    document = bundle["documents"][document_name]
                    if (PurePosixPath(document_name).suffix.lower() == ".pdf"
                            and document.get("kind") == "original_scientific_data"):
                        derived_name = document_name + ".txt"
                        derived = bundle["documents"].get(derived_name)
                        if (isinstance(derived, dict) and derived.get("kind") == "derived_readable_text"
                                and isinstance(derived.get("derived_from"), dict)
                                and derived["derived_from"].get("document") == document_name
                                and derived["derived_from"].get("sha256") == document.get("sha256")):
                            targets.append(document_pointer(derived_name))
            if not targets:
                normalized.append(old)
            else:
                normalized.extend(targets)
                mapping["acquired_paths"].append({
                    "criterion": criterion.get("criterion"),
                    "from": old,
                    "to": targets,
                })
        basis["acquired_paths"] = normalized
    return raw, effective, mapping


def _validate_docs_for_staging(bundle: dict) -> list[tuple[str, dict, bytes]]:
    rows = []
    seen_paths = set()
    total = 0
    for name, metadata in bundle["documents"].items():
        relative = _safe_relative(name)
        collision_key = relative.as_posix().casefold()
        if collision_key in seen_paths:
            raise ReferenceDataError(f"colliding document path: {name!r}")
        seen_paths.add(collision_key)
        data = document_bytes_from_bundle(bundle, name)
        if metadata.get("kind") == "derived_readable_text":
            origin = metadata.get("derived_from")
            if not isinstance(origin, dict) or not isinstance(origin.get("document"), str):
                raise ReferenceDataError(f"derived document has no source binding: {name!r}")
            origin_name = origin["document"]
            source_record = bundle["documents"].get(origin_name)
            if (not isinstance(source_record, dict)
                    or PurePosixPath(origin_name).suffix.lower() != ".pdf"
                    or name != origin_name + ".txt"
                    or origin.get("sha256") != source_record.get("sha256")):
                raise ReferenceDataError(f"derived text source binding is invalid: {name!r}")
            document_bytes_from_bundle(bundle, origin_name)
        total += len(data)
        if total > MAX_TOTAL_DOCUMENT_BYTES:
            raise ReferenceDataError("decoded documents exceed the total size limit")
        rows.append((name, metadata, data))
    return rows


def document_bytes_from_bundle(bundle: dict, name: str) -> bytes:
    """Internal decoder used after a bundle was loaded once."""
    if not isinstance(bundle, dict) or bundle.get("reference_bundle_schema") != BUNDLE_SCHEMA:
        raise ReferenceDataError("unsupported reference bundle schema")
    record = bundle.get("documents", {}).get(name)
    if not isinstance(record, dict):
        raise ReferenceDataError(f"document metadata must be an object: {name!r}")
    _safe_relative(name)
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in _MEDIA_TYPES:
        raise ReferenceDataError(f"unsupported document extension: {name!r}")
    if record.get("runtime_path") != name:
        raise ReferenceDataError(f"runtime_path must match its bundle key: {name!r}")
    encoding = record.get("encoding")
    if encoding != _ALLOWED_ENCODING.get(suffix, "utf-8"):
        raise ReferenceDataError(f"unknown or disallowed encoding for {name!r}")
    if record.get("media_type") != _MEDIA_TYPES[suffix]:
        raise ReferenceDataError(f"unexpected MIME type for {name!r}")
    if not isinstance(record.get("kind"), str) or not record["kind"].strip():
        raise ReferenceDataError(f"missing document kind for {name!r}")
    size, digest, encoded = record.get("size"), record.get("sha256"), record.get("data")
    if type(size) is not int or not 0 <= size <= MAX_DOCUMENT_BYTES:
        raise ReferenceDataError(f"invalid document size for {name!r}")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ReferenceDataError(f"invalid document SHA-256 for {name!r}")
    if not isinstance(encoded, str):
        raise ReferenceDataError(f"document data must be a string: {name!r}")
    if encoding == "base64":
        try:
            data = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
            raise ReferenceDataError(f"invalid base64 document data: {name!r}") from exc
    else:
        try:
            data = encoded.encode("utf-8", errors="strict")
            data.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ReferenceDataError(f"invalid UTF-8 document data: {name!r}") from exc
    if len(data) != size:
        raise ReferenceDataError(f"document size mismatch for {name!r}")
    if _sha256(data) != digest:
        raise ReferenceDataError(f"document SHA-256 mismatch for {name!r}")
    return data


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o600)






def _canonical_source_pointer(path: str) -> str:
    return "/" + "/".join(_json_pointer_escape(part) for part in path.split("/"))


def reference_manifest_entries(task_root: Path | str) -> list[dict]:
    """Return virtual manifest rows for packed docs and the scientific_values object."""
    bundle = load_bundle(task_root)
    rows = []
    for name, metadata, data in _validate_docs_for_staging(bundle):
        row = {
            "path": document_pointer(name),
            "sha256": _sha256(data),
            "size": len(data),
            "source": {
                "container": REFS_RELATIVE,
                "json_pointer": "/documents/" + _json_pointer_escape(name),
                "encoding": metadata["encoding"],
            },
            "storage": "_embedded/" + name,
        }
        for key in ("media_type", "kind", "derived_from", "extraction"):
            if key in metadata:
                row["source"][key] = metadata[key]
        rows.append(row)
    scientific_bytes = _canonical_json(bundle["scientific_values"])
    rows.append({
        "path": f"{REFS_RELATIVE}#/scientific_values",
        "sha256": _sha256(scientific_bytes),
        "size": len(scientific_bytes),
        "source": {
            "container": REFS_RELATIVE,
            "json_pointer": "/scientific_values",
            "encoding": "canonical-json-utf-8",
        },
        "storage": "_embedded/scientific-values.json",
    })
    return rows


def _manifest_source_bytes(root: Path, row: dict) -> bytes:
    raw_path = row.get("path")
    if not isinstance(raw_path, str):
        raise ReferenceDataError("manifest path must be a string")
    if "#" in raw_path:
        container, pointer = raw_path.split("#", 1)
        if container == REFS_RELATIVE and pointer.startswith("/documents/"):
            name = _json_pointer_unescape(pointer[len("/documents/"):])
            if document_pointer(name) != raw_path:
                raise ReferenceDataError("malformed document JSON Pointer in manifest")
            return document_bytes(root, name)
        if container == REFS_RELATIVE and pointer == "/scientific_values":
            return _canonical_json(load_bundle(root)["scientific_values"])
        raise ReferenceDataError(f"unknown virtual reference path: {raw_path!r}")
    relative = _safe_relative_manifest_path(raw_path)
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        try:
            parent_info = cursor.lstat()
        except OSError as exc:
            raise ReferenceDataError(f"cannot stat manifest source directory {cursor}: {exc}") from exc
        if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
            raise ReferenceDataError(f"manifest source path crosses an unsafe directory: {cursor}")
    source = root.joinpath(*relative.parts)
    return _read_regular(source, label=f"manifest source {raw_path}", limit=MAX_CONTAINER_BYTES)


def _safe_relative_manifest_path(raw: str) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise ReferenceDataError(f"invalid manifest source path: {raw!r}")
    path = PurePosixPath(raw)
    if (path.is_absolute() or path.as_posix() != raw
            or any(part in {"", ".", ".."} for part in path.parts)):
        raise ReferenceDataError(f"unsafe manifest source path: {raw!r}")
    return path


@contextlib.contextmanager
def reference_data_view(task_root: Path | str, manifest: list[dict]) -> Iterator[tuple[Path, dict[str, Path]]]:
    """Stage hash-checked physical references and virtual packed references in a temp root."""
    root = Path(task_root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ReferenceDataError("task root must be a real directory")
    if not isinstance(manifest, list):
        raise ReferenceDataError("reference manifest must be a list")
    parent = tempfile.TemporaryDirectory(prefix="bench07-reference-view-")
    staged_root = Path(parent.name)
    os.chmod(staged_root, 0o700)
    aliases: dict[str, Path] = {}
    destinations = set()
    virtual_names = set()
    try:
        for row in manifest:
            if not isinstance(row, dict):
                raise ReferenceDataError("manifest rows must be objects")
            virtual = row.get("path")
            expected_hash = row.get("sha256")
            expected_size = row.get("size")
            if not isinstance(virtual, str) or not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
                raise ReferenceDataError("manifest row requires a path and SHA-256")
            if virtual in virtual_names:
                raise ReferenceDataError(f"duplicate manifest path: {virtual!r}")
            virtual_names.add(virtual)
            if type(expected_size) is not int or expected_size < 0:
                raise ReferenceDataError(f"invalid manifest size for {virtual!r}")
            storage = row.get("storage")
            if storage is not None:
                relative_storage = _safe_relative(storage, allow_embedded=True)
                if relative_storage.parts[0] != "_embedded":
                    raise ReferenceDataError("virtual reference storage must be under _embedded/")
                data = _manifest_source_bytes(root, row)
                if storage.startswith("_embedded/") and "#" not in virtual:
                    raise ReferenceDataError("embedded storage is reserved for virtual references")
            else:
                if "#" in virtual:
                    raise ReferenceDataError("virtual references require a storage path")
                relative_storage = _safe_relative_manifest_path(virtual)
                data = _manifest_source_bytes(root, row)
            if len(data) != expected_size or _sha256(data) != expected_hash:
                raise ReferenceDataError(f"manifest content mismatch for {virtual!r}")
            key = relative_storage.as_posix().casefold()
            if key in destinations:
                raise ReferenceDataError(f"duplicate or colliding staged path: {storage or virtual!r}")
            destinations.add(key)
            target = staged_root.joinpath(*relative_storage.parts)
            _write_private(target, data)
            aliases[virtual] = target
        yield staged_root, aliases
    finally:
        parent.cleanup()
