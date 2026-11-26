# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: bidirectional downhill paths and endpoint identity.
from __future__ import annotations
import csv,hashlib,json,math,os,subprocess,sys,tempfile
from pathlib import Path
"""Standard-library safeguards for untrusted candidate output trees.

Call before any scientific parser (including ASE). The returned manifest is a
bounded inventory of regular files; malformed or resource-exhausting candidate
trees raise :class:`CandidateInputError` and should be scored as FAIL.
"""

import csv
import hashlib
import io
import json
import math
import os
import re
import stat
import struct
from pathlib import Path


class CandidateInputError(ValueError):
    """The candidate submission is unsafe, malformed, or exceeds its budget."""


# Derived from the frozen public case protocols. Event caps include up to two
# event-sidecar representations (for example input and evaluation JSONL).
_CASE_LIMITS = {
    "case-01-derivative-consistency": dict(atoms=24, frames=2, events=80, csv=256),
    "case-02-curvature-bias": dict(atoms=48, frames=0, events=0, csv=64),
    "case-03-hessian-comparison": dict(atoms=48, frames=4, events=64, csv=700),
    "case-04-saddle-search": dict(atoms=24, frames=508, events=1240, csv=1280),
    "case-05-initial-guess-robustness": dict(atoms=16, frames=660, events=1640, csv=1700),
    "case-06-path-identity": dict(atoms=32, frames=245, events=1205, csv=2600),
}


def _lstat(path: Path, label: str):
    try:
        return path.lstat()
    except OSError as exc:
        raise CandidateInputError("cannot inspect %s: %s" % (label, exc)) from exc


def _regular_file_bytes(path: Path, expected_stat, max_file_bytes: int) -> bytes:
    """Read only the lstat'ed regular file, resisting symlink/type swaps."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise CandidateInputError("cannot safely open %s: %s" % (path.name, exc)) from exc
    try:
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_dev != expected_stat.st_dev
                or opened.st_ino != expected_stat.st_ino):
            raise CandidateInputError("candidate file changed during inspection: %s" % path.name)
        if opened.st_size > max_file_bytes:
            raise CandidateInputError("candidate file exceeds %d-byte limit: %s" % (max_file_bytes, path.name))
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, max_file_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_file_bytes:
                raise CandidateInputError("candidate file exceeds %d-byte limit: %s" % (max_file_bytes, path.name))
        if total != opened.st_size:
            raise CandidateInputError("candidate file changed while reading: %s" % path.name)
        after = os.fstat(fd)
        if after.st_size != opened.st_size or after.st_mtime_ns != opened.st_mtime_ns:
            raise CandidateInputError("candidate file changed while reading: %s" % path.name)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _count_xyz_frames(data: bytes, path: str, max_atoms: int, max_per_file: int) -> int:
    """Bound XYZ frame sizes from each header before any ASE parsing."""
    stream = io.BytesIO(data)
    frames = 0
    while True:
        header = stream.readline().strip()
        if not header:
            if stream.tell() == len(data):
                break
            raise CandidateInputError("blank XYZ atom-count header in %s" % path)
        if not header or not re.fullmatch(br"[0-9]+", header):
            raise CandidateInputError("invalid XYZ atom-count header in %s" % path)
        atoms = int(header)
        if atoms <= 0 or atoms > max_atoms:
            raise CandidateInputError("XYZ atom count %d exceeds limit %d in %s" % (atoms, max_atoms, path))
        # Read the comment and N atom records only after validating the header.
        if not stream.readline() or sum(1 for _ in range(atoms) if stream.readline()) != atoms:
            raise CandidateInputError("truncated XYZ frame in %s" % path)
        frames += 1
        if frames > max_per_file:
            raise CandidateInputError("XYZ frame count exceeds limit %d in %s" % (max_per_file, path))
    return frames


def _stream_xyz_file(path: Path, expected_stat, label: str, max_file_bytes: int,
                     max_atoms: int, max_per_file: int):
    """Stream XYZ records and check atom coordinates before any ASE reader."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise CandidateInputError("cannot safely open XYZ %s: %s" % (label, exc)) from exc
    digest = hashlib.sha256()
    try:
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_dev != expected_stat.st_dev
                or opened.st_ino != expected_stat.st_ino):
            raise CandidateInputError("XYZ changed during inspection: %s" % label)
        if opened.st_size > max_file_bytes:
            raise CandidateInputError("candidate file exceeds %d-byte limit: %s" % (max_file_bytes, label))
        with os.fdopen(fd, "rb", closefd=False) as stream:
            frames = 0
            total = 0
            while True:
                header = stream.readline(128)
                if not header:
                    break
                total += len(header); digest.update(header)
                if total > max_file_bytes or len(header) >= 128 or not header.endswith(b"\n"):
                    raise CandidateInputError("invalid or oversized XYZ atom-count header in %s" % label)
                header = header.strip()
                if not re.fullmatch(br"[0-9]+", header):
                    raise CandidateInputError("invalid XYZ atom-count header in %s" % label)
                atoms = int(header)
                if atoms <= 0 or atoms > max_atoms:
                    raise CandidateInputError("XYZ atom count %d exceeds limit %d in %s" % (atoms, max_atoms, label))
                comment = stream.readline(1024 * 1024 + 1)
                total += len(comment); digest.update(comment)
                if not comment or total > max_file_bytes or len(comment) > 1024 * 1024:
                    raise CandidateInputError("missing or oversized XYZ comment line in %s" % label)
                for atom_index in range(atoms):
                    record = stream.readline(4097)
                    total += len(record); digest.update(record)
                    if not record or total > max_file_bytes or len(record) > 4096:
                        raise CandidateInputError("missing or oversized XYZ atom record in %s" % label)
                    fields = record.split(None, 4)
                    if len(fields) < 4:
                        raise CandidateInputError("malformed XYZ atom record in %s" % label)
                    try:
                        xyz = [float(fields[i]) for i in (1, 2, 3)]
                    except (ValueError, IndexError) as exc:
                        raise CandidateInputError("non-numeric XYZ coordinate in %s" % label) from exc
                    if not all(math.isfinite(value) for value in xyz):
                        raise CandidateInputError("non-finite XYZ coordinate in %s" % label)
                frames += 1
                if frames > max_per_file:
                    raise CandidateInputError("XYZ frame count exceeds limit %d in %s" % (max_per_file, label))
        if total != opened.st_size:
            raise CandidateInputError("XYZ file changed or contains an unparsed suffix: %s" % label)
        after = os.fstat(fd)
        if after.st_size != opened.st_size or after.st_mtime_ns != opened.st_mtime_ns:
            raise CandidateInputError("XYZ changed while reading: %s" % label)
        return frames, digest.hexdigest(), total
    finally:
        os.close(fd)


def _dtype_bytes(dtype: str) -> int:
    name = dtype.lstrip("<>!=|")
    table = {"float64": 8, "float32": 4, "int64": 8, "int32": 4,
             "int16": 2, "int8": 1, "uint64": 8, "uint32": 4,
             "uint16": 2, "uint8": 1, "bool": 1,
             "f8": 8, "f4": 4, "i8": 8, "i4": 4, "i2": 2, "i1": 1,
             "u8": 8, "u4": 4, "u2": 2, "u1": 1, "?": 1}
    if name not in table:
        raise CandidateInputError("unsupported ULM array dtype: %s" % dtype)
    return table[name]


def _validate_ulm_header_record(record, file_size: int, max_atoms: int) -> None:
    """Validate ULM array dimensions and byte ranges without materializing arrays."""
    stack = [record]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            spec = value.get("ndarray")
            if isinstance(spec, list) and len(spec) == 3:
                shape, dtype, offset = spec
                if (not isinstance(shape, list) or len(shape) > 4
                        or any(type(dim) is not int or dim < 0 for dim in shape)):
                    raise CandidateInputError("invalid native.traj ULM ndarray shape")
                count = 1
                for dim in shape:
                    count *= dim
                    if count > max(1024, max_atoms * max_atoms * 9):
                        raise CandidateInputError("native.traj ULM ndarray dimensions exceed limit")
                if not isinstance(dtype, str) or type(offset) is not int or offset < 48:
                    raise CandidateInputError("invalid native.traj ULM ndarray metadata")
                nbytes = count * _dtype_bytes(dtype)
                if offset + nbytes > file_size:
                    raise CandidateInputError("native.traj ULM ndarray points beyond file bounds")
                if shape and shape[0] > max_atoms and shape not in ([3, 3],):
                    raise CandidateInputError("native.traj ULM array exceeds atom limit")
            for child in value.values():
                stack.append(child)
        elif isinstance(value, list):
            stack.extend(value)


def _count_ulm_frames(data: bytes, path: str, max_atoms: int, max_frames: int) -> int:
    if len(data) < 48 or data[:8] not in (b"- of Ulm", b"AFFormat"):
        raise CandidateInputError("native trajectory is not a valid ULM file: %s" % path)
    try:
        version, nitems, pos0 = struct.unpack("<qqq", data[24:48])
    except struct.error as exc:
        raise CandidateInputError("truncated ULM header: %s" % path) from exc
    if nitems <= 0 or nitems > max_frames:
        raise CandidateInputError("native.traj frame count exceeds limit %d" % max_frames)
    if pos0 < 48 or pos0 + nitems * 8 > len(data):
        raise CandidateInputError("native.traj ULM offset table exceeds file bounds")
    offsets = struct.unpack("<" + "q" * nitems, data[pos0:pos0 + nitems * 8]) if nitems else ()
    if any(off < 48 or off + 8 > len(data) for off in offsets):
        raise CandidateInputError("native.traj ULM item offset is invalid")
    if tuple(offsets) != tuple(sorted(set(offsets))):
        raise CandidateInputError("native.traj ULM item offsets are not strictly increasing")
    for offset in offsets:
        size = struct.unpack("<q", data[offset:offset + 8])[0]
        begin, end = offset + 8, offset + 8 + size
        if size < 0 or end > len(data) or size > 1024 * 1024:
            raise CandidateInputError("native.traj ULM metadata record exceeds bounds")
        try:
            record = json.loads(data[begin:end].decode("utf-8"))
        except Exception as exc:
            raise CandidateInputError("native.traj ULM metadata is malformed: %s" % exc) from exc
        if not isinstance(record, dict):
            raise CandidateInputError("native.traj ULM item metadata is not an object")
        _validate_ulm_header_record(record, len(data), max_atoms)
        numbers = record.get("numbers.", {}).get("ndarray") if isinstance(record.get("numbers."), dict) else None
        positions = record.get("positions.", {}).get("ndarray") if isinstance(record.get("positions."), dict) else None
        if numbers is not None:
            shape = numbers[0] if isinstance(numbers, list) and numbers else None
            if not isinstance(shape, list) or len(shape) != 1 or shape[0] <= 0 or shape[0] > max_atoms:
                raise CandidateInputError("native.traj atom-number array exceeds limit")
        if positions is not None:
            shape = positions[0] if isinstance(positions, list) and positions else None
            if not isinstance(shape, list) or len(shape) != 2 or shape[1] != 3 or shape[0] > max_atoms:
                raise CandidateInputError("native.traj position-array shape exceeds atom limit")
    return nitems


def safe_candidate_path(root, value, *, must_exist=True):
    """Resolve a candidate-reported relative path inside ``root`` only.

    Each path component is inspected with lstat; symlinks and special files are
    rejected before callers open the target.
    """
    base = Path(root)
    base_stat = _lstat(base, "candidate root")
    if stat.S_ISLNK(base_stat.st_mode) or not stat.S_ISDIR(base_stat.st_mode):
        raise CandidateInputError("candidate root must be a real directory")
    base = base.resolve(strict=True)
    try:
        raw = Path(os.fspath(value))
    except Exception as exc:
        raise CandidateInputError("candidate path must be a string") from exc
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise CandidateInputError("candidate path must be a nonempty string")
    if raw.is_absolute():
        try:
            relative = raw.relative_to(base)
        except ValueError as exc:
            raise CandidateInputError("candidate path escapes submission root") from exc
    else:
        relative = raw
    if any(part in ("", ".", "..") for part in relative.parts):
        raise CandidateInputError("candidate path has unsafe components")
    cursor = base
    for index, part in enumerate(relative.parts):
        cursor = cursor / part
        try:
            current = cursor.lstat()
        except FileNotFoundError:
            if must_exist:
                raise CandidateInputError("candidate path does not exist: %s" % relative.as_posix())
            return cursor
        except OSError as exc:
            raise CandidateInputError("cannot inspect candidate path: %s" % exc) from exc
        if stat.S_ISLNK(current.st_mode):
            raise CandidateInputError("candidate path contains a symlink: %s" % relative.as_posix())
        is_final = index == len(relative.parts) - 1
        if not is_final and not stat.S_ISDIR(current.st_mode):
            raise CandidateInputError("candidate path parent is not a directory")
        if is_final and not (stat.S_ISREG(current.st_mode) or stat.S_ISDIR(current.st_mode)):
            raise CandidateInputError("candidate path is not a regular file or directory")
    return cursor


