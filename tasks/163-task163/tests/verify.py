#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Analyse alkene conical-intersection geometries and surface-hopping evidence.
"""Case-02 layered verifier: 2D-grid static photochemistry analysis.

Exit codes: 0 PASS, 1 candidate FAIL, 2 evaluator ENV_ERROR.
All references are recomputed from the public grid databases bundled with the package.
"""
from __future__ import annotations

import argparse
import csv
from io import BytesIO
import hashlib
import json
import sys
from pathlib import Path

try:
    import numpy as np
    from ase.db import connect
    from PIL import Image
except ImportError as exc:
    print(f"ENV_ERROR: required dependency unavailable: {exc}", file=sys.stderr)
    raise SystemExit(2)

REFERENCES: dict | None = None
QUANTILE_FAMILY: str | None = None
THRESHOLD_FAMILY: str | None = None
PINNED_REFERENCE_POLICY_SHA256 = "6f59838fe4c8ef5cb9c15a9d794d27de3cb097738f363d722d3b069ce4c8387b"


def load_references(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != PINNED_REFERENCE_POLICY_SHA256:
        raise ValueError("refs.json canonical policy digest differs from the reviewed case-02 policy")
    if not isinstance(value, dict) or value.get("schema") != "bench25-case02-reference-policy/v1":
        raise ValueError("unsupported refs.json schema")
    units, windows, tolerances = value.get("unit_conversions"), value.get("windows"), value.get("tolerances")
    tolerance_keys = {"theta_match_deg", "overlap_zero", "overlap_full", "r_search_margin_bohr", "boundary_margin", "metrics_relative", "axis_summary", "grid_radius_match_bohr", "grid_property_relative", "grid_property_absolute_floor", "region_window", "region_metric_relative", "paper_dihedral_overlap_deg", "paper_r_overlap_bohr", "conclusion"}
    if (not isinstance(units, dict) or set(units) != {"hartree_to_ev"}
            or not isinstance(windows, dict) or set(windows) != {"paper_dihedral_deg", "paper_r_cc_bohr", "calibrated_dihedral_deg"}
            or not isinstance(tolerances, dict) or set(tolerances) != tolerance_keys
            or value.get("selector_families") != ["nac_norm_quantile_window/v1", "gap_nac_threshold_window/v1"]):
        raise ValueError("refs.json fields do not match the case-02 policy schema")
    numbers = list(units.values()) + list(tolerances.values())
    for pair in windows.values():
        if not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(x, (int, float)) or isinstance(x, bool) or not np.isfinite(x) for x in pair):
            raise ValueError("refs.json windows must be finite numeric pairs")
        numbers.extend(pair)
    if any(not isinstance(x, (int, float)) or isinstance(x, bool) or not np.isfinite(x) or x < 0 for x in numbers):
        raise ValueError("refs.json policy values must be finite nonnegative numbers")
    return value


def policy(name: str) -> float:
    return float(REFERENCES["tolerances"][name])


class CandidateFail(Exception):
    pass


