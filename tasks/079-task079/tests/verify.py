#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Reconcile Vertical-Excitation Statistics and Assess Basis Limits.
"""Case 04 verifier: main Table 1/2 Evert entries reconciled with SI tables 25/27,
double-zeta insufficiency and reference-conditioned sTDA verdicts.

Frozen criteria:
- main_table_evert_entries_reconciled_with_si: 12 reconciliation rows; printed
  values transcribed, SI values transcribed, rounding agreement computed.
- double_zeta_insufficiency_verdict: report quotes the table 22/24 and 28/29 MEs.
- reference_conditioned_admm_stda_conclusions: report quotes sTDA MEs from
  tables 22/24 (CP2K reference) and 28/29 (Turbomole reference) with conditions.
No per-molecule samples exist for vertical excitations (values not published);
verdicts rest on the published statistics only.
"""
from __future__ import annotations

import json
import os
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

CASE_ID = "case-04-vertical-excitation-basis-verdict"
COLUMNS = ["entry", "printed_me", "printed_mae", "si_table", "si_me", "si_mae", "match"]
T1_COMBOS = [("dzp", "DZVP"), ("dzp", "TZVP"), ("dzp", "TZV2P"),
             ("tzp", "TZVP"), ("tzp", "TZV2P"), ("tz2p", "TZV2P")]
T1_TO_T27 = {"PBE0|DZVP": "PBE0|DZVP", "PBE0|TZVP": "PBE0|TZVP", "PBE0|TZV2P": "PBE0|TZV2P",
             "ADMM-PBE0|TZVP+tzp": "ADMM|TZVP+tzp", "sTDA@PBE0|TZVP": "sTDA@PBE0|TZVP",
             "sTDA@ADMM-PBE0|TZVP+tzp": "sTDA@ADMM|TZVP+tzp"}
T2_METHODS = list(T1_TO_T27)
ROUND_TOL, TRANS_TOL = 0.011, 0.005