def guard_submission(root, max_total_bytes=64 * 1024 * 1024,
                     max_file_bytes=16 * 1024 * 1024, max_files=1024, *,
                     case_id=None, max_xyz_atoms=None, max_xyz_frames=None,
                     max_event_rows=None, max_frame_count=None, max_csv_rows=None):
    """Safely inventory and bound a candidate tree before scientific parsing.

    Event, CSV, XYZ and ASE ULM frame limits are case-specific and derived from
    the frozen task budgets. Explicit keyword limits can override them for
    isolated unit tests or a future protocol revision.
    """
    base = Path(root)
    base_stat = _lstat(base, "candidate root")
    if stat.S_ISLNK(base_stat.st_mode) or not stat.S_ISDIR(base_stat.st_mode):
        raise CandidateInputError("candidate root must be a real directory")
    base = base.resolve(strict=True)
    case_id = case_id or os.environ.get("CCB_CASE_ID")
    limits = _CASE_LIMITS.get(case_id, {})
    max_xyz_atoms = max_xyz_atoms if max_xyz_atoms is not None else limits.get("atoms", 48)
    max_xyz_frames = max_xyz_frames if max_xyz_frames is not None else limits.get("frames", 256)
    max_event_rows = max_event_rows if max_event_rows is not None else limits.get("events", 5000)
    max_frame_count = max_frame_count if max_frame_count is not None else limits.get("frames", 256)
    max_csv_rows = max_csv_rows if max_csv_rows is not None else limits.get("csv", 10000)
    if min(max_total_bytes, max_file_bytes, max_files, max_xyz_atoms, max_csv_rows) <= 0:
        raise ValueError("submission guard limits must be positive")
    if max_xyz_frames < 0 or max_event_rows < 0 or max_frame_count < 0:
        raise ValueError("submission guard limits must be positive")
    files = {}
    stack = [(base, 0)]
    total_bytes = event_rows = csv_rows = frame_count = dir_count = 0
    while stack:
        directory, depth = stack.pop()
        if depth > 32:
            raise CandidateInputError("candidate directory depth exceeds 32")
        try:
            scan = os.scandir(str(directory))
        except OSError as exc:
            raise CandidateInputError("cannot enumerate candidate directory: %s" % exc) from exc
        with scan:
            for entry in scan:
                path = Path(entry.path)
                label = path.relative_to(base).as_posix()
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise CandidateInputError("cannot lstat candidate entry %s: %s" % (label, exc)) from exc
                mode = entry_stat.st_mode
                if stat.S_ISLNK(mode):
                    raise CandidateInputError("candidate submission contains symlink: %s" % label)
                if stat.S_ISDIR(mode):
                    dir_count += 1
                    if dir_count > 2048:
                        raise CandidateInputError("candidate submission exceeds 2048-directory limit")
                    stack.append((path, depth + 1))
                    continue
                if not stat.S_ISREG(mode):
                    raise CandidateInputError("candidate submission contains nonregular file: %s" % label)
                if len(files) >= max_files:
                    raise CandidateInputError("candidate submission exceeds %d-file limit" % max_files)
                if entry_stat.st_size < 0 or entry_stat.st_size > max_file_bytes:
                    raise CandidateInputError("candidate file exceeds %d-byte limit: %s" % (max_file_bytes, label))
                total_bytes += entry_stat.st_size
                if total_bytes > max_total_bytes:
                    raise CandidateInputError("candidate submission exceeds %d-byte total limit" % max_total_bytes)
                suffix = path.suffix.lower()
                local_frames = 0
                if suffix in (".xyz", ".extxyz"):
                    local_frames, file_sha, file_bytes = _stream_xyz_file(path, entry_stat, label,
                        max_file_bytes, max_xyz_atoms, max_xyz_frames)
                    data = None
                    frame_count += local_frames
                else:
                    data = _regular_file_bytes(path, entry_stat, max_file_bytes)
                    file_sha, file_bytes = hashlib.sha256(data).hexdigest(), len(data)
                if suffix == ".traj":
                    local_frames = _count_ulm_frames(data, label, max_xyz_atoms, max_xyz_frames)
                    frame_count += local_frames
                if frame_count > max_frame_count:
                    raise CandidateInputError("candidate trajectories exceed %d-frame total limit" % max_frame_count)
                if suffix == ".csv":
                    try:
                        text = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8-sig", newline="")
                        rows = 0
                        for _ in csv.reader(text):
                            rows += 1
                            if rows - 1 + csv_rows > max_csv_rows:
                                raise CandidateInputError("candidate CSV rows exceed case budget %d" % max_csv_rows)
                    except (UnicodeDecodeError, csv.Error) as exc:
                        raise CandidateInputError("malformed candidate CSV %s: %s" % (label, exc)) from exc
                    csv_rows += max(0, rows - 1)
                    if csv_rows > max_csv_rows:
                        raise CandidateInputError("candidate CSV rows exceed case budget %d" % max_csv_rows)
                if suffix == ".jsonl" or (suffix == ".csv" and any(token in path.name.lower() for token in ("event", "execution_trace"))):
                    event_rows += data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
                    if event_rows > max_event_rows:
                        raise CandidateInputError("candidate event records exceed case budget %d" % max_event_rows)
                files[label] = {"bytes": file_bytes, "sha256": file_sha,
                                "frames": local_frames}
    return {"files": files, "file_count": len(files), "total_bytes": total_bytes,
            "csv_rows": csv_rows, "event_rows": event_rows, "frame_count": frame_count}

_DEPENDENCY_ERROR=None
try:
    import numpy as np
    import networkx as nx
    from ase.io import read
    from ase import Atoms
except Exception as _exc:  # report dependency failures through the standard ENV_INVALID channel
    _DEPENDENCY_ERROR=f"required verifier dependency import failed: {_exc}"

ROOT=Path(os.environ.get("APP","/app")).parent;TESTS=Path(os.environ.get("TESTS","/tests"))
class InvalidEnvironment(Exception):pass
class ScientificFailure(Exception):pass
def emit(status,reason,code=0,reward=None,details=None):
    obj={"status":status,"reason":str(reason)}
    if reward is not None:obj["reward"]=reward
    if details:obj["details"]=details
    print(json.dumps(obj,ensure_ascii=False,allow_nan=False));return code
REFS=None
def load_refs():
    global REFS
    try:
        raw=(Path(__file__).resolve().parent/"refs.json").read_bytes()
        if hashlib.sha256(raw).hexdigest()!="48ae2e79870ccaff0b7bb3bad76db4c6245aef7ab61f23a6d2c822f15a135216":raise ValueError("refs.json SHA-256 mismatch")
        data=json.loads(raw.decode("utf-8"))
        if not isinstance(data,dict) or set(data)!={"schema","case_id","kind","verifier","thresholds","tolerances","limits","reference_values"}:raise ValueError("refs.json has invalid top-level schema")
        if data["schema"]!="bench21-case-refs/1" or data["case_id"]!="case-06-path-identity" or data["verifier"]!="tests/verify.py" or not isinstance(data["kind"],str) or not data["kind"]:raise ValueError("refs.json identity/schema mismatch")
        for key in ("thresholds","tolerances","limits","reference_values"):
            if not isinstance(data[key],dict) or not data[key]:raise ValueError(f"refs.json {key} must be a nonempty object")
        hashes=data["reference_values"].get("input_sha256")
        if not isinstance(hashes,dict) or not hashes or any(not isinstance(k,str) or not isinstance(v,str) or len(v)!=64 or any(c not in "0123456789abcdef" for c in v) for k,v in hashes.items()):raise ValueError("refs.json input hashes are malformed")
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in data["tolerances"].values()):raise ValueError("refs.json tolerances must be finite numbers")
        def threshold_value(v):
            return (type(v) in (int,float) and math.isfinite(v)) or (isinstance(v,str) and bool(v)) or (isinstance(v,list) and bool(v) and all(type(x) in (int,float) and math.isfinite(x) for x in v))
        if any(not threshold_value(v) for v in data["thresholds"].values()):raise ValueError("refs.json thresholds have invalid types")
        for key,value in data["reference_values"].items():
            if key=="input_sha256":continue
            if not (isinstance(value,str) and value) and not (isinstance(value,dict) and all(isinstance(k,str) and isinstance(v,str) for k,v in value.items())):raise ValueError("refs.json reference_values have invalid types")
        if any(type(v) is not int or v<0 for v in data["limits"].values()):raise ValueError("refs.json limits must be nonnegative integers")
        REFS=data;return data
    except Exception as exc:raise InvalidEnvironment(f"trusted refs.json is missing or invalid: {type(exc).__name__}: {exc}")

def asset(name):
    for p in (Path(os.environ.get("APP","/app"))/"assets"/name,ROOT/"environment/assets"/name):
        if p.is_file():
            if hashlib.sha256(p.read_bytes()).hexdigest()!=load_refs()["reference_values"]["input_sha256"][name]:raise InvalidEnvironment(f"evaluation asset hash mismatch: {name}")
            return p
    raise InvalidEnvironment(f"evaluation asset missing: {name}")
def read_frames(p):
    try:return read(str(p),index=":")
    except Exception as e:raise ScientificFailure(f"cannot parse trajectory {p.name}: {e}")
def csv_rows(p,cols):
    try:
        lines=[]
        with p.open("rb") as f:
            for i,raw in enumerate(f):
                if i>1200:raise ScientificFailure(f"{p.name} exceeds its row limit")
                if len(raw)>32768:raise ScientificFailure(f"{p.name} contains an oversized row")
                lines.append(raw.decode("utf-8-sig" if i==0 else "utf-8"))
        if not lines:raise ScientificFailure(f"{p.name} is empty")
        rd=csv.DictReader(lines);rows=list(rd);names=rd.fieldnames or []
    except Exception as e:raise ScientificFailure(f"cannot read {p.name}: {e}")
    if not rows or not set(cols).issubset(names):raise ScientificFailure(f"{p.name} missing required rows or columns")
    return rows
def candidate_file(root,relative):
    try:return safe_candidate_path(root,relative)
    except CandidateInputError as e:raise ScientificFailure(str(e))
def finite_number(value,label):
    try:number=float(value)
    except Exception as e:raise ScientificFailure(f"{label} must be numeric: {e}")
    if not math.isfinite(number):raise ScientificFailure(f"{label} must be finite")
    return number
def finite_int(value,label):
    number=finite_number(value,label)
    if not number.is_integer():raise ScientificFailure(f"{label} must be an integer")
    return int(number)
def path_search_direction(forces,previous_force,previous_direction,method_id):
    forces=np.asarray(forces,float)
    if method_id=="steepest-descent/v1" or previous_force is None:return forces.copy()
    if method_id!="pr-plus-conjugate-gradient/v1":raise ScientificFailure("unsupported path method")
    diff=forces-np.asarray(previous_force,float)
    beta=max(0.,float(np.sum(forces*diff)/max(float(np.sum(np.asarray(previous_force,float)**2)),1e-20)))
    search=forces+beta*np.asarray(previous_direction,float)
    return search if float(np.sum(forces*search))>0. else forces.copy()