def read_csv_rows(path: Path, expected_header: list[str]) -> list[dict]:
    if not path.is_file():
        raise CandidateFail(f"missing outputs file: {path.name}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise CandidateFail(f"{path.name} is empty")
        if [h.strip() for h in header] != expected_header:
            raise CandidateFail(f"{path.name} header mismatch: {header} != {expected_header}")
        return [dict(zip(expected_header, row)) for row in reader if row]


def dihedral(p0, p1, p2, p3) -> float:
    b0 = p0 - p1
    b1 = p2 - p1
    b2 = p3 - p2
    b1n = b1 / np.linalg.norm(b1)
    v = b0 - np.dot(b0, b1n) * b1n
    w = b2 - np.dot(b2, b1n) * b1n
    return np.degrees(np.arctan2(np.dot(np.cross(b1n, v), w), np.dot(v, w)))


def sp2_frame(pos: np.ndarray, numbers: np.ndarray):
    cidx = list(np.where(numbers == 6)[0])
    hidx = list(np.where(numbers == 1)[0])
    bonded = {c: [h for h in hidx if np.linalg.norm(pos[c] - pos[h]) < 2.4] for c in cidx}
    sp2 = [c for c in cidx if len(bonded[c]) <= 2]  # CH2/CH carbons; methyl carbons have 3 H
    if len(sp2) != 2:
        raise RuntimeError(f"cannot identify sp2 carbons: {sp2}")
    c0, c1 = sp2
    h0 = min(bonded[c0], key=lambda h: np.linalg.norm(pos[c0] - pos[h]))
    h1 = min(bonded[c1], key=lambda h: np.linalg.norm(pos[c1] - pos[h]))
    return c0, c1, h0, h1


def recompute_truth(inputs_dir: Path) -> dict:
    truth = {}
    for molecule, fname in (("C2H4", "04_3Sing_C2H4_grid.db"), ("C3H6", "05_3Sing_C3H6_grid.db"),
                            ("C4H8", "06_3Sing_C4H8_grid.db")):
        database_path = inputs_dir / fname
        if not database_path.is_file():
            raise RuntimeError(f"public database is missing: {database_path}")
        pts = []
        for row in connect(database_path).select():
            pos = np.asarray(row.positions, dtype=float)  # Bohr
            numbers = np.asarray(row.numbers)
            c0, c1, h0, h1 = sp2_frame(pos, numbers)
            r = float(np.linalg.norm(pos[c1] - pos[c0]))
            th = abs(dihedral(pos[h0], pos[c0], pos[c1], pos[h1]))
            energy = np.asarray(row.data["energy"], dtype=float).reshape(-1)
            gap = float(energy[1] - energy[0]) * REFERENCES["unit_conversions"]["hartree_to_ev"]
            dip = np.asarray(row.data["dipoles"], dtype=float)
            mu10 = dip[3]
            f01 = (2.0 / 3.0) * float(energy[1] - energy[0]) * float(np.dot(mu10, mu10))
            nac01 = float(np.linalg.norm(np.asarray(row.data["nacs"], dtype=float)[:, 0, :]))
            pts.append((r, th, energy[0], energy[1], energy[2], gap, f01, nac01))
        if len(pts) != 3731:
            raise RuntimeError(f"{fname}: expected 3,731 public grid rows, found {len(pts)}")
        pts.sort(key=lambda p: (round(p[1], 3), round(p[0], 4)))
        truth[molecule] = pts
    return truth


def theta_matches(a: float, b: float, tol: float | None = None) -> bool:
    a, b = abs(a), abs(b)
    tol = policy("theta_match_deg") if tol is None else tol
    return abs(a - b) <= tol or abs(180.0 - a - b) <= tol


def overlap(x0: float, x1: float, lo: float, hi: float) -> float:
    return max(0.0, min(x1, hi) - max(x0, lo))


def overlap_category(width: float, candidate_width: float, paper_width: float) -> str:
    if width <= policy("overlap_zero"):
        return "none"
    if abs(width - min(candidate_width, paper_width)) <= policy("overlap_full"):
        return "full"
    return "partial"


def recompute_selection(points: list[tuple], family: str, search: dict, parameters: dict, molecule: str) -> dict:
    rlo, rhi = (number(x, "search r bound") for x in search["r_cc_bohr"])
    dlo, dhi = (number(x, "search dihedral bound") for x in search["dihedral_deg"])
    if rhi <= rlo or dlo < REFERENCES["windows"]["calibrated_dihedral_deg"][0] or dhi > REFERENCES["windows"]["calibrated_dihedral_deg"][1] or dhi <= dlo:
        raise CandidateFail(f"{molecule}: invalid selector search rectangle")
    if rlo < min(p[0] for p in points) - policy("r_search_margin_bohr") or rhi > max(p[0] for p in points) + policy("r_search_margin_bohr"):
        raise CandidateFail(f"{molecule}: selector r search rectangle exceeds the sampled grid")
    population = [p for p in points if rlo <= p[0] <= rhi and dlo <= p[1] <= dhi]
    if not population:
        raise CandidateFail(f"{molecule}: selector search rectangle has no grid points")
    if family == QUANTILE_FAMILY:
        q = number(parameters.get("quantile"), "selector quantile")
        if not 0 < q < 1:
            raise CandidateFail(f"{molecule}: quantile must be in (0,1)")
        threshold = float(np.quantile([p[7] for p in population], q))
        chosen = [p for p in population if p[7] >= threshold]
        metrics = {"quantile": q, "nac_threshold_1_per_bohr": threshold}
    elif family == THRESHOLD_FAMILY:
        gap_max = number(parameters.get("gap_max_eV"), "gap_max_eV")
        nac_min = number(parameters.get("nac_min_1_per_bohr"), "nac_min_1_per_bohr")
        chosen = [p for p in population if p[5] <= gap_max and p[7] >= nac_min]
        metrics = {"gap_max_eV": gap_max, "nac_min_1_per_bohr": nac_min}
    else:
        raise CandidateFail(f"{molecule}: unsupported selector family {family!r}")
    if not chosen:
        raise CandidateFail(f"{molecule}: selector parameters select no grid points")
    rr = [p[0] for p in chosen]
    tt = [p[1] for p in chosen]
    envelope = [p for p in points if min(rr) <= p[0] <= max(rr) and min(tt) <= p[1] <= max(tt)]
    all_r, all_t = [p[0] for p in points], [p[1] for p in points]
    metrics.update({
        "search_population": len(population), "selected_points": len(chosen),
        "r_extent_bohr": [min(rr), max(rr)], "dihedral_extent_deg": [min(tt), max(tt)],
        "selected_min_gap_eV": min(p[5] for p in chosen),
        "selected_max_nac01_1_per_bohr": max(p[7] for p in chosen),
        "envelope_grid_points": len(envelope), "envelope_min_gap_eV": min(p[5] for p in envelope),
        "envelope_max_nac01_1_per_bohr": max(p[7] for p in envelope),
        "touches_r_grid_boundary": min(rr) <= min(all_r) + policy("boundary_margin") or max(rr) >= max(all_r) - policy("boundary_margin"),
        "touches_dihedral_grid_boundary": min(tt) <= min(all_t) + policy("boundary_margin") or max(tt) >= max(all_t) - policy("boundary_margin"),
    })
    return metrics


def check_recomputed_metrics(actual: dict, expected: dict, molecule: str) -> None:
    if not isinstance(actual, dict) or set(actual) != set(expected):
        raise CandidateFail(f"{molecule}: sensitivity entry fields do not match the executable schema")
    for key, value in expected.items():
        got = actual[key]
        if isinstance(value, dict):
            if got != value:
                raise CandidateFail(f"{molecule}: sensitivity {key} mismatch")
        elif isinstance(value, bool):
            if got is not value:
                raise CandidateFail(f"{molecule}: sensitivity {key} mismatch")
        elif isinstance(value, int):
            if int(got) != value:
                raise CandidateFail(f"{molecule}: sensitivity {key} mismatch")
        elif isinstance(value, list):
            if not isinstance(got, list) or len(got) != len(value) or any(abs(number(a, key)-b) > policy("metrics_relative") for a, b in zip(got, value)):
                raise CandidateFail(f"{molecule}: sensitivity {key} mismatch")
        elif abs(number(got, key) - value) > policy("metrics_relative") * max(1.0, abs(value)):
            raise CandidateFail(f"{molecule}: sensitivity {key} mismatch")


def number(value: str, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateFail(f"{label} is not numeric: {value!r}") from exc
    if not np.isfinite(result):
        raise CandidateFail(f"{label} must be finite")
    return result


def axis_definition(points: list[tuple], coordinate: int, digits: int) -> tuple[float, float, float, int]:
    values = sorted({round(point[coordinate], digits) for point in points})
    steps = np.diff(np.asarray(values, dtype=float))
    if not len(steps) or not np.allclose(steps, steps[0], atol=10 ** (-digits), rtol=0):
        raise RuntimeError("reference grid axis is not regular")
    return float(values[0]), float(values[-1]), float(steps[0]), len(values)


def nonempty_description(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(value) and any(nonempty_description(item) for item in value.values())
    if isinstance(value, list):
        return bool(value) and any(nonempty_description(item) for item in value)
    return value is not None


def valid_ci_interpretation(value) -> bool:
    if not isinstance(value, dict):
        return False
    if (value.get("evidence_scope") != "finite_static_grid_proxy"
            or value.get("exact_ci_seam_established") is not False
            or value.get("dynamical_visitation_established") is not False):
        return False
    if "evidence_reference" not in value:
        return True
    reference = value["evidence_reference"]
    return isinstance(reference, str) and bool(reference.strip())


def valid_ci_notes(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_axis_summary(entry: dict, prefix: str, expected: tuple, molecule: str) -> None:
    lo, hi, step, count = expected
    range_keys = {
        "r_cc_bohr": ("r_cc_bohr_range", "r_range_bohr", "r_bohr_range", "r_range"),
        "dihedral_deg": ("dihedral_deg_range", "dihedral_range_deg", "dihedral_range"),
    }[prefix]
    step_keys = {
        "r_cc_bohr": ("r_cc_bohr_step", "r_step_bohr", "r_bohr_step", "r_step"),
        "dihedral_deg": ("dihedral_deg_step", "dihedral_step_deg", "dihedral_step"),
    }[prefix]
    range_key = next((key for key in range_keys if key in entry), None)
    range_value = entry.get(range_key) if range_key is not None else None
    if not isinstance(range_value, list) or len(range_value) != 2:
        raise CandidateFail(f"{molecule}: grid_definition missing {prefix}_range")
    if abs(number(range_value[0], prefix + " range min") - lo) > policy("axis_summary") or abs(number(range_value[1], prefix + " range max") - hi) > policy("axis_summary"):
        raise CandidateFail(f"{molecule}: grid_definition {prefix}_range does not match public grid")
    step_key = next((key for key in step_keys if key in entry), None)
    step_value = entry.get(step_key) if step_key is not None else None
    if step_value is None or abs(number(step_value, prefix + " step") - step) > policy("axis_summary"):
        raise CandidateFail(f"{molecule}: grid_definition {prefix} step does not match public grid")
    count_key = "dihedral_unique_count" if prefix == "dihedral_deg" else prefix + "_unique_count"
    count_value = entry.get(prefix + "_unique_count", entry.get(count_key))
    if count_value is not None and int(count_value) != count:
        raise CandidateFail(f"{molecule}: grid_definition {count_key} does not match public grid")


def is_valid_png(raw: bytes) -> bool:
    try:
        with Image.open(BytesIO(raw), formats=("PNG",)) as image:
            image.verify()
        with Image.open(BytesIO(raw), formats=("PNG",)) as image:
            image.load()
            return image.width > 0 and image.height > 0
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", nargs="?", default=".")
    parser.add_argument("--public-input-root", type=Path, default=None,
                        help="root directory containing the read-only public database files")
    parser.add_argument("--reference-file", type=Path, default=Path(__file__).with_name("refs.json"))
    parser.add_argument("--reference-dir", type=Path, default=None)
    parser.add_argument("--suite-root", type=Path, default=None)
    args = parser.parse_args()

    global REFERENCES
    try:
        REFERENCES = load_references(args.reference_file)
    except Exception as exc:
        print(f"ENV_ERROR: reference policy unavailable: {exc}", file=sys.stderr)
        return 2

    global QUANTILE_FAMILY, THRESHOLD_FAMILY
    PAPER_DIH = tuple(REFERENCES["windows"]["paper_dihedral_deg"])
    PAPER_R = tuple(REFERENCES["windows"]["paper_r_cc_bohr"])
    QUANTILE_FAMILY, THRESHOLD_FAMILY = REFERENCES["selector_families"]
    out = Path(args.output_dir) / "outputs"
    package = Path(__file__).resolve().parents[1]
    inputs_dir = args.public_input_root or package / "environment" / "assets" / "databases"
    if not out.is_dir():
        raise CandidateFail("missing outputs/")
    try:
        truth = recompute_truth(inputs_dir)
    except Exception as exc:
        print(f"ENV_ERROR: reference recomputation failed: {exc}", file=sys.stderr)
        return 2

    # ---------- L1: files ----------
    for name in ("grid_map.csv", "ci_region.csv", "summary.json"):
        if not (out / name).is_file():
            raise CandidateFail(f"missing outputs/{name}")
    figures = list((out / "figures").glob("*.png")) if (out / "figures").is_dir() else []
    valid_figures = []
    for path in figures:
        if is_valid_png(path.read_bytes()):
            valid_figures.append(path)
    if len(valid_figures) < 2:
        raise CandidateFail("outputs/figures must contain at least two fully decodable PNG images")

    # ---------- L2: grid_map.csv ----------
    map_header = ["molecule", "point_index", "r_cc_bohr", "dihedral_deg", "e0_hartree",
                  "e1_hartree", "e2_hartree", "gap_S10_eV", "f_01", "nac01_norm"]
    rows = read_csv_rows(out / "grid_map.csv", map_header)
    expected_total = sum(len(points) for points in truth.values())
    if len(rows) != expected_total:
        raise CandidateFail(f"grid_map must have {expected_total} rows, got {len(rows)}")
    by_mol = {m: [] for m in truth}
    for r in rows:
        if r["molecule"] not in by_mol:
            raise CandidateFail(f"unknown molecule {r['molecule']}")
        by_mol[r["molecule"]].append(r)
    for molecule, pts in truth.items():
        agent_rows = by_mol[molecule]
        if len(agent_rows) != len(pts):
            raise CandidateFail(f"{molecule}: expected {len(pts)} rows, got {len(agent_rows)}")
        # Match every output point to the public grid as a one-to-one assignment.
        # At 0/180 degrees both H-pair conventions can be geometrically equivalent,
        # so matching each CSV row greedily can either reject a valid file or reuse a point.
        point_indices = []
        candidates_by_row = []
        by_r = {}
        for i, point in enumerate(pts):
            by_r.setdefault(round(point[0], 3), []).append((i, point))
        for row in agent_rows:
            rv, tv = number(row["r_cc_bohr"], "r_cc_bohr"), abs(number(row["dihedral_deg"], "dihedral_deg"))
            rnear = [item for k in (round(rv, 3) - 0.001, round(rv, 3), round(rv, 3) + 0.001)
                     for item in by_r.get(round(k, 3), [])]
            candidates = [(i, p) for i, p in rnear
                          if abs(p[0] - rv) <= policy("grid_radius_match_bohr") and
                          (abs(p[1] - tv) <= policy("theta_match_deg") or abs((180.0 - p[1]) - tv) <= policy("theta_match_deg"))]
            value_fields = (("e0_hartree", 2), ("e1_hartree", 3), ("e2_hartree", 4),
                            ("gap_S10_eV", 5), ("f_01", 6), ("nac01_norm", 7))
            candidates = [(i, p) for i, p in candidates
                          if all(abs(number(row[field], field) - p[index]) <=
                                 max(policy("grid_property_relative") * abs(p[index]), policy("grid_property_absolute_floor"))
                                 for field, index in value_fields)]
            if not candidates:
                raise CandidateFail(f"{molecule}: grid point (r={rv}, theta={tv}) not found in reference grid")
            candidates_by_row.append([item[0] for item in candidates])
            point_indices.append(int(row["point_index"]))
        assigned = {}
        def assign(row_index: int, visited: set[int]) -> bool:
            for ref_index in candidates_by_row[row_index]:
                if ref_index in visited:
                    continue
                visited.add(ref_index)
                if ref_index not in assigned or assign(assigned[ref_index], visited):
                    assigned[ref_index] = row_index
                    return True
            return False
        for row_index in range(len(agent_rows)):
            if not assign(row_index, set()):
                raise CandidateFail(f"{molecule}: grid points do not map one-to-one to the public grid")
        row_to_ref = {row_index: ref_index for ref_index, row_index in assigned.items()}
        for row_index, row in enumerate(agent_rows):
            hit = row_to_ref[row_index]
            _, _, e0, e1, e2, gap, f01, n01 = pts[hit]
            for field, ref, tol in (("e0_hartree", e0, policy("grid_property_relative")), ("e1_hartree", e1, policy("grid_property_relative")),
                                    ("e2_hartree", e2, policy("grid_property_relative")), ("gap_S10_eV", gap, policy("grid_property_relative")),
                                    ("f_01", f01, policy("grid_property_relative")), ("nac01_norm", n01, policy("grid_property_relative"))):
                av = number(row[field], field)
                if abs(av - ref) > max(tol * abs(ref), policy("grid_property_absolute_floor")):
                    raise CandidateFail(
                        f"{molecule} (r={rv}, theta={tv}): {field} {av} != reference {ref:.8g}")
        if len(assigned) != len(pts) or sorted(point_indices) != list(range(len(pts))):
            raise CandidateFail(f"{molecule}: grid_map point_index values must cover 0..{len(pts)-1} exactly once")

    # ---------- L1/L2: summary grid_definition ----------
    try:
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CandidateFail(f"summary.json is not valid JSON: {exc}")
    if summary.get("schema") != "case02/scientific-summary/v2":
        raise CandidateFail("summary.json schema must be case02/scientific-summary/v2")
    for key in ("grid_definition", "ci_criteria", "paper_comparison", "figures"):
        if key not in summary:
            raise CandidateFail(f"summary.json missing key: {key}")
    criteria = summary["ci_criteria"]
    if not isinstance(criteria, dict) or not valid_ci_interpretation(criteria.get("interpretation")):
        raise CandidateFail("ci_criteria must make the bounded static-grid interpretation explicit")
    criterion_molecules = criteria.get("molecules")
    if not isinstance(criterion_molecules, dict) or set(criterion_molecules) != set(truth):
        raise CandidateFail("ci_criteria.molecules must cover all three molecules")
    comparison = summary["paper_comparison"]
    if not isinstance(comparison, dict) or not isinstance(comparison.get("per_molecule"), dict) or set(comparison["per_molecule"]) != set(truth):
        raise CandidateFail("paper_comparison.per_molecule must contain structured conclusions for all molecules")
    figure_descriptions = summary["figures"]
    if not isinstance(figure_descriptions, list) or len(figure_descriptions) < 2 or not all(
            isinstance(item, str) and item.strip() for item in figure_descriptions):
        raise CandidateFail("summary.json figures must list at least two figure descriptions")
    grid_summary = summary["grid_definition"]
    if not isinstance(grid_summary, dict) or set(grid_summary) != set(truth):
        raise CandidateFail("summary.json grid_definition must cover all three molecules")
    for molecule, pts in truth.items():
        entry = grid_summary[molecule]
        if not isinstance(entry, dict):
            raise CandidateFail(f"{molecule}: grid_definition must be an object")
        check_axis_summary(entry, "r_cc_bohr", axis_definition(pts, 0, 4), molecule)
        check_axis_summary(entry, "dihedral_deg", axis_definition(pts, 1, 3), molecule)
        if entry.get("points") is not None and int(entry["points"]) != len(pts):
            raise CandidateFail(f"{molecule}: grid_definition point count does not match public grid")

    # ---------- L3: ci_region.csv ----------
    ci_header = ["molecule", "criterion", "r_cc_min_bohr", "r_cc_max_bohr", "dihedral_min_deg",
                 "dihedral_max_deg", "n_points", "min_gap_eV", "max_nac01",
                 "overlap_with_paper_dihedral_deg", "overlap_with_paper_r_bohr", "notes"]
    ci_rows = read_csv_rows(out / "ci_region.csv", ci_header)
    if len(ci_rows) != len(truth) or {r["molecule"] for r in ci_rows} != set(truth):
        raise CandidateFail("ci_region must cover all three molecules exactly once")
    for row in ci_rows:
        molecule = row["molecule"]
        dlo, dhi = number(row["dihedral_min_deg"], "dihedral_min_deg"), number(row["dihedral_max_deg"], "dihedral_max_deg")
        rlo, rhi = number(row["r_cc_min_bohr"], "r_cc_min_bohr"), number(row["r_cc_max_bohr"], "r_cc_max_bohr")
        if dhi <= dlo or rhi <= rlo:
            raise CandidateFail(f"{molecule}: empty CI window")
        if dlo < REFERENCES["windows"]["calibrated_dihedral_deg"][0] or dhi > REFERENCES["windows"]["calibrated_dihedral_deg"][1]:
            raise CandidateFail(
                f"{molecule}: dihedral window [{dlo},{dhi}] outside data-calibrated coupling ridge {REFERENCES['windows']['calibrated_dihedral_deg']}")
        pts = truth[molecule]
        claim = criterion_molecules[molecule]
        if not isinstance(claim, dict) or set(claim) != {"selector", "sensitivity", "selected_sensitivity_index"}:
            raise CandidateFail(f"{molecule}: ci criterion must use the v2 executable structure")
        selector = claim["selector"]
        if not isinstance(selector, dict) or set(selector) != {"family", "search_rectangle", "parameters"}:
            raise CandidateFail(f"{molecule}: selector fields are invalid")
        family, search, selected_parameters = selector["family"], selector["search_rectangle"], selector["parameters"]
        if not isinstance(search, dict) or set(search) != {"r_cc_bohr", "dihedral_deg"}:
            raise CandidateFail(f"{molecule}: search_rectangle fields are invalid")
        if (not isinstance(selected_parameters, dict) or
                set(selected_parameters) != ({"quantile"} if family == QUANTILE_FAMILY else
                                             {"gap_max_eV", "nac_min_1_per_bohr"} if family == THRESHOLD_FAMILY else set())):
            raise CandidateFail(f"{molecule}: unsupported or malformed selector family")
        sensitivity = claim["sensitivity"]
        if not isinstance(sensitivity, list) or len(sensitivity) < 2:
            raise CandidateFail(f"{molecule}: at least two sensitivity criteria are required")
        sensitivity_keys = []
        sensitivity_metrics = []
        for entry in sensitivity:
            if not isinstance(entry, dict) or set(entry) != {"parameters", "search_population", "selected_points",
                    "r_extent_bohr", "dihedral_extent_deg", "selected_min_gap_eV", "selected_max_nac01_1_per_bohr",
                    "envelope_grid_points", "envelope_min_gap_eV", "envelope_max_nac01_1_per_bohr",
                    "touches_r_grid_boundary", "touches_dihedral_grid_boundary"} | (
                        {"nac_threshold_1_per_bohr", "quantile"} if family == QUANTILE_FAMILY else
                        {"gap_max_eV", "nac_min_1_per_bohr"}):
                raise CandidateFail(f"{molecule}: sensitivity entry fields are invalid")
            params = entry["parameters"]
            required_parameter_keys = {"quantile"} if family == QUANTILE_FAMILY else {"gap_max_eV", "nac_min_1_per_bohr"}
            if not isinstance(params, dict) or set(params) != required_parameter_keys:
                raise CandidateFail(f"{molecule}: sensitivity parameters are invalid")
            key = tuple(number(params[k], k) for k in sorted(required_parameter_keys))
            sensitivity_keys.append(key)
            recomputed = recompute_selection(pts, family, search, params, molecule)
            metrics = {"parameters": params, **recomputed}
            check_recomputed_metrics(entry, metrics, molecule)
            sensitivity_metrics.append(recomputed)
        if len(set(sensitivity_keys)) != len(sensitivity_keys):
            raise CandidateFail(f"{molecule}: sensitivity criteria must be distinct")
        try:
            selected_index = int(claim["selected_sensitivity_index"])
        except (TypeError, ValueError) as exc:
            raise CandidateFail(f"{molecule}: selected_sensitivity_index must be an integer") from exc
        if selected_index < 0 or selected_index >= len(sensitivity):
            raise CandidateFail(f"{molecule}: selected_sensitivity_index is out of range")
        selected_entry = sensitivity[selected_index]
        if selected_parameters != selected_entry["parameters"]:
            raise CandidateFail(f"{molecule}: selector parameters do not match the selected sensitivity entry")
        selected_result = sensitivity_metrics[selected_index]
        if any(abs(x-y) > policy("region_window") for x, y in zip((rlo, rhi, dlo, dhi),
                (*selected_result["r_extent_bohr"], *selected_result["dihedral_extent_deg"]))):
            raise CandidateFail(f"{molecule}: ci_region window does not match selected sensitivity criterion")
        inside = [p for p in pts if rlo <= p[0] <= rhi and dlo <= p[1] <= dhi]
        if not inside:
            raise CandidateFail(f"{molecule}: CI window contains no grid points")
        if int(row["n_points"]) != len(inside):
            raise CandidateFail(f"{molecule}: n_points {row['n_points']} != {len(inside)}")
        if not (abs(number(row["min_gap_eV"], "min_gap_eV") - min(p[5] for p in inside)) <= policy("region_metric_relative") * max(1.0, abs(min(p[5] for p in inside)))):
            raise CandidateFail(f"{molecule}: min_gap_eV inconsistent with recomputed window")
        if not (abs(number(row["max_nac01"], "max_nac01") - max(p[7] for p in inside)) <= policy("region_metric_relative") * max(1.0, max(p[7] for p in inside))):
            raise CandidateFail(f"{molecule}: max_nac01 inconsistent with recomputed window")
        ov_d = overlap(dlo, dhi, *PAPER_DIH)
        ov_r = overlap(rlo, rhi, *PAPER_R)
        if abs(number(row["overlap_with_paper_dihedral_deg"], "dihedral overlap") - ov_d) > policy("paper_dihedral_overlap_deg"):
            raise CandidateFail(f"{molecule}: paper dihedral overlap {row['overlap_with_paper_dihedral_deg']} != {ov_d:.2f}")
        if abs(number(row["overlap_with_paper_r_bohr"], "r overlap") - ov_r) > policy("paper_r_overlap_bohr"):
            raise CandidateFail(f"{molecule}: paper r overlap {row['overlap_with_paper_r_bohr']} != {ov_r:.2f}")
        if not valid_ci_notes(row["notes"]):
            raise CandidateFail(f"{molecule}: notes must be nonempty")
        if not row["criterion"].strip():
            raise CandidateFail(f"{molecule}: criterion must state the CI-region selection rule")
        conclusion = comparison["per_molecule"][molecule]
        expected_conclusion = {
            "candidate_window": {"r_cc_bohr": [rlo, rhi], "dihedral_deg": [dlo, dhi]},
            "paper_window": {"dihedral_deg": list(PAPER_DIH), "r_cc_bohr": list(PAPER_R)},
            "radial_overlap_bohr": ov_r,
            "radial_overlap_category": overlap_category(ov_r, rhi-rlo, PAPER_R[1]-PAPER_R[0]),
            "angular_overlap_deg": ov_d,
            "angular_overlap_category": overlap_category(ov_d, dhi-dlo, PAPER_DIH[1]-PAPER_DIH[0]),
            "selected_bound_touches_grid_boundary": {
                "r_cc_bohr": selected_result["touches_r_grid_boundary"],
                "dihedral_deg": selected_result["touches_dihedral_grid_boundary"],
            },
        }
        if not isinstance(conclusion, dict) or set(conclusion) != set(expected_conclusion):
            raise CandidateFail(f"{molecule}: paper comparison conclusion fields are invalid")
        for key, expected_value in expected_conclusion.items():
            got = conclusion[key]
            if isinstance(expected_value, dict):
                if set(got) != set(expected_value):
                    raise CandidateFail(f"{molecule}: conclusion {key} fields are invalid")
                for subkey, subvalue in expected_value.items():
                    if isinstance(subvalue, bool) or isinstance(subvalue, str):
                        if got[subkey] is not subvalue and got[subkey] != subvalue:
                            raise CandidateFail(f"{molecule}: conclusion {key}.{subkey} mismatch")
                    elif isinstance(subvalue, list):
                        actual_list = got[subkey]
                        if (not isinstance(actual_list, list) or len(actual_list) != len(subvalue) or
                                any(abs(number(a, key) - b) > policy("conclusion") for a, b in zip(actual_list, subvalue))):
                            raise CandidateFail(f"{molecule}: conclusion {key}.{subkey} mismatch")
                    elif abs(number(got[subkey], key) - subvalue) > policy("conclusion"):
                        raise CandidateFail(f"{molecule}: conclusion {key}.{subkey} mismatch")
            elif isinstance(expected_value, bool) or isinstance(expected_value, str):
                if got is not expected_value and got != expected_value:
                    raise CandidateFail(f"{molecule}: conclusion {key} mismatch")
            elif abs(number(got, key) - expected_value) > policy("conclusion"):
                raise CandidateFail(f"{molecule}: conclusion {key} mismatch")

    print("PASS: case-02 static analysis consistent with recomputed grid references")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CandidateFail as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except (ValueError, TypeError, LookupError, OverflowError, csv.Error) as exc:
        print(f"FAIL: malformed candidate output: {exc}", file=sys.stderr)
        raise SystemExit(1)
