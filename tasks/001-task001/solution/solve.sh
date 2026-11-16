#!/bin/sh
set -eu

WORK=$(mktemp -d "${TMPDIR:-/tmp}/task1-solve.XXXXXX")
cleanup() { status=$?; rm -rf "$WORK"; trap - 0; exit "$status"; }
trap cleanup 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

cat > "$WORK/analyze.py" <<'__TASK1_PYTHON_SOURCE_1__'
#!/usr/bin/env python3
"""Public-source parser and evidence-bounded arithmetic for Case01 audit-v3."""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

EH_TO_KCAL = 627.5094740631
JOIN_TOL_EH = 5e-7
ASSET_RE = re.compile(r"SC-012-D0SC04896H-s(\d+)\.(log|dat)$")
ATOMIC_SYMBOLS = {1:"H", 6:"C", 7:"N", 8:"O", 9:"F", 17:"Cl"}
ELEMENTS = {"H":1,"C":6,"N":7,"O":8,"F":9,"Cl":17}
GAUSSIAN_IDS = ["325", "343", "353", "1694", "1712", "456", "797", "1584"]
GOODVIBES_IDS = ["326", "344", "350", "449", "1695", "1713", "1577", "790"]
REACTIVE_ROLE_MAPS = {
    "325": ("E1-entry-28", None, 4, None),
    "343": ("E1-entry-28", 8, None, 9),
    "456": ("E1-entry-28", 8, 21, 9),
    "353": ("E1-entry-28", 8, 21, 9),
    "1694": ("E1-entry-90", None, 2, None),
    "1712": ("E1-entry-90", 2, None, 1),
    "1584": ("E1-entry-90", 2, 17, 1),
    "797": ("E1-entry-28", 8, 21, 9),
}


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(text)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def asset_id(path: Path) -> str:
    m = ASSET_RE.search(path.name)
    if not m:
        raise ValueError(f"not a named public calculation asset: {path.name}")
    return m.group(1)


def parse_gaussian(path: Path):
    text = path.read_text(encoding="latin-1", errors="replace")
    lines = text.splitlines()
    scf = list(re.finditer(r"SCF Done:\s+E\([^)]*\)\s*=\s*(-?\d+\.\d+)", text))
    if not scf:
        raise ValueError(f"no Gaussian SCF energy in {path.name}")
    final_energy = float(scf[-1].group(1))
    scf_line = text.count("\n", 0, scf[-1].start()) + 1
    freq_matches = list(re.finditer(r"(?m)^\s*Frequencies --\s*(.*)$", text))
    if not freq_matches:
        raise ValueError(f"no frequency table in {path.name}")

    # The final input-orientation table before the first frequency block is the geometry
    # against which this frequency calculation was printed.
    orient_matches = [m for m in re.finditer(r"(?m)^[ \t]*(Standard|Input) orientation:[ \t]*$", text)
                      if m.start() < freq_matches[0].start()]
    orient = None
    standard_matches = [m for m in orient_matches if m.group(1) == "Standard"]
    preferred = standard_matches or [m for m in orient_matches if m.group(1) == "Input"]
    if preferred:
        for om in reversed(preferred):
            orient = _parse_orientation(text, om.start())
            if orient:
                orient["frame_kind"] = "Standard orientation" if om.group(1) == "Standard" else "Input orientation"
                break
    if orient is None:
        raise ValueError(f"no complete Input orientation before frequency table: {path.name}")

    modes = []
    cursor_index = 0
    freq_lines = []
    for fm in freq_matches:
        values = [_float(x) for x in fm.group(1).split()]
        if not values:
            continue
        freq_lines.append(text.count("\n", 0, fm.start()) + 1)
        # A Gaussian frequency row is followed by its displacement table.
        atom_marker = re.search(r"(?m)^\s*Atom\s+AN\s+X\s+Y\s+Z", text[fm.end():])
        if not atom_marker:
            raise ValueError(f"frequency block has no displacement table: {path.name}")
        table_start = fm.end() + atom_marker.end()
        table_end = text.find("\n\n", table_start)
        if table_end < 0:
            table_end = len(text)
        atom_rows = []
        vector_line_numbers = []
        for rel_line, raw in enumerate(text[table_start:table_end].splitlines(), 1):
            bits = raw.split()
            if len(bits) < 5 or not bits[0].isdigit() or not bits[1].isdigit():
                continue
            atom_rows.append((int(bits[0]), int(bits[1]), [_float(v) for v in bits[2:]]))
            vector_line_numbers.append(text.count("\n", 0, table_start) + rel_line)
        if len(atom_rows) != orient["atom_count"]:
            # Restrict to exactly this atom table; Gaussian uses blank lines after it.
            atom_rows = atom_rows[:orient["atom_count"]]
            vector_line_numbers = vector_line_numbers[:orient["atom_count"]]
        if len(atom_rows) != orient["atom_count"]:
            raise ValueError(f"incomplete mode vectors in {path.name}: {len(atom_rows)} rows")
        if any(len(v) < 3 * len(values) for _, _, v in atom_rows):
            raise ValueError(f"mode vector columns incomplete in {path.name}")
        for j, freq in enumerate(values):
            vector = {}
            vector_atomic_numbers = {}
            for atom_num, atomic_num, components in atom_rows:
                vector[atom_num] = [components[3*j+k] for k in range(3)]
                vector_atomic_numbers[atom_num] = atomic_num
            modes.append({"mode_index":cursor_index, "frequency_cm-1":freq,
                          "vector_by_atom":vector,
                          "vector_atomic_numbers":vector_atomic_numbers,
                          "source_line":text.count("\n", 0, fm.start()) + 1,
                          "vector_line_range":[vector_line_numbers[0], vector_line_numbers[-1]],
                          "source_line_range":[text.count("\n", 0, fm.start()) + 1,
                                               vector_line_numbers[-1]]})
            cursor_index += 1

    neg = [m for m in modes if m["frequency_cm-1"] < 0]
    opt_before_freq = text[:freq_matches[0].start()]
    opt_completed = bool(re.search(r"Optimization completed\.", opt_before_freq))
    # Retain exact input route and source labels as provenance where available.
    route = []
    for line in lines[:min(len(lines), 120)]:
        if line.lstrip().startswith("#"):
            route.append(line.strip())
    return {"path":path, "text":text, "energy_Eh":final_energy,
            "scf_line":scf_line, "geometry":orient, "modes":modes,
            "negative_modes":neg, "mode_count":len(modes), "opt_converged":opt_completed,
            "route":route, "frequency_start_line":freq_lines[0] if freq_lines else None}


