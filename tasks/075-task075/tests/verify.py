#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Asp50/Asp397 Dyad Proton-Exchange Barriers.
"""Scientific verifier for native ioChem/CML calculation artifacts.

The verifier reads only the collected candidate directory and the pinned public
task description. Author archive files live outside this package and are never
needed to grade a candidate.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CASE = "case-06-proton-exchange-qm"
REFS_SHA256 = "8c33bd7f15e9fb8b73f361d35c5a5ca0becf040e45d8518e2b17f1d113b5f9a7"
HARTREE_TO_KCAL = 627.509474
NS = {"c": "http://www.xml-cml.org/schema"}
PUBLIC_INPUT_SHA256 = "7bf078fa6419f1e59b632019a8990349a986e16d166dafec6c81c66e3db2b976"
TOLERANCES = {
    "endpoint_energy_hartree_abs": 2e-5,
    "barrier_kcal_mol_abs": 0.02,
    "facile_threshold_kcal_mol": 3.0,
    "facile_threshold_abs": 1e-9,
}


class CandidateFail(Exception):
    pass


class EnvironmentInvalid(Exception):
    pass


class ReviewRequired(Exception):
    """The evidence is complete, but the model/method route is not calibrated."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_refs() -> dict:
    path = Path(__file__).with_name("refs.json")
    if path.is_symlink() or not path.is_file() or sha256(path) != REFS_SHA256:
        raise EnvironmentInvalid("case-06 refs.json is missing, redirected, or changed")
    try:
        refs = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnvironmentInvalid(f"case-06 refs.json cannot be parsed: {exc}") from exc
    if (not isinstance(refs, dict) or refs.get("schema_version") != "case06-verifier-reference/v1"
            or not isinstance(refs.get("public_input_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", refs["public_input_sha256"])
            or isinstance(refs.get("hartree_to_kcal"), bool)
            or not isinstance(refs.get("hartree_to_kcal"), (int, float))
            or not math.isfinite(refs["hartree_to_kcal"]) or refs["hartree_to_kcal"] <= 0
            or not isinstance(refs.get("tolerances"), dict)):
        raise EnvironmentInvalid("case-06 refs.json has an unsupported or malformed schema")
    tolerances = refs["tolerances"]
    if set(tolerances) != set(TOLERANCES) or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
            for value in tolerances.values()):
        raise EnvironmentInvalid("case-06 refs.json numeric tolerances are malformed")
    return refs


