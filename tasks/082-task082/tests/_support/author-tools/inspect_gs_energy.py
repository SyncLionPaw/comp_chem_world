#!/usr/bin/env python3
"""Author-side strict syntax review for a single CP2K GS ENERGY run.

This wrapper reuses inspect_full_scf's common terminal checks but does not
pretend ENERGY has forces. It is not a scorer and cannot authenticate the
executable, actual WFN bytes, restart provenance, Slurm cost, or physics.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

from inspect_full_scf import inspect_text as inspect_full_scf_text
from parse_workflow import ENERGY_RE, parse_text

FLOAT_TOKEN = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
SCF_TOTAL_RE = re.compile(rf"^\s*Total energy:\s*({FLOAT_TOKEN})\s*$", re.I)
SCF_TOTAL_NONFINITE_RE = re.compile(r"^\s*Total energy:\s*[-+]?(?:nan|inf(?:inity)?)\s*$", re.I)
SCF_TOTAL_HEADING_RE = re.compile(r"^\s*Total energy\s*:", re.I)
ENERGY_FAMILY_RE = re.compile(r"^\s*ENERGY\|\s*Total FORCE_EVAL(?:\s*\([^)]*\))?(.*)$", re.I)
GLOBAL_RUN_RE = re.compile(r"^\s*GLOBAL\|\s*Run type\s+(\S+)\s*$", re.I)
RESTART_READ_RE = re.compile(r"^\s*WFN_RESTART\|\s*Restart file\s+seed\.wfn\s+read\s*$", re.I)
RESTART_GUESS_RE = re.compile(r"Density guess:\s*RESTART\b", re.I)
ANY_DENSITY_GUESS_RE = re.compile(r"Density guess:\s*(\S+)", re.I)
ATOMIC_GUESS_RE = re.compile(r"Density guess:\s*(?:ATOMIC|CORE|ATOMIC_DENSITY)\b|SCF_GUESS\s+ATOMIC\b|\busing atomic guess\b", re.I)

COMMON_REQUIRED_CHECKS = (
    "input_outer_scf_configured_inside_scf",
    "input_block_structure_well_formed",
    "native_header_atom_count_matches_expected",
    "exactly_one_energy_evaluation",
    "finite_final_energy_record",
    "all_energy_headings_well_formed_and_attached",
    "all_scf_total_headings_finite_and_well_formed",
    "finite_scf_e0_record",
    "positive_inner_scf_convergence_events",
    "positive_configured_outer_scf_convergence_events",
    "one_native_start_and_end_with_footer_after_evaluation",
    "no_abort_or_nonconvergence_errors",
    "no_unresolved_tail_events",
    "no_fortran_fatal_or_error_text",
)
COMMON_EXCLUDED_CHECKS = (
    "input_run_type_is_energy_force",
    "run_type_declared_under_global",
    "fixed_geometry_energy_force_no_opt_step",
    "complete_finite_ordered_force_blocks_before_end",
)


def _energy_heading_inventory(native_text: str) -> dict:
    headings, malformed = [], []
    for line_number, line in enumerate(native_text.splitlines(), 1):
        family = ENERGY_FAMILY_RE.match(line)
        if not family:
            continue
        descriptor = family.group(1).strip().lower()
        # These are separate CP2K diagnostics, not total-energy records.
        if descriptor.startswith("gap") or descriptor.startswith("free energy"):
            continue
        headings.append(line_number)
        match = ENERGY_RE.match(line)
        if not match:
            malformed.append(line_number)
            continue
        try:
            if not math.isfinite(float(match.group(1).replace("D", "E").replace("d", "e"))):
                malformed.append(line_number)
        except (ValueError, OverflowError):
            malformed.append(line_number)
    return {"heading_lines": headings, "malformed_lines": malformed}


class ReviewInputError(ValueError):
    pass


def _active_lines(text: str) -> list[str]:
    return [line.split("!", 1)[0].split("#", 1)[0] for line in text.splitlines()]


def _input_keywords(text: str) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    stack: list[str] = []
    run_types, wfn_names, guesses, errors = [], [], [], []
    for line_number, line in enumerate(_active_lines(text), 1):
        if re.match(r"^\s*@", line):
            errors.append(f"active preprocessor directive/include at line {line_number}")
        m = re.match(r"^\s*RUN_TYPE\s+(\S+)\s*$", line, re.I)
        if m:
            run_types.append({"value": m.group(1).upper(), "path": list(stack), "line": line_number})
        m = re.match(r"^\s*WFN_RESTART_FILE_NAME\s+(\S+)\s*$", line, re.I)
        if m:
            wfn_names.append({"value": m.group(1), "path": list(stack), "line": line_number})
        m = re.match(r"^\s*SCF_GUESS\s+(\S+)\s*$", line, re.I)
        if m:
            guesses.append({"value": m.group(1).upper(), "path": list(stack), "line": line_number})
        close = re.match(r"^\s*&\s*END(?:\s+([A-Z][A-Z0-9_]*))?\s*$", line, re.I)
        if close:
            if not stack:
                errors.append(f"unexpected END at line {line_number}")
            else:
                name = close.group(1).upper() if close.group(1) else None
                top = stack.pop()
                if name and name != top:
                    errors.append(f"mismatched END at line {line_number}: expected {top}, found {name}")
            continue
        opening = re.match(r"^\s*&\s*([A-Z][A-Z0-9_]*)(?:\s+.*)?$", line, re.I)
        if opening:
            stack.append(opening.group(1).upper())
    if stack:
        errors.append("unclosed input blocks: " + "/".join(stack))
    return run_types, wfn_names, guesses, errors


def _half_ulp(token: str) -> Decimal:
    value = token.replace("D", "E").replace("d", "e")
    dec = Decimal(value)
    exponent = dec.as_tuple().exponent
    return Decimal("0.5").scaleb(exponent)


def _energy_consistency(native_text: str, parsed_energy: float) -> dict:
    energy_records = []
    scf_records = []
    for line_number, line in enumerate(native_text.splitlines(), 1):
        match = ENERGY_RE.match(line)
        if match:
            energy_records.append({"line": line_number, "token": match.group(1)})
        match = SCF_TOTAL_RE.match(line)
        if match:
            scf_records.append({"line": line_number, "token": match.group(1)})
    if len(energy_records) != 1 or not scf_records:
        return {"passed": False, "reason": "need exactly one ENERGY total and at least one SCF Total energy record",
                "energy_records": energy_records, "scf_total_energy_records": scf_records}
    e_record, scf_record = energy_records[-1], scf_records[-1]
    if scf_record["line"] >= e_record["line"]:
        return {"passed": False, "reason": "last SCF Total energy record must precede final ENERGY total",
                "energy_records": energy_records, "scf_total_energy_records": scf_records,
                "energy_record_line": e_record["line"], "scf_total_energy_line": scf_record["line"]}
    try:
        e_value = Decimal(e_record["token"].replace("D", "E").replace("d", "e"))
        s_value = Decimal(scf_record["token"].replace("D", "E").replace("d", "e"))
        if not e_value.is_finite() or not s_value.is_finite() or not math.isfinite(parsed_energy):
            return {"passed": False, "reason": "non-finite energy token",
                    "energy_records": energy_records, "scf_total_energy_records": scf_records}
        delta = abs(e_value - s_value)
        rounding_envelope = _half_ulp(e_record["token"]) + _half_ulp(scf_record["token"])
        parsed_equal = math.isfinite(parsed_energy) and float(e_value) == parsed_energy
    except (InvalidOperation, ValueError, OverflowError):
        return {"passed": False, "reason": "non-numeric or non-finite energy token",
                "energy_records": energy_records, "scf_total_energy_records": scf_records}
    return {"passed": delta <= rounding_envelope and parsed_equal,
            "energy_record_line": e_record["line"], "scf_total_energy_line": scf_record["line"],
            "energy_token": e_record["token"], "scf_total_energy_token": scf_record["token"],
            "absolute_difference_Ha": float(delta), "printed_rounding_envelope_Ha": float(rounding_envelope),
            "method": "Decimal comparison within half-unit-last-place bounds derived from the two printed tokens; not a scientific tolerance."}


def _energy_record_diagnostic(native_text: str, parsed_energy: float,
                              last_scf_event_line: int | None = None,
                              line_offset: int = 0) -> dict:
    """Check finite/order syntax while leaving SCF-total/ENERGY relation unjudged.

    CP2K 2024.3 prints the SCF summary and final force-evaluation energy at
    different source points. Their difference is retained as an observation;
    no production tolerance or pass/fail relation is inferred here.
    """
    energy_records, scf_records = [], []
    energy_inventory = _energy_heading_inventory(native_text)
    energy_heading_lines, malformed_energy_lines = energy_inventory["heading_lines"], energy_inventory["malformed_lines"]
    scf_heading_lines, malformed_scf_lines, nonfinite_scf_lines = [], [], []
    for local_line_number, line in enumerate(native_text.splitlines(), 1):
        line_number = local_line_number + line_offset
        if match := ENERGY_RE.match(line):
            energy_records.append({"line": line_number, "token": match.group(1)})
        if SCF_TOTAL_HEADING_RE.match(line):
            scf_heading_lines.append(line_number)
        if match := SCF_TOTAL_RE.match(line):
            scf_records.append({"line": line_number, "token": match.group(1)})
        elif SCF_TOTAL_NONFINITE_RE.match(line):
            nonfinite_scf_lines.append(line_number)
        elif SCF_TOTAL_HEADING_RE.match(line):
            malformed_scf_lines.append(line_number)
    if (len(energy_records) != 1 or len(energy_heading_lines) != 1 or malformed_energy_lines or
            not scf_records or len(scf_heading_lines) != len(scf_records) or malformed_scf_lines or
            nonfinite_scf_lines):
        return {"syntax_passed": False,
                "reason": "need exactly one well-formed finite ENERGY heading and only well-formed finite SCF Total headings",
                "energy_records": energy_records, "scf_total_energy_records": scf_records,
                "energy_heading_lines": energy_heading_lines, "malformed_energy_heading_lines": malformed_energy_lines,
                "scf_total_heading_lines": scf_heading_lines, "malformed_scf_total_lines": malformed_scf_lines,
                "nonfinite_scf_total_lines": nonfinite_scf_lines,
                "numerical_relation_verified": False, "production_tolerance": None}
    energy_record, scf_record = energy_records[0], scf_records[-1]
    try:
        energy_value = Decimal(energy_record["token"].replace("D", "E").replace("d", "e"))
        scf_value = Decimal(scf_record["token"].replace("D", "E").replace("d", "e"))
        if (not energy_value.is_finite() or not scf_value.is_finite() or
                not math.isfinite(float(energy_value)) or not math.isfinite(float(scf_value)) or
                isinstance(parsed_energy, bool) or not isinstance(parsed_energy, (int, float)) or
                not math.isfinite(parsed_energy)):
            raise InvalidOperation("nonfinite/untyped energy")
        delta = abs(energy_value - scf_value)
        printed_envelope = _half_ulp(energy_record["token"]) + _half_ulp(scf_record["token"])
        parser_energy_matches_token = float(energy_value) == float(parsed_energy)
    except (InvalidOperation, ValueError, OverflowError):
        return {"syntax_passed": False, "reason": "non-numeric or non-finite final ENERGY/SCF token",
                "energy_records": energy_records, "scf_total_energy_records": scf_records,
                "numerical_relation_verified": False, "production_tolerance": None}
    scf_after_event = last_scf_event_line is None or scf_record["line"] > last_scf_event_line
    ordered = scf_record["line"] < energy_record["line"] and scf_after_event
    return {"syntax_passed": bool(ordered and parser_energy_matches_token),
            "reason": None if ordered and parser_energy_matches_token else
                ("last SCF Total must follow final inner SCF event and precede ENERGY" if not ordered else
                 "parsed ENERGY value does not match native ENERGY token"),
            "energy_record_line": energy_record["line"], "scf_total_energy_line": scf_record["line"],
            "last_scf_event_line": last_scf_event_line, "energy_token": energy_record["token"],
            "scf_total_energy_token": scf_record["token"], "absolute_difference_Ha": str(delta),
            "printed_rounding_envelope_Ha": str(printed_envelope),
            "parser_energy_matches_native_token": parser_energy_matches_token,
            "numerical_relation_verified": False, "production_tolerance": None,
            "relation_interpretation": "Difference and printed-token envelope are reported only; neither agreement nor disagreement is an accuracy verdict."}


def inspect_text(input_text: str, native_text: str, expected_atoms: int = 192) -> dict:
    shared = inspect_full_scf_text(input_text, native_text, expected_atoms=expected_atoms)
    parsed = parse_text(native_text, expected_atoms=expected_atoms, stage="auto")
    evaluations = parsed.get("evaluations", [])
    ev = evaluations[0] if len(evaluations) == 1 else None
    run_types, wfn_names, guesses, input_errors = _input_keywords(input_text)
    input_energy = (len(run_types) == 1 and run_types[0]["value"] == "ENERGY" and
                    run_types[0]["path"] == ["GLOBAL"])
    input_restart = (len(wfn_names) == 1 and wfn_names[0]["value"] == "seed.wfn" and
                     wfn_names[0]["path"] == ["FORCE_EVAL", "DFT"] and
                     len(guesses) == 1 and guesses[0]["value"] == "RESTART" and
                     guesses[0]["path"] == ["FORCE_EVAL", "DFT", "SCF"])
    no_excited_input = not bool(re.search(r"^\s*&\s*(?:EXCITED_STATES|TDDFPT)\b", "\n".join(_active_lines(input_text)), re.I | re.M))
    native_lines = native_text.splitlines()
    global_runs = [m.group(1).upper() for line in native_lines if (m := GLOBAL_RUN_RE.match(line))]
    native_energy_mode = global_runs == ["ENERGY"]
    no_td_native = not bool(re.search(
        r"\bTDDFPT\b|\bR-TDDFPT\b|Excitation analysis|Excited State Energy|"
        r"Excitation Energy|Results for Excited State", native_text, re.I))
    restart_read_lines = [i + 1 for i, line in enumerate(native_lines) if RESTART_READ_RE.match(line)]
    restart_guess_lines = [i + 1 for i, line in enumerate(native_lines) if RESTART_GUESS_RE.search(line)]
    density_guesses = [(i + 1, m.group(1).upper()) for i, line in enumerate(native_lines)
                       if (m := ANY_DENSITY_GUESS_RE.search(line))]
    atomic_guess_lines = [i + 1 for i, line in enumerate(native_lines) if ATOMIC_GUESS_RE.search(line)]
    scf_lines = [x["line"] for x in (ev or {}).get("scf_events", [])]
    scf_start_lines = [i + 1 for i, line in enumerate(native_lines)
                       if re.search(r"SCF WAVEFUNCTION OPTIMIZATION|^\s*\d+\s+OT\s+", line, re.I)]
    actual_restart_read = (len(restart_read_lines) == 1 and len(restart_guess_lines) == 1 and
                           len(density_guesses) == 1 and density_guesses[0][1] == "RESTART" and
                           not atomic_guess_lines and bool(scf_start_lines) and
                           restart_guess_lines[0] < restart_read_lines[0] < min(scf_start_lines))
    opt_lines = [i + 1 for i, line in enumerate(native_lines) if re.search(r"\bOPT\|\s*Step number|GEOMETRY OPTIMIZATION COMPLETED", line, re.I)]
    fixed_r_energy = (input_energy and native_energy_mode and len(evaluations) == 1 and not opt_lines and
                      parsed.get("stage") == "ENERGY")
    last_scf_event_line = max((x.get("line", 0) for x in (ev or {}).get("scf_events", [])), default=None)
    energy_consistency = _energy_record_diagnostic(
        native_text, ev.get("energy_total_Ha", float("nan")) if ev else float("nan"), last_scf_event_line)
    force_headings = [i + 1 for i, line in enumerate(native_lines)
                      if re.search(r"^\s*(?:ATOMIC\s+FORCES\b|FORCES\|\s*Atomic forces\b|FORCES\s+\[a\.u\.\])", line, re.I)]
    common_checks = shared.get("checks", {})
    common_keyset_exact = (set(common_checks) == set(COMMON_REQUIRED_CHECKS) | set(COMMON_EXCLUDED_CHECKS))
    common_check_results = {name: common_checks.get(name) is True for name in COMMON_REQUIRED_CHECKS}
    # ENERGY cannot calculate forces. CP2K emits force tables only when force
    # evaluation is requested; any force heading in this ENERGY-only record is
    # unexpected or concatenated output and invalidates this syntax review.
    no_force_output = not force_headings
    checks = {
        "common_inspect_full_scf_checks_pass": common_keyset_exact and all(common_check_results.values()),
        "input_global_run_type_energy": input_energy,
        "native_global_run_type_energy_only": native_energy_mode,
        "fixed_r_single_energy_evaluation_with_no_opt_steps": fixed_r_energy,
        "input_ground_state_without_excited_state_blocks": no_excited_input,
        "native_has_no_td_or_excitation_output": no_td_native,
        "input_has_no_active_preprocessor_directives": not any("active preprocessor" in e for e in input_errors),
        "input_declares_seed_wfn_restart": input_restart,
        "native_positive_seed_wfn_read_before_scf_without_atomic_guess": actual_restart_read,
        "native_force_output_absent_for_energy_only_run": no_force_output,
        "finite_final_energy_and_ordered_scf_total_record": bool(energy_consistency.get("syntax_passed")),
        "input_block_structure_well_formed": not input_errors and shared.get("input_contract", {}).get("block_structure_well_formed") is True,
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "helper": "case07-gs-energy-author-review/v1",
        "stage": "GS_ENERGY",
        "expected_atoms": expected_atoms,
        "checks": checks,
        "strict_syntax_complete": not failures,
        "failed_checks": failures,
        "common_validator": {
            "name": "inspect_full_scf.inspect_text",
            "selected_required_checks": list(COMMON_REQUIRED_CHECKS),
            "selected_results": common_check_results,
            "excluded_checks": list(COMMON_EXCLUDED_CHECKS),
            "actual_common_keyset_matches_contract": common_keyset_exact,
            "exclusion_reason": "Only ENERGY_FORCE RUN_TYPE and force-table-specific checks are excluded; ENERGY runs legitimately have no forces. All convergence, one-evaluation, energy, header, native end/footer, abort/fatal, and unresolved-tail checks remain required.",
        },
        "input_contract": {"run_type_records": run_types, "restart_filename_records": wfn_names,
                           "scf_guess_records": guesses, "block_errors": input_errors},
        "native_contract": {"global_run_types": global_runs, "td_output_present": not no_td_native,
                            "restart_read_lines": restart_read_lines, "restart_guess_lines": restart_guess_lines,
                            "density_guess_records": density_guesses,
                            "atomic_guess_lines": atomic_guess_lines, "first_scf_work_lines": scf_start_lines,
                            "optimization_lines": opt_lines,
                            "force_table_heading_lines_unexpected_for_energy_only": force_headings},
        "evaluation": None if ev is None else {"energy_total_Ha": ev.get("energy_total_Ha"),
            "scf_energies_Ha": ev.get("scf_energies_Ha"), "scf_events": ev.get("scf_events"),
            "outer_scf_events": ev.get("outer_scf_events"), "line_start": ev.get("line_start"),
            "line_end": ev.get("line_end")},
        "energy_relation_diagnostic": energy_consistency,
        "parser_diagnostic": {"stage": parsed.get("stage"), "errors": parsed.get("errors", []),
            "warnings": parsed.get("warnings", []), "unresolved_tail_events": parsed.get("unresolved_tail_events", []),
            "stage_file_diagnostic": parsed.get("stage_file_diagnostic")},
        "external_evidence": {"restart_source_bytes_sha_and_source_job": "not checked by helper",
            "actual_seed_read_proof_authentication": "native text line only; not independently authenticated",
            "runtime_binary_module_data_identity": "not checked by helper",
            "slurm_state_and_cost": "not checked by helper",
            "geometry_provenance": "input syntax only; not independently authenticated"},
        "science_validated": False,
        "gold_eligible": False,
        "scope": "Author-side GS ENERGY syntax diagnostic only; not a scorer, provenance validator, or scientific acceptance result.",
    }


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _output_alias_error(output: Path | None, sources: list[Path]) -> str | None:
    if output is None:
        return None
    out_resolved = output.resolve(strict=False)
    for source in sources:
        if out_resolved == source.resolve(strict=False):
            return f"output aliases protected source: {source}"
        try:
            if output.exists() and source.exists() and os.path.samefile(output, source):
                return f"output inode aliases protected source: {source}"
        except OSError:
            return f"cannot safely distinguish output from protected source: {source}"
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--native", required=True, type=Path)
    ap.add_argument("--expected-atoms", type=int, default=192)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args(argv)
    sources = [args.input, args.native]
    alias = _output_alias_error(args.output, sources)
    if alias:
        print(json.dumps({"helper": "case07-gs-energy-author-review/v1", "error": alias,
                          "science_validated": False}, indent=2))
        return 2
    try:
        input_raw, native_raw = args.input.read_bytes(), args.native.read_bytes()
        result = inspect_text(input_raw.decode("utf-8"), native_raw.decode("utf-8"), args.expected_atoms)
        result["input"] = {"path": str(args.input), "sha256": hashlib.sha256(input_raw).hexdigest()}
        result["native"] = {"path": str(args.native), "sha256": hashlib.sha256(native_raw).hexdigest()}
        rendered = json.dumps(_json_safe(result), indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0 if result["strict_syntax_complete"] else 1
    except (OSError, UnicodeError, ValueError) as exc:
        rendered = json.dumps({"helper": "case07-gs-energy-author-review/v1", "error": str(exc),
                               "science_validated": False}, indent=2, allow_nan=False) + "\n"
        if args.output:
            alias = _output_alias_error(args.output, sources)
            if not alias:
                try:
                    args.output.write_text(rendered, encoding="utf-8")
                except OSError:
                    print(rendered, end="")
            else:
                print(rendered, end="")
        else:
            print(rendered, end="")
        return 2


if __name__ == "__main__":
    sys.exit(main())
