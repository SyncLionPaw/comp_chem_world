# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Calculate emitter transition rates.
"""Scorer for the rate-law kernel, including isolated source replay."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


EXPECTED = json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))["inputs"]
ACCEPTANCE = json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))["acceptance"]
RTOL = ACCEPTANCE["rtol"]
ATOL = ACCEPTANCE["atol"]


class EnvironmentError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _close(actual, target, *, rtol=RTOL, atol=ATOL, label="value"):
    try:
        import numpy as np
    except ImportError as exc:
        raise EnvironmentError("NumPy is required by the scorer") from exc
    left, right = np.asarray(actual, dtype=float), np.asarray(target, dtype=float)
    if left.shape != right.shape or not np.isfinite(left).all() or not np.allclose(left, right, rtol=rtol, atol=atol):
        raise ValueError(f"{label}: numerical mismatch or non-finite value")
    return float(np.max(np.abs(left - right))) if left.size else 0.0


def _assets(app: Path) -> dict:
    inputs = app / "inputs"
    for name, digest in EXPECTED.items():
        path = inputs / name
        if path.is_symlink() or not path.is_file() or _sha(path) != digest:
            raise EnvironmentError(f"evaluation input missing or damaged: {name}")
    return json.loads((inputs / "benchmark.json").read_text(encoding="utf-8"))


def _run(script: Path, cfg: dict, root: Path, *, timeout=60) -> subprocess.CompletedProcess:
    scratch = root / "scratch"
    if scratch.exists():
        shutil.rmtree(scratch)
    (scratch / "final").mkdir(parents=True)
    (scratch / "inputs").mkdir()
    shutil.copy2(script, scratch / "final" / "kernel.py")
    (scratch / "inputs" / "benchmark.json").write_text(json.dumps(cfg), encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(root),
           "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
    result = subprocess.run([sys.executable, "final/kernel.py"], cwd=scratch, env=env,
                             capture_output=True, text=True, timeout=timeout)
    return result


def _replay_output(scratch: Path) -> Path | None:
    """Find one safe replay result in either supported output location."""
    try:
        if not stat.S_ISDIR(scratch.lstat().st_mode):
            raise ValueError("unsafe replay scratch directory")
    except FileNotFoundError:
        raise ValueError("replay scratch directory is missing")
    final_dir = scratch / "final"
    try:
        final_mode = final_dir.lstat().st_mode
    except FileNotFoundError:
        final_mode = None
    if final_mode is not None and not stat.S_ISDIR(final_mode):
        raise ValueError("unsafe replay final directory")
    candidates = (scratch / "result.json", scratch / "final" / "result.json")
    present = []
    for path in candidates:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(mode):
            raise ValueError(f"unsafe replay result file: {path.relative_to(scratch)}")
        present.append(path)
    if len(present) == 2 and present[0].read_bytes() != present[1].read_bytes():
        raise ValueError("ambiguous replay results: both supported locations contain different data")
    return present[0] if present else None


def _replay_result(scratch: Path) -> dict:
    path = _replay_output(scratch)
    if path is None:
        raise ValueError("required replay result is missing")
    return _read_result(path)


def _read_result(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required result file is missing: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _spin_values(rows):
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("spin_rows must be a list of row objects")
    keys = ("T_K", "gap_eV", "soc_cm1", "gamma_cm1", "isc_s1", "risc_s1")
    try:
        return [[row[key] for key in keys] for row in rows]
    except KeyError as exc:
        raise ValueError(f"spin_rows missing field: {exc}") from exc


def _validate_evidence(path: Path, observed: dict) -> None:
    evidence = _read_result(path)
    if {"commands", "baseline_exit_code", "invalid_input_probes"} <= evidence.keys():
        if evidence.get("schema_version", "1.0") != "1.0":
            raise ValueError("validation.json schema_version must be 1.0")
        commands = evidence.get("commands")
        if (not isinstance(commands, list) or not commands
                or not any(isinstance(command, str) and "kernel.py" in command for command in commands)):
            raise ValueError("validation.json must record a reproducible kernel.py command")
        if evidence.get("baseline_exit_code") != 0:
            raise ValueError("validation.json baseline_exit_code must be zero")
        invalid = evidence.get("invalid_input_probes")
        if not isinstance(invalid, list):
            raise ValueError("validation.json invalid_input_probes is missing")
        by_field = {item.get("field"): item for item in invalid if isinstance(item, dict)}
        for field, values in (("temperature_K", (0, -1)), ("gamma_cm1", (0, -1))):
            for value in values:
                item = next((row for row in invalid if isinstance(row, dict)
                             and row.get("field") == field and row.get("value") == value), None)
                if not item or item.get("exit_code", 0) == 0:
                    raise ValueError(f"validation.json does not document rejected {field}={value}")
    checks = evidence.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("validation.json quantitative checks are missing")
    for name, measured in observed.items():
        try:
            claimed = float(checks[name])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"validation.json is missing quantitative check {name}") from exc
        if not math.isfinite(claimed) or not math.isclose(claimed, measured, rel_tol=2e-6, abs_tol=1e-12):
            raise ValueError(f"validation.json check {name} does not match recomputed evidence")


def grade(app: Path, final: Path) -> dict:
    app, final = Path(app), Path(final)
    try:
        cfg = _assets(app)
        script = final / "kernel.py"
        if script.is_symlink() or not script.is_file():
            raise ValueError("final/kernel.py is required")
        candidate = _read_result(final / "result.json")
        try:
            reference_api = _make_rate_reference()
            expected = reference_api.expected
        except ImportError as exc:
            raise EnvironmentError("SciPy/author reference dependencies are unavailable") from exc
        expected_values = expected(cfg)
        _close(candidate.get("radiative_s1"), expected_values["radiative_s1"], label="radiative_s1")
        _close(_spin_values(candidate.get("spin_rows")), _spin_values(expected_values["spin_rows"]), label="spin_rows")
        _close(candidate.get("ic_up_s1"), expected_values["ic_up_s1"], label="ic_up_s1")

        with tempfile.TemporaryDirectory(prefix="rate-kernel-grade-") as temp:
            root = Path(temp)
            replay = _run(script, cfg, root)
            if replay.returncode != 0:
                raise ValueError(f"kernel replay failed (rc={replay.returncode}): {replay.stderr[-1000:]}")
            replayed = _replay_result(root / "scratch")
            for key in expected_values:
                if key == "spin_rows":
                    _close(_spin_values(replayed.get(key)), _spin_values(expected_values[key]), label=f"replayed {key}")
                    _close(_spin_values(candidate.get(key)), _spin_values(replayed.get(key)), label=f"candidate/replay {key}")
                else:
                    _close(replayed.get(key), expected_values[key], label=f"replayed {key}")
                    _close(candidate.get(key), replayed.get(key), label=f"candidate/replay {key}")

            # A valid unseen configuration prevents a hard-coded baseline from passing.
            probe_cfg = {
                "provenance": "Verifier-generated held-out valid configuration",
                "temperature_K": [223, 417], "signed_gap_eV": [-0.117, 0.041],
                "soc_cm1": [0.0, 1.37, 3.2], "gamma_cm1": [317.0, 711.0],
                "radiative": [{"gap_eV": 2.13, "dipole_au": 0.73, "n_ref": 1.41},
                              {"gap_eV": 3.41, "dipole_au": 1.12, "n_ref": 1.67}],
                "ic": [{"down_s1": 7.3e7, "gap_eV": 0.071, "temperature_K": 417.0},
                       {"down_s1": 1.21e8, "gap_eV": 0.19, "temperature_K": 223.0}],
            }
            probe_run = _run(script, probe_cfg, root)
            if probe_run.returncode != 0:
                raise ValueError(f"kernel failed held-out valid-input replay (rc={probe_run.returncode})")
            probe_result = _replay_result(root / "scratch")
            probe_expected = expected(probe_cfg)
            _close(probe_result.get("radiative_s1"), probe_expected["radiative_s1"], label="held-out radiative_s1")
            _close(_spin_values(probe_result.get("spin_rows")), _spin_values(probe_expected["spin_rows"]), label="held-out spin_rows")
            _close(probe_result.get("ic_up_s1"), probe_expected["ic_up_s1"], label="held-out ic_up_s1")

            for field in ("temperature_K", "gamma_cm1"):
                for bad_value in (0, -1):
                    invalid_cfg = json.loads(json.dumps(cfg))
                    invalid_cfg[field][0] = bad_value
                    invalid_run = _run(script, invalid_cfg, root)
                    invalid_output = _replay_output(root / "scratch")
                    if invalid_run.returncode == 0 or invalid_output is not None:
                        raise ValueError(f"kernel must reject {field}={bad_value} without writing a result")

        # Independently test zero SOC, quadratic SOC scaling and thermal detailed balance.
        zero_soc_max = 0.0
        balance_errors = []
        for row in candidate["spin_rows"]:
            if row["soc_cm1"] == 0 and (row["isc_s1"] != 0 or row["risc_s1"] != 0):
                raise ValueError("zero SOC must give zero ISC and RISC")
            if row["soc_cm1"] == 0:
                zero_soc_max = max(zero_soc_max, abs(row["isc_s1"]), abs(row["risc_s1"]))
            if row["isc_s1"] > 0 and row["risc_s1"] > 0:
                ratio = row["risc_s1"] / row["isc_s1"]
                try:
                    import scipy.constants as C
                except ImportError as exc:
                    raise EnvironmentError("SciPy is required by the scorer") from exc
                target = math.exp(-row["gap_eV"] * C.e / (C.k * row["T_K"])) / 3
                _close(ratio, target, rtol=2e-7, atol=1e-12, label="detailed balance")
                balance_errors.append(abs(ratio / target - 1))
        scale_ratios = []
        for t in sorted({r["T_K"] for r in candidate["spin_rows"]}):
            for gap in sorted({r["gap_eV"] for r in candidate["spin_rows"]}):
                for gamma in sorted({r["gamma_cm1"] for r in candidate["spin_rows"]}):
                    lookup = {(r["T_K"], r["gap_eV"], r["soc_cm1"], r["gamma_cm1"]): r for r in candidate["spin_rows"]}
                    low = lookup[(t, gap, 0.5, gamma)]["isc_s1"]
                    high = lookup[(t, gap, 5.0, gamma)]["isc_s1"]
                    ratio = high / low if low else 0.0
                    scale_ratios.append(ratio)
                    _close(ratio, 100.0,
                           rtol=2e-7, atol=1e-12, label="SOC-squared scaling")
        checks = {
            "zero_soc_max_abs_s-1": zero_soc_max,
            "soc_squared_ratio_min": min(scale_ratios),
            "soc_squared_ratio_max": max(scale_ratios),
            "detailed_balance_max_relative_error": max(balance_errors, default=0.0),
        }
        validation = final / "validation.json"
        if validation.exists() or validation.is_symlink():
            _validate_evidence(validation, checks)
        return {"status": "PASS", "reward": 1.0, "exit_code": 0,
                "detail": "Independent SI values, isolated code replay, invalid-input rejection and rate-law invariants passed."}
    except EnvironmentError as exc:
        return {"status": "ENV_INVALID", "reward": None, "exit_code": 2, "detail": str(exc)}
    except Exception as exc:
        return {"status": "FAIL", "reward": 0.0, "exit_code": 1, "detail": str(exc)}


def check(package, candidate):
    return grade(Path(package), Path(candidate))



def _make_rate_reference():
    from types import SimpleNamespace

    import math
    from scipy import constants as C


    def radiative_rate(gap_ev: float, dipole_au: float, refractive_index: float) -> float:
        energy = gap_ev * C.e
        dipole = dipole_au * C.e * C.physical_constants["Bohr radius"][0]
        n = refractive_index
        return energy**3 * dipole**2 / (3 * math.pi * C.epsilon_0 * C.hbar**4 * C.c**3) * n * (n*n + 2)**2 / 9


    def spin_rates(temperature_k: float, gap_ev: float, soc_cm1: float, gamma_cm1: float) -> tuple[float, float]:
        conversion = C.h * C.c * 100
        gap = gap_ev * C.e
        coupling = soc_cm1 * conversion
        width = gamma_cm1 * conversion
        lorentzian = 2 * coupling**2 * width / (C.hbar * (gap**2 + width**2))
        thermal = math.exp(-abs(gap) / (C.k * temperature_k))
        isc = lorentzian if gap_ev >= 0 else lorentzian * thermal
        risc = lorentzian * thermal / 3 if gap_ev >= 0 else lorentzian / 3
        return isc, risc


    def expected(cfg: dict) -> dict:
        return {
            "radiative_s1": [radiative_rate(row["gap_eV"], row["dipole_au"], row["n_ref"])
                             for row in cfg["radiative"]],
            "spin_rows": [
                {"T_K": t, "gap_eV": gap, "soc_cm1": soc, "gamma_cm1": gamma,
                 "isc_s1": spin_rates(t, gap, soc, gamma)[0],
                 "risc_s1": spin_rates(t, gap, soc, gamma)[1]}
                for t in cfg["temperature_K"] for gap in cfg["signed_gap_eV"]
                for soc in cfg["soc_cm1"] for gamma in cfg["gamma_cm1"]
            ],
            "ic_up_s1": [row["down_s1"] * math.exp(-row["gap_eV"] * C.e /
                                                       (C.k * row["temperature_K"]))
                         for row in cfg["ic"]],
        }
    return SimpleNamespace(expected=expected)

if __name__ == "__main__":
    outcome = grade(Path(os.environ.get("APP", "/app")),
                    Path(os.environ.get("APP", "/app")) / "final")
    logs = Path(os.environ.get("LOGS", "/logs/verifier"))
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "verification.json").write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
    if outcome["reward"] is not None:
        (logs / "reward.txt").write_text(f"{outcome['reward']}\n", encoding="utf-8")
    elif (logs / "reward.txt").exists():
        (logs / "reward.txt").unlink()
    print(json.dumps(outcome, ensure_ascii=False))
    raise SystemExit(outcome["exit_code"])