def replay_path_step(forces,previous_force,previous_direction,old_energy,deltas,energies,event_types,method_id):
    """Independently replay a complete synthetic/observed Armijo backtracking step."""
    forces=np.asarray(forces,float);deltas=[np.asarray(x,float) for x in deltas];energies=list(map(float,energies))
    if not deltas or len(deltas)!=len(energies) or len(deltas)!=len(event_types):raise ScientificFailure("path step event arrays must be nonempty and aligned")
    if event_types[-1]!="accepted_trial" or any(t!="rejected_trial" for t in event_types[:-1]):raise ScientificFailure("path step must contain rejected trials followed by one accepted trial")
    search=path_search_direction(forces,previous_force,previous_direction,method_id)
    atom_norm=float(np.max(np.linalg.norm(search,axis=1)))
    scale=min(.08/max(atom_norm,1e-20),.25/max(atom_norm,1e-20))
    for idx,(delta,energy,kind) in enumerate(zip(deltas,energies,event_types)):
        expected=search*scale*(.5**idx)
        if not close(delta,expected,2e-6,1e-5):raise ScientificFailure("path event displacement differs from independently replayed direction/backtracking scale")
        if np.max(np.linalg.norm(delta,axis=1))>.080001:raise ScientificFailure("path trial exceeds maximum per-atom displacement")
        work=float(np.sum(forces*delta)); threshold=float(old_energy)-min(REFS["thresholds"]["armijo_absolute_eV"],REFS["thresholds"]["armijo_relative_work"]*work)
        if kind=="rejected_trial" and energy<=threshold+REFS["tolerances"]["armijo_energy_abs_eV"]:raise ScientificFailure("rejected trial satisfies Armijo acceptance condition")
        if kind=="accepted_trial" and energy>threshold+REFS["tolerances"]["armijo_energy_abs_eV"]:raise ScientificFailure("accepted trial fails Armijo acceptance condition")
    # Protocol: halve only the current trial displacement after rejection.
    # The next PR+ step reuses the unscaled search direction, not the accepted scale.
    return search,forces.copy(),search
def xyz_preflight(path,expected_symbols,max_frames):
    """Validate every XYZ record before ASE sees attacker-controlled atom counts."""
    frames=0
    try:
        with path.open("rt",encoding="utf-8",errors="strict",newline="") as stream:
            while True:
                header=stream.readline()
                if header=="":break
                if not header.strip().isdigit():raise ScientificFailure(f"{path.name} has an invalid atom-count header")
                natoms=int(header.strip())
                expected_natoms=len(expected_symbols) if expected_symbols is not None else 16
                if natoms!=expected_natoms:raise ScientificFailure(f"{path.name} must contain exactly {expected_natoms} atoms per frame")
                comment=stream.readline()
                if comment=="":raise ScientificFailure(f"{path.name} has a truncated frame comment")
                for atom_index in range(expected_natoms):
                    row=stream.readline()
                    if row=="":raise ScientificFailure(f"{path.name} has a truncated frame")
                    fields=row.split()
                    if len(fields)<4 or not fields[0].isalpha():raise ScientificFailure(f"{path.name} atom {atom_index} has invalid symbol/coordinates")
                    for component,value in enumerate(fields[1:4]):finite_number(value,f"{path.name} coordinate {atom_index}:{component}")
                frames+=1
                if frames>max_frames:raise ScientificFailure(f"{path.name} exceeds {max_frames} frames")
    except ScientificFailure:raise
    except Exception as e:raise ScientificFailure(f"cannot safely inspect {path.name}: {e}")
    if frames==0:raise ScientificFailure(f"{path.name} contains no frames")
    return frames
def matrix_file(path,rows,cols):
    parsed=[]
    try:
        with path.open("rb") as stream:
            for i,raw in enumerate(stream,1):
                if i>rows:raise ScientificFailure(f"{path.name} contains too many rows")
                if len(raw)>cols*64+64:raise ScientificFailure(f"{path.name} contains an oversized row")
                values=raw.decode("ascii").strip().split(",")
                if len(values)!=cols:raise ScientificFailure(f"{path.name} must have {cols} columns")
                parsed.append([finite_number(v,f"{path.name} matrix value") for v in values])
    except ScientificFailure:raise
    except Exception as e:raise ScientificFailure(f"cannot parse {path.name}: {e}")
    result=np.asarray(parsed,float)
    if result.shape!=(rows,cols) or not np.isfinite(result).all():raise ScientificFailure(f"{path.name} must be finite {rows}x{cols}")
    return result
def close(a,b,atol,rtol=0):
    a=np.asarray(a,float);b=np.asarray(b,float)
    return a.shape==b.shape and np.isfinite(a).all() and bool(np.all(np.abs(a-b)<=atol+rtol*np.abs(b)))
def replay(calc,atoms,hessian,label):
    try:return calc.evaluate(atoms,hessian=hessian)
    except Exception as e:raise InvalidEnvironment(f"fixed NewtonNet replay failed at {label}: {e}")
