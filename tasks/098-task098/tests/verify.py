#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: MD spectra and elastic-modulus inversion.
"""case-03-md-spectra-elastic-moduli: tracked LB branch + non-empty mode evidence; strict finite parsing."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
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
EXPECTED_P = [0.0, 0.5, 1.65, 2.4, 3.06, 4.09, 4.7, 5.48, 6.3, 7.25, 8.0, 9.6]
MD_REF = {
    0.0: 3.83, 0.5: 4.25, 1.65: 5.32, 2.4: 5.81, 3.06: 6.16,
    4.09: 6.87, 4.7: 7.24, 5.48: 7.82, 6.3: 8.21,
}
S_ABS = 3.0
LB_ABS = 8.0
ALPHA_ID = 0.06
MOD_ID = 0.08
AUTHOR_S_REL = float(_tol("AUTHOR_S_REL"))
NEED = ["pressures_GPa", "omega_S_bulk_cm1", "omega_LB_bulk_cm1",
        "alpha_parallel_e19", "alpha_perp_e19", "C44_GPa", "C33_GPa"]
NECESSARY = [
    "deliverables_complete",
    "finite_numeric_fields",
    "grid_complete",
    "independent_shear_peaks",
    "tracked_lb_branch",
    "alpha_omega_and_C_equals_alpha_t",
    "alpha_parallel_vs_author_md",
    "high_pressure_independent_coverage",
    "mode_assignment_evidence",
]


def load_indep(asset_root: Path):
    try:
        rows = _json_input("independent_md_spectra.json")
    except (OSError, ValueError) as exc:
        raise InfraError(f"independent LB reference is unreadable: {exc}") from exc
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_P):
        raise InfraError("independent LB reference must contain exactly 12 records")
    expected_files = ["P_0.00.txt", "P_0.50.txt", "P_1.65.txt", "P_2.4.txt",
                      "P_3.06.txt", "P_4.09.txt", "P_4.70.txt", "P_5.48.txt",
                      "P_6.30.txt", "P_7.25.txt", "P_8.00.txt", "P_9.60.txt"]
    meta_files = {
        "trajectory_format.md": "trajectory_format_sha256",
        "6L_MoS2_origin": "layer_order_sha256",
        "conventions.md": "conventions_sha256",
    }
    meta_hashes = {}
    for filename, field in meta_files.items():
        source = asset_root / filename
        if source.is_symlink() or not source.is_file():
            raise InfraError(f"pinned LB source metadata is missing or redirected: {filename}")
        meta_hashes[field] = hashlib.sha256(source.read_bytes()).hexdigest()
    try:
        import numpy as np
    except Exception as exc:
        raise InfraError(f"NumPy unavailable for pinned raw-source validation: {exc}") from exc
    out = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise InfraError(f"independent LB record {i} is not an object")
        try:
            pressure = float(row.get("P_GPa"))
        except (TypeError, ValueError):
            raise InfraError(f"independent LB record {i} has invalid pressure")
        if not math.isfinite(pressure) or abs(pressure - EXPECTED_P[i]) > 1e-8:
            raise InfraError(f"independent LB pressure grid/order mismatch at record {i}")
        filename = expected_files[i]
        if row.get("file") != filename:
            raise InfraError(f"independent LB record has wrong source filename at P={pressure}")
        for field, expected_hash in meta_hashes.items():
            if row.get(field) != expected_hash:
                raise InfraError(f"independent LB metadata pin mismatch: {field}")
        source = asset_root / filename
        if source.is_symlink() or not source.is_file():
            raise InfraError(f"pinned raw centroid source missing or redirected: {filename}")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if row.get("source_sha256") != digest or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise InfraError(f"raw centroid source pin mismatch: {filename}")
        if row.get("dt_s") != 1e-15 or type(row.get("n_frames")) is not int or row.get("n_frames") != 50001:
            raise InfraError(f"raw centroid sampling metadata mismatch: {filename}")
        try:
            raw = np.loadtxt(source, comments="#", dtype=float)
        except Exception as exc:
            raise InfraError(f"raw centroid source cannot be parsed: {filename}: {exc}") from exc
        if raw.ndim != 2 or raw.shape[0] != 50001 or raw.shape[1] < 18:
            raise InfraError(f"raw centroid source has wrong shape: {filename}: {raw.shape}")
        if not np.isfinite(raw[:, :18]).all():
            raise InfraError(f"raw centroid source contains non-finite values: {filename}")
        if "omega_LB_candidates_cm1" in row or "omega_LB_tracked_cm1" in row:
            raise InfraError("obsolete nearest-candidate LB reference fields are forbidden")
        numeric_fields = ("omega_S_cm1", "omega_LB_reference_cm1", "omega_LB_gap_correlation_cm1",
                          "omega_LB_segmented_cm1", "method_spread_cm1",
                          "alternating_residual_fraction", "gap_pattern_fraction")
        values = {}
        for field in numeric_fields:
            value = row.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise InfraError(f"independent LB reference field is invalid: {field} at P={pressure}")
            values[field] = float(value)
        if any(values[field] <= 0 for field in numeric_fields[:4]):
            raise InfraError(f"independent mode frequency is not positive at P={pressure}")
        if values["method_spread_cm1"] < 0 or values["method_spread_cm1"] > LB_ABS:
            raise InfraError(f"independent estimators disagree beyond the public tolerance at P={pressure}")
        if not 0 < values["alternating_residual_fraction"] <= 1 or not 0 < values["gap_pattern_fraction"] <= 1:
            raise InfraError(f"independent spatial-mode evidence is invalid at P={pressure}")
        lags = row.get("gap_lag_sensitivity")
        if not isinstance(lags, list) or [x.get("lag_samples") for x in lags if isinstance(x, dict)] != [5000, 10000, 15000]:
            raise InfraError(f"gap-lag sensitivity record is malformed at P={pressure}")
        if round(pressure, 2) in out:
            raise InfraError("duplicate independent LB pressure record")
        out[round(pressure, 2)] = row
    if len(out) != len(EXPECTED_P):
        raise InfraError("independent LB pressure coverage is incomplete")
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
        asset_root = Path(args.output_dir).absolute().parent / "assets"
        indep = load_indep(asset_root)
    except InfraError as exc:
        report, rc = finalize_report("case-03-md-spectra-elastic-moduli", checks, NECESSARY, infra=str(exc))
        emit(args, report)
        return rc

    rpath = find_results(base)
    methods = find_named(base, "methods.md")
    evidence = find_named(base, "mode_evidence.md") or find_named(base, "spectra.csv")
    data = None
    arrays = None
    if rpath is None:
        add("deliverables_complete", "L1", False, "results.json not found")
    else:
        try:
            data = load_json(rpath)
        except ValueError as exc:
            add("deliverables_complete", "L1", False, str(exc))
        if not isinstance(data, dict) or not data:
            add("deliverables_complete", "L1", False, "null/empty results")
            add("finite_numeric_fields", "L1", False, "no finite numeric arrays")
        else:
            missing = [k for k in NEED if k not in data]
            add("deliverables_complete", "L1", not missing and methods is not None,
                f"missing={missing or 'none'}; methods.md={methods is not None}")
            arrays = {}
            bad = []
            for key in NEED:
                seq = numbers_aligned(data.get(key), 12)
                arrays[key] = seq
                if seq is None:
                    bad.append(key)
            add("finite_numeric_fields", "L1", not bad, f"unparsable/non-finite/wrong-length: {bad or 'none'}")

    if not arrays or any(arrays.get(k) is None for k in NEED):
        for name, level in [
            ("grid_complete", "L1"),
            ("independent_shear_peaks", "L2"),
            ("tracked_lb_branch", "L2"),
            ("alpha_omega_and_C_equals_alpha_t", "L3"),
            ("alpha_parallel_vs_author_md", "L3"),
            ("high_pressure_independent_coverage", "L3"),
            ("mode_assignment_evidence", "L2"),
        ]:
            add(name, level, False, "numeric arrays unavailable; science check not skipped")
        report, rc = finalize_report("case-03-md-spectra-elastic-moduli", checks, NECESSARY)
        emit(args, report)
        return rc

    P = arrays["pressures_GPa"]
    uniq = len(set(round(p, 2) for p in P))
    grid = uniq == 12 and all(abs(a - b) <= 0.03 for a, b in zip(sorted(P), EXPECTED_P))
    add("grid_complete", "L1", grid, f"pressures={P}")
    if not grid:
        for name, level in [
            ("independent_shear_peaks", "L2"),
            ("tracked_lb_branch", "L2"),
            ("alpha_omega_and_C_equals_alpha_t", "L3"),
            ("alpha_parallel_vs_author_md", "L3"),
            ("high_pressure_independent_coverage", "L3"),
            ("mode_assignment_evidence", "L2"),
        ]:
            add(name, level, False, "pressure grid invalid; science check not skipped")
        report, rc = finalize_report("case-03-md-spectra-elastic-moduli", checks, NECESSARY)
        emit(args, report)
        return rc

    order = sorted(range(12), key=lambda i: P[i])
    P = [P[i] for i in order]
    wS = [arrays["omega_S_bulk_cm1"][i] for i in order]
    wL = [arrays["omega_LB_bulk_cm1"][i] for i in order]
    aP = [arrays["alpha_parallel_e19"][i] for i in order]
    aT = [arrays["alpha_perp_e19"][i] for i in order]
    c44 = [arrays["C44_GPa"][i] for i in order]
    c33 = [arrays["C33_GPa"][i] for i in order]

    s_err, lb_err, lb_pressure_errors = [], [], []
    try:
        for i, p in enumerate(P):
            rec = indep.get(round(p, 2))
            if rec is None:
                raise InfraError(f"no independent spectrum for P={p}")
            s_err.append(abs(wS[i] - rec["omega_S_cm1"]))
            error = abs(wL[i] - rec["omega_LB_reference_cm1"])
            lb_err.append(error)
            lb_pressure_errors.append((p, error))
    except (InfraError, TypeError, ValueError) as exc:
        report, rc = finalize_report("case-03-md-spectra-elastic-moduli", checks, NECESSARY, infra=str(exc))
        emit(args, report)
        return rc
    add("independent_shear_peaks", "L2", max(s_err) <= S_ABS,
        f"max |Δω_S| {max(s_err):.2f} cm-1 (tol {S_ABS})")
    worst_p, worst_error = max(lb_pressure_errors, key=lambda item: item[1])
    add("tracked_lb_branch", "L2", bool(lb_err) and max(lb_err) <= LB_ABS,
        f"max per-pressure |Δω_LB| {worst_error:.2f} cm-1 at {worst_p:g} GPa (single tolerance {LB_ABS:g} cm-1)")

    id_err, c_err, hier = [], [], True
    for i, p in enumerate(P):
        aP_id = omega_to_alpha_e19(wS[i])
        aT_id = omega_to_alpha_e19(wL[i])
        id_err.append(abs(aP[i] - aP_id) / aP_id)
        id_err.append(abs(aT[i] - aT_id) / aT_id)
        t = t_of_p(p)
        c_err.append(abs(c44[i] - aP[i] * 1e19 * t / 1e9) / max(abs(c44[i]), 1e-6))
        c_err.append(abs(c33[i] - aT[i] * 1e19 * t / 1e9) / max(abs(c33[i]), 1e-6))
        hier = hier and aT[i] > aP[i] > 0 and c33[i] > c44[i]
    add("alpha_omega_and_C_equals_alpha_t", "L3", max(id_err) <= ALPHA_ID and max(c_err) <= MOD_ID and hier,
        f"max α–ω rel {max(id_err):.2%}; max C−αt rel {max(c_err):.2%}; hierarchy {hier}")

    rels = []
    matched = 0
    for i, p in enumerate(P):
        key = round(p, 2)
        if key in MD_REF:
            rels.append(abs(aP[i] - MD_REF[key]) / MD_REF[key])
            if rels[-1] <= AUTHOR_S_REL:
                matched += 1
    add("alpha_parallel_vs_author_md", "L3", matched == len(MD_REF),
        f"{matched}/{len(MD_REF)} shared P within {AUTHOR_S_REL:.0%} on α_||; max rel {max(rels, default=1):.1%}")
    add("high_pressure_independent_coverage", "L3", sum(1 for p in P if p >= 7.2) == 3,
        "7.25, 8.0, 9.6 GPa present")

    body = evidence.read_text(encoding="utf-8", errors="ignore") if evidence else ""
    add("mode_assignment_evidence", "L2", bool(body.strip()),
        f"nonempty mode-assignment evidence file={evidence is not None}")

    report, rc = finalize_report("case-03-md-spectra-elastic-moduli", checks, NECESSARY)
    emit(args, report)
    return rc


if __name__ == "__main__":
    sys.exit(main())
