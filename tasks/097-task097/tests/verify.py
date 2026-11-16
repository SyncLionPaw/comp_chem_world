#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Pressure coefficients and the S/LB crossover.
"""case-02-pressure-coefficient-crossover: unique (N,branch) slope tables; recompute alternate-window slopes."""
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
SLOPE_TOL = float(_tol("SLOPE_TOL"))
DEFAULT_PMIN, DEFAULT_PMAX = 1.0, 8.0
S_N = list(range(2, 10))
LB_N = [2, 4, 5, 6, 7, 8, 9]
NECESSARY = [
    "deliverables_complete",
    "finite_numeric_fields",
    "slopes_match_independent_refit",
    "slope_table_complete_unique",
    "n3_lb_missing_declared",
    "opposite_layer_trends",
    "crossover_split_continuous_vs_integer",
    "window_sensitivity_recomputed",
]


def load_peaks():
    s, lb = defaultdict(list), defaultdict(list)
    for name, store in (("public_s_n1_vs_p.csv", s), ("public_lb_nnminus1_vs_p.csv", lb)):
        for row in _csv_input(name):
            if str(row["N"]).lower() == "bulk":
                continue
            store[int(float(row["N"]))].append((float(row["P_GPa"]), float(row["omega_cm1"])))
    return s, lb


def window_from(obj, default=None):
    if isinstance(obj, dict) and parse_finite_number(obj.get("pmin")) is not None and parse_finite_number(obj.get("pmax")) is not None:
        pmin, pmax = float(obj["pmin"]), float(obj["pmax"])
        if pmax > pmin:
            return pmin, pmax
    if isinstance(obj, (list, tuple)) and len(obj) == 2:
        a, b = parse_finite_number(obj[0]), parse_finite_number(obj[1])
        if a is not None and b is not None and b > a:
            return a, b
    return default


def fit_branch(series, pmin, pmax):
    out = {}
    for n, pts in series.items():
        xs = [p for p, o in pts if pmin <= p <= pmax]
        ys = [o for p, o in pts if pmin <= p <= pmax]
        fit = linreg(xs, ys)
        if fit:
            out[n] = fit
    return out


def slope_dict(raw, required):
    keyed = as_nkey(raw)
    if keyed is None:
        return None
    out = {}
    for n in required:
        number = parse_finite_number(keyed.get(n))
        if number is None:
            return None
        out[n] = number
    return out


def first_observed_reversal(s_slopes, l_slopes):
    ns = sorted(set(s_slopes) & set(l_slopes))
    cont = None
    first = None
    for a, b in zip(ns, ns[1:]):
        d0 = s_slopes[a] - l_slopes[a]
        d1 = s_slopes[b] - l_slopes[b]
        if d0 == 0:
            cont = float(a)
            first = a
            break
        if d0 * d1 < 0:
            cont = a + (0 - d0) / (d1 - d0) * (b - a)
            first = b if d1 > 0 else a
            break
    return cont, first


def validate_n3_lb_status(value, available_in_packaged_data):
    """Validate the exact public N=3 LB availability declaration against the loaded CSV."""
    keys = {"available_in_packaged_data", "imputed"}
    if not isinstance(value, dict) or set(value) != keys:
        return False, "status must be an object with exactly available_in_packaged_data and imputed"
    available = value.get("available_in_packaged_data")
    imputed = value.get("imputed")
    if type(available) is not bool or type(imputed) is not bool:
        return False, "both status fields must be JSON booleans"
    if available != available_in_packaged_data:
        return False, f"availability declaration {available} differs from supplied CSV ({available_in_packaged_data})"
    if imputed:
        return False, "N=3 LB value must not be imputed"
    return True, f"availability matches supplied CSV ({available}); imputed={imputed}"


