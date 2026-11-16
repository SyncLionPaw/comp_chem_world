#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including charges.json, report.md).
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Interpret Bader charge changes in TiS2 and LiTiS2.
"""Score Bader redox assignment for TiS2 and LiTiS2 at PBE and HSE06."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path


REFS = json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))
SYSTEM_IDS = tuple(REFS["system_ids"])
CHARGE_TOL_E = float(REFS["charge_tol_e"])
REQUIRED_METHODS = dict(REFS["required_methods"])


def fail(message: str, details: dict | None = None) -> int:
    payload = {"status": "FAIL", "reward": 0, "message": message}
    if details:
        payload["details"] = details
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1


def environment_error(message: str) -> int:
    print(json.dumps({"status": "ERROR", "message": message}, ensure_ascii=False, indent=2))
    return 2


def read_poscar_species(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    species = lines[5].split()
    counts = [int(value) for value in lines[6].split()]
    labels = []
    for element, count in zip(species, counts):
        labels.extend([element] * count)
    return labels


def read_acf(path: Path) -> list[float]:
    charges = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if parts and parts[0].isdigit() and len(parts) >= 5:
            charges.append(float(parts[4]))
    if not charges:
        raise ValueError(f"no charges in {path}")
    return charges


def mean_charges(asset_dir: Path, system_id: str) -> dict[str, float]:
    labels = read_poscar_species(asset_dir / system_id / "POSCAR")
    charges = read_acf(asset_dir / system_id / "ACF.dat")
    if len(labels) != len(charges):
        raise ValueError(f"{system_id} POSCAR/ACF atom count mismatch")
    totals: dict[str, list[float]] = {}
    for label, charge in zip(labels, charges):
        totals.setdefault(label, []).append(charge)
    return {element: sum(values) / len(values) for element, values in totals.items()}


def delta(lithiated: dict[str, float], pristine: dict[str, float], element: str) -> float:
    return lithiated[element] - pristine[element]


def reference(asset_dir: Path) -> dict:
    systems = {system_id: mean_charges(asset_dir, system_id) for system_id in SYSTEM_IDS}
    deltas = {}
    for functional, pristine_id, lithiated_id in (
        ("GGA", "TiS2_GGA", "LiTiS2_GGA"),
        ("HSE06", "TiS2_HSE06", "LiTiS2_HSE06"),
    ):
        pristine = systems[pristine_id]
        lithiated = systems[lithiated_id]
        sulfur_mean = delta(lithiated, pristine, "S")
        deltas[functional] = {
            "Ti": delta(lithiated, pristine, "Ti"),
            "S_mean": sulfur_mean,
            "S_total": 2.0 * sulfur_mean,
        }
    claims = {
        "GGA_S_total_gain_exceeds_Ti": deltas["GGA"]["S_total"] > deltas["GGA"]["Ti"],
        "HSE06_S_total_gain_exceeds_Ti": deltas["HSE06"]["S_total"] > deltas["HSE06"]["Ti"],
        "bader_alone_shows_sulfur_redox_inactive": False,
    }
    return {"schema_version": 2, "systems": systems, "deltas": deltas, "claims": claims, "methods": dict(REQUIRED_METHODS)}


def load_renderer(asset_dir: Path):
    path = asset_dir / "render_report.py"
    spec = importlib.util.spec_from_file_location("task152_render_report", path)
    if spec is None or spec.loader is None:
        raise ValueError("render_report.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render


def as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def close(actual: object, expected: float) -> bool:
    number = as_float(actual)
    return number is not None and abs(number - expected) <= CHARGE_TOL_E


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    args = parser.parse_args()
    try:
        gold = reference(args.assets)
        render = load_renderer(args.assets)
    except (OSError, ValueError, IndexError, ImportError) as exc:
        return environment_error(f"evaluation assets are unreadable: {exc}")

    report = args.submission / "report.md"
    charges_path = args.submission / "charges.json"
    try:
        submitted = json.loads(charges_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail(f"charges.json is missing or not JSON: {exc}")
    if not isinstance(submitted, dict):
        return fail("charges.json must be an object")
    if submitted.get("schema_version") != 2:
        return fail("schema_version must be 2")
    systems = submitted.get("systems")
    deltas = submitted.get("deltas")
    claims = submitted.get("claims")
    methods = submitted.get("methods")
    if not isinstance(systems, dict) or not isinstance(deltas, dict) or not isinstance(claims, dict) or not isinstance(methods, dict):
        return fail("charges.json needs systems, deltas, claims, and methods objects")

    mismatches = []
    for system_id, expected in gold["systems"].items():
        actual = systems.get(system_id)
        if not isinstance(actual, dict):
            mismatches.append(f"{system_id} missing")
            continue
        for element, charge in expected.items():
            if not close(actual.get(element), charge):
                mismatches.append(f"{system_id}.{element}")
    for functional, expected in gold["deltas"].items():
        actual = deltas.get(functional)
        if not isinstance(actual, dict):
            mismatches.append(f"deltas.{functional} missing")
            continue
        for key, charge in expected.items():
            if not close(actual.get(key), charge):
                mismatches.append(f"deltas.{functional}.{key}")
    for key, expected in gold["claims"].items():
        if claims.get(key) is not expected:
            mismatches.append(f"claims.{key}")
    for key, expected in REQUIRED_METHODS.items():
        if methods.get(key) != expected:
            mismatches.append(f"methods.{key}")
    if mismatches:
        return fail("Bader charges or redox claims do not match the deposited ACF.dat files", {"mismatches": mismatches[:16]})
    try:
        expected_report = render(submitted)
    except Exception as exc:  # noqa: BLE001
        return fail(f"cannot render the submitted result: {exc}")
    try:
        actual_report = report.read_text(encoding="utf-8")
    except OSError:
        return fail("report.md is missing")
    if actual_report.replace("\r\n", "\n") != expected_report:
        return fail("report.md does not match the public renderer applied to charges.json")
    print(json.dumps({"status": "PASS", "reward": 1}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
