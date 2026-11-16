#!/usr/bin/env bash
# Oracle reference solution for task 152: real remote execution, no precomputed
# answers. The two helpers below are embedded so solution/ keeps one entrypoint.
set -euo pipefail
APP_DIR="${APP:-/app}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/oracle_science.py" <<'PY'
"""Candidate-side parsers and artifact writer for the finite Task 152 ORCA study.

This module has no dependency on the grader, test fixtures, or archived runs. Its
only scientific inputs are the public assets and files collected for this call.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import shlex
import datetime as dt
from pathlib import Path, PurePosixPath


class NativeEvidenceError(ValueError):
    """Native data are missing, malformed, or scientifically unresolved."""


ELEMENTS = {"H", "C", "N", "O"}
PINNED_INPUTS = {
    "1br5_candidate.xyz": "4577723bf344560381954776313ff391e75da6d6243a1c6dd27a662579deae9f",
    "1br5_reference.xyz": "dcd2a67f393172737605cd770bc235418bd653d1a52451d310c9948363bafae2",
    "NEO.cif": "032d8e009325672f60a6636e3a76f9f65c27e367445c047de025ff3a0119b680",
    "1BR5_NEO_A_500.pdb": "6a0944b888a972ecbc42198c809a5590c426d6840d2b1fcaaa85eef08e015081",
}
OPT_KEYS = ("energy_change", "rms_gradient", "max_gradient", "rms_step", "max_step")
UNITS = {"energy_change": "Eh", "rms_gradient": "Eh/bohr", "max_gradient": "Eh/bohr",
         "rms_step": "bohr", "max_step": "bohr", "max_cycles": "cycles"}


def _number(value: str) -> float:
    result = float(value.replace("D", "E").replace("d", "e"))
    if not math.isfinite(result):
        raise NativeEvidenceError("native record contains a non-finite number")
    return result


def parse_xyz_text(text: str) -> tuple[list[str], list[tuple[float, float, float]]]:
    lines = text.splitlines()
    if len(lines) < 3:
        raise NativeEvidenceError("XYZ is truncated")
    try:
        count = int(lines[0].strip())
    except ValueError as exc:
        raise NativeEvidenceError("XYZ atom count is malformed") from exc
    symbols, coords = [], []
    for line in lines[2:]:
        fields = line.split()
        if len(fields) != 4 or fields[0] not in ELEMENTS:
            raise NativeEvidenceError("XYZ coordinate row is malformed")
        symbols.append(fields[0])
        coords.append(tuple(_number(x) for x in fields[1:]))
    if count < 1 or len(symbols) != count:
        raise NativeEvidenceError("XYZ atom count does not match coordinate rows")
    return symbols, coords


def _orca_xyz(text: str) -> tuple[list[str], list[tuple[float, float, float]]]:
    sections = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "CARTESIAN COORDINATES (ANGSTROEM)" not in line.upper():
            continue
        symbols, coords = [], []
        for row in lines[i + 1:]:
            fields = row.split()
            if not fields or set(row.strip()) == {"-"}:
                if symbols:
                    break
                continue
            if len(fields) != 4 or fields[0] not in ELEMENTS:
                if symbols:
                    break
                continue
            try:
                xyz = tuple(_number(x) for x in fields[1:])
            except (ValueError, NativeEvidenceError):
                if symbols:
                    break
                continue
            symbols.append(fields[0]); coords.append(xyz)
        if symbols:
            sections.append((symbols, coords))
    if not sections:
        raise NativeEvidenceError("ORCA output contains no Cartesian Angstrom coordinates")
    return sections[-1]


def _convergence_table(text: str) -> dict[str, tuple[float, float, bool]]:
    sections = list(re.finditer(r"Geometry convergence", text, re.I))
    if not sections:
        raise NativeEvidenceError("ORCA output has no geometry convergence table")
    tail = text[sections[-1].start():]
    labels = {"energy_change": "Energy change", "rms_gradient": "RMS gradient",
              "max_gradient": "MAX gradient", "rms_step": "RMS step", "max_step": "MAX step"}
    result = {}
    for key, label in labels.items():
        pattern = rf"(?im)^\s*{re.escape(label)}\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+(YES|NO)\s*$"
        rows = re.findall(pattern, tail)
        if len(rows) != 1:
            raise NativeEvidenceError(f"final convergence table needs one {label} row; found {len(rows)}")
        result[key] = (_number(rows[0][0]), _number(rows[0][1]), rows[0][2].upper() == "YES")
    return result


def parse_opt_log(input_text: str, output_text: str) -> dict:
    """Return native optimization status, final table, energy and coordinates."""
    maxiter_matches = re.findall(r"(?im)^\s*MaxIter\s+(\d+)\s*$", input_text)
    if len(maxiter_matches) != 1:
        raise NativeEvidenceError("optimization input must declare exactly one MaxIter")
    maxiter = int(maxiter_matches[0])
    if not re.search(r"Program\s+Version\s+6\.0\.1\s+-\s+RELEASE", output_text, re.I):
        raise NativeEvidenceError("optimization output does not identify ORCA 6.0.1")
    cycles = [int(x) for x in re.findall(r"(?i)GEOMETRY OPTIMIZATION CYCLE\s+(\d+)", output_text)]
    table = _convergence_table(output_text)
    normal = "ORCA TERMINATED NORMALLY" in output_text.upper()
    converged = bool(re.search(r"THE OPTIMIZATION HAS CONVERGED|OPTIMIZATION CONVERGED", output_text, re.I))
    energy_rows = re.findall(r"(?im)^\s*FINAL SINGLE POINT ENERGY\s+([-+\d.eE]+)\s*$", output_text)
    if not energy_rows:
        raise NativeEvidenceError("ORCA output has no final single point energy")
    energy = _number(energy_rows[-1])
    symbols, coords = _orca_xyz(output_text)
    failed = [name for name, row in table.items() if not row[2]]
    if converged != (not failed):
        raise NativeEvidenceError("optimizer marker contradicts the final convergence table")
    return {"normal_termination": normal, "converged": converged, "optimizer_table": table,
            "energy_Eh": energy, "cycles": max(cycles, default=0), "maxiter": maxiter,
            "final_symbols": symbols, "final_coordinates": coords, "failed_criteria": failed,
            "maxiter_reached": bool(maxiter and cycles and max(cycles) >= maxiter)}


def parse_frequencies(output_text: str, hessian_text: str) -> dict:
    heads = list(re.finditer(r"VIBRATIONAL FREQUENCIES", output_text, re.I))
    if not heads:
        raise NativeEvidenceError("frequency output lacks the vibrational frequencies section")
    modes = []
    for line in output_text[heads[-1].end():].splitlines():
        m = re.match(r"^\s*(\d+)\s*:\s*([-+\d.eE]+)\s+cm\*\*-1\b", line, re.I)
        if m:
            modes.append((int(m.group(1)), _number(m.group(2))))
        elif modes and re.search(r"NORMAL MODES|IR SPECTRUM|RAMAN SPECTRUM", line, re.I):
            break
    if not modes or [i for i, _ in modes] != list(range(len(modes))) or len(modes) % 3:
        raise NativeEvidenceError("frequency table must contain sequential 3N modes")
    section = re.search(r"(?ms)^\$vibrational_frequencies\s*\n(.*?)(?=^\$|\Z)", hessian_text)
    if not section:
        raise NativeEvidenceError("Hessian lacks vibrational frequencies")
    lines = section.group(1).splitlines()
    if not lines or int(lines[0].strip()) != len(modes):
        raise NativeEvidenceError("Hessian frequency count differs from native frequency table")
    hm = []
    for line in lines[1:]:
        fields = line.split()
        if fields:
            if len(fields) != 2 or not fields[0].isdigit():
                raise NativeEvidenceError("Hessian frequency row is malformed")
            hm.append((int(fields[0]), _number(fields[1])))
    if [i for i, _ in hm] != list(range(len(modes))):
        raise NativeEvidenceError("Hessian frequencies are incomplete or unordered")
    hess_matrix = re.search(r"(?ms)^\$hessian\s*\n\s*(\d+)\s*\n(.*?)(?=^\$|\Z)", hessian_text)
    n = len(modes)
    if not hess_matrix or int(hess_matrix.group(1)) != n:
        raise NativeEvidenceError("Hessian matrix dimension differs from 3N")
    matrix = [[None] * n for _ in range(n)]
    cols = []
    for line in hess_matrix.group(2).splitlines():
        fields = line.split()
        if not fields: continue
        if all(x.isdigit() for x in fields) and len(fields) <= 6 and all(int(x) < n for x in fields):
            cols = [int(x) for x in fields]; continue
        if not cols or not fields[0].isdigit() or len(fields) != len(cols) + 1:
            raise NativeEvidenceError("Hessian matrix block is malformed")
        row = int(fields[0])
        if not 0 <= row < n: raise NativeEvidenceError("Hessian row index is invalid")
        for col, token in zip(cols, fields[1:]):
            value = _number(token)
            if matrix[row][col] is not None: raise NativeEvidenceError("duplicate Hessian matrix element")
            matrix[row][col] = value
    if any(x is None for row in matrix for x in row):
        raise NativeEvidenceError("Hessian matrix is incomplete")
    if any(abs(matrix[i][j] - matrix[j][i]) > 1e-7 for i in range(n) for j in range(i)):
        raise NativeEvidenceError("Hessian matrix is not symmetric")
    if any(abs(hm[i][1] - modes[i][1]) > 0.02 for i in range(n)):
        raise NativeEvidenceError("Hessian and frequency output modes disagree")
    trans = modes[:6]
    vib = [v for _, v in modes[6:]]
    if len(trans) != 6 or any(v != 0 for _, v in trans):
        raise NativeEvidenceError("six ProjectTR rigid modes are not explicitly zero")
    if any(v < -20.0 for v in vib):
        decision = "reject"
        reason = f"native frequency analysis has imaginary mode {min(vib):.2f} cm-1"
    elif any(-20.0 <= v <= 0.0 for v in vib):
        raise NativeEvidenceError("frequency contains an unresolved mode in [-20, 0] cm-1")
    else:
        decision, reason = "accept", "all native vibrational modes are above 0 cm-1"
    return {"modes_cm-1": [v for _, v in modes], "mode_count": n,
            "trans_rot_mode_count": 6, "decision": decision, "reason": reason}


def parse_stability_eigenvalues(output_text: str) -> dict:
    sections = list(re.finditer(r"(?im)^\s*WAVEFUNCTION STABILITY ANALYSIS\s*$", output_text))
    if not sections:
        raise NativeEvidenceError("stability output lacks wavefunction stability analysis")
    tail = output_text[sections[-1].end():]
    stop = re.search(r"(?im)^\s*TOTAL SCF ENERGY\s*$", tail)
    block = tail[:stop.start()] if stop else tail
    if not re.search(r"(?im)^\s*\*\*\*\s*CONVERGENCE OF RESIDUAL NORM REACHED\s*\*\*\*\s*$", block):
        raise NativeEvidenceError("stability eigensolver did not converge")
    header = re.search(r"(?im)^\s*The eigenvalues of the stability matrix:\s*$", block)
    if not header:
        raise NativeEvidenceError("stability matrix eigenvalues are absent")
    values = []
    for line in block[header.end():].splitlines():
        m = re.fullmatch(r"\s*E\(\s*(\d+)\s*\)\s*=\s*([-+\d.eE]+)\s+Eh\s*", line, re.I)
        if m:
            if int(m.group(1)) != len(values): raise NativeEvidenceError("stability eigenvalue roots are unordered")
            values.append(_number(m.group(2)))
        elif values: break
    if len(values) != 3:
        raise NativeEvidenceError("stability output must contain exactly three eigenvalues")
    residuals = re.findall(r"(?im)^\s*Maximum residual norm\s*:\s*([-+\d.eE]+)\s*$", block)
    if not residuals or not math.isfinite(_number(residuals[-1])):
        raise NativeEvidenceError("stability output lacks a finite final residual norm")
    if any(v < 0 for v in values): decision, reason = "reject", f"negative SCF stability eigenvalue {min(values):.8g} Eh"
    elif any(v == 0 for v in values): raise NativeEvidenceError("zero SCF stability eigenvalue is unresolved")
    else: decision, reason = "accept", "all three native SCF stability eigenvalues are positive"
    return {"lowest_eigenvalues_hartree": values, "decision": decision, "reason": reason}


def parse_optimization(input_path: Path, output_path: Path) -> dict:
    raw = parse_opt_log(Path(input_path).read_text(), Path(output_path).read_text())
    return {"normal_termination": raw["normal_termination"], "converged": raw["converged"],
            "table": raw["optimizer_table"], "energy": raw["energy_Eh"],
            "cycle_count": raw["cycles"], "final_xyz": _xyz_text(raw["final_symbols"], raw["final_coordinates"]),
            "failed_criteria": raw["failed_criteria"], "maxiter": raw["maxiter"],
            "maxiter_reached": raw["maxiter_reached"]}


def parse_frequency(output_path: Path, hess_path: Path, geometry_path: Path) -> dict:
    result = parse_frequencies(Path(output_path).read_text(), Path(hess_path).read_text())
    symbols, coords = parse_xyz_text(Path(geometry_path).read_text())
    if len(symbols) * 3 != result["mode_count"]:
        raise NativeEvidenceError("frequency mode count does not equal 3N for its geometry")
    output = Path(output_path).read_text()
    out_symbols, out_coords = _orca_xyz(output)
    if out_symbols != symbols or len(out_coords) != len(coords) or any(_distance(a,b) > 1e-3 for a,b in zip(out_coords,coords)):
        raise NativeEvidenceError("frequency output coordinates differ from its geometry input")
    if "ORCA TERMINATED NORMALLY" not in output.upper():
        raise NativeEvidenceError("frequency output did not terminate normally")
    hess = Path(hess_path).read_text()
    atom_section = re.search(r"(?ms)^\$atoms\s*\n(.*?)(?=^\$|\Z)", hess)
    if not atom_section:
        raise NativeEvidenceError("Hessian lacks atom coordinates")
    rows = [line.split() for line in atom_section.group(1).splitlines() if line.split()]
    if not rows or not rows[0][0].isdigit() or int(rows[0][0]) != len(symbols):
        raise NativeEvidenceError("Hessian atom count differs from geometry")
    atom_rows = rows[1:]
    bohr_to_angstrom = 0.529177210903
    if len(atom_rows) != len(symbols): raise NativeEvidenceError("Hessian atom block is incomplete")
    hcoords = []
    for symbol, xyz, row in zip(symbols, coords, atom_rows):
        if len(row) != 5 or row[0] != symbol:
            raise NativeEvidenceError("Hessian atom order differs from validation geometry")
        native = tuple(_number(x) * bohr_to_angstrom for x in row[2:])
        hcoords.append(native)
    if not _same_oriented_geometry(coords, hcoords):
        raise NativeEvidenceError("Hessian atom geometry differs from validation geometry")
    return result


def parse_stability(output_path: Path, geometry_path: Path) -> dict:
    symbols, coords = parse_xyz_text(Path(geometry_path).read_text())
    output = Path(output_path).read_text()
    out_symbols, out_coords = _orca_xyz(output)
    if out_symbols != symbols or len(out_coords) != len(coords) or any(_distance(a,b) > 1e-3 for a,b in zip(out_coords,coords)):
        raise NativeEvidenceError("stability output coordinates differ from its geometry input")
    if "ORCA TERMINATED NORMALLY" not in output.upper():
        raise NativeEvidenceError("stability output did not terminate normally")
    hftypes = re.findall(r"(?im)^\s*Hartree-Fock type\s+HFTyp\s+\.\.\.\.\s+(\w+)\s*$", output)
    charges = re.findall(r"(?im)^\s*Total Charge\s+Charge\s+\.\.\.\.\s+([-+]?\d+)\s*$", output)
    multiplicities = re.findall(r"(?im)^\s*Multiplicity\s+Mult\s+\.\.\.\.\s+(\d+)\s*$", output)
    methods = re.findall(r"(?im)^\s*Density Functional\s+Method\s+\.\.\.\.\s+([^\n]+)$", output)
    functionals = re.findall(r"(?im)^\s*Functional name\s+\.\.\.\.\s+([^\n]+)$", output)
    if (len(hftypes) != 1 or hftypes[0].upper() not in {"RHF", "RKS"} or charges != ["0"]
            or multiplicities != ["1"] or len(methods) != 1 or "DFT" not in methods[0].upper()
            or not any("Re-regularized SCAN exchange" in x for x in functionals)
            or not any("Re-regularized SCAN correlation" in x for x in functionals)):
        raise NativeEvidenceError("stability output does not establish restricted neutral-singlet r2SCAN DFT")
    parsed = parse_stability_eigenvalues(output)
    conclusions = re.findall(r"(?im)^\s*The stability analysis shows that the wavefunction is (stable|unstable)\s*$", output)
    if len(conclusions) != 1:
        raise NativeEvidenceError("stability output lacks one native stable/unstable conclusion")
    if (parsed["decision"] == "accept") != (conclusions[0].lower() == "stable"):
        raise NativeEvidenceError("native stability conclusion contradicts the eigenvalue signs")
    return parsed


def _cif_tables(path: Path) -> tuple[dict, list[dict]]:
    lines = path.read_text(encoding="utf-8").splitlines(); loops = []; i = 0
    while i < len(lines):
        if lines[i].strip() != "loop_": i += 1; continue
        i += 1; headers = []
        while i < len(lines) and lines[i].lstrip().startswith("_"):
            headers.append(lines[i].strip()); i += 1
        rows = []
        while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith("#") and lines[i].strip() != "loop_" and not lines[i].lstrip().startswith("_"):
            fields = shlex.split(lines[i], posix=True)
            if len(fields) != len(headers): raise NativeEvidenceError("CCD CIF row is malformed")
            rows.append(dict(zip(headers, fields))); i += 1
        loops.append(rows)
    atoms = next((r for r in loops if r and "_chem_comp_atom.atom_id" in r[0]), None)
    bonds = next((r for r in loops if r and "_chem_comp_bond.atom_id_1" in r[0]), None)
    if not atoms or not bonds: raise NativeEvidenceError("public CCD lacks atom or bond table")
    return {x["_chem_comp_atom.atom_id"]: x for x in atoms}, bonds


def _distance(a, b): return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


def _same_oriented_geometry(a, b, tolerance=1e-3):
    if len(a) != len(b) or len(a) < 4: return False
    for i in range(len(a)):
        for j in range(i):
            if abs(_distance(a[i], a[j]) - _distance(b[i], b[j])) > tolerance: return False
    def volume(points, ids):
        p0, p1, p2, p3 = (points[i] for i in ids)
        x = tuple(p0[k]-p3[k] for k in range(3)); y = tuple(p1[k]-p3[k] for k in range(3)); z = tuple(p2[k]-p3[k] for k in range(3))
        return x[0]*(y[1]*z[2]-y[2]*z[1])-x[1]*(y[0]*z[2]-y[2]*z[0])+x[2]*(y[0]*z[1]-y[1]*z[0])
    for ids in itertools.combinations(range(len(a)), 4):
        va, vb = volume(a, ids), volume(b, ids)
        if abs(va) > 1e-3: return abs(va-vb) <= tolerance
    return False


def _assignment(cost):
    """Exact minimum assignment for small element groups using subset DP."""
    n = len(cost)
    dp = {0: (0.0, ())}
    for row in range(n):
        nxt = {}
        for mask, (score, chosen) in dp.items():
            for col in range(n):
                if mask >> col & 1: continue
                key = mask | (1 << col); value = (score + cost[row][col], chosen + (col,))
                if key not in nxt or value[0] < nxt[key][0]: nxt[key] = value
        dp = nxt
    return dp[(1 << n)-1][1]


def derive_atom_mapping(app: Path, geometry_text: str) -> dict:
    """Map row identity from pinned input geometry; check final H-parent retention."""
    symbols, xyz = parse_xyz_text((app / "assets/1br5_candidate.xyz").read_text())
    final_symbols, final_xyz = parse_xyz_text(geometry_text)
    if symbols != final_symbols:
        raise NativeEvidenceError("final geometry changed the public candidate atom order")
    atoms, _bonds = _cif_tables(app / "assets/NEO.cif")
    pdb = []
    for line in (app / "assets/1BR5_NEO_A_500.pdb").read_text().splitlines():
        if line.startswith("HETATM") and line[17:20] == "NEO" and line[21] == "A" and line[22:26].strip() == "500":
            name, elem = line[12:16].strip(), line[76:78].strip()
            coord = tuple(float(line[i:i+8]) for i in (30, 38, 46))
            if name in atoms and elem == atoms[name]["_chem_comp_atom.type_symbol"]:
                pdb.append((name, elem, coord))
    heavy_rows = [i for i, e in enumerate(symbols) if e != "H"]
    mapped = {}
    for elem in sorted({symbols[i] for i in heavy_rows}):
        rows = [i for i in heavy_rows if symbols[i] == elem]
        refs = [p for p in pdb if p[1] == elem]
        if len(rows) != len(refs): raise NativeEvidenceError("heavy atom inventory differs from public PDB")
        cols = _assignment([[_distance(xyz[row], p[2]) for p in refs] for row in rows])
        for row, col in zip(rows, cols):
            name = refs[col][0]
            if _distance(xyz[row], refs[col][2]) > 1.6: raise NativeEvidenceError("geometry cannot be matched to PDB heavy atoms")
            mapped[row] = name
    hydrogens = []
    for row, elem in enumerate(symbols):
        if elem != "H": continue
        near = sorted((_distance(xyz[row], xyz[hr]), name, hr) for hr, name in mapped.items())
        if not near or not 0.72 <= near[0][0] <= 1.35: raise NativeEvidenceError("hydrogen parent is not geometrically resolved")
        d, parent, _ = near[0]
        parent_row = next(hr for hr, atom_name in mapped.items() if atom_name == parent)
        final_distance = _distance(final_xyz[row], final_xyz[parent_row])
        if not 0.72 <= final_distance <= 1.35:
            raise NativeEvidenceError("optimized geometry does not retain mapped hydrogen parent bond length")
        hydrogens.append({"xyz_row": row+1, "parent_atom_id": parent, "distance_angstrom": d,
                          "confidence": "high" if d <= 1.15 else "medium",
                          "interpretation": "geometric parent assignment from the supplied candidate order"})
    heavy = [{"xyz_row": row+1, "ccd_atom_id": mapped[row], "pdb_atom_name": mapped[row]}
             for row in heavy_rows]
    return {"schema": "case03-atom-map/v2", "heavy_atoms": heavy, "hydrogen_assignments": hydrogens}


def _sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _parse_full_sacct(text: str, job_id: str) -> tuple[list[str], dict[str, str]]:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != 2: raise NativeEvidenceError("rich sacct evidence must contain one header and one allocation row")
    headers = [part.strip() for part in lines[0].split("|")]
    values = [part.strip() for part in lines[1].split("|")]
    if len(headers) != len(values) or len(headers) != len(set(headers)):
        raise NativeEvidenceError("rich sacct header and row dimensions are inconsistent")
    record = dict(zip(headers, values))
    id_key = next((key for key in ("JobIDRaw", "job_id", "jobid") if key in record), None)
    if id_key is None or record[id_key] != job_id:
        raise NativeEvidenceError("rich sacct record does not identify exactly the collected allocation")
    return headers, record


def _xyz_text(symbols, coords):
    return f"{len(symbols)}\nTask152 live ORCA coordinates\n" + "".join(
        f"{e:2s} {x: .10f} {y: .10f} {z: .10f}\n" for e, (x,y,z) in zip(symbols, coords))


def _rel(app: Path, path: Path) -> str:
    rel = path.resolve().relative_to(app.resolve()).as_posix()
    if PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts: raise NativeEvidenceError("artifact escaped candidate root")
    return rel


def build_candidate(app: Path, stages: list[dict], ledger: dict, *, discovery: dict | None = None,
                    fixture_only: bool = False) -> dict[str, Path]:
    """Build candidate artifacts from collected native stages and measured ledger.

    Each stage is {name, kind, directory, job}; kinds are opt/frequency/stability.
    Fixture mode is summary-only and deliberately cannot write candidate artifacts.
    """
    app = Path(app)
    if fixture_only:
        return {"summary": Path("control_flow_only"), "qualifying": Path("false")}
    if discovery is not None and "stdout" in discovery and "6.0.1" not in str(discovery["stdout"]):
        raise NativeEvidenceError("read-only discovery did not identify the pinned ORCA 6.0.1 release")
    if not stages: raise NativeEvidenceError("no collected native stages")
    if any(s.get("kind") not in {"opt", "frequency", "stability"} for s in stages):
        raise NativeEvidenceError("unknown native stage kind")
    names = [s.get("name") for s in stages]
    if len(names) != len(set(names)): raise NativeEvidenceError("native stage names must be unique")
    artifacts: dict[str, dict] = {}
    records = []
    def add(path: Path, role: str) -> str:
        rel = _rel(app, path)
        if rel in artifacts: return rel
        if not path.is_file() or path.is_symlink(): raise NativeEvidenceError(f"missing or linked artifact: {rel}")
        artifacts[rel] = {"path": rel, "sha256": _sha(path), "role": role}
        return rel
    # Pin all public sources to the hashes currently present in the package.
    for name, role in (("1br5_candidate.xyz", "input"), ("1br5_reference.xyz", "reference"),
                       ("NEO.cif", "ccd_source"), ("1BR5_NEO_A_500.pdb", "pdb_source")):
        public_path = app / "assets" / name
        if not public_path.is_file() or _sha(public_path) != PINNED_INPUTS[name]:
            raise NativeEvidenceError(f"pinned public asset is missing or changed: {name}")
        add(public_path, role)
    opt_stages = [s for s in stages if s["kind"] == "opt"]
    freq_stage = next(s for s in stages if s["kind"] == "frequency")
    stab_stage = next(s for s in stages if s["kind"] == "stability")
    if not opt_stages: raise NativeEvidenceError("optimization stage is missing")
    if len(opt_stages) > 3: raise NativeEvidenceError("the fixed plan permits at most two optimizer recoveries")
    ids = [str(s.get("job", {}).get("job_id")) for s in stages]
    if len(ids) != len(set(ids)): raise NativeEvidenceError("native stages reuse a Slurm job ID")
    parsed_opts = []
    stage_refs = {}
    for s in stages:
        name, kind, directory, job = s["name"], s["kind"], Path(s["directory"]), s["job"]
        expected_wall = 30 if kind == "opt" else 90 if kind == "frequency" else 15
        if (int(job["allocated_cpus"]) != 2 or int(job["memory_gib"]) != 4
                or int(job["wall_minutes"]) != expected_wall):
            raise NativeEvidenceError(f"{name} resources differ from the preregistered study plan")
        if not 0 <= int(job["elapsed_seconds"]) <= expected_wall * 60:
            raise NativeEvidenceError(f"{name} elapsed time exceeds its preregistered wall allowance")
        if directory.is_symlink(): raise NativeEvidenceError("stage directory may not be a symlink")
        in_path, out_path = directory / "stage.inp", directory / "stage.out"
        required = {"input": in_path, "output": out_path, "batch": directory / "batch.sh",
                    "stdout": directory / "stdout.raw", "stderr": directory / "stderr.raw",
                    "submit_out": directory / "sbatch.stdout.raw", "submit_err": directory / "sbatch.stderr.raw",
                    "sacct": directory / "sacct.raw", "scheduler": directory / "scheduler_record.json",
                    "accounting": directory / "slurm-accounting.json"}
        if (directory / "stage.stderr.raw").is_file():
            required["engine_stderr"] = directory / "stage.stderr.raw"
        required["provenance_sacct"] = directory / "sacct_provenance.raw"
        if kind != "opt": required["collection_budget"] = directory / "collection-budget.json"
        prefix = "validation_frequency" if kind == "frequency" else "validation_stability"
        roles = {"input": "engine_input" if kind == "opt" else f"{prefix}_native_input",
                 "output": "engine_output" if kind == "opt" else f"{prefix}_native_output",
                 "batch": "scheduler_submission", "stdout": "scheduler_submission", "stderr": "scheduler_submission",
                 "submit_out": "scheduler_submission", "submit_err": "scheduler_submission",
                 "sacct": "scheduler_accounting_raw" if kind == "opt" else f"{prefix}_scheduler_accounting_raw",
                 "scheduler": "scheduler_record", "accounting": "scheduler_accounting" if kind == "opt" else f"{prefix}_slurm_accounting",
                 "provenance_sacct": "scheduler_provenance_raw"}
        if kind != "opt": roles["submit_out"] = f"{prefix}_scheduler_submission"
        if "engine_stderr" in required: roles["engine_stderr"] = "engine_error"
        if kind != "opt": roles["collection_budget"] = f"{prefix}_budget_snapshot"
        refs = {key: add(path, roles[key]) for key, path in required.items()}
        stage_refs[name] = refs
        if kind == "opt":
            opt_input = in_path.read_text()
            if not re.search(r"(?im)^\s*!\s*r2SCAN-3c\s+Opt\s+TightSCF\s*$", opt_input):
                raise NativeEvidenceError(f"{name} input is outside the fixed optimization method")
            pal = re.findall(r"(?im)^\s*%pal\s+nprocs\s+(\d+)\s+end\s*$", opt_input)
            maxcore = re.findall(r"(?im)^\s*%maxcore\s+(\d+)\s*$", opt_input)
            if (len(pal) != 1 or len(maxcore) != 1 or int(pal[0]) > int(job["allocated_cpus"])
                    or int(maxcore[0]) * int(pal[0]) > int(job["memory_gib"])*1024):
                raise NativeEvidenceError(f"{name} input process/memory directives exceed its allocation")
            parsed = parse_opt_log(in_path.read_text(), out_path.read_text())
            if parsed["normal_termination"] is not True:
                raise NativeEvidenceError(f"{name} ORCA job did not terminate normally")
            if not parsed["converged"] and name == opt_stages[-1]["name"]:
                raise NativeEvidenceError(f"{name} remained nonconverged; driver must stop")
            if not parsed_opts and parsed["maxiter"] != 100:
                raise NativeEvidenceError("initial optimization must use preregistered MaxIter 100")
            if parsed["cycles"] > parsed["maxiter"]:
                raise NativeEvidenceError(f"{name} optimizer cycles exceed its native MaxIter")
            if len(parsed_opts) and parsed["maxiter"] <= parsed_opts[-1][1]["maxiter"]:
                raise NativeEvidenceError("recovery MaxIter must strictly increase")
            parsed_opts.append((s, parsed, refs))
            geom_path = directory / "opt.xyz"
            if not geom_path.is_file(): raise NativeEvidenceError("optimization stage lacks ORCA-derived opt.xyz")
            add(geom_path, "final_geometry" if name == opt_stages[-1]["name"] else "intermediate_geometry")
        else:
            job = s["job"]
            if int(job["allocated_cpus"]) != 2 or int(job["memory_gib"]) != 4:
                raise NativeEvidenceError(f"{name} does not match preregistered 2 CPU / 4 GiB resources")
            inp = in_path.read_text()
            if not re.search(r"(?i)r2SCAN-3c", inp) or not re.search(r"(?im)^\s*\*\s*xyzfile\s+0\s+1\s+\S+", inp):
                raise NativeEvidenceError(f"{name} input differs from fixed neutral-singlet r2SCAN-3c model")
            pal = re.findall(r"(?im)^\s*%pal\s+nprocs\s+(\d+)\s+end\s*$", inp)
            maxcore = re.findall(r"(?im)^\s*%maxcore\s+(\d+)\s*$", inp)
            if (len(pal) != 1 or int(pal[0]) > int(job["allocated_cpus"])
                    or (maxcore and (len(maxcore) != 1 or int(maxcore[0]) * int(pal[0]) > int(job["memory_gib"])*1024))):
                raise NativeEvidenceError(f"{name} input process/memory directives exceed its allocation")
            if kind == "frequency" and (not re.search(r"(?i)\bFREQ\b", inp)
                    or not re.search(r"(?is)%freq\s+.*?ProjectTR\s+true", inp)
                    or re.search(r"(?i)\bOPT\b", inp)):
                raise NativeEvidenceError("frequency input lacks fixed FREQ/ProjectTR protocol")
            if kind == "stability" and (not re.search(r"(?i)STABPerform\s+true", inp)
                    or not re.search(r"(?i)STABRestartUHFifUnstable\s+false", inp)
                    or not re.search(r"(?i)STABNRoots\s+3", inp)
                    or re.search(r"(?i)\bOPT\b|\bFREQ\b", inp)):
                raise NativeEvidenceError("stability input lacks fixed three-root RKS-to-UKS protocol")
            geom_path = directory / "geometry.xyz"
            if not geom_path.is_file(): raise NativeEvidenceError(f"{name} lacks geometry.xyz")
            refs["geometry"] = add(geom_path, f"validation_{kind}_geometry_input")
            if kind == "frequency":
                hesses = list(directory.glob("*.hess"))
                if len(hesses) != 1: raise NativeEvidenceError("frequency stage must contain exactly one Hessian")
                refs["hessian"] = add(hesses[0], "native_hessian")
    final_stage, final_opt, final_refs = parsed_opts[-1]
    symbols, coords = final_opt["final_symbols"], final_opt["final_coordinates"]
    xyz_text = f"{len(symbols)}\nTask152 live ORCA final coordinates\n" + "".join(
        f"{e:2s} {x: .10f} {y: .10f} {z: .10f}\n" for e, (x,y,z) in zip(symbols, coords))
    mapping = derive_atom_mapping(app, xyz_text)
    freq_native = parse_frequency(Path(freq_stage["directory"], "stage.out"),
                                  next(Path(freq_stage["directory"]).glob("*.hess")),
                                  Path(freq_stage["directory"], "geometry.xyz"))
    stability = parse_stability(Path(stab_stage["directory"], "stage.out"),
                                Path(stab_stage["directory"], "geometry.xyz"))
    for validation_stage in (freq_stage, stab_stage):
        output_text = Path(validation_stage["directory"], "stage.out").read_text()
        if not re.search(r"Program\s+Version\s+6\.0\.1\s+-\s+RELEASE", output_text, re.I):
            raise NativeEvidenceError(f"{validation_stage['name']} output does not identify ORCA 6.0.1")
        energies = re.findall(r"(?im)^\s*FINAL SINGLE POINT ENERGY\s+([-+\d.eE]+)\s*$", output_text)
        if not energies or abs(_number(energies[-1]) - final_opt["energy_Eh"]) > 1e-6:
            raise NativeEvidenceError(f"{validation_stage['name']} energy differs from final optimization by more than 1e-6 Eh")
    for validation_stage in (freq_stage, stab_stage):
        vs, vc = parse_xyz_text(Path(validation_stage["directory"], "geometry.xyz").read_text())
        if vs != symbols or len(vc) != len(coords) or any(_distance(a,b) > 1e-3 for a,b in zip(vc,coords)):
            raise NativeEvidenceError(f"{validation_stage['name']} geometry differs from optimized coordinates")
    if freq_native["decision"] == "reject" or stability["decision"] == "reject": decision = "reject"
    else: decision = "accept"
    # Scheduler and charge records are generated only from driver-collected fields.
    execution = []
    attempts = []
    validations = {}
    rows = []
    for s, parsed, refs in parsed_opts:
        name, job = s["name"], s["job"]
        rec = _stage_record(app, s, refs, add)
        execution.append(rec["candidate_submission"])
        rows.append(rec["ledger_row"])
        attempts.append({"name": name, "reason": "initial optimization" if len(attempts) == 0 else "native nonconvergence recovery",
                         "job_id": job["job_id"], "slurm_state": job["state"], "allocated_cpus": int(job["allocated_cpus"]),
                         "memory_gib": int(job["memory_gib"]), "wall_minutes": int(job["wall_minutes"]),
                         "elapsed_seconds": int(job["elapsed_seconds"]), "native_input": refs["input"],
                         "native_output": refs["output"], "scheduler_submission": refs["submit_out"],
                         "scheduler_accounting_raw": refs["sacct"], "slurm_accounting": refs["accounting"],
                         "normal_termination": parsed["normal_termination"], "converged": parsed["converged"]})
    # Recovery is permitted only after native-normal completion and an explicit failed table.
    for i in range(len(attempts)-1):
        prev = attempts[i]
        if prev["slurm_state"] != "COMPLETED" or not prev["normal_termination"] or prev["converged"]:
            raise NativeEvidenceError("recovery lacks a normally terminated nonconvergence trigger")
        prev["next_action"] = {"kind": "extend_optimizer_iterations", "evidence": {
            "native_output": prev["native_output"], "failed_criteria": parsed_opts[i][1]["failed_criteria"]}}
        recovery_dir = Path(opt_stages[i+1]["directory"])
        recovery_input = (recovery_dir / "stage.inp").read_text()
        xyz_ref = re.search(r"(?im)^\s*\*\s*xyzfile\s+0\s+1\s+(\S+)\s*$", recovery_input)
        if not xyz_ref or Path(xyz_ref.group(1)).name != "geometry.xyz":
            raise NativeEvidenceError("recovery input must use its staged geometry.xyz")
        recovery_geometry = recovery_dir / "geometry.xyz"
        rs, rc = parse_xyz_text(recovery_geometry.read_text())
        previous_symbols = parsed_opts[i][1]["final_symbols"]
        previous_coords = parsed_opts[i][1]["final_coordinates"]
        if rs != previous_symbols or any(_distance(a,b) > 1e-3 for a,b in zip(rc,previous_coords)):
            raise NativeEvidenceError("recovery geometry differs from prior native final coordinates")
        attempts[i+1]["native_geometry_input"] = add(recovery_geometry, "recovery_geometry_input")
    final_table = final_opt["optimizer_table"]
    final_convergence = {"cycles": final_opt["cycles"], "energy_change_Eh": final_table["energy_change"][0],
                         "rms_gradient_Eh_per_bohr": final_table["rms_gradient"][0],
                         "max_gradient_Eh_per_bohr": final_table["max_gradient"][0],
                         "rms_step_bohr": final_table["rms_step"][0], "max_step_bohr": final_table["max_step"][0],
                         "final_energy_Eh": final_opt["energy_Eh"], "normal_termination": final_opt["normal_termination"]}
    scopes = {"local_model_only": True, "experimental_bound_state_established": False,
              "global_tautomer_optimum_established": False, "recovery_exercised": len(opt_stages) > 1}
    for s, native in ((freq_stage, freq_native), (stab_stage, stability)):
        rec = _stage_record(app, s, stage_refs[s["name"]], add)
        execution.append(rec["candidate_submission"]); rows.append(rec["ledger_row"])
        job, refs = s["job"], rec["refs"]
        snapshot_rel = refs["collection_budget"]
        item = {"attempt_name": "freq-validation" if s["kind"] == "frequency" else "stability-validation",
                "job_id": job["job_id"], "slurm_state": job["state"], "allocated_cpus": int(job["allocated_cpus"]),
                "memory_gib": int(job["memory_gib"]), "wall_minutes": int(job["wall_minutes"]),
                "elapsed_seconds": int(job["elapsed_seconds"]), "native_input": refs["input"], "native_output": refs["output"],
                "geometry_input": refs["geometry"], "scheduler_submission": refs["submit_out"],
                "scheduler_accounting_raw": refs["sacct"], "slurm_accounting": refs["accounting"],
                "collection_budget_snapshot": snapshot_rel}
        if s["kind"] == "frequency": item.update({"native_hessian": refs["hessian"], "mode_count": native["mode_count"], "trans_rot_mode_count": 6})
        else: item.update({"lowest_eigenvalues_hartree": native["lowest_eigenvalues_hartree"], "analysis_space": "RKS_to_UKS"})
        validations["frequency" if s["kind"] == "frequency" else "stability"] = item
    charged = sum(r["charged_cpu_minutes"] for r in rows)
    if charged > 390: raise NativeEvidenceError("measured CPU-minute total exceeds the preregistered 390 CPU-minute plan")
    budget_path = app / "native" / "budget.json"
    reserved = int(ledger.get("reserved_cpu_minutes", 0))
    if reserved != 0: raise NativeEvidenceError("unresolved budget reservations prevent candidate publication")
    declared_charged = ledger.get("charged_cpu_minutes")
    if declared_charged is not None and int(declared_charged) != charged:
        raise NativeEvidenceError("driver budget total disagrees with settled native-stage charges")
    ledger_out = {"schema": "case03-budget/v1", "limit_cpu_minutes": 960, "charged_cpu_minutes": charged,
                  "reserved_cpu_minutes": 0, "attempts": rows, "additional_billing_records": []}
    _write_json(budget_path, ledger_out); budget_rel = add(budget_path, "budget_ledger")
    (app / "geometry.xyz").write_text(xyz_text, encoding="utf-8")
    _write_json(app / "atom_mapping.json", mapping)
    # Collection snapshots are written from the current ledger state, never from a reference result.
    scope_line = "Scope assertions: " + "; ".join(f"{k}={str(v).lower()}" for k,v in scopes.items())
    result = {"task_version": "2.0", "schema": "case03-result/v2", "evaluation_scope": {
        "model": "ORCA 6.0.1 r2SCAN-3c gas-phase neutral singlet", "recovery_attempts_max": 2,
        "native_authenticity": "unverified", "recovery_coverage": "finite-normal-stop-only"},
        "decision": decision, "engine": {"name": "ORCA", "version": "6.0.1"}, "method": "r2SCAN-3c",
        "charge_spin": {"charge": 0, "multiplicity": 1, "rationale": "Conditional neutral singlet specified by the public model."},
        "connectivity_source": "public NEO CCD bond table in assets/NEO.cif", "convergence_thresholds": [
            {"name": name, "value": final_table[name][1], "unit": UNITS[name]} for name in OPT_KEYS] +
            [{"name": "max_cycles", "value": final_opt["maxiter"], "unit": "cycles"}],
        "final_convergence": final_convergence, "attempts": attempts, "recovery_exercised": len(opt_stages)>1,
        "native_artifacts": list(artifacts.values()), "scope_limitations": "Conditional gas-phase local-model result; does not establish experimental bound-state behavior or a global tautomer optimum.",
        "scope_claims": scopes, "scientific_validation": {"model": {"method": "r2SCAN-3c", "charge": 0,
            "multiplicity": 1, "geometry_sha256": hashlib.sha256(xyz_text.encode()).hexdigest()}, **validations},
        "budget_snapshot": {"path": budget_rel, "charged_cpu_minutes": charged,
                            "reserved_cpu_minutes": int(ledger.get("reserved_cpu_minutes", 0)), "limit_cpu_minutes": 960},
        "candidate_submission": {"schema": "bench23-candidate-submission/v1", "execution_order": execution}}
    _write_json(app / "result.json", result)
    report = ("# Task 152 native ORCA result\n\n" + f"Decision: **{decision}**.\n\n"
              + f"Optimization cycles: {final_opt['cycles']}; final energy: {final_opt['energy_Eh']:.12f} Eh.\n\n"
              + f"Frequency: {freq_native['reason']}. Stability: {stability['reason']}.\n\n" + scope_line + "\n")
    (app / "report.md").write_text(report, encoding="utf-8")
    # Add the ordinary candidate files and final manifest hash after writing all outputs.
    for path, role in ((app / "geometry.xyz", "final_geometry"), (app / "atom_mapping.json", "atom_mapping"), (app / "report.md", "report")):
        add(path, role)
    for rel, item in artifacts.items():
        item["sha256"] = _sha(app / rel)
    result["native_artifacts"] = list(artifacts.values())
    _write_json(app / "result.json", result)
    add(app / "result.json", "result")
    manifest = app / "native" / "manifest.json"
    _write_json(manifest, {"schema": "task152-native-manifest/v1", "artifacts": list(artifacts.values())})
    return {"result": app / "result.json", "geometry": app / "geometry.xyz", "mapping": app / "atom_mapping.json",
            "report": app / "report.md", "manifest": manifest}


def _stage_record(app: Path, stage: dict, refs: dict, add_artifact) -> dict:
    name, directory, job = stage["name"], Path(stage["directory"]), stage["job"]
    required = ("job_id", "allocation_id", "state", "allocated_cpus", "memory_gib", "wall_minutes",
                "elapsed_seconds", "exit_code")
    if any(k not in job for k in required): raise NativeEvidenceError(f"{name} job metadata is incomplete")
    start_time = job.get("start_time", job.get("start"))
    end_time = job.get("end_time", job.get("end"))
    if not start_time or not end_time: raise NativeEvidenceError(f"{name} scheduler timestamps are missing")
    drel = _rel(app, directory)
    ref_paths = {"receipt": directory / "receipt.json", "scheduler_record": directory / "scheduler_record.json",
                 "scheduler_raw_log": directory / "sacct_provenance.raw", "batch_script": directory / "batch.sh",
                 "stdout": directory / "stdout.raw", "stderr": directory / "stderr.raw",
                 "submit_out": directory / "sbatch.stdout.raw"}
    raw_path = ref_paths["scheduler_raw_log"]
    headers, raw = _parse_full_sacct(raw_path.read_text(encoding="utf-8"), str(job["job_id"]))
    def field(*names):
        found = [raw[name] for name in names if name in raw]
        if len(found) != 1: raise NativeEvidenceError(f"{name} scheduler raw record lacks one of {names}")
        return found[0]
    raw_state = field("State", "State%40", "state").split()[0].upper()
    raw_start, raw_end = field("Start", "start_time"), field("End", "end_time")
    try:
        for stamp in (raw_start, raw_end):
            parsed_stamp = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if parsed_stamp.tzinfo is None or parsed_stamp.utcoffset() is None: raise ValueError
    except ValueError as exc:
        raise NativeEvidenceError(f"{name} scheduler timestamps require explicit UTC offsets") from exc
    try:
        raw_elapsed = int(field("ElapsedRaw", "elapsed_seconds"))
        raw_cpus = int(field("AllocCPUS", "allocated_cpus"))
        raw_exit = field("ExitCode", "exit_code")
        raw_id = field("JobIDRaw", "job_id", "jobid")
        tres = field("AllocTRES", "alloc_tres")
    except ValueError as exc:
        raise NativeEvidenceError(f"{name} scheduler allocation row is malformed") from exc
    mem_matches = re.findall(r"(?:^|,)mem=(\d+)([KMG])(?:i?B)?(?=,|$)", tres, re.I)
    memory_mb = {round(int(amount) * {"K": 1/1024, "M": 1, "G": 1024}[unit.upper()]) for amount,unit in mem_matches}
    raw_gpu = re.findall(r"(?:^|,)(?:gpu|gres/gpu)(?:[:/][A-Za-z0-9_.-]+)?=(\d+)(?=,|$)", tres, re.I)
    if (raw_id != str(job["job_id"]) or raw_state != "COMPLETED" or raw_elapsed != int(job["elapsed_seconds"])
            or raw_cpus != int(job["allocated_cpus"]) or raw_exit != str(job["exit_code"])
            or raw_start != start_time or raw_end != end_time
            or memory_mb != {int(job["memory_gib"])*1024} or any(int(v) for v in raw_gpu)):
        raise NativeEvidenceError(f"{name} collected scheduler raw record contradicts stage metadata/resources")
    scheduler_record = {"job_id": str(job["job_id"]), "scheduler": "slurm",
                        "allocation_id": str(job["allocation_id"]), "gpus": 0,
                        "cpus": int(job["allocated_cpus"]), "memory_mb": int(job["memory_gib"])*1024,
                        "wall_seconds": int(job["elapsed_seconds"]), "exit_code": str(job["exit_code"]),
                        "final_state": raw_state, "start_time": raw_start, "end_time": raw_end,
                        "raw_scheduler_log": {"path": _rel(app, raw_path), "sha256": _sha(raw_path)}}
    _write_json(ref_paths["scheduler_record"], scheduler_record)
    batch_hash = _sha(ref_paths["batch_script"])
    receipt = {"job_id": str(job["job_id"]), "scheduler": "slurm", "allocation_id": str(job["allocation_id"]),
               "gpus": 0, "cpus": int(job["allocated_cpus"]), "memory_mb": int(job["memory_gib"])*1024,
               "wall_seconds": int(job["elapsed_seconds"]), "exit_code": job["exit_code"],
               "batch_script_sha256": batch_hash,
               "native_outputs": [{"path": _rel(app, directory / "stage.out"),
                                   "sha256": _sha(directory / "stage.out")} ]}
    exit_code = job["exit_code"]
    if isinstance(exit_code, str):
        if not re.fullmatch(r"(?:0|[1-9]\d*):(?:0|[1-9]\d*)", exit_code):
            raise NativeEvidenceError(f"{name} exit code is malformed")
        receipt["exit_code"] = exit_code
    else:
        receipt["exit_code"] = int(exit_code)
    _write_json(ref_paths["receipt"], receipt)
    refs = dict(refs)
    refs["receipt"] = add_artifact(ref_paths["receipt"], "scheduler_receipt")
    return _finish_stage_record(app, stage, refs, ref_paths, receipt)


def _finish_stage_record(app, stage, refs, paths, receipt):
    name, job = stage["name"], stage["job"]
    # The stage files are already in the native-artifact table; receipt is included here.
    sub_files = {"receipt": paths["receipt"], "scheduler_record": paths["scheduler_record"],
                 "scheduler_raw_log": paths["scheduler_raw_log"], "batch_script": paths["batch_script"],
                 "stdout": paths["stdout"], "stderr": paths["stderr"]}
    sub = {"attempt_name": name, "job_id": str(job["job_id"]), "allocation_id": str(job["allocation_id"]),
           "files": {key: {"path": _rel(app, path), "sha256": _sha(path)} for key, path in sub_files.items()}}
    charged = int(job["allocated_cpus"]) * max(1, math.ceil(int(job["elapsed_seconds"])/60))
    state = str(job["state"]).split()[0].upper()
    if state != "COMPLETED": raise NativeEvidenceError(f"{name} scheduler allocation did not complete")
    purpose = "optimization" if stage["kind"] == "opt" else "scientific_validation"
    return {"candidate_submission": sub, "ledger_row": {"name": name, "purpose": purpose,
             "job_id": str(job["job_id"]), "state": "settled",
             "scheduler_state": state, "allocated_cpus": int(job["allocated_cpus"]),
             "elapsed_seconds": int(job["elapsed_seconds"]), "wall_minutes": int(job["wall_minutes"]),
             "memory_gib": int(job["memory_gib"]), "charged_cpu_minutes": charged, "reserved_cpu_minutes": 0,
             "scheduler_accounting_raw": _rel(app, Path(stage["directory"]) / "sacct.raw"),
             "scheduler_submission": _rel(app, paths["submit_out"])}, "refs": refs}
PY

cat > "$WORK/live_oracle.py" <<'PY'
#!/usr/bin/env python3
"""Task152 live, candidate-side ORCA/Slurm Oracle.

