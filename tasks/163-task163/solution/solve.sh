#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP:-/app}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SOLVE_SCRIPT="${SOLVE_SCRIPT:-$SCRIPT_DIR/solve.sh}"
INPUT_ROOT="$APP_ROOT/inputs/databases"
if [[ ! -d "$INPUT_ROOT" ]]; then
  echo "public input directory not found: $INPUT_ROOT" >&2
  exit 2
fi

python3 - --input-root "$INPUT_ROOT" --output-root "$APP_ROOT" --solve-script "$SOLVE_SCRIPT" <<'CASE02_SOLVE'
"""Independent public-grid integration baseline for Bench25 case-02.

This is a locally derived reference delivery, not author-provided Gold. It reads
only the published public ASE databases and implements the documented output
contract without importing or calling the case verifier.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from ase.db import connect


def render_figures(plot_data: Path, figures: Path) -> None:
    """Render PNGs from the public plot-data table using the former plot helper."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures.mkdir(parents=True, exist_ok=True)
    with plot_data.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    for value, title, unit, filename in (
        ("gap_S10_eV", "S1-S0 energy gap", "eV", "gap-surface.png"),
        ("nac01_norm", "S1/S0 NAC norm", "1/Bohr", "nac01-surface.png"),
    ):
        fig, axes = plt.subplots(1, 3, figsize=(14, 4.2), constrained_layout=True)
        for ax, molecule in zip(axes, ("C2H4", "C3H6", "C4H8")):
            subset = [row for row in rows if row["molecule"] == molecule]
            scatter = ax.scatter([float(row["dihedral_deg"]) for row in subset],
                                 [float(row["r_cc_bohr"]) for row in subset],
                                 c=[float(row[value]) for row in subset], s=8, marker="s", linewidths=0)
            ax.set(title=molecule, xlabel="Absolute H-C=C-H dihedral (deg)", ylabel="C=C distance (Bohr)")
            fig.colorbar(scatter, ax=ax, label=unit)
        fig.suptitle(title)
        fig.savefig(figures / filename, dpi=160)
        plt.close(fig)

HA_EV = 27.211386245988
MOLECULES = (
    ("C2H4", "04_3Sing_C2H4_grid.db"),
    ("C3H6", "05_3Sing_C3H6_grid.db"),
    ("C4H8", "06_3Sing_C4H8_grid.db"),
)
PAPER_DIH = (80.0, 100.0)
PAPER_R = (2.5, 2.8)
RIDGE_DIH = (70.0, 110.0)
PAPER_WINDOW = {"dihedral_deg": list(PAPER_DIH), "r_cc_bohr": list(PAPER_R)}
GRID_SCHEMA = "case02/scientific-summary/v2"
QUANTILE_FAMILY = "nac_norm_quantile_window/v1"
THRESHOLD_FAMILY = "gap_nac_threshold_window/v1"


def dihedral(p0: np.ndarray, p1: np.ndarray, p2: np.ndarray, p3: np.ndarray) -> float:
    b0, b1, b2 = p0 - p1, p2 - p1, p3 - p2
    b1 = b1 / np.linalg.norm(b1)
    v = b0 - np.dot(b0, b1) * b1
    w = b2 - np.dot(b2, b1) * b1
    return float(np.degrees(np.arctan2(np.dot(np.cross(b1, v), w), np.dot(v, w))))


def geometry(row) -> tuple[float, float]:
    positions = np.asarray(row.positions, dtype=float)
    numbers = np.asarray(row.numbers)
    carbons = list(np.where(numbers == 6)[0])
    hydrogens = list(np.where(numbers == 1)[0])
    bonded = {c: [h for h in hydrogens if np.linalg.norm(positions[c] - positions[h]) < 2.4]
              for c in carbons}
    sp2 = [c for c in carbons if len(bonded[c]) <= 2]
    if len(sp2) != 2:
        raise ValueError(f"expected two sp2 carbons, found {sp2}")
    c0, c1 = sp2
    h0 = min(bonded[c0], key=lambda h: np.linalg.norm(positions[c0] - positions[h]))
    h1 = min(bonded[c1], key=lambda h: np.linalg.norm(positions[c1] - positions[h]))
    r = float(np.linalg.norm(positions[c1] - positions[c0]))
    theta = abs(dihedral(positions[h0], positions[c0], positions[c1], positions[h1]))
    return r, theta


