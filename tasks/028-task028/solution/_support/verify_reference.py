#!/usr/bin/env python3
"""Independent, bounded checks for the generated author reference package.

Exit 0: numeric/reference checks pass. Exit 1: candidate science/output mismatch.
Exit 2: missing or damaged validation inputs (environment/infrastructure).
This is not the protected scientific reviewer or the task grader.
"""
from __future__ import annotations
import csv, hashlib, json, math, sys
from pathlib import Path

K_B = 1.380649e-23

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_reference.py FINAL_DIR", file=sys.stderr); return 2
    final = Path(sys.argv[1]).resolve()
    native = final / "native_evidence"
    required = [native/"data/rate_evidence.csv", native/"kinetic_screen/early_competition.csv",
                native/"kinetic_screen/stress_sensitivity.csv", native/"kinetic_screen/validation.json",
                native/"sources/source-manifest.json", native/"sources/article.xml",
                native/"sources/41467_2023_40675_MOESM1_ESM.docx",
                native/"sources/Toluene-ipso-HR-300-mesmer_out.xml"]
    if any(not p.is_file() or p.is_symlink() or p.stat().st_size == 0 for p in required):
        print("ENV_INVALID: required source/output is missing, empty, or symlinked"); return 2
    try:
        rates = {}
        with required[0].open(newline="") as f:
            for row in csv.DictReader(f):
                rates[row["reaction"]] = (float(row["rate_value"]), row["rate_units"],
                    float(row["temperature_K"]), float(row["pressure_atm"]))
        expected = {
            "i-BPR -> P-C1": (0.164121, "s^-1"),
            "i-BPR -> P-C2": (0.585048, "s^-1"),
            "i-BPR + NO -> nitrate/NO-derived sinks": (9.15e-12, "cm^3 molecule^-1 s^-1")}
        if set(rates) != set(expected): raise ValueError("rate table rows differ from reference definition")
        for key, (value, unit) in expected.items():
            if rates[key][1] != unit or rates[key][2:] != (300.0, 1.0) or not math.isclose(rates[key][0], value, rel_tol=0, abs_tol=1e-15):
                raise ValueError(f"source rate or unit mismatch: {key}")
        k1, k2, kno = (rates[k][0] for k in expected)
        density = 101325 / (K_B * 300) / 1e6
        rows = {}
        with required[1].open(newline="") as f:
            for row in csv.DictReader(f):
                key = (float(row["time_s"]), float(row["no_ppbv"]))
                if key in rows: raise ValueError("duplicate time/NO output row")
                rows[key] = row
        if len(rows) != 412: raise ValueError("early-screen row count mismatch")
        for (t, ppbv), row in rows.items():
            no_cm3 = ppbv * 1e-9 * density
            loss = kno * no_cm3
            total = k1 + k2 + loss
            reacted = -math.expm1(-total*t)
            expected_values = {"iBPR": math.exp(-total*t), "P-C1": k1/total*reacted,
                "P-C2": k2/total*reacted, "NO_lumped_sink": loss/total*reacted,
                "mass_closure": 1.0}
            for name, value in expected_values.items():
                actual = float(row[name])
                if not math.isfinite(actual) or not math.isclose(actual, value, rel_tol=2e-12, abs_tol=2e-14):
                    raise ValueError(f"numeric mismatch in {name} at t={t:g}, NO={ppbv:g} ppbv")
        validation = json.loads(required[3].read_text())
        checks = validation["checks"]
        if checks.get("accepted_grid_pass") is not True or checks.get("accepted_step_sizes_s") != [0.01, 0.001]:
            raise ValueError("analytic/RK4 validation gate failed or is malformed")
        if checks.get("accepted_grid_max_mass_closure_error", math.inf) >= 1e-10 or checks.get("accepted_grid_max_RK4_exact_error", math.inf) >= 1e-9:
            raise ValueError("reported conservation/convergence error exceeds reference tolerance")
        for name in ("g50-qd", "g200-qd"):
            d = native/"historical_local_mesmer"/name
            receipt = json.loads((d/"run-receipt.json").read_text())
            if receipt.get("architecture") != "arm64" or receipt.get("returncode") != 0:
                raise ValueError(f"historical control receipt is inconsistent: {name}")
            for pathkey, file in (("output_xml_sha256", "mesmer_out.xml"), ("test_sha256", "Toluene-mech-S2-R1.test"), ("input_sha256", "Toluene-mech-S2-R1.xml")):
                if sha(d/file) != receipt.get(pathkey): raise ValueError(f"historical receipt hash mismatch: {name}/{file}")
        print(json.dumps({"status":"PASS_REFERENCE_NUMERICS", "rows":len(rows),
            "max_mass_error":checks["accepted_grid_max_mass_closure_error"],
            "max_rk4_error":checks["accepted_grid_max_RK4_exact_error"],
            "scope":"author reference validation only; not HPC or human scientific review"}, sort_keys=True))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, OverflowError) as exc:
        print(f"FAIL_REFERENCE: {exc}", file=sys.stderr); return 1

if __name__ == "__main__": raise SystemExit(main())
