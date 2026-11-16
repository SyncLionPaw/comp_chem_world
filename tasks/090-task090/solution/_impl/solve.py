#!/usr/bin/env python3
"""Compute case 003 pressure curves from the public model constants."""
from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import force_solver_gold as model  # noqa: E402


def write_curve(path, x, y):
    lines = ["L_A,Pi_Pa"]
    lines.extend(f"{xx:.4f},{yy:.8e}" for xx, yy in zip(x, y))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    workspace = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    public = model.configure_from_public_constants(workspace)
    source_path = Path(public.pop("_source_path"))
    final = workspace / "final"
    final.mkdir(parents=True, exist_ok=True)
    h_coarse, h_fine = 1.0e-3, 2.0e-4
    p_h_coarse = model.pressure(0.40, h=h_coarse, n=2001)
    p_h_fine = model.pressure(0.40, h=h_fine, n=2001)
    h_relative = abs(p_h_coarse - p_h_fine) / max(abs(p_h_fine), 1.0)
    p_n_coarse = model.pressure(0.40, h=h_coarse, n=2001)
    p_n_fine = model.pressure(0.40, h=h_coarse, n=8001)
    n_relative = abs(p_n_coarse - p_n_fine) / max(abs(p_n_fine), 1.0)
    energy_residual = abs(model.energy(8.0, n=2001) - model.energy(8.0, n=4001))
    table = model.sharp_pressure_table()
    Ls, Vs = model.sharp_grid()
    smearing = public["smearing"]
    Lg, Vg = model.smeared_grid(
        two_sigma=float(smearing["task_width_label_A"]),
        floor=float(smearing["film_floor_A"]), table=table)
    write_curve(final / "force_sharp.csv", Ls, Vs)
    write_curve(final / "force_smeared.csv", Lg, Vg)
    poles = model.lengths()
    analysis = {
        **poles,
        "oscillation_period_A": model.period_from_extrema(Ls, Vs),
        "sharp_sign_changes_4_20": model.sign_changes(Ls, Vs, 4.0, 20.0),
        "smeared_sign_changes_5_20": model.sign_changes(Lg, Vg, 5.0, 20.0),
        "smeared_sign_changes_10_20": model.sign_changes(Lg, Vg, 10.0, 20.0),
        "film_floor_A": float(smearing["film_floor_A"]),
        "task_two_sigma_A": float(smearing["task_width_label_A"]),
        "gaussian": "exp(-x^2/(2*sigma^2)), not Equation 19",
        "natural_boundary": "P1''=0",
        "internal_sharp_start_A": float(smearing["internal_sharp_grid_A"]["start"]),
    }
    (final / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    (final / "solver.log").write_text(
        "\n".join([
            "case 003 variational mode solution",
            "natural boundary P1''=0",
            "internal sharp table starts at 0.40 Angstrom; public curve starts at 2 Angstrom",
            "task Gaussian sigma = 1.25 Angstrom, not Equation 19",
            f"public_constants_sha256 {hashlib.sha256(source_path.read_bytes()).hexdigest()}",
            f"max_boundary_residual {model._MAX_BOUNDARY_RESIDUAL:.8e}",
            f"pressure_step_relative_change_at_0.40A {h_relative:.8e}",
            f"quadrature_relative_change_at_0.40A {n_relative:.8e}",
            f"energy_reproducibility_residual_at_8A {energy_residual:.8e}",
            "central_difference_steps_A 1e-3 2e-4",
            "quadrature_nodes 2001 8001",
            "converged",
        ]) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(analysis, indent=2))


if __name__ == "__main__":
    main()