def load_points(input_root: Path) -> dict[str, list[dict[str, float]]]:
    result = {}
    for molecule, filename in MOLECULES:
        points = []
        for row in connect(input_root / filename).select():
            r, theta = geometry(row)
            data = row.data
            energy = np.asarray(data["energy"], dtype=float).reshape(-1)
            dipoles = np.asarray(data["dipoles"], dtype=float)
            mu10 = dipoles[3]
            gap = float(energy[1] - energy[0]) * HA_EV
            oscillator = (2.0 / 3.0) * float(energy[1] - energy[0]) * float(np.dot(mu10, mu10))
            nac01 = float(np.linalg.norm(np.asarray(data["nacs"], dtype=float)[:, 0, :]))
            points.append({
                "r": r, "theta": theta, "e0": float(energy[0]), "e1": float(energy[1]),
                "e2": float(energy[2]), "gap": gap, "f01": oscillator, "nac": nac01,
            })
        points.sort(key=lambda p: (round(p["theta"], 3), round(p["r"], 4)))
        result[molecule] = points
    return result


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def run_selector(points: list[dict[str, float]], family: str, search: dict,
                 parameters: dict[str, float]) -> tuple[list[dict[str, float]], dict]:
    rlo, rhi = search["r_cc_bohr"]
    dlo, dhi = search["dihedral_deg"]
    population = [p for p in points if rlo <= p["r"] <= rhi and dlo <= p["theta"] <= dhi]
    if not population:
        raise ValueError("selector search rectangle contains no public grid points")
    if family == QUANTILE_FAMILY:
        q = parameters["quantile"]
        threshold = float(np.quantile([p["nac"] for p in population], q))
        chosen = [p for p in population if p["nac"] >= threshold]
        reported_thresholds = {"quantile": q, "nac_threshold_1_per_bohr": threshold}
    elif family == THRESHOLD_FAMILY:
        gap_max = parameters["gap_max_eV"]
        nac_min = parameters["nac_min_1_per_bohr"]
        threshold = {"gap_max_eV": gap_max, "nac_min_1_per_bohr": nac_min}
        chosen = [p for p in population if p["gap"] <= gap_max and p["nac"] >= nac_min]
        reported_thresholds = threshold.copy()
    else:
        raise ValueError(f"unsupported selector family: {family}")
    if not chosen:
        raise ValueError("selector thresholds select no public grid points")
    er = [p["r"] for p in chosen]
    et = [p["theta"] for p in chosen]
    envelope = [p for p in points if min(er) <= p["r"] <= max(er) and min(et) <= p["theta"] <= max(et)]
    result = {
        "search_population": len(population), **reported_thresholds,
        "selected_points": len(chosen), "r_extent_bohr": [min(er), max(er)],
        "dihedral_extent_deg": [min(et), max(et)],
        "selected_min_gap_eV": min(p["gap"] for p in chosen),
        "selected_max_nac01_1_per_bohr": max(p["nac"] for p in chosen),
        "envelope_grid_points": len(envelope), "envelope_min_gap_eV": min(p["gap"] for p in envelope),
        "envelope_max_nac01_1_per_bohr": max(p["nac"] for p in envelope),
        "touches_r_grid_boundary": min(er) <= min(p["r"] for p in points) + 1e-6 or max(er) >= max(p["r"] for p in points) - 1e-6,
        "touches_dihedral_grid_boundary": min(et) <= min(p["theta"] for p in points) + 1e-6 or max(et) >= max(p["theta"] for p in points) - 1e-6,
    }
    return chosen, result


def overlap_category(width: float, candidate_width: float, paper_width: float) -> str:
    if width <= 1e-12:
        return "none"
    if abs(width - min(candidate_width, paper_width)) <= 1e-9:
        return "full"
    return "partial"


def axis_info(values: list[float], digits: int) -> dict[str, object]:
    axis = sorted({round(value, digits) for value in values})
    steps = np.diff(np.asarray(axis, dtype=float))
    if not len(steps) or not np.allclose(steps, steps[0], atol=10 ** (-digits), rtol=0):
        raise ValueError("public grid axis is not a regular scan")
    return {"range": [float(axis[0]), float(axis[-1])], "step": float(steps[0]),
            "unique_count": len(axis)}


