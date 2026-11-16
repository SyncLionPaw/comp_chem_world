#!/usr/bin/env python3
"""Fail-closed evidence verifier for the case06 25-route and L3 task contract.

A scientific PASS requires every required native optimizer, same-surface minimum and M14
physical/remedy gate plus the frozen empirical bond rule. Synthetic component fixtures are
not scientific gold, and the currently collected reference/HPC components do not constitute
the complete 25-route evidence set.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import sys
import importlib.util
import zlib
from decimal import Decimal, InvalidOperation
from pathlib import Path
import science_profile
import scientific_summary
import native_science

CASE_ID = "case-06-es-geometry-execution-slice"
EXPECTED_REF_SHA256 = "e8b4adef1e1d9d30870ee3fa2c17f88b4bdd1540f82f96f5994ee35cbac3100e"
HISTORICAL_PROFILE_SHA256 = "4b6944e3774779a56cdd786eec1180ca7873945bceb50bb774d2cb0621d502c9"
MOLECULES = ("M2", "M3", "M14", "M19", "M29")
GS_ROUTES = ("pbe0-tzvp", "admm-tzvp-tzp")
ES_ROUTES = ("pbe0-tzvp", "admm-tzvp-tzp", "stda-pbe0-tzvp")
EXPECTED_RECORDS = {
    f"{molecule}/{state}/{route}"
    for molecule in MOLECULES
    for state, routes in (("GS", GS_ROUTES), ("ES", ES_ROUTES))
    for route in routes
}
SPECIES = {
    "M2": ["C", "O", "H", "H"],
    "M3": ["C", "S", "H", "H"],
    "M14": ["C", "O", "Cl", "H"],
    "M19": ["C", "O", "C", "H", "H", "H", "H"],
    "M29": ["N", "C", "C", "N", "C", "C", "H", "H", "H", "H"],
}
GTH_VALENCE = {"H": 1, "C": 4, "N": 5, "O": 6, "S": 6, "Cl": 7}
BONDS = {
    "M2": {"c o": [(0, 1)], "c h": [(0, 2), (0, 3)]},
    "M3": {"c s": [(0, 1)], "c h": [(0, 2), (0, 3)]},
    "M14": {"c o": [(0, 1)], "c cl": [(0, 2)], "c h": [(0, 3)]},
    "M19": {"c o": [(0, 1)], "c c": [(0, 2)], "c hald": [(0, 3)]},
    "M29": {"c n": [(1, 0), (2, 3), (4, 3), (5, 0)],
            "c c": [(1, 2), (4, 5)], "c h": [(6, 1), (7, 2), (8, 4), (9, 5)]},
}


def _clean_input(text: str) -> str:
    return "\n".join(line.split("!", 1)[0].split("#", 1)[0] for line in text.splitlines())


def _section_body(text: str, name: str) -> str:
    clean = _clean_input(text)
    lines = clean.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = re.match(r"^\s*&([A-Za-z_][A-Za-z0-9_]*)\b", line)
        if m and m.group(1).upper() == name.upper():
            start = i
            break
    if start is None:
        return ""
    depth = 1
    body = []
    for line in lines[start + 1:]:
        end = re.match(r"^\s*&END(?:\s+([A-Za-z_][A-Za-z0-9_]*))?\b", line, re.I)
        if end:
            if end.group(1) and depth == 1 and end.group(1).upper() != name.upper():
                return ""
            depth -= 1
            if depth == 0:
                return "\n".join(body)
            body.append(line)
            continue
        section = re.match(r"^\s*&([A-Za-z_][A-Za-z0-9_]*)\b", line)
        if section:
            depth += 1
        body.append(line)
    return ""


def _kind_sections(text: str) -> list[tuple[str, str]]:
    found = []
    for m in re.finditer(
            r"(?ims)^\s*&KIND\s+([A-Za-z][A-Za-z0-9_]*)\b(.*?)^\s*&END(?:\s+KIND)?\b", _clean_input(text)):
        name, body = m.group(1), m.group(2)
        element = re.search(r"(?im)^\s*ELEMENT\s+([A-Za-z]{1,2})\s*$", body)
        species = element.group(1).capitalize() if element else re.match(r"[A-Za-z]+", name).group(0).capitalize()
        found.append((species, body))
    return found


def _kind_aliases(text: str) -> dict[str, str]:
    aliases = {}
    for m in re.finditer(
            r"(?ims)^\s*&KIND\s+([A-Za-z][A-Za-z0-9_]*)\b(.*?)^\s*&END(?:\s+KIND)?\b", _clean_input(text)):
        element = re.search(r"(?im)^\s*ELEMENT\s+([A-Za-z]{1,2})\s*$", m.group(2))
        aliases[m.group(1).capitalize()] = element.group(1).capitalize() if element else re.match(
            r"[A-Za-z]+", m.group(1)).group(0).capitalize()
    return aliases


def _science_method_signature(text: str) -> dict:
    """Return the validated electronic identity that a final-R VIB run must preserve."""
    clean = _clean_input(text)
    force_eval = _section_body(clean, "FORCE_EVAL")
    dft = _section_body(clean, "DFT")
    def directives(block: str, names: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
        allowed = {x.upper() for x in names}
        rows = []
        for line in block.splitlines():
            p = line.split()
            if p and p[0].upper() in allowed:
                values = []
                for value in p[1:]:
                    try:
                        number = Decimal(value.replace("D", "E").replace("d", "e"))
                    except InvalidOperation:
                        values.append(value.upper())
                    else:
                        values.append(format(number.normalize(), "f") if number.is_finite() else str(number))
                rows.append((p[0].upper(), " ".join(values)))
        return tuple(rows)

    xc_section = _section_body(dft, "XC")
    hf = _section_body(xc_section, "HF") or _section_body(dft, "HF")
    xc_semantics = native_science.pbe0_semantics(text)
    hf_fraction_match = re.search(r"(?im)^\s*FRACTION\s+(\S+)", hf)
    try:
        hf_fraction = (xc_semantics["hf_fraction"] if xc_semantics else
                       float(hf_fraction_match.group(1).replace("D", "E")) if hf_fraction_match else 0.25)
    except (ValueError, OverflowError):
        hf_fraction = None
    xc = xc_semantics["xc"] if xc_semantics else tuple(
        x.upper() for x in re.findall(r"(?im)^\s*&XC_FUNCTIONAL\s+([A-Za-z0-9_-]+)", dft))
    charge_mult = directives(dft, ("CHARGE", "MULTIPLICITY"))
    qs_method = directives(_section_body(dft, "QS"), ("METHOD",))
    hf_physics = xc_semantics["hf_physics"] if xc_semantics else directives(hf, ("INTERACTION_POTENTIAL", "POTENTIAL_TYPE", "CUTOFF_RADIUS",
                                 "OMEGA", "RANGE_SEPARATOR", "LONG_RANGE_CORRECTION"))
    cell = directives(_section_body(clean, "CELL"), ("ABC", "A", "B", "C", "PERIODIC"))
    kind_signature = []
    for species, body in _kind_sections(clean):
        kind_signature.append((species, directives(body, ("BASIS_SET", "POTENTIAL"))))
    es = _section_body(clean, "EXCITED_STATES")
    prop = _section_body(clean, "PROPERTIES")
    td = _section_body(prop, "TDDFPT") or _section_body(clean, "TDDFPT")
    td_triplets = directives(td, ("RKS_TRIPLETS",))
    stda = _section_body(td, "STDA")
    fractions = []
    for value in re.findall(r"(?im)^\s*FRACTION\s+(\S+)", stda):
        try:
            number = float(value.replace("D", "E"))
        except (ValueError, OverflowError):
            number = None
        fractions.append(number)
    admm = _section_body(dft, "AUXILIARY_DENSITY_MATRIX_METHOD")
    es_header = re.search(r"(?im)^\s*&EXCITED_STATES(?:\s+([^\s!#]+))?", clean)
    es_active = True
    if es_header and es_header.group(1):
        es_active = es_header.group(1).upper() not in ("F", "FALSE", ".FALSE.", "0")
    return {
        "force_eval_method": directives(force_eval, ("METHOD",)),
        "basis_file": directives(dft, ("BASIS_SET_FILE_NAME",)),
        "potential_file": directives(dft, ("POTENTIAL_FILE_NAME",)),
        "xc_functional": xc,
        "charge_multiplicity": charge_mult,
        "qs_method": qs_method,
        "hf_fraction": hf_fraction,
        "hf_physics": hf_physics,
        "kind_basis_potential": tuple(sorted(kind_signature)),
        "cell_periodicity": cell,
        "kernel": tuple(x.upper() for x in re.findall(r"(?im)^\s*KERNEL\s+(\S+)", td)),
        "stda_fraction": tuple(fractions),
        "admm": directives(admm, ("METHOD", "ADMM_PURIFICATION_METHOD", "EXCH_CORRECTION_FUNC",
                                    "EXCH_CORRECTION", "EXCH_MODEL")),
        "excited_state_active": es_active,
        "excited_state": directives(es, ("STATE", "MULTIPLICITY")),
        "td_rks_triplets": td_triplets,
    }


def _checked_data_artifact_map(owner: dict, label: str, final: Path, report: dict,
                               *, route: str | None = None) -> dict | None:
    artifacts = owner.get("data_artifacts")
    if not isinstance(artifacts, dict):
        return None
    required = {"basis", "potential"}
    if route == "admm-tzvp-tzp":
        required.add("admm_basis")
    if not required.issubset(artifacts):
        report["problems"].append(f"{label}: data_artifacts lacks {sorted(required - set(artifacts))}")
        return {}
    checked = {}
    for logical_name, entry in artifacts.items():
        if not isinstance(logical_name, str) or not isinstance(entry, dict):
            report["problems"].append(f"{label}: malformed data artifact entry")
            continue
        path = _safe_artifact(final, entry.get("path"), f"{label}.data_artifacts.{logical_name}", report["problems"])
        expected = entry.get("sha256")
        if path is None:
            continue
        actual = sha256(path)
        if not isinstance(expected, str) or actual != expected:
            report["problems"].append(f"{label}: data artifact {logical_name} SHA-256 mismatch")
        checked[logical_name] = actual
    return checked


def _input_coordinates(text: str) -> list[tuple[str, float, float, float]]:
    body = _section_body(text, "COORD")
    if not body:
        return []
    rows = []
    for line in body.splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) < 4:
            raise ValueError("incomplete coordinate row")
        coords = tuple(float(x) for x in parts[1:4])
        if not all(math.isfinite(x) for x in coords):
            raise ValueError("nonfinite input coordinate")
        rows.append((parts[0].capitalize(), *coords))
    return rows


def _xyz_frames(path: Path) -> list[list[tuple[str, float, float, float]]]:
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    frames = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        try:
            n = int(lines[i].strip())
        except ValueError as exc:
            raise ValueError(f"invalid XYZ atom count at line {i+1}") from exc
        if n <= 0 or i + n + 2 > len(lines):
            raise ValueError(f"truncated/invalid XYZ frame at line {i+1}")
        frame = []
        for line in lines[i + 2:i + 2 + n]:
            parts = line.split()
            if len(parts) < 4:
                raise ValueError("truncated XYZ atom row")
            xyz = tuple(float(x) for x in parts[1:4])
            if not all(math.isfinite(x) for x in xyz):
                raise ValueError("nonfinite XYZ coordinate")
            frame.append((parts[0].capitalize(), *xyz))
        if len(frame) != n:
            raise ValueError("XYZ atom count does not match frame header")
        frames.append(frame)
        i += n + 2
    if not frames:
        raise ValueError("XYZ file has no complete frames")
    return frames


def _distance(a: tuple, b: tuple) -> float:
    value = math.hypot(*(a[k] - b[k] for k in range(1, 4)))
    if not math.isfinite(value):
        raise ValueError("derived geometry distance is nonfinite")
    return value


def _bond_values(molecule: str, label: str, atoms: list[tuple]) -> list[float] | None:
    groups = BONDS.get(molecule, {}).get(label.lower())
    if groups is None:
        return None
    values = [_distance(atoms[a], atoms[b]) * 100.0 for a, b in groups]
    if not all(math.isfinite(x) for x in values):
        raise ValueError("derived bond length is nonfinite")
    # Preserve the full distance reconstructed from the native XYZ.  The CSV is
    # a display artifact; scientific gates must not consume its 0.001 pm rounding.
    return values


def _xyz_last_frame_coordinate_half_units_pm(path: Path) -> list[tuple[float, float, float]]:
    """Bound coordinate serialization error from the actual final XYZ tokens."""
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    i = 0
    final_rows = None
    number = re.compile(r"^[+-]?(?:(?:\d+(?:\.(\d*))?)|(?:\.(\d+)))(?:[Ee]([+-]?\d+))?$")
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        n = int(lines[i].strip())
        if n <= 0 or i + n + 2 > len(lines):
            raise ValueError("truncated XYZ while estimating coordinate precision")
        rows = []
        for row in lines[i + 2:i + 2 + n]:
            parts = row.split()
            if len(parts) < 4:
                raise ValueError("malformed XYZ while estimating coordinate precision")
            axes = []
            for token in parts[1:4]:
                match = number.fullmatch(token)
                if not match:
                    raise ValueError("unsupported coordinate token while estimating XYZ precision")
                decimals = len(match.group(1) if match.group(1) is not None else match.group(2) or "")
                exponent = int(match.group(3) or 0)
                half_unit = 0.5 * (10.0 ** (exponent - decimals)) * 100.0
                if not math.isfinite(half_unit):
                    raise ValueError("nonfinite XYZ coordinate precision bound")
                axes.append(half_unit)
            rows.append(tuple(axes))
        final_rows = rows
        i += n + 2
    if not final_rows:
        raise ValueError("XYZ contains no complete frame for coordinate precision")
    return final_rows


def _bond_coordinate_uncertainty_pm(molecule: str, label: str,
                                    coordinate_half_units_pm: list[tuple[float, float, float]],
                                    atom_map: list[int]) -> float:
    """Lipschitz bound for mean bond length from rounded Cartesian coordinates."""
    groups = BONDS.get(molecule, {}).get(label.lower())
    if groups is None:
        raise ValueError(f"unknown bond group {molecule}/{label}")
    bounds = []
    for canonical_a, canonical_b in groups:
        a, b = atom_map[canonical_a], atom_map[canonical_b]
        error = math.hypot(*(coordinate_half_units_pm[a][axis] + coordinate_half_units_pm[b][axis]
                             for axis in range(3)))
        bounds.append(error)
    result = math.fsum(bounds) / len(bounds)
    if not math.isfinite(result):
        raise ValueError("derived XYZ bond precision bound is nonfinite")
    return result


def _valid_state_manifold(nstates: int, states: list[tuple[int, float]]) -> bool:
    """Require indexed positive excitation energies; exact degeneracies are allowed."""
    return (nstates > 0 and len(states) == nstates
            and [index for index, _ in states] == list(range(1, nstates + 1))
            and all(math.isfinite(energy) and energy > 0 for _, energy in states)
            and all(states[i][1] <= states[i + 1][1] for i in range(len(states) - 1)))


class InfraError(Exception):
    """Broken grading inputs/dependencies: exit 2 and no reward."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_refs(tests: Path) -> dict:
    path = tests / "refs.json"
    if not path.is_file():
        raise InfraError("tests/refs.json is missing")
    if sha256(path) != EXPECTED_REF_SHA256:
        raise InfraError("case06 SI reference bytes do not match the reviewed source snapshot")
    try:
        refs = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InfraError(f"case06 SI reference is unreadable/invalid: {exc}") from exc
    if refs.get("schema") != "case06-reference/v3":
        raise InfraError("unexpected case06 reference schema")
    if set(refs.get("target_molecules", {})) != set(MOLECULES):
        raise InfraError("reference target molecule inventory changed")
    es_bonds = {k: v for k, v in refs.get("items", {}).items()
                if v.get("state") == "ES" and v.get("quantity") == "bond"}
    if len(es_bonds) != 13:
        raise InfraError(f"expected 13 published ES bond references, found {len(es_bonds)}")
    for entry in es_bonds.values():
        values = entry.get("values", {})
        for column in ("CCSD", "PBE0|TZVP", "ADMM|TZVP+tzp"):
            if not isinstance(values.get(column), (int, float)):
                raise InfraError(f"reference lacks numeric {column} value")
        stda = values.get("sTDA@PBE0|TZVP")
        if entry["molecule"] == "M14" and stda is not None:
            raise InfraError("M14 default-aEX sTDA must remain excluded/null")
        if entry["molecule"] != "M14" and not isinstance(stda, (int, float)):
            raise InfraError("non-M14 ES sTDA reference is missing")
    return refs