The driver owns a deliberately small and fixed allocation plan.  It never
loads grader code or archived run data.  Offline transports are for control
flow tests only and are explicitly prevented from publishing a candidate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

INPUT_HASHES = {
    "assets/1BR5_NEO_A_500.pdb": "6a0944b888a972ecbc42198c809a5590c426d6840d2b1fcaaa85eef08e015081",
    "assets/1br5_candidate.xyz": "4577723bf344560381954776313ff391e75da6d6243a1c6dd27a662579deae9f",
    "assets/1br5_reference.xyz": "dcd2a67f393172737605cd770bc235418bd653d1a52451d310c9948363bafae2",
    "assets/NEO.cif": "032d8e009325672f60a6636e3a76f9f65c27e367445c047de025ff3a0119b680",
}
PLAN = {"cores": 2, "memory_gib": 4, "initial_minutes": 30,
        "recovery_minutes": 30, "max_recoveries": 2,
        "frequency_minutes": 90, "stability_minutes": 15,
        "cpu_minute_cap": 390, "study_hard_cap": 960}
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL",
            "OUT_OF_MEMORY", "PREEMPTED", "BOOT_FAIL", "DEADLINE"}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class OracleError(RuntimeError):
    pass


class NotReady(OracleError):
    pass


class Transport(Protocol):
    def discover(self) -> dict[str, str]: ...
    def put(self, local: Path, remote: str) -> None: ...
    def run(self, command: str, *, timeout: int = 60) -> tuple[int, bytes, bytes]: ...
    def get(self, remote: str, local: Path) -> None: ...


