#!/usr/bin/env bash
set -euo pipefail
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/task72-solution.XXXXXX")"
# Keep extracted sources available until execution and any HPC staging/collection finish.
trap 'rm -rf -- "$work_dir"' EXIT
cat > "$work_dir/solve.py" <<'TASK_SOURCE_SOLVE_PY'
#!/usr/bin/env python3
"""Run the reference case02 structure extraction and native PROPKA prediction."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from prepare_structures import SYSTEMS, run as prepare_structures


CASE = "case-02-dyad-protonation"
TARGET_RESIDUES = {
    "S_V72I": {"Asp50": 51, "Asp397": 398},
    "D_V72I": {"Asp50": 50, "Asp397": 397},
    "F_V72I": {"Asp50": 50, "Asp397": 397},
}
PKA_ROW = re.compile(r"^ASP\s+(\d+)\s+(\S)\s+([-+]?\d+(?:\.\d+)?)(?:\*)?\s+\d+\s+%")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_pka(path: Path, system: str) -> dict[str, float]:
    found: dict[int, list[float]] = {number: [] for number in TARGET_RESIDUES[system].values()}
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        match = PKA_ROW.match(line)
        if not match:
            continue
        residue_number, chain, value = int(match.group(1)), match.group(2), float(match.group(3))
        if chain == "A" and residue_number in found:
            found[residue_number].append(value)
    result = {}
    for mature_name, residue_number in TARGET_RESIDUES[system].items():
        values = found[residue_number]
        if len(values) != 1:
            raise ValueError(f"{system}: expected one PROPKA Asp at chain A residue {residue_number}, found {len(values)}")
        result[mature_name] = values[0]
    return result


def build_plan(predictions: dict[str, dict[str, float]]) -> dict:
    plan = {
        "schema_version": "case02-protonation-plan/v1",
        "physiological_pH": {"minimum": 7.0, "maximum": 7.4, "reference": 7.2},
        "state_names": {
            "AspAsp": "Asp50− / Asp397−",
            "AshAsp": "Asp50H / Asp397−",
            "AspAsh": "Asp50− / Asp397H",
            "AshAsh": "Asp50H / Asp397H",
        },
        "systems": {},
        "coupling_caveat": (
            "The two PROPKA pKa values are structure-based site estimates, not a joint microscopic pKa model. "
            "Protonating one member changes the electrostatics of the other, so independent Henderson–Hasselbalch "
            "fractions must not be multiplied and reported as dyad microstate populations."
        ),
    }
    for system, pka in predictions.items():
        site_class = {
            key: ("deprotonated" if value < 6.4 else "protonated" if value > 8.0 else "pH-sensitive")
            for key, value in pka.items()
        }
        dominant_at_reference = {
            key: ("protonated" if value >= 7.2 else "deprotonated")
            for key, value in pka.items()
        }
        target_protonation = {
            "AspAsp": {"Asp50": "deprotonated", "Asp397": "deprotonated"},
            "AshAsp": {"Asp50": "protonated", "Asp397": "deprotonated"},
            "AspAsh": {"Asp50": "deprotonated", "Asp397": "protonated"},
            "AshAsh": {"Asp50": "protonated", "Asp397": "protonated"},
        }
        assessed = {}
        for state, target in target_protonation.items():
            strong_mismatches = sum(
                site_class[site] in {"protonated", "deprotonated"} and site_class[site] != target[site]
                for site in target
            )
            pH_sensitive_sites = sum(site_class[site] == "pH-sensitive" for site in target)
            if all(target[site] == dominant_at_reference[site] for site in target):
                decision = "recommended"
            elif strong_mismatches == 0 or (strong_mismatches == 1 and pH_sensitive_sites == 1):
                decision = "sensitivity"
            else:
                decision = "low_priority"
            assessed[state] = {
                "decision": decision,
                "rationale": (
                    f"The isolated-site estimates classify Asp50 as {site_class['Asp50']} and Asp397 as "
                    f"{site_class['Asp397']} at pH 7.0–7.4; this state is a coupled-dyad hypothesis, "
                    "so retain it only at the stated priority and do not infer a joint population."
                ),
            }
        recommended = [state for state, item in assessed.items() if item["decision"] == "recommended"]
        if not recommended:
            recommended = ["AspAsp"]
            assessed["AspAsp"]["decision"] = "recommended"
        rationale = (
            f"At pH 7.0–7.4, the native PROPKA estimates classify Asp50 as {site_class['Asp50']} and Asp397 as "
            f"{site_class['Asp397']}. Prioritize the four-state choices marked recommended and use the marked "
            "sensitivity states to probe uncertainty, especially for sites near the physiological range. These "
            "isolated-site estimates are not microscopic dyad pKas and cannot be multiplied into joint populations."
        )
        plan["systems"][system] = {
            "predicted_pka": pka,
            "recommended_states": recommended,
            "assessed_states": assessed,
            "rationale": rationale,
        }
    return plan


def solve(assets: Path, output: Path) -> dict:
    assets = assets.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    evidence = output / "evidence"
    structures_dir = evidence / "structures"
    propka_dir = evidence / "propka"
    structures_dir.mkdir(parents=True, exist_ok=True)
    propka_dir.mkdir(parents=True, exist_ok=True)

    selection_manifest = prepare_structures(assets, structures_dir)
    propka_executable = shutil.which("propka3")
    if not propka_executable:
        raise RuntimeError("propka3 is unavailable; this is an environment error, not a scientific result")
    propka_version = subprocess.run(
        [propka_executable, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if propka_version != "propka3 " + importlib.metadata.version("propka"):
        raise RuntimeError(f"PROPKA executable/version metadata disagree: {propka_version}")

    predictions = {}
    provenance = {
        "schema_version": "case02-propka-provenance/v1",
        "case_id": CASE,
        "python": sys.version,
        "parmed_version": importlib.metadata.version("ParmEd"),
        "propka_version": propka_version,
        "propka_command_template": ["propka3", "--log-level", "INFO", "<chainA_site.pdb>"],
        "selection_manifest_sha256": sha256(structures_dir / "selection_manifest.json"),
        "systems": {},
    }

    for system in SYSTEMS:
        structure_name = f"{system}_chainA_site.pdb"
        structure_path = structures_dir / structure_name
        command = [propka_executable, "--log-level", "INFO", str(structure_path.resolve())]
        completed = subprocess.run(command, cwd=propka_dir, capture_output=True, text=True)
        stem = structure_path.stem
        (propka_dir / f"{stem}.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (propka_dir / f"{stem}.stderr.log").write_text(completed.stderr, encoding="utf-8")
        (propka_dir / f"{stem}.returncode.txt").write_text(f"{completed.returncode}\n", encoding="ascii")
        if completed.returncode != 0:
            raise RuntimeError(f"PROPKA failed for {system} with exit code {completed.returncode}: {completed.stderr[-1000:]}")
        pka_path = propka_dir / f"{stem}.pka"
        if pka_path.is_symlink() or not pka_path.is_file() or pka_path.stat().st_size == 0:
            raise RuntimeError(f"PROPKA exited successfully but did not create {pka_path.name}")
        predictions[system] = parse_pka(pka_path, system)
        row = selection_manifest["systems"][system]
        provenance["systems"][system] = {
            "command": command,
            "returncode": completed.returncode,
            "pdb": {"path": f"evidence/structures/{structure_name}", "sha256": sha256(structure_path)},
            "pka_output": {"path": f"evidence/propka/{pka_path.name}", "sha256": sha256(pka_path)},
            "parsed_pka": predictions[system],
            "source_topology_sha256": row["input_topology"]["sha256"],
            "source_coordinates_sha256": row["input_coordinates"]["sha256"],
        }

    # Copy the exact analysis source into the evidence bundle for independent review.
    script_root = Path(__file__).resolve().parent
    for source_name in ("solve.py", "prepare_structures.py"):
        shutil.copyfile(script_root / source_name, evidence / source_name)
    (evidence / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    pka_document = {
        "schema_version": "case02-pka/v1",
        "method": {
            "name": "PROPKA",
            "version": propka_version,
            "model": "empirical structure-based pKa prediction",
            "requested_ph_for_stability_context": 7.2,
            "uncertainty": "PROPKA does not provide calibrated per-residue confidence intervals; absolute estimates are approximate, especially for ATP/metal-containing structures.",
            "ligand_metal_treatment": "The first subunit PDB retains its local ATP, Mg and K atoms; PROPKA's built-in ligand treatment was used without custom parameters or charge redistribution.",
        },
        "physiological_ph_range": [7.0, 7.4],
        "systems": {},
    }
    for system, values in predictions.items():
        structure_record = provenance["systems"][system]["pdb"]
        pka_document["systems"][system] = {
            "Asp50": {
                "mature_residue": 50,
                "system_residue": TARGET_RESIDUES[system]["Asp50"],
                "pka": values["Asp50"],
            },
            "Asp397": {
                "mature_residue": 397,
                "system_residue": TARGET_RESIDUES[system]["Asp397"],
                "pka": values["Asp397"],
            },
            "input_structure_sha256": structure_record["sha256"],
            "source_topology_sha256": provenance["systems"][system]["source_topology_sha256"],
            "source_coordinates_sha256": provenance["systems"][system]["source_coordinates_sha256"],
            "evidence": provenance["systems"][system]["pka_output"]["path"],
        }
    (output / "pka.json").write_text(json.dumps(pka_document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "protonation_plan.json").write_text(
        json.dumps(build_plan(predictions), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "report.md").write_text(make_report(predictions, selection_manifest, propka_version), encoding="utf-8")
    print(json.dumps({"systems": predictions, "propka_version": propka_version}, sort_keys=True))
    return predictions


def make_report(predictions: dict[str, dict[str, float]], selection_manifest: dict, version: str) -> str:
    lines = [
        "# Asp50/Asp397 protonation estimate",
        "",
        f"Method: native PROPKA {version} on the first Hsp60 monomer extracted from the supplied Amber topology and restart coordinates.",
        "The PDB files, selection manifest, raw `.pka` outputs, exact commands and logs are included under `evidence/`.",
        "",
        "## Predicted pKa values",
        "",
        "| System | Asp50 | Asp397 | Mature numbering |",
        "|---|---:|---:|---|",
    ]
    for system, values in predictions.items():
        number_note = "51 / 398 in the supplied system" if system == "S_V72I" else "50 / 397 in the supplied system"
        lines.append(f"| {system} | {values['Asp50']:.2f} | {values['Asp397']:.2f} | {number_note} |")
    lines.extend([
        "",
        "## Structural selection and interpretation",
        "",
        "Each input topology has no chain identifiers, so residue and atom order were used to identify its first repeated Hsp60 subunit as chain A. The S topology numbers this dyad one residue above mature numbering; D and F use the mature numbering directly. The chain A model retains the complete 526-residue protein. ATP, Mg and K were retained when their atoms fell within the recorded spatial cutoff of the dyad; bulk water and distant ring cofactors were excluded.",
        "",
        f"The predictor used physiological pH 7.0–7.4 as the interpretation range and pH 7.2 as its stability-context setting. PROPKA does not return per-site confidence intervals. Its values are empirical estimates, and uncertainty is greater for ligand and metal environments because no custom ligand parameters were supplied.",
        "",
        "The selected native model gives both apo S estimates below the physiological range. In D, Asp50 is predicted to be strongly shifted upward while Asp397 lies near the lower edge of the physiological range. In F, Asp397 is predicted to be strongly shifted upward while Asp50 remains below the range. These are the results of this extracted static structure and PROPKA setup; the pocket, ATP, Mg²⁺ and K⁺ environment can influence electrostatics, but this comparison does not isolate a single causal contribution.",
        "The plan assesses all four dyad states in every system. For D and F, compare the doubly deprotonated baseline with separate Asp50-protonated and Asp397-protonated models; prioritize the alternatives using the actual site estimates and retain states near pH 7.0–7.4 as sensitivity conditions. The independently predicted site pKas do not define joint microscopic dyad-state populations: protonating one carboxylate changes the electrostatics of the other.",
        "The four states are AspAsp (Asp50−/Asp397−), AshAsp (Asp50H/Asp397−), AspAsh (Asp50−/Asp397H), and AshAsh (Asp50H/Asp397H). The plan gives each a system-specific simulation priority.",
        "",
        "The paper's illustrative PROPKA values (S 3.18/4.91, D 8.22/12.52, F 7.13/11.13) are not imposed as constants. The native-input run gives S 3.12/4.91, D 13.16/6.51, and F 3.70/11.97 (Asp50/Asp397). The different D/F pattern makes the structure selection, ligand treatment, and predictor setup material to the interpretation; absolute estimates remain approximate.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    solve(args.assets, args.output)


if __name__ == "__main__":
    main()
TASK_SOURCE_SOLVE_PY
cat > "$work_dir/prepare_structures.py" <<'TASK_SOURCE_PREPARE_STRUCTURES_PY'
#!/usr/bin/env python3
"""Extract the first Hsp60 subunit and its active-site cofactors with ParmEd."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
from pathlib import Path

