#!/usr/bin/env python3
"""Author-side syntax inspection for a fixed-R 500-state CP2K ENERGY spectrum.

This is not a scorer and does not authenticate geometry, restart bytes, runtime,
Slurm evidence, spectral correctness, or scientific acceptance. The native case07
500-state ENERGY ordering has not been observed; fixtures in tests are synthetic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re

from inspect_gs_energy import inspect_text as inspect_gs_energy
from parse_workflow import STATE_RE, parse_text

FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
KERNEL_RE = re.compile(r"^\s*KERNEL\|\s*(FULL|sTDA)\s*$", re.I)
SPIN_RE = re.compile(r"^\s*KERNEL\|\s*Spin symmetry of excitations\s+(Singlet|Triplet)\s*$", re.I)
RUN_RE = re.compile(r"^\s*RUN_TYPE\s+(\S+)\s*$", re.I)
ENERGY_TABLE_RE = re.compile(r"^\s*ENERGY\| Total FORCE_EVAL \( QS \) energy \[a\.u\.\]:", re.I)
TD_CONV_RE = re.compile(r"^\s*-\s*TDDFPT run (NOT )?converged in\s+(\d+)\s+iteration", re.I)
STATE_TABLE_RE = re.compile(r"^\s*R-TDDFPT states of multiplicity\s+1\s*$", re.I)
STATE_TABLE_END_RE = re.compile(r"^\s*TDDFPT\s*:\s*CheckSum\s*=", re.I)
STATE_HEADER_RE = re.compile(r"^\s*State\s+Excitation\s+Transition dipole\s+\(a\.u\.\)", re.I)
FORCE_RE = re.compile(r"^\s*(?:ATOMIC\s+FORCES\b|FORCES\|\s*Atomic forces\b|FORCES\s+\[a\.u\.\])", re.I)
FORBIDDEN_EXCITED_NATIVE_RE = re.compile(
    r"\b(?:Excited State Energy|Excited State Forces|Excitation Energy\s+\[Hartree\]|"
    r"Results for Excited State|EXCITED_STATES)\b", re.I)


class SpectrumError(ValueError):
    pass


def _records(input_text: str) -> dict:
    stack: list[str] = []
    blocks: list[dict] = []
    keywords: list[dict] = []
    runs: list[dict] = []
    errors: list[str] = []
    for number, raw in enumerate(input_text.splitlines(), 1):
        line = raw.split("!", 1)[0].split("#", 1)[0]
        if re.match(r"^\s*@", line):
            errors.append(f"active preprocessor directive at line {number}")
        run = RUN_RE.match(line)
        if run:
            runs.append({"value": run[1].upper(), "path": list(stack), "line": number})
        close = re.match(r"^\s*&\s*END(?:\s+([A-Z][A-Z0-9_]*))?\s*$", line, re.I)
        if close:
            if not stack:
                errors.append(f"unexpected END at line {number}")
            else:
                name = close[1].upper() if close[1] else None
                top = stack.pop()
                if name and name != top:
                    errors.append(f"mismatched END at line {number}: expected {top}, found {name}")
            continue
        opening = re.match(r"^\s*&\s*([A-Z][A-Z0-9_]*)(?:\s+(.*))?$", line, re.I)
        if opening:
            blocks.append({"name": opening[1].upper(), "args": (opening[2] or "").strip(),
                           "path": tuple(stack + [opening[1].upper()]), "line": number})
            stack.append(opening[1].upper())
            continue
        keyword = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s+(\S+)\s*$", line, re.I)
        if keyword:
            keywords.append({"key": keyword[1].upper(), "value": keyword[2], "path": tuple(stack), "line": number})
    if stack:
        errors.append("unclosed input blocks: " + "/".join(stack))
    return {"runs": runs, "blocks": blocks, "keywords": keywords, "errors": errors}


def _at(records: dict, key: str, path: tuple[str, ...]) -> list[dict]:
    return [x for x in records["keywords"] if x["key"] == key and x["path"] == path]


def _input_contract(input_text: str) -> dict:
    rec = _records(input_text)
    blocks = rec["blocks"]
    td_path = ("FORCE_EVAL", "PROPERTIES", "TDDFPT")
    td_blocks = [b for b in blocks if b["name"] == "TDDFPT"]
    td = [b for b in td_blocks if b["path"] == td_path]
    excited = [b for b in blocks if b["name"] == "EXCITED_STATES"]
    excited_ok = (not excited or (len(excited) == 1 and
                   excited[0]["path"] == ("FORCE_EVAL", "DFT", "EXCITED_STATES") and
                   excited[0]["args"].upper() in ("F", "FALSE", "OFF")))
    vals = {
        "nstates": _at(rec, "NSTATES", td_path),
        "kernel": _at(rec, "KERNEL", td_path),
        "triplets": _at(rec, "RKS_TRIPLETS", td_path),
        "dipole_form": _at(rec, "DIPOLE_FORM", td_path + ("DIPOLE_MOMENTS",)),
        "wfn_name": _at(rec, "WFN_RESTART_FILE_NAME", ("FORCE_EVAL", "DFT")),
        "scf_guess": _at(rec, "SCF_GUESS", ("FORCE_EVAL", "DFT", "SCF")),
        "do_ewald": _at(rec, "DO_EWALD", td_path + ("STDA",)),
    }
    run_ok = (len(rec["runs"]) == 1 and rec["runs"][0] == {
        "value": "ENERGY", "path": ["GLOBAL"], "line": rec["runs"][0]["line"]})
    kernel = vals["kernel"][0]["value"].upper() if len(vals["kernel"]) == 1 else None
    expected_kernel = kernel if kernel in ("FULL", "STDA") else None
    checks = {
        "input_well_formed_without_active_preprocessor": not rec["errors"],
        "global_run_type_energy": run_ok,
        "exactly_one_direct_td_block": len(td_blocks) == len(td) == 1 and td[0]["args"].upper() in ("", "T"),
        "nstates_500": len(vals["nstates"]) == 1 and vals["nstates"][0]["value"] == "500",
        "kernel_full_or_stda": expected_kernel is not None,
        "singlet_requested": len(vals["triplets"]) == 1 and vals["triplets"][0]["value"].upper() == "F",
        "velocity_dipole_form_requested": len(vals["dipole_form"]) == 1 and vals["dipole_form"][0]["value"].upper() == "VELOCITY",
        "excited_state_optimization_off_or_absent": excited_ok,
        "seed_restart_declared": (len(vals["wfn_name"]) == 1 and vals["wfn_name"][0]["value"] == "seed.wfn" and
                                  len(vals["scf_guess"]) == 1 and vals["scf_guess"][0]["value"].upper() == "RESTART"),
        "stda_ewald_enabled_when_stda": (expected_kernel != "STDA" or
                                         (len(vals["do_ewald"]) == 1 and vals["do_ewald"][0]["value"].upper() in ("T", "TRUE", ".TRUE."))),
    }
    return {"records": rec, "values": vals, "kernel": expected_kernel,
            "checks": checks, "passed": all(checks.values()),
            "excited_states_off_basis": ("explicit off" if excited else
                "absent; CP2K v2024.3 input_cp2k_exstate.F sets EXCITED_STATES section default_l_val=.FALSE.; executable version is not authenticated")}


def inspect_text(input_text: str, native_text: str, expected_atoms: int = 192) -> dict:
    if isinstance(expected_atoms, bool) or not isinstance(expected_atoms, int) or expected_atoms < 1:
        raise SpectrumError("expected_atoms must be a positive integer")
    contract = _input_contract(input_text)
    # The GS wrapper supplies strict convergence, restart-read, single ENERGY,
    # normal native footer, fixed-R, and E0/ENERGY printed-precision checks.
    gs = inspect_gs_energy(input_text, native_text, expected_atoms=expected_atoms)
    parsed = parse_text(native_text, expected_atoms=expected_atoms, expected_states=500, stage="ENERGY")
    evaluations = parsed.get("evaluations", [])
    ev = evaluations[0] if len(evaluations) == 1 else None
    states = (ev or {}).get("states", [])
    state_checks = (ev or {}).get("state_checks", {})
    td_events = (ev or {}).get("td_events", [])
    lines = native_text.splitlines()
    kernel_rows = [(i + 1, m[1].upper()) for i, line in enumerate(lines) if (m := KERNEL_RE.match(line))]
    spin_rows = [(i + 1, m[1].upper()) for i, line in enumerate(lines) if (m := SPIN_RE.match(line))]
    dipole_mode_rows = [(i + 1, line.strip()) for i, line in enumerate(lines)
                        if re.search(r"^\s*Transition dipoles calculated using\s+velocity formulation\s*$", line, re.I)]
    table_rows = [(i + 1, int(m[1])) for i, line in enumerate(lines) if (m := STATE_RE.match(line))]
    table_markers = [i for i, line in enumerate(lines) if STATE_TABLE_RE.match(line)]
    table_ends = [i for i, line in enumerate(lines) if STATE_TABLE_END_RE.match(line)]
    state_headers = [i + 1 for i, line in enumerate(lines) if STATE_HEADER_RE.match(line)]
    state_table_candidates = []
    if len(table_markers) == 1 and len(table_ends) == 1 and table_markers[0] < table_ends[0]:
        state_table_candidates = [(i + 1, STATE_RE.match(line)) for i, line in enumerate(lines)
                                  if table_markers[0] < i < table_ends[0] and re.match(r"^\s*TDDFPT\|", line)]
    td_convergence_rows = [(i + 1, bool(m[1]), int(m[2])) for i, line in enumerate(lines)
                           if (m := TD_CONV_RE.match(line))]
    final_energy_lines = [i + 1 for i, line in enumerate(lines) if ENERGY_TABLE_RE.match(line)]
    scf_total_lines = [i + 1 for i, line in enumerate(lines) if re.match(r"^\s*Total energy:\s*[-+0-9.EeDd]+\s*$", line)]
    force_headings = [i + 1 for i, line in enumerate(lines) if FORCE_RE.match(line)]
    excited_native = bool(FORBIDDEN_EXCITED_NATIVE_RE.search(native_text))
    native_runs = gs.get("native_contract", {}).get("global_run_types", [])
    common = gs.get("common_validator", {})
    common_ok = (common.get("actual_common_keyset_matches_contract") is True and
                 all(common.get("selected_results", {}).values()))
    restart_ok = gs.get("checks", {}).get("native_positive_seed_wfn_read_before_scf_without_atomic_guess") is True
    state_lines_in_energy = (len(table_markers) == len(table_ends) == 1 and
                             len(state_table_candidates) == 500 and all(m is not None for _, m in state_table_candidates) and
                             len(table_rows) == len(states) == 500 and
                             table_rows == [(s.get("line"), s.get("state")) for s in states])
    scf_lines = [line for line in (ev or {}).get("scf_energy_lines", [])]
    td_order = (len(scf_lines) > 0 and len(final_energy_lines) == 1 and len(td_events) == 1 and
                len(table_rows) == 500 and scf_lines[-1] < td_convergence_rows[0][0] < table_rows[0][0] <=
                table_rows[-1][0] < final_energy_lines[0]) if td_convergence_rows else False
    checksum_order = (len(table_ends) == 1 and len(table_rows) == 500 and len(final_energy_lines) == 1 and
                      table_rows[-1][0] < table_ends[0] + 1 < final_energy_lines[0])
    marker_line = table_markers[0] + 1 if len(table_markers) == 1 else None
    first_state_line = table_rows[0][0] if table_rows else None
    td_converged_line = td_convergence_rows[0][0] if len(td_convergence_rows) == 1 else None
    kernel_before_td = (len(kernel_rows) == 1 and len(spin_rows) == 1 and td_converged_line is not None and
                        kernel_rows[0][0] < td_converged_line and spin_rows[0][0] < td_converged_line)
    table_mode_order = (marker_line is not None and first_state_line is not None and
                        len(state_headers) == 1 and marker_line < state_headers[0] < first_state_line and
                        len(dipole_mode_rows) == 1 and marker_line < dipole_mode_rows[0][0] < first_state_line)
    td_convergence_precedes_table = (td_converged_line is not None and marker_line is not None and
                                     td_converged_line < marker_line)
    checks = {
        "input_contract_passes": contract["passed"],
        "common_gs_scf_restart_end_and_energy_checks_pass": common_ok,
        "fixed_geometry_single_energy_evaluation_without_optimizer": gs.get("checks", {}).get("fixed_r_single_energy_evaluation_with_no_opt_steps") is True,
        "expected_native_header_atom_count": parsed.get("header_atom_count") == expected_atoms,
        "all_energy_headings_well_formed_and_attached": gs.get("checks", {}).get("finite_final_energy_and_ordered_scf_total_record") is True,
        "native_run_type_energy_only": native_runs == ["ENERGY"],
        "native_restart_read_before_scf_without_fallback": restart_ok,
        "finite_final_ground_state_energy_and_ordered_scf_total_record": gs.get("checks", {}).get("finite_final_energy_and_ordered_scf_total_record") is True,
        "exactly_one_positive_td_convergence": len(td_convergence_rows) == 1 and not td_convergence_rows[0][1] and td_convergence_rows[0][2] > 0,
        "parser_td_converged_and_500_ordered_finite_nonnegative_states": ((ev or {}).get("convergence_flags", {}).get("td") is True and
            state_checks.get("count") == 500 and not state_checks.get("duplicate_ids") and
            not state_checks.get("missing_expected_ids") and state_checks.get("ordered") is True and
            state_checks.get("finite") is True and state_checks.get("nonnegative_energy_and_f") is True and
            all(s.get("energy_eV", 0) > 0 for s in states)),
        "all_native_state_rows_match_parser_rows": state_lines_in_energy,
        "native_td_table_after_scf_and_before_final_energy": td_order,
        "native_checksum_after_last_state_and_before_final_energy": checksum_order,
        "native_kernel_matches_requested_kernel": len(kernel_rows) == 1 and contract["kernel"] is not None and kernel_rows[0][1] == contract["kernel"],
        "native_singlet_and_velocity_dipoles": len(spin_rows) == 1 and spin_rows[0][1] == "SINGLET" and len(dipole_mode_rows) == 1,
        "native_kernel_and_spin_metadata_precede_td_convergence": kernel_before_td,
        "native_td_convergence_precedes_state_table": td_convergence_precedes_table,
        "native_velocity_and_single_state_header_inside_table_preamble": table_mode_order,
        "single_energy_evaluation_and_no_force_output": len(evaluations) == 1 and not force_headings,
        "no_excited_state_total_energy_block_or_optimizer_output": not excited_native and not parsed.get("geometry_optimization_completed") and not parsed.get("minimum_reevaluation_lines"),
    }
    failures = [name for name, value in checks.items() if not value]
    return {
        "helper": "case07-spectrum-energy-author-review/v1", "stage": "ENERGY_SPECTRUM",
        "expected_atoms": expected_atoms, "expected_states": 500,
        "checks": checks, "strict_syntax_complete": not failures, "failed_checks": failures,
        "input_contract": {"kernel": contract["kernel"], "checks": contract["checks"],
            "excited_states_off_basis": contract["excited_states_off_basis"],
            "block_errors": contract["records"]["errors"], "run_types": contract["records"]["runs"]},
        "native_contract": {"native_run_types": native_runs, "td_convergence_records": td_convergence_rows,
            "state_row_count": len(table_rows), "state_checks": state_checks, "kernel_records": kernel_rows,
            "spin_records": spin_rows, "dipole_mode_records": dipole_mode_rows,
            "state_table_header_lines": state_headers, "state_table_marker_lines": [i + 1 for i in table_markers],
            "state_table_checksum_lines": [i + 1 for i in table_ends],
            "scf_total_energy_lines": scf_total_lines, "final_energy_lines": final_energy_lines,
            "force_headings": force_headings, "td_table_ordered_after_scf_before_energy": td_order},
        "common_gs_inspector": gs,
        "parser_diagnostic": {"errors": parsed.get("errors", []), "warnings": parsed.get("warnings", []),
            "unresolved_tail_events": parsed.get("unresolved_tail_events", []),
            "stage_file_diagnostic": parsed.get("stage_file_diagnostic")},
        "scope_limits": {"external_seed_bytes_and_source_job": "not checked",
            "actual_restart_provenance": "native text only; not authenticated",
            "runtime_and_slurm": "not checked", "geometry_identity": "not checked",
            "scientific_spectrum_correctness_or_tolerance": "not assessed",
            "native_500_state_case07_fixture": "not available; synthetic test only"},
        "tolerances": None, "science_validated": False, "gold_eligible": False,
        "interpretation": "Author-side syntax only. ENERGY is checked as ground-state E0; TD excitation energies are not added to ENERGY and are not identified as S1.",
    }


def _safe_output(output: Path | None, sources: list[Path]) -> bool:
    if output is None:
        return True
    resolved = output.resolve(strict=False)
    for source in sources:
        if resolved == source.resolve(strict=False):
            return False
        try:
            if output.exists() and source.exists() and os.path.samefile(output, source):
                return False
        except OSError:
            return False
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--native", required=True, type=Path)
    ap.add_argument("--expected-atoms", type=int, default=192)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args(argv)
    if not _safe_output(args.output, [args.input, args.native]):
        print(json.dumps({"helper": "case07-spectrum-energy-author-review/v1", "error": "output aliases protected input/native", "science_validated": False}, indent=2))
        return 2
    try:
        input_bytes = args.input.read_bytes()
        native_bytes = args.native.read_bytes()
        result = inspect_text(input_bytes.decode("utf-8"), native_bytes.decode("utf-8"), args.expected_atoms)
        result["file_hashes"] = {"input_sha256": hashlib.sha256(input_bytes).hexdigest(),
                                 "native_sha256": hashlib.sha256(native_bytes).hexdigest()}
        rendered = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0 if result["strict_syntax_complete"] else 1
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        print(json.dumps({"helper": "case07-spectrum-energy-author-review/v1", "error": str(exc),
                          "science_validated": False, "gold_eligible": False}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
