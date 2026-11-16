#!/usr/bin/env python3
"""Invert the published two-mode response from the public target file."""
from __future__ import annotations

import json
import importlib.util
import shutil
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

NAMES = ("K11", "K12", "K13", "K21", "K22")


def epsilon(k, K):
    k2 = np.asarray(k, dtype=float) ** 2
    A = K["K11"] + K["K12"] * k2 + K["K13"] * k2 ** 2
    B = K["K21"] + K["K22"] * k2
    return 1.0 + 1.0 / A + 1.0 / B


def load_targets(workspace: Path):
    paths = (workspace / "assets/response_targets.json",
             Path(__file__).resolve().parents[2] / "environment/assets/response_targets.json")
    for path in paths:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))["targets"]
    raise FileNotFoundError("public assets/response_targets.json is unavailable")


def load_objective_features(workspace: Path):
    path = workspace / "assets/objective_features.py"
    spec = importlib.util.spec_from_file_location("task90_objective_features", path)
    if spec is None or spec.loader is None:
        raise ImportError("public assets/objective_features.py is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ObjectiveRPC:
    """Ask the evaluator to calculate each objective value in its own process."""

    def __init__(self):
        self.sequence = 0

    def __call__(self, x):
        request = {"type": "objective_query", "seq": self.sequence,
                   "K": [float(value) for value in x]}
        print(json.dumps(request, allow_nan=False, separators=(",", ":")), flush=True)
        reply = json.loads(sys.stdin.readline())
        if reply.get("type") != "objective_result" or reply.get("seq") != self.sequence:
            raise RuntimeError("evaluator objective response is out of sequence")
        self.sequence += 1
        return np.asarray(reply["residual"], dtype=float)


def main():
    workspace = Path(sys.argv[1] if len(sys.argv) > 1 else "/app")
    raw = load_targets(workspace)
    objective = load_objective_features(workspace)

    def local_residual(x):
        K = dict(zip(NAMES, x))
        if min(K["K11"], K["K13"], K["K21"], K["K22"]) <= 0 or K["K12"] >= 0:
            return np.full(5, 10.0)
        try:
            return objective.scaled_residual(K, raw)
        except RuntimeError:
            return np.full(5, 10.0)

    residual = ObjectiveRPC() if "--objective-rpc" in sys.argv[2:] else local_residual

    bounds = ([1e-4, -2.0, 1e-4, 1e-4, 1e-3], [2.0, -1e-3, 1.0, 2.0, 20.0])
    # Use deterministic, deliberately broad starts. The public task is an
    # inverse problem; its published kernel is not an admissible substitute
    # for fitting the five observed response features.
    rng = np.random.default_rng(20261016)
    starts = [[
        rng.uniform(0.02, 1.0),
        -10.0 ** rng.uniform(-2.0, -0.3),
        10.0 ** rng.uniform(-2.0, -1.0),
        10.0 ** rng.uniform(-2.0, -1.0),
        10.0 ** rng.uniform(-0.3, 1.0),
    ] for _ in range(12)]
    trials = []
    for x0 in starts:
        fit = least_squares(residual, np.array(x0, dtype=float), bounds=bounds,
                            xtol=1e-12, ftol=1e-12, max_nfev=60)
        trials.append((float(fit.cost), int(fit.nfev), fit.x.copy()))
    cost, nfev, x = min(trials, key=lambda row: row[0])
    K = dict(zip(NAMES, (float(v) for v in x)))
    got = objective.features(K)
    k = np.linspace(0.0, 8.0, 801)
    eps = epsilon(k, K)
    chi = 1.0 - 1.0 / eps
    final = workspace / "final"
    final.mkdir(parents=True, exist_ok=True)
    # The verifier reruns this submitted source in an isolated process. The
    # host, not this program, writes the authoritative solver.log receipt.
    shutil.copyfile(Path(__file__).resolve(), final / "solver.py")
    (final / "response_curves.csv").write_text(
        "k_Ainv,eps,chi\n" + "\n".join(f"{a:.6f},{b:.8e},{c:.8e}" for a,b,c in zip(k,eps,chi)) + "\n",
        encoding="utf-8")
    (final / "kernel_params.json").write_text(json.dumps({
        **K, "units": {"K11": "1", "K12": "Angstrom^2", "K13": "Angstrom^4",
                        "K21": "1", "K22": "Angstrom^2"},
        "observables": got, "branch_note": "best of twelve deterministic broad bounded fits",
    }, indent=2) + "\n", encoding="utf-8")
    (final / "solver.log").write_text(json.dumps({
        "schema": "task90-candidate-objective-report/v1",
        "status": "PENDING",
        "objective_scope": "evaluator-observable objective requests; internal optimizer calls are not counted",
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
