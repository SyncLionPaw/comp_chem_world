#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Characterize Li–Li RDF features and comparison curves.
"""Score the Li-Li environment and literature comparison."""
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


def load_xy(path: Path, scale: float) -> tuple[np.ndarray, np.ndarray]:
    xs, ys = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.replace(";", " ").split()
        if len(parts) < 2:
            continue
        xs.append(float(parts[0]) * scale)
        ys.append(float(parts[1]))
    return np.asarray(xs), np.asarray(ys)


def local_maxima(r: np.ndarray, g: np.ndarray) -> list[tuple[float, float]]:
    """Return peaks after sorting and averaging samples at identical distances."""
    order = np.argsort(r, kind="stable")
    r, g = r[order], g[order]
    unique_r, inverse = np.unique(r, return_inverse=True)
    sums = np.bincount(inverse, weights=g)
    counts = np.bincount(inverse)
    unique_g = sums / counts
    return [
        (float(unique_r[i]), float(unique_g[i]))
        for i in range(1, len(unique_r) - 1)
        if unique_g[i] > unique_g[i - 1] and unique_g[i] >= unique_g[i + 1]
    ]


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
    schema = {'output': 'str', 'assets': [{'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}], 'gold': {'r_first_maximum_A': 'number', 'g_first_maximum': 'number', 'r_boundary_I_II_A': 'number', 'r_boundary_II_III_A': 'number', 'barrier_I_II_kcal_mol': 'number', 'barrier_comparable_to_kT': 'bool', 'curves_with_maximum_below_3A_and_g_at_least_0.6': ['str', 'str'], 'any_literature_curve_matches_aimd_peak_near_2.5A': 'bool'}, 'tolerances': {'peak_position_A': 'number', 'peak_height': 'number', 'boundary_A': 'number', 'barrier_kcal_mol': 'number', 'literature_position_A': 'number', 'literature_height_relative': 'number'}, 'criteria': {'temperature_K': 'number', 'rdf_scale': 'number', 'peak_window_A': ['number', 'number'], 'well_window_A': ['number', 'number'], 'saddle_window_A': ['number', 'number'], 'second_trough_window_A': ['number', 'number'], 'positive_g_min': 'number', 'literature_maximum_A': 'number', 'literature_minimum_g': 'number', 'barrier_kT_range': ['number', 'number'], 'literature_scales': {'mendez-morales.dat': 'number', 'li-zhujie.dat': 'number', 'triolo.dat': 'number', 'cheng-yu.dat': 'number', 'kuhnel-reber.dat': 'number'}}}

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
    KB_KCAL = criteria["temperature_K"] * 8.314462618 / 1000.0 / 4.184
    EXPECTED = set(gold["curves_with_maximum_below_3A_and_g_at_least_0.6"])
    assets = asset_directory()
    rdf = assets / "li_li_rdf_this_work.csv"
    if not rdf.is_file():
        return emit("ENVIRONMENT_ERROR", [{"criterion": "assets", "passed": False, "detail": "rdf missing"}], 2)
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"criterion": name, "passed": ok, "detail": detail})

    path = final / refs["output"]
    if not path.is_file():
        add("environments_file_present", False, "missing environments.json")
        return emit("FAIL", checks, 1)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        add("environments_file_present", False, str(exc))
        return emit("FAIL", checks, 1)
    add("environments_file_present", True, "parsed")
    legacy_key = "any_literature_curve_matches_aimd_peak_near_2.5A"
    scientific_key = "any_comparison_curve_matches_contact_peak"
    if scientific_key in doc:
        if legacy_key in doc and doc[legacy_key] is not doc[scientific_key]:
            add("comparison_consistency", False, "conflicting contact-peak comparison declarations")
            return emit("FAIL", checks, 1)
        doc[legacy_key] = doc[scientific_key]

    r, g = load_xy(rdf, criteria["rdf_scale"])
    order = np.argsort(r, kind="stable")
    r, g = r[order], g[order]
    window = (r > criteria["peak_window_A"][0]) & (r < criteria["peak_window_A"][1])
    peak_i = np.where(window)[0][np.argmax(g[window])]
    units_ok = (
        num(doc.get("r_first_maximum_A"))
        and abs(float(doc["r_first_maximum_A"]) - float(r[peak_i])) <= tol["peak_position_A"]
        and num(doc.get("g_first_maximum"))
        and abs(float(doc["g_first_maximum"]) - float(g[peak_i])) <= tol["peak_height"]
    )
    add("unit_conversion_applied", units_ok, f"author contact at {r[peak_i]:.3f} Å, g={g[peak_i]:.3f}")

    ok = g > criteria["positive_g_min"]
    free = np.full_like(g, np.nan)
    free[ok] = -np.log(g[ok]) * KB_KCAL
    well = (r > criteria["well_window_A"][0]) & (r < criteria["well_window_A"][1]) & ok
    saddle = (r > criteria["saddle_window_A"][0]) & (r < criteria["saddle_window_A"][1]) & ok
    barrier = float(np.nanmax(free[saddle]) - np.nanmin(free[well]))
    curves = doc.get("curves_with_maximum_below_3A_and_g_at_least_0.6")
    reported = {str(item) for item in curves} if isinstance(curves, list) else set()
    literature = criteria["literature_scales"]
    recomputed = set()
    for name, scale in literature.items():
        rr, gg = load_xy(assets / "literature" / name, scale)
        qualifying = [(x, y) for x, y in local_maxima(rr, gg) if x < criteria["literature_maximum_A"] and y >= criteria["literature_minimum_g"]]
        if qualifying:
            recomputed.add(name)
    if recomputed != EXPECTED:
        return emit("ENVIRONMENT_ERROR", checks + [{"criterion": "literature_reference", "passed": False,
                                                    "detail": f"recomputed {sorted(recomputed)}"}], 2)
    trough_one = (r > criteria["saddle_window_A"][0]) & (r < criteria["saddle_window_A"][1])
    trough_two = (r > criteria["second_trough_window_A"][0]) & (r < criteria["second_trough_window_A"][1])
    i_one = np.where(trough_one)[0][np.argmin(g[trough_one])]
    i_two = np.where(trough_two)[0][np.argmin(g[trough_two])]
    kbt = KB_KCAL
    matching_literature = any(
        abs(x - float(r[peak_i])) <= tol["literature_position_A"]
        and abs(y / float(g[peak_i]) - 1.0) <= tol["literature_height_relative"]
        for name, scale in literature.items()
        for x, y in local_maxima(*load_xy(assets / "literature" / name, scale))
        if x < criteria["literature_maximum_A"] and y >= criteria["literature_minimum_g"]
    )
    science_ok = (
        num(doc.get("r_boundary_I_II_A")) and abs(float(doc["r_boundary_I_II_A"]) - float(r[i_one])) <= tol["boundary_A"]
        and num(doc.get("r_boundary_II_III_A")) and abs(float(doc["r_boundary_II_III_A"]) - float(r[i_two])) <= tol["boundary_A"]
        and num(doc.get("barrier_I_II_kcal_mol")) and abs(float(doc["barrier_I_II_kcal_mol"]) - barrier) <= tol["barrier_kcal_mol"]
        and doc.get("barrier_comparable_to_kT") is (criteria["barrier_kT_range"][0] <= barrier / kbt <= criteria["barrier_kT_range"][1])
        and reported == EXPECTED
        and doc.get("any_literature_curve_matches_aimd_peak_near_2.5A") is matching_literature
    )
    add("contact_barrier_and_literature", science_ok,
        f"author peak {r[peak_i]:.3f} Å, g={g[peak_i]:.3f}; minima {r[i_one]:.3f}/{r[i_two]:.3f} Å; "
        f"barrier {barrier:.3f} kcal/mol ({barrier / kbt:.2f} kT); literature maxima {sorted(EXPECTED)}; match={matching_literature}")
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
