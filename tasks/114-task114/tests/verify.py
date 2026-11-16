#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including lattice.json, report.md).
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Compare TiS2 interlayer spacing across deposited structures.
"""Score the TiS2 intercalation lattice task from deposited CONTCAR files."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path


REFS = json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))
STRUCTURE_IDS = tuple(REFS["structure_ids"])
LENGTH_TOL_A = float(REFS["length_tol_A"])
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


def read_contcar(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 8:
        raise ValueError(f"CONTCAR too short: {path}")
    scale = float(lines[1].split()[0])
    vectors = []
    for index in range(2, 5):
        vectors.append([float(value) * scale for value in lines[index].split()[:3]])
    species = lines[5].split()
    counts = [int(value) for value in lines[6].split()]
    if len(species) != len(counts):
        raise ValueError(f"species/count mismatch: {path}")
    lengths = [math.sqrt(sum(component * component for component in vector)) for vector in vectors]
    n_ti = sum(count for element, count in zip(species, counts) if element == "Ti")
    a_length, b_length, c_length = lengths
    if abs(a_length - b_length) <= 0.01 and a_length < 4.5 and n_ti in (1, 3):
        interlayer = c_length / n_ti
    else:
        interlayer = None
    return {
        "a_A": a_length,
        "b_A": b_length,
        "c_A": c_length,
        "n_Ti": n_ti,
        "interlayer_A": interlayer,
    }


def reference(asset_dir: Path) -> dict:
    structures = {}
    for structure_id in STRUCTURE_IDS:
        structures[structure_id] = read_contcar(asset_dir / structure_id / "CONTCAR")
    o1_ti = structures["TiS2_P-3m1"]["interlayer_A"]
    o1_li = structures["LiTiS2_P-3m1"]["interlayer_A"]
    o1_na = structures["NaTiS2_P-3m1"]["interlayer_A"]
    claims = {
        "O1_lithiation_expands_interlayer": o1_li > o1_ti + 0.05,
        "O1_sodiation_expands_interlayer_more_than_lithiation": (o1_na - o1_ti) > (o1_li - o1_ti) + 0.05,
        "deposited_GGA_set_contains_MgTiS2": False,
        "R3m_TiS2_is_primitive_monolayer_cell": structures["TiS2_R3m"]["interlayer_A"] is not None,
    }
    return {"schema_version": 2, "structures": structures, "claims": claims, "methods": dict(REQUIRED_METHODS)}


def load_renderer(asset_dir: Path):
    path = asset_dir / "render_report.py"
    spec = importlib.util.spec_from_file_location("task150_render_report", path)
    if spec is None or spec.loader is None:
        raise ValueError("render_report.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render


def close(actual: object, expected: float) -> bool:
    try:
        value = float(actual)
    except (TypeError, ValueError):
        return False
    if isinstance(actual, bool) or not math.isfinite(value):
        return False
    return abs(value - expected) <= LENGTH_TOL_A


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    args = parser.parse_args()
    asset_dir = args.assets
    submission = args.submission
    try:
        gold = reference(asset_dir)
    except (OSError, ValueError) as exc:
        return environment_error(f"evaluation assets are unreadable: {exc}")

    try:
        render = load_renderer(asset_dir)
    except (OSError, ValueError, ImportError) as exc:
        return environment_error(f"evaluation assets are unreadable: {exc}")
    report = submission / "report.md"
    lattice_path = submission / "lattice.json"
    try:
        submitted = json.loads(lattice_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail(f"lattice.json is missing or not JSON: {exc}")
    if not isinstance(submitted, dict):
        return fail("lattice.json must be an object")
    if submitted.get("schema_version") != 2:
        return fail("schema_version must be 2")
    structures = submitted.get("structures")
    claims = submitted.get("claims")
    methods = submitted.get("methods")
    if not isinstance(structures, dict) or not isinstance(claims, dict) or not isinstance(methods, dict):
        return fail("lattice.json needs structures, claims, and methods objects")

    mismatches = []
    for structure_id, expected in gold["structures"].items():
        actual = structures.get(structure_id)
        if not isinstance(actual, dict):
            mismatches.append(f"{structure_id} missing")
            continue
        for key in ("a_A", "b_A", "c_A"):
            if not close(actual.get(key), expected[key]):
                mismatches.append(f"{structure_id}.{key}")
        if type(actual.get("n_Ti")) is not int or actual["n_Ti"] != expected["n_Ti"]:
            mismatches.append(f"{structure_id}.n_Ti")
        if expected["interlayer_A"] is None:
            if actual.get("interlayer_A") is not None:
                mismatches.append(f"{structure_id}.interlayer_A should be null")
        elif not close(actual.get("interlayer_A"), expected["interlayer_A"]):
            mismatches.append(f"{structure_id}.interlayer_A")
    for key, expected in gold["claims"].items():
        if claims.get(key) is not expected:
            mismatches.append(f"claims.{key}")
    if methods.get("interlayer_rule") != REQUIRED_METHODS["interlayer_rule"]:
        mismatches.append("methods.interlayer_rule")
    if mismatches:
        return fail("lattice metrics or claims do not match the deposited GGA cells", {"mismatches": mismatches[:12]})
    try:
        expected_report = render(submitted)
    except Exception as exc:  # noqa: BLE001
        return fail(f"cannot render the submitted result: {exc}")
    try:
        actual_report = report.read_text(encoding="utf-8")
    except OSError:
        return fail("report.md is missing")
    if actual_report.replace("\r\n", "\n") != expected_report:
        return fail("report.md does not match the public renderer applied to lattice.json")
    print(json.dumps({"status": "PASS", "reward": 1}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