def _safe_artifact(final: Path, rel: object, field: str, problems: list[str]) -> Path | None:
    if not isinstance(rel, str) or not rel:
        problems.append(f"{field}: missing relative artifact path")
        return None
    if "\x00" in rel:
        problems.append(f"{field}: path contains a NUL byte")
        return None
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts:
        problems.append(f"{field}: path must be relative and cannot escape final/")
        return None
    try:
        full = (final / p).resolve()
        full.relative_to(final.resolve())
    except (ValueError, OSError, RuntimeError):
        problems.append(f"{field}: resolved path escapes final/")
        return None
    try:
        exists = full.is_file()
    except (OSError, RuntimeError):
        exists = False
    if not exists:
        problems.append(f"{field}: file does not exist ({rel})")
        return None
    return full


def _native_output_coordinates(out: str, n_atoms: int) -> list[list[tuple[str, float, float, float]]]:
    lines = out.splitlines()
    frames = []
    row_re = re.compile(r"^\s*\d+\s+\d+\s+([A-Za-z]{1,2})\s+\d+\s+([-+0-9.Ee]+)\s+([-+0-9.Ee]+)\s+([-+0-9.Ee]+)\b")
    for i, line in enumerate(lines):
        if not re.search(r"MODULE QUICKSTEP:\s+ATOMIC COORDINATES IN\s+angstrom", line, re.I):
            continue
        frame = []
        for row in lines[i + 1:]:
            match = row_re.match(row)
            if match:
                xyz = tuple(float(match.group(k)) for k in (2, 3, 4))
                if not all(math.isfinite(x) for x in xyz):
                    raise ValueError("native output contains nonfinite atom coordinates")
                frame.append((match.group(1).capitalize(), *xyz))
                if len(frame) == n_atoms:
                    break
            elif frame and row.strip():
                break
        if len(frame) == n_atoms:
            frames.append(frame)
    return frames


def _select_last_output_run(out: str) -> tuple[str, int]:
    """Select only the final CP2K invocation; never fall back to an earlier appended run."""
    starts = list(re.finditer(r"(?im)^.*PROGRAM STARTED AT\b", out))
    if not starts:
        return out, 0
    return out[starts[-1].start():], len(starts)


def _select_last_run_xyz_segment(output_run: str, trajectory: Path, tolerance: float = 5.1e-11) -> dict:
    """Recompute the complete optimizer-step/energy binding for one invocation."""
    energies = [float(x.replace("D", "E").replace("d", "e")) for x in re.findall(
        r"ENERGY\| Total FORCE_EVAL \( QS \) energy \[a\.u\.\]:\s*([-+\d.EeDd]+)", output_run)]
    step_ids = [int(x) for x in re.findall(r"Informations at step\s*=\s*(\d+)", output_run, re.I)]
    if len(energies) < 2 or len(step_ids) != len(energies) - 1 or step_ids != list(range(len(step_ids))):
        raise ValueError("last invocation lacks the complete native ENERGY/optimizer-step sequence")
    lines = trajectory.read_text(encoding="utf-8", errors="strict").splitlines()
    frames = []
    frame_ids = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        n = int(lines[i].strip())
        comment = lines[i + 1]
        match = re.search(r"(?:^|,\s*)E\s*=\s*([-+\d.EeDd]+)", comment)
        energy = float(match.group(1).replace("D", "E").replace("d", "e")) if match else None
        frames.append(energy)
        id_match = re.search(r"(?:^|,)\s*i\s*=\s*(\d+)", comment, re.I)
        frame_ids.append(int(id_match.group(1)) if id_match else None)
        i += n + 2
    optimizer_energies = energies[1:]
    expected_ids = list(range(1, len(step_ids) + 1))
    matches = []
    for offset in range(len(frames) - len(step_ids) + 1):
        candidate = frames[offset:offset + len(step_ids)]
        errors = [abs(a - b) if b is not None else math.inf for a, b in zip(optimizer_energies, candidate)]
        if (frame_ids[offset:offset + len(step_ids)] == expected_ids
                and all(math.isfinite(e) and e <= tolerance for e in errors)):
            matches.append((offset, max(errors, default=0.0)))
    if len(matches) != 1:
        raise ValueError(f"complete optimizer sequence does not identify one XYZ segment (matches={len(matches)})")
    first, max_error = matches[0]
    return {"start_zero_based": first, "end_zero_based_inclusive": first + len(step_ids) - 1,
            "count": len(step_ids), "last_invocation_energy_count": len(energies),
            "last_invocation_optimizer_step_ids": step_ids,
            "matched_energy_count": len(optimizer_energies), "max_energy_rounding_delta_hartree": max_error,
            "energy_match_tolerance_hartree": tolerance,
            "method": "complete-last-invocation-optimizer-energies[1:]-and-step-ids-to-XYZ/v2"}


def _check_hash(path: Path | None, record: dict, key: str, field: str, problems: list[str]) -> None:
    expected = record.get(key)
    if path is not None and (not isinstance(expected, str) or sha256(path) != expected):
        problems.append(f"{field}: SHA-256 is absent or does not match the artifact")