import parmed as pmd


SYSTEMS = {
    "S_V72I": ("S_V72I", 526, 397, 50),
    "D_V72I": ("D_V72I_ASPASP", 526, 397, 50),
    "F_V72I": ("F_V72I_ASPASP", 526, 397, 50),
}
PROTEIN = {
    "ALA", "ARG", "ASN", "ASP", "ASH", "CYS", "GLN", "GLU", "GLH", "GLY",
    "HIS", "HID", "HIE", "HIP", "ILE", "LEU", "LYS", "MET", "PHE", "PRO",
    "SER", "THR", "TRP", "TYR", "VAL",
}
COFACTORS = {"atp", "mg", "k+", "k"}
COFACTOR_RADIUS_ANGSTROM = 12.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def pdb_atom(serial: int, atom, chain: str) -> str:
    residue = atom.residue
    name = atom.name.strip()
    resname = residue.name.upper()[:3]
    element = atom.element_name.strip().upper()[:2]
    record = "ATOM  " if residue.name.upper() in PROTEIN else "HETATM"
    atomname = (" " + name).ljust(4)[:4] if len(name) < 4 else name[:4]
    x, y, z = (float(c) for c in (atom.xx, atom.xy, atom.xz))
    return (
        f"{record}{serial:5d} {atomname}{' ':1}{resname:>3s} {chain}"
        f"{residue.idx + 1:4d}{' ':1}   {x:8.3f}{y:8.3f}{z:8.3f}"
        f"{1.0:6.2f}{0.0:6.2f}          {element:>2s}  \n"
    )


