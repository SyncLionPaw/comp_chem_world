#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Strain and doping trends.
"""Scientific verifier for case-03-tuning-phase-diagram.

Usage: verify.py [FINAL_DIR]     (default /app/final)

Recomputes every series member from the bundled a2f-tuning-series.csv and
compares against the agent's tuning-report.json.
Exit: 0 PASS / 1 FAIL / 2 environment error.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

CM1_TO_K = 1.4387768775
RESULT_NAME = "tuning-report.json"

def _validate_criteria(cfg: object) -> None:
    def number(value, *, positive=False, nonnegative=False):
        return (type(value) in (int, float) and math.isfinite(float(value))
                and (not positive or value > 0) and (not nonnegative or value >= 0))
    def span(value, *, positive=False):
        return (isinstance(value, list) and len(value) == 2
                and all(number(x, positive=positive) for x in value) and value[0] <= value[1])
    if not isinstance(cfg, dict): raise ValueError("criteria must be an object")
    members = cfg["members"]
    if not isinstance(members, list) or len(members) != 11 or len(set(members)) != 11 or any(not isinstance(x, str) or not x.strip() for x in members):
        raise ValueError("criteria.members must contain 11 unique nonempty IDs")
    for key in ("soft_frequency_cutoff_cm1", "exceeds_known_lambda"):
        if not number(cfg[key], positive=True): raise ValueError(f"criteria.{key} must be finite and positive")
    if not number(cfg["soft_lambda_fraction_max"], nonnegative=True) or cfg["soft_lambda_fraction_max"] > 1:
        raise ValueError("criteria.soft_lambda_fraction_max must be between 0 and 1")
    for key in ("lambda_omega_rel_tolerance", "tc_abs_tolerance_K", "soft_fraction_abs_tolerance",
                "hole_bracket_abs_tolerance", "electron_tc_abs_tolerance_K", "electron_range_margin_K",
                "extreme_lambda_rel_tolerance"):
        if not number(cfg[key], nonnegative=True): raise ValueError(f"criteria.{key} must be finite and nonnegative")
    if not span(cfg["electron_paper_tc_range_K"], positive=True):
        raise ValueError("criteria.electron_paper_tc_range_K must be an increasing positive pair")
    points = cfg["trend_comparison_points"]
    expected = {"compression_lambda", "compression_omega_log", "hole_lambda", "expansion_lambda", "electron_tc", "extreme_coupling"}
    if not isinstance(points, dict) or set(points) != expected:
        raise ValueError("criteria.trend_comparison_points has invalid keys")
    for key in ("compression_lambda", "compression_omega_log", "hole_lambda"):
        pair = points[key]
        if not isinstance(pair, list) or len(pair) != 2 or any(x not in members for x in pair):
            raise ValueError(f"criteria.trend_comparison_points.{key} must name two series members")
    for key in ("expansion_lambda", "electron_tc", "extreme_coupling"):
        if not isinstance(points[key], str) or points[key] not in members:
            raise ValueError(f"criteria.trend_comparison_points.{key} must name a series member")


def fail_env(message: str) -> int:
    print(json.dumps({"overall": "ENV_INVALID", "infra_error": message}, ensure_ascii=False))
    return 2


def fail_science(message: str) -> int:
    print(json.dumps({"overall": "FAIL", "reward": 0.0,
                      "checks": [{"criterion": "deliverable_valid", "level": "L1",
                                  "passed": False, "detail": message}],
                      "failed": ["deliverable_valid"]}, ensure_ascii=False, indent=2))
    return 1


def load_series(path: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    data: dict[str, list[tuple[float, float]]] = {}
    with path.open() as fh:
        for row in csv.reader(fh):
            if not row or row[0].lstrip().startswith("#") or row[0].strip() == "series_id":
                continue
            data.setdefault(row[0].strip(), []).append((float(row[1]), float(row[2])))
    out = {}
    for sid, rows in data.items():
        arr = np.array(rows, dtype=float)
        order = np.argsort(arr[:, 0])
        out[sid] = (arr[order, 0], arr[order, 1])
    return out


def member_reference(omega: np.ndarray, a2f: np.ndarray, cfg: dict) -> dict:
    y = a2f / omega
    lam = 2.0 * float(np.trapezoid(y, omega))
    wlog = math.exp(2.0 * float(np.trapezoid(y * np.log(omega), omega)) / lam)

    def tc(mu):
        return (wlog * CM1_TO_K / 1.2) * math.exp(-1.04 * (1.0 + lam) / (lam - mu * (1.0 + 0.62 * lam)))

    m_soft = omega < cfg["soft_frequency_cutoff_cm1"]
    soft_frac = 2.0 * float(np.trapezoid(a2f[m_soft] / omega[m_soft], omega[m_soft])) / lam
    proxy_safe = soft_frac <= cfg["soft_lambda_fraction_max"]
    return {"lambda": lam, "omega_log_cm1": wlog, "tc_mu016_K": tc(0.16), "tc_mu01_K": tc(0.10),
            "soft": soft_frac, "proxy_safe": proxy_safe, "soft_mode_risk": not proxy_safe}


def close(value, ref, rel=0.0, abs_tol=0.0) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if not math.isfinite(float(value)):
        return False
    return abs(value - ref) <= max(abs_tol, rel * abs(ref))


def main(argv: list[str]) -> int:
    final = Path(argv[1]).resolve() if len(argv) > 1 else Path("/app/final").resolve()
    tests = Path(__file__).resolve().parent
    result_path = final / RESULT_NAME
    import os
    app_root = Path(os.environ.get("APP", "/app")).resolve()
    asset = app_root / "assets" / "a2f-tuning-series.csv"
    if not asset.is_file():
        asset = tests.parent / "environment" / "assets" / "a2f-tuning-series.csv"
    refs_path = tests / "refs.json"
    if not asset.is_file() or not refs_path.is_file():
        return fail_env("verifier assets missing from package")
    try:
        refs = json.loads(refs_path.read_text())
        cfg = refs["criteria"]
        _validate_criteria(cfg)
        expected_hash = refs["asset_hashes"]["assets/a2f-tuning-series.csv"].removeprefix("sha256:")
    except Exception as exc:
        return fail_env(f"invalid verifier reference file: {exc}")
    if hashlib.sha256(asset.read_bytes()).hexdigest() != expected_hash:
        return fail_env("bundled a2f-tuning-series.csv failed SHA-256 integrity check")

    if not result_path.is_file():
        return fail_science(f"missing deliverable: {RESULT_NAME}")
    try:
        res = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail_science(f"{RESULT_NAME} is not valid JSON: {exc}")
    if not isinstance(res, dict):
        return fail_science(f"{RESULT_NAME} must contain a JSON object")

    series = load_series(asset)
    member_ids = cfg["members"]
    ref = {sid: member_reference(*series[sid], cfg) for sid in series}

    checks: list[dict] = []

    def check(name, ok, detail, level="L2"):
        checks.append({"criterion": name, "level": level, "passed": bool(ok), "detail": detail})

    members = res.get("members")
    if not isinstance(members, list):
        members = []
    by_id = {}
    for entry in members:
        if isinstance(entry, dict) and isinstance(entry.get("series_id"), str):
            by_id[entry["series_id"]] = entry

    # ---- L1 coverage ---------------------------------------------------------
    missing_ids = [sid for sid in member_ids if sid not in by_id]
    extra_ids = [sid for sid in by_id if sid not in member_ids]
    check("members_covered", not missing_ids and not extra_ids and len(members) == len(member_ids),
          f"missing={missing_ids}, unexpected={extra_ids}", level="L1")


    # ---- L2/L3 per-member ----------------------------------------------------
    numeric_fail = []
    proxy_fail = []
    for sid in member_ids:
        entry = by_id.get(sid)
        r = ref[sid]
        if entry is None:
            continue
        if not close(entry.get("lambda"), r["lambda"], rel=cfg["lambda_omega_rel_tolerance"]):
            numeric_fail.append(f"{sid}:lambda agent={entry.get('lambda')} ref={r['lambda']:.3f}")
        if not close(entry.get("omega_log_cm1"), r["omega_log_cm1"], rel=cfg["lambda_omega_rel_tolerance"]):
            numeric_fail.append(f"{sid}:omega_log agent={entry.get('omega_log_cm1')} ref={r['omega_log_cm1']:.2f}")
        if entry.get("soft_mode_risk") is not r["soft_mode_risk"]:
            proxy_fail.append(f"{sid}: soft_mode_risk={entry.get('soft_mode_risk')}, expected={r['soft_mode_risk']}")
        if entry.get("proxy_safe") is not r["proxy_safe"]:
            proxy_fail.append(f"{sid}: proxy_safe={entry.get('proxy_safe')}, expected={r['proxy_safe']}")
        for key in ("tc_mu016_K", "tc_mu01_K"):
            value = entry.get(key)
            if r["soft_mode_risk"]:
                if value is not None:
                    numeric_fail.append(f"{sid}:{key} must be null when the soft-mode proxy flags risk")
            elif not close(value, r[key], abs_tol=cfg["tc_abs_tolerance_K"]):
                numeric_fail.append(f"{sid}:{key} agent={value} ref={r[key]:.2f}")
        sf = entry.get("soft_lambda_fraction_below_12cm1")
        if not close(sf, r["soft"], abs_tol=cfg["soft_fraction_abs_tolerance"]):
            numeric_fail.append(f"{sid}:soft_fraction agent={sf} ref={r['soft']:.3f}")

    check("member_numerics", not numeric_fail,
          "; ".join(numeric_fail) if numeric_fail else
          "all 11 members within tolerances (lambda/omega_log 3%, Tc 1.0 K, soft fraction 0.05)")
    check("soft_mode_screening", not proxy_fail,
          "; ".join(proxy_fail) if proxy_fail else
          "soft_mode_risk/proxy_safe match the low-frequency spectral-weight screen; these labels do not establish dynamical stability",
          level="L3")

    points = cfg["trend_comparison_points"]
    compression, baseline = points["compression_lambda"]
    omega_compression, omega_baseline = points["compression_omega_log"]
    hole, hole_baseline = points["hole_lambda"]
    expansion = points["expansion_lambda"]
    electron = points["electron_tc"]
    extreme = points["extreme_coupling"]
    lam0 = ref[baseline]["lambda"]
    trends_ref = {
        "compression_reduces_lambda": ref[compression]["lambda"] < lam0,
        "compression_raises_omega_log": ref[omega_compression]["omega_log_cm1"] > ref[omega_baseline]["omega_log_cm1"],
        "hole_doping_raises_lambda": ref[hole]["lambda"] > ref[hole_baseline]["lambda"],
    }
    trends = res.get("trends", {})
    if not isinstance(trends, dict): trends = {}
    if not isinstance(trends, dict):
        trends = {}
    check("trend_compression_lambda", trends.get("compression_reduces_lambda") is trends_ref["compression_reduces_lambda"],
          f"reference={trends_ref['compression_reduces_lambda']} "
          f"(lambda {ref[compression]['lambda']:.2f} @ -2% vs {lam0:.2f} @ 0%)", level="L3")
    check("trend_compression_omega_log", trends.get("compression_raises_omega_log") is trends_ref["compression_raises_omega_log"],
          f"reference={trends_ref['compression_raises_omega_log']} "
          f"(omega_log {ref[omega_compression]['omega_log_cm1']:.0f} vs "
          f"{ref[omega_baseline]['omega_log_cm1']:.0f} cm-1)", level="L3")
    check("trend_expansion_lambda", close(trends.get("expansion_1pct_lambda"), ref[expansion]["lambda"], rel=cfg["extreme_lambda_rel_tolerance"]),
          f"agent={trends.get('expansion_1pct_lambda')}, reference={ref[expansion]['lambda']:.3f} "
          f"[paper anchor 3.5]", level="L3")
    check("trend_hole_lambda", trends.get("hole_doping_raises_lambda") is trends_ref["hole_doping_raises_lambda"],
          f"reference={trends_ref['hole_doping_raises_lambda']} "
          f"(lambda {ref[hole]['lambda']:.2f} @ 0.1h vs {lam0:.2f})", level="L3")

    bracket = trends.get("hole_soft_mode_risk_bracket")
    proxy_safe_holes = sorted(float(sid.split("_")[1].rstrip("h").replace("p", "."))
                              for sid in member_ids if sid.startswith("hole_") and ref[sid]["proxy_safe"])
    risk_holes = sorted(float(sid.split("_")[1].rstrip("h").replace("p", "."))
                        for sid in member_ids if sid.startswith("hole_") and ref[sid]["soft_mode_risk"])
    expected_bracket = [proxy_safe_holes[-1], risk_holes[0]] if proxy_safe_holes and risk_holes else None
    bracket_ok = (isinstance(bracket, list) and len(bracket) == 2 and expected_bracket is not None
                  and all(close(x, y, abs_tol=cfg["hole_bracket_abs_tolerance"]) for x, y in zip(bracket, expected_bracket)))
    check("hole_soft_mode_risk_bracket", bracket_ok,
          f"agent={bracket}, sampled proxy bracket={expected_bracket}; must use neighboring supplied hole-doping members",
          level="L3")

    e_tc = trends.get(f"{electron}_tc_mu016_K")
    e_member_tc = by_id.get(electron, {}).get("tc_mu016_K")
    e_ref = ref[electron]["tc_mu016_K"]
    e_ok = (close(e_tc, e_ref, abs_tol=cfg["electron_tc_abs_tolerance_K"])
            and close(e_member_tc, e_ref, abs_tol=cfg["electron_tc_abs_tolerance_K"])
            and cfg["electron_paper_tc_range_K"][0] - cfg["electron_range_margin_K"] <= e_tc <= cfg["electron_paper_tc_range_K"][1] + cfg["electron_range_margin_K"])
    check("electron_doping_tc_range", e_ok,
          f"agent trend={e_tc}, member={e_member_tc}, reference={e_ref:.2f} K; "
          "paper range 0.4-1.6 K (+-0.1 margin)", level="L3")
    check("electron_doping_range_boolean", trends.get("electron_doping_tc_in_paper_range") is (cfg["electron_paper_tc_range_K"][0] <= e_ref <= cfg["electron_paper_tc_range_K"][1]),
          "agent must recognize the 1.0 e/u.c. Tc falls inside the paper's reported range", level="L3")

    ec = res.get("extreme_coupling", {})
    if not isinstance(ec, dict): ec = {}
    if not isinstance(ec, dict):
        ec = {}
    check("extreme_coupling_series", ec.get("series_id") == extreme
          and close(ec.get("lambda_value"), ref[expansion]["lambda"], rel=cfg["extreme_lambda_rel_tolerance"]),
          f"agent={ec.get('series_id')}, lambda={ec.get('lambda_value')}", level="L3")
    check("extreme_coupling_record", ec.get("exceeds_known_materials") is (ref[expansion]["lambda"] > cfg["exceeds_known_lambda"]),
          f"reference +1% lambda compared with stated bound {cfg['exceeds_known_lambda']}", level="L3")
    check("extreme_coupling_tc_reliability", ec.get("quantitative_tc_reliable") is False,
          "the supplied +1% spectrum flags soft-mode risk and lambda exceeds the stated range; qualify the scalar Allen-Dynes estimate",
          level="L3")
    rationale = ec.get("rationale")
    check("extreme_coupling_rationale", isinstance(rationale, str) and bool(rationale.strip()),
          "physical justification required", level="L3")

    failed = [c for c in checks if not c["passed"]]
    overall = "PASS" if not failed else "FAIL"
    print(json.dumps({"overall": overall, "reward": 1.0 if overall == "PASS" else 0.0,
                      "checks": checks, "failed": [c["criterion"] for c in failed],
                      "reference_members": {sid: {k: (round(v, 4) if isinstance(v, float) else v)
                                                  for k, v in r.items()}
                                            for sid, r in ref.items()}},
                     ensure_ascii=False, indent=2))
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