class SSHTransport:
    """OpenSSH backend using only aliases already present in the user's config."""
    def __init__(self, alias: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", alias):
            raise NotReady("SSH host must be an existing simple config alias")
        self.alias = alias

    def run(self, command: str, *, timeout: int = 60) -> tuple[int, bytes, bytes]:
        try:
            proc = subprocess.run(["ssh", "-T", "--", self.alias, command],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=timeout, check=False)
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            # Keep any partial submit response. The caller must treat this as
            # an unknown submission and retain its durable reservation.
            return 124, exc.stdout or b"", exc.stderr or b"SSH command timed out; submission status unknown"

    def put(self, local: Path, remote: str) -> None:
        if "\n" in remote or remote.startswith("-"):
            raise NotReady("unsafe remote path")
        proc = subprocess.run(["scp", "--", str(local), f"{self.alias}:{remote}"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=120, check=False)
        if proc.returncode:
            raise NotReady("secure copy failed; preserve the pending reservation and stop")

    def get(self, remote: str, local: Path) -> None:
        if "\n" in remote or remote.startswith("-"):
            raise NotReady("unsafe remote path")
        proc = subprocess.run(["scp", "--", f"{self.alias}:{remote}", str(local)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=120, check=False)
        if proc.returncode:
            raise NotReady("native evidence collection failed; preserve the reservation and stop")

    def discover(self) -> dict[str, str]:
        # Every command in this discovery block is read-only.  Submission is
        # a separate explicit phase, after asset validation and reservation.
        script = r'''set -euo pipefail
module load orca/6.0.1
printf 'HOST='; hostname
printf 'USER='; id -un
printf 'SLURM='; command -v sbatch
printf 'SACCT='; command -v sacct
orca_path=$(command -v orca)
orca_root=${orca_path%/*}
probe_dir=$(mktemp -d /tmp/task152-orca-probe.XXXXXX)
printf '# bounded version probe; no scientific calculation\n' > "$probe_dir/probe.inp"
# ORCA prints its release banner at startup, beyond the first screenful.
timeout 8 "$orca_path" "$probe_dir/probe.inp" > "$probe_dir/output" 2>&1 || true
orca_banner=$(grep -E -m1 '^[[:space:]]*Program Version[[:space:]]+6\.0\.1[[:space:]]+-[[:space:]]+RELEASE[[:space:]]+-[[:space:]]*$' "$probe_dir/output" || true)
rm -rf "$probe_dir"
[ -n "$orca_banner" ] || { echo 'loaded ORCA module did not provide the pinned 6.0.1 RELEASE' >&2; exit 4; }
mpi_path=$(command -v mpirun)
mpi_banner=$(timeout 5 "$mpi_path" --version 2>&1 | sed -n '1p')
[ "$mpi_banner" = 'mpirun (Open MPI) 4.1.1' ] || { echo 'loaded ORCA module did not provide reviewed Open MPI 4.1.1' >&2; exit 5; }
mpi_root=${mpi_path%/bin/mpirun}
[ "$mpi_root" != "$mpi_path" ] || { echo 'MPI path does not end in /bin/mpirun' >&2; exit 6; }
orca_mpi=$(ldd "$orca_root/orca_scfresp_mpi" | awk '$1 == "libmpi.so.40" && $2 == "=>" {print $3}')
[ "$orca_mpi" = "$mpi_root/lib/libmpi.so.40" ] || { echo 'ORCA MPI helper is not linked to the loaded MPI module' >&2; exit 7; }
printf 'ORCA_MODULE=orca/6.0.1\n'
printf 'ORCA_PATH=%s\n' "$orca_path"
printf 'ORCA_BANNER=%s\n' "$orca_banner"
printf 'MPI_PATH=%s\n' "$mpi_path"
printf 'MPI_BANNER=%s\n' "$mpi_banner"
printf 'MPI_ROOT=%s\n' "$mpi_root"
printf 'ORCA_MPI_LIB=%s\n' "$orca_mpi"
printf 'SLURM_VERSION='; sbatch --version
printf 'PARTITIONS_BEGIN\n'; sinfo -h -o '%P|%a|%l|%c|%m'
printf 'PARTITIONS_END\n'
'''
        command = "bash -lc " + shlex.quote(script)
        rc, stdout, stderr = self.run(command, timeout=30)
        if rc:
            raise NotReady("read-only SSH discovery failed: " + stderr.decode("utf-8", "replace")[-300:])
        text = stdout.decode("utf-8", "strict")
        if not re.search(r"(?m)^ORCA_PATH=/[^\s]+", text) or "SLURM_VERSION=" not in text:
            raise NotReady("remote host does not expose ORCA and Slurm discovery records")
        if not re.search(r"(?m)^ORCA_BANNER=[ \t]*Program Version[ \t]+6\.0\.1[ \t]+-[ \t]+RELEASE[ \t]+-[ \t]*$", text):
            raise NotReady("remote ORCA is not the required 6.0.1 release")
        if ("ORCA_MODULE=orca/6.0.1" not in text
                or not re.search(r"(?m)^MPI_PATH=/[^\s]+/bin/mpirun$", text)
                or "MPI_BANNER=mpirun (Open MPI) 4.1.1" not in text):
            raise NotReady("remote ORCA module did not expose the reviewed MPI runtime")
        mpi_root = re.search(r"(?m)^MPI_ROOT=(/[^\s]+)$", text)
        mpi_lib = re.search(r"(?m)^ORCA_MPI_LIB=(/[^\s]+)$", text)
        if not mpi_root or not mpi_lib or mpi_lib.group(1) != mpi_root.group(1) + "/lib/libmpi.so.40":
            raise NotReady("remote ORCA MPI helper is not linked to the selected MPI runtime")
        return {"stdout": text, "sha256": sha(stdout), "hostname": re.search(r"(?m)^HOST=(.*)$", text).group(1),
                "username": re.search(r"(?m)^USER=(.*)$", text).group(1)}


def configured_ssh_aliases(config: Path | None = None) -> list[str]:
    """Read aliases only; never expands credentials or initiates a connection."""
    config = config or (Path.home() / ".ssh/config")
    if config.is_symlink() or not config.is_file():
        return []
    aliases = []
    for line in config.read_text(errors="replace").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0].lower() == "host":
            aliases.extend(x for x in parts[1:] if not any(c in x for c in "*?!"))
    return list(dict.fromkeys(aliases))


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def validate_public_assets(app: Path) -> dict[str, Path]:
    if app.is_symlink() or not app.is_dir():
        raise NotReady("APP must be an existing real directory")
    assets = app / "assets"
    if assets.is_symlink() or not assets.is_dir():
        raise NotReady("public assets directory is missing or linked")
    found = {}
    for rel, expected in INPUT_HASHES.items():
        path = app / rel
        if path.is_symlink() or not path.is_file() or sha(path.read_bytes()) != expected:
            raise NotReady("pinned public input missing, linked, or hash-mismatched: " + rel)
        found[rel] = path
    return found


def cpu_plan() -> list[dict[str, Any]]:
    return [{"stage": "initial", "wall_minutes": 30, "maxiter": 100},
            {"stage": "recovery-1", "wall_minutes": 30, "maxiter": 200},
            {"stage": "recovery-2", "wall_minutes": 30, "maxiter": 400},
            {"stage": "freq-validation", "wall_minutes": 90},
            {"stage": "stability-validation", "wall_minutes": 15}]


def optimization_action(parsed: dict[str, Any], recovery_count: int) -> str:
    """Choose only from native termination/convergence records and fixed limits."""
    if parsed.get("normal_termination") is not True:
        return "stop"
    if parsed.get("converged") is True:
        return "validate"
    failed = parsed.get("failed_criteria")
    if parsed.get("converged") is False and isinstance(failed, list) and failed and recovery_count < PLAN["max_recoveries"]:
        return "recover"
    return "stop"


def validate_sacct(text: str, job_id: str, wall_minutes: int | None = None,
                   stage: str | None = None) -> dict[str, Any]:
    """Parse a raw pipe-delimited sacct record; require authoritative UTC offsets."""
    lines = [line for line in text.splitlines() if line]
    if len(lines) < 2:
        raise NotReady("raw sacct must contain headers and an allocation row")
    headers = [x.strip() for x in lines[0].split("|")]
    if len(set(headers)) != len(headers):
        raise NotReady("raw sacct contains duplicate headers")
    matches = [line.split("|") for line in lines[1:] if line.split("|", 1)[0].strip() == job_id]
    if len(matches) != 1 or len(matches[0]) != len(headers):
        raise NotReady("raw sacct must contain exactly one allocation row for the submitted job")
    row = dict(zip(headers, (part.strip() for part in matches[0])))
    state = row.get("State", "").split()[0].upper()
    if state not in TERMINAL:
        raise NotReady("sacct state is not a supported terminal state")
    if row.get("JobIDRaw") != job_id:
        raise NotReady("sacct identity mismatch")
    if stage is not None and row.get("JobName") != "b23-152-" + stage:
        raise NotReady("sacct job name does not match the submitted fixed stage")
    start, end = row.get("Start", ""), row.get("End", "")
    stamps = []
    for stamp in (start, end):
        try:
            parsed = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise NotReady("sacct Start/End must retain timezone-qualified timestamps") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise NotReady("sacct Start/End timestamps lack UTC offsets")
        stamps.append(parsed)
    try:
        cpus = int(row["AllocCPUS"])
        elapsed = int(row["ElapsedRaw"])
        exit_code = row["ExitCode"]
    except (KeyError, ValueError) as exc:
        raise NotReady("sacct allocation, elapsed or exit fields are malformed") from exc
    tres = row.get("AllocTRES", "")
    cpu_matches = re.findall(r"(?:^|,)cpu=(\d+)(?=,|$)", tres)
    mem_matches = re.findall(r"(?:^|,)mem=(\d+)([KMG])(?:i?B)?(?=,|$)", tres, re.I)
    gpu_counts = re.findall(r"(?:^|,)(?:gres/)?gpu(?::[A-Za-z0-9_.-]+)?=(\d+)(?=,|$)", tres, re.I)
    mem_mb = {int(amount) * {"K": 1 / 1024, "M": 1, "G": 1024}[unit.upper()]
              for amount, unit in mem_matches}
    duration = (stamps[1] - stamps[0]).total_seconds()
    if (cpus != PLAN["cores"] or len(cpu_matches) != 1 or set(map(int, cpu_matches)) != {PLAN["cores"]}
            or elapsed < 0
            or not re.fullmatch(r"\d+:\d+", exit_code)
            or len(mem_mb) != 1 or round(next(iter(mem_mb))) != PLAN["memory_gib"] * 1024
            or any(int(n) for n in gpu_counts)
            or re.search(r"gpu|gres/gpu", tres, re.I) and not gpu_counts
            or duration < 0 or abs(duration - elapsed) > 1):
        raise NotReady("sacct allocation contradicts the frozen resource contract")
    return {"job_id": job_id, "state": state, "start": start, "end": end,
            "elapsed_seconds": elapsed, "allocated_cpus": cpus,
            "exit_code": exit_code, "over_wall": wall_minutes is not None and elapsed > wall_minutes * 60,
            "raw": text}


def charged_minutes(row: dict[str, Any]) -> int:
    return int(row["allocated_cpus"]) * max(1, math.ceil(int(row["elapsed_seconds"]) / 60))


class Budget:
    """Persistent per-candidate conservative holds; uncertain jobs stay held."""
    def __init__(self, path: Path):
        self.path = path
        if path.exists():
            try:
                value = json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                raise NotReady("budget ledger is unreadable; refusing new allocation") from exc
            if value.get("schema") != "task152-live-budget/v1":
                raise NotReady("budget ledger schema mismatch")
            if value.get("limit_cpu_minutes") != PLAN["cpu_minute_cap"]:
                raise NotReady("budget ledger allowance differs from the frozen task plan")
            if type(value.get("charged_cpu_minutes")) is not int or type(value.get("reserved_cpu_minutes")) is not int:
                raise NotReady("budget ledger totals are malformed")
            if value["charged_cpu_minutes"] < 0 or value["reserved_cpu_minutes"] < 0:
                raise NotReady("budget ledger totals cannot be negative")
            rows = value.get("jobs")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise NotReady("budget ledger job rows are malformed")
            stages, tokens, job_ids, charges, held = set(), set(), set(), 0, 0
            allowed_stages = {row["stage"] for row in cpu_plan()}
            for row in rows:
                stage, token, state = row.get("stage"), row.get("reservation_id"), row.get("state")
                try:
                    if str(uuid.UUID(token)) != token:
                        raise ValueError("non-canonical UUID")
                except (ValueError, TypeError, AttributeError):
                    raise NotReady("budget ledger reservation token is malformed")
                if stage not in allowed_stages or stage in stages or token in tokens:
                    raise NotReady("budget ledger stage or reservation identity is duplicate/invalid")
                stages.add(stage); tokens.add(token)
                if type(row.get("reserved_cpu_minutes")) is not int or row["reserved_cpu_minutes"] < 0:
                    raise NotReady("budget reservation row is malformed")
                if state == "RESERVED":
                    held += row["reserved_cpu_minutes"]
                    raise NotReady("prior submission is unsettled; preserve evidence and do not submit again")
                if state != "SETTLED" or row["reserved_cpu_minutes"] != 0:
                    raise NotReady("budget ledger contains an unknown or unsettled state")
                accounting = row.get("accounting")
                required_accounting = {"job_id", "state", "allocated_cpus", "memory_gib",
                                       "wall_minutes", "elapsed_seconds", "start", "end", "exit_code"}
                if (not isinstance(accounting, dict) or set(accounting) != required_accounting
                        or not re.fullmatch(r"[1-9][0-9]*", str(accounting.get("job_id", "")))):
                    raise NotReady("settled budget row lacks its actual scheduler identity")
                if accounting["job_id"] in job_ids:
                    raise NotReady("budget ledger reuses a Slurm job ID")
                job_ids.add(accounting["job_id"])
                expected_wall = next(spec["wall_minutes"] for spec in cpu_plan() if spec["stage"] == stage)
                if (accounting["state"] not in TERMINAL
                        or type(accounting["allocated_cpus"]) is not int or accounting["allocated_cpus"] != PLAN["cores"]
                        or type(accounting["memory_gib"]) is not int or accounting["memory_gib"] != PLAN["memory_gib"]
                        or type(accounting["wall_minutes"]) is not int or accounting["wall_minutes"] != expected_wall
                        or type(accounting["elapsed_seconds"]) is not int or accounting["elapsed_seconds"] < 0
                        or accounting["elapsed_seconds"] > expected_wall * 60
                        or not re.fullmatch(r"\d+:\d+", str(accounting["exit_code"]))):
                    raise NotReady("settled budget row scheduler accounting contradicts the fixed stage contract")
                parsed_stamps = []
                for stamp in (accounting["start"], accounting["end"]):
                    try:
                        parsed_stamp = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                    except ValueError as exc:
                        raise NotReady("settled budget row has an invalid timezone-qualified timestamp") from exc
                    if parsed_stamp.tzinfo is None or parsed_stamp.utcoffset() is None:
                        raise NotReady("settled budget row timestamp omits its source timezone")
                    parsed_stamps.append(parsed_stamp)
                duration = (parsed_stamps[1] - parsed_stamps[0]).total_seconds()
                if duration < 0 or abs(duration - accounting["elapsed_seconds"]) > 1:
                    raise NotReady("settled budget row timestamps do not reconcile with actual elapsed seconds")
                if row.get("job_id") not in (None, accounting["job_id"]):
                    raise NotReady("reservation and settled accounting job IDs disagree")
                amount = charged_minutes(accounting)
                if type(row.get("charged_cpu_minutes")) is not int or row["charged_cpu_minutes"] != amount:
                    raise NotReady("settled budget row charge differs from actual elapsed scheduler evidence")
                charges += amount
            if charges != value["charged_cpu_minutes"] or held != value["reserved_cpu_minutes"]:
                raise NotReady("budget ledger totals disagree with its rows")
            if charges + held > PLAN["cpu_minute_cap"]:
                raise NotReady("budget ledger exceeds the frozen task cap")
            if any(row.get("state") == "RESERVED" for row in rows):
                raise NotReady("prior submission is unsettled; preserve evidence and do not submit again")
            if value["reserved_cpu_minutes"] != 0:
                raise NotReady("budget ledger has an unbound reservation; no new submission permitted")
            self.value = value
        else:
            self.value = {"schema": "task152-live-budget/v1", "limit_cpu_minutes": 390,
                          "charged_cpu_minutes": 0, "reserved_cpu_minutes": 0, "jobs": []}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.value, sort_keys=True, indent=2) + "\n")
        os.replace(tmp, self.path)

    def collection_snapshot(self, app: Path) -> dict[str, Any]:
        """Public-contract snapshot of only this run's measured settled rows."""
        rows = []
        for job in self.value["jobs"]:
            if job.get("state") != "SETTLED":
                continue
            stage = job["stage"]
            accounting = job["accounting"]
            rows.append({"name": stage, "job_id": accounting["job_id"], "state": "settled",
                         "scheduler_state": accounting["state"],
                         "purpose": "optimization" if stage.startswith(("initial", "recovery-"))
                         else "scientific_validation",
                         "allocated_cpus": accounting["allocated_cpus"],
                         "elapsed_seconds": accounting["elapsed_seconds"],
                         "charged_cpu_minutes": job["charged_cpu_minutes"], "reserved_cpu_minutes": 0,
                         "wall_minutes": accounting["wall_minutes"], "memory_gib": accounting["memory_gib"],
                         "scheduler_accounting_raw": f"native/{stage}/sacct.raw",
                         "scheduler_submission": f"native/{stage}/sbatch.stdout.raw"})
        return {"schema": "case03-budget/v1", "limit_cpu_minutes": PLAN["study_hard_cap"],
                "charged_cpu_minutes": sum(row["charged_cpu_minutes"] for row in rows),
                "reserved_cpu_minutes": self.value["reserved_cpu_minutes"], "attempts": rows,
                "additional_billing_records": []}

    def reserve(self, stage: str, minutes: int) -> str:
        allowed = {row["stage"]: row["wall_minutes"] for row in cpu_plan()}
        if stage not in allowed or minutes != allowed[stage] or any(row.get("stage") == stage for row in self.value["jobs"]):
            raise NotReady("stage is outside the unique fixed allocation plan")
        cpum = minutes * PLAN["cores"]
        charged = self.value["charged_cpu_minutes"]
        held = self.value["reserved_cpu_minutes"]
        if charged + held + cpum > PLAN["cpu_minute_cap"] or charged + held + cpum > PLAN["study_hard_cap"]:
            raise NotReady("fixed task budget exhausted; no additional submission permitted")
        token = str(uuid.uuid4())
        self.value["reserved_cpu_minutes"] += cpum
        self.value["jobs"].append({"stage": stage, "reservation_id": token,
                                   "reserved_cpu_minutes": cpum, "state": "RESERVED"})
        self.save()
        return token

    def settle(self, token: str, accounting: dict[str, Any]) -> None:
        job = next((item for item in self.value["jobs"] if item["reservation_id"] == token), None)
        if job is None or job["state"] != "RESERVED":
            raise NotReady("reservation is missing or already settled")
        amount = charged_minutes(accounting)
        new_reserved = self.value["reserved_cpu_minutes"] - job["reserved_cpu_minutes"]
        new_charged = self.value["charged_cpu_minutes"] + amount
        job.update({"state": "SETTLED", "charged_cpu_minutes": amount,
                    "accounting": {**{k: accounting[k] for k in
                                   ("job_id", "state", "elapsed_seconds", "allocated_cpus", "start", "end", "exit_code")},
                                   "memory_gib": PLAN["memory_gib"],
                                   "wall_minutes": next(spec["wall_minutes"] for spec in cpu_plan()
                                                        if spec["stage"] == job["stage"])}})
        job["reserved_cpu_minutes"] = 0
        self.value["reserved_cpu_minutes"] = new_reserved
        self.value["charged_cpu_minutes"] = new_charged
        if new_charged + new_reserved > PLAN["study_hard_cap"]:
            self.save()
            raise NotReady("actual reconciled charge exceeds hard cap; evidence and charge were retained")
        if new_charged + new_reserved > PLAN["cpu_minute_cap"]:
            self.save()
            raise NotReady("reconciled resources exceed the fixed task allowance")
        self.save()

    def bind_job_id(self, token: str, job_id: str) -> None:
        if not re.fullmatch(r"[1-9][0-9]*", job_id):
            raise NotReady("invalid Slurm job identity")
        if any(row.get("accounting", {}).get("job_id") == job_id or row.get("job_id") == job_id
               for row in self.value["jobs"]):
            raise NotReady("Slurm returned a duplicate job ID; current hold and raw response retained")
        row = next((item for item in self.value["jobs"] if item["reservation_id"] == token), None)
        if row is None or row.get("state") != "RESERVED":
            raise NotReady("cannot bind a job ID to a missing reservation")
        row["job_id"] = job_id
        self.save()