def coords_hash(pos):
    payload=json.dumps(np.asarray(pos,float).tolist(),separators=(",",":"),allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()
def obabel_graph(atoms):
    with tempfile.TemporaryDirectory() as td:
        source=Path(td)/"graph.xyz";sdf=Path(td)/"graph.sdf"
        source.write_text(str(len(atoms))+"\nendpoint\n"+"\n".join(f"{s} {x:.12f} {y:.12f} {z:.12f}" for s,(x,y,z) in zip(atoms.get_chemical_symbols(),atoms.positions))+"\n")
        try:proc=subprocess.run(["obabel","-ixyz",str(source),"-osdf","-O",str(sdf)],text=True,capture_output=True,timeout=30)
        except Exception as e:raise InvalidEnvironment(f"Open Babel graph-perception runtime unavailable: {e}")
        if proc.returncode!=0 or not sdf.is_file():raise InvalidEnvironment(f"Open Babel XYZ import failed: {proc.stderr.strip()}")
        lines=sdf.read_text().splitlines()
    if "M  END" not in lines:raise InvalidEnvironment("Open Babel produced incomplete SDF")
    i=next((i for i,x in enumerate(lines) if "V2000" in x),-1)
    if i<0:raise InvalidEnvironment("Open Babel SDF has no V2000 counts")
    na=int(lines[i][:3]);nb=int(lines[i][3:6]);g=nx.Graph()
    for atom in range(na):g.add_node(atom,element=lines[i+1+atom][31:34].strip())
    edges=[]
    for j in range(i+1+na,i+1+na+nb):
        row=lines[j];a,b,order=int(row[:3])-1,int(row[3:6])-1,int(row[6:9]);g.add_edge(a,b,bond_order=order);edges.append((a,b,order))
    canonical={"elements":[g.nodes[k]["element"] for k in range(na)],"edges":[list(e) for e in sorted((min(a,b),max(a,b),o) for a,b,o in edges)]}
    digest=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return g,digest
def iso(a,b):
    return nx.is_isomorphic(a,b,node_match=lambda x,y:x.get("element")==y.get("element"))
def main(argv):
    if len(argv)!=2:return emit("ENV_INVALID","usage: verify.py <submission_dir>",2)
    if _DEPENDENCY_ERROR:return emit("ENV_INVALID",_DEPENDENCY_ERROR,2)
    final=Path(argv[1])
    try:
        load_refs()
        try:
            guard_submission(final,case_id="case-06-path-identity",max_xyz_atoms=16,
                max_xyz_frames=REFS["limits"]["trajectory_frames_per_direction_max"],max_frame_count=245,max_event_rows=1205,max_csv_rows=1300)
        except CandidateInputError as e:raise ScientificFailure(f"unsafe, malformed or oversized submission: {e}")
        required=("ts.xyz","hessian.csv","ts_properties.json","hessian_eigenvalues.csv",
                  "irc_forward.xyz","irc_reverse.xyz","graph_classification.json",
                  "execution_trace.csv","model_event_log.csv","report.md")
        files={name:candidate_file(final,name) for name in required}
        if files["report.md"].stat().st_size>65536:raise ScientificFailure("report.md exceeds 64 KiB")
        # Cheap structural and budget validation comes before any model inference.
        ts_props=json.loads(files["ts_properties.json"].read_text())
        classification=json.loads(files["graph_classification.json"].read_text())
        if not isinstance(ts_props,dict) or not isinstance(classification,dict):raise ScientificFailure("candidate JSON outputs must be objects")
        if ts_props.get("energy_unit")!="eV" or ts_props.get("force_unit")!="eV/angstrom":raise ScientificFailure("TS property units must be eV and eV/angstrom")
        finite_number(ts_props.get("energy_eV"),"TS energy")
        ts_forces=np.asarray(ts_props.get("forces_eV_A"),float)
        if ts_forces.shape!=(16,3) or not np.isfinite(ts_forces).all():raise ScientificFailure("TS forces must be finite 16x3 values")
        if classification.get("method_id") not in ("pr-plus-conjugate-gradient/v1","steepest-descent/v1") or classification.get("coordinate_metric")!="unweighted_cartesian":
            raise ScientificFailure("graph classification must name a supported method_id and coordinate metric")
        if not isinstance(classification.get("algorithm"),str) or not classification["algorithm"].strip():raise ScientificFailure("graph classification must describe the path algorithm")
        if not isinstance(classification.get("identity_outcome"),str) or not isinstance(classification.get("pair_connects_R_P"),bool):
            raise ScientificFailure("graph classification is missing structured identity fields")
        for direction in ("forward","reverse"):
            claim=classification.get(direction)
            if (not isinstance(claim,dict) or type(claim.get("match_R")) is not bool or type(claim.get("match_P")) is not bool
                    or claim.get("stop_status") not in ("force_threshold","step_limit")):
                raise ScientificFailure(f"graph classification {direction} fields are malformed")
        report_text=files["report.md"].read_text()
        if classification["identity_outcome"] not in report_text or f"pair_connects_R_P: {str(classification['pair_connects_R_P']).lower()}" not in report_text:
            raise ScientificFailure("report.md must contain the candidate's structured identity fields")
        candidate_h=matrix_file(files["hessian.csv"],48,48)
        evrows=csv_rows(files["hessian_eigenvalues.csv"],["mode_index","eigenvalue_eV_A2"])
        if len(evrows)!=42:raise ScientificFailure("hessian_eigenvalues.csv must contain exactly 42 modes")
        for index,row in enumerate(evrows):
            finite_int(row["mode_index"],f"eigenvalue row {index} mode_index")
            finite_number(row["eigenvalue_eV_A2"],f"eigenvalue row {index} value")
        trace_rows=csv_rows(files["execution_trace.csv"],["scope","ef_calls","h_calls","accepted_steps","walltime_s"])
        if len(trace_rows)!=3 or len({r["scope"] for r in trace_rows})!=3 or {r["scope"] for r in trace_rows}!={"forward","reverse","total"}:
            raise ScientificFailure("execution_trace.csv must contain exactly unique forward/reverse/total rows")
        trace_by={r["scope"]:r for r in trace_rows};trace_counts={}
        for scope,row in trace_by.items():
            trace_counts[scope]={k:finite_number(row[k],f"{scope} {k}") for k in ("ef_calls","h_calls","accepted_steps","walltime_s")}
            if any(v<0 for v in trace_counts[scope].values()):raise ScientificFailure("execution trace contains a negative value")
            if any(not trace_counts[scope][k].is_integer() for k in ("ef_calls","h_calls","accepted_steps")):
                raise ScientificFailure("execution trace call/step counts must be integers")
        total=trace_counts["total"]
        if total["h_calls"]!=REFS["limits"]["hessian_calls_expected"] or total["h_calls"]>REFS["limits"]["hessian_calls_max"] or total["ef_calls"]>REFS["limits"]["energy_force_calls_max"] or total["accepted_steps"]>REFS["limits"]["accepted_steps_total_max"] or total["walltime_s"]>REFS["limits"]["walltime_seconds_max"]:
            raise ScientificFailure("execution trace exceeds the frozen H/EF/step/wall-time budget")
        for direction in ("forward","reverse"):
            if trace_counts[direction]["accepted_steps"]>REFS["limits"]["accepted_steps_per_direction_max"] or trace_by[direction].get("stop_status") not in ("force_threshold","step_limit"):
                raise ScientificFailure(f"{direction} trace exceeds its step cap or has an invalid stop status")
        frames_by_direction={}
        for direction in ("forward","reverse"):
            nframes=xyz_preflight(files[f"irc_{direction}.xyz"],None,122)
            if nframes<3:raise ScientificFailure(f"{direction} path must include the TS, seed, and at least one accepted point")
            if trace_counts[direction]["accepted_steps"]!=nframes-2:raise ScientificFailure(f"{direction} trace steps do not match bounded XYZ frame count")
            frames_by_direction[direction]=nframes
        xyz_preflight(files["ts.xyz"],None,1)
        if abs(total["ef_calls"]-trace_counts["forward"]["ef_calls"]-trace_counts["reverse"]["ef_calls"])>1e-9 or abs(total["h_calls"]-trace_counts["forward"]["h_calls"]-trace_counts["reverse"]["h_calls"])>1e-9:
            raise ScientificFailure("total call counts must equal directional sums")
        if total["ef_calls"]<sum(frames_by_direction.values())+1 or total["accepted_steps"]!=sum(trace_counts[d]["accepted_steps"] for d in ("forward","reverse")):
            raise ScientificFailure("execution trace omits saved-frame evaluations or has inconsistent step totals")
        event_rows=csv_rows(files["model_event_log.csv"],["sequence","direction","event_type","step_index","line_search_attempt","call_type","coordinates_sha256","positions_json","energy_eV","fmax_eV_A"])
        if len(event_rows)!=int(total["ef_calls"]):raise ScientificFailure("model event row count must equal bounded total E/F calls")
        if len(event_rows)>REFS["limits"]["event_rows_max"]:raise ScientificFailure("model event log exceeds 1200 evaluations")
        for sequence,row in enumerate(event_rows):
            if finite_int(row["sequence"],f"event {sequence} sequence")!=sequence:raise ScientificFailure("model event sequence must be contiguous")
            if row["direction"] not in ("forward","reverse") or row["event_type"] not in ("ts_hessian","seed","rejected_trial","accepted_trial") or row["call_type"] not in ("H","EF"):
                raise ScientificFailure(f"event {sequence} has an unsupported event/call type")
            finite_int(row["step_index"],f"event {sequence} step_index")
            finite_int(row["line_search_attempt"],f"event {sequence} line_search_attempt")
            finite_number(row["energy_eV"],f"event {sequence} energy")
            finite_number(row["fmax_eV_A"],f"event {sequence} fmax")
            try:pos=np.asarray(json.loads(row["positions_json"]),float)
            except Exception as e:raise ScientificFailure(f"event {sequence} positions_json is malformed: {e}")
            if pos.shape!=(16,3) or not np.isfinite(pos).all():raise ScientificFailure(f"event {sequence} positions must be finite 16x3")
            digest=row["coordinates_sha256"]
            if len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest.lower()) or coords_hash(pos)!=digest:
                raise ScientificFailure(f"event {sequence} coordinate hash is invalid")
        if sum(r["call_type"]=="H" for r in event_rows)!=int(total["h_calls"]) or sum(r["event_type"]=="ts_hessian" for r in event_rows)!=1:
            raise ScientificFailure("event log H count or starting Hessian event is invalid")
        if any((r["call_type"]=="H")!=(r["event_type"]=="ts_hessian") for r in event_rows):raise ScientificFailure("only the starting TS event may request H")
        for direction in ("forward","reverse"):
            drows=[r for r in event_rows if r["direction"]==direction]
            if len(drows)!=int(trace_counts[direction]["ef_calls"]) or sum(r["call_type"]=="H" for r in drows)!=int(trace_counts[direction]["h_calls"]):
                raise ScientificFailure(f"{direction} event rows do not match its trace budget")
            seeds=[i for i,r in enumerate(drows) if r["event_type"]=="seed"]
            if len(seeds)!=1:raise ScientificFailure(f"{direction} requires exactly one seed event")
            if any(r["event_type"] in ("accepted_trial","rejected_trial") for r in drows[:seeds[0]+1]):
                raise ScientificFailure(f"{direction} seed must precede optimizer trial events")
            last=-1
            step=1;attempt=0
            groups={};closed=[]
            for row in drows:
                if row["event_type"] not in ("accepted_trial","rejected_trial"):continue
                got_step=finite_int(row["step_index"],"event step_index");got_attempt=finite_int(row["line_search_attempt"],"event line_search_attempt")
                if got_step!=step or got_attempt!=attempt:raise ScientificFailure(f"{direction} event trials are not in optimizer sequence")
                groups.setdefault(step,[]).append(row)
                if row["event_type"]=="accepted_trial":closed.append(step);step+=1;attempt=0
                else:
                    if attempt>=23:raise ScientificFailure(f"{direction} backtracking attempts exceed the frozen cap")
                    attempt+=1
            if step-1!=int(trace_counts[direction]["accepted_steps"]):raise ScientificFailure(f"{direction} event accepted count differs from trace")
            if closed!=list(groups) or any(not group or group[-1]["event_type"]!="accepted_trial" or any(r["event_type"]!="rejected_trial" for r in group[:-1]) for group in groups.values()):
                raise ScientificFailure(f"{direction} event log contains an incomplete or reordered optimizer step")
        refpath=asset("case06_reference_ts.xyz");rp=asset("case06_original_zenodo_000_R.xyz");pp=asset("case06_original_zenodo_000_P.xyz")
        ck=asset("best_model_state.tar");spec=asset("newtonnet_model_spec.yml")
        try:
            protocol=json.loads(asset("path_protocol.json").read_text())
            reference=read(str(refpath));reactant=read(str(rp));product=read(str(pp))
        except Exception as e:raise InvalidEnvironment(f"pinned case protocol/assets cannot be parsed: {e}")
        if len(reference)!=16 or len(reactant)!=16 or len(product)!=16:raise InvalidEnvironment("pinned path/endpoint assets must contain 16 atoms")
        sys.path.insert(0,str(TESTS/"private"))
        try:from scoring_evaluator import NewtonNetEvaluator,projected_internal_spectrum
        except Exception as e:raise InvalidEnvironment(f"fixed scorer dependency cannot be imported: {e}")
        try:calc=NewtonNetEvaluator(ck,spec)
        except Exception as e:raise InvalidEnvironment(f"fixed NewtonNet evaluator unavailable: {e}")
        candidate_ts=read(str(files["ts.xyz"]))
        if len(candidate_ts)!=16 or candidate_ts.get_chemical_symbols()!=reference.get_chemical_symbols() or not close(candidate_ts.positions,reference.positions,1e-7):
            raise ScientificFailure("ts.xyz must reproduce the pinned case01 accepted TS coordinates and atom order")
        start=replay(calc,reference,True,"starting TS")
        if not close(candidate_h,start.hessian_eV_A2,2e-5,2e-5):raise ScientificFailure("submitted starting Hessian differs from independent fixed-model replay")
        props=ts_props
        if props.get("energy_unit")!="eV" or props.get("force_unit")!="eV/angstrom" or not close(float(props["energy_eV"]),start.energy_eV,1e-6) or not close(props["forces_eV_A"],start.forces_eV_A,1e-6,1e-6):
            raise ScientificFailure("starting TS E/F result or units do not match independent model replay")
        spectrum=projected_internal_spectrum(start.hessian_eV_A2,reference.positions);spectrum_vals=np.asarray(spectrum["internal_eigenvalues_eV_A2"])
        saddle_threshold=REFS["thresholds"]["index_one_internal_eigenvalue_eV_A2"]
        if float(protocol["initial_saddle_criterion"]["index_one_threshold_eV_A2"])!=saddle_threshold:raise InvalidEnvironment("pinned protocol differs from refs threshold")
        start_fmax=float(np.max(np.linalg.norm(start.forces_eV_A,axis=1)))
        if start_fmax>REFS["thresholds"]["force_threshold_eV_A"] or len(spectrum_vals)!=42 or np.count_nonzero(spectrum_vals < saddle_threshold)!=1:raise ScientificFailure("independently replayed TS fails the frozen force or index-one saddle criterion")
        evrows=csv_rows(files["hessian_eigenvalues.csv"],["mode_index","eigenvalue_eV_A2"])
        evrows.sort(key=lambda r:int(r["mode_index"]))
        if len(evrows)!=42 or [int(r["mode_index"]) for r in evrows]!=list(range(42)) or not close([float(r["eigenvalue_eV_A2"]) for r in evrows],spectrum_vals,2e-5,2e-5):
            raise ScientificFailure("hessian_eigenvalues.csv does not match all 42 independently replayed internal modes")
        cls=json.loads((final/"graph_classification.json").read_text())
        if not cls.get("algorithm") or not cls.get("coordinate_metric"):raise ScientificFailure("graph_classification.json must state path algorithm and coordinate metric")
        method_id=cls.get("method_id")
        if method_id not in ("pr-plus-conjugate-gradient/v1","steepest-descent/v1"):raise ScientificFailure("method_id must select a supported independently replayed path algorithm")
        expected_algorithm={"pr-plus-conjugate-gradient/v1":"backtracked-pr-plus-conjugate-gradient/v1","steepest-descent/v1":"backtracked-steepest-descent/v1"}[method_id]
        if cls.get("algorithm_id")!=expected_algorithm:raise ScientificFailure("algorithm_id does not match submitted method_id")
        if cls.get("coordinate_metric") != "unweighted_cartesian":
            raise ScientificFailure("coordinate metric label is missing or unsupported")
        rg,_=obabel_graph(reactant);pg,_=obabel_graph(product);results={};path_metrics={};paths={}
        lowest=np.asarray(spectrum["lowest_internal_mode_cartesian"]).reshape((16,3));lowest=lowest/np.max(np.linalg.norm(lowest,axis=1));seed_dots={};expected_stops={}
        for direction,sign in (("forward",1),("reverse",-1)):
            path=read_frames(files[f"irc_{direction}.xyz"])
            paths[direction]=path
            if len(path)<3 or len(path)>REFS["limits"]["trajectory_frames_per_direction_max"]:raise ScientificFailure(f"{direction} trajectory must contain TS, initial displacement and accepted path frames within 120 accepted steps")
            if any(a.get_chemical_symbols()!=reference.get_chemical_symbols() for a in path):raise ScientificFailure(f"{direction} atom ordering/elements changed")
            if not close(path[0].positions,reference.positions,1e-7):raise ScientificFailure(f"{direction} trajectory does not start at the pinned TS")
            displacement=path[1].positions-reference.positions
            # Its initial seed must be the matching sign of the projected lowest mode.
            aligned=float(np.sum(displacement*lowest));norm=float(np.linalg.norm(displacement)*np.linalg.norm(lowest))
            if norm==0 or abs(aligned/norm)<0.90:raise ScientificFailure(f"{direction} initial displacement is not along the lowest projected internal mode")
            seed_dots[direction]=aligned/norm
            if abs(np.max(np.linalg.norm(displacement,axis=1))-REFS["thresholds"]["mode_seed_max_atom_displacement_A"])>REFS["tolerances"]["initial_seed_displacement_abs_A"]:raise ScientificFailure(f"{direction} initial mode displacement must have max per-atom norm 0.035 Å")
            Es=[];Fmax=[]
            for frame in path:
                res=replay(calc,frame,False,f"{direction} saved frame");Es.append(res.energy_eV);Fmax.append(float(np.max(np.linalg.norm(res.forces_eV_A,axis=1))))
            if np.any(np.diff(Es)>REFS["tolerances"]["accepted_energy_increase_abs_eV"]):raise ScientificFailure(f"{direction} saved path contains an energy increase")
            steps=len(path)-2
            if steps>REFS["limits"]["accepted_steps_per_direction_max"]:raise ScientificFailure(f"{direction} accepted path steps exceed 120")
            if Fmax[-1] <= REFS["thresholds"]["force_threshold_eV_A"]+REFS["tolerances"]["force_stop_abs_eV_A"]:expected_stop="force_threshold"
            elif steps==int(protocol["stopping"]["max_accepted_steps_each_direction"]):expected_stop="step_limit"
            else:raise ScientificFailure(f"{direction} path stopped before force convergence or the accepted-step cap")
            expected_stops[direction]=expected_stop
            for a,b in zip(path[1:],path[2:]):
                if np.max(np.linalg.norm(b.positions-a.positions,axis=1))>.080001:raise ScientificFailure(f"{direction} accepted step exceeds max per-atom displacement")
            endpoint_xyz=final/f"irc_{direction}.xyz"
            eg,ehash=obabel_graph(path[-1])
            match_r=iso(eg,rg);match_p=iso(eg,pg)
            stated=cls.get(direction,{})
            if stated.get("match_R") is not match_r or stated.get("match_P") is not match_p or stated.get("endpoint_graph_sha256")!=ehash:
                raise ScientificFailure(f"{direction} endpoint R/P VF2 claim or graph hash differs from independent Open Babel/NetworkX replay")
            stop=stated.get("stop_status")
            if stop!=expected_stop:raise ScientificFailure(f"{direction} stop_status does not match independent force/cap replay")
            results[direction]={"match_R":match_r,"match_P":match_p,"endpoint_graph_sha256":ehash,"accepted_steps":steps,"endpoint_force_max_eV_A":Fmax[-1],"energy_start_eV":Es[0],"energy_end_eV":Es[-1]}
            path_metrics[direction]={"frames":len(path),"accepted_steps":steps,"endpoint_fmax":Fmax[-1],"energy_drop_eV":Es[0]-Es[-1]}
        if seed_dots["forward"]*seed_dots["reverse"]>=0:raise ScientificFailure("forward/reverse path seeds must use opposite signs of the lowest internal mode")
        pair=bool((results["forward"]["match_R"] and results["reverse"]["match_P"]) or (results["forward"]["match_P"] and results["reverse"]["match_R"]))
        if cls.get("pair_connects_R_P") is not pair:raise ScientificFailure("pair_connects_R_P does not match the two independently replayed endpoint identities")
        if results["forward"]["match_P"] and results["reverse"]["match_P"] and not results["forward"]["match_R"] and not results["reverse"]["match_R"]:identity="both_endpoints_match_product_no_reactant"
        elif pair:identity="connects_reactant_to_product"
        elif results["forward"]["match_R"] and results["reverse"]["match_R"]:identity="both_endpoints_match_reactant"
        elif any(v["match_R"] or v["match_P"] for v in results.values()):identity="partial_template_match"
        else:identity="neither_endpoint_matches_templates"
        if cls.get("identity_outcome")!=identity:raise ScientificFailure("identity_outcome does not match independently replayed endpoint graph identities")
        try:
            with (final/"execution_trace.csv").open(newline="",encoding="utf8") as f:
                rd=csv.DictReader(f);rows=list(rd);names=rd.fieldnames or []
        except Exception as e:raise ScientificFailure(f"cannot read execution_trace.csv: {e}")
        if not rows or not {"scope","ef_calls","h_calls","accepted_steps","walltime_s"}.issubset(names):raise ScientificFailure("execution_trace.csv missing required columns")
        if len(rows)!=3 or len({r["scope"] for r in rows})!=3 or {r["scope"] for r in rows}!={"forward","reverse","total"}:raise ScientificFailure("execution_trace.csv must contain exactly unique forward/reverse/total rows")
        by={r["scope"]:r for r in rows}
        parsed={}
        for scope,row in by.items():
            vals={k:float(row[k]) for k in ("ef_calls","h_calls","accepted_steps","walltime_s")}
            if any(not math.isfinite(v) or v<0 for v in vals.values()):raise ScientificFailure("nonfinite or negative execution trace counter")
            if any(not vals[k].is_integer() for k in ("ef_calls","h_calls","accepted_steps")):raise ScientificFailure("call and accepted-step counters must be integers")
            parsed[scope]=vals
        for direction in ("forward","reverse"):
            if by[direction].get("stop_status")!=expected_stops[direction]:raise ScientificFailure(f"execution_trace stop_status differs from independent {direction} endpoint check")
        for scope in ("forward","reverse"):
            if parsed[scope]["accepted_steps"]!=path_metrics[scope]["accepted_steps"]:raise ScientificFailure(f"reported {scope} accepted step count differs from saved accepted geometries")
            if parsed[scope]["ef_calls"]<path_metrics[scope]["frames"]:raise ScientificFailure(f"{scope} E/F trace omits evaluations needed for saved frames")
            if parsed[scope]["h_calls"]<0:raise ScientificFailure("negative H call count")
        for key in ("ef_calls","h_calls","accepted_steps"):
            if abs(parsed["total"][key]-parsed["forward"][key]-parsed["reverse"][key])>1e-9:raise ScientificFailure(f"total {key} is not the sum of directional traces")
        if parsed["total"]["h_calls"]<REFS["limits"]["hessian_calls_expected"] or parsed["total"]["h_calls"]>REFS["limits"]["hessian_calls_max"] or parsed["total"]["ef_calls"]>REFS["limits"]["energy_force_calls_max"] or parsed["total"]["accepted_steps"]>REFS["limits"]["accepted_steps_total_max"] or parsed["total"]["walltime_s"]>REFS["limits"]["walltime_seconds_max"] or parsed["forward"]["accepted_steps"]>REFS["limits"]["accepted_steps_per_direction_max"] or parsed["reverse"]["accepted_steps"]>REFS["limits"]["accepted_steps_per_direction_max"]:
            raise ScientificFailure("execution exceeds the frozen per-direction or total compute budget")
        if parsed["total"]["ef_calls"]<len(read_frames(final/"irc_forward.xyz"))+len(read_frames(final/"irc_reverse.xyz"))+1:
            raise ScientificFailure("reported E/F calls omit the start and saved path frame replays")
        event_rows=csv_rows(final/"model_event_log.csv",["sequence","direction","event_type","step_index","line_search_attempt","call_type","coordinates_sha256","positions_json","energy_eV","fmax_eV_A"])
        if len(event_rows)!=int(parsed["total"]["ef_calls"]):raise ScientificFailure("model_event_log.csv row count must equal total E/F calls, including rejected line-search evaluations and the H callback")
        if [int(r["sequence"]) for r in event_rows]!=list(range(len(event_rows))):raise ScientificFailure("model event sequence must be unique and contiguous")
        if sum(r["call_type"]=="H" for r in event_rows)!=int(parsed["total"]["h_calls"]):raise ScientificFailure("event-log Hessian calls do not match execution trace")
        start_h_rows=[r for r in event_rows if r["event_type"]=="ts_hessian"]
        if len(start_h_rows)!=1 or start_h_rows[0]["call_type"]!="H" or sum(r["event_type"]=="seed" for r in event_rows)!=2:raise ScientificFailure("event log must include exactly one TS Hessian call and one starting displacement per direction")
        if any((r["call_type"]=="H")!=(r["event_type"]=="ts_hessian") for r in event_rows):raise ScientificFailure("the sole Hessian evaluation must be the starting TS H call; path trials use E/F")
        start_h_atoms=np.asarray(json.loads(start_h_rows[0]["positions_json"]),float)
        if not close(start_h_atoms,reference.positions,REFS["tolerances"]["starting_coordinates_abs_A"]) or start_h_rows[0]["coordinates_sha256"]!=coords_hash(reference.positions):raise ScientificFailure("the unique starting Hessian event must be evaluated at the exact pinned TS")
        if any(r["call_type"] not in ("H","EF") or r["direction"] not in ("forward","reverse") or r["event_type"] not in ("ts_hessian","seed","rejected_trial","accepted_trial") for r in event_rows):raise ScientificFailure("model event log contains an unsupported event/call type")
        event_results={};events_by_dir={"forward":[],"reverse":[]}
        for row in event_rows:
            try:
                pos=np.asarray(json.loads(row["positions_json"]),float)
                if pos.shape!=(16,3) or not np.isfinite(pos).all() or coords_hash(pos)!=row["coordinates_sha256"]:raise ValueError("geometry hash/shape invalid")
                atoms=Atoms(symbols=reference.get_chemical_symbols(),positions=pos)
                result=replay(calc,atoms,row["call_type"]=="H",f"event {row['sequence']}")
                efmax=float(np.max(np.linalg.norm(result.forces_eV_A,axis=1)))
                if not close(float(row["energy_eV"]),result.energy_eV,1e-6) or not close(float(row["fmax_eV_A"]),efmax,1e-5,1e-5):raise ScientificFailure(f"event {row['sequence']} energy/force observation differs from independent evaluator replay")
                event_results[int(row["sequence"])]=(atoms,result)
                events_by_dir[row["direction"]].append(row)
            except ScientificFailure:raise
            except InvalidEnvironment:raise
            except Exception as e:raise ScientificFailure(f"malformed model event row {row.get('sequence')}: {e}")
        for direction in ("forward","reverse"):
            if len(events_by_dir[direction])!=int(parsed[direction]["ef_calls"]):raise ScientificFailure(f"{direction} event count differs from execution trace")
            if sum(r["call_type"]=="H" for r in events_by_dir[direction])!=int(parsed[direction]["h_calls"]):raise ScientificFailure(f"{direction} Hessian event count differs from its trace row")
            drows=events_by_dir[direction]
            seeds=[r for r in drows if r["event_type"]=="seed"]
            if len(seeds)!=1 or not close(json.loads(seeds[0]["positions_json"]),paths[direction][1].positions,1e-7):raise ScientificFailure(f"{direction} seed event does not match saved initial displacement")
            trials=[r for r in drows if r["event_type"] in ("accepted_trial","rejected_trial")]
            if trials and int(seeds[0]["sequence"])>=int(trials[0]["sequence"]):raise ScientificFailure(f"{direction} seed event must precede all optimizer trial evaluations")
            accepted=[r for r in drows if r["event_type"]=="accepted_trial"]
            if len(accepted)!=path_metrics[direction]["accepted_steps"]:raise ScientificFailure(f"{direction} accepted event count differs from saved geometries")
            if [int(r["step_index"]) for r in accepted]!=list(range(1,len(accepted)+1)):raise ScientificFailure(f"{direction} accepted trial sequence must be in ascending optimizer-step order")
            for row,frame in zip(accepted,paths[direction][2:]):
                if not close(json.loads(row["positions_json"]),frame.positions,1e-7):raise ScientificFailure(f"{direction} accepted model events do not reproduce saved path frames")
            groups={};current_step=1;next_attempt=0;closed_steps=[]
            for row in drows:
                if row["event_type"] not in ("accepted_trial","rejected_trial"):continue
                step=int(row["step_index"]);attempt=int(row["line_search_attempt"])
                if step!=current_step or attempt!=next_attempt:raise ScientificFailure(f"{direction} event sequence is noncontiguous or out of order at step {step}, attempt {attempt}")
                groups.setdefault(step,[]).append(row)
                if row["event_type"]=="accepted_trial":
                    closed_steps.append(step);current_step+=1;next_attempt=0
                else:next_attempt+=1
            if list(groups)!=list(range(1,path_metrics[direction]["accepted_steps"]+1)) or closed_steps!=list(groups.keys()):raise ScientificFailure(f"{direction} event log misses or reorders optimizer steps")
            prev_force=None;prev_direction=None
            for step,group in groups.items():
                if len(group)>24 or group[-1]["event_type"]!="accepted_trial" or any(r["event_type"]!="rejected_trial" for r in group[:-1]):raise ScientificFailure(f"{direction} step {step} has invalid backtracking event sequence")
                state_row=seeds[0] if step==1 else groups[step-1][-1]
                old_atoms,old_result=event_results[int(state_row["sequence"])]
                forces=old_result.forces_eV_A
                deltas=[];energies=[];event_types=[]
                for row in group:
                    proposed,event_result=event_results[int(row["sequence"])]
                    deltas.append(proposed.positions-old_atoms.positions);energies.append(event_result.energy_eV);event_types.append(row["event_type"])
                _,prev_force,prev_direction=replay_path_step(forces,prev_force,prev_direction,old_result.energy_eV,deltas,energies,event_types,method_id)
        report=final/"report.md"
        if not report.is_file() or not report.read_text().strip():raise ScientificFailure("report.md missing or empty")
        report_text=report.read_text()
        if identity not in report_text or f"pair_connects_R_P: {str(pair).lower()}" not in report_text or method_id not in report_text:raise ScientificFailure("report.md must state the selected method_id and exact structured endpoint result")
        return emit("PASS","independent model path replay and endpoint graph-identity audit passed",reward=1,details={"method_id":method_id,"start_energy_eV":start.energy_eV,"negative_internal_modes":int(np.count_nonzero(spectrum_vals < saddle_threshold)),"directions":path_metrics,"endpoint_identities":results,"identity_outcome":identity,"pair_connects_R_P":pair,"reported_total_calls":parsed["total"]})
    except InvalidEnvironment as e:return emit("ENV_INVALID",e,2)
    except ScientificFailure as e:return emit("FAIL",e,1,reward=0)
    except Exception as e:
        if os.environ.get("DEBUG_VERIFIER"):import traceback;traceback.print_exc()
        return emit("FAIL",f"malformed path bundle: {type(e).__name__}: {e}",1,reward=0)

