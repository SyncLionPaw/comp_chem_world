#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Compare total X-ray scattering curves.
"""Score the X-ray S(q) comparison and its specificity limit."""
from __future__ import annotations

import json
import math
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


def load_columns(path: Path, q_scale: float) -> tuple[np.ndarray, np.ndarray]:
    q, y = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.replace(";", " ").split()
        q.append(float(parts[0]) * q_scale)
        y.append(float(parts[1]))
    q, y = np.asarray(q), np.asarray(y)
    order = np.argsort(q, kind="stable")
    q, y = q[order], y[order]
    unique_q, inverse = np.unique(q, return_inverse=True)
    mean_y = np.bincount(inverse, weights=y) / np.bincount(inverse)
    return unique_q, mean_y


def rmse(exp_q, exp_y, calc_q, calc_y, shift: float) -> float:
    criteria = load_refs()["criteria"]
    grid = np.linspace(*criteria["q_range_Ainv"], int(criteria["grid_samples"]))
    exp = np.interp(grid, exp_q, exp_y) + shift
    calc = np.interp(grid, calc_q, calc_y)
    return float(np.sqrt(np.mean((exp - calc) ** 2)))


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
    schema = {'output': 'str', 'assets': [{'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}], 'gold': {'experimental_vertical_shift': 'number', 'q_min_Ainv': 'number', 'q_max_Ainv': 'number', 'rmse_unshifted': 'number', 'rmse_shifted': 'number', 'qualitative_agreement': 'bool', 'total_s_uniquely_proves_short_li_chains': 'bool', 'rationale': 'str'}, 'tolerances': {'shift': 'number', 'q_Ainv': 'number', 'rmse': 'number'}, 'criteria': {'q_range_Ainv': ['number', 'number'], 'grid_samples': 'number', 'experiment_q_scale': 'number', 'calculation_q_scale': 'number', 'agreement_rmse': 'number'}}

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
    exp_path, calc_path = assets / "saxs_experiment.dat", assets / "sfac_xray_calc.csv"
    if not exp_path.is_file() or not calc_path.is_file():
        return emit("ENVIRONMENT_ERROR", [{"criterion": "assets", "passed": False, "detail": "scattering files missing"}], 2)
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"criterion": name, "passed": ok, "detail": detail})

    path = final / refs["output"]
    if not path.is_file():
        add("scattering_file_present", False, "missing scattering.json")
        return emit("FAIL", checks, 1)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        add("scattering_file_present", False, str(exc))
        return emit("FAIL", checks, 1)
    add("scattering_file_present", True, "parsed")

    exp_q, exp_y = load_columns(exp_path, criteria["experiment_q_scale"])
    calc_q, calc_y = load_columns(calc_path, criteria["calculation_q_scale"])
    raw = rmse(exp_q, exp_y, calc_q, calc_y, 0.0)
    grid = np.linspace(*criteria["q_range_Ainv"], int(criteria["grid_samples"]))
    best_shift = float(np.mean(np.interp(grid, calc_q, calc_y) - np.interp(grid, exp_q, exp_y)))
    best_shifted = rmse(exp_q, exp_y, calc_q, calc_y, best_shift)
    shift = doc.get("experimental_vertical_shift")
    shifted = rmse(exp_q, exp_y, calc_q, calc_y, float(shift)) if num(shift) else math.nan
    q_min = doc.get("q_min_Ainv")
    q_max = doc.get("q_max_Ainv")
    alignment_ok = (
        num(shift) and abs(float(shift) - best_shift) <= tol["shift"]
        and num(q_min) and math.isfinite(float(q_min)) and abs(float(q_min) - criteria["q_range_Ainv"][0]) <= tol["q_Ainv"]
        and num(q_max) and math.isfinite(float(q_max)) and abs(float(q_max) - criteria["q_range_Ainv"][1]) <= tol["q_Ainv"]
        and num(doc.get("rmse_unshifted")) and abs(float(doc["rmse_unshifted"]) - raw) <= tol["rmse"]
        and num(doc.get("rmse_shifted")) and abs(float(doc["rmse_shifted"]) - shifted) <= tol["rmse"]
    )
    add("q_axis_and_shift", alignment_ok, f"raw RMSE {raw:.3f}, shifted RMSE {shifted:.3f}")
    rationale = doc.get("rationale")
    science_ok = (
        alignment_ok
        and doc.get("qualitative_agreement") is (best_shifted <= criteria["agreement_rmse"])
        and doc.get("total_s_uniquely_proves_short_li_chains") is False
        and isinstance(rationale, str)
        and bool(rationale.strip())
    )
    add("agreement_without_chain_proof", science_ok,
        f"best-offset RMSE {best_shifted:.3f} (reference agreement cutoff); total scattering does not identify the short Li-Li contact")
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