def parse_submit_id(stdout: bytes, stderr: bytes) -> str:
    """Slurm's successful sbatch response is one unambiguous numeric ID."""
    text = stdout.decode("utf-8", "strict").strip()
    match = re.fullmatch(r"([1-9][0-9]*)(?:;[A-Za-z0-9_.-]+)?", text)
    if stderr.strip() or not match:
        raise NotReady("sbatch response is ambiguous; preserve it and stop without retry")
    return match.group(1)


def optimization_input(maxiter: int, coordinate_name: str) -> bytes:
    if maxiter < 100 or not re.fullmatch(r"[A-Za-z0-9_.-]+", coordinate_name):
        raise NotReady("invalid fixed optimizer control or coordinate basename")
    return ("! r2SCAN-3c Opt TightSCF\n%maxcore 1024\n%pal nprocs 2 end\n"
            "%geom\n  MaxIter " + str(maxiter) + "\nend\n"
            "* xyzfile 0 1 " + coordinate_name + "\n").encode("ascii")


def validation_input(kind: str) -> bytes:
    if kind == "frequency":
        return ("! r2SCAN-3c TightSCF FREQ\n%maxcore 1024\n%pal nprocs 2 end\n"
                "%freq ProjectTR true end\n* xyzfile 0 1 geometry.xyz\n").encode("ascii")
    if kind == "stability":
        return ("! r2SCAN-3c TightSCF\n%maxcore 1024\n%pal nprocs 2 end\n"
                "%scf STABPerform true STABRestartUHFifUnstable false STABNRoots 3 end\n"
                "* xyzfile 0 1 geometry.xyz\n").encode("ascii")
    raise NotReady("unknown scientific validation stage")