# Frozen independent evaluator source (UTF-8 bytes are hash-bound at load time).
SCORING_EVALUATOR_SHA256 = 'b40ba9954b54b4a1bba88f20c976da63fda1f5c7683656f42019d804e100f57f'
SCORING_EVALUATOR_SOURCE = """\"\"\"Independent NewtonNet v1 checkpoint loading and Cartesian derivative audit.

This module is shared by the local case graders. It loads only the published
NewtonNet checkpoint and model specification; no submitter-controlled model or
"independent" marker is accepted.
\"\"\"
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
import tempfile


class EvaluatorUnavailable(RuntimeError):
    \"\"\"The evaluator backend or evaluation assets are unavailable.\"\"\"


@dataclass
class ModelResult:
    energy_eV: float
    forces_eV_A: np.ndarray
    hessian_eV_A2: np.ndarray | None


class NewtonNetEvaluator:
    \"\"\"CPU double-precision evaluator built from NewtonNet's public v1 API.\"\"\"

    def __init__(self, checkpoint: str | Path, model_spec: str | Path, device: str = "cpu"):
        try:
            import torch
            from newtonnet.utils.ase_interface import MLAseCalculator
        except Exception as exc:  # pragma: no cover - depends on installed runtime
            raise EvaluatorUnavailable(f"NewtonNet/PyTorch backend import failed: {exc}") from exc

        self.torch = torch
        self.device = device
        self.checkpoint = Path(checkpoint)
        self.model_spec = Path(model_spec)
        if not self.checkpoint.is_file() or not self.model_spec.is_file():
            raise EvaluatorUnavailable("checkpoint or model specification is missing")

        settings = yaml.safe_load(self.model_spec.read_text(encoding="utf-8"))
        model = settings.get("model", {})
        cutoff = settings.get("data", {}).get("cutoff")
        required = {
            "activation", "resolution", "n_features", "n_interactions",
            "cutoff_network", "normalize_atomic", "requires_dr",
            "shared_interactions", "double_update_latent", "layer_norm",
        }
        missing = sorted(required - model.keys())
        if missing or cutoff is None:
            raise EvaluatorUnavailable(f"model specification lacks fields: {missing or ['data.cutoff']}")

        # NewtonNet v1.0.1's constructor receives architecture from config.yml;
        # the learned per-element inverse normalization values live in the
        # checkpoint's inverse_normalize.* state_dict entries.
        settings["training"] = {"dropout": 0.0}
        settings.setdefault("data", {})["cutoff"] = float(cutoff)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", encoding="utf-8") as config:
            yaml.safe_dump(settings, config)
            config.flush()
            self.calc = MLAseCalculator(
                model_path=str(self.checkpoint), settings_path=config.name,
                hess_method="autograd", dtype="double", disagreement=None, device=device,
            )
            self.force_calc = MLAseCalculator(
                model_path=str(self.checkpoint), settings_path=config.name,
                hess_method=None, dtype="double", disagreement=None, device=device,
            )
        self.model = self.calc.models[0]
        self.torch.set_num_threads(1)

    def evaluate(self, atoms, *, hessian: bool = True) -> ModelResult:
        \"\"\"Return E [eV], F [eV/Å], and optional Cartesian H [eV/Å²].\"\"\"
        from ase.calculators.calculator import PropertyNotImplementedError

        probe = atoms.copy()
        calc = self.calc if hessian else self.force_calc
        calc.reset()  # Make each score/probe call an actual model replay, even for repeated geometries.
        probe.calc = calc
        try:
            energy = float(probe.get_potential_energy())
            forces = np.asarray(probe.get_forces(), dtype=float)
            if hessian:
                h = np.asarray(calc.get_property("hessian", atoms=probe), dtype=float)
                n = len(probe)
                if h.size != (3 * n) ** 2:
                    raise EvaluatorUnavailable(f"unexpected NewtonNet Hessian size: {h.shape}")
                h = h.reshape(3 * n, 3 * n)
            else:
                h = None
        except (PropertyNotImplementedError, RuntimeError, ValueError) as exc:
            raise EvaluatorUnavailable(f"NewtonNet evaluation failed: {exc}") from exc
        if forces.shape != (len(probe), 3) or not np.isfinite(energy) or not np.isfinite(forces).all():
            raise EvaluatorUnavailable("NewtonNet returned malformed or non-finite energy/forces")
        if h is not None and not np.isfinite(h).all():
            raise EvaluatorUnavailable("NewtonNet returned a non-finite Hessian")
        return ModelResult(energy, forces, h)


def rigid_body_basis(positions: np.ndarray, *, linear_tol: float = 1e-8) -> tuple[np.ndarray, bool]:
    \"\"\"Orthonormal rigid translation/rotation basis and linearity flag.\"\"\"
    x = np.asarray(positions, dtype=float)
    centered = x - x.mean(axis=0)
    vectors = []
    for axis in np.eye(3):
        vectors.append(np.broadcast_to(axis, centered.shape).copy().ravel())
    for axis in np.eye(3):
        vectors.append(np.cross(np.broadcast_to(axis, centered.shape), centered).ravel())
    rigid_stack = np.stack(vectors, axis=1)
    # SVD is required here: ordinary QR can invent a basis vector when a zero
    # rotation column occurs before the two physical rotations (e.g. a molecule
    # aligned with x has a zero x-axis rotation).
    u, singular, _ = np.linalg.svd(rigid_stack, full_matrices=False)
    threshold = linear_tol * max(float(singular[0]), 1.0)
    rank = int(np.count_nonzero(singular > threshold))
    if rank not in (5, 6):
        raise ValueError(f"expected 5 or 6 rigid-body modes, got {rank}")
    linear = rank == 5
    basis = u[:, :rank]
    return basis, linear


def projected_internal_spectrum(hessian_eV_A2: np.ndarray, positions: np.ndarray) -> dict[str, Any]:
    \"\"\"Project Cartesian H away from rigid modes and return internal spectrum.\"\"\"
    h = np.asarray(hessian_eV_A2, dtype=float)
    h = 0.5 * (h + h.T)
    rigid, linear = rigid_body_basis(positions)
    # Complete an orthogonal basis and retain its internal columns.
    q, _ = np.linalg.qr(rigid, mode="complete")
    internal = q[:, rigid.shape[1]:]
    eig, vec = np.linalg.eigh(internal.T @ h @ internal)
    return {
        "linear": linear,
        "rigid_modes": int(rigid.shape[1]),
        "internal_eigenvalues_eV_A2": eig,
        "lowest_internal_mode_cartesian": internal @ vec[:, 0],
    }


def finite_difference_hessian(evaluator: NewtonNetEvaluator, atoms, step_A: float = 1e-4) -> np.ndarray:
    \"\"\"Central-difference each Cartesian force component to validate autograd H.\"\"\"
    x0 = atoms.get_positions()
    ncart = x0.size
    h = np.empty((ncart, ncart), dtype=float)
    for j in range(ncart):
        xp, xm = x0.copy(), x0.copy()
        xp.flat[j] += step_A
        xm.flat[j] -= step_A
        ap, am = atoms.copy(), atoms.copy()
        ap.positions = xp
        am.positions = xm
        fp = evaluator.evaluate(ap, hessian=False).forces_eV_A.ravel()
        fm = evaluator.evaluate(am, hessian=False).forces_eV_A.ravel()
        h[:, j] = -(fp - fm) / (2.0 * step_A)
    return h
"""
def load_scoring_evaluator():
    import types
    raw = SCORING_EVALUATOR_SOURCE.encode("utf-8")
    if hashlib.sha256(raw).hexdigest() != SCORING_EVALUATOR_SHA256:
        raise InvalidEnvironment("embedded fixed evaluator source hash mismatch")
    module = types.ModuleType("scoring_evaluator")
    module.__file__ = "<embedded:scoring_evaluator.py>"
    sys.modules[module.__name__] = module
    exec(compile(raw, module.__file__, "exec"), module.__dict__)
    return module