def _float(x):
    return float(x.replace("D", "E").replace("d", "e"))


def _parse_orientation(text: str, start: int):
    # Gaussian's Input orientation table has two dashed delimiters, then rows.
    chunk = text[start:]
    lines = chunk.splitlines()
    dashes = [i for i, line in enumerate(lines[:15]) if re.fullmatch(r"\s*-{5,}\s*", line)]
    if len(dashes) < 2:
        return None
    rows = []
    for line in lines[dashes[1]+1:]:
        bits = line.split()
        if len(bits) >= 6 and bits[0].isdigit() and bits[1].isdigit() and bits[2].isdigit():
            rows.append({"index":int(bits[0]), "atomic_number":int(bits[1]),
                         "xyz_A":[_float(x) for x in bits[3:6]]})
        elif rows:
            break
    if not rows:
        return None
    if [a["index"] for a in rows] != list(range(1, len(rows)+1)):
        return None
    # Locate exact coordinate-row line numbers for the evidence record.
    header_line = text.count("\n", 0, start) + 1
    row_lines = []
    for offset, line in enumerate(lines[dashes[1]+1:], dashes[1]+2):
        bits = line.split()
        if len(bits) >= 6 and bits[0].isdigit() and bits[1].isdigit() and bits[2].isdigit():
            row_lines.append(header_line + offset - 1)
        elif row_lines:
            break
    for atom, line_no in zip(rows, row_lines):
        atom["line_1based"] = line_no
    return {"atom_count":len(rows), "atoms":rows, "line_start":header_line,
            "frame_kind":None}


def parse_goodvibes(path: Path):
    text = path.read_text(encoding="latin-1", errors="replace")
    row_match = re.search(r"(?m)^\s*o\s+(\S+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$", text)
    if not row_match:
        raise ValueError(f"no GoodVibes table row in {path.name}")
    vals = [float(x) for x in row_match.groups()[1:]]
    temp = re.search(r"Temperature\s*=\s*([\d.]+)\s+Kelvin\s+Concentration\s*=\s*([\d.]+)\s+mol/l", text)
    scale = re.search(r"scale factor\s+([\d.]+)", text)
    cutoff = re.search(r"cut-off value of\s+([\d.]+)\s+wavenumbers", text)
    qs = re.search(r"QS\s*=\s*([^:]+):", text)
    request = re.search(r"Requested:\s*(.+)", text)
    unit = re.search(r"All energetic values below shown in\s+([^\s]+)\s+unless otherwise specified\.", text, re.I)
    energy_label = re.search(r"(?m)^\s*Structure\s+.*?\b(qh-G\(T\))\s*$", text)
    if not all((temp, scale, cutoff, qs, request, unit, energy_label)):
        raise ValueError(f"incomplete GoodVibes conventions in {path.name}")
    enthalpy, tqhs, qhg = vals[2], vals[4], vals[6]
    reproduced = enthalpy - tqhs
    if abs(reproduced - qhg) > 1.5e-6:
        raise ValueError(f"H - T.qhS does not reproduce qh-G(T) in {path.name}")
    timestamp = re.search(r"GoodVibes v\S+\s+\S+\s+(\d{2}:\d{2}:\d{2})", text)
    return {"path":path,
            "timestamp":timestamp.group(1) if timestamp else None,
            "E_electronic_Eh":vals[0],
            "ZPE_Eh":vals[1], "H_Eh":enthalpy, "TS_Eh":vals[3],
            "T_qhS_Eh":tqhs, "G_Eh":vals[5], "qhG_Eh":qhg,
            "temperature_K":float(temp.group(1)), "concentration_mol_L":float(temp.group(2)),
            "scale_factor":float(scale.group(1)), "frequency_cutoff_cm-1":float(cutoff.group(1)),
            "quasi_harmonic_scheme":qs.group(1).strip(),
            "energy_unit":unit.group(1), "energy_label":row_match.group(1),
            "requested":request.group(1).strip(), "version":"GoodVibes v3.0.1",
            "source_line":text.count("\n",0,row_match.start())+1,
            "H_minus_TqhS_Eh":reproduced}


def join_records(logs, dats):
    joined = {}
    unused = set(dats)
    for sid, log in logs.items():
        matches = [(did, d) for did, d in dats.items()
                   if abs(log["energy_Eh"] - d["E_electronic_Eh"]) <= JOIN_TOL_EH]
        if len(matches) != 1:
            raise ValueError(f"Gaussian/GoodVibes join for s{sid} has {len(matches)} matches")
        did, d = matches[0]
        if did not in unused:
            raise ValueError(f"GoodVibes source s{did} joined more than once")
        unused.remove(did)
        joined[sid] = {"gaussian_id":sid, "goodvibes_id":did,
                       "energy_delta_Eh":log["energy_Eh"]-d["E_electronic_Eh"],
                       "gaussian_energy_Eh":log["energy_Eh"], "goodvibes":d}
    if unused:
        raise ValueError(f"unmatched GoodVibes reports: {sorted(unused)}")
    return joined


