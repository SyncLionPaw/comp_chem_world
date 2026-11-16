#!/bin/sh
set -eu

WORK=$(mktemp -d "${TMPDIR:-/tmp}/task5-solve.XXXXXX")
cleanup() { status=$?; rm -rf "$WORK"; trap - 0; exit "$status"; }
trap cleanup 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

cat > "$WORK/solve.py" <<'__TASK5_PYTHON_SOURCE_1__'
#!/usr/bin/env python3
"""Public-evidence-only reference solver for the audit-v2 ORCA bundle.

The solver consumes only the ZIP explicitly passed on the command line.  It
does not discover adjacent files, extract archive paths, or key decisions on
opaque case identifiers.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

MAX_MEMBERS = 300
MAX_TOTAL = 100 * 1024 * 1024
MAX_MEMBER = 20 * 1024 * 1024
MAX_RATIO = 500
HARTREE_TO_KCAL = 627.509474


class SolveError(Exception):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_archive_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/") or "\x00" in name:
        return False
    p = PurePosixPath(name)
    return not p.is_absolute() and all(part not in ("", ".", "..") for part in p.parts)


def read_bundle(path: Path) -> tuple[dict[str, bytes], dict[str, str]]:
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SolveError(f"cannot open public bundle: {exc}") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_MEMBERS:
            raise SolveError("archive exceeds member-count limit")
        names: set[str] = set()
        total = 0
        for info in infos:
            if not safe_archive_name(info.filename) or info.filename in names:
                raise SolveError("unsafe or duplicate ZIP member name")
            names.add(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode) or info.flag_bits & 1:
                raise SolveError("symlink or encrypted ZIP member is not allowed")
            if info.file_size > MAX_MEMBER:
                raise SolveError("archive member exceeds size limit")
            total += info.file_size
            if total > MAX_TOTAL:
                raise SolveError("archive exceeds total uncompressed size limit")
            if info.file_size and (not info.compress_size or info.file_size / info.compress_size > MAX_RATIO):
                raise SolveError("archive member exceeds compression-ratio limit")
        contents: dict[str, bytes] = {}
        for info in infos:
            data = zf.read(info)
            if len(data) != info.file_size:
                raise SolveError("ZIP member size changed while reading")
            contents[info.filename] = data
    manifest = json_obj(contents, "bundle-manifest.json")
    rows = manifest.get("files")
    if manifest.get("version") not in ("audit-v2", "audit-v2-joint-fix-r1") or not isinstance(rows, list):
        raise SolveError("unrecognized bundle manifest")
    expected: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SolveError("invalid manifest row")
        name, digest, nbytes = row.get("path"), row.get("sha256"), row.get("bytes")
        if not isinstance(name, str) or not safe_archive_name(name) or name in expected:
            raise SolveError("invalid or duplicate manifest path")
        if name not in contents or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SolveError(f"manifest target missing or malformed: {name}")
        data = contents[name]
        if len(data) != nbytes or sha(data) != digest:
            raise SolveError(f"bundle manifest mismatch: {name}")
        expected[name] = digest
    if set(contents) != set(expected) | {"bundle-manifest.json"}:
        raise SolveError("archive has unmanifested or missing entries")
    return contents, expected


def json_obj(files: dict[str, bytes], name: str) -> dict[str, Any]:
    try:
        value = json.loads(files[name])
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SolveError(f"invalid JSON member: {name}") from exc
    if not isinstance(value, dict):
        raise SolveError(f"expected JSON object: {name}")
    return value


def text_of(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def parse_index(data: bytes) -> dict[str, dict[str, str]]:
    try:
        rows = csv.DictReader(io.StringIO(text_of(data)))
        needed = {"evidence_id", "relative_path", "artifact_role", "direction", "sha256"}
        if not rows.fieldnames or not needed.issubset(rows.fieldnames):
            raise SolveError("evidence index is missing required columns")
        result: dict[str, dict[str, str]] = {}
        for row in rows:
            evidence_id = row.get("evidence_id", "")
            if not evidence_id or evidence_id in result:
                raise SolveError("empty or duplicate evidence id")
            result[evidence_id] = {k: (v or "") for k, v in row.items()}
        return result
    except csv.Error as exc:
        raise SolveError("invalid evidence index CSV") from exc


def matching_file(files: dict[str, bytes], row: dict[str, str]) -> tuple[str, bytes]:
    name = row["relative_path"]
    if not safe_archive_name(name):
        raise SolveError("unsafe evidence-index path")
    if name not in files or sha(files[name]) != row["sha256"]:
        raise SolveError(f"evidence-index hash mismatch: {name}")
    return name, files[name]


def associated(files: dict[str, bytes], index: dict[str, dict[str, str]], evidence_ids: list[str]) -> list[tuple[str, bytes, dict[str, str]]]:
    result = []
    for eid in evidence_ids:
        if eid not in index:
            raise SolveError(f"required evidence id missing from index: {eid}")
        name, data = matching_file(files, index[eid])
        result.append((name, data, index[eid]))
    return result


def extract_frequency_rows(text: str) -> list[tuple[int, float]]:
    start = text.rfind("VIBRATIONAL FREQUENCIES")
    if start < 0:
        return []
    block = text[start:]
    rows = []
    for line in block.splitlines()[1:]:
        m = re.match(r"\s*(\d+)\s*:\s*(-?\d+(?:\.\d*)?(?:[Ee][+-]?\d+)?)\s+cm", line)
        if m:
            index, val = int(m.group(1)), float(m.group(2))
            if math.isfinite(val):
                rows.append((index, val))
        elif rows and not line.strip():
            break
    return rows


def extract_frequencies(text: str) -> list[float]:
    return [value for _, value in extract_frequency_rows(text)]


def parse_protocol(texts: list[str]) -> dict[str, Any]:
    joined = "\n".join(texts)
    upper = joined.upper()
    # ORCA echoes its input in output logs; use the directive line where present.
    directive_lines = []
    for line in joined.splitlines():
        stripped = line.strip()
        if stripped.startswith("!"):
            directive_lines.append(stripped[1:].strip())
        elif re.match(r"\|\s*\d+\s*>\s*!", stripped):
            directive_lines.append(re.sub(r"^\|\s*\d+\s*>\s*!\s*", "", stripped).strip())
    directives_original = " ".join(directive_lines)
    directives = directives_original.upper()
    functional = None
    basis = None
    tokens = directives_original.split()
    for i, token in enumerate(tokens):
        if token.upper().startswith("WB97") or token.upper() in {"PBE", "B3LYP", "BP86", "M062X", "PBE0", "TPSS"}:
            functional = token
        if re.match(r"^(DEF2-|6-|AUG-|CC-PV|SVP$|TZVP$)", token, flags=re.I):
            basis = token
    solvent_model = None
    solvent = None
    if re.search(r"\bSMD\s+TRUE\b", upper):
        solvent_model = "SMD"
    elif re.search(r"\bSMD\b", directives):
        solvent_model = "SMD"
    elif "%CPCM" in upper:
        solvent_model = "CPCM"
    msolv = re.search(r'SMDsolvent\s+["\']?([^"\'\s]+)', joined, flags=re.I)
    if msolv:
        solvent = msolv.group(1).lower()
    else:
        msolv = re.search(r"\bSolvent\s+([A-Za-z0-9_-]+)", joined, flags=re.I)
        if msolv:
            solvent = msolv.group(1).lower()
    ri = None
    if re.search(r"\bNORI\b", directives) or re.search(r"\bNOCOSX\b", directives):
        ri = False
    else:
        states = re.findall(r"RIJ-COSX[^\n]*?\b(on|off)\b", joined, flags=re.I)
        if states:
            ri = states[-1].lower() == "on"
    job_type = None
    for token in ("OPTTS", "IRC", "FREQ", "SP", "OPT"):
        if re.search(rf"\b{token}\b", directives):
            job_type = token
            break
    return {"functional": functional, "basis": basis, "solvent_model": solvent_model,
            "solvent": solvent, "ri_jcosx_enabled": ri, "job_type": job_type}


def parse_observation(kind: str, sources: list[tuple[str, bytes, dict[str, str]]], files: dict[str, bytes], index: dict[str, dict[str, str]], manifest_hashes: dict[str, str], case_id: str) -> Any:
    texts = [text_of(data) for _, data, _ in sources]
    if kind == "irc_direction_inventory":
        dirs = sorted({r.get("direction", "").lower() for r in index.values()
                       if "irc" in r.get("artifact_role", "").lower()
                       and "output" in r.get("artifact_role", "").lower()
                       and r.get("direction", "").lower() in {"forward", "backward"}})
        return dirs
    if kind == "irc_converged":
        return any("THE IRC HAS CONVERGED" in t.upper() for t in texts)
    if kind == "orca_normal_exit":
        return any("ORCA TERMINATED NORMALLY" in t.upper() for t in texts)
    if kind == "opt_converged":
        # Only explicit geometry optimization markers count; normal process exit does not.
        result = None
        for text in texts:
            low = text.lower()
            if "the optimization did not converge" in low or "optimization did not converge" in low:
                result = False
            if re.search(r"the optimization has converged\b", low) or "geometry optimization converged" in low:
                result = True
        return result
    if kind == "optimization_cycle_count":
        cycles = []
        for text in texts:
            cycles.extend(int(m.group(1)) for m in re.finditer(r"GEOMETRY OPTIMIZATION CYCLE\s+(\d+)", text, flags=re.I))
        return max(cycles) if cycles else None
    if kind in {"lowest_vibrational_frequency_cm-1", "negative_frequency_count"}:
        frequencies = []
        for text in texts:
            frequencies.extend(extract_frequencies(text))
        if not frequencies:
            return None
        return min(frequencies) if kind == "lowest_vibrational_frequency_cm-1" else sum(v < 0 for v in frequencies)
    if kind == "final_single_point_energy_hartree":
        found = []
        for text in texts:
            found.extend(float(m.group(1)) for m in re.finditer(r"FINAL SINGLE POINT ENERGY\s+(-?\d+(?:\.\d*)?(?:[Ee][+-]?\d+)?)", text, flags=re.I))
        return found[-1] if found else None
    if kind == "sp_protocol_signature":
        return parse_protocol(texts)
    raise SolveError(f"unknown required observation kind: {kind}")


def observation_evidence(kind: str, rows: list[dict[str, str]], case_id: str, manifest_hashes: dict[str, str]) -> list[dict[str, str]]:
    citations = []
    for row in rows:
        if row.get("evidence_id") == "metadata-index":
            name = f"cases/{case_id}/evidence-index.csv"
            digest = manifest_hashes.get(name)
            if not digest:
                raise SolveError("metadata index is not covered by bundle manifest")
        else:
            name, digest = row["relative_path"], row["sha256"]
        citation = {"path": name, "sha256": digest}
        if citation not in citations:
            citations.append(citation)
    if not citations:
        raise SolveError("required observation has no citable evidence")
    return citations


def finite_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def classify_minimum(lowest: Any, negative_count: Any) -> tuple[str, str, str, str | None]:
    """Return decision, claim status, explanation, and typed issue."""
    if not finite_number(lowest) or not isinstance(negative_count, int) or isinstance(negative_count, bool) or negative_count < 0:
        return "insufficient_evidence", "underdetermined", "The supplied frequency evidence is incomplete or malformed.", "imaginary_mode_unresolved"
    if negative_count == 0:
        return "accept", "supported", "The frequency output contains zero negative modes, supporting the certified-minimum claim.", None
    if abs(lowest) < 10:
        return "insufficient_evidence", "underdetermined", "The reported lowest mode is within the contract's equivocal |ν| < 10 cm⁻¹ region; minimum certification remains unresolved.", "imaginary_mode_unresolved"
    return "reject", "contradicted", "The frequency output contains negative modes and does not certify a minimum.", None


PHYSICAL_PROTOCOL_FIELDS = ("functional", "basis", "solvent_model", "solvent", "ri_jcosx_enabled")


def physical_protocols_equal(signatures: list[dict[str, Any]]) -> bool:
    return bool(signatures) and all(all(sig.get(k) is not None for k in PHYSICAL_PROTOCOL_FIELDS) for sig in signatures) and all(
        tuple(s[k] for k in PHYSICAL_PROTOCOL_FIELDS) == tuple(signatures[0][k] for k in PHYSICAL_PROTOCOL_FIELDS)
        for s in signatures[1:])


def mapped_reactive_coordinate(files: dict[str, bytes], index: dict[str, dict[str, str]], candidate: dict[str, Any]) -> tuple[bool | None, list[dict[str, str]]]:
    cid = candidate.get("candidate_id")
    site_map = candidate.get("site_map")
    if not isinstance(cid, str) or not isinstance(site_map, dict):
        return None, []
    required = ("attacked_carbon_zero_based", "leaving_chloride_zero_based", "amine_nitrogen_zero_based")
    if any(not isinstance(site_map.get(k), int) for k in required):
        return None, []
    expected_ts = {site_map["attacked_carbon_zero_based"], site_map["amine_nitrogen_zero_based"]}
    expected_bonds = {
        frozenset((site_map["attacked_carbon_zero_based"], site_map["amine_nitrogen_zero_based"])),
        frozenset((site_map["attacked_carbon_zero_based"], site_map["leaving_chloride_zero_based"])),
    }
    inputs = []
    citations = []
    for row in index.values():
        role = row.get("artifact_role", "").lower()
        if row.get("candidate_id") == cid and "transition-structure input" in role:
            name, data = matching_file(files, row)
            inputs.append(text_of(data))
            citations.append({"path": name, "sha256": row["sha256"]})
    if len(inputs) != 1:
        return None, citations
    text = inputs[0]
    tm = re.search(r"TS_Mode\s*\{\s*B\s+(\d+)\s+(\d+)\s*\}", text, flags=re.I)
    pairs = [frozenset((int(a), int(b))) for a, b in re.findall(r"\{\s*B\s+(\d+)\s+(\d+)(?:\s+[A-Z])?\s*\}", text, flags=re.I)]
    mapped = bool(tm and {int(tm.group(1)), int(tm.group(2))} == expected_ts and expected_bonds.issubset(set(pairs)))
    return mapped, citations


def parse_xyz_geometry(text: str) -> tuple[list[str], list[tuple[float, float, float]]] | None:
    lines = text.splitlines()
    if len(lines) < 2:
        return None
    try:
        count = int(lines[0].strip())
    except ValueError:
        return None
    if count <= 0 or len(lines) != count + 2:
        return None
    symbols, coords = [], []
    for line in lines[2:]:
        fields = line.split()
        if len(fields) != 4 or not re.fullmatch(r"[A-Za-z]{1,3}", fields[0]):
            return None
        try:
            xyz = tuple(float(x) for x in fields[1:])
        except ValueError:
            return None
        if not all(math.isfinite(x) for x in xyz):
            return None
        symbols.append(fields[0].capitalize())
        coords.append(xyz)
    return symbols, coords


def parse_orca_cartesian_geometry(text: str) -> tuple[list[str], list[tuple[float, float, float]]] | None:
    lines = text.splitlines()
    headers = [i for i, line in enumerate(lines) if re.fullmatch(r"\s*CARTESIAN COORDINATES \(ANGSTROEM\)\s*", line, flags=re.I)]
    geometries = []
    for header in headers:
        symbols, coords = [], []
        started = False
        for line in lines[header + 1:]:
            stripped = line.strip()
            if not stripped or re.fullmatch(r"[-=]+", stripped):
                if started:
                    break
                continue
            fields = stripped.split()
            if len(fields) == 4 and re.fullmatch(r"[A-Za-z]{1,3}", fields[0]):
                try:
                    xyz = tuple(float(x) for x in fields[1:])
                except ValueError:
                    break
                if not all(math.isfinite(x) for x in xyz):
                    break
                symbols.append(fields[0].capitalize())
                coords.append(xyz)
                started = True
            elif started:
                break
        if symbols and len(symbols) == len(coords):
            geometries.append((symbols, coords))
    return geometries[-1] if geometries else None


def parse_normal_mode_matrix(text: str, coordinate_count: int) -> list[list[float]] | None:
    """Parse ORCA's block-column NORMAL MODES table into mode-major rows."""
    start = text.rfind("NORMAL MODES")
    if start < 0 or coordinate_count <= 0:
        return None
    table = text[start:].splitlines()[1:]
    values: dict[int, dict[int, float]] = {}
    columns: list[int] | None = None
    started = False
    row_re = re.compile(r"^\s*(\d+)\s+((?:[-+]?\d+\.\d+(?:[Ee][+-]?\d+)?\s*)+)$")
    for line in table:
        stripped = line.strip()
        if not stripped:
            continue
        if re.fullmatch(r"\d+(?:\s+\d+)+", stripped):
            new_columns = [int(x) for x in stripped.split()]
            if len(set(new_columns)) != len(new_columns) or any(x >= coordinate_count for x in new_columns):
                return None
            columns = new_columns
            started = True
            continue
        match = row_re.match(line)
        if match and columns is not None:
            row = int(match.group(1))
            raw_values = [float(x) for x in match.group(2).split()]
            if row >= coordinate_count or len(raw_values) != len(columns):
                return None
            target = values.setdefault(row, {})
            for col, value in zip(columns, raw_values):
                if col in target or not math.isfinite(value):
                    return None
                target[col] = value
            continue
        if started:
            break
    expected = set(range(coordinate_count))
    if set(values) != expected:
        return None
    if any(set(values[row]) != expected for row in expected):
        return None
    return [[values[row][mode] for row in range(coordinate_count)] for mode in range(coordinate_count)]


