#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Recompute ADMM Errors in Adiabatic Excitation and Fluorescence Energies.
"""Case 03 verifier: recomputed ADMM Ead/Efl statistics vs SI tables 45/50,
verify-only kernel rows vs SI tables 46/51, abstract-claim check.

Frozen criteria with per-item authenticity gate:
- recomputed_admm_energy_statistics_match_published: 18 aggregates (Ead/Efl x 9
  ABS/PBS combos) within +/-0.02 eV of SI tables 45/50; per-molecule samples must
  match SI tables 42/43/47/48 item-for-item (molecule id + derived error).
- kernel_statistics_verified_with_explicit_boundary: SI table 46 rows cite the
  EOM-CCSD reference, SI table 51 rows cite the Turbomole reference; claiming
  recomputation or mixing references FAILs.
- abstract_claim_checked_numerically: MAE 0.02-0.04 eV claim evaluated against
  the recomputed tzp/tz2p MAEs; vertical excitations declared out of scope.
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

CASE_ID = "case-03-adiabatic-fluorescence-recomputation"
COLUMNS = ["row_type", "quantity", "pbs", "abs", "method", "me", "mae", "max", "std",
           "source_table", "reference"]
COMBOS = [("DZVP", "dzp"), ("TZVP", "dzp"), ("TZV2P", "dzp"), ("cc-GRB-D", "dzp"),
          ("TZVP", "tzp"), ("TZV2P", "tzp"), ("cc-GRB-T", "tzp"),
          ("TZV2P", "tz2p"), ("cc-GRB-Q", "tz2p")]
EAD_KERNEL_ROWS = ["PBE0|DZVP", "PBE0|TZVP", "PBE0|TZV2P", "ADMM|TZVP+tzp",
                   "ADMM|TZV2P+tzp", "sTDA@PBE0|TZVP", "sTDA@ADMM|TZVP+tzp"]
EFL_KERNEL_ROWS = ["PBE0|DZVP", "PBE0|TZVP", "PBE0|TZV2P", "ADMM|DZVP+dzp", "ADMM|TZVP+dzp",
                   "ADMM|TZV2P+dzp", "ADMM|TZVP+tzp", "ADMM|TZV2P+tzp", "ADMM|TZV2P+tz2p",
                   "sTDA@PBE0|TZVP", "sTDA@ADMM|TZVP+tzp"]
# Instruction uses ADMM-PBE0 / sTDA@ADMM-PBE0; older SI shorthand omits -PBE0.
METHOD_ALIASES = {
    "ADMM-PBE0": "ADMM",
    "sTDA@ADMM-PBE0": "sTDA@ADMM",
}
STATS_TOL, TRANS_TOL = 0.02, 0.001
STDA_TRANS_TOL = 0.005


def normalize_method(method: str) -> str:
    method = (method or "").strip()
    return METHOD_ALIASES.get(method, method)


def sample_items(value):
    """Accept a bare sample list or an object that wraps the list plus provenance."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("items", "samples", "errors", "per_molecule", "values"):
            arr = value.get(key)
            if isinstance(arr, list):
                return arr
        lists = [v for v in value.values() if isinstance(v, list)]
        if len(lists) == 1:
            return lists[0]
    return None


