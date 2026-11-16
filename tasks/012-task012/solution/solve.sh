#!/usr/bin/env bash
set -euo pipefail
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
cat > "$work_dir/solve.py" <<'CCB_SOLVE_PY'
"""Intrinsic cleavage-versus-emission comparison for the revised Case01 scope.

This is a bounded, source-driven comparison at fixed bulk concentration and
temperature. It does not model crack-tip segregation, applied-load evolution,
Ni, or a macroscopic embrittlement verdict. Coverage coordinates C_S and
C_usf are independent axes; the output is their full Cartesian product.
"""
from __future__ import annotations

import csv
import itertools
import math
import json
from pathlib import Path
from typing import Mapping, Sequence

USF_AREA_A2 = 108.0
NUCLEATION_AREA_A2 = 50.0
SIGMA_AREA_FACTOR = math.sqrt(USF_AREA_A2 / NUCLEATION_AREA_A2)
NUCLEATION_AREA_SENSITIVITY_A2 = (30.0, 50.0, 70.0)
CB_FIXED = 0.0058
TEMPERATURE_K = 300.0
EXPECTED_ALLOYS = (
    "SS304", "SS316L", "CoCrNi", "CoNiV", "CoCrFeNi", "CoCrFeMnNi"
)


class MissingDependencyError(ValueError):
    """Raised when a required sourced curve or material parameter is absent."""


def phase_classification(d_low: float, d_high: float) -> str:
    """Classify the intrinsic competition interval; no macro-scale label."""
    low, high = float(d_low), float(d_high)
    if not (math.isfinite(low) and math.isfinite(high)) or low > high:
        raise ValueError("D interval must be finite and ordered")
    if high < 0.0:
        return "cleavage_first_robust"
    if low > 0.0:
        return "emission_first_robust"
    return "competition_uncertain"


def compute_d_interval(
    alpha_gpa: float,
    beta_gpa: float,
    gamma_f_mean_j_m2: float,
    gamma_f_low_j_m2: float,
    gamma_f_high_j_m2: float,
    gamma_usf_mean_mj_m2: float,
    gamma_usf_std_dft_mj_m2: float,
) -> dict[str, float | str]:
    """Compute D and the conservative interval specified for this scope.

    D = alpha*gamma_F(C_S) - beta*gamma_usf(C_usf). The SI standard deviation
    is rescaled by sqrt(A_usf/A_nucleation) for the upper bound. The published
    Fig. 2(b) gamma_F is already a fracture-free-energy value: this function
    does not add entropy or apply the separate random-50% gammaE correction.
    """
    alpha, beta = float(alpha_gpa), float(beta_gpa)
    gf, gf_low, gf_high = map(float, (gamma_f_mean_j_m2, gamma_f_low_j_m2, gamma_f_high_j_m2))
    gu, gu_std = map(float, (gamma_usf_mean_mj_m2, gamma_usf_std_dft_mj_m2))
    vals = (alpha, beta, gf, gf_low, gf_high, gu, gu_std)
    if any(not math.isfinite(x) for x in vals):
        raise ValueError("all numerical inputs must be finite")
    if alpha <= 0 or beta <= 0 or gf < 0 or gf_low < 0 or gf_high < gf_low or not gf_low <= gf <= gf_high or gu < 0 or gu_std < 0:
        raise ValueError("invalid elastic constants, energy interval, or USF statistics")
    usf_std_scaled = gu_std * SIGMA_AREA_FACTOR
    # Gamma_F is J/m²; Fig. 2(c) USF values are mJ/m².
    d_center = alpha * gf - beta * gu / 1000.0
    d_low = alpha * gf_low - beta * gu / 1000.0
    d_high = alpha * gf_high - beta * (gu - usf_std_scaled) / 1000.0
    return {
        "D_low_GPa_J_m2": d_low,
        "D_center_GPa_J_m2": d_center,
        "D_high_GPa_J_m2": d_high,
        "gamma_usf_sigma_scaled_mJ_m2": usf_std_scaled,
        "classification": phase_classification(d_low, d_high),
    }


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def load_elastic_parameters(path: str | Path) -> dict[str, dict[str, float]]:
    rows = _read_csv(path)
    result = {}
    for row in rows:
        alloy = row["alloy"]
        result[alloy] = {
            "alpha_GPa": float(row["alpha_GPa"]),
            "beta_GPa": float(row["beta_GPa"]),
        }
    return result


