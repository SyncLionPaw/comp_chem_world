# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Compare catalytic geometry across assembly and ligand/protonation conditions.
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


import csv
import os


class CandidateFail(ValueError):
    pass


class EnvironmentInvalid(RuntimeError):
    pass


INPUT_SHA256 = {
    "README_residue_numbering": "a1488c55ef353c6ae82a2f9d77c35a6dfc9929ac70a65081f098acb4156ea230",
    "corrmat_c0_WT.dat": "be3202d7235606d7e212b6baac5a26bc26a38c2c9a809a359f054bac28cf7bb0",
    "distmat_c0_WT.dat": "63d6042457f7fcc811fd24fb0cb2a2ac18185cc85bfdb28ed3831b42e6be2686",
    "corrmat_c0_V72I.dat": "881b191e61b3807565c83125ddcbb9d03840a855885582d3a732318128c3cd05",
    "distmat_c0_V72I.dat": "3f0f76ec7bb044b55783151835833341b2ca3d418cb1d9e388862cffc62a8b65",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def public_root(path: str, expected: dict[str, str]) -> dict[str, Path]:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise EnvironmentInvalid("public input root is absent or redirected")
    result: dict[str, Path] = {}
    for name, digest in expected.items():
        file = root / name
        if file.is_symlink() or not file.is_file():
            raise EnvironmentInvalid(f"required public input is absent or redirected: {name}")
        if sha256_file(file) != digest:
            raise EnvironmentInvalid(f"public input SHA-256 mismatch: {name}")
        result[name] = file
    return result


def real_output_dir(app: str) -> Path:
    root = Path(app)
    final = root / "final"
    if root.is_symlink() or not root.is_dir() or final.is_symlink() or not final.is_dir():
        raise CandidateFail("APP/final must be a real directory")
    return final


def require_files(final: Path, names: tuple[str, ...]) -> dict[str, Path]:
    result = {}
    for name in names:
        path = final / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise CandidateFail(f"required final deliverable is missing, empty, or redirected: {name}")
        result[name] = path
    return result


def read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
                raise CandidateFail(f"{path.name} is missing required columns: {sorted(required)}")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise CandidateFail(f"cannot parse {path.name}: {exc}") from exc
    if not rows:
        raise CandidateFail(f"{path.name} has no data rows")
    return rows


def finite_number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateFail(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise CandidateFail(f"{label} must be finite")
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateFail(f"cannot parse {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateFail(f"{path.name} must contain a JSON object")
    return value


def emit(logs: str, case_id: str, status: str, message: str, details: dict[str, Any] | None = None) -> int:
    root = Path(logs)
    root.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"case_id": case_id, "status": status, "message": message}
    if details:
        report["details"] = details
    if status in {"PASS", "FAIL"}:
        report["reward"] = 1.0 if status == "PASS" else 0.0
        (root / "reward.txt").write_text(f"{report['reward']:g}\n", encoding="ascii")
    else:
        (root / "reward.txt").unlink(missing_ok=True)
    (root / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return {"PASS": 0, "REVIEW_REQUIRED": 0, "FAIL": 1, "ENV_INVALID": 2}.get(status, 2)

"""Text-level compatibility checks for case04's uncertainty contract."""

import re


INFERENTIAL_MARKERS = (
    "confidence intervals?", "bootstrap", "p[- ]values?", "t[- ]tests?", "mann-whitney",
    "mann whitney", "wilcoxon", "anova", "permutation tests?", "hypothesis tests?",
    "inferential tests?", "significance tests?", "statistical significance",
    "置信区间", "假设检验", "推断检验", "显著性检验",
)
_MARKER_RE = re.compile("|".join(f"(?:{item})" for item in INFERENTIAL_MARKERS), re.IGNORECASE)
_METHOD_SPLIT_RE = re.compile(r"[.;\n]|\bbut\b|\bhowever\b|\bwhereas\b|\bwhile\b|但|但是|然而")
# Finite verbs that turn a negated list into a positive assertion when they sit between the
# negator and an inferential term.
_CLAUSE_VERB_RE = re.compile(
    r"(?:^|[\s,])(?:is|are|was|were|be|been|being|has|have|had|report|reports|reported|"
    r"use|uses|used|using|perform|performs|performed|apply|applies|applied|compute|computes|"
    r"computed|calculat(?:e|es|ed)|assum(?:e|es|ed)|deriv(?:e|es|ed)|infer(?:s|red)?|"
    r"conduct(?:s|ed)?|run|runs|ran|estimat(?:e|es|ed)|claim(?:s|ed)?|test(?:s|ed)?|"
    r"implement(?:s|ed)?|adopt(?:s|ed)?|obtain(?:s|ed)?|give|gives|gave)\b",
    re.IGNORECASE,
)


def normalize_limitations(value: object) -> list[str] | None:
    """Normalize the public contract's prose or list representation."""
    if isinstance(value, str):
        return [value] if value.strip() else None
    if isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value):
        return value if value else None
    return None


def discloses_absent_replica_labels(items: list[str]) -> bool:
    patterns = (
        r"\bno (?:independent[- ]?)?replica(?:te)? (?:labels?|ids?|identifiers?)\b",
        r"\b(?:without|lacking|missing|absent|lack of|absence of) (?:any )?(?:independent[- ]?)?replica(?:te)? (?:labels?|ids?|identifiers?)\b",
        r"\b(?:independent[- ]?)?replica(?:te)? (?:labels?|ids?|identifiers?) (?:are |is )?(?:absent|missing|unavailable|not provided|not available|not supplied)\b",
        r"(?:没有|無|无|缺少|缺乏|未提供|不存在).{0,16}(?:独立)?(?:重复|副本)(?:标签|编号|标识|識別碼)",
        r"(?:独立)?(?:重复|副本)(?:标签|编号|标识|識別碼).{0,16}(?:缺失|缺少|不存在|未提供|不可用)",
    )
    for item in items:
        text = re.sub(r"[_-]+", " ", item.casefold()).strip()
        if any(re.search(pattern, text) for pattern in patterns):
            return True
    return False


def discloses_absent_time_axis(items: list[str]) -> bool:
    patterns = (
        r"\bno (?:time )?axis\b",
        r"\b(?:without|lacking|missing|absent|lack of|absence of) (?:a )?(?:time )?axis\b",
        r"\b(?:time )?axis (?:is |was )?(?:absent|missing|unavailable|not provided|not available|not supplied)\b",
        r"\bno (?:time )?(?:index|indices|timestamps?|temporal ordering)\b",
        r"(?:没有|無|无|缺少|缺乏|未提供|不存在).{0,16}(?:时间轴|時間軸|时间索引|时间戳|時間戳)",
        r"(?:时间轴|時間軸|时间索引|时间戳|時間戳).{0,16}(?:缺失|缺少|不存在|未提供|不可用)",
    )
    for item in items:
        text = re.sub(r"[_-]+", " ", item.casefold()).strip()
        if any(re.search(pattern, text) for pattern in patterns):
            return True
    return False


def _explicitly_negates_mention(clause: str, start: int, end: int) -> bool:
    before = clause[max(0, start - 100):start]
    after = clause[end:end + 48]
    # Negation immediately governing the method name or an explicit non-use verb.
    direct_before = re.search(
        r"(?:\bno\b|\bwithout\b|\bnever\b|\bnot\b|\bavoid(?:ed)?\b|"
        r"\bexclude[ds]?\b|\black(?:s|ing)?\b|\b(?:do|did|does) not\b)"
        r"(?:\s+(?:any|a|an|the|formal|inferential|statistical|independent|using|use|"
        r"perform|conduct|apply|report|calculate|estimate|claim))*\s*$",
        before,
    ) or re.search(
        r"(?:未|不|無|没有|沒|并未|並未|不得|避免)"
        r"(?:使用|采用|採用|进行|進行|做|计算|計算|报告|報告|开展|開展)?\s*$",
        before,
    )
    direct_after = re.match(
        r"\s*(?:(?:is|are|was|were|has been|have been|had been|will be|would be)\s+)?"
        r"(?:not|never)\s+(?:used|applied|performed|conducted|calculated|estimated|"
        r"reported|claimed|run|carried out)\b|"
        r"\s*(?:未|不|無|没有|沒|并未|並未|不得|避免)"
        r"(?:使用|采用|採用|进行|進行|计算|計算|报告|報告|开展|開展)",
        after,
    )
    if direct_before or direct_after:
        return True

    # A leading “no X or Y” may negate a short coordinated list. Permit only a list of
    # inferential terms and conjunctions between the negator and this term; extra prose
    # means the scope is ambiguous and the mention remains reviewable.
    scope_patterns = (
        r"\bno\s+(.{0,90})$",
        r"\b(?:do|did|does) not\s+(?:use|perform|conduct|apply|report|calculate|estimate|claim)\s+(.{0,90})$",
        r"(?:不|未|無|没有|沒|并未|並未|不得|避免)"
        r"(?:使用|采用|採用|进行|進行|做|计算|計算|报告|報告|开展|開展)\s*(.{0,90})$",
    )
    for scope_pattern in scope_patterns:
        scope = re.search(scope_pattern, before)
        if scope and _MARKER_RE.search(scope.group(1)):
            remainder = _MARKER_RE.sub(" ", scope.group(1))
            if re.fullmatch(r"[\s,;]*(?:(?:and|or|或|和|及|与|、)\s*[,;]?\s*)*", remainder, re.IGNORECASE):
                return True

    # A negator may also scope over a coordinated list of nouns, e.g. "not standard errors or
    # confidence intervals" or "no hypothesis tests, p-values, confidence intervals". Accept
    # that only when no finite verb sits between the negator and this mention, so a positive
    # statement joined by "and" ("we did not assume normality and report confidence intervals")
    # is still treated as a positive mention.
    list_scope = re.search(
        r"(?:\bno\b|\bnot\b|\bwithout\b|\bnever\b|\bnor\b|(?:do|did|does) not)\s+([^.;:]{0,120})$",
        before,
    )
    if list_scope and not _CLAUSE_VERB_RE.search(list_scope.group(1)):
        return True
    return False


def has_positive_inferential_claim(methods: list[str]) -> bool:
    """Return true for inferential terms without a narrow, explicit non-use statement."""
    for method in methods:
        text = method.casefold().replace("p-value", "p value").replace("t-test", "t test")
        for clause in _METHOD_SPLIT_RE.split(text):
            for match in _MARKER_RE.finditer(clause):
                if not _explicitly_negates_mention(clause, match.start(), match.end()):
                    return True
    return False


CASE = "case-04-post-hydrolysis"
INPUT_SHA256 = {
    "Fig_9a.dat": "d93d82e552543086f17e8392eccf0641845b1287a6eec9c521ad1197f92e07ac",
    "data_dictionary.md": "8aa2908aed5396968041001cb603e1380fd564ca6047057f8386ab71767664ee",
}
REFERENCE_SHA256 = "9aa402270ed8528db6da02b4e521d0ef26612414e74856175ab169f8e47a937d"
PANELS = {
    ("S", "WT"): (0, 1),
    ("D-AspAsh", "WT"): (2, 3),
    ("D-ADP-Pi", "WT"): (4, 5),
    ("S", "V72I"): (6, 7),
    ("D-AspAsh", "V72I"): (8, 9),
    ("D-ADP-Pi", "V72I"): (11, 10),
}
STAT_FIELDS = ("n", "mean", "std", "median", "q25", "q75")
SUMMARY_KEYS = {(c, v, o) for c, v in PANELS for o in ("delta", "gamma")}
EFFECT_KEYS = {(v, o) for v in ("WT", "V72I") for o in ("delta", "gamma")}
TOLERANCE = 2e-6

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_reference() -> dict[str, Any]:
    path = Path(__file__).with_name("refs.json")
    if path.is_symlink() or not path.is_file() or digest(path) != REFERENCE_SHA256:
        raise EnvironmentInvalid("pinned evaluator reference basis is absent or changed")
    try:
        basis = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnvironmentInvalid(f"pinned evaluator reference basis cannot be parsed: {exc}") from exc
    if not isinstance(basis, dict) or basis.get("schema_version") != "post-hydrolysis-reference/v1":
        raise EnvironmentInvalid("pinned evaluator reference basis has an unsupported schema")
    return basis


def input_summary(raw_path: Path, dictionary: str) -> dict[tuple[str, str, str], dict[str, int | float]]:
    if "第 11 列是角、第 12 列是距离" not in dictionary or "D-ADP-Pi" not in dictionary:
        raise EnvironmentInvalid("pinned Fig. 9a data dictionary no longer identifies the reversed final panel")
    try:
        frame = pd.read_csv(raw_path, sep=r"\s+", header=0, na_values=["NaN"], engine="c")
    except Exception as exc:
        raise EnvironmentInvalid(f"pinned Fig_9a.dat cannot be parsed: {exc}") from exc
    if frame.shape != (560000, 12):
        raise EnvironmentInvalid(f"pinned Fig_9a.dat has unexpected shape {frame.shape}")
    expected = {}
    for (condition, variant), (delta_col, gamma_col) in PANELS.items():
        for observable, col in (("delta", delta_col), ("gamma", gamma_col)):
            values = frame.iloc[:, col].to_numpy(dtype=float)
            values = values[np.isfinite(values)]
            if values.size < 1000:
                raise EnvironmentInvalid(f"public {condition}/{variant}/{observable} series is unexpectedly short")
            expected[(condition, variant, observable)] = {
                "n": int(values.size), "mean": float(np.mean(values)),
                "std": float(np.std(values, ddof=1)), "median": float(np.median(values)),
                "q25": float(np.quantile(values, .25)), "q75": float(np.quantile(values, .75)),
            }
    return expected


def require_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateFail(f"{label} must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise CandidateFail(f"{label} must be finite")
    return number


def require_count(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise CandidateFail(f"{label} must be a nonnegative JSON integer")
    return value


def close(got: Any, expected: float, label: str) -> None:
    number = require_number(got, label)
    if not math.isclose(number, expected, rel_tol=TOLERANCE, abs_tol=TOLERANCE):
        raise CandidateFail(f"{label} does not reproduce the pinned public data")


def compare_reference(expected: dict, basis: dict) -> None:
    if basis.get("input_sha256") != INPUT_SHA256:
        raise EnvironmentInvalid("pinned evaluator basis references different public input bytes")
    if basis.get("units") != {"delta": "angstrom", "gamma": "degree"}:
        raise EnvironmentInvalid("pinned evaluator basis has unexpected units")
    if basis.get("tolerance") != TOLERANCE:
        raise EnvironmentInvalid("pinned evaluator basis has unexpected numeric tolerance")
    refs = basis.get("summary_statistics")
    if not isinstance(refs, list) or len(refs) != 12:
        raise EnvironmentInvalid("pinned evaluator basis has incomplete series statistics")
    seen = set()
    for row in refs:
        key = (row.get("condition"), row.get("variant"), row.get("observable")) if isinstance(row, dict) else None
        if key not in expected or key in seen:
            raise EnvironmentInvalid("pinned evaluator basis has duplicate or unknown summary keys")
        seen.add(key)
        for field in STAT_FIELDS:
            if field == "n":
                if type(row.get(field)) is not int or row[field] != expected[key][field]:
                    raise EnvironmentInvalid(f"pinned evaluator basis disagrees with raw data for {key}/{field}")
            elif not isinstance(row.get(field), (int, float)) or isinstance(row.get(field), bool) or not math.isclose(
                float(row[field]), float(expected[key][field]), rel_tol=TOLERANCE, abs_tol=TOLERANCE
            ):
                raise EnvironmentInvalid(f"pinned evaluator basis disagrees with raw data for {key}/{field}")
    effects = basis.get("effects")
    if not isinstance(effects, list) or len(effects) != 4:
        raise EnvironmentInvalid("pinned evaluator basis has incomplete computed effects")
    effect_seen = set()
    for row in effects:
        if not isinstance(row, dict) or (row.get("variant"), row.get("observable")) not in EFFECT_KEYS:
            raise EnvironmentInvalid("pinned evaluator basis has an unknown effect key")
        key = (row["variant"], row["observable"])
        if key in effect_seen or row.get("baseline") != "D-AspAsh" or row.get("target") != "D-ADP-Pi" or row.get("location_statistic") != "mean":
            raise EnvironmentInvalid("pinned evaluator basis has duplicate or inconsistent effect provenance")
        expected_units = "angstrom" if key[1] == "delta" else "degree"
        if row.get("units") != expected_units:
            raise EnvironmentInvalid(f"pinned evaluator basis has incorrect units for effect {key}")
        effect_seen.add(key)
        expected_effect = expected[("D-ADP-Pi", *key)]["mean"] - expected[("D-AspAsh", *key)]["mean"]
        if not math.isclose(float(row.get("mean_effect", math.nan)), expected_effect, rel_tol=TOLERANCE, abs_tol=TOLERANCE):
            raise EnvironmentInvalid(f"pinned evaluator basis disagrees with raw data for effect {key}")
    if effect_seen != EFFECT_KEYS:
        raise EnvironmentInvalid("pinned evaluator basis has incomplete effect coverage")


def validate_candidate(findings: dict, report: str, expected: dict) -> str:
    allowed_root = {"schema_version", "summary_statistics", "statistical_methods", "comparisons", "return_toward_S", "uncertainty"}
    if set(findings) != allowed_root:
        raise CandidateFail(f"findings.json must use the declared schema fields; unknown or missing fields: {sorted(set(findings) ^ allowed_root)}")
    if findings.get("schema_version") != "post-hydrolysis/v1":
        raise CandidateFail("findings.json must declare schema_version post-hydrolysis/v1")

    rows = findings.get("summary_statistics")
    if not isinstance(rows, list):
        raise CandidateFail("findings.json must contain a summary_statistics array")
    actual = {}
    for row in rows:
        if not isinstance(row, dict):
            raise CandidateFail("summary_statistics entries must be objects")
        allowed = {"condition", "variant", "observable", *STAT_FIELDS}
        if set(row) != allowed:
            raise CandidateFail("summary_statistics entries must use exactly the declared fields")
        if any(not isinstance(row.get(field), str) for field in ("condition", "variant", "observable")):
            raise CandidateFail("summary_statistics condition, variant, and observable must be strings")
        key = (row.get("condition"), row.get("variant"), row.get("observable"))
        if key not in expected or key in actual:
            raise CandidateFail(f"unknown or duplicate summary row: {key}")
        missing = set(STAT_FIELDS) - set(row)
        if missing:
            raise CandidateFail(f"summary row {key} is missing {sorted(missing)}")
        actual[key] = row
        for name in STAT_FIELDS:
            got = require_count(row[name], f"summary {key} n") if name == "n" else require_number(row[name], f"summary {key} {name}")
            if name == "n":
                if got != expected[key][name]:
                    raise CandidateFail(f"summary {key} has n={got}, expected {expected[key][name]}")
            else:
                close(got, float(expected[key][name]), f"summary {key} {name}")
    if set(actual) != set(SUMMARY_KEYS):
        raise CandidateFail(f"summary_statistics must cover all 12 dictionary-defined series; found {len(actual)}")

    methods = findings.get("statistical_methods")
    if not isinstance(methods, list) or not methods or any(not isinstance(x, str) or not x.strip() for x in methods):
        raise CandidateFail("findings.json must contain nonempty statistical_methods descriptions")

    comparisons = findings.get("comparisons")
    if not isinstance(comparisons, list) or len(comparisons) != 4:
        raise CandidateFail("comparisons must contain exactly the two variants by two observables")
    seen = set()
    comparison_statistic = {}
    for row in comparisons:
        if not isinstance(row, dict):
            raise CandidateFail("comparison entries must be objects")
        allowed = {"variant", "observable", "baseline", "target", "location_statistic", "effect", "units", "conclusion"}
        if set(row) != allowed:
            raise CandidateFail("comparison entries must use exactly the declared fields")
        if any(not isinstance(row.get(field), str) for field in ("variant", "observable")):
            raise CandidateFail("comparison variant and observable must be strings")
        key = (row.get("variant"), row.get("observable"))
        if key not in EFFECT_KEYS or key in seen:
            raise CandidateFail(f"unknown or duplicate comparison: {key}")
        seen.add(key)
        if row.get("baseline") != "D-AspAsh" or row.get("target") != "D-ADP-Pi":
            raise CandidateFail(f"comparison {key} must compare D-ADP-Pi against D-AspAsh")
        statistic = row.get("location_statistic")
        if statistic not in ("mean", "median"):
            raise CandidateFail(f"comparison {key} location_statistic must be mean or median")
        comparison_statistic[key] = statistic
        units = "angstrom" if key[1] == "delta" else "degree"
        if row.get("units") != units:
            raise CandidateFail(f"comparison {key} has incorrect units")
        base = expected[("D-AspAsh", key[0], key[1])][statistic]
        target = expected[("D-ADP-Pi", key[0], key[1])][statistic]
        effect = float(target - base)
        close(row.get("effect"), effect, f"comparison {key} effect")
        expected_conclusion = "increased" if effect > TOLERANCE else "decreased" if effect < -TOLERANCE else "inconclusive"
        if row.get("conclusion") != expected_conclusion:
            raise CandidateFail(f"comparison {key} conclusion must be {expected_conclusion} from its numeric effect")

    returns = findings.get("return_toward_S")
    if not isinstance(returns, list) or len(returns) != 2:
        raise CandidateFail("return_toward_S must contain exactly one record per variant")
    seen_variants = set()
    for row in returns:
        if not isinstance(row, dict):
            raise CandidateFail("return_toward_S entries must be objects")
        allowed = {"variant", "location_statistic", "baseline_condition", "target_condition", "reference_condition", "before_distance", "after_distance", "units", "closer_to_S"}
        if set(row) != allowed:
            raise CandidateFail("return_toward_S entries must use exactly the declared fields")
        if not isinstance(row.get("variant"), str):
            raise CandidateFail("return_toward_S variant must be a string")
        variant = row.get("variant")
        if variant not in ("WT", "V72I") or variant in seen_variants:
            raise CandidateFail("return_toward_S has an unknown or duplicate variant")
        seen_variants.add(variant)
        statistic = row.get("location_statistic")
        if statistic not in ("mean", "median"):
            raise CandidateFail(f"return_toward_S {variant} location_statistic must be mean or median")
        if statistic != comparison_statistic[(variant, "delta")]:
            raise CandidateFail(f"return_toward_S {variant} must use the same delta statistic as its comparison")
        if (row.get("baseline_condition"), row.get("target_condition"), row.get("reference_condition"), row.get("units")) != (
            "D-AspAsh", "D-ADP-Pi", "S", "angstrom"
        ):
            raise CandidateFail(f"return_toward_S {variant} must describe delta distances to S")
        s_value = expected[("S", variant, "delta")][statistic]
        before = abs(expected[("D-AspAsh", variant, "delta")][statistic] - s_value)
        after = abs(expected[("D-ADP-Pi", variant, "delta")][statistic] - s_value)
        close(row.get("before_distance"), before, f"return_toward_S {variant} before_distance")
        close(row.get("after_distance"), after, f"return_toward_S {variant} after_distance")
        if type(row.get("closer_to_S")) is not bool or row["closer_to_S"] is not (after < before):
            raise CandidateFail(f"return_toward_S {variant} closer_to_S must reflect strict distance reduction")

    uncertainty = findings.get("uncertainty")
    if not isinstance(uncertainty, dict):
        raise CandidateFail("findings.json must describe uncertainty")
    if set(uncertainty) != {"approach", "independent_sampling_claim", "series_spread", "applicability", "limitations"}:
        raise CandidateFail("uncertainty must use exactly the declared schema fields; unsupported CI/p-value claims are not allowed")
    if uncertainty.get("independent_sampling_claim") is not False:
        raise CandidateFail("the pooled frame data cannot support an independent-sampling claim")
    spread = uncertainty.get("series_spread")
    if not isinstance(spread, list) or len(spread) != 12:
        raise CandidateFail("series_spread must cover all 12 condition/variant/observable series")
    spread_seen = set()
    for row in spread:
        if not isinstance(row, dict):
            raise CandidateFail("series_spread entries must be objects")
        if set(row) != {"condition", "variant", "observable", "q25", "q75"}:
            raise CandidateFail("series_spread entries must use exactly the declared fields")
        if any(not isinstance(row.get(field), str) for field in ("condition", "variant", "observable")):
            raise CandidateFail("series_spread condition, variant, and observable must be strings")
        key = (row.get("condition"), row.get("variant"), row.get("observable"))
        if key not in expected or key in spread_seen:
            raise CandidateFail(f"unknown or duplicate series_spread row: {key}")
        spread_seen.add(key)
        close(row.get("q25"), float(expected[key]["q25"]), f"series_spread {key} q25")
        close(row.get("q75"), float(expected[key]["q75"]), f"series_spread {key} q75")
    if spread_seen != SUMMARY_KEYS:
        raise CandidateFail("series_spread must cover all 12 dictionary-defined series")
    if uncertainty.get("applicability") != "pooled_empirical_data":
        raise CandidateFail("uncertainty applicability must be pooled_empirical_data")
    limitations = normalize_limitations(uncertainty.get("limitations"))
    if limitations is None:
        raise CandidateFail("uncertainty limitations must be nonempty prose or an array of nonempty text disclosures")
    if not discloses_absent_replica_labels(limitations) or not discloses_absent_time_axis(limitations):
        raise CandidateFail("uncertainty limitations must disclose absent independent-replica labels/identifiers and the time axis")
    route = uncertainty.get("approach")
    if route not in ("descriptive", "inferential"):
        raise CandidateFail("uncertainty approach must be descriptive or inferential")
    if route == "descriptive":
        # The descriptive route has no interval or sampling model fields; claims in prose
        # cannot replace the machine-readable no-independence declaration above.
        if any(k.lower() in {"ci", "confidence_interval", "p_value", "pvalue", "standard_error"} for k in uncertainty):
            raise CandidateFail("descriptive uncertainty cannot include inferential intervals or p-values")
        if has_positive_inferential_claim(methods):
            # A valid technique name is not itself an error, but the available pooled
            # frames do not let this verifier validate dependence handling or assumptions.
            return "REVIEW_REQUIRED"
        return "PASS"
    # Named inferential procedures are not rejected solely by name, but this dataset has
    # no independent groups or time axis with which to verify their assumptions/results.
    return "REVIEW_REQUIRED"


def run(app: str, assets: str, logs: str) -> int:
    try:
        public = public_root(assets, INPUT_SHA256)
        basis = load_reference()
        dictionary = public["data_dictionary.md"].read_text(encoding="utf-8")
        expected = input_summary(public["Fig_9a.dat"], dictionary)
        compare_reference(expected, basis)
        final = real_output_dir(app)
        out = require_files(final, ("findings.json", "report.md"))
        try:
            report = out["report.md"].read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CandidateFail(f"cannot read report.md as UTF-8: {exc}") from exc
        if not report.strip():
            raise CandidateFail("report.md must explain the comparisons and descriptive uncertainty")
        try:
            findings = json.loads(out["findings.json"].read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CandidateFail(f"cannot parse findings.json: {exc}") from exc
        if not isinstance(findings, dict):
            raise CandidateFail("findings.json must contain a JSON object")
        status = validate_candidate(findings, report, expected)
        details = {
            "series_recomputed": len(expected), "comparison_rows": 4, "return_to_S_rows": 2,
            "uncertainty_route": findings["uncertainty"]["approach"],
            "reference_basis_sha256": REFERENCE_SHA256,
            "provenance": "pinned Fig_9a.dat plus its dictionary-defined panel ordering",
        }
        message = (
            "all structured summaries and effects reproduce the pinned public measurements; descriptive conclusions are data-derived"
            if status == "PASS" else
            "summaries and effects reproduce the pinned data, but the inferential route cannot be verified without independent groups or a time axis"
        )
        return emit(logs, CASE, status, message, details)
    except EnvironmentInvalid as exc:
        return emit(logs, CASE, "ENV_INVALID", str(exc))
    except CandidateFail as exc:
        return emit(logs, CASE, "FAIL", str(exc))
    except Exception as exc:
        return emit(logs, CASE, "ENV_INVALID", f"verifier could not establish a safe complete result: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("app")
    parser.add_argument("--assets", required=True)
    parser.add_argument("--logs", required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.app, args.assets, args.logs))