def run(source: Path, destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "case02-propka-inputs/v1",
        "extractor": "ParmEd",
        "parmed_version": pmd.__version__,
        "systems": {},
    }
    for label, (stem, first_chain_residues, asp397_mature, asp50_mature) in SYSTEMS.items():
        topology, coordinates = source / f"{stem}.top", source / f"{stem}.rst"
        print(f"Loading {label} topology and coordinates with ParmEd", flush=True)
        structure = pmd.load_file(str(topology), xyz=str(coordinates))
        if structure.coordinates is None or len(structure.coordinates) != len(structure.atoms):
            raise ValueError(f"{label}: topology/coordinate atom counts differ")
        selected = [False] * len(structure.atoms)
        selected_residues = set()
        for atom in structure.atoms:
            residue_index = atom.residue.idx
            if residue_index < first_chain_residues and atom.residue.name.upper() in PROTEIN:
                selected[atom.idx] = True
                selected_residues.add(residue_index)

        # The topology records each chain as an independent repeated sequence.
        # Check both target residue names and their expected system numbering.
        offset = 1 if label == "S_V72I" else 0
        targets = {}
        dyad_anchor_coordinates = []
        for mature in (asp50_mature, asp397_mature):
            system_number = mature + offset
            residue = structure.residues[system_number - 1]
            if residue.name.upper() != "ASP":
                raise ValueError(
                    f"{label}: system residue {system_number} is {residue.name}, expected ASP"
                )
            atom_names = {atom.name.strip(): atom for atom in residue.atoms}
            required = {"CG", "OD1", "OD2"}
            if not required.issubset(atom_names):
                raise ValueError(f"{label} Asp{mature}: missing {sorted(required - atom_names.keys())}")
            cg = atom_names["CG"]
            dyad_anchor_coordinates.extend(
                [float(atom_names[name].xx), float(atom_names[name].xy), float(atom_names[name].xz)]
                for name in ("CG", "OD1", "OD2")
            )
            targets[str(mature)] = {
                "system_residue_number": system_number,
                "topology_residue_index_1based": residue.idx + 1,
                "residue_name": residue.name,
                "atoms": {
                    name: {
                        "topology_atom_index_1based": atom_names[name].idx + 1,
                        "coordinate_angstrom": [float(atom_names[name].xx), float(atom_names[name].xy), float(atom_names[name].xz)],
                        "bonds": sorted(partner.name.strip() for partner in atom_names[name].bond_partners),
                    }
                    for name in sorted(required)
                },
                "cg_coordinate_angstrom": [float(cg.xx), float(cg.xy), float(cg.xz)],
            }

        cofactor_records = []
        for residue in structure.residues:
            if residue.name.lower() not in COFACTORS:
                continue
            distances = [
                math.dist(
                    (float(atom.xx), float(atom.xy), float(atom.xz)), anchor
                )
                for atom in residue.atoms
                for anchor in dyad_anchor_coordinates
            ]
            nearest = min(distances)
            include = nearest <= COFACTOR_RADIUS_ANGSTROM
            if include:
                for atom in residue.atoms:
                    selected[atom.idx] = True
                selected_residues.add(residue.idx)
            cofactor_records.append({
                "topology_residue_number": residue.idx + 1,
                "name": residue.name,
                "nearest_dyad_distance_angstrom": round(nearest, 4),
                "included": include,
            })

        output = destination / f"{label}_chainA_site.pdb"
        with output.open("w") as stream:
            stream.write(f"REMARK Generated from {stem}.top and {stem}.rst using ParmEd {pmd.__version__}\n")
            stream.write(f"REMARK First Hsp60 subunit: topology residues 1-{first_chain_residues}\n")
            stream.write(f"REMARK Cofactors retained when any atom is within {COFACTOR_RADIUS_ANGSTROM:.1f} A of dyad CG/OD1/OD2 atoms\n")
            for atom in structure.atoms:
                if selected[atom.idx]:
                    stream.write(pdb_atom(atom.idx + 1, atom, "A"))
            stream.write("TER\nEND\n")

        selected_protein_residues = {
            r.idx for r in structure.residues
            if r.idx < first_chain_residues and r.name.upper() in PROTEIN
        }
        if len(selected_protein_residues) != first_chain_residues:
            raise ValueError(f"{label}: selected {len(selected_protein_residues)} protein residues, expected {first_chain_residues}")
        expected_cofactors = {r["name"].lower() for r in cofactor_records if r["included"]}
        required_cofactors = {
            "S_V72I": set(),
            "D_V72I": {"atp", "mg", "k+"},
            "F_V72I": {"atp", "mg", "k"},
        }[label]
        missing = required_cofactors - expected_cofactors
        if missing:
            raise ValueError(f"{label}: active-site cofactors outside selection radius or missing: {sorted(missing)}")
        manifest["systems"][label] = {
            "input_topology": {"path": str(topology), "sha256": sha256(topology)},
            "input_coordinates": {"path": str(coordinates), "sha256": sha256(coordinates)},
            "selection": {
                "protein_residue_count": first_chain_residues,
                "protein_topology_residues_1based": f"1-{first_chain_residues}",
                "topology_to_chain_map": "Amber topologies have blank chain IDs; first repeated Hsp60 sequence is chain A",
                "pdb_chain": "A",
                "ligand_policy": "retain ATP/Mg/K residues with any atom within the recorded radius of Asp50/Asp397 CG/OD1/OD2; no bulk solvent or distant ions",
                "cofactor_radius_angstrom": COFACTOR_RADIUS_ANGSTROM,
                "protein_atom_count": sum(1 for a in structure.atoms if selected[a.idx] and a.residue.name.upper() in PROTEIN),
                "retained_atom_count": sum(selected),
                "cofactor_residues": cofactor_records,
            },
            "target_residues": targets,
            "structure": {"path": output.name, "sha256": sha256(output)},
        }
        print(f"Exported {label}: {sum(selected)} atoms to {output}", flush=True)
        del structure
        # ParmEd atoms retain graph references to their bond partners. Break these
        # cyclic graphs before loading the next full-ring topology in the small
        # task container.
        gc.collect()
    manifest_path = destination / "selection_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.source, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
TASK_SOURCE_PREPARE_STRUCTURES_PY

python3 "$work_dir/solve.py" --assets /app/assets --output /app/final "$@"
