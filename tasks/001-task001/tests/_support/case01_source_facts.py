#!/usr/bin/env python3
"""Parse the frozen Case 01 Gaussian, GoodVibes, and native source facts."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from itertools import combinations
import hashlib
import json
import math
import re
import sys
from pathlib import Path


CASE_ID = "case-01-snar-mechanism-transition-state"
HARTREE_TO_KCAL = 627.5094740631
LOGS = ("s325", "s343", "s456", "s353", "s1694", "s1712", "s1584", "s797")
THERMO = ("s326", "s344", "s449", "s350", "s1695", "s1713", "s1577", "s790")
DEFAULT_QH_GAUSSIAN_PAIRS = {"s449": "s456", "s790": "s797", "s1577": "s1584",
                            "s326": "s325", "s344": "s343", "s350": "s353",
                            "s1695": "s1694", "s1713": "s1712"}
ATOMIC_SYMBOLS = {1: "H", 6: "C", 7: "N", 8: "O", 9: "F", 17: "Cl"}
FORCE_CRITERIA = ("Maximum Force", "RMS Force", "Maximum Displacement", "RMS Displacement")


class SourceError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _float_list(text: str) -> list[float]:
    values = [float(x.replace("D", "E")) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?", text)]
    if any(not math.isfinite(x) for x in values):
        raise SourceError("non-finite numeric value in source")
    return values


def _orientation(lines: list[str], before: int, floor: int, route: str) -> dict:
    starts = [i for i, line in enumerate(lines[floor:before], start=floor)
              if "orientation:" in line.lower()]
    standards = [i for i in starts if "standard orientation:" in lines[i].lower()]
    inputs = [i for i in starts if "input orientation:" in lines[i].lower()]
    candidates = list(reversed(standards))
    if not candidates and ("geom=allcheck" in route.lower() or "nosymm" in route.lower()):
        candidates = list(reversed(inputs))
    for start in candidates:
        rows = []
        separator_count = 0
        for i in range(start + 1, min(before, start + 100)):
            line = lines[i]
            if "Center" in line and "Atomic" in line and "Coordinates" in line:
                continue
            if set(line.strip()) == {"-"} and line.strip():
                separator_count += 1
                if separator_count >= 3:
                    break
                continue
            if separator_count >= 2:
                fields = line.split()
                if len(fields) >= 6 and fields[0].isdigit() and fields[1].isdigit() and fields[2].isdigit():
                    try:
                        rows.append({"atom_index_1based": int(fields[0]),
                                     "atomic_number": int(fields[1]),
                                     "element": ATOMIC_SYMBOLS.get(int(fields[1]), "Z" + fields[1]),
                                     "xyz_angstrom": [float(x) for x in fields[3:6]],
                                     "line_1based": i + 1})
                    except ValueError:
                        pass
                elif rows:
                    break
        if rows:
            header = " ".join(line.strip() for line in lines[start:min(before, start + 5)])
            if "coordinates (angstroms)" not in header.lower():
                raise SourceError("Gaussian geometry coordinates are not explicitly in Angstroms")
            if "standard orientation:" in lines[start].lower():
                frame_kind = "Standard orientation"
            elif "input orientation:" in lines[start].lower():
                frame_kind = "Input orientation"
            else:
                raise SourceError("Gaussian geometry frame type is not recognized")
            return {"orientation_header_line_1based": start + 1,
                    "source_kind": header, "frame_kind": frame_kind,
                    "coordinates_unit": "Angstroms",
                    "atoms": rows}
    raise SourceError("no complete Gaussian orientation table precedes the frequency block")


def _force_criteria(lines: list[str], start: int, stop: int) -> dict:
    labels = ("Maximum Force", "RMS Force", "Maximum Displacement", "RMS Displacement")
    result = {}
    for label in labels:
        pattern = re.compile(r"^\s*" + re.escape(label).replace(r"\ ", r"\s+") +
                             r"\s+([-+\d.]+)\s+([-+\d.]+)\s+(YES|NO)\s*$")
        found = [(i, match) for i, line in enumerate(lines[start:stop], start=start)
                 if (match := pattern.match(line))]
        if found:
            i, match = found[-1]
            result[label] = {"value": float(match.group(1)), "threshold": float(match.group(2)),
                             "pass": match.group(3), "line_1based": i + 1}
    return result


def derive_stationary_evidence(source: dict) -> dict:
    """Derive interpretation options from parsed observations, never from candidate labels."""
    prior = source["prior_geometry_optimization"]
    frequency = source["frequency_level_force_criteria"]
    prior_criteria = prior.get("force_criteria", {})

    def all_four_pass(criteria: dict) -> bool:
        return (set(criteria) == set(FORCE_CRITERIA)
                and all(criteria[key].get("pass") == "YES" for key in FORCE_CRITERIA))

    prior_completion = prior.get("optimization_completed_line_1based") is not None
    prior_stationary = prior.get("stationary_point_line_1based") is not None
    prior_normal = prior.get("normal_termination_line_1based") is not None
    prior_all_four = all_four_pass(prior_criteria)
    frequency_completion = source.get("frequency_link_optimization_completed_line_1based") is not None
    frequency_stationary = source.get("frequency_link_stationary_point_line_1based") is not None
    frequency_all_four = all_four_pass(frequency)
    frequency_stationarity_complete = frequency_completion and frequency_stationary and frequency_all_four
    prior_minimum_evidence = prior_completion and prior_stationary and prior_normal and prior_all_four
    negative_count = source.get("formal_negative_mode_count")
    if type(negative_count) is not int or negative_count < 0:
        raise SourceError("formal negative mode count is invalid")

    if negative_count == 1:
        allowed = (["converged_first_order_saddle_candidate"]
                   if prior_minimum_evidence or frequency_stationarity_complete else [])
    elif negative_count > 1:
        allowed = (["higher_order_saddle_candidate"]
                   if prior_minimum_evidence or frequency_stationarity_complete else [])
    elif frequency_stationarity_complete:
        allowed = ["optimized_minimum_candidate"]
    elif prior_minimum_evidence:
        allowed = ["optimized_minimum_candidate", "unresolved"]
    else:
        allowed = ["unresolved"]

    limitations = []
    if not frequency_completion:
        limitations.append("The frequency link has no Optimization completed event.")
    if not frequency_stationary:
        limitations.append("The frequency link has no Stationary point found event.")
    if not frequency_all_four:
        for key in FORCE_CRITERIA:
            item = frequency.get(key)
            if item is None:
                limitations.append(f"Frequency-link {key} criterion is absent.")
            elif item.get("pass") != "YES":
                limitations.append(
                    f"Frequency-link {key} is {item.get('value')} against threshold "
                    f"{item.get('threshold')} (source pass={item.get('pass')}).")
    if not limitations:
        limitations.append("The frequency link reports completion, stationarity, and all four criteria passing.")

    return {
        "observed": {
            "formal_negative_mode_count": negative_count,
            "prior_optimization_completed": prior_completion,
            "prior_stationary_point_observed": prior_stationary,
            "prior_normal_termination": prior_normal,
            "prior_all_four_criteria_pass": prior_all_four,
            "frequency_link_optimization_completed": frequency_completion,
            "frequency_link_stationary_point_observed": frequency_stationary,
            "frequency_link_all_four_criteria_pass": frequency_all_four,
            "frequency_level_stationarity_complete": frequency_stationarity_complete,
        },
        "allowed_interpretations": allowed,
        "limitations": limitations,
    }


def parse_gaussian(path: Path, asset_name: str) -> dict:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise SourceError(f"cannot read {asset_name}: {exc}") from exc
    starts = [i for i, line in enumerate(lines) if "Harmonic frequencies (cm" in line]
    if len(starts) != 1:
        raise SourceError(f"{asset_name}: expected one formal Harmonic frequencies block, found {len(starts)}")
    block_start = starts[0]
    link_boundaries = [i for i, line in enumerate(lines[:block_start])
                       if "Normal termination of Gaussian" in line]
    link_floor = link_boundaries[-1] + 1 if link_boundaries else 0
    natom_candidates = [(i, int(m.group(1))) for i, line in enumerate(lines[link_floor:block_start + 1], start=link_floor)
                        if (m := re.search(r"\bNAtoms=\s*(\d+)", line))]
    if not natom_candidates:
        raise SourceError(f"{asset_name}: NAtoms declaration missing before harmonic block")
    natoms_line, natoms = natom_candidates[-1]
    route_rows = [(i, line.strip()) for i, line in enumerate(lines[link_floor:block_start], start=link_floor)
                  if re.match(r"\s*#", line)]
    if not route_rows:
        raise SourceError(f"{asset_name}: current frequency link has no route directive")
    route_index, route_text = route_rows[0]
    geom = _orientation(lines, block_start, link_floor, route_text)
    if len(geom["atoms"]) != natoms:
        raise SourceError(f"{asset_name}: orientation has {len(geom['atoms'])} atoms, NAtoms={natoms}")

    modes: list[dict] = []
    current: dict | None = None
    in_vectors = False
    for i in range(block_start + 1, len(lines)):
        line = lines[i]
        if i > block_start + 3 and ("Normal termination of Gaussian" in line or "Thermochemistry" in line):
            break
        freq_match = re.match(r"\s*Frequencies --\s*(.*)$", line)
        if freq_match:
            in_vectors = False
            if current is not None:
                modes.extend(current)
            freqs = _float_list(freq_match.group(1))
            current = [{"mode_index_zero_based": None, "frequency_cm-1": x,
                        "frequency_line_1based": i + 1, "vector_atoms": {},
                        "vector_atomic_numbers": {}}
                       for x in freqs]
            continue
        if current is None:
            continue
        if re.match(r"\s*Atom\s+AN\b", line):
            in_vectors = True
            continue
        if in_vectors:
            fields = line.split()
            if len(fields) < 2 or not fields[0].isdigit() or not fields[1].isdigit():
                if any("vector_atoms" in m and m["vector_atoms"] for m in current):
                    in_vectors = False
                continue
            count = len(current)
            vals = _float_list(" ".join(fields[2:]))
            if len(vals) < 3 * count:
                in_vectors = False
                continue
            atom = int(fields[0])
            atomic_number = int(fields[1])
            for j, mode in enumerate(current):
                if str(atom) in mode["vector_atoms"]:
                    raise SourceError(f"{asset_name}: duplicate normal-coordinate row for atom {atom}")
                mode["vector_atoms"][str(atom)] = vals[3 * j:3 * j + 3]
                mode["vector_atomic_numbers"][str(atom)] = atomic_number
                mode["vector_line_start_1based"] = mode.get("vector_line_start_1based", i + 1)
                mode["vector_line_end_1based"] = i + 1
    if current is not None:
        modes.extend(current)
    for index, mode in enumerate(modes):
        mode["mode_index_zero_based"] = index
        mode["source_mode_ordinal_1based"] = index + 1
        mode["vector_coordinate_kind"] = "Gaussian printed normal-coordinate components"
        mode["vector_units_reported"] = None
        mode["vector_units_note"] = "The source labels these as normal coordinates but does not declare Cartesian displacement units."
    geom_by_index = {atom["atom_index_1based"]: atom for atom in geom["atoms"]}
    origin = geom["atoms"][0]["xyz_angstrom"]
    displacements = [[a["xyz_angstrom"][k] - origin[k] for k in range(3)] for a in geom["atoms"][1:]]
    is_linear = True
    for i in range(len(displacements)):
        for j in range(i + 1, len(displacements)):
            a, b = displacements[i], displacements[j]
            cross = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
            if math.sqrt(sum(x * x for x in cross)) > 1e-6:
                is_linear = False
                break
        if not is_linear:
            break
    expected = 3 * natoms - (5 if is_linear else 6)
    linear_expected = 3 * natoms - 5
    if len(modes) != expected:
        raise SourceError(f"{asset_name}: formal mode count {len(modes)} does not match geometry-proven {'linear 3N-5' if is_linear else 'nonlinear 3N-6'} count {expected}")
    if any(len(m["vector_atoms"]) != natoms for m in modes):
        missing = [m["mode_index_zero_based"] for m in modes if len(m["vector_atoms"]) != natoms]
        raise SourceError(f"{asset_name}: normal-coordinate rows incomplete for modes {missing[:8]}")
    for mode in modes:
        if set(mode["vector_atomic_numbers"]) != {str(index) for index in geom_by_index}:
            raise SourceError(f"{asset_name}: normal-coordinate atom index inventory differs from geometry")
        for idx, atom in geom_by_index.items():
            if mode["vector_atomic_numbers"].get(str(idx)) != atom["atomic_number"]:
                raise SourceError(f"{asset_name}: normal-coordinate atomic number disagrees with geometry at atom {idx}")
    negative = [m for m in modes if m["frequency_cm-1"] < 0.0]
    normal_terminations = [i + 1 for i, line in enumerate(lines) if "Normal termination of Gaussian" in line]
    preceding_terminations = [i for i, line in enumerate(lines[:block_start])
                              if "Normal termination of Gaussian" in line]
    prior_optimization = None
    if preceding_terminations:
        prior_end = preceding_terminations[-1]
        completed = [i for i, line in enumerate(lines[:prior_end + 1]) if "Optimization completed." in line]
        if completed:
            completed_at = completed[-1]
            metrics = _force_criteria(lines, 0, completed_at + 1)
            stationary = [(i + 1, line.strip()) for i, line in enumerate(lines[:prior_end + 1])
                          if "Stationary point found." in line]
            prior_optimization = {"optimization_completed_line_1based": completed_at + 1,
                                  "stationary_point_line_1based": stationary[-1][0] if stationary else None,
                                  "force_criteria": metrics,
                                  "normal_termination_line_1based": prior_end + 1,
                                  "geometry_source_relation": "frequency-link checkpoint/input follows prior normally terminated optimization link"}
    next_termination = next((i for i in range(block_start + 1, len(lines))
                             if "Normal termination of Gaussian" in lines[i]), len(lines))
    frequency_force_criteria = _force_criteria(lines, link_floor, next_termination)
    frequency_link_completions = [i + 1 for i, line in enumerate(lines[link_floor:next_termination], start=link_floor)
                                  if "Optimization completed." in line]
    frequency_link_stationary = [i + 1 for i, line in enumerate(lines[link_floor:next_termination], start=link_floor)
                                 if "Stationary point found." in line]
    if prior_optimization is None:
        prior_optimization = {"optimization_completed_line_1based": None,
                              "stationary_point_line_1based": None,
                              "force_criteria": {},
                              "normal_termination_line_1based": None,
                              "geometry_source_relation": "frequency-only link has no prior linked optimization completion"}
    charges = {int(match.group(1)) for line in lines
               if (match := re.search(r"Charge\s*=\s*([+-]?\d+)\s+Multiplicity\s*=", line))}
    if len(charges) != 1:
        raise SourceError(f"{asset_name}: source charge is absent or ambiguous")
    result = {
        "charge": charges.pop(),
        "source_file": asset_name,
        "source_sha256": sha256(path),
        "source_bytes": path.stat().st_size,
        "harmonic_block_line_1based": block_start + 1,
        "frequency_link_floor_line_1based": link_floor + 1,
        "frequency_route": route_text,
        "frequency_route_line_1based": route_index + 1,
        "n_atoms": natoms,
        "n_atoms_line_1based": natoms_line + 1,
        "geometry": geom,
        "formal_mode_count": len(modes),
        "expected_nonlinear_modes": expected,
        "expected_linear_modes": linear_expected,
        "geometry_is_linear": is_linear,
        "formal_negative_mode_count": len(negative),
        "normal_termination_lines_1based": normal_terminations,
        "prior_geometry_optimization": prior_optimization,
        "frequency_level_force_criteria": frequency_force_criteria,
        "frequency_level_gradient_status": (
            "gradient_criteria_converged"
            if all(frequency_force_criteria.get(key, {}).get("pass") == "YES"
                   for key in ("Maximum Force", "RMS Force"))
            else "gradient_criteria_not_converged"),
        "frequency_level_all_four_criteria_status": (
            "all_four_criteria_converged"
            if set(frequency_force_criteria) == {"Maximum Force", "RMS Force", "Maximum Displacement", "RMS Displacement"}
            and all(item["pass"] == "YES" for item in frequency_force_criteria.values())
            else "not_all_four_criteria_converged"),
        "frequency_link_optimization_completed_line_1based": frequency_link_completions[-1] if frequency_link_completions else None,
        "frequency_link_stationary_point_line_1based": frequency_link_stationary[-1] if frequency_link_stationary else None,
        "frequency_level_stationarity": (
            "source_reported_stationary_with_all_four_criteria"
            if frequency_link_completions and frequency_link_stationary
            and set(frequency_force_criteria) == {"Maximum Force", "RMS Force", "Maximum Displacement", "RMS Displacement"}
            and all(item["pass"] == "YES" for item in frequency_force_criteria.values())
            else "not_proven"),
        "normal_coordinate_data_scope": "all source-reported Gaussian mode components; preserve printed sign and precision; global eigenvector sign is arbitrary",
        "modes": modes,
        "negative_modes": negative,
    }
    result["stationary_point_interpretation_evidence"] = derive_stationary_evidence(result)
    return result


def parse_goodvibes(path: Path, asset_name: str) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    temps = [(i + 1, float(m.group(1))) for i, line in enumerate(lines)
             if (m := re.search(r"Temperature\s*=\s*([-+\d.]+)\s*Kelvin", line))]
    concentrations = [(i + 1, float(m.group(1))) for i, line in enumerate(lines)
                    if (m := re.search(r"Concentration\s*=\s*([-+\d.]+)\s*mol/l", line))]
    header = [i for i, line in enumerate(lines) if "qh-G(T)" in line and "Structure" in line]
    if len(temps) != 1 or len(concentrations) != 1 or len(header) != 1:
        raise SourceError(f"{asset_name}: GoodVibes temperature/concentration/table header is ambiguous")
    rows = []
    pattern = re.compile(r"^\s*o\s+(\S+)\s+" + r"\s+".join([r"([-+]?\d+\.\d+)"] * 7) + r"\s*$")
    for i in range(header[0] + 1, len(lines)):
        match = pattern.match(lines[i])
        if match:
            vals = [float(x) for x in match.groups()[1:]]
            rows.append((i + 1, match.group(1), vals))
    if len(rows) != 1:
        raise SourceError(f"{asset_name}: expected one GoodVibes structure row, found {len(rows)}")
    line, label, values = rows[0]
    concentration = concentrations[0][1]
    energy_unit_rows = [line for line in lines if "All energetic values below shown in" in line]
    cutoff_rows = [(i + 1, float(m.group(1))) for i, line in enumerate(lines)
                   if (m := re.search(r"frequency cut-off value of\s*([-+\d.]+)\s*wavenumbers", line))]
    qs_rows = [(i + 1, m.group(1).strip()) for i, line in enumerate(lines)
               if (m := re.search(r"^\s*QS\s*=\s*([^:]+):", line))]
    if len(energy_unit_rows) != 1 or len(cutoff_rows) != 1 or len(qs_rows) != 1:
        raise SourceError(f"{asset_name}: GoodVibes unit/QS/cutoff convention is incomplete or ambiguous")
    unit_match = re.search(r"shown in\s+([A-Za-z]+)", energy_unit_rows[0])
    if not unit_match:
        raise SourceError(f"{asset_name}: GoodVibes energy unit is not parseable")
    scale_rows = [(i + 1, float(m.group(1))) for i, line in enumerate(lines)
                  if (m := re.search(r"User-defined vibrational scale factor\s+([-+\d.]+)", line))]
    if len(scale_rows) != 1:
        raise SourceError(f"{asset_name}: vibrational scale factor is incomplete or ambiguous")
    row_values = dict(zip(("E_hartree", "ZPE_hartree", "H_hartree", "T_S_hartree", "T_qh_S_hartree", "G_T_hartree", "qh_G_T_hartree"), values))
    return {"source_file": asset_name, "source_sha256": sha256(path), "source_bytes": path.stat().st_size,
            "source_line_1based": line, "source_energy_label": label,
            "temperature_K": temps[0][1], "temperature_line_1based": temps[0][0],
            "concentration_mol_L": concentration, "standard_state": f"{concentration:g} M",
            "reported_energy_unit": unit_match.group(1), "qh_G_T_hartree": values[-1],
            "scale_factor": scale_rows[0][1], "scale_factor_line_1based": scale_rows[0][0],
            "reported_values_hartree": row_values,
            "qs_treatment": qs_rows[0][1], "qs_line_1based": qs_rows[0][0],
            "frequency_cutoff_cm-1": cutoff_rows[0][1], "frequency_cutoff_line_1based": cutoff_rows[0][0],
            "thermochemistry_convention": f"GoodVibes qh-G(T); QS {qs_rows[0][1]}, {cutoff_rows[0][1]:g} cm-1 cutoff as printed"}


def verify_qh_gaussian_energy_join(goodvibes: dict, gaussian_log: Path, gaussian_stem: str) -> tuple[float, int, float]:
    lines = gaussian_log.read_text(encoding="utf-8", errors="replace").splitlines()
    scf = [(i + 1, float(m.group(1).replace("D", "E"))) for i, line in enumerate(lines)
           if (m := re.search(r"SCF Done:\s+E\(R?\w+\)\s*=\s*([-+\d.]+)", line))]
    if not scf:
        raise SourceError(f"{gaussian_stem}: no parseable final SCF energy for qh join")
    line_number, energy = scf[-1]
    diff = abs(goodvibes["reported_values_hartree"]["E_hartree"] - energy)
    if diff > 5e-7:
        raise SourceError(f"{goodvibes['source_file'].rsplit('-', 1)[-1].split('.')[0]} qh source electronic E does not match final {gaussian_stem} SCF")
    return energy, line_number, diff


def parse_native_excerpt(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if document.get("schema") != "case01-native-diagnostic-excerpts/v2":
        raise SourceError("native diagnostic excerpt schema mismatch")
    result = []
    for record in document.get("records", []):
        excerpts = record.get("excerpts", [])
        joined = "\n".join(row.get("text", "") for row in excerpts)
        row = {"job_id": record.get("job_id"), "source_record": record.get("source_record"),
               "excerpts": excerpts}
        if record.get("job_id") == "3886694":
            frequencies = [(int(m.group(1)), float(m.group(2))) for m in re.finditer(
                r"^\s*(\d+):\s+([-+]?\d+\.\d+)\s+cm\*\*-1", joined, re.M)]
            convergence = [line for line in joined.splitlines() if re.search(r"\bYES\s*$", line)]
            temp_matches = [float(m.group(1)) for m in re.finditer(r"THERMOCHEMISTRY AT\s+([-+\d.]+)K", joined)]
            gibbs_matches = [float(m.group(1)) for m in re.finditer(r"Final Gibbs free energy\s+\.\.\.\s+([-+\d.]+)\s+Eh", joined)]
            if len(temp_matches) != 1 or len(gibbs_matches) != 1:
                raise SourceError("native 3886694 excerpt lacks one parseable temperature and final Gibbs value")
            coordinate = record.get("coordinate_source", {})
            coordinate_text = coordinate.get("text", "")
            coordinate_lines = coordinate_text.splitlines()
            try:
                coordinate_natoms = int(coordinate_lines[0].strip())
            except (IndexError, ValueError) as exc:
                raise SourceError("native 3886694 coordinate source has no atom count") from exc
            if len(coordinate_lines) != coordinate_natoms + 2:
                raise SourceError("native 3886694 coordinate source atom count does not match rows")
            row.update({"engine_termination": "normal" if "ORCA TERMINATED NORMALLY" in joined else "not_proven",
                        "frequencies_count": len(frequencies),
                        "negative_frequency_count": sum(value < 0 for _, value in frequencies),
                        "frequency_zero_or_near_zero_count": sum(abs(value) < 1.0 for _, value in frequencies),
                        "geometry_convergence_yes_line_count": len(convergence),
                        "thermochemistry_temperature_K": temp_matches[0],
                        "final_gibbs_hartree": gibbs_matches[0],
                        "coordinate_atom_count": coordinate_natoms,
                        "coordinate_source_line_count": len(coordinate_lines),
                        "final_gibbs_hartree_source_present": "Final Gibbs free energy" in joined,
                        "coordinate_source": coordinate})
        elif record.get("job_id") == "3887010":
            status = record.get("execution_status", {}).get("content", {})
            scheduler = record.get("scheduler_receipt", {}).get("scheduler", {})
            row["execution_source_label"] = record.get("execution_status", {}).get("source_label")
            row["scheduler_source_label"] = record.get("scheduler_receipt", {}).get("source_label")
            sacct = scheduler.get("sacct_receipt", {})
            try:
                sacct_bytes = base64.b64decode(sacct.get("sacct_rows_base64", ""), validate=True)
            except (ValueError, TypeError) as exc:
                raise SourceError("native scheduler sacct rows are invalid base64") from exc
            sacct_rows = sacct_bytes.decode("utf-8", errors="strict").splitlines()
            if len(sacct_rows) != 1:
                raise SourceError("native scheduler receipt must contain one sacct row")
            fields = sacct_rows[0].split("|")
            if len(fields) != 9 or fields[0] != record.get("job_id"):
                raise SourceError("native scheduler sacct row does not bind to the expected job ID/schema")
            if fields[1] != scheduler.get("partition"):
                raise SourceError("native scheduler sacct raw row disagrees with normalized partition")
            for idx, key in ((2, "AllocTRES"), (3, "ReqTRES"), (4, "NodeList"),
                             (5, "Elapsed"), (7, "State"), (8, "ExitCode")):
                if fields[idx] != sacct.get(key):
                    raise SourceError(f"native scheduler sacct raw row disagrees with normalized {key}")
            execution = record.get("execution_status", {}).get("content", {})
            if execution.get("state") != "failed" or scheduler.get("state") != "FAILED":
                raise SourceError("native 3887010 engine and scheduler states are incomplete")
            if (fields[6] != "" or sacct.get("JobIDRaw") != fields[0]
                    or scheduler.get("exit_code") != fields[8]
                    or scheduler.get("elapsed") != fields[5]
                    or scheduler.get("node_list") != fields[4]
                    or status.get("error") != "ORCA exit code 139"):
                raise SourceError("native scheduler/engine normalized fields do not reconcile with the raw receipt")
            row.update({"engine_termination": "failed_PROPINT" if "error termination in PROPINT" in joined else "unresolved",
                        "engine_error_code": status.get("error"),
                        "execution_state": execution.get("state"),
                        "scheduler_state": scheduler.get("state"),
                        "scheduler_exit_code": scheduler.get("exit_code"),
                        "sacct_job_id": fields[0],
                        "mpi_openfabrics_causality": "suspected_only_not_proven"})
        else:
            raise SourceError(f"unexpected native diagnostic job id: {record.get('job_id')!r}")
        result.append(row)
    if [row["job_id"] for row in result] != ["3886694", "3887010"]:
        raise SourceError("native diagnostic jobs are incomplete or reordered")
    return {"source_file": path.name, "records": result}


def build_source_facts(asset_root: Path, refs: dict, qh_gaussian_pairs: dict | None = None) -> dict:
    asset_root = asset_root.resolve()
    pinned = refs.get("asset_hashes")
    if not isinstance(pinned, dict) or len(pinned) != 18:
        raise SourceError("trusted refs must pin exactly 18 Case01 public assets")
    asset_digests = {}
    for rel, expected in pinned.items():
        if not rel.startswith("assets/") or "/" in rel.removeprefix("assets/"):
            raise SourceError(f"invalid trusted asset path: {rel}")
        path = asset_root / rel.removeprefix("assets/")
        if not path.is_file() or path.is_symlink():
            raise SourceError(f"missing/unsafe trusted source asset: {rel}")
        actual = "sha256:" + sha256(path)
        if actual != expected:
            raise SourceError(f"trusted source asset digest mismatch: {rel}")
        asset_digests[rel] = {"bytes": path.stat().st_size, "sha256": actual}
    contexts = json.loads((asset_root / "public-context.json").read_text(encoding="utf-8-sig"))
    if (contexts.get("schema") != "case01-public-context/v2"
            or {row.get("context_id") for row in contexts.get("records", [])} != {"E1-entry-28", "E1-entry-90"}
            or len(contexts.get("records", [])) != 2):
        raise SourceError("public context identity/inventory is not the frozen two-record set")
    redacted = set(contexts.get("redacted_fields", []))
    if not {"Product SMILES", "Exp_Rate_Constant k1 (M-1s-1)",
            "Activation Free Energy (kcalmol-1)"}.issubset(redacted):
        raise SourceError("public context redaction declaration is incomplete")
    logs = [parse_gaussian(asset_root / f"SC-012-D0SC04896H-{stem}.log", f"SC-012-D0SC04896H-{stem}.log") for stem in LOGS]
    thermo = [parse_goodvibes(asset_root / f"SC-012-D0SC04896H-{stem}.dat", f"SC-012-D0SC04896H-{stem}.dat") for stem in THERMO]
    native = parse_native_excerpt(asset_root / "native-diagnostic-excerpts.json")
    by_name = {row["source_file"].removesuffix(".dat").rsplit("-", 1)[-1]: row for row in thermo}
    # Derive the reference species from source stationarity and balanced inventories.
    gaussian_by_stem = {Path(row["source_file"]).stem.rsplit("-", 1)[-1]: row for row in logs}
    thermo_to_log = qh_gaussian_pairs or DEFAULT_QH_GAUSSIAN_PAIRS
    gaussian_by_thermo = {stem: gaussian_by_stem[log] for stem, log in thermo_to_log.items()}
    inventories = {stem: Counter(atom["element"] for atom in row["geometry"]["atoms"])
                   for stem, row in gaussian_by_thermo.items()}
    separated = [stem for stem, row in gaussian_by_thermo.items()
                 if row["formal_negative_mode_count"] == 0
                 and all(derive_stationary_evidence(row)["observed"][key] for key in
                         ("prior_all_four_criteria_pass", "prior_optimization_completed",
                          "prior_stationary_point_observed", "prior_normal_termination"))]
    pairs = []
    for stem, saddle in gaussian_by_thermo.items():
        if saddle["formal_negative_mode_count"] != 1: continue
        matches = [(a, b) for a, b in combinations(separated, 2)
                   if inventories[a] + inventories[b] == inventories[stem]
                   and gaussian_by_thermo[a]["charge"] + gaussian_by_thermo[b]["charge"] == saddle["charge"]]
        if len(matches) != 1:
            raise SourceError(f"{stem}: cannot uniquely derive separated optimized reference species")
        pairs.append((stem, *matches[0]))
    if len(pairs) != 3:
        raise SourceError("frozen source inventory must support three one-negative-mode complex comparisons")
    differences = []
    for ts, reactant, intermediate in pairs:
        a = by_name[ts]
        b = by_name[reactant]
        c = by_name[intermediate] if intermediate is not None else None
        conventions = ("temperature_K", "concentration_mol_L", "reported_energy_unit", "qs_treatment",
                       "frequency_cutoff_cm-1", "standard_state")
        same = all(a[key] == b[key] and (c is None or a[key] == c[key]) for key in conventions)
        same = same and a["scale_factor"] == b["scale_factor"] and (c is None or a["scale_factor"] == c["scale_factor"])
        terms = [(a, 1), (b, -1)] + ([(c, -1)] if c is not None else [])
        value = sum(row["qh_G_T_hartree"] * coefficient for row, coefficient in terms) * HARTREE_TO_KCAL if same else None
        differences.append({"source_ids": [ts, reactant] + ([intermediate] if intermediate else []),
                            "coefficients": [1, -1] + ([-1] if intermediate else []),
                            "temperature_K": a["temperature_K"] if same else None,
                            "standard_state": a["standard_state"] if same else None,
                            "candidate_delta_g_kcal_mol": value,
                            "reaction_barrier_kcal_mol": None,
                            "reaction_barrier_status": "unresolved_no_proven_path_connection_and_join"})
    gaussian_by_stem = {Path(row["source_file"]).stem.rsplit("-", 1)[-1]: row for row in logs}
    thermo_to_log = qh_gaussian_pairs or DEFAULT_QH_GAUSSIAN_PAIRS
    source_joins = []
    for dat_stem, log_stem in thermo_to_log.items():
        therm = by_name[dat_stem]
        gaussian = gaussian_by_stem[log_stem]
        log_path = asset_root / f"SC-012-D0SC04896H-{log_stem}.log"
        log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        scf_matches = [(i + 1, float(m.group(1).replace("D", "E"))) for i, line in enumerate(log_lines)
                       if (m := re.search(r"SCF Done:\s+E\(R?\w+\)\s*=\s*([-+\d.]+)", line))]
        zpe_matches = [(i + 1, float(m.group(1))) for i, line in enumerate(log_lines)
                       if (m := re.search(r"Zero-point correction=\s*([-+\d.]+)", line))]
        term_matches = [(i + 1, m.group(1).strip()) for i, line in enumerate(log_lines)
                        if "Normal termination of Gaussian" in line
                        and (m := re.search(r"Normal termination of Gaussian\s+\w+\s+at\s+(.+)$", line))]
        if not scf_matches or not zpe_matches or not term_matches:
            raise SourceError(f"{log_stem}: final SCF/ZPE/normal termination join data missing")
        scf_line, scf_energy = scf_matches[-1]
        zpe_line, zpe = zpe_matches[-1]
        term_line, timestamp = term_matches[-1]
        gv_lines = therm["source_file"]
        gv_text = (asset_root / gv_lines).read_text(encoding="utf-8", errors="replace").splitlines()
        gv_time = [m.group(1) for line in gv_text
                   if (m := re.search(r"GoodVibes\s+v\S+\s+\d{4}/\d{2}/\d{2}\s+(\d{2}:\d{2}:\d{2})", line))]
        if len(gv_time) != 1:
            raise SourceError(f"{dat_stem}: GoodVibes timestamp is missing or ambiguous")
        e_value = therm["reported_values_hartree"]["E_hartree"]
        qh_g = therm["qh_G_T_hartree"]
        qh_h = therm["reported_values_hartree"]["H_hartree"]
        tqhs = therm["reported_values_hartree"]["T_qh_S_hartree"]
        verify_qh_gaussian_energy_join(therm, log_path, log_stem)
        # GoodVibes prints each component to six decimals; three rounded
        # operands can differ by up to roughly 1.5 microhartree.
        if abs((qh_h - tqhs) - qh_g) > 2e-6:
            raise SourceError(f"{dat_stem} qh G(T) does not reconcile with H - T.qhS")
        source_joins.append({"goodvibes_stem": dat_stem, "goodvibes_sha256": therm["source_sha256"],
            "goodvibes_timestamp": gv_time[0], "gaussian_stem": log_stem,
            "gaussian_sha256": gaussian["source_sha256"], "gaussian_normal_termination_timestamp": timestamp,
            "gaussian_normal_termination_line_1based": term_line,
            "final_scf_E_hartree": scf_energy, "final_scf_line_1based": scf_line,
            "gaussian_zpe_hartree": zpe, "gaussian_zpe_line_1based": zpe_line,
            "goodvibes_E_hartree": e_value, "goodvibes_ZPE_hartree": therm["reported_values_hartree"]["ZPE_hartree"],
            "goodvibes_qh_G_T_hartree": qh_g, "goodvibes_H_minus_T_qhS_hartree": qh_h - tqhs,
            "energy_abs_diff_hartree": abs(e_value - scf_energy), "qh_reconciliation_abs_diff_hartree": abs((qh_h - tqhs) - qh_g),
            "scale_factor": therm["scale_factor"], "temperature_K": therm["temperature_K"],
            "concentration_mol_L": therm["concentration_mol_L"], "standard_state": therm["standard_state"],
            "qs_treatment": therm["qs_treatment"],
            "frequency_cutoff_cm-1": therm["frequency_cutoff_cm-1"]})
    return {"schema": "case01-source-facts/v1", "case_id": CASE_ID,
            "source_asset_count": len(asset_digests), "source_asset_hashes": asset_digests,
            "gaussian": logs, "goodvibes": thermo, "candidate_differences": differences,
            "source_joins": source_joins,
            "native": native,
            "limits": ["Source frequency rows are reported as Gaussian normal-coordinate components; the source excerpt does not state Cartesian displacement units.",
                       "Formal reaction barriers remain unresolved without independently supported context identity, optimized geometry, reaction-directed mode, atom mapping, and path connection.",
                       "Native records report one completed minimum and one PROPINT failure; scheduler state and engine state remain separate."]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True, help="trusted read-only Case01 assets directory")
    parser.add_argument("--refs", type=Path, required=True, help="grader-only tests/refs.json")
    args = parser.parse_args(argv)
    try:
        refs = json.loads(args.refs.read_text(encoding="utf-8-sig"))
        facts = build_source_facts(args.assets, refs)
    except (OSError, UnicodeError, json.JSONDecodeError, SourceError) as exc:
        print(json.dumps({"status": "INFRA_ERROR", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(facts, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
