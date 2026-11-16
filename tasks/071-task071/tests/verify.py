#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Structural Protonation Assessment of the Hsp60 Catalytic Dyad.
"""Independent case02 evidence and scientific review scorer."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any




class CandidateFail(ValueError):
    pass


class EnvironmentInvalid(RuntimeError):
    pass


INPUT_SHA256 = {
    "S_V72I.top": "cdca0f1a9870370bd66c09bd3abbaf713c3c78d2983da037421354ca393a7488",
    "S_V72I.rst": "80c30d0de644cc1223ab134286b98b96ee8bda409b352a23a6277d4ea9ac4753",
    "D_V72I_ASPASP.top": "331fe0bf7eb306d564a3e4cdc2927d555821919d2a141b17455621ac490b50f9",
    "D_V72I_ASPASP.rst": "0ada00fba712d54842febc851c175a4e8aea2ae7b861dd0bd48a3b21ef25b23a",
    "F_V72I_ASPASP.top": "2ad547555c30fd49dc9645689e483c3c6ea26dab4270d65e559a81afcfd1979b",
    "F_V72I_ASPASP.rst": "266a4571b2293a729a45a09533146dbf4d2e75d336aaeb46b70b71439ee17a70",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, *, candidate: bool = True) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        error = CandidateFail if candidate else EnvironmentInvalid
        raise error(f"cannot parse {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        error = CandidateFail if candidate else EnvironmentInvalid
        raise error(f"{path.name} must contain a JSON object")
    return value


def real_output_dir(app: str) -> Path:
    root = Path(app)
    final = root / "final"
    if root.is_symlink() or not root.is_dir() or final.is_symlink() or not final.is_dir():
        raise CandidateFail("APP/final must be a real directory")
    return final


def require_files(final: Path, names: tuple[str, ...]) -> dict[str, Path]:
    result = {}
    for name in names:
        path = final / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise CandidateFail(f"required final deliverable is missing, empty, or redirected: {name}")
        result[name] = path
    return result


def emit(logs: Path, status: str, message: str, details: dict[str, Any] | None = None) -> int:
    logs.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "case_id": "case-02-dyad-protonation",
        "status": status,
        "message": message,
    }
    if details:
        report["details"] = details
    if status in {"PASS", "FAIL"}:
        reward = 1.0 if status == "PASS" else 0.0
        report["reward"] = reward
        (logs / "reward.txt").write_text(f"{reward:g}\n", encoding="ascii")
    else:
        (logs / "reward.txt").unlink(missing_ok=True)
    (logs / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return {"PASS": 0, "REVIEW_REQUIRED": 0, "FAIL": 1, "ENV_INVALID": 2}.get(status, 2)


CASE = "case-02-dyad-protonation"
REFS_SHA256 = "54e72a64585fa187781f772cdddaf9f03e990cdb6437e5d9346c9f9fd90fc76f"
SYSTEMS = {
    "S_V72I": ("S_V72I", 1),
    "D_V72I": ("D_V72I_ASPASP", 0),
    "F_V72I": ("F_V72I_ASPASP", 0),
}
PROTEIN = {
    "ALA", "ARG", "ASN", "ASP", "ASH", "CYS", "GLN", "GLU", "GLH", "GLY",
    "HIS", "HID", "HIE", "HIP", "ILE", "LEU", "LYS", "MET", "PHE", "PRO",
    "SER", "THR", "TRP", "TYR", "VAL",
}
COFACTORS = {"atp", "mg", "k+", "k"}
# Amber names the histidine tautomers HID/HIE/HIP; standard PDB writes HIS. The atom set below
# already fixes the protonation state, so treat the names as aliases when matching chains.
_PDB_RESIDUE_ALIASES = {"HID": "HIS", "HIE": "HIS", "HIP": "HIS"}


def _cofactor_name(value: object) -> str:
    """Normalize a cofactor name for identity comparison (case and charge suffix are cosmetic)."""
    return str(value).strip().casefold().rstrip("+")
COFACTOR_RADIUS = 12.0
PKA_ROW = re.compile(r"^ASP\s+(\d+)\s+(\S)\s+([-+]?\d+(?:\.\d+)?)(?:\*)?\s+\d+\s+%")
STATE_NAMES = {"AspAsp", "AshAsp", "AspAsh", "AshAsh"}


def _sha(path: Path) -> str:
    return sha256_file(path)


def _normalize_target_bonds(targets: dict[str, Any]) -> dict[str, Any]:
    """Accept bond entries given either as atom names or as {name, ...} objects.

    The reference basis stores plain name arrays. A submission that also reports the bonded
    atom's topology index carries the same information, so reduce it to names while keeping the
    submitted order (the reference order is checked by dict equality below).
    """
    normalized: dict[str, Any] = {}
    for key, residue in targets.items():
        if not isinstance(residue, dict):
            normalized[key] = residue
            continue
        atoms = residue.get("atoms")
        if not isinstance(atoms, dict):
            normalized[key] = residue
            continue
        rebuilt = {}
        for name, atom in atoms.items():
            if not isinstance(atom, dict):
                rebuilt[name] = atom
                continue
            bonds = atom.get("bonds")
            if isinstance(bonds, list) and all(isinstance(item, dict) for item in bonds):
                if all(isinstance(item.get("name"), str) for item in bonds):
                    atom = {**atom, "bonds": [item["name"] for item in bonds]}
            rebuilt[name] = atom
        normalized[key] = {**residue, "atoms": rebuilt}
    return normalized


def _json_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateFail(f"{label} must be a finite JSON number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise CandidateFail(f"{label} must be a finite JSON number") from exc
    if not math.isfinite(result):
        raise CandidateFail(f"{label} must be a finite JSON number")
    return result


def _candidate_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CandidateFail(f"{label} must be a JSON object")
    return value


def _read_report(path: Path) -> str:
    try:
        report = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CandidateFail(f"report.md must be readable UTF-8: {exc}") from exc
    if not report.strip():
        raise CandidateFail("report.md must contain a scientific interpretation")
    return report


def _load_json(path: Path, what: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise CandidateFail(f"{what} is absent, empty, or redirected")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateFail(f"{what} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateFail(f"{what} must be a JSON object")
    return value


def _basis() -> dict[str, Any]:
    path = Path(__file__).with_name("refs.json")
    if path.is_symlink() or not path.is_file() or sha256_file(path) != REFS_SHA256:
        raise EnvironmentInvalid("private scientific reference is missing, redirected, or changed")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnvironmentInvalid(f"private scientific reference is absent or damaged: {exc}") from exc
    if not isinstance(result, dict) or result.get("schema_version") != "case02-native-reference/v1":
        raise EnvironmentInvalid("private scientific reference has an unsupported schema")
    if result.get("input_sha256") != INPUT_SHA256:
        raise EnvironmentInvalid("private scientific reference input pins disagree with the scorer")
    return result


def _public_assets(root: Path) -> dict[str, Path]:
    if root.is_symlink() or not root.is_dir():
        raise EnvironmentInvalid("public asset directory is absent or redirected")
    paths: dict[str, Path] = {}
    for name, expected in INPUT_SHA256.items():
        path = root / name
        if path.is_symlink() or not path.is_file() or _sha(path) != expected:
            raise EnvironmentInvalid(f"public input is missing, redirected, or differs from its pinned SHA-256: {name}")
        paths[name] = path
    return paths


def _pdb_atom_records(path: Path) -> list[tuple[int, str, str, str, int, tuple[float, float, float]]]:
    rows = []
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CandidateFail(f"{path.name} is not a readable ASCII PDB: {exc}") from exc
    for line in lines:
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 54:
            raise CandidateFail(f"{path.name} contains a truncated coordinate record")
        try:
            rows.append((
                int(line[6:11]), line[12:16].strip(), line[17:20].strip(), line[21:22], int(line[22:26]),
                (round(float(line[30:38]), 3), round(float(line[38:46]), 3), round(float(line[46:54]), 3)),
            ))
        except ValueError as exc:
            raise CandidateFail(f"{path.name} contains an invalid atom record") from exc
    if not rows:
        raise CandidateFail(f"{path.name} contains no coordinate records")
    return rows


def _validate_selection_manifest(path: Path, basis: dict[str, Any], assets: dict[str, Path], output: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ccb-case02-reference-") as temp:
        reference_dir = Path(temp)
        _restore_reference_files(basis, reference_dir)
        return _validate_selection_manifest_with_references(path, basis, assets, output, reference_dir)


def _restore_reference_files(basis: dict[str, Any], reference_dir: Path) -> None:
    native = basis.get("native_structure_reference", {})
    reference_files = native.get("reference_files", {})
    embedded = native.get("embedded_files_base64")
    expected_names = {f"{system}_chainA_site.pdb" for system in SYSTEMS} | {
        "native-cofactors.json", "selection_manifest.json",
    }
    if (not isinstance(reference_files, dict) or set(reference_files) != expected_names
            or not isinstance(embedded, dict) or set(embedded) != expected_names):
        raise EnvironmentInvalid("private native reference bytes are incomplete")
    for name in sorted(expected_names):
        try:
            data = base64.b64decode(embedded[name], validate=True)
        except (TypeError, ValueError) as exc:
            raise EnvironmentInvalid(f"private native reference encoding is invalid: {name}") from exc
        if hashlib.sha256(data).hexdigest() != reference_files[name]:
            raise EnvironmentInvalid(f"private native reference bytes do not match their SHA-256: {name}")
        try:
            with (reference_dir / name).open("xb") as stream:
                stream.write(data)
        except OSError as exc:
            raise EnvironmentInvalid(f"private native reference cannot be restored: {name}") from exc


def _validate_selection_manifest_with_references(path: Path, basis: dict[str, Any], assets: dict[str, Path],
                                                  output: Path, reference_dir: Path) -> dict[str, Any]:
    manifest = _load_json(path, "selection_manifest.json")
    if manifest.get("schema") != "case02-propka-inputs/v1" or not isinstance(manifest.get("systems"), dict):
        raise CandidateFail("selection_manifest.json has an unsupported schema")
    if set(manifest["systems"]) != set(SYSTEMS):
        raise CandidateFail("selection_manifest.json must describe S, D, and F exactly")
    native_systems = basis.get("native_structure_reference", {}).get("systems", {})
    if set(native_systems) != set(SYSTEMS):
        raise EnvironmentInvalid("private native topology-derived structure basis is incomplete")
    ref_files = basis["native_structure_reference"].get("reference_files", {})
    for name, expected_hash in ref_files.items():
        ref_path = reference_dir / name
        if ref_path.is_symlink() or not ref_path.is_file() or _sha(ref_path) != expected_hash:
            raise EnvironmentInvalid(f"private native reference file is missing or damaged: {name}")
    try:
        cofactor_basis = json.loads((reference_dir / "native-cofactors.json").read_text(encoding="utf-8"))
        reference_manifest = json.loads((reference_dir / "selection_manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnvironmentInvalid(f"private native cofactor basis is unreadable: {exc}") from exc
    if cofactor_basis.get("schema_version") != "case02-native-cofactors/v1":
        raise EnvironmentInvalid("private native cofactor basis has an unsupported schema")
    for system, (stem, offset) in SYSTEMS.items():
        submitted = _candidate_object(manifest["systems"][system], f"{system} selection record")
        native = native_systems[system]
        for field, name in (("input_topology", f"{stem}.top"), ("input_coordinates", f"{stem}.rst")):
            item = submitted.get(field)
            if not isinstance(item, dict) or item.get("sha256") != _sha(assets[name]):
                raise CandidateFail(f"{system}: selection manifest does not pin the actual {name} bytes")
            pinned_native = cofactor_basis.get("source_topology_coordinates_sha256", {}).get(system, {})
            if item.get("sha256") != pinned_native.get("top" if field == "input_topology" else "rst"):
                raise EnvironmentInvalid(f"private cofactor basis source pin disagrees for {system} {name}")
        selection = _candidate_object(submitted.get("selection"), f"{system} selection")
        if (type(selection.get("protein_residue_count")) is not int or selection.get("protein_residue_count") != 526
                or selection.get("pdb_chain") != "A"
                or type(selection.get("protein_atom_count")) is not int
                or selection.get("protein_atom_count") != native["protein_atom_count"]):
            raise CandidateFail(f"{system}: select the complete first 526-residue protein subunit as chain A")
        if not isinstance(selection.get("ligand_policy"), str) or not selection["ligand_policy"].strip():
            raise CandidateFail(f"{system}: explain the chosen ATP/Mg/K treatment in the selection manifest")
        submitted_cofactors = selection.get("cofactor_residues")
        reference_cofactors = reference_manifest["systems"][system]["selection"]["cofactor_residues"]
        if not isinstance(submitted_cofactors, list) or len(submitted_cofactors) != len(reference_cofactors):
            raise CandidateFail(f"{system}: selection manifest must account for all native ATP/Mg/K residues")
        # Residue identities and native dyad distances are fixed by the supplied topology;
        # the inclusion policy is a scientific choice and may vary between defensible models.
        # Cofactor names follow the Amber spelling (atp/MG/K+); the residue number is the identity,
        # so compare names case-insensitively and ignore a trailing charge suffix.
        submitted_by_key = {
            (_cofactor_name(item.get("name")), item.get("topology_residue_number")): item
            for item in submitted_cofactors if isinstance(item, dict)
        }
        reference_by_key = {(_cofactor_name(item["name"]), item["topology_residue_number"]): item
                            for item in reference_cofactors}
        if len(submitted_by_key) != len(submitted_cofactors) or set(submitted_by_key) != set(reference_by_key):
            raise CandidateFail(f"{system}: cofactor inventory contains missing or duplicate native residues")
        for key, actual in submitted_by_key.items():
            expected = reference_by_key[key]
            if (type(actual.get("topology_residue_number")) is not int
                    or actual.get("topology_residue_number") != expected["topology_residue_number"]
                    or _cofactor_name(actual.get("name")) != _cofactor_name(expected["name"])
                    or not math.isclose(_json_number(actual.get("nearest_dyad_distance_angstrom"), "nearest_dyad_distance_angstrom"),
                                        float(expected["nearest_dyad_distance_angstrom"]), abs_tol=0.01)
                    or not isinstance(actual.get("included"), bool)):
                raise CandidateFail(f"{system}: cofactor inventory or measured native distance is incorrect")
        targets = submitted.get("target_residues")
        if isinstance(targets, dict):
            targets = _normalize_target_bonds(targets)
        if not isinstance(targets, dict) or targets != native["target_residues"]:
            raise CandidateFail(f"{system}: mature Asp50/Asp397 indices, coordinates, or topology bonds differ from the native basis")
        pdb_meta = submitted.get("structure")
        if not isinstance(pdb_meta, dict):
            raise CandidateFail(f"{system}: selected PDB hash is absent from the manifest")
        pdb_path = output / "evidence" / "structures" / Path(pdb_meta.get("path", "")).name
        expected_name = f"{system}_chainA_site.pdb"
        if pdb_meta.get("path") != expected_name or pdb_path.is_symlink() or not pdb_path.is_file():
            raise CandidateFail(f"{system}: candidate selected PDB is missing or has an unexpected path")
        actual_hash = _sha(pdb_path)
        if pdb_meta.get("sha256") != actual_hash:
            raise CandidateFail(f"{system}: selected PDB hash in manifest is stale")
        actual_rows = _pdb_atom_records(pdb_path)
        reference_path = reference_dir / f"{system}_chainA_site.pdb"
        reference_rows = _pdb_atom_records(reference_path)
        def row_key(row):
            return (row[3], row[4], _PDB_RESIDUE_ALIASES.get(row[2], row[2]), row[1])
        expected_protein = {row_key(row): row for row in reference_rows if row[3] == "A" and row[2] in PROTEIN and row[4] <= 526}
        actual_protein = {row_key(row): row for row in actual_rows if row[2] in PROTEIN}
        if len(actual_protein) != len([row for row in actual_rows if row[2] in PROTEIN]) or set(actual_protein) != set(expected_protein):
            raise CandidateFail(f"{system}: selected PDB must preserve every atom and residue of the native chain-A protein")
        if any(row[3] != "A" or row[4] < 1 or row[4] > 526 for row in actual_protein.values()):
            raise CandidateFail(f"{system}: native protein chain or residue numbering changed")
        for key, expected in expected_protein.items():
            actual = actual_protein[key]
            if any(abs(actual[5][i] - expected[5][i]) > 0.001 for i in range(3)):
                raise CandidateFail(f"{system}: {key[2]} {key[3]} coordinate differs from supplied native restart")
        # Cofactors may be retained or omitted by the stated protocol, but every retained
        # atom must map back to a complete native residue and its exact topology coordinates.
        all_native_cofactors = cofactor_basis["systems"][system]
        residue_lookup = {(_cofactor_name(item["name"]), item["topology_residue_number"]): item for item in all_native_cofactors}
        actual_nonprotein = [row for row in actual_rows if row[2] not in PROTEIN]
        if any(row[3] != "A" for row in actual_nonprotein):
            raise CandidateFail(f"{system}: retained ligand/ion records must preserve chain-A topology mapping")
        actual_groups: dict[tuple[str, int], list[tuple]] = {}
        for row in actual_nonprotein:
            actual_groups.setdefault((_cofactor_name(row[2]), row[4]), []).append(row)
        declared_included = {(_cofactor_name(item["name"]), item["topology_residue_number"]) for item in submitted_cofactors if item["included"]}
        if set(actual_groups) != declared_included:
            raise CandidateFail(f"{system}: selected native cofactor residues disagree with the declared inclusion policy")
        for key, rows in actual_groups.items():
            native_cofactor = residue_lookup.get(key)
            if native_cofactor is None:
                raise CandidateFail(f"{system}: selected PDB contains a non-native ligand or ion")
            expected_atoms = {_cofactor_name(atom["name"]): atom for atom in native_cofactor["atoms"]}
            observed = {_cofactor_name(row[1]): row for row in rows}
            if len(observed) != len(rows) or set(observed) != set(expected_atoms):
                raise CandidateFail(f"{system}: selected cofactor {key} is incomplete or has duplicate atoms")
            for atom_name, row in observed.items():
                xyz = expected_atoms[atom_name]["xyz"]
                if any(abs(row[5][i] - round(float(xyz[i]), 3)) > 0.001 for i in range(3)):
                    raise CandidateFail(f"{system}: selected cofactor {key} {atom_name} differs from native coordinates")
        reference_included = {(_cofactor_name(item["name"]), item["topology_residue_number"]) for item in reference_cofactors if item["included"]}
        if declared_included != reference_included:
            selection["requires_expert_review"] = True
        radius = selection.get("cofactor_radius_angstrom")
        if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not math.isfinite(radius):
            raise CandidateFail(f"{system}: cofactor_radius_angstrom must be a finite JSON number")
        if radius <= 0:
            selection["requires_expert_review"] = True
        elif not math.isclose(float(radius), COFACTOR_RADIUS, abs_tol=1e-6):
            selection["requires_expert_review"] = True
        if type(selection.get("retained_atom_count")) is not int or selection.get("retained_atom_count") != len(actual_rows):
            raise CandidateFail(f"{system}: retained atom count disagrees with selected PDB contents")
        for mature, residue_name in ((50, "Asp50"), (397, "Asp397")):
            native_target = native["target_residues"][str(mature)]
            system_residue = native_target["system_residue_number"]
            for atom_name, detail in native_target["atoms"].items():
                rows = [row for row in actual_rows if row[3] == "A" and row[4] == system_residue and row[1] == atom_name]
                if (len(rows) != 1 or rows[0][1] != atom_name or rows[0][2] != "ASP"
                        or rows[0][3] != "A" or rows[0][4] != system_residue):
                    raise CandidateFail(f"{system}: {residue_name} {atom_name} PDB atom mapping differs from native topology")
                if any(abs(rows[0][5][i] - round(float(detail["coordinate_angstrom"][i]), 3)) > 0.001 for i in range(3)):
                    raise CandidateFail(f"{system}: {residue_name} {atom_name} PDB coordinate differs from native topology")
    return manifest


def _parse_pka(path: Path, system: str, offset: int) -> dict[str, float]:
    found: dict[int, list[float]] = {50 + offset: [], 397 + offset: []}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CandidateFail(f"{path.name} is not readable UTF-8 text: {exc}") from exc
    for line in text.splitlines():
        match = PKA_ROW.match(line)
        if match and match.group(2) == "A" and int(match.group(1)) in found:
            found[int(match.group(1))].append(float(match.group(3)))
    values = {}
    for mature, label in ((50, "Asp50"), (397, "Asp397")):
        rows = found[mature + offset]
        if len(rows) != 1 or not math.isfinite(rows[0]):
            raise CandidateFail(f"{system}: {path.name} must contain exactly one finite chain-A {label} pKa")
        values[label] = rows[0]
    return values


def _run_propka(pdb_path: Path, cwd: Path, expected: dict[str, float], system: str) -> None:
    executable = shutil.which("propka3")
    if not executable:
        raise EnvironmentInvalid("PROPKA is required to independently replay the submitted prediction")
    command = [executable, "--log-level", "INFO", str(pdb_path.resolve())]
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as exc:
        raise EnvironmentInvalid(f"independent PROPKA replay timed out for {system}") from exc
    if result.returncode != 0:
        raise EnvironmentInvalid(f"independent PROPKA replay failed for {system}: {result.stderr[-1000:]}")
    raw = cwd / f"{pdb_path.stem}.pka"
    if not raw.is_file() or raw.stat().st_size == 0:
        raise EnvironmentInvalid(f"independent PROPKA replay produced no usable .pka file for {system}")
    offset = SYSTEMS[system][1]
    replay = _parse_pka(raw, system, offset)
    for residue, value in expected.items():
        if not math.isclose(replay[residue], value, rel_tol=0, abs_tol=0.011):
            raise CandidateFail(f"{system}: submitted PROPKA evidence is stale or does not replay for {residue}")


def _validate_plan(plan: dict[str, Any], pka: dict[str, dict[str, float]]) -> None:
    if plan.get("schema_version") != "case02-protonation-plan/v1":
        raise CandidateFail("protonation_plan.json has an unsupported schema")
    ph = plan.get("physiological_pH")
    if not isinstance(ph, dict) or ph.get("minimum") != 7.0 or ph.get("maximum") != 7.4 or ph.get("reference") != 7.2:
        raise CandidateFail("protonation_plan.json must interpret estimates over pH 7.0-7.4")
    if plan.get("state_names") != {
        "AspAsp": "Asp50− / Asp397−", "AshAsp": "Asp50H / Asp397−",
        "AspAsh": "Asp50− / Asp397H", "AshAsh": "Asp50H / Asp397H",
    }:
        raise CandidateFail("protonation_plan.json must define all four dyad states clearly")
    if not isinstance(plan.get("coupling_caveat"), str) or not plan["coupling_caveat"].strip():
        raise CandidateFail("protonation plan must distinguish independent site estimates from coupled dyad microstates")
    systems = plan.get("systems")
    if not isinstance(systems, dict) or set(systems) != set(SYSTEMS):
        raise CandidateFail("protonation plan must discuss all three structural systems")
    for system, record in systems.items():
        record = _candidate_object(record, f"{system} protonation record")
        if record.get("predicted_pka") != pka[system]:
            raise CandidateFail(f"{system}: plan pKa values differ from pka.json")
        assessed = record.get("assessed_states")
        if not isinstance(assessed, dict) or set(assessed) != STATE_NAMES:
            raise CandidateFail(f"{system}: assess all four dyad protonation states")
        for name, state in assessed.items():
            if not isinstance(state, dict) or state.get("decision") not in {"recommended", "sensitivity", "low_priority"}:
                raise CandidateFail(f"{system}: {name} needs a clear simulation-priority decision")
            if not isinstance(state.get("rationale"), str) or not state["rationale"].strip():
                raise CandidateFail(f"{system}: {name} needs a specific rationale")
        recommended = record.get("recommended_states")
        if not isinstance(recommended, list) or not recommended or not set(recommended).issubset(STATE_NAMES):
            raise CandidateFail(f"{system}: recommended_states must name one or more of the four supported states")
        if set(recommended) != {name for name, state in assessed.items() if state["decision"] == "recommended"}:
            raise CandidateFail(f"{system}: recommended_states disagrees with assessed_states")
        if system in {"D_V72I", "F_V72I"} and not {"AspAsp", "AshAsp", "AspAsh"}.issubset(assessed):
            raise CandidateFail(f"{system}: evaluate the doubly deprotonated baseline and both single-proton alternatives")


def score(app: str, assets_dir: str, logs_dir: str) -> int:
    try:
        basis = _basis()
        assets = _public_assets(Path(assets_dir))
        output = real_output_dir(app)
        required = (
            "pka.json", "protonation_plan.json", "report.md",
            "evidence/structures/S_V72I_chainA_site.pdb",
            "evidence/structures/D_V72I_chainA_site.pdb",
            "evidence/structures/F_V72I_chainA_site.pdb",
            "evidence/structures/selection_manifest.json", "evidence/provenance.json",
        )
        files = require_files(output, required)
        # Reject structurally malformed submissions before any scientific replay.
        pka_doc = _load_json(files["pka.json"], "pka.json")
        if pka_doc.get("schema_version") != "case02-pka/v1":
            raise CandidateFail("pka.json has an unsupported schema")
        manifest = _validate_selection_manifest(files["evidence/structures/selection_manifest.json"], basis, assets, output)
        method = pka_doc.get("method")
        if not isinstance(method, dict) or not isinstance(method.get("name"), str):
            raise CandidateFail("pka.json must name the selected predictor method")
        if method["name"].upper() != "PROPKA":
            alternate_systems = pka_doc.get("systems")
            if not isinstance(alternate_systems, dict) or set(alternate_systems) != set(SYSTEMS):
                raise CandidateFail("alternate predictor must report both dyad sites for all three systems")
            alternate_version = method.get("version")
            if not isinstance(alternate_version, str) or not alternate_version.strip():
                raise CandidateFail("alternate predictor must provide its exact version")
            alternate_values = {}
            alternate_provenance = _load_json(files["evidence/provenance.json"], "evidence/provenance.json")
            if (alternate_provenance.get("case_id") != CASE
                    or not isinstance(alternate_provenance.get("systems"), dict)
                    or set(alternate_provenance["systems"]) != set(SYSTEMS)):
                raise CandidateFail("alternate predictor provenance must cover all three systems")
            for system, row in alternate_systems.items():
                row = _candidate_object(row, f"{system} alternate predictor record")
                alternate_values[system] = {}
                stem, _offset = SYSTEMS[system]
                pdb_path = files[f"evidence/structures/{system}_chainA_site.pdb"]
                record = _candidate_object(alternate_provenance["systems"][system], f"{system} alternate provenance")
                raw_meta = _candidate_object(record.get("pka_output"), f"{system} pka_output")
                raw_rel = raw_meta.get("path")
                if not isinstance(raw_rel, str) or not raw_rel.startswith("evidence/"):
                    raise CandidateFail(f"{system}: alternate predictor output must be stored under evidence/")
                relative = Path(raw_rel)
                raw_path = output / relative
                try:
                    resolved_raw = raw_path.resolve(strict=True)
                    resolved_raw.relative_to(output.resolve())
                except (OSError, ValueError):
                    raise CandidateFail(f"{system}: alternate predictor raw output is missing or escapes the result directory") from None
                if (relative.is_absolute() or ".." in relative.parts
                        or any(part.is_symlink() for part in (output / part for part in relative.parents if str(part) != "."))
                        or raw_path.is_symlink() or not raw_path.is_file()):
                    raise CandidateFail(f"{system}: alternate predictor raw output is missing or redirected")
                command = record.get("command")
                pdb_provenance = _candidate_object(record.get("pdb"), f"{system} PDB provenance")
                if (type(record.get("returncode")) is not int or record.get("returncode") != 0
                        or pdb_provenance.get("sha256") != _sha(pdb_path)
                        or record.get("source_topology_sha256") != _sha(assets[f"{stem}.top"])
                        or record.get("source_coordinates_sha256") != _sha(assets[f"{stem}.rst"])
                        or raw_meta.get("sha256") != _sha(raw_path)
                        or not isinstance(command, list) or not command
                        or not any(pdb_path.name in str(argument) for argument in command)):
                    raise CandidateFail(f"{system}: alternate predictor provenance must bind its successful command and raw output to the actual PDB and native inputs")
                for residue in ("Asp50", "Asp397"):
                    value = row.get(residue)
                    value = _candidate_object(value, f"{system} alternate {residue} record")
                    value_pka = _json_number(value.get("pka"), f"{system} {residue} pKa")
                    if (type(value.get("mature_residue")) is not int or type(value.get("system_residue")) is not int
                            or value.get("mature_residue") != int(residue[3:])
                            or value.get("system_residue") != basis["mature_to_system_residue"][system][residue]):
                        raise CandidateFail(f"{system}: alternate predictor {residue} uses the wrong residue mapping")
                if (row.get("input_structure_sha256") != _sha(pdb_path)
                        or row.get("source_topology_sha256") != _sha(assets[f"{stem}.top"])
                        or row.get("source_coordinates_sha256") != _sha(assets[f"{stem}.rst"])
                        or row.get("evidence") != raw_rel):
                    raise CandidateFail(f"{system}: alternate pKa record omits native input hashes")
                # Populate both site values after schema checks above.
                for residue in ("Asp50", "Asp397"):
                    alternate_values[system][residue] = float(row[residue]["pka"])
            _validate_plan(_load_json(files["protonation_plan.json"], "protonation_plan.json"), alternate_values)
            _read_report(files["report.md"])
            return emit(Path(logs_dir), "REVIEW_REQUIRED", "native topology, residue mapping, cofactor selection, structured alternative predictions, and four-state plan are complete; an expert must review the predictor and its native output evidence", {
                "method": method["name"], "native_structure_selection_verified": True,
                "alternate_pka": alternate_values, "expert_scientific_review_required": True,
            })
        files.update(require_files(output, tuple(
            f"evidence/propka/{system}_chainA_site.pka" for system in SYSTEMS
        )))
        version = method.get("version")
        if not isinstance(version, str) or not version.startswith("propka3 "):
            raise CandidateFail("pka.json must name the PROPKA version")
        if not re.fullmatch(r"propka3 3\.\d+(?:\.\d+)?", version):
            raise CandidateFail("supported automatic PROPKA evidence must name a 3.x release")
        if pka_doc.get("physiological_ph_range") != [7.0, 7.4]:
            raise CandidateFail("pka.json must report the requested physiological pH range")
        if not isinstance(method.get("uncertainty"), str) or not method["uncertainty"].strip():
            raise CandidateFail("pka.json must describe uncertainty and avoid presenting point estimates as calibrated confidence intervals")
        submitted_systems = pka_doc.get("systems")
        if not isinstance(submitted_systems, dict) or set(submitted_systems) != set(SYSTEMS):
            raise CandidateFail("pka.json must report Asp50 and Asp397 for S, D, and F")

        provenance = _load_json(files["evidence/provenance.json"], "evidence/provenance.json")
        if provenance.get("case_id") != CASE or provenance.get("propka_version") != version:
            raise CandidateFail("provenance case or PROPKA version disagrees with pka.json")
        if provenance.get("selection_manifest_sha256") != _sha(files["evidence/structures/selection_manifest.json"]):
            raise CandidateFail("provenance selection manifest hash is stale")
        if not isinstance(provenance.get("systems"), dict) or set(provenance["systems"]) != set(SYSTEMS):
            raise CandidateFail("provenance must describe all three executed PROPKA calculations")

        parsed: dict[str, dict[str, float]] = {}
        executable = shutil.which("propka3")
        if not executable:
            raise EnvironmentInvalid("PROPKA is required to evaluate the submitted native predictor evidence")
        installed_version_result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=15)
        if installed_version_result.returncode != 0:
            raise EnvironmentInvalid("PROPKA version query failed in verifier runtime")
        installed_version = installed_version_result.stdout.strip()
        independently_replayed = installed_version == version
        report = _read_report(files["report.md"])
        for system in SYSTEMS:
            raw_rel = f"evidence/propka/{system}_chainA_site.pka"
            pdb_path = files[f"evidence/structures/{system}_chainA_site.pdb"]
            raw_path = files[raw_rel]
            record = _candidate_object(provenance["systems"][system], f"{system} PROPKA provenance")
            if type(record.get("returncode")) is not int or record.get("returncode") != 0:
                raise CandidateFail(f"{system}: provenance records an unsuccessful predictor run")
            raw_info = _candidate_object(record.get("pka_output"), f"{system} PROPKA output provenance")
            if raw_info.get("path") != raw_rel or raw_info.get("sha256") != _sha(raw_path):
                raise CandidateFail(f"{system}: provenance does not hash the actual raw PROPKA output")
            if record.get("pdb", {}).get("path") != f"evidence/structures/{system}_chainA_site.pdb" or record.get("pdb", {}).get("sha256") != _sha(pdb_path):
                raise CandidateFail(f"{system}: provenance does not hash the actual PDB sent to PROPKA")
            stem, offset = SYSTEMS[system]
            source_top = f"{stem}.top"
            source_rst = f"{stem}.rst"
            if record.get("source_topology_sha256") != _sha(assets[source_top]) or record.get("source_coordinates_sha256") != _sha(assets[source_rst]):
                raise CandidateFail(f"{system}: predictor provenance does not name the supplied native topology/restart")
            parsed[system] = _parse_pka(raw_path, system, offset)
            if record.get("parsed_pka") != parsed[system]:
                raise CandidateFail(f"{system}: provenance parsed values disagree with raw PROPKA output")
            values = _candidate_object(submitted_systems[system], f"{system} pKa result")
            # `evidence` names that system's raw PROPKA output; accept an evidence object that
            # carries the same path under its pka_output key.
            evidence_value = values.get("evidence")
            if isinstance(evidence_value, dict):
                evidence_value = evidence_value.get("pka_output")
            if (values.get("input_structure_sha256") != _sha(pdb_path)
                    or values.get("source_topology_sha256") != _sha(assets[source_top])
                    or values.get("source_coordinates_sha256") != _sha(assets[source_rst])
                    or evidence_value != raw_rel):
                raise CandidateFail(f"{system}: result omits or misstates its exact native input/evidence hashes")
            expected_map = basis["mature_to_system_residue"][system]
            for residue in ("Asp50", "Asp397"):
                item = values.get(residue)
                if (not isinstance(item, dict) or type(item.get("mature_residue")) is not int
                        or type(item.get("system_residue")) is not int
                        or item.get("mature_residue") != int(residue[3:]) or item.get("system_residue") != expected_map[residue]):
                    raise CandidateFail(f"{system}: {residue} mature/system numbering is incorrect")
                pka_value = _json_number(item.get("pka"), f"{system} {residue} pKa")
                if not math.isclose(pka_value, parsed[system][residue], abs_tol=0.005):
                    raise CandidateFail(f"{system}: {residue} JSON pKa does not match the actual raw PROPKA output")
            command = record.get("command")
            if (not isinstance(command, list) or len(command) < 3 or Path(str(command[0])).name != "propka3"
                    or "--log-level" not in command or Path(str(command[-1])).name != pdb_path.name):
                raise CandidateFail(f"{system}: provenance lacks the actual PROPKA command line")
            if not isinstance(record.get("pka_output", {}).get("sha256"), str):
                raise CandidateFail(f"{system}: provenance is missing predictor output hash")
            # Re-run the predictor when the verifier has the same version. Other 3.x
            # results remain eligible for evidence review and are never silently rejected.
            if independently_replayed:
                with tempfile.TemporaryDirectory(prefix="ccb-case02-propka-") as temp:
                    scratch = Path(temp)
                    replay_pdb = scratch / pdb_path.name
                    shutil.copyfile(pdb_path, replay_pdb)
                    _run_propka(replay_pdb, scratch, parsed[system], system)

        _validate_plan(_load_json(files["protonation_plan.json"], "protonation_plan.json"), parsed)
        if version != "propka3 3.5.1":
            return emit(Path(logs_dir), "REVIEW_REQUIRED", "complete native topology, PDB mapping, raw PROPKA 3.x outputs, and four-state plan verified; alternate PROPKA version results need scientific review", {
                "method": version, "pka": parsed, "runtime_propka_version": installed_version,
                "native_structure_selection_verified": True,
                "independent_propka_replay": independently_replayed,
                "expert_scientific_review_required": True,
            })
        review_selection = any(row["selection"].get("requires_expert_review") for row in manifest["systems"].values())
        if parsed != basis["native_propka_pka"] and not review_selection:
            raise CandidateFail("submitted PROPKA 3.5.1 values disagree with independent replay from the pinned native structures")
        if review_selection:
            return emit(Path(logs_dir), "REVIEW_REQUIRED", "candidate cofactor inclusion differs from the reference protocol; native mappings and exact PROPKA replay were verified, and an expert must review the declared ligand treatment", {
                "method": version, "pka": parsed, "independent_propka_replay": True,
                "native_topology_and_coordinates": "all protein and selected cofactor atoms matched against the SHA-pinned ParmEd topology/restart basis",
                "expert_scientific_review_required": True,
            })
        return emit(Path(logs_dir), "PASS", "native Amber topology extraction, atom mapping, cofactor selection, raw PROPKA replay, pKa table, and four-state protonation analysis agree", {
            "method": version,
            "pka": parsed,
            "verified_chain_a_residues": 526,
            "native_topology_and_coordinates": "candidate atoms checked against private ParmEd 4.3.0-derived basis pinned to all six public input hashes",
            "independent_propka_replay": True,
            "reference_comparison": basis["scientific_interpretation"],
            "all_four_dyad_states_assessed": True,
        })
    except EnvironmentInvalid as exc:
        return emit(Path(logs_dir), "ENV_INVALID", str(exc))
    except CandidateFail as exc:
        return emit(Path(logs_dir), "FAIL", str(exc))
    except Exception as exc:
        return emit(Path(logs_dir), "ENV_INVALID", f"verifier could not establish a safe complete result: {type(exc).__name__}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("app")
    parser.add_argument("--assets", required=True)
    parser.add_argument("--logs", required=True)
    args = parser.parse_args()
    raise SystemExit(score(args.app, args.assets, args.logs))


if __name__ == "__main__":
    main()
