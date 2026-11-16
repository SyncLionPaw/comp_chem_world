#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: DCM inversion of intra- and interlayer force constants.
"""case-04-dcm-force-constant-inversion: S7/S8 physical root, Figure 5b check, both slopes, full Cs ratio."""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
from collections import defaultdict
from pathlib import Path


C_CM_S = 2.99792458e10
U_KG = 1.66053906660e-27
MO_U = 95.95
S_U = 32.065
A_ANG = 3.160
MU_KG_M2 = (MO_U + 2.0 * S_U) * U_KG / ((A_ANG * 1e-10) ** 2 * math.sqrt(3.0) / 2.0)
MU_LAYER_KG = (MO_U + 2.0 * S_U) * U_KG
MX_ATOM_KG = S_U * U_KG  # SI Note 2: Mx is the chalcogen *atomic* mass
MM_ATOM_KG = MO_U * U_KG
T0_M = 6.15e-10
BETA_C = 10.4e-3

NONFINITE_STRINGS = {
    "nan", "+nan", "-nan", "na", "n/a", "none", "null",
    "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity",
}


class InfraError(Exception):
    """Missing reference files or verifier internals — not a science FAIL."""


def parse_finite_number(value, *, field: str = "value"):
    """Return a finite float, or None if the value is not an allowed number.

    Allowed: int/float (not bool) and numeric strings such as '32.5'.
    Rejected: None, bool, 'NaN', Infinity, empty, other types.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in NONFINITE_STRINGS:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isfinite(number):
            return number
        return None
    return None


def must_number(value, field: str):
    number = parse_finite_number(value, field=field)
    if number is None:
        raise ValueError(f"{field}: not a finite number ({value!r})")
    return number


def finite(x) -> bool:
    return parse_finite_number(x) is not None


def omega_to_alpha_e19(omega_cm1: float, mu: float = MU_KG_M2) -> float:
    return mu * (math.pi * C_CM_S * float(omega_cm1)) ** 2 / 1e19


def t_of_p(p: float) -> float:
    return T0_M * (1.0 - BETA_C * float(p))


def mcm_sin_high(n: int) -> float:
    return math.sin((n - 1) * math.pi / (2.0 * n))


def mcm_sin_low(n: int) -> float:
    return math.sin(math.pi / (2.0 * n))


def find_results(base: Path):
    for cand in (base / "final" / "results.json", base / "results.json"):
        if cand.is_file():
            return cand
    hits = list(base.rglob("results.json"))
    return hits[0] if hits else None


def find_named(base: Path, name: str):
    for cand in (base / "final" / name, base / name):
        if cand.is_file():
            return cand
    hits = [p for p in base.rglob(name) if p.is_file()]
    return hits[0] if hits else None


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"unparsable JSON: {exc}") from exc


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def linreg(xs, ys):
    pts = []
    for x, y in zip(xs, ys):
        px, py = parse_finite_number(x), parse_finite_number(y)
        if px is not None and py is not None:
            pts.append((px, py))
    n = len(pts)
    if n < 2:
        return None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    den = sum((p[0] - mx) ** 2 for p in pts)
    if den <= 0:
        return None
    slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / den
    intercept = my - slope * mx
    resid = [p[1] - (slope * p[0] + intercept) for p in pts]
    dof = max(n - 2, 1)
    s2 = sum(r * r for r in resid) / dof
    se = math.sqrt(s2 / den)
    rmse = math.sqrt(sum(r * r for r in resid) / n)
    return {"slope": slope, "intercept": intercept, "n": n, "se": se, "rmse": rmse}


def as_nkey(x):
    if not isinstance(x, dict):
        return None
    out = {}
    for k, v in x.items():
        ks = str(k).strip().lower()
        if ks == "bulk":
            if "bulk" in out:
                return None
            out["bulk"] = v
            continue
        try:
            nk = int(float(k))
        except (TypeError, ValueError):
            return None
        if nk in out:
            return None
        out[nk] = v
    return out


def numbers_aligned(seq, expected_len: int | None = None):
    if isinstance(seq, dict):
        try:
            keys = sorted(seq, key=lambda s: float(s))
        except (TypeError, ValueError):
            return None
        values = [seq[k] for k in keys]
    elif isinstance(seq, list):
        values = list(seq)
    else:
        return None
    out = []
    for item in values:
        number = parse_finite_number(item)
        if number is None:
            return None
        out.append(number)
    if expected_len is not None and len(out) != expected_len:
        return None
    return out


def unique_pairs(rows: list[dict], fields: tuple[str, ...]) -> tuple[bool, str]:
    seen = []
    for row in rows:
        key = tuple((row.get(f) or "").strip() for f in fields)
        if key in seen:
            return False, f"duplicate {fields}: {key}"
        seen.append(key)
    return True, f"{len(seen)} unique rows"


def text_nonempty(path: Path, min_chars: int = 80) -> bool:
    if path is None or not path.is_file():
        return False
    return len(path.read_text(encoding="utf-8", errors="ignore").strip()) >= min_chars


def finalize_report(case_id: str, checks: list[dict], necessary: list[str], infra: str | None = None) -> tuple[dict, int]:
    if infra:
        report = {
            "case_id": case_id,
            "overall": "ERROR",
            "infra_error": infra,
            "checks": checks,
        }
        return report, 2
    names = {c["criterion"] for c in checks}
    missing = [name for name in necessary if name not in names]
    if missing:
        checks.append({
            "criterion": "necessary_checks_executed",
            "level": "L1",
            "pass": False,
            "detail": f"required checks never ran: {missing}",
        })
    overall = bool(checks) and all(c.get("pass") for c in checks)
    report = {
        "case_id": case_id,
        "overall": "PASS" if overall else "FAIL",
        "checks": checks,
    }
    return report, (0 if overall else 1)


def emit(args, report: dict) -> None:
    if args.json:
        print(json.dumps(report, indent=2))
        return
    for check in report.get("checks", []):
        flag = "PASS" if check.get("pass") else "FAIL"
        print(f"[{flag}] {check.get('level')} {check.get('criterion')}: {check.get('detail')}")
    if report.get("infra_error"):
        print("INFRA:", report["infra_error"])
    print("OVERALL:", report["overall"])

HERE = Path(__file__).resolve().parent

_REFS = json.loads((HERE / "refs.json").read_text(encoding="utf-8"))
_TOL = _REFS.get("tolerances") or {}
if not isinstance(_TOL, dict):
    raise InfraError("refs.json tolerances must be an object")


def _tol(name):
    if name not in _TOL:
        raise InfraError(f"refs.json missing tolerance: {name}")
    return _TOL[name]

def _input_text(name):
    doc = json.loads((HERE / "refs.json").read_text(encoding="utf-8"))
    text = (doc.get("test_inputs") or {}).get(name)
    if text is None:
        path = HERE / name
        if not path.is_file():
            raise InfraError(f"missing embedded input: {name}")
        text = path.read_text(encoding="utf-8")
    return text


def _csv_input(name):
    return list(csv.DictReader(io.StringIO(_input_text(name))))


def _json_input(name):
    return json.loads(_input_text(name))
RATIO_BOUND = 0.045
CSB_REL = float(_tol("CSB_REL"))
CSB_ROUTE_REL = float(_tol("CSB_ROUTE_REL"))
CSW_ROUTE_REL = float(_tol("CSW_ROUTE_REL"))
MM = MM_ATOM_KG
MX = MX_ATOM_KG
M_RED = (MM * MX) / (MM + 2.0 * MX)
LAYERS = [2, 3, 4, 5, 6, 7, 8, 9, "bulk"]
NECESSARY = [
    "deliverables_complete",
    "finite_numeric_fields",
    "dcm_table_content",
    "physical_root_and_coverage",
    "cs_b_vs_author_figure5b",
    "slopes_refit_cs_b_and_cs_w",
    "ratio_recomputed_from_cs",
    "ratio_bound_and_max_point",
    "dcm_science_status",
]


def ang2(nu: float) -> float:
    return (2.0 * math.pi * C_CM_S * float(nu)) ** 2


def nu_from_ang2(value: float) -> float:
    return math.sqrt(value) / (2.0 * math.pi * C_CM_S)


def routes(nu1: float, nu2: float):
    """S8/S7 approximation and the exact S7/S8 quadratic. Units: N/m ≡ 10^-2 N/cm."""
    w1, w2 = ang2(nu1), ang2(nu2)
    cb_approx = w2 * (MM + 2.0 * MX) / 4.0
    cw_lead = M_RED * w1
    prod = w1 * w2 * MM * MX / 4.0
    b_coef = (w1 + w2) * MX / 2.0
    c_coef = w1 * w2 * MX * (MM + 2.0 * MX) / 8.0
    disc = b_coef * b_coef - 4.0 * c_coef
    if disc < 0:
        return None
    small = (b_coef - math.sqrt(disc)) / 2.0
    large = (b_coef + math.sqrt(disc)) / 2.0
    cw_exact = prod / small
    return {
        "cb_approx": cb_approx,
        "cw_lead": cw_lead,
        "cb_exact": small,
        "cw_exact": cw_exact,
        "cb_large": large,
    }


def nearest_omega(series, pressure, span=0.25):
    if not series:
        return None
    p, omega = min(series, key=lambda item: abs(item[0] - pressure))
    if abs(p - pressure) > span:
        return None
    return omega


def load_public_modes():
    e1, e2 = defaultdict(list), defaultdict(list)
    for row in _csv_input("public_e2g1_vs_p.csv"):
        e1[row["N"].strip()].append((float(row["P_GPa"]), float(row["omega_E2g1_cm1"])))
    for row in _csv_input("public_e2g2_vs_p.csv"):
        key = "omega_cm1" if "omega_cm1" in row else "omega_E2g2_cm1"
        e2[row["N"].strip()].append((float(row["P_GPa"]), float(row[key])))
    return e1, e2


def load_author_csb():
    by_n = defaultdict(list)
    for row in _csv_input("author_cs_b.csv"):
        n = row["N"].strip()
        by_n[n].append((float(row["P_GPa"]), float(row["Cs_b_e-2_N_cm-1"])))
    return by_n


def as_table(raw):
    keyed = as_nkey(raw)
    if keyed is None:
        return None
    out = {}
    for n, series in keyed.items():
        if not isinstance(series, dict) or not series:
            return None
        pts = {}
        for p, v in series.items():
            pf, vf = parse_finite_number(p), parse_finite_number(v)
            if pf is None or vf is None:
                return None
            if pf in pts:
                return None
            pts[pf] = vf
        out[str(n)] = pts
    return out


def slope_map(raw, required_keys):
    keyed = as_nkey(raw)
    if keyed is None:
        return None
    out = {}
    for n in required_keys:
        lookup = keyed.get("bulk" if n == "bulk" else int(n))
        number = parse_finite_number(lookup)
        if number is None:
            return None
        out[str(n)] = number
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("output_dir", nargs="?", default="/app/final")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    base = Path(args.output_dir)
    checks = []

    def add(name, level, passed, detail):
        checks.append({"criterion": name, "level": level, "pass": bool(passed), "detail": detail})

    try:
        author = load_author_csb()
        public_e1, public_e2 = load_public_modes()
    except InfraError as exc:
        report, rc = finalize_report("case-04-dcm-force-constant-inversion", checks, NECESSARY, infra=str(exc))
        emit(args, report)
        return rc

    need = ["Cs_b", "Cs_w", "dCs_b_dP", "dCs_w_dP", "ratio_Cs_b_over_Cs_w",
            "physical_root_rationale", "pairing_rule"]
    rpath = find_results(base)
    tbl_path = find_named(base, "dcm_table.csv")
    data = None
    if rpath is None:
        add("deliverables_complete", "L1", False, "results.json not found")
    else:
        try:
            data = load_json(rpath)
        except ValueError as exc:
            add("deliverables_complete", "L1", False, str(exc))
        if not isinstance(data, dict) or not data:
            add("deliverables_complete", "L1", False, "empty/null")
        else:
            missing = [k for k in need if k not in data]
            add("deliverables_complete", "L1", not missing and tbl_path is not None,
                f"missing={missing or 'none'}; dcm_table.csv={tbl_path is not None}")

    csb = csw = ratio = dcsb = dcsw = None
    if isinstance(data, dict):
        csb = as_table(data.get("Cs_b"))
        csw = as_table(data.get("Cs_w"))
        ratio = as_table(data.get("ratio_Cs_b_over_Cs_w"))
        reqk = [2, 3, 4, 5, 6, 7, 8, 9, "bulk"]
        dcsb = slope_map(data.get("dCs_b_dP"), reqk)
        dcsw = slope_map(data.get("dCs_w_dP"), reqk)
        add("finite_numeric_fields", "L1",
            all(v is not None for v in (csb, csw, ratio, dcsb, dcsw)),
            f"Cs_b={csb is not None} Cs_w={csw is not None} ratio={ratio is not None} "
            f"dCs_b={dcsb is not None} dCs_w={dcsw is not None}")
    else:
        add("finite_numeric_fields", "L1", False, "no results")

    if not all(v is not None for v in (csb, csw, ratio, dcsb, dcsw)):
        for name, level in [
            ("dcm_table_content", "L2"),
            ("physical_root_and_coverage", "L3"),
            ("cs_b_vs_author_figure5b", "L3"),
            ("slopes_refit_cs_b_and_cs_w", "L3"),
            ("ratio_recomputed_from_cs", "L3"),
            ("ratio_bound_and_max_point", "L3"),
            ("dcm_science_status", "L3"),
        ]:
            add(name, level, False, "tables incomplete; science check not skipped")
        report, rc = finalize_report("case-04-dcm-force-constant-inversion", checks, NECESSARY)
        emit(args, report)
        return rc

    rows = read_csv(tbl_path) if tbl_path else []
    uniq_ok, uniq_detail = unique_pairs(rows, ("N", "P_GPa")) if rows else (False, "empty")
    parse_fail = []
    n_layers = set()
    for row in rows:
        try:
            n = str(row.get("N")).strip()
            p = must_number(row.get("P_GPa"), "P")
            for col in ("Cs_b", "Cs_w", "ratio", "omega_E2g1_cm1", "omega_E2g2_cm1",
                        "omega_E2g1_back_cm1", "omega_E2g2_back_cm1"):
                must_number(row.get(col), col)
            n_layers.add(n)
        except ValueError as exc:
            parse_fail.append(str(exc))
    ok_tbl = uniq_ok and len(rows) >= 80 and len(n_layers) >= 8 and not parse_fail
    add("dcm_table_content", "L2", ok_tbl,
        f"{uniq_detail}; rows={len(rows)}; layers={sorted(n_layers)}; parse_fail={parse_fail[:4] or 'none'}")

    phys = True
    coverage = set()
    npts = 0
    for n, series in csb.items():
        if n not in csw:
            phys = False
            continue
        coverage.add(n)
        for p, vb in series.items():
            vw = csw[n].get(p)
            if vw is None:
                # nearest
                pw = min(csw[n], key=lambda q: abs(q - p))
                if abs(pw - p) > 0.2:
                    continue
                vw = csw[n][pw]
            npts += 1
            phys = phys and vb > 0 and vw > vb
    add("physical_root_and_coverage", "L3", phys and npts >= 40 and len(coverage) >= 8,
        f"points={npts}; layers={sorted(coverage)}; Cs_w>Cs_b>0: {phys}")
    add("root_rationale_present", "L2",
        isinstance(data.get("physical_root_rationale"), str) and bool(data["physical_root_rationale"].strip()),
        "physical-root rationale")
    add("pairing_rule_present", "L2",
        isinstance(data.get("pairing_rule"), str) and bool(data["pairing_rule"].strip()),
        "pairing rule")

    # Independent author check (Figure 5b), not scorer-forward formula.
    rels = []
    for n, pts in author.items():
        series = csb.get(n) or csb.get(str(n))
        if not series:
            continue
        for p, ref in pts:
            pb = min(series, key=lambda q: abs(q - p))
            if abs(pb - p) > 0.2:
                continue
            rels.append(abs(series[pb] - ref) / abs(ref))
    add("cs_b_vs_author_figure5b", "L3", len(rels) >= 40 and max(rels) <= CSB_REL,
        f"{len(rels)} Cs_b points vs Figure 5b; max rel {max(rels, default=1):.1%} (tol {CSB_REL:.0%}). "
        "Figure 5b matches the S8 approximation to ≤0.2%; the exact physical root stays within 4%.")

    slope_err = []
    for label, table, submitted in (("b", csb, dcsb), ("w", csw, dcsw)):
        for n, series in table.items():
            fit = linreg(sorted(series), [series[p] for p in sorted(series)])
            if not fit or str(n) not in submitted:
                continue
            slope_err.append(abs(submitted[str(n)] - fit["slope"]))
    add("slopes_refit_cs_b_and_cs_w", "L3", len(slope_err) >= 14 and max(slope_err) <= 0.08,
        f"{len(slope_err)} dCs/dP values vs linreg of submitted Cs curves; max |Δ| {max(slope_err, default=99):.3f}")

    ratio_err, rmax, rcount = [], 0.0, 0
    full_max = 0.0
    for n, series in csb.items():
        if n not in csw:
            continue
        for p, vb in series.items():
            pw = min(csw[n], key=lambda q: abs(q - p))
            if abs(pw - p) > 0.15:
                continue
            pred = vb / csw[n][pw]
            full_max = max(full_max, pred)
            if n in ratio:
                pr = min(ratio[n], key=lambda q: abs(q - p), default=None)
                if pr is None or abs(pr - p) > 0.15:
                    continue
                rcount += 1
                rmax = max(rmax, ratio[n][pr], pred)
                ratio_err.append(abs(ratio[n][pr] - pred) / max(abs(pred), 1e-12))
    add("ratio_recomputed_from_cs", "L3", rcount >= 40 and max(ratio_err, default=1) <= 0.05,
        f"{rcount} ratio points; max identity error {max(ratio_err, default=1):.1%}")
    add("ratio_bound_and_max_point", "L3", full_max <= RATIO_BOUND + 0.005 and rcount > 0,
        f"max Cs_b/Cs_w over complete Cs table={full_max:.4f} (paper bound {RATIO_BOUND}; "
        "S8+S7-leading stays ≤4.5%, exact physical root ≤5%)")

    cb_err, cw_err, large_hits, n_inv = [], [], 0, 0
    for n, series in csb.items():
        if n not in csw:
            continue
        for p, vb in series.items():
            o2 = nearest_omega(public_e2.get(n, []), p)
            o1 = nearest_omega(public_e1.get(n, []), p)
            if o1 is None or o2 is None:
                continue
            route = routes(o1, o2)
            if route is None:
                continue
            pw = min(csw[n], key=lambda q: abs(q - p))
            if abs(pw - p) > 0.2:
                continue
            vw = csw[n][pw]
            n_inv += 1
            cb_ok = min(
                abs(vb - route["cb_approx"]) / route["cb_approx"],
                abs(vb - route["cb_exact"]) / route["cb_exact"],
            )
            cw_ok = min(
                abs(vw - route["cw_lead"]) / route["cw_lead"],
                abs(vw - route["cw_exact"]) / abs(route["cw_exact"]),
            )
            cb_err.append(cb_ok)
            cw_err.append(cw_ok)
            if abs(vb - route["cb_large"]) < abs(vb - route["cb_exact"]):
                large_hits += 1
    back_bad = 0
    back_n = 0
    for row in rows:
        try:
            cb = must_number(row.get("Cs_b"), "Cs_b")
            cw = must_number(row.get("Cs_w"), "Cs_w")
            b1 = must_number(row.get("omega_E2g1_back_cm1"), "back1")
            b2 = must_number(row.get("omega_E2g2_back_cm1"), "back2")
        except ValueError:
            back_bad += 1
            continue
        if cb <= 0 or cw <= 0:
            back_bad += 1
            continue
        nu2_a = nu_from_ang2(4.0 * cb / (MM + 2.0 * MX))
        nu1_a = nu_from_ang2(cw / M_RED)
        approx_err = max(abs(b1 - nu1_a), abs(b2 - nu2_a))
        inner = (cw / (2.0 * M_RED) + cb / MX) ** 2 - 4.0 * cw * cb / (MM * MX)
        exact_err = 1e9
        if inner >= 0:
            root = math.sqrt(inner)
            base = cw / (2.0 * M_RED) + cb / MX
            nu1_e = nu_from_ang2(base + root)
            nu2_e = nu_from_ang2(base - root)
            exact_err = max(abs(b1 - nu1_e), abs(b2 - nu2_e))
        back_n += 1
        if min(approx_err, exact_err) > 1.0:
            back_bad += 1
    science_ok = (
        n_inv >= 40
        and max(cb_err, default=1) <= CSB_ROUTE_REL
        and max(cw_err, default=1) <= CSW_ROUTE_REL
        and large_hits == 0
        and back_n >= 40
        and back_bad == 0
    )
    add("dcm_science_status", "L3", science_ok,
        f"{n_inv} paired points; max |Δ| Cs_b {max(cb_err, default=1):.1%} (tol {CSB_ROUTE_REL:.0%}), "
        f"Cs_w {max(cw_err, default=1):.1%} (tol {CSW_ROUTE_REL:.0%}); "
        f"large-root hits={large_hits}; back-substitution failures={back_bad}/{back_n}. "
        "Accepts the S8/S7 approximation or the smaller exact root. "
        "Mx is the chalcogen atomic mass; M = Mm Mx/(Mm+2 Mx).")

    report, rc = finalize_report("case-04-dcm-force-constant-inversion", checks, NECESSARY)
    emit(args, report)
    return rc


if __name__ == "__main__":
    sys.exit(main())