def run(app: Path) -> dict:
    report = base_report(CASE_ID)
    refs = load_refs()
    final = app / "final"

    for name in ("reconciliation.csv", "report.md", "provenance.json"):
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

    rows = read_csv_rows(final / "reconciliation.csv", COLUMNS)
    if not rows:
        report["problems"].append("final/reconciliation.csv has no data rows")
        report["status"] = "FAIL"
        return report

    entries: dict[str, dict] = {}
    for i, row in enumerate(rows):
        where = f"reconciliation.csv row {i + 2}"
        entry = row.get("entry", "").strip()
        for public, legacy in (("admm|", "main-T1|"), ("kernel|", "main-T2|")):
            if entry.startswith(public):
                entry = legacy + entry[len(public):]
                break
        if entry in entries:
            report["problems"].append(f"{where}: duplicate entry {entry!r}")
            continue
        entries[entry] = {
            "printed_me": to_float(row.get("printed_me", ""), f"{where}.printed_me"),
            "printed_mae": to_float(row.get("printed_mae", ""), f"{where}.printed_mae"),
            "si_table": row.get("si_table", "").strip(),
            "si_me": to_float(row.get("si_me", ""), f"{where}.si_me"),
            "si_mae": to_float(row.get("si_mae", ""), f"{where}.si_mae"),
            "match": row.get("match", "").strip().lower(),
        }
    if report["problems"]:
        report["status"] = "FAIL"
        return report

    ok_verdicts = {"consistent", "rounding-consistent"}

    # main Table 1 Evert (printed 3 dp) vs SI table 25 (2 dp)
    for abs_, pbs in T1_COMBOS:
        entry_id = f"main-T1|{abs_}/{pbs}"
        entry = entries.get(entry_id)
        if entry is None:
            report["problems"].append(f"reconciliation.csv: missing entry {entry_id}")
            continue
        printed = refs["main_t1_evert"][f"{abs_}|{pbs}"]
        si = refs["si_t25"][f"{abs_}|{pbs}"]
        if abs(entry["printed_me"] - printed[0]) > TRANS_TOL + 1e-9 or \
           abs(entry["printed_mae"] - printed[1]) > TRANS_TOL + 1e-9:
            report["problems"].append(f"{entry_id}: printed ME/MAE must transcribe main table 1 "
                                      f"({printed[0]}/{printed[1]})")
        if abs(entry["si_me"] - si[0]) > TRANS_TOL + 1e-9 or \
           abs(entry["si_mae"] - si[1]) > TRANS_TOL + 1e-9:
            report["problems"].append(f"{entry_id}: si_me/si_mae must transcribe SI table 25 "
                                      f"({si[0]}/{si[1]})")
        if not table_cited(entry["si_table"], 25):
            report["problems"].append(f"{entry_id}: si_table must cite 25 (got "
                                      f"{entry['si_table']!r})")
        if not (abs(entry["printed_me"] - entry["si_me"]) <= ROUND_TOL + 1e-9
                and abs(entry["printed_mae"] - entry["si_mae"]) <= ROUND_TOL + 1e-9):
            report["problems"].append(f"{entry_id}: printed and SI values disagree beyond the "
                                      "rounding bound; mapping error FAILs")
        elif entry["match"] not in ok_verdicts:
            report["problems"].append(f"{entry_id}: match column must record agreement "
                                      f"(got {entry['match']!r})")

    # main Table 2 Evert (printed 2 dp) vs SI table 27 (2 dp)
    for method in T2_METHODS:
        entry_id = f"main-T2|{method.replace('|', '/')}"
        entry = entries.get(entry_id)
        if entry is None:
            report["problems"].append(f"reconciliation.csv: missing entry {entry_id}")
            continue
        printed = refs["main_t2_evert"][method]
        si = refs["si_t27"][T1_TO_T27[method]]
        if abs(entry["printed_me"] - printed[0]) > TRANS_TOL + 1e-9 or \
           abs(entry["printed_mae"] - printed[1]) > TRANS_TOL + 1e-9:
            report["problems"].append(f"{entry_id}: printed ME/MAE must transcribe main table 2 "
                                      f"({printed[0]}/{printed[1]})")
        if abs(entry["si_me"] - si[0]) > TRANS_TOL + 1e-9 or \
           abs(entry["si_mae"] - si[1]) > TRANS_TOL + 1e-9:
            report["problems"].append(f"{entry_id}: si_me/si_mae must transcribe SI table 27 "
                                      f"({si[0]}/{si[1]})")
        if not table_cited(entry["si_table"], 27):
            report["problems"].append(f"{entry_id}: si_table must cite 27 (got "
                                      f"{entry['si_table']!r})")
        if not (abs(entry["printed_me"] - entry["si_me"]) <= ROUND_TOL + 1e-9
                and abs(entry["printed_mae"] - entry["si_mae"]) <= ROUND_TOL + 1e-9):
            report["problems"].append(f"{entry_id}: printed and SI values disagree beyond the "
                                      "rounding bound; mapping error FAILs")
        elif entry["match"] not in ok_verdicts:
            report["problems"].append(f"{entry_id}: match column must record agreement "
                                      f"(got {entry['match']!r})")
    if report["problems"]:
        report["status"] = "FAIL"
        return report
    report["checks_passed"].append("L3 12 Evert entries reconciled: main T1->SI 25, "
                                   "main T2->SI 27")

    md = read_text(final / "report.md")
    md_low = md.lower()
    dz_mes = [refs["double_zeta"][k][0] for k in
              ("T22_PBE0_DZVP", "T24_PBE0_DZVP", "T28_PBE0_DZVP", "T29_PBE0_DZVP")]
    stda_mes = [refs["stda_reference_conditioned"][k][0] for k in
                ("T22_sTDA@ADMM", "T24_sTDA@ADMM", "T28_sTDA@ADMM", "T29_sTDA@ADMM")]
    missing_numbers = has_distinct_numbers(md_low, dz_mes + stda_mes, 0.03)
    if missing_numbers:
        report["problems"].append(
            "report.md: verdicts must quote the double-zeta MEs (tables 22/24, 28/29) and the "
            f"sTDA@ADMM MEs with both references; missing near {missing_numbers}")
        report["status"] = "FAIL"
        return report
    if "cp2k" not in md_low or "turbomole" not in md_low:
        report["problems"].append("report.md: sTDA/ADMM conclusions must state the reference "
                                  "system (CP2K vs Turbomole) and geometry variant")
        report["status"] = "FAIL"
        return report
    report["checks_passed"].append("L3 double-zeta insufficiency and reference-conditioned "
                                   "sTDA verdicts supported")
    return report


def main() -> int:
    return guarded_main(CASE_ID, run)


if __name__ == "__main__":
    raise SystemExit(main())