def _read_text(path: Path, where: str, problems: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        problems.append(f"{where}: cannot read artifact: {exc}")
        return ""


def _native_trace(record: dict, final: Path, problems: list[str], *, allow_dissociation: bool = False) -> dict:
    initial_problem_count = len(problems)
    fields = {
        "input": "input_path", "output": "output_path", "stderr": "stderr_path", "exit": "exit_code_path",
        "trajectory": "trajectory_path",
    }
    artifacts = {}
    for kind, key in fields.items():
        artifacts[kind] = _safe_artifact(final, record.get(key), key, problems)
    for kind, hash_key in (("input", "input_sha256"), ("output", "output_sha256"),
                           ("stderr", "stderr_sha256"),
                           ("exit", "exit_code_sha256"), ("trajectory", "trajectory_sha256")):
        _check_hash(artifacts.get(kind), record, hash_key, kind, problems)
    if not all(artifacts.get(k) for k in fields):
        return {"artifacts": artifacts, "native_traceable": False}

    inp = _read_text(artifacts["input"], "input", problems)
    clean_inp = _clean_input(inp)
    global_section = _section_body(clean_inp, "GLOBAL")
    dft_section = _section_body(clean_inp, "DFT")
    for kind, key in fields.items():
        rel = record.get(key)
        if not isinstance(rel, str) or not Path(rel).parts or Path(rel).parts[0] != "geometries":
            problems.append(f"{record.get('id')}: {kind} artifact must be under final/geometries/")
    output_file = _read_text(artifacts["output"], "output", problems)
    out, output_run_count = _select_last_output_run(output_file)
    if output_run_count == 0:
        problems.append(f"{record.get('id')}: output lacks a native PROGRAM STARTED AT boundary")
    stderr = _read_text(artifacts["stderr"], "stderr", problems)
    rc = _read_text(artifacts["exit"], "exit_code", problems).strip()
    if not re.fullmatch(r"\d+", rc):
        problems.append(f"{record.get('id')}: launcher exit code is not an integer")
    if rc != "0" and not allow_dissociation:
        problems.append(f"{record.get('id')}: native CP2K exit code is {rc!r}, expected 0")
    if allow_dissociation:
        # Termination is reported independently by classify_m14_dissociation.
        # A later resource stop cannot erase an already complete physical prefix,
        # and the stop itself is never accepted as proof of dissociation.
        pass
    if "CP2K| version string:" not in out or (not allow_dissociation and "PROGRAM ENDED AT" not in out):
        problems.append(f"{record.get('id')}: output lacks CP2K version or normal-end marker")
    if not allow_dissociation and "GEOMETRY OPTIMIZATION COMPLETED" not in out:
        problems.append(f"{record.get('id')}: output does not show completed GEO_OPT")
    if not allow_dissociation and not re.search(
            r"(?im)^\s*(?:OPT\| Step number\s+\d+|OPTIMIZATION STEP:\s*\d+)\s*$", out):
        problems.append(f"{record.get('id')}: output lacks native geometry-optimization step evidence")
    scf_markers = list(re.finditer(r"SCF run (NOT )?converged", out, re.I))
    if (not scf_markers or
            (not allow_dissociation and scf_markers[-1].group(1)) or
            (allow_dissociation and not any(not m.group(1) for m in scf_markers))):
        problems.append(f"{record.get('id')}: output lacks an unambiguous converged SCF trace")
    if not re.search(r"SCF WAVEFUNCTION OPTIMIZATION", out, re.I):
        problems.append(f"{record.get('id')}: output lacks a native iterative SCF block")
    scf_energy_text = re.findall(r"(?m)^\s*Total energy:\s*([-+0-9.Ee]+)\s*$", out)
    try:
        if not scf_energy_text or not all(math.isfinite(float(value)) for value in scf_energy_text):
            problems.append(f"{record.get('id')}: native SCF energy trace is absent or nonfinite")
    except (ValueError, OverflowError):
        problems.append(f"{record.get('id')}: native SCF energy trace is malformed")
    es_open = re.search(r"(?im)^\s*&EXCITED_STATES(?:\s+(\S+))?", clean_inp)
    es_body = _section_body(clean_inp, "EXCITED_STATES")
    explicit_state = re.search(r"(?im)^\s*STATE\s+\d+\s*$", es_body)
    active_es = bool(es_open and (not es_open.group(1) or es_open.group(1).upper() not in {"F", "FALSE", ".FALSE."}))
    if record.get("state") == "GS" and active_es:
        problems.append(f"{record.get('id')}: GS record requests an active excited-state geometry")
    if record.get("state") == "ES":
        legacy_singlet = bool(re.search(r"R-TDDFPT states of multiplicity\s+1", out))
        if (not active_es or not re.search(r"(?im)^\s*&TDDFPT\b", clean_inp)
                or ("TDDFPT| Number of states calculated" not in out and not legacy_singlet)):
            problems.append(f"{record.get('id')}: ES deck/output lacks TDDFPT state evidence")
        if not re.search(r"(?im)^\s*STATE\s+1\s*$", clean_inp):
            problems.append(f"{record.get('id')}: ES deck does not request S1")
        triplets = re.search(r"(?im)^\s*RKS_TRIPLETS\s+(\S+)\s*$", clean_inp)
        triplets_off = bool(triplets and triplets.group(1).upper() in {"F", "FALSE", ".FALSE."})
        if not (re.search(r"Spin symmetry of excitations\s+Singlet", out, re.I) or legacy_singlet) or not triplets_off:
            problems.append(f"{record.get('id')}: singlet-only state evidence is missing")
        nstates_in = re.findall(r"(?im)^\s*NSTATES\s+(\d+)\s*$", clean_inp)
        counts = [int(x) for x in re.findall(r"TDDFPT\| Number of states calculated\s+(\d+)", out)]
        states = [(int(i), float(e)) for i, e in re.findall(
            r"(?m)^\s*TDDFPT\|\s+(\d+)\s+([0-9]+(?:\.[0-9]*)?(?:[Ee][+-]?\d+)?)\s+", out)]
        if legacy_singlet and not counts:
            last_legacy_block = out.rsplit("R-TDDFPT states of multiplicity 1", 1)[-1]
            states = [(int(i), float(e)) for i, e in re.findall(
                r"(?m)^\s*TDDFPT\|\s+(\d+)\s+([0-9]+(?:\.[0-9]*)?(?:[Ee][+-]?\d+)?)\s+",
                last_legacy_block)]
        nstates = counts[-1] if counts else (len(states) if legacy_singlet else 0)
        last_states = states[-nstates:] if nstates and len(states) >= nstates else []
        if (len(nstates_in) != 1 or not nstates_in or int(nstates_in[0]) != nstates
                or not _valid_state_manifold(nstates, last_states)):
            problems.append(f"{record.get('id')}: final singlet manifold does not establish ordered positive S1 states")
        td_markers = list(re.finditer(r"TDDFPT run (NOT )?converged", out, re.I))
        if not allow_dissociation and (not td_markers or td_markers[-1].group(1)):
            problems.append(f"{record.get('id')}: final TDDFPT iteration did not converge")
        linear_markers = list(re.finditer(r"linear solver (NOT )?converged", out, re.I))
        if not allow_dissociation and (not linear_markers or linear_markers[-1].group(1)):
            problems.append(f"{record.get('id')}: final S1 force linear solve did not converge")
        if allow_dissociation and "TDDFPT| Number of states calculated" not in out and not legacy_singlet:
            problems.append(f"{record.get('id')}: physical failure lacks any native excited-state calculation")
    if not re.search(r"(?im)^\s*RUN_TYPE\s+GEO_OPT\s*$", global_section):
        problems.append(f"{record.get('id')}: input is not a GEO_OPT")
    kind_sections = _kind_sections(clean_inp)
    expected_species = set(SPECIES.get(record.get("molecule"), []))
    kind_by_species = {name: body for name, body in kind_sections}
    if expected_species - set(kind_by_species):
        problems.append(f"{record.get('id')}: KIND blocks do not cover the molecule elements")
    for element in expected_species:
        body = kind_by_species.get(element, "")
        if not re.search(r"(?im)^\s*BASIS_SET\s+(?:ORB\s+)?TZVP-MOLOPT-PBE0-GTH-", body):
            problems.append(f"{record.get('id')}: {element} KIND lacks TZVP-MOLOPT-PBE0-GTH basis")
        if not re.search(rf"(?im)^\s*POTENTIAL\s+GTH-PBE0-q{GTH_VALENCE.get(element, -1)}\s*$", body):
            problems.append(f"{record.get('id')}: {element} KIND lacks GTH-PBE0 potential")
    if not re.search(r"(?im)^\s*BASIS_SET_FILE_NAME\s+\S+", dft_section):
        problems.append(f"{record.get('id')}: DFT section lacks a basis data-file declaration")
    if not re.search(r"(?im)^\s*POTENTIAL_FILE_NAME\s+\S+", dft_section):
        problems.append(f"{record.get('id')}: DFT section lacks a potential data-file declaration")
    if record.get("route") == "admm-tzvp-tzp":
        admm_section = _section_body(dft_section, "AUXILIARY_DENSITY_MATRIX_METHOD")
        if (not admm_section
                or not re.search(r"(?im)^\s*METHOD\s+BASIS_PROJECTION\s*$", admm_section)
                or not re.search(r"(?im)^\s*ADMM_PURIFICATION_METHOD\s+NONE\s*$", admm_section)
                or not re.search(r"(?im)^\s*EXCH_CORRECTION_FUNC\s+NONE\s*$", admm_section)
                or any(not re.search(r"(?im)^\s*BASIS_SET\s+AUX_FIT\s+admm-tzp-", kind_by_species.get(element, ""))
                       for element in expected_species)
                or re.search(r"(?im)^\s*KERNEL\s+sTDA\s*$", clean_inp)):
            problems.append(f"{record.get('id')}: input lacks ADMM2/tzp method evidence")
    elif record.get("route") == "stda-pbe0-tzvp":
        if not re.search(r"(?im)^\s*KERNEL\s+sTDA\s*$", clean_inp):
            problems.append(f"{record.get('id')}: input lacks sTDA kernel")
        if _section_body(dft_section, "AUXILIARY_DENSITY_MATRIX_METHOD"):
            problems.append(f"{record.get('id')}: sTDA route unexpectedly includes ADMM")
        try:
            aex = float(record.get("aex"))
        except (TypeError, ValueError):
            aex = math.nan
        if not math.isfinite(aex):
            problems.append(f"{record.get('id')}: sTDA aEX is not a finite number")
        td_body = _section_body(_section_body(clean_inp, "PROPERTIES"), "TDDFPT")
        stda_body = _section_body(td_body, "STDA")
        fractions_raw = re.findall(r"(?im)^\s*FRACTION\s+(\S+)\s*$", stda_body)
        try:
            fractions = [float(x) for x in fractions_raw]
        except ValueError:
            fractions = []
        if (len(fractions) != 1 or not all(math.isfinite(x) for x in fractions)
                or not math.isfinite(aex) or abs(fractions[0] - aex) > 1e-10):
            problems.append(f"{record.get('id')}: input sTDA FRACTION disagrees with declared aEX")
    elif _section_body(dft_section, "AUXILIARY_DENSITY_MATRIX_METHOD") or re.search(r"(?im)^\s*KERNEL\s+sTDA\s*$", clean_inp):
        problems.append(f"{record.get('id')}: route input contains a conflicting method")
    if record.get("state") == "ES" and record.get("route") != "stda-pbe0-tzvp":
        if not re.search(r"(?im)^\s*KERNEL\s+FULL\s*$", clean_inp):
            problems.append(f"{record.get('id')}: ES input does not use the full TDDFT kernel")
    try:
        input_atoms = _input_coordinates(clean_inp)
        aliases = _kind_aliases(clean_inp)
        input_atoms = [(aliases.get(a[0], a[0]), *a[1:]) for a in input_atoms]
        frames = _xyz_frames(artifacts["trajectory"])
        expected_species = SPECIES[record["molecule"]]
        atom_map = record.get("atom_map", list(range(len(input_atoms))))
        if (not isinstance(atom_map, list) or len(atom_map) != len(input_atoms)
                or any(type(x) is not int for x in atom_map)
                or sorted(atom_map) != list(range(len(input_atoms)))):
            problems.append(f"{record.get('id')}: atom_map must map canonical atoms to native atom indices")
            atom_map = list(range(len(input_atoms)))
        canonical_input = [input_atoms[i] for i in atom_map]
        if [a[0] for a in canonical_input] != expected_species:
            problems.append(f"{record.get('id')}: input atom composition/order does not match molecule identity")
        if any(len(frame) != len(input_atoms) or
               [a[0] for a in [frame[j] for j in atom_map]] != expected_species for frame in frames):
            problems.append(f"{record.get('id')}: native trajectory atom identity/order changes or is wrong")
        if len(input_atoms) != len(frames[0]):
            problems.append(f"{record.get('id')}: input and first trajectory frame atom counts differ")
        # CP2K's first GEO_OPT XYZ frame can already be post-step. Input coordinates are
        # therefore checked for atom identity/count, while trajectory authenticity is only
        # cross-linked to the final native energy below; no false input==frame gate is used.
        # CP2K XYZ carries the energy in its frame comment; link final coordinates to final native energy.
        xyz_lines = artifacts["trajectory"].read_text(encoding="utf-8").splitlines()
        comment_idx = sum(len(frame) + 2 for frame in frames[:-1]) + 1
        comment = xyz_lines[comment_idx] if comment_idx < len(xyz_lines) else ""
        frame_energy = re.search(r"\bE\s*=\s*([-+0-9.Ee]+)", comment)
        output_energies = re.findall(r"ENERGY\| Total FORCE_EVAL \( QS \) energy \[[^]]+\]:?\s*([-+0-9.Ee]+)", out)
        native_coord_frames = _native_output_coordinates(out, len(input_atoms))
        if not native_coord_frames:
            problems.append(f"{record.get('id')}: output lacks native atom-coordinate frames")
        else:
            native_atoms = native_coord_frames[0]
            if [atom[0] for atom in native_atoms] != expected_species:
                problems.append(f"{record.get('id')}: native output coordinates disagree with input atom identity/order")
        if frame_energy and output_energies:
            try:
                frame_e = float(frame_energy.group(1))
                native_es = [float(x) for x in output_energies]
            except (ValueError, OverflowError):
                frame_e, native_es = math.nan, []
            if (not math.isfinite(frame_e) or not native_es
                    or not all(math.isfinite(x) for x in native_es)):
                problems.append(f"{record.get('id')}: final energy trace contains nonfinite values")
            elif abs(frame_e - native_es[-1]) > 1e-6:
                problems.append(f"{record.get('id')}: final XYZ energy does not match the last native FORCE_EVAL energy")
        elif not allow_dissociation:
            problems.append(f"{record.get('id')}: cannot link final XYZ frame to native FORCE_EVAL energy")
    except (OSError, UnicodeDecodeError, ValueError, KeyError, IndexError, TypeError, OverflowError) as exc:
        problems.append(f"{record.get('id')}: malformed input/trajectory artifact: {exc}")
    version_match = re.search(r"CP2K\| version string:\s*(.+)", out)
    return {"artifacts": artifacts, "native_traceable": len(problems) == initial_problem_count,
            "engine_version": version_match.group(1).strip() if version_match else None,
            "native_run_count": output_run_count,
            "geo_opt_completed": "GEOMETRY OPTIMIZATION COMPLETED" in out,
            "normal_end": "PROGRAM ENDED AT" in out}


def _verify_sTDA_ground_link(record: dict, gs_record: dict, final: Path,
                             problems: list[str]) -> None:
    rec_id = record.get("id", "sTDA record")
    ref = record.get("ground_reference")
    if not isinstance(ref, dict) or ref.get("record_id") != gs_record.get("id"):
        problems.append(f"{rec_id}: sTDA must link the matching PBE0/TZVP GS record")
        return
    for field in ("input_sha256", "output_sha256", "trajectory_sha256"):
        if ref.get(field) != gs_record.get(field):
            problems.append(f"{rec_id}: ground-reference {field} does not match the PBE0 GS record")
    receipt_rel = record.get("ground_reference_path")
    if receipt_rel is None:
        return  # Alternative valid ES starting structures are allowed by the contract.
    receipt_path = _safe_artifact(final, receipt_rel, f"{rec_id}.ground_reference_path", problems)
    _check_hash(receipt_path, record, "ground_reference_sha256", f"{rec_id} GS receipt", problems)
    if receipt_path is None:
        return
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        inp = _safe_artifact(final, record.get("input_path"), f"{rec_id}.input_path", problems)
        gs_xyz = _safe_artifact(final, gs_record.get("trajectory_path"), f"{gs_record.get('id')}.trajectory", problems)
        if not isinstance(receipt, dict) or receipt.get("schema") != "case06-gs-geometry-render/v1":
            raise ValueError("invalid GS geometry-render receipt schema")
        if (receipt.get("rendered_input_sha256") != record.get("input_sha256")
                or receipt.get("source_gs_trajectory_sha256") != gs_record.get("trajectory_sha256")
                or receipt.get("source_gs_output_sha256") != gs_record.get("output_sha256")):
            raise ValueError("GS geometry-render receipt does not bind the submitted input and PBE0 GS artifacts")
        if inp is None or gs_xyz is None:
            return
        input_atoms = _input_coordinates(_read_text(inp, "sTDA input", problems))
        gs_atoms = _xyz_frames(gs_xyz)[-1]
        if receipt.get("rendered_geometry_start") is True:
            if len(input_atoms) != len(gs_atoms) or any(a[0] != b[0] for a, b in zip(input_atoms, gs_atoms)):
                raise ValueError("rendered sTDA start differs in atom identity/count from linked PBE0 GS geometry")
            if any(abs(a[k] - b[k]) > 6e-9 for a, b in zip(input_atoms, gs_atoms) for k in range(1, 4)):
                raise ValueError("rendered sTDA input COORD is not the linked PBE0 GS optimized geometry")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, OverflowError) as exc:
        problems.append(f"{rec_id}: invalid PBE0 GS geometry link: {exc}")


def _finite_number(row: dict[str, str], field: str, where: str, problems: list[str]) -> float | None:
    try:
        value = float(row.get(field, ""))
    except (TypeError, ValueError):
        problems.append(f"{where}: {field} is missing or not numeric")
        return None
    if not math.isfinite(value):
        problems.append(f"{where}: {field} is not finite")
        return None
    return value