def analyze_reactive_mode(freq_text: str, xyz_text: str, site_map: dict[str, Any]) -> dict[str, Any] | None:
    reference_geometry = parse_xyz_geometry(xyz_text)
    geometry = parse_orca_cartesian_geometry(freq_text)
    if geometry is None or reference_geometry is None:
        return None
    symbols, coords = geometry
    if symbols != reference_geometry[0]:
        return None
    atom_count = len(symbols)
    if atom_count < 1 or len(coords) != atom_count:
        return None
    frequency_rows = extract_frequency_rows(freq_text)
    coordinate_count = 3 * atom_count
    if len(frequency_rows) != coordinate_count or [i for i, _ in frequency_rows] != list(range(coordinate_count)):
        return None
    frequencies = [value for _, value in frequency_rows]
    negative_indices = [i for i, value in enumerate(frequencies) if value < 0]
    if len(negative_indices) != 1:
        return None
    mode_index = negative_indices[0]
    matrix = parse_normal_mode_matrix(freq_text, coordinate_count)
    if matrix is None or len(matrix) != coordinate_count:
        return None
    try:
        c = site_map["attacked_carbon_zero_based"]
        cl = site_map["leaving_chloride_zero_based"]
        n = site_map["amine_nitrogen_zero_based"]
        if any(not isinstance(x, int) or isinstance(x, bool) or not 0 <= x < atom_count for x in (c, cl, n)):
            return None
        if (symbols[c], symbols[cl], symbols[n]) != ("C", "Cl", "N"):
            return None
    except (KeyError, TypeError):
        return None

    vector = matrix[mode_index]
    displacement = [tuple(vector[3*i+j] for j in range(3)) for i in range(atom_count)]

    def projection(atom_b: int, atom_a: int) -> float | None:
        bond = tuple(coords[atom_b][j] - coords[atom_a][j] for j in range(3))
        norm = math.sqrt(sum(v*v for v in bond))
        if not math.isfinite(norm) or norm == 0:
            return None
        unit = tuple(v / norm for v in bond)
        relative = tuple(displacement[atom_b][j] - displacement[atom_a][j] for j in range(3))
        value = sum(relative[j] * unit[j] for j in range(3))
        return value if math.isfinite(value) else None

    d_cn = projection(n, c)
    d_ccl = projection(cl, c)
    if d_cn is None or d_ccl is None:
        return None
    nonzero_opposed = d_cn != 0.0 and d_ccl != 0.0 and d_cn * d_ccl < 0.0
    return {
        "imaginary_mode_index_zero_based": mode_index,
        "imaginary_frequency_cm-1": frequencies[mode_index],
        "atom_count": atom_count,
        "cartesian_displacement_row_count": coordinate_count,
        "negative_frequency_count": len(negative_indices),
        "mode_displacement_basis": "mass-weighted Cartesian NORMAL MODES as printed by ORCA",
        "coordinates_from_frequency_output": True,
        "coordinate_element_order_matches_optimized_xyz": True,
        "dot_vN_minus_vC_uCN": d_cn,
        "dot_vCl_minus_vC_uCCl": d_ccl,
        "relative_projection_relation": "opposite_sign" if nonzero_opposed else "not_established",
        "sign_invariant_opposed_motion": nonzero_opposed,
        "scope": "Projection of the unique negative ORCA normal mode onto the two mapped bond directions; it does not establish the full reaction mechanism."
    }


