#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Eliashberg spectral numerics.
"""Scientific verifier for case-02-eliashberg-numerics.

Usage: verify.py [FINAL_DIR]     (default /app/final)

The reference values are recomputed independently from the bundled
a2f-unstrained.csv (hash-checked against tests/refs.json).
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
RESULT_NAME = "eliashberg-results.json"

def _validate_criteria(cfg: object) -> None:
    def number(value, *, positive=False, nonnegative=False):
        return (type(value) in (int, float) and math.isfinite(float(value))
                and (not positive or value > 0) and (not nonnegative or value >= 0))
    if not isinstance(cfg, dict): raise ValueError("criteria must be an object")
    mu = cfg["mu_star"]
    if not isinstance(mu, list) or len(mu) != 2 or not all(number(x, positive=True) and x < 1 for x in mu):
        raise ValueError("criteria.mu_star must contain two finite values between 0 and 1")
    bands = cfg["bands_cm1"]
    if (not isinstance(bands, list) or len(bands) != 5
            or any(not isinstance(b, list) or len(b) != 2 or not number(b[0], nonnegative=True)
                   or (b[1] is not None and not number(b[1], positive=True)) for b in bands)
            or bands[0][0] != 0 or bands[-1][1] is not None
            or any(bands[i][1] != bands[i + 1][0] for i in range(4))
            or any(b[1] is not None and b[1] <= b[0] for b in bands)):
        raise ValueError("criteria.bands_cm1 must be five contiguous increasing bands ending at null")
    for key in ("lambda_rel_tolerance", "omega_log_rel_tolerance", "tc_abs_tolerance_K",
                "band_rel_tolerance", "band_abs_tolerance", "ratio_self_rel_tolerance",
                "ratio_reference_rel_tolerance", "ad_surrogate_max_ratio"):
        if not number(cfg[key], positive=True): raise ValueError(f"criteria.{key} must be finite and positive")
    if (not isinstance(cfg["dominant_bands"], list) or len(cfg["dominant_bands"]) != 2
            or any(not isinstance(x, str) or not x.strip() for x in cfg["dominant_bands"])):
        raise ValueError("criteria.dominant_bands must contain two nonempty strings")


def fail_env(message: str) -> int:
    print(json.dumps({"overall": "ENV_INVALID", "infra_error": message}, ensure_ascii=False))
    return 2


def fail_science(message: str) -> int:
    print(json.dumps({"overall":"FAIL","reward":0.0,"checks":[],"failed":[message]},ensure_ascii=False))
    return 1


def load_spectrum(path: Path):
    omega, a2f = [], []
    with path.open() as fh:
        for row in csv.reader(fh):
            if not row or row[0].lstrip().startswith("#") or row[0].strip() == "omega_cm1":
                continue
            omega.append(float(row[0]))
            a2f.append(float(row[1]))
    return np.asarray(omega), np.asarray(a2f)


def reference_values(omega: np.ndarray, a2f: np.ndarray, cfg: dict) -> dict:
    y = a2f / omega
    lam = 2.0 * float(np.trapezoid(y, omega))
    wlog_cm1 = math.exp(2.0 * float(np.trapezoid(y * np.log(omega), omega)) / lam)

    def tc(mu: float) -> float:
        denom = lam - mu * (1.0 + 0.62 * lam)
        return (wlog_cm1 * CM1_TO_K / 1.2) * math.exp(-1.04 * (1.0 + lam) / denom)

    edges = [(lo, hi if hi is not None else 1e9) for lo, hi in cfg["bands_cm1"]]
    bands = {}
    for lo, hi in edges:
        m = (omega > lo) & (omega <= hi)
        bands[f"lambda_{lo:g}_{hi:g}_cm1" if hi < 1e9 else "lambda_above_450_cm1"] = \
            2.0 * float(np.trapezoid(a2f[m] / omega[m], omega[m]))
    return {"lambda": lam, "omega_log_cm1": wlog_cm1, "omega_log_K": wlog_cm1 * CM1_TO_K,
            "tc_mu016_K": tc(cfg["mu_star"][0]), "tc_mu01_K": tc(cfg["mu_star"][1]), "bands": bands,
            "ratio": tc(0.10) / tc(0.16)}


def close(value, ref, rel=0.0, abs_tol=0.0) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return math.isfinite(float(value)) and abs(value - ref) <= max(abs_tol, rel * abs(ref))


def finite_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def main(argv: list[str]) -> int:
    final = Path(argv[1]).resolve() if len(argv) > 1 else Path("/app/final").resolve()
    tests = Path(__file__).resolve().parent
    result_path = final / RESULT_NAME

    # Preflight bundled input integrity before grading candidate deliverables.
    import os
    asset = Path(os.environ.get("APP", "/app")) / "assets" / "a2f-unstrained.csv"
    if not asset.is_file():
        asset = tests.parent / "environment" / "assets" / "a2f-unstrained.csv"
    refs_path = tests / "refs.json"
    if not asset.is_file() or not refs_path.is_file():
        return fail_env("verifier assets missing from package")
    try:
        refs = json.loads(refs_path.read_text())
        cfg = refs["criteria"]
        _validate_criteria(cfg)
        expected_hash = refs["asset_hashes"]["assets/a2f-unstrained.csv"].removeprefix("sha256:")
    except Exception as exc:
        return fail_env(f"invalid verifier refs: {exc}")
    actual_hash = hashlib.sha256(asset.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        return fail_env("bundled a2f-unstrained.csv failed SHA-256 integrity check")

    if not result_path.is_file():
        return fail_science(f"missing deliverable: {RESULT_NAME}")
    try:
        res = json.loads(result_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return fail_science(f"{RESULT_NAME} is not valid JSON: {exc}")
    if not isinstance(res, dict):
        return fail_science(f"{RESULT_NAME} must contain a JSON object")

    omega, a2f = load_spectrum(asset)
    ref = reference_values(omega, a2f, cfg)

    checks: list[dict] = []

    def check(name, ok, detail, level="L2"):
        checks.append({"criterion": name, "level": level, "passed": bool(ok), "detail": detail})

    # ---- L1 schema ----------------------------------------------------------
    needed = ["lambda", "omega_log_cm1", "omega_log_K", "tc_mu016_K", "tc_mu01_K",
              "mu_star_sensitivity", "decomposition"]
    missing = [k for k in needed if k not in res]
    check("schema_complete", not missing,
          f"missing: {missing}" if missing else "all required fields present", level="L1")
    if missing:
        failed = [c for c in checks if not c["passed"]]
        print(json.dumps({"overall": "FAIL", "reward": 0.0, "checks": checks,
                          "failed": [c["criterion"] for c in failed]}, ensure_ascii=False))
        return 1

    sens = res.get("mu_star_sensitivity", {})
    dec = res.get("decomposition", {})
    if not isinstance(sens, dict): sens = {}
    if not isinstance(dec, dict): dec = {}
    needed2 = ["ratio_tc_mu01_over_mu016", "ad_surrogate_le_10pct_supported", "sensitivity_note"]
    band_keys = ["lambda_0_200_cm1", "lambda_200_300_cm1", "lambda_300_360_cm1",
                 "lambda_360_450_cm1", "lambda_above_450_cm1"]
    missing2 = [k for k in needed2 if k not in sens] + [k for k in band_keys if k not in dec]
    check("subschema_complete", not missing2,
          f"missing: {missing2}" if missing2 else "subfields present", level="L1")
    if missing2:
        print(json.dumps({"overall": "FAIL", "reward": 0.0, "checks": checks,
                          "failed": ["subschema_complete"]}, ensure_ascii=False))
        return 1

    # Reject malformed candidate values as a scientific/schema failure before
    # arithmetic below; malformed submissions must not crash the verifier and
    # be misreported by test.sh as an environment error.
    numeric_fields = ("lambda", "omega_log_cm1", "omega_log_K", "tc_mu016_K", "tc_mu01_K")
    bad_types = [key for key in numeric_fields if not finite_number(res.get(key))]
    bad_types += [key for key in band_keys if not finite_number(dec.get(key))]
    if not finite_number(sens.get("ratio_tc_mu01_over_mu016")):
        bad_types.append("ratio_tc_mu01_over_mu016")
    if not isinstance(sens.get("ad_surrogate_le_10pct_supported"), bool):
        bad_types.append("ad_surrogate_le_10pct_supported")
    if not isinstance(sens.get("sensitivity_note"), str):
        bad_types.append("sensitivity_note")
    if bad_types:
        checks.append({"criterion": "schema_types", "level": "L1", "passed": False,
                       "detail": f"invalid or non-finite candidate values: {bad_types}"})
        print(json.dumps({"overall": "FAIL", "reward": 0.0, "checks": checks,
                          "failed": ["schema_types"]}, ensure_ascii=False))
        return 1

    # ---- L2/L3 numeric comparisons ------------------------------------------
    mid_omega = (omega[:-1] + omega[1:]) / 2
    mid_y = (a2f[:-1] + a2f[1:]) / (2 * mid_omega)
    widths = np.diff(omega)
    mid_lambda = 2 * float(np.dot(widths, mid_y))
    mid_omega_log = math.exp(2 * float(np.dot(widths, mid_y * np.log(mid_omega))) / mid_lambda)
    integration = res.get("integration_check")
    expected = {"trapezoid_lambda": ref["lambda"], "trapezoid_omega_log_cm1": ref["omega_log_cm1"],
                "midpoint_lambda": mid_lambda, "midpoint_omega_log_cm1": mid_omega_log}
    valid_methods = (isinstance(integration, dict) and
                     all(close(integration.get(k), value, rel=1e-5) for k, value in expected.items()))
    stable_methods = (abs(mid_lambda / ref["lambda"] - 1) < 0.005 and
                      abs(mid_omega_log / ref["omega_log_cm1"] - 1) < 0.005)
    check("integration_method_sensitivity", valid_methods and stable_methods,
          "trapezoid and midpoint integrals must reproduce and differ by less than 0.5%", level="L3")
    check("lambda_value", close(res["lambda"], ref["lambda"], rel=cfg["lambda_rel_tolerance"]),
          f"agent={res['lambda']}, reference={ref['lambda']:.4f} (tol 2%)", level="L3")
    check("omega_log_cm1", close(res["omega_log_cm1"], ref["omega_log_cm1"], rel=cfg["omega_log_rel_tolerance"]),
          f"agent={res['omega_log_cm1']}, reference={ref['omega_log_cm1']:.2f} cm-1", level="L3")
    check("omega_log_K_consistent", close(res["omega_log_K"], ref["omega_log_K"], rel=cfg["omega_log_rel_tolerance"]),
          f"agent={res['omega_log_K']}, reference={ref['omega_log_K']:.2f} K", level="L3")
    check("tc_mu016", close(res["tc_mu016_K"], ref["tc_mu016_K"], abs_tol=cfg["tc_abs_tolerance_K"]),
          f"agent={res['tc_mu016_K']}, reference={ref['tc_mu016_K']:.2f} K (tol 0.6 K) "
          f"[paper anchor 19.4 K]", level="L3")
    check("tc_mu010", close(res["tc_mu01_K"], ref["tc_mu01_K"], abs_tol=cfg["tc_abs_tolerance_K"]),
          f"agent={res['tc_mu01_K']}, reference={ref['tc_mu01_K']:.2f} K (tol 0.6 K)", level="L3")

    band_ok = True
    band_detail = []
    for key in band_keys:
        ok = close(dec[key], ref["bands"][key], rel=cfg["band_rel_tolerance"], abs_tol=cfg["band_abs_tolerance"])
        band_ok &= ok
        band_detail.append(f"{key}: agent={dec[key]}, ref={ref['bands'][key]:.4f}")
    check("band_decomposition", band_ok, "; ".join(band_detail), level="L3")
    band_sum = math.fsum(dec[key] for key in band_keys)
    check("band_sum_consistent", close(band_sum, res["lambda"], rel=0.02),
          f"band sum={band_sum:.6g}, lambda={res['lambda']:.6g}", level="L3")

    ranked = sorted(band_keys, key=lambda k: -float(dec[k]))
    top2 = set(ranked[:2])
    check("dominant_modes_identified", top2 == set(cfg["dominant_bands"]),
          f"two largest bands by agent numbers: {ranked[:2]} "
          f"(paper: acoustic + 330 cm-1 optical dominate)", level="L3")

    ratio = sens.get("ratio_tc_mu01_over_mu016")
    ratio_self_consistent = (res["tc_mu016_K"] > 0 and
                             close(ratio, res["tc_mu01_K"] / res["tc_mu016_K"], rel=cfg["ratio_self_rel_tolerance"]))
    check("sensitivity_ratio_selfconsistent", ratio_self_consistent,
          f"reported ratio={ratio}, tc ratio={res['tc_mu01_K'] / res['tc_mu016_K']:.4f}")
    check("sensitivity_ratio_value", close(ratio, ref["ratio"], rel=cfg["ratio_reference_rel_tolerance"]),
          f"agent={ratio}, reference={ref['ratio']:.4f} (tol 3%)", level="L3")
    check("ad_surrogate_sensitivity_result", sens.get("ad_surrogate_le_10pct_supported") is (ref["ratio"] <= cfg["ad_surrogate_max_ratio"]),
          f"On this spectrum (lambda=1.9) the Allen-Dynes mu* sensitivity is "
          f"{ref['ratio']:.3f} (>1.10); agent must report the computed conclusion",
          level="L3")
    note = sens.get("sensitivity_note")
    check("sensitivity_note_present", isinstance(note, str) and bool(note.strip()),
          "explanation of applicability required", level="L3")

    failed = [c for c in checks if not c["passed"]]
    overall = "PASS" if not failed else "FAIL"
    print(json.dumps({"overall": overall, "reward": 1.0 if overall == "PASS" else 0.0,
                      "checks": checks, "failed": [c["criterion"] for c in failed],
                      "reference_summary": {k: (round(v, 4) if isinstance(v, float) else v)
                                            for k, v in ref.items() if k != "bands"}},
                     ensure_ascii=False, indent=2))
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