ADAPTER_SOURCE_TEXT = (
    '"""Bounded, fail-closed adapter for case scientific verifier scripts."""\n'
    'from __future__ import annotations\n'
    '\n'
    'import json\n'
    'import hashlib\n'
    'import math\n'
    'import os\n'
    'import signal\n'
    'import selectors\n'
    'import stat\n'
    'import subprocess\n'
    'import sys\n'
    'import time\n'
    'from pathlib import Path\n'
    '\n'
    'from submission_guard import CandidateInputError, guard_submission\n'
    '\n'
    '\n'
    'OUTPUT_CAP = 2 * 1024 * 1024\n'
    'DEFAULT_TIMEOUT = 1100\n'
    '\n'
    '\n'
    'def _json_bytes(value):\n'
    '    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\\n").encode("utf-8")\n'
    '\n'
    '\n'
    'def _write(path, payload):\n'
    '    path.parent.mkdir(parents=True, exist_ok=True)\n'
    '    path.write_bytes(payload)\n'
    '\n'
    '\n'
    'def _prepare_logs(path):\n'
    '    if path.exists() or path.is_symlink():\n'
    '        mode = path.lstat().st_mode\n'
    '        if path.is_symlink() or not path.is_dir():\n'
    '            raise OSError("LOGS root must be a real directory: %s" % path)\n'
    '    else:\n'
    '        path.mkdir(parents=True, exist_ok=True)\n'
    '    for name in ("verification.json", "reward.txt", "verification.stdout", "verification.stderr"):\n'
    '        target = path / name\n'
    '        try:\n'
    '            target.unlink()\n'
    '        except FileNotFoundError:\n'
    '            pass\n'
    '        except IsADirectoryError as exc:\n'
    '            raise OSError("LOGS output path is a directory: %s" % target) from exc\n'
    '\n'
    '\n'
    'def _process_descendants(root_pid):\n'
    '    """Return bounded Linux descendants before the parent is killed/reparented."""\n'
    '    proc_root = Path("/proc")\n'
    '    if not proc_root.is_dir():\n'
    '        return []\n'
    '    parents = {}\n'
    '    try:\n'
    '        with os.scandir(proc_root) as entries:\n'
    '            for entry in entries:\n'
    '                if not entry.name.isdigit():\n'
    '                    continue\n'
    '                try:\n'
    '                    with open(proc_root / entry.name / "stat", "r", encoding="ascii") as stream:\n'
    '                        stat_line = stream.read(4096)\n'
    '                    close = stat_line.rfind(")")\n'
    '                    fields = stat_line[close + 2:].split()\n'
    '                    if close >= 0 and len(fields) > 1:\n'
    '                        parents[int(entry.name)] = int(fields[1])\n'
    '                except (OSError, ValueError, IndexError):\n'
    '                    continue\n'
    '                if len(parents) >= 32768:\n'
    '                    break\n'
    '    except OSError:\n'
    '        return []\n'
    '    found = set()\n'
    '    frontier = {root_pid}\n'
    '    while frontier:\n'
    '        children = {pid for pid, parent in parents.items() if parent in frontier and pid not in found}\n'
    '        if not children:\n'
    '            break\n'
    '        found.update(children)\n'
    '        frontier = children\n'
    '    return sorted(found, reverse=True)\n'
    '\n'
    '\n'
    'def _kill_group(proc, known_descendants=()):\n'
    '    # Also kill descendants which deliberately escaped the verifier process\n'
    '    # group with setsid(); collect the tree before reparenting changes it.\n'
    '    for pid in set(_process_descendants(proc.pid)) | set(known_descendants):\n'
    '        try:\n'
    '            os.kill(pid, signal.SIGKILL)\n'
    '        except (ProcessLookupError, PermissionError, OSError):\n'
    '            pass\n'
    '    try:\n'
    '        os.killpg(proc.pid, signal.SIGKILL)\n'
    '    except (ProcessLookupError, PermissionError, OSError):\n'
    '        try:\n'
    '            proc.kill()\n'
    '        except OSError:\n'
    '            pass\n'
    '\n'
    '\n'
    'def _strict_object(pairs):\n'
    '    result = {}\n'
    '    for key, value in pairs:\n'
    '        if key in result:\n'
    '            raise ValueError("duplicate JSON key: %s" % key)\n'
    '        result[key] = value\n'
    '    return result\n'
    '\n'
    '\n'
    'def _finite_float(token):\n'
    '    value = float(token)\n'
    '    if not math.isfinite(value):\n'
    '        raise ValueError("non-finite JSON number")\n'
    '    return value\n'
    '\n'
    '\n'
    'def _preflight_file(base, relative, expected_sha, label, max_bytes=64 * 1024 * 1024,\n'
    '                    parse_json=False, parse_jsonl=False):\n'
    '    rel = Path(relative)\n'
    '    if rel.is_absolute() or not rel.parts or any(part in ("", ".", "..") for part in rel.parts):\n'
    '        raise OSError("invalid %s path" % label)\n'
    '    current = base\n'
    '    for part in rel.parts:\n'
    '        current = current / part\n'
    '        info = current.lstat()\n'
    '        if stat.S_ISLNK(info.st_mode):\n'
    '            raise OSError("symlink in %s path" % label)\n'
    '    if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:\n'
    '        raise OSError("missing, non-regular, or oversized %s file" % label)\n'
    '    fd = os.open(str(current), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))\n'
    '    try:\n'
    '        opened = os.fstat(fd)\n'
    '        if (not stat.S_ISREG(opened.st_mode) or opened.st_dev != info.st_dev\n'
    '                or opened.st_ino != info.st_ino or opened.st_size != info.st_size):\n'
    '            raise OSError("%s changed while opening" % label)\n'
    '        digest = hashlib.sha256()\n'
    '        total = 0\n'
    '        chunks = [] if parse_json or parse_jsonl else None\n'
    '        while True:\n'
    '            data = os.read(fd, 1024 * 1024)\n'
    '            if not data:\n'
    '                break\n'
    '            total += len(data)\n'
    '            if total > max_bytes:\n'
    '                raise OSError("%s exceeds size limit" % label)\n'
    '            digest.update(data)\n'
    '            if chunks is not None:\n'
    '                chunks.append(data)\n'
    '        after = os.fstat(fd)\n'
    '        if total != opened.st_size or after.st_mtime_ns != opened.st_mtime_ns:\n'
    '            raise OSError("%s changed while reading" % label)\n'
    '        if digest.hexdigest() != expected_sha:\n'
    '            raise OSError("%s SHA-256 mismatch" % label)\n'
    '        if chunks is not None:\n'
    '            payload = b"".join(chunks).decode("utf-8")\n'
    '            parse_args = {"object_pairs_hook": _strict_object, "parse_float": _finite_float,\n'
    '                          "parse_constant": lambda value: (_ for _ in ()).throw(ValueError("invalid JSON constant"))}\n'
    '            if parse_json:\n'
    '                json.loads(payload, **parse_args)\n'
    '            else:\n'
    '                for number, line in enumerate(payload.splitlines(), 1):\n'
    '                    if line.strip():\n'
    '                        try:\n'
    '                            json.loads(line, **parse_args)\n'
    '                        except Exception as exc:\n'
    '                            raise ValueError("malformed JSONL row %d: %s" % (number, exc)) from exc\n'
    '    finally:\n'
    '        os.close(fd)\n'
    '\n'
    '\n'
    'def _preflight_environment(tests, app):\n'
    '    config_path = tests / "environment_preflight.json"\n'
    '    config_stat = config_path.lstat()\n'
    '    if stat.S_ISLNK(config_stat.st_mode) or not stat.S_ISREG(config_stat.st_mode) or config_stat.st_size > 1024 * 1024:\n'
    '        raise OSError("environment preflight manifest is unavailable")\n'
    '    config = json.loads(config_path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object,\n'
    '                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("invalid JSON constant")))\n'
    '    if not isinstance(config, dict) or config.get("schema") != "ccb-environment-preflight/v1":\n'
    '        raise OSError("unsupported environment preflight schema")\n'
    '    if not isinstance(config.get("public_assets"), list) or not isinstance(config.get("trusted_files"), list):\n'
    '        raise OSError("invalid environment preflight file lists")\n'
    '    for item in config["public_assets"]:\n'
    '        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:\n'
    '            raise OSError("invalid public asset preflight entry")\n'
    '        target = Path(item["path"])\n'
    '        if target.is_absolute() or any(part in ("", ".", "..") for part in target.parts):\n'
    '            raise OSError("invalid public asset target")\n'
    '        _preflight_file(app / "assets", target, item["sha256"], "public asset",\n'
    '                        parse_json=target.suffix.lower() == ".json",\n'
    '                        parse_jsonl=target.suffix.lower() == ".jsonl")\n'
    '    for item in config["trusted_files"]:\n'
    '        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:\n'
    '            raise OSError("invalid trusted file preflight entry")\n'
    '        _preflight_file(tests, item["path"], item["sha256"], "trusted grader file")\n'
    '\n'
    '\n'
    'def _run_verifier(script, final, timeout):\n'
    '    proc = subprocess.Popen([sys.executable, str(script), str(final)],\n'
    '                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,\n'
    '                            start_new_session=True, close_fds=True)\n'
    '    outputs = {proc.stdout: bytearray(), proc.stderr: bytearray()}\n'
    '    totals = {proc.stdout: 0, proc.stderr: 0}\n'
    '    selector = selectors.DefaultSelector()\n'
    '    for stream in outputs:\n'
    '        os.set_blocking(stream.fileno(), False)\n'
    '        selector.register(stream, selectors.EVENT_READ)\n'
    '    timed_out = False\n'
    '    overflow = False\n'
    '    killed = False\n'
    '    deadline = time.monotonic() + timeout\n'
    '    cleanup_deadline = None\n'
    '    observed_descendants = set()\n'
    '    try:\n'
    '        while selector.get_map():\n'
    '            now = time.monotonic()\n'
    '            if proc.poll() is None:\n'
    '                observed_descendants.update(_process_descendants(proc.pid))\n'
    '            if not killed and now >= deadline:\n'
    '                timed_out = True\n'
    '                killed = True\n'
    '                _kill_group(proc, observed_descendants)\n'
    '                cleanup_deadline = now + 1.0\n'
    '                try:\n'
    '                    proc.wait(timeout=0.5)\n'
    '                except subprocess.TimeoutExpired:\n'
    '                    try:\n'
    '                        proc.kill()\n'
    '                    except OSError:\n'
    '                        pass\n'
    '                    try:\n'
    '                        proc.wait(timeout=0.5)\n'
    '                    except subprocess.TimeoutExpired:\n'
    '                        pass\n'
    '            events = selector.select(0.05 if killed else min(0.1, max(0, deadline - now)))\n'
    '            for key, _ in events:\n'
    '                stream = key.fileobj\n'
    '                try:\n'
    '                    block = os.read(stream.fileno(), 65536)\n'
    '                except BlockingIOError:\n'
    '                    continue\n'
    '                except OSError:\n'
    '                    block = b""\n'
    '                if not block:\n'
    '                    try:\n'
    '                        selector.unregister(stream)\n'
    '                    except Exception:\n'
    '                        pass\n'
    '                    continue\n'
    '                totals[stream] += len(block)\n'
    '                room = max(0, OUTPUT_CAP - len(outputs[stream]))\n'
    '                if room:\n'
    '                    outputs[stream].extend(block[:room])\n'
    '                if totals[stream] > OUTPUT_CAP and not killed:\n'
    '                    overflow = True\n'
    '                    killed = True\n'
    '                    _kill_group(proc, observed_descendants)\n'
    '                    cleanup_deadline = time.monotonic() + 1.0\n'
    '                    try:\n'
    '                        proc.wait(timeout=0.5)\n'
    '                    except subprocess.TimeoutExpired:\n'
    '                        try:\n'
    '                            proc.kill()\n'
    '                        except OSError:\n'
    '                            pass\n'
    '                        try:\n'
    '                            proc.wait(timeout=0.5)\n'
    '                        except subprocess.TimeoutExpired:\n'
    '                            pass\n'
    '            if proc.poll() is not None and cleanup_deadline is None:\n'
    '                # A verifier that exits while a detached child retains either\n'
    '                # pipe is an invalid grader protocol, not a reason to wait for\n'
    '                # the outer container watchdog.\n'
    '                cleanup_deadline = time.monotonic() + 0.75\n'
    '            if cleanup_deadline is not None and time.monotonic() >= cleanup_deadline:\n'
    '                if selector.get_map():\n'
    '                    overflow = True\n'
    '                    _kill_group(proc, observed_descendants)\n'
    '                    for key in list(selector.get_map().values()):\n'
    '                        try:\n'
    '                            selector.unregister(key.fileobj)\n'
    '                        except Exception:\n'
    '                            pass\n'
    '                break\n'
    '        if proc.poll() is None:\n'
    '            _kill_group(proc, observed_descendants)\n'
    '            try:\n'
    '                proc.wait(timeout=0.5)\n'
    '            except subprocess.TimeoutExpired:\n'
    '                try:\n'
    '                    proc.kill()\n'
    '                except OSError:\n'
    '                    pass\n'
    '                try:\n'
    '                    proc.wait(timeout=0.5)\n'
    '                except subprocess.TimeoutExpired:\n'
    '                    pass\n'
    '    finally:\n'
    '        selector.close()\n'
    '        for stream in outputs:\n'
    '            try:\n'
    '                stream.close()\n'
    '            except OSError:\n'
    '                pass\n'
    '    return bytes(outputs[proc.stdout]), bytes(outputs[proc.stderr]), proc.returncode, timed_out, overflow\n'
    '\n'
    '\n'
    'def _parse_report(data):\n'
    '    lines = [line for line in data.decode("utf-8", "replace").splitlines() if line.strip()]\n'
    '    if not lines:\n'
    '        raise ValueError("verifier produced no JSON report")\n'
    '\n'
    '    def reject_constant(token):\n'
    '        raise ValueError("non-finite JSON number: " + token)\n'
    '\n'
    '    report = json.loads(lines[-1], object_pairs_hook=_strict_object,\n'
    '                        parse_constant=reject_constant, parse_float=_finite_float)\n'
    '    if not isinstance(report, dict):\n'
    '        raise ValueError("verifier report must be a JSON object")\n'
    '    return report\n'
    '\n'
    '\n'
    'def _normalize(report, rc):\n'
    '    status = report.get("status")\n'
    '    embedded_reward = report.get("reward")\n'
    '    if isinstance(embedded_reward, bool) or (embedded_reward is not None and not isinstance(embedded_reward, (int, float))):\n'
    '        raise ValueError("verifier reward must be a numeric scalar")\n'
    '    if status == "PASS":\n'
    '        if rc != 0 or embedded_reward not in (None, 1, 1.0):\n'
    '            raise ValueError("PASS status, verifier exit, and reward disagree")\n'
    '        report["reward"] = 1\n'
    '        return report, 0, "1\\n"\n'
    '    if status == "FAIL":\n'
    '        if rc != 1 or embedded_reward not in (None, 0, 0.0):\n'
    '            raise ValueError("FAIL status, verifier exit, and reward disagree")\n'
    '        report["reward"] = 0\n'
    '        return report, 1, "0\\n"\n'
    '    if status == "ENV_INVALID":\n'
    '        if rc != 2 or embedded_reward is not None:\n'
    '            raise ValueError("ENV_INVALID status and verifier exit disagree")\n'
    '        return report, 2, None\n'
    '    if status == "REVIEW_REQUIRED":\n'
    '        if rc != 0 or embedded_reward is not None:\n'
    '            raise ValueError("REVIEW_REQUIRED must have no reward and a handled verifier exit")\n'
    '        return report, 0, None\n'
    '    raise ValueError("verifier status is missing or unsupported")\n'
    '\n'
    '\n'
    'def main(argv=None):\n'
    '    argv = list(sys.argv[1:] if argv is None else argv)\n'
    '    app = Path(os.environ.get("APP", "/app"))\n'
    '    tests = Path(os.environ.get("TESTS", "/tests"))\n'
    '    logs = Path(os.environ.get("LOGS", "/logs/verifier"))\n'
    '    final = Path(argv[0]) if argv else app / "final"\n'
    '    script = Path(argv[1]) if len(argv) > 1 else tests / "verify.py"\n'
    '    try:\n'
    '        _prepare_logs(logs)\n'
    '    except OSError as exc:\n'
    '        print(json.dumps({"status": "ENV_INVALID", "reason": "cannot prepare verifier logs: %s" % exc}))\n'
    '        return 2\n'
    '\n'
    '    report = None\n'
    '    result_code = 2\n'
    '    reward_text = None\n'
    '    out = b""\n'
    '    err = b""\n'
    '    try:\n'
    '        try:\n'
    '            script_mode = script.lstat().st_mode\n'
    '            if script.is_symlink() or not script.is_file():\n'
    '                raise OSError("trusted verifier script is not a regular file")\n'
    '        except OSError as exc:\n'
    '            report = {"status": "ENV_INVALID", "reason": "trusted verifier script is unavailable: %s" % exc}\n'
    '            result_code, reward_text = 2, None\n'
    '        else:\n'
    '            try:\n'
    '                timeout = float(os.environ.get("CCB_VERIFIER_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT)))\n'
    '                if not math.isfinite(timeout) or timeout <= 0 or timeout > 24 * 3600:\n'
    '                    raise ValueError("verifier timeout is outside the allowed range")\n'
    '                _preflight_environment(tests, app)\n'
    '            except Exception as exc:\n'
    '                report = {"status": "ENV_INVALID", "reason": "environment preflight failed: %s" % exc}\n'
    '                result_code, reward_text = 2, None\n'
    '            else:\n'
    '                try:\n'
    '                    case_id = os.environ.get("CCB_CASE_ID")\n'
    '                    guard_submission(final, case_id=case_id)\n'
    '                except CandidateInputError as exc:\n'
    '                    report = {"status": "FAIL", "reason": "unsafe or over-budget candidate submission: %s" % exc,\n'
    '                              "reward": 0}\n'
    '                    result_code, reward_text = 1, "0\\n"\n'
    '                except Exception as exc:\n'
    '                    report = {"status": "ENV_INVALID", "reason": "submission guard failed: %s" % exc}\n'
    '                    result_code, reward_text = 2, None\n'
    '                else:\n'
    '                    try:\n'
    '                        out, err, rc, timed_out, overflow = _run_verifier(script, final, timeout)\n'
    '                        if timed_out:\n'
    '                            raise RuntimeError("trusted verifier exceeded %.1f-second limit" % timeout)\n'
    '                        if overflow:\n'
    '                            raise RuntimeError("trusted verifier exceeded bounded stdout/stderr capture")\n'
    '                        raw = _parse_report(out)\n'
    '                        report, result_code, reward_text = _normalize(raw, rc)\n'
    '                    except Exception as exc:\n'
    '                        report = {"status": "ENV_INVALID", "reason": "verifier execution/protocol error: %s" % exc}\n'
    '                        result_code, reward_text = 2, None\n'
    '    except Exception as exc:\n'
    '        # A grader infrastructure fault never becomes a candidate scientific FAIL.\n'
    '        report = {"status": "ENV_INVALID", "reason": "adapter failure: %s" % exc}\n'
    '        result_code, reward_text = 2, None\n'
    '    try:\n'
    '        _write(logs / "verification.stdout", out[:OUTPUT_CAP])\n'
    '        _write(logs / "verification.stderr", err[:OUTPUT_CAP])\n'
    '        _write(logs / "verification.json", _json_bytes(report))\n'
    '        if reward_text is not None:\n'
    '            _write(logs / "reward.txt", reward_text.encode("ascii"))\n'
    '    except Exception as exc:\n'
    '        report = {"status": "ENV_INVALID", "reason": "cannot persist verifier result: %s" % exc}\n'
    '        result_code, reward_text = 2, None\n'
    '        try:\n'
    '            print(json.dumps(report, ensure_ascii=False, allow_nan=False))\n'
    '        except Exception:\n'
    '            print(\'{"status":"ENV_INVALID","reason":"cannot persist verifier result"}\')\n'
    '        return result_code\n'
    '    print(json.dumps(report, ensure_ascii=False, allow_nan=False))\n'
    '    return result_code\n'
    '\n'
    '\n'
    'if __name__ == "__main__":\n'
    '    raise SystemExit(main())\n'
)
ADAPTER_SOURCE_SHA256 = '10bddc3b564e927765831ab86ee57094c05a34d92f67ec30d374c046c59e05bc'
ACTIVE_ADAPTER_SHA256 = 'f63912b3ead2b3b2ba4117a6e8bb0aaeb184e2cc67e3451daf019c52cb10fef0'
CHILD_ARGV_OLD = '[sys.executable, str(script), str(final)]'
CHILD_ARGV_NEW = '[sys.executable, str(script), "--scientific-child", str(final)]'
TEST_SH_SHA256 = '2b9d91bb7790917d2989d6ea713540996f3a4fb04fbd040430c644c9f5986db4'
PREFLIGHT_JSON = '{\n  "case_id": "case-06-path-identity",\n  "public_assets": [\n    {\n      "path": "best_model_state.tar",\n      "sha256": "a8efa83fa760076377d1be644309eaf22935f620b2c8d46cd837989dc49728d3"\n    },\n    {\n      "path": "case06_original_zenodo_000_P.xyz",\n      "sha256": "611e03e2875519d65e1c5cb6aecb4e6dde9ae534be059867c3f71fa9882723fd"\n    },\n    {\n      "path": "case06_original_zenodo_000_R.xyz",\n      "sha256": "5836d06545213c34025ede4e5626b8592de4cb2829b2a775dc3b3e0f5e6d5292"\n    },\n    {\n      "path": "case06_reference_ts.xyz",\n      "sha256": "c6d1f0f2faa9e4dd0dfa40ccf96cfb4d2b4c6e99f7bfd907c0d13058650bbcb2"\n    },\n    {\n      "path": "newtonnet_model_spec.yml",\n      "sha256": "eef241bd191da59fae309fd995f61a567f89d403c1d784c9280e72b38c862ddf"\n    },\n    {\n      "path": "output-contract.json",\n      "sha256": "3e0afef72aaa43907765ac309989a254e13019ddfaea19f45337cc7ed0ce254a"\n    },\n    {\n      "path": "path_protocol.json",\n      "sha256": "b6a922f12ac849f4ae5228839354408e7312838eecf350ed432a60f1cbacee57"\n    }\n  ],\n  "schema": "ccb-environment-preflight/v1",\n  "trusted_files": [\n    {\n      "path": "private/scoring_evaluator.py",\n      "sha256": "b40ba9954b54b4a1bba88f20c976da63fda1f5c7683656f42019d804e100f57f"\n    },\n    {\n      "path": "submission_guard.py",\n      "sha256": "37fdf998a836dcfc208276b0a9e36590b19126f6d9d0ce24be7fcda281fce93f"\n    },\n    {\n      "path": "test.sh",\n      "sha256": "2b9d91bb7790917d2989d6ea713540996f3a4fb04fbd040430c644c9f5986db4"\n    },\n    {\n      "path": "verifier_adapter.py",\n      "sha256": "10bddc3b564e927765831ab86ee57094c05a34d92f67ec30d374c046c59e05bc"\n    },\n    {\n      "path": "verify.py",\n      "sha256": "56c3577c77579961614eb4ae39cf1fdfa194fe34bb4dbabcba9d669aaad2ff6b"\n    }\n  ]\n}'
PREFLIGHT_SHA256 = '3d9ba6474f889dde9f9a9575f9447788d12d7aefb2f5f06a1aa3bfa5a163d859'
GUARD_SOURCE_SHA256 = '7c36065d4fa78e29c0a669200c78f0bed29aa944a71f0a7fe5820b27558d8515'