def _dist(a,b):
    return math.sqrt(sum((a[i]-b[i])**2 for i in range(3)))


def _dot(a,b):
    return sum(a[i]*b[i] for i in range(3))


def projection(log, atom_indices):
    """Compute C-Nu and C-X mode projections; inputs are 1-based atom indices."""
    geom = {a["index"]:a for a in log["geometry"]["atoms"]}
    c_i, nu_i, x_i = atom_indices
    if not all(i in geom for i in atom_indices):
        raise ValueError("mapped atom absent from Gaussian geometry")
    expected = ["C", "N" if log["context"] == "E1-entry-28" else "O",
                "F" if log["context"] == "E1-entry-28" else "Cl"]
    actual = [ATOMIC_SYMBOLS.get(geom[i]["atomic_number"]) for i in atom_indices]
    if actual != expected:
        raise ValueError(f"mapped element mismatch: expected {expected}, found {actual}")
    c, nu, x = [geom[i]["xyz_A"] for i in atom_indices]
    r_cn = [nu[k]-c[k] for k in range(3)]
    r_cx = [x[k]-c[k] for k in range(3)]
    d_cn = _dist(c,nu); d_cx = _dist(c,x)
    u_cn=[v/d_cn for v in r_cn]; u_cx=[v/d_cx for v in r_cx]
    mode=log["negative_modes"][0]
    v=mode["vector_by_atom"]
    dr_cn=_dot([v[nu_i][k]-v[c_i][k] for k in range(3)],u_cn)
    dr_cx=_dot([v[x_i][k]-v[c_i][k] for k in range(3)],u_cx)
    phase = 1.0 if dr_cn >= 0 else -1.0
    return {"mapped_atom_indices_1based":{"C":c_i,"nucleophile":nu_i,"leaving_group":x_i},
            "mapped_elements":dict(zip(["C","nucleophile","leaving_group"],actual)),
            "distances_A":{"C_nucleophile":d_cn,"C_leaving_group":d_cx},
            "projection_formula":"(v_nucleophile-v_C) dot unit(r_nucleophile-r_C) - (v_leaving_group-v_C) dot unit(r_leaving_group-r_C)",
            "dr_C_nucleophile":dr_cn, "dr_C_leaving_group":dr_cx,
            "projected_delta_r":dr_cn-dr_cx,
            "sign_invariant_abs_projected_delta_r":abs(dr_cn-dr_cx),
            "sign_invariant_opposite_direction":dr_cn*dr_cx < 0,
            "global_phase_choice":"multiply by +1 if raw dR(C-Nu) >= 0 else -1; comparison convention only, not a reaction direction",
            "global_phase_factor":phase,
            "phase_normalized_dr_C_nucleophile":phase*dr_cn,
            "phase_normalized_dr_C_leaving_group":phase*dr_cx,
            "phase_normalized_projected_delta_r":phase*(dr_cn-dr_cx),
            "mode_direction_interpretation":"not assigned; the eigenvector global sign is arbitrary and no path connection is supplied",
            "displacement_unit":"not declared by Gaussian printed normal-coordinate table",
            "mode_vectors_for_mapped_atoms":{str(i):mode["vector_by_atom"][i] for i in atom_indices},
            "coordinates_for_mapped_atoms_A":{str(i):geom[i]["xyz_A"] for i in atom_indices}}


def partial_role_projection(sid, atoms):
    context, carbon, nucleophile, leaving_group = REACTIVE_ROLE_MAPS[sid]
    coordinates = {atom["atom_index_1based"]: atom["xyz_angstrom"] for atom in atoms}
    def distance(first, second):
        if first is None or second is None:
            return None
        return math.dist(coordinates[first], coordinates[second])
    return {"context_id": context,
            "central_carbon_atom_index_1based": carbon,
            "nucleophile_atom_index_1based": nucleophile,
            "leaving_group_atom_index_1based": leaving_group,
            "C_Nu_distance_angstrom": distance(carbon, nucleophile),
            "C_X_distance_angstrom": distance(carbon, leaving_group),
            "projected_C_Nu_change_raw": None,
            "projected_C_X_change_raw": None,
            "projected_delta_r_raw": None,
            "sign_equivalent_magnitude": None,
            "projection_units": None}


