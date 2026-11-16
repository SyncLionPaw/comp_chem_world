#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Audit COF Efficiency Claims and Cross-Table Consistency.
"""Case 05 verifier: printed-number audit of efficiency and COF claims.

Frozen criteria:
- timing_claims_verified_from_tables: main Table 3 totals/shares/speed-ups;
  Table 4 cycle derivation for all six COFs with the 15100N2 exception.
- table5_stokes_and_mae_consistency: Stokes shifts within 0.01 eV; MAE row
  Evert/Efl/lambda reproduced within +/-0.02 eV; the Ead column difference
  (~0.48 eV vs printed 0.42 eV) MUST be reported as documented-discrepancy.
- cof_bookkeeping_cross_table_match: Table 4 vs SI table 52 atoms/basis counts.
Negative examples: forcing the Ead MAE to match or silently dropping it FAILs;
environment/grading-input damage exits 2 without reward.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import csv


import json

import math

import os

import re

from pathlib import Path

class InfraError(Exception):
    """Missing/corrupted grading inputs or verifier dependencies -> exit 2, no reward."""

class CandidateError(Exception):
    """Malformed candidate submission (bad values/columns) -> scientific FAIL, reward 0."""

def load_refs() -> dict:
    refs_path = Path(os.environ.get("TESTS", "/tests")) / "refs.json"
    try:
        raw = refs_path.read_text(encoding="utf-8")
        refs = json.loads(raw)
    except OSError as exc:
        raise InfraError(f"refs.json unreadable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise InfraError(f"refs.json corrupted: {exc}") from exc
    if not isinstance(refs, dict) or refs.get("schema") != "bench12-refs/v1":
        raise InfraError("refs.json has unexpected schema")
    return refs

def read_csv_rows(path: Path, required_columns: list[str]) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            fields = [f.strip() for f in (reader.fieldnames or [])]
            missing = [c for c in required_columns if c not in fields]
            if missing:
                raise CandidateError(f"{path.name}: missing columns {missing}; found {fields}")
            rows = []
            for raw in reader:
                rows.append({(k or "").strip(): (v or "").strip() for k, v in raw.items()})
            return rows
    except UnicodeDecodeError as exc:
        raise CandidateError(f"{path.name}: not valid UTF-8 CSV: {exc}") from exc

def to_float(text: str, where: str) -> float:
    text = (text or "").strip().replace("−", "-").replace(",", "")
    try:
        value = float(text)
    except ValueError:
        raise CandidateError(f"{where}: cannot parse number {text!r}") from None
    if not math.isfinite(value):
        raise CandidateError(f"{where}: non-finite number {text!r}")
    return value

def moments(samples: list[float]) -> tuple[float, float, float, float]:
    """ME, MAE, MAX (signed value of largest |.|), STD with ddof=0."""
    n = len(samples)
    me = sum(samples) / n
    mae = sum(abs(s) for s in samples) / n
    max_val = max(samples, key=abs)
    var = sum((s - me) ** 2 for s in samples) / n
    return me, mae, max_val, math.sqrt(var)

def stats_mismatch(claimed: dict[str, float], ref: list[float], tol: float,
                   where: str, max_sign_flexible: bool = False) -> list[str]:
    keys = ["me", "mae", "max", "std"]
    problems = []
    for key, expect in zip(keys, ref):
        got = claimed.get(key)
        if got is None:
            problems.append(f"{where}: missing {key}")
            continue
        if key == "max" and max_sign_flexible:
            # only for rows whose gold contains opposite-sign extremes within printed
            # rounding (refs.max_sign_ambiguous): the published MAX sign is ambiguous
            ok = abs(got - expect) <= tol + 1e-9 or abs(got + expect) <= tol + 1e-9
        else:
            ok = abs(got - expect) <= tol + 1e-9
        if not ok:
            problems.append(f"{where}: {key}={got} vs published {expect} (tol {tol})")
    return problems

def numbers_in(text: str) -> list[float]:
    text = text.replace("−", "-")
    out = []
    for tok in re.findall(r"-?\d+(?:\.\d+)?", text):
        try:
            out.append(float(tok))
        except ValueError:
            pass
    return out

def has_number_in_range(text: str, low: float, high: float) -> bool:
    return any(low <= v <= high for v in numbers_in(text))

def has_distinct_numbers(text: str, values: list[float], tol: float) -> list[float]:
    """Each required value must be matched by a DIFFERENT number in the text.

    Prevents a single mid-point number (e.g. '4.0' for both 3.98 and 4.03)
    from satisfying several quantitative-quote requirements at once."""
    remaining = numbers_in(text)
    missing = []
    for v in values:
        for i, n in enumerate(remaining):
            if abs(n - v) <= tol + 1e-9:
                remaining.pop(i)
                break
        else:
            missing.append(v)
    return missing

def table_cited(text: str, table_number: int) -> bool:
    """True if the table number appears standalone (not '125' standing in for '25')."""
    return re.search(rf"(?<!\d){table_number}(?!\d)", text) is not None

def norm_label(text: str) -> str:
    """Normalise an SI item label: lowercase, drop angle/dihedral markers."""
    import re as _re
    toks = [t for t in str(text).lower().replace("∠", " ").replace("η", " ").split() if t]
    return " ".join(toks)

def parse_mol(value) -> int | None:
    try:
        return int(str(value).strip().lower().lstrip("m"))
    except (TypeError, ValueError):
        return None

def check_per_item(candidate_items, gold_items, tol: float, where: str) -> list[str]:
    """Per-item authenticity gate: the candidate's per-molecule errors must carry the
    same (molecule, label) multiset as the published per-molecule table and match each
    derived error within the printed-rounding tolerance."""
    from collections import Counter
    problems: list[str] = []
    if not isinstance(candidate_items, list) or not candidate_items:
        return [f"{where}: per-item samples missing"]
    cand: Counter = Counter()
    errs: dict[tuple, list[float]] = {}
    for it in candidate_items:
        if not isinstance(it, dict):
            return [f"{where}: samples must be objects with mol/label/err"]
        mol = parse_mol(it.get("mol"))
        label = norm_label(it.get("label", ""))
        if mol is None:
            return [f"{where}: sample without a valid molecule id: {it!r}"]
        try:
            err = float(str(it.get("err", "")).replace("−", "-"))
        except ValueError:
            return [f"{where}: sample with unparsable err: {it!r}"]
        cand[(mol, label)] += 1
        errs.setdefault((mol, label), []).append(err)
    gold = Counter()
    gold_err: dict[tuple, list[float]] = {}
    for it in gold_items:
        k = (it["mol"], norm_label(it["label"]))
        gold[k] += 1
        gold_err.setdefault(k, []).append(it["err"])
    missing = gold - cand
    extra = cand - gold
    for (mol, label), n in sorted(missing.items())[:3]:
        problems.append(f"{where}: missing per-molecule item M{mol} '{label}' (x{n})")
    for (mol, label), n in sorted(extra.items())[:3]:
        problems.append(f"{where}: unknown per-molecule item M{mol} '{label}' (x{n})")
    if missing or extra:
        problems.append(f"{where}: item identity mismatch "
                        f"({sum(missing.values())} missing, {sum(extra.values())} extra "
                        f"of {sum(gold.values())} published items)")
        return problems
    bad = []
    for key in sorted(gold_err):
        cvals = sorted(errs[key])
        gvals = sorted(gold_err[key])
        if len(cvals) != len(gvals):
            problems.append(f"{where}: duplicate count mismatch for M{key[0]} '{key[1]}'")
            continue
        for cv, gv in zip(cvals, gvals):
            if abs(cv - gv) > tol + 1e-9:
                bad.append((key, cv, gv))
                break
    for (mol, label), cv, gv in bad[:3]:
        problems.append(f"{where}: M{mol} '{label}' err={cv} does not match the published "
                        f"per-molecule value {gv}")
    if bad:
        problems.append(f"{where}: {len(bad)} per-molecule errors inconsistent with SI tables")
    return problems

def check_samples(provenance: dict, sample_keys: list[str], claimed: dict[str, dict[str, float]],
                  min_n: int, moment_tol: float, labels: dict[str, str]) -> list[str]:
    """Per-molecule signed-error samples must exist and reproduce the claimed aggregates.

    This is the anti-copying gate: aggregates copied from the paper without the
    underlying per-molecule deviations fail here."""
    problems = []
    samples = provenance.get("samples")
    if not isinstance(samples, dict) or not samples:
        return ["provenance.json: 'samples' must map each statistics key to the per-molecule "
                "signed errors used to derive it"]
    for key in sample_keys:
        where = labels.get(key, key)
        arr = samples.get(key)
        if not isinstance(arr, list) or len(arr) < min_n:
            problems.append(f"{where}: per-molecule samples missing or fewer than {min_n} values")
            continue
        try:
            vals = [to_float(str(v), where) for v in arr]
        except InfraError as exc:
            problems.append(str(exc))
            continue
        me, mae, max_val, std = moments(vals)
        c = claimed[key]
        for name, got, expect in (("me", me, c["me"]), ("mae", mae, c["mae"]),
                                  ("max", max_val, c["max"]), ("std", std, c["std"])):
            if abs(got - expect) > moment_tol + 1e-9:
                problems.append(f"{where}: claimed {name}={expect} not reproduced by samples "
                                f"({name}={got:.4f}, n={len(vals)}); copied values without derivation FAIL")
                break
    return problems

def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InfraError(f"cannot read {path.name}: {exc}") from exc

def finish(report: dict) -> int:
    """Write verification.json to LOGS and return the process exit code."""
    logs = Path(os.environ.get("LOGS", "/logs/verifier"))
    logs.mkdir(parents=True, exist_ok=True)
    status = report["status"]
    report["reward"] = 1.0 if status == "PASS" else 0.0
    (logs / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for problem in report.get("problems", [])[:40]:
        print("FAIL:", problem)
    print(f"verdict: {status} ({len(report.get('checks_passed', []))} checks passed, "
          f"{len(report.get('problems', []))} problems)")
    return 0 if status == "PASS" else 1

def base_report(case_id: str) -> dict:
    return {"status": "PASS", "case_id": case_id, "checks_passed": [], "problems": []}

def guarded_main(case_id: str, run) -> int:
    """Centralised verifier entry: FAIL for candidate errors, exit 2 for infra damage."""
    app = Path(os.environ.get("APP", "/app"))
    logs = Path(os.environ.get("LOGS", "/logs/verifier"))
    try:
        report = run(app)
    except CandidateError as exc:
        report = base_report(case_id)
        report["status"] = "FAIL"
        report["problems"].append(f"malformed submission: {exc}")
    except InfraError as exc:
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "verification.json").write_text(json.dumps(
            {"status": "ENV_INVALID", "case_id": case_id, "error": str(exc)}, ensure_ascii=False),
            encoding="utf-8")
        print("ENV_INVALID:", exc)
        return 2
    except Exception as exc:  # unexpected verifier crash must not look like a scientific FAIL
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "verification.json").write_text(json.dumps(
            {"status": "ENV_INVALID", "case_id": case_id,
             "error": f"verifier crash: {exc!r}"}, ensure_ascii=False),
            encoding="utf-8")
        print("ENV_INVALID: verifier crash:", repr(exc))
        return 2
    return finish(report)

CASE_ID = "case-05-cof-efficiency-consistency-audit"
COLUMNS = ["claim_id", "recomputed", "printed", "verdict", "source"]
COFS = ["05000N2", "05001N2", "15100N2", "15101N2", "20610N2", "20611N2"]
VERDICTS = {"confirmed", "rounding-consistent", "documented-discrepancy", "not-derivable"}


def run(app: Path) -> dict:
    report = base_report(CASE_ID)
    refs = load_refs()
    final = app / "final"

    for name in ("audit.csv", "report.md", "provenance.json"):
        if not (final / name).is_file():
            report["problems"].append(f"final/{name} is missing")
    if report["problems"]:
        report["status"] = "FAIL"
        return report
    report["checks_passed"].append("L1 deliverables present")

    try:
        prov = json.loads(read_text(final / "provenance.json"))
    except json.JSONDecodeError as exc:
        raise CandidateError(f"provenance.json is not valid JSON: {exc}") from None
    if not isinstance(prov, dict):
        raise CandidateError("provenance.json must be a JSON object")

    rows = read_csv_rows(final / "audit.csv", COLUMNS)
    claims: dict[str, dict] = {}
    claim_aliases = {"t4_cycle_5of6": "t4_more_stda_cycles_count"}
    for i, row in enumerate(rows):
        where = f"audit.csv row {i + 2}"
        cid = row.get("claim_id", "").strip()
        if not cid:
            report["problems"].append(f"{where}: empty claim_id")
            continue
        canonical_cid = cid
        for public, legacy in (("timing_", "t3_"), ("workflow_", "t4_"),
                               ("energy_", "t5_"), ("structure_", "t52_")):
            if cid.startswith(public):
                canonical_cid = legacy + cid[len(public):]
                break
        canonical_cid = claim_aliases.get(canonical_cid, canonical_cid)
        if canonical_cid in claims:
            report["problems"].append(f"{where}: duplicate claim_id {cid!r}")
            continue
        claims[canonical_cid] = {
            "recomputed": to_float(row.get("recomputed", ""), f"{where}.recomputed"),
            "printed": to_float(row.get("printed", ""), f"{where}.printed"),
            "verdict": row.get("verdict", "").strip().lower(),
            "source": row.get("source", "").strip(),
        }
    if report["problems"]:
        report["status"] = "FAIL"
        return report

    def expect(claim_id: str, recomputed: float, printed: float, tol_recomp: float,
               tol_match: float, allowed_verdicts: set[str] | None = None,
               required_verdict: str | None = None, source_contains: str | None = None) -> None:
        entry = claims.get(claim_id)
        if entry is None:
            report["problems"].append(f"audit.csv: missing claim {claim_id}")
            return
        if abs(entry["recomputed"] - recomputed) > tol_recomp + 1e-9:
            report["problems"].append(
                f"{claim_id}: recomputed={entry['recomputed']} but derivation gives {recomputed}")
        if abs(entry["printed"] - printed) > tol_match + 1e-9:
            report["problems"].append(
                f"{claim_id}: printed={entry['printed']} must transcribe the published {printed}")
        if entry["verdict"] not in VERDICTS:
            report["problems"].append(
                f"{claim_id}: verdict must be one of {sorted(VERDICTS)} "
                f"(got {entry['verdict']!r})")
            return
        if required_verdict and entry["verdict"] != required_verdict:
            report["problems"].append(
                f"{claim_id}: verdict must be {required_verdict!r} (got "
                f"{entry['verdict']!r}); forcing a match or dropping the discrepancy FAILs")
        if allowed_verdicts is not None and entry["verdict"] not in allowed_verdicts:
            report["problems"].append(
                f"{claim_id}: verdict {entry['verdict']!r} not justified for this claim")
        table = re.search(r'(\d+)$', source_contains) if source_contains else None
        source_ok = (table_cited(entry['source'], int(table.group(1))) if table else
                     not source_contains or source_contains.lower() in entry['source'].lower())
        if not source_ok:
            report["problems"].append(
                f"{claim_id}: source must cite {source_contains!r} (got {entry['source']!r})")

    # Table 3: transcribe every printed component and total for all three methods.
    t3 = refs["t3_timings"]
    der = refs["t3_derived"]
    t3_methods = ("PBE0", "ADMM-PBE0", "sTDA@ADMM-PBE0")
    for column, values in t3.items():
        for index, method in enumerate(t3_methods):
            expect(f"t3_{column}_{method}", values[index], values[index], 0.5, 0.5,
                   {"confirmed"}, source_contains="Table 3")
    expect("t3_ERI_share_PBE0", der["eri_share_pct"], 31.0, 1.0, 0.5,
           {"confirmed"}, source_contains="Table 3")
    expect("t3_DERI_share_PBE0", der["deri_share_pct"], 57.0, 1.0, 0.5,
           {"confirmed"}, source_contains="Table 3")
    expect("t3_speedup_ADMM", der["speedup_admm"], 4.0, 0.3, 0.5,
           {"confirmed"}, source_contains="Table 3")
    expect("t3_speedup_sTDA", der["speedup_stda"], 8.0, 0.3, 0.5,
           {"confirmed"}, source_contains="Table 3")
    expect("t3_speedup_DERI", der["speedup_deri"], 115.0, 1.5, 0.5,
           {"confirmed"}, source_contains="Table 3")

    # Table 4 full columns: absorption times, ES-optimization times/steps (all printed)
    for cof in refs["t4_cofs"]:
        cid = cof["id"]
        for col in ("abs_admm", "abs_stda", "opt_admm", "opt_admm_step",
                    "opt_stda", "opt_stda_step"):
            expect(f"t4_{col}_{cid}", cof[col], cof[col], 0.001, 0.001,
                   {"confirmed"}, source_contains="Table 4")

    # Table 4 derived: per-step speed-up range and the sTDA spectrum-time maximum
    ratios = [c["opt_admm_step"] / c["opt_stda_step"] for c in refs["t4_cofs"]]
    expect("t4_perstep_speedup_min", round(min(ratios), 2), 1.4, 0.05, 0.05,
           {"confirmed"}, source_contains="Table 4")
    expect("t4_perstep_speedup_max", round(max(ratios), 2), 5.0, 0.1, 0.1,
           {"confirmed"}, source_contains="Table 4")
    expect("t4_abs_stda_max_min", round(max(c["abs_stda"] for c in refs["t4_cofs"]) / 60, 1),
           44.0, 0.5, 0.5, {"confirmed"}, source_contains="Table 4")

    # Table 4 cycles and the 15100N2 exception
    n_more = 0
    exception_ids = []
    for cof in refs["t4_cofs"]:
        cid = cof["id"]
        admm_cycles = cof["opt_admm"] / cof["opt_admm_step"]
        stda_cycles = cof["opt_stda"] / cof["opt_stda_step"]
        if stda_cycles > admm_cycles:
            n_more += 1
        else:
            exception_ids.append(cid)
        expect(f"t4_cycles_{cid}_ADMM", round(admm_cycles, 0), round(admm_cycles, 0),
               1.5, 1.5, {"confirmed"}, source_contains="Table 4")
        expect(f"t4_cycles_{cid}_sTDA", round(stda_cycles, 0), round(stda_cycles, 0),
               1.5, 1.5, {"confirmed"}, source_contains="Table 4")
    aggregate_claim = claims.get("t4_more_stda_cycles_count")
    if aggregate_claim is None:
        report["problems"].append("audit.csv: missing claim t4_more_stda_cycles_count")
    else:
        entry = aggregate_claim
        if abs(entry["recomputed"] - n_more) > 0.01 or abs(entry["printed"] - n_more) > 0.01:
            report["problems"].append(
                f"t4_more_stda_cycles_count: recomputed/printed must encode the derived count "
                "(got "
                f"{entry['recomputed']}/{entry['printed']})")
        elif entry["verdict"] not in {"confirmed", "rounding-consistent"}:
            report["problems"].append(
                f"t4_more_stda_cycles_count: verdict {entry['verdict']!r} is not justified")
        if not table_cited(entry["source"], 4):
            report["problems"].append(
                "t4_more_stda_cycles_count: source must cite Table 4")
        omitted_ids = [cof_id for cof_id in exception_ids if cof_id not in entry["source"]]
        if omitted_ids:
            report["problems"].append(
                "t4_more_stda_cycles_count: source must identify the exception COF ID(s) "
                "derived from the Table 4 cycle comparisons")

    # Table 5 Stokes shifts and MAE row
    for cof, row in refs["t5"]["rows"].items():
        for kernel in ("ADMM", "sTDA"):
            printed_stokes = row["stokes"][kernel]
            recomputed_stokes = row["Evert"][kernel] - row["Efl"][kernel]
            ok = {"confirmed"} if abs(recomputed_stokes - printed_stokes) <= 0.005 + 1e-9 \
                else {"rounding-consistent"}
            expect(f"t5_stokes_{cof}_{kernel}", recomputed_stokes, printed_stokes,
                   0.005, 0.0, ok, source_contains="Table 5")
    mae = refs["t5_recomputed_mae"]
    mae_row = refs["t5"]["mae_row"]
    expect("t5_MAE_Evert", mae["Evert"], mae_row["Evert"], 0.02, 0.005,
           {"confirmed"}, source_contains="Table 5")
    expect("t5_MAE_Ead", mae["Ead"], mae_row["Ead"], 0.02, 0.005,
           None, required_verdict="documented-discrepancy", source_contains="Table 5")
    expect("t5_MAE_Efl", mae["Efl"], mae_row["Efl"], 0.02, 0.005,
           {"confirmed"}, source_contains="Table 5")
    expect("t5_MAE_stokes", mae["stokes"], mae_row["stokes"], 0.02, 0.005,
           {"confirmed"}, source_contains="Table 5")

    # SI table 52 bookkeeping
    for cid in COFS:
        book = refs["t52_bookkeeping"][cid]
        expect(f"t52_atoms_{cid}", book["atoms"], book["atoms"], 0.001, 0.001,
               {"confirmed"}, source_contains="52")
        expect(f"t52_basis_{cid}", book["basis"], book["basis"], 0.001, 0.001,
               {"confirmed"}, source_contains="52")

    if report["problems"]:
        report["status"] = "FAIL"
        return report
    report["checks_passed"].append("L3 timing, Table 4 full columns, cycles, Stokes/MAE and "
                                   f"bookkeeping claims audited ({len(claims)} claim rows)")

    md = read_text(final / "report.md")
    md_low = md.lower()
    ead_mae = claims.get("t5_MAE_Ead")
    if ead_mae is None:
        report["problems"].append("audit.csv: missing t5_MAE_Ead needed for report comparison")
        report["status"] = "FAIL"
        return report
    report_values = ((ead_mae["recomputed"], 0.03), (ead_mae["printed"], 0.02))
    missing_values = [value for value, tol in report_values
                      if not has_number_in_range(md_low, value - tol, value + tol)]
    has_submitted_values = not missing_values
    if "documented-discrepancy" not in md_low and not has_submitted_values:
        report["problems"].append("report.md: explain the Ead MAE difference using the "
                                  "audit result or the submitted recomputed/printed values")
        report["status"] = "FAIL"
        return report
    if not (("定性" in md or "qualitative" in md_low) and (re.search(r"\bspectr(?:um|a|al)\b", md_low) or "谱" in md)):
        report["problems"].append("report.md: the spectral-shape comparison must be labelled "
                                  "qualitative / not numerically auditable")
        report["status"] = "FAIL"
        return report
    report["checks_passed"].append("L3 Ead discrepancy and qualitative-spectrum boundary "
                                   "reported")
    return report


def main() -> int:
    return guarded_main(CASE_ID, run)


if __name__ == "__main__":
    raise SystemExit(main())
