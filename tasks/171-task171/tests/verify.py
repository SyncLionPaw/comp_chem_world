#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Diagnose an electron–phonon campaign.
"""Scientific verifier for case-05-epc-output-diagnosis.

Usage: verify.py [FINAL_DIR]     (default /app/final)

Unpacks the bundled epc-campaign.tar.gz (hash-checked), independently parses
the reference run outputs, and audits the agent's diagnosis.json.
Exit: 0 PASS / 1 FAIL / 2 environment error.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import tarfile
import tempfile
from pathlib import Path

RESULT_NAME = "diagnosis.json"

def _validate_criteria(cfg: object) -> None:
    def number(value, *, positive=False, nonnegative=False):
        return (type(value) in (int, float) and math.isfinite(float(value))
                and (not positive or value > 0) and (not nonnegative or value >= 0))
    def window(value):
        return (isinstance(value, list) and len(value) == 2
                and all(number(x) for x in value) and value[0] <= value[1])
    if not isinstance(cfg, dict): raise ValueError("criteria must be an object")
    vocab = cfg["pathology_vocab"]
    if not isinstance(vocab, list) or not vocab or len(set(vocab)) != len(vocab) or any(not isinstance(x, str) or not x.strip() for x in vocab):
        raise ValueError("criteria.pathology_vocab must contain unique nonempty strings")
    expected = cfg["expected_pathologies"]
    runs = {"run-A", "run-B", "run-C", "run-D"}
    if not isinstance(expected, dict) or set(expected) != runs:
        raise ValueError("criteria.expected_pathologies must contain the four campaign run IDs")
    for run_id, labels in expected.items():
        if not isinstance(labels, list) or len(set(labels)) != len(labels) or any(x not in vocab for x in labels):
            raise ValueError(f"criteria.expected_pathologies.{run_id} is invalid")
    for key in ("lambda_summary_abs_tolerance", "lambda_integral_rel_tolerance", "gamma_mode_abs_tolerance_cm1"):
        if not number(cfg[key], positive=True): raise ValueError(f"criteria.{key} must be finite and positive")
    for key in ("omega_log_cm1_window", "tc_mu016_K_window", "gamma_meV_window", "gamma_mode_cm1_window"):
        if not window(cfg[key]): raise ValueError(f"criteria.{key} must be an ordered finite pair")


def fail_env(message: str) -> int:
    print(json.dumps({"overall": "ENV_INVALID", "infra_error": message}, ensure_ascii=False))
    return 2


def fail_science(message: str) -> int:
    print(json.dumps({"overall":"FAIL", "reward":0.0, "checks":[], "failed":[message]}, ensure_ascii=False))
    return 1


def parse_lambda_summary(text: str) -> dict:
    out = {}
    m = re.search(r"lambda\s*=\s*([\d.]+)", text)
    if m:
        out["lambda"] = float(m.group(1))
    m = re.search(r"omega_log \(cm-1\)\s*=\s*([\d.]+)", text)
    if m:
        out["omega_log_cm1"] = float(m.group(1))
    m = re.search(r"mu_star\s*=\s*0\.16\s*:\s*Tc\s*=\s*([\d.]+)", text)
    if m:
        out["tc_mu016_K"] = float(m.group(1))
    return out


def integrate_a2f(path: Path) -> float:
    data = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        data.append((float(parts[0]), float(parts[1])))
    import math
    lam = 0.0
    for (w0, y0), (w1, y1) in zip(data, data[1:]):
        lam += 0.5 * (y0 / w0 + y1 / w1) * (w1 - w0)
    return 2.0 * lam


def parse_linewidths(path: Path):
    best = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        gamma = float(parts[3])
        omega = float(parts[2])
        if best is None or gamma > best[1]:
            best = (omega, gamma)
    return best  # (omega_cm1, gamma_meV)


def main(argv: list[str]) -> int:
    final = Path(argv[1]).resolve() if len(argv) > 1 else Path("/app/final").resolve()
    tests = Path(__file__).resolve().parent
    result_path = final / RESULT_NAME
    asset = Path(__import__("os").environ.get("APP", "/app")) / "assets" / "epc-campaign.tar.gz"
    if not asset.is_file():
        asset = tests.parent / "environment" / "assets" / "epc-campaign.tar.gz"
    refs_path = tests / "refs.json"
    if not asset.is_file() or not refs_path.is_file():
        return fail_env("verifier assets missing from package")
    try:
        refs = json.loads(refs_path.read_text())
        cfg = refs["criteria"]
        _validate_criteria(cfg)
        expected_hash = refs["asset_hashes"]["assets/epc-campaign.tar.gz"].removeprefix("sha256:")
    except Exception as exc:
        return fail_env(f"invalid verifier refs: {exc}")
    if hashlib.sha256(asset.read_bytes()).hexdigest() != expected_hash:
        return fail_env("bundled epc-campaign.tar.gz failed SHA-256 integrity check")

    if not result_path.is_file():
        return fail_science(f"missing deliverable: {RESULT_NAME}")
    try:
        res = json.loads(result_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return fail_science(f"{RESULT_NAME} is not valid JSON: {exc}")
    if not isinstance(res, dict):
        return fail_science(f"{RESULT_NAME} must contain a JSON object")

    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(asset) as tar:
            tar.extractall(td)
        camp = Path(td) / "epc-campaign"
        summary = parse_lambda_summary((camp / "runA_lambda_summary.txt").read_text())
        lam_from_a2f = integrate_a2f(camp / "runA_a2f.dat")
        gamma_max = parse_linewidths(camp / "runA_linewidths.dat")
    if not summary or gamma_max is None:
        return fail_env("cannot parse reference outputs inside the campaign bundle")

    checks: list[dict] = []

    def check(name, ok, detail, level="L2"):
        checks.append({"criterion": name, "level": level, "passed": bool(ok), "detail": detail})

    runs = res.get("runs")
    if not isinstance(runs, dict) or set(runs) != {"run-A", "run-B", "run-C", "run-D"}:
        return fail_science("runs must contain exactly run-A, run-B, run-C, run-D")

    # ---- diagnosis sets ------------------------------------------------------
    diag_fail = []
    for rid, expected_pathologies in cfg["expected_pathologies"].items():
        truth = set(expected_pathologies)
        entry = runs.get(rid, {})
        if not isinstance(entry, dict):
            diag_fail.append(f"{rid}: entry must be an object")
            continue
        pathologies = entry.get("pathologies")
        if not isinstance(pathologies, list):
            diag_fail.append(f"{rid}: pathologies not a list")
            continue
        if not set(pathologies) <= set(cfg["pathology_vocab"]):
            diag_fail.append(f"{rid}: out-of-vocabulary pathologies {sorted(set(pathologies) - set(cfg['pathology_vocab']))}")
            continue
        if set(pathologies) != truth:
            diag_fail.append(f"{rid}: agent={sorted(pathologies)}, reference={sorted(truth)}")
        if entry.get("trustworthy") is not (rid == "run-A"):
            diag_fail.append(f"{rid}: trustworthy should be {rid == 'run-A'}")
        ev = entry.get("evidence")
        if not isinstance(ev, str) or not ev.strip():
            diag_fail.append(f"{rid}: evidence missing")
    check("run_diagnosis_sets", not diag_fail,
          "; ".join(diag_fail) if diag_fail else
          "all four runs diagnosed with exact pathology sets (run-B unconverged_scf; "
          "run-C insufficient_vacuum; run-D k+q mesh + smearing)", level="L3")
    check("selected_chain", res.get("selected_chain") == "run-A",
          f"agent={res.get('selected_chain')}", level="L3")

    # ---- extraction ----------------------------------------------------------
    ex = res.get("extracted")
    if not isinstance(ex, dict):
        return fail_science("extracted must be a mapping")
    numeric_fields = ("lambda", "omega_log_cm1", "tc_mu016_K", "lambda_from_a2f_dat", "gamma_max_meV", "gamma_max_mode_omega_cm1")
    bad_numbers = [k for k in numeric_fields if not isinstance(ex.get(k), (int, float)) or not math.isfinite(ex[k])]
    for key in bad_numbers:
        ex[key] = -1.0
    check("lambda_from_summary", abs(ex.get("lambda", -1) - summary["lambda"]) <= cfg["lambda_summary_abs_tolerance"],
          f"agent={ex.get('lambda')}, bundle summary={summary['lambda']}", level="L3")
    check("omega_log", cfg["omega_log_cm1_window"][0] <= ex.get("omega_log_cm1", -1) <= cfg["omega_log_cm1_window"][1],
          f"agent={ex.get('omega_log_cm1')}, bundle={summary['omega_log_cm1']} cm-1 "
          "(paper anchor ~112.8)", level="L3")
    check("tc_mu016", cfg["tc_mu016_K_window"][0] <= ex.get("tc_mu016_K", -1) <= cfg["tc_mu016_K_window"][1],
          f"agent={ex.get('tc_mu016_K')}, bundle={summary['tc_mu016_K']} K "
          "(paper anchor 19.4 K)", level="L3")
    check("lambda_crosscheck_from_a2f",
          abs(ex.get("lambda_from_a2f_dat", -1) - lam_from_a2f) <= cfg["lambda_integral_rel_tolerance"] * lam_from_a2f
          and abs(ex.get("lambda_from_a2f_dat", -1) - ex.get("lambda", 9)) <= cfg["lambda_integral_rel_tolerance"] * ex.get("lambda", 9),
          f"agent={ex.get('lambda_from_a2f_dat')}, verifier integration={lam_from_a2f:.4f}", level="L3")
    check("gamma_max_mode",
          cfg["gamma_meV_window"][0] <= ex.get("gamma_max_meV", -1) <= cfg["gamma_meV_window"][1] and cfg["gamma_mode_cm1_window"][0] <= ex.get("gamma_max_mode_omega_cm1", -1) <= cfg["gamma_mode_cm1_window"][1]
          and abs(ex.get("gamma_max_mode_omega_cm1", -1) - gamma_max[0]) <= cfg["gamma_mode_abs_tolerance_cm1"],
          f"agent=({ex.get('gamma_max_meV')} meV @ {ex.get('gamma_max_mode_omega_cm1')} cm-1), "
          f"reference=({gamma_max[1]} meV @ {gamma_max[0]} cm-1); paper: the 330 cm-1 "
          "optical mode carries the largest linewidth", level="L3")

    failed = [c for c in checks if not c["passed"]]
    overall = "PASS" if not failed else "FAIL"
    print(json.dumps({"overall": overall, "reward": 1.0 if overall == "PASS" else 0.0,
                      "checks": checks, "failed": [c["criterion"] for c in failed],
                      "reference": {"summary": summary, "lambda_from_a2f": round(lam_from_a2f, 4),
                                    "gamma_max": gamma_max}},
                     ensure_ascii=False, indent=2))
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
