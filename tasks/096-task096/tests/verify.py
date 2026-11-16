#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Fit ambient MCM interlayer force constants.
"""case-01-ambient-mcm-force-constant-fit: MCM ambient fit; reject unparsable numbers; require fit-table coverage."""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
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
FIT_RMS_TOL = float(_tol("FIT_RMS_TOL"))
ALPHA_REL = float(_tol("ALPHA_REL"))
TABLE_RMS = float(_tol("TABLE_RMS"))
NEED = ["omega_S_bulk_cm1", "omega_LB_bulk_cm1", "alpha_parallel_e19", "alpha_perp_e19"]
NECESSARY = [
    "deliverables_complete",
    "finite_numeric_fields",
    "fit_reproduces_experimental_modes",
    "alpha_omega_mu_identity",
    "fit_table_consistent",
]


def load_exp():
    rows = _csv_input("public_ambient_s_lb.csv")
    s, lb = {}, {}
    for row in rows:
        n = int(float(row["N"]))
        if n > 9:
            continue
        if row.get("omega_S_N1_cm1"):
            s[n] = float(row["omega_S_N1_cm1"])
        if row.get("omega_LB_highest_cm1"):
            lb[n] = float(row["omega_LB_highest_cm1"])
    if len(s) < 8 or len(lb) < 8:
        raise InfraError("ambient reference series incomplete")
    return s, lb


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("output_dir", nargs="?", default="/app/final")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    base = Path(args.output_dir)
    checks = []

    def add(name, level, passed, detail):
        checks.append({"criterion": name, "level": level, "pass": bool(passed), "detail": detail})

    infra = None
    try:
        exp_s, exp_lb = load_exp()
    except InfraError as exc:
        report, rc = finalize_report("case-01-ambient-mcm-force-constant-fit", checks, NECESSARY, infra=str(exc))
        emit(args, report)
        return rc

    rpath = find_results(base)
    tbl_path = find_named(base, "fit_table.csv")
    data = None
    parsed = None
    if rpath is None:
        add("deliverables_complete", "L1", False, "results.json not found")
    else:
        try:
            data = load_json(rpath)
        except ValueError as exc:
            add("deliverables_complete", "L1", False, str(exc))
            data = None
        if not isinstance(data, dict) or not data:
            add("deliverables_complete", "L1", False, "results.json is null/empty")
            add("finite_numeric_fields", "L1", False, "no finite numeric fields")
        else:
            missing = [k for k in NEED if k not in data]
            add("deliverables_complete", "L1", not missing and tbl_path is not None,
                f"missing={missing or 'none'}; fit_table.csv={tbl_path is not None}")
            bad = []
            parsed = {}
            for key in NEED:
                number = parse_finite_number(data.get(key), field=key)
                parsed[key] = number
                if number is None:
                    bad.append(key)
            add("finite_numeric_fields", "L1", not bad,
                f"unparsable or non-finite: {bad or 'none'}")

    if parsed is None or any(parsed.get(k) is None for k in NEED):
        add("fit_reproduces_experimental_modes", "L2", False, "numeric fields not available; science check not skipped")
        add("alpha_omega_mu_identity", "L3", False, "numeric fields not available; science check not skipped")
        add("fit_table_consistent", "L3", False, "numeric fields not available; science check not skipped")
        report, rc = finalize_report("case-01-ambient-mcm-force-constant-fit", checks, NECESSARY, infra=infra)
        emit(args, report)
        return rc

    wS, wL = parsed["omega_S_bulk_cm1"], parsed["omega_LB_bulk_cm1"]
    aP, aT = parsed["alpha_parallel_e19"], parsed["alpha_perp_e19"]

    def rms(exp, wbulk):
        vals = [(wbulk * mcm_sin_high(n) - obs) ** 2 for n, obs in exp.items()]
        return math.sqrt(sum(vals) / len(vals))

    rS, rL = rms(exp_s, wS), rms(exp_lb, wL)
    add("fit_reproduces_experimental_modes", "L2", rS <= FIT_RMS_TOL and rL <= FIT_RMS_TOL,
        f"S RMS {rS:.3f}, LB RMS {rL:.3f} cm-1 (tol {FIT_RMS_TOL})")

    aP_id = omega_to_alpha_e19(wS)
    aT_id = omega_to_alpha_e19(wL)
    ok_id = (
        wS > 0 and wL > 0 and aP_id > 0 and aT_id > 0
        and abs(aP - aP_id) / aP_id <= ALPHA_REL
        and abs(aT - aT_id) / aT_id <= ALPHA_REL
    )
    add("alpha_omega_mu_identity", "L3", ok_id and aT > aP > 0,
        f"alpha_|| {aP:.3f} vs mu-identity {aP_id:.3f}; alpha_perp {aT:.3f} vs {aT_id:.3f}; hierarchy {aT > aP}; mu={MU_KG_M2:.6e} kg m-2")

    rows = read_csv(tbl_path) if tbl_path else []
    uniq_ok, uniq_detail = unique_pairs(rows, ("N", "branch")) if rows else (False, "empty table")
    covered_s, covered_lb = set(), set()
    errs = []
    for row in rows:
        try:
            n = int(must_number(row.get("N") or row.get("n"), "N"))
            obs = must_number(row.get("omega_exp_cm1") or row.get("exp_cm1"), "omega_exp_cm1")
            pred = must_number(row.get("omega_fit_cm1") or row.get("fit_cm1") or row.get("pred_cm1"), "omega_fit_cm1")
        except ValueError as exc:
            errs.append(str(exc))
            continue
        branch = (row.get("branch") or row.get("mode") or "").strip()
        bu = branch.upper().replace(" ", "")
        if bu.startswith("S") or "SHEAR" in bu:
            w, expmap, bucket = wS, exp_s, covered_s
        elif "LB" in bu or "BREATH" in bu:
            w, expmap, bucket = wL, exp_lb, covered_lb
        else:
            errs.append(f"unrecognized branch {branch!r}")
            continue
        bucket.add(n)
        errs.append(abs(pred - w * mcm_sin_high(n)))
        if n in expmap:
            errs.append(abs(obs - expmap[n]))
    need_n = set(range(2, 10))
    numeric_errs = [e for e in errs if isinstance(e, float)]
    msg_errs = [e for e in errs if isinstance(e, str)]
    ok_tbl = (
        uniq_ok
        and need_n <= covered_s
        and need_n <= covered_lb
        and not msg_errs
        and numeric_errs
        and max(numeric_errs) <= TABLE_RMS
    )
    add("fit_table_consistent", "L3", ok_tbl,
        f"{uniq_detail}; S N={sorted(covered_s)} LB N={sorted(covered_lb)}; "
        f"messages={msg_errs or 'none'}; max |Δ|={max(numeric_errs) if numeric_errs else 'n/a'}")

    report, rc = finalize_report("case-01-ambient-mcm-force-constant-fit", checks, NECESSARY, infra=infra)
    emit(args, report)
    return rc


if __name__ == "__main__":
    sys.exit(main())
