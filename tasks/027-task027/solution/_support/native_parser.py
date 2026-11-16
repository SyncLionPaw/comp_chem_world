"""Minimal self-contained Case07 ORCA parser closure copied from verify.py.

Source SHA256: 6497c71723c54f17ab51f8ad16099f970a480451445a92a2f5949881dc0ea4cc
Only raw parsing, path confinement, and geometry helpers are included; no
archive registry, scoring, reward, credentials, or execution code is included.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re

class EnvInvalid(ValueError):
    pass

def parse_engrad(path: Path) -> dict:
    """Parse the pinned 21-atom ORCA EnGrad layout used by screening."""
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    def section(marker):
        hits = [i for i, line in enumerate(lines) if line.strip() == marker]
        if len(hits) != 1:
            raise ValueError(f"ORCA engrad must contain exactly one {marker} section")
        values = []
        for line in lines[hits[0]+1:]:
            stripped = line.strip()
            if stripped.startswith("#"):
                if values: break
                continue
            if stripped: values.extend(stripped.split())
        return values
    if section("# Number of atoms") != ["21"]:
        raise ValueError("ORCA engrad must contain 21 atoms")
    energy_tokens = section("# The current total energy in Eh")
    gradient_tokens = section("# The current gradient in Eh/bohr")
    atom_rows = section("# The atomic numbers and current coordinates in Bohr")
    if len(energy_tokens) != 1 or len(gradient_tokens) != 63 or len(atom_rows) != 84:
        raise ValueError("ORCA engrad section dimensions are invalid")
    energy = float(energy_tokens[0]); gradient = [float(x) for x in gradient_tokens]
    numbers = [int(atom_rows[4*i]) for i in range(21)]
    expected = [6]*6 + [1]*4 + [8]*4 + [1, 8, 6] + [1]*4
    if numbers != expected:
        raise ValueError("ORCA engrad atom ordering is invalid")
    bohr = [float(atom_rows[4*i+j]) for i in range(21) for j in (1, 2, 3)]
    geometry = [[bohr[3*i+j]*0.529177210903 for j in range(3)] for i in range(21)]
    if any(not math.isfinite(x) for x in [energy] + gradient + bohr):
        raise ValueError("ORCA engrad contains non-finite values")
    return {"energy_au": energy, "gradient": gradient, "geometry": geometry}

class UnsupportedEvidence(Exception):
    """Evidence uses a valid but currently unsupported engine/method format."""

def safe_json(path: Path):
    if path.is_symlink() or not path.is_file():
        raise EnvInvalid(f"missing or unsafe JSON: {path}")
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise EnvInvalid(f"duplicate JSON key: {key}")
            out[key] = value
        return out
    def parse_float(raw):
        val = float(raw)
        if not math.isfinite(val):
            raise EnvInvalid("non-finite JSON number")
        return val
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                          parse_float=parse_float,
                          parse_constant=lambda x: (_ for _ in ()).throw(EnvInvalid(f"invalid JSON number {x}")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnvInvalid(f"invalid JSON {path}: {exc}") from exc

def sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise EnvInvalid(f"missing or unsafe file: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def confined(final: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("evidence path must be a nonempty relative path")
    rel = Path(relative)
    if ".." in rel.parts:
        raise ValueError("evidence path escapes final/")
    target = final / rel
    current = final
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("candidate evidence contains a symlink")
    try:
        target.resolve(strict=True).relative_to(final.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ValueError("evidence path is missing or escapes final/") from exc
    return target

def parse_xyz(path: Path) -> tuple[list[str], list[list[float]]]:
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    if len(lines) != 23 or lines[0].strip() != "21":
        raise ValueError("geometry must contain exactly 21 atoms")
    elements, coords = [], []
    for line in lines[2:]:
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("malformed XYZ coordinate row")
        elements.append(fields[0])
        try:
            xyz = [float(x) for x in fields[1:]]
        except ValueError as exc:
            raise ValueError("non-numeric XYZ coordinate") from exc
        if any(not math.isfinite(x) for x in xyz):
            raise ValueError("non-finite XYZ coordinate")
        coords.append(xyz)
    if elements != ["C"]*6 + ["H"]*4 + ["O"]*4 + ["H"] + ["O", "C"] + ["H"]*4:
        raise ValueError("XYZ atom order differs from frozen C7H9O5 mapping")
    return elements, coords

def parse_hess(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    def section(name):
        starts = [i for i, line in enumerate(lines) if line.strip() == "$" + name]
        if len(starts) != 1:
            raise ValueError(f"Hessian must contain exactly one ${name} section")
        rows, i = [], starts[0] + 1
        while i < len(lines) and not lines[i].startswith("$"):
            if lines[i].strip() and not lines[i].lstrip().startswith("#"):
                rows.append(lines[i].split())
            i += 1
        return rows
    arows = section("atoms")
    if len(arows) != 22 or arows[0] != ["21"]:
        raise ValueError("Hessian atom section must contain 21 atoms")
    elements, coords = [], []
    for row in arows[1:]:
        if len(row) != 5:
            raise ValueError("malformed Hessian atom row")
        elements.append(row[0])
        vals = [float(x) for x in row[1:]]
        if any(not math.isfinite(x) for x in vals) or vals[0] <= 0:
            raise ValueError("invalid Hessian atom mass/coordinate")
        coords.append([x * 0.529177210903 for x in vals[1:]])
    if elements != ["C"]*6 + ["H"]*4 + ["O"]*4 + ["H"] + ["O", "C"] + ["H"]*4:
        raise ValueError("Hessian atom ordering differs from frozen atom mapping")
    rows = section("hessian")
    if not rows or rows[0] != ["63"]:
        raise ValueError("Cartesian Hessian dimension must be 63")
    matrix = [[None]*63 for _ in range(63)]
    columns, cells, block_rows = [], set(), set()
    for row in rows[1:]:
        if all(re.fullmatch(r"\d+", x) for x in row):
            columns = [int(x) for x in row]
            if not columns or len(columns) != len(set(columns)) or any(x >= 63 for x in columns):
                raise ValueError("invalid Hessian column block")
            block_rows = set()
            continue
        if not columns or len(row) != len(columns) + 1:
            raise ValueError("malformed Hessian matrix row")
        rid = int(row[0])
        if rid >= 63 or rid in block_rows:
            raise ValueError("duplicate/invalid Hessian row")
        block_rows.add(rid)
        for col, raw in zip(columns, row[1:]):
            cell = (rid, col)
            if cell in cells:
                raise ValueError("duplicate Hessian matrix cell")
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError("non-finite Hessian matrix")
            matrix[rid][col] = value
            cells.add(cell)
    if len(cells) != 63*63 or any(v is None for row in matrix for v in row):
        raise ValueError("incomplete Hessian matrix")
    symmetry = max(abs(matrix[i][j]-matrix[j][i]) for i in range(63) for j in range(63))
    maximum = max(abs(v) for row in matrix for v in row)
    if symmetry > 1e-7:
        raise ValueError("Hessian is not symmetric")
    frows = section("vibrational_frequencies")
    if not frows or frows[0] != ["63"] or len(frows) != 64:
        raise ValueError("frequency section must contain 63 modes")
    freqs = {}
    for row in frows[1:]:
        if len(row) != 2:
            raise ValueError("malformed frequency row")
        idx, freq = int(row[0]), float(row[1])
        if idx in freqs or idx not in range(63) or not math.isfinite(freq):
            raise ValueError("duplicate or non-finite frequency")
        freqs[idx] = freq
    if set(freqs) != set(range(63)):
        raise ValueError("incomplete frequency indices")
    modes = section("normal_modes")
    if not modes or modes[0] != ["63", "63"]:
        raise ValueError("normal-mode matrix must be 63 by 63")
    mode_cols, mode_cells, mode_matrix = [], set(), [[None]*63 for _ in range(63)]
    mode_rows = set()
    for row in modes[1:]:
        if all(re.fullmatch(r"\d+", x) for x in row):
            mode_cols = [int(x) for x in row]
            if not mode_cols or len(mode_cols) != len(set(mode_cols)) or any(x >= 63 for x in mode_cols):
                raise ValueError("invalid normal-mode column block")
            mode_rows = set()
            continue
        if not mode_cols or len(row) != len(mode_cols)+1:
            raise ValueError("malformed normal-mode matrix row")
        rid = int(row[0])
        if rid >= 63 or rid in mode_rows:
            raise ValueError("duplicate/invalid normal-mode row")
        mode_rows.add(rid)
        for col, raw in zip(mode_cols, row[1:]):
            key = (rid, col)
            if key in mode_cells:
                raise ValueError("duplicate normal-mode matrix cell")
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError("non-finite normal-mode matrix")
            mode_matrix[rid][col] = value
            mode_cells.add(key)
    if len(mode_cells) != 63*63 or any(v is None for row in mode_matrix for v in row):
        raise ValueError("incomplete normal-mode matrix")
    physical = [freqs[i] for i in range(6, 63)]
    if maximum > 100 or any(abs(v) > 10000 for v in physical):
        raise ValueError("numerical_invalid: Hessian/frequency exceeds frozen sanity ceiling")
    return {"elements": elements, "coordinates": coords, "frequencies": freqs, "modes": mode_matrix,
            "physical_imaginary": [i for i in range(6, 63) if freqs[i] < 0],
            "max_abs_hessian": maximum, "symmetry_error": symmetry}

def stage_facts(final: Path, relative: object, *, require_opt: bool = False,
                expected_imaginary: int | None = None, registry: dict | None = None) -> dict:
    folder = confined(final, relative)
    if not folder.is_dir():
        raise ValueError("native stage path is not a directory")
    inp, out, receipt = folder/"job.inp", folder/"job.out", folder/"receipt.json"
    for path in (inp, out, receipt):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"native stage missing {path.name}")
    input_text = inp.read_text(encoding="utf-8", errors="strict")
    output_text = out.read_text(encoding="utf-8", errors="strict")
    receipt_obj = safe_json(receipt)
    if not re.search(r"ORCA", output_text, re.I):
        raise UnsupportedEvidence("native output uses an engine format not parsed by this verifier")
    method_lines = re.findall(r"(?im)^\s*!\s*(.+)$", input_text)
    if len(method_lines) != 1:
        raise ValueError("native ORCA input must contain exactly one method directive")
    method_line = method_lines[0]
    # The calibrated archive supports the PBE screening jobs and r2SCAN-3c
    # production jobs. Reject contradictory/second functional directives;
    # unknown method families remain review-only rather than being guessed.
    functionals = re.findall(r"(?i)(?<![A-Za-z0-9_-])(r2SCAN-3c|PBE|B3LYP|\w+-\w+)(?![A-Za-z0-9_-])", method_line)
    recognized = [x.lower() for x in functionals if x.lower() in {"r2scan-3c", "pbe", "b3lyp"}]
    if len(recognized) > 1 or re.search(r"(?im)^\s*%method\s+.*\b(?:functional|method|exchange|correlation|basis)\b", input_text):
        raise ValueError("native ORCA input contains a conflicting method override")
    if not recognized:
        raise UnsupportedEvidence("native method is outside the calibrated ORCA/r2SCAN-3c parser scope")
    method_family = recognized[0]
    if not re.search(r"\bUKS\b", method_line, re.I):
        raise ValueError("native ORCA input is not unrestricted for the doublet state")
    allowed_method_tokens = {"UKS", "r2SCAN-3c", "DefGrid3", "TightSCF", "VeryTightSCF",
                             "Opt", "OptTS", "TightOpt", "AnFreq", "SP", "EnGrad", "IRC",
                             "PBE", "D3BJ", "def2-SVP", "def2/J", "RI", "MOREAD"}
    method_tokens = method_line.split()
    if any(token not in allowed_method_tokens for token in method_tokens):
        if method_family == "r2scan-3c":
            raise ValueError("production input contains an unvalidated method, basis, or action override")
        raise UnsupportedEvidence("native method variant is not in the calibrated parser scope")
    if method_family == "r2scan-3c" and not {"r2SCAN-3c", "DefGrid3"}.issubset(method_tokens):
        raise ValueError("r2SCAN-3c production input must use the frozen DefGrid3 level")
    if method_family == "pbe":
        pbe_level = {"UKS", "PBE", "D3BJ", "def2-SVP", "def2/J", "RI", "DefGrid3"}
        if not pbe_level.issubset(method_tokens):
            raise UnsupportedEvidence("PBE production level is outside the calibrated PBE-D3BJ/def2-SVP/def2/J/RI/DefGrid3 profile")
        scf_tokens = {token for token in method_tokens if token in {"TightSCF", "VeryTightSCF"}}
        if len(scf_tokens) > 1:
            raise ValueError("native input has conflicting SCF convergence directives")
    if re.search(r"(?im)^\s*%basis\b", input_text):
        if method_family == "r2scan-3c":
            raise ValueError("r2SCAN-3c production input cannot override its built-in basis")
        raise UnsupportedEvidence("native custom-basis input is not in the calibrated parser scope")
    echoed = re.search(r"(?ms)^\s*INPUT FILE\s*\n[-=]+\s*\n(.*?)^\s*\|\s*\d+>\s+\*{4}END OF INPUT\*{4}", output_text)
    if not echoed:
        raise ValueError("native ORCA output lacks its echoed input block")
    echo_lines = [re.sub(r"^\s*\|\s*\d+>\s?", "", line).strip()
                  for line in echoed.group(1).splitlines()]
    if echo_lines and re.fullmatch(r"NAME\s*=\s*job\.inp", echo_lines[0], re.I):
        echo_lines.pop(0)
    input_lines = [line.strip() for line in input_text.splitlines()]
    while echo_lines and not echo_lines[-1]:
        echo_lines.pop()
    while input_lines and not input_lines[-1]:
        input_lines.pop()
    if echo_lines != input_lines:
        raise ValueError("native ORCA output input echo differs from the hashed job.inp")
    if not re.search(r"(?m)^\*\s+xyzfile\s+0\s+2\s+\S+\s*$", input_text):
        raise ValueError("native input charge/spin/geometry declaration is invalid")
    if re.search(r"SCF\s+(?:FAILED|NOT CONVERGED|DID NOT CONVERGE)", output_text, re.I):
        raise ValueError("native output reports SCF failure")
    if not re.search(r"SCF CONVERGED AFTER\s+\d+\s+CYCLES", output_text):
        raise ValueError("native output lacks a positive SCF-converged marker")
    if "ORCA TERMINATED NORMALLY" not in output_text:
        raise ValueError("native engine output did not terminate normally")
    if require_opt and "THE OPTIMIZATION HAS CONVERGED" not in output_text:
        raise ValueError("native geometry optimization did not converge")
    energy_matches = re.findall(r"FINAL SINGLE POINT ENERGY\s+([-+0-9.Ee]+)", output_text)
    if not energy_matches:
        raise ValueError("native output has no final energy")
    energy = float(energy_matches[-1])
    if not math.isfinite(energy):
        raise ValueError("non-finite native energy")
    zpe_matches = re.findall(r"Zero point energy\s+\.\.\.\s+([-+0-9.Ee]+)\s+Eh", output_text)
    zpe = float(zpe_matches[-1]) if zpe_matches else None
    if zpe is not None and not math.isfinite(zpe):
        raise ValueError("non-finite native ZPE")
    hess_path = folder/"job.hess"
    hess = None
    if expected_imaginary is not None:
        hess = parse_hess(hess_path)
        if len(hess["physical_imaginary"]) != expected_imaginary:
            raise ValueError(f"expected {expected_imaginary} physical imaginary mode(s)")
        if expected_imaginary == 1 and len(hess["physical_imaginary"]) != 1:
            raise ValueError("TS must have one physical imaginary mode")
        if not zpe_matches:
            raise ValueError("frequency output lacks an actual ZPE")
        start_xyz = folder / "start.xyz"
        if start_xyz.is_file() and not start_xyz.is_symlink():
            xyz_elements, xyz_coords = parse_xyz(start_xyz)
            if xyz_elements != hess["elements"]:
                raise ValueError("Hessian atom order differs from input geometry")
            delta = [[hess["coordinates"][i][k]-xyz_coords[i][k] for k in range(3)] for i in range(21)]
            mean = [sum(row[k] for row in delta)/21 for k in range(3)]
            aligned = max(math.sqrt(sum((row[k]-mean[k])**2 for k in range(3))) for row in delta)
            if aligned > 1e-5:
                raise ValueError("Hessian coordinates do not match frequency input geometry")
        output_matches = re.findall(r"(?m)^\s*(\d+):\s*([-+0-9.Ee]+)\s+cm\*\*-1", output_text)
        output_freqs = {}
        for raw_idx, raw_freq in output_matches:
            idx, freq = int(raw_idx), float(raw_freq)
            if idx in output_freqs or not math.isfinite(freq):
                raise ValueError("duplicate/non-finite native output frequency")
            output_freqs[idx] = freq
        if set(output_freqs) != set(range(63)):
            raise ValueError("native output must contain all 63 frequency modes")
        if any(abs(output_freqs[i]-hess["frequencies"][i]) > 0.02 for i in range(63)):
            raise ValueError("native output frequency table differs from Hessian")
        if any(abs(output_freqs[i]) > 1.0 for i in range(6)):
            raise ValueError("external modes were not projected near zero")
    for key, expected_name in (("input_sha256", inp), ("output_sha256", out)):
        recorded = receipt_obj.get(key)
        if not isinstance(recorded, str) or not re.fullmatch(r"[0-9a-f]{64}", recorded):
            raise ValueError(f"stage receipt lacks required {key}")
        if recorded != sha(expected_name):
            raise ValueError(f"stage receipt {key} does not match native bytes")
    start_xyz = folder / "start.xyz"
    if start_xyz.is_symlink() or not start_xyz.is_file():
        raise ValueError("native stage lacks its declared start.xyz geometry")
    xyz_directives = re.findall(r"(?m)^\s*\*\s+xyzfile\s+0\s+2\s+(\S+)\s*$", input_text)
    if len(xyz_directives) != 1 or xyz_directives[0] != "start.xyz":
        raise ValueError("native input must declare the receipt-bound start.xyz geometry")
    recorded_start = receipt_obj.get("start_xyz_sha256")
    # Older original native receipts predate this field; their exact start
    # geometry is still bound by the immutable input hash and Hessian coordinates.
    if recorded_start is not None and recorded_start != sha(start_xyz):
        raise ValueError("stage receipt start_xyz_sha256 does not match start.xyz")
    if not isinstance(recorded_start, str):
        receipt_rel = receipt.relative_to(final).as_posix()
        pinned_receipt = (registry or {}).get("source_files", {}).get(receipt_rel, {})
        if pinned_receipt.get("sha256") != sha(receipt):
            raise ValueError("stage receipt lacks required start_xyz_sha256 and is not evaluator-pinned original evidence")
    if receipt_obj.get("status") != "normal" or receipt_obj.get("returncode") != 0:
        raise ValueError("native execution receipt is not normal/zero exit")
    return {"energy_au": energy, "zpe_au": zpe, "hessian": hess,
            "receipt": receipt_obj, "output": output_text,
            "method_fingerprint": ("uks r2scan-3c defgrid3" if method_family == "r2scan-3c"
                                    else "uks pbe d3bj def2-svp def2/j ri defgrid3"),
            "scf_convergence": next((token for token in ("VeryTightSCF", "TightSCF")
                                     if token in method_tokens), "unspecified")}

def aligned_max_difference(first: list[list[float]], second: list[list[float]]) -> float:
    if len(first) != len(second) or not first:
        raise ValueError("geometry atom count differs")
    delta = [[second[i][k]-first[i][k] for k in range(3)] for i in range(len(first))]
    mean = [sum(row[k] for row in delta)/len(delta) for k in range(3)]
    return max(math.sqrt(sum((row[k]-mean[k])**2 for k in range(3))) for row in delta)

def bond_graph(elements: list[str], coords: list[list[float]]) -> set[tuple[int, int]]:
    """Map a frozen Case07 geometry to the scorer's covalent graph."""
    radii = {"C": 0.76, "H": 0.31, "O": 0.66}
    return {(i, j) for i in range(len(elements)) for j in range(i + 1, len(elements))
            if math.dist(coords[i], coords[j]) < 1.20 * (radii[elements[i]] + radii[elements[j]])}