def _comparison_check(rows: list[dict[str, str]], refs: dict, by_id: dict[str, dict],
                      final: Path, problems: list[str], *,
                      measurement_uncertainties: dict[tuple[str, str, str], float] | None = None
                      ) -> dict[tuple[str, str, str], float]:
    """Cross-check comparison.csv against native final XYZ and frozen SI values.

    The geometry parser's canonical atom order follows the existing case06 input builder.
    An optional atom_map maps canonical indices to the submitted XYZ index order.
    This is a consistency check, not an acceptance tolerance for reproducing the paper.
    """
    ref_items = {k: v for k, v in refs["items"].items()
                 if v.get("state") == "ES" and v.get("quantity") == "bond"}
    route_columns = {"pbe0-tzvp": "PBE0|TZVP", "admm-tzvp-tzp": "ADMM|TZVP+tzp",
                     "stda-pbe0-tzvp": "sTDA@PBE0|TZVP"}
    expected = {}
    computed = {}
    for ref_key, ref in ref_items.items():
        molecule = ref["molecule"]
        label = ref["label"]
        for route, column in route_columns.items():
            published = ref["values"].get(column)
            if published is None:
                continue
            rec_id = f"{molecule}/ES/{route}"
            expected[(molecule, route, label)] = (ref_key, float(published), float(ref["values"]["CCSD"]))
            rec = by_id[rec_id]
            trajectory = _safe_artifact(final, rec.get("trajectory_path"), f"{rec_id}.trajectory", problems)
            if trajectory is None:
                continue
            try:
                frames = _xyz_frames(trajectory)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                problems.append(f"{rec_id}: malformed native XYZ trajectory: {exc}")
                continue
            frame_index = rec.get("selected_frame_index_zero_based", len(frames) - 1)
            if type(frame_index) is not int or not 0 <= frame_index < len(frames):
                problems.append(f"{rec_id}: selected endpoint frame index is invalid")
                continue
            atoms = frames[frame_index]
            atom_map = rec.get("atom_map", list(range(len(atoms))))
            if (not isinstance(atom_map, list) or len(atom_map) != len(atoms)
                    or any(type(x) is not int for x in atom_map)
                    or sorted(atom_map) != list(range(len(atoms)))):
                problems.append(f"{rec_id}: atom_map must be a permutation of trajectory atom indices")
                continue
            canonical_atoms = [atoms[i] for i in atom_map]
            species = [a[0].capitalize() for a in canonical_atoms]
            expected_species = SPECIES[molecule]
            if species != expected_species:
                problems.append(f"{rec_id}: atom_map does not match the canonical molecule composition/order")
                continue
            try:
                values = _bond_values(molecule, label, canonical_atoms)
                if measurement_uncertainties is not None:
                    precision = _xyz_last_frame_coordinate_half_units_pm(trajectory)
                    measurement_uncertainties[(molecule, route, label)] = _bond_coordinate_uncertainty_pm(
                        molecule, label, precision, atom_map)
            except (ValueError, OverflowError) as exc:
                problems.append(f"{rec_id}: native geometry contains nonfinite derived bond data: {exc}")
                continue
            if values is None:
                problems.append(f"{rec_id}: no geometry mapping for published bond {label}")
            else:
                # Keep unrounded native geometry for the scientific interval gate
                # and checker summary. comparison.csv remains a display table.
                computed[(molecule, route, label)] = math.fsum(values) / len(values)

    seen = set()
    required = {"molecule", "route", "label", "computed_mean_pm", "published_cp2k_pm",
                "ccsd_pm", "delta_cp2k_pm", "delta_ccsd_pm"}
    for i, row in enumerate(rows, 2):
        where = f"comparison.csv row {i}"
        if not required <= set(row):
            problems.append(f"{where}: required columns missing")
            return computed
        key_fields = [row.get(k) for k in ("molecule", "route", "label")]
        if any(not isinstance(x, str) for x in key_fields):
            problems.append(f"{where}: molecule, route and label must be nonempty strings")
            continue
        key = tuple(x.strip() for x in key_fields)
        if any(not x for x in key):
            problems.append(f"{where}: molecule, route and label must be nonempty strings")
            continue
        if key in seen:
            problems.append(f"{where}: duplicate comparison key {key}")
            continue
        seen.add(key)
        if key not in expected:
            problems.append(f"{where}: unknown/unavailable method comparison key {key}")
            continue
        ref_key, pub, ccsd = expected[key]
        values = {f: _finite_number(row, f, where, problems) for f in required - {"molecule", "route", "label"}}
        got_geom = computed.get(key)
        if got_geom is None:
            continue
        # Geometry rows are printed to 0.001 pm in the collector; 0.02 pm only covers
        # representation rounding and is not used as a scientific reproduction gate.
        for field, want in (("computed_mean_pm", got_geom), ("published_cp2k_pm", pub), ("ccsd_pm", ccsd),
                            ("delta_cp2k_pm", got_geom - pub), ("delta_ccsd_pm", got_geom - ccsd)):
            got = values[field]
            tol = 0.02 if field in ("computed_mean_pm", "delta_cp2k_pm", "delta_ccsd_pm") else 1e-9
            if got is not None and abs(got - want) > tol:
                problems.append(f"{where}: {field} does not match the referenced geometry/source ({ref_key})")
    missing = set(expected) - seen
    if missing:
        problems.append(f"comparison.csv is missing {len(missing)} available ES bond/method rows")
    return computed


def _review_unsupported_xc(input_text: str, record_id: str, report: dict) -> bool:
    """Mark unsupported XC syntax for review; never infer it is PBE0 or fail by guesswork."""
    if native_science.pbe0_semantics(input_text) is not None:
        return False
    report["unsupported_method_semantics"] = True
    report["pending_science_reviews"].append(
        f"{record_id}: XC form is outside the source-validated PBE0 equivalence rules")
    return True


def _native_minimum_status(rec: dict, final: Path, report: dict) -> dict:
    """Recompute minimum evidence only from path/hash-bound native artifacts.

    Candidate JSON may point at artifacts, but it cannot declare a passing status
    or provide its own stationarity thresholds.
    """
    evidence = rec.get("minimum_evidence")
    rec_id = rec.get("id", "minimum record")
    result = {"status": "UNVERIFIED", "record_id": rec_id, "issues": []}
    if not isinstance(evidence, dict) or evidence.get("schema") != "case06-native-vib-evidence/v1":
        result["issues"].append("missing case06-native-vib-evidence/v1 artifact map")
        report["pending_science_reviews"].append(f"{rec_id}: native projected-vibration minimum evidence is unavailable")
        return result

    # Optimizer geometry and restart must independently identify the final R.
    opt_xyz = _safe_artifact(final, rec.get("trajectory_path"), f"{rec_id}.trajectory_path", report["problems"])
    opt_out = _safe_artifact(final, rec.get("output_path"), f"{rec_id}.output_path", report["problems"])
    restart = _safe_artifact(final, evidence.get("restart_path"), f"{rec_id}.minimum.restart_path", report["problems"])
    vib_input = _safe_artifact(final, evidence.get("input_path"), f"{rec_id}.minimum.input_path", report["problems"])
    vib_output = _safe_artifact(final, evidence.get("output_path"), f"{rec_id}.minimum.output_path", report["problems"])
    vib_log = _safe_artifact(final, evidence.get("vib_log_path"), f"{rec_id}.minimum.vib_log_path", report["problems"])
    replica_rels = evidence.get("replica_output_paths")
    replica_paths = []
    if not isinstance(replica_rels, list) or not replica_rels or any(not isinstance(x, str) for x in replica_rels):
        report["problems"].append(f"{rec_id}: replica_output_paths must be a nonempty path array")
    else:
        for i, rel in enumerate(replica_rels):
            path = _safe_artifact(final, rel, f"{rec_id}.minimum.replica_output_paths[{i}]", report["problems"])
            if path:
                replica_paths.append(path)

    hash_specs = [
        (opt_xyz, rec, "trajectory_sha256", f"{rec_id} optimizer trajectory"),
        (opt_out, rec, "output_sha256", f"{rec_id} optimizer output"),
        (restart, evidence, "restart_sha256", f"{rec_id} final restart"),
        (vib_input, evidence, "input_sha256", f"{rec_id} VIB input"),
        (vib_output, evidence, "output_sha256", f"{rec_id} VIB output"),
        (vib_log, evidence, "vib_log_sha256", f"{rec_id} VIB log"),
    ]
    for path, source, field, label in hash_specs:
        _check_hash(path, source, field, label, report["problems"])
    replica_hashes = evidence.get("replica_output_sha256")
    if not isinstance(replica_hashes, list) or len(replica_hashes) != len(replica_paths):
        report["problems"].append(f"{rec_id}: replica output hashes do not match the path list")
    else:
        for i, (path, digest) in enumerate(zip(replica_paths, replica_hashes)):
            if not isinstance(digest, str) or sha256(path) != digest:
                report["problems"].append(f"{rec_id}: replica output {i} SHA-256 mismatch")

    if not all((opt_xyz, opt_out, restart, vib_input, vib_output, vib_log)):
        result["issues"].append("one or more required native VIB/final-geometry artifacts are missing")
        return result

    # The VIB input may tighten numerical thresholds and change geometry/run type,
    # but its electronic surface must match the validated optimizer input.
    opt_input = _safe_artifact(final, rec.get("input_path"), f"{rec_id}.optimizer.input_path", report["problems"])
    _check_hash(opt_input, rec, "input_sha256", f"{rec_id} optimizer input", report["problems"])
    if opt_input is None:
        return result
    try:
        opt_text = opt_input.read_bytes()
        vib_input_bytes = vib_input.read_bytes()
        if b"\x00" in opt_text or b"\x00" in vib_input_bytes:
            raise ValueError("input contains NUL bytes")
        opt_text = opt_text.decode("utf-8", errors="strict")
        vib_text = vib_input_bytes.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        report["problems"].append(f"{rec_id}: optimizer/VIB input is malformed: {exc}")
        result["status"] = "FAIL"
        return result
    if (_review_unsupported_xc(opt_text, rec_id, report)
            or _review_unsupported_xc(vib_text, rec_id, report)):
        result["issues"].append("optimizer/VIB XC equivalence requires source review")
        return result
    if _science_method_signature(opt_text) != _science_method_signature(vib_text):
        report["problems"].append(f"{rec_id}: VIB input changes the validated optimizer electronic method/basis/potential/state")
        result["status"] = "FAIL"
        return result
    opt_data = _checked_data_artifact_map(rec, f"{rec_id} optimizer", final, report, route=rec.get("route"))
    vib_data = _checked_data_artifact_map(evidence, f"{rec_id} VIB", final, report, route=rec.get("route"))
    if opt_data is None or vib_data is None:
        result["issues"].append("hash-checked optimizer/VIB basis and potential data copies are required")
        report["pending_science_reviews"].append(f"{rec_id}: actual basis/potential bytes are not bound across optimization and VIB")
        return result
    if opt_data != vib_data:
        report["problems"].append(f"{rec_id}: VIB basis/potential data bytes differ from the validated optimizer")
        result["status"] = "FAIL"
        return result

    canonical_species = SPECIES.get(rec.get("molecule"), ())
    atom_map = rec.get("atom_map", list(range(len(canonical_species))))
    native_species = [None] * len(canonical_species)
    if (not isinstance(atom_map, list) or len(atom_map) != len(canonical_species)
            or any(type(i) is not int or i < 0 or i >= len(native_species) for i in atom_map)
            or len(set(atom_map)) != len(native_species)):
        report["problems"].append(f"{rec_id}: invalid atom_map for final geometry/minimum binding")
        result["status"] = "FAIL"
        return result
    for canonical_index, native_index in enumerate(atom_map):
        native_species[native_index] = canonical_species[canonical_index]
    geometry = native_science.bind_final_geometry(
        opt_xyz, restart, opt_out, expected_species=native_species,
        expected_sha256={"xyz": rec.get("trajectory_sha256"),
                         "restart": evidence.get("restart_sha256"),
                         "output": rec.get("output_sha256")})
    result["geometry_binding"] = geometry
    if geometry.get("status") == "FAIL":
        report["problems"].extend(f"{rec_id}: {item}" for item in geometry.get("issues", []))
        result["status"] = "FAIL"
        return result
    if geometry.get("status") != "PASS":
        result["issues"].extend(geometry.get("issues", []))
        report["pending_science_reviews"].append(f"{rec_id}: final optimizer geometry/restart binding is unverified")
        return result

    expected_settings = {"STATE": 1, "XC_FUNCTIONAL": "PBE0"}
    if rec.get("route") == "stda-pbe0-tzvp":
        expected_settings["FRACTION"] = rec.get("aex")
    atom_count = len(SPECIES.get(rec.get("molecule"), ()))
    stationarity_policy = {"method": "raw_or_rigid_projected", "max_gradient_au_bohr": 1.0e-5,
                           "rms_gradient_au_bohr": 1.0e-5}
    profile_path = Path(__file__).resolve().parent / "science_profile.json"
    try:
        profile_doc = json.loads(profile_path.read_text(encoding="utf-8"))
        soft_band = profile_doc.get("minimum_frequency_review_band_cm1")
        if isinstance(soft_band, bool) or not isinstance(soft_band, (int, float)) or not math.isfinite(soft_band) or soft_band <= 0:
            raise ValueError("minimum_frequency_review_band_cm1 is missing or invalid")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        result["issues"].append(f"reviewed soft-frequency policy unavailable: {exc}")
        report["pending_science_reviews"].append(f"{rec_id}: soft-mode review threshold unavailable")
        return result
    parsed = native_science.parse_vibminimum(
        vib_output, vib_input, expected_mode_count=3 * atom_count - 6,
        expected_s1_settings=expected_settings,
        expected_final_coordinates=geometry.get("final_coordinates"), vib_log=vib_log,
        replica_logs=replica_paths, stationarity_policy=stationarity_policy,
        soft_frequency_threshold_cm1=float(soft_band),
        expected_sha256=evidence.get("output_sha256"))
    result["native_vibration"] = parsed
    result["status"] = parsed.get("status", "UNVERIFIED")
    result["issues"].extend(parsed.get("issues", []))
    if result["status"] == "FAIL":
        report["problems"].extend(f"{rec_id}: {item}" for item in parsed.get("issues", []))
    elif result["status"] != "PASS":
        report["pending_science_reviews"].append(f"{rec_id}: native minimum evidence is incomplete or near-boundary")
    return result


