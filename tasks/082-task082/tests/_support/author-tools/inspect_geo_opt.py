#!/usr/bin/env python3
"""Strict author-side syntax review for fixed-cell CP2K GS/S1 GEO_OPT runs.

Requires the native output and a complete CP2K XYZ trajectory so the final
geometry is not inferred from a previous force record. This is not a scorer
or scientific acceptance test; geometry identity, state continuity, restart
bytes, runtime provenance, and scientific tolerances remain external.
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

from inspect_gs_energy import _energy_heading_inventory, _energy_record_diagnostic
from inspect_s1_energy import _half_ulp, NATIVE_KERNEL_RE, NATIVE_SPIN_RE
from parse_workflow import ENERGY_RE, STATE_RE, parse_text

FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
RUN_RE = re.compile(r"^\s*RUN_TYPE\s+(\S+)\s*$", re.I)
KEY_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s+(\S+)\s*$", re.I)
OPEN_RE = re.compile(r"^\s*&\s*([A-Z][A-Z0-9_]*)(?:\s+(.*))?$", re.I)
CLOSE_RE = re.compile(r"^\s*&\s*END(?:\s+([A-Z][A-Z0-9_]*))?\s*$", re.I)
COORD_ROW_RE = re.compile(rf"^\s*([A-Za-z][A-Za-z0-9_]*)\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*$")
XYZ_COMMENT_RE = re.compile(rf"\bi\s*=\s*(\d+)\s*,\s*E\s*=\s*({FLOAT})", re.I)
SCF_TOTAL_RE = re.compile(rf"^\s*Total energy:\s*({FLOAT})\s*$", re.I)
SCF_TOTAL_NONFINITE_RE = re.compile(r"^\s*Total energy:\s*[-+]?(?:nan|inf(?:inity)?)\s*$", re.I)
EXCITATION_RE = re.compile(rf"^\s*Excitation Energy\s+\[Hartree\]\s+({FLOAT})\s*$", re.I)
S1_TOTAL_RE = re.compile(rf"^\s*Total Energy\s+\[Hartree\]\s+({FLOAT})\s*$", re.I)
OPT_TOTAL_RE = re.compile(rf"^\s*OPT\|\s*Total energy\s+\[hartree\]\s+({FLOAT})\s*$", re.I)
STATE_ID_RE = re.compile(r"^\s*Results for Excited State Nr\.\s*(\d+)\s*$", re.I)
OPT_STEP_RE = re.compile(r"^\s*OPT\|\s*Step number\s+(\d+)\s*$", re.I)
FORCE_TITLE_RE = re.compile(r"^\s*(?:ATOMIC\s+FORCES\b|FORCES\|\s*Atomic forces\b|FORCES\s+\[a\.u\.\])", re.I)

METRICS = {
    "Maximum step size": "MAX_DR",
    "RMS step size": "RMS_DR",
    "Maximum gradient": "MAX_FORCE",
    "RMS gradient": "RMS_FORCE",
}


def _finite_decimal(token: str) -> Decimal:
    value = Decimal(token.replace("D", "E").replace("d", "e"))
    if not value.is_finite():
        raise InvalidOperation("nonfinite number")
    return value


def _input_records(text: str) -> dict:
    stack: list[str] = []
    blocks: list[dict] = []
    keywords: list[dict] = []
    errors: list[str] = []
    run_types: list[dict] = []
    coord_rows: list[dict] = []
    cell_lines: list[dict] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("!", 1)[0].split("#", 1)[0]
        if re.match(r"^\s*@", line):
            errors.append(f"active preprocessor directive/include at line {n}")
        if m := RUN_RE.match(line):
            run_types.append({"value": m[1].upper(), "path": list(stack), "line": n})
        if m := CLOSE_RE.match(line):
            if not stack:
                errors.append(f"unexpected END at line {n}")
            else:
                top = stack.pop()
                if m[1] and m[1].upper() != top:
                    errors.append(f"mismatched END at line {n}: expected {top}, found {m[1].upper()}")
            continue
        if m := OPEN_RE.match(line):
            name, args = m[1].upper(), (m[2] or "").strip()
            blocks.append({"name": name, "args": args, "path": list(stack + [name]), "line": n})
            stack.append(name)
            continue
        path = list(stack)
        if m := COORD_ROW_RE.match(line):
            if path == ["FORCE_EVAL", "SUBSYS", "COORD"]:
                try:
                    coords = [_finite_decimal(m[i]) for i in (2, 3, 4)]
                    coord_rows.append({"element": m[1], "coords": coords, "line": n})
                except InvalidOperation:
                    errors.append(f"nonfinite coordinate at line {n}")
        elif path == ["FORCE_EVAL", "SUBSYS", "COORD"] and line.strip():
            errors.append(f"unsupported coordinate directive/unit/row at line {n}")
        if path == ["FORCE_EVAL", "SUBSYS", "CELL"] and line.strip():
            cell_lines.append({"line": n, "text": line.strip()})
        if m := KEY_RE.match(line):
            keywords.append({"key": m[1].upper(), "value": m[2], "path": path, "line": n})
    if stack:
        errors.append("unclosed input blocks: " + "/".join(stack))
    return {"run_types": run_types, "blocks": blocks, "keywords": keywords,
            "coord_rows": coord_rows, "cell_lines": cell_lines, "errors": errors}


def _direct(records: dict, key: str, path: list[str]) -> list[dict]:
    return [row for row in records["keywords"] if row["key"] == key and row["path"] == path]


def _input_contract(text: str, mode: str, expected_atoms: int) -> dict:
    r = _input_records(text)
    blocks = r["blocks"]
    run_ok = (len(r["run_types"]) == 1 and r["run_types"][0] ==
              {"value": "GEO_OPT", "path": ["GLOBAL"], "line": r["run_types"][0]["line"]})
    geo_blocks = [b for b in blocks if b["name"] == "GEO_OPT" and b["path"] == ["MOTION", "GEO_OPT"]]
    required_sections = ("GLOBAL", "MOTION", "FORCE_EVAL", "DFT", "SCF", "SUBSYS", "COORD")
    required_paths = {
        "GLOBAL": ["GLOBAL"], "MOTION": ["MOTION"], "FORCE_EVAL": ["FORCE_EVAL"],
        "DFT": ["FORCE_EVAL", "DFT"], "SCF": ["FORCE_EVAL", "DFT", "SCF"],
        "SUBSYS": ["FORCE_EVAL", "SUBSYS"], "COORD": ["FORCE_EVAL", "SUBSYS", "COORD"],
    }
    required_blocks = {name: [b for b in blocks if b["name"] == name and b["path"] == required_paths[name]]
                       for name in required_sections}
    cell_blocks = [b for b in blocks if b["name"] == "CELL" and b["path"] == ["FORCE_EVAL", "SUBSYS", "CELL"]]
    cell_opt = [b for b in blocks if b["name"] == "CELL_OPT"]
    opt_values = {key: _direct(r, key, ["MOTION", "GEO_OPT"]) for key in
                  ("OPTIMIZER", "MAX_ITER", "MAX_FORCE", "RMS_FORCE", "MAX_DR", "RMS_DR")}
    try:
        opt_name = opt_values["OPTIMIZER"][0]["value"].upper() if len(opt_values["OPTIMIZER"]) == 1 else None
        max_iter_token = opt_values["MAX_ITER"][0]["value"] if len(opt_values["MAX_ITER"]) == 1 else None
        max_iter = int(max_iter_token) if max_iter_token is not None and re.fullmatch(r"\d+", max_iter_token) else None
        criteria = {}
        for metric, key in (("MAX_FORCE", "Maximum gradient"), ("RMS_FORCE", "RMS gradient"),
                            ("MAX_DR", "Maximum step size"), ("RMS_DR", "RMS step size")):
            vals = opt_values[metric]
            token = vals[0]["value"] if len(vals) == 1 else None
            number = _finite_decimal(token) if token is not None else None
            criteria[metric] = {"token": token, "value": number, "native_metric": key,
                                "valid": number is not None and number > 0}
    except (InvalidOperation, ValueError, OverflowError):
        opt_name, max_iter, criteria = None, None, {}
    outer = [b for b in blocks if b["name"] == "OUTER_SCF" and b["path"] == ["FORCE_EVAL", "DFT", "SCF", "OUTER_SCF"]]
    excited = [b for b in blocks if b["name"] == "EXCITED_STATES"]
    td = [b for b in blocks if b["name"] == "TDDFPT"]
    direct_kw = r["keywords"]
    s1_state = [k["value"] for k in direct_kw if k["key"] == "STATE" and k["path"] == ["FORCE_EVAL", "DFT", "EXCITED_STATES"]]
    nstates = [k["value"] for k in direct_kw if k["key"] == "NSTATES" and k["path"] == ["FORCE_EVAL", "PROPERTIES", "TDDFPT"]]
    kernels = [k["value"].upper() for k in direct_kw if k["key"] == "KERNEL" and k["path"] == ["FORCE_EVAL", "PROPERTIES", "TDDFPT"]]
    triplets = [k["value"].upper() for k in direct_kw if k["key"] == "RKS_TRIPLETS" and k["path"] == ["FORCE_EVAL", "PROPERTIES", "TDDFPT"]]
    enabled = lambda block: block["args"].upper() in ("", "T", "ON")
    mode_ok = ((mode == "GS" and not excited and not td) or
               (mode == "S1" and len(excited) == 1 and excited[0]["path"] == ["FORCE_EVAL", "DFT", "EXCITED_STATES"]
                and excited[0]["args"].upper() == "T" and s1_state == ["1"]
                and len(td) == 1 and td[0]["path"] == ["FORCE_EVAL", "PROPERTIES", "TDDFPT"]
                and enabled(td[0])
                and nstates == ["8"] and len(kernels) == 1 and kernels[0] in ("FULL", "STDA")
                and triplets == ["F"]))
    vector_names = [m[1].upper() for c in r["cell_lines"]
                    if (m := re.match(r"\s*(ABC|A|B|C)\s+", c["text"], re.I))]
    cell_has_vectors = (vector_names.count("ABC") == 1 and
                        all(vector_names.count(x) == 0 for x in ("A", "B", "C"))) or \
                       (vector_names.count("ABC") == 0 and
                        all(vector_names.count(x) == 1 for x in ("A", "B", "C")) and len(vector_names) == 3)
    input_structure = [{"element": row["element"].upper(), "coords": [str(x) for x in row["coords"]]} for row in r["coord_rows"]]
    return {"records": r, "run_type_geo_opt": run_ok,
            "one_geo_opt_block": len(geo_blocks) == 1 and enabled(geo_blocks[0]),
            "required_input_hierarchy_unique": all(len(required_blocks[name]) == 1 for name in required_sections),
            "fixed_cell_input": len(cell_blocks) == 1 and cell_has_vectors and not cell_opt,
            "optimizer_lbfgs": opt_name == "LBFGS", "optimizer": opt_name, "max_iter": max_iter,
            "max_iter_valid": max_iter is not None and max_iter > 0,
            "criteria": criteria, "all_four_criteria_valid": len(criteria) == 4 and all(x["valid"] for x in criteria.values()),
            "outer_scf_configured": len(outer) == 1 and enabled(outer[0]), "stage_mode_matches_input": mode_ok,
            "input_s1_kernel": kernels[0] if len(kernels) == 1 else None,
            "input_atom_count": len(input_structure), "input_atoms": input_structure,
            "input_atom_count_matches_expected": len(input_structure) == expected_atoms,
            "input_errors": r["errors"], "input_blocks_well_formed": not r["errors"]}


def _native_end(lines: list[str]) -> dict:
    starts = [i + 1 for i, line in enumerate(lines) if "PROGRAM STARTED AT" in line]
    ends = [i + 1 for i, line in enumerate(lines) if "PROGRAM ENDED AT" in line]
    stops = [i + 1 for i, line in enumerate(lines) if "PROGRAM STOPPED IN" in line]
    fields = ("PROGRAM RAN ON", "PROGRAM RAN BY", "PROGRAM PROCESS ID", "PROGRAM STOPPED IN")
    footer = lines[ends[0] - 1:] if len(ends) == 1 else []
    counts = {x: sum(x in line.upper() for line in footer) for x in fields}
    positions = [[i for i, line in enumerate(footer) if key in line.upper()] for key in fields]
    ordered = all(len(p) == 1 for p in positions) and [p[0] for p in positions] == sorted(p[0] for p in positions)
    clean = False
    poststop = False
    if ordered:
        allowed = {0, *(p[0] for p in positions)}
        stop_pos = positions[-1][0]
        clean = all(not line.strip() or idx in allowed for idx, line in enumerate(footer[:stop_pos + 1]))
        poststop = all(not line.strip() or
                       (re.fullmatch(r"\s{20,}[A-Za-z0-9_.\-/]+\s*", line) and
                        not re.search(r"\b(?:RESTART|SCF|ENERGY|FORCES|ABORT|ERROR|WARNING|PROGRAM)\b", line, re.I))
                       for line in footer[stop_pos + 1:])
    ok = len(starts) == len(ends) == len(stops) == 1 and starts[0] < ends[0] < stops[0] and ordered and clean and poststop
    return {"passed": ok, "start_lines": starts, "end_lines": ends, "stop_lines": stops,
            "footer_field_counts": counts, "ordered": ordered, "interstitial_clean": clean,
            "post_stop_path_wrap_only": poststop}


def _trajectory(path_text: str, expected_atoms: int) -> dict:
    lines = path_text.splitlines()
    frames = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        if not lines[i].strip().isdigit():
            return {"valid": False, "reason": f"bad XYZ atom count at line {i + 1}", "frames": frames}
        n = int(lines[i].strip())
        if n != expected_atoms or i + n + 1 >= len(lines):
            return {"valid": False, "reason": f"wrong or truncated XYZ frame at line {i + 1}", "frames": frames}
        comment = lines[i + 1]
        match = XYZ_COMMENT_RE.search(comment)
        if not match:
            return {"valid": False, "reason": f"XYZ frame lacks CP2K i/E comment at line {i + 2}", "frames": frames}
        atoms = []
        try:
            for j in range(i + 2, i + 2 + n):
                cols = lines[j].split()
                if len(cols) < 4:
                    raise ValueError("short atom row")
                xyz = [_finite_decimal(x) for x in cols[1:4]]
                atoms.append({"element": cols[0].upper(), "coords": xyz})
        except (ValueError, InvalidOperation):
            return {"valid": False, "reason": f"invalid XYZ atom row in frame at line {i + 1}", "frames": frames}
        frames.append({"index": int(match[1]), "energy_token": match[2], "atoms": atoms,
                       "line_start": i + 1, "line_end": i + n + 1})
        i += n + 2
    indexes = [f["index"] for f in frames]
    return {"valid": bool(frames) and indexes == list(range(1, len(frames) + 1)),
            "reason": None if frames and indexes == list(range(1, len(frames) + 1)) else "trajectory frame indexes not contiguous",
            "frame_count": len(frames), "frames": frames}


def _energy_check_for_eval(lines: list[str], ev: dict, mode: str) -> dict:
    chunk = lines[ev["line_start"] - 1:ev["line_end"]]
    energy_lines = [(i + ev["line_start"], m[1]) for i, line in enumerate(chunk) if (m := ENERGY_RE.match(line))]
    scf_lines = [(i + ev["line_start"], m[1]) for i, line in enumerate(chunk) if (m := SCF_TOTAL_RE.match(line))]
    nonfinite_scf_lines = [i + ev["line_start"] for i, line in enumerate(chunk) if SCF_TOTAL_NONFINITE_RE.match(line)]
    if len(energy_lines) != 1 or not scf_lines or nonfinite_scf_lines:
        return {"passed": False, "reason": "evaluation needs one ENERGY and SCF total"}
    if scf_lines[-1][0] >= energy_lines[0][0]:
        return {"passed": False, "reason": "last SCF total must precede evaluation ENERGY"}
    if mode == "GS":
        final_scf_event = max((x.get("line", 0) for x in ev.get("scf_events", [])), default=None)
        return _energy_record_diagnostic("\n".join(chunk), ev.get("energy_total_Ha", float("nan")),
                                          final_scf_event, line_offset=ev["line_start"] - 1)
    state_blocks = [(i, m[1]) for i, line in enumerate(chunk) if (m := STATE_ID_RE.match(line))]
    omega = [(i, m[1]) for i, line in enumerate(chunk) if (m := EXCITATION_RE.match(line))]
    s1_totals = [(i, m[1]) for i, line in enumerate(chunk) if (m := S1_TOTAL_RE.match(line))]
    td_rows = [(i, m) for i, line in enumerate(chunk) if (m := STATE_RE.match(line))]
    if len(state_blocks) != 1 or int(state_blocks[0][1]) != 1 or len(omega) != 1 or len(s1_totals) != 1:
        return {"passed": False, "reason": "S1 evaluation must name state 1 and contain one omega and one S1 total"}
    selected = [m for _, m in td_rows if int(m[1]) == 1]
    if len(selected) != 1:
        return {"passed": False, "reason": "S1 evaluation needs one native TD state-1 row"}
    td_converged = [i + ev["line_start"] for i, line in enumerate(chunk)
                    if re.search(r"TDDFPT run converged in\s+\d+ iteration", line, re.I)]
    td_failed = [i + ev["line_start"] for i, line in enumerate(chunk)
                 if re.search(r"TDDFPT run not converged", line, re.I)]
    td_row_lines = [i + ev["line_start"] for i, line in enumerate(chunk) if STATE_RE.match(line)]
    state_line = state_blocks[0][0] + ev["line_start"]
    omega_line = omega[0][0] + ev["line_start"]
    total_line = s1_totals[0][0] + ev["line_start"]
    energy_line = energy_lines[0][0]
    order_ok = (len(td_converged) == 1 and not td_failed and bool(td_row_lines) and
                scf_lines[-1][0] < td_converged[0] < min(td_row_lines) <= max(td_row_lines) <
                state_line < omega_line < total_line < energy_line)
    try:
        e0 = _finite_decimal(scf_lines[-1][1]); w = _finite_decimal(omega[0][1])
        s1 = _finite_decimal(s1_totals[0][1]); final = _finite_decimal(energy_lines[0][1])
        td_ev = _finite_decimal(selected[0][2])
        e0_env = sum((_half_ulp(scf_lines[-1][1]), _half_ulp(omega[0][1]), _half_ulp(s1_totals[0][1])), Decimal(0))
        s1_env = _half_ulp(energy_lines[0][1]) + _half_ulp(s1_totals[0][1])
        # CP2K 2024.x prints state excitation energies with the CODATA-2006
        # evolt constant. This is a printed-token consistency check only.
        evolt = Decimal("27.2113838565563")
        td_env = _half_ulp(omega[0][1]) * evolt + _half_ulp(selected[0][2]) + Decimal("1e-14")
        sum_delta = abs(e0 + w - s1); final_delta = abs(final - s1); td_delta = abs(w * evolt - td_ev)
        passed = (order_ok and w >= 0 and sum_delta <= e0_env and final_delta <= s1_env and td_delta <= td_env)
    except (InvalidOperation, ValueError, OverflowError):
        return {"passed": False, "reason": "nonfinite S1 energy token"}
    return {"passed": passed, "state": 1, "E0_token_Ha": scf_lines[-1][1], "omega_token_Ha": omega[0][1],
            "S1_total_token_Ha": s1_totals[0][1], "final_ENERGY_token_Ha": energy_lines[0][1],
            "E0_plus_omega_delta_Ha": str(sum_delta), "printed_envelope_Ha": str(e0_env),
            "final_ENERGY_vs_S1_delta_Ha": str(final_delta), "omega_vs_TD_state1_delta_eV": str(td_delta),
            "TD_energy_envelope_eV": str(td_env), "evaluation_event_order_consistent": order_ok,
            "interpretation": "State-1 total is checked as E0+omega and against final ENERGY at printed precision; omega is not added again."}


def _scf_gate(ev: dict, configured_outer: bool) -> dict:
    scf = ev.get("scf_events", [])
    outer = ev.get("outer_scf_events", [])
    scf_positive = [x for x in scf if x.get("kind") == "converged"]
    outer_positive = [x for x in outer if re.search(r"outer SCF loop\s+converged\b", x.get("text", ""), re.I)
                      and not re.search(r"\bnot\s+converged\b", x.get("text", ""), re.I)]
    last_outer = outer[-1] if outer else None
    last_outer_pos = bool(last_outer and re.search(r"outer SCF loop\s+converged\b", last_outer.get("text", ""), re.I)
                          and not re.search(r"\bnot\s+converged\b", last_outer.get("text", ""), re.I))
    # An inner SCF attempt may hit its limit; accept it only when this same
    # evaluation subsequently reports the configured outer loop converged.
    failed_inner_before_outer = all(x.get("line", 0) < (last_outer or {}).get("line", 0)
                                    for x in scf if x.get("kind") == "not_converged")
    last_inner_before_outer = bool(scf and max(x.get("line", 0) for x in scf) < (last_outer or {}).get("line", 0))
    final_inner_positive = bool(scf and scf[-1].get("kind") == "converged")
    ok = bool(scf_positive) and final_inner_positive and configured_outer and last_outer_pos and failed_inner_before_outer and last_inner_before_outer
    return {"passed": ok, "inner_events": scf, "outer_events": outer,
            "inner_convergence_seen": bool(scf_positive), "inner_failures_precede_final_outer_success": failed_inner_before_outer,
            "final_inner_event_converged": final_inner_positive,
            "configured_outer_final_event_converged": last_outer_pos, "outer_after_inner_events": last_inner_before_outer}


def _step_metrics(lines: list[str], start: int, stop: int, input_criteria: dict) -> dict:
    segment = lines[start - 1:stop]
    result = {}
    for input_key, native_name in (("MAX_DR", "Maximum step size"), ("RMS_DR", "RMS step size"),
                                   ("MAX_FORCE", "Maximum gradient"), ("RMS_FORCE", "RMS gradient")):
        value_re = re.compile(rf"^\s*OPT\|\s*{re.escape(native_name)}\s+({FLOAT})\s*$", re.I)
        limit_re = re.compile(rf"^\s*OPT\|\s*Convergence limit for {re.escape(native_name)}\s+({FLOAT})\s*$", re.I)
        flag_re = re.compile(rf"^\s*OPT\|\s*{re.escape(native_name)} is converged\s+(YES|NO)\s*$", re.I)
        values = [m[1] for line in segment if (m := value_re.match(line))]
        limits = [m[1] for line in segment if (m := limit_re.match(line))]
        flags = [m[1].upper() == "YES" for line in segment if (m := flag_re.match(line))]
        if len(values) != 1 or len(limits) != 1 or len(flags) != 1:
            result[input_key] = {"valid": False, "reason": "missing_or_duplicate_native_metric"}
            continue
        configured = input_criteria.get(input_key, {}).get("value")
        configured_token = input_criteria.get(input_key, {}).get("token")
        if configured is None or configured_token is None:
            result[input_key] = {"valid": False, "reason": "missing_input_criterion"}
            continue
        try:
            value, limit = _finite_decimal(values[0]), _finite_decimal(limits[0])
            input_limit_match = abs(limit - configured) <= _half_ulp(limits[0]) + _half_ulp(configured_token)
            numeric_flag = (value <= limit) == flags[0]
            result[input_key] = {"valid": value >= 0 and limit > 0 and input_limit_match and numeric_flag,
                                 "value_token": values[0], "limit_token": limits[0], "flag_yes": flags[0],
                                 "input_limit_token": input_criteria[input_key]["token"],
                                 "value_at_or_below_limit": value <= limit, "input_limit_matches_native": input_limit_match,
                                 "flag_matches_numeric_value": numeric_flag}
        except (InvalidOperation, ValueError, OverflowError):
            result[input_key] = {"valid": False, "reason": "nonfinite_metric"}
    return result


def inspect_text(input_text: str, native_text: str, trajectory_text: str,
                 expected_atoms: int, mode: str) -> dict:
    if isinstance(expected_atoms, bool) or not isinstance(expected_atoms, int) or expected_atoms <= 0:
        raise ValueError("expected_atoms must be a positive integer")
    mode = mode.upper()
    if mode not in ("GS", "S1"):
        raise ValueError("mode must be GS or S1")
    contract = _input_contract(input_text, mode, expected_atoms)
    parsed = parse_text(native_text, expected_atoms=expected_atoms,
                        expected_states=(8 if mode == "S1" else None),
                        stage=("GS_GEO_OPT" if mode == "GS" else "S1_GEO_OPT"))
    lines = native_text.splitlines()
    evals = parsed.get("evaluations", [])
    step_rows = [(i + 1, int(m[1])) for i, line in enumerate(lines) if (m := OPT_STEP_RE.match(line))]
    completion = [i + 1 for i, line in enumerate(lines) if "GEOMETRY OPTIMIZATION COMPLETED" in line]
    reevaluate = [i + 1 for i, line in enumerate(lines) if "Reevaluating energy at the minimum" in line]
    global_runs = [m[1].upper() for line in lines if (m := re.match(r"^\s*GLOBAL\|\s*Run type\s+(\S+)\s*$", line, re.I))]
    native_mode_ok = global_runs == ["GEO_OPT"]
    footer = _native_end(lines)
    trajectory = _trajectory(trajectory_text, expected_atoms)
    header_count = parsed.get("header_atom_count")
    input_atoms = contract["input_atoms"]
    frames = trajectory.get("frames", [])
    trajectory_labels_match_input = bool(frames and all(
        [a["element"].upper() for a in frame["atoms"]] == [a["element"].upper() for a in input_atoms]
        for frame in frames))
    trajectory_matches_steps = (trajectory.get("valid") is True and len(frames) == len(step_rows) and
                                [s for _, s in step_rows] == list(range(len(step_rows))))
    # Evaluation records include every optimizer evaluation plus a distinct
    # minimum re-evaluation. Force tables belong only to optimizer evaluations.
    endpoint = evals[-1] if evals else None
    accepted = evals[:-1] if endpoint and endpoint.get("role") == "minimum_endpoint" else []
    steps_by_eval = [e.get("opt_step") for e in accepted]
    step_ids = [x.get("step") for x in steps_by_eval if x]
    one_step_per_force_eval = (len(accepted) == len(step_rows) == len(steps_by_eval) and
                               all(x is not None and x.get("after_force") for x in steps_by_eval) and
                               step_ids == list(range(len(step_ids))))
    maxiter_not_reached = bool(step_ids and contract["max_iter"] is not None and max(step_ids) < contract["max_iter"])
    step_metric_reports = []
    optimizer_identity_reports = []
    for idx, (step_line, step_number) in enumerate(step_rows):
        stop_line = (step_rows[idx + 1][0] - 1 if idx + 1 < len(step_rows) else
                     completion[0] - 1 if completion else len(lines))
        report = _step_metrics(lines, step_line, stop_line, contract["criteria"])
        method_rows = [m[1].upper() for line in lines[step_line - 1:stop_line]
                       if (m := re.match(r"^\s*OPT\|\s*Optimization method\s+(\S+)\s*$", line, re.I))]
        optimizer_identity_reports.append({"step": step_number, "methods": method_rows,
                                           "matches_input_lbfgs": method_rows == ["LBFGS"]})
        is_initial_without_metrics = (step_number == 0 and all(
            item.get("reason") == "missing_or_duplicate_native_metric" for item in report.values()))
        well_formed = is_initial_without_metrics or (len(report) == 4 and all(item.get("valid") for item in report.values()))
        step_metric_reports.append({"step": step_number, "line": step_line, "metrics": report,
                                    "initial_step_metrics_absent": is_initial_without_metrics,
                                    "well_formed": well_formed})
    all_metrics_well_formed = (len(step_metric_reports) == len(step_rows) and bool(step_rows) and
                               all(x["well_formed"] for x in step_metric_reports))
    final_metric_report = step_metric_reports[-1]["metrics"] if step_metric_reports else {}
    final_four_yes = (len(final_metric_report) == 4 and all(
        x.get("valid") and x.get("flag_yes") and x.get("value_at_or_below_limit")
        for x in final_metric_report.values()))
    energy_tokens_by_line = {i + 1: m[1] for i, line in enumerate(lines) if (m := ENERGY_RE.match(line))}
    force_evaluations = []
    force_energy_matches = []
    for index, ev in enumerate(accepted):
        blocks = ev.get("force_blocks", [])
        force_ok = len(blocks) == 1 and blocks[0].get("checks", {}).get("complete") is True and \
                   blocks[0].get("checks", {}).get("finite") is True and \
                   blocks[0].get("checks", {}).get("atom_ids_ordered_unique") is True
        opt_line = step_rows[index][0] if index < len(step_rows) else None
        opt_stop = step_rows[index + 1][0] - 1 if index + 1 < len(step_rows) else (completion[0] - 1 if completion else len(lines))
        opt_energies = [m[1] for line in lines[opt_line - 1:opt_stop] if (m := OPT_TOTAL_RE.match(line))] if opt_line else []
        force_order_ok = (len(blocks) == 1 and opt_line is not None and ev.get("line_end", 0) < blocks[0].get("line_start", 0)
                          and blocks[0].get("line_end", 0) < opt_line)
        energy_token = energy_tokens_by_line.get(ev.get("line_end", 0))
        opt_energy_ok = False
        if len(opt_energies) == 1 and energy_token:
            try:
                a, b = _finite_decimal(opt_energies[0]), _finite_decimal(energy_token)
                opt_energy_ok = abs(a - b) <= _half_ulp(opt_energies[0]) + _half_ulp(energy_token)
            except InvalidOperation:
                opt_energy_ok = False
        force_energy_matches.append(force_order_ok and opt_energy_ok)
        lin = ev.get("convergence_flags", {}).get("linear_response")
        if mode == "S1":
            lin = bool(ev.get("linear_solver_events")) and all(x.get("converged") is True for x in ev.get("linear_solver_events", []))
        force_evaluations.append({"evaluation": ev.get("index"), "force_block_count": len(blocks),
                                  "complete_finite_ordered_force": force_ok,
                                  "linear_response_converged_for_force": (lin is True if mode == "S1" else None),
                                  "energy_force_opt_order_consistent": force_order_ok and opt_energy_ok,
                                  "OPT_energy_tokens": opt_energies, "ENERGY_token": energy_token})
    all_forces_ok = len(force_evaluations) == len(accepted) and bool(accepted) and all(
        x["complete_finite_ordered_force"] and x["energy_force_opt_order_consistent"] and
        (mode != "S1" or x["linear_response_converged_for_force"])
        for x in force_evaluations)
    parsed_force_blocks = [block for ev in evals for block in ev.get("force_blocks", [])]
    native_force_titles = [i + 1 for i, line in enumerate(lines) if FORCE_TITLE_RE.match(line)]
    parsed_force_title_lines = [block.get("line_start") for block in parsed_force_blocks]
    all_force_titles_accounted = (len(native_force_titles) == len(parsed_force_blocks) and
                                  sorted(native_force_titles) == sorted(parsed_force_title_lines))
    eval_scf = [_scf_gate(ev, contract["outer_scf_configured"]) for ev in evals]
    all_scf_ok = bool(evals) and len(eval_scf) == len(evals) and all(x["passed"] for x in eval_scf)
    energy_checks = [_energy_check_for_eval(lines, ev, mode) for ev in evals]
    energy_gate_key = "syntax_passed" if mode == "GS" else "passed"
    all_energy_ok = bool(evals) and len(energy_checks) == len(evals) and all(x.get(energy_gate_key) for x in energy_checks)
    all_td_ok = (mode == "GS" or (bool(evals) and all(
        ev.get("convergence_flags", {}).get("td") is True and
        ev.get("state_checks", {}).get("count") == 8 and
        ev.get("state_checks", {}).get("duplicate_ids") == [] and
        ev.get("state_checks", {}).get("missing_expected_ids") == [] and
        ev.get("state_checks", {}).get("ordered") is True and
        ev.get("state_checks", {}).get("finite") is True and
        ev.get("state_checks", {}).get("nonnegative_energy_and_f") is True
        for ev in evals)))
    kernels_native = [m[1].upper() for line in lines if (m := NATIVE_KERNEL_RE.match(line))]
    spins_native = [m[1].upper() for line in lines if (m := NATIVE_SPIN_RE.match(line))]
    per_eval_mode_identity = []
    native_mode_identity = True
    if mode == "GS":
        no_td = not bool(re.search(r"\bTDDFPT\b|\bR-TDDFPT\b|Excited State Energy|Excitation Energy|Results for Excited State", native_text, re.I))
        native_mode_identity = no_td and not kernels_native and not spins_native
    else:
        expected_kernel = contract["input_s1_kernel"]
        for ev in evals:
            segment = lines[ev["line_start"] - 1:ev["line_end"]]
            eval_kernels = [m[1].upper() for line in segment if (m := NATIVE_KERNEL_RE.match(line))]
            eval_spins = [m[1].upper() for line in segment if (m := NATIVE_SPIN_RE.match(line))]
            per_eval_mode_identity.append({"evaluation": ev.get("index"), "kernel_records": eval_kernels,
                                          "spin_records": eval_spins,
                                          "matches_input": eval_kernels == [expected_kernel] and eval_spins == ["SINGLET"]})
        native_mode_identity = bool(evals) and len(per_eval_mode_identity) == len(evals) and all(
            x["matches_input"] for x in per_eval_mode_identity)
    last_eval_line = max((e.get("line_end", 0) for e in evals), default=0)
    opt_steps_after_completion = bool(completion and any(line > completion[0] for line, _ in step_rows))
    one_completion_endpoint = (len(completion) == len(reevaluate) == 1 and len(evals) >= 2 and
                               endpoint is not None and endpoint.get("role") == "minimum_endpoint" and
                               completion[0] < reevaluate[0] < endpoint.get("line_end", 0) < footer["end_lines"][0]
                               if footer["end_lines"] else False)
    endpoint_force_ok = (endpoint is not None and (not endpoint.get("force_blocks") or
                        (len(endpoint["force_blocks"]) == 1 and endpoint["force_blocks"][0].get("checks", {}).get("complete") is True and
                         endpoint["force_blocks"][0].get("checks", {}).get("finite") is True and
                         endpoint["force_blocks"][0].get("checks", {}).get("atom_ids_ordered_unique") is True and
                         endpoint.get("line_end", 0) < endpoint["force_blocks"][0].get("line_start", 0) <
                         (footer["end_lines"][0] if footer["end_lines"] else 0))))
    trajectory_endpoint_energy = False
    trajectory_eval_energy_matches = []
    if trajectory.get("valid") and len(evals) == len(frames) + 1:
        for frame in frames:
            # CP2K XYZ frame i (1-based) is printed at the next evaluation
            # boundary; this one-evaluation offset was verified in the local
            # complete M2 GS and STDA GEO_OPT records. It is a syntax mapping,
            # not proof that coordinates and forces share physical identity.
            ev = evals[frame["index"]]
            ev_energy = energy_tokens_by_line.get(ev.get("line_end", 0))
            try:
                xyz_energy = frame["energy_token"]
                matches = bool(ev_energy) and abs(_finite_decimal(ev_energy) - _finite_decimal(xyz_energy)) <= (
                    _half_ulp(ev_energy) + _half_ulp(xyz_energy))
            except InvalidOperation:
                matches = False
            trajectory_eval_energy_matches.append({"frame": frame["index"], "evaluation": ev.get("index"),
                                                   "xyz_energy_token": frame["energy_token"],
                                                   "evaluation_energy_token": ev_energy, "matches_printed_precision": matches})
    trajectory_energy_eval_ordered = (len(trajectory_eval_energy_matches) == len(frames) and bool(frames) and
                                      all(x["matches_printed_precision"] for x in trajectory_eval_energy_matches))
    if endpoint and frames:
        energy_tokens = [m[1] for line in lines if (m := ENERGY_RE.match(line))]
        try:
            if energy_tokens:
                end_energy = _finite_decimal(energy_tokens[-1]); xyz_energy = _finite_decimal(frames[-1]["energy_token"])
                trajectory_endpoint_energy = abs(end_energy - xyz_energy) <= _half_ulp(energy_tokens[-1]) + _half_ulp(frames[-1]["energy_token"])
        except InvalidOperation:
            trajectory_endpoint_energy = False
    no_tail = not parsed.get("unresolved_tail_events")
    fatal = bool(re.search(r"\[ABORT\]|\bFATAL ERROR\b|\bforrtl:\s*(?:severe|fatal)|\bMPI_ABORT\b", native_text, re.I))
    optimizer_maxiter_exit = bool(re.search(r"\bMAXIMUM NUMBER OF OPTIMIZATION STEPS REACHED\b", native_text, re.I))
    file_checks = {
        "input_geo_opt_fixed_cell_lbfgs_four_criteria": contract["run_type_geo_opt"] and contract["one_geo_opt_block"] and
            contract["required_input_hierarchy_unique"] and contract["fixed_cell_input"] and contract["optimizer_lbfgs"] and
            contract["max_iter_valid"] and contract["all_four_criteria_valid"] and contract["outer_scf_configured"],
        "input_stage_mode_matches_requested_mode": contract["stage_mode_matches_input"],
        "input_and_native_atom_count_match_expected": contract["input_atom_count_matches_expected"] and header_count == expected_atoms,
        "native_run_type_geo_opt": native_mode_ok,
        "all_energy_headings_well_formed_and_attached": (not _energy_heading_inventory(native_text)["malformed_lines"] and
            len(_energy_heading_inventory(native_text)["heading_lines"]) == len(evals)),
        "native_complete_start_end_footer": footer["passed"],
        "exactly_one_completion_and_distinct_minimum_endpoint": one_completion_endpoint,
        "accepted_steps_are_ordered_contiguous_and_below_max_iter": one_step_per_force_eval and maxiter_not_reached and not opt_steps_after_completion,
        "native_optimizer_identity_matches_lbfgs_input_per_step": (len(optimizer_identity_reports) == len(step_rows) and
            bool(step_rows) and all(x["matches_input_lbfgs"] for x in optimizer_identity_reports)),
        "native_reported_step_metrics_finite_consistent_and_final_four_yes": all_metrics_well_formed and final_four_yes,
        "every_geometry_update_has_complete_ordered_finite_forces": all_forces_ok,
        "all_native_force_headings_are_parsed_and_attached": all_force_titles_accounted,
        "configured_scf_and_outer_converged_for_each_evaluation": all_scf_ok,
        "evaluation_energy_semantics_consistent": all_energy_ok,
        "S1_td_eight_roots_and_force_response_converged_when_required": all_td_ok,
        "native_mode_kernel_and_singlet_match_input": native_mode_identity,
        "trajectory_complete_ordered_and_atom_labels_match_input": trajectory["valid"] and trajectory_matches_steps and trajectory_labels_match_input,
        "trajectory_frame_energies_match_next_native_evaluation": trajectory_energy_eval_ordered,
        "trajectory_final_energy_matches_distinct_minimum_endpoint": trajectory_endpoint_energy and endpoint_force_ok,
        "no_post_completion_optimizer_steps": not opt_steps_after_completion,
        "no_abort_fatal_or_unresolved_tail": not fatal and no_tail,
        "optimizer_did_not_exit_at_maxiter": not optimizer_maxiter_exit,
        "input_syntax_and_preprocessor_clean": contract["input_blocks_well_formed"],
    }
    failed = [key for key, value in file_checks.items() if not value]
    return {"helper": "case07-geo-opt-author-review/v1", "mode": mode, "expected_atoms": expected_atoms,
            "strict_syntax_complete": not failed, "failed_checks": failed, "checks": file_checks,
            "input_contract": {k: v for k, v in contract.items() if k not in ("records", "input_atoms", "criteria")} |
                             {"criteria": {k: {kk: (str(vv) if isinstance(vv, Decimal) else vv) for kk, vv in val.items()}
                                           for k, val in contract["criteria"].items()},
                              "block_errors": contract["records"]["errors"]},
            "native": {"global_run_types": global_runs, "header_atom_count": header_count,
                       "completion_lines": completion, "minimum_reevaluation_lines": reevaluate,
                       "accepted_opt_steps": step_ids, "evaluation_count": len(evals),
                       "evaluation_roles": [e.get("role") for e in evals],
                       "scf_outer_gates": eval_scf, "energy_semantics_checks": energy_checks,
                       "force_evaluations": force_evaluations, "final_step_metrics": final_metric_report,
                       "native_force_title_lines": native_force_titles,
                       "parsed_force_title_lines": parsed_force_title_lines,
                       "native_kernel_records": kernels_native, "native_spin_records": spins_native,
                       "native_mode_identity_by_evaluation": per_eval_mode_identity,
                       "optimizer_step_metric_records": step_metric_reports,
                       "optimizer_identity_by_step": optimizer_identity_reports,
                       "td_state_ids_by_evaluation": [[s.get("state") for s in e.get("states", [])] for e in evals]},
            "trajectory": {"frame_count": trajectory.get("frame_count"), "valid": trajectory.get("valid"),
                           "reason": trajectory.get("reason"),
                           "first_frame_atom_labels": [a["element"] for a in frames[0]["atoms"]] if frames else [],
                           "final_frame_index": frames[-1]["index"] if frames else None,
                           "final_frame_energy_token": frames[-1]["energy_token"] if frames else None,
                           "frame_evaluation_energy_matches": trajectory_eval_energy_matches,
                           "final_geometry_from_trajectory": bool(frames),
                           "geometry_force_identity": "trajectory frame count/order, ordered atom labels/IDs, frame E tokens against the next native evaluation at printed precision, and final ENERGY token; per-step coordinate-to-force identity is not checked",
                           "trajectory_energy_mapping_basis": "Observed M2 GS and STDA native outputs map XYZ frame i (1-based) to the next ENERGY evaluation boundary; not externally authenticated for other CP2K versions/stages.",
                           "coordinate_reference_and_restart_geometry_identity": "unverified; trajectory frames are finite and ordered, but a restart may start from geometry different from input COORD"},
            "external_evidence": {"geometry_identity_authenticated": False, "restart_bytes_or_read_provenance": "not checked",
                                  "runtime_binary_data_modules_libraries": "not checked", "slurm_exit_cost_resources": "not checked",
                                  "science_tolerances": None,
                                  "force_metric_recalculation_from_ordered_force_vectors": "not performed; native OPT metric values/limits/flags are parsed and checked against the input thresholds, not independently recomputed from force vectors"},
            "science_validated": False, "gold_eligible": False,
            "scope": "Author-side native/input/trajectory syntax and local consistency only; not scorer, geometry/state-identity validator, or science acceptance."}


def _safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    return value


def _alias_error(output: Path | None, sources: list[Path]) -> str | None:
    if output is None:
        return None
    for source in sources:
        if output.resolve(strict=False) == source.resolve(strict=False):
            return f"output aliases protected evidence: {source}"
        try:
            if output.exists() and source.exists() and os.path.samefile(output, source):
                return f"output inode aliases protected evidence: {source}"
        except OSError:
            return f"cannot safely distinguish output from protected evidence: {source}"
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--native", required=True, type=Path)
    ap.add_argument("--trajectory", required=True, type=Path,
                    help="complete CP2K XYZ trajectory (required for final geometry evidence)")
    ap.add_argument("--expected-atoms", required=True, type=int)
    ap.add_argument("--mode", required=True, choices=("GS", "S1"))
    ap.add_argument("--output", type=Path)
    args = ap.parse_args(argv)
    sources = [args.input, args.native, args.trajectory]
    alias = _alias_error(args.output, sources)
    if alias:
        print(json.dumps({"helper": "case07-geo-opt-author-review/v1", "error": alias,
                          "science_validated": False}, allow_nan=False))
        return 2
    try:
        input_text = args.input.read_text(encoding="utf-8", errors="replace")
        native_text = args.native.read_text(encoding="utf-8", errors="replace")
        trajectory_text = args.trajectory.read_text(encoding="utf-8", errors="replace")
        result = inspect_text(input_text, native_text, trajectory_text, args.expected_atoms, args.mode)
        for label, path in (("input", args.input), ("native", args.native), ("trajectory", args.trajectory)):
            raw = path.read_bytes()
            result.setdefault("sha256", {})[label] = hashlib.sha256(raw).hexdigest()
        rendered = json.dumps(_safe(result), indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0 if result["strict_syntax_complete"] else 1
    except (OSError, UnicodeError, ValueError) as exc:
        payload = json.dumps({"helper": "case07-geo-opt-author-review/v1", "error": str(exc),
                              "science_validated": False, "gold_eligible": False}, indent=2, allow_nan=False)
        # Never retry a failed output path: it may alias evidence through a
        # symlink/hardlink that became visible after the initial check.
        print(payload)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