def batch_script(stage: str, workdir: str, orca: str, mpi_root: str, minutes: int) -> bytes:
    if stage not in {row["stage"] for row in cpu_plan()}:
        raise NotReady("unknown fixed-budget stage")
    if (not re.fullmatch(r"/[A-Za-z0-9_./-]+", workdir)
            or not re.fullmatch(r"/[A-Za-z0-9_./+-]+", orca)
            or not re.fullmatch(r"/[A-Za-z0-9_./+-]+", mpi_root)):
        raise NotReady("unsafe discovered remote path")
    if minutes not in {15, 30, 90}:
        raise NotReady("wall time is outside the fixed plan")
    return ("#!/usr/bin/env bash\n"
            f"#SBATCH --job-name=b23-152-{stage}\n"
            "#SBATCH --no-requeue\n"
            "#SBATCH --nodes=1\n"
            f"#SBATCH --ntasks={PLAN['cores']}\n#SBATCH --cpus-per-task=1\n"
            f"#SBATCH --mem={PLAN['memory_gib']}G\n"
            f"#SBATCH --time={minutes // 60:02d}:{minutes % 60:02d}:00\n"
            f"#SBATCH --chdir={workdir}\n"
            f"#SBATCH --output={workdir}/slurm.%j.stdout\n"
            f"#SBATCH --error={workdir}/slurm.%j.stderr\n"
            "set -euo pipefail\n"
            "source /etc/profile.d/modules.sh\n"
            "module load orca/6.0.1\n"
            f"ORCA_EXE={shlex.quote(orca)}\nORCA_ROOT=${{ORCA_EXE%/*}}\n"
            f"MPI_ROOT={shlex.quote(mpi_root)}\n"
            "test \"$(command -v orca)\" = \"$ORCA_EXE\"\n"
            "test \"$(command -v mpirun)\" = \"$MPI_ROOT/bin/mpirun\"\n"
            "export OMPI_MCA_btl=self,tcp OMPI_MCA_pml=ob1 OMPI_MCA_orte_base_help_aggregate=0\n"
            "export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OMP_DYNAMIC=FALSE\n"
            "exec \"$ORCA_EXE\" stage.inp > stage.out 2> stage.stderr.raw\n").encode("utf-8")


