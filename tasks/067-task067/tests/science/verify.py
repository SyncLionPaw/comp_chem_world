#!/usr/bin/env python3
"""Check case-06-water-model-free-energy calculations and structured scientific diagnosis."""
from __future__ import annotations
import argparse, csv, json, math
from pathlib import Path

HERE = Path(__file__).resolve().parent
REF = json.loads((HERE / "refs.json").read_text(encoding="utf-8"))
TOL = 1e-6

def fail(message):
    raise ValueError(message)

def close(got, want, label, tol=TOL):
    if not math.isclose(float(got), float(want), rel_tol=0.0, abs_tol=tol):
        fail(f"{label}: got {got}; expected {want} ± {tol}")

def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"cannot parse {path.name}: {exc}")

def check(submission: Path):
    required = ("metrics.json", "per_ligand_effects.csv", "interpretation.json", "comparison-report.md", "provenance.json")
    missing = [name for name in required if not (submission / name).is_file()]
    if missing:
        fail("missing outputs: " + ", ".join(missing))
    metrics = load_json(submission / "metrics.json")
    for model in ("TIP3P", "TIP4P_EW"):
        if model not in metrics.get("metrics", {}):
            fail(f"metrics.json missing {model}")
        for name, expected in REF["metrics"][model].items():
            close(metrics["metrics"][model].get(name), expected, f"{model}.{name}")
    with (submission / "per_ligand_effects.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 6 or [row.get("ligand") for row in rows] != [f"G{i}" for i in range(1, 7)]:
        fail("per_ligand_effects.csv must contain ordered G1–G6 rows")
    fields = ("TIP4P_EW_minus_TIP3P_kcal_mol", "TIP3P_minus_experiment_kcal_mol", "TIP4P_EW_minus_experiment_kcal_mol")
    for row, expected in zip(rows, REF["per_ligand"]):
        for field in fields:
            close(row.get(field), expected[field], f"{expected['ligand']}.{field}")
    interp = load_json(submission / "interpretation.json")
    expected_diag = REF["diagnosis"]
    effect = interp.get("water_model_effect", {})
    close(effect.get("mean_shift_kcal_mol"), expected_diag["mean_TIP4P_EW_minus_TIP3P_kcal_mol"], "mean water-model shift", 0.01)
    expected_more_negative = [item["ligand"] for item in REF["per_ligand"] if item["TIP4P_EW_minus_TIP3P_kcal_mol"] < 0]
    if effect.get("more_negative_ligands") != expected_more_negative:
        fail("water_model_effect.more_negative_ligands must follow the six paired values")
    ranking = interp.get("ranking", {})
    close(ranking.get("kendall_tau_TIP3P"), REF["metrics"]["TIP3P"]["kendall_tau"], "TIP3P Kendall tau")
    close(ranking.get("kendall_tau_TIP4P_EW"), REF["metrics"]["TIP4P_EW"]["kendall_tau"], "TIP4P/Ew Kendall tau")
    if ranking.get("ranking_comparison") not in ("similar", "different"):
        fail("ranking.ranking_comparison must state whether the rankings are similar or different")
    calculated_same = abs(REF["metrics"]["TIP3P"]["kendall_tau"] - REF["metrics"]["TIP4P_EW"]["kendall_tau"]) <= 0.01
    if (ranking["ranking_comparison"] == "similar") != calculated_same:
        fail("ranking comparison does not follow the Kendall results")
    accuracy = interp.get("absolute_accuracy", {})
    if accuracy.get("lower_RMSE_model") not in ("TIP3P", "TIP4P_EW"):
        fail("absolute_accuracy.lower_RMSE_model must name the model with lower RMSE")
    expected_lower_rmse = min(REF["metrics"], key=lambda name: REF["metrics"][name]["absolute_rmse_kcal_mol"])
    if accuracy["lower_RMSE_model"] != expected_lower_rmse:
        fail("absolute RMSE comparison is incorrect")
    uncertainty = interp.get("uncertainty", {})
    if uncertainty.get("sigma_scope") not in ("sampling_only", "model_form_or_force_field"):
        fail("uncertainty.sigma_scope must identify what the reported sigma represents")
    if (uncertainty["sigma_scope"] == "sampling_only") != (expected_diag["force_field_causality_established"] is False):
        fail("uncertainty scope exceeds the acquired comparison evidence")
    causality = interp.get("causality", {})
    if causality.get("force_field_causal_claim_supported") is not False:
        fail("the six-ligand comparison does not support a causal force-field claim")
    report = (submission / "comparison-report.md").read_text(encoding="utf-8").strip()
    if not report:
        fail("comparison-report.md must contain a human-readable scientific diagnosis")
    provenance = load_json(submission / "provenance.json")
    if provenance.get("input_sha256") != REF["provenance"]["input_sha256"]:
        fail("provenance.json must identify the exact observation CSV hash")
    source = provenance.get("source", {})
    expected_source = REF["provenance"]["source"]
    if not isinstance(source, dict) or any(source.get(key) != value for key, value in expected_source.items()):
        fail("provenance.json must identify the source DOI, SI file, page, and tables")
    return {"status":"PASS_NUMERIC_AND_STRUCTURED_DIAGNOSIS", "scope":"numeric outputs and bounded interpretation fields; full narrative quality remains manual review"}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", action="store_true", help="run the case scoring chain using APP/TESTS/LOGS")
    parser.add_argument("submission", type=Path, nargs="?")
    args, extra = parser.parse_known_args()
    if args.runner:
        import os
        from review_status import run_case
        raise SystemExit(run_case(Path(os.environ.get("APP", "/app")).resolve(),
                                  Path(os.environ.get("TESTS", "/tests")).resolve(),
                                  Path(os.environ.get("LOGS", "/logs/verifier")).resolve()))
    if extra:
        parser.error("unexpected arguments")
    if args.submission is None:
        parser.error("submission is required unless --runner is used")
    try:
        print(json.dumps(check(args.submission), indent=2))
    except Exception as exc:
        print(json.dumps({"status":"FAIL","error":str(exc)}, indent=2))
        raise SystemExit(1)
