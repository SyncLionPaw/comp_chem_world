#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP:-/app}"
INPUT_ROOT="$APP_ROOT/inputs/databases"
if [[ ! -d "$INPUT_ROOT" ]]; then
  echo "public input directory not found: $INPUT_ROOT" >&2
  exit 2
fi

python3 - --input-root "$INPUT_ROOT" --output-root "$APP_ROOT" <<'CASE01_SOLVE'
"""Independent, public-data-derived baseline for the complete case-01 contract."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from ase.db import connect

HA_EV = 27.211386245988
CASES = (
    ("C2H4", "01_3Sing_C2H4.db"),
    ("C3H6", "02_3Sing_C3H6.db"),
    ("C4H8", "03_3Sing_C4H8.db"),
)
COUPLINGS = (("S1/S0", 0, 1), ("S2/S0", 0, 2), ("S2/S1", 1, 2))


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def describe(values: list[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    return {"mean": float(arr.mean()), "std": float(arr.std()),
            "min": float(arr.min()), "max": float(arr.max())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_root / "outputs"
    out.mkdir(parents=True, exist_ok=True)

    audit_rows: list[list[object]] = []
    property_rows: list[list[object]] = []
    smooth_rows: list[list[object]] = []
    molecule_summary = {}
    schema_summary = {}
    for molecule, filename in CASES:
        entries = list(connect(args.input_root / filename).select())
        records = [(row, dict(row.data)) for row in entries]
        energies = [np.asarray(data["energy"], dtype=float).reshape(3) for _, data in records]
        forces = [np.asarray(data["forces"], dtype=float) for _, data in records]
        nacs = [np.asarray(data["nacs"], dtype=float) for _, data in records]
        smooth = [np.asarray(data["smooth_nacs"], dtype=float) for _, data in records]
        global_s0_min = min(float(e[0]) for e in energies)
        n_atoms = sorted({row.natoms for row, _ in records})
        confs = sorted({str(data["conf"]) for _, data in records if data.get("conf") is not None})
        keys = sorted({key for _, data in records for key in data})
        path_yes = sum(data.get("path") == "yes" for _, data in records)
        audit_rows.append([
            molecule, len(records), ";".join(map(str, n_atoms)), 3, 3, "bohr", "hartree",
            ";".join(confs), path_yes, ";".join(keys),
        ])

        rel_by_state = [[] for _ in range(3)]
        force_by_state = [[] for _ in range(3)]
        nac_by_pair = [[] for _ in range(3)]
        smooth_deviation = [0.0] * 3
        smooth_scale = [0.0] * 3
        for e, f, n, sm in zip(energies, forces, nacs, smooth):
            for state in range(3):
                rel_by_state[state].append(float(e[state] - global_s0_min) * HA_EV)
                force_by_state[state].append(float(np.linalg.norm(f[:, state, :])))
            for index, (coupling, low, high) in enumerate(COUPLINGS):
                nac_by_pair[index].append(float(np.linalg.norm(n[:, index, :])))
                expected = n[:, index, :] * float(e[low] - e[high])
                smooth_deviation[index] = max(
                    smooth_deviation[index], float(np.max(np.abs(sm[:, index, :] - expected))))
                smooth_scale[index] = max(smooth_scale[index], float(np.max(np.abs(sm[:, index, :])))
                                          if sm[:, index, :].size else 0.0)

        for state, name in enumerate(("S0", "S1", "S2")):
            for prop, unit, values in (
                ("energy", "eV", rel_by_state[state]),
                ("force_norm", "Hartree/Bohr", force_by_state[state]),
            ):
                stats = describe(values)
                property_rows.append([molecule, prop, name, unit, stats["mean"], stats["std"], stats["min"], stats["max"]])
        for index, (coupling, _, _) in enumerate(COUPLINGS):
            stats = describe(nac_by_pair[index])
            property_rows.append([molecule, "nac_norm", coupling, "1/Bohr",
                                  stats["mean"], stats["std"], stats["min"], stats["max"]])
            relative = smooth_deviation[index] / max(smooth_scale[index], 1e-12)
            smooth_rows.append([molecule, coupling, sum(sm[:, index, :].size for sm in smooth),
                                smooth_deviation[index], relative, relative <= 1e-8])

        first_row = entries[0]
        molecule_summary[molecule] = {
            "structures": len(entries), "atom_count": n_atoms,
            "conformer_count": len(confs), "conf_labels": confs,
            "s0_energy_min_hartree": global_s0_min,
        }
        schema_summary[molecule] = {
            "energy": {"stored_shape": list(np.asarray(first_row.data["energy"]).shape),
                       "normalized_shape": list(np.asarray(first_row.data["energy"]).reshape(3).shape),
                       "axes": ["record", "state"], "normalized_axes": ["state"],
                       "state_order": ["S0", "S1", "S2"], "unit": "hartree"},
            "forces": {"shape": list(np.asarray(first_row.data["forces"]).shape),
                       "axes": ["atom", "state", "xyz"], "unit": "hartree/bohr"},
            "dipoles": {"stored_shape": list(np.asarray(first_row.data["dipoles"]).shape),
                        "axes": ["dipole_vector", "xyz"],
                       "known_transition_anchor": {"stored_row_index": 3, "meaning": "mu_10"},
                       "unresolved_row_mapping": True,
                        "meaning": "The SI prose describes three permanent dipole vectors (mu_0, mu_1, mu_2) and three transition dipole vectors (mu_10, mu_20, mu_21), Supplementary Information p. 8. The public case-02 contract anchors stored row index 3 (one-based row 4) as mu_10. The remaining exact row map is not inferred from shape alone.",
                        "source_note": "The same SI p. 8 Table S2 includes an Nstates+1 slice expression that would imply 4 permanent plus 2 transition vectors for Nstates=3, conflicting with the prose and six-vector table shape. This apparent printed/indexing ambiguity is disclosed rather than resolved by assumption."},
            "nacs": {"shape": list(np.asarray(first_row.data["nacs"]).shape),
                     "axes": ["atom", "coupling", "xyz"], "unit": "1/bohr",
                     "coupling_axis_order": [name for name, _, _ in COUPLINGS]},
            "smooth_nacs": {"shape": list(np.asarray(first_row.data["smooth_nacs"]).shape),
                            "axes": ["atom", "coupling", "xyz"], "unit": "hartree/bohr"},
        }

    write_csv(out / "database_audit.csv",
              ["molecule", "n_structures", "n_atoms", "n_states", "n_couplings", "coordinate_unit",
               "energy_unit", "conf_labels", "path_yes_count", "data_keys"], audit_rows)
    write_csv(out / "property_stats.csv",
              ["molecule", "property", "state_or_coupling", "unit", "mean", "std", "min", "max"], property_rows)
    write_csv(out / "smooth_nacs_check.csv",
              ["molecule", "coupling", "n_points", "max_abs_deviation", "relative_max_deviation", "consistent"],
              smooth_rows)
    (out / "summary.json").write_text(json.dumps({
        "schema": "case01/scientific-summary/v2",
        "units": {
            "positions": {"value": "bohr", "evidence": "The public geometry's C-C and near-bond C-H distance scales are molecular when interpreted as Bohr; science-evidence.json reports ranges in Bohr and converted Angstrom."},
            "energy": {"value": "hartree", "evidence": "state energies have atomic-unit scale; differences convert to eV using 27.211386245988 eV/Hartree."},
            "forces": {"value": "hartree/bohr", "evidence": "gradient units follow energy divided by the stored coordinate unit."},
            "nacs": {"value": "1/bohr", "evidence": "smooth_nacs equals NAC times the corresponding state-energy difference."},
        },
        "data_schema": schema_summary,
        "molecules": molecule_summary,
        "smooth_nacs_convention": "For each coupling axis, smooth_nacs[:,c,:] = nacs[:,c,:] * (E_low - E_high); the three-axis order is S1/S0, S2/S0, S2/S1.",
        "coupling_axis_evidence": "The smooth-NAC identity is checked elementwise for all public rows and axes against all three energy-state pairs; see science-evidence.json for the full residual matrix. This supports coupling-axis assignment, while dipole row semantics need the dataset/SI convention.",
        "caveats": ["Dipole composition follows the SI p. 8 prose (three permanent plus three transition vectors); Table S2's Nstates+1 slice expression is inconsistent for Nstates=3. Only row index 3 = mu_10 is anchored by the public case-02 output contract; do not infer the remaining row map from numerical shape alone."],
        "baseline_provenance": "Independent public-data-derived integration baseline; not an author-provided Gold.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
CASE01_SOLVE
python3 - --input-root "$INPUT_ROOT" --output-root "$APP_ROOT" <<'CASE01_EVIDENCE'
"""Optional full-public-database shape, unit-scale and smooth-NAC evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from ase.db import connect