def _query_hosts(host_arg: str | None) -> str:
    aliases = configured_ssh_aliases()
    if host_arg:
        if host_arg != "ikkem" and host_arg not in aliases:
            raise NotReady("--ssh-host must name an alias present in ~/.ssh/config")
        return host_arg
    if "ikkem" in aliases:
        return "ikkem"
    if len(aliases) != 1:
        if not aliases:
            return "ikkem"
        raise NotReady("select an existing SSH config alias with --ssh-host; no SSH connection attempted")
    return aliases[0]


def _remote_discovery(transport: SSHTransport) -> tuple[dict[str, str], str, str, str]:
    code, home_out, home_err = transport.run("printf '%s\\n' \"$HOME\"", timeout=15)
    if code or not home_out.strip():
        raise NotReady("cannot discover remote home directory")
    home = home_out.decode("utf-8", "strict").strip()
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", home):
        raise NotReady("remote home is not a safe absolute path")
    discovery = transport.discover()
    executable = re.search(r"(?m)^ORCA_PATH=(.+)$", discovery["stdout"])
    mpi_root = re.search(r"(?m)^MPI_ROOT=(/[^\s]+)$", discovery["stdout"])
    if not executable or not mpi_root:
        raise NotReady("ORCA executable or reviewed MPI root was not discovered")
    return discovery, home, executable.group(1).strip(), mpi_root.group(1)