def load_gamma_f_curve(path: str | Path) -> dict[str, dict[float, tuple[float, float, float]]]:
    """Load explicitly digitized Fig. 2(b) intervals in J/m²; no interpolation."""
    result: dict[str, dict[float, tuple[float, float, float]]] = {}
    for row in _read_csv(path):
        if row.get("gamma_F_units") != "J/m^2":
            raise ValueError("gamma_F curve must declare gamma_F_units=J/m^2")
        alloy = row["alloy"]
        cs = float(row["C_surface"])
        result.setdefault(alloy, {})[cs] = (
            float(row["gamma_F_mean_J_m2"]),
            float(row["gamma_F_low_J_m2"]),
            float(row["gamma_F_high_J_m2"]),
        )
    return result


def load_gamma_usf_parameters(path: str | Path) -> dict[str, dict[float, tuple[float, float]]]:
    result: dict[str, dict[float, tuple[float, float]]] = {}
    for row in _read_csv(path):
        if row.get("gamma_usf_units", "mJ/m^2") != "mJ/m^2":
            raise ValueError("gamma_usf input must declare mJ/m^2 units")
        alloy = row["alloy"]
        coverage = float(row.get("C_usf", row.get("coverage_Cusf")))
        result.setdefault(alloy, {})[coverage] = (
            float(row["gamma_usf_mean_mJ_m2"]),
            float(row["gamma_usf_std_DFT_mJ_m2"]),
        )
    return result