def _embedded_preflight(tests, app):
    if hashlib.sha256(SCORING_EVALUATOR_SOURCE.encode("utf-8")).hexdigest()!=SCORING_EVALUATOR_SHA256:
        raise OSError("embedded fixed evaluator source hash mismatch")
    own=Path(__file__).read_text(encoding="utf-8")
    first=own.index("\"\"\"Standard-library safeguards")
    last=own.index("\n_DEPENDENCY_ERROR",first)
    if hashlib.sha256(own[first:last].strip().encode("utf-8")).hexdigest()!=GUARD_SOURCE_SHA256:
        raise OSError("active submission guard source hash mismatch")
    if hashlib.sha256(PREFLIGHT_JSON.encode("utf-8")).hexdigest()!=PREFLIGHT_SHA256:
        raise OSError("embedded environment preflight hash mismatch")
    config=json.loads(PREFLIGHT_JSON)
    for item in config["public_assets"]:
        target=Path(item["path"])
        if target.is_absolute() or any(part in ("", ".", "..") for part in target.parts): raise OSError("invalid public asset target")
        ACTIVE_ADAPTER._preflight_file(app/"assets",target,item["sha256"],"public asset",parse_json=target.suffix.lower()==".json",parse_jsonl=target.suffix.lower()==".jsonl")
    launcher=tests/"test.sh"
    if launcher.is_symlink() or not launcher.is_file() or hashlib.sha256(launcher.read_bytes()).hexdigest()!=TEST_SH_SHA256:
        raise OSError("physical test.sh launcher hash mismatch")