def _save_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _stage_run(transport: SSHTransport, home: str, orca: str, mpi_root: str, app: Path,
               output: Path, budget: Budget, name: str, kind: str,
               minutes: int, run_id: str, *, maxiter: int | None = None,
               geometry: Path | None = None) -> dict[str, Any]:
    """Submit one allocation after a durable hold; never retries uncertain work."""
    reservation = budget.reserve(name, minutes)
    stage_dir = output / "native" / name
    stage_dir.mkdir(parents=True, exist_ok=False)
    remote = home.rstrip("/") + "/.cache/bench23-task152/" + run_id + "/" + name
    rc, stdout, stderr = transport.run("mkdir -p " + shlex.quote(remote), timeout=30)
    if rc:
        _save_bytes(stage_dir / "transport.mkdir.stdout.raw", stdout)
        _save_bytes(stage_dir / "transport.mkdir.stderr.raw", stderr)
        raise NotReady("remote work directory creation failed; reserved budget retained")
    source_geometry = geometry or (app / "assets/1br5_candidate.xyz")
    local_geometry = stage_dir / ("1br5_candidate.xyz" if kind == "opt" and name == "initial" else "geometry.xyz")
    shutil.copyfile(source_geometry, local_geometry)
    if kind == "opt":
        content = optimization_input(maxiter or 100, local_geometry.name)
    else:
        content = validation_input(kind)
    _save_bytes(stage_dir / "stage.inp", content)
    batch = batch_script(name, remote, orca, mpi_root, minutes)
    _save_bytes(stage_dir / "batch.sh", batch)
    for path in (local_geometry, stage_dir / "stage.inp", stage_dir / "batch.sh"):
        transport.put(path, remote + "/" + path.name)
    # Use the ordinary sbatch response format verbatim; don't retry on any
    # transport error because Slurm may already have accepted the request.
    submit_code, submit_out, submit_err = transport.run(
        "cd " + shlex.quote(remote) + " && sbatch --parsable batch.sh", timeout=60)
    _save_bytes(stage_dir / "sbatch.stdout.raw", submit_out)
    _save_bytes(stage_dir / "sbatch.stderr.raw", submit_err)
    if submit_code:
        raise NotReady("sbatch returned an error/unknown result; reservation and raw response retained")
    job_id = parse_submit_id(submit_out, submit_err)
    budget.bind_job_id(reservation, job_id)
    row = _wait_and_collect(transport, remote, job_id, stage_dir, minutes)
    budget.settle(reservation, row)
    budget_snapshot = stage_dir / "collection-budget.json"
    snapshot = budget.collection_snapshot(output)
    snapshot["captured_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    _save_bytes(budget_snapshot, (json.dumps(snapshot, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    row.update({"name": name, "kind": kind, "directory": stage_dir,
                "maxiter": maxiter, "native_input": stage_dir / "stage.inp",
                "native_output": stage_dir / "stage.out",
                "geometry": local_geometry, "batch": stage_dir / "batch.sh",
                "submission": stage_dir / "sbatch.stdout.raw",
                "collection_budget_snapshot": budget_snapshot,
                "reservation_id": reservation, "memory_gib": PLAN["memory_gib"],
                "wall_minutes": minutes, "allocation_id": job_id})
    if row.get("collection_errors"):
        raise NotReady("native collection incomplete after settled allocation; no further work submitted")
    if row.get("over_wall"):
        raise NotReady("Slurm elapsed time exceeded the requested wall limit; actual charge was settled")
    if row["state"] != "COMPLETED" or row["exit_code"] != "0:0":
        raise NotReady("supported scheduler abnormal stop; evidence collected and no recovery submitted")
    return row


