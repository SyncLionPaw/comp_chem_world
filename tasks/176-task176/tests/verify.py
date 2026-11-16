#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Compare coordination and angle distributions.
"""Score coordination and angle features using author-labeled windows."""
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


def load_table(path: Path) -> np.ndarray:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rows.append([float(part) for part in line.split()])
    return np.asarray(rows)


def mode_n(table: np.ndarray, column: int) -> int:
    return int(table[np.argmax(table[:, column]), 0])


def angle_mode(table: np.ndarray, lower: float, upper: float) -> float:
    selected = (table[:, 0] > lower) & (table[:, 0] < upper)
    return float(table[np.where(selected)[0][np.argmax(table[selected, 1])], 0])


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
    schema = {'output': 'str', 'assets': [{'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}], 'gold': {'short_contact_window': 'str', 'short_contact_mode_total_cn': 'number', 'average_mode_total_cn': 'number', 'short_contact_cn_higher_than_average': 'bool', 'short_contact_modal_anion_cn': 'number', 'angle_modes_deg': ['number', 'number'], 'acute_mode_tighter_than_bulk_water': 'bool'}, 'tolerances': {'angle_deg': 'number'}, 'criteria': {'acute_angle_range_deg': ['number', 'number'], 'obtuse_angle_range_deg': ['number', 'number'], 'short_contact_window': 'str'}}

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
    needed = ["window_blue.dat", "window_green.dat", "window_red.dat", "window_all.dat",
              "angle_li_ow_li.dat", "angle_bulk_water_exp.dat"]
    if any(not (assets / name).is_file() for name in needed):
        return emit("ENVIRONMENT_ERROR", [{"criterion": "assets", "passed": False, "detail": "histogram missing"}], 2)
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"criterion": name, "passed": ok, "detail": detail})

    path = final / refs["output"]
    if not path.is_file():
        add("solvation_file_present", False, "missing solvation.json")
        return emit("FAIL", checks, 1)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        add("solvation_file_present", False, str(exc))
        return emit("FAIL", checks, 1)
    add("solvation_file_present", True, "parsed")

    blue = load_table(assets / "window_blue.dat")
    average = load_table(assets / "window_all.dat")
    angles = load_table(assets / "angle_li_ow_li.dat")
    bulk = load_table(assets / "angle_bulk_water_exp.dat")
    mode_ok = (
        doc.get("short_contact_mode_total_cn") == mode_n(blue, 1)
        and doc.get("average_mode_total_cn") == mode_n(average, 1)
        and doc.get("short_contact_modal_anion_cn") == mode_n(blue, 2)
    )
    add("histogram_modes", mode_ok, f"blue total mode {mode_n(blue, 1)}, anion mode {mode_n(blue, 2)}")

    modes = doc.get("angle_modes_deg")
    acute_peak = angle_mode(angles, *criteria["acute_angle_range_deg"])
    obtuse_peak = angle_mode(angles, *criteria["obtuse_angle_range_deg"])
    bulk_peak = float(bulk[np.argmax(bulk[:, 1]), 0])
    angle_ok = (
        isinstance(modes, list) and len(modes) == 2 and all(num(x) for x in modes)
        and abs(float(modes[0]) - acute_peak) <= tol["angle_deg"]
        and abs(float(modes[1]) - obtuse_peak) <= tol["angle_deg"]
    )
    science_ok = (
        doc.get("short_contact_window") == criteria["short_contact_window"]
        and mode_ok
        and doc.get("short_contact_cn_higher_than_average") is True
        and mode_n(blue, 1) > mode_n(average, 1)
        and angle_ok
        and doc.get("acute_mode_tighter_than_bulk_water") is (acute_peak < bulk_peak)
    )
    add("contact_shell_and_angle", science_ok,
        f"trajectory acute/obtuse modes {acute_peak:.1f}/{obtuse_peak:.1f}°; bulk-water mode {bulk_peak:.1f}°")
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