def compute_phase_map(
    elastic: Mapping[str, Mapping[str, float]],
    gamma_f: Mapping[str, Mapping[float, tuple[float, float, float]]],
    gamma_usf: Mapping[str, Mapping[float, tuple[float, float]]],
    *,
    alloys: Sequence[str] = EXPECTED_ALLOYS,
    cb_fixed: float = CB_FIXED,
    temperature_K: float = TEMPERATURE_K,
    grid_size: int = 101,
    nucleation_areas_a2: Sequence[float] = NUCLEATION_AREA_SENSITIVITY_A2,
) -> list[dict]:
    """Compute the independent continuous 2-D grid using piecewise-linear source curves.

    Interpolation is only between the explicitly digitized 0, 0.5, and 1
    coverage anchors. There is no extrapolation. The map is repeated for the
    SI's 30/50/70 A^2 nucleation-area sensitivity values.
    """
    if not math.isclose(float(cb_fixed), CB_FIXED, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("this benchmark scope fixes Cb=0.0058")
    if not math.isclose(float(temperature_K), TEMPERATURE_K, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("this benchmark scope fixes T=300 K")
    if grid_size < 3:
        raise ValueError("grid_size must be at least 3")
    areas = tuple(float(x) for x in nucleation_areas_a2)
    if not areas or any(not math.isfinite(x) or x <= 0 for x in areas):
        raise ValueError("nucleation areas must be a nonempty sequence of positive values")
    cs_grid = [i / (grid_size - 1) for i in range(grid_size)]
    cusf_grid = cs_grid[:]
    outputs: list[dict] = []
    for alloy in alloys:
        if alloy not in elastic or alloy not in gamma_f or alloy not in gamma_usf:
            raise MissingDependencyError(f"missing sourced material inputs for {alloy}")
        alpha = float(elastic[alloy]["alpha_GPa"])
        beta = float(elastic[alloy]["beta_GPa"])
        for axis, anchors in (("C_surface", gamma_f[alloy]), ("C_usf", gamma_usf[alloy])):
            if not all(any(math.isclose(float(key), target, abs_tol=1e-12, rel_tol=0.0) for key in anchors)
                       for target in (0.0, 0.5, 1.0)):
                raise MissingDependencyError(f"{alloy} {axis} curve needs sourced 0, 0.5, and 1.0 anchors")
        for cs, cusf, area in itertools.product(cs_grid, cusf_grid, areas):
            gf_mean, gf_low, gf_high = _piecewise_value(gamma_f[alloy], cs)
            gu_mean, gu_std = _piecewise_value(gamma_usf[alloy], cusf)
            d = compute_d_interval(alpha, beta, gf_mean, gf_low, gf_high, gu_mean, gu_std)
            scaled_std = gu_std * math.sqrt(USF_AREA_A2 / area)
            d_high = alpha * gf_high - beta * (gu_mean - scaled_std) / 1000.0
            ki_c_mean = math.sqrt(alpha * gf_mean / 1000.0)
            ki_c_low = math.sqrt(alpha * gf_low / 1000.0)
            ki_c_high = math.sqrt(alpha * gf_high / 1000.0)
            # KI^2 = beta[GPa] * Gamma[J/m^2] / 1000. USF is in mJ/m^2,
            # so its conversion adds another factor of 1/1000.
            ki_e_mean = math.sqrt(beta * gu_mean / 1_000_000.0)
            ki_e_low = math.sqrt(beta * max(0.0, gu_mean - scaled_std) / 1_000_000.0)
            outputs.append({
                "alloy": alloy,
                "alpha_GPa": alpha,
                "beta_GPa": beta,
                "elastic_source": "main_paper_Fig2(a)",
                "elastic_provenance": "environment/assets/elastic_constants_fig2a.provenance.json",
                "Cb_fixed": CB_FIXED,
                "temperature_K": TEMPERATURE_K,
                "C_surface": cs,
                "C_usf": cusf,
                "gamma_F_mean_J_m2": gf_mean,
                "gamma_F_low_J_m2": gf_low,
                "gamma_F_high_J_m2": gf_high,
                "gamma_F_source": "main_paper_Fig2(b)_digitized",
                "gamma_F_provenance": "environment/assets/gamma_f_fig2b_digitized.provenance.json",
                "gamma_usf_mean_mJ_m2": gu_mean,
                "gamma_usf_std_DFT_mJ_m2": gu_std,
                "gamma_usf_source": "main_paper_Fig2(c)_transcribed",
                "gamma_usf_provenance": "environment/assets/gamma_usf_fig2c_parameters.provenance.json",
                "A_usf_A2": USF_AREA_A2,
                "A_nucleation_A2": area,
                "gamma_usf_sigma_scaled_mJ_m2": scaled_std,
                "D_low_GPa_J_m2": d["D_low_GPa_J_m2"],
                "D_center_GPa_J_m2": d["D_center_GPa_J_m2"],
                "D_high_GPa_J_m2": d_high,
                "D_units": "GPa*J/m^2",
                "KIc_low_MPa_sqrt_m": ki_c_low,
                "KIc_mean_MPa_sqrt_m": ki_c_mean,
                "KIc_high_MPa_sqrt_m": ki_c_high,
                "KIe_low_MPa_sqrt_m": ki_e_low,
                "KIe_mean_MPa_sqrt_m": ki_e_mean,
                "K_units": "MPa*sqrt(m)",
                "classification": phase_classification(d["D_low_GPa_J_m2"], d_high),
                "interpolation": "piecewise_linear_between_digitized_anchors_no_extrapolation",
                "scope": "intrinsic_cleavage_emission_competition",
            })
    return outputs


def _piecewise_value(table: Mapping[float, tuple], x: float) -> tuple:
    """Linear interpolation across explicit coverage anchors, never extrapolate."""
    points = sorted((float(k), tuple(float(v) for v in value)) for k, value in table.items())
    if not points or x < points[0][0] - 1e-12 or x > points[-1][0] + 1e-12:
        raise MissingDependencyError(f"coverage {x} is outside the sourced curve")
    for point_x, point_y in points:
        if math.isclose(x, point_x, rel_tol=0.0, abs_tol=1e-12):
            return point_y
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 < x < x1:
            fraction = (x - x0) / (x1 - x0)
            return tuple(a + fraction * (b - a) for a, b in zip(y0, y1))
    raise MissingDependencyError(f"coverage {x} cannot be resolved from the supplied curve")


def _zero_crossing(x0: float, y0: float, x1: float, y1: float) -> float | None:
    if y0 == 0.0:
        return x0
    if y1 == 0.0:
        return x1
    if y0 * y1 > 0:
        return None
    return x0 + (-y0 / (y1 - y0)) * (x1 - x0)


def analytic_boundary_segments(
    alpha_gpa: float,
    beta_gpa: float,
    gamma_f_curve: Mapping[float, tuple[float, float, float]],
    gamma_usf_curve: Mapping[float, tuple[float, float]],
    nucleation_areas_a2: Sequence[float] = NUCLEATION_AREA_SENSITIVITY_A2,
) -> list[dict]:
    """Clip each exact affine D=0 contour to every source-anchor rectangle.

    Within a cell bounded by C_surface/C_usf anchors (0, .5, 1), both
    source curves are linear and the axes are independent, so each D bound is
    affine. Returned cell endpoints include every edge intersection and all
    source kinks are explicit cell boundaries; no grid tracing is used.
    """
    cs_anchors = sorted(float(x) for x in gamma_f_curve)
    cu_anchors = sorted(float(x) for x in gamma_usf_curve)
    if cs_anchors[0] > 0 or cs_anchors[-1] < 1 or cu_anchors[0] > 0 or cu_anchors[-1] < 1:
        raise MissingDependencyError("both curves must cover [0,1]")
    segments: list[dict] = []
    for area in nucleation_areas_a2:
        if not math.isfinite(float(area)) or float(area) <= 0:
            raise ValueError("nucleation areas must be positive")
        for cs0, cs1 in zip(cs_anchors, cs_anchors[1:]):
            for cu0, cu1 in zip(cu_anchors, cu_anchors[1:]):
                for bound_name, gi, std_factor in (("D_low", 1, 0.0), ("D_center", 0, 0.0),
                                                   ("D_high", 2, math.sqrt(USF_AREA_A2 / float(area)))):
                    points: list[tuple[float, float]] = []
                    def value(cs: float, cu: float) -> float:
                        gf = _piecewise_value(gamma_f_curve, cs)[gi]
                        gu, gu_std = _piecewise_value(gamma_usf_curve, cu)
                        return alpha_gpa * gf - beta_gpa * (gu - gu_std * std_factor) / 1000.0
                    for cs in (cs0, cs1):
                        root = _zero_crossing(cu0, value(cs, cu0), cu1, value(cs, cu1))
                        if root is not None and cu0 - 1e-12 <= root <= cu1 + 1e-12:
                            points.append((cs, min(cu1, max(cu0, root))))
                    for cu in (cu0, cu1):
                        root = _zero_crossing(cs0, value(cs0, cu), cs1, value(cs1, cu))
                        if root is not None and cs0 - 1e-12 <= root <= cs1 + 1e-12:
                            points.append((min(cs1, max(cs0, root)), cu))
                    unique: list[tuple[float, float]] = []
                    for point in points:
                        if not any(math.isclose(point[0], prev[0], abs_tol=1e-10) and
                                   math.isclose(point[1], prev[1], abs_tol=1e-10) for prev in unique):
                            unique.append(point)
                    if len(unique) >= 2:
                        segments.append({
                            "A_nucleation_A2": float(area), "boundary": bound_name,
                            "C_surface_cell": [cs0, cs1], "C_usf_cell": [cu0, cu1],
                            "endpoints_C_surface_C_usf": unique,
                            "contour_equation": "alpha*gammaF(C_surface)-beta*(gammaUSF_mean(C_usf)-scaled_sigma)/1000=0",
                            "sigma_factor": std_factor,
                        })
    return segments


def exact_region_areas(alpha_gpa: float, beta_gpa: float,
                       gamma_f_curve: Mapping[float, tuple[float, float, float]],
                       gamma_usf_curve: Mapping[float, tuple[float, float]],
                       nucleation_areas_a2: Sequence[float] = NUCLEATION_AREA_SENSITIVITY_A2) -> list[dict]:
    """Exact cleavage/emission/uncertain areas by clipping each anchor cell.

    D_low and D_high are affine per cell. The uncertain region is their
    intersection with D_low<=0<=D_high; robust regions are complementary
    half-plane clips. Polygon areas are summed over the four anchor cells.
    """
    def clip(poly, f, keep_nonpositive):
        if not poly:
            return []
        out = []
        for p, q in zip(poly, poly[1:] + poly[:1]):
            fp, fq = f(*p), f(*q)
            inp = fp <= 1e-12 if keep_nonpositive else fp >= -1e-12
            inq = fq <= 1e-12 if keep_nonpositive else fq >= -1e-12
            if inp:
                out.append(p)
            if inp != inq:
                t = fp / (fp - fq)
                out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
        return out
    def area(poly):
        return abs(sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(poly, poly[1:] + poly[:1]))) / 2 if len(poly) >= 3 else 0.0
    result = []
    f_anchors, u_anchors = sorted(gamma_f_curve), sorted(gamma_usf_curve)
    for nucleation_area in nucleation_areas_a2:
        totals = {"cleavage_first_robust": 0.0, "emission_first_robust": 0.0, "competition_uncertain": 0.0}
        for x0, x1 in zip(f_anchors, f_anchors[1:]):
            for y0, y1 in zip(u_anchors, u_anchors[1:]):
                def d(x, y, which):
                    gf = _piecewise_value(gamma_f_curve, x)
                    gu, us = _piecewise_value(gamma_usf_curve, y)
                    sig = us * math.sqrt(USF_AREA_A2 / float(nucleation_area))
                    gi = {"low": 1, "high": 2}[which]
                    us_term = gu if which == "low" else gu - sig
                    return alpha_gpa * gf[gi] - beta_gpa * us_term / 1000
                cell = [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
                # D_high<0: robust cleavage. D_low>0: robust emission.
                totals["cleavage_first_robust"] += area(clip(cell, lambda x,y: d(x,y,"high"), True))
                totals["emission_first_robust"] += area(clip(cell, lambda x,y: d(x,y,"low"), False))
                uncertain = clip(clip(cell, lambda x,y: d(x,y,"low"), True), lambda x,y: d(x,y,"high"), False)
                totals["competition_uncertain"] += area(uncertain)
        result.append({"A_nucleation_A2": float(nucleation_area), **totals,
                       "domain_area": 1.0, "area_sum": sum(totals.values())})
    return result


def extrema_certificate(alpha_gpa: float, beta_gpa: float,
                        gamma_f_curve: Mapping[float, tuple[float, float, float]],
                        gamma_usf_curve: Mapping[float, tuple[float, float]],
                        nucleation_area_a2: float = NUCLEATION_AREA_A2) -> dict:
    """Certify full-domain D-bound extrema from all piecewise-cell vertices."""
    candidates = []
    for cs in sorted(gamma_f_curve):
        for cu in sorted(gamma_usf_curve):
            gf = _piecewise_value(gamma_f_curve, float(cs))
            gu, std = _piecewise_value(gamma_usf_curve, float(cu))
            scaled = std * math.sqrt(USF_AREA_A2 / float(nucleation_area_a2))
            candidates.append({
                "C_surface": float(cs), "C_usf": float(cu),
                "D_low_GPa_J_m2": alpha_gpa * gf[1] - beta_gpa * gu / 1000,
                "D_high_GPa_J_m2": alpha_gpa * gf[2] - beta_gpa * (gu-scaled) / 1000,
            })
    min_low = min(candidates, key=lambda r: r["D_low_GPa_J_m2"])
    max_low = max(candidates, key=lambda r: r["D_low_GPa_J_m2"])
    min_high = min(candidates, key=lambda r: r["D_high_GPa_J_m2"])
    max_high = max(candidates, key=lambda r: r["D_high_GPa_J_m2"])
    if max_high["D_high_GPa_J_m2"] < 0:
        certificate = "cleavage_first_robust_entire_domain"
    elif min_low["D_low_GPa_J_m2"] > 0:
        certificate = "emission_first_robust_entire_domain"
    else:
        certificate = "local_competition_or_uncertainty_present"
    return {"A_nucleation_A2": float(nucleation_area_a2), "vertices_checked": len(candidates),
            "min_D_low": min_low, "max_D_low": max_low,
            "min_D_high": min_high, "max_D_high": max_high,
            "whole_domain_certificate": certificate}


def write_case_outputs(asset_dir: str | Path, output_dir: str | Path, *, grid_size: int = 101) -> None:
    """CLI-friendly output writer for full 6-alloy phase maps and exact contours."""
    asset_dir, output_dir = Path(asset_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    elastic = load_elastic_parameters(asset_dir / "elastic_constants_fig2a.csv")
    gf = load_gamma_f_curve(asset_dir / "gamma_f_fig2b_digitized.csv")
    gu = load_gamma_usf_parameters(asset_dir / "gamma_usf_fig2c_parameters.csv")
    grid = compute_phase_map(elastic, gf, gu, grid_size=grid_size)
    with (output_dir / "phase_map.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(grid[0]))
        writer.writeheader(); writer.writerows(grid)
    contours, areas, extrema = [], [], []
    for alloy in EXPECTED_ALLOYS:
        contours.extend({"alloy": alloy, **item} for item in analytic_boundary_segments(elastic[alloy]["alpha_GPa"], elastic[alloy]["beta_GPa"], gf[alloy], gu[alloy]))
        areas.extend({"alloy": alloy, **item} for item in exact_region_areas(elastic[alloy]["alpha_GPa"], elastic[alloy]["beta_GPa"], gf[alloy], gu[alloy]))
        extrema.extend({"alloy": alloy, **extrema_certificate(elastic[alloy]["alpha_GPa"], elastic[alloy]["beta_GPa"], gf[alloy], gu[alloy], area)} for area in NUCLEATION_AREA_SENSITIVITY_A2)
    (output_dir / "analytic_boundaries.json").write_text(json.dumps(contours, indent=2) + "\n", encoding="utf-8")
    with (output_dir / "region_areas.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(areas[0]))
        writer.writeheader(); writer.writerows(areas)
    (output_dir / "extrema_certificates.json").write_text(json.dumps(extrema, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--grid-size", type=int, default=101)
    args = parser.parse_args()
    write_case_outputs(args.assets, args.output, grid_size=args.grid_size)


CCB_SOLVE_PY
APP="${APP:-/app}"
mkdir -p "$APP/final"
python3 "$work_dir/solve.py" --assets "$APP/assets" --output "$APP/final" --grid-size 101