def csv_write(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True,
                        help="APP path; outputs/ will be created below it")
    parser.add_argument("--solve-script", type=Path, required=True,
                        help="mounted solution/solve.sh path for provenance")
    args = parser.parse_args()
    out = args.output_root / "outputs"
    figures = out / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    grids = load_points(args.input_root)

    map_rows = []
    for molecule, points in grids.items():
        for index, point in enumerate(points):
            map_rows.append([molecule, index, point["r"], point["theta"], point["e0"], point["e1"],
                             point["e2"], point["gap"], point["f01"], point["nac"]])
    csv_write(out / "grid_map.csv",
              ["molecule", "point_index", "r_cc_bohr", "dihedral_deg", "e0_hartree", "e1_hartree",
               "e2_hartree", "gap_S10_eV", "f_01", "nac01_norm"], map_rows)
    csv_write(out / "plot_data.csv",
              ["molecule", "point_index", "r_cc_bohr", "dihedral_deg", "gap_S10_eV", "nac01_norm"],
              [[row[0], row[1], row[2], row[3], row[7], row[9]] for row in map_rows])

    ci_rows = []
    criteria = {}
    for molecule, points in grids.items():
        search = {"r_cc_bohr": [min(p["r"] for p in points), max(p["r"] for p in points)],
                  "dihedral_deg": list(RIDGE_DIH)}
        family = QUANTILE_FAMILY
        sensitivity_parameters = ([{"quantile": q} for q in (0.85, 0.90, 0.95)])
        selected_index = 1
        selected_params = sensitivity_parameters[selected_index]
        chosen, selected_result = run_selector(points, family, search, selected_params)
        rlo, rhi = selected_result["r_extent_bohr"]
        dlo, dhi = selected_result["dihedral_extent_deg"]
        inside = [p for p in points if rlo <= p["r"] <= rhi and dlo <= p["theta"] <= dhi]
        crit = f"NAC01 >= search-rectangle q{100*selected_params['quantile']:g} ({selected_result['nac_threshold_1_per_bohr']:.8g} 1/Bohr)"
        ci_rows.append([
            molecule, crit, rlo, rhi, dlo, dhi, len(inside), min(p["gap"] for p in inside),
            max(p["nac"] for p in inside), overlap(dlo, dhi, *PAPER_DIH), overlap(rlo, rhi, *PAPER_R),
            "Static public-grid selection envelope; it does not establish an exact seam or dynamical visitation.",
        ])
        sensitivity = []
        for params in sensitivity_parameters:
            _, metrics = run_selector(points, family, search, params)
            sensitivity.append({"parameters": params, **metrics})
        criteria[molecule] = {
            "selector": {"family": family, "search_rectangle": search, "parameters": selected_params},
            "sensitivity": sensitivity,
            "selected_sensitivity_index": selected_index,
        }

    csv_write(out / "ci_region.csv",
              ["molecule", "criterion", "r_cc_min_bohr", "r_cc_max_bohr", "dihedral_min_deg",
               "dihedral_max_deg", "n_points", "min_gap_eV", "max_nac01",
               "overlap_with_paper_dihedral_deg", "overlap_with_paper_r_bohr", "notes"], ci_rows)

    r_all = [p["r"] for points in grids.values() for p in points]
    t_all = [p["theta"] for points in grids.values() for p in points]
    paper_conclusions = {}
    for row in ci_rows:
        molecule = row[0]
        info = criteria[molecule]
        selected = info["sensitivity"][info["selected_sensitivity_index"]]
        rlo, rhi, dlo, dhi = map(float, (row[2], row[3], row[4], row[5]))
        radial, angular = float(row[10]), float(row[9])
        paper_conclusions[molecule] = {
            "candidate_window": {"r_cc_bohr": [rlo, rhi], "dihedral_deg": [dlo, dhi]},
            "paper_window": PAPER_WINDOW,
            "radial_overlap_bohr": radial,
            "radial_overlap_category": overlap_category(radial, rhi-rlo, PAPER_R[1]-PAPER_R[0]),
            "angular_overlap_deg": angular,
            "angular_overlap_category": overlap_category(angular, dhi-dlo, PAPER_DIH[1]-PAPER_DIH[0]),
            "selected_bound_touches_grid_boundary": {
                "r_cc_bohr": selected["touches_r_grid_boundary"],
                "dihedral_deg": selected["touches_dihedral_grid_boundary"],
            },
        }
    summary = {
        "schema": GRID_SCHEMA,
        "grid_definition": {
            mol: {
                "r_cc_bohr_range": [min(p["r"] for p in points), max(p["r"] for p in points)],
                "r_cc_bohr_step": axis_info([p["r"] for p in points], 4)["step"],
                "r_cc_bohr_unique_count": len({round(p["r"], 8) for p in points}),
                "dihedral_deg_range": [min(p["theta"] for p in points), max(p["theta"] for p in points)],
                "dihedral_deg_step": axis_info([p["theta"] for p in points], 3)["step"],
                "dihedral_unique_count": len({round(p["theta"], 8) for p in points}),
                "points": len(points),
            } for mol, points in grids.items()
        },
        "ci_criteria": {
            "molecules": criteria,
            "interpretation": {
                "evidence_scope": "finite_static_grid_proxy",
                "exact_ci_seam_established": False,
                "dynamical_visitation_established": False,
                "evidence_reference": "ci_criteria.molecules[*].sensitivity and selected_sensitivity_index",
            },
        },
        "paper_comparison": {
            "per_molecule": paper_conclusions,
        },
        "figures": [
            "figures/gap-surface.png: S1-S0 energy-gap maps, gap in eV and C=C distance in Bohr",
            "figures/nac01-surface.png: S1/S0 NAC-norm maps, NAC in 1/Bohr and C=C distance in Bohr",
        ],
        "provenance": "Independent full public-grid integration baseline; not author-provided Gold. Generated directly from the public ASE database values without importing or invoking the verifier.",
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    render_figures(out / "plot_data.csv", figures)
    manifest = {
        "status": "artifact_binding_only; image pixels and scientific meaning require independent review",
        "plot_data": {"path": "plot_data.csv", "sha256": sha256(out / "plot_data.csv"),
                      "columns": ["molecule", "point_index", "r_cc_bohr", "dihedral_deg", "gap_S10_eV", "nac01_norm"]},
        "plot_script": {"path": "solution/solve.sh", "sha256": sha256(args.solve_script)},
        "figures": {
            path.name: {"path": f"figures/{path.name}", "sha256": sha256(path),
                        "source_columns": ["dihedral_deg", "r_cc_bohr", "gap_S10_eV" if path.name.startswith("gap-") else "nac01_norm"]}
            for path in sorted(figures.glob("*.png"))
        },
    }
    (out / "plot-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
CASE02_SOLVE