def _validate_summary_artifact(final: Path, refs: dict, native_bonds: dict,
                               remedy_record: dict | None, report: dict,
                               m14_default: dict | None = None, m14_remedy: dict | None = None,
                               minimum_status: dict | None = None) -> None:
    """Require the hash-linked machine summary to match checker-recomputed values."""
    path = _safe_artifact(final, "scientific-summary.json", "final/scientific-summary.json",
                          report["problems"])
    if path is None:
        return
    try:
        candidate = json.loads(_read_text(path, "scientific-summary.json", report["problems"]))
        if m14_default is None or m14_remedy is None:
            m14_default, m14_remedy = scientific_summary.pending_science_sections(remedy_record)
        expected = scientific_summary.build_summary(
            refs, native_bonds, m14_default=m14_default, m14_remedy=m14_remedy,
            minimum_status=minimum_status or {"status": "pending_native_vibration_validation",
                                              "required_es_records": 14, "validated_es_records": 0})
        report_path = _safe_artifact(final, "report.md", "final/report.md", report["problems"])
        if report_path is None:
            return
        report_text = _read_text(report_path, "report.md", report["problems"])
        expected_hash = sha256(path)
        links = re.findall(r"(?m)^Summary artifact: scientific-summary\.json / SHA256: ([0-9a-f]{64})\s*$",
                           report_text)
        if links != [expected_hash]:
            report["problems"].append("report.md must contain exactly one valid hash link to scientific-summary.json")
        if not scientific_summary.summaries_match(expected, candidate):
            report["problems"].append("scientific-summary.json does not match checker-recomputed native statistics/status")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, OverflowError) as exc:
        report["problems"].append(f"scientific-summary.json is malformed: {exc}")