def candidate_reactive_mode(files: dict[str, bytes], index: dict[str, dict[str, str]], candidate: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    cid = candidate.get("candidate_id")
    freq_rows = [r for r in index.values() if r.get("candidate_id") == cid and r.get("artifact_role", "").lower() == "frequency output"]
    geom_rows = [r for r in index.values() if r.get("candidate_id") == cid and r.get("artifact_role", "").lower() == "optimized transition-structure geometry"]
    if len(freq_rows) != 1 or len(geom_rows) != 1:
        return None, []
    freq_name, freq_data = matching_file(files, freq_rows[0])
    geom_name, geom_data = matching_file(files, geom_rows[0])
    result = analyze_reactive_mode(text_of(freq_data), text_of(geom_data), candidate.get("site_map", {}))
    citations = [{"path": freq_name, "sha256": freq_rows[0]["sha256"]},
                 {"path": geom_name, "sha256": geom_rows[0]["sha256"]}]
    return result, citations


def solve_case(files: dict[str, bytes], manifest_hashes: dict[str, str], case_id: str) -> dict[str, Any]:
    base = f"cases/{case_id}/"
    challenge = json_obj(files, base + "challenge.json")
    if challenge.get("case_id") != case_id:
        raise SolveError("challenge index and challenge case id mismatch")
    index = parse_index(files[base + "evidence-index.csv"])
    values: dict[str, Any] = {}
    observations = []
    kinds = set()
    for spec in challenge.get("required_observations", []):
        kind = spec.get("kind")
        if not isinstance(kind, str):
            raise SolveError("malformed required observation")
        kinds.add(kind)
        ids = spec.get("source_evidence_ids")
        if not isinstance(ids, list) or not ids:
            raise SolveError("required observation has no sources")
        rows = []
        sources = []
        for eid in ids:
            if eid == "metadata-index":
                rows.append({"evidence_id": eid, "relative_path": f"cases/{case_id}/evidence-index.csv", "sha256": manifest_hashes[f"cases/{case_id}/evidence-index.csv"]})
                continue
            if eid not in index:
                raise SolveError(f"required evidence id missing: {eid}")
            row = index[eid]
            rows.append(row)
            sources.append((*matching_file(files, row), row))
        value = parse_observation(kind, sources, files, index, manifest_hashes, case_id)
        values[spec["observation_id"]] = value
        observations.append({"observation_id": spec["observation_id"], "value": value,
                             "evidence": observation_evidence(kind, rows, case_id, manifest_hashes)})

    claims = challenge.get("claims", [])
    assessments: dict[str, str] = {}
    decision = "insufficient_evidence"
    issues: list[str] = []
    result: dict[str, Any] = {"case_id": case_id, "decision": decision, "issues": issues,
                              "claim_assessments": assessments, "observations": observations,
                              "confidence": "unrated", "reason": "The supplied public evidence does not establish the primary claim."}

    if "irc_direction_inventory" in kinds:
        inventory = next((o["value"] for o in observations if o["observation_id"] in values and
                          next((x["kind"] for x in challenge["required_observations"] if x["observation_id"] == o["observation_id"]), None) == "irc_direction_inventory"), None)
        irc_vals = [o["value"] for o in observations if next(x["kind"] for x in challenge["required_observations"] if x["observation_id"] == o["observation_id"]) == "irc_converged"]
        complete = inventory == ["backward", "forward"] and len(irc_vals) >= 2 and all(v is True for v in irc_vals)
        result.update(decision="accept" if complete else "insufficient_evidence", confidence="unrated",
                      reason="Both native IRC directions are required; the supplied direction inventory and convergence markers do not establish both." if not complete else "Both native IRC directions are represented and converged.")
        if not complete:
            issues.append("missing_irc")
        assessments[claims[0]["claim_id"]] = "supported" if complete else "underdetermined"
    elif "sp_protocol_signature" in kinds and "final_single_point_energy_hartree" in kinds and len(claims) == 1:
        signatures = [o["value"] for o in observations if next(x["kind"] for x in challenge["required_observations"] if x["observation_id"] == o["observation_id"]) == "sp_protocol_signature"]
        comparable = bool(signatures) and all(all(sig.get(k) is not None for k in PHYSICAL_PROTOCOL_FIELDS) for sig in signatures)
        consistent = physical_protocols_equal(signatures)
        result.update(decision="accept" if consistent else "reject" if comparable else "insufficient_evidence",
                      reason="All four single-point signatures agree on the physical method, basis, solvent treatment, and RIJCOSX setting." if consistent else "The single-point protocol signatures differ, so one common electronic-energy reference is contradicted." if comparable else "One or more protocol fields cannot be established from the supplied native inputs and outputs.")
        if comparable and not consistent:
            issues.append("inconsistent_sp_protocol")
        assessments[claims[0]["claim_id"]] = "supported" if consistent else "contradicted" if comparable else "underdetermined"
    elif "negative_frequency_count" in kinds and "lowest_vibrational_frequency_cm-1" in kinds and len(claims) == 1:
        lowest = next((o["value"] for o in observations if next(x["kind"] for x in challenge["required_observations"] if x["observation_id"] == o["observation_id"]) == "lowest_vibrational_frequency_cm-1"), None)
        count = next((o["value"] for o in observations if next(x["kind"] for x in challenge["required_observations"] if x["observation_id"] == o["observation_id"]) == "negative_frequency_count"), None)
        decision, status, why, issue = classify_minimum(lowest, count)
        result.update(decision=decision, reason=why)
        assessments[claims[0]["claim_id"]] = status
        if issue:
            issues.append(issue)
    elif "optimization_cycle_count" in kinds and "opt_converged" in kinds:
        converged = next((o["value"] for o in observations if next(x["kind"] for x in challenge["required_observations"] if x["observation_id"] == o["observation_id"]) == "opt_converged"), None)
        if converged is False:
            decision = "reject"
            issues.append("opt_not_converged")
            assessments[claims[0]["claim_id"]] = "contradicted"
            result["decision"] = decision
            result["reason"] = "The native output explicitly reports that geometry optimization did not converge; normal termination does not validate a transition structure."
        elif converged is True:
            decision = "insufficient_evidence"
            result["decision"] = decision
            assessments[claims[0]["claim_id"]] = "underdetermined"
            result["reason"] = "Optimization convergence is necessary but the supplied observations do not establish the required first-order frequency and mapped reactive mode."
        else:
            assessments[claims[0]["claim_id"]] = "underdetermined"
    elif "final_single_point_energy_hartree" in kinds and len(claims) >= 2:
        # This branch is selected by evidence shape, not by case identifier.
        obs_by_kind: dict[str, list[Any]] = {}
        for obs in observations:
            k = next(x["kind"] for x in challenge["required_observations"] if x["observation_id"] == obs["observation_id"])
            obs_by_kind.setdefault(k, []).append(obs["value"])
        energies = obs_by_kind.get("final_single_point_energy_hartree", [])
        sigs = obs_by_kind.get("sp_protocol_signature", [])
        converged = obs_by_kind.get("opt_converged", [])
        freqs = obs_by_kind.get("lowest_vibrational_frequency_cm-1", [])
        ircs = obs_by_kind.get("irc_converged", [])
        nfreqs = obs_by_kind.get("negative_frequency_count", [])
        candidates = challenge.get("conditions", {}).get("candidates", [])
        candidate_ids = [c.get("candidate_id") for c in candidates]
        mapping_results = [mapped_reactive_coordinate(files, index, candidate) for candidate in candidates]
        mapping_ok = len(mapping_results) == 2 and all(value is True for value, _ in mapping_results)
        for candidate, (mapped, citations) in zip(candidates, mapping_results):
            if citations:
                observations.append({"observation_id": f"obs-ts-mode-input-map-{candidate.get('candidate_id', 'unknown')}",
                                     "value": {"input_coordinate_setup_matches_site_map": mapped,
                                     "scope": "TS_Mode and modify_internal input coordinates only; normal-mode displacement is not independently established by this observation."},
                                     "evidence": citations})
        mode_results = [candidate_reactive_mode(files, index, candidate) for candidate in candidates]
        mode_ok = len(mode_results) == 2 and all(value is not None and value.get("sign_invariant_opposed_motion") is True for value, _ in mode_results)
        for candidate, (analysis, citations) in zip(candidates, mode_results):
            if citations:
                observations.append({"observation_id": f"obs-reactive-coordinate-mode-{candidate.get('candidate_id', 'unknown')}",
                                     "value": analysis if analysis is not None else {
                                         "available": False,
                                         "scope": "Normal-mode projection unavailable because frequency, mode matrix, geometry, or atom-map validation failed closed."
                                     },
                                     "evidence": citations})
        valid = (len(energies) == 4 and len(sigs) == 4 and len(candidate_ids) == 2 and
                 all(finite_number(e) for e in energies) and
                 physical_protocols_equal(sigs) and
                 len(converged) == 2 and all(v is True for v in converged) and
                 len(freqs) == 2 and all(finite_number(v) and v < -100 for v in freqs) and
                 mapping_ok and mode_ok and
                 len(ircs) == 4 and all(v is True for v in ircs) and
                 len(nfreqs) == 4 and all(v == 0 for v in nfreqs))
        if valid:
            # Map energy observations by the public prompt's species labels.
            energy_specs = [x for x in challenge["required_observations"] if x["kind"] == "final_single_point_energy_hartree"]
            e_by_candidate: dict[str, float] = {}
            substrate = nucleophile = None
            for spec, energy in zip(energy_specs, energies):
                prompt = spec.get("prompt", "").lower()
                if "substrate monomer" in prompt:
                    substrate = energy
                elif "nucleophile monomer" in prompt:
                    nucleophile = energy
                else:
                    m = re.search(r"candidate\s+(\S+)", prompt)
                    if m:
                        e_by_candidate[m.group(1).rstrip(".")] = energy
            if substrate is None or nucleophile is None or set(e_by_candidate) != set(candidate_ids):
                valid = False
        if valid:
            barriers = {cid: (e_by_candidate[cid] - substrate - nucleophile) * HARTREE_TO_KCAL for cid in candidate_ids}
            order = sorted(candidate_ids, key=lambda cid: barriers[cid])
            gap = abs(barriers[order[1]] - barriers[order[0]])
            near = gap <= 1.0
            result.update(decision="accept", barriers_kcal_mol=barriers, ranking=order,
                          near_degenerate=near, confidence="moderate" if near else "low",
                          major_product_claim=False,
                          reason=f"Method-consistent electronic barriers support the computed ranking ({order[0]} lower by {gap:.3f} kcal/mol). The electronic ranking alone does not establish a confident experimental major product.")
            assessments[claims[0]["claim_id"]] = "supported"
            assessments[claims[1]["claim_id"]] = "contradicted"
            issues.append("overconfident_major")
        else:
            result.update(decision="insufficient_evidence", reason="The supplied evidence does not establish a complete, method-consistent pair of transition structures, endpoint minima, converged IRCs, and four comparable single-point energies.")
            for claim in claims:
                assessments[claim["claim_id"]] = "underdetermined"
            if len(sigs) == 4 and any(s != sigs[0] for s in sigs[1:]):
                issues.append("inconsistent_sp_protocol")
            if len(ircs) != 4 or not all(v is True for v in ircs):
                issues.append("missing_irc")
            if not mapping_ok or not mode_ok:
                issues.append("imaginary_mode_unresolved")
            if len(converged) != 2 or not all(v is True for v in converged):
                issues.append("opt_not_converged")
    else:
        raise SolveError("unrecognized public challenge observation profile; refusing to guess")

    if not result["issues"]:
        result["issues"] = ["none"]
    # Keep output deterministic and reject accidental non-JSON numeric values.
    json.dumps(result, allow_nan=False)
    if set(assessments) != {c.get("claim_id") for c in claims}:
        raise SolveError("not every public claim received an assessment")
    return result


def run(zip_path: Path, out_dir: Path) -> None:
    files, hashes = read_bundle(zip_path)
    idx = json_obj(files, "challenge-index.json")
    case_ids = idx.get("case_ids")
    if not isinstance(case_ids, list) or not case_ids or len(set(case_ids)) != len(case_ids):
        raise SolveError("challenge index has invalid case list")
    out_dir.mkdir(parents=True, exist_ok=True)
    for case_id in case_ids:
        if not isinstance(case_id, str) or not re.fullmatch(r"case-[a-z0-9-]+", case_id):
            raise SolveError("unsafe case id in public index")
        result = solve_case(files, hashes, case_id)
        target = out_dir / f"{case_id}.json"
        target.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("public_zip", type=Path, nargs="?", default=Path("/app/assets/participant-audit-v2.zip"))
    parser.add_argument("output_dir", type=Path, nargs="?", default=Path("/app/final/submissions"))
    args = parser.parse_args(argv)
    try:
        run(args.public_zip, args.output_dir)
    except (SolveError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"case05-solver: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
__TASK5_PYTHON_SOURCE_1__

if [ "$#" -ne 0 ] && [ "$#" -ne 2 ]; then
  echo "usage: solve.sh [PUBLIC_AUDIT_V2_ZIP OUTPUT_DIR]" >&2
  exit 2
fi
if [ "$#" -eq 0 ]; then
  python3 "$WORK/solve.py"
else
  python3 "$WORK/solve.py" "$1" "$2"
fi
