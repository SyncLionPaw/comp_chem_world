#!/bin/bash
set -euo pipefail
RUNTIME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/bench22-runtime.XXXXXXXX")"
trap 'rm -rf "${RUNTIME_DIR}"' EXIT
cat > "${RUNTIME_DIR}/solver.py" <<'BENCH22_EMBED_SOLVER_PY'
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.linalg import expm


def generator(r):
    return np.array([
        [-(r["isc1"]+r["isc2"]+r["f"]+r["nrS"]), r["risc1"], r["risc2"]],
        [r["isc1"], -(r["risc1"]+r["ic12"]+r["ph1"]+r["nr1"]), r["ic21"]],
        [r["isc2"], r["ic12"], -(r["risc2"]+r["ic21"]+r["ph2"]+r["nr2"])],
    ], dtype=float)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=("expm", "BDF"), default="expm")
    args = parser.parse_args()
    cfg = json.loads(Path("inputs/benchmark.json").read_text(encoding="utf-8"))
    a = generator(cfg["rates_s1"])
    p0 = np.array([1.0, 0.0, 0.0])
    times = np.asarray(cfg["times_s"], dtype=float)
    if args.method == "expm":
        transient = np.array([expm(a * t) @ p0 for t in times])
    else:
        run = solve_ivp(lambda t, y: a @ y, (float(times[0]), float(times[-1])), p0,
                        t_eval=times, method="BDF", rtol=1e-11, atol=1e-14)
        if not run.success or run.y.shape[1] != len(times):
            raise RuntimeError(f"BDF failed: {run.message}")
        transient = run.y.T
    populations = np.column_stack((transient, 1-transient.sum(axis=1)))
    occupancy = np.linalg.solve(-a, p0)
    r = cfg["rates_s1"]
    fluorescence = r["f"] * occupancy[0]
    ph1 = r["ph1"] * occupancy[1]
    ph2 = r["ph2"] * occupancy[2]
    nonradiative = r["nrS"]*occupancy[0] + r["nr1"]*occupancy[1] + r["nr2"]*occupancy[2]
    result = {
        "times_s": cfg["times_s"],
        "populations": populations.tolist(),
        "yields": {"fluorescence": float(fluorescence), "phosphorescence_T1": float(ph1),
                   "phosphorescence_T2": float(ph2), "nonradiative": float(nonradiative),
                   "total_PLQY": float(fluorescence+ph1+ph2)},
    }
    Path("result.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
BENCH22_EMBED_SOLVER_PY
cat > "${RUNTIME_DIR}/validation.py" <<'BENCH22_EMBED_VALIDATION_PY'
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import scipy
from scipy.linalg import expm


def run(script, cfg, root, method):
    case = root / method
    if case.exists():
        shutil.rmtree(case)
    (case / "inputs").mkdir(parents=True)
    shutil.copy2(script, case / "solver.py")
    (case / "inputs/benchmark.json").write_text(json.dumps(cfg), encoding="utf-8")
    proc = subprocess.run([sys.executable, "solver.py", "--method", method], cwd=case,
                          capture_output=True, text=True, timeout=120)
    result = json.loads((case / "result.json").read_text()) if (case / "result.json").is_file() else None
    return proc, result


script, benchmark, output = map(Path, sys.argv[1:4])
cfg = json.loads(benchmark.read_text(encoding="utf-8"))
baseline = json.loads((script.parent / "result.json").read_text(encoding="utf-8"))
r = cfg["rates_s1"]
a = np.array([
    [-(r["isc1"]+r["isc2"]+r["f"]+r["nrS"]), r["risc1"], r["risc2"]],
    [r["isc1"], -(r["risc1"]+r["ic12"]+r["ph1"]+r["nr1"]), r["ic21"]],
    [r["isc2"], r["ic12"], -(r["risc2"]+r["ic21"]+r["ph2"]+r["nr2"])],
])
residual = float(np.max(np.abs(np.sum(np.asarray(baseline["populations"]), axis=1)-1)))
tail = float(np.sum(expm(a*cfg["times_s"][-1]) @ np.array([1., 0., 0.])))
with tempfile.TemporaryDirectory(prefix="exciton-validation-") as raw:
    root = Path(raw)
    independent_proc, independent = run(script, cfg, root, "BDF")
    if independent_proc.returncode != 0 or independent is None:
        raise SystemExit("BDF independent calculation failed")
    method_delta = float(np.max(np.abs(np.asarray(independent["populations"])-np.asarray(baseline["populations"]))))

    zero = json.loads(json.dumps(cfg))
    zero["rates_s1"]["isc1"] = 0.0
    zero["rates_s1"]["isc2"] = 0.0
    zero_proc, zero_result = run(script, zero, root, "expm")
    if zero_proc.returncode != 0 or zero_result is None:
        raise SystemExit("zero-ISC check failed")
    analytic = zero["rates_s1"]["f"]/(zero["rates_s1"]["f"]+zero["rates_s1"]["nrS"])
    zero_delta = max(abs(zero_result["yields"]["fluorescence"]-analytic),
                     abs(zero_result["yields"]["phosphorescence_T1"]),
                     abs(zero_result["yields"]["phosphorescence_T2"]))

    scaled = json.loads(json.dumps(cfg))
    scaled["rates_s1"] = {key: value*10 for key, value in cfg["rates_s1"].items()}
    scaled["times_s"] = [value/10 for value in cfg["times_s"]]
    scaled_proc, scaled_result = run(script, scaled, root, "expm")
    if scaled_proc.returncode != 0 or scaled_result is None:
        raise SystemExit("tenfold-rate rescaling check failed")
    scaling_delta = float(np.max(np.abs(np.asarray(scaled_result["populations"])-np.asarray(baseline["populations"]))))

payload = {
    "schema_version": "1.0",
    "solver": "scipy.linalg.expm",
    "solver_version": scipy.__version__,
    "commands": ["python solver.py --method expm"],
    "convergence_comparison": {"approach": "second_solver",
                               "settings": [{"method": "scipy.linalg.expm", "command": ["python", "solver.py", "--method", "expm"]},
                                            {"method": "scipy.integrate.solve_ivp(BDF)", "rtol": 1e-11, "atol": 1e-14,
                                             "command": ["python", "solver.py", "--method", "BDF"]}],
                               "replay": {"script": "solver.py", "command": ["python", "solver.py", "--method", "BDF"]},
                               "max_population_delta": method_delta},
    "checks": {"probability_residual": residual, "tail_bound": tail,
               "zero_isc_analytic_abs_error": zero_delta,
               "tenfold_rate_time_rescaling_max_abs_error": scaling_delta},
}
output.write_text(json.dumps(payload, indent=2, allow_nan=False)+"\n", encoding="utf-8")
BENCH22_EMBED_VALIDATION_PY
mkdir -p /app/final
cp "$RUNTIME_DIR/solver.py" /app/final/solver.py
(cd /app && python /app/final/solver.py --method expm)
mv /app/result.json /app/final/result.json
python "$RUNTIME_DIR/validation.py" /app/final/solver.py /app/inputs/benchmark.json /app/final/convergence.json
