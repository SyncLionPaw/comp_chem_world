#!/usr/bin/env python3
"""Author-side syntax review for a fixed-R, selected-state S1 ENERGY output.

This is not a scorer and does not authenticate restart bytes/provenance,
geometry, executable/runtime identity, scheduler records, or scientific quality.
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

from inspect_gs_energy import inspect_text as inspect_gs_text
from parse_workflow import ENERGY_RE, STATE_RE, parse_text

FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
RUN_RE = re.compile(r"^\s*RUN_TYPE\s+(\S+)\s*$", re.I)
ENERGY_BLOCK_RE = re.compile(r"^\s*!-+\s*Excited State Energy\s*-+!\s*$", re.I)
RESULT_STATE_RE = re.compile(r"^\s*Results for Excited State Nr\.\s*(\d+)\s*$", re.I)
NATIVE_KERNEL_RE = re.compile(r"^\s*KERNEL\|\s*(FULL|sTDA)\s*$", re.I)
NATIVE_SPIN_RE = re.compile(r"^\s*KERNEL\|\s*Spin symmetry of excitations\s+(Singlet|Triplet)\s*$", re.I)
EXCITATION_RE = re.compile(rf"^\s*Excitation Energy\s+\[Hartree\]\s+({FLOAT})\s*$", re.I)
EXCITED_TOTAL_RE = re.compile(rf"^\s*Total Energy\s+\[Hartree\]\s+({FLOAT})\s*$", re.I)
SCF_TOTAL_RE = re.compile(rf"^\s*Total energy:\s*({FLOAT})\s*$", re.I)
RESTART_READ_RE = re.compile(r"^\s*WFN_RESTART\|\s*Restart file\s+seed\.wfn\s+read\s*$", re.I)
RESTART_GUESS_RE = re.compile(r"Density guess:\s*RESTART\b", re.I)
ANY_GUESS_RE = re.compile(r"Density guess:\s*(\S+)", re.I)
BAD_GUESS_RE = re.compile(r"Density guess:\s*(?:ATOMIC|CORE|ATOMIC_DENSITY)\b|\busing atomic guess\b", re.I)
FORCE_TITLE_RE = re.compile(r"^\s*(?:ATOMIC\s+FORCES\b|FORCES\|\s*Atomic forces\b|FORCES\s+\[a\.u\.\])", re.I)


class ReviewError(ValueError):
    pass


def _input_records(text: str) -> dict:
    stack: list[str] = []
    runs, blocks, keywords = [], [], []
    errors = []
    lines = text.splitlines()
    for n, raw in enumerate(lines, 1):
        line = raw.split("!", 1)[0].split("#", 1)[0]
        if re.match(r"^\s*@", line):
            errors.append(f"active preprocessor directive at line {n}")
        run = RUN_RE.match(line)
        if run:
            runs.append({"value": run[1].upper(), "path": list(stack), "line": n})
        opening = re.match(r"^\s*&\s*([A-Z][A-Z0-9_]*)(?:\s+(.*))?$", line, re.I)
        close = re.match(r"^\s*&\s*END(?:\s+([A-Z][A-Z0-9_]*))?\s*$", line, re.I)
        if close:
            if not stack:
                errors.append(f"unexpected END at line {n}")
            else:
                name = close[1].upper() if close[1] else None
                top = stack.pop()
                if name and top != name:
                    errors.append(f"mismatched END at line {n}: expected {top}, found {name}")
            continue
        if opening:
            name, args = opening[1].upper(), opening[2] or ""
            path = tuple(stack + [name])
            content = []
            depth = 1
            for later in lines[n:]:
                active = later.split("!", 1)[0].split("#", 1)[0]
                if re.match(r"^\s*&\s*END(?:\s+[A-Z][A-Z0-9_]*)?\s*$", active, re.I):
                    depth -= 1
                    if depth == 0:
                        break
                elif re.match(r"^\s*&\s*[A-Z][A-Z0-9_]*(?:\s+.*)?$", active, re.I):
                    depth += 1
                content.append(active.strip())
            blocks.append({"name": name, "args": args.strip(), "path": path, "line": n, "content": content})
            stack.append(name)
            continue
        for key in ("STATE", "NSTATES", "KERNEL", "RKS_TRIPLETS", "WFN_RESTART_FILE_NAME", "SCF_GUESS"):
            match = re.match(rf"^\s*{key}\s+(\S+)\s*$", line, re.I)
            if match:
                keywords.append({"key": key, "value": match[1], "path": list(stack), "line": n})
    if stack:
        errors.append("unclosed blocks: " + "/".join(stack))
    return {"run_types": runs, "blocks": blocks, "keywords": keywords, "errors": errors}


def _number(token: str) -> Decimal:
    value = Decimal(token.replace("D", "E").replace("d", "e"))
    if not value.is_finite():
        raise InvalidOperation("non-finite token")
    return value


def _half_ulp(token: str) -> Decimal:
    return Decimal("0.5").scaleb(_number(token).as_tuple().exponent)


def _energy_block(lines: list[str]) -> dict:
    marks = [i for i, line in enumerate(lines) if ENERGY_BLOCK_RE.match(line)]
    if len(marks) != 1:
        return {"passed": False, "reason": f"expected one Excited State Energy block, found {len(marks)}", "line": None}
    start = marks[0]
    finish = next((i for i in range(start + 1, len(lines)) if re.match(r"^\s*!-+\s*!\s*$", lines[i])), None)
    if finish is None:
        return {"passed": False, "reason": "missing Excited State Energy block terminator", "line": start + 1}
    excitations = [(i, m[1]) for i in range(start + 1, finish) if (m := EXCITATION_RE.match(lines[i]))]
    totals = [(i, m[1]) for i in range(start + 1, finish) if (m := EXCITED_TOTAL_RE.match(lines[i]))]
    states = [(i, int(m[1])) for i in range(start + 1, finish) if (m := RESULT_STATE_RE.match(lines[i]))]
    if len(excitations) != 1 or len(totals) != 1 or len(states) != 1:
        return {"passed": False, "reason": "block context must identify one selected state and contain one excitation and total energy", "line": start + 1}
    if not (states[0][0] < excitations[0][0] < totals[0][0]):
        return {"passed": False, "reason": "selected state, excitation, and S1 total are out of order", "line": start + 1}
    return {"passed": True, "line_start": start + 1, "line_end": finish + 1,
            "selected_state": states[0][1], "selected_state_line": states[0][0] + 1,
            "excitation_line": excitations[0][0] + 1, "excitation_token_Ha": excitations[0][1],
            "total_line": totals[0][0] + 1, "total_token_Ha": totals[0][1]}


def _calc_energy_checks(native: str, parsed_energy: float, excited: dict, evaluation: dict) -> dict:
    lines = native.splitlines()
    final_marks = [(i + 1, m[1]) for i, line in enumerate(lines) if (m := ENERGY_RE.match(line))]
    scf_marks = [(i + 1, m[1]) for i, line in enumerate(lines) if (m := SCF_TOTAL_RE.match(line))]
    if len(final_marks) != 1 or not excited.get("passed") or not scf_marks:
        return {"passed": False, "reason": "need one final ENERGY, one parsed S1 energy block, and SCF total"}
    e_line, e_token = final_marks[0]
    x_line, x_token = excited["total_line"], excited["total_token_Ha"]
    w_line, w_token = excited["excitation_line"], excited["excitation_token_Ha"]
    last_scf_line, scf_token = scf_marks[-1]
    td_state_lines = [i + 1 for i, line in enumerate(lines) if STATE_RE.match(line)]
    td_table_last = max(td_state_lines) if td_state_lines else None
    td_table_first = min(td_state_lines) if td_state_lines else None
    if not (last_scf_line < (td_table_first or 0) <= (td_table_last or 0) < excited["selected_state_line"] < w_line < x_line < e_line):
        return {"passed": False, "reason": "SCF E0, excitation, excited total, final ENERGY must occur in that order",
                "last_scf_total_line": last_scf_line, "excitation_line": w_line,
                "td_state_table_first_line": td_table_first, "td_state_table_last_line": td_table_last,
                "selected_state_line": excited.get("selected_state_line"),
                "excited_total_line": x_line, "final_energy_line": e_line}
    try:
        e0, omega, s1, final = map(_number, (scf_token, w_token, x_token, e_token))
        rounding_e0_omega = _half_ulp(scf_token) + _half_ulp(w_token) + _half_ulp(x_token)
        rounding_s1 = _half_ulp(x_token)
        rounding_final = _half_ulp(e_token) + _half_ulp(x_token)
        sum_delta = abs((e0 + omega) - s1)
        final_delta = abs(final - s1)
        parser_equal = math.isfinite(parsed_energy) and float(final) == parsed_energy
    except (InvalidOperation, ValueError, OverflowError):
        return {"passed": False, "reason": "non-finite or invalid energy token"}
    state_rows = []
    for i, line in enumerate(lines, 1):
        match = STATE_RE.match(line)
        if match:
            state_rows.append({"state": int(match[1]), "energy_eV_token": match[2], "line": i})
    selected_td = [row for row in state_rows if row["state"] == 1]
    if len(selected_td) != 1:
        return {"passed": False, "reason": "native TDDFPT output must contain exactly one state-1 energy row",
                "selected_state_rows": selected_td}
    try:
        td_eV = _number(selected_td[0]["energy_eV_token"])
        # CP2K v2024.3 src/common/physcon.F defines evolt from CODATA-2006
        # constants (https://github.com/cp2k/cp2k/blob/v2024.3/src/common/physcon.F).
        # This conversion only cross-checks printed representations; the combined
        # half-ULP envelope includes both native decimal fields and float rounding.
        evolt = Decimal("27.2113838565563")
        converted_delta = abs(omega * evolt - td_eV)
        converted_envelope = _half_ulp(w_token) * evolt + _half_ulp(selected_td[0]["energy_eV_token"]) + Decimal("1e-14")
    except (InvalidOperation, ValueError, OverflowError):
        return {"passed": False, "reason": "selected TD state energy is non-finite or invalid"}
    passed = (omega >= 0 and excited.get("selected_state") == 1 and
              sum_delta <= rounding_e0_omega and final_delta <= rounding_final and
              converted_delta <= converted_envelope and parser_equal)
    return {"passed": passed, "E0_token_Ha": scf_token, "omega_token_Ha": w_token,
            "S1_total_token_Ha": x_token, "final_ENERGY_token_Ha": e_token,
            "E0_plus_omega_delta_Ha": float(sum_delta), "E0_plus_omega_rounding_envelope_Ha": float(rounding_e0_omega),
            "final_ENERGY_vs_S1_total_delta_Ha": float(final_delta),
            "td_state1_energy_eV_token": selected_td[0]["energy_eV_token"],
            "omega_vs_td_state1_delta_eV": float(converted_delta),
            "omega_vs_td_state1_printed_rounding_envelope_eV": float(converted_envelope),
            "final_ENERGY_rounding_envelope_Ha": float(rounding_final),
            "line_numbers": {"E0": last_scf_line, "excitation": w_line, "S1_total": x_line, "ENERGY": e_line},
            "method": "Printed-token Decimal rounding envelope only; state-unit conversion uses CP2K v2024.3 CODATA-2006 evolt; no scientific tolerance."}


def inspect_text(input_text: str, native_text: str, expected_atoms: int = 192) -> dict:
    shared = inspect_gs_text(input_text, native_text, expected_atoms=expected_atoms)
    parsed = parse_text(native_text, expected_atoms=expected_atoms, expected_states=8, stage="ENERGY")
    evaluations = parsed.get("evaluations", [])
    ev = evaluations[0] if len(evaluations) == 1 else None
    records = _input_records(input_text)
    all_excited_blocks = [b for b in records["blocks"] if b["name"] == "EXCITED_STATES"]
    all_td_blocks = [b for b in records["blocks"] if b["name"] == "TDDFPT"]
    excited_blocks = [b for b in all_excited_blocks if b["path"] == ("FORCE_EVAL", "DFT", "EXCITED_STATES")]
    td_blocks = [b for b in all_td_blocks if b["path"] == ("FORCE_EVAL", "PROPERTIES", "TDDFPT")]
    direct = records["keywords"]
    selected = [int(k["value"]) for k in direct if k["key"] == "STATE" and
                k["path"] == ["FORCE_EVAL", "DFT", "EXCITED_STATES"] and k["value"].isdigit()]
    nstates_values = [int(k["value"]) for k in direct if k["key"] == "NSTATES" and
                      k["path"] == ["FORCE_EVAL", "PROPERTIES", "TDDFPT"] and k["value"].isdigit()]
    kernels = [k["value"].upper() for k in direct if k["key"] == "KERNEL" and
               k["path"] == ["FORCE_EVAL", "PROPERTIES", "TDDFPT"]]
    triplet_flags = [k["value"].upper() for k in direct if k["key"] == "RKS_TRIPLETS" and
                     k["path"] == ["FORCE_EVAL", "PROPERTIES", "TDDFPT"]]
    wfn_names = [k for k in direct if k["key"] == "WFN_RESTART_FILE_NAME"]
    guesses = [k for k in direct if k["key"] == "SCF_GUESS"]
    input_restart = (len(wfn_names) == 1 and wfn_names[0]["value"] == "seed.wfn" and
                     wfn_names[0]["path"] == ["FORCE_EVAL", "DFT"] and len(guesses) == 1 and
                     guesses[0]["value"].upper() == "RESTART" and
                     guesses[0]["path"] == ["FORCE_EVAL", "DFT", "SCF"])
    native_kernels = [m[1].upper() for line in native_text.splitlines() if (m := NATIVE_KERNEL_RE.match(line))]
    native_spins = [m[1].upper() for line in native_text.splitlines() if (m := NATIVE_SPIN_RE.match(line))]
    input_run_energy = (len(records["run_types"]) == 1 and records["run_types"][0]["value"] == "ENERGY" and
                        records["run_types"][0]["path"] == ["GLOBAL"])
    input_selected_state = (len(all_excited_blocks) == len(excited_blocks) == 1 and selected == [1] and
                            excited_blocks[0]["args"].upper() == "T")
    input_td8 = (len(all_td_blocks) == len(td_blocks) == 1 and td_blocks[0]["args"].upper() in ("", "T") and nstates_values == [8] and
                 len(kernels) == 1 and kernels[0] in ("FULL", "STDA"))
    energy_block = _energy_block(native_text.splitlines())
    e_consistency = _calc_energy_checks(native_text, ev.get("energy_total_Ha", float("nan")) if ev else float("nan"),
                                        energy_block, ev or {})
    common = shared.get("common_validator", {})
    common_results = common.get("selected_results", {})
    native_runs = shared.get("native_contract", {}).get("global_run_types", [])
    common_gate = (common.get("actual_common_keyset_matches_contract") is True and
                   all(common_results.values()))
    no_force_output = not any(FORCE_TITLE_RE.match(line) for line in native_text.splitlines())
    state_checks = (ev or {}).get("state_checks", {})
    td_ok = ((ev or {}).get("convergence_flags", {}).get("td") is True and
             state_checks.get("count") == 8 and not state_checks.get("duplicate_ids") and
             not state_checks.get("missing_expected_ids") and state_checks.get("ordered") is True and
             state_checks.get("finite") is True and state_checks.get("nonnegative_energy_and_f") is True)
    checks = {
        "common_native_scf_end_and_file_checks_pass": common_gate,
        "input_global_run_type_energy": input_run_energy,
        "native_global_run_type_energy": native_runs == ["ENERGY"],
        "all_energy_headings_well_formed_and_attached": shared.get("checks", {}).get("finite_final_energy_and_ordered_scf_total_record") is True,
        "fixed_geometry_single_evaluation_no_opt_steps": shared.get("checks", {}).get("fixed_r_single_energy_evaluation_with_no_opt_steps") is True,
        "selected_state_one_requested": input_selected_state,
        "td_states_eight_full_or_stda_requested": input_td8,
        "input_declares_named_restart_and_restart_guess": input_restart,
        "native_kernel_matches_input_kernel": len(native_kernels) == 1 and len(kernels) == 1 and native_kernels == kernels,
        "singlet_input_and_native_symmetry": triplet_flags == ["F"] and native_spins == ["SINGLET"],
        "td_converged_and_eight_ordered_finite_states": td_ok,
        "native_excited_energy_block_and_e0_plus_omega_consistent": bool(e_consistency.get("passed")),
        "native_restart_read_before_scf_without_fallback": shared.get("checks", {}).get("native_positive_seed_wfn_read_before_scf_without_atomic_guess") is True,
        "no_active_preprocessor_directives_or_malformed_input": not records["errors"] and shared.get("checks", {}).get("input_has_no_active_preprocessor_directives") is True,
        "force_headings_absent_for_energy_only": no_force_output,
    }
    failed = [name for name, value in checks.items() if not value]
    return {"helper": "case07-s1-energy-author-review/v1", "stage": "S1_ENERGY", "expected_atoms": expected_atoms,
            "checks": checks, "strict_syntax_complete": not failed, "failed_checks": failed,
            "input_contract": {"run_type_records": records["run_types"], "selected_state_records": selected,
                "restart_file_records": wfn_names, "scf_guess_records": guesses,
                "tddfpt_blocks": [{"path": list(b["path"]), "args": b["args"], "content": b["content"]} for b in td_blocks],
                "block_errors": records["errors"]},
            "native_contract": {"native_global_run_types": native_runs,
                "td_convergence_flag": (ev or {}).get("convergence_flags", {}).get("td"),
                "native_kernel_records": native_kernels,
                "native_spin_symmetry_records": native_spins,
                "td_state_checks": state_checks, "state_ids": [s.get("state") for s in (ev or {}).get("states", [])],
                "selected_state_1_output_record": next((s for s in (ev or {}).get("states", []) if s.get("state") == 1), None),
                "excited_energy_block": energy_block,
                "energy_block_state_identity": "Native Results for Excited State Nr. must explicitly identify state 1; it is cross-checked against native TDDFPT state-1 energy."},
            "evaluation": None if ev is None else {"energy_total_Ha": ev.get("energy_total_Ha"),
                "scf_energies_Ha": ev.get("scf_energies_Ha"), "scf_events": ev.get("scf_events"),
                "outer_scf_events": ev.get("outer_scf_events"), "line_start": ev.get("line_start"), "line_end": ev.get("line_end")},
            "s1_energy_consistency": e_consistency,
            "common_validator": {"name": "inspect_gs_energy.inspect_text + inspect_full_scf common subset",
                "selected_common_results": common_results, "science_semantics": "GS-only comparisons are excluded; their S1 energy identity is validated separately."},
            "external_evidence": {"restart_source_hash_and_job": "not checked", "actual_seed_read_authentication": "native line only; not authenticated",
                "geometry/runtime/binary/data/Slurm/cost": "not checked"},
            "science_validated": False, "gold_eligible": False,
            "scope": "Author syntax and printed energy identity diagnostic only; no force-response solver or scientific accuracy acceptance."}


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value): return None
    if isinstance(value, dict): return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list): return [_json_safe(v) for v in value]
    return value


def _output_alias(output: Path | None, sources: list[Path]) -> bool:
    if output is None: return False
    out = output.resolve(strict=False)
    for source in sources:
        if out == source.resolve(strict=False): return True
        try:
            if output.exists() and source.exists() and os.path.samefile(output, source): return True
        except OSError: return True
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--native", required=True, type=Path)
    ap.add_argument("--expected-atoms", type=int, default=192)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args(argv)
    sources = [args.input, args.native]
    if _output_alias(args.output, sources):
        print(json.dumps({"helper": "case07-s1-energy-author-review/v1", "error": "output aliases protected source", "science_validated": False}, indent=2))
        return 2
    try:
        inp, native = args.input.read_bytes(), args.native.read_bytes()
        result = inspect_text(inp.decode("utf-8"), native.decode("utf-8"), args.expected_atoms)
        result["input"] = {"path": str(args.input), "sha256": hashlib.sha256(inp).hexdigest()}
        result["native"] = {"path": str(args.native), "sha256": hashlib.sha256(native).hexdigest()}
        rendered = json.dumps(_json_safe(result), indent=2, allow_nan=False) + "\n"
        if args.output: args.output.write_text(rendered, encoding="utf-8")
        else: print(rendered, end="")
        return 0 if result["strict_syntax_complete"] else 1
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"helper": "case07-s1-energy-author-review/v1", "error": str(exc), "science_validated": False}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