def _load_adapter():
    import types
    if hashlib.sha256(ADAPTER_SOURCE_TEXT.encode("utf-8")).hexdigest()!=ADAPTER_SOURCE_SHA256: raise RuntimeError("original adapter source hash mismatch")
    if ADAPTER_SOURCE_TEXT.count(CHILD_ARGV_OLD)!=1: raise RuntimeError("adapter child argv transform ambiguous")
    active=ADAPTER_SOURCE_TEXT.replace(CHILD_ARGV_OLD,CHILD_ARGV_NEW,1)
    if hashlib.sha256(active.encode("utf-8")).hexdigest()!=ACTIVE_ADAPTER_SHA256: raise RuntimeError("active adapter source mismatch")
    guardmod=types.ModuleType("submission_guard");guardmod.CandidateInputError=CandidateInputError;guardmod.guard_submission=guard_submission;guardmod.safe_candidate_path=safe_candidate_path;sys.modules["submission_guard"]=guardmod
    mod=types.ModuleType("embedded_verifier_adapter");mod.__dict__.update({k:x for k,x in globals().items() if k not in ("__name__","__file__")});mod.__file__="<embedded:verifier_adapter.py>";sys.modules[mod.__name__]=mod
    exec(compile(active,mod.__file__,"exec"),mod.__dict__);mod._preflight_environment=_embedded_preflight
    return mod
ACTIVE_ADAPTER=_load_adapter()

def _dispatch():
    try:
        _scrub_agent_credentials()
    except Exception as exc:
        report = {"status": "ENV_INVALID", "reason": "credential cleanup failed: %s" % exc}
        try:
            logs = Path(os.environ.get("LOGS", "/logs/verifier"))
            ACTIVE_ADAPTER._prepare_logs(logs)
            (logs / "reward.json").unlink(missing_ok=True)
            ACTIVE_ADAPTER._write(logs / "verification.stdout", b"")
            ACTIVE_ADAPTER._write(logs / "verification.stderr", (str(exc) + "\n").encode("utf-8", "replace"))
            ACTIVE_ADAPTER._write(logs / "verification.json", ACTIVE_ADAPTER._json_bytes(report))
        except Exception as persist_exc:
            report["reason"] += "; cannot persist verification report: %s" % persist_exc
        print(json.dumps(report, ensure_ascii=False, allow_nan=False))
        raise SystemExit(2)
    if len(sys.argv) > 1 and sys.argv[1] == "--scientific-child":
        load_scoring_evaluator()
        raise SystemExit(main([sys.argv[0], *sys.argv[2:]]))
    raise SystemExit(ACTIVE_ADAPTER.main())

def _scrub_agent_credentials(root=Path("/root"), container_marker=Path("/.dockerenv"), euid=None):
    """Remove agent credential mounts only inside the root-owned verifier container."""
    import shutil

    root = Path(root)
    container_marker = Path(container_marker)
    if euid is None:
        euid = os.geteuid()
    marker_stat = container_marker.lstat()
    if not stat.S_ISREG(marker_stat.st_mode) or euid != 0:
        raise RuntimeError("credential cleanup requires a Docker container running as root")
    root_stat = root.lstat()
    if not stat.S_ISDIR(root_stat.st_mode):
        raise RuntimeError("credential cleanup root is not a real directory")

    for relative in (Path(".ssh"), Path(".config/submit-job")):
        for parent in reversed(relative.parents):
            if parent == Path("."):
                continue
            parent_path = root / parent
            try:
                parent_stat = parent_path.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(parent_stat.st_mode):
                raise RuntimeError("credential parent is not a real directory: %s" % parent_path)
        target = root / relative
        try:
            target_stat = target.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(target_stat.st_mode) and not stat.S_ISLNK(target_stat.st_mode):
            shutil.rmtree(target)
        else:
            target.unlink()
        try:
            target.lstat()
        except FileNotFoundError:
            continue
        raise RuntimeError("credential path remains after cleanup: %s" % target)


if __name__ == "__main__":
    _dispatch()