def number(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateFail(f"{label} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise CandidateFail(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise CandidateFail(f"{label} must be a finite number")
    return result


def native_text_number(value: str, label: str) -> float:
    """Parse a finite number from native XML/XYZ text, never from JSON fields."""
    if not isinstance(value, str):
        raise CandidateFail(f"{label} must be finite native numeric text")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise CandidateFail(f"{label} must be finite native numeric text") from exc
    if not math.isfinite(result):
        raise CandidateFail(f"{label} must be finite native numeric text")
    return result


def cml_data(path: Path, *, require_state: bool = True) -> dict:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise CandidateFail(f"cannot parse native CML output {path.name}: {exc}") from exc

    def values(ref: str) -> list[ET.Element]:
        return [e for e in root.iter() if e.attrib.get("dictRef") == ref]

    scalar = {}
    for ref in ("cc:program", "cc:method", "cc:basis", "g:charge", "g:mult", "g:solvent", "g:eps",
                "g:gradientmax", "g:stationarytype"):
        found = values(ref)
        if found:
            scalar[ref] = " ".join(" ".join("".join(e.itertext()).split()) for e in found if "".join(e.itertext()).strip())
    if require_state and ("g:charge" not in scalar or "g:mult" not in scalar):
        raise CandidateFail(f"{path.name} lacks charge/multiplicity in native metadata")
    energy_nodes = [e for e in values("cc:hfenergy") if "".join(e.itertext()).strip()]
    if not energy_nodes:
        raise CandidateFail(f"{path.name} lacks a native electronic energy")
    energy = native_text_number("".join(energy_nodes[-1].itertext()).strip(), f"{path.name} electronic energy")
    energy_unit = energy_nodes[-1].attrib.get("units", "").lower()
    if "hartree" not in energy_unit:
        raise CandidateFail(f"{path.name} native electronic energy lacks Hartree units")

    atoms: list[dict] = []
    for atom_array in root.findall(".//c:atomArray", NS):
        found = atom_array.findall("c:atom", NS)
        if found:
            atoms = [{
                "element": e.attrib.get("elementType", "").capitalize(),
                "xyz": [native_text_number(e.attrib.get(k), f"{path.name} atom coordinate") for k in ("x3", "y3", "z3")],
            } for e in found]
    if not atoms:
        raise CandidateFail(f"{path.name} lacks optimized atom coordinates")

    freq_arrays = [e for e in values("cc:frequency") if e.text]
    disp_arrays = [e for e in values("cc:displacement") if e.text]
    if len(freq_arrays) != 1:
        raise CandidateFail(f"{path.name} lacks native vibrational frequencies")
    if len(disp_arrays) != 1:
        raise CandidateFail(f"{path.name} lacks one complete native displacement array")
    frequencies = [native_text_number(x, f"{path.name} frequency") for x in freq_arrays[-1].text.split()]
    displacements = [native_text_number(x, f"{path.name} displacement") for x in disp_arrays[-1].text.split()]

    messages = [" ".join("".join(e.itertext()).split()) for e in values("g:optimization")]
    joined = " ".join(messages).lower()
    if "optimization completed" not in joined or "stationary point found" not in joined:
        raise CandidateFail(f"{path.name} does not document a completed optimization and stationary point")
    gradient_max = None
    if "g:gradientmax" in scalar:
        gradient_max = native_text_number(scalar["g:gradientmax"].split()[-1], f"{path.name} gradient maximum")
    stationary_type = scalar.get("g:stationarytype", "").lower().split()[-1] if scalar.get("g:stationarytype") else None
    model_text = " ".join((e.text or "").lower() for e in root.iter())
    cpcm = "cpcm" in model_text or "c-pcm" in model_text
    try:
        dielectric = float(scalar.get("g:eps", "nan").split()[-1])
    except (ValueError, IndexError):
        dielectric = math.nan
    return {
        "energy_hartree": energy,
        "energy_unit": energy_unit,
        "frequencies_cm-1": frequencies,
        "displacements": displacements,
        "atoms": atoms,
        "charge": int(float(scalar["g:charge"].split()[-1])) if "g:charge" in scalar else None,
        "multiplicity": int(float(scalar["g:mult"].split()[-1])) if "g:mult" in scalar else None,
        "method": scalar.get("cc:method", "").upper(),
        "basis": scalar.get("cc:basis", ""),
        "program": scalar.get("cc:program", ""),
        "solvent": scalar.get("g:solvent", ""),
        "dielectric": dielectric,
        "cpcm": cpcm,
        "converged": True,
        "max_abs_gradient_hartree_per_bohr": gradient_max,
        "stationary_type": stationary_type,
    }


def xyz_atoms(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        count = int(lines[0].strip())
        rows = lines[2:2 + count]
        atoms = []
        for row in rows:
            fields = row.split()
            if len(fields) < 4:
                raise ValueError("short XYZ row")
            atoms.append({"element": fields[0].capitalize(), "xyz": [native_text_number(x, path.name) for x in fields[1:4]]})
        if len(atoms) != count:
            raise ValueError("atom count mismatch")
        return atoms
    except (OSError, ValueError, IndexError) as exc:
        raise CandidateFail(f"invalid XYZ geometry {path.name}: {exc}") from exc


def distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def transfer_projection(data: dict, transfer_atoms: dict, mode_index: int) -> float:
    atoms, freq, disp = data["atoms"], data["frequencies_cm-1"], data["displacements"]
    try:
        raw = [transfer_atoms[k] for k in ("oxygen_a", "proton", "oxygen_b")]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in raw):
            raise ValueError("atom indices must be JSON integers")
        oi, hi, oj = (value - 1 for value in raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise CandidateFail("transfer_atoms must name 1-based oxygen_a, proton, and oxygen_b indices") from exc
    if min(oi, hi, oj) < 0 or max(oi, hi, oj) >= len(atoms) or len({oi, hi, oj}) != 3:
        raise CandidateFail("transfer_atoms indices are invalid for the native geometry")
    if atoms[oi]["element"] != "O" or atoms[oj]["element"] != "O" or atoms[hi]["element"] != "H":
        raise CandidateFail("transfer_atoms must identify two oxygens and one hydrogen in the native geometry")
    if not disp or len(disp) != len(freq) * len(atoms) * 3 or not (0 <= mode_index < len(freq)):
        raise CandidateFail("native displacement array is absent or inconsistent with frequency/atom counts")
    mode = disp[mode_index * len(atoms) * 3:(mode_index + 1) * len(atoms) * 3]
    mode_norm = math.sqrt(sum(x * x for x in mode))
    if mode_norm <= 1e-14:
        raise CandidateFail("selected imaginary-mode displacement is degenerate")
    mode = [x / mode_norm for x in mode]
    xyz = [a["xyz"] for a in atoms]

    def directional_change(i: int) -> float:
        vec = [xyz[hi][k] - xyz[i][k] for k in range(3)]
        r = math.sqrt(sum(v * v for v in vec))
        if r < 1e-8:
            raise CandidateFail("degenerate proton-transfer geometry")
        unit = [v / r for v in vec]
        return sum(unit[k] * (mode[3 * hi + k] - mode[3 * i + k]) for k in range(3))

    # Cosine overlap of the Cartesian normal displacement with grad(r(Oa-H)-r(Ob-H));
    # this is scale-independent, unlike the raw directional derivative.
    gradient = [0.0] * (len(atoms) * 3)
    for atom_index, sign in ((oi, 1.0), (oj, -1.0)):
        delta = [xyz[hi][k] - xyz[atom_index][k] for k in range(3)]
        norm = math.sqrt(sum(x * x for x in delta))
        if norm < 1e-8:
            raise CandidateFail("degenerate proton-transfer geometry")
        unit = [x / norm for x in delta]
        for k in range(3):
            gradient[3 * atom_index + k] -= sign * unit[k]
            gradient[3 * hi + k] += sign * unit[k]
    gradient_norm = math.sqrt(sum(x * x for x in gradient))
    if gradient_norm <= 1e-14:
        raise CandidateFail("degenerate proton-transfer coordinate")
    return sum(a * b for a, b in zip(mode, gradient)) / gradient_norm


def native_log_sections(text: str) -> dict[tuple[str, str], str]:
    begin = re.compile(r"^CASE06_ENDPOINT_BEGIN model_id=([^\s]+) role=(minimum_1|minimum_2|transition_state)\s*$")
    end = re.compile(r"^CASE06_ENDPOINT_END model_id=([^\s]+) role=(minimum_1|minimum_2|transition_state) energy_hartree=([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*$")
    sections: dict[tuple[str, str], str] = {}
    active = None
    chunks: list[str] = []
    for line in text.splitlines():
        start = begin.match(line.strip())
        finish = end.match(line.strip())
        if start:
            if active is not None:
                raise CandidateFail("native run log has nested or unterminated endpoint sections")
            active = (start.group(1), start.group(2))
            if active in sections:
                raise CandidateFail("native run log repeats an endpoint section")
            chunks = []
            continue
        if finish:
            key = (finish.group(1), finish.group(2))
            if active != key:
                raise CandidateFail("native run log endpoint markers are mismatched")
            chunks.append(line)
            sections[key] = "\n".join(chunks)
            active = None
            continue
        if active is not None:
            chunks.append(line)
    if active is not None:
        raise CandidateFail("native run log has an unterminated endpoint section")
    return sections


def check_endpoint_log(model_id: str, role: str, endpoint: dict, sections: dict, energy: float) -> None:
    log_id = endpoint.get("native_log_id")
    if log_id != f"{model_id}:{role}":
        raise CandidateFail(f"{model_id} {role} must identify its role-bound native log section")
    section = sections.get((model_id, role))
    if section is None:
        raise CandidateFail(f"{model_id} {role} has no matching native log section")
    end_match = re.search(r"^CASE06_ENDPOINT_END model_id=[^\s]+ role=[^\s]+ energy_hartree=([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)$",
                          section, flags=re.MULTILINE)
    if not end_match or abs(float(end_match.group(1)) - energy) > TOLERANCES["endpoint_energy_hartree_abs"]:
        raise CandidateFail(f"{model_id} {role} native endpoint record disagrees with CML energy")
    energy_pattern = re.compile(
        r"(?:converged\s+SCF\s+energy\s*=|SCF\s+Done:\s*E\([^)]*\)\s*=|"
        r"FINAL\s+SINGLE\s+POINT\s+ENERGY\s+|total\s+energy\s*[:=])"
        r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)", re.IGNORECASE)
    energies = [float(x) for x in energy_pattern.findall(section)]
    if not any(abs(value - energy) <= 2e-5 for value in energies):
        raise CandidateFail(f"{model_id} {role} native log section lacks its converged CML energy")
    low = section.lower()
    converged = any(token in low for token in (
        "converged! =d", "optimization completed", "stationary point found",
        "the optimization has converged", "optimization converged",
    ))
    if not converged:
        raise CandidateFail(f"{model_id} {role} native log section lacks optimizer convergence evidence")


def validate_carboxylate_connectivity(atoms: list[dict], formula: dict, bridge: bool,
                                      transfer: dict) -> None:
    coords = [atom["xyz"] for atom in atoms]
    oi, hi, oj = (transfer[k] - 1 for k in ("oxygen_a", "proton", "oxygen_b"))
    dist = lambda i, j: distance(coords[i], coords[j])
    acid_carbons = []
    for oxygen in (oi, oj):
        neighbors = [i for i, atom in enumerate(atoms) if atom["element"] == "C" and dist(i, oxygen) < 1.75]
        if len(neighbors) != 1:
            raise CandidateFail("each transfer oxygen must be covalently attached to one carboxyl carbon")
        acid_carbons.append(neighbors[0])
    if acid_carbons[0] == acid_carbons[1]:
        raise CandidateFail("transfer oxygens must belong to two distinct carboxyl groups")
    for carbon in acid_carbons:
        oxygens = [i for i, atom in enumerate(atoms) if atom["element"] == "O" and dist(i, carbon) < 1.75]
        if len(oxygens) != 2:
            raise CandidateFail("each transferred proton endpoint must be a two-oxygen carboxylate group")
    if formula.get("C") == 4:
        for carbon in acid_carbons:
            methyls = [i for i, atom in enumerate(atoms) if atom["element"] == "C" and i != carbon and dist(i, carbon) < 1.85]
            if len(methyls) != 1:
                raise CandidateFail("acetate carboxyl carbon must be connected to one methyl carbon")
            methyl_h = [i for i, atom in enumerate(atoms) if atom["element"] == "H" and dist(i, methyls[0]) < 1.25]
            if len(methyl_h) != 3:
                raise CandidateFail("each acetate methyl carbon must carry three hydrogens")
    elif formula.get("C") == 2:
        for carbon in acid_carbons:
            formyl_h = [i for i, atom in enumerate(atoms) if atom["element"] == "H" and i != hi and dist(i, carbon) < 1.25]
            if len(formyl_h) != 1:
                raise CandidateFail("each formate carbon must carry one hydrogen")
    if bridge:
        carbon_bonded_oxygens = {i for i, atom in enumerate(atoms) if atom["element"] == "O"
                                 and any(other["element"] == "C" and dist(i, j) < 1.75
                                         for j, other in enumerate(atoms))}
        water_oxygens = [i for i, atom in enumerate(atoms) if atom["element"] == "O" and i not in carbon_bonded_oxygens]
        if len(water_oxygens) != 1:
            raise CandidateFail("bridge-water model must contain exactly one non-carboxylate oxygen")
        water = water_oxygens[0]
        water_h = [i for i, atom in enumerate(atoms) if atom["element"] == "H" and dist(i, water) < 1.25]
        if len(water_h) != 2 or max(dist(water, oi), dist(water, oj)) > 4.25:
            raise CandidateFail("explicit water must be an intact molecule positioned between the two carboxylates")


def report_assessment(report_text: str) -> dict:
    match = re.search(r"<!-- CASE06_SCIENTIFIC_ASSESSMENT_BEGIN\s*(\{.*?\})\s*CASE06_SCIENTIFIC_ASSESSMENT_END -->",
                      report_text, flags=re.DOTALL)
    if not match:
        raise CandidateFail("report.md lacks its structured scientific-assessment block")
    try:
        obj = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise CandidateFail(f"report.md scientific-assessment block is malformed: {exc}") from exc
    if not isinstance(obj, dict) or obj.get("schema") != "case06-scientific-assessment/v1" or not isinstance(obj.get("models"), list):
        raise CandidateFail("report.md scientific-assessment block has the wrong schema")
    return obj


def is_calibrated_route(species: str, row: dict, dielectric: float) -> bool:
    return (species == "acetate" and str(row.get("method", "")).strip().upper() == "B3LYP"
            and str(row.get("basis", "")).replace(" ", "").lower() == "6-31g(d)"
            and 3.95 <= dielectric <= 4.05)


def scientific_verdict(maximum: float, threshold: float | None = None) -> str:
    if threshold is None:
        threshold = TOLERANCES["facile_threshold_kcal_mol"]
    return "facile" if maximum <= threshold else "not_facile"


def parse_candidate(root: Path) -> tuple[dict, list[str]]:
    try:
        return _parse_candidate(root)
    except CandidateFail:
        raise
    except EnvironmentInvalid:
        raise
    except (KeyError, TypeError, ValueError, IndexError, OverflowError, OSError, UnicodeError, AttributeError) as exc:
        raise CandidateFail(f"malformed candidate evidence: {type(exc).__name__}: {exc}") from exc


def _parse_candidate(root: Path) -> tuple[dict, list[str]]:
    json_path = root / "final/barriers.json"
    if not json_path.is_file():
        raise CandidateFail("missing final/barriers.json")
    try:
        obj = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateFail(f"final/barriers.json is malformed: {exc}") from exc
    if not isinstance(obj, dict) or obj.get("schema") != "case06-barriers/v1" or not isinstance(obj.get("models"), list):
        raise CandidateFail("barriers.json must use schema case06-barriers/v1 and contain a models array")
    report = root / "final/report.md"
    if not report.is_file() or not report.read_text(encoding="utf-8").strip():
        raise CandidateFail("missing or empty final/report.md")
    report_text = report.read_text(encoding="utf-8")
    native_log = root / "final/native-run.log"
    log_text = native_log.read_text(encoding="utf-8", errors="replace") if native_log.is_file() else ""
    if "PRIVATE SYNTHETIC CALIBRATION FIXTURE" in log_text:
        raise CandidateFail("synthetic calibration logs are not native calculation evidence")
    log_sections = native_log_sections(log_text) if log_text.strip() else {}
    models = obj["models"]
    if len(models) < 2:
        raise CandidateFail("submit at least one no-water model and one bridge-water model")

    seen_classes = set()
    seen_ids = set()
    results = []
    uncalibrated_routes = []
    soft_negative_minima = []
    expected_report_assessments = []
    for row in models:
        if not isinstance(row, dict):
            raise CandidateFail("each models entry must be an object")
        model_id = row.get("model_id")
        if not isinstance(model_id, str) or not model_id.strip() or model_id in seen_ids:
            raise CandidateFail("model_id must be a unique non-empty string")
        seen_ids.add(model_id)
        bridge = row.get("bridge_water")
        if not isinstance(bridge, bool):
            raise CandidateFail(f"{model_id}: bridge_water must be boolean")
        seen_classes.add(bridge)
        if row.get("energy_unit") != "hartree" or row.get("barrier_unit") != "kcal/mol":
            raise CandidateFail(f"{model_id}: energies must be Hartree and barriers kcal/mol")
        if row.get("barrier_basis") not in (None, "electronic_energy"):
            raise CandidateFail(f"{model_id}: barrier_basis must identify electronic-energy differences")
        if row.get("charge") != -1 or row.get("multiplicity") != 1:
            raise CandidateFail(f"{model_id}: model must be charge -1, singlet")
        if not isinstance(row.get("method"), str) or not row["method"].strip() or not isinstance(row.get("basis"), str) or not row["basis"].strip():
            raise CandidateFail(f"{model_id}: report the electronic method and basis")
        solvent = row.get("solvent")
        if not isinstance(solvent, dict) or str(solvent.get("model", "")).lower() not in {"cpcm", "cpcm-like", "pcm", "implicit"}:
            raise CandidateFail(f"{model_id}: report a CPCM-like implicit solvent model")
        dielectric = number(solvent.get("dielectric"), f"{model_id} dielectric")
        if not 3.5 <= dielectric <= 4.5:
            raise CandidateFail(f"{model_id}: low-dielectric solvent must be near epsilon=4")

        minima = row.get("minima")
        ts = row.get("transition_state")
        if not isinstance(minima, list) or len(minima) != 2 or not isinstance(ts, dict):
            raise CandidateFail(f"{model_id}: provide exactly two minima and one transition state")
        transfer = row.get("transfer_atoms")
        if not isinstance(transfer, dict):
            raise CandidateFail(f"{model_id}: transfer_atoms must be an object")
        raw_transfer = [transfer.get(k) for k in ("oxygen_a", "proton", "oxygen_b")]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in raw_transfer):
            raise CandidateFail(f"{model_id}: transfer_atoms must use JSON integer atom indices")
        parsed = []
        localized_sides = []
        endpoint_rows = [("minimum_1", minima[0]), ("minimum_2", minima[1]), ("transition_state", ts)]
        for endpoint_role, endpoint in endpoint_rows:
            endpoint_name = "transition_state" if endpoint_role == "transition_state" else "minimum"
            if not isinstance(endpoint, dict):
                raise CandidateFail(f"{model_id}: {endpoint_name} must be an object")
            # The cm-1 key is unambiguous, so accept its underscore spelling too; the array is
            # still compared value-by-value against the native output below.
            if "frequencies_cm-1" not in endpoint and "frequencies_cm_minus_1" in endpoint:
                endpoint = {**endpoint, "frequencies_cm-1": endpoint["frequencies_cm_minus_1"]}
            for key in ("energy_hartree", "frequencies_cm-1", "native_output", "geometry_xyz"):
                if key not in endpoint:
                    raise CandidateFail(f"{model_id}: {endpoint_name} missing {key}")
            reported_energy = number(endpoint["energy_hartree"], f"{model_id} {endpoint_name} energy")
            frequencies = endpoint["frequencies_cm-1"]
            if not isinstance(frequencies, list) or not frequencies:
                raise CandidateFail(f"{model_id}: {endpoint_name} must report its vibrational frequencies")
            frequencies = [number(x, f"{model_id} {endpoint_name} frequency") for x in frequencies]
            if any(not isinstance(endpoint[key], str) or not endpoint[key].strip()
                   for key in ("native_output", "geometry_xyz")):
                raise CandidateFail(f"{model_id}: endpoint artifact paths must be non-empty strings")
            native_input = root / endpoint["native_output"]
            geom_input = root / endpoint["geometry_xyz"]
            if native_input.is_symlink() or geom_input.is_symlink():
                raise CandidateFail(f"{model_id}: symlinked artifacts are not accepted")
            native = native_input.resolve()
            geom = geom_input.resolve()
            try:
                native.relative_to(root.resolve()); geom.relative_to(root.resolve())
            except ValueError as exc:
                raise CandidateFail(f"{model_id}: artifact paths must stay under the submitted directory") from exc
            if native.suffix.lower() not in {".cml", ".xml"} or not native.is_file() or not geom.is_file():
                raise CandidateFail(f"{model_id}: native_output must be a raw CML/XML file and geometry_xyz must exist")
            data = cml_data(native)
            # The raw native CML/XML endpoint is required evidence and carries
            # its own energy, optimization/stationarity metadata, frequencies,
            # modes, and geometry. A native optimizer log is optional extra
            # corroboration because common archive exports do not retain it.
            if endpoint.get("native_log_id") is not None or log_sections:
                check_endpoint_log(model_id, endpoint_role, endpoint, log_sections, data["energy_hartree"])
            expected_modes = 3 * len(data["atoms"]) - 6
            if len(data["frequencies_cm-1"]) != expected_modes:
                raise CandidateFail(f"{model_id} {endpoint_role}: expected all 3N-6={expected_modes} frequencies")
            if len(data["displacements"]) != expected_modes * len(data["atoms"]) * 3:
                raise CandidateFail(f"{model_id} {endpoint_role}: displacement array is incomplete")
            oi, hi, oj = (value - 1 for value in raw_transfer)
            if min(oi, hi, oj) < 0 or max(oi, hi, oj) >= len(data["atoms"]):
                raise CandidateFail(f"{model_id}: transfer atom index is out of bounds")
            if ([data["atoms"][oi]["element"], data["atoms"][oj]["element"], data["atoms"][hi]["element"]]
                    != ["O", "O", "H"]):
                raise CandidateFail(f"{model_id}: transfer indices must refer to O-H-O atoms at every endpoint")
            if not math.isclose(reported_energy, data["energy_hartree"], abs_tol=TOLERANCES["endpoint_energy_hartree_abs"], rel_tol=0):
                raise CandidateFail(f"{model_id}: reported energy does not match {endpoint_name} native output")
            expected_role = "transition_state" if endpoint_name == "transition_state" else "minimum"
            if data["stationary_type"] is not None and data["stationary_type"] != expected_role:
                raise CandidateFail(f"{model_id}: {endpoint_name} CML stationary-point type is inconsistent")
            grad_limit = 5e-4 if endpoint_name == "transition_state" else 4e-4
            if data["max_abs_gradient_hartree_per_bohr"] is not None and data["max_abs_gradient_hartree_per_bohr"] > grad_limit:
                raise CandidateFail(f"{model_id}: {endpoint_name} gradient does not satisfy its stationarity threshold")
            if len(frequencies) != len(data["frequencies_cm-1"]) or any(abs(x-y) > 1.0 for x, y in zip(frequencies, data["frequencies_cm-1"])):
                raise CandidateFail(f"{model_id}: reported frequencies do not match {endpoint_name} native output")
            if data["charge"] != -1 or data["multiplicity"] != 1:
                raise CandidateFail(f"{model_id}: native output has wrong charge or multiplicity")
            native_method = data["method"].lower().replace(" ", "").replace("r", "", 1) if data["method"] else ""
            reported_method = row["method"].lower().replace(" ", "")
            if not native_method or reported_method not in native_method:
                raise CandidateFail(f"{model_id}: reported method does not match native output")
            native_basis = data["basis"].lower().replace(" ", "")
            reported_basis = row["basis"].lower().replace(" ", "")
            if not native_basis or reported_basis not in native_basis:
                raise CandidateFail(f"{model_id}: reported basis does not match native output")
            if not data["cpcm"] or not math.isfinite(data["dielectric"]) or abs(data["dielectric"] - dielectric) > .05:
                raise CandidateFail(f"{model_id}: native output does not support reported CPCM dielectric")
            if not data["program"].strip():
                raise CandidateFail(f"{model_id}: native CML does not identify its quantum-chemistry program")
            if len(data["atoms"]) not in {9, 12, 15, 18}:
                raise CandidateFail(f"{model_id}: expected a minimal 9/12 atom formate or 15/18 atom acetate model")
            formula = {}
            for atom in data["atoms"]:
                formula[atom["element"]] = formula.get(atom["element"], 0) + 1
            expected = ({"C": 4, "H": 9, "O": 5} if bridge else None)
            accepted = ({"C": 4, "H": 9, "O": 5}, {"C": 2, "H": 5, "O": 5}) if bridge else ({"C": 4, "H": 7, "O": 4}, {"C": 2, "H": 3, "O": 4})
            if formula not in accepted:
                raise CandidateFail(f"{model_id}: native composition {formula} is not an acetate/formate proton-shared model for bridge_water={bridge}")
            validate_carboxylate_connectivity(data["atoms"], formula, bridge, transfer)
            xyz = xyz_atoms(geom)
            if [a["element"] for a in xyz] != [a["element"] for a in data["atoms"]]:
                raise CandidateFail(f"{model_id}: XYZ atom sequence does not match native output")
            if any(distance(a["xyz"], b["xyz"]) > .025 for a, b in zip(xyz, data["atoms"])):
                raise CandidateFail(f"{model_id}: XYZ coordinates do not match native optimized geometry")
            negative = [i for i, f in enumerate(data["frequencies_cm-1"]) if f < -20.0]
            if endpoint_name == "transition_state":
                if len(negative) != 1:
                    raise CandidateFail(f"{model_id}: transition state must have exactly one significant imaginary mode")
                projection = transfer_projection(data, transfer, negative[0])
                if abs(projection) < .20:
                    raise CandidateFail(f"{model_id}: imaginary mode is not projected onto the nominated proton-transfer coordinate")
                atoms = data["atoms"]
                oi, hi, oj = (transfer[k]-1 for k in ("oxygen_a", "proton", "oxygen_b"))
                d1, d2 = distance(atoms[oi]["xyz"], atoms[hi]["xyz"]), distance(atoms[oj]["xyz"], atoms[hi]["xyz"])
                oo = distance(atoms[oi]["xyz"], atoms[oj]["xyz"])
                if max(d1, d2) > 1.55 or min(d1, d2) < .65 or oo > 2.8:
                    raise CandidateFail(f"{model_id}: nominated TS proton is not shared between the two carboxylate oxygens")
            else:
                if negative:
                    raise CandidateFail(f"{model_id}: minimum contains a significant imaginary frequency")
                soft_negative = [f for f in data["frequencies_cm-1"] if -20.0 <= f < 0.0]
                if soft_negative:
                    soft_negative_minima.append(f"{model_id}:{endpoint_role}={soft_negative}")
                oi, hi, oj = (transfer[k]-1 for k in ("oxygen_a", "proton", "oxygen_b"))
                d1 = distance(data["atoms"][oi]["xyz"], data["atoms"][hi]["xyz"])
                d2 = distance(data["atoms"][oj]["xyz"], data["atoms"][hi]["xyz"])
                if min(d1, d2) > 1.25 or abs(d1-d2) < .15 or max(d1, d2) > 1.8:
                    raise CandidateFail(f"{model_id}: minimum does not localize the shared proton on one of the two carboxylates")
                localized_sides.append(0 if d1 < d2 else 1)
            parsed.append(data)
        if len({x["method"].lower().replace(" ", "") for x in parsed}) != 1:
            raise CandidateFail(f"{model_id}: endpoint native outputs use inconsistent electronic methods")
        if len({x["basis"].lower().replace(" ", "") for x in parsed}) != 1:
            raise CandidateFail(f"{model_id}: endpoint native outputs use inconsistent basis sets")
        if len({x["program"].lower().replace(" ", "") for x in parsed}) != 1:
            raise CandidateFail(f"{model_id}: endpoint native outputs use inconsistent quantum-chemistry programs")
        if len(parsed) < 3:
            raise CandidateFail(f"{model_id}: incomplete endpoint evidence")
        if localized_sides[0] == localized_sides[1]:
            raise CandidateFail(f"{model_id}: the two minima must localize the shared proton on opposite carboxylates")
        e0, e1, ets = parsed[0]["energy_hartree"], parsed[1]["energy_hartree"], parsed[2]["energy_hartree"]
        barriers = row.get("barriers_kcal_mol")
        if not isinstance(barriers, dict):
            raise CandidateFail(f"{model_id}: barriers_kcal_mol is required")
        forward = (ets - e0) * HARTREE_TO_KCAL
        reverse = (ets - e1) * HARTREE_TO_KCAL
        if forward <= 0 or reverse <= 0:
            raise CandidateFail(f"{model_id}: TS energy must be above both minima")
        if not math.isclose(number(barriers.get("forward"), "forward barrier"), forward, abs_tol=TOLERANCES["barrier_kcal_mol_abs"], rel_tol=0):
            raise CandidateFail(f"{model_id}: forward barrier is not recomputed from the native electronic energies")
        if not math.isclose(number(barriers.get("reverse"), "reverse barrier"), reverse, abs_tol=TOLERANCES["barrier_kcal_mol_abs"], rel_tol=0):
            raise CandidateFail(f"{model_id}: reverse barrier is not recomputed from the native electronic energies")
        assessment = row.get("scientific_assessment")
        if not isinstance(assessment, dict) or assessment.get("barrier_basis") != "electronic_energy":
            raise CandidateFail(f"{model_id}: structured electronic-energy scientific_assessment is required")
        threshold = number(assessment.get("facile_threshold_kcal_mol"), f"{model_id} facile threshold")
        maximum = max(forward, reverse)
        if not math.isclose(threshold, TOLERANCES["facile_threshold_kcal_mol"], abs_tol=TOLERANCES["facile_threshold_abs"], rel_tol=0):
            raise CandidateFail(f"{model_id}: frozen facile interpretation threshold is 3.0 kcal/mol")
        if not math.isclose(number(assessment.get("maximum_bidirectional_barrier_kcal_mol"),
                                  f"{model_id} assessed barrier"), maximum, abs_tol=.02, rel_tol=0):
            raise CandidateFail(f"{model_id}: scientific assessment does not match the native barriers")
        verdict = scientific_verdict(maximum, threshold)
        if assessment.get("verdict") != verdict:
            raise CandidateFail(f"{model_id}: scientific assessment verdict contradicts the recomputed barrier")
        expected_report_assessments.append({"model_id": model_id, **assessment})
        species = "acetate" if formula.get("C") == 4 else "formate"
        canonical_route = is_calibrated_route(species, row, dielectric)
        if not canonical_route:
            uncalibrated_routes.append(f"{model_id} uses {species} {row['method']}/{row['basis']} at epsilon={dielectric:g}")
        results.append({"model_id": model_id, "bridge_water": bridge, "barrier_forward": forward, "barrier_reverse": reverse,
                        "atom_count": len(parsed[0]["atoms"]), "ts_imaginary_cm-1": min(parsed[2]["frequencies_cm-1"]),
                        "ts_transfer_projection_cosine": transfer_projection(parsed[2], transfer,
                            next(i for i, f in enumerate(parsed[2]["frequencies_cm-1"]) if f < -20.0)),
                        "species": species})
    if seen_classes != {False, True}:
        raise CandidateFail("the submission must include both a no-water and a bridge-water model")
    if report_assessment(report_text).get("models") != expected_report_assessments:
        raise CandidateFail("report.md structured assessment does not match the native barriers.json evidence")
    if uncalibrated_routes or soft_negative_minima:
        details = []
        if uncalibrated_routes:
            details.append("unvalidated method/model route: " + "; ".join(uncalibrated_routes))
        if soft_negative_minima:
            details.append("minimum has a sub-threshold negative mode: " + "; ".join(soft_negative_minima))
        raise ReviewRequired("; ".join(details))
    return obj, [json.dumps(x, sort_keys=True) for x in results]


def check_public_input(assets: Path) -> None:
    source = assets / "qm_task.md"
    if not source.is_file() or sha256(source) != PUBLIC_INPUT_SHA256:
        raise EnvironmentInvalid("pinned public qm_task.md is missing or has a SHA-256 mismatch")


def main() -> int:
    global HARTREE_TO_KCAL, PUBLIC_INPUT_SHA256, TOLERANCES
    parser = argparse.ArgumentParser()
    parser.add_argument("app", nargs="?", default=os.environ.get("APP", "."))
    parser.add_argument("--assets", type=Path, default=Path(os.environ.get("ASSETS", "/app/environment/assets")))
    parser.add_argument("--logs", type=Path, default=Path(os.environ.get("LOGS", "/tmp/case06-logs")))
    args = parser.parse_args()
    try:
        refs = load_refs()
        HARTREE_TO_KCAL = refs["hartree_to_kcal"]
        PUBLIC_INPUT_SHA256 = refs["public_input_sha256"]
        TOLERANCES = refs["tolerances"]
    except EnvironmentInvalid as exc:
        args.logs.mkdir(parents=True, exist_ok=True)
        (args.logs / "reward.txt").unlink(missing_ok=True)
        result = {"case_id": CASE, "status": "ERROR", "error": str(exc)}
        (args.logs / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 2
    root = Path(args.app).resolve()
    logs = args.logs
    try:
        check_public_input(args.assets)
        _, rows = parse_candidate(root)
        result = {"case_id": CASE, "status": "PASS", "reward": 1, "criteria": {
            "qm_deliverables": "PASS", "ts_validity": "PASS", "scientific_assessment": "PASS"}, "models": [json.loads(x) for x in rows]}
        rc = 0
    except CandidateFail as exc:
        result = {"case_id": CASE, "status": "FAIL", "reward": 0, "reason": str(exc)}
        rc = 1
    except ReviewRequired as exc:
        result = {"case_id": CASE, "status": "REVIEW_REQUIRED", "reason": str(exc)}
        rc = 3
    except EnvironmentInvalid as exc:
        result = {"case_id": CASE, "status": "ERROR", "error": str(exc)}
        rc = 2
    except Exception as exc:
        result = {"case_id": CASE, "status": "ERROR", "error": f"unexpected verifier error: {type(exc).__name__}: {exc}"}
        rc = 2
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if rc == 0:
        (logs / "reward.txt").write_text("1\n", encoding="utf-8")
    else:
        (logs / "reward.txt").unlink(missing_ok=True)
    print(json.dumps(result, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
