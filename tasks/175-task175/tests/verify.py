#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Compare lithium contacts and oxygen bridges in two frames.
"""Rebuild the Li-O-Li contact graph on the two author frames."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np



def emit(status: str, checks: list[dict], code: int) -> int:
    print(json.dumps({"overall": status, "checks": checks}, ensure_ascii=False, indent=2))
    return code


def num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def asset_directory() -> Path:
    app_assets = Path(os.environ.get("APP", "/app")) / "environment" / "assets"
    if app_assets.is_dir():
        return app_assets
    return Path(__file__).resolve().parents[1] / "environment" / "assets"


def load_xyz(path: Path) -> tuple[np.ndarray, np.ndarray]:
    elems, rows = [], []
    for line in path.read_text(encoding="utf-8").splitlines()[2:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        elems.append(parts[0])
        rows.append([float(parts[1]), float(parts[2]), float(parts[3])])
    return np.asarray(elems), np.asarray(rows)


def minimum_image(delta: np.ndarray, box: float) -> np.ndarray:
    return delta - box * np.round(delta / box)


def analyze(elems: np.ndarray, xyz: np.ndarray, li_cut: float, o_cut: float, criteria: dict) -> dict:
    li = np.where(elems == "Li")[0]
    oxygen = np.where(elems == "O")[0]
    hydrogen = xyz[elems == "H"]
    water = set()
    for index in oxygen:
        dist = np.linalg.norm(minimum_image(hydrogen - xyz[index], criteria["box_length_A"]), axis=1)
        if np.any(dist < criteria["water_OH_cutoff_A"]):
            water.add(int(index))
    neighbors = []
    for index in li:
        dist = np.linalg.norm(minimum_image(xyz[oxygen] - xyz[index], criteria["box_length_A"]), axis=1)
        neighbors.append([int(oxygen[j]) for j in np.where(dist <= o_cut)[0]])
    li_xyz = xyz[li]
    n = len(li)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    n_pairs = bridged = water_only = anion_only = both = 0
    for i in range(n):
        delta = minimum_image(li_xyz[i + 1 :] - li_xyz[i], criteria["box_length_A"])
        dist = np.linalg.norm(delta, axis=1)
        for offset, dij in enumerate(dist):
            if dij > li_cut:
                continue
            j = i + 1 + offset
            n_pairs += 1
            shared = set(neighbors[i]) & set(neighbors[j])
            n_water = len(shared & water)
            n_anion = len(shared - water)
            if shared:
                bridged += 1
            if n_water and n_anion:
                both += 1
            elif n_water:
                water_only += 1
            elif n_anion:
                anion_only += 1
            a, b = find(i), find(j)
            if a != b:
                parent[b] = a
    sizes: dict[int, int] = {}
    for i in range(n):
        sizes[find(i)] = sizes.get(find(i), 0) + 1
    in_chain = sum(size for size in sizes.values() if size >= criteria["chain_component_min"])
    return {
        "n_contact_pairs": n_pairs,
        "fraction_oxygen_bridged": (bridged / n_pairs) if n_pairs else 0.0,
        "max_component_size": max(sizes.values()) if sizes else 0,
        "fraction_Li_in_components_ge_3": in_chain / n,
        "contacts_share_water": (water_only + both) > 0 and anion_only < n_pairs,
        "anion_can_co_bridge": both > 0,
    }


def close_block(reported: dict, ref: dict, tol: dict) -> bool:
    if not isinstance(reported, dict):
        return False
    return (
        reported.get("n_contact_pairs") == ref["n_contact_pairs"]
        and num(reported.get("fraction_oxygen_bridged"))
        and abs(float(reported["fraction_oxygen_bridged"]) - ref["fraction_oxygen_bridged"]) <= tol["fraction_oxygen_bridged"]
        and reported.get("max_component_size") == ref["max_component_size"]
        and num(reported.get("fraction_Li_in_components_ge_3"))
        and abs(float(reported["fraction_Li_in_components_ge_3"]) - ref["fraction_Li_in_components_ge_3"]) <= tol["fraction_Li_in_components_ge_3"]
    )


def load_refs() -> dict:
    """Require the private references and every pinned scientific input."""
    import hashlib
    import math
    import re
    from pathlib import PurePosixPath

    tests = Path(os.environ.get("TESTS", Path(__file__).resolve().parent)).resolve()
    path = tests / "refs.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("refs.json missing or unsafe")
    refs = json.loads(path.read_text(encoding="utf-8"))
    schema = {'output': 'str', 'assets': [{'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}], 'gold': {'li_li_cutoff_A': 'number', 'li_o_cutoff_A': 'number', 'early': {'n_contact_pairs': 'number', 'fraction_oxygen_bridged': 'number', 'max_component_size': 'number', 'fraction_Li_in_components_ge_3': 'number'}, 'late': {'n_contact_pairs': 'number', 'fraction_oxygen_bridged': 'number', 'max_component_size': 'number', 'fraction_Li_in_components_ge_3': 'number'}, 'contacts_share_water': 'bool', 'anion_can_co_bridge': 'bool', 'chains_present_in_late_frame': 'bool', 'extended_chains_present_at_classical_start': 'bool', 'ensemble_population_established': 'bool'}, 'tolerances': {'fraction_oxygen_bridged': 'number', 'fraction_Li_in_components_ge_3': 'number'}, 'criteria': {'box_length_A': 'number', 'water_OH_cutoff_A': 'number', 'li_li_cutoff_range_A': ['number', 'number'], 'li_o_cutoff_range_A': ['number', 'number'], 'chain_component_min': 'number', 'extended_component_min': 'number'}}

    def validate(value, expected):
        if isinstance(expected, dict):
            if not isinstance(value, dict) or set(value) != set(expected):
                raise ValueError("refs.json keys are missing or malformed")
            for key in expected:
                validate(value[key], expected[key])
        elif isinstance(expected, list):
            if not isinstance(value, list) or len(value) != len(expected):
                raise ValueError("refs.json array is malformed")
            for item, entry in zip(value, expected):
                validate(item, entry)
        elif expected == "number":
            if not num(value) or not math.isfinite(value):
                raise ValueError("refs.json number is invalid")
        elif expected == "bool":
            if not isinstance(value, bool):
                raise ValueError("refs.json boolean is invalid")
        elif not isinstance(value, str) or not value:
            raise ValueError("refs.json string is invalid")

    validate(refs, schema)

    def validate_bounds(value):
        if isinstance(value, dict):
            for item in value.values():
                validate_bounds(item)
        elif isinstance(value, list):
            if len(value) == 2 and all(num(item) for item in value) and value[0] > value[1]:
                raise ValueError("reference bounds are reversed")
            for item in value:
                validate_bounds(item)
        elif num(value) and value < 0:
            raise ValueError("negative reference tolerance or criterion")

    validate_bounds(refs["tolerances"])
    validate_bounds(refs["criteria"])
    output = PurePosixPath(refs["output"])
    if len(output.parts) != 1 or output.name in (".", ".."):
        raise ValueError("unsafe output name")
    app = asset_directory().parents[1]
    seen = set()
    for item in refs["assets"]:
        rel, expected = item["path"], item["sha256"]
        path = PurePosixPath(rel)
        if (path.is_absolute() or ".." in path.parts
                or path.parts[:2] != ("environment", "assets")
                or rel in seen or re.fullmatch(r"[0-9a-f]{64}", expected) is None):
            raise ValueError("invalid asset reference")
        seen.add(rel)
        target = app.joinpath(*path.parts)
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"asset missing or unsafe: {rel}")
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError(f"asset hash mismatch: {rel}")
    return refs


def main(argv: list[str]) -> int:
    try:
        refs = load_refs()
    except Exception as exc:
        return emit("ENV_INVALID", [{"criterion": "references", "passed": False, "detail": str(exc)}], 2)
    gold, tol, criteria = refs["gold"], refs["tolerances"], refs["criteria"]
    final = Path(argv[1]).resolve() if len(argv) > 1 else Path("/app/final")
    assets = asset_directory()
    early_path, late_path = assets / "frame_early.xyz", assets / "frame_late.xyz"
    if not early_path.is_file() or not late_path.is_file():
        return emit("ENVIRONMENT_ERROR", [{"criterion": "assets", "passed": False, "detail": "frames missing"}], 2)
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"criterion": name, "passed": ok, "detail": detail})

    path = final / refs["output"]
    if not path.is_file():
        add("topology_file_present", False, "missing topology.json")
        return emit("FAIL", checks, 1)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        add("topology_file_present", False, str(exc))
        return emit("FAIL", checks, 1)
    add("topology_file_present", True, "parsed")

    li_cut, o_cut = doc.get("li_li_cutoff_A"), doc.get("li_o_cutoff_A")
    cutoff_ok = num(li_cut) and num(o_cut) and criteria["li_li_cutoff_range_A"][0] <= float(li_cut) <= criteria["li_li_cutoff_range_A"][1] and criteria["li_o_cutoff_range_A"][0] <= float(o_cut) <= criteria["li_o_cutoff_range_A"][1]
    if not cutoff_ok:
        add("cutoffs_and_pbc_graph", False, "cutoffs outside the first-shell window")
        add("late_chains_and_single_frame_limit", False, "graph was not compared")
        return emit("FAIL", checks, 1)
    early = analyze(*load_xyz(early_path), float(li_cut), float(o_cut), criteria)
    late = analyze(*load_xyz(late_path), float(li_cut), float(o_cut), criteria)
    graph_ok = close_block(doc.get("late"), late, tol) and close_block(doc.get("early"), early, tol)
    add("cutoffs_and_pbc_graph", graph_ok, f"late pairs {late['n_contact_pairs']}, max {late['max_component_size']}")
    science_ok = (
        graph_ok
        and doc.get("contacts_share_water") is late["contacts_share_water"]
        and doc.get("anion_can_co_bridge") is late["anion_can_co_bridge"]
        and doc.get("chains_present_in_late_frame") is (late["max_component_size"] >= criteria["chain_component_min"])
        and doc.get("extended_chains_present_at_classical_start") is (early["max_component_size"] >= criteria["extended_component_min"])
        and doc.get("ensemble_population_established") is False
    )
    add("late_chains_and_single_frame_limit", science_ok, "structure judgments follow the selected contact graph; two frames do not establish an ensemble population")
    passed = all(item["passed"] for item in checks)
    return emit("PASS" if passed else "FAIL", checks, 0 if passed else 1)



def harbor_main() -> int:
    """Validate mounted inputs and translate the scientific verifier into Harbor reward protocol."""
    import json
    import os
    import subprocess
    from pathlib import Path

    app = Path(os.environ.get("APP", "/app")).resolve()
    tests = Path(os.environ.get("TESTS", Path(__file__).resolve().parent)).resolve()
    logs = Path(os.environ.get("LOGS", "/logs/verifier")).resolve()
    report_path = logs / "verification.json"
    reward_path = logs / "reward.txt"

    def report(status: str, **extra: object) -> int:
        report_path.write_text(
            json.dumps({"status": status, **extra}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"status": status, **extra}, ensure_ascii=False))
        return 2

    try:
        load_refs()

        verifier = Path(__file__).resolve()
        result = subprocess.run(
            [sys.executable, str(verifier), str(app / "final")],
            capture_output=True, text=True, check=False,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return report("ENV_INVALID", error=f"verifier emitted invalid JSON (rc={result.returncode})")
        status = payload.get("overall") if isinstance(payload, dict) else None
        checks = payload.get("checks") if isinstance(payload, dict) else None
        if (not isinstance(checks, list) or not checks
                or any(not isinstance(check, dict) or not isinstance(check.get("passed"), bool)
                       for check in checks)):
            return report("ENV_INVALID", error="verifier output has no valid checks array")
        checks_passed = all(check["passed"] for check in checks)
        if status == "ENVIRONMENT_ERROR" or result.returncode == 2:
            return report("ENV_INVALID", checks=checks, error="scientific verifier reported unavailable/broken evaluation inputs")
        if status == "PASS" and result.returncode == 0 and checks_passed:
            reward = 1
        elif status == "FAIL" and result.returncode == 1 and not checks_passed:
            reward = 0
        else:
            return report("ENV_INVALID", checks=checks, error=f"verifier status/exit mismatch: {status!r}/{result.returncode}")
        reward_path.write_text(f"{reward}\n", encoding="utf-8")
        report_path.write_text(
            json.dumps({"status": status, "reward": reward, "checks": checks},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return 0
    except Exception as exc:
        return report("ENV_INVALID", error=f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--harbor"]:
        raise SystemExit(harbor_main())
    sys.exit(main(sys.argv))
