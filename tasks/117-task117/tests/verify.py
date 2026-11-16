#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including polarization.json, report.md).
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Analyse differential Li/Mg charge densities using consistent cells and references.
"""Score Li/Mg first-grid total-density differences after VASP CHGCAR normalization."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np

REFS = json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))
IONS = tuple(REFS["ions"])
INTEGRAL_TOL_E = float(REFS["integral_tol_e"])
VOLUME_TOL_A3 = float(REFS["volume_tol_a3"])
MAX_ABS_RTOL = float(REFS["max_abs_rtol"])
MAX_ABS_ATOL = float(REFS["max_abs_atol"])
FRACTION_TOL = float(REFS["fraction_tol"])
ELECTRON_CLOSE_E = float(REFS["electron_close_e"])
GEOMETRY_TOL_A = float(REFS["geometry_tol_a"])
LATTICE_TOL_A = float(REFS["lattice_tol_a"])
REQUIRED_METHODS = dict(REFS["required_methods"])


def _next_nonempty(handle) -> str:
    while True:
        line = handle.readline()
        if line == "":
            raise ValueError("CHGCAR ended before the first density grid")
        if line.strip():
            return line


def read_first_grid(path: Path) -> tuple[np.ndarray, tuple[int, int, int], float, np.ndarray]:
    """Read the first total-density grid from a VASP CHGCAR.

    The stored grid values are D = rho * V. Returns D, the grid shape, and the
    cell volume. Never reads the PAW augmentation block or a later grid.
    """
    with path.open(encoding="utf-8", errors="replace") as handle:
        if handle.readline() == "":
            raise ValueError(f"empty CHGCAR: {path}")
        scale_line = handle.readline()
        if not scale_line.strip():
            raise ValueError(f"missing scale line in {path}")
        scale = float(scale_line.split()[0])
        vectors = []
        for _ in range(3):
            line = handle.readline()
            if not line.strip():
                raise ValueError(f"missing lattice vector in {path}")
            vectors.append([float(value) * scale for value in line.split()[:3]])
        vectors_array = np.asarray(vectors, dtype=np.float64)
        species_line = handle.readline()
        counts_line = handle.readline()
        if not species_line.strip() or not counts_line.strip():
            raise ValueError(f"missing species block in {path}")
        counts = [int(value) for value in counts_line.split()]
        natoms = sum(counts)
        coord_line = handle.readline()
        if not coord_line:
            raise ValueError(f"missing coordinate mode in {path}")
        token = coord_line.strip().split()[0][:1].lower() if coord_line.strip() else ""
        if token == "s":
            coord_line = handle.readline()
            if not coord_line:
                raise ValueError(f"missing coordinate mode after selective dynamics in {path}")
        for _ in range(natoms):
            if handle.readline() == "":
                raise ValueError(f"truncated coordinates in {path}")
        grid_line = _next_nonempty(handle)
        try:
            nx, ny, nz = [int(value) for value in grid_line.split()[:3]]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid grid shape in {path}") from exc
        needed = nx * ny * nz
        values: list[float] = []
        while len(values) < needed:
            line = handle.readline()
            if line == "":
                raise ValueError(f"CHGCAR ended after {len(values)} of {needed} grid values: {path}")
            parts = line.split()
            if not parts:
                if values:
                    break
                continue
            try:
                chunk = [float(item) for item in parts]
            except ValueError as exc:
                raise ValueError(f"non-numeric grid value in {path}") from exc
            values.extend(chunk)
        if len(values) < needed:
            raise ValueError(f"CHGCAR ended after {len(values)} of {needed} grid values: {path}")
    stored = np.asarray(values[:needed], dtype=np.float64)
    if not np.isfinite(stored).all():
        raise ValueError(f"non-finite grid values in {path}")
    volume = abs(float(np.dot(vectors_array[0], np.cross(vectors_array[1], vectors_array[2]))))
    if volume <= 0.0 or not np.isfinite(volume):
        raise ValueError(f"invalid cell volume in {path}")
    return stored, (nx, ny, nz), volume, vectors_array


def read_structure(path: Path) -> tuple[list[str], np.ndarray, np.ndarray]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 8:
        raise ValueError(f"CONTCAR too short: {path}")
    scale = float(lines[1].split()[0])
    vectors = np.array([[float(value) * scale for value in lines[index].split()[:3]] for index in range(2, 5)], dtype=float)
    species = lines[5].split()
    counts = [int(value) for value in lines[6].split()]
    labels = []
    for element, count in zip(species, counts):
        labels.extend([element] * count)
    cursor = 7
    if not lines[cursor].strip():
        raise ValueError(f"missing coordinate mode in {path}")
    token = lines[cursor].strip().split()[0][:1].lower()
    if token == "s":
        cursor += 1
        token = lines[cursor].strip().split()[0][:1].lower()
    cartesian = token == "c" or token == "k"
    cursor += 1
    coords = np.array(
        [[float(value) for value in lines[cursor + index].split()[:3]] for index in range(len(labels))],
        dtype=float,
    )
    if cartesian:
        fractional = (coords * scale) @ np.linalg.inv(vectors)
    else:
        fractional = coords
    return labels, fractional, vectors


def lattices_match(left: np.ndarray, right: np.ndarray) -> bool:
    return bool(np.allclose(left, right, atol=LATTICE_TOL_A, rtol=0.0))


def minimum_image_cartesian(fractional_a: np.ndarray, fractional_b: np.ndarray, vectors: np.ndarray) -> float:
    delta = fractional_a - fractional_b
    delta -= np.round(delta)
    return float(np.linalg.norm(delta @ vectors))


def unique_match(labels_a: list[str], frac_a: np.ndarray, labels_b: list[str], frac_b: np.ndarray, vectors: np.ndarray) -> bool:
    if len(labels_a) != len(labels_b):
        return False
    used = set()
    for index, label in enumerate(labels_a):
        best_j = None
        best = 1e9
        for other, other_label in enumerate(labels_b):
            if other in used or other_label != label:
                continue
            distance = minimum_image_cartesian(frac_a[index], frac_b[other], vectors)
            if distance < best:
                best = distance
                best_j = other
        if best_j is None or best > GEOMETRY_TOL_A:
            return False
        used.add(best_j)
    return len(used) == len(labels_a)


def split_ion(labels: list[str], fractional: np.ndarray, ion: str) -> tuple[list[str], np.ndarray, list[str], np.ndarray]:
    host_mask = [label != ion for label in labels]
    ion_mask = [label == ion for label in labels]
    if not any(ion_mask):
        raise ValueError(f"no {ion} atom found")
    host_labels = [label for label, keep in zip(labels, host_mask) if keep]
    ion_labels = [label for label, keep in zip(labels, ion_mask) if keep]
    return host_labels, fractional[np.array(host_mask)], ion_labels, fractional[np.array(ion_mask)]


def geometries_match(ion_dir: Path, ion: str) -> bool:
    host_ion_labels, host_ion_frac, vectors = read_structure(ion_dir / "host_ion" / "CONTCAR")
    host_labels, host_frac, host_vectors = read_structure(ion_dir / "host" / "CONTCAR")
    ion_labels, ion_frac, ion_vectors = read_structure(ion_dir / "ion" / "CONTCAR")
    if not (lattices_match(vectors, host_vectors) and lattices_match(vectors, ion_vectors)):
        return False
    host_from_combined_labels, host_from_combined_frac, ion_from_combined_labels, ion_from_combined_frac = split_ion(
        host_ion_labels, host_ion_frac, ion
    )
    if ion_labels != [ion] * len(ion_labels):
        return False
    return unique_match(host_labels, host_frac, host_from_combined_labels, host_from_combined_frac, vectors) and unique_match(
        ion_labels, ion_frac, ion_from_combined_labels, ion_from_combined_frac, vectors
    )


def fail(message: str, details: dict | None = None) -> int:
    payload = {"status": "FAIL", "reward": 0, "message": message}
    if details:
        payload["details"] = details
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1


def environment_error(message: str) -> int:
    print(json.dumps({"status": "ERROR", "message": message}, ensure_ascii=False, indent=2))
    return 2


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


def load_renderer(asset_dir: Path):
    path = asset_dir / "render_report.py"
    spec = importlib.util.spec_from_file_location("task153_render_report", path)
    if spec is None or spec.loader is None:
        raise ValueError("render_report.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render


def difference_metrics(ion_dir: Path) -> dict:
    stored = []
    grids = []
    volumes = []
    lattices = []
    for role in ("host_ion", "host", "ion"):
        values, grid, volume, lattice = read_first_grid(ion_dir / role / "CHGCAR")
        stored.append(values)
        grids.append(grid)
        volumes.append(volume)
        lattices.append(lattice)
    if not (grids[0] == grids[1] == grids[2]):
        raise ValueError(f"incommensurate grids in {ion_dir}")
    if not (lattices_match(lattices[0], lattices[1]) and lattices_match(lattices[0], lattices[2])):
        raise ValueError(f"incommensurate cells in {ion_dir}")
    if max(abs(volumes[0] - volumes[1]), abs(volumes[0] - volumes[2])) > VOLUME_TOL_A3:
        raise ValueError(f"incommensurate volumes in {ion_dir}")
    densities = [values / volume for values, volume in zip(stored, volumes)]
    delta_rho = densities[0] - densities[1] - densities[2]
    if not np.isfinite(delta_rho).all():
        raise ValueError(f"non-finite density difference in {ion_dir}")
    voxel = volumes[0] / delta_rho.size
    delta_stored = (
        stored[0]
        - stored[1] * (volumes[0] / volumes[1])
        - stored[2] * (volumes[0] / volumes[2])
    )
    integral_from_density = float(delta_rho.sum() * voxel)
    integral_from_stored = float(delta_stored.sum() / delta_stored.size)
    if abs(integral_from_density - integral_from_stored) > 1e-8:
        raise ValueError(f"integral cross-check failed in {ion_dir}")
    return {
        "grid": list(grids[0]),
        "cell_volume_A3": volumes[0],
        "integral_delta_e": integral_from_density,
        "max_abs_delta_e_per_A3": float(np.max(np.abs(delta_rho))),
        "volume_fraction_abs_gt_0.004": float(np.mean(np.abs(delta_rho) > 0.004)),
        "geometry_match": geometries_match(ion_dir, ion_dir.name),
    }


def independent_stored_metrics(ion_dir: Path) -> dict:
    """Second path: keep D until the last step. Do not call difference_metrics()."""
    stored = []
    grids = []
    volumes = []
    for role in ("host_ion", "host", "ion"):
        values, grid, volume, _lattice = read_first_grid(ion_dir / role / "CHGCAR")
        stored.append(values)
        grids.append(grid)
        volumes.append(volume)
    if not (grids[0] == grids[1] == grids[2]):
        raise ValueError("independent path saw mismatched grids")
    volume = volumes[0]
    delta_stored = stored[0] - stored[1] - stored[2]
    return {
        "cell_volume_A3": volume,
        "max_abs_delta_e_per_A3": float(np.max(np.abs(delta_stored)) / volume),
        "volume_fraction_abs_gt_0.004": float(np.mean(np.abs(delta_stored) / volume > 0.004)),
        "integral_delta_e": float(delta_stored.sum() / delta_stored.size),
    }


def reference(asset_dir: Path) -> dict:
    ions = {ion: difference_metrics(asset_dir / ion) for ion in IONS}
    closed = all(abs(row["integral_delta_e"]) < ELECTRON_CLOSE_E for row in ions.values())
    compatible = all(row["grid"] == ions["Li"]["grid"] for row in ions.values()) and all(
        abs(row["cell_volume_A3"] - ions["Li"]["cell_volume_A3"]) <= VOLUME_TOL_A3 for row in ions.values()
    )
    checks = {
        "cells_and_grids_compatible": compatible,
        "geometry_matches": all(row["geometry_match"] for row in ions.values()),
        "electron_count_closed": closed,
    }
    return {"ions": ions, "checks": checks, "interpretation": dict(REQUIRED_METHODS)}


def close_abs(actual: object, expected: float, tolerance: float) -> bool:
    number = as_float(actual)
    return number is not None and abs(number - expected) <= tolerance


def close_max(actual: object, expected: float) -> bool:
    number = as_float(actual)
    return number is not None and abs(number - expected) <= max(MAX_ABS_ATOL, MAX_ABS_RTOL * abs(expected))


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

    result_path = args.submission / "polarization.json"
    report_path = args.submission / "report.md"
    try:
        submitted = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail(f"polarization.json is missing or not JSON: {exc}")
    if not isinstance(submitted, dict):
        return fail("polarization.json must be an object")
    if submitted.get("schema_version") != 2:
        return fail("schema_version must be 2")
    checks = submitted.get("checks")
    interpretation = submitted.get("interpretation")
    if not isinstance(checks, dict) or not isinstance(interpretation, dict):
        return fail("polarization.json needs checks and interpretation objects")

    mismatches = []
    for ion, expected in gold["ions"].items():
        actual = submitted.get(ion)
        if not isinstance(actual, dict):
            mismatches.append(f"{ion} missing")
            continue
        grid = actual.get("grid")
        if (
            not isinstance(grid, list)
            or any(type(dimension) is not int for dimension in grid)
            or grid != expected["grid"]
        ):
            mismatches.append(f"{ion}.grid")
        if not close_abs(actual.get("cell_volume_A3"), expected["cell_volume_A3"], VOLUME_TOL_A3):
            mismatches.append(f"{ion}.cell_volume_A3")
        if not close_abs(actual.get("integral_delta_e"), expected["integral_delta_e"], INTEGRAL_TOL_E):
            mismatches.append(f"{ion}.integral_delta_e")
        if not close_max(actual.get("max_abs_delta_e_per_A3"), expected["max_abs_delta_e_per_A3"]):
            mismatches.append(f"{ion}.max_abs_delta_e_per_A3")
        if not close_abs(actual.get("volume_fraction_abs_gt_0.004"), expected["volume_fraction_abs_gt_0.004"], FRACTION_TOL):
            mismatches.append(f"{ion}.volume_fraction_abs_gt_0.004")
    for key, expected in gold["checks"].items():
        if checks.get(key) is not expected:
            mismatches.append(f"checks.{key}")
    for key, expected in REQUIRED_METHODS.items():
        if interpretation.get(key) != expected:
            mismatches.append(f"interpretation.{key}")
    if mismatches:
        return fail("charge-density diagnosis does not match the deposited first-grid CHGCARs", {"mismatches": mismatches[:16]})

    try:
        expected_report = render(submitted)
    except Exception as exc:  # noqa: BLE001
        return fail(f"cannot render the submitted result: {exc}")
    try:
        actual_report = report_path.read_text(encoding="utf-8")
    except OSError:
        return fail("report.md is missing")
    if actual_report.replace("\r\n", "\n") != expected_report:
        return fail("report.md does not match the public renderer applied to polarization.json")
    print(json.dumps({"status": "PASS", "reward": 1}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
