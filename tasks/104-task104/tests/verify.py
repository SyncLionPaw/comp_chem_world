#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Evaluate site-resolved Li K-edge spectra and local environments.
"""Score reconstructed Li K-edge site curves and evidence-backed M assignment."""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
from pathlib import Path

# Fixed protocol and scoring thresholds; native reference data are recomputed below.
REFS = json.loads(Path(__file__).with_name("refs.json").read_text(encoding="utf-8"))
COMPOSITIONS = REFS["compositions"]
FWHM_EV = REFS["fwhm_eV"]
MAIN_PEAK_EV = REFS["main_peak_eV"]
GRID_N = REFS["grid_points"]
WINDOW = REFS["window_eV"]
SHAPE_TOL = REFS["shape_tolerance"]
DOS_ROUNDING_EPSILON = REFS["dos_rounding_epsilon"]
DOS_ROUNDING_DIGITS = REFS["dos_rounding_digits"]
DOS_MIN_ENERGY_EV = REFS["dos_min_energy_eV"]
DOS_MAX_INDEX = REFS["dos_max_index"]
MIN_DOS_POINTS = REFS["min_dos_points"]
MIN_SITES = REFS["min_sites_per_composition"]
MIN_SPECTRUM_POINTS = REFS["min_spectrum_points"]
PREPEAK_WINDOW = REFS["prepeak_window_eV"]
MIN_PREPEAK_POINTS = REFS["min_prepeak_points"]
COORDINATION_CUTOFF_A = REFS["coordination_cutoff_A"]
SINGULAR_LATTICE_TOL = REFS["singular_lattice_tolerance"]
DISTANCE_TOL_A = REFS["distance_tolerance_A"]
DISTORTION_TOL = REFS["distortion_tolerance"]
MIN_DISTORTION = REFS["min_distortion_index"]
MIN_LONGEST_BOND_A = REFS["min_longest_bond_A"]
MAX_NEAREST_LI_A = REFS["max_nearest_li_A"]


def assets_root() -> Path:
    override = os.environ.get("CASE_ASSETS")
    if override:
        return Path(override)
    mounted = Path("/app/assets")
    if mounted.is_dir():
        return mounted
    return Path(__file__).resolve().parents[1] / "environment" / "assets"