def run(app: Path) -> dict:
    report = base_report(CASE_ID)
    refs = load_refs()
    final = app / "final"

    for name in ("statistics.csv", "report.md", "provenance.json"):
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

    rows = read_csv_rows(final / "statistics.csv", COLUMNS)
    if not rows:
        report["problems"].append("final/statistics.csv has no data rows")
        report["status"] = "FAIL"
        return report

    recomputed: dict[str, dict] = {}
    verified: dict[str, dict] = {}
    for i, row in enumerate(rows):
        where = f"statistics.csv row {i + 2}"
        row_type = row.get("row_type", "").strip().lower()
        quantity = row.get("quantity", "").strip().upper()
        if row_type == "recomputed-from-raw":
            if quantity not in ("EAD", "EFL"):
                report["problems"].append(f"{where}: bad quantity {quantity!r}")
                continue
            pbs, abs_ = row.get("pbs", "").strip(), row.get("abs", "").strip().lower()
            if (pbs, abs_) not in COMBOS:
                report["problems"].append(f"{where}: bad ABS/PBS combo {abs_}/{pbs}")
                continue
            key = f"{quantity}|{abs_}|{pbs}"
            if key in recomputed:
                report["problems"].append(f"{where}: duplicate {key}")
                continue
            recomputed[key] = {
                "stats": {k: to_float(row.get(k, ""), f"{where}.{k}")
                          for k in ("me", "mae", "max", "std")},
                "source": row.get("source_table", ""),
                "reference": row.get("reference", ""),
            }
        elif row_type == "verified-against-si":
            if quantity not in ("EAD", "EFL"):
                report["problems"].append(f"{where}: bad quantity {quantity!r}")
                continue
            method = normalize_method(row.get("method", ""))
            key = f"{quantity}|{method}|{row.get('abs', '').strip()}"
            if key in verified:
                report["problems"].append(f"{where}: duplicate {key}")
                continue
            verified[key] = {
                "me": to_float(row.get("me", ""), f"{where}.me"),
                "mae": to_float(row.get("mae", ""), f"{where}.mae"),
                "max": to_float(row.get("max", ""), f"{where}.max"),
                "std": to_float(row.get("std", ""), f"{where}.std"),
                "source": row.get("source_table", ""),
                "reference": row.get("reference", ""),
            }
        else:
            report["problems"].append(f"{where}: row_type must be recomputed-from-raw or "
                                      f"verified-against-SI, got {row_type!r}")
    if report["problems"]:
        report["status"] = "FAIL"
        return report

    expected_recomputed = {f"{q}|{a}|{p}" for q, table in (("EAD", "admm_ead_stats"),
                                                           ("EFL", "admm_efl_stats"))
                           for (p, a) in COMBOS}
    missing = expected_recomputed - set(recomputed)
    if missing:
        report["problems"].append(f"statistics.csv: missing {len(missing)} recomputed entries, "
                                  f"e.g. {sorted(missing)[:3]}")
    if report["problems"]:
        report["status"] = "FAIL"
        return report
    report["checks_passed"].append(f"L1 all {len(expected_recomputed)} recomputed entries present")

    # L2: per-item authenticity against SI tables 42/43 (Ead) and 47/48 (Efl)
    per_item = refs.get("per_item", {})
    if not per_item:
        raise InfraError("refs.json lacks per-item gold")
    item_tol = refs.get("per_item_tol", 0.006)
    max_sign_ambiguous = set(refs.get("max_sign_ambiguous", []))
    samples = prov.get("samples")
    if not isinstance(samples, dict):
        report["problems"].append("provenance.json: 'samples' must map each recomputed key "
                                  "to its identified per-molecule items ({mol, err})")
        report["status"] = "FAIL"
        return report
    for key in sorted(expected_recomputed):
        gold = per_item.get(key)
        if gold is None:
            raise InfraError(f"refs.json lacks per-item gold for {key}")
        items = sample_items(samples.get(key))
        report["problems"].extend(check_per_item(items, gold, item_tol,
                                                 f"samples[{key}]"))
        if report["problems"]:
            report["status"] = "FAIL"
            return report
        item_errs = [to_float(str(it.get("err", "")), key) for it in items]
        me, mae, mx, std = moments(item_errs)
        c = recomputed[key]["stats"]
        for name, got, expect in (("me", me, c["me"]), ("mae", mae, c["mae"]),
                                  ("max", mx, c["max"]), ("std", std, c["std"])):
            flexible = name == "max" and key in max_sign_ambiguous
            ok = (abs(got - expect) <= 0.02 + 1e-9
                  or (flexible and abs(got + expect) <= 0.02 + 1e-9))
            if not ok:
                report["problems"].append(
                    f"samples[{key}]: claimed {name}={expect} not reproduced by the items "
                    f"({name}={got:.4f})")
    if report["problems"]:
        report["status"] = "FAIL"
        return report
    n_items = sum(len(v) for v in per_item.values())
    report["checks_passed"].append(f"L2 per-molecule energies match SI tables 42/43/47/48 "
                                   f"item-for-item ({n_items} gold items) and reproduce the "
                                   f"claimed aggregates")

    # L3: recomputed ADMM aggregates vs SI 45/50
    for key in sorted(expected_recomputed):
        quantity, abs_, pbs = key.split("|")
        table = "admm_ead_stats" if quantity == "EAD" else "admm_efl_stats"
        si_table = "45" if quantity == "EAD" else "50"
        report["problems"].extend(stats_mismatch(
            recomputed[key]["stats"], refs[table][f"{abs_}|{pbs}"], STATS_TOL,
            f"statistics.csv {key}", max_sign_flexible=key in max_sign_ambiguous))
        if si_table not in recomputed[key]["source"]:
            report["problems"].append(f"statistics.csv {key}: source_table must cite SI table "
                                      f"{si_table} (got {recomputed[key]['source']!r})")
        if "pbe0" not in recomputed[key]["reference"].lower():
            report["problems"].append(f"statistics.csv {key}: recomputed rows are ADMM vs "
                                      "conventional PBE0 (same primary basis); reference "
                                      f"column reads {recomputed[key]['reference']!r}")
    if report["problems"]:
        report["status"] = "FAIL"
        return report
    report["checks_passed"].append(f"L3 18 recomputed ADMM aggregates match SI 45/50 within "
                                   f"+-{STATS_TOL}")

    # verify-only kernel rows vs SI 46/51 with reference-system labels
    for quantity, rows_expected, si_table, ref_keyword in (
            ("EAD", EAD_KERNEL_ROWS, "46", "eom-ccsd"),
            ("EFL", EFL_KERNEL_ROWS, "51", "turbomole")):
        for row_key in rows_expected:
            key = f"{quantity}|{row_key}"
            if key not in verified:
                report["problems"].append(f"statistics.csv: missing verify-only row "
                                          f"{quantity} {row_key}")
                continue
            entry = verified[key]
            method, basis = row_key.split("|")
            expect = refs["kernel_ead_verify_only" if quantity == "EAD" else
                          "kernel_efl_verify_only"][f"{method}|{basis}"]
            tol = STDA_TRANS_TOL if method.startswith("sTDA") else TRANS_TOL
            for stat, e in zip(("me", "mae", "max", "std"), expect):
                if abs(entry[stat] - e) > tol + 1e-9:
                    report["problems"].append(f"statistics.csv {key}: {stat}={entry[stat]} "
                                              f"does not transcribe SI table {si_table} value {e}")
            if not re.search(rf"(?<!\d){si_table}(?!\d)", entry["source"]):
                report["problems"].append(f"statistics.csv {key}: source must cite SI table "
                                          f"{si_table} (got {entry['source']!r})")
            if ref_keyword not in entry["reference"].lower():
                report["problems"].append(
                    f"statistics.csv {key}: reference must state "
                    f"{'EOM-CCSD' if quantity == 'EAD' else 'PBE0/def2-QZVPP/Turbomole'} "
                    f"(got {entry['reference']!r}); mixing reference systems FAILs")
    if report["problems"]:
        report["status"] = "FAIL"
        return report
    report["checks_passed"].append("L3 kernel rows transcribed with EOM-CCSD (Ead) / "
                                   "Turbomole (Efl) references kept apart")

    md = read_text(final / "report.md")
    md_low = md.lower()
    if not (has_number_in_range(md_low, 0.015, 0.025) and has_number_in_range(md_low, 0.035, 0.045)):
        report["problems"].append("report.md: the abstract-claim check must quote the "
                                  "0.02 and 0.04 eV MAE bounds numerically")
        report["status"] = "FAIL"
        return report
    if not (("垂直" in md or "vertical" in md_low)
            and re.search(r"(未刊|未重刊|范围之外|不属于本题|not published|out of scope|"
                          r"unpublished|not included|cannot be recomputed|not reproducible)", md_low)):
        report["problems"].append("report.md: must state explicitly that vertical excitation "
                                  "energies are outside this case (per-molecule values not "
                                  "published)")
        report["status"] = "FAIL"
        return report
    report["checks_passed"].append("L3 abstract claim checked; verify-only boundary stated")
    return report


def main() -> int:
    return guarded_main(CASE_ID, run)


if __name__ == "__main__":
    raise SystemExit(main())
