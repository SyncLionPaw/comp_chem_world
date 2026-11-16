#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including barriers.json, report.md).
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Reconstruct migration barriers from deposited CI-NEB paths.
"""Score CI-NEB barrier interpretation from deposited image OSZICAR files."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path


REFS = json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))
PATH_IDS = tuple(REFS["path_ids"])
ENERGY_TOL_EV = float(REFS["energy_tol_eV"])
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


def final_free_energy(path: Path) -> float:
    energy = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if " F= " not in line:
            continue
        parts = line.split()
        for index, token in enumerate(parts):
            if token == "F=" and index + 1 < len(parts):
                energy = float(parts[index + 1])
    if energy is None:
        raise ValueError(f"no ionic F= record in {path}")
    return energy


def path_reference(path_dir: Path) -> dict:
    images = sorted(
        (item for item in path_dir.iterdir() if item.is_dir() and item.name.isdigit()),
        key=lambda item: int(item.name),
    )
    if len(images) < 2:
        raise ValueError(f"fewer than two images in {path_dir}")
    absolute = [final_free_energy(image / "OSZICAR") for image in images]
    relative = [value - absolute[0] for value in absolute]
    maximum_index = max(range(len(relative)), key=lambda index: relative[index])
    return {
        "n_images": len(images),
        "energies_rel_eV": relative,
        "barrier_eV": relative[maximum_index],
        "barrier_image": int(images[maximum_index].name),
        "endpoint_rel_eV": relative[-1],
        "interior_saddle": maximum_index not in (0, len(relative) - 1),
    }


def reference(asset_dir: Path) -> dict:
    paths = {path_id: path_reference(asset_dir / "neb" / path_id) for path_id in PATH_IDS}
    claims = {
        "O1_Mg_slower_than_O1_Li": paths["O1_Mg"]["barrier_eV"] > paths["O1_Li"]["barrier_eV"] + 0.05,
        "O1_Na_interior_saddle": paths["O1_Na"]["interior_saddle"],
        "Li05_lowers_Mg_barrier": paths["Li05_Mg"]["barrier_eV"] < paths["O1_Mg"]["barrier_eV"] - 0.05,
        "Li05_lowers_Li_barrier": paths["Li05_Li"]["barrier_eV"] < paths["O1_Li"]["barrier_eV"] - 0.05,
        "P3_Na_below_O3_Na": paths["P3_Na"]["barrier_eV"] < paths["O3_Na"]["barrier_eV"] - 0.05,
        "P3_Mg_below_both_O3_paths": (
            paths["P3_Mg"]["barrier_eV"] < paths["O3_Mg_PATH1"]["barrier_eV"] - 0.05
            and paths["P3_Mg"]["barrier_eV"] < paths["O3_Mg_PATH2"]["barrier_eV"] - 0.05
        ),
        "low_P3_barrier_explains_poor_Mg_Na_storage": (
            paths["P3_Na"]["barrier_eV"] > paths["O3_Na"]["barrier_eV"] + 0.05
            and paths["P3_Mg"]["barrier_eV"] > paths["O3_Mg_PATH1"]["barrier_eV"] + 0.05
            and paths["P3_Mg"]["barrier_eV"] > paths["O3_Mg_PATH2"]["barrier_eV"] + 0.05
        ),
    }
    delta = paths["O1_Mg"]["barrier_eV"] - paths["Li05_Mg"]["barrier_eV"]
    return {"schema_version": 2, "paths": paths, "claims": claims, "delta_Mg_O1_minus_Li05_eV": delta, "methods": dict(REQUIRED_METHODS)}


def load_renderer(asset_dir: Path):
    path = asset_dir / "render_report.py"
    spec = importlib.util.spec_from_file_location("task151_render_report", path)
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
    return number is not None and abs(number - expected) <= ENERGY_TOL_EV


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    args = parser.parse_args()
    try:
        gold = reference(args.assets)
        render = load_renderer(args.assets)
    except (OSError, ValueError, ImportError) as exc:
        return environment_error(f"evaluation assets are unreadable: {exc}")

    report = args.submission / "report.md"
    barriers_path = args.submission / "barriers.json"
    try:
        submitted = json.loads(barriers_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail(f"barriers.json is missing or not JSON: {exc}")
    if not isinstance(submitted, dict):
        return fail("barriers.json must be an object")
    if submitted.get("schema_version") != 2:
        return fail("schema_version must be 2")
    paths = submitted.get("paths")
    claims = submitted.get("claims")
    methods = submitted.get("methods")
    if not isinstance(paths, dict) or not isinstance(claims, dict) or not isinstance(methods, dict):
        return fail("barriers.json needs paths, claims, and methods objects")

    mismatches = []
    for path_id, expected in gold["paths"].items():
        actual = paths.get(path_id)
        if not isinstance(actual, dict):
            mismatches.append(f"{path_id} missing")
            continue
        energies = actual.get("energies_rel_eV")
        if not isinstance(energies, list) or len(energies) != expected["n_images"]:
            mismatches.append(f"{path_id}.energies_rel_eV")
        else:
            for index, expected_energy in enumerate(expected["energies_rel_eV"]):
                if not close(energies[index], expected_energy):
                    mismatches.append(f"{path_id}.energies_rel_eV[{index}]")
                    break
        if type(actual.get("n_images")) is not int or actual["n_images"] != expected["n_images"]:
            mismatches.append(f"{path_id}.n_images")
        if not close(actual.get("barrier_eV"), expected["barrier_eV"]):
            mismatches.append(f"{path_id}.barrier_eV")
        image = actual.get("barrier_image")
        if type(image) is not int:
            image = None
        if image != expected["barrier_image"]:
            mismatches.append(f"{path_id}.barrier_image")
        if not close(actual.get("endpoint_rel_eV"), expected["endpoint_rel_eV"]):
            mismatches.append(f"{path_id}.endpoint_rel_eV")
        if actual.get("interior_saddle") is not expected["interior_saddle"]:
            mismatches.append(f"{path_id}.interior_saddle")
    if not close(submitted.get("delta_Mg_O1_minus_Li05_eV"), gold["delta_Mg_O1_minus_Li05_eV"]):
        mismatches.append("delta_Mg_O1_minus_Li05_eV")
    for key, expected in gold["claims"].items():
        if claims.get(key) is not expected:
            mismatches.append(f"claims.{key}")
    if methods.get("energy_source") != REQUIRED_METHODS["energy_source"]:
        mismatches.append("methods.energy_source")
    if mismatches:
        return fail("migration barriers or mechanistic claims do not match the deposited CI-NEB paths", {"mismatches": mismatches[:16]})
    try:
        expected_report = render(submitted)
    except Exception as exc:  # noqa: BLE001
        return fail(f"cannot render the submitted result: {exc}")
    try:
        actual_report = report.read_text(encoding="utf-8")
    except OSError:
        return fail("report.md is missing")
    if actual_report.replace("\r\n", "\n") != expected_report:
        return fail("report.md does not match the public renderer applied to barriers.json")
    print(json.dumps({"status": "PASS", "reward": 1}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