def site_dirs(comp: str) -> list[Path]:
    base = assets_root() / comp
    return sorted((p for p in base.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: int(p.name))


def be_p_dos(vasprun_gz: Path) -> tuple[float, list[float], list[float]]:
    efermi = None
    spins: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] | None = None
    ion = None
    with gzip.open(vasprun_gz, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if efermi is None and 'name="efermi"' in line:
                efermi = float(line.split(">", 1)[1].split("<", 1)[0])
            if "<partial>" in line:
                break
        if efermi is None:
            raise ValueError(f"missing efermi in {vasprun_gz}")
        for line in handle:
            if 'comment="ion ' in line:
                ion = line.split('comment="ion ', 1)[1].split('"', 1)[0]
                current = None
            elif 'comment="spin ' in line and ion == "1":
                current = []
            elif current is not None and "<r>" in line:
                vals = [float(x) for x in line.split(">", 1)[1].split("<", 1)[0].split()]
                current.append((vals[0], vals[2] + vals[3] + vals[4]))
            elif current is not None and "</set>" in line:
                spins.append(current)
                current = None
                if len(spins) == 2:
                    break
    if len(spins) != 2 or len(spins[0]) != len(spins[1]):
        raise ValueError(f"incomplete Be p DOS in {vasprun_gz}")
    energy = [row[0] - efermi for row in spins[0]]
    density = [a[1] + b[1] for a, b in zip(spins[0], spins[1])]
    return efermi, energy, density


def truncated(energy: list[float], density: list[float]) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for e, d in zip(energy, density):
        rounded = round(e + DOS_ROUNDING_EPSILON, DOS_ROUNDING_DIGITS)
        if rounded >= DOS_MIN_ENERGY_EV and len(xs) <= DOS_MAX_INDEX:
            xs.append(rounded)
            ys.append(d)
    if len(xs) < MIN_DOS_POINTS:
        raise ValueError("truncated DOS is too short")
    return xs, ys


def smear(xs: list[float], ys: list[float], fwhm: float = FWHM_EV, n: int = GRID_N) -> tuple[list[float], list[float]]:
    sigma = fwhm / (2.0 * math.sqrt(2.0 * math.log(2.0)))
    x0, x1 = xs[0], xs[-1]
    grid = [x0 + (x1 - x0) * i / (n - 1) for i in range(n)]
    out = [0.0] * n
    out[0] = ys[0]
    out[-1] = ys[-1]
    norm = sigma * math.sqrt(2.0 * math.pi)
    for i in range(1, len(xs) - 1):
        dx = 0.5 * (xs[i + 1] - xs[i - 1])
        center = xs[i]
        weight = ys[i] * dx / norm
        for j in range(1, n - 1):
            z = (grid[j] - center) / sigma
            out[j] += weight * math.exp(-0.5 * z * z)
    return grid, out


def composition_curves(comp: str) -> list[dict]:
    rows = []
    for site in site_dirs(comp):
        _ef, energy, density = be_p_dos(site / "vasprun.xml.gz")
        xs, ys = truncated(energy, density)
        grid, broad = smear(xs, ys)
        rows.append({"site": site.name, "energy_eV": grid, "intensity": broad})
    if len(rows) < MIN_SITES:
        raise ValueError(f"not enough sites for {comp}")
    total = [0.0] * len(rows[0]["intensity"])
    for row in rows:
        for i, value in enumerate(row["intensity"]):
            total[i] += value
    imax = max(range(len(total)), key=total.__getitem__)
    shift = MAIN_PEAK_EV - rows[0]["energy_eV"][imax]
    for row in rows:
        row["energy_eV"] = [e + shift for e in row["energy_eV"]]
        row["shift_eV"] = shift
    return rows


def interp(xs: list[float], ys: list[float], x: float) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    span = xs[hi] - xs[lo]
    if span == 0:
        return ys[lo]
    w = (x - xs[lo]) / span
    return ys[lo] * (1.0 - w) + ys[hi] * w


def window_max(xs: list[float], ys: list[float]) -> float:
    vals = [y for x, y in zip(xs, ys) if WINDOW[0] <= x <= WINDOW[1]]
    if not vals:
        raise ValueError("spectrum does not cover 56–67 eV")
    return max(vals)


def shape_delta(reference: dict, submitted: dict) -> float:
    ref_x = reference["energy_eV"]
    ref_y = reference["intensity"]
    sub_x = submitted["energy_eV"]
    sub_y = submitted["intensity"]
    ref_scale = window_max(ref_x, ref_y)
    sub_scale = window_max(sub_x, sub_y)
    if ref_scale <= 0 or sub_scale <= 0:
        return math.inf
    worst = 0.0
    for x, y in zip(ref_x, ref_y):
        if not (WINDOW[0] <= x <= WINDOW[1]):
            continue
        delta = abs(y / ref_scale - interp(sub_x, sub_y, x) / sub_scale)
        if delta > worst:
            worst = delta
    return worst


def match_composition(submitted, reference: list[dict]) -> tuple[bool, str]:
    # Accept either a list of spectrum objects or a site-ID-keyed mapping.
    if isinstance(submitted, dict) and submitted:
        normalized = []
        for site, payload in submitted.items():
            if isinstance(payload, dict):
                item = dict(payload)
                item.setdefault("site", str(site))
            else:
                return False, "spectra mapping values must be objects"
            normalized.append(item)
        submitted = normalized
    if not isinstance(submitted, list) or not submitted:
        return False, "spectra entry must be a non-empty list"
    by_site = {}
    for item in submitted:
        if not isinstance(item, dict):
            return False, "each spectrum must be an object"
        site = str(item.get("site") or "").strip()
        xs = item.get("energy_eV")
        ys = item.get("intensity")
        if not site or not isinstance(xs, list) or not isinstance(ys, list) or len(xs) != len(ys) or len(xs) < MIN_SPECTRUM_POINTS:
            return False, f"site {site or '?'} needs paired energy_eV and intensity arrays"
        try:
            pair = {"energy_eV": [float(x) for x in xs], "intensity": [float(y) for y in ys]}
        except (TypeError, ValueError):
            return False, f"non-numeric spectrum at site {site}"
        if any(not math.isfinite(v) for v in pair["energy_eV"] + pair["intensity"]):
            return False, f"non-finite spectrum at site {site}"
        if site in by_site:
            return False, f"duplicate site {site}"
        by_site[site] = pair
    missing = [row["site"] for row in reference if row["site"] not in by_site]
    extra = [site for site in by_site if site not in {row["site"] for row in reference}]
    if missing or extra:
        return False, f"site set mismatch missing={missing[:8]} extra={extra[:8]}"
    for row in reference:
        xs = by_site[row["site"]]["energy_eV"]
        if not any(WINDOW[0] <= x <= WINDOW[1] for x in xs):
            return False, f"site {row['site']} spectrum does not cover 56–67 eV"
    worst = 0.0
    worst_site = reference[0]["site"]
    for row in reference:
        try:
            delta = shape_delta(row, by_site[row["site"]])
        except ValueError as exc:
            return False, f"site {row['site']} {exc}"
        if delta > worst:
            worst = delta
            worst_site = row["site"]
        if delta > SHAPE_TOL:
            return False, f"site {row['site']} shape delta {delta:.4f} exceeds {SHAPE_TOL}"
    return True, f"all {len(reference)} sites within {SHAPE_TOL}; worst {worst_site} {worst:.4f}"

def _poscar(path: Path) -> tuple[list[list[float]], list[str], list[list[float]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    scale = float(lines[1].split()[0])
    lattice = [[float(x) * scale for x in lines[i].split()[:3]] for i in (2, 3, 4)]
    symbols = lines[5].split()
    counts = [int(x) for x in lines[6].split()]
    if len(symbols) != len(counts):
        raise ValueError(f"invalid POSCAR species/count rows: {path}")
    cursor = 7
    if lines[cursor].strip().lower().startswith("s"):
        cursor += 1
    mode = lines[cursor].strip().lower()
    direct = mode.startswith("d")
    cursor += 1
    coordinates: list[list[float]] = []
    elements: list[str] = []
    for symbol, count in zip(symbols, counts):
        for row in lines[cursor:cursor + count]:
            xyz = [float(x) for x in row.split()[:3]]
            if len(xyz) != 3:
                raise ValueError(f"invalid POSCAR coordinate row: {path}")
            if not direct:
                # Cartesian coordinates are also scaled by the POSCAR scale.
                xyz = [x * scale for x in xyz]
                xyz = [sum(xyz[k] * _inverse(lattice)[k][j] for k in range(3)) for j in range(3)]
            coordinates.append(xyz)
            elements.append(symbol)
        cursor += count
    return lattice, elements, coordinates


def _inverse(a: list[list[float]]) -> list[list[float]]:
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
           - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    if abs(det) < SINGULAR_LATTICE_TOL:
        raise ValueError("singular POSCAR lattice")
    cof = [
        [a[1][1]*a[2][2]-a[1][2]*a[2][1], a[0][2]*a[2][1]-a[0][1]*a[2][2], a[0][1]*a[1][2]-a[0][2]*a[1][1]],
        [a[1][2]*a[2][0]-a[1][0]*a[2][2], a[0][0]*a[2][2]-a[0][2]*a[2][0], a[0][2]*a[1][0]-a[0][0]*a[1][2]],
        [a[1][0]*a[2][1]-a[1][1]*a[2][0], a[0][1]*a[2][0]-a[0][0]*a[2][1], a[0][0]*a[1][1]-a[0][1]*a[1][0]],
    ]
    return [[cof[i][j] / det for j in range(3)] for i in range(3)]


def _distance(a: list[float], b: list[float], lattice: list[list[float]]) -> float:
    delta = [b[i] - a[i] for i in range(3)]
    center = [round(v) for v in delta]
    best = math.inf
    for i in range(center[0] - 1, center[0] + 2):
        for j in range(center[1] - 1, center[1] + 2):
            for k in range(center[2] - 1, center[2] + 2):
                frac = [delta[0] - i, delta[1] - j, delta[2] - k]
                cart = [sum(frac[n] * lattice[n][m] for n in range(3)) for m in range(3)]
                best = min(best, math.sqrt(sum(x*x for x in cart)))
    return best


def site_geometry(comp: str, site: str) -> dict:
    path = assets_root() / comp / str(site) / "POSCAR"
    lattice, elements, coords = _poscar(path)
    be = next(i for i, element in enumerate(elements) if element == "Be")
    distances = sorted(_distance(coords[be], coords[i], lattice) for i, element in enumerate(elements) if element == "O")
    li_distances = sorted(_distance(coords[be], coords[i], lattice) for i, element in enumerate(elements) if element == "Li")
    coordination = sum(value < COORDINATION_CUTOFF_A for value in distances)
    six = distances[:6] if len(distances) >= 6 and coordination >= 6 else None
    if six:
        mean = sum(six) / 6
        distortion = sum(abs(value - mean) for value in six) / (6 * mean)
    else:
        distortion = None
    return {
        "coordination": coordination,
        "nearest_li_A": li_distances[0] if li_distances else None,
        "six_li_o_A": six,
        "distortion_index": distortion,
    }

class DepositedInputError(Exception):
    """The scorer cannot read a deposited vasprun or POSCAR."""


class NonFiniteJSON(Exception):
    """results.json contains NaN or Infinity."""


def _parse_json(text: str):
    def reject(token: str):
        raise NonFiniteJSON(token)

    return json.loads(text, parse_constant=reject)


def _has_local_maximum(curve, low: float = PREPEAK_WINDOW[0], high: float = PREPEAK_WINDOW[1]) -> bool:
    if not isinstance(curve, dict):
        return False
    xs, ys = curve.get("energy_eV"), curve.get("intensity")
    if not isinstance(xs, list) or not isinstance(ys, list) or len(xs) != len(ys) or len(xs) < MIN_PREPEAK_POINTS:
        return False
    try:
        energy = [float(value) for value in xs]
        intensity = [float(value) for value in ys]
    except (TypeError, ValueError):
        return False
    if any(not math.isfinite(value) for value in energy + intensity):
        return False
    return any(
        low <= energy[i] <= high and intensity[i] >= intensity[i - 1] and intensity[i] >= intensity[i + 1]
        for i in range(1, len(energy) - 1)
    )


def deposited_inputs() -> None:
    """Every scored composition must have a readable POSCAR and vasprun."""
    root = assets_root()
    if not root.is_dir():
        raise DepositedInputError(f"evaluation asset root is not a directory: {root}")
    for comp in COMPOSITIONS:
        try:
            sites = site_dirs(comp)
        except OSError as exc:
            raise DepositedInputError(f"cannot list deposited sites for {comp}: {exc}") from exc
        if len(sites) < MIN_SITES:
            raise DepositedInputError(f"deposited site set for {comp} is incomplete")
        for site in sites:
            poscar = site / "POSCAR"
            vasprun = site / "vasprun.xml.gz"
            if not poscar.is_file() or not vasprun.is_file():
                missing = poscar if not poscar.is_file() else vasprun
                raise DepositedInputError(f"missing deposited evaluation input: {missing}")
            try:
                site_geometry(comp, site.name)
            except (OSError, StopIteration, ValueError) as exc:
                raise DepositedInputError(f"unreadable deposited POSCAR {poscar}: {exc}") from exc


def assignment_problems(assignment, *, check_geometry: bool = True) -> list[str]:
    """Check assignment fields and independently validate native geometry evidence."""
    if not isinstance(assignment, dict):
        return ["assignment must be an object"]
    problems = []
    sites = assignment.get("sites_with_extra_prepeak")
    if not isinstance(sites, dict):
        problems.append("sites_with_extra_prepeak must be an object")
    else:
        for comp in COMPOSITIONS:
            rows = sites.get(comp)
            if not isinstance(rows, list):
                problems.append(f"sites_with_extra_prepeak.{comp} must be a list")
                continue
            if any(not _site_id(item) for item in rows):
                problems.append(f"sites_with_extra_prepeak.{comp} entries must be site ids")
    present = assignment.get("present_in_endmembers")
    if not isinstance(present, bool):
        problems.append("present_in_endmembers must be a boolean")
    description = assignment.get("site_description")
    if not isinstance(description, str) or not description.strip():
        problems.append("site_description must be a non-empty string")
    evidence = assignment.get("site_geometry_evidence")
    if not isinstance(evidence, list) or not evidence:
        problems.append("site_geometry_evidence must contain structural comparison records")
        return problems
    seen = set()
    by_site = {}
    for row in evidence:
        if not isinstance(row, dict):
            problems.append("site_geometry_evidence entries must be objects")
            continue
        comp, site = row.get("composition"), str(row.get("site", "")).strip()
        if comp not in COMPOSITIONS or not site:
            problems.append("site_geometry_evidence needs a valid composition and site")
            continue
        key = (comp, site)
        if key in seen:
            problems.append(f"duplicate site_geometry_evidence for {comp}/{site}")
            continue
        seen.add(key)
        by_site[key] = row
        if not check_geometry:
            continue
        try:
            expected = site_geometry(comp, site)
        except (OSError, StopIteration, ValueError) as exc:
            problems.append(f"cannot derive POSCAR geometry for {comp}/{site}: {exc}")
            continue
        if row.get("coordination") != expected["coordination"]:
            problems.append(f"{comp}/{site} coordination does not match its POSCAR")
        nearest_li = row.get("nearest_li_A")
        expected_nearest_li = expected["nearest_li_A"]
        if expected_nearest_li is None:
            if nearest_li is not None:
                problems.append(f"{comp}/{site} nearest Li distance must be null")
        elif (not isinstance(nearest_li, (int, float)) or isinstance(nearest_li, bool)
              or not math.isfinite(float(nearest_li)) or abs(float(nearest_li) - expected_nearest_li) > DISTANCE_TOL_A):
            problems.append(f"{comp}/{site} nearest Li distance does not match its POSCAR within {DISTANCE_TOL_A} A")
        values = row.get("six_li_o_A")
        expected_values = expected["six_li_o_A"]
        if expected_values is None:
            if values is not None or row.get("distortion_index") is not None:
                problems.append(f"{comp}/{site} is not six-coordinate; six-bond geometry must be null")
        elif (not isinstance(values, list) or len(values) != 6
              or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v))
                     or abs(float(v) - target) > DISTANCE_TOL_A for v, target in zip(values, expected_values))):
            problems.append(f"{comp}/{site} six Li-O distances do not match its POSCAR within {DISTANCE_TOL_A} A")
        else:
            d = row.get("distortion_index")
            expected_d = expected["distortion_index"]
            if not isinstance(d, (int, float)) or isinstance(d, bool) or not math.isfinite(float(d)) or abs(float(d) - expected_d) > DISTORTION_TOL:
                problems.append(f"{comp}/{site} distortion_index does not match its POSCAR within {DISTORTION_TOL}")
    if isinstance(sites, dict):
        for comp in COMPOSITIONS:
            rows = sites.get(comp)
            if isinstance(rows, list):
                missing = [str(site) for site in rows if (comp, str(site)) not in by_site]
                if missing:
                    problems.append(f"site_geometry_evidence missing claimed M sites {comp}/{missing}")
    for comp in COMPOSITIONS:
        controls = [row for (c, _), row in by_site.items() if c == comp]
        if not controls or not any(row.get("coordination") == 6 for row in controls):
            problems.append(f"site_geometry_evidence needs a six-coordinate control for {comp}")
    return problems