def mcm_continuous_crossover(ref_s, ref_lb):
    """Fit independent zero-intercept MCM prefactors to observed layers in one window."""
    s_num = s_den = lb_num = lb_den = 0.0
    for n in sorted(set(ref_s) & set(S_N)):
        fit = ref_s[n]
        basis = math.cos(math.pi / (2.0 * n))
        s_num += basis * fit["slope"]
        s_den += basis * basis
    for n in sorted(set(ref_lb) & set(LB_N)):
        fit = ref_lb[n]
        basis = math.sin(math.pi / (2.0 * n))
        lb_num += basis * fit["slope"]
        lb_den += basis * basis
    if s_den <= 0 or lb_den <= 0:
        return None
    pref_s, pref_lb = s_num / s_den, lb_num / lb_den
    if not all(math.isfinite(x) and x > 0 for x in (pref_s, pref_lb)):
        return None
    root = math.pi / (2.0 * math.atan2(pref_s, pref_lb))
    return root if math.isfinite(root) and root > 0 else None


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
        peaks_s, peaks_lb = load_peaks()
    except InfraError as exc:
        report, rc = finalize_report("case-02-pressure-coefficient-crossover", checks, NECESSARY, infra=str(exc))
        emit(args, report)
        return rc

    need = ["domega_dP_S_cm1_per_GPa", "domega_dP_LB_cm1_per_GPa",
            "crossover_N_continuous", "crossover_N_integer_first_observed_reversal",
            "n3_LB_status", "pressure_window_GPa", "window_sensitivity",
            "crossover_continuous_method"]
    # accept predecessor key name
    rpath = find_results(base)
    tbl_path = find_named(base, "slope_fits.csv")
    data = None
    if rpath is None:
        add("deliverables_complete", "L1", False, "results.json not found")
    else:
        try:
            data = load_json(rpath)
        except ValueError as exc:
            add("deliverables_complete", "L1", False, str(exc))
            data = None
        if not isinstance(data, dict) or not data:
            add("deliverables_complete", "L1", False, "empty/null results")
        else:
            if "crossover_N_integer_first_observed_reversal" not in data and "crossover_N_integer_first_reversal" in data:
                data["crossover_N_integer_first_observed_reversal"] = data["crossover_N_integer_first_reversal"]
            missing = [k for k in need if k not in data]
            add("deliverables_complete", "L1", not missing and tbl_path is not None,
                f"missing={missing or 'none'}; slope_fits.csv={tbl_path is not None}")

    sS = sL = None
    if isinstance(data, dict):
        sS = slope_dict(data.get("domega_dP_S_cm1_per_GPa"), S_N)
        sL = slope_dict(data.get("domega_dP_LB_cm1_per_GPa"), LB_N)
        extra_lb3 = False
        keyed_l = as_nkey(data.get("domega_dP_LB_cm1_per_GPa") or {})
        if keyed_l and 3 in keyed_l and parse_finite_number(keyed_l[3]) is not None:
            extra_lb3 = True
        add("finite_numeric_fields", "L1", sS is not None and sL is not None and not extra_lb3,
            f"S slopes parsed={sS is not None}; LB slopes parsed={sL is not None}; N=3 LB numeric submitted={extra_lb3}")
    else:
        add("finite_numeric_fields", "L1", False, "no results")

    if sS is None or sL is None or not isinstance(data, dict):
        for name, level in [
            ("slopes_match_independent_refit", "L2"),
            ("slope_table_complete_unique", "L2"),
            ("n3_lb_missing_declared", "L2"),
            ("opposite_layer_trends", "L3"),
            ("crossover_split_continuous_vs_integer", "L3"),
            ("window_sensitivity_recomputed", "L2"),
        ]:
            add(name, level, False, "numeric slopes unavailable; science check not skipped")
        report, rc = finalize_report("case-02-pressure-coefficient-crossover", checks, NECESSARY)
        emit(args, report)
        return rc

    win = window_from(data.get("pressure_window_GPa"))
    if win is None:
        add("slopes_match_independent_refit", "L2", False, "pressure_window_GPa not a finite pmin<pmax pair")
        pmin, pmax = DEFAULT_PMIN, DEFAULT_PMAX
    else:
        pmin, pmax = win
    ref_s = fit_branch(peaks_s, pmin, pmax)
    ref_lb = fit_branch(peaks_lb, pmin, pmax)
    if win is not None:
        devs = [abs(sS[n] - ref_s[n]["slope"]) for n in S_N if n in ref_s]
        devs += [abs(sL[n] - ref_lb[n]["slope"]) for n in LB_N if n in ref_lb]
        ok = len(devs) >= 12 and max(devs) <= SLOPE_TOL
        add("slopes_match_independent_refit", "L2", ok,
            f"{len(devs)} slopes on window [{pmin},{pmax}] GPa; max |Δ| {max(devs, default=99):.3f}")

    rows = read_csv(tbl_path) if tbl_path else []
    uniq_ok, uniq_detail = unique_pairs(rows, ("N", "branch")) if rows else (False, "empty")
    seen_s, seen_lb = set(), set()
    row_fail = []
    for row in rows:
        try:
            n = int(must_number(row.get("N") or row.get("n"), "N"))
            sl = must_number(row.get("slope") or row.get("domega_dP"), "slope")
            intercept = must_number(row.get("intercept"), "intercept")
            npts = int(must_number(row.get("n_points") or row.get("n"), "n_points"))
            se = parse_finite_number(row.get("se") or row.get("stderr") or 0)
        except ValueError as exc:
            row_fail.append(str(exc))
            continue
        br = (row.get("branch") or "").upper()
        if br.startswith("S"):
            target, ref, bucket = sS, fit_branch(peaks_s, pmin, pmax), seen_s
        elif "LB" in br:
            target, ref, bucket = sL, fit_branch(peaks_lb, pmin, pmax), seen_lb
        else:
            row_fail.append(f"bad branch {br}")
            continue
        if n not in target:
            row_fail.append(f"unexpected {br} N={n}")
            continue
        bucket.add(n)
        if abs(sl - target[n]) > 0.05:
            row_fail.append(f"slope mismatch N={n} {br}")
        if n in ref:
            if abs(intercept - ref[n]["intercept"]) > 0.8:
                row_fail.append(f"intercept mismatch N={n}")
            if npts != ref[n]["n"]:
                row_fail.append(f"n_points mismatch N={n} got {npts} expected {ref[n]['n']}")
            if se is None:
                row_fail.append(f"se missing N={n}")
    ok_tbl = uniq_ok and set(S_N) <= seen_s and set(LB_N) <= seen_lb and 3 not in seen_lb and not row_fail
    add("slope_table_complete_unique", "L2", ok_tbl,
        f"{uniq_detail}; S={sorted(seen_s)} LB={sorted(seen_lb)}; issues={row_fail[:8] or 'none'}")

    n3_available = 3 in peaks_lb and bool(peaks_lb[3])
    ok_n3, n3_detail = validate_n3_lb_status(
        data.get("n3_LB_status"), n3_available
    )
    add("n3_lb_missing_declared", "L2", ok_n3, n3_detail)

    def trend(d):
        pts = sorted(d.items())
        fit = linreg([n for n, _ in pts], [v for _, v in pts])
        return fit["slope"] if fit else 0.0
    s_up, l_dn = trend(sS) > 0.02, trend(sL) < -0.02
    add("opposite_layer_trends", "L3", s_up and l_dn,
        f"d(slope_S)/dN={trend(sS):.3f}; d(slope_LB)/dN={trend(sL):.3f}")

    n_cont = parse_finite_number(data.get("crossover_N_continuous"))
    n_int = parse_finite_number(data.get("crossover_N_integer_first_observed_reversal"))
    method = data.get("crossover_continuous_method")
    ref_cont, first = first_observed_reversal(
        {n: fit["slope"] for n, fit in ref_s.items()},
        {n: fit["slope"] for n, fit in ref_lb.items()},
    )
    if method == "experimental_interpolation":
        expected_cont = ref_cont
    elif method == "mcm":
        expected_cont = mcm_continuous_crossover(ref_s, ref_lb)
    else:
        expected_cont = None
    ok_integer = (
        n_int is not None and n_int.is_integer() and first is not None
        and int(n_int) == first
    )
    ok_continuous = (
        n_cont is not None and expected_cont is not None
        and abs(n_cont - expected_cont) <= 0.8
    )
    ok_split = (
        isinstance(method, str) and method in {"experimental_interpolation", "mcm"}
        and ok_integer and ok_continuous
    )
    detail = (
        f"method={method!r}; continuous {n_cont} vs independent {expected_cont}; "
        f"integer observed {n_int} vs independently refit first reversal {first}"
    )
    add("crossover_split_continuous_vs_integer", "L3", bool(ok_split), detail)

    sens = data.get("window_sensitivity")
    alt = None
    if isinstance(sens, dict):
        alt = window_from(sens.get("alt_window") or sens)
    ok_sens = False
    sens_detail = "alt window missing or null"
    if alt:
        apmin, apmax = alt
        if abs(apmin - pmin) < 1e-9 and abs(apmax - pmax) < 1e-9:
            sens_detail = "alternate window must differ from the primary window"
        else:
            alt_s = fit_branch(peaks_s, apmin, apmax)
            submitted_alt = sens.get("slopes_S") or sens.get("domega_dP_S_cm1_per_GPa") if isinstance(sens, dict) else None
            keyed = as_nkey(submitted_alt) if isinstance(submitted_alt, dict) else None
            if keyed:
                cmp = []
                for n in S_N:
                    if n in alt_s and parse_finite_number(keyed.get(n)) is not None:
                        cmp.append(abs(float(keyed[n]) - alt_s[n]["slope"]))
                ok_sens = len(cmp) >= 6 and max(cmp) <= SLOPE_TOL
                sens_detail = f"alt [{apmin},{apmax}] compared {len(cmp)} S slopes; max |Δ| {max(cmp, default=99):.3f}"
            else:
                sens_detail = "alternate slopes missing or non-finite"
    add("window_sensitivity_recomputed", "L2", ok_sens, sens_detail)

    report, rc = finalize_report("case-02-pressure-coefficient-crossover", checks, NECESSARY)
    emit(args, report)
    return rc


if __name__ == "__main__":
    sys.exit(main())