def _verify_m14_dissociation(record: dict, diagnosis: dict, final: Path,
                             problems: list[str]) -> None:
    """Tie the qualitative dissociation declaration to raw C-Cl trajectory distances."""
    if not isinstance(diagnosis, dict):
        problems.append("M14 dissociation diagnosis must be an object")
        return
    evidence_path = _safe_artifact(final, diagnosis.get("evidence_path"),
                                   "m14_stda_diagnosis.evidence_path", problems)
    _check_hash(evidence_path, diagnosis, "evidence_sha256", "M14 dissociation evidence", problems)
    if evidence_path is not None:
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(f"M14 dissociation evidence is invalid JSON: {exc}")
            evidence = {}
        if not isinstance(evidence, dict):
            problems.append("M14 dissociation evidence JSON must be an object")
            evidence = {}
        allowed = {"physical_dissociation", "not_physically_dissociated", "requires_scientific_review"}
        if evidence.get("classification") not in allowed or evidence.get("bond_label") != "c cl":
            problems.append("M14 evidence classification/bond identity is malformed")
        elif evidence.get("classification") != diagnosis.get("classification"):
            problems.append("M14 evidence classification disagrees with provenance")
    else:
        evidence = {}
    traj = _safe_artifact(final, record.get("trajectory_path"), "M14 default sTDA trajectory", problems)
    if traj is None:
        return
    # Strict parsing rejects a partial final geometry instead of falling back to an old frame.
    try:
        frames = _xyz_frames(traj)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        problems.append(f"M14 trajectory is unreadable or malformed: {exc}")
        return
    atom_map = record.get("atom_map", list(range(4)))
    if (len(frames) < 3 or not isinstance(atom_map, list) or len(atom_map) != 4
            or any(type(x) is not int for x in atom_map) or sorted(atom_map) != [0, 1, 2, 3]):
        problems.append("M14 dissociation needs at least three complete trajectory frames and a valid atom_map")
        return
    if any([frame[j][0] for j in atom_map] != SPECIES["M14"] for frame in frames):
        problems.append("M14 dissociation trajectory atom identity/order does not match CHClO")
        return
    try:
        distances = [_distance(frame[atom_map[0]], frame[atom_map[2]]) * 100.0 for frame in frames]
    except (IndexError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        problems.append(f"M14 trajectory cannot establish C-Cl distance: {exc}")
        return
    if not all(math.isfinite(x) for x in distances):
        problems.append("M14 native C-Cl distance series is nonfinite")
        return
    # This is only a consistency check against native coordinates. The independent
    # native M14 adapter supplies physical classification; a trend alone is insufficient.
    claimed = evidence.get("distance_series_pm")
    if not isinstance(claimed, list) or len(claimed) != len(distances):
        problems.append("M14 dissociation evidence must report the native C-Cl trajectory distance series")
        return
    for i, (actual, stated) in enumerate(zip(distances, claimed)):
        try:
            stated = float(stated)
        except (TypeError, ValueError):
            problems.append(f"M14 distance_series_pm[{i}] is not numeric")
            break
        if not math.isfinite(stated) or abs(actual - stated) > 0.02:
            problems.append(f"M14 distance_series_pm[{i}] does not match the native trajectory")
            break


def verify(app: Path, tests: Path) -> tuple[dict, int]:
    final = app / "final"
    history_prov = final / "provenance.json"
    if history_prov.is_file():
        try:
            history_doc = json.loads(history_prov.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            history_doc = None
        if isinstance(history_doc, dict) and history_doc.get("evidence_mode") == "historical_oracle_archive":
            return _verify_historical_archive(app, tests, final, history_doc)
    refs = load_refs(tests)
    try:
        science_profile_active, science_profile_reason = science_profile.load_profile(
            tests / "_support" / "science_profile.json", refs, EXPECTED_REF_SHA256)
    except science_profile.ProfileError as exc:
        raise InfraError(str(exc)) from exc
    final = app / "final"
    report = {"case_id": CASE_ID, "status": "FAIL", "scientific_result_status": "unavailable",
              "unsupported_method_semantics": False,
              "science_profile_status": ("reviewed_profile_structurally_valid" if science_profile_active
                                         else "unavailable_or_native_adapter_incomplete"),
              "checks_passed": [], "problems": [], "pending_science_reviews": [], "limits": [
                  "the fixed 3 pm task rule is empirical and is not a force/curvature error theorem",
                  "minimum and M14 classification remain pending native science adapters",
                  "native hashes/manifests establish internal traceability, not cryptographic provenance",
                  "M2 HPC single-point smoke is a component test, not full-case science acceptance"]}
    required = ("comparison.csv", "report.md", "provenance.json", "scientific-summary.json")
    checked_required = {name: _safe_artifact(final, name, f"final/{name}", report["problems"])
                        for name in required}
    missing = [name for name, path in checked_required.items() if path is None]
    if missing:
        report["problems"].append("missing, unreadable, or out-of-final deliverables: " + ", ".join(missing))
        return report, 1
    report["checks_passed"].append("required top-level deliverables exist")
    try:
        prov = json.loads(checked_required["provenance.json"].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        report["problems"].append(f"final/provenance.json is invalid: {exc}")
        return report, 1
    if not isinstance(prov, dict) or prov.get("schema") != "case06-provenance/v1":
        report["problems"].append("provenance.json schema must be case06-provenance/v1")
        return report, 1
    records = prov.get("calculations")
    if not isinstance(records, list):
        report["problems"].append("provenance.json calculations must be an array")
        return report, 1
    by_id: dict[str, dict] = {}
    for rec in records:
        if not isinstance(rec, dict) or not isinstance(rec.get("id"), str):
            report["problems"].append("each calculation record must have a string id")
            continue
        if rec["id"] in by_id:
            report["problems"].append(f"duplicate calculation id: {rec['id']}")
        else:
            by_id[rec["id"]] = rec
    missing_ids = EXPECTED_RECORDS - set(by_id)
    if missing_ids:
        report["problems"].append(f"missing {len(missing_ids)} of 25 required optimization records")
    if report["problems"]:
        return report, 1
    report["checks_passed"].append("exact five-molecule, two-GS plus three-ES inventory (25 records)")

    for rec_id in sorted(EXPECTED_RECORDS):
        rec = by_id[rec_id]
        parts = rec_id.split("/")
        if len(parts) != 3 or rec.get("molecule") != parts[0] or rec.get("state") != parts[1] or rec.get("route") != parts[2]:
            report["problems"].append(f"{rec_id}: ID and declared method identity disagree")
            continue
        trace = _native_trace(rec, final, report["problems"],
                              allow_dissociation=(rec_id == "M14/ES/stda-pbe0-tzvp"))
        rec["_verified_trace"] = trace
        _verify_optimizer_final_geometry(rec, final, trace, report)
    for field in ("output_path", "trajectory_path"):
        seen_paths: dict[str, str] = {}
        seen_hashes: dict[str, str] = {}
        hash_field = field.replace("_path", "_sha256")
        for rec_id in sorted(EXPECTED_RECORDS):
            rec = by_id[rec_id]
            path_value, hash_value = rec.get(field), rec.get(hash_field)
            if path_value in seen_paths:
                report["problems"].append(f"{rec_id}: {field} is reused from {seen_paths[path_value]}")
            elif isinstance(path_value, str):
                seen_paths[path_value] = rec_id
            if isinstance(hash_value, str) and hash_value in seen_hashes:
                report["problems"].append(f"{rec_id}: {field} content hash duplicates {seen_hashes[hash_value]}")
            elif isinstance(hash_value, str):
                seen_hashes[hash_value] = rec_id
    if report["problems"]:
        return report, 1
    report["checks_passed"].append("all 25 native calculation records are internally traceable and method-labelled")
    # sTDA must be explicitly linked to the same molecule's PBE0/TZVP ground-state result.
    for mol in MOLECULES:
        es = by_id[f"{mol}/ES/stda-pbe0-tzvp"]
        gs = by_id[f"{mol}/GS/pbe0-tzvp"]
        ref = es.get("ground_reference")
        if not isinstance(ref, dict) or ref.get("record_id") != f"{mol}/GS/pbe0-tzvp" or ref.get("method") != "PBE0/TZVP":
            report["problems"].append(f"{mol} sTDA ES must identify its corresponding PBE0/TZVP GS reference")
        elif ref.get("basis") != "MOLOPT TZVP" or ref.get("state") != "GS":
            report["problems"].append(f"{mol} sTDA reference method/basis/state is inconsistent")
        else:
            for ref_hash, gs_hash in (("input_sha256", "input_sha256"),
                                      ("output_sha256", "output_sha256"),
                                      ("trajectory_sha256", "trajectory_sha256")):
                if not isinstance(ref.get(ref_hash), str) or ref.get(ref_hash) != gs.get(gs_hash):
                    report["problems"].append(f"{mol} sTDA ground-reference {ref_hash} does not bind the PBE0 GS artifact")
            _verify_sTDA_ground_link(es, gs, final, report["problems"])
    if report["problems"]:
        return report, 1
    report["checks_passed"].append("sTDA ES records link to same-molecule PBE0/TZVP ground-state references")

    # Minimum evidence is separate from optimizer convergence. A true JSON flag is never proof.
    minimum_results: dict[str, dict] = {}
    for rec_id in sorted(EXPECTED_RECORDS):
        rec = by_id[rec_id]
        if rec.get("state") != "ES" or rec_id == "M14/ES/stda-pbe0-tzvp":
            continue
        minimum_results[rec_id] = _native_minimum_status(rec, final, report)

    # M14's default-aEX sTDA failure and its remedy are not represented by an ordinary rc!=0.
    diagnosis = prov.get("m14_stda_diagnosis")
    m14_default_summary = {"status": "native_classification_unverified", "aex": 0.2,
                           "comparison_target": "null_target_excluded"}
    m14_remedy_summary = {"status": "native_minimum_unverified", "route": None, "aex": None}
    if not isinstance(diagnosis, dict) or diagnosis.get("default_aex") != 0.2:
        report["problems"].append("M14 default-aEX sTDA diagnosis is missing")
    else:
        default_record = by_id.get("M14/ES/stda-pbe0-tzvp")
        if default_record is not None:
            if default_record.get("state") != "ES":
                report["problems"].append("M14 default sTDA record must be an ES calculation")
            try:
                default_aex = float(default_record.get("aex"))
            except (TypeError, ValueError):
                default_aex = math.nan
            if not math.isfinite(default_aex) or abs(default_aex - 0.2) > 1e-10:
                report["problems"].append("M14 default sTDA record must use aEX=0.2")
            _verify_m14_dissociation(default_record, diagnosis, final, report["problems"])
            arts = default_record.get("_verified_trace", {}).get("artifacts", {})
            if all(arts.get(k) for k in ("output", "trajectory", "input")):
                try:
                    m14_native = native_science.classify_m14_dissociation(
                        arts["output"], arts["trajectory"], arts["input"], expected_method="PBE0", aex=0.2,
                        min_independent_frames=3,
                        expected_sha256={"output": default_record.get("output_sha256"),
                                         "trajectory": default_record.get("trajectory_sha256"),
                                         "input": default_record.get("input_sha256")})
                except (OSError, ValueError, TypeError, OverflowError) as exc:
                    m14_native = {"status": "UNVERIFIED", "issues": [f"native adapter error: {exc}"]}
                default_record["_verified_m14"] = m14_native
                if m14_native.get("status") == "PASS":
                    m14_default_summary = {"status": "physical_dissociation", "aex": 0.2,
                                           "comparison_target": "null_target_excluded",
                                           "termination_reason": m14_native.get("termination_reason")}
                    default_record["_verified_final_geometry"] = {
                        "status": "PASS", "source": "native-validated-M14-physical-prefix"}
                    if diagnosis.get("classification") != "physical_dissociation":
                        report["problems"].append("M14 declared classification disagrees with native physical evidence")
                elif m14_native.get("status") == "FAIL":
                    m14_default_summary = {"status": "not_physically_dissociated", "aex": 0.2,
                                           "comparison_target": "null_target_excluded",
                                           "termination_reason": m14_native.get("termination_reason")}
                    report["problems"].extend(f"M14 default: {x}" for x in m14_native.get("issues", []))
                else:
                    report["pending_science_reviews"].extend(
                        f"M14 default classification: {x}" for x in m14_native.get("issues", []))
                    exit_text = _read_text(arts.get("exit"), "M14 exit code", report["problems"]).strip()
                    stderr_text = _read_text(arts.get("stderr"), "M14 stderr", report["problems"])
                    output_text = _read_text(arts.get("output"), "M14 output", report["problems"])
                    if (exit_text != "0" or re.search(
                            r"(?i)out of memory|oom-kill|killed by signal|mpi_abort|fatal error|segmentation fault",
                            stderr_text + "\n" + output_text)):
                        report["problems"].append(
                            "M14 termination was abnormal and no independently validated physical prefix was established")
        remedy_records = prov.get("remedy_calculations")
        if not isinstance(remedy_records, list) or any(not isinstance(r, dict) for r in remedy_records):
            report["problems"].append("M14 remedy_calculations must be a list of records")
            remedy_records = []
        if any(not isinstance(r.get("id"), str) for r in remedy_records):
            report["problems"].append("every M14 remedy record must have a string id")
            remedy_records = [r for r in remedy_records if isinstance(r.get("id"), str)]
        remedy = diagnosis.get("remedy_record_id")
        if not isinstance(remedy, str) or remedy not in {r.get("id") for r in remedy_records}:
            report["problems"].append("M14 requires a separately traceable remedy attempt with aEX >= 0.25")
        else:
            matching = [r for r in remedy_records if r.get("id") == remedy]
            if len(matching) != 1:
                report["problems"].append("M14 remedy record ID must resolve uniquely")
                matching = []
            remedy_rec = matching[0] if matching else {"id": remedy, "state": None}
            if not all(isinstance(remedy_rec.get(k), str) for k in ("molecule", "state", "route")):
                report["problems"].append("M14 remedy molecule, state, and route must be strings")
                remedy_rec = None
            if remedy_rec is None:
                report["problems"].append("M14 remedy record identity is malformed")
                # Keep evaluation in the normal FAIL path without calling native parsers
                # on attacker-controlled non-string molecule/route values.
            else:
                try:
                    remedy_aex = float(remedy_rec.get("aex", 0))
                except (TypeError, ValueError, OverflowError):
                    remedy_aex = math.nan
                remedy_route = remedy_rec.get("route")
                if remedy_rec.get("molecule") != "M14" or remedy_rec.get("state") != "ES" or remedy_route not in ES_ROUTES:
                    report["problems"].append("M14 remedy must be a traceable excited-state calculation using a supported route")
                elif remedy_route == "stda-pbe0-tzvp" and (not math.isfinite(remedy_aex) or remedy_aex < 0.25):
                    report["problems"].append("M14 sTDA remedy must declare aEX >= 0.25")
                elif remedy_route != "stda-pbe0-tzvp":
                    report["pending_science_reviews"].append("M14 alternate-method remedy requires scientific review")
                remedy_trace_before = len(report["problems"])
                remedy_rec["_verified_trace"] = _native_trace(remedy_rec, final, report["problems"])
                if remedy_rec.get("route") == "stda-pbe0-tzvp":
                    remedy_ref = remedy_rec.get("ground_reference")
                    gs = by_id.get("M14/GS/pbe0-tzvp", {})
                    if not isinstance(remedy_ref, dict):
                        report["problems"].append("M14 sTDA remedy must link its PBE0/TZVP GS record")
                    else:
                        for ref_hash in ("input_sha256", "output_sha256", "trajectory_sha256"):
                            if remedy_ref.get(ref_hash) != gs.get(ref_hash):
                                report["problems"].append(f"M14 remedy ground-reference {ref_hash} mismatch")
                        _verify_sTDA_ground_link(remedy_rec, gs, final, report["problems"])
                m14_remedy_summary = {"status": "native_minimum_unverified",
                                      "route": remedy_route, "aex": remedy_rec.get("aex")}
                remedy_min = _native_minimum_status(remedy_rec, final, report)
                if remedy_min.get("status") == "PASS":
                    m14_remedy_summary["status"] = "native_minimum_pass"
                elif remedy_min.get("status") == "FAIL":
                    m14_remedy_summary["status"] = "native_minimum_fail"
                if len(report["problems"]) == remedy_trace_before:
                    report["checks_passed"].append("M14 remedy has a separately traceable native optimization")
                if m14_remedy_summary["status"] != "native_minimum_pass":
                    report["pending_science_reviews"].append("M14 remedy minimum remains unverified")

    # Twenty-four ordinary baseline optimizers need terminal XYZ/restart binding.
    # M14 default is the intentional chemical-failure reference: a qualifying
    # native physical prefix binds its relevant geometries even if later execution
    # terminates without a final restart.
    geometry_statuses = {
        rec_id: by_id[rec_id].get("_verified_final_geometry", {}).get("status", "UNVERIFIED")
        for rec_id in sorted(EXPECTED_RECORDS)
    }
    geometry_passes = sum(status == "PASS" for status in geometry_statuses.values())
    optimizer_geometry_complete = geometry_passes == len(EXPECTED_RECORDS)
    report["optimizer_final_geometry_status"] = {
        "status": "PASS" if optimizer_geometry_complete else "UNVERIFIED",
        "required_records": len(EXPECTED_RECORDS),
        "validated_records": geometry_passes,
    }
    if optimizer_geometry_complete:
        report["checks_passed"].append(
            "all 25 baseline optimizer geometries are bound to native restart or M14 physical-prefix evidence")
    else:
        report["pending_science_reviews"].append(
            f"native final geometry binding covers {geometry_passes}/{len(EXPECTED_RECORDS)} optimizer records")

    # The published comparison file must exist and carry all available ES bond comparisons.
    refs_by_key = {k: v for k, v in refs["items"].items()
                   if v.get("state") == "ES" and v.get("quantity") == "bond"}
    expected_rows = sum(2 if key.startswith("bond|ES|M14|") else 3 for key in refs_by_key)
    bond_precision_bounds: dict[tuple[str, str, str], float] = {}
    try:
        with (final / "comparison.csv").open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        report["problems"].append(f"comparison.csv is unreadable: {exc}")
        return report, 1
    if len(rows) != expected_rows:
        report["problems"].append(f"comparison.csv needs {expected_rows} available ES-bond/method rows, found {len(rows)}")
        native_bonds = {}
    else:
        native_bonds = _comparison_check(rows, refs, by_id, final, report["problems"],
                                         measurement_uncertainties=bond_precision_bounds)
        if not report["problems"]:
            report["checks_passed"].append("comparison values cross-check against final native XYZ and published ES bond references")

    comparison_gate_unverified = False
    if science_profile_active and science_profile_active.get("schema") == science_profile.EMPIRICAL_PROFILE_SCHEMA:
        route_columns = {"pbe0-tzvp": "PBE0|TZVP", "admm-tzvp-tzp": "ADMM|TZVP+tzp",
                         "stda-pbe0-tzvp": "sTDA@PBE0|TZVP"}
        for ref_key, ref in refs_by_key.items():
            mol, label = ref["molecule"], ref["label"]
            for route, column in route_columns.items():
                published = ref["values"].get(column)
                if published is None:
                    continue
                key = (mol, route, label)
                measured = native_bonds.get(key)
                if measured is None:
                    continue
                try:
                    within, detail = science_profile.accept_empirical_residual(
                        candidate_pm=measured, published_pm=published,
                        candidate_coordinate_uncertainty_pm=bond_precision_bounds.get(key, math.inf))
                except ValueError as exc:
                    report["problems"].append(f"{ref_key}/{route}: invalid empirical residual inputs: {exc}")
                    continue
                report.setdefault("same_method_residuals", {})[f"{ref_key}|{route}"] = detail
                if detail["decision"] == "FAIL":
                    report["problems"].append(
                        f"{ref_key}/{route}: same-method residual {detail['absolute_residual_pm']:.6f} pm "
                        f"exceeds the reviewed 3.0 pm task limit")
                elif detail["decision"] == "UNVERIFIED":
                    comparison_gate_unverified = True
                    report["pending_science_reviews"].append(
                        f"{ref_key}/{route}: printed-coordinate/SI interval {detail['absolute_residual_interval_pm']} "
                        "straddles the reviewed 3.0 pm boundary")
        if not report["problems"] and not comparison_gate_unverified:
            report["checks_passed"].append("all 36 available same-method ES bond rows meet the reviewed 3.0 pm empirical task limit")

    min_passes = sum(1 for value in minimum_results.values() if value.get("status") == "PASS")
    required_minimum_count = len(minimum_results)
    minimum_status = {
        "status": "PASS" if required_minimum_count == 14 and min_passes == 14 else "UNVERIFIED",
        "required_es_records": 14,
        "validated_es_records": min_passes,
    }
    report["minimum_status"] = minimum_status
    report["m14_default_status"] = m14_default_summary
    report["m14_remedy_status"] = m14_remedy_summary
    report["native_bonds_pm"] = {"|".join((mol, route, label)): value
                                  for (mol, route, label), value in native_bonds.items()}
    if not report["problems"]:
        diagnosis = prov.get("m14_stda_diagnosis", {})
        remedy_id = diagnosis.get("remedy_record_id") if isinstance(diagnosis, dict) else None
        remedies = prov.get("remedy_calculations", [])
        remedy_record = next((r for r in remedies if isinstance(r, dict) and r.get("id") == remedy_id), None)
        _validate_summary_artifact(final, refs, native_bonds, remedy_record, report,
                                   m14_default=m14_default_summary, m14_remedy=m14_remedy_summary,
                                   minimum_status=minimum_status)
        if not report["problems"]:
            report["checks_passed"].append("hash-linked scientific summary matches checker-recomputed native statistics")

    if report["problems"]:
        report["status"] = "FAIL"
        return report, 1
    minima_complete = minimum_status["status"] == "PASS"
    m14_complete = (m14_default_summary.get("status") == "physical_dissociation"
                    and m14_remedy_summary.get("status") == "native_minimum_pass")
    if (science_profile_active and optimizer_geometry_complete and minima_complete and m14_complete
            and not report.get("unsupported_method_semantics")
            and not comparison_gate_unverified):
        report["scientific_result_status"] = "reviewed_empirical_3pm_and_native_minimum_checks_pass"
        report["status"] = "PASS"
        return report, 0
    report["scientific_result_status"] = "unverified_native_minimum_or_m14_evidence"
    report["status"] = "UNVERIFIED"
    report["pending_science_reviews"].append(f"L3 evidence incomplete: {science_profile_reason}")
    if not minima_complete:
        report["pending_science_reviews"].append(
            f"native minimum validation covers {min_passes}/{required_minimum_count} baseline ES records")
    if not optimizer_geometry_complete:
        report["pending_science_reviews"].append(
            "all 25 baseline optimizer final geometries must bind to native restart evidence")
    if not m14_complete:
        report["pending_science_reviews"].append("M14 default dissociation and/or remedy minimum remains unverified")
    if comparison_gate_unverified:
        report["pending_science_reviews"].append("one or more same-method residual intervals straddle 3.0 pm")
    return report, 2


def _verify_historical_archive(app: Path, tests: Path, final: Path, provenance: dict) -> tuple[dict, int]:
    """Validate historical source replay without treating it as fresh Agent execution.

    This branch is Oracle-only and can return only UNVERIFIED for the currently
    incomplete minimum evidence. The host mode is a policy selector, not a job
    attestation mechanism.
    """
    report = {"case_id": CASE_ID, "status": "FAIL", "scientific_result_status": "historical_source_invalid",
              "evidence_mode": "historical_oracle_archive", "checks_passed": [], "problems": [],
              "pending_science_reviews": [], "limits": [
                  "host-owned answer mode does not authenticate historical process execution",
                  "archive correspondence does not prove active per-run aEX echoes",
                  "minimum evidence is evaluated separately from optimizer geometry and S1"]}
    if os.environ.get("CCB_ANSWER_MODE") != "oracle":
        report["status"] = "UNVERIFIED"
        report["scientific_result_status"] = "historical_archive_not_allowed_as_agent_execution"
        report["pending_science_reviews"].append("pinned historical archive is permitted only for host-selected Oracle reference mode")
        return report, 2
    if provenance.get("schema") != "case06-provenance/v1":
        report["problems"].append("historical provenance schema mismatch")
        return report, 1
    if (provenance.get("source_record") != "Materials Cloud c9peh-kt938"
            or provenance.get("full_archive_md5_verified") is not False
            or provenance.get("launcher_exit_code") is not None
            or provenance.get("stderr") is not None):
        report["problems"].append("historical source/unknown launcher metadata is inconsistent")
        return report, 1
    profile_path = tests / "_support" / "historical-source-profile.json"
    try:
        profile_bytes = profile_path.read_bytes()
        if sha256(profile_path) != HISTORICAL_PROFILE_SHA256:
            raise InfraError("fixed historical source profile pin mismatch")
        profile = json.loads(profile_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise InfraError(f"fixed historical source profile unavailable: {exc}") from exc
    if (profile.get("schema") != "case06-trusted-public-source-profile/v1"
            or provenance.get("central_directory_sha256") != profile.get("central_directory_sha256")
            or provenance.get("official_archive_size_bytes") != profile.get("official_archive_size_bytes")
            or provenance.get("official_archive_md5") != profile.get("official_archive_md5")):
        report["problems"].append("historical archive identity does not match grader-pinned public source")
        return report, 1
    trusted = profile.get("members")
    if not isinstance(trusted, dict) or len(trusted) != 122:
        raise InfraError("fixed historical source profile has an invalid member inventory")
    selected = provenance.get("selected_members")
    if not isinstance(selected, list) or len(selected) != len(trusted):
        report["problems"].append("historical source receipt must name all 122 pinned members")
        return report, 1
    selected_by_name = {}
    for item in selected:
        if not isinstance(item, dict) or not isinstance(item.get("member"), str):
            report["problems"].append("malformed historical member receipt")
            continue
        member = item["member"]
        if member in selected_by_name:
            report["problems"].append(f"duplicate historical member receipt: {member}")
        selected_by_name[member] = item
    if set(selected_by_name) != set(trusted):
        report["problems"].append("historical source receipt does not match the exact pinned member set")
    verified_paths = {}
    for member, expected in trusted.items():
        item = selected_by_name.get(member)
        if not isinstance(item, dict):
            continue
        rel_expected = (Path("geometries") / "source-members" / Path(member).relative_to("DATA_MATERIALS_CLOUD")).as_posix()
        if item.get("path") != rel_expected:
            report["problems"].append(f"{member}: source member path mismatch")
            continue
        if (item.get("sha256") != expected["sha256"] or item.get("crc32") != expected["crc32"]
                or item.get("bytes") != expected["uncompressed_bytes"]):
            report["problems"].append(f"{member}: reported source receipt differs from fixed pin")
            continue
        path = _safe_artifact(final, item.get("path"), f"historical source {member}", report["problems"])
        if path is None:
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            report["problems"].append(f"{member}: cannot read source member: {exc}")
            continue
        got = {"sha256": hashlib.sha256(raw).hexdigest(),
               "crc32": f"{zlib.crc32(raw) & 0xffffffff:08x}", "uncompressed_bytes": len(raw)}
        if any(got[k] != expected[k] for k in got):
            report["problems"].append(f"{member}: bytes do not match the grader-pinned public archive member")
            continue
        verified_paths[member] = path
    if report["problems"]:
        return report, 1
    report["checks_passed"].append("all 122 selected public archive members match fixed grader pins")

    calculations = provenance.get("calculations")
    remedies = provenance.get("remedy_calculations")
    if not isinstance(calculations, list) or not isinstance(remedies, list) or len(calculations) != 25 or len(remedies) != 1:
        report["problems"].append("historical replay must contain 25 baseline routes and one separate M14 remedy")
        return report, 1
    records = calculations + remedies
    by_id = {r.get("id"): r for r in records if isinstance(r, dict)}
    expected_ids = set(profile.get("records", {}))
    if set(by_id) != expected_ids:
        report["problems"].append("historical route inventory does not match the 26 pinned source records")
        return report, 1
    source_calc_by_id = {}
    route_observed_energy_deltas = []
    for rec_id, pin in profile["records"].items():
        rec = by_id[rec_id]
        if (rec.get("molecule"), rec.get("state"), rec.get("route")) != tuple(rec_id.split("/", 2)):
            # The M14 remedy is a separate route id, but the molecule/state fields
            # remain identical to its source record and are checked below.
            if not (rec_id.endswith("-remedy") and rec.get("molecule") == "M14"
                    and rec.get("state") == "ES" and rec.get("route") == "stda-pbe0-tzvp-aex0.25-remedy"):
                report["problems"].append(f"{rec_id}: declared molecule/state/route identity mismatch")
                continue
        if (rec.get("evidence_kind") != "public_historical_author_archive"
                or rec.get("source_correspondence_status") != "AUTHOR_SOURCE_CORRESPONDENCE_ACCEPTED"
                or rec.get("launcher_exit_code") is not None or rec.get("stderr") is not None
                or rec.get("archive_members") != pin["roles"]):
            report["problems"].append(f"{rec_id}: historical source scope/unknown execution metadata mismatch")
            continue
        if (not isinstance(rec.get("geometry"), dict)
                or not isinstance(rec.get("source_member_sha256"), dict)
                or not isinstance(rec.get("minimum"), dict)):
            report["problems"].append(f"{rec_id}: malformed nested historical geometry/source metadata")
            continue
        role_hashes = rec.get("source_member_sha256")
        if not isinstance(role_hashes, dict):
            report["problems"].append(f"{rec_id}: source-member hash map must be an object")
            continue
        for role, member in pin["roles"].items():
            rel = (Path("geometries") / "source-members" / Path(member).relative_to("DATA_MATERIALS_CLOUD")).as_posix()
            role_entry = role_hashes.get(role)
            if not isinstance(role_entry, dict):
                report["problems"].append(f"{rec_id}: malformed {role} source metadata")
                continue
            if role_entry.get("sha256") != trusted[member]["sha256"]:
                report["problems"].append(f"{rec_id}: {role} source SHA does not match grader pin")
            if role_entry.get("path") != rel:
                report["problems"].append(f"{rec_id}: {role} source path does not match grader pin")
        mol, state, route = rec_id.split("/")[:3]
        if (mol, state, route) == ("M14", "ES", "stda-pbe0-tzvp-aex0.25-remedy"):
            route = "stda-pbe0-tzvp-aex0.25-remedy"
        out_path = verified_paths.get(pin["roles"]["output"])
        inp_path = verified_paths.get(pin["roles"]["input"])
        xyz_path = verified_paths.get(pin["roles"]["trajectory"])
        if not (out_path and inp_path and xyz_path):
            continue
        if rec.get("geometry", {}).get("path") != (Path("geometries") / "source-members" / Path(pin["roles"]["trajectory"]).relative_to("DATA_MATERIALS_CLOUD")).as_posix():
            report["problems"].append(f"{rec_id}: final geometry path is not its pinned author trajectory")
        try:
            inp = inp_path.read_text(encoding="utf-8")
            out = out_path.read_text(encoding="utf-8", errors="replace")
            frames = _xyz_frames(xyz_path)
            geom_meta = rec.get("geometry", {})
            reviewed_map = profile.get("canonical_atom_maps", {}).get(mol)
            output_run, run_count = _select_last_output_run(out)
            selected_segment = _select_last_run_xyz_segment(output_run, xyz_path)
            selected_idx = selected_segment["end_zero_based_inclusive"]
            if (geom_meta.get("selected_segment") != selected_segment
                    or geom_meta.get("selected_frame_index_zero_based") != selected_idx
                    or geom_meta.get("selected_frame_range_zero_based_inclusive") != [
                        selected_segment["start_zero_based"], selected_idx]):
                report["problems"].append(f"{rec_id}: selected XYZ segment is not the unique last-invocation energy-bound segment")
            if geom_meta.get("atom_count") != len(frames[selected_idx]) or geom_meta.get("frame_count") != len(frames):
                report["problems"].append(f"{rec_id}: final XYZ count/frame observations disagree with source bytes")
            if geom_meta.get("canonical_atom_map") != reviewed_map:
                report["problems"].append(f"{rec_id}: canonical atom map differs from the fixed reviewed topology map")
            if rec.get("geometry", {}).get("sha256") != hashlib.sha256(xyz_path.read_bytes()).hexdigest():
                report["problems"].append(f"{rec_id}: geometry hash does not bind to pinned XYZ")
            if not re.search(r"(?im)^\s*&GLOBAL\b", _clean_input(inp)):
                report["problems"].append(f"{rec_id}: pinned input lacks CP2K GLOBAL section")
            if state == "ES":
                if not re.search(r"(?im)^\s*STATE\s+1\s*$", _clean_input(inp)):
                    report["problems"].append(f"{rec_id}: pinned excited-state deck does not request S1")
                if not ("R-TDDFPT states of multiplicity 1" in out or "Spin symmetry of excitations Singlet" in out):
                    report["problems"].append(f"{rec_id}: native output lacks singlet-state marker")
            if rec_id == "M14/ES/stda-pbe0-tzvp":
                expected_fraction = 0.2
            elif rec_id.endswith("-remedy"):
                expected_fraction = 0.25
            else:
                expected_fraction = None
            fraction = _input_stda_fraction(inp)
            if expected_fraction is not None and (fraction is None or abs(fraction - expected_fraction) > 1e-10):
                report["problems"].append(f"{rec_id}: effective input aEX does not match the pinned route deck")
            if fraction is not None and (not isinstance(rec.get("aex"), (int, float)) or abs(float(rec["aex"]) - fraction) > 1e-10):
                report["problems"].append(f"{rec_id}: declared aEX disagrees with the effective pinned deck")
            clean_input = _clean_input(inp)
            dft = _section_body(clean_input, "DFT")
            admm_on = bool(_section_body(dft, "AUXILIARY_DENSITY_MATRIX_METHOD"))
            td = _section_body(_section_body(clean_input, "PROPERTIES"), "TDDFPT") or _section_body(clean_input, "TDDFPT")
            stda_on = bool(_section_body(td, "STDA"))
            if route == "pbe0-tzvp" and (admm_on or stda_on or native_science.pbe0_semantics(inp) is None):
                report["problems"].append(f"{rec_id}: effective input does not match conventional PBE0 route")
            elif route == "admm-tzvp-tzp" and (not admm_on or stda_on or native_science.pbe0_semantics(inp) is None):
                report["problems"].append(f"{rec_id}: effective input does not match ADMM-PBE0 route")
            elif route.startswith("stda-") and (not stda_on or admm_on):
                report["problems"].append(f"{rec_id}: effective input does not match sTDA@PBE0 route")
            if run_count == 0 or "PROGRAM ENDED AT" not in output_run or "GEOMETRY OPTIMIZATION COMPLETED" not in output_run:
                report["problems"].append(f"{rec_id}: last native optimizer run lacks normal end/GEO_OPT completion")
            scf_markers = list(re.finditer(r"SCF run (NOT )?converged", output_run, re.I))
            if not scf_markers or scf_markers[-1].group(1):
                report["problems"].append(f"{rec_id}: last native run SCF did not converge")
            if state == "ES":
                td_markers = list(re.finditer(r"TDDFPT run (NOT )?converged", output_run, re.I))
                lin_markers = list(re.finditer(r"linear solver (NOT )?converged", output_run, re.I))
                if not td_markers or td_markers[-1].group(1) or not lin_markers or lin_markers[-1].group(1):
                    report["problems"].append(f"{rec_id}: last native TD or S1-force solve is not converged")
            xyz_comment = xyz_path.read_text(encoding="utf-8").splitlines()
            frame_starts = []
            cursor = 0
            while cursor < len(xyz_comment):
                if not xyz_comment[cursor].strip():
                    cursor += 1
                    continue
                count = int(xyz_comment[cursor].strip())
                frame_starts.append(cursor)
                cursor += count + 2
            xyz_final_comment = xyz_comment[frame_starts[selected_idx] + 1]
            xyz_energy_match = re.search(r"\bE\s*=\s*([-+0-9.Ee]+)", xyz_final_comment)
            output_energies = re.findall(r"ENERGY\| Total FORCE_EVAL \( QS \) energy \[a\.u\.\]:\s*([-+0-9.Ee]+)", output_run)
            if not xyz_energy_match or not output_energies or abs(float(xyz_energy_match.group(1)) - float(output_energies[-1])) > 1e-7:
                report["problems"].append(f"{rec_id}: final output energy is not bound to selected trajectory endpoint at printed precision")
            route_observed_energy_deltas.append(abs(float(xyz_energy_match.group(1)) - float(output_energies[-1])) if xyz_energy_match and output_energies else math.inf)
            # A candidate cannot promote positive modes or a self-authored status to minimum PASS.
            minimum_claim = rec.get("minimum")
            required_minimum = state == "ES" and rec_id != "M14/ES/stda-pbe0-tzvp"
            if not isinstance(minimum_claim, dict):
                report["problems"].append(f"{rec_id}: minimum claim must be a JSON object")
                minimum_claim = {}
            if required_minimum and minimum_claim.get("status") != "UNVERIFIED":
                report["problems"].append(f"{rec_id}: incomplete curvature evidence cannot claim a minimum PASS")
            record_for_bonds = {"id": rec_id, "molecule": mol, "state": state,
                                "route": route, "trajectory_path": geom_meta.get("path"),
                                "trajectory_sha256": geom_meta.get("sha256"),
                                "selected_frame_index_zero_based": selected_idx,
                                "atom_map": geom_meta.get("canonical_atom_map")}
            source_calc_by_id[rec_id] = record_for_bonds
            required_minimum = state == "ES" and rec_id != "M14/ES/stda-pbe0-tzvp"
            if required_minimum and minimum_claim.get("status") != "UNVERIFIED":
                report["problems"].append(f"{rec_id}: missing/unbound curvature cannot establish minimum PASS")
            if required_minimum and minimum_claim.get("status") == "UNVERIFIED":
                if minimum_claim.get("candidate_vibration_status") == "PASS" or minimum_claim.get("curvature_status") == "PASS":
                    report["problems"].append(f"{rec_id}: positive modes or unbound candidate flags cannot produce minimum PASS")
            if rec_id.endswith("-remedy"):
                expected_min_members = pin.get("minimum_candidate_members", [])
                actual_min = minimum_claim.get("candidate_members") if isinstance(minimum_claim, dict) else None
                if not isinstance(actual_min, list) or [x.get("member") for x in actual_min if isinstance(x, dict)] != expected_min_members:
                    report["problems"].append("M14 remedy legacy VIB candidate inventory differs from fixed source profile")
                fixed_review = profile.get("reviewed_science_facts", {}).get("m14_remedy", {})
                vib_review = minimum_claim.get("legacy_vib_review") if isinstance(minimum_claim, dict) else None
                if not isinstance(vib_review, dict):
                    report["problems"].append("M14 legacy VIB review facts are absent")
                elif any(vib_review.get(key) != fixed_review.get(source_key) for key, source_key in (
                        ("status", "legacy_vib_stationarity"),
                        ("projected_force_max_ha_bohr", "projected_force_max_ha_bohr"),
                        ("projected_force_rms_ha_bohr", "projected_force_rms_ha_bohr"),
                        ("center_force_raw_max_ha_bohr", "center_force_raw_max_ha_bohr"))):
                    report["problems"].append("M14 legacy VIB values differ from fixed author-review receipt")
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            report["problems"].append(f"{rec_id}: cannot parse pinned source artifacts: {exc}")
    if report["problems"]:
        return report, 1
    report["checks_passed"].append("route decks, last-run SCF/TD/S1 markers, energy-to-XYZ closure, and final frames match pinned source members")

    # All true historical process fields stay unavailable; require the adapter to
    # preserve this rather than manufacture modern launcher traces.
    refs = load_refs(tests)
    rows = []
    try:
        with (final / "comparison.csv").open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, UnicodeError, csv.Error) as exc:
        report["problems"].append(f"historical comparison.csv unreadable: {exc}")
    if len(rows) != 36:
        report["problems"].append(f"historical comparison needs 36 available SI rows, got {len(rows)}")
    uncertainties = {}
    native_bonds = _comparison_check(rows, refs, source_calc_by_id, final, report["problems"],
                                     measurement_uncertainties=uncertainties)
    if report["problems"]:
        return report, 1
    try:
        profile_active, profile_reason = science_profile.load_profile(
            tests / "_support" / "science_profile.json", refs, EXPECTED_REF_SHA256)
    except science_profile.ProfileError as exc:
        raise InfraError(str(exc)) from exc
    comparison_gate_unverified = False
    route_columns = {"pbe0-tzvp": "PBE0|TZVP", "admm-tzvp-tzp": "ADMM|TZVP+tzp",
                     "stda-pbe0-tzvp": "sTDA@PBE0|TZVP"}
    for ref_key, ref in refs["items"].items():
        if ref.get("state") != "ES" or ref.get("quantity") != "bond":
            continue
        mol, label = ref["molecule"], ref["label"]
        for route, column in route_columns.items():
            published = ref["values"].get(column)
            key = (mol, route, label)
            if published is None or key not in native_bonds:
                continue
            within, detail = science_profile.accept_empirical_residual(
                candidate_pm=native_bonds[key], published_pm=published,
                candidate_coordinate_uncertainty_pm=uncertainties.get(key, math.inf))
            report.setdefault("same_method_residuals", {})[f"{ref_key}|{route}"] = detail
            if detail["decision"] == "FAIL":
                report["problems"].append(f"{ref_key}/{route}: same-method residual exceeds frozen 3.0 pm gate")
            elif detail["decision"] == "UNVERIFIED":
                comparison_gate_unverified = True
    if report["problems"]:
        return report, 1
    report["checks_passed"].append("36 SI bond values, coordinate-precision intervals, and the frozen 3.0 pm policy gate recomputed from pinned XYZ files")
    m14_id = "M14/ES/stda-pbe0-tzvp"
    m14_pin = profile["records"][m14_id]
    m14_output = verified_paths[m14_pin["roles"]["output"]]
    m14_input = verified_paths[m14_pin["roles"]["input"]]
    m14_xyz = verified_paths[m14_pin["roles"]["trajectory"]]
    m14_expected_sha = {role: trusted[member]["sha256"]
                        for role, member in m14_pin["roles"].items()}
    m14_dissociation = native_science.classify_m14_dissociation(
        m14_output, m14_xyz, m14_input, expected_method="PBE0", aex=0.2,
        min_independent_frames=3, expected_sha256=m14_expected_sha)
    report["m14_default_native_classifier"] = m14_dissociation
    if m14_dissociation.get("status") == "PASS":
        report["checks_passed"].append("M14 default dissociation independently recomputed from pinned native S1 force/trajectory frames")
    else:
        report["pending_science_reviews"].append("M14 default native dissociation classifier did not establish the reviewed physical diagnosis")
    report["optimizer_final_geometry_status"] = {"status": "AUTHOR_SOURCE_CORRESPONDENCE_ACCEPTED",
                                                  "source_correspondence_records": 26,
                                                  "energy_closed_records": 26,
                                                  "note": "pinned historical endpoint source association and printed energy closure are verified; fresh process/restart attestation and minimum evidence remain separate"}
    report["minimum_status"] = {"status": "UNVERIFIED", "required_es_records": 15, "passed": 0,
                                "ordinary_missing_curvature": 14,
                                "m14_remedy_vib_candidate": "FAIL_stationarity_on_its_own_center; endpoint transfer unverified"}
    report["m14_default_status"] = {"status": "physical_dissociation" if m14_dissociation.get("status") == "PASS" else "UNVERIFIED",
                                    "aex": 0.2,
                                    "source_correspondence": "historical author-source pairing with cwd anomaly; exact per-run aEX echo absent",
                                    "native_classifier_status": m14_dissociation.get("status")}
    report["m14_remedy_status"] = {"status": "UNVERIFIED", "candidate_vib_stationarity": "FAIL",
                                   "minimum_endpoint_binding": "UNVERIFIED"}
    report["scientific_result_status"] = "historical_reference_validated_minimum_claims_unverified"
    report["pending_science_reviews"] = [
        "14 ordinary ES routes lack same-surface curvature/endpoint evidence; recalculation necessity remains route-specific review",
        "M14 remedy VIB candidate fails 1e-5 stationarity at its own center and cannot transfer force to translated optimizer endpoint without calibrated grid-phase uncertainty",
        "M14 active sTDA aEX is source-correspondence reviewed, not echoed per concatenated native run",
        "historical archive has no scheduler receipt or launcher exit/stderr; Oracle host mode is not execution attestation"]
    report["source_correspondence_records"] = 26
    report["comparison_row_count"] = len(native_bonds)
    summary_path = _safe_artifact(final, "scientific-summary.json", "historical scientific summary", report["problems"])
    report_path = _safe_artifact(final, "report.md", "historical report", report["problems"])
    if summary_path is None or report_path is None:
        report["problems"].append("historical summary/report missing")
        return report, 1
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        report_text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report["problems"].append(f"historical summary/report invalid: {exc}")
        return report, 1
    if not isinstance(summary, dict):
        report["problems"].append("historical scientific summary must be a JSON object")
        return report, 1
    minimum_claims = summary.get("minimum_claims")
    if not isinstance(minimum_claims, dict):
        minimum_claims = {}
    stated_bond_summary = summary.get("same_method_es_bond_comparison")
    if not isinstance(stated_bond_summary, dict):
        stated_bond_summary = {}
    if (summary.get("schema") != "case06-scientific-summary/historical-v2"
            or minimum_claims.get("passed_count") != 0
            or minimum_claims.get("ordinary_unverified_count") != 14
            or stated_bond_summary.get("row_count") != 36):
        report["problems"].append("historical scientific summary does not preserve the independent minimum/SI findings")
    expected_residuals = []
    for ref in refs["items"].values():
        if ref.get("state") != "ES" or ref.get("quantity") != "bond":
            continue
        mol, label = ref["molecule"], ref["label"]
        for route, column in route_columns.items():
            key = (mol, route, label)
            target = ref["values"].get(column)
            if target is not None and key in native_bonds:
                expected_residuals.append(abs(native_bonds[key] - float(target)))
    expected_max_residual = max(expected_residuals) if expected_residuals else None
    stated_comparison = summary.get("same_method_es_bond_comparison", {})
    declared_max_residual = stated_comparison.get("max_abs_residual_pm") if isinstance(stated_comparison, dict) else None
    if (not isinstance(stated_comparison, dict)
            or stated_comparison.get("row_count") != len(expected_residuals)
            or stated_comparison.get("rows_with_abs_residual_le_3pm") != sum(x <= 3.0 for x in expected_residuals)
            or type(declared_max_residual) not in (int, float)
            or not math.isfinite(float(declared_max_residual))
            or expected_max_residual is None
            or abs(float(declared_max_residual) - expected_max_residual) > 1e-6):
        report["problems"].append("historical summary SI residual statistics do not match grader recomputation")
    if (stated_comparison.get("rows_scientifically_checked") != 36
            or stated_comparison.get("rows_passed_3pm") != sum(x <= 3.0 for x in expected_residuals)):
        report["problems"].append("historical summary does not report all 36 rows as checked under the 3 pm rule")
    expected_energy_closure = max(route_observed_energy_deltas) if route_observed_energy_deltas else None
    stated_optimizer = summary.get("optimizer", {})
    stated_energy_closure = (stated_optimizer.get("last_output_xyz_energy_closure_max_hartree")
                             if isinstance(stated_optimizer, dict) else None)
    if (not isinstance(stated_optimizer, dict)
            or type(stated_energy_closure) not in (int, float)
            or not math.isfinite(float(stated_energy_closure))
            or expected_energy_closure is None
            or abs(float(stated_energy_closure) - expected_energy_closure) > 1e-10):
        report["problems"].append("historical summary energy-to-XYZ closure statistic is not recomputed correctly")
    m14_default = summary.get("m14_default")
    if not isinstance(m14_default, dict):
        m14_default = {}
    m14_record = source_calc_by_id.get("M14/ES/stda-pbe0-tzvp")
    try:
        m14_path = _safe_artifact(final, m14_record["trajectory_path"], "M14 default XYZ", report["problems"])
        m14_frames = _xyz_frames(m14_path) if m14_path else []
        m14_selected_idx = m14_record["selected_frame_index_zero_based"]
        m14_atoms = [m14_frames[m14_selected_idx][i] for i in profile["canonical_atom_maps"]["M14"]]
        expected_m14_ccl = _distance(m14_atoms[0], m14_atoms[2]) * 100.0
        stated_m14_ccl = m14_default["last_xyz_c_cl_pm"]
        if (type(stated_m14_ccl) not in (int, float) or not math.isfinite(float(stated_m14_ccl))
                or abs(float(stated_m14_ccl) - expected_m14_ccl) > 1e-6):
            report["problems"].append("M14 default C-Cl diagnostic does not match the pinned final XYZ")
    except (KeyError, TypeError, ValueError, OverflowError):
        report["problems"].append("M14 default C-Cl diagnostic is missing or malformed")
    match = re.search(r"(?m)^Summary artifact: scientific-summary\.json / SHA256: ([0-9a-f]{64})$", report_text)
    if not match or match.group(1) != hashlib.sha256(summary_path.read_bytes()).hexdigest():
        report["problems"].append("historical report does not correctly bind scientific-summary.json")
    if report["problems"]:
        report["status"] = "FAIL"
        return report, 1
    report["checks_passed"].append("historical scientific summary and report hash link validated; no minimum PASS shortcut")
    report["status"] = "UNVERIFIED"
    return report, 2


def _input_stda_fraction(text: str) -> float | None:
    clean = _clean_input(text)
    td = _section_body(clean, "TDDFPT") or _section_body(_section_body(clean, "PROPERTIES"), "TDDFPT")
    stda = _section_body(td, "STDA")
    match = re.search(r"(?im)^\s*FRACTION\s+([-+\d.Ee]+)", stda)
    try:
        return float(match.group(1).replace("D", "E")) if match else None
    except (ValueError, OverflowError):
        return None


def _verify_optimizer_final_geometry(rec: dict, final: Path, trace: dict, report: dict) -> None:
    """Bind every optimizer XYZ to its native restart, including GS records.

    Missing restart evidence leaves the component unverified; a supplied but
    mismatching restart is a candidate failure. This check is independent of the
    stronger ES minimum/VIB check.
    """
    record_id = rec.get("id", "optimizer")
    if record_id == "M14/ES/stda-pbe0-tzvp":
        # The intentional M14 dissociation attempt may lack a terminal restart;
        # its native physical-prefix adapter binds the qualifying geometries.
        rec["_verified_final_geometry"] = {"status": "UNVERIFIED", "source": "m14-physical-prefix-pending"}
        return
    input_path = _safe_artifact(final, rec.get("input_path"), f"{record_id}.input_path", report["problems"])
    if input_path is not None:
        try:
            input_text = input_path.read_bytes().decode("utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            input_text = ""
        if _review_unsupported_xc(input_text, record_id, report):
            rec["_verified_final_geometry"] = {"status": "UNVERIFIED", "source": "unsupported-xc-review"}
            return
    restart_rel = rec.get("restart_path")
    if not isinstance(restart_rel, str):
        report["pending_science_reviews"].append(f"{record_id}: native final restart/geometry binding is unavailable")
        return
    restart = _safe_artifact(final, restart_rel, f"{record_id}.restart_path", report["problems"])
    if restart is None:
        return
    _check_hash(restart, rec, "restart_sha256", f"{record_id} optimizer restart", report["problems"])
    artifacts = trace.get("artifacts", {})
    xyz, output = artifacts.get("trajectory"), artifacts.get("output")
    if xyz is None or output is None:
        return
    species = SPECIES.get(rec.get("molecule"), ())
    atom_map = rec.get("atom_map", list(range(len(species))))
    if (not isinstance(atom_map, list) or len(atom_map) != len(species)
            or any(type(x) is not int or x < 0 or x >= len(species) for x in atom_map)
            or len(set(atom_map)) != len(species)):
        report["problems"].append(f"{record_id}: invalid atom map for optimizer final geometry")
        return
    native_species = [None] * len(species)
    for canonical_index, native_index in enumerate(atom_map):
        native_species[native_index] = species[canonical_index]
    result = native_science.bind_final_geometry(
        xyz, restart, output, expected_species=native_species,
        expected_sha256={"xyz": rec.get("trajectory_sha256"),
                         "restart": rec.get("restart_sha256"),
                         "output": rec.get("output_sha256")})
    rec["_verified_final_geometry"] = result
    if result.get("status") == "FAIL":
        report["problems"].extend(f"{record_id}: {issue}" for issue in result.get("issues", []))
    elif result.get("status") != "PASS":
        report["pending_science_reviews"].extend(
            f"{record_id}: optimizer final geometry: {issue}" for issue in result.get("issues", []))


def main() -> int:
    app = Path(os.environ.get("APP", "/app")).resolve()
    tests = Path(os.environ.get("TESTS", Path(__file__).resolve().parent)).resolve()
    logs = Path(os.environ.get("LOGS", "/logs/verifier")).resolve()
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "reward.txt").unlink(missing_ok=True)
    try:
        report, code = verify(app, tests)
    except InfraError as exc:
        print(f"grader infrastructure error: {exc}", file=sys.stderr)
        return 2
    (logs / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks_passed": report["checks_passed"],
                      "problems": report["problems"]}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