def _dump_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def _line_no(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _last_match(lines, pattern, start=0, end=None):
    end = len(lines) if end is None else end
    found = [(i + 1, re.search(pattern, lines[i])) for i in range(start, end)
             if re.search(pattern, lines[i])]
    return found[-1] if found else (None, None)


def _criteria_in(lines):
    names = ("Maximum Force", "RMS Force", "Maximum Displacement", "RMS Displacement")
    label_pattern = {"RMS Force": r"RMS\s+Force", "RMS Displacement": r"RMS\s+Displacement"}
    patterns = {name: re.compile(r"^\s*" + label_pattern.get(name, re.escape(name)) +
                r"\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?)\s+"
                r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?)\s+(YES|NO)\s*$")
                for name in names}
    result = {}
    for i, line in enumerate(lines, 1):
        for name, pattern in patterns.items():
            m = pattern.match(line)
            if m:
                result[name] = {"value": _float(m.group(1)), "threshold": _float(m.group(2)),
                                "pass": m.group(3), "line_1based": i}
    return result


def _gaussian_contract_record(sid, rec):
    text = rec["text"]
    lines = text.splitlines()
    harmonic = next((i + 1 for i, line in enumerate(lines)
                     if "Harmonic frequencies" in line), None)
    if harmonic is None:
        raise ValueError(f"harmonic block missing in {rec['path'].name}")
    freq_line = next((i + 1 for i, line in enumerate(lines[harmonic - 1:], harmonic - 1)
                      if re.search(r"^\s*Frequencies --", line)), None)
    if freq_line is None:
        raise ValueError(f"formal frequency rows missing in {rec['path'].name}")
    previous_normal, _ = _last_match(lines, r"Normal termination of Gaussian", 0, harmonic - 1)
    floor = (previous_normal + 1) if previous_normal else 1
    final_normal, normal_match = _last_match(lines, r"Normal termination of Gaussian\s+16 at (.+?)\s*$")
    route_line, route_match = next(((i + 1, re.match(r"^\s*(#.*)$", line))
                                    for i, line in enumerate(lines[floor - 1:harmonic - 1], floor - 1)
                                    if re.match(r"^\s*#", line)), (None, None))
    # The Gaussian route may be wrapped across several lines. Preserve the first route line
    # as the identifying source text and its exact source line.
    route = route_match.group(1).strip() if route_match else ""
    prior_completion, _ = _last_match(lines, r"Optimization completed\.", 0, (floor - 1))
    prior_stationary, _ = _last_match(lines, r"-- Stationary point found\.", 0, (floor - 1))
    prior_criteria = {}
    if prior_completion:
        prior_criteria = _criteria_in(lines[:prior_completion])
    freq_end = final_normal or len(lines)
    frequency_segment = lines[floor - 1:freq_end]
    freq_criteria = _criteria_in(frequency_segment)
    for criterion in freq_criteria.values():
        criterion["line_1based"] += floor - 1
    freq_completion_rel, _ = _last_match(frequency_segment, r"Optimization completed\.")
    freq_stationary_rel, _ = _last_match(frequency_segment, r"-- Stationary point found\.")
    freq_completion = floor + freq_completion_rel - 1 if freq_completion_rel else None
    freq_stationary = floor + freq_stationary_rel - 1 if freq_stationary_rel else None
    gradient_names = ("Maximum Force", "RMS Force")
    all_names = gradient_names + ("Maximum Displacement", "RMS Displacement")
    gradient_pass = len(freq_criteria) == 4 and all(freq_criteria.get(k, {}).get("pass") == "YES" for k in gradient_names)
    all_pass = len(freq_criteria) == 4 and all(freq_criteria.get(k, {}).get("pass") == "YES" for k in all_names)
    # Use the last complete Standard orientation before the formal harmonic block;
    # Input orientation is the documented fallback for checkpoint/allcheck links.
    before_offset = sum(len(x) + 1 for x in lines[:harmonic - 1])
    geometry_matches = [m for m in re.finditer(r"(?m)^[ \t]*(Standard|Input) orientation:[ \t]*$", text)
                        if m.start() < before_offset]
    preferred = [m for m in geometry_matches if m.group(1) == "Standard"] or geometry_matches
    geometry = None
    for gm in reversed(preferred):
        geometry = _parse_orientation(text, gm.start())
        if geometry:
            geometry["frame_kind"] = "Standard orientation" if gm.group(1) == "Standard" else "Input orientation"
            break
    if not geometry:
        raise ValueError(f"no complete geometry before formal harmonic block in {rec['path'].name}")
    atoms = [{"atom_index_1based": a["index"], "atomic_number": a["atomic_number"],
              "element": ATOMIC_SYMBOLS.get(a["atomic_number"], "Z" + str(a["atomic_number"])),
              "xyz_angstrom": a["xyz_A"], "line_1based": a["line_1based"]}
             for a in geometry["atoms"]]
    formal_negative = [m for m in rec["negative_modes"]]
    neg_rows = []
    reactive_projection = None
    atom_numbers = {str(a["atom_index_1based"]): a["atomic_number"] for a in atoms}
    for mode in formal_negative:
        neg = {"mode_index_zero_based": mode["mode_index"],
               "frequency_cm-1": mode["frequency_cm-1"],
               "vector_atoms": {str(k): v for k, v in mode["vector_by_atom"].items()},
               "vector_atomic_numbers": atom_numbers,
               "vector_coordinate_kind": "Gaussian printed normal-coordinate components",
               "vector_units_reported": None,
               "source_line_range_1based": mode["source_line_range"],
               "vector_line_range_1based": mode["vector_line_range"]}
        atom_map = {"456": ("E1-entry-28", (8, 21, 9)),
                    "797": ("E1-entry-28", (8, 21, 9)),
                    "1584": ("E1-entry-90", (2, 17, 1))}.get(sid)
        if atom_map:
            rec["context"] = atom_map[0]
            p = projection(rec, atom_map[1])
            reactive_projection = {
                "context_id": atom_map[0],
                "central_carbon_atom_index_1based": atom_map[1][0],
                "nucleophile_atom_index_1based": atom_map[1][1],
                "leaving_group_atom_index_1based": atom_map[1][2],
                "C_Nu_distance_angstrom": p["distances_A"]["C_nucleophile"],
                "C_X_distance_angstrom": p["distances_A"]["C_leaving_group"],
                "projected_C_Nu_change_raw": p["dr_C_nucleophile"],
                "projected_C_X_change_raw": p["dr_C_leaving_group"],
                "projected_delta_r_raw": p["projected_delta_r"],
                "sign_equivalent_magnitude": p["sign_invariant_abs_projected_delta_r"],
                "projection_units": None,
                "formula": "dot(u_CNu, v_Nu-v_C) - dot(u_CX, v_X-v_C)",
                "projection_note": "Derived from source-printed normal-coordinate components; no Cartesian displacement unit is reported by Gaussian."}
        neg_rows.append(neg)
    prior_all_pass = len(prior_criteria) == 4 and all(prior_criteria.get(k, {}).get("pass") == "YES" for k in all_names)
    prior_evidence_complete = bool(prior_completion and prior_stationary and previous_normal and prior_all_pass)
    frequency_evidence_complete = bool(freq_completion and freq_stationary and all_pass)
    if len(formal_negative) == 1:
        if not (prior_evidence_complete or frequency_evidence_complete):
            raise ValueError(f"s{sid}: formal negative mode lacks converged optimization evidence for saddle interpretation")
        interpretation = "converged_first_order_saddle_candidate"
    elif len(formal_negative) > 1:
        if not (prior_evidence_complete or frequency_evidence_complete):
            raise ValueError(f"s{sid}: formal negative modes lack converged optimization evidence for saddle interpretation")
        interpretation = "higher_order_saddle_candidate"
    elif frequency_evidence_complete:
        interpretation = "optimized_minimum_candidate"
    else:
        # A completed prior optimization remains a minimum candidate, while a
        # failed/incomplete frequency link also permits the conservative unresolved reading.
        interpretation = "unresolved"
    if freq_completion and freq_stationary and all_pass:
        stationarity = "source_reported_stationary_with_all_four_criteria"
    else:
        stationarity = "not_proven"
    result = {
        "source_file": rec["path"].name, "n_atoms": geometry["atom_count"],
        "formal_mode_count": rec["mode_count"], "formal_negative_mode_count": len(formal_negative),
        "harmonic_block_line_1based": harmonic,
        "frequency_link_floor_line_1based": floor,
        "frequency_route": route, "frequency_route_line_1based": route_line,
        "geometry_frame_kind": geometry["frame_kind"],
        "geometry_header_line_1based": geometry["line_start"], "geometry_atoms": atoms,
        "prior_geometry_optimization": {
            "optimization_completed_line_1based": prior_completion,
            "stationary_point_line_1based": prior_stationary,
            "force_criteria": prior_criteria,
            "normal_termination_line_1based": previous_normal,
            "geometry_source_relation": ("frequency-link checkpoint/input follows prior normally terminated optimization link"
                if prior_completion and previous_normal else
                "frequency-only link has no prior linked optimization completion")},
        "frequency_level_force_criteria": freq_criteria,
        "frequency_level_gradient_status": "gradient_criteria_converged" if gradient_pass else "gradient_criteria_not_converged",
        "frequency_level_all_four_criteria_status": "all_four_criteria_converged" if all_pass else "not_all_four_criteria_converged",
        "frequency_link_optimization_completed_line_1based": freq_completion,
        "frequency_link_stationary_point_line_1based": freq_stationary,
        "frequency_level_stationarity": stationarity,
        "stationary_point_interpretation": interpretation,
        "negative_modes": neg_rows}
    if reactive_projection is None:
        reactive_projection = partial_role_projection(sid, atoms)
    result["reactive_coordinate_projection"] = reactive_projection
    return result


def _native_contract_records(native):
    rows = []
    for item in native["records"]:
        common = {"source_file": "native-diagnostic-excerpts.json#" + str(item["job_id"]),
                  "job_id": item["job_id"],
                  "source_record": item["source_record"], "excerpts": item["excerpts"]}
        if str(item["job_id"]) == "3886694":
            joined = "\n".join(e["text"] for e in item["excerpts"])
            freqs = [_float(x) for x in re.findall(r"(?m)^\s*\d+:\s*([+-]?[\d.]+)\s+cm\*\*-1", joined)]
            temp = re.search(r"THERMOCHEMISTRY AT\s+([\d.]+)K", joined)
            gibbs = re.search(r"Final Gibbs free energy\s*\.\.\.\s*([+-]?[\d.]+)\s+Eh", joined)
            convergence = re.search(r"Geometry convergence\|[-\s\S]*?\.\.\.+", joined)
            coord = item["coordinate_source"]
            coord_text = coord["text"]
            coord_lines = coord_text.splitlines()
            try:
                atom_count = int(coord_lines[0].strip())
            except Exception as exc:
                raise ValueError("native coordinate atom-count header is malformed") from exc
            yes_count = len(re.findall(r"(?m)^.*\bYES\s*$", joined))
            common.update({
                "engine_termination": {"status": "normal", "failed_module": None,
                                       "reason": "ORCA TERMINATED NORMALLY appears in the supplied source excerpt."},
                "frequencies_count": len(freqs),
                "negative_frequency_count": sum(x < 0 for x in freqs),
                "frequency_zero_or_near_zero_count": sum(abs(x) < 1 for x in freqs),
                "geometry_convergence_yes_line_count": yes_count,
                "thermochemistry_temperature_K": float(temp.group(1)) if temp else None,
                "final_gibbs_hartree": float(gibbs.group(1)) if gibbs else None,
                "coordinate_atom_count": atom_count,
                "coordinate_source_line_count": len(coord_lines),
                "final_gibbs_hartree_source_present": bool(gibbs),
                "coordinate_source": coord})
        else:
            status = item["execution_status"]["content"]
            receipt = item["scheduler_receipt"]
            sched = receipt["scheduler"]
            sacct = sched["sacct_receipt"]
            common.update({"engine_termination": {"status": "failed", "failed_module": "PROPINT",
                                                   "reason": "The ORCA source excerpt reports a PROPINT exit 139."},
                           "engine_error_code": status.get("error"),
                           "execution_state": status.get("state"),
                           "scheduler_state": sched.get("state"),
                           "scheduler_exit_code": sched.get("exit_code"),
                           "sacct_job_id": sacct.get("JobIDRaw"),
                           "mpi_openfabrics_causality": {"established": False,
                                                          "reason": "The artifacts establish a PROPINT engine failure and scheduler record, but do not establish MPI/OpenFabrics as its cause."}})
        rows.append(common)
    return rows


def _write_jsonl(path, rows):
    atomic_write(path, "".join(json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n" for row in rows))


def _analyze_v3(assets: Path, out: Path, *, replay=False):
    logs = {sid: parse_gaussian(assets / f"SC-012-D0SC04896H-s{sid}.log") for sid in GAUSSIAN_IDS}
    dats = {sid: parse_goodvibes(assets / f"SC-012-D0SC04896H-s{sid}.dat") for sid in GOODVIBES_IDS}
    joins = join_records(logs, dats)
    gaussian_for_d = {j["goodvibes_id"]: logs[gid] for gid, j in joins.items()}
    source_join_rows = []
    for goodvibes_id in GOODVIBES_IDS:
        d = dats[goodvibes_id]
        g = gaussian_for_d[goodvibes_id]
        glines = g["text"].splitlines()
        scf_matches = list(re.finditer(r"SCF Done:\s+E\([^)]*\)\s*=\s*(-?\d+\.\d+)", g["text"]))
        zpe_match = re.search(r"(?m)^[ \t]*Zero-point correction=[ \t]*([+-]?[\d.]+)[ \t]*\(Hartree/Particle\)", g["text"])
        normal_match = list(re.finditer(r"Normal termination of Gaussian\s+16 at (.+?)\s*$", g["text"], re.M))
        if not (scf_matches and zpe_match and normal_match and d["timestamp"]):
            raise ValueError(f"incomplete Gaussian/GoodVibes provenance join: s{goodvibes_id}")
        scf = scf_matches[-1]
        zpe_line = _line_no(g["text"], zpe_match.start())
        normal = normal_match[-1]
        source_join_rows.append({
            "goodvibes_stem": "s" + goodvibes_id,
            "goodvibes_timestamp": d["timestamp"],
            "gaussian_stem": "s" + asset_id(g["path"]),
            "gaussian_normal_termination_timestamp": normal.group(1),
            "gaussian_normal_termination_line_1based": _line_no(g["text"], normal.start()),
            "final_scf_E_hartree": g["energy_Eh"], "final_scf_line_1based": _line_no(g["text"], scf.start()),
            "gaussian_zpe_hartree": float(zpe_match.group(1)), "gaussian_zpe_line_1based": zpe_line,
            "goodvibes_E_hartree": d["E_electronic_Eh"], "goodvibes_ZPE_hartree": d["ZPE_Eh"],
            "goodvibes_qh_G_T_hartree": d["qhG_Eh"],
            "goodvibes_H_minus_T_qhS_hartree": d["H_minus_TqhS_Eh"],
            "energy_abs_diff_hartree": abs(g["energy_Eh"] - d["E_electronic_Eh"]),
            "qh_reconciliation_abs_diff_hartree": abs(d["H_minus_TqhS_Eh"] - d["qhG_Eh"]),
            "scale_factor": d["scale_factor"], "temperature_K": d["temperature_K"],
            "concentration_mol_L": d["concentration_mol_L"],
            "standard_state": f"{d['concentration_mol_L']:g} M",
            "qs_treatment": d["quasi_harmonic_scheme"],
            "frequency_cutoff_cm-1": d["frequency_cutoff_cm-1"]})

    audit = [_gaussian_contract_record(sid, logs[sid]) for sid in GAUSSIAN_IDS]
    joins_by_gaussian = {item["gaussian_stem"]: dict(item)
                         for item in source_join_rows}
    for row in audit:
        stem = "s" + asset_id(assets / row["source_file"])
        row["thermochemistry_join"] = joins_by_gaussian[stem]
    native = read_json(assets / "native-diagnostic-excerpts.json")
    audit.extend(_native_contract_records(native))
    # Each one-negative-mode complete complex is compared with its separated optimized substrate + nucleophile.
    differences = [("E1-entry-28", "s449,s326,s344", ("449", "326", "344")),
                   ("E1-entry-28", "s790,s326,s344", ("790", "326", "344")),
                   ("E1-entry-90", "s1577,s1695,s1713", ("1577", "1695", "1713"))]
    by_d = dats
    thermo_fields = ["record_type", "source_file", "source_energy_label", "source_ids", "coefficients",
                     "identity_status", "temperature_K", "concentration_mol_L", "standard_state", "energy_unit",
                     "qh_G_T_hartree", "scale_factor", "qs_treatment", "frequency_cutoff_cm-1", "convention",
                     "candidate_delta_g_kcal_mol", "reaction_barrier_kcal_mol", "reaction_barrier_status"]
    thermo = []
    for sid in GOODVIBES_IDS:
        d = dats[sid]
        g = gaussian_for_d[sid]
        convention = (f"GoodVibes qh-G(T); {d['temperature_K']:g} K; {d['concentration_mol_L']:g} M; "
                      f"{d['quasi_harmonic_scheme']} QS; cutoff {d['frequency_cutoff_cm-1']:g} cm-1; "
                      f"scale {d['scale_factor']:g}")
        thermo.append({"record_type": "source", "source_file": d["path"].name,
                       "source_energy_label": d["energy_label"],
                       "source_ids": "", "coefficients": "",
                       "identity_status": "", "temperature_K": d["temperature_K"],
                       "concentration_mol_L": d["concentration_mol_L"],
                       "standard_state": f"{d['concentration_mol_L']:g} M",
                       "energy_unit": d["energy_unit"], "qh_G_T_hartree": d["qhG_Eh"],
                       "scale_factor": d["scale_factor"], "qs_treatment": d["quasi_harmonic_scheme"],
                       "frequency_cutoff_cm-1": d["frequency_cutoff_cm-1"], "convention": convention,
                       "candidate_delta_g_kcal_mol": "", "reaction_barrier_kcal_mol": "",
                       "reaction_barrier_status": ""})
    diff_rows = []
    for ctx, source_ids, ids in differences:
        a, b, c = (by_d[k] for k in ids)
        if len({a["temperature_K"], b["temperature_K"], c["temperature_K"]}) != 1 or len({a["concentration_mol_L"], b["concentration_mol_L"], c["concentration_mol_L"]}) != 1 or len({a["quasi_harmonic_scheme"], b["quasi_harmonic_scheme"], c["quasi_harmonic_scheme"]}) != 1:
            raise ValueError(f"incompatible GoodVibes convention in {source_ids}")
        dg = (a["qhG_Eh"] - b["qhG_Eh"] - c["qhG_Eh"]) * EH_TO_KCAL
        diff_rows.append({"record_type": "candidate_difference", "source_file": "", "source_energy_label": "",
                          "source_ids": source_ids, "coefficients": "+1,-1,-1",
                          "identity_status": "supported_by_atom_inventory_and_reactive_geometry",
                          "temperature_K": a["temperature_K"], "concentration_mol_L": "",
                          "standard_state": "1 M", "energy_unit": "",
                          "qh_G_T_hartree": "", "scale_factor": "",
                          "qs_treatment": "", "frequency_cutoff_cm-1": "",
                          "convention": "", "candidate_delta_g_kcal_mol": dg,
                          "reaction_barrier_kcal_mol": "",
                          "reaction_barrier_status": "unresolved_no_proven_path_connection_and_join"})
    thermo.extend(diff_rows)
    # Interpret the locally observed coordinates, independently of the grader.
    # No path connectivity or real global kinetics are inferred from these roles.
    mechanisms = []
    gv_for_log = {item["gaussian_stem"]: item["goodvibes_stem"] for item in source_join_rows}
    qh_for_log = {stem: dats[gv[1:]]["qhG_Eh"] for stem, gv in gv_for_log.items()}
    for context in sorted({roles[0] for roles in REACTIVE_ROLE_MAPS.values()}):
        complete = [record for record in audit if record.get("reactive_coordinate_projection", {}).get("context_id") == context
                    and all(record["reactive_coordinate_projection"].get(key) is not None for key in
                            ("central_carbon_atom_index_1based", "nucleophile_atom_index_1based", "leaving_group_atom_index_1based"))]
        local_steps, intermediates = {}, []
        for record in complete:
            stem = "s" + asset_id(Path(record["source_file"]))
            if not record["negative_modes"]:
                intermediates.append(stem)
            elif len(record["negative_modes"]) == 1:
                mode = record["reactive_coordinate_projection"]
                cn, cx = mode["projected_C_Nu_change_raw"], mode["projected_C_X_change_raw"]
                if cn * cx >= 0 or abs(cn) == abs(cx):
                    raise ValueError("reactive mode does not resolve a local substitution coordinate")
                local_steps[stem] = "addition_like" if abs(cn) > abs(cx) else "elimination_like"
        sequential = (list(local_steps.values()).count("addition_like") == 1
                      and list(local_steps.values()).count("elimination_like") == 1 and len(intermediates) == 1)
        model, step = "none", "unresolved"
        if sequential:
            addition = next(stem for stem, role in local_steps.items() if role == "addition_like")
            elimination = next(stem for stem, role in local_steps.items() if role == "elimination_like")
            add_delta = next(row["candidate_delta_g_kcal_mol"] for row in diff_rows
                             if row["source_ids"].split(",")[0] == gv_for_log[addition])
            local_barriers = {"addition": add_delta,
                              "elimination": (qh_for_log[elimination] - qh_for_log[intermediates[0]]) * EH_TO_KCAL}
            model = "irreversible_equal_prefactors_unit_activity"
            step = ("unresolved" if math.isclose(local_barriers["addition"], local_barriers["elimination"], rel_tol=0.0, abs_tol=0.01)
                    else max(local_barriers, key=local_barriers.get))
        mapped = complete[0]["reactive_coordinate_projection"]
        carbon, nu, leaving = (mapped[key] for key in ("central_carbon_atom_index_1based", "nucleophile_atom_index_1based", "leaving_group_atom_index_1based"))
        elements = {a["atom_index_1based"]: a["element"] for a in complete[0]["geometry_atoms"]}
        mechanisms.append({"context_id": context, "claim_scope": "local_context",
            "reactive_site": f"C{carbon}/Nu{nu}/{elements[leaving]}{leaving}",
            "identity_status": "supported_by_atom_inventory_and_reactive_geometry",
            "mechanism": "stepwise_SNAr_candidate" if sequential else "SNAr_candidate",
            "mechanism_evidence": json.dumps({"local_steps": local_steps, "intermediate_candidates": intermediates}),
            "rate_determining_step (global)": "unresolved",
            "model_conditional_RDS": json.dumps({"model": model, "step": step}),
            "barrier_status": "local_saddle_energy_difference_path_unvalidated"})
    failures = [
        {"reason_code": "global_rate_determining_step_unresolved", "source_ids": ["E1-entry-28", "E1-entry-90"],
         "reason": "Neither context has complete connected path evidence establishing a global rate-determining step."},
        {"reason_code": "formal_barrier_path_connection_missing", "source_ids": ["s456", "s797", "s1584"],
         "reason": "No IRC or equivalent path connection is supplied for the three first-order saddle candidates; formal reaction barriers remain unresolved."},
        {"reason_code": "native_3887010_engine_failure_not_scheduler_cause", "source_ids": ["native-diagnostic-excerpts.json#3887010"],
         "reason": "ORCA reports PROPINT exit 139 while Slurm reports FAILED 1:0. MPI/OpenFabrics causality is suspected only, not established."}]
    out.mkdir(parents=True, exist_ok=True)
    contracted = {"mechanism.csv", "artifact_audit.jsonl", "thermochemistry.csv", "failures.jsonl",
                  "analyze.py", "notes.md"}
    unexpected = [p.name for p in out.iterdir() if p.name not in contracted]
    if unexpected:
        raise ValueError(f"output directory contains files outside the four-file-plus-optional contract: {sorted(unexpected)}")
    if replay:
        replay_names = {"artifact_audit.jsonl", "thermochemistry.csv", "failures.jsonl"}
        for name in contracted - replay_names:
            p = out / name
            if p.exists():
                p.unlink()
        _write_jsonl(out / "artifact_audit.jsonl", audit)
        _dump_csv(out / "thermochemistry.csv", thermo, thermo_fields)
        _write_jsonl(out / "failures.jsonl", failures)
        return
    for name in ("mechanism.csv", "notes.md", "analyze.py"):
        p = out / name
        if p.exists():
            p.unlink()
    _write_jsonl(out / "artifact_audit.jsonl", audit)
    _dump_csv(out / "thermochemistry.csv", thermo, thermo_fields)
    _dump_csv(out / "mechanism.csv", mechanisms, ["context_id", "claim_scope", "reactive_site", "identity_status", "mechanism",
        "mechanism_evidence", "rate_determining_step (global)", "model_conditional_RDS", "barrier_status", "dg_kcal_mol", "temperature_K", "convention", "source_ids"])
    _write_jsonl(out / "failures.jsonl", failures)
    # Publish each scientific observation once; full source tables stay in the inputs.
    compact_audit = []
    for row in audit:
        row = dict(row)
        if "negative_modes" in row:
            prior = row["prior_geometry_optimization"]
            row["prior_geometry_optimization"] = {
                "optimization_completed": prior.get("optimization_completed_line_1based") is not None,
                "stationary_point_observed": prior.get("stationary_point_line_1based") is not None,
                "normal_termination": prior.get("normal_termination_line_1based") is not None,
                "failed_criteria": [key for key, value in prior["force_criteria"].items() if value["pass"] != "YES"]}
            row["frequency_level_force_criteria"] = {"failed_criteria": [key for key, value in row["frequency_level_force_criteria"].items() if value["pass"] != "YES"]}
            for line, flag in (("frequency_link_optimization_completed_line_1based", "frequency_link_optimization_completed"),
                               ("frequency_link_stationary_point_line_1based", "frequency_link_stationary_point_observed")):
                row[flag] = row.get(line) is not None
            row["thermochemistry_join"] = {key: row["thermochemistry_join"][key] for key in ("final_scf_E_hartree", "gaussian_zpe_hartree")}
            row["negative_modes"] = [{"frequency_cm-1": mode["frequency_cm-1"]} for mode in row["negative_modes"]]
            for field in ("geometry_atoms", "n_atoms", "formal_mode_count", "formal_negative_mode_count", "frequency_level_stationarity",
                          "frequency_link_optimization_completed_line_1based", "frequency_link_stationary_point_line_1based"):
                row.pop(field, None)
            for field in ("projection", "reactive_coordinate_projection"):
                if isinstance(row.get(field), dict):
                    for key in ("projected_delta_r_raw", "sign_equivalent_magnitude", "projection_note", "formula"): row[field].pop(key, None)
        else:
            row.pop("source_file", None)
            if "geometry_convergence_yes_line_count" in row: row["geometry_converged"] = row["geometry_convergence_yes_line_count"] >= 5
            for field in ("coordinate_source_line_count", "sacct_job_id", "geometry_convergence_yes_line_count", "final_gibbs_hartree_source_present", "coordinate_source"): row.pop(field, None)
        compact_audit.append(row)
    _write_jsonl(out / "artifact_audit.jsonl", compact_audit)
    drop_thermo = {"source_energy_label", "standard_state", "energy_unit", "convention", "reaction_barrier_kcal_mol", "reaction_barrier_status"}
    _dump_csv(out / "thermochemistry.csv", [{key: value for key, value in row.items() if key not in drop_thermo} for row in thermo], [key for key in thermo_fields if key not in drop_thermo])
    drop_mech = {"dg_kcal_mol", "temperature_K", "convention", "source_ids"}
    compact_mech = [{**{key: value for key, value in row.items() if key not in drop_mech}, "path_connectivity": "unvalidated"} for row in mechanisms]
    _dump_csv(out / "mechanism.csv", compact_mech, list(compact_mech[0]))
    (out / "failures.jsonl").unlink(missing_ok=True)



def analyze(assets: Path, out: Path):
    _analyze_v3(assets, out)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--assets",type=Path,default=Path("/app/assets"))
    ap.add_argument("--output", "--out", dest="output", type=Path, default=Path("/app/final"))
    ap.add_argument("--case01-reproduce", action="store_true")
    args=ap.parse_args()
    _analyze_v3(args.assets,args.output,replay=args.case01_reproduce)


if __name__=="__main__":
    main()
__TASK1_PYTHON_SOURCE_1__

ASSETS="${1:-/app/assets}"
OUTPUT="${2:-/app/final}"
python3 "$WORK/analyze.py" --assets "$ASSETS" --output "$OUTPUT"