def assignment_l3(assignment, spectra, references) -> tuple[bool, str]:
    if not isinstance(assignment, dict) or not isinstance(spectra, dict):
        return False, "assignment or spectra missing"
    description = str(assignment.get("site_description", "")).casefold()
    class_ok = "16c" in description and (
        ("face" in description and ("sharing" in description or "share" in description))
        or "面共享" in description or "面共用" in description
    ) and (
        "distort" in description or "畸变" in description or "扭曲" in description
    )
    endmember_ok = assignment.get("present_in_endmembers") is False
    claimed_sites = assignment.get("sites_with_extra_prepeak", {})
    endpoint_sites_ok = isinstance(claimed_sites, dict) and all(
        claimed_sites.get(comp) == [] for comp in ("Li4", "Li7")
    )
    evidence = assignment.get("site_geometry_evidence", [])
    intermediate_support = {"Li5": False, "Li6": False}
    candidate_lists_consistent = True
    endmember_controls = {"Li4": False, "Li7": False}
    evidence_rows = evidence if isinstance(evidence, list) else []
    evidence_by_site = {
        (row.get("composition"), str(row.get("site", ""))): row
        for row in evidence_rows if isinstance(row, dict)
    }
    for comp in ("Li5", "Li6"):
        candidates = claimed_sites.get(comp, []) if isinstance(claimed_sites, dict) else None
        if not isinstance(candidates, list):
            candidate_lists_consistent = False
            continue
        for candidate in candidates:
            site = str(candidate)
            row = evidence_by_site.get((comp, site))
            ref_curve = {str(item.get("site")): item for item in references.get(comp, [])}.get(site)
            submitted = spectra.get(comp)
            by_site = {str(item.get("site")): item for item in submitted if isinstance(item, dict)} if isinstance(submitted, list) else {}
            ref_has_m = _has_local_maximum(ref_curve)
            submitted_has_m = _has_local_maximum(by_site.get(site))
            bond_values = row.get("six_li_o_A") if isinstance(row, dict) else None
            bonds_valid = (isinstance(bond_values, list) and len(bond_values) == 6
                           and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                                   and math.isfinite(float(value)) for value in bond_values))
            candidate_ok = bool(
                row and row.get("coordination") == 6
                and isinstance(row.get("distortion_index"), (int, float))
                and row["distortion_index"] >= MIN_DISTORTION
                and bonds_valid
                and max(bond_values) >= MIN_LONGEST_BOND_A
                and isinstance(row.get("nearest_li_A"), (int, float))
                and row["nearest_li_A"] <= MAX_NEAREST_LI_A
                and ref_has_m
                and submitted_has_m
            )
            candidate_lists_consistent = candidate_lists_consistent and candidate_ok
    for row in evidence if isinstance(evidence, list) else []:
        if not isinstance(row, dict):
            continue
        comp = row.get("composition")
        site = str(row.get("site", ""))
        values = row.get("six_li_o_A")
        d = row.get("distortion_index")
        if row.get("coordination") != 6 or not isinstance(d, (int, float)) or not isinstance(values, list):
            continue
        nearest_li = row.get("nearest_li_A")
        try:
            longest_bond = max(float(value) for value in values)
        except (TypeError, ValueError):
            continue
        if comp in ("Li5", "Li6") and d >= MIN_DISTORTION and longest_bond >= MIN_LONGEST_BOND_A and isinstance(nearest_li, (int, float)) and not isinstance(nearest_li, bool) and nearest_li <= MAX_NEAREST_LI_A:
            claimed = assignment.get("sites_with_extra_prepeak", {})
            claimed_sites = claimed.get(comp, []) if isinstance(claimed, dict) else []
            if not isinstance(claimed_sites, list) or site not in {str(value) for value in claimed_sites}:
                continue
            submitted = spectra.get(comp)
            by_site = {str(item.get("site")): item for item in submitted if isinstance(item, dict)} if isinstance(submitted, list) else {}
            actual = by_site.get(site)
            ref_by_site = {str(item.get("site")): item for item in references.get(comp, [])}
            ref_curve = ref_by_site.get(site)
            intermediate_support[comp] = intermediate_support[comp] or (
                _has_local_maximum(ref_curve) and _has_local_maximum(actual)
            )
        elif comp in endmember_controls and row.get("coordination") == 6 and d < MIN_DISTORTION and isinstance(nearest_li, (int, float)) and nearest_li > MAX_NEAREST_LI_A:
            ref_by_site = {str(item.get("site")): item for item in references.get(comp, [])}
            ref_curve = ref_by_site.get(site)
            submitted = spectra.get(comp)
            by_site = {str(item.get("site")): item for item in submitted if isinstance(item, dict)} if isinstance(submitted, list) else {}
            actual = by_site.get(site)
            no_m_peak = (
                ref_curve is not None and actual is not None
                and not _has_local_maximum(ref_curve)
                and not _has_local_maximum(actual)
            )
            endmember_controls[comp] = endmember_controls[comp] or no_m_peak
    passed = class_ok and endmember_ok and endpoint_sites_ok and candidate_lists_consistent and all(intermediate_support.values()) and all(endmember_controls.values())
    detail = {
        "assigned_class_is_distorted_face_sharing_Li16c": class_ok,
        "endmember_call_is_absent": endmember_ok,
        "no_M_sites_claimed_in_endmembers": endpoint_sites_ok,
        "Li5_and_Li6_spectrum_and_geometry_support": intermediate_support,
        "every_listed_M_candidate_supported": candidate_lists_consistent,
        "Li4_and_Li7_low_distortion_controls": endmember_controls,
    }
    return passed, json.dumps(detail, ensure_ascii=False)


