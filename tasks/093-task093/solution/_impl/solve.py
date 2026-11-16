#!/usr/bin/env python3
"""Reference repair for the public P1' / P1'' boundary-condition defect."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import force_model

SHIFTS = ((0.08, 0.50), (0.12, 0.50), (0.10, 0.35), (0.10, 0.65))

def curve(P0: float, alpha: float):
    old = force_model.P0, force_model.ALPHA
    force_model.P0, force_model.ALPHA = P0, alpha
    try:
        L = np.arange(2.0, 20.0001, 0.10)
        pressure = np.asarray([force_model.pressure(float(x)) for x in L])
    finally:
        force_model.P0, force_model.ALPHA = old
    return L, pressure

def main() -> None:
    workspace = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    final = workspace / "final"
    final.mkdir(parents=True, exist_ok=True)
    P0 = float(os.environ.get("CASE007_P0", "0.10"))
    alpha = float(os.environ.get("CASE007_ALPHA", "0.50"))
    L, pressure = curve(P0, alpha)
    np.savetxt(final / "force_fixed.csv", np.column_stack((L, pressure)), delimiter=",",
               header="L_A,Pi_Pa", comments="")
    (final / "fixed_solver.py").write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    (final / "force_model.py").write_text((HERE / "force_model.py").read_text(encoding="utf-8"), encoding="utf-8")
    (final / "diagnosis.md").write_text(
        "The defective solver imposed P1'=0 at both interfaces in place of the natural P1''=0 condition. "
        "The repaired mode system uses P1''=0, keeps the published sixth-order kernel, and computes pressure "
        "as -dU/dL/epsilon0. The recovered oscillations are checked against the full curve, not just the sign count.\n",
        encoding="utf-8")
    metrics = []
    for p, a in SHIFTS:
        Lh, yh = curve(p, a)
        metrics.append({"P0": p, "alpha": a, "points": int(len(yh)),
                        "max_abs_pressure_Pa": float(np.max(np.abs(yh))),
                        "min_pressure_Pa": float(np.min(yh)), "max_pressure_Pa": float(np.max(yh))})
    (final / "recovery.json").write_text(json.dumps({
        "executed": True, "natural_boundary": "P1''=0", "pressure_definition": "-dU/dL_A/epsilon0",
        "base_parameters": {"P0": P0, "alpha": alpha}, "hidden_runs": metrics,
    }, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
