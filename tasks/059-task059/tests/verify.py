#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including parameters.json, convergence.json, report.md).
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Generate and validate GaAs first-principles inputs for carrier-scattering calculations.
"""Standalone Case05 candidate-native grader; no host runtime or private source mount."""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any
import sys
import argparse
from types import SimpleNamespace
import hashlib
import json
import math
import os
import re
import stat
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
import math, re
import numpy as np
from typing import Any, Mapping
import copy
import datetime as _datetime

CASE_ID = "case-05-first-principles-inputs"
RESULT_SCHEMA = "case05-scientific-verification/v1"
ADAPTER_SCHEMA = "case05.native_observation_adapter.v1"
NATIVE_LINK_SCHEMA = "case05-native-source-links/v1"
CRITERIA = ("native_generation", "physical_tensors", "applicable_numerical_reference")
MAX_TRUST_BYTES = 16 * 1024 * 1024
MAX_XML_BYTES = 64 * 1024 * 1024
MAX_CANDIDATE_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 64
MAX_NODES = 100_000
JOB_RE = re.compile(r"^[0-9]{1,32}$")
RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")

CASE_ID = "case-05-first-principles-inputs"

RESULT_SCHEMA = "case05-scientific-verification/v1"

NATIVE_LINK_SCHEMA = "case05-native-source-links/v1"

ADAPTER_SCHEMA = "case05.native_observation_adapter.v1"

MAX_TRUST_BYTES = 16 * 1024 * 1024

MAX_CANDIDATE_BYTES = 16 * 1024 * 1024

MAX_XML_BYTES = 64 * 1024 * 1024

SHA_RE = re.compile(r"^[0-9a-f]{64}$")

NATIVE_FILES = ("POSCAR", "INCAR", "KPOINTS", "OUTCAR", "vasprun.xml",
                "execution-receipt.json", "input-manifest.json")

CRITERIA = ("native_generation", "physical_tensors", "applicable_numerical_reference")

MAX_DEPTH = 64

MAX_NODES = 100_000

class EnvironmentInvalid(Exception):
    """A broken trust root, dependency, or unsupported evaluation capability."""

class CandidateFailure(Exception):
    """A decisive candidate/output violation under healthy evaluation inputs."""

    def __init__(self, message: str, criterion: str = "native_generation") -> None:
        super().__init__(message)
        self.criterion = criterion

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)

def _require_supported_bulk_gap_phase(record: dict[str, Any]) -> None:
    """Reject finite-displacement spectra as the undeformed PBE bulk gap."""
    result = record.get("result", {})
    hashes = result.get("source_hashes", {})
    if any(type(hashes.get(name)) is not str or not SHA_RE.fullmatch(hashes[name])
           for name in ("INCAR", "vasprun.xml")):
        raise EnvironmentInvalid("PBE gap source lacks source-bound native phase controls")
    layers = result.get("native_control_layers", {}).get("values_by_source", {})
    layer_names = ("INCAR", "vasprun.xml/incar", "vasprun.xml/parameters")
    values = []
    for layer_name in layer_names:
        layer = layers.get(layer_name)
        value = layer.get("IBRION") if type(layer) is dict else None
        if type(value) not in (int, float) or not math.isfinite(value) or int(value) != value:
            raise EnvironmentInvalid("PBE gap source lacks a supported source-bound IBRION phase")
        values.append(int(value))
    incar_observation = result.get("incar_observations", {}).get("IBRION")
    if (type(incar_observation) is not dict or type(incar_observation.get("source")) is not str or
            incar_observation["source"].split(":", 1)[0] != "INCAR" or
            incar_observation.get("value") not in values or len(set(values)) != 1):
        raise EnvironmentInvalid("PBE gap source has inconsistent source-bound IBRION phase controls")
    if values[0] in (5, 6):
        raise EnvironmentInvalid(
            f"PBE gap source uses unsupported finite-displacement groundstate phase (IBRION={values[0]})")

def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result

def _constant(token: str) -> None:
    raise ValueError("nonfinite JSON constant")

def strict_json(raw: bytes, *, max_bytes: int = MAX_TRUST_BYTES) -> Any:
    if len(raw) > max_bytes:
        raise ValueError("JSON exceeds fixed size limit")
    text = raw.decode("utf-8")
    # Bound parser work before constructing nested Python objects.
    depth = 0
    nodes = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            nodes += 1
            if depth > MAX_DEPTH:
                raise ValueError("JSON nesting exceeds fixed limit")
        elif char in "]}":
            depth -= 1
            nodes += 1
            if depth < 0:
                raise ValueError("unbalanced JSON container")
        elif char in ",:":
            nodes += 1
        if nodes > MAX_NODES:
            raise ValueError("JSON node count exceeds fixed limit")
    if in_string or depth != 0:
        raise ValueError("unterminated string or unbalanced JSON")
    value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant,
                       parse_float=lambda x: _finite_float(x))
    _finite_tree(value)
    return value

def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("nonfinite JSON number")
    return value

def _finite_tree(value: Any) -> None:
    if type(value) is float and not math.isfinite(value):
        raise ValueError("nonfinite JSON number")
    if type(value) is dict:
        for child in value.values():
            _finite_tree(child)
    elif type(value) is list:
        for child in value:
            _finite_tree(child)

def read_regular(path: Path, *, max_bytes: int, environment: bool) -> bytes:
    err = EnvironmentInvalid if environment else CandidateFailure
    try:
        before_path = os.lstat(path)
        if stat.S_ISLNK(before_path.st_mode) or not stat.S_ISREG(before_path.st_mode):
            raise err(f"not a regular file: {path.name}")
        if before_path.st_size > max_bytes:
            raise err(f"file exceeds fixed size limit: {path.name}")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                     getattr(os, "O_CLOEXEC", 0))
        try:
            before = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_size) != (
                    before_path.st_dev, before_path.st_ino, before_path.st_size):
                raise err(f"file identity changed before read: {path.name}")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise err(f"file exceeds fixed size limit: {path.name}")
            after = os.fstat(fd)
            current = os.stat(path, follow_symlinks=False)
            identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            if identity(before) != identity(after) or identity(before) != identity(current) or total != before.st_size:
                raise err(f"file changed while reading: {path.name}")
            return b"".join(chunks)
        finally:
            os.close(fd)
    except (EnvironmentInvalid, CandidateFailure):
        raise
    except OSError as exc:
        raise err(f"cannot securely read {path.name}: {type(exc).__name__}") from exc

def read_candidate_member(final: Path, relative: str, *, max_bytes: int) -> bytes:
    root = Path(final)
    try:
        root_stat = os.lstat(root)
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise CandidateFailure("final directory must be a real directory")
        current = root
        for part in PurePosixPath(relative).parts:
            if part in ("", ".", ".."):
                raise CandidateFailure("candidate path is not canonical")
            current = current / part
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode):
                raise CandidateFailure("candidate output path traverses a symlink")
            if current != root / relative and not stat.S_ISDIR(info.st_mode):
                raise CandidateFailure("candidate output parent is not a directory")
        return read_regular(current, max_bytes=max_bytes, environment=False)
    except CandidateFailure:
        raise
    except OSError as exc:
        raise CandidateFailure(f"candidate output missing or unreadable: {Path(relative).name}") from exc

def read_public_member(root: Path, relative: str, *, max_bytes: int) -> bytes:
    """Read a declared public member beneath the explicit read-only mount."""
    parts = PurePosixPath(relative).parts
    if PurePosixPath(relative).is_absolute() or not parts or any(part in ("", ".", "..") for part in parts):
        raise EnvironmentInvalid("public metadata path is not canonical")
    try:
        root_info = os.lstat(root)
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            raise EnvironmentInvalid("public input root must be a real mounted directory")
        current = root
        for index, part in enumerate(parts):
            current = current / part
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode):
                raise EnvironmentInvalid("symlink in public metadata/input path")
            if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
                raise EnvironmentInvalid("public metadata/input parent is not a directory")
        return read_regular(current, max_bytes=max_bytes, environment=True)
    except EnvironmentInvalid:
        raise
    except OSError as exc:
        raise EnvironmentInvalid(f"cannot securely read public member {Path(relative).name}: {type(exc).__name__}") from exc

def _finite_matrix(value: Any, rows: int, cols: int, label: str) -> list[list[float]]:
    if type(value) is not list or len(value) != rows:
        raise CandidateFailure(f"{label} must have {rows} rows")
    out: list[list[float]] = []
    for row in value:
        if type(row) is not list or len(row) != cols or any(not finite(x) for x in row):
            raise CandidateFailure(f"{label} must be a finite {rows}x{cols} numeric matrix")
        out.append([float(x) for x in row])
    return out

def _symmetric_positive_definite(matrix: list[list[float]], tol: float = 1e-6) -> bool:
    n = len(matrix)
    if any(abs(matrix[i][j] - matrix[j][i]) > tol * max(1.0, abs(matrix[i][j]), abs(matrix[j][i]))
           for i in range(n) for j in range(n)):
        return False
    # Cholesky positivity check avoids a NumPy dependency in the verifier.
    lower = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            acc = matrix[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                if acc <= 0:
                    return False
                lower[i][j] = math.sqrt(acc)
            else:
                lower[i][j] = acc / lower[j][j]
    return True

def _obs_map(observations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for row in observations:
        if type(row) is dict and type(row.get("field")) is str:
            if row["field"] in result:
                raise EnvironmentInvalid("native adapter emitted duplicate observation field")
            result[row["field"]] = row
    return result

def _candidate_native(final: Path, groups: dict[str, dict[str, dict[str, Any]]], adapter: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    native_dir = final / "native"
    manifest_raw = read_candidate_member(final, "native/manifest.json", max_bytes=2 * 1024 * 1024)
    try:
        manifest = strict_json(manifest_raw, max_bytes=2 * 1024 * 1024)
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateFailure("native/manifest.json is not strict JSON") from exc
    if type(manifest) is not dict or set(manifest) != {"schema", "runs"} or manifest.get("schema") != NATIVE_LINK_SCHEMA:
        raise CandidateFailure("native manifest schema mismatch")
    if type(manifest["runs"]) is not list or not manifest["runs"]:
        raise CandidateFailure("native manifest must list collected runs")
    seen_runs: set[str] = set()
    observations: dict[str, dict[str, Any]] = {}
    source_ids: list[str] = []
    for run in manifest["runs"]:
        if type(run) is not dict or set(run) != {"run_id", "files"}:
            raise CandidateFailure("native run link has unsupported fields")
        run_id = run["run_id"]
        if type(run_id) is not str or run_id in seen_runs or run_id not in groups:
            raise CandidateFailure("native run is not uniquely present in trusted collection")
        seen_runs.add(run_id)
        if type(run["files"]) is not list or len(run["files"]) != len(NATIVE_FILES):
            raise CandidateFailure("native run must link all seven native members")
        links: dict[str, dict[str, Any]] = {}
        for link in run["files"]:
            if type(link) is not dict or set(link) != {"name", "source_id", "sha256"}:
                raise CandidateFailure("native source link malformed")
            name = link["name"]
            if name not in NATIVE_FILES or name in links:
                raise CandidateFailure("native source filename missing, extra, or duplicated")
            trusted = groups[run_id][name]
            row = trusted["row"]
            if link["source_id"] != trusted["source_id"] or link["sha256"] != row["sha256"]:
                raise CandidateFailure(f"native source link does not match collected {name}")
            candidate_path = native_dir / "runs" / run_id / name
            raw = read_candidate_member(final, f"native/runs/{run_id}/{name}",
                                        max_bytes=MAX_XML_BYTES if name == "vasprun.xml" else 32 * 1024 * 1024)
            if digest(raw) != row["sha256"] or len(raw) != row["bytes"]:
                raise CandidateFailure(f"submitted native/{run_id}/{name} differs from collected source")
            links[name] = trusted
            source_ids.append(trusted["source_id"])
        if set(links) != set(NATIVE_FILES):
            raise CandidateFailure("native run does not contain the exact collected file set")
        expected = {name: links[name]["row"]["sha256"] for name in NATIVE_FILES}
        try:
            result = adapter.observe_native_run(native_dir / "runs" / run_id, expected)
        except adapter.CandidateNativeInvalid as exc:
            raise CandidateFailure(f"hash-authenticated native content is malformed: {exc}") from exc
        except adapter.EnvironmentInvalid as exc:
            raise EnvironmentInvalid(f"native adapter trust/capability error: {exc}") from exc
        if (result.get("schema") != ADAPTER_SCHEMA or result.get("science_gate_released") is not False or
                result.get("scoring_status") != "NOT_EVALUATED" or result.get("source_hashes") != expected):
            raise EnvironmentInvalid("native adapter returned unsupported trust/status metadata")
        manifest_path = groups[run_id]["input-manifest.json"]["path"]
        manifest_raw = read_regular(manifest_path, max_bytes=2 * 1024 * 1024, environment=True)
        if digest(manifest_raw) != groups[run_id]["input-manifest.json"]["row"]["sha256"]:
            raise EnvironmentInvalid("trusted input manifest changed after native observation")
        try:
            manifest_obj = strict_json(manifest_raw, max_bytes=2 * 1024 * 1024)
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise EnvironmentInvalid("trusted input manifest is not strict JSON") from exc
        evidence_rows = {}
        for name in NATIVE_FILES:
            row = dict(groups[run_id][name]["row"])
            row["source_id"] = links[name]["source_id"]
            evidence_rows[name] = row
        observations[run_id] = {"result": result, "fields": _obs_map(result["observations"]),
                                "source_ids": [links[n]["source_id"] for n in NATIVE_FILES],
                                "evidence_rows": evidence_rows,
                                "manifest_metadata": {key: manifest_obj.get(key) for key in (
                                    "stage", "stage_kind", "source_poscar_sha256", "parent_geometry_sha256",
                                    "relaxed_geometry_sha256", "encut_ev", "mesh")}}
    if seen_runs != set(groups):
        raise CandidateFailure("native/manifest omits one or more trusted collected native runs")
    return observations, sorted(source_ids)

def _parse_poscar(path: Path) -> dict[str, Any]:
    raw = read_regular(path, max_bytes=2 * 1024 * 1024, environment=True)
    try:
        lines = [line.strip() for line in raw.decode("ascii").splitlines() if line.strip()]
        scale = float(lines[1])
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError
        lattice = [[float(x) * scale for x in lines[i].split()] for i in range(2, 5)]
        species = lines[5].split()
        counts = [int(x) for x in lines[6].split()]
        if len(species) != len(counts) or any(n < 0 for n in counts):
            raise ValueError
        mode_i = 7
        if lines[mode_i].lower().startswith("s"):
            mode_i += 1
        direct = lines[mode_i].lower().startswith("d")
        if not direct and not lines[mode_i].lower().startswith(("c", "k")):
            raise ValueError
        nsites = sum(counts)
        positions = [[float(x) for x in lines[mode_i + 1 + i].split()[:3]] for i in range(nsites)]
        expanded_species = [sp for sp, count in zip(species, counts) for _ in range(count)]
        if any(len(row) != 3 for row in lattice) or len(positions) != nsites:
            raise ValueError
        if not direct:
            # Convert Cartesian coordinates to fractional using an explicit 3x3 inverse.
            a, b, c = lattice
            det = (a[0]*(b[1]*c[2]-b[2]*c[1]) - a[1]*(b[0]*c[2]-b[2]*c[0]) + a[2]*(b[0]*c[1]-b[1]*c[0]))
            if abs(det) < 1e-12:
                raise ValueError
            inv = [[(b[1]*c[2]-b[2]*c[1])/det, (a[2]*c[1]-a[1]*c[2])/det, (a[1]*b[2]-a[2]*b[1])/det],
                   [(b[2]*c[0]-b[0]*c[2])/det, (a[0]*c[2]-a[2]*c[0])/det, (a[2]*b[0]-a[0]*b[2])/det],
                   [(b[0]*c[1]-b[1]*c[0])/det, (a[1]*c[0]-a[0]*c[1])/det, (a[0]*b[1]-a[1]*b[0])/det]]
            positions = [[sum(row[j] * inv[j][i] for j in range(3)) for i in range(3)] for row in positions]
        return {"lattice_vectors_angstrom": lattice, "species_order": expanded_species,
                "fractional_positions": positions}
    except (ValueError, IndexError, UnicodeError, OverflowError) as exc:
        raise EnvironmentInvalid("public GaAs seed POSCAR is malformed") from exc

def _close(a: float, b: float, tol: float = 2e-5) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))

def _candidate_sources(value: Any, all_sources: set[str], label: str) -> list[str]:
    if (type(value) is not list or not value or
            any(type(item) is not str or item not in all_sources for item in value) or
            len(set(value)) != len(value)):
        raise CandidateFailure(f"{label} source_ids must be a unique list of trusted source identifiers")
    return value

def _compare_structure(candidate: Any, native: dict[str, Any], seed: dict[str, Any]) -> None:
    if type(candidate) is not dict or set(candidate) != {
            "lattice_vectors_angstrom", "species_order", "fractional_positions"}:
        raise CandidateFailure("parameters.structure schema is incomplete")
    if candidate["species_order"] != native["structure.species_order"]["value"]:
        raise CandidateFailure("reported structure species order differs from native XML")
    if candidate["species_order"] != seed["species_order"]:
        raise CandidateFailure("reported structure species differ from public GaAs seed")
    for key, obs_key in (("lattice_vectors_angstrom", "structure.lattice"),
                         ("fractional_positions", "structure.fractional_positions")):
        value = candidate[key]
        expected = native[obs_key]["value"]
        if type(value) is not list or len(value) != len(expected):
            raise CandidateFailure(f"reported structure {key} shape differs from native XML")
        try:
            for ra, rb in zip(value, expected):
                if type(ra) is not list or len(ra) != len(rb):
                    raise CandidateFailure(f"reported structure {key} shape malformed")
                if any(not finite(x) or not _close(float(x), float(y)) for x, y in zip(ra, rb)):
                    raise CandidateFailure(f"reported structure {key} differs from native XML")
        except TypeError as exc:
            raise CandidateFailure(f"reported structure {key} malformed") from exc
    # The public seed defines composition and site count; final coordinates/cell
    # come from the selected, hash-authenticated relaxed/native calculation.
    if len(candidate["species_order"]) != len(seed["species_order"]):
        raise CandidateFailure("native structure site count differs from public seed")

def _check_convergence(obj: Any, required_quantities: tuple[str, ...], all_sources: set[str]) -> tuple[bool, str]:
    if type(obj) is not dict or set(obj) != {"schema", "quantities"} or obj.get("schema") != "case05-convergence/v1":
        raise CandidateFailure("convergence.json schema mismatch")
    rows = obj["quantities"]
    if type(rows) is not list:
        raise CandidateFailure("convergence quantities must be a list")
    by_name: dict[str, Any] = {}
    for row in rows:
        if type(row) is not dict or set(row) != {"quantity", "units", "settings", "claimed_tolerance", "claimed_converged"}:
            raise CandidateFailure("convergence row schema malformed")
        name = row["quantity"]
        if type(name) is not str or name in by_name:
            raise CandidateFailure("convergence quantity missing or duplicated")
        if type(row["units"]) is not str or not row["units"] or not finite(row["claimed_tolerance"]) or row["claimed_tolerance"] < 0:
            raise CandidateFailure("convergence units/tolerance malformed")
        if type(row["claimed_converged"]) is not bool or type(row["settings"]) is not list or len(row["settings"]) < 2:
            raise CandidateFailure("each reported quantity needs two comparable settings")
        seen = set()
        parsed = []
        for setting in row["settings"]:
            if type(setting) is not dict or set(setting) != {"setting_id", "method_id", "value", "source_ids"}:
                raise CandidateFailure("convergence setting schema malformed")
            if (type(setting["setting_id"]) is not str or not setting["setting_id"] or
                    type(setting["method_id"]) is not str or not setting["method_id"]):
                raise CandidateFailure("convergence setting identity/value malformed")
            if name in {"epsilon_high", "epsilon_static"}:
                if type(setting["value"]) is list:
                    parsed_value: Any = _finite_matrix(setting["value"], 3, 3, f"{name} convergence value")
                elif finite(setting["value"]):
                    parsed_value = float(setting["value"])
                else:
                    raise CandidateFailure("convergence setting identity/value malformed")
            else:
                if not finite(setting["value"]):
                    raise CandidateFailure("convergence setting identity/value malformed")
                parsed_value = float(setting["value"])
            _candidate_sources(setting["source_ids"], all_sources, "convergence setting")
            seen.add(setting["setting_id"])
            parsed.append(parsed_value)
        if len(seen) < 2 or len({s["method_id"] for s in row["settings"]}) != 1:
            raise CandidateFailure("convergence settings must differ while sharing a method")
        if name in {"epsilon_high", "epsilon_static"} and all(type(x) is list for x in parsed):
            actual_delta = max(abs(a[i][j] - b[i][j]) for a in parsed for b in parsed
                               for i in range(3) for j in range(3))
        else:
            if name in {"epsilon_high", "epsilon_static"} and any(type(x) is list for x in parsed):
                raise CandidateFailure("convergence tensor settings must use one consistent shape")
            actual_delta = max(parsed) - min(parsed)
        if row["claimed_converged"] and actual_delta > float(row["claimed_tolerance"]):
            raise CandidateFailure("convergence claim exceeds its own declared tolerance")
        by_name[name] = row
    missing = [name for name in required_quantities if name not in by_name]
    if missing:
        raise CandidateFailure("convergence omits reported quantities: " + ",".join(missing))
    # The payload is internally checkable, but its tolerance/method suitability
    # is not qualified by an independent Case 05 reference.
    return False, "two-setting records are structurally consistent; tolerance suitability is unqualified"

def _validate_candidate(final: Path, observations: dict[str, dict[str, Any]], all_sources: list[str], seed: dict[str, Any],
                        component_reference: Any) -> tuple[list[dict[str, Any]], bool]:
    params_raw = read_candidate_member(final, "parameters.json", max_bytes=MAX_CANDIDATE_BYTES)
    convergence_raw = read_candidate_member(final, "convergence.json", max_bytes=MAX_CANDIDATE_BYTES)
    report_raw = read_candidate_member(final, "report.md", max_bytes=MAX_CANDIDATE_BYTES)
    if not report_raw.strip():
        raise CandidateFailure("report.md is empty")
    try:
        params = strict_json(params_raw, max_bytes=MAX_CANDIDATE_BYTES)
        convergence = strict_json(convergence_raw, max_bytes=MAX_CANDIDATE_BYTES)
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateFailure("parameters.json or convergence.json is not strict JSON") from exc
    if type(params) is not dict or params.get("schema") != "case05-parameters/v1":
        raise CandidateFailure("parameters.json schema mismatch")
    required = {"schema", "method", "structure", "pbe_bandgap", "hse06_bandgap_annotation",
                "elastic_C_GPa", "epsilon_high", "epsilon_static", "pop_frequency", "deformation_potentials"}
    if set(params) != required:
        raise CandidateFailure("parameters.json has missing or unexpected top-level fields")
    # Validate every response container before source/geometry resolution.
    # Malformed candidate shapes are decisive output failures; they must not
    # escape as KeyError/AttributeError and be mislabeled grader ENV failures.
    for key in ("epsilon_high", "epsilon_static"):
        if type(params[key]) is not dict or set(params[key]) != {"matrix", "units", "source_ids"}:
            raise CandidateFailure(f"{key} schema mismatch", "physical_tensors")
    if type(params["pop_frequency"]) is not dict or set(params["pop_frequency"]) != {
            "value_THz", "mode", "q_limit", "source_ids"}:
        raise CandidateFailure("pop_frequency schema mismatch")
    dp_shape = params["deformation_potentials"]
    if type(dp_shape) is not dict or set(dp_shape) != {
            "energy_reference", "strain_convention", "electron", "hole"}:
        raise CandidateFailure("deformation_potentials schema mismatch")
    for carrier in ("electron", "hole"):
        block = dp_shape[carrier]
        if type(block) is not dict or set(block) != {"states", "source_ids"}:
            raise CandidateFailure(f"{carrier} deformation block schema mismatch")
        if type(block["states"]) is not list or not block["states"]:
            raise CandidateFailure(f"{carrier} deformation states missing")
        if type(block["source_ids"]) is not list:
            raise CandidateFailure(f"{carrier} deformation source_ids must be a list")
    if type(params["method"]) is not dict or set(params["method"]) != {"engine", "functional", "source_ids"}:
        raise CandidateFailure("parameters.method schema mismatch")
    method_sources = _candidate_sources(params["method"]["source_ids"], set(all_sources), "method")
    obs_rows = [x for record in observations.values() for x in record["fields"].values()]
    native_pbe_runs = [record for record in observations.values()
                       if record["result"].get("method", {}).get("xc_from_incar") == "PBE"]
    if not native_pbe_runs:
        raise EnvironmentInvalid("available native adapter does not identify a supported PBE run")
    if params["method"]["functional"] != "PBE":
        # Equivalent scientific methods require an independently qualified adapter.
        raise EnvironmentInvalid("candidate method lacks an approved equivalent-method adapter")
    if params["method"]["engine"] != "VASP":
        raise EnvironmentInvalid("candidate engine lacks an approved native adapter")

    def source_record(source_ids: list[str], label: str) -> dict[str, Any]:
        """Resolve a candidate source declaration to exactly one native run."""
        declared = set(source_ids)
        matches = [record for record in observations.values()
                   if declared.issubset(set(record["source_ids"]))]
        if len(matches) != 1:
            if any(declared & set(record["source_ids"]) for record in observations.values()
                   if record["result"].get("method", {}).get("xc_from_incar") != "PBE"):
                raise EnvironmentInvalid(f"{label} cites a valid native route without a qualified adapter")
            raise CandidateFailure(f"{label} sources do not identify one native run")
        record = matches[0]
        if record["result"].get("method", {}).get("xc_from_incar") != "PBE":
            raise EnvironmentInvalid(f"{label} native method route is not qualified")
        return record

    selected = source_record(method_sources, "declared method")
    fields = selected["fields"]
    _compare_structure(params["structure"], fields, seed)
    pbe = params["pbe_bandgap"]
    if type(pbe) is not dict or set(pbe) != {"fundamental_eV", "direct_eV", "method", "source_ids"}:
        raise CandidateFailure("pbe_bandgap schema mismatch")
    if pbe["method"] != "PBE":
        raise CandidateFailure("PBE gap method/provenance missing")
    pbe_sources = _candidate_sources(pbe["source_ids"], set(all_sources), "PBE gap")
    pbe_record = source_record(pbe_sources, "PBE gap")
    if pbe_record is not selected:
        raise CandidateFailure("PBE gap cites unrelated native evidence")
    f_gap = fields["band.fundamental_gap"]["value"]
    d_gap = fields["band.direct_gap"]["value"]
    if f_gap is None or d_gap is None:
        raise CandidateFailure("native PBE occupations do not support an insulating gap")
    if not finite(pbe["fundamental_eV"]) or not finite(pbe["direct_eV"]):
        raise CandidateFailure("PBE gap values must be finite")
    if float(f_gap) <= 0 or float(d_gap) <= 0:
        raise CandidateFailure("native PBE evidence is metallic or has a nonpositive gap")
    if not _close(float(pbe["fundamental_eV"]), float(f_gap), 3e-4) or not _close(float(pbe["direct_eV"]), float(d_gap), 3e-4):
        raise CandidateFailure("reported PBE gaps disagree with source-bound native observations")

    def assert_response_parent(source_ids: list[str], label: str) -> None:
        response_run = source_record(source_ids, label)
        # Compare the response's XML initial geometry to the submitted bulk
        # structure, which was itself selected from the declared PBE source.
        # Do not substitute a relaxation run's XML initial geometry for its
        # selected final bulk geometry; elastic finite-difference final cells
        # remain handled by their separately named native observations.
        for field, declared_key in (("structure.initial_lattice", "lattice_vectors_angstrom"),
                                    ("structure.initial_fractional_positions", "fractional_positions")):
            response_row = response_run["fields"].get(field)
            if type(response_row) is not dict:
                raise EnvironmentInvalid(f"{label} parent geometry is unavailable from the native adapter")
            if response_row.get("native_sha256") != response_run["result"].get("source_hashes", {}).get("vasprun.xml"):
                raise EnvironmentInvalid(f"{label} parent geometry is not bound to its XML")
            actual = response_row.get("value")
            declared = params["structure"].get(declared_key)
            if (type(actual) is not list or type(declared) is not list or len(declared) != len(actual) or
                    any(type(a) is not list or type(b) is not list or len(a) != len(b) or
                        any(not finite(x) or not finite(y) or not _close(float(x), float(y))
                            for x, y in zip(a, b)) for a, b in zip(declared, actual))):
                raise CandidateFailure(f"{label} submitted parent geometry differs from the declared bulk")

    for key in ("epsilon_high", "epsilon_static", "pop_frequency"):
        assert_response_parent(_candidate_sources(params[key]["source_ids"], set(all_sources), key), key)
    # Geometry contradictions retain their candidate FAIL priority. Once all
    # declared response parents agree with the selected bulk geometry, reject
    # a finite-displacement run as an unsupported bulk-gap phase.
    _require_supported_bulk_gap_phase(pbe_record)
    for carrier in ("electron", "hole"):
        dp_sources = _candidate_sources(params["deformation_potentials"][carrier]["source_ids"],
                                        set(all_sources), f"{carrier} deformation")
        dp_records = [record for record in observations.values()
                      if set(dp_sources) & set(record["source_ids"])]
        if not dp_records or any(record["result"].get("method", {}).get("xc_from_incar") != "PBE"
                                 for record in dp_records):
            if any(set(dp_sources) & set(record["source_ids"]) for record in observations.values()):
                raise EnvironmentInvalid(f"{carrier} deformation source route lacks a qualified adapter")
            raise CandidateFailure(f"{carrier} deformation sources do not resolve to native PBE runs")

    hse = params["hse06_bandgap_annotation"]
    if hse is not None:
        if type(hse) is not dict or set(hse) != {"value_eV", "method", "source_ids"} or hse["method"] != "HSE06":
            raise CandidateFailure("HSE06 gap must be a separate typed annotation")
        if not finite(hse["value_eV"]):
            raise CandidateFailure("HSE06 annotation lacks finite value or provenance")
        hse_sources = _candidate_sources(hse["source_ids"], set(all_sources), "HSE06 annotation")
        if _close(float(hse["value_eV"]), float(pbe["fundamental_eV"]), 1e-10) and hse["source_ids"] == pbe["source_ids"]:
            raise CandidateFailure("HSE06 annotation cannot relabel the PBE gap evidence")
        hse_runs = [record for record in observations.values()
                    if set(hse_sources).issubset(record["source_ids"])
                    and str(record["result"].get("method", {}).get("method_manifest_xc_raw", "")).upper()
                    in {"HSE", "HSE06"}]
        if not hse_runs:
            raise CandidateFailure("HSE06 annotation lacks a linked native HSE06 run")
        hse_gaps = [record["fields"].get("band.fundamental_gap", {}).get("value") for record in hse_runs]
        if not any(value is not None and finite(value) and _close(float(hse["value_eV"]), float(value), 3e-4)
                   for value in hse_gaps):
            raise CandidateFailure("HSE06 annotation disagrees with its linked native gap")

    checks: list[dict[str, Any]] = []
    def rec(name: str, status: str, reason: str, count: int, sources: list[str]) -> None:
        checks.append({"name": name, "status": status, "reason": reason,
                       "execution_count": count, "source_ids": sorted(set(sources))})
    rec("native_generation", "PASS", "source-bound structure, PBE gap, response, and strain native observations were replayed", 1,
        selected["source_ids"])

    required_quantities = ["elastic_C_GPa", "epsilon_high", "epsilon_static", "pop_frequency", "electron_deformation", "hole_deformation", "pbe_bandgap", "pbe_direct_gap"]
    _check_convergence(convergence, tuple(required_quantities), set(all_sources))
    # Structural and physical contradictions are decisive failures. The evaluator
    # does not infer missing response data from synthetic/convergence tables.
    elastic = params["elastic_C_GPa"]
    elastic_ok = False
    if type(elastic) is dict and set(elastic) == {"matrix", "units", "voigt_order", "source_ids"}:
        c = _finite_matrix(elastic["matrix"], 6, 6, "elastic tensor")
        if elastic["units"] != "GPa" or elastic["voigt_order"] != ["xx", "yy", "zz", "yz", "xz", "xy"]:
            raise CandidateFailure("elastic tensor units or engineering Voigt order are invalid", "physical_tensors")
        elastic_sources = _candidate_sources(elastic["source_ids"], set(all_sources), "elastic tensor")
        if not _symmetric_positive_definite(c):
            raise CandidateFailure("elastic tensor is nonsymmetric or mechanically unstable", "physical_tensors")
        outcar_sources = {record["result"]["source_hashes"]["OUTCAR"]:
                          record["source_ids"][NATIVE_FILES.index("OUTCAR")]
                          for record in observations.values()}
        matched = [row for row in obs_rows if row["field"] == "elastic.relaxed_ion_total" and row.get("value") is not None]
        if matched:
            if not any(all(_close(float(c[i][j]), float(native_row["value"][i][j]), 1e-5)
                               for i in range(6) for j in range(6)) and
                       outcar_sources.get(native_row["native_sha256"]) in elastic_sources
                       for native_row in matched):
                raise CandidateFailure("reported elastic tensor differs from parsed native total tensor", "physical_tensors")
            elastic_ok = True
        else:
            # The reviewed adapter reports absence explicitly. Without a native
            # response section this is an evidence gap, not proof of a bad tensor.
            elastic_ok = False
    else:
        raise CandidateFailure("elastic_C_GPa schema mismatch")

    dielectrics_observed = {}
    for key in ("epsilon_high", "epsilon_static"):
        obj = params[key]
        if type(obj) is not dict or set(obj) != {"matrix", "units", "source_ids"}:
            raise CandidateFailure(f"{key} schema mismatch", "physical_tensors")
        m = _finite_matrix(obj["matrix"], 3, 3, key)
        if obj["units"] != "dimensionless":
            raise CandidateFailure(f"{key} units/provenance invalid", "physical_tensors")
        dielectric_sources = _candidate_sources(obj["source_ids"], set(all_sources), key)
        if not _symmetric_positive_definite(m):
            raise CandidateFailure(f"{key} must be symmetric positive definite", "physical_tensors")
        dielectrics_observed[key] = m
    high, static = dielectrics_observed["epsilon_high"], dielectrics_observed["epsilon_static"]
    difference = [[static[i][j] - high[i][j] for j in range(3)] for i in range(3)]
    # PSD by principal minors for symmetric 3x3.
    minors = [difference[0][0], difference[1][1], difference[2][2],
              difference[0][0]*difference[1][1]-difference[0][1]*difference[1][0],
              difference[0][0]*difference[2][2]-difference[0][2]*difference[2][0],
              difference[1][1]*difference[2][2]-difference[1][2]*difference[2][1],
              (difference[0][0]*(difference[1][1]*difference[2][2]-difference[1][2]*difference[2][1])
               - difference[0][1]*(difference[1][0]*difference[2][2]-difference[1][2]*difference[2][0])
               + difference[0][2]*(difference[1][0]*difference[2][1]-difference[1][1]*difference[2][0]))]
    if min(minors) < -1e-7:
        raise CandidateFailure("static-minus-high dielectric tensor is not positive semidefinite", "physical_tensors")
    for key, field_name in (("epsilon_high", "dielectric.epsilon_high"), ("epsilon_static", "dielectric.epsilon_static_observed_sum")):
        candidate_matrix = dielectrics_observed[key]
        candidate_sources = _candidate_sources(
            params[key]["source_ids"], set(all_sources), key
        )
        matches = [(record, record["fields"][field_name]) for record in observations.values()
                   if field_name in record["fields"] and record["fields"][field_name].get("value") is not None]
        if matches:
            if not any(all(_close(float(candidate_matrix[i][j]), float(native_row["value"][i][j]), 1e-5)
                               for i in range(3) for j in range(3)) and
                       record["source_ids"][NATIVE_FILES.index("OUTCAR")] in candidate_sources
                       for record, native_row in matches):
                raise CandidateFailure(f"reported {key} differs from parsed native tensor", "physical_tensors")
            dielectrics_observed[key] = candidate_matrix
        else:
            dielectrics_observed[key] = None
    if not elastic_ok or any(v is None for v in dielectrics_observed.values()):
        physical_status = "NOT_EVALUATED"
        physical_reason = "response source lacks one or more native qualified total/electronic/static tensors"
    else:
        physical_status = "NOT_EVALUATED"
        physical_reason = "tensor form/positivity checked; method-matched response convergence/reference is unqualified"
    pop = params["pop_frequency"]
    if type(pop) is not dict or set(pop) != {"value_THz", "mode", "q_limit", "source_ids"}:
        raise CandidateFailure("pop_frequency schema mismatch")
    if not finite(pop["value_THz"]) or float(pop["value_THz"]) <= 0 or pop["mode"] not in {"LO", "polar-optical"}:
        raise CandidateFailure("POP frequency must be a positive long-wave polar optical frequency")
    if pop["q_limit"] != "q_to_0":
        raise CandidateFailure("POP frequency lacks direction/mode/source provenance")
    _candidate_sources(pop["source_ids"], set(all_sources), "POP frequency")
    dp = params["deformation_potentials"]
    if type(dp) is not dict or set(dp) != {"energy_reference", "strain_convention", "electron", "hole"}:
        raise CandidateFailure("deformation_potentials schema mismatch")
    if dp["energy_reference"] not in {"common_all_atom_1s", "common_electrostatic", "other_explicit"} or type(dp["strain_convention"]) is not str or not dp["strain_convention"]:
        raise CandidateFailure("deformation potential energy reference or strain convention missing")
    for carrier in ("electron", "hole"):
        block = dp[carrier]
        if type(block) is not dict or set(block) != {"states", "source_ids"} or type(block["states"]) is not list or not block["states"]:
            raise CandidateFailure(f"{carrier} deformation states missing")
        _candidate_sources(block["source_ids"], set(all_sources), f"{carrier} deformation")
        if carrier == "hole":
            # Each degenerate valence edge must retain an explicit full matrix or
            # a declared invariant; a scalar band-centroid is insufficient.
            for state in block["states"]:
                if type(state) is not dict or not ({"subspace_matrix_eV"} <= set(state) or {"symmetry_invariant_eV"} <= set(state)):
                    raise CandidateFailure("hole edge omits the full degenerate subspace response/invariant")
                if "subspace_matrix_eV" in state:
                    _finite_matrix(state["subspace_matrix_eV"], 3, 3, "hole subspace matrix")
                else:
                    if not finite(state["symmetry_invariant_eV"]):
                        raise CandidateFailure("hole symmetry invariant is nonfinite")
    rec("physical_tensors", physical_status, physical_reason, 1,
        list(dict.fromkeys(elastic.get("source_ids", []) + params["epsilon_high"].get("source_ids", []) + params["epsilon_static"].get("source_ids", []))))
    rec("applicable_numerical_reference", "NOT_EVALUATED",
        "refs are explicitly partial; dielectric labels conflict in supplied sources and POP/deformation adapters are not qualified", 0, [])
    try:
        component_status = component_reference.evaluate_component_references(params, convergence, observations)
    except component_reference.CandidateReferenceError as exc:
        raise CandidateFailure(f"component reference/source mismatch: {exc}", "applicable_numerical_reference") from exc
    except component_reference.ReferenceEnvironmentError as exc:
        raise EnvironmentInvalid(f"component reference capability/source error: {exc}") from exc
    for key, criterion in (("elastic", "physical_tensors"),
                           ("band_edge_deformation", "applicable_numerical_reference")):
        qualification = component_status.get(key, {})
        if (qualification.get("status") == "QUALIFIED" and
                qualification.get("amplitude_convergence_status") == "NOT_QUALIFIED"):
            raise CandidateFailure(
                f"{key} source amplitudes exceed the existing convergence tolerance; value matching does not qualify amplitude convergence",
                criterion)
    checks[-1]["component_qualifications"] = component_status
    all_components_qualified = component_status.get("overall_scoring_ready") is True
    source_physics_qualified = (
        component_status.get("dielectric") == "QUALIFIED" and
        component_status.get("elastic", {}).get("status") == "QUALIFIED")
    if all_components_qualified and source_physics_qualified:
        checks[1]["status"] = "PASS"
        checks[1]["reason"] = "native elastic and dielectric tensors pass physical and source-convergence checks"
        checks[-1]["status"] = "PASS"
        checks[-1]["reason"] = "all finite source-family components, including both PBE gap quantities, are qualified"
    else:
        checks[-1]["reason"] = "one or more source-family components or source-bound setting checks remain unqualified"
    checks[1]["component_qualifications"] = {
        "dielectric": component_status["dielectric"],
        "elastic": component_status.get("elastic", {"status": "NOT_EVALUATED"}),
        "band_edge_deformation": component_status.get("band_edge_deformation", {"status": "NOT_EVALUATED"}),
        "pbe_bandgap": component_status.get("pbe_bandgap", "NOT_EVALUATED"),
        "pbe_direct_gap": component_status.get("pbe_direct_gap", "NOT_EVALUATED"),
        "overall_scoring_ready": all_components_qualified}
    checks[0]["execution_count"] = 1
    return checks, all_components_qualified and source_physics_qualified

def _empty_checks() -> list[dict[str, Any]]:
    return [{"name": name, "status": "NOT_EVALUATED", "reason": "environment preflight did not authorize scoring",
             "execution_count": 0, "source_ids": []} for name in CRITERIA]

def _make_result(status: str, reason: str, *, checks: list[dict[str, Any]] | None = None,
                 env: dict[str, str] | None = None, failed_outputs: list[str] | None = None,
                 decision_complete: bool = True, all_executed: bool = False) -> dict[str, Any]:
    out = {"schema": RESULT_SCHEMA, "case_id": CASE_ID, "status": status,
           "decision_complete": decision_complete, "checks_all_executed": all_executed,
           "reason": reason,
           "environment": env or {"task_inputs": "NOT_EVALUATED", "runner_context": "NOT_EVALUATED",
                                   "remote_evidence": "NOT_EVALUATED", "adapter": "NOT_EVALUATED"},
           "checks": checks if checks is not None else _empty_checks(),
           "missing_or_invalid_outputs": failed_outputs or [],
           "scoring_policy": {"PASS_implemented": True, "FAIL_reward": 0, "ENV_INVALID_reward": None}}
    if status == "FAIL":
        out["reward"] = 0
    return out
# Inlined, namespaced scientific module: native_observation_adapter_v1.py
from pathlib import Path

from typing import Any

ad_SCHEMA = "case05.native_observation_adapter.v1"

ad_FILES = (
    "POSCAR", "INCAR", "KPOINTS", "OUTCAR", "vasprun.xml",
    "execution-receipt.json", "input-manifest.json",
)

ad_LIMITS = {"vasprun.xml": 64 * 1024 * 1024, "OUTCAR": 32 * 1024 * 1024,
          "execution-receipt.json": 2 * 1024 * 1024,
          "input-manifest.json": 2 * 1024 * 1024}

ad_LIMIT_DEFAULT = 1024 * 1024

ad_NUMBER = re.compile(r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[Ee][+-]?\d+)?$")

ad_CONSISTENCY_TAGS = {"GGA", "LHFCALC", "AEXX", "HFSCREEN", "LEPSILON", "NSW", "IBRION",
                    "ENCUT", "EDIFF", "EDIFFG", "ISPIN", "ISMEAR", "SIGMA", "IBRION",
                    "ISIF", "PREC", "NELM", "NBANDS", "ICHARG", "ISYM", "LPEAD", "LREAL"}

class ad_AdapterError(Exception):
    """Base for a fail-closed adapter result."""

class ad_EnvironmentInvalid(ad_AdapterError):
    """Trusted snapshot, path, schema, dependency, or adapter capability issue."""

class ad_CandidateNativeInvalid(ad_AdapterError):
    """Malformed content in an otherwise hash-bound, candidate-owned native file."""

def ad__sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def ad__finite(value: float, where: str) -> float:
    if not math.isfinite(value):
        raise ad_CandidateNativeInvalid(f"non-finite native value at {where}")
    return value

def ad__strict_json(data: bytes, source: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"duplicate key {key!r}")
            out[key] = value
        return out

    def bad_constant(value: str) -> None:
        raise ValueError(f"non-finite token {value}")

    def reject_nonfinite(value: Any, path: str = "$") -> None:
        if type(value) is float and not math.isfinite(value):
            raise ValueError(f"non-finite numeric value at {path}")
        if type(value) is dict:
            for key, child in value.items():
                reject_nonfinite(child, f"{path}.{key}")
        elif type(value) is list:
            for index, child in enumerate(value):
                reject_nonfinite(child, f"{path}[{index}]")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=bad_constant)
        reject_nonfinite(value)
        return value
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ad_EnvironmentInvalid(f"invalid trusted {source}: {exc}") from exc