def _site_id(item) -> bool:
    if isinstance(item, bool):
        return False
    if isinstance(item, int):
        return True
    return isinstance(item, str) and bool(item.strip())


def find_one(base: Path, name: str) -> Path | None:
    for cand in (base / "final" / name, base / name):
        if cand.is_file():
            return cand
    hits = list(base.rglob(name))
    return hits[0] if hits else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", nargs="?", default="/app/final")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    checks = []

    def add(name: str, level: str, passed: bool, detail: str) -> None:
        checks.append({"criterion": name, "level": level, "pass": bool(passed), "detail": detail})

    base = Path(args.output_dir)
    results_path = find_one(base, "results.json")
    methods_path = find_one(base, "methods.md")
    data = None
    spectra = None
    env_error = False
    shape_problem = None
    if results_path is None:
        shape_problem = "results.json not found"
    else:
        try:
            data = _parse_json(results_path.read_text(encoding="utf-8"))
        except NonFiniteJSON as exc:
            shape_problem = f"results.json contains a non-finite number ({exc})"
        except json.JSONDecodeError as exc:
            shape_problem = f"results.json unparsable: {exc}"
        except OSError as exc:
            shape_problem = f"results.json unreadable: {exc}"
        else:
            if not isinstance(data, dict):
                shape_problem = "results.json must be a JSON object"
                data = None
    input_error = None
    try:
        deposited_inputs()
    except DepositedInputError as exc:
        input_error = str(exc)
        env_error = True
    assignment = None
    if shape_problem:
        add("deliverables_complete", "L1", False, shape_problem)
    elif data is not None:
        spectra = data.get("spectra") if isinstance(data, dict) else None
        assignment = data.get("assignment") if isinstance(data, dict) else None
        try:
            problems = assignment_problems(assignment, check_geometry=input_error is None)
        except DepositedInputError as exc:
            input_error = str(exc)
            env_error = True
            problems = [f"deposited evaluation input unreadable: {exc}"]
        spectra_ok = isinstance(spectra, dict) and all(key in spectra for key in COMPOSITIONS)
        methods_ok = methods_path is not None and methods_path.stat().st_size > 0
        ok = spectra_ok and methods_ok and not problems
        detail = "spectra, assignment fields and methods.md"
        if not ok:
            detail = (
                f"spectra_keys={spectra_ok}; methods.md={methods_ok}; "
                f"assignment={problems or 'ok'}"
            )
        add("deliverables_complete", "L1", ok, detail)

    spectrum_ok = True
    details = {}
    references = {}
    if input_error:
        env_error = True
        spectrum_ok = False
        details = {"error": f"could not read deposited evaluation inputs: {input_error}"}
    else:
        try:
            for comp in COMPOSITIONS:
                reference = composition_curves(comp)
                references[comp] = reference
                block = spectra.get(comp) if isinstance(spectra, dict) else None
                passed, detail = match_composition(block, reference)
                details[comp] = {"pass": passed, "detail": detail}
                spectrum_ok = spectrum_ok and passed
        except (OSError, ValueError) as exc:
            env_error = True
            spectrum_ok = False
            references = {}
            details = {"error": f"could not read deposited vasprun inputs: {exc}"}
    add("site_spectra", "L2", spectrum_ok, json.dumps(details, ensure_ascii=False))

    l3_ok, l3_detail = assignment_l3(assignment if data is not None else None, spectra, references)
    add("prepeak_m_site", "L3", l3_ok and spectrum_ok, l3_detail)

    automatic_ok = all(row["pass"] for row in checks) and not env_error
    if env_error:
        overall = "ERROR"
        rc = 2
    elif not automatic_ok:
        overall = "FAIL"
        rc = 1
    else:
        overall = "PASS"
        rc = 0
    payload = {
        "case_id": "case-02",
        "status": overall,
        "overall": overall,
        "coverage": "complete",
        "checks": checks,
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for row in checks:
            print(f"{row['level']} {row['criterion']}: {'PASS' if row['pass'] else 'FAIL'} {row['detail']}")
        print(overall)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