def _wait_and_collect(transport: SSHTransport, remote: str, job_id: str,
                      stage_dir: Path, minutes: int) -> dict[str, Any]:
    deadline = time.monotonic() + minutes * 60 + 600
    raw = b""
    while time.monotonic() < deadline:
        command = ("TZ=UTC SLURM_TIME_FORMAT=%Y-%m-%dT%H:%M:%S%z sacct -X -P -j "
                   + shlex.quote(job_id)
                   + " -o JobIDRaw,JobName,State%40,ExitCode,Start%40,End%40,ElapsedRaw,AllocCPUS,AllocTRES%100")
        code, stdout, stderr = transport.run(command, timeout=30)
        _save_bytes(stage_dir / "sacct-provenance-query.stdout.raw", stdout)
        if code:
            _save_bytes(stage_dir / "sacct-provenance-query.stderr.raw", stderr)
            time.sleep(15)
            continue
        raw = stdout
        lines = [line for line in raw.decode("utf-8", "replace").splitlines() if line]
        if len(lines) >= 2:
            try:
                record = validate_sacct(raw.decode("utf-8", "strict"), job_id, minutes, stage_dir.name)
                break
            except NotReady as exc:
                if "not a supported terminal" not in str(exc):
                    # A pending job can appear before its allocation fields are final.
                    if "exactly one allocation row" not in str(exc) and "malformed" not in str(exc):
                        raise
        time.sleep(15)
    else:
        raise NotReady("Slurm did not provide terminal allocation evidence before the bounded wait; hold retained")
    _save_bytes(stage_dir / "sacct_provenance.raw", raw)
    parsed = {k: v for k, v in record.items() if k != "raw"}
    parsed.update({"memory_gib": PLAN["memory_gib"], "wall_minutes": minutes,
                   "allocation_id": job_id, "scheduler": "slurm"})
    _save_bytes(stage_dir / "slurm-accounting.json", (json.dumps(parsed, sort_keys=True, indent=2) + "\n").encode())
    _save_bytes(stage_dir / "scheduler_record.json", (json.dumps(parsed, sort_keys=True, indent=2) + "\n").encode())
    collection_errors = []
    narrow_command = ("TZ=UTC SLURM_TIME_FORMAT=%Y-%m-%dT%H:%M:%S%z sacct -X -n -P -j "
                      + shlex.quote(job_id) + " -o JobIDRaw,State,ElapsedRaw,AllocCPUS")
    try:
        narrow_code, narrow_raw, narrow_err = transport.run(narrow_command, timeout=30)
    except (OracleError, OSError, subprocess.SubprocessError, UnicodeError) as exc:
        narrow_code, narrow_raw, narrow_err = 1, b"", str(exc).encode("utf-8", "replace")
    _save_bytes(stage_dir / "sacct.raw", narrow_raw)
    if narrow_code:
        _save_bytes(stage_dir / "sacct-query.stderr.raw", narrow_err)
        collection_errors.append("four-field sacct query failed")
    else:
        rows = [line.split("|") for line in narrow_raw.decode("utf-8", "replace").splitlines() if line]
        if (len(rows) != 1 or len(rows[0]) != 4 or rows[0][0] != job_id
                or rows[0][1].split()[0].upper() != record["state"]
                or not rows[0][2].isdigit() or int(rows[0][2]) != record["elapsed_seconds"]
                or not rows[0][3].isdigit() or int(rows[0][3]) != record["allocated_cpus"]):
            collection_errors.append("four-field raw sacct record conflicts with the full allocation record")
    for basename in ("stage.out", "stage.stderr.raw", f"slurm.{job_id}.stdout", f"slurm.{job_id}.stderr"):
        try:
            transport.get(remote + "/" + basename, stage_dir / ("stdout.raw" if basename.endswith("stdout") else
                                                                   "stderr.raw" if basename.endswith("stderr") else basename))
        except (OracleError, OSError, subprocess.SubprocessError) as exc:
            collection_errors.append(basename + ": " + str(exc))
    if stage_dir.name == "freq-validation":
        try:
            code, listing, err = transport.run(
                "find " + shlex.quote(remote) + " -maxdepth 1 -type f -name '*.hess' -printf '%f\\n'",
                timeout=20)
            names = listing.decode("utf-8", "strict").splitlines() if code == 0 else []
        except (OracleError, OSError, subprocess.SubprocessError, UnicodeError) as exc:
            code, listing, err, names = 1, b"", str(exc).encode("utf-8", "replace"), []
        if len(names) != 1 or not re.fullmatch(r"[A-Za-z0-9_.-]+\.hess", names[0]):
            _save_bytes(stage_dir / "hessian-discovery.stdout.raw", listing)
            _save_bytes(stage_dir / "hessian-discovery.stderr.raw", err)
            collection_errors.append("frequency job did not produce exactly one collectable Hessian")
        else:
            try:
                transport.get(remote + "/" + names[0], stage_dir / names[0])
            except (OracleError, OSError, subprocess.SubprocessError) as exc:
                collection_errors.append("Hessian: " + str(exc))
    parsed["collection_errors"] = collection_errors
    return parsed


def _science_module():
    path = Path(__file__).with_name("oracle_science.py")
    if path.is_symlink() or not path.is_file():
        raise NotReady("self-contained native science parser is unavailable")
    import importlib.util
    spec = importlib.util.spec_from_file_location("task152_oracle_science", path)
    if spec is None or spec.loader is None:
        raise NotReady("native science parser cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_live(app: Path, output: Path, *, ssh_host: str | None = None) -> dict[str, Path]:
    validate_public_assets(app)
    if output.is_symlink() or not output.is_dir():
        raise NotReady("output directory must exist and must not be a symlink")
    if output.resolve() != app.resolve():
        raise NotReady("candidate outputs must be written under APP so manifest paths bind correctly")
    native_root = output / "native"
    budget_path = native_root / "budget.json"
    preexisting = ("native", "result.json", "report.md", "geometry.xyz", "atom_mapping.json")
    if any((output / name).exists() or (output / name).is_symlink() for name in preexisting):
        raise NotReady("candidate output workspace is not empty; refusing rerun or overwrite")
    if any(path.is_symlink() for path in output.rglob("*")):
        raise NotReady("candidate output workspace contains a symlink")
    science = _science_module()
    host = _query_hosts(ssh_host)
    transport = SSHTransport(host)
    discovery, remote_home, orca, mpi_root = _remote_discovery(transport)
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
    native_root.mkdir(mode=0o700)
    _save_bytes(native_root / "remote-discovery.raw", discovery["stdout"].encode("utf-8"))
    if getattr(transport, "fixture_only", False) or getattr(transport, "control_flow_only", False):
        _save_bytes(native_root / "control-flow-only.json",
                    b'{"fixture_only":true,"qualification":false,"purpose":"driver control-flow test"}\n')
    budget = Budget(budget_path)
    stages: list[dict[str, Any]] = []
    geometry: Path | None = None
    final = None
    maxiters = (100, 200, 400)
    for idx, name in enumerate(("initial", "recovery-1", "recovery-2")):
        stage_geometry = None if idx == 0 else geometry
        job = _stage_run(transport, remote_home, orca, mpi_root, app, output, budget, name, "opt", 30,
                         run_id, maxiter=maxiters[idx], geometry=stage_geometry)
        parsed = science.parse_optimization(job["native_input"], job["native_output"])
        job.update(parsed)
        action = optimization_action(parsed, idx)
        if action == "stop" and parsed.get("normal_termination") is not True:
            raise NotReady("native optimization stopped abnormally; evidence retained and no retry submitted")
        if action == "validate":
            final = job
            stages.append({"name": name, "kind": "opt", "directory": job["directory"], "job": job})
            break
        if action != "recover":
            stages.append({"name": name, "kind": "opt", "directory": job["directory"], "job": job})
            if idx == 2:
                raise NotReady("three normal optimization attempts did not converge; fixed recovery allowance exhausted")
            raise NotReady("native optimizer output does not support an automatic recovery; evidence retained")
        xyz = parsed.get("final_xyz")
        if not isinstance(xyz, (str, bytes)) or not xyz:
            raise NotReady("native nonconvergence lacks final geometry; recovery is unsafe")
        geometry = job["directory"] / "opt.xyz"
        _save_bytes(geometry, xyz.encode("utf-8") if isinstance(xyz, str) else xyz)
        job["native_geometry_output"] = geometry
        stages.append({"name": name, "kind": "opt", "directory": job["directory"], "job": job})

    if final is None:
        raise NotReady("no converged final geometry; no validation jobs submitted")
    geometry = final["directory"] / "opt.xyz"
    if not geometry.is_file():
        xyz = final.get("final_xyz")
        if not isinstance(xyz, (str, bytes)) or not xyz:
            raise NotReady("converged optimization output lacks final geometry")
        _save_bytes(geometry, xyz.encode() if isinstance(xyz, str) else xyz)
    for name, kind, minutes in (("freq-validation", "frequency", 90),
                                ("stability-validation", "stability", 15)):
        job = _stage_run(transport, remote_home, orca, mpi_root, app, output, budget, name, kind,
                         minutes, run_id, geometry=geometry)
        if kind == "frequency":
            parsed = science.parse_frequency(job["native_output"], next(job["directory"].glob("*.hess")), geometry)
        else:
            parsed = science.parse_stability(job["native_output"], geometry)
        job.update(parsed)
        stages.append({"name": name, "kind": kind, "directory": job["directory"], "job": job})
    ledger = json.loads(budget_path.read_text(encoding="utf-8"))
    if getattr(transport, "fixture_only", False):
        raise NotReady("mock transport artifacts are control-flow fixtures and cannot publish a candidate")
    return science.build_candidate(app, stages, ledger, discovery=discovery, fixture_only=False)


def run_local_plan(app: Path) -> dict[str, Any]:
    validate_public_assets(app)
    return {"mode": "plan_only", "qualification": False,
            "plan": cpu_plan(), "total_cpu_minutes": sum(
                item["wall_minutes"] * PLAN["cores"] for item in cpu_plan()),
            "assets": sorted(INPUT_HASHES)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path(os.environ.get("APP", "/app")))
    parser.add_argument("--output", type=Path, default=Path(os.environ.get("OUTPUT", "/app")))
    parser.add_argument("--ssh-host", help="existing SSH config alias; defaults to ikkem")
    parser.add_argument("--plan", action="store_true", help="validate public assets and print the fixed plan; no network")
    parser.add_argument("--transport", choices=("ssh", "mock"), default="ssh")
    parser.add_argument("--fixture", type=Path, help="offline control-flow fixture; can never publish a scoreable result")
    args = parser.parse_args(argv)
    try:
        if args.plan:
            print(json.dumps(run_local_plan(args.app), indent=2, sort_keys=True))
            return 0
        validate_public_assets(args.app)
        if args.transport == "mock" or args.fixture:
            raise NotReady("fixture/control-flow transport is non-qualifying and cannot publish candidate outputs")
        result = run_live(args.app, args.output, ssh_host=args.ssh_host)
        print(json.dumps({"qualification": False,
                          "status": "candidate_artifacts_written_pending_live_qualification",
                          "files": {name: str(path) for name, path in result.items()}}, sort_keys=True))
        return 0
    except (OracleError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print("NOT_READY: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
PY

exec python3 "$WORK/live_oracle.py" --app "$APP_DIR" \
  --output "${OUTPUT:-$APP_DIR}" "$@"
