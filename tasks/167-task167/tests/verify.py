#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Construct and validate monolayer W₂N₃.
"""Scientific verifier for case-01-structure-characterization.

Usage: verify.py [FINAL_DIR]     (default /app/final)

Emits a strict JSON verdict on stdout and exits 0 (PASS / reward 1),
1 (FAIL / reward 0) or 2 (environment error, no reward).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

REQUIRED_FILES = ("W2N3-monolayer.poscar", "structure-report.json")

def _validate_criteria(cfg: object) -> None:
    def number(value, *, positive=False, nonnegative=False):
        return (type(value) in (int, float) and math.isfinite(float(value))
                and (not positive or value > 0) and (not nonnegative or value >= 0))
    def integer(value, *, positive=False, nonnegative=False):
        return (type(value) is int and (not positive or value > 0)
                and (not nonnegative or value >= 0))
    def pair(value, *, positive=False):
        return (isinstance(value, list) and len(value) == 2
                and all(number(x, positive=positive) for x in value) and value[0] <= value[1])
    if not isinstance(cfg, dict): raise ValueError("criteria must be an object")
    if set(cfg["atom_counts"]) != {"W", "N"} or not all(integer(cfg["atom_counts"][k], positive=True) for k in ("W", "N")):
        raise ValueError("criteria.atom_counts must contain positive integer W and N counts")
    h = cfg["hexagonal"]
    if not isinstance(h, dict) or not all(number(h[k], positive=True) for k in ("relative_a1_a2_max", "gamma_cos_tolerance", "verticality_cos_max")) or not number(h["gamma_cos_target"]):
        raise ValueError("criteria.hexagonal has invalid values")
    if not pair(cfg["lattice_a_A"], positive=True) or not number(cfg["vacuum_min_A"], positive=True) or not pair(cfg["thickness_A"], positive=True) or not number(cfg["minimum_pair_distance_A"], positive=True):
        raise ValueError("criteria geometry windows must be finite positive ordered values")
    c = cfg["coordination"]
    if not isinstance(c, dict) or not pair(c["W_count"], positive=False) or not all(integer(x, nonnegative=True) for x in c["W_count"]):
        raise ValueError("criteria.coordination.W_count must be two nonnegative integers")
    if not all(number(c[k], positive=True) for k in ("W_cutoff_A", "outer_N_cutoff_A", "center_N_cutoff_A")):
        raise ValueError("criteria coordination cutoffs must be finite and positive")
    if not all(integer(c[k], nonnegative=True) for k in ("outer_N_count", "outer_N_atoms", "center_N_count_min")):
        raise ValueError("criteria coordination counts must be nonnegative integers")
    s = cfg["symmetry"]
    if not isinstance(s, dict) or not number(s["symprec_A"], positive=True) or not integer(s["space_group_number"], positive=True):
        raise ValueError("criteria.symmetry is invalid")
    rt = cfg["report_tolerance"]
    if not isinstance(rt, dict) or not all(number(rt[k], nonnegative=True) for k in ("a_A", "vacuum_A", "thickness_A")):
        raise ValueError("criteria.report_tolerance is invalid")
    claims = cfg["paper_coordination_claims"]
    if not isinstance(claims, dict) or set(claims) != {"W", "N_outer", "N_center"} or not all(integer(v, nonnegative=True) for v in claims.values()):
        raise ValueError("criteria.paper_coordination_claims must contain three nonnegative integers")


def fail_env(message: str) -> int:
    print(json.dumps({"overall": "ENV_INVALID", "infra_error": message}, ensure_ascii=False))
    return 2


def fail_science(message: str) -> int:
    print(json.dumps({"overall":"FAIL","reward":0.0,"checks":[],"failed":[message]},ensure_ascii=False))
    return 1


def main(argv: list[str]) -> int:
    final = Path(argv[1]).resolve() if len(argv) > 1 else Path("/app/final").resolve()
    tests = Path(__file__).resolve().parent
    refs_path = tests / "refs.json"
    asset = Path(os.environ.get("APP", "/app")) / "assets" / "structure-brief.md"
    if not refs_path.is_file() or not asset.is_file():
        return fail_env("verifier refs or public structure brief missing")
    try:
        refs = json.loads(refs_path.read_text(encoding="utf-8"))
        cfg = refs["criteria"]
        _validate_criteria(cfg)
        expected = refs["asset_hashes"]["assets/structure-brief.md"].removeprefix("sha256:")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, AttributeError, ValueError) as exc:
        return fail_env(f"invalid verifier reference file: {exc}")
    if hashlib.sha256(asset.read_bytes()).hexdigest() != expected:
        return fail_env("public structure brief failed SHA-256 integrity check")
    missing = [name for name in REQUIRED_FILES if not (final / name).is_file()]
    if missing:
        return fail_science(f"missing deliverables: {missing}")
    try:
        report = json.loads((final / "structure-report.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return fail_science(f"structure-report.json is not valid JSON: {exc}")
    if not isinstance(report, dict):
        return fail_science("structure-report.json must contain an object")

    try:
        import spglib  # noqa: F401
    except ImportError:
        return fail_env("verifier dependency missing: spglib (declared in requirements.software)")

    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str, *, level: str = "L2", necessary: bool = True):
        checks.append({"criterion": name, "level": level, "necessary": necessary,
                       "passed": bool(ok), "detail": detail})

    # ---- L1: schema ---------------------------------------------------------
    req_fields = ["stoichiometry", "n_atoms", "space_group_number", "space_group_symbol",
                  "inplane_lattice_a_A", "vacuum_A", "layer_thickness_A", "coordination",
                  "paper_coordination_claims", "discrepancy_note"]
    missing_fields = [k for k in req_fields if k not in report]
    numeric = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))
    schema_errors = [f"missing fields: {', '.join(missing_fields)}"] if missing_fields else []
    expected_types = {
        "stoichiometry": str, "n_atoms": int, "space_group_number": int,
        "space_group_symbol": str, "coordination": dict,
        "paper_coordination_claims": dict, "discrepancy_note": str,
    }
    for key, typ in expected_types.items():
        value = report.get(key)
        if key in {"n_atoms", "space_group_number"}:
            valid = isinstance(value, typ) and not isinstance(value, bool)
        else:
            valid = isinstance(value, typ)
        if not valid:
            schema_errors.append(f"{key} must be {typ.__name__}")
    for key in ("inplane_lattice_a_A", "vacuum_A", "layer_thickness_A"):
        if not numeric(report.get(key)):
            schema_errors.append(f"{key} must be a finite number")
    coord_report = report.get("coordination")
    if isinstance(coord_report, dict):
        for key in ("cutoff_A",):
            if not numeric(coord_report.get(key)):
                schema_errors.append(f"coordination.{key} must be a finite number")
        counts = coord_report.get("W_counts")
        if (not isinstance(counts, list) or
                any(not isinstance(v, int) or isinstance(v, bool) for v in counts)):
            schema_errors.append("coordination.W_counts must be a list of integers")
        for key in ("N_three_coordination_count", "N_center_count"):
            value = coord_report.get(key)
            if not isinstance(value, int) or isinstance(value, bool):
                schema_errors.append(f"coordination.{key} must be an integer")
    check("report_schema", not schema_errors,
          "; ".join(schema_errors) if schema_errors else "required fields have contracted types",
          level="L1")
    if schema_errors:
        print(json.dumps({"overall": "FAIL", "reward": 0.0, "checks": checks,
                          "failed": ["report_schema"]}, ensure_ascii=False))
        return 1

    # ---- parse POSCAR -------------------------------------------------------
    try:
        lattice, species, frac = parse_poscar(final / "W2N3-monolayer.poscar")
    except Exception as exc:  # noqa: BLE001
        return fail_science(f"cannot parse submitted POSCAR: {exc}")

    n_w = species.count("W")
    n_n = species.count("N")
    check("stoichiometry_5atoms_W2N3", len(species) == sum(cfg["atom_counts"].values()) and n_w == cfg["atom_counts"]["W"] and n_n == cfg["atom_counts"]["N"],
          f"species counts W={n_w} N={n_n} total={len(species)}", level="L1")

    # ---- L2: geometry -------------------------------------------------------
    a1, a2, a3 = lattice
    na1, na2, na3 = (np.linalg.norm(v) for v in (a1, a2, a3))
    cos12 = float(np.dot(a1, a2) / (na1 * na2))
    cos_v1 = abs(float(np.dot(a1, a3) / (na1 * na3)))
    cos_v2 = abs(float(np.dot(a2, a3) / (na2 * na3)))
    hex_cfg = cfg["hexagonal"]
    hex_ok = (abs(na1 - na2) / na1 < hex_cfg["relative_a1_a2_max"] and abs(cos12 - hex_cfg["gamma_cos_target"]) < hex_cfg["gamma_cos_tolerance"]
              and cos_v1 < hex_cfg["verticality_cos_max"] and cos_v2 < hex_cfg["verticality_cos_max"])
    a_inplane = 0.5 * (na1 + na2)
    check("hexagonal_metric", hex_ok,
          f"|a1|={na1:.4f} |a2|={na2:.4f} gamma_cos={cos12:.4f} verticality=({cos_v1:.3f},{cos_v2:.3f})")
    check("inplane_a_window", cfg["lattice_a_A"][0] <= a_inplane <= cfg["lattice_a_A"][1],
          f"a={a_inplane:.4f} A (paper: 2.890 exp / 2.898 SOC / 2.912 PBE)")

    cart = frac @ lattice
    z = cart[:, 2]
    thickness = float(z.max() - z.min())
    vacuum = float(na3 - thickness)
    check("vacuum_ge_15A", vacuum >= cfg["vacuum_min_A"], f"vacuum={vacuum:.2f} A (paper uses 40 A)")
    check("layer_thickness", cfg["thickness_A"][0] <= thickness <= cfg["thickness_A"][1], f"thickness={thickness:.2f} A")

    dmin = min_pair_distance(cart, lattice)
    check("sane_bonds", dmin >= cfg["minimum_pair_distance_A"], f"min interatomic distance={dmin:.3f} A")

    coord = coordination_table(species, cart, lattice, cfg["coordination"])
    w_counts = sorted(coord["W"])
    w_ok = all(cfg["coordination"]["W_count"][0] <= c <= cfg["coordination"]["W_count"][1] for c in w_counts)
    check("W_six_coordinated", w_ok, f"W N-coordination counts (<=2.45 A): {w_counts}")
    n_wide = coord["N_wide"]
    center_i = int(np.argmax(n_wide))
    n_center = int(n_wide[center_i])
    outer_i = [i for i in range(len(n_wide)) if i != center_i]
    n_three = sum(1 for i in outer_i if coord["N_short"][i] == cfg["coordination"]["outer_N_count"])
    check("two_outer_N_three_coordinated", n_three == cfg["coordination"]["outer_N_atoms"],
          f"outer N with exactly 3 W neighbors (<=2.15 A): {n_three} of 2 "
          f"(N_short={[coord['N_short'][i] for i in outer_i]})")
    check("center_N_multicoordinated", n_center >= cfg["coordination"]["center_N_count_min"],
          f"center N W-coordination (<=2.5 A): {n_center}")

    # symmetry via spglib
    sg_number = None
    try:
        cell = (lattice, frac, [74 if s == "W" else 7 for s in species])
        ds = spglib.get_symmetry_dataset(cell, symprec=cfg["symmetry"]["symprec_A"])
        sg_number = int(ds.number)
        sg_symbol = str(ds.international)
    except Exception as exc:  # noqa: BLE001
        return fail_env(f"spglib failed on submitted structure: {exc}")
    check("spacegroup_187", sg_number == cfg["symmetry"]["space_group_number"],
          f"spglib: #{sg_number} {sg_symbol} (symprec 1e-3)")

    sites = report.get("computed_wyckoff_sites")
    expected_sites = [
        {"atom_index": i, "species": symbol, "wyckoff_letter": str(ds.wyckoffs[i]),
         "site_symmetry": str(ds.site_symmetry_symbols[i])}
        for i, symbol in enumerate(species)
    ]

    def required_site_fields(site: dict) -> dict | None:
        if not isinstance(site, dict) or type(site.get("atom_index")) is not int:
            return None
        letter = site.get("wyckoff_letter")
        if letter is None and isinstance(site.get("wyckoff_label"), str):
            # Accept full labels like "2h" only when reduced to the letter field.
            label = site["wyckoff_label"].strip()
            letter = label[-1] if label and label[-1].isalpha() else label
        if not isinstance(letter, str):
            return None
        # Letter field must be the Wyckoff letter alone (not multiplicity+letter).
        letter = letter.strip()
        if len(letter) != 1 or not letter.isalpha():
            return None
        return {
            "atom_index": site["atom_index"],
            "species": site.get("species"),
            "wyckoff_letter": letter,
            "site_symmetry": site.get("site_symmetry"),
        }

    projected = None
    if isinstance(sites, list):
        projected = [required_site_fields(site) for site in sites]
    sites_valid = (
        isinstance(projected, list)
        and len(projected) == len(expected_sites)
        and all(site is not None for site in projected)
        and sorted(projected, key=lambda site: site["atom_index"]) == expected_sites
    )
    check("reported_wyckoff_sites", sites_valid,
          "compare species, Wyckoff letters and site symmetry against the submitted cell")

    # report consistency
    rep = report.get("coordination", {}) if isinstance(report.get("coordination"), dict) else {}
    check("report_sg_matches", report.get("space_group_number") == cfg["symmetry"]["space_group_number"] and sg_number == cfg["symmetry"]["space_group_number"],
          f"reported={report.get('space_group_number')}, recomputed={sg_number}", level="L1")
    check("report_sg_symbol_matches", report.get("space_group_symbol") == sg_symbol,
          f"reported={report.get('space_group_symbol')}, recomputed={sg_symbol}", level="L1")
    a_rep = report.get("inplane_lattice_a_A")
    check("report_a_matches", isinstance(a_rep, (int, float)) and abs(a_rep - a_inplane) <= cfg["report_tolerance"]["a_A"],
          f"reported={a_rep}, recomputed={a_inplane:.4f}")
    vac_rep = report.get("vacuum_A")
    check("report_vacuum_matches", isinstance(vac_rep, (int, float)) and abs(vac_rep - vacuum) <= cfg["report_tolerance"]["vacuum_A"],
          f"reported={vac_rep}, recomputed={vacuum:.2f}")
    th_rep = report.get("layer_thickness_A")
    check("report_thickness_matches", isinstance(th_rep, (int, float)) and abs(th_rep - thickness) <= cfg["report_tolerance"]["thickness_A"],
          f"reported={th_rep}, recomputed={thickness:.2f}")
    w_rep = rep.get("W_counts")
    check("report_W_counts_truthful", sorted(w_rep or []) == w_counts,
          f"reported={w_rep}, recomputed={w_counts}")
    nc_rep = rep.get("N_center_count")
    check("report_N_center_truthful", nc_rep == n_center,
          f"reported={nc_rep}, recomputed={n_center}")
    n3_rep = rep.get("N_three_coordination_count")
    check("report_N_three_count_truthful", n3_rep == n_three,
          f"reported={n3_rep}, recomputed={n_three}")
    paper_claims = report.get("paper_coordination_claims")
    expected_paper_claims = cfg["paper_coordination_claims"]
    check("paper_coordination_claims_match_source", paper_claims == expected_paper_claims,
          f"reported={paper_claims}, paper Section B claims={expected_paper_claims}", level="L3")
    check("report_stoichiometry", report.get("stoichiometry") == "W2N3"
          and report.get("n_atoms") == sum(cfg["atom_counts"].values()), "stoichiometry/n_atoms as contracted", level="L1")

    # ---- L3: discrepancy disclosure ----------------------------------------
    note = report.get("discrepancy_note")
    note_ok = isinstance(note, str) and bool(note.strip())
    check("paper_vs_geometry_crosscheck", note_ok and n_center >= cfg["coordination"]["center_N_count_min"],
          "agent must report the paper's five-coordinated central-N claim against the "
          "symmetry-forced 3+3 coordination and state which geometry it adopted",
          level="L3")

    # ---- verdict -------------------------------------------------------------
    failed = [c for c in checks if c["necessary"] and not c["passed"]]
    overall = "PASS" if not failed else "FAIL"
    print(json.dumps({
        "overall": overall,
        "reward": 1.0 if overall == "PASS" else 0.0,
        "checks": checks,
        "failed": [c["criterion"] for c in failed],
        "structure_summary": {"a_A": round(a_inplane, 4), "vacuum_A": round(vacuum, 2),
                              "thickness_A": round(thickness, 2), "spacegroup": sg_number,
                              "W_counts": w_counts, "N_center": n_center},
    }, ensure_ascii=False, indent=2))
    return 0 if overall == "PASS" else 1


# ---------- helpers ----------

def parse_poscar(path: Path):
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    scale = float(lines[1])
    lattice = np.array([[float(x) for x in lines[2 + i].split()[:3]] for i in range(3)]) * scale
    idx = 5
    symbols: list[str] = []
    if lines[5][0].isalpha():
        names = lines[5].split()
        counts = [int(x) for x in lines[6].split()]
        if len(names) != len(counts):
            raise ValueError("POSCAR species line / count line mismatch")
        for name, c in zip(names, counts):
            symbols += [name] * c
        idx = 7
    else:
        counts = [int(x) for x in lines[5].split()]
        symbols = ["X"] * sum(counts)  # species-resolved POSCAR required by contract
        raise ValueError("species-resolved POSCAR (line 6 alphabetic) is required")
    mode = lines[idx].lower()
    if not mode.startswith("d"):
        raise ValueError("only Direct coordinates accepted")
    frac = np.array([[float(x) for x in lines[idx + 1 + i].split()[:3]] for i in range(len(symbols))])
    return lattice, symbols, frac


def min_pair_distance(cart: np.ndarray, lattice: np.ndarray) -> float:
    n = len(cart)
    shifts = np.array([[i, j, k] for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1)])
    dmin = float("inf")
    for i in range(n):
        for j in range(n):
            for s in shifts:
                if i == j and not s.any():
                    continue
                d = np.linalg.norm(cart[j] + s @ lattice - cart[i])
                if d > 1e-6:
                    dmin = min(dmin, d)
    return dmin


def coordination_table(species, cart, lattice, cutoffs):
    """Per-atom W<->N coordination counts under PBC minimum image convention."""
    shifts = np.array([[i, j, k] for i in (-2, -1, 0, 1, 2) for j in (-2, -1, 0, 1, 2)
                       for k in (-1, 0, 1)])
    w_idx = [i for i, s in enumerate(species) if s == "W"]
    n_idx = [i for i, s in enumerate(species) if s == "N"]
    w_counts, n_short, n_wide = [], [], []
    for i in w_idx:
        c = 0
        for j in n_idx:
            for s in shifts:
                d = np.linalg.norm(cart[j] + s @ lattice - cart[i])
                if d <= cutoffs["W_cutoff_A"]:
                    c += 1
        w_counts.append(c)
    for i in n_idx:
        c_short = c_wide = 0
        for j in w_idx:
            for s in shifts:
                d = np.linalg.norm(cart[j] + s @ lattice - cart[i])
                if d <= cutoffs["outer_N_cutoff_A"]:
                    c_short += 1
                if d <= cutoffs["center_N_cutoff_A"]:
                    c_wide += 1
        n_short.append(c_short)
        n_wide.append(c_wide)
    return {"W": w_counts, "N_short": n_short, "N_wide": n_wide}


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
