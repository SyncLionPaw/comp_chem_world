#!/usr/bin/env bash
set -euo pipefail
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
cat > "$work_dir/solve.py" <<'CCB_SOLVE_PY'
#!/usr/bin/env python3
"""Compute conditional surface-excess hulls from the acquired three-coverage records."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

EV_A2_TO_J_M2 = 16.02176634
AREA_CORRECTION_J_M2 = -0.06
MU_GRID = [-0.2 + 0.001 * i for i in range(401)]
CONVENTIONS = {
    "sigma0": "sigma0_eV",
    "without_entropy": "without_entropy_eV",
    "toten": "TOTEN_eV",
}
CORRECTIONS = {"native": 0.0, "random50_minus_0.06_J_m2": AREA_CORRECTION_J_M2}


def read_records(path: Path) -> dict[str, list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["alloy"], []).append(row)
    expected = {"CoCrNi", "CoNiV", "SS316L"}
    if set(grouped) != expected or any(len(values) != 3 for values in grouped.values()):
        raise ValueError("native input must contain exactly three coverage records for each of the three alloys")
    for alloy, values in grouped.items():
        values.sort(key=lambda r: float(r["coverage_fraction"]))
        if [float(r["coverage_fraction"]) for r in values] != [0.0, 0.5, 1.0]:
            raise ValueError(f"{alloy}: expected coverage fractions 0, 0.5, 1")
        if [int(r["H_count"]) for r in values] != [0, 20, 40]:
            raise ValueError(f"{alloy}: expected H counts 0, 20, 40")
        if any(int(r["metal_count"]) != 180 for r in values):
            raise ValueError(f"{alloy}: expected 180 metal atoms in each slab")
        areas = [float(r["one_face_area_A2"]) for r in values]
        if max(areas) - min(areas) > 1e-6:
            raise ValueError(f"{alloy}: coverage records do not share a consistent one-face area")
    return grouped


def envelope(d: float) -> dict:
    if math.isclose(d, 0.0, rel_tol=0.0, abs_tol=1e-12):
        intervals = [
            {"coverage": 0.0, "mu_tilde_eV_interval": ["-inf", 0.0]},
            {"coverage": 0.5, "mu_tilde_eV_interval": [0.0, 0.0]},
            {"coverage": 1.0, "mu_tilde_eV_interval": [0.0, "+inf"]},
        ]
        transitions = [{"mu_tilde_eV": 0.0, "coexisting_coverages": [0.0, 0.5, 1.0]}]
        vertices = [0.0, 0.5, 1.0]
    elif d > 0.0:
        lo, hi = -d / 40.0, d / 40.0
        intervals = [
            {"coverage": 0.0, "mu_tilde_eV_interval": ["-inf", lo]},
            {"coverage": 0.5, "mu_tilde_eV_interval": [lo, hi]},
            {"coverage": 1.0, "mu_tilde_eV_interval": [hi, "+inf"]},
        ]
        transitions = [
            {"mu_tilde_eV": lo, "coexisting_coverages": [0.0, 0.5]},
            {"mu_tilde_eV": hi, "coexisting_coverages": [0.5, 1.0]},
        ]
        vertices = [0.0, 0.5, 1.0]
    else:
        intervals = [
            {"coverage": 0.0, "mu_tilde_eV_interval": ["-inf", 0.0]},
            {"coverage": 1.0, "mu_tilde_eV_interval": [0.0, "+inf"]},
        ]
        transitions = [{"mu_tilde_eV": 0.0, "coexisting_coverages": [0.0, 1.0]}]
        vertices = [0.0, 1.0]
    return {"stable_intervals": intervals, "transitions": transitions, "hull_vertices": vertices}


def evaluate(native_csv: Path, outdir: Path) -> dict:
    grouped = read_records(native_csv)
    native = [r for alloy in sorted(grouped) for r in grouped[alloy]]
    curvature_rows: list[dict] = []
    surface_rows: list[dict] = []
    threshold_rows: list[dict] = []
    hull = {
        "model": "three discrete coverages with affine metal/H reservoir terms analytically eliminated",
        "mu_tilde_domain_eV": ["-inf", "+inf"],
        "visualization_grid_only": {"min_eV": -0.2, "max_eV": 0.2, "points": 401},
        "groups": [],
    }
    for alloy in sorted(grouped):
        points = grouped[alloy]
        area = float(points[0]["one_face_area_A2"])
        for convention, field in CONVENTIONS.items():
            energies = [float(row[field]) for row in points]
            e0, e50, e100 = energies
            d_native = e100 - 2.0 * e50 + e0
            mu_star = (e100 - e0) / 40.0
            for correction_name, correction_j_m2 in CORRECTIONS.items():
                correction_e50 = correction_j_m2 * (2.0 * area) / EV_A2_TO_J_M2
                e50_used = e50 + correction_e50
                d = e100 - 2.0 * e50_used + e0
                offset = d - d_native
                correction_actual_j_m2 = correction_j_m2
                curvature_rows.append({
                    "alloy": alloy,
                    "energy_convention": convention,
                    "surface_correction": correction_name,
                    "E0_eV": f"{e0:.12g}",
                    "E50_native_eV": f"{e50:.12g}",
                    "E50_used_eV": f"{e50_used:.12g}",
                    "E100_eV": f"{e100:.12g}",
                    "delta_E100_minus_2E50_plus_E0_eV": f"{d:.12g}",
                    "one_face_area_A2": f"{area:.12g}",
                    "candidate_curvature_J_m2": f"{d / (2.0 * area) * EV_A2_TO_J_M2:.12g}",
                    "source_geometry_join_states": json.dumps([r["initial_geometry_join"] for r in points]),
                    "magnetic_parent": "unverified; do not interpret as a same-parent causal interaction",
                    "interpretation_domain": "record-level candidate contrast; absolute gamma_s/gamma_E and reservoir remain unidentified",
                })
                env = envelope(d)
                hull["groups"].append({
                    "alloy": alloy,
                    "energy_convention": convention,
                    "surface_correction": correction_name,
                    "delta_eV": d,
                    "mu_star_eV_per_H": mu_star,
                    **env,
                    "line_intercepts_eV": {"0": 0.0, "0.5": -d / 2.0, "1": 0.0},
                    "line_slopes_eV_per_H": {"0": 0.0, "0.5": -20.0, "1": -40.0},
                    "coverage_energy_lines": [
                        {"coverage": 0.0, "intercept_eV": 0.0, "slope_eV_per_H": 0.0},
                        {"coverage": 0.5, "intercept_eV": -d / 2.0, "slope_eV_per_H": -20.0},
                        {"coverage": 1.0, "intercept_eV": 0.0, "slope_eV_per_H": -40.0},
                    ],
                    "lower_hull_segments": [
                        {"coverage_from": left, "coverage_to": right,
                         "mu_tilde_eV": transition["mu_tilde_eV"],
                         "coexistence_tie": True}
                        for transition in env["transitions"]
                        for left, right in zip(transition["coexisting_coverages"], transition["coexisting_coverages"][1:])
                    ],
                    "finite_interval_endpoints_inclusive": True,
                    "zero_curvature_midpoint_is_collinear_candidate": math.isclose(d, 0.0, rel_tol=0.0, abs_tol=1e-12),
                })
                threshold_rows.extend([
                    {"alloy": alloy, "energy_convention": convention, "surface_correction": correction_name,
                     "transition": "0_to_50_increment_decreases", "strict_condition": "mu_tilde_eV > -delta_eV/40",
                     "threshold_mu_tilde_eV": f"{-d / 40.0:.12g}"},
                    {"alloy": alloy, "energy_convention": convention, "surface_correction": correction_name,
                     "transition": "50_to_100_increment_decreases", "strict_condition": "mu_tilde_eV > delta_eV/40",
                     "threshold_mu_tilde_eV": f"{d / 40.0:.12g}"},
                    {"alloy": alloy, "energy_convention": convention, "surface_correction": correction_name,
                     "transition": "both_stepwise_increments_decrease", "strict_condition": "mu_tilde_eV > abs(delta_eV)/40",
                     "threshold_mu_tilde_eV": f"{abs(d) / 40.0:.12g}"},
                    {"alloy": alloy, "energy_convention": convention, "surface_correction": correction_name,
                     "transition": "total_0_to_100_excess_decreases", "strict_condition": "mu_tilde_eV > 0",
                     "threshold_mu_tilde_eV": "0"},
                ])
                for mu_tilde in MU_GRID:
                    omega = {0.0: 0.0, 0.5: -d / 2.0 - 20.0 * mu_tilde, 1.0: -40.0 * mu_tilde}
                    min_omega = min(omega.values())
                    minimizers = [c for c, value in omega.items() if math.isclose(value, min_omega, rel_tol=0.0, abs_tol=1e-12)]
                    for coverage in (0.0, 0.5, 1.0):
                        surface_rows.append({
                            "alloy": alloy, "energy_convention": convention, "surface_correction": correction_name,
                            "mu_tilde_eV": f"{mu_tilde:.6f}", "coverage_fraction": f"{coverage:.1f}",
                            "omega_excess_eV": f"{omega[coverage]:.12g}",
                            "surface_excess_J_m2": f"{omega[coverage] / (2.0 * area) * EV_A2_TO_J_M2:.12g}",
                            "on_lower_envelope": str(coverage in minimizers).lower(),
                            "minimizing_coverages": json.dumps(minimizers),
                            "grid_role": "visualization only; analytical hull covers the full real domain",
                        })
    test_a, test_b = 7.3, -0.123
    delta_residuals = []
    mu_star_residuals = []
    mu_tilde_residuals = []
    omega_residuals = []
    surface_residuals = []
    for alloy in sorted(grouped):
        points = grouped[alloy]
        area = float(points[0]["one_face_area_A2"])
        for field in CONVENTIONS.values():
            e0, e50, e100 = [float(row[field]) for row in points]
            shifted = [e0 + test_a, e50 + test_a + 20.0 * test_b, e100 + test_a + 40.0 * test_b]
            d0 = e100 - 2.0 * e50 + e0
            d1 = shifted[2] - 2.0 * shifted[1] + shifted[0]
            mu0 = (e100 - e0) / 40.0
            mu1 = (shifted[2] - shifted[0]) / 40.0
            delta_residuals.append(abs(d1 - d0))
            mu_star_residuals.append(abs(mu1 - (mu0 + test_b)))
            for offset_mu_h in (-0.2, 0.0, 0.2):
                mu_h0 = mu0 + offset_mu_h
                mu_h1 = mu_h0 + test_b
                mt0 = mu_h0 - mu0
                mt1 = mu_h1 - mu1
                mu_tilde_residuals.append(abs(mt1 - mt0))
                for coverage in (0.0, 0.5, 1.0):
                    omega0 = {0.0: 0.0, 0.5: -d0 / 2.0 - 20.0 * mt0, 1.0: -40.0 * mt0}[coverage]
                    omega1 = {0.0: 0.0, 0.5: -d1 / 2.0 - 20.0 * mt1, 1.0: -40.0 * mt1}[coverage]
                    omega_residuals.append(abs(omega1 - omega0))
                    surface_residuals.append(abs((omega1 - omega0) / (2.0 * area) * EV_A2_TO_J_M2))
    outdir.mkdir(parents=True, exist_ok=True)
    write_csv(outdir / "native_slab_slice.csv", native)
    write_csv(outdir / "coverage_contrasts.csv", curvature_rows)
    write_csv(outdir / "surface_excess.csv", surface_rows)
    write_csv(outdir / "softening_thresholds.csv", threshold_rows)
    ident = {
        "scientific_scope": {"absolute_surface_energy_identified": False,
                             "actual_reservoir_identified": False,
                             "common_magnetic_parent_confirmed": False},
        "scope": "Three acquired native candidate slab families; conditional three-state coverage model.",
        "area_normalization": "one_face_area_A2 is |a x b|; two surfaces give 2A; eV/A^2 converts by 16.02176634 to J/m^2.",
        "energies": "E0, E50, E100 are record-level values in sigma0, without_entropy, and TOTEN conventions.",
        "linear_reference_cancellation": "d=E100-2E50+E0 cancels any common affine reference a+b*N_H for counts 0,20,40.",
        "chemical_potential": "mu_star=(E100-E0)/40; mu_tilde=mu_H-mu_star. This defines a coordinate and does not assert an actual reservoir chemical potential.",
        "surface_correction": "The conditional -0.06 J/m^2 correction at 50% lowers E50 by 0.06*(2A)/16.02176634 eV and raises d by 0.24*A/16.02176634 eV; native energies are never overwritten.",
        "model_excesses_eV": {"Omega0": "0", "Omega50": "-d/2-20*mu_tilde", "Omega100": "-40*mu_tilde"},
        "normalization": "Omega/(2A)*16.02176634 J/m^2; three coverages are discrete candidate states.",
        "softening_conditions": {"0_to_50": "mu_tilde>-d/40", "50_to_100": "mu_tilde>d/40", "both_steps_if_d_positive_or_negative": "mu_tilde>|d|/40", "total_0_to_100": "mu_tilde>0"},
        "unidentified_or_conditional": [
            "No absolute gamma_s/gamma_E without compatible H2/ZPE/occupied-bulk references.",
            "No actual reservoir chemical potential; inequalities are conditional on mu_tilde.",
            "No confirmed common magnetic parent across coverage states.",
            "The random-50% correction is a sourced sensitivity scenario, not an edit to native records or an uncertainty interval.",
            "No continuous-coverage equilibrium, configurational entropy, ZPE curvature, or unique H-H pair interaction is inferred.",
        ],
        "affine_reference_invariance": {"test_a_eV": test_a, "test_b_eV_per_H": test_b,
             "maximum_delta_residual_eV": max(delta_residuals),
             "mu_star_shift_residual_eV_per_H": max(mu_star_residuals),
             "mu_tilde_residual_eV": max(mu_tilde_residuals),
             "grand_potential_residual_eV": max(omega_residuals),
             "surface_excess_residual_J_m2": max(surface_residuals),
             "note": "mu_H is translated by the same b as mu_star; mu_tilde, all Omega states and normalized surface excess are invariant."},
        "groups": len(curvature_rows),
        "surface_excess_rows": len(surface_rows),
        "threshold_rows": len(threshold_rows),
        "hull_groups": len(hull["groups"]),
        "native_input_rows": len(native),
        "rounding_bound_delta_eV": 2e-8,
        "rounding_bound_each_mu_threshold_eV": 2e-8 / 40.0,
    }
    (outdir / "reference_identifiability.json").write_text(json.dumps(ident, indent=2) + "\n", encoding="utf-8")
    (outdir / "coverage_hull.json").write_text(json.dumps(hull, indent=2) + "\n", encoding="utf-8")
    narrative = [
        "# Coverage surface-excess model",
        "",
        "This calculation analyzes three acquired coverage records for CoCrNi, CoNiV and SS316L. It reports three energy conventions and an unmodified versus explicitly conditional random-50% correction scenario.",
        "",
        "For each group, d=E100−2E50+E0, mu*= (E100−E0)/40 and mu_tilde=mu_H−mu*. The discrete excesses are Ω0=0, Ω50=−d/2−20 mu_tilde, Ω100=−40 mu_tilde. The plotted [-0.2,0.2] eV grid is visualization only; coverage_hull.json gives exact analytical full-real-domain intervals and ties.",
        "",
        "The surface excess normalization is Ω/(2A)×16.02176634 J/m². The random-50% case lowers E50 by the sourced 0.06 J/m² scenario; it does not alter the native energy table.",
        "",
        "Softening is conditional on mu_tilde: the 0→50 and 50→100 increments decrease above −d/40 and d/40, respectively; both steps decrease above |d|/40, while the total 0→100 excess decreases above zero.",
        "",
        "These candidate records do not establish an absolute surface free energy, actual hydrogen reservoir, shared magnetic parent, continuous-coverage equilibrium or unique H-H interaction. Geometry joins and execution indicators are preserved as evidence; magnetic initialization is unverified.",
    ]
    (outdir / "interpretation.md").write_text("\n".join(narrative) + "\n", encoding="utf-8")
    return {"native_rows": len(native), "curvature_groups": len(curvature_rows), "surface_rows": len(surface_rows), "hulls": len(hull["groups"]), "threshold_rows": len(threshold_rows)}


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", type=Path, required=True, help="Nine-row native_slab_slice.csv")
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.native, args.outdir)
    import hashlib, shutil
    source_path = Path(__file__).resolve()
    source_out = args.outdir / "calculation_source.py"
    shutil.copyfile(source_path, source_out)
    def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    outputs = {p.name: digest(p) for p in args.outdir.iterdir() if p.is_file() and p.name not in {"calculation_source.py", "run_metadata.json"}}
    metadata = {
        "schema": "compchemworld-calculation-run/v1",
        "command": "python calculation_source.py --native <public-input> --outdir <output-dir>",
        "calculation_source_sha256": digest(source_out),
        "input": {"logical_name": Path(args.native).name, "sha256": digest(Path(args.native))},
        "output_sha256": outputs,
        "python": __import__("platform").python_version(),
        "execution_context": "local CPU calculation; this receipt does not assert independent author DFT execution",
    }
    (args.outdir / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
CCB_SOLVE_PY
python3 "$work_dir/solve.py" --native /app/assets/native_slab_slice.csv --outdir /app/final
