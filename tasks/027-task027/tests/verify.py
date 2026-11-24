#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Toluene ipso-BPR: dual-channel screening and saddle-point validation.
"""Conservative Case07 scorer. Archive authority is pinned by verifier code."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

# Evaluator-only parsing/review helpers; never copied into the image.
sys.path.insert(0, str(Path(__file__).resolve().parent / "_support"))
import csv
from datetime import datetime, timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import fresh_evidence
import fresh_native
import candidate_execution
import case07_review
from types import SimpleNamespace

CASE_ID = "case-07-independent-saddle-point-recomputation"
P04_CASE07_STANDARD_ARTIFACTS = (
    "ts_search_report.json", "barriers.csv", "native_outputs", "failures.md", "resource_usage.csv")
P04_CASE07_HOST_SOURCE_FILES = (
    "src/compchembench/eval.py", "src/compchembench/container.py",
    "src/compchembench/p04_standard_attempt.py", "src/compchembench/p04_case07_standard_adapter.py",
    "src/compchembench/p04_host_receipts.py", "src/compchembench/p04_case07_lifecycle.py",
    "src/compchembench/p04_case07_network.py", "src/compchembench/p04_case07_broker.py",
    "src/compchembench/p04_case07_backend.py", "src/compchembench/p04_case08_backend.py",
    "src/compchembench/case08_budget.py", "src/compchembench/p04_runtime_watchdog.py",
    "src/compchembench/p04_case07_qualification.py",
    "src/compchembench/p04_case07_operator_qualification.py",
    "src/compchembench/p04_case07_stage_b_operator.py",
    "src/compchembench/p04_case07_stage_b_entry.py")
P04_CASE07_BENCH_SOURCE_FILES = (
    "packages/case-07-independent-saddle-point-recomputation/task.toml",
    "packages/case-07-independent-saddle-point-recomputation/instruction.md",
    "packages/case-07-independent-saddle-point-recomputation/environment/Dockerfile",
    "packages/case-07-independent-saddle-point-recomputation/environment/ccb_hpc_rpc.py",
    "packages/case-07-independent-saddle-point-recomputation/tests/test.sh",
    "packages/case-07-independent-saddle-point-recomputation/tests/verify.py",
    "runtimes/hpc/case07/ordinary-profile.json", "runtimes/hpc/case07/policy.json",
    "runtimes/hpc/case07/runtime_bootstrap.py", "runtimes/hpc/case07/reference_campaign.py",
    "runtimes/hpc/case07/reference_driver.py", "runtimes/hpc/case07/node_adapter.py",
    "runtimes/hpc/case07/ordinary_node_worker.py", "runtimes/hpc/case07/ordinary_submission_script.py",
    "runtimes/hpc/case07/ordinary_transport.py", "runtimes/hpc/case07/ordinary_admission.py",
    "runtimes/hpc/case07/queue_certificate.py", "runtimes/hpc/case07/storage_guard.py",
    "runtimes/hpc/case07/typed_request.py", "runtimes/hpc/case07/submission_script.py",
    "runtimes/hpc/case07/trusted_executor.py", "runtimes/hpc/case07/production_launch.py",
    "runtimes/hpc/case07/native_parser.py", "runtimes/hpc/case07/writer_inventory.json",
    "runtimes/hpc/case07/typed-request.schema.json", "runtimes/hpc/case07/tools/mpi-smoke",
    "runtimes/hpc/case07/tools/loopback-smoke",
    "runtimes/hpc/case07/tools/diagnostic-toolchain.json", "runtimes/hpc/case07/tools/mpi-smoke.c",
    "runtimes/hpc/case07/tools/loopback-smoke.c",
    "runtimes/hpc/case07/rpc-qualification/remote/inside-probe.sh",
    "runtimes/hpc/case07/rpc-qualification/remote/mount-audit.py",
    "runtimes/hpc/case07/rpc-qualification/remote/mount-audit.sh",
    "runtimes/hpc/case07/rpc-qualification/remote/mpi-smoke.c",
    "runtimes/hpc/case07/rpc-qualification/remote/loopback-smoke.c",
    "runtimes/hpc/case07/rpc-qualification/remote/rpc-probe-input.txt",
    "runtimes/hpc/case07/rpc-qualification/remote/process-tree.py",
    "runtimes/hpc/case07/qualification/MANIFEST.json",
    "runtimes/hpc/case07/qualification/pilot_request.py")
CHECKS = [
    ("report_and_outputs_present", "L1"),
    ("native_outputs_internally_consistent", "L2"),
    ("saddle_connects_the_claimed_pair", "L3"),
    ("budgeted_scientific_decisions", "L3"),
    ("reference_comparison_and_uncertainty", "L3"),
    ("new_run_provenance", "L3"),
    ("resource_envelope_respected", "L2"),
]
REGISTRY_SHA256 = "de74ecba0d0461f1ccf99befa277d11043013b42094c61b7259668ff828de731"
REFS_SHA256 = "06a116ca06310407c970f4eda3db01f033268c8b1d4cc32634af6bea461d7a71"
FROZEN_PRODUCT_SOURCE_INDEX = {
    # Evaluator-pinned reactant-order -> public product-row mapping, transcribed
    # from the canonical 2.0 C1/C2 atom-mapping tables. Values are 1-based.
    "bpr": list(range(1, 22)),
    "C1": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 20, 12, 13, 21, 14, 16, 17, 18, 19, 15],
    "C2": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 11, 12, 13, 21, 14, 15, 16, 17, 18, 19],
}


class EnvInvalid(Exception):
    pass


class CriterionFailure(ValueError):
    def __init__(self, criterion: str, message: str):
        super().__init__(message)
        self.criterion = criterion


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


def parse_datetime(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def checked_tree(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise EnvInvalid("candidate final directory is missing or redirected")
    found = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise EnvInvalid(f"symlink in final/: {path.relative_to(root)}")
        if path.is_file():
            found[path.relative_to(root).as_posix()] = sha(path)
    return found


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


FROZEN_ELEMENTS = ["C"]*6 + ["H"]*4 + ["O"]*4 + ["H"] + ["O", "C"] + ["H"]*4


def parse_screen_cycles(text: str) -> list[dict]:
    starts = list(re.finditer(r"GEOMETRY OPTIMIZATION CYCLE\s+(\d+)", text))
    coord_re = re.compile(r"CARTESIAN COORDINATES \(ANGSTROE?M\)")
    energy_re = re.compile(r"FINAL SINGLE POINT ENERGY\s+([-+0-9.Ee]+)")
    grad_re = re.compile(r"CARTESIAN GRADIENT\s*[-\s]*\n")
    row_re = re.compile(r"^\s*(\d+)\s+([A-Z][a-z]?)\s*:\s*([-+0-9.Ee]+)\s+([-+0-9.Ee]+)\s+([-+0-9.Ee]+)\s*$")
    records = []
    for i, marker in enumerate(starts):
        end = starts[i+1].start() if i+1 < len(starts) else len(text)
        block = text[marker.start():end]
        coord, em, grad = coord_re.search(block), energy_re.search(block), grad_re.search(block)
        if not coord or not em or not grad:
            continue
        symbols, xyz = [], []
        for line in block[coord.end():].splitlines()[1:]:
            tokens = line.split()
            if len(tokens) == 4 and tokens[0] in {"C", "H", "O"}:
                try: row = [float(x) for x in tokens[1:]]
                except ValueError: break
                if not all(math.isfinite(x) for x in row): break
                symbols.append(tokens[0]); xyz.append(row)
                if len(xyz) == 21: break
            elif xyz:
                break
        try: energy = float(em.group(1))
        except ValueError: continue
        if symbols != FROZEN_ELEMENTS or len(xyz) != 21 or not math.isfinite(energy):
            continue
        indices, grad_symbols, gradient = [], [], []
        for line in block[grad.end():].splitlines():
            match = row_re.match(line)
            if not match:
                if indices: break
                continue
            indices.append(int(match.group(1))); grad_symbols.append(match.group(2))
            vals = [float(match.group(k)) for k in (3, 4, 5)]
            if not all(math.isfinite(x) for x in vals): break
            gradient.extend(vals)
            if len(indices) == 21: break
        scf = re.search(r"SCF CONVERGED AFTER\s+\d+\s+CYCLES", block)
        failed = re.search(r"SCF (?:NOT CONVERGED|DID NOT CONVERGE|FAILED)", block, re.I)
        offsets = [marker.start()+coord.start(), marker.start()+(scf.start() if scf else 10**20),
                   marker.start()+em.start(), marker.start()+grad.start()]
        if (indices != list(range(1, 22)) or grad_symbols != FROZEN_ELEMENTS or len(gradient) != 63
                or not scf or failed or not offsets[0] < offsets[1] < offsets[2] < offsets[3]):
            continue
        coords_text = "\n".join(" ".join([sym]+[format(x, ".12f") for x in row])
                                for sym, row in zip(symbols, xyz)) + "\n"
        records.append({"cycle_number": int(marker.group(1)), "energy_au": energy,
                        "geometry_sha256": hashlib.sha256(coords_text.encode()).hexdigest(),
                        "gradient_component_count": len(gradient), "gradient": gradient, "coordinates": xyz,
                        "output_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "offsets": offsets})
    return records


def audit_screening(final: Path, report: dict) -> dict:
    results = {}
    for channel in ("C1", "C2"):
        entries = report["channels"][channel]["screening"]
        successful = []
        for entry in entries:
            inp = confined(final, entry.get("native_input"))
            out = confined(final, entry.get("native_output"))
            rec = confined(final, entry.get("receipt_path"))
            geometry = confined(final, entry.get("geometry_path"))
            parse_xyz(geometry)
            receipt = safe_json(rec)
            if receipt.get("input_sha256") != sha(inp) or receipt.get("output_sha256") != sha(out):
                raise ValueError(f"{channel} screening receipt does not bind native input/output")
            if receipt.get("status") not in {"normal", "timeout", "failed"}:
                raise ValueError(f"{channel} screening receipt has unsupported execution status")
            cycles = parse_screen_cycles(out.read_text(encoding="utf-8", errors="strict"))
            wanted = entry.get("cycle_number")
            matches = [cycle for cycle in cycles if cycle["cycle_number"] == wanted]
            if not matches:
                raise ValueError(f"{channel} screening point lacks its claimed complete SCF/energy/gradient cycle")
            cycle = matches[-1]
            if entry.get("cycle_geometry_sha256") != cycle["geometry_sha256"]:
                raise ValueError(f"{channel} evaluation geometry hash differs from selected native cycle")
            if entry.get("native_output_sha256") != cycle["output_sha256"]:
                raise ValueError(f"{channel} screening output hash differs from selected native output")
            if receipt.get("energy_au") is not None and abs(float(receipt["energy_au"])-cycle["energy_au"]) > 1e-5:
                raise ValueError(f"{channel} receipt energy is not paired to selected complete cycle")
            successful.append(cycle)
        if len(successful) < 3:
            raise ValueError(f"{channel} needs at least three actual successful energy/gradient cycles")
        if len({p["geometry_sha256"] for p in successful}) < 3:
            raise ValueError(f"{channel} screening geometries are not distinct")
        results[channel] = {"successful_evaluations": len(successful),
                            "distinct_geometry_hashes": len({p["geometry_sha256"] for p in successful})}
    return results


def audit_native(final: Path, report: dict, registry: dict) -> dict:
    actual = checked_tree(final)
    native_manifest = safe_json(final / "native_outputs/manifest.json")
    if native_manifest.get("schema") != "case07-native-manifest/v1" or not isinstance(native_manifest.get("files"), dict):
        raise ValueError("native outputs manifest is malformed")
    observed_native = {name: digest for name, digest in actual.items()
                       if name.startswith("native_outputs/") and name != "native_outputs/manifest.json"}
    if native_manifest["files"] != {name: "sha256:" + digest for name, digest in observed_native.items()}:
        raise ValueError("native outputs manifest does not match native evidence bytes")
    channel_status = {name: item.get("status") for name, item in report["channels"].items()}
    if channel_status.get("C2") == "validated":
        raise UnsupportedEvidence("C2 native validation is outside the calibrated archive parser scope")
    if channel_status.get("C1") != "validated":
        raise ValueError("the calibrated native route requires a validated C1 channel")
    c1 = report["channels"]["C1"]["validation"]
    facts = {}
    facts["ts_opt"] = stage_facts(final, c1.get("ts_opt"), require_opt=True, registry=registry)
    facts["ts_freq"] = stage_facts(final, c1.get("ts_freq"), expected_imaginary=1, registry=registry)
    facts["minus_opt"] = stage_facts(final, c1.get("minus_opt"), require_opt=True, registry=registry)
    facts["minus_freq"] = stage_facts(final, c1.get("minus_freq"), expected_imaginary=0, registry=registry)
    plus_chain = c1.get("plus_opt_chain")
    if not isinstance(plus_chain, list) or not plus_chain:
        raise ValueError("C1 product-side restart and final optimization chain are required")
    if len(plus_chain) == 1:
        raise UnsupportedEvidence("single-stage product optimization routes are not calibrated by this archive scorer")
    restart_opt = confined(final, plus_chain[0])
    if "THE OPTIMIZATION HAS CONVERGED" in (restart_opt / "job.out").read_text(errors="strict"):
        # A chain may contain a converged parent; this report's designated cycle34 source may not.
        pass
    facts["plus_opt"] = stage_facts(final, plus_chain[-1], require_opt=True, registry=registry)
    facts["plus_freq"] = stage_facts(final, c1.get("plus_freq"), expected_imaginary=0, registry=registry)
    fingerprints = {item["method_fingerprint"] for item in facts.values()}
    if len(fingerprints) != 1:
        raise CriterionFailure("native_outputs_internally_consistent", "production stationary stages use mixed electronic-structure levels")
    native_level = next(iter(fingerprints))
    declared_level = " ".join(str(report.get("final_level", "")).strip().lower().split())
    display_levels = {"uks r2scan-3c defgrid3": "uks r2scan-3c defgrid3",
                      "uks pbe d3bj def2-svp def2/j ri defgrid3":
                          "uks pbe d3bj def2-svp def2/j ri defgrid3"}
    if (native_level not in display_levels
            or frozenset(re.findall(r"def2/j|[a-z0-9-]+", declared_level))
            != frozenset(re.findall(r"def2/j|[a-z0-9-]+", display_levels.get(native_level, "")))):
        raise ValueError("report final_level does not match the native production method fingerprint")
    # Bind the TS Hessian to the actual converged TS geometry.
    ts_opt_dir = confined(final, c1["ts_opt"])
    _, ts_final_coords = parse_xyz(ts_opt_dir / "job.xyz")
    _, ts_freq_start = parse_xyz(confined(final, c1["ts_freq"]) / "start.xyz")
    if aligned_max_difference(ts_final_coords, ts_freq_start) > 1e-5:
        raise CriterionFailure("saddle_connects_the_claimed_pair", "TS frequency geometry differs from optimized TS")
    # Bind each fresh endpoint frequency Hessian to its optimization geometry.
    for opt_rel, freq_rel, label in ((c1["minus_opt"], c1["minus_freq"], "minus"),
                                     (plus_chain[-1], c1["plus_freq"], "plus")):
        opt_xyz = confined(final, opt_rel) / "job.xyz"
        freq_xyz = confined(final, freq_rel) / "start.xyz"
        _, opt_coords = parse_xyz(opt_xyz)
        _, freq_coords = parse_xyz(freq_xyz)
        if aligned_max_difference(opt_coords, freq_coords) > 1e-5:
            raise ValueError(f"{label} frequency input geometry differs from converged optimization")

    # Reconstruct both signed seeds from the actual TS Hessian's physical mode.
    seed_minus = confined(final, c1.get("signed_mode_seed_minus"))
    seed_plus = confined(final, c1.get("seed_plus"))
    disp_path = seed_plus.parent / "displacement.json"
    displacement = safe_json(disp_path)
    ts_hess_path = confined(final, c1["ts_freq"]) / "job.hess"
    ts_hess = facts["ts_freq"]["hessian"]
    mode_id = ts_hess["physical_imaginary"][0]
    if (displacement.get("mode_index") != mode_id
            or displacement.get("hess_sha256") != sha(ts_hess_path)
            or not math.isclose(float(displacement.get("frequency_cm1")), ts_hess["frequencies"][mode_id], abs_tol=0.02)):
        raise ValueError("signed-mode displacement metadata does not bind the native TS Hessian")
    vector = [[ts_hess["modes"][3*i+k][mode_id] for k in range(3)] for i in range(21)]
    mode_norm = max(math.sqrt(sum(v*v for v in row)) for row in vector)
    if mode_norm <= 0:
        raise ValueError("TS imaginary mode has zero displacement")
    reconstructed_seeds = []
    for sign in (-1, 1):
        reconstructed_seeds.append([[xyz[k] + sign*0.12*vec[k]/mode_norm for k in range(3)]
                                    for xyz, vec in zip(ts_hess["coordinates"], vector)])
    actual_seed_coords = []
    for seed_path, label in ((seed_minus, "minus"), (seed_plus, "plus")):
        actual_elements, actual = parse_xyz(seed_path)
        if actual_elements != ts_hess["elements"]:
            raise CriterionFailure("saddle_connects_the_claimed_pair", "signed seed atom ordering differs from TS Hessian")
        if min(aligned_max_difference(actual, candidate) for candidate in reconstructed_seeds) > 1e-5:
            raise CriterionFailure("saddle_connects_the_claimed_pair",
                                   f"{label} seed does not reconstruct from either phase of the actual TS mode")
        actual_seed_coords.append(actual)
    if aligned_max_difference(actual_seed_coords[0], actual_seed_coords[1]) < 1e-4:
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "signed mode seeds are duplicated instead of opposite displacements")
    minus_start = parse_xyz(confined(final, c1["minus_opt"]) / "start.xyz")[1]
    plus_initial_start = parse_xyz(confined(final, plus_chain[0]) / "start.xyz")[1]
    if aligned_max_difference(parse_xyz(seed_minus)[1], minus_start) > 1e-5:
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "signed minus mode seed does not match the minus optimization start")
    if aligned_max_difference(parse_xyz(seed_plus)[1], plus_initial_start) > 1e-5:
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "signed plus mode seed does not match the first plus optimization start")

    # Verify the defining bond changes directly from the two endpoint Hessian geometries.
    minus_coords = facts["minus_freq"]["hessian"]["coordinates"]
    plus_coords = facts["plus_freq"]["hessian"]["coordinates"]
    def close(coords, i, j, threshold):
        return math.dist(coords[i], coords[j]) < threshold
    expected_bpr = [close(minus_coords, 0, 5, 1.9), close(minus_coords, 10, 11, 1.9),
                    close(minus_coords, 13, 14, 1.25), close(minus_coords, 11, 14, 1.25)]
    expected_product = [close(plus_coords, 0, 5, 1.9), close(plus_coords, 10, 11, 1.9),
                        close(plus_coords, 13, 14, 1.25), close(plus_coords, 11, 14, 1.25)]
    if expected_bpr != [True, True, True, False]:
        raise CriterionFailure("saddle_connects_the_claimed_pair", "minus endpoint graph does not match BPR role")
    if expected_product != [False, False, False, True]:
        raise CriterionFailure("saddle_connects_the_claimed_pair", "plus endpoint graph does not match C1 product role")
    coordinate_roles = report["channels"]["C1"].get("coordinates", {})
    bpr_path = confined(final, coordinate_roles.get("bpr"))
    product_path = confined(final, coordinate_roles.get("product"))
    bpr_elements, bpr_coords = parse_xyz(bpr_path)
    product_elements, product_coords = parse_xyz(product_path)
    if bpr_elements != FROZEN_ELEMENTS or product_elements != FROZEN_ELEMENTS:
        raise ValueError("endpoint coordinate atom mapping is invalid")
    bpr_signature = [math.dist(bpr_coords[0], bpr_coords[5]) < 1.9,
                     math.dist(bpr_coords[10], bpr_coords[11]) < 1.9,
                     math.dist(bpr_coords[13], bpr_coords[14]) < 1.25,
                     math.dist(bpr_coords[11], bpr_coords[14]) < 1.25]
    minus_signature = [math.dist(minus_coords[0], minus_coords[5]) < 1.9,
                       math.dist(minus_coords[10], minus_coords[11]) < 1.9,
                       math.dist(minus_coords[13], minus_coords[14]) < 1.25,
                       math.dist(minus_coords[11], minus_coords[14]) < 1.25]
    if bpr_signature != [True, True, True, False] or minus_signature != bpr_signature:
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "minus frequency endpoint does not match the reported BPR graph role")
    if aligned_max_difference(bpr_coords, minus_coords) > 1e-5:
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "reported BPR coordinates do not match the native minus endpoint")
    if aligned_max_difference(product_coords, plus_coords) > 1e-5:
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "plus frequency endpoint does not match the reported C1 product geometry")
    graph_reference_paths = ("structures/BPR_reference.xyz", "structures/C1_product_reference.xyz")
    for relative in graph_reference_paths:
        pinned = registry.get("fixture_manifest", {}).get(relative)
        if not isinstance(pinned, str) or sha(confined(final, relative)) != pinned:
            raise ValueError(f"full graph reference differs from evaluator-pinned source: {relative}")
    bpr_ref_e, bpr_ref_c = parse_xyz(confined(final, graph_reference_paths[0]))
    product_ref_e, product_ref_c = parse_xyz(confined(final, graph_reference_paths[1]))
    if any(e != FROZEN_ELEMENTS for e in (bpr_elements, product_elements, bpr_ref_e, product_ref_e)):
        raise ValueError("full graph comparison requires the frozen 21-atom order")
    bpr_edges = bond_graph(bpr_ref_e, bpr_ref_c)
    product_edges = bond_graph(product_ref_e, product_ref_c)
    if bond_graph(bpr_elements, bpr_coords) != bpr_edges:
        raise CriterionFailure("saddle_connects_the_claimed_pair", "reported BPR full graph differs from the pinned reactant reference")
    if bond_graph(FROZEN_ELEMENTS, minus_coords) != bpr_edges:
        raise CriterionFailure("saddle_connects_the_claimed_pair", "native minus endpoint full graph differs from BPR")
    if bond_graph(FROZEN_ELEMENTS, plus_coords) != product_edges:
        raise CriterionFailure("saddle_connects_the_claimed_pair", "native plus endpoint full graph differs from C1 product")
    if bpr_edges-product_edges != {(0, 5), (10, 11), (13, 14)} or product_edges-bpr_edges != {(11, 14)}:
        raise CriterionFailure("saddle_connects_the_claimed_pair", "mapped full graph changes are not the canonical C1 bond rearrangement")
    for item in report["channels"].values():
        if item["channel"] == "C1" and item.get("status") != "validated":
            raise ValueError("C1 local path must be explicitly validated to satisfy the output contract")
    scope = report.get("scope", {})
    restart = report.get("restart_source")
    if not isinstance(restart, dict) or restart.get("cycle_number") != 34 or restart.get("gradient_component_count") != 63:
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "product-side restart must cite fully evaluated cycle 34")
    output_path = confined(final, restart.get("output_path"))
    if restart.get("trial_geometry_role") != "uncompleted cycle-35 trial, not used":
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "uncompleted cycle-35 trial must be excluded")
    cycle_eval = safe_json(confined(final, restart.get("path")))
    record = cycle_eval.get("record", cycle_eval)
    reparsed = safe_json(confined(final, restart.get("reparsed_path")))
    if record.get("cycle_number") != 34 or record.get("gradient_component_count") != 63:
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "cycle34 source lacks a complete 63-component gradient")
    if record.get("output_sha256") != sha(output_path):
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "cycle34 evidence is not bound to its native output")
    restart_stage = output_path.parent
    restart_receipt = safe_json(restart_stage / "receipt.json")
    if (restart_receipt.get("output_sha256") != sha(output_path)
            or restart_receipt.get("input_sha256") != sha(restart_stage / "job.inp")):
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "cycle34 native output is not bound to its stage receipt")
    parsed_cycles = [r for r in parse_screen_cycles(output_path.read_text(encoding="utf-8"))
                     if r["cycle_number"] == 34]
    if len(parsed_cycles) != 1:
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "cycle34 raw output lacks one complete SCF/energy/gradient evaluation")
    actual_cycle = parsed_cycles[0]
    if (reparsed.get("output_sha256") != sha(output_path)
            or reparsed.get("geometry_sha256") != actual_cycle["geometry_sha256"]
            or reparsed.get("energy_au") != actual_cycle["energy_au"]
            or reparsed.get("gradient_au_per_bohr") != actual_cycle["gradient"]
            or len(reparsed.get("gradient_au_per_bohr", [])) != 63
            or record.get("geometry_sha256") != actual_cycle["geometry_sha256"]
            or record.get("energy_au") != actual_cycle["energy_au"]
            or record.get("coordinates_angstrom") != actual_cycle["coordinates"]):
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "cycle34 saved geometry/energy/gradient differs from a fresh raw-output reparse")
    plus_start = parse_xyz(confined(final, restart.get("start_geometry_path")))[1]
    if aligned_max_difference(actual_cycle["coordinates"], plus_start) > 1e-5:
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "last plus optimization start differs from the fully evaluated cycle34 geometry")
    if aligned_max_difference(actual_cycle["coordinates"], parse_xyz(confined(final, plus_chain[-1]) / "start.xyz")[1]) > 1e-5:
        raise CriterionFailure("saddle_connects_the_claimed_pair",
                               "final plus optimization restart differs from the complete cycle34 geometry")
    trial_path = confined(final, restart.get("trial_geometry_path"))
    if not trial_path.is_file():
        raise CriterionFailure("saddle_connects_the_claimed_pair", "cycle35 trial geometry evidence is missing")
    with confined(final, "barriers.csv").open(newline="", encoding="utf-8") as stream:
        barriers = list(csv.DictReader(stream))
    c1bar = [r for r in barriers if r.get("channel") == "C1"]
    if len(c1bar) != 1:
        raise ValueError("barriers.csv must contain one C1 forward barrier row")
    if c1bar[0].get("status") != "validated":
        raise ValueError("C1 barrier row must identify the validated channel")
    barrier_level = " ".join(str(c1bar[0].get("level", "")).strip().lower().split())
    if (frozenset(re.findall(r"def2/j|[a-z0-9-]+", barrier_level))
            != frozenset(re.findall(r"def2/j|[a-z0-9-]+", native_level))):
        raise ValueError("C1 barrier level does not match the six native production stages")
    expected_native_sources = {
        "reactant_output": f"{c1['minus_freq']}/job.out",
        "ts_output": f"{c1['ts_freq']}/job.out",
    }
    for field, expected_path in expected_native_sources.items():
        if c1bar[0].get(field) != expected_path:
            raise CriterionFailure("native_outputs_internally_consistent",
                                   f"C1 {field} does not identify the validated native frequency output")
    for field, native_value in (
        ("e_reactant_au", facts["minus_freq"]["energy_au"]),
        ("e_ts_au", facts["ts_freq"]["energy_au"]),
        ("zpe_reactant_au", facts["minus_freq"]["zpe_au"]),
        ("zpe_ts_au", facts["ts_freq"]["zpe_au"]),
    ):
        try:
            candidate_value = float(c1bar[0][field])
        except (ValueError, TypeError, KeyError) as exc:
            raise CriterionFailure("native_outputs_internally_consistent",
                                   f"C1 {field} is missing or malformed") from exc
        if not math.isfinite(candidate_value) or native_value is None or abs(candidate_value-native_value) > 1e-6:
            raise CriterionFailure("native_outputs_internally_consistent",
                                   f"C1 {field} does not match its native frequency output")
    factor = 627.5094740631
    fwd = ((facts["ts_freq"]["energy_au"] + facts["ts_freq"]["zpe_au"])
           - (facts["minus_freq"]["energy_au"] + facts["minus_freq"]["zpe_au"])) * factor
    declared = float(c1bar[0]["dft_zpe_barrier_kcal_per_mol"])
    if not math.isfinite(declared) or abs(fwd-declared) > 0.05:
        raise ValueError("C1 same-level E+ZPE forward barrier does not reproduce from native outputs")
    return {"stages": facts, "forward_barrier": fwd}


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


def audit_resources(final: Path, registry: dict) -> tuple[str, str, dict]:
    path = confined(final, "resource_usage.csv")
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return "FAIL", "resource ledger has no allocation rows", {}
    ids = [row.get("job_id", "").strip() for row in rows]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        return "FAIL", "resource ledger has missing or duplicate job IDs", {}
    sources = registry.get("allocation_rows", [])
    expected_ids = {r.get("job_id") for r in sources}
    if set(ids) != expected_ids:
        # Resource IDs in candidate CSV are not the only archive identity.
        # If the candidate still carries evaluator-pinned raw Slurm outputs,
        # relabeling every row cannot turn that same failed archive into a
        # fresh run with unverified job IDs.
        pinned_hashes = {row.get("sacct_sha256") for row in sources if row.get("sacct_sha256")}
        registered_sacct = {path: item.get("sha256", "").removeprefix("sha256:")
                            for path, item in registry.get("source_files", {}).items()
                            if item.get("sha256", "").removeprefix("sha256:") in pinned_hashes}
        archive_sacct_present = False
        for relative, expected_sha in registered_sacct.items():
            try:
                if sha(confined(final, relative)) == expected_sha:
                    archive_sacct_present = True
                    break
            except (ValueError, EnvInvalid):
                continue
        if set(ids) & expected_ids or archive_sacct_present:
            return "FAIL", "resource ledger omits evaluator-pinned historical allocations still present in native evidence", {}
        try:
            cores = [int(row["allocated_cores"]) for row in rows]
            hours = [float(row["allocated_core_hours"]) for row in rows]
            mem = [None if not row.get("peak_memory_gib", "").strip()
                   else float(row["peak_memory_gib"]) for row in rows]
            scratch = [None if not row.get("scratch_gib", "").strip()
                       else float(row["scratch_gib"]) for row in rows]
            if any(c <= 0 for c in cores):
                return "FAIL", "unrecognized allocation has invalid allocated-core accounting", {}
            if any(not math.isfinite(h) or h < 0 for h in hours):
                return "FAIL", "unrecognized allocation has invalid core-hour accounting", {}
            if any(x is not None and (not math.isfinite(x) or x < 0) for x in mem):
                return "FAIL", "unrecognized allocation has invalid peak-memory measurement", {}
            if any(x is not None and (not math.isfinite(x) or x < 0) for x in scratch):
                return "FAIL", "unrecognized allocation has invalid scratch measurement", {}
            starts = [parse_datetime(r.get("raw_site_start") or r["start_utc"]) for r in rows]
            ends = [parse_datetime(r.get("raw_site_end") or r["end_utc"]) for r in rows]
            if any(end < start for start, end in zip(starts, ends)):
                return "FAIL", "unrecognized allocation has a negative interval", {}
            if any(abs(h - c * (end-start).total_seconds()/3600) > 0.05
                   for c, h, start, end in zip(cores, hours, starts, ends)):
                return "FAIL", "unrecognized allocation core-hours disagree with cores × elapsed", {}
            if max(ends) - min(starts) > timedelta(hours=8):
                return "FAIL", "unrecognized allocation activity window exceeds eight hours with no queue exclusion proof", {}
            concurrent_cores = 0
            for start, end in zip(starts, ends):
                concurrent_cores = max(concurrent_cores,
                    sum(cores[i] for i in range(len(rows)) if starts[i] < end and ends[i] > start))
        except (ValueError, TypeError, KeyError, OverflowError):
            return "FAIL", "unrecognized resource ledger is malformed", {}
        return "REVIEW_REQUIRED", "resource job IDs are not authenticated by the archive registry", {}
    by_id = {row["job_id"].strip(): row for row in rows}
    intervals, unknown_mem, unknown_scratch = [], False, False
    corehours, allocation_seconds = 0.0, 0
    failures = []
    try:
        for source in sources:
            row = by_id[source["job_id"]]
            raw_start = parse_datetime(row["raw_site_start"])
            raw_end = parse_datetime(row["raw_site_end"])
            start = raw_start
            end = raw_end
            seconds = int((end-start).total_seconds())
            cores = int(row["allocated_cores"])
            hours = float(row["allocated_core_hours"])
            if seconds != int(source["elapsed_seconds"]) or cores != int(source["allocated_cores"]):
                failures.append(f"allocation {source['job_id']} interval/core count differs from pinned Slurm evidence")
            if row.get("raw_site_start") != source.get("raw_site_start") or row.get("raw_site_end") != source.get("raw_site_end"):
                failures.append(f"allocation {source['job_id']} raw site start/end differs from pinned Slurm evidence")
            if source.get("start_utc") is None or source.get("end_utc") is None:
                if row.get("start_utc", "").strip() or row.get("end_utc", "").strip() or row.get("utc_receipt_path", "").strip():
                    failures.append(f"allocation {source['job_id']} asserts UTC timestamps without per-job UTC evidence")
            elif (row.get("start_utc") != source["start_utc"] or row.get("end_utc") != source["end_utc"]
                  or parse_datetime(row["start_utc"]) != parse_datetime(source["start_utc"])
                  or parse_datetime(row["end_utc"]) != parse_datetime(source["end_utc"])):
                failures.append(f"allocation {source['job_id']} UTC start/end differs from receipt-verified Slurm evidence")
            if row.get("raw_site_submit") != source.get("raw_site_submit"):
                failures.append(f"allocation {source['job_id']} raw site Submit differs from pinned Slurm evidence")
            if source.get("start_utc") is not None:
                receipt_rel = source.get("utc_receipt_path")
                registered = registry.get("source_files", {}).get(receipt_rel, {})
                receipt_path = confined(final, receipt_rel)
                if not receipt_rel or registered.get("sha256") != sha(receipt_path):
                    failures.append(f"allocation {source['job_id']} lacks its evaluator-pinned UTC submission receipt")
                else:
                    receipt_data = safe_json(receipt_path)
                    receipt_data = receipt_data.get("submission_receipt", receipt_data)
                    if receipt_data.get("job_id") != source["job_id"]:
                        failures.append(f"allocation {source['job_id']} UTC receipt job ID differs")
                    submitted = parse_datetime(receipt_data["submitted_utc"])
                    raw_submit = parse_datetime(row["raw_site_submit"])
                    offset = timedelta(hours=8)
                    if abs((raw_submit - submitted.replace(tzinfo=None) - offset).total_seconds()) >= 1:
                        failures.append(f"allocation {source['job_id']} UTC receipt does not authenticate the raw site timezone offset")
                    for utc_key, site_key in (("start_utc", "raw_site_start"), ("end_utc", "raw_site_end")):
                        derived = (parse_datetime(row[site_key])-offset).replace(tzinfo=submitted.tzinfo)
                        if derived.isoformat() != source[utc_key]:
                            failures.append(f"allocation {source['job_id']} {utc_key} conversion does not follow the pinned receipt")
            if str(row.get("status")) != str(source["state"]):
                failures.append(f"allocation {source['job_id']} state differs from pinned Slurm evidence")
            expected_hours = cores * seconds / 3600
            if not math.isfinite(hours) or hours < 0 or abs(hours-expected_hours) > 1e-6:
                failures.append(f"allocation {source['job_id']} core-hours do not equal cores × elapsed")
            if int(source["cpu_time_raw_seconds"]) != cores * seconds:
                failures.append(f"pinned Slurm CPUTimeRAW mismatch for allocation {source['job_id']}")
            cpu_raw = row.get("process_cpu_hours", "").strip()
            if cpu_raw:
                cpu_value = float(cpu_raw)
                if not math.isfinite(cpu_value) or cpu_value < 0:
                    failures.append(f"allocation {source['job_id']} has invalid process CPU hours")
            mem_raw, scratch_raw = row.get("peak_memory_gib", "").strip(), row.get("scratch_gib", "").strip()
            mem = None if not mem_raw else float(mem_raw)
            scratch = None if not scratch_raw else float(scratch_raw)
            if mem is None:
                unknown_mem = True
            elif not math.isfinite(mem) or mem < 0:
                failures.append(f"allocation {source['job_id']} has invalid peak-memory measurement")
            if scratch is None:
                unknown_scratch = True
            elif not math.isfinite(scratch) or scratch < 0:
                failures.append(f"allocation {source['job_id']} has invalid scratch measurement")
            intervals.append((start, end, cores, mem, scratch))
            corehours += hours
            allocation_seconds += seconds
    except (ValueError, TypeError, KeyError, OverflowError):
        return "FAIL", "resource ledger has malformed or non-finite allocation data", {}
    max_cores, max_memory, max_scratch = 0, 0.0, 0.0
    for start, end, *_ in intervals:
        active = [item for item in intervals if item[0] < end and item[1] > start]
        max_cores = max(max_cores, sum(x[2] for x in active))
        if all(x[3] is not None for x in active):
            max_memory = max(max_memory, sum(x[3] for x in active))
        if all(x[4] is not None for x in active):
            max_scratch = max(max_scratch, sum(x[4] for x in active))
    activity = registry.get("activity_window", {})
    wall_seconds = int(activity.get("elapsed_seconds", 0))
    queue_seconds = int(activity.get("pure_queue_excluded_seconds", 0))
    if not (0 <= queue_seconds <= wall_seconds):
        failures.append("pinned queue-exclusion interval is invalid")
        queue_seconds = 0
    active_wall = wall_seconds - queue_seconds
    observed_start = min(x[0] for x in intervals).isoformat()
    observed_end = max(x[1] for x in intervals).isoformat()
    if observed_start != activity.get("raw_site_start") or observed_end != activity.get("raw_site_end"):
        failures.append("allocation rows do not span the evaluator-pinned raw site activity window")
    if active_wall > 8*3600:
        failures.append("pinned first-start to final-end activity window exceeds eight hours; no pure-queue time is certified")
    if registry.get("expected_scope", {}).get("original_strict_8h_budget_pass") is not False:
        failures.append("evaluator-pinned archive does not establish the original strict eight-hour budget pass")
    facts = {"core_hours": corehours, "allocated_interval_seconds_sum": allocation_seconds,
             "active_wall_seconds_upper_bound": active_wall, "pure_queue_excluded_seconds": queue_seconds,
             "activity_time_basis": activity.get("basis", "raw site timestamps; timezone status is evaluator-pinned"),
             "max_concurrent_cores": max_cores, "max_concurrent_memory_gib": max_memory if not unknown_mem else None,
             "max_concurrent_scratch_gib": max_scratch if not unknown_scratch else None}
    if failures:
        return "FAIL", "; ".join(failures), facts
    if unknown_mem or unknown_scratch:
        return "REVIEW_REQUIRED", "independent peak memory or scratch measurements are missing", facts
    return "PASS", "allocation intervals and measured resource accounting are consistent", facts


def audit_references(final: Path, app: Path, report: dict) -> dict:
    """Recompute author scalar comparisons directly from the protected public CSV."""
    source = app / "assets/ipso_energy_reference.csv"
    with source.open(newline="", encoding="utf-8") as stream:
        refs = {row["species"]: row for row in csv.DictReader(stream)}
    with (final / "barriers.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["channel"]: row for row in csv.DictReader(stream)}
    if set(rows) != {"C1", "C2"} or set(refs) != {"BPR", "C1", "C2"}:
        raise ValueError("author-reference or barrier rows do not contain the frozen BPR/C1/C2 set")
    factor = 627.5094740631
    computed = {}
    for channel in ("C1", "C2"):
        bpr, product, row = refs["BPR"], refs[channel], rows[channel]
        dft = (float(product["e_dft_au"]) + float(product["zpe_au"])
               - float(bpr["e_dft_au"]) - float(bpr["zpe_au"])) * factor
        composite = (float(product["e_f12_au"]) + float(product["zpe_au"])
                     - float(bpr["e_f12_au"]) - float(bpr["zpe_au"])) * factor
        published = float(product["published_channel_barrier_kcal_per_mol"])
        if not all(math.isfinite(x) for x in (dft, composite, published)):
            raise ValueError("author-reference CSV produced a non-finite barrier")
        for field, expected in (("author_dft_zpe_barrier_kcal_per_mol", dft),
                                ("author_composite_barrier_kcal_per_mol", composite),
                                ("published_channel_barrier_kcal_per_mol", published)):
            try:
                observed = float(row[field])
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{channel} {field} is missing or malformed") from exc
            if not math.isfinite(observed) or abs(observed-expected) > 0.05:
                raise ValueError(f"{channel} {field} differs from recomputed author reference")
        computed[channel] = {"author_dft_zpe": dft, "author_composite": composite,
                             "published": published}
    scope = report.get("scope", {})
    if scope.get("F12_migrated") is True:
        narrative = (final / "references_uncertainty.md").read_text(encoding="utf-8").lower()
        if not all(term in narrative for term in ("conditional", "assumption", "limitation")):
            raise ValueError("claimed F12 transfer is not explicitly conditional with assumptions and limitations")
    return {"author_reference_barriers_kcal_mol": computed}


def load_registry(tests: Path) -> dict:
    path = tests / "protected/archive-registry.json"
    digest = sha(path)
    if digest != REGISTRY_SHA256:
        raise EnvInvalid("pinned archive registry bytes do not match verifier authority")
    obj = safe_json(path)
    if (obj.get("schema") != "case07-archive-registry/v1"
            or obj.get("case_id") != CASE_ID
            or obj.get("mode") != "archived_author_evidence"):
        raise EnvInvalid("unsupported archive registry")
    return obj


def validate_refs(tests: Path, app: Path) -> dict:
    refs_path = tests / "refs.json"
    if sha(refs_path) != REFS_SHA256:
        raise EnvInvalid("canonical public-reference manifest digest mismatch")
    refs = safe_json(refs_path)
    if refs.get("case_id") != CASE_ID:
        raise EnvInvalid("refs.json case identity mismatch")
    assets = app / "assets"
    for relative, expected in refs.get("asset_hashes", {}).items():
        if not re.fullmatch(r"assets/[A-Za-z0-9_.\-/]+", relative) or ".." in Path(relative).parts:
            raise EnvInvalid("unsafe public asset reference")
        target = assets.parent / relative
        if sha(target) != expected.removeprefix("sha256:"):
            raise EnvInvalid(f"public asset digest mismatch: {relative}")
    return refs


def check_report(final: Path, registry: dict) -> tuple[dict, dict, bool]:
    report_path = final / "ts_search_report.json"
    try:
        report = safe_json(report_path)
    except EnvInvalid as exc:
        raise ValueError(f"candidate report is missing, unsafe, or malformed: {exc}") from exc
    required = {"definition_revision", "resource_profile", "engine", "final_level",
                "atom_mapping", "short_pilots", "decision_events", "channels"}
    if not required <= report.keys():
        raise ValueError("report.json lacks frozen output-contract fields")
    channels = report.get("channels")
    if not isinstance(channels, dict) or set(channels) != {"C1", "C2"}:
        raise ValueError("report must contain exactly C1 and C2")
    for name, item in channels.items():
        if not isinstance(item, dict) or item.get("channel") != name:
            raise ValueError(f"malformed {name} channel")
        if item.get("status") not in {"validated", "screened_unresolved", "failed"}:
            raise ValueError(f"invalid {name} status")
        if not isinstance(item.get("screening"), list):
            raise ValueError(f"{name} screening must be a list")
        if len(item["screening"]) < 3:
            raise ValueError(f"{name} needs at least three screening records")
    for path in (report_path, final / "barriers.csv", final / "native_outputs",
                 final / "failures.md", final / "resource_usage.csv"):
        if not path.exists() or path.is_symlink():
            raise ValueError(f"required output absent or unsafe: {path.name}")
    if not (final / "native_outputs").is_dir():
        raise ValueError("native_outputs must be a directory")
    barrier_fields = ["channel", "status", "level", "reactant_output", "ts_output",
                      "e_reactant_au", "e_ts_au", "zpe_reactant_au", "zpe_ts_au",
                      "dft_zpe_barrier_kcal_per_mol", "author_dft_zpe_barrier_kcal_per_mol",
                      "author_composite_barrier_kcal_per_mol", "published_channel_barrier_kcal_per_mol",
                      "comparison_scope"]
    with (final / "barriers.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        barrier_rows = list(reader)
        if reader.fieldnames != barrier_fields or len(barrier_rows) != 2:
            raise ValueError("barriers.csv must follow the frozen 14-column, two-channel contract")
    if {r.get("channel") for r in barrier_rows} != {"C1", "C2"}:
        raise ValueError("barriers.csv must contain exactly C1 and C2 rows")
    c2bar = next(r for r in barrier_rows if r["channel"] == "C2")
    if (next(r for r in barrier_rows if r["channel"] == "C2").get("status") != "validated"
            and any(c2bar.get(k, "").strip() for k in ("reactant_output", "ts_output", "e_reactant_au",
                                                        "e_ts_au", "zpe_reactant_au", "zpe_ts_au",
                                                        "dft_zpe_barrier_kcal_per_mol"))):
        raise ValueError("unverified C2 new-level energy and barrier fields must remain empty")
    actual = checked_tree(final)
    expected = registry.get("fixture_manifest")
    exact_archive = (registry.get("fixture_id") == "archived-C1-local-connection-expected-fail"
                     and actual == expected)
    return report, actual, exact_archive


def _has_energy_only_screening(report: dict) -> bool:
    channels = report.get("channels", {})
    if not isinstance(channels, dict):
        return False
    return any(isinstance(entry, dict) and entry.get("native_engrad") is None
               for channel in ("C1", "C2")
               for entry in channels.get(channel, {}).get("screening", []))


def _generic_final_manifest(context: dict) -> tuple[dict[str, str], str]:
    """Normalize the generic CCB artifact snapshot to final/-relative hashes."""
    if context.get("schema") not in {"compchembench.runner-context/v1", "compchembench.runner-context/v2"}:
        raise EnvInvalid("generic runner context schema is invalid")
    if context.get("task_id") != CASE_ID:
        raise EnvInvalid("generic runner context belongs to a different task")
    generic_manifest = context.get("artifact_manifest")
    generic_sha = context.get("artifact_manifest_sha256")
    if (not isinstance(generic_manifest, dict)
            or fresh_evidence.canonical_sha256(generic_manifest) != generic_sha):
        raise EnvInvalid("generic runner artifact snapshot hash is invalid")
    if generic_manifest.get("missing") != []:
        raise EnvInvalid("generic runner artifact snapshot reports missing files")
    declared = generic_manifest.get("declared")
    collected = generic_manifest.get("collected")
    if (declared != [{"source":"/app/final","destination":"final"}]
            or not isinstance(collected, list) or len(collected) != 1
            or not isinstance(collected[0], dict) or collected[0].get("destination") != "final"
            or not isinstance(collected[0].get("files"), list)):
        raise EnvInvalid("generic runner artifact snapshot does not describe the Case07 final mount")
    files: dict[str, str] = {}
    for row in collected[0]["files"]:
        if not isinstance(row, dict):
            raise EnvInvalid("generic final artifact record is malformed")
        path = row.get("path")
        if not isinstance(path, str) or not path.startswith("final/"):
            raise EnvInvalid("generic artifact path is outside the final mount")
        relative = path.removeprefix("final/")
        if (not fresh_evidence._safe_relative(relative) or relative in files
                or type(row.get("bytes")) is not int or row["bytes"] < 0
                or not isinstance(row.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
            raise EnvInvalid("generic final artifact path, size, or hash is invalid")
        files[relative] = row["sha256"]
    if not files:
        raise EnvInvalid("generic final artifact snapshot is empty")
    return files, generic_sha


def load_case07_runner_context(final: Path | None = None) -> dict | None:
    """Load evaluator-mounted Case07 authority, including scoped generic context."""
    context_path = Path(os.environ.get("CCB_RUN_CONTEXT_PATH", "/trusted/runner-context.json"))
    if (os.environ.get("CCB_P04_CASE07_PROVIDER_ID") is not None
            and os.environ.get("CCB_RUN_CONTEXT_PATH") is not None):
        if os.environ.get("CCB_RUN_CONTEXT_PATH") != "/trusted/runner-context.json":
            raise EnvInvalid("standard runner context path is not the fixed trusted mount")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(context_path, flags)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024 * 1024:
                    raise EnvInvalid("standard runner context is not a bounded regular file")
                raw = bytearray()
                while len(raw) <= 2 * 1024 * 1024:
                    chunk = os.read(fd, min(65536, 2 * 1024 * 1024 + 1 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                if len(raw) > 2 * 1024 * 1024:
                    raise EnvInvalid("standard runner context exceeds its byte limit")
            finally:
                os.close(fd)
            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise EnvInvalid("duplicate standard runner context key")
                    result[key] = value
                return result
            context = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=unique_pairs,
                                 parse_constant=lambda value: (_ for _ in ()).throw(
                                     EnvInvalid(f"invalid standard context number {value}")))
        except EnvInvalid:
            raise
        except Exception as exc:
            raise EnvInvalid("standard runner context cannot be safely read") from exc
        expected_sha = os.environ.get("CCB_RUN_CONTEXT_SHA256")
        if (not isinstance(context, dict)
                or context.get("schema") != "compchembench.runner-context/v3"
                or not isinstance(expected_sha, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_sha)
                or hashlib.sha256(raw).hexdigest() != expected_sha
                or os.environ.get("CCB_P04_CASE07_PROVIDER_ID") != context.get("provider_id")):
            raise EnvInvalid("standard runner context v3 schema, digest, or provider environment mismatch")
        return _validate_standard_runner_context_v3(context, final)
    if not context_path.exists():
        return None
    if context_path.is_symlink() or not context_path.is_file():
        raise EnvInvalid("trusted runner context path is redirected or not a regular file")
    context = safe_json(context_path)
    if not isinstance(context, dict):
        raise EnvInvalid("trusted runner context is not an object")
    if context.get("schema") == "case07-runner-context/v1":
        # This standalone context shape is supported. Generic CCB contexts are
        # separately scoped below and never source candidate files.
        return context
    if context.get("schema") not in {"compchembench.runner-context/v1", "compchembench.runner-context/v2"}:
        return None
    namespace = context.get("p04_case07_runtime")
    if namespace is None:
        return None
    if isinstance(namespace, dict) and namespace.get("schema") == "compchembench.p04-case07-runtime-context/v2":
        _validate_p04_case07_operational_context(context, namespace, final)
        # This marker is added only after the host-created operational projection
        # and final artifact snapshot have been validated. It is deliberately
        # not a scientific execution authority.
        context["_p04_case07_operational_verified"] = True
        return context
    if (not isinstance(namespace, dict)
            or set(namespace) != {"schema", "case_id", "attempt_id", "image_id", "authority",
                                  "authority_sha256", "collection_root_binding"}
            or namespace.get("schema") != "p04-case07-runtime-context/v1"
            or namespace.get("case_id") != CASE_ID
            or namespace.get("attempt_id") != context.get("attempt_id")
            or namespace.get("image_id") != context.get("image_id")):
        raise EnvInvalid("P04 Case07 runtime namespace is malformed or cross-bound")
    authority = namespace.get("authority")
    binding = namespace.get("collection_root_binding")
    if (not isinstance(authority, dict) or authority.get("schema") != "case07-runner-context/v1"
            or authority.get("attempt_id") != context.get("attempt_id")
            or not isinstance(binding, dict)
            or binding.get("schema") != "case07-collection-root-projection/v1"):
        raise EnvInvalid("P04 Case07 authority or final-root projection is malformed")
    if namespace.get("authority_sha256") != fresh_evidence.canonical_sha256(authority):
        raise EnvInvalid("P04 Case07 authority digest mismatch")
    projection_unsigned = {key:value for key,value in binding.items() if key != "projection_sha256"}
    if binding.get("projection_sha256") != fresh_evidence.canonical_sha256(projection_unsigned):
        raise EnvInvalid("P04 Case07 final-root projection digest mismatch")
    projection_fields = {"schema", "source_final_root", "host_collected_final_root", "grader_final_root",
        "generic_snapshot_manifest_sha256", "authority_artifact_manifest_sha256",
        "projection_source_sha256", "projected_at_utc", "projection_sha256"}
    if set(binding) != projection_fields:
        raise EnvInvalid("P04 Case07 final-root projection fields differ from the frozen schema")
    for key in ("source_final_root", "host_collected_final_root", "grader_final_root"):
        if (not isinstance(binding.get(key), str) or not binding[key].startswith("/")):
            raise EnvInvalid("P04 Case07 root projection contains a non-absolute root")
    for key in ("generic_snapshot_manifest_sha256", "authority_artifact_manifest_sha256",
                "projection_source_sha256"):
        if not isinstance(binding.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", binding[key]):
            raise EnvInvalid("P04 Case07 root projection contains a malformed digest")
    try:
        fresh_evidence._parse_utc(binding.get("projected_at_utc"))
    except (ValueError, TypeError) as exc:
        raise EnvInvalid("P04 Case07 root projection time is invalid") from exc
    selected_final = Path(final or "/app/final").resolve(strict=True)
    if binding.get("grader_final_root") != str(selected_final):
        raise EnvInvalid("P04 Case07 root projection does not name the grader's actual final directory")
    normalized, generic_sha = _generic_final_manifest(context)
    authority_manifest = authority.get("artifact_manifest")
    authority_sha = authority.get("artifact_manifest_sha256")
    if (not isinstance(authority_manifest, dict)
            or fresh_evidence.canonical_sha256(authority_manifest) != authority_sha
            or normalized != authority_manifest
            or binding.get("generic_snapshot_manifest_sha256") != generic_sha
            or binding.get("authority_artifact_manifest_sha256") != authority_sha):
        raise EnvInvalid("generic final snapshot differs from scoped Case07 authority")
    if fresh_evidence._manifest_from_disk(selected_final) != authority_manifest:
        raise EnvInvalid("mounted /app/final differs from trusted scoped Case07 authority")
    authority = dict(authority)
    authority["collection_root_binding"] = {
        "schema":binding["schema"], "source_final_root":binding["source_final_root"],
        "host_collected_final_root":binding["host_collected_final_root"],
        "collected_final_root":binding["grader_final_root"],
        "grader_final_root":binding["grader_final_root"],
        "artifact_manifest_sha256":authority_sha,
        "generic_snapshot_manifest_sha256":generic_sha,
        "projection_source_sha256":binding["projection_source_sha256"],
        "projected_at_utc":binding["projected_at_utc"]}
    return authority


def _validate_standard_runner_context_v3(context: dict, final: Path | None) -> dict:
    required = {"schema", "task_id", "case_id", "attempt_id", "run_id", "nonce", "image_id",
        "run_path", "case_path", "case_source_files",
        "artifact_manifest", "artifact_manifest_sha256", "attempt_binding_sha256",
        "artifact_declarations", "missing_declarations", "observed_empty", "case_source_hashes",
        "host_source_hashes", "host_source_root", "bench_source_hashes", "bench_source_root",
        "provider_id", "provider_key_id", "provider_public_key_sha256", "provider_public_key_pem",
        "operational_context", "operational_context_sha256", "host_receipts", "accepted_runtime_context"}
    operator_diagnostic = context.get("operator_diagnostic")
    operator_mode = operator_diagnostic is not None
    expected_fields = required | ({"operator_diagnostic"} if operator_mode else set())
    attempt, image = context.get("attempt_id"), context.get("image_id")
    if (set(context) != expected_fields or context.get("task_id") != CASE_ID or context.get("case_id") != CASE_ID
            or not isinstance(attempt, str) or not re.fullmatch(r"[0-9a-f]{32}", attempt)
            or context.get("nonce") != attempt or not isinstance(context.get("run_id"), str)
            or not isinstance(image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image)):
        raise EnvInvalid("standard runner context fields or identity are malformed")
    if operator_mode:
        if (context.get("accepted_runtime_context") is not False
                or not isinstance(operator_diagnostic, dict)
                or os.environ.get("CCB_P04_CASE07_OPERATOR_DIAGNOSTIC") != operator_diagnostic.get("purpose")):
            raise EnvInvalid("Case07 operator diagnostic is not explicitly scoped as local-only")
    elif context.get("accepted_runtime_context") is not True:
        raise EnvInvalid("standard runner context has no accepted trusted admission")
    elif os.environ.get("CCB_P04_CASE07_OPERATOR_DIAGNOSTIC") is not None:
        raise EnvInvalid("operator diagnostic environment cannot accompany ordinary accepted context")
    for key in ("artifact_manifest_sha256", "attempt_binding_sha256", "operational_context_sha256"):
        if not isinstance(context.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", context[key]):
            raise EnvInvalid(f"standard runner context {key} is malformed")
    manifest = context.get("artifact_manifest")
    if (not isinstance(manifest, list) or len(manifest) > 20000
            or fresh_evidence.canonical_sha256(manifest) != context["artifact_manifest_sha256"]):
        raise EnvInvalid("standard runner artifact manifest digest is invalid")
    for row in manifest:
        valid_path = (row.get("path") == "final" and row.get("type") == "directory"
                      and row.get("bytes") == 0 and row.get("sha256") is None) if isinstance(row, dict) else False
        valid_path = valid_path or (isinstance(row, dict) and isinstance(row.get("path"), str)
                      and row["path"].startswith("final/") and fresh_evidence._safe_relative(row["path"]))
        if (not isinstance(row, dict) or set(row) != {"path", "type", "bytes", "sha256"}
                or row.get("type") not in {"file", "directory"}
                or type(row.get("bytes")) is not int or row["bytes"] < 0
                or not valid_path
                or row.get("path") == "final" and row.get("type") != "directory"):
            raise EnvInvalid("standard runner artifact manifest contains an unsafe row")
        if (row["type"] == "file" and (not isinstance(row["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]))
                or row["type"] == "directory" and row["sha256"] is not None):
            raise EnvInvalid("standard runner artifact manifest digest row is malformed")
    declarations = context.get("artifact_declarations")
    # The signed store declaration uses its canonical case-relative source path.
    # Convert to /app only when constructing the grader mount.
    expected_sources = ["final/" + name for name in P04_CASE07_STANDARD_ARTIFACTS]
    if (not isinstance(declarations, list) or len(declarations) != len(expected_sources)
            or [item.get("source") if isinstance(item, dict) else None for item in declarations] != expected_sources
            or any(not isinstance(item, dict) or set(item) != {"source", "destination", "observation"}
                   or item.get("destination") != "final/" + name
                   or item.get("observation") not in {"PRESENT", "MISSING"}
                   for item, name in zip(declarations, P04_CASE07_STANDARD_ARTIFACTS))):
        raise EnvInvalid("standard runner artifact declarations differ from the canonical task root list")
    missing_declarations = context.get("missing_declarations")
    expected_missing = [item for item in declarations if item["observation"] == "MISSING"]
    if missing_declarations != expected_missing:
        raise EnvInvalid("standard runner missing declarations differ from the signed root list")
    for key in ("case_source_hashes", "host_source_hashes", "bench_source_hashes"):
        values = context.get(key)
        if (not isinstance(values, dict) or not values or len(values) > 2000
                or any(not isinstance(path, str) or not isinstance(digest, str)
                       or not re.fullmatch(r"[0-9a-f]{64}", digest)
                       for path, digest in values.items())):
            raise EnvInvalid(f"standard runner {key} inventory is malformed")
    if (set(context["host_source_hashes"]) != set(P04_CASE07_HOST_SOURCE_FILES)
            or set(context["bench_source_hashes"]) != set(P04_CASE07_BENCH_SOURCE_FILES)):
        raise EnvInvalid("standard runner host or bench source pin inventory is incomplete")
    source_files = context.get("case_source_files")
    mandatory_case_files = {"task.toml", "instruction.md", "tests/test.sh", "tests/verify.py"}
    if (not isinstance(source_files, list) or any(not isinstance(item, str) for item in source_files)
            or len(source_files) != len(set(source_files))
            or set(source_files) != set(context["case_source_hashes"])
            or not mandatory_case_files <= set(source_files)
            or not isinstance(context.get("case_path"), str)
            or not context["case_path"].startswith("/")
            or not context["case_path"].rstrip("/").endswith("/packages/" + CASE_ID)
            or not isinstance(context.get("run_path"), str) or not context["run_path"].startswith("/")):
        raise EnvInvalid("standard runner case source inventory or canonical roots are malformed")
    for key in ("host_source_root", "bench_source_root"):
        if not isinstance(context.get(key), str) or not context[key].startswith("/"):
            raise EnvInvalid(f"standard runner {key} is not an absolute trusted root")
    try:
        pem = context["provider_public_key_pem"]
        public_key = serialization.load_pem_public_key(pem.encode("ascii"))
    except Exception as exc:
        raise EnvInvalid("standard runner provider public key is malformed") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise EnvInvalid("standard runner provider key is not Ed25519")
    der = public_key.public_bytes(serialization.Encoding.DER,
                                  serialization.PublicFormat.SubjectPublicKeyInfo)
    key_id = hashlib.sha256(der).hexdigest()[:16]
    if (context.get("provider_key_id") != key_id
            or context.get("provider_public_key_sha256") != hashlib.sha256(pem.encode("ascii")).hexdigest()
            or context.get("provider_id") != f"compchembench.p04-case07-host-receipt/v1:{key_id}"):
        raise EnvInvalid("standard runner provider key identity mismatch")
    if operator_mode:
        stage_a = (isinstance(operator_diagnostic, dict)
                   and operator_diagnostic.get("schema") == "compchembench.p04-case07-stageA-diagnostic/v1")
        diagnostic_fields = {"schema", "purpose", "attempt_id", "image_id", "epoch_sha256",
            "ticket_sha256", "ordinary_runtime_admission", "hpc_submit_allowed", "signature_b64"}
        if not stage_a:
            diagnostic_fields |= {"request_sha256", "source_manifest_sha256", "backend_bundle_sha256",
                                  "accepted_runtime_context", "scientific_authority"}
        if (not isinstance(operator_diagnostic, dict) or set(operator_diagnostic) != diagnostic_fields
                or (stage_a and operator_diagnostic.get("purpose") != "LOCAL_STAGE_A_DIAGNOSTIC_ONLY")
                or (not stage_a and (operator_diagnostic.get("schema") != "compchembench.p04-case07-stageB-pilot-diagnostic/v1"
                    or operator_diagnostic.get("purpose") != "LOCAL_STAGE_B_FIXED_PILOT_DIAGNOSTIC_ONLY"
                    or operator_diagnostic.get("hpc_submit_allowed") is not True
                    or operator_diagnostic.get("accepted_runtime_context") is not False
                    or operator_diagnostic.get("scientific_authority") is not False
                    or not re.fullmatch(r"[0-9a-f]{64}", str(operator_diagnostic.get("request_sha256", "")))
                    or not re.fullmatch(r"[0-9a-f]{64}", str(operator_diagnostic.get("source_manifest_sha256", "")))
                    or not re.fullmatch(r"[0-9a-f]{64}", str(operator_diagnostic.get("backend_bundle_sha256", "")))))
                or operator_diagnostic.get("attempt_id") != attempt
                or operator_diagnostic.get("image_id") != image
                or operator_diagnostic.get("ordinary_runtime_admission") is not False
                or (stage_a and operator_diagnostic.get("hpc_submit_allowed") is not False)
                or not isinstance(operator_diagnostic.get("epoch_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", operator_diagnostic["epoch_sha256"])
                or not isinstance(operator_diagnostic.get("ticket_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", operator_diagnostic["ticket_sha256"])):
            raise EnvInvalid("Case07 Stage A diagnostic ticket scope is malformed")
        unsigned_diagnostic = {k: v for k, v in operator_diagnostic.items() if k != "signature_b64"}
        try:
            public_key.verify(base64.b64decode(operator_diagnostic["signature_b64"], validate=True),
                              fresh_evidence._canonical_bytes(unsigned_diagnostic))
        except Exception as exc:
            raise EnvInvalid("Case07 Stage A diagnostic signature is invalid") from exc
        if not stage_a:
            operational = context.get("operational_context")
            if (not isinstance(operational, dict)
                    or operational.get("operator_stage_b_pilot") is not True
                    or operational.get("ordinary_runtime_admission") is not False
                    or operational.get("scientific_authority") is not False
                    or operational.get("accounting_status") != "SETTLED"
                    or operational.get("stage_b_request_sha256") != operator_diagnostic.get("request_sha256")
                    or operational.get("stage_b_ticket_sha256") != operator_diagnostic.get("ticket_sha256")
                    or operational.get("stage_b_source_manifest_sha256") != operator_diagnostic.get("source_manifest_sha256")
                    or operational.get("stage_b_backend_bundle_sha256") != operator_diagnostic.get("backend_bundle_sha256")):
                raise EnvInvalid("Case07 Stage B diagnostic lifecycle binding is invalid")
    operational = context.get("operational_context")
    if (not isinstance(operational, dict)
            or fresh_evidence.canonical_sha256(operational) != context["operational_context_sha256"]
            or operational.get("case_id") != CASE_ID or operational.get("attempt_id") != attempt
            or operational.get("run_id") != context["run_id"] or operational.get("image_id") != image):
        raise EnvInvalid("standard runner operational context binding mismatch")
    unsigned = {key: value for key, value in operational.items() if key != "operational_proof_sha256"}
    if operational.get("operational_proof_sha256") != fresh_evidence.canonical_sha256(unsigned):
        raise EnvInvalid("standard runner operational context proof mismatch")
    receipts = context.get("host_receipts")
    if not isinstance(receipts, dict) or set(receipts) != {"lifecycle", "collection"}:
        raise EnvInvalid("standard runner lifecycle and collection receipts are required")
    bodies = {}
    for kind in ("lifecycle", "collection"):
        try:
            raw = base64.b64decode(receipts[kind], validate=True)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("oversized")
            doc = json.loads(raw.decode("utf-8", "strict"))
            body = doc["body"]
            public_key.verify(base64.b64decode(doc["signature_b64"], validate=True),
                              fresh_evidence._canonical_bytes(body))
        except Exception as exc:
            raise EnvInvalid(f"standard runner {kind} receipt signature is invalid") from exc
        common_fields = {"domain", "provider_id", "key_id", "attempt_id", "run_id", "case_path",
            "case_id", "image_id", "artifact_manifest_sha256", "attempt_binding_sha256",
            "declarations", "missing_declarations", "observed_empty", "answer_started_at_epoch",
            "answer_ended_at_epoch", "answer_outcome", "container_id", "lifecycle_receipt_sha256",
            "operational_context_sha256", "accounting_status", "source_hashes_sha256",
            "host_source_hashes_sha256", "host_source_root", "bench_source_hashes_sha256",
            "bench_source_root", "kind"}
        exact_fields = common_fields | ({"collection_receipt_sha256", "collection_status"}
                                        if kind == "collection" else set())
        if (not isinstance(doc, dict) or set(doc) != {"body", "signature_b64"}
                or not isinstance(body, dict) or set(body) != exact_fields or body.get("kind") != kind
                or body.get("domain") != "compchembench.p04-case07-host-receipt/v1"
                or body.get("provider_id") != context["provider_id"] or body.get("key_id") != key_id
                or body.get("case_id") != CASE_ID or body.get("attempt_id") != attempt
                or body.get("run_id") != context["run_id"] or body.get("image_id") != image
                or body.get("artifact_manifest_sha256") != context["artifact_manifest_sha256"]
                or body.get("attempt_binding_sha256") != context["attempt_binding_sha256"]
                or body.get("operational_context_sha256") != context["operational_context_sha256"]
                or body.get("answer_outcome") != "COMPLETED"
                or body.get("case_path") != context["case_path"]
                or body.get("source_hashes_sha256") != fresh_evidence.canonical_sha256(context["case_source_hashes"])
                or body.get("host_source_hashes_sha256") != fresh_evidence.canonical_sha256(context["host_source_hashes"])
                or body.get("host_source_root") != context["host_source_root"]
                or body.get("bench_source_hashes_sha256") != fresh_evidence.canonical_sha256(context["bench_source_hashes"])
                or body.get("bench_source_root") != context["bench_source_root"]):
            raise EnvInvalid(f"standard runner {kind} receipt is cross-bound")
        bodies[kind] = body
    lifecycle, collection = bodies["lifecycle"], bodies["collection"]
    common = set(lifecycle) - {"kind"}
    if (set(collection) - {"kind", "collection_receipt_sha256", "collection_status"} != common
            or any(lifecycle.get(key) != collection.get(key) for key in common)
            or lifecycle.get("lifecycle_receipt_sha256") != operational.get("lifecycle_receipt_sha256")):
        raise EnvInvalid("standard runner receipt pair does not bind together")
    binding = {
        "schema": "compchembench.standard-attempt-binding/v1",
        "attempt_id": attempt, "run_id": context["run_id"], "run_path": context["run_path"],
        "case_path": context["case_path"], "image_digest": image,
        "source_hashes": context["case_source_hashes"],
        "host_source_hashes": context["host_source_hashes"],
        "host_source_root": context["host_source_root"],
        "bench_source_hashes": context["bench_source_hashes"],
        "bench_source_root": context["bench_source_root"],
        "answer_started_at_epoch": lifecycle["answer_started_at_epoch"],
        "answer_ended_at_epoch": lifecycle["answer_ended_at_epoch"],
        "artifact_manifest_sha256": context["artifact_manifest_sha256"],
        "declarations": declarations, "missing_declarations": missing_declarations,
        "observed_empty": context["observed_empty"],
    }
    if fresh_evidence.canonical_sha256(binding) != context["attempt_binding_sha256"]:
        raise EnvInvalid("standard runner attempt binding digest mismatch")
    collections = operational.get("collections")
    hashes = collection.get("collection_receipt_sha256")
    if (not isinstance(collections, list) or not isinstance(hashes, list)
            or sorted(row.get("receipt_sha256") for row in collections if isinstance(row, dict)) != sorted(hashes)
            or any(not isinstance(row, dict) or row.get("image_id") != image for row in collections)):
        raise EnvInvalid("standard runner collection evidence differs from signed image receipts")
    selected_final = Path(final or "/app/final")
    if (selected_final.is_symlink() or not selected_final.exists() or not selected_final.is_dir()):
        raise EnvInvalid("standard runner final artifact projection is missing or unsafe")
    if selected_final.exists():
        expected = {row["path"].removeprefix("final/"): row["sha256"] for row in manifest
                    if isinstance(row, dict) and row.get("type") == "file"
                    and isinstance(row.get("path"), str) and row["path"].startswith("final/")}
        missing = context.get("missing_declarations")
        if type(context.get("observed_empty")) is not bool:
            raise EnvInvalid("standard runner absence observation is malformed")
        for declaration in missing:
            if (not isinstance(declaration, dict)
                    or set(declaration) != {"source", "destination", "observation"}
                    or declaration.get("observation") != "MISSING"
                    or declaration not in declarations):
                raise EnvInvalid("standard runner missing declaration differs from signed inventory")
            source = declaration.get("source")
            if not isinstance(source, str) or not source.startswith("final/"):
                raise EnvInvalid("standard runner absence declaration escapes final artifacts")
            relative = source.removeprefix("final/")
            if relative == "native_outputs" or relative.endswith("/native_outputs"):
                directory = selected_final / relative
                if not directory.is_dir() or directory.is_symlink() or any(directory.iterdir()):
                    raise EnvInvalid("signed missing output directory is not an empty grader mask")
            else:
                target = selected_final / relative
                if target.is_symlink() or not target.is_file() or target.stat().st_size != 0:
                    raise EnvInvalid("signed missing output file is not an empty grader mask")
                expected[relative] = hashlib.sha256(b"").hexdigest()
        if fresh_evidence._manifest_from_disk(selected_final) != expected:
            raise EnvInvalid("mounted final directory differs from signed snapshot manifest")
    return context


def _validate_p04_case07_operational_context(context: dict, namespace: dict,
                                              final: Path | None) -> None:
    """Validate ordinary transport/accounting evidence without upgrading science."""
    fields = {"schema", "case_id", "attempt_id", "run_id", "image_id", "allocation_class",
        "qualification_only", "qualification_ticket_sha256", "qualification_request_sha256",
        "lifecycle_receipt_path", "lifecycle_receipt_sha256", "profile_sha256",
        "source_manifest_sha256", "job_id", "allocation", "collections", "aborted_stage",
        "backend_status", "accounting_status", "unresolved_job_count", "operational_proof_sha256"}
    if set(namespace) != fields:
        raise EnvInvalid("P04 Case07 operational runtime fields differ from the frozen schema")
    attempt = context.get("attempt_id")
    if (namespace.get("schema") != "compchembench.p04-case07-runtime-context/v2"
            or namespace.get("case_id") != CASE_ID or namespace.get("attempt_id") != attempt
            or namespace.get("run_id") != context.get("run_id")
            or context.get("task_id") != CASE_ID
            or not isinstance(attempt, str) or not re.fullmatch(r"[0-9a-f]{32}", attempt)
            or not isinstance(context.get("image_id"), str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", context["image_id"])
            or namespace.get("image_id") != context.get("image_id")):
        raise EnvInvalid("P04 Case07 operational runtime is cross-bound to another attempt or image")
    unsigned_projection = {key:value for key,value in namespace.items()
                           if key != "operational_proof_sha256"}
    if (not isinstance(namespace.get("operational_proof_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", namespace["operational_proof_sha256"])
            or namespace["operational_proof_sha256"] !=
                fresh_evidence.canonical_sha256(unsigned_projection)):
        raise EnvInvalid("P04 Case07 operational projection digest mismatch")
    for key in ("lifecycle_receipt_sha256", "profile_sha256"):
        if not isinstance(namespace.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", namespace[key]):
            raise EnvInvalid(f"P04 Case07 operational {key} is malformed")
    receipt_path = namespace.get("lifecycle_receipt_path")
    if not isinstance(receipt_path, str) or not Path(receipt_path).is_absolute():
        raise EnvInvalid("P04 Case07 operational lifecycle receipt path is malformed")
    if namespace.get("backend_status") != "CLOSED" or namespace.get("unresolved_job_count") != 0:
        raise EnvInvalid("P04 Case07 operation was not durably closed")
    if type(namespace.get("qualification_only")) is not bool:
        raise EnvInvalid("P04 Case07 qualification marker is malformed")
    allocation_class = namespace.get("allocation_class")
    ticket_sha, request_sha = (namespace.get("qualification_ticket_sha256"),
                               namespace.get("qualification_request_sha256"))
    if namespace["qualification_only"]:
        if (allocation_class != "qualification"
                or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
                       for v in (ticket_sha, request_sha))):
            raise EnvInvalid("P04 Case07 qualification operation lacks its consumed ticket binding")
    elif allocation_class != "ordinary" or ticket_sha is not None or request_sha is not None:
        raise EnvInvalid("P04 Case07 ordinary operation contains qualification authority")
    job_id, source_sha = namespace.get("job_id"), namespace.get("source_manifest_sha256")
    allocation = namespace.get("allocation")
    if namespace.get("accounting_status") == "NO_SUBMISSION":
        if job_id is not None or source_sha is not None or allocation is not None:
            raise EnvInvalid("P04 Case07 no-submission context contains job authority")
    elif namespace.get("accounting_status") == "SETTLED":
        if (not isinstance(job_id, str) or not re.fullmatch(r"[0-9]{1,20}", job_id)
                or not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha)
                or not isinstance(allocation, dict)
                or set(allocation) != {"job_id", "state", "exit_code", "alloc_cpus",
                    "elapsed_raw", "cpu_time_raw", "raw_sacct_sha256"}
                or allocation.get("job_id") != job_id
                or allocation.get("state") not in {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT",
                    "OUT_OF_MEMORY", "NODE_FAIL", "PREEMPTED", "BOOT_FAIL", "DEADLINE",
                    "REVOKED", "SPECIAL_EXIT"}
                or allocation.get("alloc_cpus") != 8
                or type(allocation.get("elapsed_raw")) is not int
                or allocation["elapsed_raw"] < 0
                or allocation.get("cpu_time_raw") != allocation["elapsed_raw"] * 8
                or not isinstance(allocation.get("raw_sacct_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", allocation["raw_sacct_sha256"])):
            raise EnvInvalid("P04 Case07 terminal allocation evidence is malformed")
    else:
        raise EnvInvalid("P04 Case07 accounting status is unsupported")
    collections = namespace.get("collections")
    if not isinstance(collections, list) or len(collections) > 64:
        raise EnvInvalid("P04 Case07 collection evidence is malformed")
    seen_paths = set()
    for collection in collections:
        if (not isinstance(collection, dict) or set(collection) != {"receipt_sha256", "files"}
                or not isinstance(collection.get("receipt_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", collection["receipt_sha256"])
                or not isinstance(collection.get("files"), list)):
            raise EnvInvalid("P04 Case07 collection receipt projection is malformed")
        for item in collection["files"]:
            if (not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}
                    or not isinstance(item.get("path"), str)
                    or not item["path"] or Path(item["path"]).is_absolute()
                    or any(part in {"", ".", ".."} for part in Path(item["path"]).parts)
                    or type(item.get("bytes")) is not int or item["bytes"] < 0
                    or not isinstance(item.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                    or item["path"] in seen_paths):
                raise EnvInvalid("P04 Case07 collected artifact projection is malformed")
            seen_paths.add(item["path"])
    manifest, _ = _generic_final_manifest(context)
    selected_final = Path(final or "/app/final").resolve(strict=True)
    if fresh_evidence._manifest_from_disk(selected_final) != manifest:
        raise EnvInvalid("generic final snapshot differs from the actual grader final tree")
    aborted = namespace.get("aborted_stage")
    if aborted is not None and (not isinstance(aborted, dict)
            or aborted.get("termination_reason") not in {
                "answer_completed", "answer_failed", "answer_timeout", "runner_shutdown"}):
        raise EnvInvalid("P04 Case07 aborted-stage projection is malformed")


def fresh_reference_geometries(app: Path) -> dict[str, dict]:
    """Read the evaluator-pinned public atom mapping and reaction geometries."""
    path = app / "assets/bpr_skeleton_geometries.csv"
    groups: dict[str, list[dict]] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            groups.setdefault(row["species_role"], []).append(row)
    roles = {"bpr": "bicyclic_peroxy_radical", "C1": "ring_opened_product_C1",
             "C2": "ring_opened_product_C2"}
    result = {}
    for key, role in roles.items():
        rows = groups.get(role, [])
        rows.sort(key=lambda row: int(row["atom_index"]))
        if len(rows) != 21 or [int(row["atom_index"]) for row in rows] != list(range(1, 22)):
            raise EnvInvalid(f"pinned public geometry has invalid {role} atom rows")
        source_elements, source_coordinates = [], []
        for row in rows:
            element = row["element"]
            coords = [float(row[axis]) for axis in ("x", "y", "z")]
            if (any(not math.isfinite(value) for value in coords)
                    or element not in {"C", "H", "O"}):
                raise EnvInvalid(f"pinned public geometry has invalid values for {role}")
            source_elements.append(element)
            source_coordinates.append(coords)
        source_indices = FROZEN_PRODUCT_SOURCE_INDEX[key]
        elements = [source_elements[index - 1] for index in source_indices]
        coordinates = [source_coordinates[index - 1] for index in source_indices]
        if elements != FROZEN_ELEMENTS:
            raise EnvInvalid(f"pinned public geometry atom ordering differs for {role}")
        result[key] = {"elements": elements, "coordinates": coordinates}
    return result


def audit_new_native(final: Path, app: Path, tests: Path, report: dict,
                     registry: dict, context: dict | None):
    refs = validate_refs(tests, app)
    public_hashes = {name: value.removeprefix("sha256:")
                     for name, value in refs["asset_hashes"].items()}
    authority = fresh_evidence.audit_fresh_authority(final, context, public_hashes)
    api = {"stage_facts": stage_facts, "confined": confined, "parse_xyz": parse_xyz,
           "aligned_max_difference": aligned_max_difference, "safe_json": safe_json,
           "sha": sha, "UnsupportedEvidence": UnsupportedEvidence}
    native = fresh_native.audit_fresh_native(final, report, api,
                                             fresh_reference_geometries(app), registry)
    return authority, native


def record(name: str, level: str, status: str, reason: str, paths: list[str]):
    return {"name": name, "level": level, "status": status,
            "passed": True if status == "PASS" else False if status == "FAIL" else None,
            "reason": reason, "evidence_paths": paths}


def score(app: Path, tests: Path, logs: Path) -> int:
    logs.mkdir(parents=True, exist_ok=True)
    reward_path = logs / "reward.txt"
    reward_path.unlink(missing_ok=True)
    (logs / "reward.json").unlink(missing_ok=True)
    try:
        validate_refs(tests, app)
        registry = load_registry(tests)
    except EnvInvalid as exc:
        result = {"schema_version": "case07-verification/v1", "status": "ENV_INVALID",
                  "scientific_scope": "archive_replay_only", "archive_mode": False,
                  "checks": [], "errors": [str(exc)], "measurements": {}}
        (logs / "verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(str(exc), file=sys.stderr)
        return 2
    standard_context = None
    final = app / "final"
    checks = {name: record(name, level, "REVIEW_REQUIRED", "not assessed", [])
              for name, level in CHECKS}
    measurements, errors, report, manifest, exact = {}, [], {}, {}, False
    try:
        report, manifest, exact = check_report(final, registry)
        checks[CHECKS[0][0]] = record(CHECKS[0][0], "L1", "PASS",
            "All five frozen deliverable classes parse and both channel records are present.",
            ["final/ts_search_report.json", "final/barriers.csv", "final/native_outputs",
             "final/failures.md", "final/resource_usage.csv"])
    except (EnvInvalid, ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
        checks[CHECKS[0][0]] = record(CHECKS[0][0], "L1", "FAIL", str(exc), [])
        errors.append(str(exc))
        report = {}

    context = None
    fresh_authority = None
    fresh_route = False
    screen_facts = {}
    native_facts = {}
    legacy_shape = False
    if report:
        legacy_shape = isinstance(report.get("channels"), dict) and isinstance(
            report["channels"].get("C1", {}).get("validation"), dict) and (
            "plus_opt_chain" in report["channels"]["C1"]["validation"])
        fresh_route = not legacy_shape
        if report.get("definition_revision") != "2.1":
            message = "current report definition_revision must match provenance contract v2.1"
            checks[CHECKS[0][0]] = record(CHECKS[0][0], "L1", "FAIL", message, ["final/ts_search_report.json"])
            errors.append(message)

    if report and fresh_route:
        candidate_audit = candidate_execution.audit(final, report)
        if candidate_audit.get("transport") in ("hpc", "ikkem-slurm"):
            measurements["slurm_records"] = candidate_audit
        if (candidate_audit.get("status") == "REVIEW_REQUIRED"
                and (candidate_audit.get("reason") == "resource peak-memory or scratch measurement is missing"
                     or candidate_audit.get("transport") in ("hpc", "ikkem-slurm"))):
            try:
                resource_review = case07_review.assess_resources(
                    final, tests, report, candidate_audit.get("attempt_id", ""),
                    native_slurm=candidate_audit.get("transport") in ("hpc", "ikkem-slurm"))
            except case07_review.ReviewEnvironmentError as exc:
                result = {"schema_version": "case07-verification/v1", "status": "ENV_INVALID",
                          "scientific_scope": "trusted_resource_review_input_invalid", "archive_mode": False,
                          "checks": [record(n, level, "REVIEW_REQUIRED", "trusted review input invalid", [])
                                     for n, level in CHECKS], "errors": [str(exc)], "measurements": {}}
                (logs / "verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
                return 2
            if resource_review.get("status") in {"PASS", "FAIL"}:
                # Keep the original audit facts and reason available for diagnostics;
                # the protected review resolves only this exact missing-measurement state.
                original_resource_audit = dict(candidate_audit)
                candidate_audit = {**candidate_audit, "status": resource_review["status"],
                                   "reason": resource_review["reason"],
                                   "original_resource_audit": original_resource_audit,
                                   "resource_review": resource_review}
        # Candidate receipts are cross-checked attempt evidence, never host
        # authority. Scientific narrative review remains a separate gate.
        try:
            review = case07_review.assess(final, tests, report, candidate_audit.get("attempt_id", ""))
        except case07_review.ReviewEnvironmentError as exc:
            result = {"schema_version": "case07-verification/v1", "status": "ENV_INVALID",
                      "scientific_scope": "trusted_review_input_invalid", "archive_mode": False,
                      "checks": [record(n, level, "REVIEW_REQUIRED", "trusted review input invalid", [])
                                 for n, level in CHECKS], "errors": [str(exc)], "measurements": {}}
            (logs / "verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            return 2
        fresh_authority = SimpleNamespace(
            status="PASS", attempt_id=None,
            resource_status=candidate_audit["status"],
            resource_reason=candidate_audit["reason"],
            decision_review_status=review["criteria"]["budgeted_scientific_decisions"],
            reference_review_status=review["criteria"]["reference_comparison_and_uncertainty"],
            execution_status=candidate_audit["status"],
            execution_reason=candidate_audit["reason"])
        api = {"stage_facts": stage_facts, "confined": confined, "parse_xyz": parse_xyz,
               "aligned_max_difference": aligned_max_difference, "safe_json": safe_json,
               "sha": sha, "UnsupportedEvidence": UnsupportedEvidence,
               "bond_graph": bond_graph}
        try:
            native_extras = report.get("native_extra_stages", [])
            if not isinstance(native_extras, list):
                raise ValueError("native_extra_stages must be a list")
            route = report.get("native_route")
            if route is not None and (not isinstance(route, str) or not route.strip()):
                raise ValueError("native_route must be a non-empty string when supplied")
            # The calibrated single-endpoint audit cannot represent IRC or
            # explicit recovery-stage layouts. Their exact raw files and job
            # bindings have already passed candidate_execution.audit; route
            # validity is then decided only by protected native-review/v3.
            if native_extras or route not in (None, "signed-mode-two-endpoint-opt"):
                raise UnsupportedEvidence("candidate declares a nonstandard native route; protected review v3 is required")
            if _has_energy_only_screening(report):
                raise UnsupportedEvidence("candidate reports an energy-only screening format; protected native review v3 is required")
            native_result = fresh_native.audit_fresh_native(
                final, report, api, fresh_reference_geometries(app), registry)
            native_facts = dict(native_result.facts)
            checks[CHECKS[1][0]] = record(CHECKS[1][0], "L2", "PASS", native_result.reason,
                                          ["final/native_outputs"])
            checks[CHECKS[2][0]] = record(CHECKS[2][0], "L3", "PASS", native_result.reason,
                                          ["final/ts_search_report.json", "final/native_outputs"])
            screen_facts = native_facts.get("screening", {})
            pilot_facts = native_facts.get("pilots", [])
            checks[CHECKS[3][0]] = record(CHECKS[3][0], "L3", "REVIEW_REQUIRED",
                f"Fresh native pilots and distinct energy/gradient screens parsed: {screen_facts}; independent decision review is still required.",
                ["final/ts_search_report.json", "final/native_outputs"])
            if fresh_authority is not None:
                if fresh_authority.decision_review_status == "FAIL":
                    checks[CHECKS[3][0]] = record(CHECKS[3][0], "L3", "FAIL",
                        "Evaluator-pinned independent review rejected the screening or selection rationale.",
                        ["final/ts_search_report.json"])
                elif fresh_authority.decision_review_status == "PASS":
                    checks[CHECKS[3][0]] = record(CHECKS[3][0], "L3", "PASS",
                        "Fresh pilot and both-channel screening evidence passed native parsing and evaluator-pinned independent decision review.",
                        ["final/ts_search_report.json", "final/native_outputs"])
        except fresh_native.FreshCriterionFailure as exc:
            checks[exc.criterion] = record(exc.criterion, dict(CHECKS)[exc.criterion], "FAIL",
                                          str(exc), ["final/native_outputs"])
            if exc.criterion == CHECKS[3][0]:
                checks[CHECKS[3][0]] = record(CHECKS[3][0], "L3", "FAIL", str(exc),
                                              ["final/ts_search_report.json", "final/native_outputs"])
        except UnsupportedEvidence as exc:
            for criterion in (CHECKS[1][0], CHECKS[2][0]):
                checks[criterion] = record(criterion, dict(CHECKS)[criterion], "REVIEW_REQUIRED",
                                           str(exc), ["final/native_outputs"])
            decision_status = fresh_authority.decision_review_status if fresh_authority is not None else "REVIEW_REQUIRED"
            decision_label = {"PASS": "PASS", "FAIL": "FAIL"}.get(decision_status, "REVIEW_REQUIRED")
            checks[CHECKS[3][0]] = record(CHECKS[3][0], "L3", decision_label,
                ("Fresh screening decisions passed independent narrative review for this unsupported native route."
                 if decision_label == "PASS" else
                 "Independent screening-decision review rejected the submission."
                 if decision_label == "FAIL" else
                 "Fresh screening-decision narrative review is still required."),
                ["final/ts_search_report.json", "final/native_outputs"])
            # A protected v3 review can resolve only these two parser-scope
            # uncertainties. It is considered only after candidate execution
            # and resource evidence passed, and cannot override any FAIL.
            try:
                native_review = case07_review.assess_native(
                    final, tests, report, candidate_audit.get("attempt_id", ""), exc, candidate_audit)
            except case07_review.ReviewEnvironmentError as review_exc:
                errors.append(str(review_exc))
                native_review = {"status": "ENV_INVALID", "reason": str(review_exc), "criteria": {}}
            if candidate_audit.get("status") == "PASS" and native_review.get("status") in {"PASS", "FAIL"}:
                for criterion in (CHECKS[1][0], CHECKS[2][0]):
                    status = native_review["criteria"].get(criterion, "REVIEW_REQUIRED")
                    checks[criterion] = record(criterion, dict(CHECKS)[criterion], status,
                        native_review.get("reason", "protected native review result"),
                        ["final/native_outputs", "final/ts_search_report.json"])
        except (EnvInvalid, ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
            checks[CHECKS[1][0]] = record(CHECKS[1][0], "L2", "FAIL", str(exc),
                                          ["final/native_outputs"])
    elif report:
        try:
            screen_facts = audit_screening(final, report)
            checks[CHECKS[3][0]] = record(CHECKS[3][0], "L3", "REVIEW_REQUIRED",
                f"Complete native energy/gradient evaluations verified: {screen_facts}; narrative selection and canonical scope still need independent scientific review.",
                ["final/ts_search_report.json", "final/native_outputs/manifest.json"])
        except (EnvInvalid, ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
            checks[CHECKS[3][0]] = record(CHECKS[3][0], "L3", "FAIL", str(exc),
                ["final/ts_search_report.json", "final/native_outputs"])
        try:
            native_facts = audit_native(final, report, registry)
            checks[CHECKS[1][0]] = record(CHECKS[1][0], "L2", "PASS",
                "Native C1 stationary points, energies, frequencies, and Hessians are internally consistent.",
                ["final/native_outputs/manifest.json"])
            checks[CHECKS[2][0]] = record(CHECKS[2][0], "L3", "PASS",
                "The C1 local connection is bound through the actual signed mode, endpoint starts, graph roles, and complete cycle-34 restart.",
                ["final/ts_search_report.json", "final/native_outputs/manifest.json"])
        except CriterionFailure as exc:
            checks[exc.criterion] = record(exc.criterion,
                dict(CHECKS)[exc.criterion], "FAIL", str(exc), ["final/native_outputs"])
        except UnsupportedEvidence as exc:
            checks[CHECKS[1][0]] = record(CHECKS[1][0], "L2", "REVIEW_REQUIRED", str(exc),
                ["final/native_outputs"])
        except (EnvInvalid, ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
            checks[CHECKS[1][0]] = record(CHECKS[1][0], "L2", "FAIL", str(exc),
                ["final/native_outputs"])

    if report:
        try:
            ref_facts = audit_references(final, app, report)
            if fresh_route and fresh_authority is not None:
                ref_status = fresh_authority.reference_review_status
                ref_reason = ("Evaluator-pinned reference review rejected the narrative or uncertainty claims."
                              if ref_status == "FAIL" else
                              "Author scalar values were recomputed from the pinned CSV and the fresh reference narrative passed independent review."
                              if ref_status == "PASS" else
                              "Author scalar values were recomputed from the pinned CSV; independent review of the new-method comparison and uncertainty text is not authenticated.")
                checks[CHECKS[4][0]] = record(CHECKS[4][0], "L3", ref_status, ref_reason,
                    ["final/barriers.csv", "final/references_uncertainty.md", "assets/ipso_energy_reference.csv"])
            else:
                checks[CHECKS[4][0]] = record(CHECKS[4][0], "L3", "REVIEW_REQUIRED",
                    "Author scalar values were independently recomputed from the pinned CSV; narrative interpretation awaits external scientific review. No F12 migration is claimed.",
                    ["final/barriers.csv", "final/references_uncertainty.md", "assets/ipso_energy_reference.csv"])
            measurements.update(ref_facts)
        except (EnvInvalid, ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
            checks[CHECKS[4][0]] = record(CHECKS[4][0], "L3", "FAIL", str(exc),
                ["final/barriers.csv", "assets/ipso_energy_reference.csv"])

    if report and not fresh_route:
        source_files = registry.get("source_files", {})
        provenance_ok = bool(source_files)
        for relative, source in source_files.items():
            target = final / relative
            if target.is_symlink() or not target.is_file() or sha(target) != source.get("sha256"):
                provenance_ok = False
                break
        checks[CHECKS[5][0]] = record(CHECKS[5][0], "L3", "FAIL",
            "legacy plus_opt_chain report shape is not accepted as current candidate execution evidence.",
            ["final/native_outputs/manifest.json"])

    resource_status, resource_reason, resource_facts = "FAIL", "resource ledger not assessed", {}
    try:
        if fresh_route and fresh_authority is not None and fresh_authority.status == "PASS":
            resource_status, resource_reason = fresh_authority.resource_status, fresh_authority.resource_reason
            resource_facts = {"trusted_attempt_id": fresh_authority.attempt_id}
        else:
            resource_status, resource_reason, resource_facts = audit_resources(final, registry)
        if legacy_shape:
            resource_status = "FAIL"
            resource_reason = resource_reason + "; legacy plus_opt_chain shape is diagnostic only and cannot qualify current candidate resources"
        checks[CHECKS[6][0]] = record(CHECKS[6][0], "L2", resource_status, resource_reason,
            ["final/resource_usage.csv", "final/native_outputs/manifest.json"])
    except (EnvInvalid, ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
        checks[CHECKS[6][0]] = record(CHECKS[6][0], "L2", "FAIL", str(exc),
            ["final/resource_usage.csv"])

    if report and fresh_route:
        if fresh_authority is None or fresh_authority.status == "REVIEW_REQUIRED":
            checks[CHECKS[5][0]] = record(CHECKS[5][0], "L3", "REVIEW_REQUIRED",
                "Fresh native evidence is parsed, but evaluator-only host execution and sealed-snapshot authority is absent.",
                ["final/native_outputs"])
        elif fresh_authority.status == "ENV_INVALID":
            checks[CHECKS[5][0]] = record(CHECKS[5][0], "L3", "FAIL", fresh_authority.reason,
                                          ["final/native_outputs"])
        elif fresh_authority.execution_status == "FAIL":
            checks[CHECKS[5][0]] = record(CHECKS[5][0], "L3", "FAIL",
                fresh_authority.execution_reason, ["final/native_outputs"])
        elif fresh_authority.execution_status != "PASS":
            checks[CHECKS[5][0]] = record(CHECKS[5][0], "L3", "REVIEW_REQUIRED",
                fresh_authority.execution_reason, ["final/native_outputs"])
        else:
            checks[CHECKS[5][0]] = record(CHECKS[5][0], "L3", "PASS",
                fresh_authority.execution_reason, ["final/native_outputs"])
            if fresh_authority.resource_status == "ENV_INVALID":
                result = {"schema_version": "case07-verification/v1", "status": "ENV_INVALID",
                          "scientific_scope": "fresh_evidence_untrusted", "archive_mode": False,
                          "checks": [record(n, level, "REVIEW_REQUIRED", "trusted context invalid", [])
                                     for n, level in CHECKS],
                          "errors": [fresh_authority.resource_reason], "measurements": {}}
                (logs / "verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
                return 2

    measurements.update(resource_facts)
    measurements["artifact_count"] = len(manifest)
    measurements["archive_fixture_id"] = registry.get("fixture_id") if exact else None
    if native_facts:
        barrier_value = native_facts.get("forward_barrier", native_facts.get("dft_zpe_barrier_kcal_mol"))
        if barrier_value is not None:
            measurements["selected_channel_dft_zpe_barrier_kcal_mol"] = barrier_value
        stage_map = native_facts.get("stages", {})
        if "ts_freq" in stage_map:
            imag_id = stage_map["ts_freq"]["hessian"]["physical_imaginary"][0]
            measurements["ts_imaginary_frequency_cm-1"] = stage_map["ts_freq"]["hessian"]["frequencies"][imag_id]
            measurements["physical_modes"] = 57
            measurements["endpoint_imaginary_modes"] = 0
    checks_list = [checks[name] for name, _ in CHECKS]
    statuses = {item["status"] for item in checks_list}
    outcome = "FAIL" if "FAIL" in statuses else "REVIEW_REQUIRED" if "REVIEW_REQUIRED" in statuses else "PASS"
    scope = registry.get("expected_scope", {})
    if fresh_route:
        validated_channel = native_facts.get("selected_channel")
        scope = {"C1_local_connection": validated_channel == "C1",
                 "C2_validated": validated_channel == "C2",
                 "canonical_screening_scope_revalidated": bool(native_facts.get("screening")
                                     and all(native_facts.get("screening", {}).get(c, {}).get("distinct_geometries", 0) >= 3
                                             for c in ("C1", "C2"))
                                     and fresh_authority is not None
                                     and fresh_authority.decision_review_status == "PASS"),
                 "original_strict_8h_budget_pass": False,
                 "IRC_converged": False, "F12_migrated": False}
    result = {"schema_version": "case07-verification/v1", "status": outcome,
              "scientific_scope": {"C1_local_connection": bool(native_facts.get("selected_channel") == "C1"
                                                                   or (not fresh_route and native_facts)),
                                   "C2_validated": bool(scope.get("C2_validated", False)),
                                   "canonical_screening_scope_revalidated": bool(scope.get("canonical_screening_scope_revalidated", False)),
                                   "original_strict_8h_budget_pass": bool(scope.get("original_strict_8h_budget_pass", False)),
                                   "IRC_converged": bool(scope.get("IRC_converged", False)),
                                   "F12_migrated": bool(scope.get("F12_migrated", False))},
              "archive_mode": exact, "legacy_diagnostic_only": bool(legacy_shape),
              "checks": checks_list, "errors": errors,
              "measurements": measurements}
    if outcome == "FAIL":
        result["reward"] = 0
        (logs / "reward.txt").write_text("0\n")
    elif outcome == "PASS":
        result["reward"] = 1
        (logs / "reward.txt").write_text("1\n")
    else:
        reward_path.unlink(missing_ok=True)
        # An unscored review is a valid Harbor outcome, not a scientific zero.
        (logs / "reward.json").write_text("{}\n")
    (logs / "verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(f"{outcome}: scorer criteria written; reward " + ("0" if outcome == "FAIL" else "withheld"))
    return 0


def build_failure(reason: str) -> dict:
    checks = [record(n, level, "FAIL" if i == 0 else "REVIEW_REQUIRED", reason if i == 0 else "not assessed", [])
              for i, (n, level) in enumerate(CHECKS)]
    return {"schema_version": "case07-verification/v1", "status": "FAIL",
            "scientific_scope": "unverified", "archive_mode": False,
            "checks": checks, "errors": [], "measurements": {}, "reward": 0}


def build_review(report: dict, reason: str) -> dict:
    checks = [record(n, level, "REVIEW_REQUIRED", reason, []) for n, level in CHECKS]
    return {"schema_version": "case07-verification/v1", "status": "REVIEW_REQUIRED",
            "scientific_scope": "new_run_unverified", "archive_mode": False,
            "checks": checks, "errors": [], "measurements": {}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, default=Path(os.environ.get("APP", "/app")))
    parser.add_argument("--tests", type=Path, default=Path(os.environ.get("TESTS", "/tests")))
    parser.add_argument("--logs", type=Path, default=Path(os.environ.get("LOGS", "/tmp")))
    args = parser.parse_args()
    return score(args.app, args.tests, args.logs)


if __name__ == "__main__":
    raise SystemExit(main())
