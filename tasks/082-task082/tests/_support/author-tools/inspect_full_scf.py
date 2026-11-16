#!/usr/bin/env python3
"""Strict author-side syntax review for one fixed-geometry CP2K ENERGY_FORCE run.

This wraps parse_workflow.py and adds deliberately strict terminal-text checks.
It is not a scorer: input/native syntax cannot authenticate HPC execution,
restart use, runtime identity, geometry identity, or scientific validity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

from parse_workflow import ENERGY_RE, parse_text

ENERGY_FAMILY_RE = re.compile(r"^\s*ENERGY\|\s*Total FORCE_EVAL(?:\s*\([^)]*\))?(.*)$", re.I)
SCF_TOTAL_TOKEN_RE = re.compile(r"^\s*Total energy:\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?\s*$", re.I)
SCF_TOTAL_HEADING_RE = re.compile(r"^\s*Total energy\s*:", re.I)


def _input_contract(text: str) -> dict:
    """Recognize RUN_TYPE and require OUTER_SCF nested inside an SCF block."""
    active_lines = []
    for line in text.splitlines():
        # CP2K comments begin with !; tolerate # comments in locally generated
        # snippets as well, without treating a commented keyword as evidence.
        line = line.split("!", 1)[0].split("#", 1)[0]
        if line.strip():
            active_lines.append(line)

    run_types = []
    run_type_contexts = []
    stack: list[str] = []
    outer_scf_paths = []
    malformed_blocks = []
    for line_number, line in enumerate(active_lines, 1):
        m = re.match(r"\s*RUN_TYPE\s+(\S+)", line, re.I)
        if m:
            run_types.append(m.group(1).upper())
            run_type_contexts.append({"value": m.group(1).upper(), "path": list(stack)})
        close = re.match(r"\s*&\s*END(?:\s+([A-Z][A-Z0-9_]*))?\s*$", line, re.I)
        if close:
            name = close.group(1).upper() if close.group(1) else None
            if not stack:
                malformed_blocks.append({"line": line_number, "reason": "unexpected_end", "name": name})
            else:
                top = stack.pop()
                if name and name != top:
                    malformed_blocks.append({"line": line_number, "reason": "mismatched_end", "expected": top, "found": name})
            continue
        opening = re.match(r"\s*&\s*([A-Z][A-Z0-9_]*)(?:\s+.*)?$", line, re.I)
        if opening:
            name = opening.group(1).upper()
            if name == "OUTER_SCF":
                outer_scf_paths.append(list(stack))
            stack.append(name)
    if stack:
        malformed_blocks.append({"reason": "unclosed_blocks", "names": stack})
    return {
        "run_types": run_types,
        "run_type_contexts": run_type_contexts,
        "run_type_energy_force": (run_type_contexts == [{"value": "ENERGY_FORCE", "path": ["GLOBAL"]}]),
        "outer_scf_paths": outer_scf_paths,
        "outer_scf_configured_inside_scf": outer_scf_paths == [["FORCE_EVAL", "DFT", "SCF"]],
        "block_structure_well_formed": not malformed_blocks,
        "block_errors": malformed_blocks,
    }


def inspect_text(input_text: str, native_text: str, expected_atoms: int = 192) -> dict:
    contract = _input_contract(input_text)
    parsed = parse_text(native_text, expected_atoms=expected_atoms, stage="auto")
    evaluations = parsed.get("evaluations", [])
    single = len(evaluations) == 1
    ev = evaluations[0] if single else None

    scf_events = ev.get("scf_events", []) if ev else []
    outer_events = ev.get("outer_scf_events", []) if ev else []
    scf_positive = bool(scf_events) and all(item.get("kind") == "converged" for item in scf_events)
    outer_positive = (contract["outer_scf_configured_inside_scf"] and bool(outer_events) and
                      all(not re.search(r"\bnot\s+converged\b", item.get("text", ""), re.I)
                          and re.search(r"outer SCF loop\s+converged\b", item.get("text", ""), re.I)
                          for item in outer_events))
    e0 = ev.get("scf_energies_Ha", []) if ev else []
    finite_e0 = bool(e0) and all(math.isfinite(x) for x in e0) and math.isfinite(e0[-1])
    finite_energy = bool(ev and ev.get("finite_energy") and math.isfinite(ev.get("energy_total_Ha", float("nan"))))
    energy_heading_lines = []
    malformed_energy_lines = []
    for line_number, line in enumerate(native_text.splitlines(), 1):
        family = ENERGY_FAMILY_RE.match(line)
        if not family:
            continue
        descriptor = family.group(1).strip().lower()
        if descriptor.startswith("gap") or descriptor.startswith("free energy"):
            continue
        energy_heading_lines.append(line_number)
        match = ENERGY_RE.match(line)
        if not match:
            malformed_energy_lines.append(line_number)
            continue
        try:
            if not math.isfinite(float(match.group(1).replace("D", "E").replace("d", "e"))):
                malformed_energy_lines.append(line_number)
        except (ValueError, OverflowError):
            malformed_energy_lines.append(line_number)
    energy_headings_attached = (not malformed_energy_lines and len(energy_heading_lines) == len(evaluations))
    scf_total_headings = [line for line in native_text.splitlines() if SCF_TOTAL_HEADING_RE.match(line)]
    def finite_scf_total(line: str) -> bool:
        match = SCF_TOTAL_TOKEN_RE.match(line)
        if not match:
            return False
        try:
            return math.isfinite(float(line.split(":", 1)[1].strip().replace("D", "E").replace("d", "e")))
        except ValueError:
            return False
    scf_totals_well_formed = bool(scf_total_headings) and all(finite_scf_total(line) for line in scf_total_headings)
    errors = parsed.get("errors", [])
    no_errors = not errors

    native_lines = native_text.splitlines()
    start_lines = [i + 1 for i, line in enumerate(native_lines)
                   if re.search(r"PROGRAM STARTED AT", line, re.I)]
    end_lines = [i + 1 for i, line in enumerate(native_lines)
                 if re.search(r"PROGRAM ENDED AT", line, re.I)]
    stop_lines = [i + 1 for i, line in enumerate(native_lines)
                  if re.search(r"PROGRAM STOPPED IN", line, re.I)]
    normal_end = bool(parsed.get("program_ended")) and len(start_lines) == 1 and len(end_lines) == 1 and len(stop_lines) == 1
    footer = native_lines[end_lines[0] - 1:] if len(end_lines) == 1 else []
    footer_fields = ("PROGRAM RAN ON", "PROGRAM RAN BY", "PROGRAM PROCESS ID", "PROGRAM STOPPED IN")
    footer_complete = all(any(field in line.upper() for line in footer) for field in footer_fields)
    # The footer must contain the canonical fields in order. Between fields,
    # only blank lines are allowed; after STOPPED IN, CP2K may wrap the path
    # onto deeply indented path-only lines (including the very next line).
    footer_counts = {field: sum(field in line.upper() for line in footer) for field in footer_fields}
    footer_positions = []
    for field in footer_fields:
        positions = [i for i, line in enumerate(footer) if field in line.upper()]
        if len(positions) == 1:
            footer_positions.append(positions[0])
    footer_ordered = len(footer_positions) == len(footer_fields) and footer_positions == sorted(footer_positions)
    post_stop_lines = footer[footer_positions[-1] + 1:] if footer_ordered else []
    post_stop_is_path_wrap = all(
        not line.strip() or (
            re.fullmatch(r"\s{20,}[A-Za-z0-9_.\-/]+\s*", line) and
            not re.search(r"\b(?:RESTART|SCF|ENERGY|FORCES|ABORT|ERROR|WARNING|PROGRAM)\b", line, re.I)
        )
        for line in post_stop_lines
    )
    footer_interstitial_clean = False
    if footer_ordered:
        end_of_stop_line = footer_positions[-1]
        allowed_positions = {0, *footer_positions}  # include the PROGRAM ENDED AT line
        footer_interstitial_clean = all(
            not line.strip() or i in allowed_positions
            for i, line in enumerate(footer[:end_of_stop_line + 1])
        )
    footer_complete = (footer_complete and all(count == 1 for count in footer_counts.values()) and
                       footer_ordered and footer_interstitial_clean and post_stop_is_path_wrap)
    end_after_eval = bool(ev and len(end_lines) == 1 and end_lines[0] > ev.get("line_end", 0))
    start_before_eval = bool(ev and len(start_lines) == 1 and start_lines[0] < ev.get("line_end", 0))
    no_abort = not parsed.get("aborted", False)
    no_unresolved = not parsed.get("unresolved_tail_events")

    opt_step_lines = [i + 1 for i, line in enumerate(native_text.splitlines())
                      if re.search(r"\bOPT\|\s*Step number\b", line, re.I)]
    one_fixed_energy_force_eval = (contract["run_type_energy_force"] and single and not opt_step_lines and
                                   parsed.get("header_atom_count") == expected_atoms)

    force_blocks = ev.get("force_blocks", []) if ev else []
    # Count every recognizable force-table title, including malformed units or
    # duplicate tables. A malformed/extra title may not be silently ignored.
    force_heading_lines = [i + 1 for i, line in enumerate(native_lines)
                           if re.search(r"^\s*(?:ATOMIC\s+FORCES\b|FORCES\|\s*Atomic forces\b)", line, re.I)]
    force_lines_inside_eval = (len(force_blocks) == 1 and len(force_heading_lines) == 1 and
                               len(end_lines) == 1 and bool(ev) and
                               all(ev.get("line_end", 0) < b.get("line_start", 0) <= b.get("line_end", 0) < end_lines[0]
                                   for b in force_blocks))
    force_ok = bool(force_blocks) and all(
        len(block.get("atom_ids", [])) == expected_atoms and
        block.get("checks", {}).get("atom_count_matches") is True and
        block.get("checks", {}).get("complete") is True and
        block.get("checks", {}).get("atom_ids_ordered_unique") is True and
        block.get("checks", {}).get("finite") is True
        for block in force_blocks
    ) and force_lines_inside_eval
    force_summary = [{
        "format": b.get("format"),
        "line_start": b.get("line_start"),
        "line_end": b.get("line_end"),
        "row_count": len(b.get("atom_ids", [])),
        "first_atom_id": b.get("atom_ids", [None])[0] if b.get("atom_ids") else None,
        "last_atom_id": b.get("atom_ids", [None])[-1] if b.get("atom_ids") else None,
        "checks": b.get("checks", {}),
    } for b in force_blocks]

    checks = {
        "input_run_type_is_energy_force": contract["run_type_energy_force"],
        "input_outer_scf_configured_inside_scf": contract["outer_scf_configured_inside_scf"],
        "input_block_structure_well_formed": contract["block_structure_well_formed"],
        "run_type_declared_under_global": contract["run_type_energy_force"],
        "native_header_atom_count_matches_expected": parsed.get("header_atom_count") == expected_atoms,
        "exactly_one_energy_evaluation": single,
        "fixed_geometry_energy_force_no_opt_step": one_fixed_energy_force_eval,
        "finite_final_energy_record": finite_energy,
        "all_energy_headings_well_formed_and_attached": energy_headings_attached,
        "all_scf_total_headings_finite_and_well_formed": scf_totals_well_formed,
        "finite_scf_e0_record": finite_e0,
        "positive_inner_scf_convergence_events": scf_positive,
        "positive_configured_outer_scf_convergence_events": outer_positive,
        "complete_finite_ordered_force_blocks_before_end": force_ok,
        "one_native_start_and_end_with_footer_after_evaluation": normal_end and start_before_eval and end_after_eval and footer_complete,
        "no_abort_or_nonconvergence_errors": no_abort and no_errors,
        "no_unresolved_tail_events": no_unresolved,
        "no_fortran_fatal_or_error_text": not bool(re.search(r"\bforrtl:\s*(?:severe|fatal)|\bFATAL ERROR\b|\bMPI_ABORT\b", native_text, re.I)),
    }
    failures = [key for key, value in checks.items() if not value]
    return {
        "helper": "case07-full-scf-author-review/v1",
        "stage": "ENERGY_FORCE",
        "expected_atoms": expected_atoms,
        "input_contract": contract,
        "checks": checks,
        "strict_syntax_complete": not failures,
        "failed_checks": failures,
        "evaluation": None if not ev else {
            "index": ev.get("index"), "line_start": ev.get("line_start"), "line_end": ev.get("line_end"),
            "energy_total_Ha": ev.get("energy_total_Ha"), "scf_energies_Ha": e0,
            "scf_events": scf_events, "outer_scf_events": outer_events,
            "force_blocks": force_summary,
        },
        "native_end_lines": end_lines,
        "native_start_lines": start_lines,
        "native_stop_lines": stop_lines,
        "native_end_footer_fields": {field: any(field in line.upper() for line in footer) for field in footer_fields},
        "opt_step_lines": opt_step_lines,
        "parser_diagnostic": {
            "stage": parsed.get("stage"),
            "stage_file_diagnostic": parsed.get("stage_file_diagnostic"),
            "errors": errors,
            "warnings": parsed.get("warnings", []),
            "unresolved_tail_events": parsed.get("unresolved_tail_events", []),
        },
        "external_evidence": {
            "launcher_exit_status": "not_checked_by_helper",
            "slurm_parent_and_step_states": "not_checked_by_helper",
            "elapsed_and_allocated_cpu_cost": "not_checked_by_helper",
            "runtime_binary_module_and_data_identity": "not_checked_by_helper",
            "restart_read_and_final_wfn_identity_or_alignment": "not_checked_by_helper",
            "geometry_identity": "not_checked_by_helper",
        },
        "science_validated": False,
        "scope": "Author-side text syntax review only; not a scorer, provenance validator, or scientific acceptance result.",
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
        source_resolved = source.resolve(strict=False)
        if out_resolved == source_resolved:
            return f"output path aliases protected input/native evidence: {source}"
        try:
            if output.exists() and source.exists() and os.path.samefile(output, source):
                return f"output inode aliases protected input/native evidence: {source}"
        except OSError:
            return f"could not safely distinguish output from protected evidence: {source}"
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--native", required=True, type=Path)
    ap.add_argument("--expected-atoms", type=int, default=192)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args(argv)
    sources = [args.input, args.native]
    alias_error = _output_alias_error(args.output, sources)
    if alias_error:
        print(json.dumps({"helper": "case07-full-scf-author-review/v1", "error": alias_error,
                          "science_validated": False}, indent=2, allow_nan=False))
        return 2
    try:
        input_raw = args.input.read_bytes()
        native_raw = args.native.read_bytes()
        result = inspect_text(input_raw.decode(errors="replace"), native_raw.decode(errors="replace"), args.expected_atoms)
        result["input"] = {"path": str(args.input), "sha256": hashlib.sha256(input_raw).hexdigest()}
        result["native"] = {"path": str(args.native), "sha256": hashlib.sha256(native_raw).hexdigest()}
        rendered = json.dumps(_json_safe(result), indent=2, allow_nan=False) + "\n"
        if args.output:
            alias_error = _output_alias_error(args.output, sources)
            if alias_error:
                print(json.dumps({"helper": "case07-full-scf-author-review/v1", "error": alias_error,
                                  "science_validated": False}, indent=2, allow_nan=False))
                return 2
            args.output.write_text(rendered)
        else:
            print(rendered, end="")
        return 0 if result["strict_syntax_complete"] else 1
    except (OSError, UnicodeError, ValueError) as exc:
        error = {"helper": "case07-full-scf-author-review/v1", "error": str(exc), "science_validated": False}
        rendered = json.dumps(error, indent=2, allow_nan=False) + "\n"
        if args.output:
            alias_error = _output_alias_error(args.output, sources)
            if alias_error:
                print(json.dumps({"helper": "case07-full-scf-author-review/v1", "error": alias_error,
                                  "science_validated": False}, indent=2, allow_nan=False))
                return 2
            try:
                args.output.write_text(rendered)
            except OSError:
                # Preserve a structured diagnostic even when the requested
                # destination itself is unavailable; do not retry that path.
                print(rendered, end="")
        else:
            print(rendered, end="")
        return 2


if __name__ == "__main__":
    sys.exit(main())