HA_EV = 27.211386245988
BOHR_ANGSTROM = 0.529177210903
CASES = (("C2H4", "01_3Sing_C2H4.db"), ("C3H6", "02_3Sing_C3H6.db"),
         ("C4H8", "03_3Sing_C4H8.db"))
PAIRS = ((0, 1), (0, 2), (1, 2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    evidence = {}
    for molecule, filename in CASES:
        rows = list(connect(args.input_root / filename).select())
        shape_sets = {key: set() for key in ("positions", "energy", "forces", "dipoles", "nacs", "smooth_nacs")}
        energy_normalized_shapes = set()
        pair_residuals = np.zeros((3, 3), dtype=float)
        cc, ch = [], []
        energies = []
        finite_ok = True
        for row in rows:
            data = dict(row.data)
            arrays = {key: np.asarray(data[key], dtype=float) for key in shape_sets if key != "positions"}
            arrays["positions"] = np.asarray(row.positions, dtype=float)
            for key, arr in arrays.items():
                shape_sets[key].add(json.dumps(list(arr.shape)))
                finite_ok = finite_ok and bool(np.isfinite(arr).all())
            energy = arrays["energy"].reshape(3)
            energy_normalized_shapes.add(json.dumps(list(energy.shape)))
            energies.append(energy)
            nacs, smooth = arrays["nacs"], arrays["smooth_nacs"]
            for coupling in range(3):
                for pair_idx, (lo, hi) in enumerate(PAIRS):
                    pair_residuals[coupling, pair_idx] = max(
                        pair_residuals[coupling, pair_idx],
                        float(np.max(np.abs(smooth[:, coupling, :] - nacs[:, coupling, :] * (energy[lo] - energy[hi])))))
            positions = np.asarray(row.positions, dtype=float)
            numbers = np.asarray(row.numbers)
            carbon, hydrogen = np.where(numbers == 6)[0], np.where(numbers == 1)[0]
            if len(carbon) >= 2:
                cc.append(float(np.linalg.norm(positions[carbon[1]] - positions[carbon[0]])))
            for c in carbon:
                for h in hydrogen:
                    distance = float(np.linalg.norm(positions[c] - positions[h]))
                    if distance < 2.6:
                        ch.append(distance)
        energy_arr = np.asarray(energies)
        evidence[molecule] = {
            "row_count": len(rows),
            "all_required_values_finite": finite_ok,
            "shape_sets": {key: [json.loads(shape) for shape in sorted(values)] for key, values in shape_sets.items()},
            "required_shapes_constant": all(len(values) == 1 for values in shape_sets.values()),
            "energy_layout": {
                "stored_shape_set": [json.loads(shape) for shape in sorted(shape_sets["energy"])],
                "normalized_shape_set": [json.loads(shape) for shape in sorted(energy_normalized_shapes)],
                "normalization": "The public database stores each three-state energy vector with a leading singleton dimension; analysis reshapes it to one axis of three states [S0,S1,S2].",
            },
            "physical_scale_checks": {
                "C_C_bond_distance_bohr_range": [min(cc), max(cc)],
                "C_C_bond_distance_angstrom_range": [min(cc) * BOHR_ANGSTROM, max(cc) * BOHR_ANGSTROM],
                "near_bond_C_H_distance_bohr_range": [min(ch), max(ch)],
                "energy_state_ranges_hartree": [[float(energy_arr[:, s].min()), float(energy_arr[:, s].max())]
                                                  for s in range(3)],
                "energy_state_ranges_eV_after_conversion": [[float(energy_arr[:, s].min() * HA_EV),
                                                              float(energy_arr[:, s].max() * HA_EV)] for s in range(3)],
            },
            "smooth_nac_energy_pair_residual_max_hartree_per_bohr": {
                f"axis_{axis}": {f"E{lo}-E{hi}": float(pair_residuals[axis, i])
                                 for i, (lo, hi) in enumerate(PAIRS)} for axis in range(3)
            },
            "coupling_axis_inference": {
                "lowest_residual_pair_by_axis": [f"E{lo}-E{hi}" for axis in range(3)
                                                  for lo, hi in [PAIRS[int(np.argmin(pair_residuals[axis]))]]],
                "limitation": "The smooth-NAC identity supports the state-pair association. It does not by itself establish the meaning or ordering of dipole rows; interpret dipoles using the cited dataset/SI convention and state it explicitly in the scientific narrative.",
            },
            "dipoles": {
                "shape_set": [json.loads(shape) for shape in sorted(shape_sets["dipoles"])],
                "literature_composition": "Three permanent vectors (mu_0, mu_1, mu_2) plus three transition vectors (mu_10, mu_20, mu_21), from docs/SC-015-D4SC04164J-s001.pdf p. 8 prose.",
                "public_contract_anchor": "Stored row index 3 (one-based row 4) is mu_10, as used by the public case-02 oscillator-strength contract.",
                "unresolved_printed_indexing_ambiguity": "SI Table S2's Nstates+1 slice expression would imply 4 permanent plus 2 transition vectors when Nstates=3, inconsistent with its six-vector shape and p. 8 prose. The ambiguity is disclosed; no unsupported mapping is assigned to the remaining stored indices.",
            },
        }
    target = args.output_root / "outputs" / "science-evidence.json"
    target.write_text(json.dumps({"source": "all public bundled ASE rows; no sealed data", "molecules": evidence},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path = args.output_root / "outputs" / "summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["optional_public_science_evidence"] = "science-evidence.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
CASE01_EVIDENCE