def ad__read_stable(run_dir: Path, name: str) -> bytes:
    """Read one direct child without following symlinks and verify stable identity."""
    if name not in ad_FILES or Path(name).name != name:
        raise ad_EnvironmentInvalid(f"unexpected native path {name!r}")
    root = Path(run_dir).absolute()
    try:
        # Reject a symlink at the requested run-directory leaf. Resolve
        # platform-level ancestor aliases (for example macOS /var -> /private/var)
        # before checking the physical path; the opened directory itself remains
        # NOFOLLOW and is never replaced by this adapter.
        requested = os.lstat(root)
        if stat.S_ISLNK(requested.st_mode) or not stat.S_ISDIR(requested.st_mode):
            raise ad_EnvironmentInvalid("native run directory must be a real directory, not a symlink")
        root = root.resolve(strict=True)
        cur = Path(root.anchor)
        for part in root.parts[1:]:
            cur = cur / part
            st = os.lstat(cur)
            if stat.S_ISLNK(st.st_mode):
                raise ad_EnvironmentInvalid(f"symlink in native directory path: {cur}")
            if not stat.S_ISDIR(st.st_mode):
                raise ad_EnvironmentInvalid(f"non-directory in native path: {cur}")
        dfd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                      getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.stat(name, dir_fd=dfd, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode):
                raise ad_EnvironmentInvalid(f"native member is not a regular file: {name}")
            limit = ad_LIMITS.get(name, ad_LIMIT_DEFAULT)
            if before.st_size > limit:
                raise ad_EnvironmentInvalid(f"native member exceeds adapter bound: {name}")
            fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dfd)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino, opened.st_size) != (before.st_dev, before.st_ino, before.st_size):
                    raise ad_EnvironmentInvalid(f"native member changed before open: {name}")
                chunks = []
                total = 0
                while True:
                    chunk = os.read(fd, min(1024 * 1024, limit + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > limit:
                        raise ad_EnvironmentInvalid(f"native member exceeds adapter bound: {name}")
                after = os.fstat(fd)
                current = os.stat(name, dir_fd=dfd, follow_symlinks=False)
                ident = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
                if ident(opened) != ident(after) or ident(opened) != ident(current):
                    raise ad_EnvironmentInvalid(f"native member changed while reading: {name}")
                return b"".join(chunks)
            finally:
                os.close(fd)
        finally:
            os.close(dfd)
    except ad_AdapterError:
        raise
    except OSError as exc:
        raise ad_EnvironmentInvalid(f"cannot securely read native member {name}: {exc}") from exc

def ad__incar(data: bytes) -> dict[str, tuple[str, str]]:
    try:
        text = data.decode("ascii")
    except UnicodeError as exc:
        raise ad_CandidateNativeInvalid("INCAR is not ASCII") from exc
    values: dict[str, tuple[str, str]] = {}
    for number, line in enumerate(text.splitlines(), 1):
        body = re.split(r"[#!]", line, maxsplit=1)[0].strip()
        if not body:
            continue
        if "=" not in body:
            raise ad_CandidateNativeInvalid(f"unrecognized INCAR line {number}")
        key, raw = body.split("=", 1)
        key = key.strip().upper()
        raw = raw.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not raw:
            raise ad_CandidateNativeInvalid(f"malformed INCAR assignment at line {number}")
        if key in values:
            raise ad_CandidateNativeInvalid(f"duplicate INCAR tag {key}")
        values[key] = (raw, f"INCAR:{number}")
    return values

def ad__parse_float(text: str, where: str, native: bool = True) -> float:
    token = text.strip()
    if not ad_NUMBER.fullmatch(token):
        exc = ad_CandidateNativeInvalid if native else ad_EnvironmentInvalid
        raise exc(f"invalid numeric token at {where}: {token!r}")
    value = float(token)
    return ad__finite(value, where)

def ad__child_named(parent: ET.Element, tag: str, name: str) -> ET.Element:
    found = [node for node in parent.findall(tag) if node.get("name") == name]
    if len(found) != 1:
        raise ad_CandidateNativeInvalid(f"expected one {tag} name={name!r}; found {len(found)}")
    return found[0]

def ad__vector_rows(node: ET.Element, expected: int, where: str) -> list[list[float]]:
    rows = node.findall("./v")
    if len(rows) != expected:
        raise ad_CandidateNativeInvalid(f"{where}: expected {expected} vectors, found {len(rows)}")
    result = []
    for idx, row in enumerate(rows):
        fields = (row.text or "").split()
        if len(fields) != 3:
            raise ad_CandidateNativeInvalid(f"{where}[{idx}] must have 3 coordinates")
        result.append([ad__parse_float(x, f"{where}[{idx}]") for x in fields])
    return result

def ad__matrix_inverse3(rows: list[list[float]], where: str) -> list[list[float]]:
    a, b, c = rows
    det = (a[0] * (b[1] * c[2] - b[2] * c[1])
           - a[1] * (b[0] * c[2] - b[2] * c[0])
           + a[2] * (b[0] * c[1] - b[1] * c[0]))
    if not math.isfinite(det) or abs(det) < 1e-12:
        raise ad_CandidateNativeInvalid(f"{where} lattice is singular")
    return [[(b[1] * c[2] - b[2] * c[1]) / det,
             (a[2] * c[1] - a[1] * c[2]) / det,
             (a[1] * b[2] - a[2] * b[1]) / det],
            [(b[2] * c[0] - b[0] * c[2]) / det,
             (a[0] * c[2] - a[2] * c[0]) / det,
             (a[2] * b[0] - a[0] * b[2]) / det],
            [(b[0] * c[1] - b[1] * c[0]) / det,
             (a[1] * c[0] - a[0] * c[1]) / det,
             (a[0] * b[1] - a[1] * b[0]) / det]]

def ad__poscar_initial_geometry(data: bytes, digest: str) -> dict[str, Any]:
    """Parse the bounded VASP5 POSCAR geometry used as response parent input."""
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise ad_CandidateNativeInvalid("POSCAR is not ASCII") from exc
    if len(lines) < 8:
        raise ad_CandidateNativeInvalid("POSCAR is truncated before coordinate rows")
    scale_fields = lines[1].split()
    if len(scale_fields) != 1:
        raise ad_CandidateNativeInvalid("POSCAR scale must be a single supported scalar")
    scale = ad__parse_float(scale_fields[0], "POSCAR:2")
    if scale <= 0:
        raise ad_CandidateNativeInvalid("POSCAR scale must be positive in the supported profile")
    raw_lattice = []
    for idx in range(3):
        fields = lines[2 + idx].split()
        if len(fields) != 3:
            raise ad_CandidateNativeInvalid(f"POSCAR lattice row {idx + 1} is malformed")
        raw_lattice.append([ad__parse_float(value, f"POSCAR:{idx + 3}") * scale for value in fields])
    symbols = lines[5].split()
    counts_raw = lines[6].split()
    if not symbols or len(symbols) != len(counts_raw) or any(
            not re.fullmatch(r"[A-Z][a-z]?$", item) for item in symbols):
        raise ad_CandidateNativeInvalid("POSCAR VASP5 species/count rows are malformed")
    if any(not re.fullmatch(r"[1-9][0-9]*", item) for item in counts_raw):
        raise ad_CandidateNativeInvalid("POSCAR species counts must be positive integers")
    counts = [int(item) for item in counts_raw]
    species = [symbol for symbol, count in zip(symbols, counts) for _ in range(count)]
    line_index = 7
    if lines[line_index].strip().lower().startswith("s"):
        line_index += 1
    if line_index >= len(lines):
        raise ad_CandidateNativeInvalid("POSCAR lacks coordinate mode")
    mode = lines[line_index].strip().lower()
    if mode.startswith("d"):
        coordinate_mode = "direct"
    elif mode.startswith(("c", "k")):
        coordinate_mode = "cartesian"
    else:
        raise ad_CandidateNativeInvalid("POSCAR coordinate mode is unsupported")
    positions_start = line_index + 1
    if len(lines) < positions_start + len(species):
        raise ad_CandidateNativeInvalid("POSCAR coordinate list is truncated")
    positions = []
    for idx in range(len(species)):
        fields = lines[positions_start + idx].split()
        if len(fields) < 3:
            raise ad_CandidateNativeInvalid(f"POSCAR coordinate row {idx + 1} is malformed")
        positions.append([ad__parse_float(value, f"POSCAR:{positions_start + idx + 1}")
                          for value in fields[:3]])
    if coordinate_mode == "cartesian":
        inv = ad__matrix_inverse3(raw_lattice, "POSCAR")
        positions = [[scale * sum(row[j] * inv[j][i] for j in range(3))
                      for i in range(3)] for row in positions]
    return {"lattice": raw_lattice, "species_order": species,
            "fractional_positions": positions, "coordinate_mode": coordinate_mode,
            "native_sha256": digest,
            "raw_pointer": {"lattice_lines": [3, 4, 5], "species_line": 6,
                            "counts_line": 7, "mode_line": line_index + 1,
                            "position_lines": list(range(positions_start + 1,
                                                         positions_start + len(species) + 1))}}

def ad__structure_from_xml(root: ET.Element, name: str, species: list[str],
                        xml_hash: str) -> dict[str, Any] | None:
    structures = [node for node in root.findall("./structure") if node.get("name") == name]
    if len(structures) > 1:
        raise ad_CandidateNativeInvalid(f"vasprun.xml repeats {name} structure")
    if not structures:
        return None
    structure = structures[0]
    crystal = structure.find("./crystal")
    if crystal is None:
        raise ad_CandidateNativeInvalid(f"{name} lacks crystal")
    lattice = ad__vector_rows(ad__child_named(crystal, "varray", "basis"), 3, f"{name}/basis")
    positions_node = ad__child_named(structure, "varray", "positions")
    positions = []
    for idx, row in enumerate(positions_node.findall("./v")):
        fields = (row.text or "").split()
        if len(fields) != 3:
            raise ad_CandidateNativeInvalid(f"{name}/positions[{idx}] malformed")
        positions.append([ad__parse_float(x, f"{name}/positions[{idx}]") for x in fields])
    if len(positions) != len(species):
        raise ad_CandidateNativeInvalid(f"{name} position/species counts do not agree")
    return {"lattice": lattice, "species_order": list(species),
            "fractional_positions": positions, "native_sha256": xml_hash,
            "raw_pointer": {"lattice": f"/modeling/structure[@name='{name}']/crystal/varray[@name='basis']",
                            "positions": f"/modeling/structure[@name='{name}']/varray[@name='positions']",
                            "species": "/modeling/atominfo/array[@name='atoms']"}}

def ad__compare_parent_geometries(poscar: dict[str, Any], initial: dict[str, Any],
                               manifest: dict[str, Any]) -> dict[str, Any]:
    """Bind response reference geometry to submitted POSCAR and XML initialpos."""
    if manifest.get("stage_kind") != "elastic":
        raise ad_CandidateNativeInvalid("IBRION=6 response geometry has an unexpected stage kind")
    if (manifest.get("source_poscar_sha256") != poscar["native_sha256"] or
            manifest.get("parent_geometry_sha256") != poscar["native_sha256"]):
        raise ad_CandidateNativeInvalid("elastic response parent geometry is not bound to submitted POSCAR")
    if poscar["species_order"] != initial["species_order"]:
        raise ad_CandidateNativeInvalid("submitted POSCAR and vasprun initialpos species/order differ")
    max_lattice = max(abs(poscar["lattice"][i][j] - initial["lattice"][i][j])
                      for i in range(3) for j in range(3))
    if max_lattice > 1e-7:
        raise ad_CandidateNativeInvalid("submitted POSCAR and vasprun initialpos lattice differ")
    deltas = [abs((poscar["fractional_positions"][i][j] -
                   initial["fractional_positions"][i][j]) -
                  round(poscar["fractional_positions"][i][j] -
                        initial["fractional_positions"][i][j]))
              for i in range(len(poscar["species_order"])) for j in range(3)]
    max_fractional = max(deltas, default=0.0)
    if max_fractional > 1e-7:
        raise ad_CandidateNativeInvalid("submitted POSCAR and vasprun initialpos fractional geometry differ")
    return {"status": "SUBMITTED_PARENT_POSCAR_MATCHES_VASPRUN_INITIALPOS",
            "scope": "response reference geometry only; finalpos remains separate observed output",
            "max_lattice_abs_difference_angstrom": max_lattice,
            "max_fractional_difference_modulo_lattice": max_fractional,
            "poscar_sha256": poscar["native_sha256"],
            "xml_sha256": initial["native_sha256"],
            "poscar_pointer": poscar["raw_pointer"],
            "xml_pointer": initial["raw_pointer"],
            "manifest_source_poscar_sha256": manifest["source_poscar_sha256"],
            "manifest_parent_geometry_sha256": manifest["parent_geometry_sha256"]}

def ad__xml_observations(xml_bytes: bytes, xml_hash: str,
                      input_keys: set[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        root = ET.fromstring(xml_bytes)
    except (ET.ParseError, ValueError) as exc:
        raise ad_CandidateNativeInvalid(f"malformed vasprun.xml: {exc}") from exc
    if root.tag != "modeling":
        raise ad_EnvironmentInvalid("unsupported vasprun.xml root (parser capability gap)")
    generator = root.find("./generator")
    if generator is None:
        raise ad_CandidateNativeInvalid("vasprun.xml lacks generator metadata")
    prog = ad__child_named(generator, "i", "program").text or ""
    version = ad__child_named(generator, "i", "version").text or ""
    if "vasp" not in prog.lower():
        raise ad_EnvironmentInvalid("native XML is not a recognized VASP source")
    final = [s for s in root.findall("./structure") if s.get("name") == "finalpos"]
    if len(final) != 1:
        raise ad_CandidateNativeInvalid(f"expected one finalpos structure; found {len(final)}")
    structure = final[0]
    crystal = structure.find("./crystal")
    if crystal is None:
        raise ad_CandidateNativeInvalid("finalpos lacks crystal")
    basis_node = ad__child_named(crystal, "varray", "basis")
    lattice = ad__vector_rows(basis_node, 3, "finalpos/basis")
    vol_node = ad__child_named(crystal, "i", "volume")
    volume = ad__parse_float(vol_node.text or "", "finalpos/volume")
    if volume <= 0:
        raise ad_CandidateNativeInvalid("finalpos volume must be positive")
    positions_node = ad__child_named(structure, "varray", "positions")
    positions = []
    for idx, row in enumerate(positions_node.findall("./v")):
        fields = (row.text or "").split()
        if len(fields) != 3:
            raise ad_CandidateNativeInvalid(f"finalpos/positions[{idx}] malformed")
        positions.append([ad__parse_float(x, f"finalpos/positions[{idx}]") for x in fields])
    atom_array = root.find("./atominfo/array[@name='atoms']/set")
    if atom_array is None:
        raise ad_CandidateNativeInvalid("vasprun.xml lacks atom species table")
    species = []
    for idx, row in enumerate(atom_array.findall("./rc")):
        cols = row.findall("./c")
        if len(cols) < 1 or not (cols[0].text or "").strip():
            raise ad_CandidateNativeInvalid(f"atom species row {idx} malformed")
        species.append((cols[0].text or "").strip())
    if not species or len(species) != len(positions):
        raise ad_CandidateNativeInvalid("finalpos site/species counts do not agree")
    initial_structure = ad__structure_from_xml(root, "initialpos", species, xml_hash)
    observations: list[dict[str, Any]] = []

    def add(field: str, value: Any, units: str, pointer: str, frame: str | None = None) -> None:
        item: dict[str, Any] = {"field": field, "value": value, "units": units,
                                "native_sha256": xml_hash, "raw_pointer": pointer}
        if frame is not None:
            item["frame"] = frame
        observations.append(item)

    add("structure.lattice", lattice, "angstrom", "/modeling/structure[@name='finalpos']/crystal/varray[@name='basis']", "Cartesian lattice vectors as rows")
    add("structure.volume", volume, "angstrom^3", "/modeling/structure[@name='finalpos']/crystal/i[@name='volume']")
    add("structure.species_order", species, "element labels", "/modeling/atominfo/array[@name='atoms']")
    add("structure.fractional_positions", positions, "fractional", "/modeling/structure[@name='finalpos']/varray[@name='positions']", "fractional coordinates in finalpos cell")
    if initial_structure is not None:
        add("structure.initial_lattice", initial_structure["lattice"], "angstrom",
            initial_structure["raw_pointer"]["lattice"], "Cartesian lattice vectors as rows")
        add("structure.initial_fractional_positions", initial_structure["fractional_positions"],
            "fractional", initial_structure["raw_pointer"]["positions"],
            "fractional coordinates in initialpos cell")
    add("structure.final_fractional_positions", positions, "fractional",
        "/modeling/structure[@name='finalpos']/varray[@name='positions']",
        "finalpos output coordinates; not the response parent geometry")

    klist = root.findall("./kpoints/varray[@name='kpointlist']/v")
    if not klist:
        raise ad_CandidateNativeInvalid("vasprun.xml lacks kpointlist")
    kpoints = []
    kpoint_tokens = []
    for idx, row in enumerate(klist):
        fields = (row.text or "").split()
        if len(fields) != 3:
            raise ad_CandidateNativeInvalid(f"kpointlist[{idx}] malformed")
        kpoints.append([ad__parse_float(x, f"kpoint[{idx}]") for x in fields])
        kpoint_tokens.append(fields)
    calculations = root.findall("./calculation")
    if not calculations:
        raise ad_CandidateNativeInvalid("vasprun.xml has no calculation history")
    for calc_index, calculation in enumerate(calculations):
        if len(calculation.findall("./eigenvalues")) > 1:
            raise ad_CandidateNativeInvalid(f"calculation[{calc_index + 1}] repeats eigenvalues arrays")
    final_eigs = calculations[-1].findall("./eigenvalues")
    if len(final_eigs) != 1:
        raise ad_CandidateNativeInvalid("final calculation must contain exactly one eigenvalues array")
    eig_index = len(calculations)  # XPath element indices are one-based.
    eig_node = final_eigs[0]
    eig_root = eig_node.find("./array/set")
    if eig_root is None:
        raise ad_CandidateNativeInvalid("eigenvalues array has no spin sets")
    spins: list[list[list[tuple[float, float]]]] = []
    energy_tokens_by_spin: list[list[list[str]]] = []
    occupation_tokens_by_spin: list[list[list[str]]] = []
    for si, spinset in enumerate(eig_root.findall("./set")):
        spin_rows: list[list[tuple[float, float]]] = []
        spin_energy_tokens: list[list[str]] = []
        spin_occupation_tokens: list[list[str]] = []
        for ki, kset in enumerate(spinset.findall("./set")):
            rows = []
            energy_tokens = []
            occupation_tokens = []
            for bi, row in enumerate(kset.findall("./r")):
                fields = (row.text or "").split()
                if len(fields) != 2:
                    raise ad_CandidateNativeInvalid(f"eigenvalue row spin={si},k={ki},band={bi} malformed")
                energy = ad__parse_float(fields[0], "eigenvalue")
                occ = ad__parse_float(fields[1], "occupation")
                if occ < 0 or occ > 1:
                    raise ad_CandidateNativeInvalid("VASP occupation lies outside [0,1]")
                rows.append((energy, occ))
                energy_tokens.append(fields[0])
                occupation_tokens.append(fields[1])
            if not rows:
                raise ad_CandidateNativeInvalid("empty eigenvalue k-point set")
            spin_rows.append(rows)
            spin_energy_tokens.append(energy_tokens)
            spin_occupation_tokens.append(occupation_tokens)
        if spin_rows:
            spins.append(spin_rows)
            energy_tokens_by_spin.append(spin_energy_tokens)
            occupation_tokens_by_spin.append(spin_occupation_tokens)
    if not spins or any(len(s) != len(kpoints) for s in spins):
        raise ad_CandidateNativeInvalid("eigenvalue spin/k-point dimensions do not match kpointlist")
    band_counts = {len(rows) for spin in spins for rows in spin}
    if len(band_counts) != 1:
        raise ad_CandidateNativeInvalid("inconsistent eigenvalue band counts")
    fractionals = [(si, ki, bi, occ) for si, spin in enumerate(spins) for ki, bands in enumerate(spin)
                   for bi, (_, occ) in enumerate(bands) if occ not in (0.0, 1.0)]
    eig_pointer = f"/modeling/calculation[{eig_index}]/eigenvalues/array/set"
    gamma_indices = [idx for idx, point in enumerate(kpoints)
                     if all(abs(value - round(value)) <= 1e-10 for value in point)]
    gamma_value = None
    gamma_availability = "NOT_OBSERVED_NO_GAMMA_POINT"
    gamma_pointer: dict[str, Any] = {"kpointlist_entries": [], "eigenvalue_spectrum": eig_pointer}
    if len(gamma_indices) == 1:
        gamma_index = gamma_indices[0]
        gamma_pointer["kpointlist_entries"] = [
            f"/modeling/kpoints/varray[@name='kpointlist']/v[{gamma_index + 1}]"
        ]
        gamma_value = {
            "kpoint_index_0based": gamma_index,
            "fractional_coordinates": kpoints[gamma_index],
            "fractional_coordinate_tokens": kpoint_tokens[gamma_index],
            "spins": [{
                "spin_index_0based": spin_index,
                "bands": [{
                    "band_index_0based": band_index,
                    "band_index_1based": band_index + 1,
                    "energy_eV": values[gamma_index][band_index][0],
                    "energy_token_eV": energy_tokens_by_spin[spin_index][gamma_index][band_index],
                    "occupation": values[gamma_index][band_index][1],
                    "occupation_token": occupation_tokens_by_spin[spin_index][gamma_index][band_index],
                } for band_index in range(len(values[gamma_index]))],
            } for spin_index, values in enumerate(spins)]
        }
        gamma_availability = "OBSERVED_UNIQUE_GAMMA"
        gamma_pointer["spin_kpoint_spectra"] = [
            f"{eig_pointer}/set[{spin_index + 1}]/set[{gamma_index + 1}]"
            for spin_index in range(len(spins))
        ]
    elif len(gamma_indices) > 1:
        gamma_availability = "UNSUPPORTED_MULTIPLE_GAMMA_EQUIVALENTS"
        gamma_pointer["kpointlist_entries"] = [
            f"/modeling/kpoints/varray[@name='kpointlist']/v[{idx + 1}]"
            for idx in gamma_indices
        ]
    observations.append({
        "field": "band.gamma_spectrum", "value": gamma_value,
        "units": "eV and electron/state",
        "frame": "all native spin channels and bands at unique Gamma modulo reciprocal lattice vectors",
        "native_sha256": xml_hash, "raw_pointer": gamma_pointer,
        "availability": gamma_availability,
    })
    if fractionals:
        add("band.fundamental_gap", None, "eV", eig_pointer,
            "UNKNOWN: fractional occupations are neither fully occupied nor empty")
        add("band.direct_gap", None, "eV", eig_pointer,
            "UNKNOWN: fractional occupations are neither fully occupied nor empty")
        add("band.vbm", None, "eV", eig_pointer,
            "UNKNOWN: fractional occupations are neither fully occupied nor empty")
        add("band.cbm", None, "eV", eig_pointer,
            "UNKNOWN: fractional occupations are neither fully occupied nor empty")
    else:
        occupied = [(e, s, k, b, o) for s, spin in enumerate(spins) for k, bands in enumerate(spin)
                    for b, (e, o) in enumerate(bands) if o == 1.0]
        empty = [(e, s, k, b, o) for s, spin in enumerate(spins) for k, bands in enumerate(spin)
                 for b, (e, o) in enumerate(bands) if o == 0.0]
        if not occupied or not empty:
            raise ad_CandidateNativeInvalid("cannot identify fully occupied and empty eigenvalue states")
        vbm = max(occupied, key=lambda x: x[0])
        cbm = min(empty, key=lambda x: x[0])
        fundamental = ad__finite(cbm[0] - vbm[0], "fundamental gap")
        direct_candidates = []
        for si, spin in enumerate(spins):
            for ki, bands in enumerate(spin):
                occ_e = [e for e, o in bands if o == 1.0]
                emp_e = [e for e, o in bands if o == 0.0]
                if occ_e and emp_e:
                    direct_candidates.append((min(emp_e) - max(occ_e), si, ki))
        if not direct_candidates:
            raise ad_CandidateNativeInvalid("no same-k fully occupied/empty state pairs")
        direct = min(direct_candidates)
        add("band.fundamental_gap", fundamental, "eV", eig_pointer)
        add("band.direct_gap", ad__finite(direct[0], "direct gap"), "eV", eig_pointer + " (same-k, same-spin extrema)")
        add("band.vbm", {"energy_ev": vbm[0], "spin_index_0based": vbm[1], "kpoint_index_0based": vbm[2], "band_index_0based": vbm[3], "occupation": vbm[4]}, "eV", eig_pointer)
        add("band.cbm", {"energy_ev": cbm[0], "spin_index_0based": cbm[1], "kpoint_index_0based": cbm[2], "band_index_0based": cbm[3], "occupation": cbm[4]}, "eV", eig_pointer)
    add("band.occupations", {"spin_count": len(spins), "kpoint_count": len(kpoints), "band_count": next(iter(band_counts)), "fractional_state_count": len(fractionals), "fractional_state_indices": [list(x[:3]) for x in fractionals]}, "electron per state", eig_pointer)
    response_obs, response_meta = ad__xml_response_observations(calculations, species, xml_hash)
    observations.extend(response_obs)
    incar_node = root.find("./incar")
    xml_incar = {}
    xml_incar_types: dict[str, str | None] = {}
    xml_incar_element_tags: dict[str, str] = {}
    if incar_node is not None:
        for node in list(incar_node.findall("./i")) + list(incar_node.findall("./v")):
            key = node.get("name", "").upper()
            if key in xml_incar:
                raise ad_CandidateNativeInvalid(f"duplicate vasprun INCAR tag {key}")
            xml_incar[key] = (node.text or "").strip()
            xml_incar_types[key] = node.get("type")
            xml_incar_element_tags[key] = node.tag
    effective_parameters: dict[str, tuple[str, str | None]] = {}
    effective_parameter_pointers: dict[str, str] = {}
    consistency_keys = set(xml_incar) | set(input_keys or ()) | ad_CONSISTENCY_TAGS
    for separator in root.findall("./parameters/separator"):
        separator_name = separator.get("name", "")
        for node in list(separator.findall("./i")) + list(separator.findall("./v")):
            key = node.get("name", "").upper()
            if not key or key not in consistency_keys:
                continue
            if key in effective_parameters:
                raise ad_CandidateNativeInvalid(f"duplicate effective parameter {key} in vasprun.xml")
            effective_parameters[key] = ((node.text or "").strip(), node.get("type"))
            element_tag = node.tag
            effective_parameter_pointers[key] = (
                f"/modeling/parameters/separator[@name='{separator_name}']/"
                f"{element_tag}[@name='{key}']")
    for source_name, source in (("vasprun.xml/incar", xml_incar_types),
                                ("vasprun.xml/parameters", {key: pair[1] for key, pair in effective_parameters.items()})):
        for key, required_type in ad__REQUIRED_XML_TYPES.items():
            if key in source:
                declared = source[key]
                allowed = {"int", "integer"} if required_type == "int" else {required_type}
                if declared is None or declared.lower() not in allowed:
                    raise ad_CandidateNativeInvalid(
                        f"{source_name} {key} must declare XML type {required_type}"
                    )
    effective_lepsilon_value = effective_parameters.get("LEPSILON", (None, None))[0]
    convergence = {"electronic": "UNKNOWN", "ionic": "NOT_RUN_OR_UNKNOWN", "ediff_marker_count": 0,
                   "warning_markers": []}
    if xml_incar.get("NSW") == "0":
        convergence["ionic"] = "NOT_RUN_BY_NSW_ZERO"
    return observations, {"vasp_version": version.strip(), "xml_incar": xml_incar,
                          "xml_incar_types": xml_incar_types,
                          "effective_parameters": effective_parameters,
                          "effective_parameter_pointers": effective_parameter_pointers,
                          "xml_parameter_sources": {
                              "incar": {key: {"raw": raw, "declared_type": xml_incar_types[key],
                                              "raw_pointer": f"/modeling/incar/{xml_incar_element_tags[key]}[@name='{key}']"}
                                        for key, raw in xml_incar.items()},
                              "parameters": {key: {"raw": raw, "declared_type": declared,
                                                   "raw_pointer": effective_parameter_pointers[key]}
                                             for key, (raw, declared) in effective_parameters.items()},
                          },
                          "effective_lepsilon": effective_lepsilon_value,
                          "response": response_meta,
                          "initial_structure": initial_structure,
                          "kpoint_count": len(kpoints), "spin_count": len(spins),
                          "band_count": next(iter(band_counts)), "convergence": convergence}

def ad__parse_incar_value(key: str, pair: tuple[str, str]) -> Any:
    raw, loc = pair
    if raw.upper() in ("T", ".TRUE.", "TRUE"):
        return True
    if raw.upper() in ("F", ".FALSE.", "FALSE"):
        return False
    if ad_NUMBER.fullmatch(raw):
        return ad__parse_float(raw, loc, native=True)
    if "," in raw or " " in raw:
        # Keep unparsed vector/array values explicit rather than coercing them.
        return raw
    return raw.strip('"\'')

def ad__logical_lexeme(raw: str, where: str) -> bool:
    value = raw.strip().upper()
    if value in ("T", ".TRUE.", "TRUE"):
        return True
    if value in ("F", ".FALSE.", "FALSE"):
        return False
    raise ad_CandidateNativeInvalid(f"{where} is not a supported logical lexeme")

ad__LOGICAL_TAGS = {"LEPSILON", "LHFCALC", "LSORBIT", "LNONCOLLINEAR",
                 "ADDGRID", "LASPH", "LWAVE", "LCHARG", "LUSE_VDW", "LPEAD"}

ad__INTEGER_TAGS = {"NSW", "IBRION", "ISPIN", "NELM", "NBANDS", "ISMEAR", "ICHARG",
                 "ISYM", "NCORE", "KPAR"}

ad__REQUIRED_XML_TYPES = {"LEPSILON": "logical", "LPEAD": "logical", "NSW": "int"}

def ad__xml_response_observations(calculations: list[ET.Element], species: list[str],
                               xml_hash: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read response arrays only from the unique final calculation structure."""
    names = ("epsilon", "epsilon_ion", "born_charges")
    found_by_calc: list[dict[str, list[ET.Element]]] = []
    for calc in calculations:
        entry = {name: [node for node in calc.iter() if node.get("name") == name]
                 for name in names}
        found_by_calc.append(entry)
    final_index = len(calculations)
    final = found_by_calc[-1]
    for index, entry in enumerate(found_by_calc[:-1], 1):
        if any(entry[name] for name in names):
            raise ad_CandidateNativeInvalid(
                f"response arrays occur outside the unique final calculation at calculation[{index}]"
            )
    totals = {name: sum(len(entry[name]) for entry in found_by_calc) for name in names}
    if not any(totals.values()):
        return [], {"epsilon_high": None, "epsilon_ionic": None,
                    "born_effective_charges": None, "response_source_pointer": None}
    for name in names:
        if totals[name] != 1 or len(final[name]) != 1:
            raise ad_CandidateNativeInvalid(
                f"final calculation must contain exactly one {name}; found {len(final[name])}"
            )

    def matrix(node: ET.Element, where: str) -> list[list[float]]:
        rows = node.findall("./v")
        if len(rows) != 3:
            raise ad_CandidateNativeInvalid(f"{where} must contain exactly 3 rows")
        result = []
        for ri, row in enumerate(rows):
            fields = (row.text or "").split()
            if len(fields) != 3:
                raise ad_CandidateNativeInvalid(f"{where}[{ri}] must contain exactly 3 values")
            result.append([ad__parse_float(x, f"{where}[{ri}]") for x in fields])
        return result

    high_node, ionic_node, born_node = (final[name][0] for name in names)
    expected_tags = {"epsilon": "varray", "epsilon_ion": "varray", "born_charges": "array"}
    for name, node in zip(names, (high_node, ionic_node, born_node)):
        if node.tag != expected_tags[name] or node not in calculations[-1]:
            raise ad_CandidateNativeInvalid(
                f"final calculation {name} must be a direct {expected_tags[name]} child"
            )
    high = matrix(high_node, "final calculation epsilon")
    ionic = matrix(ionic_node, "final calculation epsilon_ion")
    dimensions = born_node.findall("./dimension")
    sets = born_node.findall("./set")
    if len(dimensions) != 1 or (dimensions[0].text or "").strip().lower() != "ion":
        raise ad_CandidateNativeInvalid("born_charges must declare one ion dimension")
    if len(sets) != len(species) or not species:
        raise ad_CandidateNativeInvalid("born_charges set count does not match finalpos atom count")
    born: list[list[list[float]]] = []
    for atom, node in enumerate(sets):
        born.append(matrix(node, f"final calculation born_charges ion[{atom + 1}]"))
    base = f"/modeling/calculation[{final_index}]"
    rows = [
        {"field": "dielectric.epsilon_high_xml", "value": high, "units": "dimensionless",
         "frame": "Cartesian x,y,z", "native_sha256": xml_hash,
         "raw_pointer": base + "/varray[@name='epsilon']"},
        {"field": "dielectric.epsilon_ionic_xml", "value": ionic, "units": "dimensionless",
         "frame": "Cartesian x,y,z", "native_sha256": xml_hash,
         "raw_pointer": base + "/varray[@name='epsilon_ion']"},
        {"field": "born.effective_charges_xml", "value": born, "units": "|e|",
         "frame": "atom-major, Cartesian polarization/displacement axes; atom order follows finalpos",
         "species_order": list(species), "native_sha256": xml_hash,
         "raw_pointer": base + "/array[@name='born_charges']/set"},
    ]
    return rows, {"epsilon_high": high, "epsilon_ionic": ionic,
                  "born_effective_charges": born,
                  "response_source_pointer": base}

def ad__normalized_tag(key: str, raw: str, declared_type: str | None, where: str) -> Any:
    value = raw.strip()
    kind = declared_type.lower() if declared_type else None
    if kind not in (None, "logical", "int", "integer", "float", "double", "string"):
        raise ad_CandidateNativeInvalid(f"unsupported XML type {declared_type!r} for {key} at {where}")
    if key == "LREAL":
        if kind == "logical":
            return ad__logical_lexeme(value, f"{where} {key}")
        if kind not in (None, "string"):
            raise ad_CandidateNativeInvalid(f"unsupported XML type {declared_type!r} for LREAL at {where}")
        token = value.strip('"\'').upper()
        if token in ("T", ".TRUE.", "TRUE"):
            return True
        if token in ("F", ".FALSE.", "FALSE"):
            return False
        if token in ("AUTO", "A"):
            return "AUTO"
        if token in ("ON", "O"):
            return "ON"
        raise ad_CandidateNativeInvalid(f"{where} LREAL has an unsupported mode lexeme")
    if kind == "logical" or (kind is None and key in ad__LOGICAL_TAGS):
        return ad__logical_lexeme(value, f"{where} {key}")
    if kind in ("int", "integer") or (kind is None and key in ad__INTEGER_TAGS):
        number = ad__parse_float(value, f"{where} {key}")
        if not number.is_integer():
            raise ad_CandidateNativeInvalid(f"{where} {key} must be an integer lexeme")
        return int(number)
    if kind in ("float", "double") or ad_NUMBER.fullmatch(value):
        return ad__parse_float(value, f"{where} {key}")
    if kind == "string" or kind is None:
        parts = value.split()
        if len(parts) > 1 and all(ad_NUMBER.fullmatch(part) for part in parts):
            return tuple(ad__parse_float(part, f"{where} {key}") for part in parts)
        normalized = value.strip('"\'').upper()
        # VASP serializes PREC=Accurate as the effective token "accura".
        if key == "PREC" and normalized == "ACCURA":
            normalized = "ACCURATE"
        return normalized
    raise ad_CandidateNativeInvalid(f"unsupported value for {key} at {where}")

def ad__proven_ibrion6_nsw_expansion(layers: dict[str, dict[str, tuple[str, str | None]]],
                                  manifest: dict[str, Any], receipt: dict[str, Any],
                                  xml_parameter_pointers: dict[str, str],
                                  incar_sources: dict[str, str]) -> dict[str, Any] | None:
    """Recognize only the reviewed IBRION=6 submitted/effective NSW transition."""
    if not (manifest.get("case_id") == "case-05-first-principles-inputs" and
            receipt.get("case_id") == manifest.get("case_id") and
            manifest.get("stage") == "03_elastic_pbe" and
            manifest.get("stage_kind") == "elastic" and
            receipt.get("stage") == manifest.get("stage") and
            receipt.get("status") == "FINISHED" and receipt.get("exit_code") == 0):
        return None
    observed: dict[str, dict[str, Any]] = {}
    for layer in ("INCAR", "vasprun.xml/incar", "vasprun.xml/parameters"):
        entries = layers[layer]
        if "NSW" not in entries or "IBRION" not in entries:
            raise ad_CandidateNativeInvalid(f"elastic IBRION=6 run lacks NSW/IBRION in {layer}")
        nsw_raw, nsw_type = entries["NSW"]
        ibrion_raw, ibrion_type = entries["IBRION"]
        observed[layer] = {
            "NSW": ad__normalized_tag("NSW", nsw_raw, nsw_type, layer),
            "IBRION": ad__normalized_tag("IBRION", ibrion_raw, ibrion_type, layer),
        }
    if any(observed[layer]["IBRION"] != 6 for layer in observed):
        raise ad_CandidateNativeInvalid("elastic IBRION layer values differ from the reviewed IBRION=6 profile")
    if (observed["INCAR"]["NSW"] != 1 or observed["vasprun.xml/incar"]["NSW"] != 1 or
            observed["vasprun.xml/parameters"]["NSW"] != 61):
        raise ad_CandidateNativeInvalid("elastic NSW layers differ from the reviewed 1/1/61 IBRION=6 profile")
    return {"status": "AUTHORIZED_IBRION6_EFFECTIVE_NSW_EXPANSION_OBSERVED",
            "submitted_nsw": 1,
            "xml_incar_nsw": 1,
            "xml_effective_nsw": 61,
            "ibrion": 6,
            "sources": {
                "INCAR": {key: incar_sources[key] for key in ("NSW", "IBRION")},
                "vasprun.xml/incar": {
                    key: f"/modeling/incar/i[@name='{key}']" for key in ("NSW", "IBRION")},
                "vasprun.xml/parameters": {
                    key: xml_parameter_pointers[key] for key in ("NSW", "IBRION")},
            },
            "interpretation": "effective NSW is retained as an engine parameter; it is not a count of executed ionic steps and does not qualify ionic convergence"}

def ad__compare_printed_tensors(label: str, xml_value: Any, outcar_value: Any,
                             outcar_quantum: float) -> dict[str, Any]:
    def flatten(value: Any) -> list[float]:
        if type(value) not in (list, tuple):
            raise ad_CandidateNativeInvalid(f"{label} tensor shape mismatch")
        if value and type(value[0]) in (list, tuple):
            return [item for row in value for item in flatten(row)]
        return [ad__finite(float(item), label) for item in value]
    left, right = flatten(xml_value), flatten(outcar_value)
    if len(left) != len(right) or not left:
        raise ad_CandidateNativeInvalid(f"{label} XML/OUTCAR tensor shape mismatch")
    delta = max(abs(a - b) for a, b in zip(left, right))
    tolerance = outcar_quantum / 2.0 + 5e-9  # XML values are printed to 8 decimals.
    if delta > tolerance:
        raise ad_CandidateNativeInvalid(f"{label} XML/OUTCAR values conflict beyond native print precision")
    return {"status": "MATCH_WITHIN_NATIVE_PRINT_PRECISION", "max_abs_difference": delta,
            "absolute_tolerance": tolerance, "outcar_print_quantum": outcar_quantum}

def ad__parse_tensor_section(text: str, title: str, units: str, sha: str,
                          kind: str) -> dict[str, Any] | None:
    matches = list(re.finditer(rf"(?im)^[ \t]*{re.escape(title)}[ \t]*$", text))
    if len(matches) > 1:
        raise ad_CandidateNativeInvalid(f"duplicate native {title} sections")
    if not matches:
        return None
    pos = matches[0].end()
    lines = text[pos:].splitlines()
    rows: list[list[float]] = []
    pointer = None
    heading_line = text.count("\n", 0, matches[0].start()) + 1
    # The supported VASP text form is three lines with exactly three numbers.
    num = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
    row_re = re.compile(rf"^\s*({num})\s+({num})\s+({num})\s*$")
    for off, line in enumerate(lines[:8], 1):
        if not line.strip() or re.fullmatch(r"\s*-+\s*", line):
            continue
        m = row_re.fullmatch(line)
        if not m:
            raise ad_CandidateNativeInvalid(f"malformed {title} tensor row {len(rows)+1}")
        rows.append([ad__parse_float(x, f"{title} row {len(rows)+1}") for x in m.groups()])
        if len(rows) == 3:
            pointer = f"OUTCAR:{heading_line + off}"
            break
    if len(rows) != 3:
        raise ad_CandidateNativeInvalid(f"unrecognized {title} tensor format")
    return {"kind": kind, "tensor": rows, "units": units,
            "frame": "Cartesian x,y,z", "native_sha256": sha,
            "raw_pointer": {"section": title, "relative_line": pointer}}

def ad__tensor_at(text: str, match: re.Match[str], title: str, sha: str,
               kind: str) -> dict[str, Any]:
    pos = match.end()
    lines = text[pos:].splitlines()
    rows: list[list[float]] = []
    heading_line = text.count("\n", 0, match.start()) + 1
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
    row_re = re.compile(rf"^\s*({number})\s+({number})\s+({number})\s*$")
    for offset, line in enumerate(lines[:8], 1):
        if not line.strip() or re.fullmatch(r"\s*-+\s*", line):
            continue
        parsed = row_re.fullmatch(line)
        if not parsed:
            raise ad_CandidateNativeInvalid(f"malformed {title} tensor row {len(rows) + 1}")
        rows.append([ad__parse_float(item, f"{title} row {len(rows) + 1}")
                     for item in parsed.groups()])
        if len(rows) == 3:
            return {"kind": kind, "tensor": rows, "units": "dimensionless",
                    "frame": "Cartesian x,y,z", "native_sha256": sha,
                    "raw_pointer": {"section": title,
                                    "heading_line": heading_line,
                                    "row_lines": [heading_line + i - 1 for i in range(1, offset + 1)
                                                  if lines[i - 1].strip() and row_re.fullmatch(lines[i - 1])]}}
    raise ad_CandidateNativeInvalid(f"unrecognized {title} tensor format")

def ad__born_at(text: str, match: re.Match[str], sha: str,
             atom_count: int) -> dict[str, Any]:
    heading_line = text.count("\n", 0, match.start()) + 1
    tail_text = text[match.end():]
    boundary = re.search(r"(?im)^\s*INTERNAL STRAIN TENSOR FOR ION\s+\d+", tail_text)
    if boundary is None:
        raise ad_CandidateNativeInvalid("final OUTCAR Born block lacks following internal-strain phase boundary")
    tail = tail_text[:boundary.start()].splitlines()
    atom_headers = [(i, re.fullmatch(r"\s*ion\s+(\d+)\s*", line, re.I))
                    for i, line in enumerate(tail)]
    atom_headers = [(i, m) for i, m in atom_headers if m]
    if [int(m.group(1)) for _, m in atom_headers] != list(range(1, atom_count + 1)):
        raise ad_CandidateNativeInvalid("OUTCAR Born ion headers do not match finalpos atom order")
    born: list[list[list[float]]] = []
    row_re = re.compile(r"\s*(\d+)\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*")
    row_lines: list[list[int]] = []
    for atom_index, (start, _header) in enumerate(atom_headers, 1):
        stop = atom_headers[atom_index][0] if atom_index < atom_count else len(tail)
        rows: list[list[float]] = []
        line_refs: list[int] = []
        for offset in range(start + 1, stop):
            line = tail[offset]
            if not line.strip():
                continue
            parsed = row_re.fullmatch(line)
            if not parsed:
                # The next named section is the only allowed terminator.
                if len(rows) == 3 and re.match(r"\s*[A-Z][A-Z \-()]+", line):
                    break
                raise ad_CandidateNativeInvalid(f"malformed OUTCAR Born row for ion {atom_index}")
            row_index = int(parsed.group(1))
            if row_index != len(rows) + 1 or row_index > 3:
                raise ad_CandidateNativeInvalid(f"OUTCAR Born row index/order invalid for ion {atom_index}")
            rows.append([ad__parse_float(value, f"OUTCAR Born ion[{atom_index}]")
                         for value in parsed.groups()[1:]])
            line_refs.append(heading_line + offset)
        if len(rows) != 3:
            raise ad_CandidateNativeInvalid(f"OUTCAR Born tensor for ion {atom_index} is incomplete")
        born.append(rows)
        row_lines.append(line_refs)
    return {"kind": "born_effective_charges", "tensor": born, "units": "|e|",
            "frame": "atom-major, Cartesian polarization/displacement axes; finalpos atom order",
            "native_sha256": sha,
            "raw_pointer": {"section": "BORN EFFECTIVE CHARGES (including local field effects)",
                            "heading_line": heading_line, "row_lines": row_lines}}

def ad__final_dfpt_sections(text: str, sha: str, atom_count: int) -> dict[str, Any] | None:
    high_title = "MACROSCOPIC STATIC DIELECTRIC TENSOR (including local field effects in DFT)"
    ionic_title = "MACROSCOPIC STATIC DIELECTRIC TENSOR IONIC CONTRIBUTION"
    born_title = "BORN EFFECTIVE CHARGES (including local field effects) (in |e|, cummulative output)"
    highs = list(re.finditer(rf"(?im)^[ \t]*{re.escape(high_title)}[ \t]*$", text))
    borns = list(re.finditer(rf"(?im)^[ \t]*{re.escape(born_title)}[ \t]*$", text))
    ionics = list(re.finditer(rf"(?im)^[ \t]*{re.escape(ionic_title)}[ \t]*$", text))
    if not borns and not ionics:
        return None
    if len(borns) != 1 or len(ionics) != 1 or not highs:
        raise ad_CandidateNativeInvalid("DFPT final response must have unique electronic/Born/ionic headings")
    born_match, ionic_match = borns[0], ionics[0]
    if any(m.start() > born_match.start() for m in highs):
        raise ad_CandidateNativeInvalid("electronic dielectric heading occurs outside final response phase")
    eligible = [m for m in highs if m.start() < born_match.start()]
    if not eligible or not born_match.start() < ionic_match.start():
        raise ad_CandidateNativeInvalid("DFPT electronic/Born/ionic response order is incomplete")
    piezo_e = list(re.finditer(r"(?im)^[ \t]*PIEZOELECTRIC TENSOR \(including local field effects\)\s+for field in x, y, z\s+\(e\s+Angst\)[ \t]*$", text))
    piezo_c = list(re.finditer(r"(?im)^[ \t]*PIEZOELECTRIC TENSOR \(including local field effects\)\s+for field in x, y, z\s+\(C/m\^2\)[ \t]*$", text))
    internal = list(re.finditer(r"(?im)^[ \t]*INTERNAL STRAIN TENSOR FOR ION\s+(\d+)\b.*$", text))
    modes = list(re.finditer(r"(?im)^[ \t]*Eigenvectors and eigenvalues of the dynamical matrix[ \t]*$", text))
    candidates = []
    for high in eligible:
        following_e = [m for m in piezo_e if high.end() < m.start() < born_match.start()]
        following_c = [m for m in piezo_c if high.end() < m.start() < born_match.start()]
        # A final response phase is structurally identified by both named
        # piezoelectric summaries, the Born table, the internal-strain/mode
        # section, and the ionic tensor in that order. A prior high tensor
        # heading followed by a new linear-response calculation is not enough.
        if len(following_e) == 1 and len(following_c) == 1:
            e, c = following_e[0], following_c[0]
            if not high.start() < e.start() < c.start() < born_match.start():
                continue
            if any(high.start() < other.start() < born_match.start() for other in highs):
                continue
            after_internal = [m for m in internal if born_match.end() < m.start() < ionic_match.start()]
            after_modes = [m for m in modes if born_match.end() < m.start() < ionic_match.start()]
            if (len(internal) == atom_count and
                    [int(m.group(1)) for m in internal] == list(range(1, atom_count + 1)) and
                    len(after_internal) == atom_count and
                    len(after_modes) == 1 and
                    all(m.start() < after_modes[0].start() for m in after_internal)):
                candidates.append(high)
    if len(candidates) != 1:
        raise ad_CandidateNativeInvalid("final DFPT electronic/Born/ionic phase anchor is absent or ambiguous")
    high_match = candidates[0]
    high = ad__tensor_at(text, high_match, high_title, sha, "epsilon_high")
    ionic = ad__tensor_at(text, ionic_match, ionic_title, sha, "epsilon_ionic")
    born = ad__born_at(text, born_match, sha, atom_count)
    return {"epsilon_high": high, "epsilon_ionic": ionic, "born_effective_charges": born,
            "ordered_phase": ["electronic_dielectric", "born_effective_charges", "ionic_dielectric"]}

def ad__parse_elastic_section(text: str, title: str, sha: str, kind: str) -> dict[str, Any] | None:
    starts = list(re.finditer(rf"(?im)^[ \t]*{re.escape(title)}[ \t]*$", text))
    if len(starts) > 1:
        raise ad_CandidateNativeInvalid(f"duplicate native {title} sections")
    if not starts:
        return None
    labels = ("XX", "YY", "ZZ", "XY", "YZ", "ZX")
    heading_line = text.count("\n", 0, starts[0].start()) + 1
    tail = text[starts[0].end():].splitlines()
    dir_re = re.compile(r"^\s*Direction\s+(XX\s+YY\s+ZZ\s+XY\s+YZ\s+ZX)\s*$", re.I)
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
    row_re = re.compile(rf"^\s*(XX|YY|ZZ|XY|YZ|ZX)\s+({number})\s+({number})\s+({number})\s+({number})\s+({number})\s+({number})\s*$", re.I)
    direction = None
    rows: dict[str, list[float]] = {}
    row_lines: dict[str, int] = {}
    for offset, line in enumerate(tail[:20], 1):
        dm = dir_re.fullmatch(line)
        if dm:
            direction = tuple(dm.group(1).upper().split())
            if direction != labels:
                raise ad_CandidateNativeInvalid(f"unexpected elastic column order {direction}")
            continue
        rm = row_re.fullmatch(line)
        if rm:
            label = rm.group(1).upper()
            if label in rows:
                raise ad_CandidateNativeInvalid(f"duplicate elastic row {label}")
            rows[label] = [ad__parse_float(x, f"{title}:{label}") for x in rm.groups()[1:]]
            row_lines[label] = heading_line + offset - 1
            continue
        if rows and line.strip() and not line.strip().startswith("-"):
            break
    if direction is None or tuple(rows) != labels:
        raise ad_CandidateNativeInvalid(f"incomplete or unrecognized {title} 6x6 table")
    return {"kind": kind, "tensor": [rows[label] for label in labels], "units": "kBar",
            "native_sha256": sha, "raw_pointer": {"section": title,
            "heading_line": heading_line, "row_lines": row_lines,
            "native_voigt_order": list(labels)}}

def ad__outcar_observations(data: bytes, sha: str, incar: dict[str, tuple[str, str]],
                         atom_count: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        text = data.decode("ascii")
    except UnicodeError as exc:
        raise ad_CandidateNativeInvalid("OUTCAR is not ASCII in the supported parser") from exc
    observations: list[dict[str, Any]] = []
    warnings = []
    reached = list(re.finditer(r"(?im)^\s*-+\s*aborting loop because EDIFF is reached\s*-+\s*$", text))
    not_reached = list(re.finditer(r"(?im)^\s*(?:WARNING:.*EDIFF.*not reached|reached NELM.*without reaching EDIFF).*?$", text))
    if reached and not_reached:
        state = "CONFLICTING_NATIVE_CONVERGENCE_MARKERS"
        warnings.extend({"kind": "EDIFF_REACHED", "line": text.count("\n", 0, m.start()) + 1} for m in reached)
        warnings.extend({"kind": "EDIFF_NOT_REACHED_OR_NELM", "line": text.count("\n", 0, m.start()) + 1} for m in not_reached)
    elif reached:
        state = "EDIFF_REACHED_MARKER_OBSERVED"
        warnings.extend({"kind": "EDIFF_REACHED", "line": text.count("\n", 0, m.start()) + 1} for m in reached)
    elif not_reached:
        state = "NELM_OR_EDIFF_WARNING_OBSERVED"
        warnings.extend({"kind": "EDIFF_NOT_REACHED_OR_NELM", "line": text.count("\n", 0, m.start()) + 1} for m in not_reached)
    else:
        state = "NO_RECOGNIZED_ELECTRONIC_TERMINATION_MARKER"
    observations.append({"field": "convergence.electronic_termination_observation", "value": state,
                         "units": "categorical observation", "native_sha256": sha,
                         "raw_pointer": warnings})
    stress = ad__force_on_cell_stress(text, sha)
    observations.append({"field": "stress.force_on_cell", "value": stress["value"],
                         "units": "kBar", "frame": "native VASP XX YY ZZ XY YZ ZX; compressive positive",
                         "native_sha256": sha, "raw_pointer": stress["raw_pointer"],
                         "native_tokens": stress["tokens"], "availability": stress["availability"]})
    ionic_relaxation = ad__ionic_relaxation_termination(text, sha, incar)
    observations.append({"field": "convergence.ionic_relaxation_termination",
                         "value": ionic_relaxation["value"], "units": "categorical observation",
                         "native_sha256": sha, "raw_pointer": ionic_relaxation["raw_pointer"],
                         "availability": ionic_relaxation["availability"]})
    # Parse only section names that unambiguously distinguish total and
    # clamped-ion elastic responses. No tensor stability/comparison is done.
    for title, label in (("TOTAL ELASTIC MODULI (kBar)", "relaxed_ion_total"),
                         ("ELASTIC MODULI (kBar)", "unqualified_or_clamped_native")):
        parsed = ad__parse_elastic_section(text, title, sha, label)
        if parsed is not None:
            matrix = parsed["tensor"]
            public_order = (0, 1, 2, 4, 5, 3)  # VASP XX YY ZZ XY YZ ZX -> XX YY ZZ YZ ZX XY
            reordered = [[matrix[i][j] for j in public_order] for i in public_order]
            gpa = [[ad__finite(x * 0.1, f"elastic {label}") for x in row] for row in reordered]
            observations.append({"field": f"elastic.{label}", "value": gpa, "units": "GPa",
                                 "frame": "Cartesian engineering Voigt [xx,yy,zz,yz,xz,xy]",
                                 "native_sha256": sha, "raw_pointer": parsed["raw_pointer"],
                                 "native_units": "kBar", "conversion": "0.1 GPa/kBar"})
    dielectric = []
    final_response = ad__final_dfpt_sections(text, sha, atom_count) if atom_count is not None else None
    if final_response is not None:
        for label in ("epsilon_high", "epsilon_ionic"):
            parsed = final_response[label]
            dielectric.append(parsed)
            observations.append({"field": f"dielectric.{label}", "value": parsed["tensor"],
                                 "units": "dimensionless", "frame": parsed["frame"],
                                 "native_sha256": sha, "raw_pointer": parsed["raw_pointer"]})
        parsed_born = final_response["born_effective_charges"]
        observations.append({"field": "born.effective_charges_outcar", "value": parsed_born["tensor"],
                             "units": "|e|", "frame": parsed_born["frame"],
                             "native_sha256": sha, "raw_pointer": parsed_born["raw_pointer"]})
    else:
        for title, label in (("MACROSCOPIC STATIC DIELECTRIC TENSOR (including local field effects in DFT)", "epsilon_high"),
                             ("MACROSCOPIC STATIC DIELECTRIC TENSOR IONIC CONTRIBUTION", "epsilon_ionic")):
            parsed = ad__parse_tensor_section(text, title, "dimensionless", sha, label)
            if parsed is not None:
                dielectric.append(parsed)
                observations.append({"field": f"dielectric.{label}", "value": parsed["tensor"],
                                     "units": "dimensionless", "frame": parsed["frame"],
                                     "native_sha256": sha, "raw_pointer": parsed["raw_pointer"]})
    if len(dielectric) == 2:
        static = [[ad__finite(dielectric[0]["tensor"][i][j] + dielectric[1]["tensor"][i][j], "static dielectric sum")
                   for j in range(3)] for i in range(3)]
        observations.append({"field": "dielectric.epsilon_static_observed_sum", "value": static,
                             "units": "dimensionless", "frame": "Cartesian x,y,z",
                             "native_sha256": sha,
                             "raw_pointer": ([dielectric[0]["raw_pointer"], dielectric[1]["raw_pointer"]]),
                             "response_phase": (final_response["ordered_phase"] if final_response else None),
                             "derivation": "componentwise sum of same-phase named electronic and ionic sections; observation only"})
    has_lepsilon = ad__parse_incar_value("LEPSILON", incar.get("LEPSILON", ("F", "INCAR:absent")))
    response = "NOT_REQUESTED_BY_INCAR" if has_lepsilon is False else (
        "REQUESTED_AND_BOTH_SECTIONS_OBSERVED" if len(dielectric) == 2
        else "REQUESTED_BUT_RESPONSE_SECTIONS_NOT_BOTH_OBSERVED")
    return observations, {"electronic_termination": state, "warning_markers": warnings,
                          "elastic_total_observed": any(o["field"] == "elastic.relaxed_ion_total" for o in observations),
                          "elastic_unqualified_or_clamped_observed": any(o["field"] == "elastic.unqualified_or_clamped_native" for o in observations),
                          "dielectric_response_observation": response,
                          "final_dfpt_response": final_response}

def ad__force_on_cell_stress(text: str, sha: str) -> dict[str, Any]:
    """Observe the last FORCE-on-cell stress row in native VASP print order."""
    starts = list(re.finditer(
        r"(?im)^\s*FORCE on cell\s*=-STRESS in cart\. coord\.\s*units\s*\(eV\):\s*$", text))
    if not starts:
        return {"value": None, "tokens": None, "raw_pointer": None,
                "availability": "NOT_OBSERVED_NO_FORCE_ON_CELL_SECTION"}
    heading = starts[-1]
    tail = text[heading.end():].splitlines()
    rows = [(offset, line) for offset, line in enumerate(tail[:32], 1)
            if re.match(r"^\s*in kB\b", line)]
    if len(rows) != 1:
        raise ad_CandidateNativeInvalid("final FORCE-on-cell section lacks one unique in kB stress row")
    offset, row = rows[0]
    match = re.fullmatch(r"\s*in kB\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*", row)
    if match is None:
        raise ad_CandidateNativeInvalid("final FORCE-on-cell in kB row must contain six native tokens")
    tokens = list(match.groups())
    values = [ad__parse_float(token, "OUTCAR FORCE-on-cell in kB") for token in tokens]
    line = text.count("\n", 0, heading.start()) + 1 + offset
    return {"value": values, "tokens": tokens,
            "raw_pointer": {"section_heading_line": text.count("\n", 0, heading.start()) + 1,
                            "stress_row_line": line, "section": "FORCE on cell =-STRESS in cart. coord."},
            "availability": "OBSERVED_FINAL_FORCE_ON_CELL"}

def ad__ionic_relaxation_termination(text: str, sha: str,
                                  incar: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """Observe the native ionic optimizer stop and the INCAR mode that owns it."""
    marker = list(re.finditer(
        r"(?im)^\s*reached required accuracy\s*-\s*stopping structural energy minimisation\s*$", text))
    normal = list(re.finditer(r"(?im)^\s*General timing and accounting informations for this job:\s*$", text))
    exhausted = list(re.finditer(r"(?im)^.*(?:reached NELM|without reaching EDIFF|EDIFF is not reached).*$", text))
    values = {key: ad__parse_incar_value(key, incar.get(key, ("", "INCAR:absent")))
              for key in ("IBRION", "ISIF", "NSW")}
    valid_mode = (values["IBRION"] == 2 and values["ISIF"] == 2 and
                  type(values["NSW"]) in (int, float) and values["NSW"] > 0)
    observed = valid_mode and len(marker) == 1 and len(normal) == 1 and not exhausted
    availability = "OBSERVED_RELAXED_ION_OPTIMIZER_TERMINATION" if observed else "NOT_OBSERVED_RELAXED_ION_OPTIMIZER_TERMINATION"
    def line(match: re.Match[str]) -> int:
        return text.count("\n", 0, match.start()) + 1
    return {"value": "OBSERVED_RELAXED_ION_CONVERGENCE" if observed else "NOT_OBSERVED",
            "availability": availability,
            "raw_pointer": {"ibrion_isif_nsw": values,
                            "ionic_optimizer_stop_lines": [line(m) for m in marker],
                            "normal_termination_lines": [line(m) for m in normal],
                            "electronic_exhaustion_lines": [line(m) for m in exhausted],
                            "native_sha256": sha}}

def ad__core_1s_observation(data: bytes, sha: str, species_order: list[str]) -> dict[str, Any]:
    """Return the last complete native 1s site table, or an explicit absence."""
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise ad_CandidateNativeInvalid("OUTCAR core source is not ASCII") from exc
    heads = [idx for idx, line in enumerate(lines)
             if "the core state eigenenergies are" in line.lower()]
    if not heads:
        return {"value": None, "availability": "NOT_OBSERVED_NO_CORE_SECTION", "raw_pointer": None}
    head = heads[-1]
    end = next((idx for idx in range(head + 1, len(lines))
                if re.match(r"^\s*E-fermi\b", lines[idx], flags=re.IGNORECASE)), None)
    if end is None:
        raise ad_CandidateNativeInvalid("final OUTCAR core eigenenergy section lacks E-fermi terminator")
    records: dict[int, dict[str, Any]] = {}
    declaration = re.compile(r"^\s*(\d+)\s*-\s+1s\b(.*)$", flags=re.IGNORECASE)
    for idx in range(head + 1, end):
        match = declaration.match(lines[idx])
        if not match:
            continue
        site = int(match.group(1))
        tokens = match.group(2).split()
        if not tokens or site < 1 or site > len(species_order):
            raise ad_CandidateNativeInvalid("malformed or out-of-order OUTCAR 1s core site row")
        if site in records:
            raise ad_CandidateNativeInvalid("duplicate OUTCAR 1s core site row")
        value = ad__parse_float(tokens[0], f"OUTCAR:line {idx + 1} 1s core energy")
        records[site] = {"site_index_1based": site, "species": species_order[site - 1],
                         "energy_eV": value, "energy_token_eV": tokens[0],
                         "raw_line": idx + 1}
    if set(records) != set(range(1, len(species_order) + 1)):
        raise ad_CandidateNativeInvalid("final OUTCAR core section lacks exactly one 1s energy per atom")
    return {"value": [records[idx] for idx in range(1, len(species_order) + 1)],
            "availability": "OBSERVED_COMPLETE_SITE_TABLE",
            "raw_pointer": {"section_heading_line": head + 1,
                            "site_lines": [records[idx]["raw_line"] for idx in range(1, len(species_order) + 1)],
                            "terminator_line": end + 1}}

def ad_observe_native_run(run_dir: str | os.PathLike[str],
                       trusted_expected_sha256: dict[str, str]) -> dict[str, Any]:
    """Extract observations from a seven-file bounded snapshot.

    `trusted_expected_sha256` must come from an independently authenticated
    snapshot. Its values are never learned from candidate manifests or receipts.
    The returned object is explicitly non-scoring and is not a gate receipt.
    """
    if type(trusted_expected_sha256) is not dict or set(trusted_expected_sha256) != set(ad_FILES):
        raise ad_EnvironmentInvalid("trusted expected hashes must name exactly the seven adapter inputs")
    for name, digest in trusted_expected_sha256.items():
        if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ad_EnvironmentInvalid(f"invalid trusted SHA-256 for {name}")
    payload = {name: ad__read_stable(Path(run_dir), name) for name in ad_FILES}
    hashes = {name: ad__sha(data) for name, data in payload.items()}
    mismatch = [name for name in ad_FILES if hashes[name] != trusted_expected_sha256[name]]
    if mismatch:
        raise ad_EnvironmentInvalid(f"snapshot hash differs from authenticated context: {', '.join(mismatch)}")
    receipt = ad__strict_json(payload["execution-receipt.json"], "execution receipt")
    manifest = ad__strict_json(payload["input-manifest.json"], "input manifest")
    if type(receipt) is not dict or type(manifest) is not dict:
        raise ad_EnvironmentInvalid("receipt and input manifest must be JSON objects")
    if receipt.get("input_manifest_sha256") != hashes["input-manifest.json"]:
        raise ad_EnvironmentInvalid("execution receipt does not bind input manifest bytes")
    actual_inputs = receipt.get("actual_run_inputs")
    native_outputs = receipt.get("native_output_sha256")
    if type(actual_inputs) is not dict or type(native_outputs) is not dict:
        raise ad_EnvironmentInvalid("receipt lacks native input/output hash maps")
    for name in ("POSCAR", "INCAR", "KPOINTS"):
        if actual_inputs.get(name) != hashes[name]:
            raise ad_EnvironmentInvalid(f"receipt does not bind {name}")
    for name in ("OUTCAR", "vasprun.xml"):
        if native_outputs.get(name) != hashes[name]:
            raise ad_EnvironmentInvalid(f"receipt does not bind native {name}")
    manifest_files = manifest.get("files")
    if type(manifest_files) is not dict:
        raise ad_EnvironmentInvalid("input manifest lacks its declared file hash map")
    for name in ("POSCAR", "INCAR", "KPOINTS"):
        if manifest_files.get(name) != hashes[name]:
            raise ad_EnvironmentInvalid(f"input manifest does not bind {name}")
    if receipt.get("case_id") != manifest.get("case_id") or receipt.get("stage") != manifest.get("stage"):
        raise ad_EnvironmentInvalid("execution receipt and input manifest identity/stage differ")
    incar = ad__incar(payload["INCAR"])
    xml_obs, xml_meta = ad__xml_observations(payload["vasprun.xml"], hashes["vasprun.xml"], set(incar))
    method = manifest.get("method")
    if type(method) is not dict:
        raise ad_EnvironmentInvalid("input manifest lacks method descriptor")
    layers: dict[str, dict[str, tuple[str, str | None]]] = {
        "INCAR": {key: (raw, None) for key, (raw, _loc) in incar.items()},
        "vasprun.xml/incar": {key: (raw, xml_meta["xml_incar_types"].get(key))
                               for key, raw in xml_meta["xml_incar"].items()},
        "vasprun.xml/parameters": xml_meta["effective_parameters"],
    }
    nsw_transition = ad__proven_ibrion6_nsw_expansion(
        layers, manifest, receipt, xml_meta["effective_parameter_pointers"],
        {key: source for key, (_raw, source) in incar.items()})
    normalized: dict[str, Any] = {}
    layer_values: dict[str, dict[str, Any]] = {name: {} for name in layers}
    for layer_name, entries in layers.items():
        for key, (raw, declared_type) in entries.items():
            value = ad__normalized_tag(key, raw, declared_type, layer_name)
            layer_values[layer_name][key] = value
            if key in normalized:
                prior = normalized[key]
                numeric_pair = (type(prior) in (int, float) and type(value) in (int, float))
                same = (prior == value) if numeric_pair else (type(prior) is type(value) and prior == value)
                if not same:
                    if key == "NSW" and nsw_transition is not None:
                        normalized[key] = 61
                        continue
                    raise ad_CandidateNativeInvalid(
                        f"conflicting {key} values across present input/effective layers"
                    )
            normalized[key] = value
    gga = normalized.get("GGA")
    if type(gga) is not str or not gga:
        raise ad_CandidateNativeInvalid("INCAR GGA method is missing")
    # GGA=PE alone does not identify the functional. Require the effective
    # hybrid controls to explicitly exclude the HSE/HF contribution.
    if (gga.upper() == "PE" and normalized.get("LHFCALC") is False and
            normalized.get("AEXX") == 0.0 and normalized.get("HFSCREEN") == 0.0):
        xc = "PBE"
    else:
        xc = "UNKNOWN"
    response_requested = normalized.get("LEPSILON", False)
    if type(response_requested) is not bool:
        raise ad_CandidateNativeInvalid("LEPSILON did not normalize to a logical value")
    response_sources = [name for name, entries in layers.items() if "LEPSILON" in entries]
    response_request_source = ", ".join(response_sources) if response_sources else \
        "not present in INCAR or vasprun.xml; no gate inferred"
    outcar_incar = dict(incar)
    outcar_incar["LEPSILON"] = ("T" if response_requested else "F", response_request_source)
    out_obs, out_meta = ad__outcar_observations(payload["OUTCAR"], hashes["OUTCAR"],
                                             outcar_incar, len(xml_meta["response"].get("born_effective_charges") or [])
                                             or len(next(o["value"] for o in xml_obs if o["field"] == "structure.species_order")))
    try:
        submitted_geometry = ad__poscar_initial_geometry(payload["POSCAR"], hashes["POSCAR"])
    except ad_CandidateNativeInvalid:
        # Keep the generic adapter usable for native POSCAR profiles outside
        # this bounded VASP5 parser; such a run simply cannot supply these
        # optional geometry observations.
        submitted_geometry = None
    species_order = (submitted_geometry["species_order"] if submitted_geometry is not None else
                     next(o["value"] for o in xml_obs if o["field"] == "structure.species_order"))
    core_levels = ad__core_1s_observation(payload["OUTCAR"], hashes["OUTCAR"], species_order)
    out_obs.append({"field": "core.site_1s_eigenenergies", "value": core_levels["value"],
                    "units": "eV", "frame": "site order of submitted POSCAR species",
                    "native_sha256": hashes["OUTCAR"], "raw_pointer": core_levels["raw_pointer"],
                    "availability": core_levels["availability"]})
    response_checks: dict[str, Any] = {}
    if response_requested:
        xml_response = xml_meta["response"]
        native_response = out_meta["final_dfpt_response"]
        if any(xml_response.get(key) is None for key in
               ("epsilon_high", "epsilon_ionic", "born_effective_charges")):
            raise ad_CandidateNativeInvalid("LEPSILON response lacks final-calculation XML dielectric/Born arrays")
        if native_response is None:
            raise ad_CandidateNativeInvalid("LEPSILON response lacks unique ordered final OUTCAR dielectric/Born/ionic block")
        response_checks = {
            "epsilon_high": ad__compare_printed_tensors("epsilon_high", xml_response["epsilon_high"],
                                                       native_response["epsilon_high"]["tensor"], 1e-6),
            "epsilon_ionic": ad__compare_printed_tensors("epsilon_ionic", xml_response["epsilon_ionic"],
                                                        native_response["epsilon_ionic"]["tensor"], 1e-6),
            "born_effective_charges": ad__compare_printed_tensors(
                "born_effective_charges", xml_response["born_effective_charges"],
                native_response["born_effective_charges"]["tensor"], 1e-5),
        }
    stage_kind = manifest.get("stage_kind")
    observations = xml_obs + out_obs
    for field_name, value, units, frame, pointer in (
            ("structure.submitted_lattice", submitted_geometry["lattice"] if submitted_geometry else None,
             "angstrom", "Cartesian lattice vectors as rows", submitted_geometry["raw_pointer"] if submitted_geometry else None),
            ("structure.submitted_fractional_positions", submitted_geometry["fractional_positions"] if submitted_geometry else None,
             "fractional", "submitted POSCAR cell", submitted_geometry["raw_pointer"] if submitted_geometry else None),
            ("structure.submitted_species_order", submitted_geometry["species_order"] if submitted_geometry else None,
             "element labels", "submitted POSCAR site order", submitted_geometry["raw_pointer"] if submitted_geometry else None)):
        observations.append({"field": field_name, "value": value, "units": units, "frame": frame,
                             "native_sha256": hashes["POSCAR"], "raw_pointer": pointer,
                             "availability": "OBSERVED" if submitted_geometry else "UNSUPPORTED_POSCAR_PROFILE"})
    geometry_reference: dict[str, Any] = {"status": "NOT_APPLICABLE_TO_STAGE"}
    if stage_kind == "elastic" and normalized.get("IBRION") == 6:
        initial_geometry = xml_meta.get("initial_structure")
        if initial_geometry is None:
            raise ad_CandidateNativeInvalid("receipt-bound IBRION=6 elastic response lacks XML initialpos geometry")
        submitted_geometry = ad__poscar_initial_geometry(payload["POSCAR"], hashes["POSCAR"])
        geometry_reference = ad__compare_parent_geometries(submitted_geometry, initial_geometry, manifest)
        final_positions = next(item for item in xml_obs if item["field"] == "structure.fractional_positions")
        geometry_reference["finalpos_observation"] = {
            "status": "PRESERVED_AS_FINAL_OUTPUT_NOT_PARENT_REFERENCE",
            "value": final_positions["value"],
            "native_sha256": final_positions["native_sha256"],
            "raw_pointer": final_positions["raw_pointer"],
        }
        observations.append({"field": "structure.response_parent_geometry_validation",
                             "value": geometry_reference,
                             "units": "dimensionless comparison summary",
                             "frame": "submitted POSCAR vs vasprun initialpos; finalpos retained separately",
                             "native_sha256": hashes["vasprun.xml"],
                             "raw_pointer": {"POSCAR": submitted_geometry["raw_pointer"],
                                             "vasprun.xml": initial_geometry["raw_pointer"]}})
    if stage_kind == "elastic":
        if not out_meta["elastic_total_observed"]:
            raise ad_CandidateNativeInvalid("elastic native output lacks the complete TOTAL 6x6 elastic tensor")
        if out_meta["elastic_unqualified_or_clamped_observed"]:
            raise ad_CandidateNativeInvalid("elastic native output contains an unqualified/clamped elastic tensor")
    if not any(item["field"] == "elastic.relaxed_ion_total" for item in observations):
        observations.append({"field": "elastic.relaxed_ion_total", "value": None,
                             "units": "GPa", "frame": "Cartesian engineering Voigt",
                             "native_sha256": hashes["OUTCAR"],
                             "raw_pointer": None, "availability": "SECTION_NOT_PRESENT"})
    if not response_requested:
        for key in ("epsilon_high", "epsilon_ionic", "epsilon_static"):
            observations.append({"field": f"dielectric.{key}", "value": None,
                                 "units": "dimensionless", "frame": "Cartesian x,y,z",
                                 "native_sha256": hashes["OUTCAR"], "raw_pointer": "INCAR:LEPSILON=F",
                                 "availability": "RESPONSE_NOT_REQUESTED"})
    elif out_meta["dielectric_response_observation"] == "REQUESTED_BUT_RESPONSE_SECTIONS_NOT_BOTH_OBSERVED":
        pass
    conv = xml_meta["convergence"]
    conv["electronic"] = out_meta["electronic_termination"]
    conv["ionic"] = "NOT_RUN_BY_NSW_ZERO" if incar.get("NSW", (None,))[0] == "0" else "NOT_INDEPENDENTLY_QUALIFIED"
    # Record parsed INCAR values and source locations without using them as gates.
    incar_values = {k: {"value": ad__parse_incar_value(k, v), "raw": v[0], "raw_type": None, "source": v[1]}
                    for k, v in sorted(incar.items())}
    return {
        "schema": ad_SCHEMA,
        "result_class": "NATIVE_OBSERVATIONS_ONLY_NOT_SCIENCE_VERIFIED",
        "science_gate_released": False,
        "scoring_status": "NOT_EVALUATED",
        "source_hashes": hashes,
        "provenance": {
            "receipt_sha256": hashes["execution-receipt.json"],
            "manifest_sha256": hashes["input-manifest.json"],
            "receipt_status_raw": receipt.get("status"),
            "receipt_exit_code_raw": receipt.get("exit_code"),
            "slurm_job_id_raw": receipt.get("slurm_job_id"),
            "method_descriptor_raw": method,
            "paw_identity_source": "input-manifest metadata only; POTCAR body was not read",
            "trusted_context_required": True,
        },
        "method": {"engine": "VASP", "engine_version": xml_meta["vasp_version"],
                   "xc_from_incar": xc, "gga_lexeme": gga,
                   "method_manifest_xc_raw": method.get("xc"),
                   "paw_family_manifest_raw": method.get("paw_family"),
                   "method_consistency": "OBSERVATION_ONLY_NOT_AUTHENTICATED"},
        "incar_observations": incar_values,
        "xml_parameter_observations": xml_meta["xml_parameter_sources"],
        "native_dimensions": {k: xml_meta[k] for k in ("kpoint_count", "spin_count", "band_count")},
        "geometry_reference": geometry_reference,
        "observations": observations,
        "termination_observations": {"electronic": conv["electronic"], "ionic": conv["ionic"],
                                     "outcar_warning_markers": out_meta["warning_markers"],
                                     "receipt_is_not_a_science_judgment": True},
        "response_availability": {"lepsilon_requested": response_requested,
                                   "lepsilon_request_source": response_request_source,
                                   "elastic_total": "OBSERVED" if out_meta["elastic_total_observed"] else "NOT_OBSERVED",
                                   "dielectric": ("NOT_REQUESTED_BY_NATIVE_EFFECTIVE_PARAMETER" if not response_requested
                                                  else out_meta["dielectric_response_observation"])},
        "native_control_layers": {
            "values_by_source": layer_values,
            "nsw_effective_expansion": nsw_transition,
            "ionic_convergence_interpretation": (
                "NOT_INFERRED_FROM_EFFECTIVE_NSW; native OUTCAR/XML trajectory still required"
                if nsw_transition else conv["ionic"]),
        },
        "response_print_precision_crosschecks": response_checks,
        "unsupported_method": None if xc == "PBE" else {"status": "ENV_INVALID", "method": xc},
    }
# Inlined, namespaced scientific module: component_reference_v1.py
from typing import Any

ref_SCHEMA = "case05.component_reference.v1"

ref_REFERENCE_METHOD = "VASP-6.4.3/PBE/PBE.54/Ga_d+As"

ref_GEOMETRY_SHA256 = "08e7e31e4db180514934c9455afa986c4a52751d03daf93c31da4b362c8b47e3"

ref_VASP_SHA256 = "4191538b24159631419278681a8853370b8f2d2ecbb38065f548e57708673f74"

ref_PAW_PROVENANCE_SHA256 = "7a872f550ce8a0fc2aa337c01e666a7979e6d391df7c14379fc933681918d6bf"

ref_PAW_ORDERED_SHA256 = (
    "a60ddf36e14f00ea098d9e3914b3745f1b7105e68786148f49ae384e44b4226c",
    "bc8fb55b00baa90d383a523722e1771deb40ea3f17a5ce25913641995975acad",
)

ref_POP_ALGORITHM_SHA256 = "473046bc3813828641bc9cd77efb0d6de74c803f3d749431de6d63e4b8d1368b"

ref_PRINT_TOLERANCE = 1.0e-6

ref_PARAMETER_TOLERANCE = 1.0e-5

ref_DIELECTRIC_ABS_TOLERANCE = 0.2

ref_DIELECTRIC_REL_TOLERANCE = 0.02

ref_POP_ABS_TOLERANCE_THz = 0.1

ref_POP_REL_TOLERANCE = 0.02

ref_PBE_GAP_SETTING_TOLERANCE_EV = 0.03

ref_PBE_GAP_NATIVE_MATCH_TOLERANCE_EV = 3.0e-4

ref_ELASTIC_REFERENCE_SOURCE_SHA256 = "31edadb8580abc1ff3464f6a1d7f407befacb1d5eb58fbe130464c131bce3ee6"

ref_DEFORMATION_REFERENCE_SOURCE_SHA256 = "83da4911c32d831893498aa2f9c9de8f771ce4f60d1db52e36e0d387ccb27ea2"

ref_ELASTIC_C_REFERENCE_GPA = (
    (98.89794775, 41.4920934, 41.49119065, 0.0001816, 0.00007115, 0.0001116),
    (41.4902199, 98.89984195, 41.49119065, 0.0000834, 0.00017285, 0.0001116),
    (41.4902199, 41.4920934, 98.8989735, 0.0000834, 0.00007115, 0.0002152),
    (0.0, 0.0, 0.0, 51.0729291, 0.0, 0.0),
    (0.0, 0.0, 0.0, 0.0, 51.0729068, 0.0),
    (0.0, 0.0, 0.0, 0.0, 0.0, 51.0728862),
)

ref_DEFORMATION_REFERENCE = {
    "cbm_D_mean_all_atom_1s_eV": {
        "0.0025": {"xx": 7.09, "yy": 7.09, "zz": 7.09, "yz": 0.0, "xz": 0.0, "xy": 0.0},
        "0.005": {"xx": 7.09, "yy": 7.09, "zz": 7.09, "yz": 0.0, "xz": 0.0, "xy": 0.0},
    },
    "hole_H_derivative_coefficients_eV": {
        "0.0025": {"a": 0.1566666671566868, "b": -5.499999999573057, "c_signed": -1.2600000003554028},
        "0.005": {"a": 0.1533333333591615, "b": -5.510000000140398, "c_signed": -1.2700000009243324},
    },
}

ref_DEFORMATION_COMPONENTS = ("xx", "yy", "zz", "yz", "xz", "xy")

ref_DEFORMATION_ABS_TOLERANCE_EV = 0.2

ref_DEFORMATION_REL_TOLERANCE = 0.05

ref_ELASTIC_ABS_TOLERANCE_GPA = 3.0

ref_ELASTIC_REL_TOLERANCE = 0.03

ref_RUNS: dict[str, dict[str, Any]] = {
    "dfpt_650_k16": {
        "setting_id": "pbe_650eV_16x16x16",
        "job_id": "3892141", "encut_ev": 650, "mesh": [16, 16, 16],
        "manifest_sha256": "6167ede3ded7a259ff129e64ccbc85be33653739a6a3404f21b3dc7a3b19eb08",
        "receipt_sha256": "5e507681d9356765211798fff2bd01d44c5c793063be4340898989716751c27d",
        "files": {
            "POSCAR": (523, "08e7e31e4db180514934c9455afa986c4a52751d03daf93c31da4b362c8b47e3"),
            "INCAR": (380, "f14de83b1f950310b2a60a322dd9b1498102ddc77c8d0045d224f265e69233c3"),
            "KPOINTS": (58, "03db421ccf569e7f3a8ac67f49d5348ef8a0ac4c5ad9d58bb6911737464b4ef9"),
            "OUTCAR": (2109913, "d9717cf9bb46f21570d9b12b88491dce2ca0152a90fd29ad8b0f0b38531626c4"),
            "vasprun.xml": (943419, "a6ef105d4539273ba8992b83c080447540e2cf6786e6d14cf44e8327468c041f"),
            "execution-receipt.json": (3881, "5e507681d9356765211798fff2bd01d44c5c793063be4340898989716751c27d"),
            "input-manifest.json": (3970, "6167ede3ded7a259ff129e64ccbc85be33653739a6a3404f21b3dc7a3b19eb08"),
        },
        "epsilon_high": 16.46087164, "epsilon_ionic": 2.23193378,
        "epsilon_static": 18.69280542,
        "pbe_gap_ev": 0.1441,
        "pop_mean_thz": 8.048815316845788, "pop_bound_thz": 0.001404056805207814,
    },
    "dfpt_520_k16": {
        "setting_id": "pbe_520eV_16x16x16",
        "job_id": "3892172", "encut_ev": 520, "mesh": [16, 16, 16],
        "manifest_sha256": "dec19781b9bab3baae7137552b83b0865d906f1aac46b67255dbe82d6dc4abe7",
        "receipt_sha256": "30e08493b4ae2752927281cae90e238c22588d822cbc4616988a8d358261216a",
        "files": {
            "POSCAR": (523, "08e7e31e4db180514934c9455afa986c4a52751d03daf93c31da4b362c8b47e3"),
            "INCAR": (380, "df0ab07646087c5eeb1aa099c3a2c7198194b5aac5fd4eaffb73a3a26c2fece8"),
            "KPOINTS": (58, "03db421ccf569e7f3a8ac67f49d5348ef8a0ac4c5ad9d58bb6911737464b4ef9"),
            "OUTCAR": (2106850, "d0bfab6f5769463bb2cc38b279dea212c8411f73a59b9b8a796b3db3567f2aeb"),
            "vasprun.xml": (942947, "e5ebab2d20f4ed4e243c700eecceaf9d07352f11b44b0d6b16b553d0acbd262e"),
            "execution-receipt.json": (3881, "30e08493b4ae2752927281cae90e238c22588d822cbc4616988a8d358261216a"),
            "input-manifest.json": (3970, "dec19781b9bab3baae7137552b83b0865d906f1aac46b67255dbe82d6dc4abe7"),
        },
        "epsilon_high": 16.45868509, "epsilon_ionic": 2.23013300,
        "epsilon_static": 18.68881809,
        "pbe_gap_ev": 0.1442,
        "pop_mean_thz": 8.051396664155080, "pop_bound_thz": 0.004907523437654143,
    },
    "dfpt_650_k12": {
        "setting_id": "pbe_650eV_12x12x12",
        "job_id": "3892173", "encut_ev": 650, "mesh": [12, 12, 12],
        "manifest_sha256": "e15d99b9d29b7c90de0c4d76e19c57d649d1a8fb33ebbdcdf9c48d3772ead693",
        "receipt_sha256": "50e7d0213a2eed21542f50a8949ee3051c61b6a5e6dcf3f5db7fcc3bf844ca26",
        "files": {
            "POSCAR": (523, "08e7e31e4db180514934c9455afa986c4a52751d03daf93c31da4b362c8b47e3"),
            "INCAR": (380, "f14de83b1f950310b2a60a322dd9b1498102ddc77c8d0045d224f265e69233c3"),
            "KPOINTS": (58, "3d2528bec4dba56c209c9046e1d52d2b2b0d38a34e666e78860539c3b53c5843"),
            "OUTCAR": (1066250, "ba974d72c5172759ee9bf368a6b5156d9a268ca67fcf28f552f1e0cd71a994dd"),
            "vasprun.xml": (675282, "b7bd94acc7cf643e605f3bf46ce24f6d426cbec1544fb6745c4c6a3e63b006b7"),
            "execution-receipt.json": (3881, "50e7d0213a2eed21542f50a8949ee3051c61b6a5e6dcf3f5db7fcc3bf844ca26"),
            "input-manifest.json": (3970, "e15d99b9d29b7c90de0c4d76e19c57d649d1a8fb33ebbdcdf9c48d3772ead693"),
        },
        "epsilon_high": 16.72051808, "epsilon_ionic": 2.24373820,
        "epsilon_static": 18.96425628,
        "pbe_gap_ev": 0.1439,
        "pop_mean_thz": 8.046050061405210, "pop_bound_thz": 0.001281647769416569,
    },
}

ref__GEOMETRY_LATTICE = ((0.0, 2.875248, 2.875248), (2.875248, 0.0, 2.875248),
                     (2.875248, 2.875248, 0.0))

ref__GEOMETRY_FRACTIONAL = ((0.0, 0.0, 0.0), (0.75, 0.75, 0.75))

class ref_CandidateReferenceError(ValueError):
    """Candidate claimed a reviewed component but joined it to the wrong data."""

class ref_ReferenceEnvironmentError(ValueError):
    """The fixed reference or supported native-observation capability is invalid."""

def ref__within_reference(value: float, expected: float, absolute: float, relative: float) -> bool:
    return abs(value - expected) <= max(absolute, relative * max(abs(value), abs(expected)))

def ref__candidate_records(native: dict[str, dict[str, Any]], source_ids: Any) -> list[tuple[str, dict[str, Any]]]:
    if type(source_ids) is not list or not source_ids or any(type(x) is not str for x in source_ids):
        raise ref_CandidateReferenceError("component source_ids must be a nonempty list")
    if len(set(source_ids)) != len(source_ids):
        raise ref_CandidateReferenceError("component source_ids contain duplicates")
    all_ids = {sid for record in native.values() for sid in record.get("source_ids", [])}
    if not set(source_ids).issubset(all_ids):
        raise ref_CandidateReferenceError("component source_ids do not resolve to collected native records")
    selected = [(run_id, record) for run_id, record in native.items()
                if set(source_ids) & set(record.get("source_ids", []))]
    return selected

def ref__record_field(record: dict[str, Any], name: str, source_name: str) -> dict[str, Any] | None:
    row = ref__extract_value(record, name)
    expected = record.get("result", {}).get("source_hashes", {}).get(source_name)
    return row if type(row) is dict and expected and row.get("native_sha256") == expected else None

def ref__require_run_source_ids(record: dict[str, Any], requested: set[str], filenames: tuple[str, ...], label: str) -> None:
    evidence = record.get("evidence_rows")
    if type(evidence) is not dict:
        raise ref_CandidateReferenceError(f"{label} lacks native evidence identity rows")
    required = {evidence[name].get("source_id") for name in filenames
                if type(evidence.get(name)) is dict}
    if len(required) != len(filenames) or not required.issubset(requested):
        raise ref_CandidateReferenceError(f"{label} source_ids omit a native member used in the replay")

def ref__transpose(a: list[list[float]]) -> list[list[float]]:
    return [list(row) for row in zip(*a)]

def ref__mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(len(b))) for j in range(len(b[0]))]
            for i in range(len(a))]

def ref__inv3(a: list[list[float]]) -> list[list[float]]:
    d = (a[0][0] * (a[1][1]*a[2][2]-a[1][2]*a[2][1])
         - a[0][1] * (a[1][0]*a[2][2]-a[1][2]*a[2][0])
         + a[0][2] * (a[1][0]*a[2][1]-a[1][1]*a[2][0]))
    if not math.isfinite(d) or abs(d) < 1e-12:
        raise ref_CandidateReferenceError("native lattice is singular")
    return [[(a[1][1]*a[2][2]-a[1][2]*a[2][1])/d, (a[0][2]*a[2][1]-a[0][1]*a[2][2])/d, (a[0][1]*a[1][2]-a[0][2]*a[1][1])/d],
            [(a[1][2]*a[2][0]-a[1][0]*a[2][2])/d, (a[0][0]*a[2][2]-a[0][2]*a[2][0])/d, (a[0][2]*a[1][0]-a[0][0]*a[1][2])/d],
            [(a[1][0]*a[2][1]-a[1][1]*a[2][0])/d, (a[0][1]*a[2][0]-a[0][0]*a[2][1])/d, (a[0][0]*a[1][1]-a[0][1]*a[1][0])/d]]

def ref__strain_from_lattices(bulk: list[list[float]], current: list[list[float]]) -> list[list[float]]:
    # Lattice vectors are stored as rows; F maps the bulk Cartesian basis to the current cell.
    f = ref__mul(ref__transpose(current), ref__inv3(ref__transpose(bulk)))
    ftf = ref__mul(ref__transpose(f), f)
    return [[0.5 * (ftf[i][j] - (1.0 if i == j else 0.0)) for j in range(3)] for i in range(3)]

def ref__strain_coordinate(e: list[list[float]], component: str) -> float:
    positions = {"xx": (0, 0), "yy": (1, 1), "zz": (2, 2),
                 "yz": (1, 2), "xz": (0, 2), "xy": (0, 1)}
    i, j = positions[component]
    return e[i][j] if i == j else 2.0 * e[i][j]

def ref__derive_deformation(native: dict[str, dict[str, Any]], source_ids: Any) -> dict[str, Any] | None:
    selected = ref__candidate_records(native, source_ids)
    requested = set(source_ids)
    rows = []
    for run_id, record in selected:
        meta = record.get("manifest_metadata")
        if type(meta) is not dict or meta.get("stage_kind") != "deformation":
            continue
        ref__require_run_source_ids(record, requested, ("OUTCAR", "POSCAR", "vasprun.xml"), "deformation run")
        fields = record.get("fields", {})
        gamma = ref__record_field(record, "band.gamma_spectrum", "vasprun.xml")
        core = ref__record_field(record, "core.site_1s_eigenenergies", "OUTCAR")
        lattice = ref__record_field(record, "structure.submitted_lattice", "POSCAR")
        species = ref__record_field(record, "structure.submitted_species_order", "POSCAR")
        if any(x is None or x.get("value") is None for x in (gamma, core, lattice, species)):
            raise ref_ReferenceEnvironmentError("deformation native source lacks source-bound Gamma/core/POSCAR observations")
        if gamma.get("availability") != "OBSERVED_UNIQUE_GAMMA" or core.get("availability") != "OBSERVED_COMPLETE_SITE_TABLE":
            raise ref_CandidateReferenceError("deformation source lacks a unique Gamma spectrum or complete site 1s table")
        if record.get("result", {}).get("method", {}).get("xc_from_incar") != "PBE":
            raise ref_ReferenceEnvironmentError("deformation route requires a qualified PBE native method")
        bands = gamma["value"].get("spins", [])
        if len(bands) != 1 or len(bands[0].get("bands", [])) < 10:
            raise ref_ReferenceEnvironmentError("deformation Gamma spectrum layout is unsupported")
        gamma_bands = bands[0]["bands"]
        if any(not ref__close(gamma_bands[i].get("occupation"), 1.0, 1e-6) for i in (6, 7, 8)) or not ref__close(
                gamma_bands[9].get("occupation"), 0.0, 1e-6):
            raise ref_CandidateReferenceError("native Gamma edge does not have the occupied triplet and empty conduction state")
        cbm = ref__record_field(record, "band.cbm", "vasprun.xml")
        if (cbm is None or type(cbm.get("value")) is not dict or
                cbm["value"].get("kpoint_index_0based") != gamma["value"].get("kpoint_index_0based")):
            raise ref_CandidateReferenceError("source-bound native all-k CBM is not at the reported Gamma point")
        vbm = ref__record_field(record, "band.vbm", "vasprun.xml")
        if (vbm is None or type(vbm.get("value")) is not dict or
                vbm["value"].get("kpoint_index_0based") != gamma["value"].get("kpoint_index_0based")):
            raise ref_CandidateReferenceError("source-bound native all-k VBM is not at the reported Gamma point")
        termination = ref__record_field(record, "convergence.electronic_termination_observation", "OUTCAR")
        if termination is None or termination.get("value") != "EDIFF_REACHED_MARKER_OBSERVED":
            raise ref_CandidateReferenceError("deformation native run lacks the electronic convergence marker")
        if (float(gamma_bands[6]["energy_eV"]) - float(gamma_bands[5]["energy_eV"]) <= 0 or
                float(gamma_bands[9]["energy_eV"]) - max(float(x["energy_eV"]) for x in gamma_bands[6:9]) <= 0):
            raise ref_CandidateReferenceError("native Gamma band-edge triplet is not isolated")
        core_rows = core["value"]
        if len(core_rows) != len(species["value"]) or any(r.get("site_index_1based") != i + 1 for i, r in enumerate(core_rows)):
            raise ref_CandidateReferenceError("deformation core table does not match submitted site order")
        if [r.get("species") for r in core_rows] != species["value"]:
            raise ref_CandidateReferenceError("deformation core species differ from submitted POSCAR order")
        mean_core = sum(float(r["energy_eV"]) for r in core_rows) / len(core_rows)
        rows.append({"run_id": run_id, "record": record, "meta": meta,
                     "lattice": lattice["value"], "mean_core": mean_core,
                     "bands": gamma_bands, "species": species["value"]})
    if not rows:
        return None
    reference_method = rows[0]["record"].get("result", {}).get("provenance", {}).get("method_descriptor_raw")
    for row in rows:
        prov_method = row["record"].get("result", {}).get("provenance", {}).get("method_descriptor_raw")
        if type(reference_method) is dict and prov_method != reference_method:
            raise ref_CandidateReferenceError("deformation native rows have incompatible ordered method metadata")
        if (row["meta"].get("encut_ev") != rows[0]["meta"].get("encut_ev") or
                row["meta"].get("mesh") != rows[0]["meta"].get("mesh")):
            raise ref_CandidateReferenceError("deformation native rows mix cutoff or k-mesh settings")
    # Select the submitted cell nearest the zero-strain geometry.  Stage labels
    # are metadata only and cannot substitute for the observed cell.
    bulk = min(rows, key=lambda r: sum(
        sum(ref__strain_coordinate(ref__strain_from_lattices(r["lattice"], other["lattice"]), name)**2
            for name in ref_DEFORMATION_COMPONENTS) for other in rows))
    endpoint_rows = []
    for r in rows:
        e = ref__strain_from_lattices(bulk["lattice"], r["lattice"])
        coords = {name: ref__strain_coordinate(e, name) for name in ref_DEFORMATION_COMPONENTS}
        active = [(name, value) for name, value in coords.items() if abs(value) > 5e-5]
        if len(active) != 1:
            continue
        component, value = active[0]
        if any(abs(coords[name]) > 1e-5 for name in coords if name != component):
            continue
        endpoint_rows.append({**r, "component": component, "coordinate": value,
                              "amplitude": abs(value)})
    grouped: dict[tuple[str, float], dict[int, dict[str, Any]]] = {}
    for row in endpoint_rows:
        sign = 1 if row["coordinate"] > 0 else -1
        key = (row["component"], round(row["amplitude"], 4))
        grouped.setdefault(key, {})[sign] = row
    pairs = {key: pair for key, pair in grouped.items() if set(pair) == {-1, 1}}
    if not pairs:
        raise ref_ReferenceEnvironmentError("deformation route lacks source-bound positive/negative strain pairs")
    electron, hole = {}, {}
    def aligned_triplet(run: dict[str, Any]) -> list[float]:
        return sorted(float(b["energy_eV"]) - run["mean_core"] for b in run["bands"][6:9])

    bulk_triplet = aligned_triplet(bulk)
    bulk_center = sum(bulk_triplet) / 3.0
    for (component, amplitude), pair in pairs.items():
        minus, plus = pair[-1], pair[1]
        dx = plus["coordinate"] - minus["coordinate"]
        if dx <= 0:
            raise ref_CandidateReferenceError("deformation strain pair has invalid sign ordering")
        def aligned(bandrow: dict[str, Any], run: dict[str, Any]) -> float:
            return float(bandrow["energy_eV"]) - run["mean_core"]
        cbm_minus = aligned(minus["bands"][9], minus)
        cbm_plus = aligned(plus["bands"][9], plus)
        electron.setdefault(amplitude, {})[component] = -(cbm_plus - cbm_minus) / dx
        hminus = aligned_triplet(minus)
        hplus = aligned_triplet(plus)
        if component in {"xx", "yy", "zz"}:
            # At a normal strain, identify the symmetry doublet by its closest
            # pair within each split spectrum, then match the remaining singlets.
            def doublet_and_singlet(values: list[float]) -> tuple[float, float]:
                pair_indices = min(((i, j) for i in range(3) for j in range(i + 1, 3)),
                                   key=lambda ij: abs(values[ij[0]] - values[ij[1]]))
                singlet_index = next(i for i in range(3) if i not in pair_indices)
                return (sum(values[i] for i in pair_indices) / 2.0, values[singlet_index])
            minus_doublet, minus_singlet = doublet_and_singlet(hminus)
            plus_doublet, plus_singlet = doublet_and_singlet(hplus)
            doublet_slope = (plus_doublet - minus_doublet) / dx
            singlet_slope = (plus_singlet - minus_singlet) / dx
            slopes = sorted((singlet_slope, doublet_slope, doublet_slope))
        else:
            # Reversed shear cells are symmetry-isospectral. Use their mean
            # split spectrum relative to the source-bound zero-strain triplet
            # to recover |c|; the accepted mirror label fixes c_H's sign.
            average = [(hminus[i] + hplus[i]) / 2.0 for i in range(3)]
            slopes = sorted((value - bulk_center) / amplitude for value in average)
        hole.setdefault(amplitude, {})[component] = slopes
    return {"electron_D_by_amplitude": electron, "hole_eigenvalue_derivatives_by_amplitude": hole,
            "source_run_ids": sorted({r["run_id"] for r in rows}), "bulk_run_id": bulk["run_id"]}

def ref__named_state_values(block: Any, label: str, value_key: str) -> dict[str, float]:
    if type(block) is not dict or type(block.get("states")) is not list:
        raise ref_CandidateReferenceError(f"{label} states are malformed")
    values = {}
    for state in block["states"]:
        if type(state) is not dict:
            raise ref_CandidateReferenceError(f"{label} state is malformed")
        if value_key not in state:
            if "subspace_matrix_eV" in state or "matrix_eV" in state:
                raise ref_ReferenceEnvironmentError(f"{label} uses a valid but unsupported matrix encoding")
            raise ref_CandidateReferenceError(f"{label} state lacks its numeric value")
        name = state.get("component", state.get("invariant"))
        value = state.get(value_key)
        if type(value) not in (int, float) or not math.isfinite(float(value)):
            raise ref_CandidateReferenceError(f"{label} state value must be finite numeric data")
        if type(name) is not str:
            raise ref_ReferenceEnvironmentError(f"{label} uses an unsupported state naming convention")
        if name in values:
            raise ref_CandidateReferenceError(f"{label} contains duplicate named states")
        values[name] = float(value)
    return values

def ref__qualify_deformation(params: dict[str, Any], native: dict[str, dict[str, Any]]) -> dict[str, Any]:
    dp = params.get("deformation_potentials")
    if dp is None:
        return {"status": "NOT_EVALUATED", "reason": "candidate did not provide deformation blocks"}
    if type(dp) is not dict or type(dp.get("electron")) is not dict or type(dp.get("hole")) is not dict:
        raise ref_CandidateReferenceError("deformation candidate blocks are malformed")
    if any(type(dp[carrier].get("source_ids")) is not list for carrier in ("electron", "hole")):
        raise ref_CandidateReferenceError("deformation source_ids are malformed")
    ids = list(dict.fromkeys(dp["electron"].get("source_ids", []) + dp["hole"].get("source_ids", [])))
    derived = ref__derive_deformation(native, ids)
    if derived is None:
        return {"status": "NOT_EVALUATED", "reason": "no source-bound supported finite-strain native route"}
    for carrier in ("electron", "hole"):
        carrier_rows = ref__candidate_records(native, dp[carrier].get("source_ids"))
        carrier_ids = set(dp[carrier].get("source_ids", []))
        carrier_run_ids = {run_id for run_id, record in carrier_rows
                           if type(record.get("manifest_metadata")) is dict and
                           record["manifest_metadata"].get("stage_kind") == "deformation"}
        if not set(derived["source_run_ids"]).issubset(carrier_run_ids):
            raise ref_CandidateReferenceError(f"{carrier} deformation sources omit part of the replayed native chain")
        for run_id, record in carrier_rows:
            if run_id in derived["source_run_ids"]:
                ref__require_run_source_ids(record, carrier_ids, ("OUTCAR", "POSCAR", "vasprun.xml"),
                                        f"{carrier} deformation run")
    if dp.get("energy_reference") != "common_all_atom_1s":
        raise ref_ReferenceEnvironmentError("only the source-supported common all-atom 1s alignment is qualified")
    ampkeys = sorted(derived["electron_D_by_amplitude"])
    if len(ampkeys) < 2:
        raise ref_ReferenceEnvironmentError("deformation route lacks two source-bound amplitude levels")
    electron_private = ref_DEFORMATION_REFERENCE["cbm_D_mean_all_atom_1s_eV"]
    hole_private = ref_DEFORMATION_REFERENCE["hole_H_derivative_coefficients_eV"]
    if any(str(amplitude) not in electron_private or str(amplitude) not in hole_private for amplitude in ampkeys):
        raise ref_ReferenceEnvironmentError("private deformation comparison is not qualified at these source strain amplitudes")
    electron_values = ref__named_state_values(dp["electron"], "electron deformation", "value_eV")
    if set(electron_values) != set(ref_DEFORMATION_COMPONENTS):
        raise ref_ReferenceEnvironmentError("supported electron encoding requires six named Cartesian components")
    electron_native = {}
    unconverged_deformation = []
    for component in ref_DEFORMATION_COMPONENTS:
        vals = [derived["electron_D_by_amplitude"].get(a, {}).get(component) for a in ampkeys]
        if any(v is None for v in vals):
            raise ref_ReferenceEnvironmentError("source-bound native electron response lacks a two-amplitude component")
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                if not ref__within_reference(vals[i], vals[j], ref_DEFORMATION_ABS_TOLERANCE_EV, ref_DEFORMATION_REL_TOLERANCE):
                    unconverged_deformation.append({"carrier": "electron", "component": component,
                                                    "amplitudes": [ampkeys[i], ampkeys[j]],
                                                    "values_eV": [vals[i], vals[j]],
                                                    "absolute_tolerance_eV": ref_DEFORMATION_ABS_TOLERANCE_EV,
                                                    "relative_tolerance": ref_DEFORMATION_REL_TOLERANCE})
        electron_native[component] = sum(vals) / len(vals)
        for amplitude, native_value in zip(ampkeys, vals):
            if not ref__within_reference(electron_values[component], native_value,
                                     ref_DEFORMATION_ABS_TOLERANCE_EV, ref_DEFORMATION_REL_TOLERANCE):
                raise ref_CandidateReferenceError(f"electron {component} response differs from source-bound native derivative at amplitude {amplitude}")
            reference_value = electron_private[str(amplitude)][component]
            if not ref__within_reference(electron_values[component], reference_value,
                                     ref_DEFORMATION_ABS_TOLERANCE_EV, ref_DEFORMATION_REL_TOLERANCE):
                raise ref_CandidateReferenceError(f"electron {component} response disagrees with accepted native reference at amplitude {amplitude}")
    hole_values = ref__named_state_values(dp["hole"], "hole deformation", "symmetry_invariant_eV")
    if set(hole_values) != {"a", "b", "c_signed"}:
        raise ref_ReferenceEnvironmentError("supported hole encoding requires explicit a, b, and signed c invariants")
    native_coefficients = {}
    for amplitude in ampkeys:
        rows = derived["hole_eigenvalue_derivatives_by_amplitude"].get(amplitude, {})
        normal = [rows.get(c) for c in ("xx", "yy", "zz")]
        shear = [rows.get(c) for c in ("xy", "xz", "yz")]
        if any(v is None for v in normal + shear):
            raise ref_ReferenceEnvironmentError("source-bound native hole response lacks full cubic component coverage")
        a = sum(sum(v) / 3.0 for v in normal) / 3.0
        bvals = []
        for slopes in normal:
            ordered = sorted(slopes)
            bvals.append(ordered[0] - (ordered[1] + ordered[2]) / 2.0)
        b = sum(bvals) / len(bvals)
        abs_c = sum((max(v) - min(v)) / 2.0 for v in shear) / len(shear)
        # The native mirror fixes H's shared xy coefficient as negative.
        native_coefficients[amplitude] = {"a": a, "b": b, "c_signed": -abs_c}
    for invariant in ("a", "b", "c_signed"):
        values = [native_coefficients[amplitude][invariant] for amplitude in ampkeys]
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                if not ref__within_reference(values[i], values[j], ref_DEFORMATION_ABS_TOLERANCE_EV, ref_DEFORMATION_REL_TOLERANCE):
                    unconverged_deformation.append({"carrier": "hole", "invariant": invariant,
                                                    "amplitudes": [ampkeys[i], ampkeys[j]],
                                                    "values_eV": [values[i], values[j]],
                                                    "absolute_tolerance_eV": ref_DEFORMATION_ABS_TOLERANCE_EV,
                                                    "relative_tolerance": ref_DEFORMATION_REL_TOLERANCE})
        for amplitude in ampkeys:
            native_value = native_coefficients[amplitude][invariant]
            if not ref__within_reference(hole_values[invariant], native_value,
                                     ref_DEFORMATION_ABS_TOLERANCE_EV, ref_DEFORMATION_REL_TOLERANCE):
                raise ref_CandidateReferenceError(f"hole {invariant} differs from source-bound Gamma response at amplitude {amplitude}")
            reference_value = hole_private[str(amplitude)][invariant]
            if reference_value is not None and not ref__within_reference(hole_values[invariant], reference_value,
                                                                      ref_DEFORMATION_ABS_TOLERANCE_EV, ref_DEFORMATION_REL_TOLERANCE):
                raise ref_CandidateReferenceError(f"hole {invariant} disagrees with accepted signed native reference at amplitude {amplitude}")
    return {"status": "QUALIFIED", "amplitudes": ampkeys,
            "amplitude_convergence_status": "QUALIFIED" if not unconverged_deformation else "NOT_QUALIFIED",
            "amplitude_convergence_unqualified_components": unconverged_deformation,
            "qualification_scope": "candidate values match each observed amplitude independently; amplitude convergence is reported separately",
            "native_electron_D_by_amplitude": derived["electron_D_by_amplitude"],
            "native_hole_H_coefficients_by_amplitude": native_coefficients,
            "hole_convention": "H(E)=a tr(E)I + b diag(Eii-tr(E)/3) + offdiagonal(c_H*gamma); c_signed is c_H (energy/H derivative), resolved negative by the accepted same-cell mirror label",
            "signed_c_reference_sha256": ref_DEFORMATION_REFERENCE_SOURCE_SHA256,
            "source_run_ids": derived["source_run_ids"], "bulk_run_id": derived["bulk_run_id"]}

def ref__stress_tensor(raw: list[Any]) -> list[list[float]]:
    if type(raw) is not list or len(raw) != 6 or any(type(x) not in (int, float) or not math.isfinite(float(x)) for x in raw):
        raise ref_CandidateReferenceError("native force-on-cell stress must contain six finite kBar values")
    # VASP order XX YY ZZ XY YZ ZX; sign is compressive-positive.
    xx, yy, zz, xy, yz, zx = [-0.1 * float(x) for x in raw]
    return [[xx, xy, zx], [xy, yy, yz], [zx, yz, zz]]

def ref__det3(a: list[list[float]]) -> float:
    return (a[0][0]*(a[1][1]*a[2][2]-a[1][2]*a[2][1])
            - a[0][1]*(a[1][0]*a[2][2]-a[1][2]*a[2][0])
            + a[0][2]*(a[1][0]*a[2][1]-a[1][1]*a[2][0]))

def ref__second_piola(raw: list[Any], bulk: list[list[float]], current: list[list[float]]) -> list[float]:
    f = ref__mul(ref__transpose(current), ref__inv3(ref__transpose(bulk)))
    inverse = ref__inv3(f)
    sigma = ref__stress_tensor(raw)
    s = ref__mul(ref__mul(inverse, sigma), ref__transpose(inverse))
    s = [[ref__det3(f) * s[i][j] for j in range(3)] for i in range(3)]
    return [s[0][0], s[1][1], s[2][2], s[1][2], s[0][2], s[0][1]]

def ref__derive_stress_elastic(native: dict[str, dict[str, Any]], source_ids: Any) -> dict[str, Any] | None:
    rows = []
    requested = set(source_ids)
    for run_id, record in ref__candidate_records(native, source_ids):
        meta = record.get("manifest_metadata")
        if type(meta) is not dict or meta.get("stage_kind") != "elastic_finite_strain":
            continue
        ref__require_run_source_ids(record, requested, ("OUTCAR", "POSCAR"), "elastic finite-strain run")
        stress = ref__record_field(record, "stress.force_on_cell", "OUTCAR")
        lattice = ref__record_field(record, "structure.submitted_lattice", "POSCAR")
        if stress is None or lattice is None or stress.get("value") is None or lattice.get("value") is None:
            raise ref_ReferenceEnvironmentError("elastic finite-strain route lacks source-bound stress or submitted lattice")
        if record.get("result", {}).get("method", {}).get("xc_from_incar") != "PBE":
            raise ref_ReferenceEnvironmentError("elastic finite-strain route requires qualified PBE native runs")
        if rows and (meta.get("encut_ev") != rows[0]["meta"].get("encut_ev") or
                     meta.get("mesh") != rows[0]["meta"].get("mesh")):
            raise ref_CandidateReferenceError("elastic finite-strain endpoints mix cutoff or k-mesh settings")
        termination = ref__record_field(record, "convergence.electronic_termination_observation", "OUTCAR")
        if termination is None or termination.get("value") != "EDIFF_REACHED_MARKER_OBSERVED":
            raise ref_CandidateReferenceError("elastic finite-strain native endpoint lacks the electronic convergence marker")
        ionic = ref__record_field(record, "convergence.ionic_relaxation_termination", "OUTCAR")
        if ionic is None or ionic.get("value") != "OBSERVED_RELAXED_ION_CONVERGENCE":
            raise ref_ReferenceEnvironmentError("elastic finite-strain route requires source-bound native ionic-relaxation termination")
        rows.append({"run_id": run_id, "meta": meta, "stress": stress["value"], "lattice": lattice["value"]})
    if not rows:
        return None
    # A candidate can use any valid bulk identifier; choose the cell nearest to the zero-strain geometry.
    bulk = min(rows, key=lambda row: sum(
        sum(ref__strain_coordinate(ref__strain_from_lattices(row["lattice"], other["lattice"]), name)**2
            for name in ref_DEFORMATION_COMPONENTS) for other in rows))
    endpoints = []
    for row in rows:
        e = ref__strain_from_lattices(bulk["lattice"], row["lattice"])
        coordinates = {name: ref__strain_coordinate(e, name) for name in ref_DEFORMATION_COMPONENTS}
        active = [(name, value) for name, value in coordinates.items() if abs(value) > 5e-5]
        if len(active) != 1:
            continue
        component, value = active[0]
        if any(abs(coordinates[name]) > 1e-5 for name in coordinates if name != component):
            continue
        endpoints.append({**row, "component": component, "coordinate": value,
                          "amplitude": abs(value), "second_piola": ref__second_piola(
                              row["stress"], bulk["lattice"], row["lattice"] )})
    grouped: dict[tuple[str, float], dict[int, dict[str, Any]]] = {}
    for endpoint in endpoints:
        grouped.setdefault((endpoint["component"], round(endpoint["amplitude"], 4)), {})[
            1 if endpoint["coordinate"] > 0 else -1] = endpoint
    pairs = {key: pair for key, pair in grouped.items() if set(pair) == {-1, 1}}
    matrices: dict[float, list[list[float]]] = {}
    for component in ref_DEFORMATION_COMPONENTS:
        levels = sorted(amp for name, amp in pairs if name == component)
        if len(levels) < 2:
            raise ref_ReferenceEnvironmentError("elastic stress route needs two amplitudes for each six strain components")
        for amplitude in levels:
            pair = pairs[(component, amplitude)]
            dx = pair[1]["coordinate"] - pair[-1]["coordinate"]
            col = [(pair[1]["second_piola"][i] - pair[-1]["second_piola"][i]) / dx for i in range(6)]
            matrix = matrices.setdefault(amplitude, [[0.0] * 6 for _ in range(6)])
            column = ref_DEFORMATION_COMPONENTS.index(component)
            for i in range(6):
                matrix[i][column] = col[i]
    return {"matrices_by_amplitude": matrices, "bulk_run_id": bulk["run_id"],
            "source_run_ids": sorted(row["run_id"] for row in rows)}

def ref__qualify_elastic(params: dict[str, Any], native: dict[str, dict[str, Any]]) -> dict[str, Any]:
    block = params.get("elastic_C_GPa")
    if block is None:
        return {"status": "NOT_EVALUATED", "reason": "candidate did not provide an elastic tensor"}
    if type(block) is not dict:
        raise ref_CandidateReferenceError("elastic tensor is malformed")
    if type(block.get("source_ids")) is not list:
        raise ref_CandidateReferenceError("elastic source_ids are malformed")
    requested = set(block["source_ids"])
    selected = ref__candidate_records(native, block.get("source_ids"))
    direct = []
    for run_id, record in selected:
        row = ref__record_field(record, "elastic.relaxed_ion_total", "OUTCAR")
        if row is not None and row.get("value") is not None:
            ref__require_run_source_ids(record, requested, ("OUTCAR",), "elastic relaxed-ion total")
            direct.append((run_id, row["value"]))
    route = "native_relaxed_ion_total"
    if direct:
        observed = direct[0][1]
        if any(not all(ref__close(observed[i][j], other[1][i][j], ref_PRINT_TOLERANCE) for i in range(6) for j in range(6))
               for other in direct[1:]):
            raise ref_CandidateReferenceError("elastic candidate cites conflicting native total tensors")
        matrix = observed
        run_ids = [direct[0][0]]
        matrices_by_amplitude = None
    else:
        derived = ref__derive_stress_elastic(native, block.get("source_ids"))
        if derived is None:
            return {"status": "NOT_EVALUATED", "reason": "no source-bound relaxed-ion total or finite-strain stress route"}
        route = "source_bound_relaxed_ion_stress_fit"
        matrices_by_amplitude = derived["matrices_by_amplitude"]
        matrices = list(matrices_by_amplitude.values())
        if len(matrices) < 2:
            raise ref_ReferenceEnvironmentError("elastic stress route lacks two comparable amplitude matrices")
        unconverged_elastic = []
        amplitude_keys = list(matrices_by_amplitude)
        for a in range(len(matrices)):
            for b in range(a + 1, len(matrices)):
                for i in range(6):
                    for j in range(6):
                        first, second = matrices[a][i][j], matrices[b][i][j]
                        if not ref__within_reference(first, second, ref_ELASTIC_ABS_TOLERANCE_GPA, ref_ELASTIC_REL_TOLERANCE):
                            unconverged_elastic.append({"amplitudes": [amplitude_keys[a], amplitude_keys[b]],
                                                        "matrix_component": [ref_DEFORMATION_COMPONENTS[i], ref_DEFORMATION_COMPONENTS[j]],
                                                        "values_GPa": [first, second],
                                                        "absolute_tolerance_GPa": ref_ELASTIC_ABS_TOLERANCE_GPA,
                                                        "relative_tolerance": ref_ELASTIC_REL_TOLERANCE})
        matrix = [[sum(item[i][j] for item in matrices) / len(matrices) for j in range(6)] for i in range(6)]
        run_ids = derived["source_run_ids"]
    candidate = ref__matrix(block.get("matrix"), 6, "elastic candidate")
    if matrices_by_amplitude is None:
        if any(not ref__within_reference(candidate[i][j], matrix[i][j], ref_PRINT_TOLERANCE, 0.0)
               for i in range(6) for j in range(6)):
            raise ref_CandidateReferenceError("elastic tensor differs from its source-bound native response")
    else:
        for amplitude, measured in matrices_by_amplitude.items():
            if any(not ref__within_reference(candidate[i][j], measured[i][j],
                                         ref_ELASTIC_ABS_TOLERANCE_GPA, ref_ELASTIC_REL_TOLERANCE)
                   for i in range(6) for j in range(6)):
                raise ref_CandidateReferenceError(f"elastic tensor differs from source-bound response at amplitude {amplitude}")
    # The private stress-fit reference is compared using the declared scientific tolerance.
    if any(not ref__within_reference(candidate[i][j], ref_ELASTIC_C_REFERENCE_GPA[i][j],
                                 ref_ELASTIC_ABS_TOLERANCE_GPA, ref_ELASTIC_REL_TOLERANCE)
           for i in range(6) for j in range(6)):
        raise ref_CandidateReferenceError("elastic tensor differs from the accepted native elastic reference")
    if matrices_by_amplitude is None:
        unconverged_elastic = []
    return {"status": "QUALIFIED", "route": route, "source_run_ids": run_ids,
            "amplitude_convergence_status": "NOT_APPLICABLE" if matrices_by_amplitude is None else
                ("QUALIFIED" if not unconverged_elastic else "NOT_QUALIFIED"),
            "amplitude_convergence_unqualified_components": unconverged_elastic,
            "qualification_scope": "candidate tensor matches each observed amplitude independently; amplitude convergence is reported separately"}

def ref__close(a: Any, b: Any, tol: float) -> bool:
    return type(a) in (int, float) and type(b) in (int, float) and math.isfinite(float(a)) \
        and math.isfinite(float(b)) and abs(float(a) - float(b)) <= tol

def ref__matrix(value: Any, n: int, label: str) -> list[list[float]]:
    if type(value) is not list or len(value) != n:
        raise ref_CandidateReferenceError(f"{label} must be a {n}x{n} matrix")
    out = []
    for row in value:
        if type(row) is not list or len(row) != n or any(type(x) not in (int, float) or not math.isfinite(float(x)) for x in row):
            raise ref_CandidateReferenceError(f"{label} must be a finite {n}x{n} matrix")
        out.append([float(x) for x in row])
    return out

def ref__matrix_equal(a: Any, b: Any, tol: float) -> bool:
    try:
        aa, bb = ref__matrix(a, 3, "response"), ref__matrix(b, 3, "reference")
    except ref_CandidateReferenceError:
        return False
    return all(ref__close(aa[i][j], bb[i][j], tol) for i in range(3) for j in range(3))

def ref__scalar_tensor(value: float) -> list[list[float]]:
    return [[value if i == j else 0.0 for j in range(3)] for i in range(3)]

def ref__extract_value(record: dict[str, Any], field: str) -> dict[str, Any] | None:
    fields = record.get("fields")
    if type(fields) is not dict:
        return None
    row = fields.get(field)
    return row if type(row) is dict else None

def ref__find_runs(native: dict[str, dict[str, Any]]) -> tuple[dict[str, tuple[str, dict[str, Any]]], list[str]]:
    matched: dict[str, tuple[str, dict[str, Any]]] = {}
    errors: list[str] = []
    for run_id, record in native.items():
        rows = record.get("evidence_rows")
        if type(rows) is not dict:
            continue
        jobs = {row.get("job_id") for row in rows.values() if type(row) is dict}
        for key, ref in ref_RUNS.items():
            if ref["job_id"] not in jobs:
                continue
            if set(rows) != set(ref["files"]):
                errors.append(f"{key}: incomplete native file identity")
                continue
            for name, (size, expected_sha) in ref["files"].items():
                row = rows.get(name)
                if (type(row) is not dict or row.get("job_id") != ref["job_id"] or
                        row.get("bytes") != size or row.get("sha256") != expected_sha):
                    errors.append(f"{key}: source substitution at {name}")
                    break
            else:
                if key in matched:
                    errors.append(f"{key}: duplicate matching native source run")
                else:
                    matched[key] = (run_id, record)
    return matched, errors

def ref__validate_reference_run(key: str, run_id: str, record: dict[str, Any]) -> None:
    ref = ref_RUNS[key]
    result = record.get("result")
    if type(result) is not dict or result.get("schema") != "case05.native_observation_adapter.v1":
        raise ref_ReferenceEnvironmentError(f"{key}: reviewed adapter result unavailable")
    hashes = result.get("source_hashes")
    if type(hashes) is not dict or hashes != {name: pair[1] for name, pair in ref["files"].items()}:
        raise ref_ReferenceEnvironmentError(f"{key}: adapter source hash inventory differs from the reviewed run")
    prov = result.get("provenance")
    method = result.get("method")
    if (type(prov) is not dict or prov.get("receipt_sha256") != ref["receipt_sha256"] or
            prov.get("manifest_sha256") != ref["manifest_sha256"] or
            prov.get("slurm_job_id_raw") != ref["job_id"] or prov.get("receipt_status_raw") != "FINISHED" or
            prov.get("receipt_exit_code_raw") != 0 or type(method) is not dict or
            method.get("engine_version") != "6.4.3" or method.get("xc_from_incar") != "PBE" or
            method.get("paw_family_manifest_raw") != "PBE.54"):
        raise ref_ReferenceEnvironmentError(f"{key}: receipt or method provenance is not the reviewed source")
    method_raw = prov.get("method_descriptor_raw")
    if (type(method_raw) is not dict or method_raw.get("xc") != "PBE" or
            method_raw.get("paw_family") != "PBE.54" or method_raw.get("potcar_order") != ["Ga_d", "As"] or
            [x.get("sha256") for x in method_raw.get("potentials", []) if type(x) is dict] != list(ref_PAW_ORDERED_SHA256)):
        raise ref_ReferenceEnvironmentError(f"{key}: ordered PAW metadata differs from the reviewed run")
    gap = ref__extract_value(record, "band.fundamental_gap")
    occupations = ref__extract_value(record, "band.occupations")
    availability = result.get("response_availability")
    termination = result.get("termination_observations")
    if (type(gap) is not dict or gap.get("native_sha256") != ref["files"]["vasprun.xml"][1] or
            not ref__close(gap.get("value"), ref["pbe_gap_ev"], 1e-4) or
            type(occupations) is not dict or type(occupations.get("value")) is not dict or
            occupations["value"].get("fractional_state_count") != 0 or
            type(availability) is not dict or availability.get("lepsilon_requested") is not True or
            type(termination) is not dict or termination.get("electronic") != "EDIFF_REACHED_MARKER_OBSERVED"):
        raise ref_ReferenceEnvironmentError(f"{key}: insulating DFPT response gate/termination differs from the reviewed run")
    # Each DFPT response must use the zero-strain input geometry, not finalpos or
    # another candidate run's cell. Compare the vasprun initialpos to the
    # independently pinned POSCAR geometry represented by this source record.
    for field, expected in (("structure.initial_lattice", ref__GEOMETRY_LATTICE),
                            ("structure.initial_fractional_positions", ref__GEOMETRY_FRACTIONAL)):
        row = ref__extract_value(record, field)
        if type(row) is not dict or row.get("native_sha256") != ref["files"]["vasprun.xml"][1]:
            raise ref_ReferenceEnvironmentError(f"{key}: response parent geometry source missing")
        actual = row.get("value")
        if type(actual) is not list or len(actual) != len(expected) or any(
                type(ar) is not list or len(ar) != len(er) or any(not ref__close(x, y, 1e-8) for x, y in zip(ar, er))
                for ar, er in zip(actual, expected)):
            raise ref_ReferenceEnvironmentError(f"{key}: response parent geometry differs from the fixed POSCAR")
    manifest_row = record.get("manifest_metadata")
    if (type(manifest_row) is not dict or manifest_row.get("stage_kind") != "dfpt" or
            manifest_row.get("stage") != "04_dfpt_dielectric_born_gamma_pbe" or
            manifest_row.get("source_poscar_sha256") != ref_GEOMETRY_SHA256 or
            manifest_row.get("parent_geometry_sha256") != ref_GEOMETRY_SHA256 or
            manifest_row.get("relaxed_geometry_sha256") != ref_GEOMETRY_SHA256 or
            manifest_row.get("encut_ev") != ref["encut_ev"] or manifest_row.get("mesh") != ref["mesh"]):
        raise ref_ReferenceEnvironmentError(f"{key}: manifest geometry or setting identity mismatch")
    for field, scalar in (("dielectric.epsilon_high", ref["epsilon_high"]),
                          ("dielectric.epsilon_ionic", ref["epsilon_ionic"]),
                          ("dielectric.epsilon_static_observed_sum", ref["epsilon_static"])):
        row = ref__extract_value(record, field)
        expected_matrix = ref__scalar_tensor(scalar)
        if (type(row) is not dict or row.get("native_sha256") != ref["files"]["OUTCAR"][1] or
                not ref__matrix_equal(row.get("value"), expected_matrix, ref_PRINT_TOLERANCE)):
            raise ref_ReferenceEnvironmentError(f"{key}: source-bound {field} differs from the accepted native response")

def ref__source_run_for_ids(native: dict[str, dict[str, Any]], source_ids: Any,
                        matched: dict[str, tuple[str, dict[str, Any]]],
                        required_files: tuple[str, ...] = ("OUTCAR",)) -> str | None:
    if type(source_ids) is not list or not source_ids or any(type(x) is not str for x in source_ids):
        return None
    selected = []
    source_set = set(source_ids)
    if len(source_set) != len(source_ids):
        return None
    for setting_key, (run_id, record) in matched.items():
        all_ids = set(record.get("source_ids", []))
        required = {record["evidence_rows"][name]["source_id"]
                    for name in required_files if name in record.get("evidence_rows", {})}
        if source_set.issubset(all_ids) and required.issubset(source_set):
            selected.append(setting_key)
    return selected[0] if len(selected) == 1 else None

def ref__has_unqualified_source(native: dict[str, dict[str, Any]], source_ids: Any,
                            matched: dict[str, tuple[str, dict[str, Any]]]) -> bool:
    if type(source_ids) is not list or any(type(x) is not str for x in source_ids):
        return False
    supported_ids = {sid for _, record in matched.values() for sid in record.get("source_ids", [])}
    all_ids = {sid for record in native.values() for sid in record.get("source_ids", [])}
    return bool(set(source_ids) & (all_ids - supported_ids))

def ref__source_ids_for(record: dict[str, Any]) -> list[str]:
    result = record.get("source_ids")
    if type(result) is not list:
        return []
    return result

def ref__validate_convergence_quantity(row: Any, quantity: str,
                                   matched: dict[str, tuple[str, dict[str, Any]]],
                                   native: dict[str, dict[str, Any]]) -> bool:
    if type(row) is not dict or type(row.get("settings")) is not list:
        return False
    setting_by_key = {ref_RUNS[key]["setting_id"]: key for key in ref_RUNS}
    seen: set[str] = set()
    settings = []
    for item in row["settings"]:
        if type(item) is not dict:
            return False
        key = setting_by_key.get(item.get("setting_id"))
        if key is None:
            if ref__has_unqualified_source(native, item.get("source_ids"), matched):
                raise ref_ReferenceEnvironmentError("convergence cites a valid but unqualified native setting")
            return False
        if key not in matched or key in seen:
            return False
        run_id, record = matched[key]
        expected_ids = {record["evidence_rows"]["OUTCAR"]["source_id"]}
        if quantity in {"pop_frequency", "pbe_bandgap", "pbe_direct_gap"}:
            expected_ids.add(record["evidence_rows"]["vasprun.xml"]["source_id"])
        if item.get("method_id") != ref_REFERENCE_METHOD:
            if ref__has_unqualified_source(native, item.get("source_ids"), matched):
                raise ref_ReferenceEnvironmentError("convergence cites a valid but unqualified method route")
            return False
        if set(item.get("source_ids", [])) != expected_ids:
            if ref__has_unqualified_source(native, item.get("source_ids"), matched):
                raise ref_ReferenceEnvironmentError("convergence cites a valid but unqualified native source")
            return False
        if quantity in {"pbe_bandgap", "pbe_direct_gap"}:
            field = "band.fundamental_gap" if quantity == "pbe_bandgap" else "band.direct_gap"
            observation = ref__record_field(record, field, "vasprun.xml")
            expected = observation.get("value") if observation else None
            value = item.get("value")
            if not ref__close(value, expected, ref_PBE_GAP_NATIVE_MATCH_TOLERANCE_EV):
                return False
            numeric = float(value)
        elif quantity == "pop_frequency":
            value = item.get("value")
            if not ref__close(value, ref_RUNS[key]["pop_mean_thz"], ref_RUNS[key]["pop_bound_thz"]):
                return False
            numeric = float(value)
        else:
            field = "dielectric.epsilon_high" if quantity == "epsilon_high" else "dielectric.epsilon_static_observed_sum"
            observation = ref__extract_value(record, field)
            expected = observation.get("value") if observation else None
            if not ref__matrix_equal(item.get("value"), expected, ref_PARAMETER_TOLERANCE):
                return False
            numeric = item["value"]
        seen.add(key)
        settings.append((key, numeric))
    if len(settings) < 2:
        return False
    for i in range(len(settings)):
        for j in range(i + 1, len(settings)):
            first, second = settings[i][1], settings[j][1]
            if quantity in {"pbe_bandgap", "pbe_direct_gap"}:
                if abs(first - second) > ref_PBE_GAP_SETTING_TOLERANCE_EV:
                    return False
            elif quantity == "pop_frequency":
                pair_bound = abs(first - second) + ref_RUNS[settings[i][0]]["pop_bound_thz"] + ref_RUNS[settings[j][0]]["pop_bound_thz"]
                threshold = max(ref_POP_ABS_TOLERANCE_THz, ref_POP_REL_TOLERANCE * max(abs(first), abs(second)))
                if pair_bound > threshold:
                    return False
            else:
                for r in range(3):
                    for c in range(3):
                        threshold = max(ref_DIELECTRIC_ABS_TOLERANCE,
                                        ref_DIELECTRIC_REL_TOLERANCE * max(abs(first[r][c]), abs(second[r][c])))
                        if abs(first[r][c] - second[r][c]) > threshold:
                            return False
    return True

def ref_evaluate_component_references(params: dict[str, Any], convergence: dict[str, Any],
                                  native: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Bind candidate response values to reviewed run identities and tolerances.

    A component is ``QUALIFIED`` when at least two comparable reviewed native
    settings are present, each response is bound to its receipt and parent
    geometry, and the candidate supplies two or more matching setting rows.
    Three frozen settings describe the current capability, not a universal
    admission requirement. The result remains partial and cannot release an
    overall criterion.
    """
    matched, errors = ref__find_runs(native)
    if errors:
        raise ref_CandidateReferenceError("; ".join(errors))
    if len(matched) < 2:
        return {"schema": ref_SCHEMA, "overall": "PARTIAL", "overall_scoring_ready": False,
                "dielectric": "NOT_EVALUATED", "analytic_q0_pop": "NOT_EVALUATED",
                "reason": "fewer than two reviewed comparable native settings are available"}
    for key, (run_id, record) in matched.items():
        ref__validate_reference_run(key, run_id, record)

    selected_high = ref__source_run_for_ids(native, params.get("epsilon_high", {}).get("source_ids"), matched)
    selected_static = ref__source_run_for_ids(native, params.get("epsilon_static", {}).get("source_ids"), matched)
    selected_pop = ref__source_run_for_ids(native, params.get("pop_frequency", {}).get("source_ids"), matched,
                                       ("OUTCAR", "vasprun.xml"))
    for parameter, selected, field in (("epsilon_high", selected_high, "dielectric.epsilon_high"),
                                       ("epsilon_static", selected_static, "dielectric.epsilon_static_observed_sum")):
        if selected is None:
            if ref__has_unqualified_source(native, params.get(parameter, {}).get("source_ids"), matched):
                raise ref_ReferenceEnvironmentError(f"{parameter}: valid native route lacks a qualified adapter")
            raise ref_CandidateReferenceError(f"{parameter}: candidate value is not bound to one reviewed native setting")
        record = matched[selected][1]
        observed = ref__extract_value(record, field)
        if observed is None or not ref__matrix_equal(params[parameter].get("matrix"), observed.get("value"), ref_PARAMETER_TOLERANCE):
            raise ref_CandidateReferenceError(f"{parameter}: candidate tensor differs from its linked native setting")
    if selected_high != selected_static:
        raise ref_CandidateReferenceError("epsilon_high and epsilon_static cite different response settings")
    if selected_pop is None:
        if ref__has_unqualified_source(native, params.get("pop_frequency", {}).get("source_ids"), matched):
            raise ref_ReferenceEnvironmentError("pop_frequency: valid native route lacks a qualified adapter")
        raise ref_CandidateReferenceError("pop_frequency: candidate value is not bound to one reviewed native setting")
    pop_value = params.get("pop_frequency", {}).get("value_THz")
    pop_ref = ref_RUNS[selected_pop]
    if not ref__close(pop_value, pop_ref["pop_mean_thz"], pop_ref["pop_bound_thz"]):
        raise ref_CandidateReferenceError("pop_frequency differs from its source-bound analytic q->0 reference")
    if not {matched[selected_pop][1]["evidence_rows"][name]["source_id"] for name in ("OUTCAR", "vasprun.xml")}.issubset(
            set(params["pop_frequency"].get("source_ids", []))):
        raise ref_CandidateReferenceError("pop_frequency omits its source-bound OUTCAR/XML response chain")

    by_quantity = {row.get("quantity"): row for row in convergence.get("quantities", []) if type(row) is dict}
    convergence_ok = {
        quantity: ref__validate_convergence_quantity(by_quantity.get(quantity), quantity, matched, native)
        for quantity in ("epsilon_high", "epsilon_static", "pop_frequency", "pbe_bandgap", "pbe_direct_gap")
    }
    for quantity, ok in convergence_ok.items():
        row = by_quantity.get(quantity)
        if not ok and type(row) is dict and row.get("claimed_converged") is True:
            raise ref_CandidateReferenceError(
                f"{quantity}: claimed convergence is not bound to the reviewed source settings and frozen tolerance")
    eps_deltas = {
        "cutoff_epsilon_high_max_abs": 0.00218655,
        "cutoff_epsilon_static_max_abs": 0.00398733,
        "mesh_epsilon_high_max_abs": 0.25964644,
        "mesh_epsilon_static_max_abs": 0.27145086,
    }
    pop_deltas = {"cutoff_conservative_thz": 0.008892927552153672,
                  "mesh_conservative_thz": 0.005450960015201647}
    elastic_component = ref__qualify_elastic(params, native)
    deformation_component = ref__qualify_deformation(params, native)
    return {
        "schema": ref_SCHEMA,
        "overall": "QUALIFIED" if all(convergence_ok.values()) and elastic_component.get("status") == "QUALIFIED" and deformation_component.get("status") == "QUALIFIED" else "PARTIAL",
        "overall_scoring_ready": all(convergence_ok.values()) and elastic_component.get("status") == "QUALIFIED" and deformation_component.get("status") == "QUALIFIED",
        "dielectric": "QUALIFIED" if convergence_ok["epsilon_high"] and convergence_ok["epsilon_static"] else "NOT_EVALUATED",
        "analytic_q0_pop": "QUALIFIED" if convergence_ok["pop_frequency"] else "NOT_EVALUATED",
        "pbe_bandgap": "QUALIFIED" if convergence_ok["pbe_bandgap"] else "NOT_EVALUATED",
        "pbe_direct_gap": "QUALIFIED" if convergence_ok["pbe_direct_gap"] else "NOT_EVALUATED",
        "elastic": elastic_component,
        "band_edge_deformation": deformation_component,
        "method": ref_REFERENCE_METHOD,
        "source_settings": [ref_RUNS[key]["setting_id"] for key in ref_RUNS if key in matched],
        "source_receipt_sha256": {key: ref_RUNS[key]["receipt_sha256"] for key in ref_RUNS if key in matched},
        "source_manifest_sha256": {key: ref_RUNS[key]["manifest_sha256"] for key in ref_RUNS if key in matched},
        "accepted_pop_algorithm_sha256": ref_POP_ALGORITHM_SHA256,
        "pbe_gap_native_match_tolerance_ev": ref_PBE_GAP_NATIVE_MATCH_TOLERANCE_EV,
        "pbe_gap_setting_tolerance_ev": ref_PBE_GAP_SETTING_TOLERANCE_EV,
        "dielectric_tolerance": {"absolute": ref_DIELECTRIC_ABS_TOLERANCE,
                                 "relative": ref_DIELECTRIC_REL_TOLERANCE},
        "pop_tolerance_thz": {"absolute": ref_POP_ABS_TOLERANCE_THz, "relative": ref_POP_REL_TOLERANCE},
        "native_pair_deltas": {**eps_deltas, **pop_deltas},
        "candidate_convergence_rows_match_native": convergence_ok,
        "remaining_unqualified": [name for name, state in (
            ("elastic_C_GPa", elastic_component), ("electron_deformation", deformation_component),
            ("hole_deformation", deformation_component),
            ("pbe_bandgap", {"status": "QUALIFIED" if convergence_ok["pbe_bandgap"] else "NOT_EVALUATED"}),
            ("pbe_direct_gap", {"status": "QUALIFIED" if convergence_ok["pbe_direct_gap"] else "NOT_EVALUATED"}))
            if state.get("status") != "QUALIFIED"],
        "science_gate_released": all(convergence_ok.values()) and elastic_component.get("status") == "QUALIFIED" and deformation_component.get("status") == "QUALIFIED",
    }
# Inlined, namespaced scientific module: candidate_pop_native_v1.py
pop_SOURCE_NATIVE_SOLVE_SHA256 = "98d6c16ba43ced487d7d071170c880f4137b8e9d14cc4343ad98fc26a99204b7"

pop_K_E_EV_ANGSTROM = 14.399645478

pop_C_F_THz_PER_SQRT_EV_ANG2_AMU = 15.63330424

class pop_Stop(RuntimeError):
    pass

def pop_xml_token(token):
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?", token):
        raise pop_Stop("non-numeric token in response XML")
    value = float(token.replace("D","E").replace("d","e"))
    if not math.isfinite(value): raise pop_Stop("nonfinite response XML number")
    m, _, exp = token.lower().replace("d","e").partition("e")
    digits = len(m.split(".",1)[1]) if "." in m else 0
    return value, 0.5*10**((int(exp) if exp else 0)-digits)

def pop_xml_rows(node, rows, cols):
    vals=[]; rad=0.0
    for child in list(node):
        if child.tag != "v" or child.text is None: continue
        parsed=[pop_xml_token(x) for x in child.text.split()]
        if len(parsed)!=cols: raise pop_Stop("response XML numeric row width mismatch")
        vals.append([x[0] for x in parsed]); rad=max(rad,max(x[1] for x in parsed))
    arr=np.asarray(vals,float)
    if arr.shape!=(rows,cols) or not np.all(np.isfinite(arr)): raise pop_Stop("response XML matrix shape/nonfinite mismatch")
    return arr,rad

def pop__upper(value, scale=1.0):
    if not math.isfinite(value):
        raise pop_Stop("non-finite upper bound")
    cushion = 128.0 * np.finfo(float).eps * max(abs(value), abs(scale), 1.0)
    return math.nextafter(value + cushion, math.inf)

def pop__lower(value, scale=1.0):
    if not math.isfinite(value):
        raise pop_Stop("non-finite lower bound")
    cushion = 128.0 * np.finfo(float).eps * max(abs(value), abs(scale), 1.0)
    return math.nextafter(value - cushion, -math.inf)

def pop__frobenius_upper(value):
    norm = math.hypot(*(float(x) for x in np.asarray(value, dtype=float).ravel()))
    if not math.isfinite(norm):
        raise pop_Stop("non-finite Frobenius norm")
    return math.nextafter(norm + 128.0 * np.finfo(float).eps * max(norm, 1.0), math.inf)

def pop__translation_basis(masses):
    t = np.zeros((6, 3), dtype=float)
    total = float(np.sum(masses))
    for axis in range(3):
        for atom in range(2):
            t[3 * atom + axis, axis] = math.sqrt(float(masses[atom]) / total)
    return t

def pop__bright_lo_mean_bound(l_min, t_max, delta_lo, delta_to):
    ratio = math.nextafter(math.sqrt(2.0), math.inf) * t_max / l_min
    ratio = pop__upper(ratio, 1.0)
    return pop__upper(delta_lo + (ratio / (1.0 + ratio)) * delta_to,
                  max(delta_lo, delta_to, 1.0))

def pop__whole_direction_envelope(xml):
    """Conservative whole-sphere q→0 matrix/print-interval envelope."""
    born = np.asarray(xml["born"], dtype=float)
    eps = np.asarray(xml["epsilon"], dtype=float)
    masses = np.asarray(xml["masses_amu"], dtype=float)
    h = np.asarray(xml["hessian_thz2"], dtype=float)
    z = float(np.mean(np.diagonal(born, axis1=1, axis2=2)[0]))
    if not math.isfinite(z) or z <= 0:
        raise pop_Stop("Ga Born cubic reference scale is not positive")
    born_rad = float(xml["born_rounding_radius"])
    ideal_born = np.asarray([z * np.eye(3), -z * np.eye(3)])
    delta_g_sq = 0.0
    for k in range(2):
        matrix_radius = pop__upper(2.0 * born_rad + math.sqrt(3.0) * born_rad,
                               2.0 * born_rad + math.sqrt(3.0) * born_rad)
        matrix_error = np.nextafter(np.abs(born[k] - ideal_born[k]) + matrix_radius, math.inf)
        mass_rad = float(xml["mass_rounding_radii"][k])
        mass_min = float(masses[k]) - mass_rad
        if mass_min <= 0:
            raise pop_Stop("mass print interval is not strictly positive")
        norm_error = pop__upper(pop__frobenius_upper(matrix_error) / math.sqrt(mass_min) +
                            math.sqrt(3.0) * z * abs(1.0 / math.sqrt(mass_min) -
                                                      1.0 / math.sqrt(float(masses[k]))),
                            pop__frobenius_upper(matrix_error))
        delta_g_sq += norm_error * norm_error
    dg = pop__upper(math.sqrt(delta_g_sq), math.sqrt(delta_g_sq))
    g0 = z * math.sqrt(float(np.sum(1.0 / masses)))
    eps0 = float(np.trace(eps) / 3.0)
    eps_rad = float(xml["epsilon_rounding_radius"])
    eps_matrix_radius = pop__upper(3.0 * eps_rad, eps_rad)
    gershgorin = min(float(eps[i, i] - sum(abs(float(eps[i, j])) for j in range(3) if j != i))
                     for i in range(3))
    eps_min = pop__lower(gershgorin - eps_matrix_radius, abs(gershgorin))
    deps = pop__upper(pop__frobenius_upper(eps - eps0 * np.eye(3)) + eps_matrix_radius, abs(eps0))
    if eps_min <= 0 or eps0 <= 0:
        raise pop_Stop("dielectric print interval is not positive")
    eig_h = np.asarray(xml["eigenvalues_hessian_thz2"], dtype=float)
    to_sq = float(np.mean(-eig_h[:3]))
    t = pop__translation_basis(masses)
    p_opt = np.eye(6) - t @ t.T
    d0 = -h
    mass_projection_radius = 0.0
    for m0 in (masses[0] - xml["mass_rounding_radii"][0], masses[0] + xml["mass_rounding_radii"][0]):
        for m1 in (masses[1] - xml["mass_rounding_radii"][1], masses[1] + xml["mass_rounding_radii"][1]):
            if m0 <= 0 or m1 <= 0:
                raise pop_Stop("mass uncertainty reaches nonpositive values")
            corner_t = pop__translation_basis(np.asarray([m0, m1]))
            mass_projection_radius = max(mass_projection_radius, 2.0 * float(np.linalg.norm(corner_t - t, ord="fro")))
    mass_projection_radius = pop__upper(mass_projection_radius, 1.0)
    delta_d0 = pop__upper(pop__frobenius_upper(d0 - to_sq * p_opt) +
                      6.0 * float(xml["hessian_rounding_radius"]) + to_sq * mass_projection_radius,
                      abs(to_sq))
    volume = float(xml["volume_angstrom3"])
    volume_rad = float(xml["volume_rounding_radius"])
    if volume <= volume_rad or volume_rad < 0:
        raise pop_Stop("volume print interval is not positive")
    c = pop_C_F_THz_PER_SQRT_EV_ANG2_AMU ** 2 * 4 * math.pi * pop_K_E_EV_ANGSTROM / volume
    c_upper = pop__upper(pop_C_F_THz_PER_SQRT_EV_ANG2_AMU ** 2 * 4 * math.pi * pop_K_E_EV_ANGSTROM / (volume-volume_rad), c)
    dc = pop__upper(c_upper - c, c_upper)
    delta_nac = pop__upper(c_upper * ((2*g0*dg+dg*dg)/eps_min + (g0*g0*deps)/(eps_min*eps0)) +
                        dc * g0*g0 / eps_min, c_upper*g0*g0/eps_min)
    delta_d = pop__upper(delta_d0 + delta_nac, delta_d0)
    ideal_strength = c * g0*g0 / eps0
    if to_sq <= 0 or ideal_strength <= 0 or delta_d >= min(to_sq, ideal_strength):
        raise pop_Stop("whole-direction POP envelope does not isolate the positive optical/bright-LO subspace")
    f_to = math.sqrt(to_sq); f_lo = math.sqrt(to_sq + ideal_strength)
    f_to_min = math.nextafter(math.sqrt(to_sq-delta_d), 0.0)
    f_lo_min = math.nextafter(math.sqrt(to_sq+ideal_strength-delta_d), 0.0)
    f_lo_max = math.nextafter(math.sqrt(to_sq+ideal_strength+delta_d), math.inf)
    delta_lo = pop__upper(delta_d / (f_lo_min + f_lo), f_lo)
    delta_to = pop__upper((f_lo-f_to) + delta_d/(f_lo_min+f_lo) + delta_d/(f_to_min+f_to), f_lo)
    sin_bound = pop__upper(delta_d/(ideal_strength-delta_d), 1.0)
    if sin_bound >= 1:
        raise pop_Stop("whole-direction bright eigenspace angle unresolved")
    cos_lower = math.nextafter(math.sqrt(max(0.0, 1.0-sin_bound*sin_bound)), 0.0)
    l_min = pop__lower((g0*cos_lower-dg)/math.sqrt(f_lo_max), g0/math.sqrt(f_lo_max))
    t_max = pop__upper((g0*sin_bound+dg)/math.sqrt(f_to_min), g0/math.sqrt(f_to_min))
    if l_min <= 0:
        raise pop_Stop("whole-direction bright LO amplitude lower bound unresolved")
    return {"ideal_TO_frequency_thz": f_to, "ideal_LO_frequency_thz": f_lo,
            "LO_interval_thz": [f_lo_min, f_lo_max],
            "combined_squared_frequency_perturbation_bound_thz2": delta_d,
            "D0_to_cubic_optical_projector_bound_thz2": delta_d0,
            "NAC_full_direction_operator_bound_thz2": delta_nac,
            "born_mass_weighted_deviation_bound": dg, "epsilon_min_bound": eps_min,
            "bright_LO_amplitude_lower_bound": l_min,
            "TO_L2_amplitude_upper_bound": t_max,
            "mean_frequency_bound_thz": pop__bright_lo_mean_bound(l_min, t_max, delta_lo, delta_to),
            "scope": "ALL_CARTESIAN_DIRECTIONS_FOR_REPRESENTED_GAMMA_MATRICES_ONLY_NOT_SCIENCE_PASS"}

def pop_pop_input(record):
    root=ET.fromstring(record["files"]["vasprun.xml"])
    epsnode=root.findall(".//varray[@name='epsilon']"); bornnode=root.findall(".//array[@name='born_charges']"); dynnodes=root.findall(".//dynmat")
    if len(epsnode)!=1 or len(bornnode)!=1 or len(dynnodes)!=1: raise pop_Stop("DFPT XML lacks unique epsilon/Born/dynmat")
    eps,er=pop_xml_rows(epsnode[0],3,3)
    sets=bornnode[0].findall("./set")
    if len(sets)!=2: raise pop_Stop("DFPT XML must contain two ordered Born tensors")
    born=[]; br=0
    for ion in sets:
        z,zr=pop_xml_rows(ion,3,3); born.append(z); br=max(br,zr)
    dyn=dynnodes[0]; unit=dyn.find("./i[@name='unit']")
    if unit is None or (unit.text or "").strip()!="THz^2": raise pop_Stop("unsupported native Hessian unit")
    h,hr=pop_xml_rows(dyn.find("./varray[@name='hessian']"),6,6)
    enode=dyn.find("./v[@name='eigenvalues']")
    if enode is None or enode.text is None: raise pop_Stop("missing native Hessian eigenvalues")
    eig_tokens=[pop_xml_token(x) for x in enode.text.split()]
    vals=[x[0] for x in eig_tokens]
    if len(vals)!=6: raise pop_Stop("native Hessian eigenvalue count mismatch")
    atomtypes=root.find("./atominfo/array[@name='atomtypes']/set")
    if atomtypes is None: raise pop_Stop("native mass block missing")
    type_rows=[[(c.text or "").strip() for c in row.findall("c")] for row in atomtypes.findall("rc")]
    if len(type_rows)!=2 or [x[1] for x in type_rows]!=["Ga","As"]: raise pop_Stop("native mass species order is unsupported")
    mass_tokens=[pop_xml_token(x[2]) for x in type_rows]
    masses=np.asarray([x[0] for x in mass_tokens])
    volnode=root.find(".//structure[@name='finalpos']/crystal/i[@name='volume']")
    if volnode is None or volnode.text is None: raise pop_Stop("native DFPT volume missing")
    volume, volume_rad = pop_xml_token(volnode.text.strip())
    envelope_input={"born":np.asarray(born),"born_rounding_radius":br,
        "epsilon":eps,"epsilon_rounding_radius":er,
        "masses_amu":masses,"mass_rounding_radii":np.asarray([x[1] for x in mass_tokens]),
        "volume_angstrom3":volume,"volume_rounding_radius":volume_rad,
        "hessian_thz2":h,"hessian_rounding_radius":hr,
        "eigenvalues_hessian_thz2":np.asarray(vals)}
    envelope=pop__whole_direction_envelope(envelope_input)
    return {"to_thz":envelope["ideal_TO_frequency_thz"],
            "lo_thz":envelope["ideal_LO_frequency_thz"],
            "bound_thz":envelope["mean_frequency_bound_thz"],
            "lo_interval_thz":envelope["LO_interval_thz"],
            "delta_squared_thz2":envelope["combined_squared_frequency_perturbation_bound_thz2"],
            "d0_to_cubic_operator_bound_thz2":envelope["D0_to_cubic_optical_projector_bound_thz2"],
            "nac_all_direction_operator_bound_thz2":envelope["NAC_full_direction_operator_bound_thz2"],
            "born_mass_weighted_deviation_bound":envelope["born_mass_weighted_deviation_bound"],
            "epsilon_min_bound":envelope["epsilon_min_bound"],
            "bright_LO_amplitude_lower_bound":envelope["bright_LO_amplitude_lower_bound"],
            "TO_L2_amplitude_upper_bound":envelope["TO_L2_amplitude_upper_bound"],
            "born_raw":np.asarray(born).tolist(),"epsilon_raw":eps.tolist(),"d0_raw":(-h).tolist(),
            "mass_amu":masses.tolist(),"volume_angstrom3":volume,
            "scope":envelope["scope"]}
# Inlined, namespaced scientific module: candidate_deformation_proof_v1.py
from typing import Any, Mapping

proof_SCHEMA = "case05-candidate-gamma-mirror-proof/v1"

proof_PROOF_LIMIT = 2 * 1024 * 1024

proof_NATIVE_MEMBERS = ("POSCAR", "INCAR", "KPOINTS", "OUTCAR", "vasprun.xml",
                  "execution-receipt.json", "input-manifest.json")

proof_NATIVE_ENERGY_MATCH_EV = 3e-4

class proof_CandidateProofError(ValueError):
    """Candidate supplied malformed or contradictory proof data."""

def proof__sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def proof__strict_json(raw: bytes) -> Any:
    if type(raw) is not bytes or len(raw) > proof_PROOF_LIMIT:
        raise proof_CandidateProofError("mirror proof is missing or exceeds its fixed size limit")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise proof_CandidateProofError(f"mirror proof is not strict JSON: {exc}") from exc
    return obj

def proof__finite_array(value: Any, shape: tuple[int, ...], label: str) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise proof_CandidateProofError(f"{label} is not numeric") from exc
    if array.shape != shape or not np.all(np.isfinite(array)):
        raise proof_CandidateProofError(f"{label} has invalid shape or nonfinite values")
    return array

def proof__green_lagrange(bulk: np.ndarray, current: np.ndarray) -> np.ndarray:
    f = current.T @ np.linalg.inv(bulk.T)
    return 0.5 * (f.T @ f - np.eye(3))

def proof__engineering_component(e: np.ndarray, component: str) -> float:
    ij = {"xx": (0, 0), "yy": (1, 1), "zz": (2, 2),
          "yz": (1, 2), "xz": (0, 2), "xy": (0, 1)}[component]
    return float(e[ij] if ij[0] == ij[1] else 2.0 * e[ij])

def proof_mirror_parity(lattice_angstrom: Any, gpoints: Any,
                  coefficients_real: Any, coefficients_imag: Any) -> int:
    """Return the x/y-mirror parity after an integral reciprocal-basis map."""
    lattice = proof__finite_array(lattice_angstrom, (3, 3), "proof lattice")
    g = np.asarray(gpoints)
    if g.ndim != 2 or g.shape[1] != 3 or len(g) == 0 or not np.all(np.isfinite(g)):
        raise proof_CandidateProofError("G-point list is malformed")
    if not np.all(g == np.rint(g)):
        raise proof_CandidateProofError("G-point list must contain integer reduced coordinates")
    g = g.astype(np.int64)
    if len({tuple(row) for row in g.tolist()}) != len(g):
        raise proof_CandidateProofError("G-point list contains duplicates")
    c_re = proof__finite_array(coefficients_real, (len(g),), "coefficient real part")
    c_im = proof__finite_array(coefficients_imag, (len(g),), "coefficient imaginary part")
    coeff = c_re + 1j * c_im
    norm = float(np.vdot(coeff, coeff).real)
    if not math.isfinite(norm) or norm <= 0:
        raise proof_CandidateProofError("coefficient vector has zero or invalid norm")

    mirror = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    transform = np.linalg.inv(lattice.T) @ mirror @ lattice.T
    rounded = np.rint(transform)
    if np.max(np.abs(transform - rounded)) > 1e-8:
        raise proof_CandidateProofError("xy mirror does not map reciprocal lattice integrally")
    mapped = g @ rounded.astype(np.int64)
    index = {tuple(row): i for i, row in enumerate(g.tolist())}
    if any(tuple(row) not in index for row in mapped.tolist()):
        raise proof_CandidateProofError("G-point basis is not closed under xy mirror")
    permutation = np.array([index[tuple(row)] for row in mapped.tolist()], dtype=int)
    mirrored = np.zeros_like(coeff)
    mirrored[permutation] = coeff
    overlap = np.vdot(coeff, mirrored) / norm
    if abs(overlap.imag) > 1e-6 or min(abs(overlap.real - 1.0), abs(overlap.real + 1.0)) > 1e-5:
        raise proof_CandidateProofError("native Gamma state has no resolved xy mirror parity")
    return 1 if overlap.real > 0 else -1

def proof__whitened_mirror_projection(coefficients: np.ndarray,
                                permutation: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray,
                                                                  np.ndarray, np.ndarray]:
    """Form the Gram-whitened symmetry representation without tall BLAS matmuls."""
    gram = np.einsum("ki,kj->ij", coefficients.conj(), coefficients, optimize=False)
    gram_values, gram_vectors = np.linalg.eigh(gram)
    if not np.all(np.isfinite(gram_values)) or float(np.min(gram_values)) <= 1e-10:
        raise proof_CandidateProofError("source Gamma valence coefficient Gram matrix is not positive definite")
    inverse_sqrt = (gram_vectors * (1.0 / np.sqrt(gram_values))) @ gram_vectors.conj().T
    q = np.einsum("ki,ij->kj", coefficients, inverse_sqrt, optimize=False)
    mirrored = np.zeros_like(q)
    mirrored[permutation, :] = q
    projected = np.einsum("ki,kj->ij", q.conj(), mirrored, optimize=False)
    closure = np.einsum("ki,ij->kj", q, projected, optimize=False)
    return gram, q, mirrored, projected, closure

def proof__mirror_subspace_diagnostics(lattice: Any, gpoints: Any, bands: dict[str, Any],
                                 band_indices: tuple[int, int, int], *,
                                 require_odd_band: bool) -> dict[str, Any]:
    """Check a Gram-whitened mirror representation of the three-state subspace."""
    g = np.asarray(gpoints, dtype=np.int64)
    ccols = []
    energies = []
    for band in band_indices:
        item = bands[str(band)]
        reals = proof__finite_array(item["coefficients_real"], (len(g),), f"band {band} real coefficients")
        imags = proof__finite_array(item["coefficients_imag"], (len(g),), f"band {band} imaginary coefficients")
        ccols.append(reals + 1j * imags)
        energies.append(float(item["energy_ev"]))
    c = np.column_stack(ccols)
    lattice = proof__finite_array(lattice, (3, 3), "proof lattice")
    mirror = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    transform = np.linalg.inv(lattice.T) @ mirror @ lattice.T
    rounded = np.rint(transform)
    if np.max(np.abs(transform - rounded)) > 1e-8:
        raise proof_CandidateProofError("xy mirror does not map reciprocal lattice integrally")
    mapped = g @ rounded.astype(np.int64)
    index = {tuple(row): i for i, row in enumerate(g.tolist())}
    if any(tuple(row) not in index for row in mapped.tolist()):
        raise proof_CandidateProofError("G-point basis is not closed under xy mirror")
    permutation = np.array([index[tuple(row)] for row in mapped.tolist()], dtype=int)
    if not np.array_equal(permutation[permutation], np.arange(len(g))):
        raise proof_CandidateProofError("discrete xy mirror does not square to identity")
    gram, q, mirrored, projected, closure = proof__whitened_mirror_projection(c, permutation)
    gram_offdiagonal_residual = float(np.max(np.abs(gram - np.diag(np.diag(gram)))))
    gram_values, gram_vectors = np.linalg.eigh(gram)
    subspace_residual = float(np.max(np.abs(mirrored - closure)))
    hermitian_residual = float(np.max(np.abs(projected - projected.conj().T)))
    unitary_residual = float(np.max(np.abs(projected.conj().T @ projected - np.eye(3))))
    h = np.diag(np.asarray(energies, dtype=float))
    commutator_residual = float(np.max(np.abs(h @ projected - projected @ h)))
    mirror_values, mirror_vectors = np.linalg.eigh(0.5 * (projected + projected.conj().T))
    if (max(subspace_residual, hermitian_residual, unitary_residual) > 1e-5 or
            np.max(np.abs(np.abs(mirror_values) - 1.0)) > 1e-5):
        raise proof_CandidateProofError("Gamma valence subspace is not closed under an involutory xy mirror")
    if commutator_residual > 1e-6:
        raise proof_CandidateProofError("Gamma mirror representation is incompatible with the source band energies")
    odd_indices = np.flatnonzero(mirror_values < 0.0)
    even_indices = np.flatnonzero(mirror_values >= 0.0)
    if len(odd_indices) != 1 or len(even_indices) != 2:
        raise proof_CandidateProofError("Gamma valence triplet must contain one odd and two even mirror states")
    odd_vector = mirror_vectors[:, int(odd_indices[0])]
    band_weights = np.abs(odd_vector) ** 2
    odd_position = int(np.argmax(band_weights))
    if require_odd_band and float(band_weights[odd_position]) < 1.0 - 1e-5:
        raise proof_CandidateProofError("unique odd mirror branch is not resolved to a native Gamma band")
    return {"odd_band_one_based": band_indices[odd_position] if require_odd_band else None,
            "mirror_eigenvalues": [float(x) for x in mirror_values],
            "odd_band_weight": float(band_weights[odd_position]),
            "gram_offdiagonal_residual": gram_offdiagonal_residual,
            "gram_condition_number": float(np.max(gram_values) / np.min(gram_values)),
            "subspace_closure_residual": subspace_residual,
            "hermiticity_residual": hermitian_residual,
            "unitarity_residual": unitary_residual,
            "commutator_residual_eV": commutator_residual,
            "representation_offdiagonal_residual": float(np.max(np.abs(projected - np.diag(np.diag(projected)))))}

def proof__source_join(row: dict[str, Any], native: dict[str, Any]) -> None:
    if set(row) != {"run_id", "source_ids", "wavecar_sha256", "lattice_angstrom",
                    "gpoints_integer_reduced", "gpoint_order_sha256", "bands_one_based"}:
        raise proof_CandidateProofError("proof run row has missing or unsupported fields")
    expected_ids = native.get("source_ids_by_name")
    if type(expected_ids) is not dict or set(expected_ids) != set(proof_NATIVE_MEMBERS):
        raise proof_CandidateProofError("native record does not expose the complete seven-member source join")
    if (type(row.get("source_ids")) is not list or
            any(type(item) is not str or not re.fullmatch(r"[0-9a-f]{64}", item) for item in row["source_ids"]) or
            set(row["source_ids"]) != set(expected_ids.values()) or
            len(row["source_ids"]) != len(proof_NATIVE_MEMBERS)):
        raise proof_CandidateProofError("proof source_ids do not bind exactly one native run")
    receipt_raw = native.get("execution_receipt_raw")
    receipt = proof__strict_json(receipt_raw)
    if type(receipt) is not dict:
        raise proof_CandidateProofError("native execution receipt is not a JSON object")
    wavecar = receipt.get("native_output_sha256", {}).get("WAVECAR") if type(receipt) is dict else None
    if wavecar != row["wavecar_sha256"]:
        raise proof_CandidateProofError("proof WAVECAR hash does not join the native execution receipt")
    native_lattice = proof__finite_array(native.get("submitted_lattice"), (3, 3), "native submitted lattice")
    proof_lattice = proof__finite_array(row["lattice_angstrom"], (3, 3), "proof lattice")
    if not np.allclose(native_lattice, proof_lattice, atol=1e-8, rtol=0):
        raise proof_CandidateProofError("proof lattice differs from source-bound submitted POSCAR")
    g = np.asarray(row["gpoints_integer_reduced"])
    if g.ndim != 2 or g.shape[1] != 3 or not np.all(g == np.rint(g)):
        raise proof_CandidateProofError("proof G-point list is malformed")
    canonical = json.dumps(g.astype(int).tolist(), separators=(",", ":")).encode()
    if row["gpoint_order_sha256"] != proof__sha(canonical):
        raise proof_CandidateProofError("proof G-point order hash mismatch")
    proof_bands = row["bands_one_based"]
    gamma = native.get("gamma_bands_one_based")
    if type(proof_bands) is not dict or type(gamma) is not dict:
        raise proof_CandidateProofError("proof/native Gamma spectra are unavailable")
    gamma_occupied = []
    for key, observed in gamma.items():
        if type(observed) is not dict:
            raise proof_CandidateProofError("native Gamma spectrum row is malformed")
        occ = observed.get("occupation")
        energy = observed.get("energy_eV")
        if type(occ) not in (int, float) or not math.isfinite(float(occ)) or type(energy) not in (int, float) or not math.isfinite(float(energy)):
            raise proof_CandidateProofError("native Gamma spectrum has nonfinite energy or occupation")
        if abs(float(occ) - 1.0) < 1e-6:
            gamma_occupied.append((int(key), float(energy)))
        elif abs(float(occ)) >= 1e-6:
            raise proof_CandidateProofError("candidate DP proof supports only fully occupied/unoccupied scalar bands")
    if native.get("spin_count") != 1 or native.get("soc") is not False or native.get("band_edge_at_gamma") is not True:
        raise proof_CandidateProofError("candidate DP proof currently supports scalar non-SOC Gamma band edges only")
    indices = tuple(index for index, _ in sorted(gamma_occupied, key=lambda item: item[1])[-3:])
    if len(indices) != 3 or tuple(sorted(indices)) != indices:
        raise proof_CandidateProofError("native Gamma top occupied subspace is not a contiguous three-band manifold")
    if set(proof_bands) != {str(index) for index in indices}:
        raise proof_CandidateProofError("proof bands do not match the native top occupied Gamma triplet")
    for band in indices:
        key = str(band)
        item = proof_bands.get(key)
        observed = gamma.get(key)
        if type(item) is not dict or set(item) != {
                "coefficients_real", "coefficients_imag", "energy_ev", "occupation"}:
            raise proof_CandidateProofError(f"proof Gamma band {band} is malformed")
        if type(observed) is not dict:
            raise proof_CandidateProofError(f"native Gamma band {band} is missing")
        energy = item["energy_ev"]
        occupation = item["occupation"]
        if (type(energy) not in (int, float) or not math.isfinite(float(energy)) or
                abs(float(energy) - float(observed.get("energy_eV", math.nan))) > proof_NATIVE_ENERGY_MATCH_EV or
                type(occupation) not in (int, float) or not math.isfinite(float(occupation)) or
                abs(float(occupation) - float(observed.get("occupation", math.nan))) > 1e-6):
            raise proof_CandidateProofError(f"proof Gamma band {band} differs from source-bound vasprun spectrum")

def proof_derive_candidate_c_h_sign(proof_raw: bytes, native_runs: Mapping[str, dict[str, Any]], *,
                              expected_bulk_run_id: str) -> dict[str, Any]:
    """Join three candidate native Gamma proofs and determine signed c_H branch.

    Run roles are inferred from source-bound strain tensors, not stage labels or
    author run IDs. The caller still owns the independent amplitude and final
    deformation-potential comparisons.
    """
    proof = proof__strict_json(proof_raw)
    if type(proof) is not dict or set(proof) != {"schema", "runs"} or proof.get("schema") != proof_SCHEMA:
        raise proof_CandidateProofError("candidate mirror proof schema mismatch")
    runs = proof["runs"]
    if type(runs) is not list or len(runs) != 3:
        raise proof_CandidateProofError("candidate mirror proof must bind bulk and both xy endpoints")
    proof_rows = {row.get("run_id"): row for row in runs if type(row) is dict}
    if len(proof_rows) != 3 or len(proof_rows) != len(runs):
        raise proof_CandidateProofError("candidate mirror proof run IDs are missing or duplicated")
    if not set(proof_rows).issubset(native_runs):
        raise proof_CandidateProofError("candidate mirror proof references a missing native run")
    if type(expected_bulk_run_id) is not str or expected_bulk_run_id not in proof_rows:
        raise proof_CandidateProofError("finite-strain deformation chain did not identify this proof's bulk run")
    methods = [native_runs[run_id].get("method_identity") for run_id in proof_rows]
    if any(type(method) is not dict for method in methods) or any(method != methods[0] for method in methods[1:]):
        raise proof_CandidateProofError("candidate mirror proof runs do not share one source-bound method identity")
    for run_id, row in proof_rows.items():
        if row.get("run_id") != run_id:
            raise proof_CandidateProofError("candidate mirror proof run identity mismatch")
        proof__source_join(row, native_runs[run_id])

    rows = []
    for run_id, row in proof_rows.items():
        lattice = proof__finite_array(row["lattice_angstrom"], (3, 3), "proof lattice")
        rows.append((run_id, row, lattice))
    # Select the unstrained lattice from the minimum norm of its Green-Lagrange
    # strain to the other proof lattices; this is independent of run labels.
    bulk_id, bulk_row, bulk_lattice = min(
        rows, key=lambda item: sum(float(np.linalg.norm(proof__green_lagrange(item[2], other[2])) ** 2)
                                   for other in rows))
    if bulk_id != expected_bulk_run_id:
        raise proof_CandidateProofError("mirror proof bulk run differs from the source-bound deformation fit bulk")
    endpoints = {}
    odd_branches = {}
    energies = {}
    symmetry_diagnostics = {}
    bulk_symmetry_diagnostics = None
    for run_id, row, lattice in rows:
        strain = proof__green_lagrange(bulk_lattice, lattice)
        coords = {name: proof__engineering_component(strain, name)
                  for name in ("xx", "yy", "zz", "yz", "xz", "xy")}
        active = [(name, val) for name, val in coords.items() if abs(val) > 5e-5]
        if run_id == bulk_id:
            if active:
                raise proof_CandidateProofError("selected bulk proof is not the unstrained reference")
            band_indices = tuple(sorted(int(key) for key in row["bands_one_based"]))
            bulk_symmetry_diagnostics = proof__mirror_subspace_diagnostics(
                row["lattice_angstrom"], row["gpoints_integer_reduced"],
                row["bands_one_based"], band_indices, require_odd_band=False)
            continue
        if len(active) != 1 or active[0][0] != "xy" or any(
                abs(value) > 1e-5 for name, value in coords.items() if name != "xy"):
            raise proof_CandidateProofError("proof endpoints must be source-bound pure xy shear strains")
        sign = 1 if active[0][1] > 0 else -1
        if sign in endpoints:
            raise proof_CandidateProofError("proof does not contain unique positive and negative xy endpoints")
        endpoints[sign] = (run_id, row, active[0][1])
        band_indices = tuple(sorted(int(key) for key in row["bands_one_based"]))
        diag = proof__mirror_subspace_diagnostics(row["lattice_angstrom"], row["gpoints_integer_reduced"],
                                            row["bands_one_based"], band_indices,
                                            require_odd_band=(run_id != bulk_id))
        symmetry_diagnostics[str(sign)] = diag
        odd_branches[sign] = diag["odd_band_one_based"]
        band_indices = tuple(sorted(int(k) for k in row["bands_one_based"]))
        for band in band_indices:
            item = row["bands_one_based"][str(band)]
            energies[(sign, band)] = float(item["energy_ev"])
    if set(endpoints) != {-1, 1}:
        raise proof_CandidateProofError("candidate proof is missing one sign of xy shear")
    minus_band = odd_branches[-1]
    plus_band = odd_branches[1]
    gamma_minus = endpoints[-1][2]
    gamma_plus = endpoints[1][2]
    raw_slope = (energies[(1, plus_band)] - energies[(-1, minus_band)]) / (gamma_plus - gamma_minus)
    centroids = {}
    for sign in (-1, 1):
        row = endpoints[sign][1]
        centroids[sign] = sum(float(row["bands_one_based"][str(band)]["energy_ev"])
                              for band in sorted(int(k) for k in row["bands_one_based"])) / 3.0
    centered_minus = energies[(-1, minus_band)] - centroids[-1]
    centered_plus = energies[(1, plus_band)] - centroids[1]
    slope = (centered_plus - centered_minus) / (gamma_plus - gamma_minus)
    if not math.isfinite(raw_slope) or not math.isfinite(slope) or abs(slope) < 1e-6:
        raise proof_CandidateProofError("odd mirror-branch central slope is unresolved")
    return {"c_h_sign": -1 if slope > 0 else 1,
            "odd_branch_slope_eV_per_engineering_xy": slope,
            "raw_odd_branch_slope_eV_per_engineering_xy": raw_slope,
            "gauge_centered_odd_energy_eV": {"xy_minus": centered_minus, "xy_plus": centered_plus},
            "gamma_triplet_centroid_eV": {"xy_minus": centroids[-1], "xy_plus": centroids[1]},
            "bulk_run_id": bulk_id,
            "xy_minus_run_id": endpoints[-1][0],
            "xy_plus_run_id": endpoints[1][0],
            "odd_band_one_based": {"xy_minus": minus_band, "xy_plus": plus_band},
            "symmetry_diagnostics": {"bulk": bulk_symmetry_diagnostics, **symmetry_diagnostics},
            "proof_sha256": proof__sha(proof_raw),
            "status": "CANDIDATE_NATIVE_SYMMETRY_PROOF_VALIDATED_NOT_FULL_DP_QUALIFICATION"}

def proof_validate_reported_c_h_sign(derived: dict[str, Any], reported_c_signed: Any) -> None:
    """Reject a reported invariant whose sign contradicts the candidate proof."""
    if (type(reported_c_signed) not in (int, float) or
            not math.isfinite(float(reported_c_signed)) or float(reported_c_signed) == 0):
        raise proof_CandidateProofError("reported c_signed must be finite and nonzero for sign validation")
    if int(math.copysign(1, float(reported_c_signed))) != derived.get("c_h_sign"):
        raise proof_CandidateProofError("reported c_signed sign contradicts the candidate Gamma mirror proof")
# Inlined, namespaced scientific module: candidate_component_reference_v1.py
from typing import Any

ccref_BASE: Any = None

ccref_POP: Any = None

ccref_DEFORMATION_PROOF: Any = None

ccref_DEFORMATION_PROOF_RAW: bytes | None = None

ccref_SCHEMA = "case05.component_reference.v1"

ccref_PUBLIC_QUANTITY_NAMES = ("elastic_C_GPa", "epsilon_high", "epsilon_static", "pop_frequency",
                         "electron_deformation", "hole_deformation", "pbe_bandgap", "pbe_direct_gap")

ccref_CandidateReferenceError: type[Exception]

ccref_ReferenceEnvironmentError: type[Exception]

def ccref_bind_reference(base: Any) -> None:
    global ccref_BASE, ccref_CandidateReferenceError, ccref_ReferenceEnvironmentError
    ccref_BASE = base
    ccref_CandidateReferenceError = base.CandidateReferenceError
    ccref_ReferenceEnvironmentError = base.ReferenceEnvironmentError

def ccref_bind_pop(module: Any) -> None:
    global ccref_POP
    ccref_POP = module

def ccref_bind_deformation_proof(module: Any, proof_raw: bytes | None) -> None:
    global ccref_DEFORMATION_PROOF, ccref_DEFORMATION_PROOF_RAW
    ccref_DEFORMATION_PROOF = module
    ccref_DEFORMATION_PROOF_RAW = proof_raw

def ccref__field(record: dict[str, Any], name: str, native_name: str) -> dict[str, Any] | None:
    row = record.get("fields", {}).get(name)
    sha = record.get("result", {}).get("source_hashes", {}).get(native_name)
    return row if type(row) is dict and row.get("native_sha256") == sha and sha else None

def ccref__semantic_method(record: dict[str, Any]) -> bool:
    method = record.get("result", {}).get("method")
    raw = record.get("result", {}).get("provenance", {}).get("method_descriptor_raw")
    version = method.get("engine_version") if type(method) is dict else None
    return (type(method) is dict and method.get("engine") == "VASP" and
            type(version) is str and bool(version) and method.get("xc_from_incar") == "PBE" and
            method.get("paw_family_manifest_raw") == "PBE.54" and type(raw) is dict and
            raw.get("xc") == "PBE" and raw.get("paw_family") == "PBE.54" and
            raw.get("potcar_order") == ["Ga_d", "As"])

def ccref__source_integrity(run_id: str, record: dict[str, Any]) -> None:
    rows = record.get("evidence_rows")
    hashes = record.get("result", {}).get("source_hashes")
    if type(rows) is not dict or type(hashes) is not dict or set(rows) != set(ccref_BASE.RUNS["dfpt_650_k16"]["files"]):
        raise ccref_CandidateReferenceError(f"{run_id}: candidate DFPT source set is incomplete")
    if set(hashes) != set(rows):
        raise ccref_CandidateReferenceError(f"{run_id}: parsed native member list differs from evidence rows")
    for name, row in rows.items():
        if (type(row) is not dict or row.get("path", "").split("/")[-2] != run_id or
                type(row.get("job_id")) is not str or not row["job_id"].isdigit() or
                row.get("sha256") != hashes.get(name) or type(row.get("bytes")) is not int):
            raise ccref_CandidateReferenceError(f"{run_id}: native member source join is invalid at {name}")
    prov = record.get("result", {}).get("provenance")
    if (type(prov) is not dict or prov.get("receipt_status_raw") != "FINISHED" or
            prov.get("receipt_exit_code_raw") != 0 or prov.get("slurm_job_id_raw") not in
            {row.get("job_id") for row in rows.values()}):
        raise ccref_CandidateReferenceError(f"{run_id}: native execution receipt does not join candidate files")

def ccref__candidate_paw_signature(run_id: str, record: dict[str, Any]) -> tuple[str, ...]:
    raw = record.get("candidate_native_raw", {}).get("input-manifest.json")
    if type(raw) is not bytes:
        raise ccref_CandidateReferenceError(f"{run_id}: candidate source-bound input manifest is unavailable")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ccref_CandidateReferenceError(f"{run_id}: candidate input manifest is malformed") from exc
    method = manifest.get("method") if type(manifest) is dict else None
    hashes = manifest.get("paw_sha256_ordered") if type(manifest) is dict else None
    potentials = method.get("potentials") if type(method) is dict else None
    if (type(hashes) is not list or len(hashes) != 2 or
            any(type(value) is not str or len(value) != 64 or
                any(char not in "0123456789abcdef" for char in value) for value in hashes) or
            type(potentials) is not list or len(potentials) != 2 or
            [item.get("sha256") for item in potentials if type(item) is dict] != hashes):
        raise ccref_CandidateReferenceError(f"{run_id}: candidate ordered PAW identity is malformed or inconsistent")
    descriptor = record.get("result", {}).get("provenance", {}).get("method_descriptor_raw")
    if (type(descriptor) is not dict or method.get("xc") != descriptor.get("xc") or
            method.get("paw_family") != descriptor.get("paw_family") or
            method.get("potcar_order") != descriptor.get("potcar_order")):
        raise ccref_CandidateReferenceError(f"{run_id}: native method descriptor disagrees with candidate input manifest")
    return tuple(hashes)

def ccref__candidate_dfpt(native: dict[str, dict[str, Any]]) -> dict[str, tuple[str, dict[str, Any]]]:
    matched: dict[str, tuple[str, dict[str, Any]]] = {}
    geometry: tuple[Any, Any, Any] | None = None
    paw_signatures: set[tuple[str, ...]] = set()
    for run_id, record in native.items():
        meta = record.get("manifest_metadata")
        if type(meta) is not dict or meta.get("stage_kind") != "dfpt":
            continue
        if (type(meta.get("encut_ev")) not in (int, float) or meta["encut_ev"] <= 0 or
                type(meta.get("mesh")) is not list or len(meta["mesh"]) != 3 or
                any(type(n) is not int or n <= 0 for n in meta["mesh"])):
            raise ccref_CandidateReferenceError(f"{run_id}: actual ENCUT/KPOINTS setting metadata is malformed")
        ccref__source_integrity(run_id, record)
        response_controls = ccref__response_setting_controls(record)
        if any(value is None for value in response_controls):
            raise ccref_CandidateReferenceError(
                f"{run_id}: native response-setting identity lacks effective LPEAD/IPEAD/LRPA")
        paw_signatures.add(ccref__candidate_paw_signature(run_id, record))
        if not ccref__semantic_method(record):
            raise ccref_CandidateReferenceError(f"{run_id}: unsupported candidate XC/engine/ordered PAW identity")
        hashes = record["result"]["source_hashes"]
        if (meta.get("source_poscar_sha256") != hashes.get("POSCAR") or
                meta.get("parent_geometry_sha256") != hashes.get("POSCAR") or
                meta.get("relaxed_geometry_sha256") != hashes.get("POSCAR")):
            raise ccref_CandidateReferenceError(f"{run_id}: candidate DFPT manifest geometry hashes do not join its submitted POSCAR")
        initial = ccref__field(record, "structure.initial_lattice", "vasprun.xml")
        initial_pos = ccref__field(record, "structure.initial_fractional_positions", "vasprun.xml")
        submitted = ccref__field(record, "structure.submitted_lattice", "POSCAR")
        submitted_pos = ccref__field(record, "structure.submitted_fractional_positions", "POSCAR")
        species = ccref__field(record, "structure.submitted_species_order", "POSCAR")
        if any(x is None or x.get("value") is None for x in (initial, initial_pos, submitted, submitted_pos, species)):
            raise ccref_CandidateReferenceError(f"{run_id}: candidate native omits required source-bound parent geometry")
        if not ccref_BASE._matrix_equal(initial["value"], submitted["value"], 1e-6):
            raise ccref_CandidateReferenceError(f"{run_id}: DFPT initial cell differs from submitted parent cell")
        if (not ccref__same_fractional_positions(initial_pos.get("value"), submitted_pos.get("value")) or
                species.get("value") != ["Ga", "As"]):
            raise ccref_CandidateReferenceError(f"{run_id}: DFPT parent positions/species differ from submitted POSCAR")
        current_geometry = (submitted["value"], submitted_pos["value"], species["value"])
        if geometry is not None and current_geometry != geometry:
            raise ccref_CandidateReferenceError("candidate DFPT settings do not share the same parent geometry")
        geometry = current_geometry
        occupations = record.get("fields", {}).get("band.occupations")
        termination = record.get("result", {}).get("termination_observations", {}).get("electronic")
        availability = record.get("result", {}).get("response_availability", {})
        gap = ccref__field(record, "band.fundamental_gap", "vasprun.xml")
        direct = ccref__field(record, "band.direct_gap", "vasprun.xml")
        high = ccref__field(record, "dielectric.epsilon_high", "OUTCAR")
        ionic = ccref__field(record, "dielectric.epsilon_ionic", "OUTCAR")
        static = ccref__field(record, "dielectric.epsilon_static_observed_sum", "OUTCAR")
        if (type(occupations) is not dict or type(occupations.get("value")) is not dict or
                occupations["value"].get("fractional_state_count") != 0 or
                termination != "EDIFF_REACHED_MARKER_OBSERVED" or availability.get("lepsilon_requested") is not True):
            raise ccref_CandidateReferenceError(f"{run_id}: candidate native is metallic, unconverged, or not DFPT")
        if gap is None or direct is None or any(x is None for x in (high, ionic, static)):
            raise ccref_CandidateReferenceError(f"{run_id}: candidate native omits required gap or dielectric observations")
        if any(not ccref_BASE._matrix_equal(static["value"], [[high["value"][i][j] + ionic["value"][i][j]
                                                            for j in range(3)] for i in range(3)], 1e-5)
               for _ in (0,)):
            raise ccref_CandidateReferenceError(f"{run_id}: candidate static dielectric is not its same-run epsilon sum")
        if run_id in matched:
            raise ccref_CandidateReferenceError(f"candidate contains duplicate native run id {run_id}")
        incar = record.get("result", {}).get("incar_observations", {})
        encut = incar.get("ENCUT", {})
        if (type(encut) is not dict or not ccref_BASE._close(encut.get("value"), meta["encut_ev"], 1e-8)):
            raise ccref_CandidateReferenceError(f"{run_id}: manifest ENCUT differs from parsed native INCAR")
        raw_kpoints = record.get("candidate_native_raw", {}).get("KPOINTS")
        if type(raw_kpoints) is not bytes:
            raise ccref_CandidateReferenceError(f"{run_id}: candidate native KPOINTS source is unavailable")
        lines = raw_kpoints.decode("utf-8", errors="strict").splitlines()
        if len(lines) < 4:
            raise ccref_CandidateReferenceError(f"{run_id}: KPOINTS automatic mesh block is malformed")
        if lines[1].strip() != "0" or lines[2].strip().lower() not in {"gamma", "monkhorst-pack"}:
            raise ccref_ReferenceEnvironmentError(f"{run_id}: candidate KPOINTS syntax is outside the supported automatic-mesh parser")
        try:
            actual_mesh = [int(x) for x in lines[3].split()]
        except ValueError as exc:
            raise ccref_CandidateReferenceError(f"{run_id}: KPOINTS mesh is not an integer triplet") from exc
        if actual_mesh != meta["mesh"]:
            raise ccref_CandidateReferenceError(f"{run_id}: manifest mesh differs from native KPOINTS")
        if run_id in matched:
            raise ccref_CandidateReferenceError(f"candidate contains duplicate native run id {run_id}")
        matched[run_id] = (run_id, record)
    if len(paw_signatures) > 1:
        raise ccref_CandidateReferenceError("candidate DFPT settings mix ordered PAW identities")
    return matched

def ccref__value_for_ids(params: dict[str, Any], native: dict[str, dict[str, Any]], matched: dict[str, Any],
                   field: str, files: tuple[str, ...]) -> tuple[str, dict[str, Any]]:
    ids = params.get("source_ids")
    if type(ids) is not list or not ids or len(set(ids)) != len(ids):
        raise ccref_CandidateReferenceError(f"{field}: invalid native source_ids")
    found = []
    for key, (run_id, record) in matched.items():
        rows = record["evidence_rows"]
        required = {rows[name]["source_id"] for name in files}
        if required.issubset(set(ids)) and set(ids).issubset(set(record.get("source_ids", []))):
            found.append((key, record))
    if len(found) != 1:
        raise ccref_CandidateReferenceError(f"{field}: source_ids must resolve to one candidate setting")
    return found[0]

def ccref__native_matrix_qualification(field: str, candidate: dict[str, Any], observed: dict[str, Any],
                                 references: list[float]) -> None:
    if not ccref_BASE._matrix_equal(candidate.get("matrix"), observed.get("value"), ccref_BASE.PARAMETER_TOLERANCE):
        raise ccref_CandidateReferenceError(f"{field}: reported tensor differs from its linked native observation")
    if not any(ccref_BASE._matrix_equal(candidate.get("matrix"), ccref_BASE._scalar_tensor(reference),
                                  max(ccref_BASE.DIELECTRIC_ABS_TOLERANCE,
                                      ccref_BASE.DIELECTRIC_REL_TOLERANCE * abs(reference)))
                                  for reference in references):
        raise ccref_CandidateReferenceError(f"{field}: candidate tensor is outside the qualified reference-family tolerance")

def ccref__reference_matrix(actual: Any, values: list[float]) -> bool:
    return any(ccref_BASE._matrix_equal(actual, ccref_BASE._scalar_tensor(value),
                                  max(ccref_BASE.DIELECTRIC_ABS_TOLERANCE,
                                      ccref_BASE.DIELECTRIC_REL_TOLERANCE * abs(value))) for value in values)

def ccref__run_for_sources(matched: dict[str, tuple[str, dict[str, Any]]], source_ids: Any,
                     required_names: tuple[str, ...]) -> tuple[str, dict[str, Any]] | None:
    if type(source_ids) is not list or not source_ids or len(set(source_ids)) != len(source_ids):
        return None
    hits = []
    for run_id, record in matched.values():
        rows = record["evidence_rows"]
        required = {rows[name]["source_id"] for name in required_names}
        own = set(record.get("source_ids", []))
        if required.issubset(set(source_ids)) and set(source_ids).issubset(own):
            hits.append((run_id, record))
    return hits[0] if len(hits) == 1 else None

def ccref__method_id(record: dict[str, Any]) -> str:
    method = record["result"]["method"]
    provenance = record["result"]["provenance"]["method_descriptor_raw"]
    return f"VASP-{method['engine_version']}/PBE/PBE.54/{'+'.join(provenance['potcar_order'])}"

def ccref__semantic_method_id(record: dict[str, Any]) -> tuple[Any, ...]:
    method = record["result"]["method"]
    provenance = record["result"]["provenance"]["method_descriptor_raw"]
    return ("VASP", method["engine_version"].split(".", 1)[0], "PBE", "PBE.54",
            tuple(provenance["potcar_order"]))

def ccref__response_setting_controls(record: dict[str, Any]) -> tuple[Any, ...]:
    """Return effective PEAD/local-field controls from parsed native layers and OUTCAR."""
    names = ("LPEAD", "IPEAD", "LRPA")
    result = record.get("result", {})
    layers = result.get("native_control_layers", {}).get("values_by_source", {})
    raw_outcar = record.get("candidate_native_raw", {}).get("OUTCAR")
    outcar_values: dict[str, list[Any]] = {name: [] for name in names}
    if type(raw_outcar) is bytes:
        import re
        patterns = {
            "LPEAD": re.compile(rb"^\s*LPEAD\s*=\s*(\.TRUE\.|\.FALSE\.|T|F)(?=\s|$)", re.I),
            "IPEAD": re.compile(rb"^\s*IPEAD\s*=\s*([+-]?\d+)\b", re.I),
            "LRPA": re.compile(rb"^\s*LRPA\s*=\s*(\.TRUE\.|\.FALSE\.|T|F)(?=\s|$)", re.I),
        }
        for line in raw_outcar.splitlines():
            for name, pattern in patterns.items():
                match = pattern.match(line)
                if match:
                    token = match.group(1).decode("ascii").upper()
                    outcar_values[name].append(
                        token in {".TRUE.", "T"} if name != "IPEAD" else int(token))

    observed = []
    for name in names:
        values = []
        for layer in layers.values() if type(layers) is dict else ():
            if type(layer) is dict and name in layer:
                values.append(layer[name])
        values.extend(outcar_values[name])
        # Missing legacy fixture controls are represented explicitly; real
        # candidate response archives carry these in XML and/or OUTCAR.
        normalized = set(values)
        if len(normalized) > 1:
            raise ccref_CandidateReferenceError(f"candidate native settings disagree on effective {name}")
        observed.append(next(iter(normalized)) if normalized else None)
    return tuple(observed)

def ccref__setting_fingerprint(record: dict[str, Any]) -> tuple[Any, ...]:
    meta = record["manifest_metadata"]
    incar = record.get("result", {}).get("incar_observations", {})
    keys = ("ISMEAR", "SIGMA", "PREC", "EDIFF", "LREAL", "ALGO", "ISYM", "LEPSILON")
    controls = tuple((key, incar.get(key, {}).get("value")
                      if type(incar.get(key)) is dict else None) for key in keys)
    return float(meta["encut_ev"]), tuple(meta["mesh"]), controls, ccref__response_setting_controls(record)

def ccref__component_convergence_ready(component: dict[str, Any], *, allow_not_applicable: bool = False) -> bool:
    status = component.get("amplitude_convergence_status")
    return status == "QUALIFIED" or (allow_not_applicable and status == "NOT_APPLICABLE")

def ccref__same_fractional_positions(left: Any, right: Any) -> bool:
    if type(left) is not list or type(right) is not list or len(left) != len(right):
        return False
    for arow, brow in zip(left, right):
        if type(arow) is not list or type(brow) is not list or len(arow) != 3 or len(brow) != 3:
            return False
        if any(abs((float(a) - float(b)) - round(float(a) - float(b))) > 1e-6
               for a, b in zip(arow, brow)):
            return False
    return True

def ccref__ref_values(name: str) -> list[float]:
    return [float(row[name]) for row in ccref_BASE.RUNS.values()]

def ccref__near_any(value: float, refs: list[float], absolute: float, relative: float) -> bool:
    return any(ccref_BASE._within_reference(float(value), ref, absolute, relative) for ref in refs)

def ccref__candidate_pop(record: dict[str, Any]) -> dict[str, Any]:
    raw_xml = record.get("candidate_native_raw", {}).get("vasprun.xml")
    if ccref_POP is None:
        raise ccref_ReferenceEnvironmentError("candidate native POP math dependency unavailable")
    if type(raw_xml) is not bytes:
        raise ccref_CandidateReferenceError("candidate POP native XML source is unavailable")
    try:
        root = ET.fromstring(raw_xml)
        dyn = root.findall(".//dynmat")
        if len(dyn) != 1:
            raise ccref_CandidateReferenceError("candidate native XML lacks a unique dynamical matrix")
        hnode = dyn[0].find("./varray[@name='hessian']")
        if hnode is None:
            raise ccref_CandidateReferenceError("candidate native XML lacks a raw Gamma Hessian")
        hessian, radius = ccref_POP.xml_rows(hnode, 6, 6)
        hermitian_residual = float(abs(hessian - hessian.T).max())
        if hermitian_residual > 2.0 * float(radius) + 1e-12:
            raise ccref_CandidateReferenceError("candidate raw Gamma Hessian is not Hermitian within its printed-value interval")
        result = ccref_POP.pop_input({"files": {"vasprun.xml": raw_xml}})
    except ccref_CandidateReferenceError:
        raise
    except Exception as exc:
        raise ccref_CandidateReferenceError(f"candidate native Gamma response is malformed: {exc}") from exc
    result["raw_hessian_hermitian_residual_thz2"] = hermitian_residual
    result["raw_hessian_print_radius_thz2"] = float(radius)
    return result

def ccref__source_soc_enabled(record: dict[str, Any]) -> bool:
    layers = record.get("result", {}).get("native_control_layers", {}).get("values_by_source", {})
    controls = record.get("result", {}).get("incar_observations", {})
    values = []
    for key in ("LSORBIT", "LNONCOLLINEAR"):
        observed = []
        if type(controls.get(key)) is dict:
            observed.append(controls[key].get("value"))
        for source in ("INCAR", "vasprun.xml/incar", "vasprun.xml/parameters"):
            source_values = layers.get(source, {}) if type(layers) is dict else {}
            if key in source_values:
                observed.append(source_values[key])
        if any(type(value) is not bool for value in observed):
            raise ccref_CandidateReferenceError(f"candidate {key} control is not a native logical value")
        if observed and any(value != observed[0] for value in observed[1:]):
            raise ccref_CandidateReferenceError(f"candidate {key} native control sources disagree")
        # VASP's documented defaults for omitted SOC controls are false.
        values.append(observed[0] if observed else False)
    return any(values)

def ccref__derive_candidate_elastic_setting(native: dict[str, dict[str, Any]], source_ids: list[str]) -> tuple[float, list[list[float]]] | None:
    """Rebuild one source-cited relaxed-ion strain-amplitude tensor."""
    rows = []
    for run_id, record in ccref_BASE._candidate_records(native, source_ids):
        meta = record.get("manifest_metadata")
        if type(meta) is not dict or meta.get("stage_kind") != "elastic_finite_strain":
            continue
        ccref_BASE._require_run_source_ids(record, set(source_ids), ("OUTCAR", "POSCAR"),
                                     "elastic finite-strain setting")
        stress = ccref__field(record, "stress.force_on_cell", "OUTCAR")
        lattice = ccref__field(record, "structure.submitted_lattice", "POSCAR")
        if stress is None or lattice is None or stress.get("value") is None or lattice.get("value") is None:
            raise ccref_CandidateReferenceError("elastic setting source omits native stress or submitted lattice")
        termination = ccref__field(record, "convergence.ionic_relaxation_termination", "OUTCAR")
        if termination is None or termination.get("value") != "OBSERVED_RELAXED_ION_CONVERGENCE":
            raise ccref_CandidateReferenceError("elastic setting includes a non-relaxed-ion source")
        rows.append({"run_id": run_id, "record": record, "meta": meta,
                     "stress": stress["value"], "lattice": lattice["value"]})
    if not rows:
        return None
    bulk = min(rows, key=lambda row: sum(
        ccref_BASE._strain_coordinate(ccref_BASE._strain_from_lattices(row["lattice"], other["lattice"]), name) ** 2
        for other in rows for name in ccref_BASE.DEFORMATION_COMPONENTS))
    grouped: dict[str, dict[int, dict[str, Any]]] = {}
    amplitudes: set[float] = set()
    for row in rows:
        strain = ccref_BASE._strain_from_lattices(bulk["lattice"], row["lattice"])
        coords = {name: ccref_BASE._strain_coordinate(strain, name) for name in ccref_BASE.DEFORMATION_COMPONENTS}
        active = [(name, value) for name, value in coords.items() if abs(value) > 5e-5]
        if not active:
            continue
        if len(active) != 1 or any(abs(value) > 1e-5 for name, value in coords.items()
                                   if name != active[0][0]):
            raise ccref_CandidateReferenceError("elastic setting contains a mixed or unsupported strain")
        component, coordinate = active[0]
        amplitude = round(abs(coordinate), 4)
        amplitudes.add(amplitude)
        sides = grouped.setdefault(component, {})
        side = 1 if coordinate > 0 else -1
        if side in sides:
            raise ccref_CandidateReferenceError("elastic setting repeats a signed strain endpoint")
        sides[side] = {**row, "coordinate": coordinate}
    if len(amplitudes) != 1 or set(grouped) != set(ccref_BASE.DEFORMATION_COMPONENTS) or any(
            set(sides) != {-1, 1} for sides in grouped.values()):
        raise ccref_CandidateReferenceError("elastic setting source_ids must bind one complete six-component signed amplitude")
    matrix = [[0.0] * 6 for _ in range(6)]
    amplitude = next(iter(amplitudes))
    for component, sides in grouped.items():
        minus, plus = sides[-1], sides[1]
        dx = plus["coordinate"] - minus["coordinate"]
        s_minus = ccref_BASE._second_piola(minus["stress"], bulk["lattice"], minus["lattice"])
        s_plus = ccref_BASE._second_piola(plus["stress"], bulk["lattice"], plus["lattice"])
        column = ccref_BASE.DEFORMATION_COMPONENTS.index(component)
        for i in range(6):
            matrix[i][column] = (s_plus[i] - s_minus[i]) / dx
    return amplitude, matrix

def ccref__component_convergence_row(quantity: str, row: Any,
                               native: dict[str, dict[str, Any]]) -> bool:
    """Qualify scalar public convergence encodings against source-derived tensors."""
    if type(row) is not dict or type(row.get("settings")) is not list:
        return False
    values: list[tuple[str, str, Any, Any]] = []
    seen_ids: set[str] = set()
    for item in row["settings"]:
        if (type(item) is not dict or type(item.get("setting_id")) is not str or
                not item["setting_id"] or item["setting_id"] in seen_ids or
                type(item.get("method_id")) is not str or not item["method_id"]):
            raise ccref_CandidateReferenceError(f"{quantity}: malformed or duplicate setting identity")
        selected = ccref_BASE._candidate_records(native, item.get("source_ids"))
        if not selected:
            raise ccref_CandidateReferenceError(f"{quantity}: setting source_ids resolve no native rows")
        method_ids = {ccref__method_id(record) for _, record in selected}
        if method_ids != {item["method_id"]}:
            raise ccref_CandidateReferenceError(f"{quantity}: method_id differs from linked native source")
        fingerprints = {ccref__setting_fingerprint(record) for _, record in selected}
        if len(fingerprints) != 1:
            raise ccref_CandidateReferenceError(f"{quantity}: one setting mixes actual computational settings")

        if quantity == "elastic_C_GPa":
            totals = []
            for run_id, record in selected:
                obs = ccref__field(record, "elastic.relaxed_ion_total", "OUTCAR")
                if obs is not None and obs.get("value") is not None:
                    ccref_BASE._require_run_source_ids(record, set(item["source_ids"]), ("OUTCAR",), quantity)
                    totals.append((run_id, obs["value"]))
            if totals and len(totals) == len(selected):
                matrix = totals[0][1]
                if any(not all(ccref_BASE._close(matrix[i][j], other[1][i][j], ccref_BASE.PRINT_TOLERANCE)
                                   for i in range(6) for j in range(6)) for other in totals[1:]):
                    raise ccref_CandidateReferenceError(f"{quantity}: direct native totals conflict within one setting")
                # Direct TOTAL records are genuine independent settings; do
                # not pretend their source identity is a strain amplitude.
                setting_identity: Any = next(iter(fingerprints))
            elif totals:
                raise ccref_CandidateReferenceError(f"{quantity}: setting mixes direct TOTAL and stress-fit source rows")
            else:
                derived = ccref__derive_candidate_elastic_setting(native, item["source_ids"])
                if derived is None:
                    raise ccref_CandidateReferenceError(f"{quantity}: source group must resolve one native strain amplitude")
                setting_identity, matrix = derived
            actual = math.sqrt(sum(float(matrix[i][j]) ** 2 for i in range(6) for j in range(6)))
            if not ccref_BASE._close(item.get("value"), actual, ccref_BASE.PARAMETER_TOLERANCE):
                raise ccref_CandidateReferenceError(f"{quantity}: scalar does not equal the source-derived C Frobenius norm")
            values.append((item["setting_id"], "direct" if totals else "strain", matrix, setting_identity))
        else:
            source_ids = item["source_ids"]
            for _, record in selected:
                ccref_BASE._require_run_source_ids(record, set(source_ids), ("OUTCAR", "POSCAR", "vasprun.xml"), quantity)
            derived = ccref__derive_candidate_deformation(native, source_ids)
            if derived is None or len(derived["electron_D_by_amplitude"]) != 1:
                raise ccref_CandidateReferenceError(f"{quantity}: source group must resolve one native strain amplitude")
            amplitude, electron_by_component = next(iter(derived["electron_D_by_amplitude"].items()))
            if len(derived["hole_eigenvalue_derivatives_by_amplitude"]) != 1:
                raise ccref_CandidateReferenceError(f"{quantity}: source group resolves multiple strain amplitudes")
            hole_rows = next(iter(derived["hole_eigenvalue_derivatives_by_amplitude"].values()))
            normal = [hole_rows[name] for name in ("xx", "yy", "zz")]
            shear = [hole_rows[name] for name in ("xy", "xz", "yz")]
            hole_components = {
                "a": sum(sum(v) / 3.0 for v in normal) / 3.0,
                "b": sum(min(v) - sum(sorted(v)[1:]) / 2.0 for v in normal) / 3.0,
                # The convergence scalar uses |c|; sign qualification is
                # independently enforced by the candidate mirror proof.
                "c_abs": sum((max(v) - min(v)) / 2.0 for v in shear) / 3.0,
            }
            component_values = (electron_by_component if quantity == "electron_deformation"
                                else hole_components)
            actual = max(abs(float(value)) for value in component_values.values())
            if not ccref_BASE._close(item.get("value"), actual, ccref_BASE.PARAMETER_TOLERANCE):
                raise ccref_CandidateReferenceError(f"{quantity}: scalar differs from the source-derived component maximum")
            values.append((item["setting_id"], "amplitude", component_values, float(amplitude)))

        seen_ids.add(item["setting_id"])

    if len(values) < 2:
        return False
    if quantity == "elastic_C_GPa":
        if values[0][1] == "direct":
            if any(kind != "direct" for _, kind, _, _ in values) or len({identity for *_, identity in values}) < 2:
                raise ccref_CandidateReferenceError(f"{quantity}: direct totals require two distinct native settings")
        elif any(kind != "strain" for _, kind, _, _ in values) or len({identity for *_, identity in values}) < 2:
            raise ccref_CandidateReferenceError(f"{quantity}: strain-fit rows require two distinct source amplitudes")
        ok = True
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                first, second = values[i][2], values[j][2]
                ok = ok and all(ccref_BASE._within_reference(first[r][c], second[r][c],
                    ccref_BASE.ELASTIC_ABS_TOLERANCE_GPA, ccref_BASE.ELASTIC_REL_TOLERANCE)
                    for r in range(6) for c in range(6))
        return ok

    if len({round(float(identity), 10) for *_, identity in values}) < 2:
        raise ccref_CandidateReferenceError(f"{quantity}: settings do not resolve distinct native strain amplitudes")
    tolerance, relative = (ccref_BASE.DEFORMATION_ABS_TOLERANCE_EV, ccref_BASE.DEFORMATION_REL_TOLERANCE)
    ok = True
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            first, second = values[i][2], values[j][2]
            if set(first) != set(second):
                raise ccref_CandidateReferenceError(f"{quantity}: native settings have different component coverage")
            ok = ok and all(ccref_BASE._within_reference(first[key], second[key], tolerance, relative)
                            for key in first)
    return ok

def ccref__derive_candidate_deformation(native: dict[str, dict[str, Any]], source_ids: list[str]) -> dict[str, Any] | None:
    """Reuse frozen fit algebra while removing author-only stage/method labels."""
    selected = ccref_BASE._candidate_records(native, source_ids)
    adapted: dict[str, dict[str, Any]] = {}
    paw_signatures: set[tuple[str, ...]] = set()
    for run_id, original in selected:
        record = copy.deepcopy(original)
        fields = record.get("fields", {})
        gamma = ccref__field(record, "band.gamma_spectrum", "vasprun.xml")
        core = ccref__field(record, "core.site_1s_eigenenergies", "OUTCAR")
        lattice = ccref__field(record, "structure.submitted_lattice", "POSCAR")
        species = ccref__field(record, "structure.submitted_species_order", "POSCAR")
        if all(row is not None and row.get("value") is not None for row in (gamma, core, lattice, species)):
            ccref__source_integrity(run_id, record)
            if not ccref__semantic_method(record):
                raise ccref_CandidateReferenceError(f"{run_id}: unsupported candidate deformation method semantics")
            paw_signatures.add(ccref__candidate_paw_signature(run_id, record))
            metadata = record.setdefault("manifest_metadata", {})
            # The source layer treats these as parsed calculation facts; stage
            # labels are retained in the original record but do not decide the
            # mathematical route.
            metadata["stage_kind"] = "deformation"
            method = record["result"]["provenance"]["method_descriptor_raw"]
            record["result"]["provenance"]["method_descriptor_raw"] = {
                "xc": method.get("xc"), "paw_family": method.get("paw_family"),
                "potcar_order": method.get("potcar_order")}
        elif record.get("manifest_metadata", {}).get("stage_kind") == "deformation":
            raise ccref_CandidateReferenceError(f"{run_id}: candidate deformation native omits Gamma, core, or submitted-structure data")
        adapted[run_id] = record
    if len(paw_signatures) > 1:
        raise ccref_CandidateReferenceError("candidate deformation rows mix ordered PAW identities")
    return ccref_BASE._derive_deformation(adapted, source_ids)

def ccref__qualify_candidate_deformation(params: dict[str, Any], native: dict[str, dict[str, Any]]) -> dict[str, Any]:
    dp = params.get("deformation_potentials")
    if type(dp) is not dict or type(dp.get("electron")) is not dict or type(dp.get("hole")) is not dict:
        raise ccref_CandidateReferenceError("deformation candidate blocks are malformed")
    electron_block, hole_block = dp["electron"], dp["hole"]
    if any(type(dp[key].get("source_ids")) is not list for key in ("electron", "hole")):
        raise ccref_CandidateReferenceError("deformation source_ids are malformed")
    ids = list(dict.fromkeys(electron_block["source_ids"] + hole_block["source_ids"]))
    derived = ccref__derive_candidate_deformation(native, ids)
    if derived is None:
        raise ccref_ReferenceEnvironmentError("candidate has no supported source-bound finite-strain response")
    if ccref_DEFORMATION_PROOF is None or ccref_DEFORMATION_PROOF_RAW is None:
        raise ccref_CandidateReferenceError("candidate-native Gamma mirror proof is required for signed c_H")

    # Adapt parser observations to the proof module's narrow typed input. All
    # values remain source-bound to the seven native members parsed above.
    proof_native: dict[str, dict[str, Any]] = {}
    for run_id in derived["source_run_ids"]:
        record = native[run_id]
        gamma = ccref__field(record, "band.gamma_spectrum", "vasprun.xml")
        lattice = ccref__field(record, "structure.submitted_lattice", "POSCAR")
        if gamma is None or lattice is None:
            raise ccref_ReferenceEnvironmentError(f"{run_id}: candidate mirror proof inputs are unavailable")
        spins = gamma.get("value", {}).get("spins", [])
        bands = spins[0].get("bands", []) if len(spins) == 1 else []
        proof_native[run_id] = {
            "source_ids_by_name": {name: row["source_id"] for name, row in record["evidence_rows"].items()},
            "submitted_lattice": lattice.get("value"),
            "gamma_bands_one_based": {str(index + 1): {
                "energy_eV": band.get("energy_eV"), "occupation": band.get("occupation")}
                for index, band in enumerate(bands)},
            "spin_count": len(spins), "soc": ccref__source_soc_enabled(record),
            "band_edge_at_gamma": all(
                ccref__field(record, field_name, "vasprun.xml") is not None and
                ccref__field(record, field_name, "vasprun.xml")["value"].get("kpoint_index_0based") ==
                gamma.get("value", {}).get("kpoint_index_0based")
                for field_name in ("band.cbm", "band.vbm")),
            "method_identity": {"engine": record["result"]["method"].get("engine"),
                                "engine_version": record["result"]["method"].get("engine_version"),
                                "xc": "PBE", "paw_family": "PBE.54",
                                "potcar_order": record["result"]["provenance"]["method_descriptor_raw"].get("potcar_order")},
            "execution_receipt_raw": record.get("candidate_native_raw", {}).get("execution-receipt.json"),
        }
    try:
        sign_proof = ccref_DEFORMATION_PROOF.derive_candidate_c_h_sign(
            ccref_DEFORMATION_PROOF_RAW, proof_native, expected_bulk_run_id=derived["bulk_run_id"])
    except ccref_DEFORMATION_PROOF.CandidateProofError as exc:
        raise ccref_CandidateReferenceError(f"candidate mirror proof failed: {exc}") from exc

    requested = set(ids)
    for carrier, block in (("electron", electron_block), ("hole", hole_block)):
        rows = ccref_BASE._candidate_records(native, block["source_ids"])
        source_runs = {run_id for run_id, record in rows if all(
            name in record.get("evidence_rows", {}) and name in record.get("result", {}).get("source_hashes", {})
            for name in ("OUTCAR", "POSCAR", "vasprun.xml"))}
        if not set(derived["source_run_ids"]).issubset(source_runs):
            raise ccref_CandidateReferenceError(f"{carrier} deformation source_ids omit replayed native runs")
        for run_id, record in rows:
            if run_id in derived["source_run_ids"]:
                ccref_BASE._require_run_source_ids(record, set(block["source_ids"]),
                                             ("OUTCAR", "POSCAR", "vasprun.xml"),
                                             f"{carrier} candidate deformation run")
    if dp.get("energy_reference") != "common_all_atom_1s":
        raise ccref_ReferenceEnvironmentError("candidate deformation gauge is outside the currently supported common all-atom 1s route")
    amplitudes = sorted(derived["electron_D_by_amplitude"])
    if len(amplitudes) < 2:
        raise ccref_CandidateReferenceError("candidate deformation fit requires at least two source-derived amplitudes")

    electron_values = ccref_BASE._named_state_values(electron_block, "electron deformation", "value_eV")
    if set(electron_values) != set(ccref_BASE.DEFORMATION_COMPONENTS):
        raise ccref_ReferenceEnvironmentError("candidate electron response must use six named Cartesian components")
    electron_native: dict[str, float] = {}
    unconverged = []
    electron_reference = ccref_BASE.DEFORMATION_REFERENCE["cbm_D_mean_all_atom_1s_eV"]
    accepted_electron_values = {name: [row[name] for row in electron_reference.values()]
                                for name in ccref_BASE.DEFORMATION_COMPONENTS}
    for component in ccref_BASE.DEFORMATION_COMPONENTS:
        values = [derived["electron_D_by_amplitude"][amp][component] for amp in amplitudes]
        electron_native[component] = sum(values) / len(values)
        for left in range(len(values)):
            for right in range(left + 1, len(values)):
                if not ccref_BASE._within_reference(values[left], values[right], ccref_BASE.DEFORMATION_ABS_TOLERANCE_EV,
                                              ccref_BASE.DEFORMATION_REL_TOLERANCE):
                    unconverged.append({"carrier": "electron", "component": component,
                                        "amplitudes": [amplitudes[left], amplitudes[right]],
                                        "values_eV": [values[left], values[right]]})
        if any(not ccref_BASE._within_reference(electron_values[component], value,
                                          ccref_BASE.DEFORMATION_ABS_TOLERANCE_EV,
                                          ccref_BASE.DEFORMATION_REL_TOLERANCE) for value in values):
            raise ccref_CandidateReferenceError(f"electron {component} differs from candidate-native response")
        if not ccref__near_any(electron_values[component], accepted_electron_values[component],
                         ccref_BASE.DEFORMATION_ABS_TOLERANCE_EV, ccref_BASE.DEFORMATION_REL_TOLERANCE):
            raise ccref_CandidateReferenceError(f"electron {component} lies outside the qualified reference family")

    hole_values = ccref_BASE._named_state_values(hole_block, "hole deformation", "symmetry_invariant_eV")
    if set(hole_values) != {"a", "b", "c_signed"}:
        raise ccref_ReferenceEnvironmentError("candidate hole response must report a, b, and c_signed")
    hole_native = {}
    reference_hole = ccref_BASE.DEFORMATION_REFERENCE["hole_H_derivative_coefficients_eV"]
    accepted_hole_values = {key: [row[key] for row in reference_hole.values()]
                            for key in ("a", "b", "c_signed")}
    for amplitude in amplitudes:
        rows = derived["hole_eigenvalue_derivatives_by_amplitude"][amplitude]
        normal = [rows.get(name) for name in ("xx", "yy", "zz")]
        shear = [rows.get(name) for name in ("xy", "xz", "yz")]
        if any(value is None for value in normal + shear):
            raise ccref_ReferenceEnvironmentError("candidate Gamma response lacks six-component cubic coverage")
        a = sum(sum(values) / 3.0 for values in normal) / 3.0
        b = sum(sorted(values)[0] - sum(sorted(values)[1:]) / 2.0 for values in normal) / 3.0
        abs_c = sum((max(values) - min(values)) / 2.0 for values in shear) / 3.0
        hole_native[amplitude] = {"a": a, "b": b, "c_signed": sign_proof["c_h_sign"] * abs_c}
    for invariant in ("a", "b", "c_signed"):
        values = [hole_native[amp][invariant] for amp in amplitudes]
        for left in range(len(values)):
            for right in range(left + 1, len(values)):
                if not ccref_BASE._within_reference(values[left], values[right], ccref_BASE.DEFORMATION_ABS_TOLERANCE_EV,
                                              ccref_BASE.DEFORMATION_REL_TOLERANCE):
                    unconverged.append({"carrier": "hole", "invariant": invariant,
                                        "amplitudes": [amplitudes[left], amplitudes[right]],
                                        "values_eV": [values[left], values[right]]})
        if any(not ccref_BASE._within_reference(hole_values[invariant], value,
                                          ccref_BASE.DEFORMATION_ABS_TOLERANCE_EV,
                                          ccref_BASE.DEFORMATION_REL_TOLERANCE) for value in values):
            raise ccref_CandidateReferenceError(f"hole {invariant} differs from candidate-native Gamma response")
        if not ccref__near_any(hole_values[invariant], accepted_hole_values[invariant],
                         ccref_BASE.DEFORMATION_ABS_TOLERANCE_EV, ccref_BASE.DEFORMATION_REL_TOLERANCE):
            raise ccref_CandidateReferenceError(f"hole {invariant} lies outside the qualified reference family")
    return {"status": "QUALIFIED", "amplitudes": amplitudes,
            "amplitude_convergence_status": "QUALIFIED" if not unconverged else "NOT_QUALIFIED",
            "amplitude_convergence_unqualified_components": unconverged,
            "native_electron_D_by_amplitude": derived["electron_D_by_amplitude"],
            "native_hole_H_coefficients_by_amplitude": hole_native,
            "mirror_proof": sign_proof,
            "qualification_scope": "candidate native source-derived values match qualified numeric family; source-setting convergence is reported separately",
            "source_run_ids": derived["source_run_ids"], "bulk_run_id": derived["bulk_run_id"]}

def ccref_evaluate_component_references(params: dict[str, Any], convergence: dict[str, Any],
                                  native: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if ccref_BASE is None:
        raise ccref_ReferenceEnvironmentError("frozen science reference module was not bound")
    matched = ccref__candidate_dfpt(native)
    if len(matched) < 2:
        return {"schema": ccref_SCHEMA, "overall": "PARTIAL", "overall_scoring_ready": False,
                "dielectric": "NOT_EVALUATED", "analytic_q0_pop": "NOT_EVALUATED",
                "reason": "fewer than two source-qualified comparable candidate DFPT settings"}
    by_quantity = {row.get("quantity"): row for row in convergence.get("quantities", []) if type(row) is dict}
    conv_status: dict[str, bool] = {}
    semantic_methods = {ccref__semantic_method_id(record) for _, record in matched.values()}
    if len(semantic_methods) != 1:
        raise ccref_CandidateReferenceError("candidate DFPT settings mix method identities")
    quantity_names = ccref_PUBLIC_QUANTITY_NAMES
    for quantity in ("elastic_C_GPa", "electron_deformation", "hole_deformation"):
        row = by_quantity.get(quantity)
        ok = ccref__component_convergence_row(quantity, row, native)
        conv_status[quantity] = ok and type(row) is dict and row.get("claimed_converged") is True
        if type(row) is dict and row.get("claimed_converged") is True and not ok:
            raise ccref_CandidateReferenceError(f"{quantity}: claimed convergence exceeds source-derived component tolerances")
    for quantity in ("epsilon_high", "epsilon_static", "pbe_bandgap", "pbe_direct_gap", "pop_frequency"):
        row = by_quantity.get(quantity)
        if type(row) is not dict or type(row.get("settings")) is not list:
            conv_status[quantity] = False
            continue
        seen: set[str] = set()
        values: list[tuple[str, Any, float, float]] = []
        for item in row["settings"]:
            if type(item) is not dict or type(item.get("setting_id")) is not str or not item["setting_id"]:
                raise ccref_CandidateReferenceError(f"{quantity}: setting row lacks its source-derived method/setting identity")
            required_files = ("OUTCAR", "vasprun.xml") if quantity in {"pbe_bandgap", "pbe_direct_gap", "pop_frequency"} else ("OUTCAR",)
            selected = ccref__run_for_sources(matched, item.get("source_ids"), required_files)
            if selected is None:
                raise ccref_CandidateReferenceError(f"{quantity}: source_ids do not resolve one candidate native setting")
            run_id, record = selected
            if item.get("method_id") != ccref__method_id(record):
                raise ccref_CandidateReferenceError(f"{quantity}: method_id differs from the source-derived native method")
            if run_id in seen:
                raise ccref_CandidateReferenceError(f"{quantity}: duplicate source setting")
            if quantity.startswith("epsilon"):
                field = "dielectric.epsilon_high" if quantity == "epsilon_high" else "dielectric.epsilon_static_observed_sum"
                obs = ccref__field(record, field, "OUTCAR")
                actual = obs["value"]
                if not ccref_BASE._matrix_equal(item.get("value"), actual, ccref_BASE.PARAMETER_TOLERANCE):
                    raise ccref_CandidateReferenceError(f"{quantity}: row differs from linked candidate native tensor")
                refs = ccref__ref_values("epsilon_high" if quantity == "epsilon_high" else "epsilon_static")
                if not ccref__reference_matrix(actual, refs):
                    raise ccref_CandidateReferenceError(f"{quantity}: native setting is outside the qualified reference-family tolerance")
                value = actual
            elif quantity in {"pbe_bandgap", "pbe_direct_gap"}:
                field = "band.fundamental_gap" if quantity == "pbe_bandgap" else "band.direct_gap"
                actual = float(ccref__field(record, field, "vasprun.xml")["value"])
                if not ccref_BASE._close(item.get("value"), actual, ccref_BASE.PBE_GAP_NATIVE_MATCH_TOLERANCE_EV):
                    raise ccref_CandidateReferenceError(f"{quantity}: row differs from linked native spectrum")
                if quantity == "pbe_bandgap" and not ccref__near_any(actual, ccref__ref_values("pbe_gap_ev"),
                        ccref_BASE.PBE_GAP_SETTING_TOLERANCE_EV, 0.0):
                    raise ccref_CandidateReferenceError("PBE gap is outside the qualified reference-family tolerance")
                value = actual
            else:
                pop = ccref__candidate_pop(record)
                actual = float(pop["lo_thz"])
                if abs(float(item.get("value")) - actual) > ccref_BASE.PARAMETER_TOLERANCE:
                    raise ccref_CandidateReferenceError(f"{quantity}: row differs from candidate-native Gamma q->0 result")
                if quantity == "pop_frequency":
                    reference_ok = any(abs(actual - float(ref["pop_mean_thz"])) + float(pop["bound_thz"]) +
                                       float(ref["pop_bound_thz"]) <= max(ccref_BASE.POP_ABS_TOLERANCE_THz,
                                       ccref_BASE.POP_REL_TOLERANCE * max(abs(actual), abs(float(ref["pop_mean_thz"]))))
                                       for ref in ccref_BASE.RUNS.values())
                    if not reference_ok:
                        raise ccref_CandidateReferenceError("candidate-native POP differs from qualified reference family")
                value = actual
            bound = float(ccref__candidate_pop(record)["bound_thz"]) if quantity == "pop_frequency" else 0.0
            values.append((run_id, value,
                           float(item.get("claimed_tolerance", row.get("claimed_tolerance", 0.0))), bound))
            seen.add(run_id)
        if len(values) < 2:
            conv_status[quantity] = False
            continue
        if len({ccref__setting_fingerprint(matched[run_id][1]) for run_id, *_ in values}) < 2:
            conv_status[quantity] = False
            if row.get("claimed_converged") is True:
                raise ccref_CandidateReferenceError(f"{quantity}: claimed convergence lacks two distinct native settings")
            continue
        ok = True
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                a, b = values[i][1], values[j][1]
                if (ccref__setting_fingerprint(matched[values[i][0]][1]) ==
                        ccref__setting_fingerprint(matched[values[j][0]][1])):
                    continue
                if quantity.startswith("epsilon"):
                    ok = ok and all(abs(a[r][c] - b[r][c]) <= max(ccref_BASE.DIELECTRIC_ABS_TOLERANCE,
                        ccref_BASE.DIELECTRIC_REL_TOLERANCE * max(abs(a[r][c]), abs(b[r][c])))
                        for r in range(3) for c in range(3))
                elif quantity == "pop_frequency":
                    threshold = max(ccref_BASE.POP_ABS_TOLERANCE_THz,
                                    ccref_BASE.POP_REL_TOLERANCE * max(abs(float(a)), abs(float(b))))
                    delta = abs(float(a) - float(b))
                    if quantity == "pop_frequency":
                        delta += values[i][3] + values[j][3]
                    ok = ok and delta <= threshold
                else:
                    ok = ok and abs(float(a) - float(b)) <= ccref_BASE.PBE_GAP_SETTING_TOLERANCE_EV
        conv_status[quantity] = ok and row.get("claimed_converged") is True
        if row.get("claimed_converged") is True and not ok:
            raise ccref_CandidateReferenceError(f"{quantity}: claimed convergence exceeds the frozen source-setting tolerance")

    high = params.get("epsilon_high")
    static = params.get("epsilon_static")
    high_selected = ccref__run_for_sources(matched, high.get("source_ids") if type(high) is dict else None, ("OUTCAR",))
    static_selected = ccref__run_for_sources(matched, static.get("source_ids") if type(static) is dict else None, ("OUTCAR",))
    if high_selected is None or static_selected is None or high_selected[0] != static_selected[0]:
        raise ccref_CandidateReferenceError("candidate dielectric parameters must bind to one candidate native setting")
    high_obs = ccref__field(high_selected[1], "dielectric.epsilon_high", "OUTCAR")
    static_obs = ccref__field(static_selected[1], "dielectric.epsilon_static_observed_sum", "OUTCAR")
    ccref__native_matrix_qualification("epsilon_high", high, high_obs, ccref__ref_values("epsilon_high"))
    ccref__native_matrix_qualification("epsilon_static", static, static_obs, ccref__ref_values("epsilon_static"))
    pop = params.get("pop_frequency")
    pop_selected = ccref__run_for_sources(matched, pop.get("source_ids") if type(pop) is dict else None,
                                    ("OUTCAR", "vasprun.xml"))
    if pop_selected is None:
        raise ccref_CandidateReferenceError("candidate POP source_ids must bind to one candidate response setting")
    pop_actual = ccref__candidate_pop(pop_selected[1])
    if (type(pop) is not dict or abs(float(pop.get("value_THz")) - float(pop_actual["lo_thz"])) >
            ccref_BASE.PARAMETER_TOLERANCE):
        raise ccref_CandidateReferenceError("reported POP differs from candidate-native Gamma q->0 calculation")

    elastic_component = ccref_BASE._qualify_elastic(params, native)
    deformation_component = ccref__qualify_candidate_deformation(params, native)
    complete_quantities = all(conv_status.get(k) is True for k in quantity_names)
    complete_components = (elastic_component.get("status") == "QUALIFIED" and
                           deformation_component.get("status") == "QUALIFIED" and
                           ccref__component_convergence_ready(elastic_component,
                               allow_not_applicable=elastic_component.get("route") == "native_relaxed_ion_total") and
                           ccref__component_convergence_ready(deformation_component) and
                           all(conv_status.get(k) is True for k in
                               ("elastic_C_GPa", "electron_deformation", "hole_deformation")))
    scoring_ready = complete_quantities and complete_components
    return {"schema": ccref_SCHEMA, "overall": "QUALIFIED" if scoring_ready else "PARTIAL",
            "overall_scoring_ready": scoring_ready,
            "dielectric": "QUALIFIED" if conv_status.get("epsilon_high") and conv_status.get("epsilon_static") else "NOT_EVALUATED",
            "analytic_q0_pop": "QUALIFIED" if conv_status.get("pop_frequency") else "NOT_EVALUATED",
            "pbe_bandgap": "QUALIFIED" if conv_status.get("pbe_bandgap") else "NOT_EVALUATED",
            "pbe_direct_gap": "QUALIFIED" if conv_status.get("pbe_direct_gap") else "NOT_EVALUATED",
            "elastic": elastic_component, "band_edge_deformation": deformation_component,
            "method": "VASP/PBE/PBE.54/Ga_d+As (source-derived VASP 6 series)",
            "candidate_source_run_ids": [run_id for run_id, _ in matched.values()],
            "candidate_convergence_rows_match_native": conv_status}
# Inlined, namespaced scientific module: submission_provenance_v1.py
from pathlib import Path

from typing import Any

prov_SCHEMA = "case05-submission-provenance/v1"

prov_DESCRIPTOR_FIELDS = {"path", "sha256", "bytes"}

prov_RUN_FIELDS = {"run_id", "execution_receipt", "scheduler_record", "batch_script", "stdout", "stderr"}

prov_RECEIPT_FIELDS = {
    "schema", "job_id", "scheduler", "allocation_id", "allocation_is_array",
    "gpus", "cpus", "memory_bytes", "wall_seconds", "exit_code",
    "batch_script_sha256",
}

prov_SCHEDULER_FIELDS = {
    "schema", "job_id", "scheduler", "final_state", "allocation_id",
    "allocation_is_array", "gpus", "cpus", "memory_bytes", "wall_seconds",
    "exit_code", "start_utc", "end_utc",
}

prov_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

prov_JOB_RE = re.compile(r"^[0-9]{1,32}$")

prov_RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")

class prov_ProvenanceFailure(ValueError):
    """Candidate provenance is missing, malformed, or contradictory."""

def prov__digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def prov__strict_keys(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise prov_ProvenanceFailure(f"{label} has missing or unsupported fields")
    return value

def prov__time(token: Any, label: str) -> tuple[_datetime.datetime, int]:
    if type(token) is not str:
        raise prov_ProvenanceFailure(f"{label} must be an ISO timestamp")
    text = token[:-1] + "+00:00" if token.endswith("Z") else token
    try:
        value = _datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        raise prov_ProvenanceFailure(f"{label} is not a supported ISO timestamp") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise prov_ProvenanceFailure(f"{label} must include an explicit timezone")
    fractional = text.split(".", 1)
    precision = len(re.match(r"\d+", fractional[1]).group(0)) if len(fractional) == 2 and re.match(r"\d+", fractional[1]) else 0
    return value, precision

def prov__validate_common(row: dict[str, Any], label: str, *, timestamps: bool) -> None:
    if row["schema"] != f"case05-{label}/v1":
        raise prov_ProvenanceFailure(f"{label} schema version is unsupported")
    job = row["job_id"]
    if type(job) is not str or not prov_JOB_RE.fullmatch(job) or "_" in job or "." in job:
        raise prov_ProvenanceFailure(f"{label} job_id is malformed or identifies an array task")
    if type(row["scheduler"]) is not str or not row["scheduler"].strip():
        raise prov_ProvenanceFailure(f"{label} scheduler is missing")
    if type(row["allocation_id"]) is not str or not row["allocation_id"].strip():
        raise prov_ProvenanceFailure(f"{label} allocation_id is missing")
    if type(row["allocation_is_array"]) is not bool or row["allocation_is_array"]:
        raise prov_ProvenanceFailure(f"{label} allocation must be a non-array allocation")
    if type(row["gpus"]) is not int or row["gpus"] < 0:
        raise prov_ProvenanceFailure(f"{label} gpus must be a nonnegative integer")
    if type(row["cpus"]) is not int or row["cpus"] <= 0:
        raise prov_ProvenanceFailure(f"{label} cpus must be a positive integer")
    if type(row["memory_bytes"]) is not int or row["memory_bytes"] <= 0:
        raise prov_ProvenanceFailure(f"{label} memory_bytes must be a positive integer")
    wall = row["wall_seconds"]
    if type(wall) not in (int, float) or not math.isfinite(wall) or wall < 0:
        raise prov_ProvenanceFailure(f"{label} wall_seconds must be nonnegative")
    if type(row["exit_code"]) is not int:
        raise prov_ProvenanceFailure(f"{label} exit_code must be an integer")
    if timestamps:
        start, precision = prov__time(row["start_utc"], f"{label} start_utc")
        end, end_precision = prov__time(row["end_utc"], f"{label} end_utc")
        if end < start:
            raise prov_ProvenanceFailure(f"{label} end_utc precedes start_utc")
        delta = (end - start).total_seconds()
        tolerance = 10 ** (-max(precision, end_precision))
        if abs(delta - float(wall)) > tolerance:
            raise prov_ProvenanceFailure(f"{label} wall_seconds differs from printed timestamps")

def prov_validate_run_records(receipt: Any, scheduler: Any, batch_sha256: str,
                         batch_script: bytes = b"") -> dict[str, Any]:
    """Validate the two candidate-supplied execution records and their joins."""
    if type(receipt) is not dict or set(receipt) not in (prov_RECEIPT_FIELDS, prov_RECEIPT_FIELDS | {"role"}):
        raise prov_ProvenanceFailure("execution receipt has missing or unsupported fields")
    if type(scheduler) is not dict or set(scheduler) not in (prov_SCHEDULER_FIELDS, prov_SCHEDULER_FIELDS | {"raw_scheduler_log"}):
        raise prov_ProvenanceFailure("scheduler record has missing or unsupported fields")
    prov__validate_common(receipt, "execution-receipt", timestamps=False)
    prov__validate_common(scheduler, "scheduler-record", timestamps=True)
    if "role" in receipt and (type(receipt["role"]) is not str or not receipt["role"].strip()):
        raise prov_ProvenanceFailure("execution receipt role must be nonempty text")
    if type(receipt["batch_script_sha256"]) is not str or not prov_SHA_RE.fullmatch(receipt["batch_script_sha256"]):
        raise prov_ProvenanceFailure("execution receipt batch_script_sha256 is malformed")
    if receipt["batch_script_sha256"] != batch_sha256:
        raise prov_ProvenanceFailure("execution receipt does not bind the submitted batch script")
    if not batch_script.strip():
        raise prov_ProvenanceFailure("submitted batch script is empty")
    if re.search(rb"(?im)^[ \t]*#SBATCH[ \t]+--array(?=[ \t=]|$)", batch_script):
        raise prov_ProvenanceFailure("submitted Slurm script requests an array but records a non-array allocation")
    for key in ("job_id", "scheduler", "allocation_id", "allocation_is_array", "gpus", "cpus",
                "memory_bytes", "wall_seconds", "exit_code"):
        if receipt[key] != scheduler[key]:
            raise prov_ProvenanceFailure(f"execution receipt and scheduler record disagree on {key}")
    if receipt["scheduler"].lower() != "slurm":
        raise prov_ProvenanceFailure("unsupported scheduler provenance; numeric Slurm job IDs are required")
    if not prov_JOB_RE.fullmatch(receipt["allocation_id"]) or receipt["allocation_id"] != receipt["job_id"]:
        raise prov_ProvenanceFailure("Slurm allocation_id must equal its numeric base job_id")
    if scheduler["final_state"] not in {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "PREEMPTED"}:
        raise prov_ProvenanceFailure("scheduler final_state is unsupported")
    if scheduler["final_state"] != "COMPLETED" or receipt["exit_code"] != 0:
        raise prov_ProvenanceFailure("scheduler job did not complete successfully")
    return receipt

def prov_validate_raw_scheduler_log(data: bytes, receipt: dict[str, Any]) -> None:
    """Cross-check job/array identity when a raw log exposes parseable fields."""
    text = data.decode("utf-8", "replace")
    found_ids = re.findall(r"(?im)\b(?:JobID|JobId|Job_ID|JobIDRaw)\s*[=:]\s*([0-9]+(?:_[0-9]+)?(?:\.[A-Za-z0-9_-]+)?)", text)
    found_ids.extend(re.findall(r"(?im)\bSubmitted batch job\s+([0-9]+(?:_[0-9]+)?)", text))
    for token in found_ids:
        if "_" in token or token.split(".", 1)[0] != receipt["job_id"]:
            raise prov_ProvenanceFailure("raw scheduler log job identity contradicts the recorded allocation")
    array_tokens = re.findall(r"(?im)\bArrayTaskId\s*[=:]\s*([^\s|,]+)", text)
    if any(token not in {"", "N/A", "4294967294", "-1"} for token in array_tokens):
        raise prov_ProvenanceFailure("raw scheduler log identifies an array task")

def prov_validate_native_receipt_span(native_receipt: dict[str, Any], scheduler: dict[str, Any]) -> None:
    """If native receipt timestamps exist, require them within allocation time."""
    start_token, end_token = native_receipt.get("start_utc"), native_receipt.get("end_utc")
    if start_token is None and end_token is None:
        return
    native_start, _ = prov__time(start_token, "native receipt start_utc")
    native_end, _ = prov__time(end_token, "native receipt end_utc")
    scheduler_start, _ = prov__time(scheduler["start_utc"], "scheduler start_utc")
    scheduler_end, _ = prov__time(scheduler["end_utc"], "scheduler end_utc")
    if native_end < native_start or native_start < scheduler_start or native_end > scheduler_end:
        raise prov_ProvenanceFailure("native receipt time range contradicts scheduler allocation span")

def prov_validate_descriptor(descriptor: Any, final_dir: Path, verify_module: Any, label: str) -> tuple[bytes, dict[str, Any]]:
    descriptor = prov__strict_keys(descriptor, prov_DESCRIPTOR_FIELDS, f"{label} descriptor")
    path = descriptor["path"]
    if type(path) is not str or not path or path.startswith("/") or "\\" in path:
        raise prov_ProvenanceFailure(f"{label} path must be a safe relative path")
    parts = Path(path).parts
    if any(part in ("", ".", "..") for part in parts):
        raise prov_ProvenanceFailure(f"{label} path is not canonical")
    try:
        data = verify_module.read_candidate_member(final_dir, "native/" + path, max_bytes=16 * 1024 * 1024)
    except Exception as exc:
        raise prov_ProvenanceFailure(f"{label} attachment is missing or unsafe") from exc
    if type(descriptor["bytes"]) is not int or descriptor["bytes"] != len(data):
        raise prov_ProvenanceFailure(f"{label} attachment byte count mismatch")
    if type(descriptor["sha256"]) is not str or not prov_SHA_RE.fullmatch(descriptor["sha256"]):
        raise prov_ProvenanceFailure(f"{label} attachment hash is malformed")
    if prov__digest(data) != descriptor["sha256"]:
        raise prov_ProvenanceFailure(f"{label} attachment hash mismatch")
    return data, descriptor

def prov_validate_manifest(final_dir: Path, verify_module: Any, run_ids: list[str]) -> dict[str, Any]:
    raw = verify_module.read_candidate_member(final_dir, "native/provenance-manifest.json", max_bytes=2 * 1024 * 1024)
    try:
        manifest = verify_module.strict_json(raw, max_bytes=2 * 1024 * 1024)
    except Exception as exc:
        raise prov_ProvenanceFailure("provenance manifest is not strict JSON") from exc
    if type(manifest) is not dict or set(manifest) != {"schema", "execution_order", "runs"}:
        raise prov_ProvenanceFailure("provenance manifest schema fields mismatch")
    if manifest["schema"] != prov_SCHEMA or type(manifest["runs"]) is not list:
        raise prov_ProvenanceFailure("provenance manifest schema/version mismatch")
    if (type(manifest["execution_order"]) is not list or
            any(type(x) is not str or not prov_RUN_RE.fullmatch(x) for x in run_ids) or
            len(set(run_ids)) != len(run_ids) or
            any(type(x) is not str or not prov_RUN_RE.fullmatch(x) for x in manifest["execution_order"]) or
            len(set(manifest["execution_order"])) != len(manifest["execution_order"] or []) or
            len(manifest["execution_order"]) != len(run_ids) or
            set(manifest["execution_order"]) != set(run_ids)):
        raise prov_ProvenanceFailure("execution_order must be a unique complete permutation of native run IDs")
    if len(manifest["runs"]) != len(run_ids):
        raise prov_ProvenanceFailure("provenance run coverage differs from native manifest")
    seen: set[str] = set()
    for run in manifest["runs"]:
        run = prov__strict_keys(run, prov_RUN_FIELDS, "provenance run")
        if type(run["run_id"]) is not str or run["run_id"] not in run_ids or run["run_id"] in seen:
            raise prov_ProvenanceFailure("provenance run IDs must uniquely cover native manifest runs")
        seen.add(run["run_id"])
    if seen != set(run_ids):
        raise prov_ProvenanceFailure("provenance run coverage differs from native manifest")
    return manifest

def prov_validate_execution_order(scheduler_by_run: dict[str, dict[str, Any]], order: list[str]) -> None:
    """Require declared runs to be chronological without tying run-array order."""
    previous = None
    for run_id in order:
        token = scheduler_by_run[run_id]["start_utc"]
        text = token[:-1] + "+00:00" if token.endswith("Z") else token
        stamp = _datetime.datetime.fromisoformat(text)
        if previous is not None and stamp < previous:
            raise prov_ProvenanceFailure("scheduler start times contradict declared execution_order")
        previous = stamp

_VERIFIER_API = SimpleNamespace(**globals().copy())

_ADAPTER = SimpleNamespace(**{k[3:]: v for k, v in globals().copy().items() if k.startswith("ad_")})
_REFERENCE = SimpleNamespace(**{k[4:]: v for k, v in globals().copy().items() if k.startswith("ref_")})
_POP = SimpleNamespace(**{k[4:]: v for k, v in globals().copy().items() if k.startswith("pop_")})
_PROOF = SimpleNamespace(**{k[6:]: v for k, v in globals().copy().items() if k.startswith("proof_")})
_CANDIDATE_COMPONENT = SimpleNamespace(**{k[5:]: v for k, v in globals().copy().items() if k.startswith("ccref_")})
_PROVENANCE = SimpleNamespace(**{k[5:]: v for k, v in globals().copy().items() if k.startswith("prov_")})
ccref_bind_reference(_REFERENCE)
ccref_bind_pop(_POP)
_CANDIDATE_COMPONENT.BASE = _REFERENCE
_CANDIDATE_COMPONENT.CandidateReferenceError = _REFERENCE.CandidateReferenceError
_CANDIDATE_COMPONENT.ReferenceEnvironmentError = _REFERENCE.ReferenceEnvironmentError

def _candidate_groups(final: Path, verify: Any) -> tuple[dict[str, dict[str, dict[str, Any]]], list[str]]:
    raw = verify.read_candidate_member(final, "native/manifest.json", max_bytes=2 * 1024 * 1024)
    try:
        manifest = verify.strict_json(raw, max_bytes=2 * 1024 * 1024)
    except Exception as exc:
        raise verify.CandidateFailure("native manifest is not strict JSON") from exc
    if (type(manifest) is not dict or set(manifest) != {"schema", "runs"} or
            manifest.get("schema") != verify.NATIVE_LINK_SCHEMA or type(manifest["runs"]) is not list or
            not manifest["runs"]):
        raise verify.CandidateFailure("native manifest schema mismatch")
    run_ids = []
    for run in manifest["runs"]:
        if type(run) is not dict or set(run) != {"run_id", "files"}:
            raise verify.CandidateFailure("native run link has unsupported fields")
        run_ids.append(run["run_id"])

    provenance_manifest = _PROVENANCE.validate_manifest(final, verify, run_ids)
    records_by_run: dict[str, dict[str, Any]] = {}
    scheduler_by_run: dict[str, dict[str, Any]] = {}
    for row in provenance_manifest["runs"]:
        run_id = row["run_id"]
        attached: dict[str, bytes] = {}
        descriptors = {}
        for key in ("execution_receipt", "scheduler_record", "batch_script", "stdout", "stderr"):
            data, descriptor = _PROVENANCE.validate_descriptor(row[key], final, verify, f"{run_id}/{key}")
            if key == "batch_script" and not data.strip():
                raise verify.CandidateFailure("submitted batch script is empty")
            attached[key] = data
            descriptors[key] = descriptor
        try:
            receipt = verify.strict_json(attached["execution_receipt"], max_bytes=2 * 1024 * 1024)
            scheduler = verify.strict_json(attached["scheduler_record"], max_bytes=2 * 1024 * 1024)
        except Exception as exc:
            raise verify.CandidateFailure("execution receipt or scheduler record is not strict JSON") from exc
        try:
            receipt = _PROVENANCE.validate_run_records(receipt, scheduler,
                                                       descriptors["batch_script"]["sha256"], attached["batch_script"])
        except _PROVENANCE.ProvenanceFailure as exc:
            raise verify.CandidateFailure(str(exc)) from exc
        if "raw_scheduler_log" in scheduler:
            raw_log, _ = _PROVENANCE.validate_descriptor(scheduler["raw_scheduler_log"], final, verify,
                                                        f"{run_id}/raw_scheduler_log")
            try:
                _PROVENANCE.validate_raw_scheduler_log(raw_log, receipt)
            except _PROVENANCE.ProvenanceFailure as exc:
                raise verify.CandidateFailure(str(exc)) from exc
        records_by_run[run_id] = {"receipt": receipt, "attached": attached, "descriptors": descriptors}
        scheduler_by_run[run_id] = scheduler

    try:
        _PROVENANCE.validate_execution_order(scheduler_by_run, provenance_manifest["execution_order"])
    except _PROVENANCE.ProvenanceFailure as exc:
        raise verify.CandidateFailure(str(exc)) from exc

    groups: dict[str, dict[str, dict[str, Any]]] = {}
    all_sources = []
    for run in manifest["runs"]:
        run_id = run["run_id"]
        if type(run_id) is not str or run_id in groups:
            raise verify.CandidateFailure("native run identifier is missing or duplicated")
        link_rows = run["files"]
        if type(link_rows) is not list or len(link_rows) != len(NATIVE_FILES):
            raise verify.CandidateFailure("native run must link all seven native members")
        names = [item.get("name") if type(item) is dict else None for item in link_rows]
        if set(names) != set(NATIVE_FILES) or len(set(names)) != len(NATIVE_FILES):
            raise verify.CandidateFailure("native run must contain exactly the seven native members")
        receipt = records_by_run[run_id]["receipt"]
        job_id = receipt["job_id"]
        if not verify.JOB_RE.fullmatch(job_id):
            raise verify.CandidateFailure("unsupported scheduler job identifier")
        current: dict[str, dict[str, Any]] = {}
        run_dir = f"native/runs/{run_id}"
        for name in NATIVE_FILES:
            relative = f"{run_dir}/{name}"
            data = verify.read_candidate_member(final, relative,
                                                max_bytes=verify.MAX_XML_BYTES if name == "vasprun.xml" else 32 * 1024 * 1024)
            digest = verify.digest(data)
            row = {"job_id": job_id, "path": f"jobs/{job_id}/native/{run_id}/{name}",
                   "bytes": len(data), "sha256": digest}
            source_id = verify.digest((job_id + "\0" + row["path"] + "\0" + digest).encode())
            current[name] = {"row": row, "path": final / relative, "source_id": source_id}
            all_sources.append(source_id)
        native_receipt = verify.strict_json(
            verify.read_candidate_member(final, f"{run_dir}/execution-receipt.json", max_bytes=2 * 1024 * 1024))
        if type(native_receipt) is not dict:
            raise verify.CandidateFailure("native execution receipt must be an object")
        if (native_receipt.get("slurm_job_id") != job_id or native_receipt.get("exit_code") != 0 or
                native_receipt.get("status") != "FINISHED"):
            raise verify.CandidateFailure("native receipt job or completion state differs from provenance")
        native_input_manifest = verify.strict_json(
            verify.read_candidate_member(final, f"{run_dir}/input-manifest.json", max_bytes=2 * 1024 * 1024))
        if type(native_input_manifest) is not dict:
            raise verify.CandidateFailure("native input manifest must be an object")
        for source in (native_receipt, native_input_manifest):
            declared_job = source.get("slurm_job_id", source.get("job_id"))
            if declared_job is not None and declared_job != job_id:
                raise verify.CandidateFailure("native source metadata job identity differs from submitted scheduler provenance")
        try:
            _PROVENANCE.validate_native_receipt_span(native_receipt, scheduler_by_run[run_id])
        except _PROVENANCE.ProvenanceFailure as exc:
            raise verify.CandidateFailure(str(exc)) from exc
        # The candidate-submitted scheduler execution receipt is a separate
        # provenance artifact; its scheduler job identity must join the native
        # calculation receipt. Raw stdout/stderr are hash-bound by their
        # descriptors, while scientific native outputs remain joined by the
        # unchanged seven-file native manifest and parser.
        groups[run_id] = current
    return groups, sorted(all_sources)

def verify_candidate(final_dir: Path, *, tests_dir: Path, public_root: Path) -> dict[str, Any]:
    env = {"task_inputs": "NOT_EVALUATED", "runner_context": "NOT_REQUIRED_CANDIDATE_PROVENANCE",
           "remote_evidence": "CANDIDATE_SUBMITTED", "adapter": "NOT_EVALUATED"}
    try:
        refs_raw = read_regular(tests_dir / "refs.json", max_bytes=MAX_TRUST_BYTES, environment=True)
        refs = strict_json(refs_raw, max_bytes=MAX_TRUST_BYTES)
        if type(refs) is not dict or refs.get("case_id") != CASE_ID or refs.get("schema") != "case05.reference-contract/v2":
            raise EnvironmentInvalid("scientific reference contract identity is unsupported")
        expected_inputs = refs.get("public_input_hashes")
        if type(expected_inputs) is not dict:
            raise EnvironmentInvalid("public input hash contract is malformed")
        for rel, expected in expected_inputs.items():
            raw = read_public_member(public_root, rel, max_bytes=MAX_TRUST_BYTES)
            if digest(raw) != expected:
                raise EnvironmentInvalid(f"public input bytes changed: {Path(rel).name}")
        for rel, row in refs.get("evidence_documents", {}).items():
            raw = read_public_member(public_root, rel, max_bytes=128 * 1024 * 1024)
            if type(row) is not dict or digest(raw) != row.get("sha256"):
                raise EnvironmentInvalid(f"public literature hash mismatch: {Path(rel).name}")
        groups, _ = _candidate_groups(final_dir, _VERIFIER_API)
        seed = _parse_poscar(public_root / "author/inputs/GaAs.POSCAR")
        env.update(task_inputs="PASS", adapter="PASS")
    except Exception as exc:
        if isinstance(exc, prov_ProvenanceFailure):
            failure = CandidateFailure(str(exc), "native_generation")
            checks = [{"name": name, "status": "FAIL" if name == failure.criterion else "NOT_EVALUATED",
                       "reason": str(failure) if name == failure.criterion else "preceding candidate evidence failure",
                       "execution_count": 1 if name == failure.criterion else 0, "source_ids": []}
                      for name in CRITERIA]
            return _make_result("FAIL", "DECISIVE_CANDIDATE_OR_OUTPUT_ERROR", checks=checks,
                                failed_outputs=[str(failure)], all_executed=False)
        if isinstance(exc, CandidateFailure):
            checks = [{"name": name, "status": "FAIL" if name == exc.criterion else "NOT_EVALUATED",
                       "reason": str(exc) if name == exc.criterion else "preceding candidate evidence failure",
                       "execution_count": 1 if name == exc.criterion else 0, "source_ids": []}
                      for name in CRITERIA]
            return _make_result("FAIL", "DECISIVE_CANDIDATE_OR_OUTPUT_ERROR", checks=checks,
                                failed_outputs=[str(exc)], all_executed=False)
        return _make_result("ENV_INVALID", f"TRUST_OR_ADAPTER_INVALID:{type(exc).__name__}", env=env)
    try:
        observations, all_sources = _candidate_native(final_dir, groups, _ADAPTER)
        for run_id, record in observations.items():
            for name, cap in (("vasprun.xml", MAX_XML_BYTES), ("execution-receipt.json", 2*1024*1024),
                              ("KPOINTS", 1024*1024), ("OUTCAR", 32*1024*1024),
                              ("input-manifest.json", 2*1024*1024)):
                member = groups[run_id][name]
                relative = member["path"].relative_to(final_dir).as_posix()
                raw = read_candidate_member(final_dir, relative, max_bytes=cap)
                expected_hash = record["result"]["source_hashes"].get(name)
                if expected_hash is not None and digest(raw) != expected_hash:
                    raise CandidateFailure(f"{run_id}: {name} changed after source-bound parsing")
                record.setdefault("candidate_native_raw", {})[name] = raw
        mirror_raw = None
        try:
            mirror_raw = read_candidate_member(final_dir, "native/deformation-mirror-proof.json", max_bytes=16*1024*1024)
        except CandidateFailure:
            pass
        ccref_bind_deformation_proof(_PROOF, mirror_raw)
        _CANDIDATE_COMPONENT.DEFORMATION_PROOF = _PROOF
        _CANDIDATE_COMPONENT.DEFORMATION_PROOF_RAW = mirror_raw
        checks, _ = _validate_candidate(final_dir, observations, all_sources, seed, _CANDIDATE_COMPONENT)
    except CandidateFailure as exc:
        checks = [{"name": name, "status": "FAIL" if name == exc.criterion else "NOT_EVALUATED",
                   "reason": str(exc) if name == exc.criterion else "preceding decisive failure",
                   "execution_count": 1 if name == exc.criterion else 0, "source_ids": []}
                  for name in CRITERIA]
        return _make_result("FAIL", "DECISIVE_CANDIDATE_OR_OUTPUT_ERROR", checks=checks,
                            failed_outputs=[str(exc)], all_executed=False)
    except EnvironmentInvalid as exc:
        if "unsupported finite-displacement groundstate phase" in str(exc):
            checks = [{"name": name, "status": "FAIL" if name == "native_generation" else "NOT_EVALUATED",
                       "reason": str(exc) if name == "native_generation" else "preceding candidate evidence failure",
                       "execution_count": 1 if name == "native_generation" else 0, "source_ids": []}
                      for name in CRITERIA]
            return _make_result("FAIL", "DECISIVE_CANDIDATE_OR_OUTPUT_ERROR", checks=checks,
                                failed_outputs=[str(exc)], all_executed=False)
        return _make_result("ENV_INVALID", f"NATIVE_EVALUATION_CAPABILITY_INVALID:{exc}", env=env)
    except Exception as exc:
        return _make_result("ENV_INVALID", f"SCORER_INTERNAL_OR_DEPENDENCY_ERROR:{type(exc).__name__}", env=env)
    if all(row.get("status") == "PASS" for row in checks):
        return _make_result("PASS", "ALL_SOURCE_BOUND_SCIENTIFIC_CRITERIA_QUALIFIED",
                            checks=checks, env=env, all_executed=True)
    return _make_result("ENV_INVALID", "SCIENTIFIC_CRITERIA_NOT_FULLY_QUALIFIED",
                        checks=checks, env=env, all_executed=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("final", nargs="?", type=Path, default=Path(os.environ.get("APP", "/app")) / "final")
    parser.add_argument("--tests", type=Path, default=Path(os.environ.get("TESTS", "/tests")))
    parser.add_argument("--assets", type=Path, default=Path(os.environ.get("APP", "/app")) / "assets")
    args = parser.parse_args(argv)
    result = verify_candidate(args.final, tests_dir=args.tests, public_root=args.assets)
    print(json.dumps(result, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 2 if result["status"] == "ENV_INVALID" else (1 if result["status"] == "FAIL" else 0)


def _runner() -> int:
    logs = Path(os.environ.get("LOGS", "/logs/verifier"))
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "reward.txt").unlink(missing_ok=True)
    result = verify_candidate(Path(os.environ.get("APP", "/app")) / "final",
                              tests_dir=Path(os.environ.get("TESTS", "/tests")),
                              public_root=Path(os.environ.get("APP", "/app")) / "assets")
    (logs / "verification.json").write_text(json.dumps(result, allow_nan=False, ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    if result["status"] == "FAIL": (logs / "reward.txt").write_text("0\n", encoding="ascii")
    elif result["status"] == "PASS": (logs / "reward.txt").write_text("1\n", encoding="ascii")
    return 2 if result["status"] == "ENV_INVALID" else (1 if result["status"] == "FAIL" else 0)

if __name__ == "__main__":
    raise SystemExit(_runner() if sys.argv[1:] == ["--runner"] else main())
