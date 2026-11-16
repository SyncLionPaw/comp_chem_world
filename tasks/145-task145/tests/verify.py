# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Propagate the supplied exciton network.
"""Scorer for probability-conserving exciton kinetics and independent reruns."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import shlex
import stat
import subprocess
import sys
import tempfile


EXPECTED = json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))["inputs"]
ACCEPTANCE = json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))["acceptance"]
RTOL, ATOL = ACCEPTANCE["rtol"], ACCEPTANCE["atol"]


class EnvironmentError(RuntimeError):
    pass


def _close(actual, expected, *, rtol=RTOL, atol=ATOL, label="value"):
    try:
        import numpy as np
    except ImportError as exc:
        raise EnvironmentError("NumPy is required by the scorer") from exc
    a, e = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    if a.shape != e.shape or not np.isfinite(a).all() or not np.allclose(a, e, rtol=rtol, atol=atol):
        raise ValueError(f"{label}: numerical mismatch or non-finite value")
    return float(np.max(np.abs(a-e))) if a.size else 0.0


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assets(app: Path) -> dict:
    inputs = app / "inputs"
    for name, digest in EXPECTED.items():
        path = inputs / name
        if path.is_symlink() or not path.is_file() or _sha(path) != digest:
            raise EnvironmentError(f"evaluation input missing or damaged: {name}")
    return json.loads((inputs / "benchmark.json").read_text(encoding="utf-8"))


def _run(script: Path, cfg: dict, root: Path, *, filename="solver.py", argv=()) -> tuple[subprocess.CompletedProcess, dict | None]:
    scratch = root / "scratch"
    if scratch.exists():
        shutil.rmtree(scratch)
    (scratch / "final").mkdir(parents=True)
    (scratch / "inputs").mkdir(parents=True)
    shutil.copy2(script, scratch / "final" / filename)
    (scratch / "inputs" / "benchmark.json").write_text(json.dumps(cfg), encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(root),
           "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
    mapped_argv = _retarget_app_paths(argv, scratch)
    run = subprocess.run([sys.executable, f"final/{filename}", *mapped_argv], cwd=scratch,
                         env=env, capture_output=True, text=True, timeout=120)
    _assert_replay_tree(scratch)
    result_path = _select_replay_result(scratch)
    if result_path is None:
        return run, None
    try:
        return run, json.loads(result_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"solver wrote invalid result.json: {exc}") from exc


def _assert_replay_tree(scratch: Path) -> None:
    for path, label in ((scratch, "scratch root"), (scratch / "inputs", "inputs directory"),
                        (scratch / "final", "final directory")):
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError as exc:
            raise ValueError(f"missing replay {label}") from exc
        if not stat.S_ISDIR(mode):
            raise ValueError(f"unsafe replay {label}")


def _select_replay_result(scratch: Path) -> Path | None:
    """Select either supported app-root or final-adjacent result output safely."""
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
        raise ValueError("conflicting replay result files")
    # The root-level form is the historical app-cwd output; use it first if both
    # locations contain identical bytes. Scratch is recreated for every replay.
    return present[0] if present else None


def _retarget_app_paths(argv, root: Path) -> list[str]:
    """Map recorded /app paths into the isolated application-shaped replay tree."""
    mapped = []
    for raw in argv:
        if not isinstance(raw, str):
            raise ValueError("replay argv entries must be strings")
        def replace(match):
            suffix = match.group(1)
            parts = Path(suffix.lstrip("/")).parts
            if any(part == ".." for part in parts):
                raise ValueError("replay command path escapes the application root")
            return str(root.joinpath(*[part for part in parts if part not in ("", ".")]))
        mapped.append(re.sub(r"(?<![A-Za-z0-9_.-])/app(?=(?:/|$))((?:/[^\s,'\"]*)?)", replace, raw))
    return mapped


def _command_parts(value) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            argv = shlex.split(value)
        except ValueError as exc:
            raise ValueError(f"invalid command record: {exc}") from exc
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        argv = list(value)
    else:
        raise ValueError("command records must be argv lists or shell-free command strings")
    if argv[:2] == ["/usr/bin/env", "-S"]:
        argv = shlex.split(" ".join(argv[2:]))
    elif argv and Path(argv[0]).name == "env":
        argv = argv[1:]
    if len(argv) < 2:
        raise ValueError("command record must identify a Python script")
    exe = Path(argv[0]).name.lower()
    if exe not in {"python", "python3", Path(sys.executable).name.lower()} and not exe.startswith("python3."):
        raise ValueError("source replay must use Python")
    return (Path(argv[1]).name, *argv[2:])


def _comparison_source(final: Path, script_name: str) -> Path:
    if script_name not in {"solver.py", "convergence_solver.py"}:
        raise ValueError("comparison replay script must be solver.py or convergence_solver.py")
    source = Path(final) / script_name
    if source.is_symlink() or not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"comparison replay source is missing, empty, or unsafe: {script_name}")
    return source


def _read(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required output is missing: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return value


def _compare_result(actual: dict, expected: dict, label: str) -> float:
    if actual.get("times_s") != expected.get("times_s"):
        raise ValueError(f"{label}: times_s differ from the requested input")
    deltas = [_close(actual.get("populations"), expected.get("populations"), label=f"{label} populations")]
    keys = ("fluorescence", "phosphorescence_T1", "phosphorescence_T2", "nonradiative", "total_PLQY")
    try:
        deltas.append(_close([actual["yields"][k] for k in keys],
                             [expected["yields"][k] for k in keys], label=f"{label} yields"))
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{label}: missing or invalid yield fields") from exc
    return max(deltas)


def grade(app: Path, final: Path) -> dict:
    app, final = Path(app), Path(final)
    try:
        cfg = _assets(app)
        script = final / "solver.py"
        if script.is_symlink() or not script.is_file():
            raise ValueError("final/solver.py is required")
        candidate = _read(final / "result.json")
        evidence = _read(final / "convergence.json")
        concise_runs = "runs" in evidence
        if concise_runs:
            runs = evidence.get("runs")
            if not isinstance(runs, list) or len(runs) != 2:
                raise ValueError("convergence.json runs must contain exactly two executed settings")
            if any(not isinstance(item, dict)
                   or not isinstance(item.get("method"), str) or not item["method"].strip()
                   or "command" not in item for item in runs):
                raise ValueError("each run must contain a nonempty method and executed command")
            parsed_runs = [_command_parts(item["command"]) for item in runs]
            if parsed_runs[0][0] != "solver.py":
                raise ValueError("the first convergence run must execute solver.py")
            if parsed_runs[1][0] not in {"solver.py", "convergence_solver.py"}:
                raise ValueError("the second run must execute solver.py or convergence_solver.py")
            approach = "second_solver" if runs[0]["method"] != runs[1]["method"] else "refined_tolerance"
            settings = []
            for item in runs:
                setting = {"method": item["method"], "command": item["command"]}
                if approach == "refined_tolerance":
                    setting["rtol"] = item.get("rtol")
                    setting["atol"] = item.get("atol")
                settings.append(setting)
            evidence = dict(evidence)
            evidence["schema_version"] = "1.0"
            evidence["commands"] = [runs[0]["command"]]
            evidence["convergence_comparison"] = {
                "approach": approach,
                "settings": settings,
                "replay": {"script": parsed_runs[1][0], "command": runs[1]["command"]},
            }
        commands = evidence.get("commands")
        if not isinstance(commands, list) or not commands:
            raise ValueError("convergence.json must record a reproducible baseline command")
        baseline_command = _command_parts(commands[0])
        if baseline_command[0] != "solver.py":
            raise ValueError("the recorded baseline command must execute final/solver.py")
        try:
            reference_api = _make_exciton_reference()
            calculate = reference_api.calculate
            calculate_bdf = reference_api.calculate_bdf
            generator = reference_api.generator
        except ImportError as exc:
            raise EnvironmentError("SciPy author reference dependencies are unavailable") from exc
        reference = calculate(cfg)
        bdf_reference = calculate_bdf(cfg)
        ref_delta = _compare_result(candidate, reference, "candidate")
        independent_reference_delta = _compare_result(bdf_reference, reference, "independent BDF reference")
        if independent_reference_delta > ATOL:
            raise ValueError("independent expm/BDF reference disagreement exceeds tolerance")
        import numpy as np
        a = generator(cfg["rates_s1"])
        tail = float(np.sum(__import__("scipy").linalg.expm(a * cfg["times_s"][-1]) @ np.array([1., 0., 0.])))
        residual = float(np.max(np.abs(np.sum(np.asarray(candidate["populations"], dtype=float), axis=1)-1)))

        with tempfile.TemporaryDirectory(prefix="exciton-grade-") as raw:
            root = Path(raw)
            replay_run, replay_result = _run(script, cfg, root, argv=baseline_command[1:])
            if replay_run.returncode != 0 or replay_result is None:
                raise ValueError(f"solver replay failed (rc={replay_run.returncode}): {replay_run.stderr[-1000:]}")
            replay_delta = _compare_result(replay_result, reference, "solver replay")
            _compare_result(candidate, replay_result, "candidate/replay")

            zero_cfg = json.loads(json.dumps(cfg))
            zero_cfg["rates_s1"]["isc1"] = 0.0
            zero_cfg["rates_s1"]["isc2"] = 0.0
            zero_run, zero_result = _run(script, zero_cfg, root, argv=baseline_command[1:])
            if zero_run.returncode != 0 or zero_result is None:
                raise ValueError("zero-ISC rerun failed")
            zero_expected = calculate(zero_cfg)
            _compare_result(zero_result, zero_expected, "zero-ISC rerun")
            analytic_f = zero_cfg["rates_s1"]["f"] / (zero_cfg["rates_s1"]["f"] + zero_cfg["rates_s1"]["nrS"])
            zero_delta = max(abs(zero_result["yields"]["fluorescence"]-analytic_f),
                             abs(zero_result["yields"]["phosphorescence_T1"]),
                             abs(zero_result["yields"]["phosphorescence_T2"]))

            scaled_cfg = json.loads(json.dumps(cfg))
            scaled_cfg["rates_s1"] = {key: value*10 for key, value in cfg["rates_s1"].items()}
            scaled_cfg["times_s"] = [value/10 for value in cfg["times_s"]]
            scaled_run, scaled_result = _run(script, scaled_cfg, root, argv=baseline_command[1:])
            if scaled_run.returncode != 0 or scaled_result is None:
                raise ValueError("tenfold-rate rerun failed")
            scaling_delta = _close(scaled_result["populations"], candidate["populations"], label="tenfold rate/time scaling")
            yield_keys = ("fluorescence", "phosphorescence_T1", "phosphorescence_T2", "nonradiative", "total_PLQY")
            _close([scaled_result["yields"][key] for key in yield_keys],
                   [candidate["yields"][key] for key in yield_keys], label="tenfold rate yield invariance")

        if residual > ATOL:
            raise ValueError(f"population closure residual {residual} exceeds {ATOL}")
        if tail < -ATOL or tail > 1+ATOL or ref_delta > ATOL or replay_delta > ATOL:
            raise ValueError("trajectory/tail exceeds the declared convergence tolerance")
        if zero_delta > ATOL or scaling_delta > ATOL:
            raise ValueError("analytic zero-ISC or tenfold rescaling test failed")

        if evidence.get("schema_version") != "1.0" or not all(
                isinstance(evidence.get(key), str) and evidence[key].strip()
                for key in ("solver", "solver_version")):
            raise ValueError("convergence.json must identify the candidate solver and version")
        comparison = evidence.get("convergence_comparison")
        if (not isinstance(comparison, dict)
                or comparison.get("approach") not in {"refined_tolerance", "second_solver"}
                or not isinstance(comparison.get("settings"), list)
                or len(comparison["settings"]) != 2):
            raise ValueError("convergence.json must document exactly two executed convergence settings")
        settings = comparison["settings"]
        if any(not isinstance(item, dict) or not isinstance(item.get("method"), str) or not item.get("method")
               or "command" not in item for item in settings):
            raise ValueError("each convergence setting must declare a method and executable command")
        setting_commands = [_command_parts(item["command"]) for item in settings]
        if setting_commands[0] != baseline_command:
            raise ValueError("first convergence setting command must match the recorded baseline command")
        replay_spec = comparison.get("replay")
        if not isinstance(replay_spec, dict):
            raise ValueError("convergence_comparison.replay must identify an executable second calculation")
        script_name = replay_spec.get("script")
        command = replay_spec.get("command")
        if script_name not in {"solver.py", "convergence_solver.py"}:
            raise ValueError("comparison replay script must be solver.py or convergence_solver.py")
        replay_command = _command_parts(command)
        if replay_command[0] != script_name or replay_command != setting_commands[1]:
            raise ValueError("second convergence setting must exactly identify its executable replay command")
        second_source = _comparison_source(final, script_name)
        baseline_source = final / "solver.py"
        same_execution = (_sha(baseline_source) == _sha(second_source)
                          and baseline_command[1:] == replay_command[1:])
        if same_execution:
            raise ValueError("second convergence setting repeats the baseline source and command")
        first_setting, second_setting = settings
        if comparison["approach"] == "second_solver":
            if first_setting["method"] == second_setting["method"]:
                raise ValueError("second_solver comparison must identify two different methods")
        else:
            if first_setting["method"] != second_setting["method"]:
                raise ValueError("refined_tolerance comparison must retain the same method")
            tolerances = []
            for item in settings:
                pair = []
                for key in ("rtol", "atol"):
                    try:
                        value = float(item[key])
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ValueError("refined_tolerance requires positive rtol and atol in both settings") from exc
                    if not math.isfinite(value) or value <= 0:
                        raise ValueError("refined_tolerance values must be finite and positive")
                    pair.append(value)
                tolerances.append(pair)
            if any(tolerances[1][i] > tolerances[0][i] for i in range(2)) or tolerances[1] == tolerances[0]:
                raise ValueError("second refined-tolerance setting must not loosen either tolerance and must tighten one")
        with tempfile.TemporaryDirectory(prefix="exciton-convergence-grade-") as comparison_raw:
            second_run, second_result = _run(second_source, cfg, Path(comparison_raw), filename=script_name, argv=replay_command[1:])
            if second_run.returncode != 0 or second_result is None:
                raise ValueError(f"comparison replay failed (rc={second_run.returncode}): {second_run.stderr[-1000:]}")
            _compare_result(second_result, reference, "comparison replay")
            _compare_result(second_result, candidate, "comparison/baseline trajectory")
            comparison_delta_actual = _close(second_result.get("populations"), candidate.get("populations"), label="candidate convergence replay")
        if comparison_delta_actual > ATOL:
            raise ValueError("replayed convergence trajectories exceed the required tolerance")
        if not concise_runs:
            try:
                comparison_delta = float(comparison["max_population_delta"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("convergence.json is missing its measured comparison delta") from exc
            if not math.isfinite(comparison_delta) or comparison_delta > ATOL or not math.isclose(comparison_delta, comparison_delta_actual, rel_tol=2e-6, abs_tol=1e-12):
                raise ValueError("convergence comparison delta disagrees with replayed trajectories or exceeds tolerance")
        reported = evidence.get("checks")
        # Reference and replay errors remain independently computed and enforced above;
        # they are verifier diagnostics, not candidate-supplied measurements.
        actual = {"probability_residual": residual, "tail_bound": tail,
                  "zero_isc_analytic_abs_error": zero_delta,
                  "tenfold_rate_time_rescaling_max_abs_error": scaling_delta}
        if not concise_runs or reported is not None:
            if not isinstance(reported, dict):
                raise ValueError("convergence.json quantitative checks are missing")
            for name, value in actual.items():
                if (not concise_runs and name not in reported) or (
                        name in reported and not math.isclose(float(reported[name]), value, rel_tol=2e-6, abs_tol=ATOL)):
                    raise ValueError(f"convergence.json check {name} differs from recomputed value")
        return {"status": "PASS", "reward": 1.0, "exit_code": 0,
                "detail": "Independent matrix and expm/BDF references, source replay, probability closure, tail, zero-ISC, and rate/time scaling passed."}
    except EnvironmentError as exc:
        return {"status": "ENV_INVALID", "reward": None, "exit_code": 2, "detail": str(exc)}
    except ImportError as exc:
        return {"status": "ENV_INVALID", "reward": None, "exit_code": 2, "detail": f"scorer dependency unavailable: {exc}"}
    except Exception as exc:
        return {"status": "FAIL", "reward": 0.0, "exit_code": 1, "detail": str(exc)}


def check(package, candidate):
    return grade(Path(package), Path(candidate))



def _make_exciton_reference():
    from types import SimpleNamespace

    import numpy as np
    from scipy.integrate import solve_ivp
    from scipy.linalg import expm


    def generator(r: dict) -> np.ndarray:
        return np.array([
            [-(r["isc1"] + r["isc2"] + r["f"] + r["nrS"]), r["risc1"], r["risc2"]],
            [r["isc1"], -(r["risc1"] + r["ic12"] + r["ph1"] + r["nr1"]), r["ic21"]],
            [r["isc2"], r["ic12"], -(r["risc2"] + r["ic21"] + r["ph2"] + r["nr2"])],
        ], dtype=float)


    def calculate(cfg: dict) -> dict:
        r = cfg["rates_s1"]
        a = generator(r)
        p0 = np.array([1.0, 0.0, 0.0])
        rows = []
        for time in cfg["times_s"]:
            state = expm(a * float(time)) @ p0
            rows.append([*state.tolist(), float(1 - state.sum())])
        occupancy = np.linalg.solve(-a, p0)
        f = r["f"] * occupancy[0]
        ph1 = r["ph1"] * occupancy[1]
        ph2 = r["ph2"] * occupancy[2]
        nr = r["nrS"] * occupancy[0] + r["nr1"] * occupancy[1] + r["nr2"] * occupancy[2]
        return {
            "times_s": list(cfg["times_s"]),
            "populations": rows,
            "yields": {"fluorescence": f, "phosphorescence_T1": ph1,
                       "phosphorescence_T2": ph2, "nonradiative": nr,
                       "total_PLQY": f + ph1 + ph2},
        }


    def calculate_bdf(cfg: dict) -> dict:
        r = cfg["rates_s1"]
        a = generator(r)
        times = np.asarray(cfg["times_s"], dtype=float)
        solution = solve_ivp(lambda t, y: a @ y, (float(times[0]), float(times[-1])),
                             np.array([1.0, 0.0, 0.0]), t_eval=times, method="BDF",
                             rtol=1e-11, atol=1e-14)
        if not solution.success or solution.y.shape[1] != len(times):
            raise RuntimeError(f"independent BDF reference failed: {solution.message}")
        transient = solution.y.T
        populations = np.column_stack((transient, 1-transient.sum(axis=1)))
        occupancy = np.linalg.solve(-a, np.array([1.0, 0.0, 0.0]))
        f = r["f"]*occupancy[0]
        ph1 = r["ph1"]*occupancy[1]
        ph2 = r["ph2"]*occupancy[2]
        nr = r["nrS"]*occupancy[0]+r["nr1"]*occupancy[1]+r["nr2"]*occupancy[2]
        return {"times_s": list(cfg["times_s"]), "populations": populations.tolist(),
                "yields": {"fluorescence": f, "phosphorescence_T1": ph1,
                           "phosphorescence_T2": ph2, "nonradiative": nr,
                           "total_PLQY": f+ph1+ph2}}
    return SimpleNamespace(calculate=calculate, calculate_bdf=calculate_bdf, generator=generator)

if __name__ == "__main__":
    app = Path(os.environ.get("APP", "/app"))
    outcome = grade(app, app / "final")
    logs = Path(os.environ.get("LOGS", "/logs/verifier"))
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "verification.json").write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
    if outcome["reward"] is not None:
        (logs / "reward.txt").write_text(f"{outcome['reward']}\n", encoding="utf-8")
    elif (logs / "reward.txt").exists():
        (logs / "reward.txt").unlink()
    print(json.dumps(outcome, ensure_ascii=False))
    raise SystemExit(outcome["exit_code"])
