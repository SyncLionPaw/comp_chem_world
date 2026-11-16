#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Audit the XAlkeneDB reference database, electronic-state conventions, and training inputs.
"""Case-01 layered verifier: XAlkeneDB audit.

Exit codes: 0 PASS, 1 candidate FAIL, 2 evaluator ENV_ERROR.
All references are recomputed from the public databases bundled with the package.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

try:
    import numpy as np
    from ase.db import connect
except ImportError as exc:  # evaluator setup failure, never a candidate error
    print(f"ENV_ERROR: required dependency unavailable: {exc}", file=sys.stderr)
    raise SystemExit(2)

REFERENCES: dict | None = None
PINNED_REFERENCE_POLICY_SHA256 = "b2b8e763a5c2fa1b2ac5f90fad1b579bb177a8f7289f6e35c8db6aa17bf01942"


def load_references(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != PINNED_REFERENCE_POLICY_SHA256:
        raise ValueError("refs.json canonical policy digest differs from the reviewed case-01 policy")
    if not isinstance(value, dict) or value.get("schema") != "bench25-case01-reference-policy/v1":
        raise ValueError("unsupported refs.json schema")
    units, tolerances = value.get("unit_conversions"), value.get("tolerances")
    if not isinstance(units, dict) or not isinstance(tolerances, dict):
        raise ValueError("refs.json must contain unit_conversions and tolerances objects")
    if set(units) != {"hartree_to_ev"} or set(tolerances) != {"smooth_abs_floor", "smooth_abs_relative", "smooth_relative_report", "smooth_relative_limit", "relative_statistic", "relative_scale_floor"}:
        raise ValueError("refs.json fields do not match the case-01 policy schema")
    for section in (units, tolerances):
        if any(not isinstance(x, (int, float)) or isinstance(x, bool) or not np.isfinite(x) or x < 0 for x in section.values()):
            raise ValueError("refs.json policy values must be finite nonnegative numbers")
    return value
COUPLINGS = ("S1/S0", "S2/S0", "S2/S1")  # coupling axis order, verified via smooth_nacs identity
GAP_INDEX = {0: (0, 1), 1: (0, 2), 2: (1, 2)}
REQUIRED_KEYS = {"energy", "forces", "dipoles", "nacs", "smooth_nacs"}


class CandidateFail(Exception):
    pass


def read_csv_rows(path: Path, expected_header: list[str]) -> list[dict]:
    if not path.is_file():
        raise CandidateFail(f"missing outputs file: {path.name}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise CandidateFail(f"{path.name} is empty")
        if [h.strip() for h in header] != expected_header:
            raise CandidateFail(f"{path.name} header mismatch: {header} != {expected_header}")
        rows = []
        for line_no, row in enumerate(reader, start=2):
            if not row:
                continue
            if len(row) != len(expected_header):
                raise CandidateFail(
                    f"{path.name} row {line_no} has {len(row)} fields; expected {len(expected_header)}")
            rows.append(dict(zip(expected_header, row)))
        return rows


def finite(value: float) -> float:
    if not np.isfinite(value):
        raise CandidateFail(f"non-finite value encountered: {value}")
    return value


def validate_finite_stat_rows(rows: list[dict]) -> None:
    for index, row in enumerate(rows, start=1):
        for field in ("mean", "std", "min", "max"):
            try:
                finite(float(row[field]))
            except (ValueError, TypeError, OverflowError, KeyError) as exc:
                raise CandidateFail(f"property_stats row {index} {field} must be a finite number: {exc}")


UNIT_ALIASES = {
    "positions": {"bohr": "bohr", "a0": "bohr", "atomicunitoflength": "bohr", "atomicunits(bohr)": "bohr"},
    "energy": {"hartree": "hartree", "ha": "hartree", "eh": "hartree", "atomicunitofenergy": "hartree"},
    "forces": {"hartree/bohr": "hartree/bohr", "hartree/a0": "hartree/bohr", "ha/bohr": "hartree/bohr",
                "ha/a0": "hartree/bohr", "eh/bohr": "hartree/bohr", "eh/a0": "hartree/bohr"},
    "nacs": {"1/bohr": "1/bohr", "bohr^-1": "1/bohr", "bohr-1": "1/bohr", "1/a0": "1/bohr",
             "a0^-1": "1/bohr", "a0-1": "1/bohr"},
    "smooth_nacs": {"hartree/bohr": "hartree/bohr", "hartree/a0": "hartree/bohr", "ha/bohr": "hartree/bohr",
                     "ha/a0": "hartree/bohr", "eh/bohr": "hartree/bohr", "eh/a0": "hartree/bohr"},
}


def reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CandidateFail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def normalize_unit(value: object, dimension: str, path: str) -> str:
    aliases = UNIT_ALIASES[dimension]

    def one(raw: object) -> str:
        if not isinstance(raw, str):
            raise CandidateFail(f"{path} unit must be a string")
        token = raw.strip().lower().replace(" ", "").replace("_", "").replace("−", "-")
        if token not in aliases:
            raise CandidateFail(f"{path} has unsupported {dimension} unit {raw!r}")
        return aliases[token]

    if isinstance(value, dict):
        declared = [one(value[key]) for key in ("value", "unit") if key in value]
        if not declared:
            raise CandidateFail(f"{path} unit object must contain 'value' or 'unit'")
        if len(set(declared)) != 1:
            raise CandidateFail(f"{path} unit aliases conflict")
        return declared[0]
    return one(value)


def required_rows_by_key(rows: list[dict], required: list[tuple], key_fields: tuple[str, ...], label: str) -> dict:
    required_set = set(required)
    indexed = {}
    for row in rows:
        key = tuple(row[field] for field in key_fields)
        if key in required_set and key in indexed:
            raise CandidateFail(f"{label} duplicates required identity {key}")
        indexed[key] = row
    missing = [key for key in required if key not in indexed]
    if missing:
        raise CandidateFail(f"{label} missing required rows: {missing[:5]}")
    return indexed


def validate_audit_order(rows: list[dict], expected_molecules: list[str]) -> None:
    actual = [row["molecule"] for row in rows]
    if actual != expected_molecules:
        raise CandidateFail(f"database_audit must contain one row per molecule in file-name order: {actual}")


def json_int(value: object, path: str) -> int:
    if isinstance(value, bool):
        raise CandidateFail(f"{path} must not be a boolean")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CandidateFail(f"{path} must be an integer") from exc
    if isinstance(value, float) and value != result:
        raise CandidateFail(f"{path} must be an integer")
    return result


def json_string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise CandidateFail(f"{path} must be a string")
    return value


def validate_json_shape(value: object, expected: list[int], path: str) -> None:
    if not isinstance(value, list) or any(type(part) is not int for part in value) or value != expected:
        raise CandidateFail(f"{path} must be integer shape {expected}")


def validate_json_axes(value: object, expected: list[str], path: str) -> None:
    if not isinstance(value, list) or any(not isinstance(part, str) for part in value) or value != expected:
        raise CandidateFail(f"{path} must be {expected}")


def validate_smooth_rows(srows: list[dict], truth: dict) -> None:
    smap = {(r["molecule"], r["coupling"]): r for r in srows}
    if len(smap) != len(srows) or set(smap) != {(mol, c) for mol in truth for c in COUPLINGS}:
        raise CandidateFail("smooth_nacs_check must contain each molecule/coupling pair exactly once")
    for mol in truth:
        for c, coupling in enumerate(COUPLINGS):
            key = (mol, coupling)
            row = smap[key]
            if int(row["n_points"]) != truth[mol]["smooth_n_points"][c]:
                raise CandidateFail(f"{key}: n_points {row['n_points']} != {truth[mol]['smooth_n_points'][c]}")
            expected_abs = truth[mol]["smooth_dev"][c]
            actual_abs = finite(float(row["max_abs_deviation"]))
            if abs(actual_abs - expected_abs) > max(REFERENCES["tolerances"]["smooth_abs_floor"], expected_abs * REFERENCES["tolerances"]["smooth_abs_relative"]):
                raise CandidateFail(f"{key}: max_abs_deviation {actual_abs} != {expected_abs:.12g}")
            rel_dev = truth[mol]["smooth_dev"][c] / max(truth[mol]["smooth_scale"][c], REFERENCES["tolerances"]["relative_scale_floor"])
            if abs(finite(float(row["relative_max_deviation"])) - rel_dev) > REFERENCES["tolerances"]["smooth_relative_report"]:
                raise CandidateFail(f"{key}: relative_max_deviation {row['relative_max_deviation']} != {rel_dev:.3g}")
            if rel_dev > REFERENCES["tolerances"]["smooth_relative_limit"]:
                raise CandidateFail(f"{key}: smooth NAC identity violated (rel dev {rel_dev:.3g})")
            if row["consistent"].strip().lower() != "true":
                raise CandidateFail(f"{key}: consistent must be true")


def recompute_truth(inputs_dir: Path) -> dict:
    """Recompute all reference quantities from the bundled public databases."""
    truth = {}
    expected_rows = {"C2H4": 5999, "C3H6": 6000, "C4H8": 13000}
    for molecule, fname in (("C2H4", "01_3Sing_C2H4.db"), ("C3H6", "02_3Sing_C3H6.db"), ("C4H8", "03_3Sing_C4H8.db")):
        database_path = inputs_dir / fname
        if not database_path.is_file():
            raise RuntimeError(f"public database is missing: {database_path}")
        db = connect(database_path)
        rows = list(db.select())
        if len(rows) != expected_rows[molecule]:
            raise RuntimeError(f"{fname}: expected {expected_rows[molecule]} public rows, found {len(rows)}")
        confs, path_yes = set(), 0
        keys = set()
        natoms_seen = set()
        energies = []
        fnorm = {s: [] for s in range(3)}
        nnorm = {c: [] for c in range(3)}
        smooth_dev = {c: 0.0 for c in range(3)}
        smooth_scale = {c: 0.0 for c in range(3)}
        stored_shapes = {}
        cc_min = None
        for row in rows:
            data = dict(row.data)
            keys.update(data.keys())
            natoms_seen.add(row.natoms)
            confs.add(data.get("conf"))
            if data.get("path") == "yes":
                path_yes += 1
            pos = np.asarray(row.positions, dtype=float)
            energy = np.asarray(data["energy"], dtype=float).reshape(-1)
            if energy.shape != (3,):
                raise RuntimeError(f"unexpected energy shape in {fname}")
            raw_energy = np.asarray(data["energy"])
            forces = np.asarray(data["forces"], dtype=float)
            nacs = np.asarray(data["nacs"], dtype=float)
            smooth = np.asarray(data["smooth_nacs"], dtype=float)
            dipoles = np.asarray(data["dipoles"], dtype=float)
            shapes = {"energy": tuple(raw_energy.shape), "forces": tuple(forces.shape),
                      "nacs": tuple(nacs.shape), "smooth_nacs": tuple(smooth.shape),
                      "dipoles": tuple(dipoles.shape)}
            if stored_shapes and shapes != stored_shapes:
                raise RuntimeError(f"inconsistent stored property shapes in {fname}")
            stored_shapes = shapes
            energies.append(energy.copy())
            pos_bohr = pos  # stored in Bohr (SHARC convention)
            if cc_min is None:
                cc = np.linalg.norm(pos_bohr[1] - pos_bohr[0])
                cc_min = float(cc)
            for s in range(3):
                fnorm[s].append(float(np.linalg.norm(forces[:, s, :])))
            if forces.shape != (row.natoms, 3, 3) or nacs.shape != (row.natoms, 3, 3) or smooth.shape != (row.natoms, 3, 3):
                raise RuntimeError(f"unexpected tensor shape in {fname}")
            for c, (i, j) in GAP_INDEX.items():
                nnorm[c].append(float(np.linalg.norm(nacs[:, c, :])))
                dev = np.abs(smooth[:, c, :] - nacs[:, c, :] * (energy[i] - energy[j]))
                smooth_dev[c] = max(smooth_dev[c], float(dev.max()))
                smooth_scale[c] = max(smooth_scale[c], float(np.abs(smooth[:, c, :]).max()))
        # The contract defines relative energy against the minimum S0 energy
        # across the complete molecule database. Convert the resulting
        # Hartree differences to eV only after the global minimum is known.
        global_s0_min = min(float(energy[0]) for energy in energies)
        rel_e = {
            state: [(float(energy[state]) - global_s0_min) * REFERENCES["unit_conversions"]["hartree_to_ev"] for energy in energies]
            for state in range(3)
        }
        truth[molecule] = {
            "n_structures": len(rows),
            "n_atoms": sorted(natoms_seen),
            "n_states": 3,
            "n_couplings": 3,
            "conf_labels": sorted(str(c) for c in confs if c is not None),
            "path_yes_count": path_yes,
            "data_keys": sorted(keys),
            "rel_e_stats": {s: stats(rel_e[s]) for s in range(3)},
            "fnorm_stats": {s: stats(fnorm[s]) for s in range(3)},
            "nnorm_stats": {c: stats(nnorm[c]) for c in range(3)},
            "smooth_dev": smooth_dev,
            "smooth_scale": smooth_scale,
            "stored_shapes": {key: list(shape) for key, shape in stored_shapes.items()},
            "smooth_n_points": {c: sum(np.asarray(row.data["smooth_nacs"]).shape[0] * 3 for row in rows)
                                for c in range(3)},
            "cc_min_bohr": cc_min,
        }
    return truth


def stats(values: list[float]) -> dict:
    arr = np.asarray(values, dtype=float)
    return {
        "mean": float(arr.mean()),
        "std": float(arr.std()),
        "min": float(arr.min()),
        "max": float(arr.max()),
    }


def close(actual: float, expected: float, rel: float) -> bool:
    scale = max(abs(expected), REFERENCES["tolerances"]["relative_scale_floor"])
    return abs(actual - expected) <= rel * scale


def _alias_values(mapping: dict, keys: tuple[str, ...], path: str, convert):
    values = [convert(mapping[key], f"{path}.{key}") for key in keys if key in mapping]
    if not values:
        return None
    if any(value != values[0] for value in values[1:]):
        raise CandidateFail(f"{path} contains conflicting aliases")
    return values[0]


def _validate_anchor(dipoles: dict, path: str) -> None:
    declared = []
    for key in ("known_transition_anchor", "anchor"):
        if key not in dipoles:
            continue
        value = dipoles[key]
        if not isinstance(value, dict):
            raise CandidateFail(f"{path}.{key} must be an object")
        index = _alias_values(value, ("stored_row_index", "index"), f"{path}.{key}", json_int)
        label = _alias_values(value, ("meaning", "label"), f"{path}.{key}", json_string)
        if index is None or label is None:
            raise CandidateFail(f"{path}.{key} must declare an index and label")
        declared.append((index, label))
    flat_index = _alias_values(dipoles, ("anchor_row_index",), path, json_int)
    flat_label = _alias_values(dipoles, ("anchor_label",), path, json_string)
    if flat_index is not None or flat_label is not None:
        if flat_index is None or flat_label is None:
            raise CandidateFail(f"{path} flat anchor aliases must include both index and label")
        declared.append((flat_index, flat_label))
    if not declared or any(value != declared[0] for value in declared[1:]):
        raise CandidateFail(f"{path} must declare one consistent transition anchor")
    if declared[0] != (3, "mu_10"):
        raise CandidateFail(f"{path} transition anchor conflicts with the given convention")

    unresolved = []
    if "unresolved_row_mapping" in dipoles:
        value = dipoles["unresolved_row_mapping"]
        if not isinstance(value, bool):
            raise CandidateFail(f"{path}.unresolved_row_mapping must be a boolean")
        unresolved.append(value)
    for key in ("other_row_mapping", "other_rows"):
        if key in dipoles:
            value = dipoles[key]
            if not isinstance(value, str):
                raise CandidateFail(f"{path}.{key} must be a string")
            unresolved.append(value.strip().lower() == "unresolved")
    if not unresolved or any(value != unresolved[0] for value in unresolved[1:]) or not unresolved[0]:
        raise CandidateFail(f"{path} must consistently state that the other row mapping is unresolved")


def validate_summary(summary: object, truth: dict) -> None:
    if not isinstance(summary, dict):
        raise CandidateFail("summary.json must contain an object")
    if summary.get("schema") != "case01/scientific-summary/v2":
        raise CandidateFail("summary.json schema must be case01/scientific-summary/v2")
    required_root = ("units", "data_schema", "molecules", "smooth_nacs_convention", "caveats")
    for key in required_root:
        if key not in summary:
            raise CandidateFail(f"summary.json missing key: {key}")
    if not isinstance(summary["caveats"], list) or any(not isinstance(x, str) for x in summary["caveats"]):
        raise CandidateFail("summary.json caveats must be an array of strings")

    units = summary["units"]
    if not isinstance(units, dict):
        raise CandidateFail("summary.json units must be an object")
    unit_aliases = {
        "positions": "positions", "energy": "energy", "forces": "forces", "nacs": "nacs"
    }
    top_units = {}
    for name, dimension in unit_aliases.items():
        if name not in units:
            raise CandidateFail(f"summary.json units missing {name}")
        top_units[name] = normalize_unit(units[name], dimension, f"summary.json units.{name}")
    if top_units != {"positions": "bohr", "energy": "hartree", "forces": "hartree/bohr", "nacs": "1/bohr"}:
        raise CandidateFail("summary.json top-level units conflict with the supported data units")
    if "smooth_nacs" in units:
        top_smooth_unit = normalize_unit(units["smooth_nacs"], "smooth_nacs", "summary.json units.smooth_nacs")
        if top_smooth_unit != "hartree/bohr":
            raise CandidateFail("summary.json units.smooth_nacs conflicts with the declared energy × NAC units")

    schema = summary["data_schema"]
    if not isinstance(schema, dict) or set(schema) != set(truth):
        raise CandidateFail("summary.json data_schema must describe all three public databases")
    expected_axes = {
        "forces": ["atom", "state", "xyz"],
        "dipoles": ["dipole_vector", "xyz"],
        "nacs": ["atom", "coupling", "xyz"],
        "smooth_nacs": ["atom", "coupling", "xyz"],
    }
    expected_couplings = list(COUPLINGS)
    expected_nested_units = {"energy": "energy", "forces": "forces", "nacs": "nacs"}

    for mol, ref in truth.items():
        entry = schema[mol]
        expected_properties = set(expected_axes) | {"energy"}
        if not isinstance(entry, dict) or set(entry) != expected_properties:
            raise CandidateFail(f"data_schema.{mol} must contain energy, forces, dipoles, nacs and smooth_nacs")
        energy = entry["energy"]
        if not isinstance(energy, dict):
            raise CandidateFail(f"data_schema.{mol}.energy must be an object")
        validate_json_shape(energy.get("stored_shape"), ref["stored_shapes"]["energy"],
                            f"data_schema.{mol}.energy.stored_shape")
        validate_json_shape(energy.get("normalized_shape"), [3],
                            f"data_schema.{mol}.energy.normalized_shape")
        validate_json_axes(energy.get("axes"), ["record", "state"], f"data_schema.{mol}.energy.axes")
        validate_json_axes(energy.get("normalized_axes"), ["state"], f"data_schema.{mol}.energy.normalized_axes")
        validate_json_axes(energy.get("state_order"), ["S0", "S1", "S2"], f"data_schema.{mol}.energy.state_order")
        if "unit" in energy:
            nested_energy = normalize_unit(energy["unit"], "energy", f"data_schema.{mol}.energy.unit")
            if nested_energy != top_units["energy"]:
                raise CandidateFail(f"data_schema.{mol}.energy.unit conflicts with top-level units.energy")

        for name, axes in expected_axes.items():
            item = entry[name]
            if not isinstance(item, dict):
                raise CandidateFail(f"data_schema.{mol}.{name} must be an object")
            expected_shape = ref["stored_shapes"][name]
            shape_values = [item[key] for key in ("shape", "stored_shape") if key in item]
            if not shape_values:
                raise CandidateFail(f"data_schema.{mol}.{name} is missing shape")
            for key, shape in zip((k for k in ("shape", "stored_shape") if k in item), shape_values):
                validate_json_shape(shape, expected_shape, f"data_schema.{mol}.{name}.{key}")
            if len(shape_values) == 2 and shape_values[0] != shape_values[1]:
                raise CandidateFail(f"data_schema.{mol}.{name} shape aliases conflict")
            validate_json_axes(item.get("axes"), axes, f"data_schema.{mol}.{name}.axes")
            if "unit" in item:
                if name in expected_nested_units:
                    dimension = expected_nested_units[name]
                    nested = normalize_unit(item["unit"], dimension, f"data_schema.{mol}.{name}.unit")
                    if nested != top_units[dimension]:
                        raise CandidateFail(f"data_schema.{mol}.{name}.unit conflicts with top-level units.{dimension}")
                elif name == "smooth_nacs":
                    nested = normalize_unit(item["unit"], "smooth_nacs", f"data_schema.{mol}.{name}.unit")
                    implied = f"{top_units['energy']}/{top_units['positions']}"
                    if nested != "hartree/bohr" or implied != "hartree/bohr":
                        raise CandidateFail(f"data_schema.{mol}.smooth_nacs.unit conflicts with declared units")
                    if "smooth_nacs" in units:
                        if nested != top_smooth_unit:
                            raise CandidateFail(f"data_schema.{mol}.smooth_nacs.unit conflicts with top-level units.smooth_nacs")

        nacs = entry["nacs"]
        order_aliases = ("coupling_axis_order", "coupling_order", "couplings")
        declared_orders = [nacs[key] for key in order_aliases if key in nacs]
        if not declared_orders:
            raise CandidateFail(f"data_schema.{mol}.nacs is missing coupling order")
        for key in order_aliases:
            if key in nacs:
                validate_json_axes(nacs[key], expected_couplings, f"data_schema.{mol}.nacs.{key}")
        if any(order != declared_orders[0] for order in declared_orders[1:]):
            raise CandidateFail(f"data_schema.{mol}.nacs coupling-order aliases conflict")
        _validate_anchor(entry["dipoles"], f"data_schema.{mol}.dipoles")

    convention = summary["smooth_nacs_convention"]
    if not isinstance(convention, str) or not convention.strip():
        raise CandidateFail("summary.json smooth_nacs_convention must provide a nonempty explanation")
    molecules = summary["molecules"]
    if not isinstance(molecules, dict) or set(molecules) != set(truth):
        raise CandidateFail("summary.json molecules must cover the three public databases")
    structure_keys = ("structures", "n_structures", "structure_count")
    conformer_keys = ("conf_label_count", "conformer_count", "n_conformers", "n_conf_labels")
    for mol, ref in truth.items():
        entry = molecules[mol]
        if not isinstance(entry, dict):
            raise CandidateFail(f"summary.json molecules.{mol} must be an object")
        count = _alias_values(entry, structure_keys, f"summary.json molecules.{mol}", json_int)
        if count is None or count != ref["n_structures"]:
            raise CandidateFail(f"summary.json molecules.{mol} structure count mismatch")
        labels = entry.get("conf_labels")
        if labels is not None and (not isinstance(labels, list) or any(not isinstance(x, str) for x in labels)):
            raise CandidateFail(f"summary.json molecules.{mol}.conf_labels must be an array of strings")
        conf_count = _alias_values(entry, conformer_keys, f"summary.json molecules.{mol}", json_int)
        if labels is not None:
            if conf_count is not None and conf_count != len(labels):
                raise CandidateFail(f"summary.json molecules.{mol} conf_labels/count aliases conflict")
            conf_count = len(labels)
        if conf_count is None or conf_count != len(ref["conf_labels"]):
            raise CandidateFail(f"summary.json molecules.{mol} conformer label count mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", nargs="?", default=".")
    parser.add_argument("--public-input-root", type=Path, default=None,
                        help="root directory containing the read-only public database files")
    parser.add_argument("--reference-file", type=Path, default=Path(__file__).with_name("refs.json"))
    parser.add_argument("--reference-dir", type=Path, default=None)
    parser.add_argument("--suite-root", type=Path, default=None)
    args = parser.parse_args()

    global REFERENCES
    try:
        REFERENCES = load_references(args.reference_file)
    except Exception as exc:
        print(f"ENV_ERROR: reference policy unavailable: {exc}", file=sys.stderr)
        return 2

    out = Path(args.output_dir) / "outputs"
    package = Path(__file__).resolve().parents[1]
    inputs_dir = args.public_input_root or package / "environment" / "assets" / "databases"
    if not out.is_dir():
        raise CandidateFail("missing outputs/")
    try:
        truth = recompute_truth(inputs_dir)
    except Exception as exc:  # reference computation broken -> environment issue
        print(f"ENV_ERROR: reference recomputation failed: {exc}", file=sys.stderr)
        return 2

    # ---------- L1/L2: database_audit.csv ----------
    audit_header = ["molecule", "n_structures", "n_atoms", "n_states", "n_couplings",
                    "coordinate_unit", "energy_unit", "conf_labels", "path_yes_count", "data_keys"]
    audit_rows = read_csv_rows(out / "database_audit.csv", audit_header)
    expected_molecules = list(truth)
    validate_audit_order(audit_rows, expected_molecules)
    audit = {r["molecule"]: r for r in audit_rows}
    for mol, ref in truth.items():
        row = audit[mol]
        if int(row["n_structures"]) != ref["n_structures"]:
            raise CandidateFail(f"{mol}: n_structures {row['n_structures']} != {ref['n_structures']}")
        if int(row["n_atoms"]) not in ref["n_atoms"]:
            raise CandidateFail(f"{mol}: n_atoms {row['n_atoms']} not in {ref['n_atoms']}")
        if int(row["n_states"]) != 3 or int(row["n_couplings"]) != 3:
            raise CandidateFail(f"{mol}: states/couplings must be 3")
        if row["coordinate_unit"].strip().lower() != "bohr":
            raise CandidateFail(f"{mol}: coordinate_unit must be bohr (C-C min = {ref['cc_min_bohr']:.4f} Bohr); got {row['coordinate_unit']!r}")
        if row["energy_unit"].strip().lower() != "hartree":
            raise CandidateFail(f"{mol}: energy_unit must be hartree; got {row['energy_unit']!r}")
        if row["conf_labels"].split(";") != ref["conf_labels"]:
            raise CandidateFail(f"{mol}: conf_labels mismatch")
        if int(row["path_yes_count"]) != ref["path_yes_count"]:
            raise CandidateFail(f"{mol}: path_yes_count {row['path_yes_count']} != {ref['path_yes_count']}")
        declared_keys = set(row["data_keys"].split(";"))
        if declared_keys != set(ref["data_keys"]):
            raise CandidateFail(f"{mol}: data_keys {sorted(declared_keys)} != public database keys {ref['data_keys']}")

    # ---------- L1/L3: property_stats.csv ----------
    stats_header = ["molecule", "property", "state_or_coupling", "unit", "mean", "std", "min", "max"]
    rows = read_csv_rows(out / "property_stats.csv", stats_header)
    validate_finite_stat_rows(rows)
    required = []
    for mol in truth:
        for state in ("S0", "S1", "S2"):
            required.append((mol, "energy", state))
        for state in ("S0", "S1", "S2"):
            required.append((mol, "force_norm", state))
        for coupling in COUPLINGS:
            required.append((mol, "nac_norm", coupling))
    stat_map = required_rows_by_key(rows, required,
                                    ("molecule", "property", "state_or_coupling"),
                                    "property_stats.csv")
    for mol in truth:
        for s in range(3):
            for prop, unit, ref_stats in (
                ("energy", "eV", truth[mol]["rel_e_stats"][s]),
                ("force_norm", "Hartree/Bohr", truth[mol]["fnorm_stats"][s]),
            ):
                state = ("S0", "S1", "S2")[s]
                row = stat_map[(mol, prop, state)]
                if row["unit"] != unit:
                    raise CandidateFail(f"{mol}/{prop}/{state}: unit must be {unit}")
                for field in ("mean", "std", "min", "max"):
                    if not close(finite(float(row[field])), ref_stats[field], REFERENCES["tolerances"]["relative_statistic"]):
                        raise CandidateFail(
                            f"{mol}/{prop}/{state}/{field}: {row[field]} != {ref_stats[field]:.6g} (rel tol {REFERENCES['tolerances']['relative_statistic']:g})")
        for c, coupling in enumerate(COUPLINGS):
            row = stat_map[(mol, "nac_norm", coupling)]
            if row["unit"] != "1/Bohr":
                raise CandidateFail(f"{mol}/nac_norm/{coupling}: unit must be 1/Bohr")
            for field in ("mean", "std", "min", "max"):
                if not close(finite(float(row[field])), truth[mol]["nnorm_stats"][c][field], REFERENCES["tolerances"]["relative_statistic"]):
                    raise CandidateFail(
                        f"{mol}/nac_norm/{coupling}/{field}: {row[field]} != {truth[mol]['nnorm_stats'][c][field]:.6g}")

    # ---------- L1/L3: smooth_nacs_check.csv ----------
    smooth_header = ["molecule", "coupling", "n_points", "max_abs_deviation",
                     "relative_max_deviation", "consistent"]
    srows = read_csv_rows(out / "smooth_nacs_check.csv", smooth_header)
    validate_smooth_rows(srows, truth)

    # ---------- L1: summary.json ----------
    summary_path = out / "summary.json"
    if not summary_path.is_file():
        raise CandidateFail("missing outputs/summary.json")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_json_keys)
    except json.JSONDecodeError as exc:
        raise CandidateFail(f"summary.json not valid JSON: {exc}")
    validate_summary(summary, truth)

    print("PASS: case-01 database audit consistent with recomputed references")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CandidateFail as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except (ValueError, TypeError, LookupError, OverflowError, csv.Error) as exc:
        print(f"FAIL: malformed candidate output: {exc}", file=sys.stderr)
        raise SystemExit(1)
