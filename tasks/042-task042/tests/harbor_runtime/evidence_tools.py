"""Read-only, manifest-scoped evidence access for independent review."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import struct
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO


_MAX_PAGE = 64 * 1024
_MAX_TEXT_FILE = 64 * 1024 * 1024
_MAX_ARRAY_FILE = 64 * 1024 * 1024
_MAX_NPZ_UNCOMPRESSED = 128 * 1024 * 1024
_MAX_NPZ_MEMBERS = 256
_MAX_ZIP_CENTRAL_DIRECTORY = 1024 * 1024
_MAX_ARRAY_ELEMENTS = 100_000
_HASH_CHUNK = 1024 * 1024


class EvidenceToolError(ValueError):
    """A safe, user-displayable evidence access error."""


def _schema(name: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": {
            "list_files": "List only files declared by the frozen submission manifest.",
            "read_text": "Read a bounded UTF-8 page from one declared text file; evidence is SHA-verified.",
            "read_reference_text": "Read a bounded UTF-8 page from one host-pinned trusted reference file.",
            "inspect_array": "Inspect a bounded NPY/NPZ numeric or fixed-width string array selection; pickle/object arrays are rejected.",
        }[name],
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


class EvidenceTools:
    """Allowlisted read-only access to a frozen output snapshot.

    Manifest forms accepted:
      * {"files": [{"path": "...", "sha256": "...", "size": 12}, ...]}
      * {"...": {"sha256": "...", "size": 12}, ...}

    The filesystem root and each path component are opened without following
    symlinks. Every successful content read hashes the opened file before and
    after the read and compares both values with the frozen manifest.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        manifest: dict[str, Any] | str | os.PathLike[str],
        *,
        max_text_bytes: int = _MAX_TEXT_FILE,
        max_array_bytes: int = _MAX_ARRAY_FILE,
        max_npz_uncompressed_bytes: int = _MAX_NPZ_UNCOMPRESSED,
        max_array_elements: int = _MAX_ARRAY_ELEMENTS,
        reference_root: str | os.PathLike[str] | None = None,
        reference_manifest: dict[str, Any] | str | os.PathLike[str] | None = None,
        reference_aliases: dict[str, str] | None = None,
    ) -> None:
        root_path = Path(root)
        root_stat = root_path.lstat()
        if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
            raise EvidenceToolError("snapshot root must be a real directory")
        self.root = root_path.absolute()
        if isinstance(manifest, (str, os.PathLike)):
            with open(manifest, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        self.manifest = self._parse_manifest(manifest)
        if (reference_root is None) != (reference_manifest is None):
            raise ValueError("reference_root and reference_manifest must be supplied together")
        self.reference_root: Path | None = None
        self.reference_manifest: dict[str, dict[str, Any]] = {}
        if reference_root is not None:
            ref_root = Path(reference_root)
            ref_stat = ref_root.lstat()
            if not stat.S_ISDIR(ref_stat.st_mode) or stat.S_ISLNK(ref_stat.st_mode):
                raise EvidenceToolError("reference root must be a real directory")
            self.reference_root = ref_root.absolute()
            if isinstance(reference_manifest, (str, os.PathLike)):
                with open(reference_manifest, "r", encoding="utf-8") as handle:
                    reference_manifest = json.load(handle)
            self.reference_manifest = self._parse_manifest(reference_manifest or {})
        self.reference_aliases = {}
        if reference_aliases:
            if self.reference_root is None:
                raise EvidenceToolError("reference aliases require a reference root")
            for alias, relative in reference_aliases.items():
                alias = self._canonical_path(alias)
                relative = self._canonical_path(relative)
                if alias not in self.reference_manifest:
                    raise EvidenceToolError("reference alias is not in the trusted manifest")
                self.reference_aliases[alias] = relative
        self.max_text_bytes = self._positive_limit(max_text_bytes, "max_text_bytes")
        self.max_array_bytes = self._positive_limit(max_array_bytes, "max_array_bytes")
        self.max_npz_uncompressed_bytes = self._positive_limit(
            max_npz_uncompressed_bytes, "max_npz_uncompressed_bytes"
        )
        self.max_array_elements = self._positive_limit(max_array_elements, "max_array_elements")
        self._seen: dict[tuple[str, str], str] = {}
        self.schemas = [
            _schema("list_files", {"prefix": {"type": "string", "description": "Optional submission/ or reference/ path prefix."}}, []),
            _schema(
                "read_text",
                {
                    "path": {"type": "string", "description": "submission/<declared-relative-path> or reference/<declared-relative-path>."},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_PAGE},
                    "source": {"type": "string", "enum": ["submission", "reference"]},
                },
                ["path"],
            ),
            _schema(
                "read_reference_text",
                {
                    "path": {"type": "string", "description": "reference/<declared-relative-path>."},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_PAGE},
                },
                ["path"],
            ),
            _schema(
                "inspect_array",
                {
                    "path": {"type": "string"},
                    "member": {"type": "string"},
                    "selection": {
                        "type": "object",
                        "properties": {
                            "axis0_start": {"type": "integer", "minimum": 0},
                            "axis0_stop": {"type": "integer", "minimum": 0},
                        },
                        "additionalProperties": False,
                    },
                },
                ["path"],
            ),
        ]

    @staticmethod
    def _positive_limit(value: int, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
        return value

    @property
    def seen_paths(self) -> list[dict[str, str]]:
        return [
            {"namespace": namespace, "path": path, "sha256": digest}
            for (namespace, path), digest in sorted(self._seen.items())
        ]

    @staticmethod
    def _parse_manifest(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
        if not isinstance(raw, dict):
            raise ValueError("manifest must be a JSON object")
        entries = raw.get("files")
        if entries is None:
            entries = [{"path": key, **value} for key, value in raw.items() if isinstance(value, dict)]
        if not isinstance(entries, list):
            raise ValueError("manifest files must be a list")
        result: dict[str, dict[str, Any]] = {}
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("manifest entries must be objects")
            path = item.get("path")
            digest = item.get("sha256")
            size = item.get("size")
            canonical = EvidenceTools._canonical_path(path)
            if canonical in result:
                raise ValueError(f"duplicate manifest path: {canonical}")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
                raise ValueError(f"invalid SHA-256 for {canonical}")
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise ValueError(f"invalid size for {canonical}")
            result[canonical] = {"path": canonical, "sha256": digest.lower(), "size": size}
            if isinstance(item.get("source"), dict):
                result[canonical]["origin"] = item["source"]
        return result

    @staticmethod
    def _canonical_path(value: Any) -> str:
        if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
            raise EvidenceToolError("path must be a non-empty POSIX relative path")
        p = PurePosixPath(value)
        if p.is_absolute() or any(part in ("", ".", "..") for part in p.parts):
            raise EvidenceToolError("absolute, dot, and parent paths are forbidden")
        canonical = p.as_posix()
        if canonical != value:
            raise EvidenceToolError("path must be canonical")
        return canonical

    def _open_declared(
        self,
        raw_path: Any,
        *,
        root: Path | None = None,
        manifest: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        path = self._canonical_path(raw_path)
        root = self.root if root is None else root
        manifest = self.manifest if manifest is None else manifest
        entry = manifest.get(path)
        if entry is None:
            raise EvidenceToolError("path is not declared in the frozen output manifest")
        flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags_file = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        root_fd = os.open(root, flags_dir)
        current_fd = root_fd
        try:
            physical = self.reference_aliases.get(path, path) if manifest is self.reference_manifest else path
            parts = physical.split("/")
            for part in parts[:-1]:
                next_fd = os.open(part, flags_dir, dir_fd=current_fd)
                if current_fd != root_fd:
                    os.close(current_fd)
                current_fd = next_fd
            fd = os.open(parts[-1], flags_file, dir_fd=current_fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                os.close(fd)
                raise EvidenceToolError("declared evidence must be a regular file")
            if info.st_size != entry["size"]:
                os.close(fd)
                raise EvidenceToolError("file size does not match frozen manifest")
            return fd, entry
        except OSError as exc:
            raise EvidenceToolError(f"cannot safely open declared file: {exc.strerror}") from None
        finally:
            if current_fd != root_fd:
                os.close(current_fd)
            os.close(root_fd)

    @staticmethod
    def _stable_hash(fd: int, max_bytes: int | None = None) -> tuple[str, os.stat_result]:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise EvidenceToolError("opened evidence is not a regular file")
        digest = hashlib.sha256()
        os.lseek(fd, 0, os.SEEK_SET)
        total = 0
        while True:
            block = os.read(fd, _HASH_CHUNK)
            if not block:
                break
            total += len(block)
            if max_bytes is not None and total > max_bytes:
                raise EvidenceToolError(f"file exceeds configured byte limit ({max_bytes})")
            digest.update(block)
        after = os.fstat(fd)
        if EvidenceTools._identity(before) != EvidenceTools._identity(after):
            raise EvidenceToolError("file changed while being read")
        return digest.hexdigest(), after

    @staticmethod
    def _identity(st: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, stat.S_IMODE(st.st_mode))

    def _verified_read(
        self,
        path: str,
        max_bytes: int | None = None,
        *,
        reference: bool = False,
    ) -> tuple[bytes, dict[str, Any]]:
        if reference:
            if self.reference_root is None:
                raise EvidenceToolError("reference evidence is unavailable for this case")
            fd, entry = self._open_declared(
                path, root=self.reference_root, manifest=self.reference_manifest
            )
        else:
            fd, entry = self._open_declared(path)
        try:
            first_hash, first_stat = self._stable_hash(fd, max_bytes)
            if first_hash != entry["sha256"]:
                raise EvidenceToolError("SHA-256 does not match frozen manifest")
            if max_bytes is not None and first_stat.st_size > max_bytes:
                raise EvidenceToolError(f"file exceeds configured byte limit ({max_bytes})")
            os.lseek(fd, 0, os.SEEK_SET)
            chunks: list[bytes] = []
            bytes_read = 0
            while True:
                chunk = os.read(fd, _HASH_CHUNK)
                if not chunk:
                    break
                bytes_read += len(chunk)
                if max_bytes is not None and bytes_read > max_bytes:
                    raise EvidenceToolError(f"file grew beyond configured byte limit ({max_bytes})")
                chunks.append(chunk)
            data = b"".join(chunks)
            second_hash, second_stat = self._stable_hash(fd, max_bytes)
            if self._identity(first_stat) != self._identity(second_stat) or second_hash != first_hash:
                raise EvidenceToolError("file changed during evidence access")
            return data, entry
        finally:
            os.close(fd)

    def list_files(self, prefix: str = "") -> dict[str, Any]:
        if not isinstance(prefix, str):
            raise EvidenceToolError("prefix must be a string")
        prefix = prefix.rstrip("/")
        if prefix:
            namespace, separator, relative_prefix = prefix.partition("/")
            if namespace not in ("submission", "reference"):
                raise EvidenceToolError("prefix must use submission/ or reference/ namespace")
            selected = self.manifest if namespace == "submission" else self.reference_manifest
            if namespace == "reference" and self.reference_root is None:
                raise EvidenceToolError("reference evidence is unavailable for this case")
            relative_prefix = self._canonical_prefix(relative_prefix) if separator and relative_prefix else relative_prefix
            files = [
                {"path": f"{namespace}/{path}", "sha256": entry["sha256"], "size": entry["size"], "namespace": namespace}
                for path, entry in sorted(selected.items())
                if not relative_prefix or path == relative_prefix or path.startswith(relative_prefix + "/")
            ]
        else:
            files = [
                {"path": f"submission/{path}", "sha256": entry["sha256"], "size": entry["size"], "namespace": "submission"}
                for path, entry in sorted(self.manifest.items())
            ]
            files.extend(
                {"path": f"reference/{path}", "sha256": entry["sha256"], "size": entry["size"], "namespace": "reference"}
                for path, entry in sorted(self.reference_manifest.items())
            )
            files.sort(key=lambda item: item["path"])
        for row in files:
            if row["namespace"] == "reference":
                entry = self.reference_manifest[row["path"].removeprefix("reference/")]
                if "origin" in entry:
                    row["origin"] = entry["origin"]
        return {"files": files, "count": len(files), "manifest_only": True}

    @staticmethod
    def _canonical_prefix(prefix: str) -> str:
        if prefix.endswith("/"):
            prefix = prefix[:-1]
        return EvidenceTools._canonical_path(prefix)

    def read_text(
        self,
        path: str,
        offset: int = 0,
        limit: int = _MAX_PAGE,
        source: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise EvidenceToolError("offset must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_PAGE:
            raise EvidenceToolError(f"limit must be between 1 and {_MAX_PAGE}")
        namespace, relative_path = self._split_namespaced(path, source)
        reference = namespace == "reference"
        data, entry = self._verified_read(relative_path, self.max_text_bytes, reference=reference)
        if offset > len(data):
            raise EvidenceToolError("offset is beyond end of file")
        page = data[offset : offset + limit]
        end = offset + len(page)
        try:
            text = page.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            if exc.reason == "unexpected end of data" and exc.end == len(page):
                boundary = exc.start
                if boundary == 0:
                    raise EvidenceToolError("page ends inside a UTF-8 codepoint; retry with a larger limit") from None
                page = page[:boundary]
                text = page.decode("utf-8", errors="strict")
                end = offset + len(page)
            else:
                raise EvidenceToolError("declared text is not valid UTF-8") from None
        self._seen[(namespace, entry["path"])] = entry["sha256"]
        result = {
            "path": f"{namespace}/{entry['path']}",
            "source": namespace,
            "sha256": entry["sha256"],
            "text": text,
            "offset": offset,
            "bytes_returned": len(page),
            "total_bytes": entry["size"],
            "partial": offset > 0 or end < entry["size"],
            "truncated": end < entry["size"],
            "next_offset": end if end < entry["size"] else None,
        }
        if "origin" in entry:
            result["origin"] = entry["origin"]
        return result

    def inspect_array(
        self,
        path: str,
        member: str | None = None,
        selection: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        try:
            import numpy as np
        except ImportError:
            raise EvidenceToolError("array inspection unavailable: NumPy is not installed in this host runtime") from None
        namespace, relative_path = self._split_namespaced(path, None)
        if namespace != "submission":
            raise EvidenceToolError("inspect_array is restricted to submission evidence")
        suffix = Path(relative_path).suffix.lower()
        if suffix not in (".npy", ".npz"):
            raise EvidenceToolError("array path must end in .npy or .npz")
        data, entry = self._verified_read(relative_path, self.max_array_bytes)
        array_member = None
        archive_members: list[str] | None = None
        if suffix == ".npz":
            try:
                expected_members = self._preflight_zip_directory(data)
                with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
                    infos = archive.infolist()
                    if len(infos) != expected_members or len(infos) > _MAX_NPZ_MEMBERS:
                        raise EvidenceToolError("NPZ contains too many members")
                    names = [info.filename for info in infos]
                    if len(names) != len(set(names)):
                        raise EvidenceToolError("NPZ contains duplicate member names")
                    if any(
                        PurePosixPath(name).is_absolute()
                        or ".." in PurePosixPath(name).parts
                        or "\\" in name
                        or "/" in name
                        or not name.endswith(".npy")
                        for name in names
                    ):
                        raise EvidenceToolError("NPZ members must be flat .npy entries with safe names")
                    if sum(info.file_size for info in infos) > self.max_npz_uncompressed_bytes:
                        raise EvidenceToolError("NPZ uncompressed size exceeds configured limit")
                    # Inspect every member header before NumPy can allocate an array.
                    actual_total = 0
                    member_headers: dict[str, tuple[tuple[int, ...], Any, int]] = {}
                    for info in infos:
                        if info.file_size > self.max_array_bytes:
                            raise EvidenceToolError("NPZ member exceeds configured array byte limit")
                        header = bytearray()
                        actual_size = 0
                        with archive.open(info, "r") as member_stream:
                            while True:
                                chunk = member_stream.read(_HASH_CHUNK)
                                if not chunk:
                                    break
                                actual_size += len(chunk)
                                actual_total += len(chunk)
                                if actual_size > self.max_array_bytes or actual_total > self.max_npz_uncompressed_bytes:
                                    raise EvidenceToolError("NPZ decompressed data exceeds configured limits")
                                if len(header) < 64 * 1024 + 12:
                                    needed = 64 * 1024 + 12 - len(header)
                                    header.extend(chunk[:needed])
                        member_headers[info.filename] = self._preflight_npy(
                            bytes(header), np, self.max_array_bytes, None,
                            payload_size=actual_size,
                            require_numeric=False,
                        )
                    npz = np.load(io.BytesIO(data), allow_pickle=False)
                    try:
                        available = list(npz.files)
                        if not available:
                            raise EvidenceToolError("NPZ has no arrays")
                        archive_members = sorted(available)
                        if member is None:
                            if len(available) != 1:
                                raise EvidenceToolError("member is required when NPZ has multiple arrays")
                            member = available[0]
                        if member not in available:
                            raise EvidenceToolError("requested NPZ member is absent")
                        array_member = member
                        selected_header = member_headers[member + ".npy"]
                        if selected_header[1].kind not in "biufcUS":
                            raise EvidenceToolError("selected array must be numeric or fixed-width string")
                        array = npz[member]
                    finally:
                        npz.close()
            except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, zlib.error) as exc:
                if isinstance(exc, EvidenceToolError):
                    raise
                raise EvidenceToolError(f"invalid NPZ: {exc}") from None
        else:
            if member is not None:
                raise EvidenceToolError("member is only valid for NPZ files")
            self._preflight_npy(data, np, self.max_array_bytes, None)
            try:
                array = np.load(io.BytesIO(data), allow_pickle=False)
            except (ValueError, OSError) as exc:
                raise EvidenceToolError(f"invalid NPY: {exc}") from None
        if not isinstance(array, np.ndarray):
            raise EvidenceToolError("input did not contain a numeric array")
        if array.dtype.hasobject:
            raise EvidenceToolError("object dtype arrays are forbidden")
        if array.dtype.kind not in "biufcUS":
            raise EvidenceToolError("only numeric or fixed-width string arrays are supported")
        selected = array
        partial = False
        if selection is not None:
            if not isinstance(selection, dict) or set(selection) - {"axis0_start", "axis0_stop"}:
                raise EvidenceToolError("selection supports only axis0_start and axis0_stop")
            if array.ndim == 0:
                raise EvidenceToolError("cannot slice a scalar array")
            start = selection.get("axis0_start", 0)
            stop = selection.get("axis0_stop", array.shape[0])
            if any(isinstance(x, bool) or not isinstance(x, int) for x in (start, stop)):
                raise EvidenceToolError("selection bounds must be integers")
            if start < 0 or stop < start or stop > array.shape[0]:
                raise EvidenceToolError("selection bounds are outside axis 0")
            selected = array[start:stop]
            partial = start != 0 or stop != array.shape[0]
        if selected.size > self.max_array_elements:
            raise EvidenceToolError("selected array exceeds configured element limit")
        if selected.dtype.kind in "US" and selected.nbytes > _MAX_PAGE:
            raise EvidenceToolError("selected fixed-width string data exceeds the response page limit")
        values = self._json_safe(selected.tolist())
        if (selected.dtype.kind in "US"
                and len(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > _MAX_PAGE):
            raise EvidenceToolError("selected fixed-width string response exceeds the response page limit")
        result = {
            "path": f"submission/{entry['path']}",
            "sha256": entry["sha256"],
            "member": array_member,
            "archive_members": archive_members,
            "dtype": str(array.dtype),
            "shape": list(array.shape),
            "selection_shape": list(selected.shape),
            "selection": selection,
            "values": values,
            "units": None,
            "units_note": "No unit metadata was inferred; consult explicit evidence.",
            "partial": partial,
            "truncated": False,
        }
        self._seen[("submission", entry["path"])] = entry["sha256"]
        return result

    @staticmethod
    def _preflight_zip_directory(data: bytes) -> int:
        # Find a valid EOCD only within the ZIP-mandated maximum comment tail,
        # before ZipFile allocates ZipInfo objects for the central directory.
        tail_start = max(0, len(data) - (65_535 + 22))
        signature = b"PK\x05\x06"
        eocd = -1
        cursor = len(data)
        while True:
            candidate = data.rfind(signature, tail_start, cursor)
            if candidate < 0:
                break
            if candidate + 22 <= len(data):
                fields = struct.unpack_from("<4s4H2LH", data, candidate)
                comment_length = fields[-1]
                if candidate + 22 + comment_length == len(data):
                    eocd = candidate
                    break
            cursor = candidate
        if eocd < 0:
            raise EvidenceToolError("NPZ has no valid ZIP end record")
        if eocd >= 20 and data[eocd - 20 : eocd - 16] == b"PK\x06\x07":
            raise EvidenceToolError("ZIP64 NPZ archives are unsupported")
        (_sig, disk, central_disk, entries_disk, entries_total, central_size, central_offset, _comment) = struct.unpack_from(
            "<4s4H2LH", data, eocd
        )
        if disk or central_disk or entries_disk != entries_total:
            raise EvidenceToolError("multi-disk ZIP archives are unsupported")
        if entries_total == 0xFFFF or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF:
            raise EvidenceToolError("ZIP64 NPZ archives are unsupported")
        if entries_total > _MAX_NPZ_MEMBERS:
            raise EvidenceToolError("NPZ contains too many members")
        if central_size > _MAX_ZIP_CENTRAL_DIRECTORY:
            raise EvidenceToolError("NPZ central directory exceeds configured limit")
        if central_offset + central_size != eocd or central_offset > len(data):
            raise EvidenceToolError("NPZ central directory bounds are invalid")
        return entries_total

    @staticmethod
    def _preflight_npy(
        data: bytes,
        np: Any,
        max_bytes: int,
        max_elements: int | None,
        *,
        payload_size: int | None = None,
        require_numeric: bool = True,
    ) -> tuple[tuple[int, ...], Any, int]:
        stream = io.BytesIO(data)
        try:
            version = np.lib.format.read_magic(stream)
            if version == (1, 0):
                shape, _fortran_order, dtype = np.lib.format.read_array_header_1_0(stream, max_header_size=64 * 1024)
            elif version == (2, 0):
                shape, _fortran_order, dtype = np.lib.format.read_array_header_2_0(stream, max_header_size=64 * 1024)
            else:
                raise EvidenceToolError(f"unsupported NPY format version: {version}")
        except EvidenceToolError:
            raise
        except (ValueError, EOFError, OSError) as exc:
            raise EvidenceToolError(f"invalid NPY header: {exc}") from None
        if dtype.hasobject:
            raise EvidenceToolError("object dtype arrays are forbidden")
        if dtype.itemsize <= 0:
            raise EvidenceToolError("zero-sized element dtypes are unsupported")
        if require_numeric and dtype.kind not in "biufcUS":
            raise EvidenceToolError("only numeric or fixed-width string arrays are supported")
        if max_elements is None:
            max_elements = max_bytes // max(1, dtype.itemsize)
        elements = 1
        for dimension in shape:
            if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension < 0:
                raise EvidenceToolError("invalid NPY shape")
            if dimension > max_elements:
                raise EvidenceToolError("array exceeds configured byte-derived element limit")
            elements *= dimension
            if elements > max_elements:
                raise EvidenceToolError("array exceeds configured byte-derived element limit")
        expected_bytes = elements * dtype.itemsize
        if expected_bytes > max_bytes:
            raise EvidenceToolError("array exceeds configured uncompressed byte limit")
        data_offset = stream.tell()
        available_payload = len(data) - data_offset if payload_size is None else payload_size - data_offset
        if available_payload != expected_bytes:
            raise EvidenceToolError("NPY payload size does not match its header")
        return tuple(shape), dtype, data_offset

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, list):
            return [EvidenceTools._json_safe(item) for item in value]
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                raise EvidenceToolError("fixed-width byte labels are not valid UTF-8") from None
        if isinstance(value, str):
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                raise EvidenceToolError("fixed-width Unicode labels contain invalid UTF-8 code points") from None
            return value
        if isinstance(value, complex):
            return {"real": EvidenceTools._json_safe(value.real), "imag": EvidenceTools._json_safe(value.imag)}
        if isinstance(value, float):
            if value != value:
                return "NaN"
            if value == float("inf"):
                return "Infinity"
            if value == float("-inf"):
                return "-Infinity"
        return value

    def read_reference_text(self, path: str, offset: int = 0, limit: int = _MAX_PAGE) -> dict[str, Any]:
        if not isinstance(path, str):
            raise EvidenceToolError("path must be a string")
        if not path.startswith("reference/"):
            path = "reference/" + path
        return self.read_text(path=path, offset=offset, limit=limit)

    @staticmethod
    def _split_namespaced(path: str, explicit: str | None) -> tuple[str, str]:
        if explicit is not None and explicit not in ("submission", "reference"):
            raise EvidenceToolError("source must be submission or reference")
        if not isinstance(path, str) or "/" not in path:
            raise EvidenceToolError("path must be prefixed with submission/ or reference/")
        namespace, relative = path.split("/", 1)
        if namespace not in ("submission", "reference"):
            raise EvidenceToolError("path must be prefixed with submission/ or reference/")
        if explicit is not None and explicit != namespace:
            raise EvidenceToolError("path namespace conflicts with source")
        return namespace, EvidenceTools._canonical_path(relative)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if not isinstance(arguments, dict):
                raise EvidenceToolError("arguments must be an object")
            if name == "list_files":
                result = self.list_files(**arguments)
                return {"ok": True, "result": result, "evidence": {"manifest_only": True}}
            if name == "read_text":
                result = self.read_text(**arguments)
                evidence = {"path": result["path"], "sha256": result["sha256"], "source": result["source"], "partial": result["partial"], "truncated": result["truncated"]}
                if result["source"] == "reference":
                    evidence["candidate_evidence"] = False
                return {"ok": True, "result": result, "evidence": evidence}
            if name == "read_reference_text":
                result = self.read_reference_text(**arguments)
                return {"ok": True, "result": result, "evidence": {"path": result["path"], "sha256": result["sha256"], "source": "reference", "candidate_evidence": False, "partial": result["partial"], "truncated": result["truncated"]}}
            if name == "inspect_array":
                result = self.inspect_array(**arguments)
                return {"ok": True, "result": result, "evidence": {"path": result["path"], "sha256": result["sha256"], "partial": result["partial"], "truncated": False}}
            raise EvidenceToolError("unknown evidence tool")
        except (EvidenceToolError, TypeError, OSError) as exc:
            return {"ok": False, "error": str(exc), "evidence": {"partial": False}}

