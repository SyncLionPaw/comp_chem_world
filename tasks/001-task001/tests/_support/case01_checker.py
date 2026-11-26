#!/usr/bin/env python3
"""Trusted source-recomputation scorer for Case01 independent evidence audit v4."""
from __future__ import annotations

import argparse
import csv
from collections import Counter
import json
import math
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any

from case01_source_facts import SourceError, build_source_facts, HARTREE_TO_KCAL

CASE_ID = "case-01-snar-mechanism-transition-state"
REQUIRED = {"mechanism.csv", "artifact_audit.jsonl", "thermochemistry.csv"}
OPTIONAL = {"analyze.py", "notes.md", "failures.jsonl"}
REACTIVE_ROLE_MAPS = {
    "s325": {"context_id": "E1-entry-28", "carbon": None, "nucleophile": 4, "leaving_group": None,
             "elements": {"nucleophile": "N"}},
    "s343": {"context_id": "E1-entry-28", "carbon": 8, "nucleophile": None, "leaving_group": 9,
             "elements": {"carbon": "C", "leaving_group": "F"}},
    "s456": {"context_id": "E1-entry-28", "carbon": 8, "nucleophile": 21, "leaving_group": 9,
             "elements": {"carbon": "C", "nucleophile": "N", "leaving_group": "F"}},
    "s353": {"context_id": "E1-entry-28", "carbon": 8, "nucleophile": 21, "leaving_group": 9,
             "elements": {"carbon": "C", "nucleophile": "N", "leaving_group": "F"}},
    "s1694": {"context_id": "E1-entry-90", "carbon": None, "nucleophile": 2, "leaving_group": None,
              "elements": {"nucleophile": "O"}},
    "s1712": {"context_id": "E1-entry-90", "carbon": 2, "nucleophile": None, "leaving_group": 1,
              "elements": {"carbon": "C", "leaving_group": "Cl"}},
    "s1584": {"context_id": "E1-entry-90", "carbon": 2, "nucleophile": 17, "leaving_group": 1,
              "elements": {"carbon": "C", "nucleophile": "O", "leaving_group": "Cl"}},
    "s797": {"context_id": "E1-entry-28", "carbon": 8, "nucleophile": 21, "leaving_group": 9,
             "elements": {"carbon": "C", "nucleophile": "N", "leaving_group": "F"}},
}
# Complete mapped transition-state sources used by the mechanism table audit.
MAPPED = {
    stem: {key: role_map[key] for key in ("context_id", "carbon", "nucleophile", "leaving_group")}
    for stem, role_map in REACTIVE_ROLE_MAPS.items()
    if all(role_map[key] is not None for key in ("carbon", "nucleophile", "leaving_group"))
}
TOL = 0.01


class ScienceFailure(ValueError):
    pass


class MissingScientificEvidence(ScienceFailure):
    """A required author observation was not supplied; no contradictory value is asserted."""


class FormatFailure(ScienceFailure):
    """A malformed or ambiguous candidate representation, not a scientific contradiction."""


class ReviewRequired(ValueError):
    pass


class StageReviewRequired(ReviewRequired):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


class StageFailure(ScienceFailure):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


class StageMissingScientificEvidence(StageFailure, MissingScientificEvidence):
    pass


class StageFormatFailure(StageFailure, FormatFailure):
    pass


class InfraFailure(RuntimeError):
    pass


def normalize_qs_method(raw: Any) -> dict[str, str]:
    """Separate named QS method identity from its explanatory annotation."""
    if not isinstance(raw, str) or not raw.strip():
        raise ScienceFailure("qs_treatment is required and must name a method")
    text = raw.strip()
    declared = re.fullmatch(r"(Truhlar|Grimme)(?:\s*(?:;|:|：)\s*(.*))?", text, re.I | re.S)
    if declared:
        return {"method": declared.group(1).lower(), "annotation": declared.group(2) or ""}
    parenthesized = re.fullmatch(r"(Truhlar|Grimme)\s*(\(.*\)|\[.*\])", text, re.I | re.S)
    if parenthesized:
        return {"method": parenthesized.group(1).lower(), "annotation": parenthesized.group(2)}
    raise ReviewRequired(f"qs_treatment needs an explicit method name separate from commentary: {text}")


def normalize_barrier_claim(numeric: Any, status: Any) -> dict[str, Any]:
    """Classify formal barrier claims without conflating candidate-state ΔG."""
    numeric_text = "" if numeric is None else str(numeric).strip()
    status_text = "" if status is None else str(status).strip()
    status_key = _label(_status_head(status_text))
    if numeric_text.casefold() not in {"", "null", "unresolved"}:
        raise ScienceFailure("reaction_barrier_kcal_mol: formal barrier value must remain empty without path validation")
    if status_key == "formal reaction barrier":
        raise ScienceFailure("reaction_barrier_status: formal_reaction_barrier is unsupported without path validation")
    if status_key == "local saddle energy difference path unvalidated":
        return {"formal_claim": False, "canonical_status": "unassigned",
                "local_candidate_comparison": True}
    if status_key in {"", "null", "unvalidated", "not validated", "formal barrier unresolved",
                      "unresolved no proven path connection and join"} or _unresolved(status_text):
        return {"formal_claim": False, "canonical_status": "unassigned",
                "local_candidate_comparison": False}
    raise ReviewRequired(f"reaction_barrier_status uses an unsupported status: {status_text}")


def _label(value: Any) -> str:
    return re.sub(r"[\s_-]+", " ", value.strip().lower()) if isinstance(value, str) else ""


def _status_head(value: Any) -> str:
    return re.split(r"[:：]", value, maxsplit=1)[0].strip() if isinstance(value, str) else ""


def _unresolved(value: Any) -> bool:
    return _label(_status_head(value)) in {"unresolved", "unknown", "undetermined", "not established",
                             "not proven", "not assigned", "unassigned", "not determined"}


def _engine_termination_matches(value: Any, expected: Any) -> bool:
    def state(raw: Any) -> tuple[str, str | None] | None:
        label = _status_head(raw).lower()
        if label == "normal": return ("normal", None)
        if label == "failed": return ("failed", None)
        if re.fullmatch(r"failed_[a-z][a-z0-9_]*", label):
            return ("failed", label.removeprefix("failed_"))
        return None

    expected_state = state(expected)
    if isinstance(value, dict):
        if (not {"status", "reason"}.issubset(value)
                or not isinstance(value.get("reason"), str) or not value["reason"].strip()):
            return False
        actual = state(value.get("status"))
        if actual is None: return False
        module = value.get("failed_module")
        if module is not None and (not isinstance(module, str) or not module.strip()): return False
        module = module.strip().lower() if module is not None else None
        if actual[1] is not None and module is not None and actual[1] != module: return False
        effective_module = actual[1] or module
        if actual[0] == "normal" and effective_module is not None: return False
        if actual[0] == "failed" and effective_module is None: return False
        return (actual[0], effective_module) == expected_state
    return isinstance(value, str) and state(value) == expected_state


def _qh_convention(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.translate(str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"}))
    return re.search(r"\bqh\s*[-_ ]\s*g\s*\(", normalized, re.I) is not None


def _one_molar(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return re.search(r"(?<![\w.])1\s*(?:M\b|mol\s*(?:/\s*[lL]\b|[lL]\s*(?:\^\s*)?[-−]1\b))", value) is not None


def _source_aliases(facts: dict) -> dict[str, str]:
    """Resolve only source-backed aliases; shared native labels need a job qualifier."""
    candidates: dict[str, set[str]] = {}

    def add(alias: str, canonical: str) -> None:
        candidates.setdefault(alias, set()).add(canonical)

    for context in ("E1-entry-28", "E1-entry-90"):
        add(context, context)
    for asset_name in facts["source_asset_hashes"]:
        base_name = Path(asset_name.removeprefix("assets/")).name
        stem = Path(base_name).stem
        match = re.search(r"(?:^|-)(s\d+)$", stem)
        canonical = match.group(1) if match else stem
        for alias in (base_name, stem, canonical, asset_name, f"assets/{base_name}", f"/app/assets/{base_name}"):
            add(alias, canonical)
    for row in facts["native"]["records"]:
        job_id = row["job_id"]
        canonical = f"native-diagnostic-excerpts.json#{job_id}"
        for alias in (canonical, f"assets/{canonical}", f"/app/assets/{canonical}"): add(alias, canonical)
        labels = {item["source_label"] for item in row.get("excerpts", []) if item.get("source_label")}
        for key in ("execution_source_label", "scheduler_source_label"):
            if row.get(key):
                labels.add(row[key])
        coordinate_label = row.get("coordinate_source", {}).get("source_label")
        if coordinate_label:
            labels.add(coordinate_label)
        for label in labels:
            add(label, canonical)
            add(f"{label}#{job_id}", canonical)
        if row.get("scheduler_source_label"):
            add(f"sacct:{job_id}", canonical)
    return {alias: next(iter(ids)) for alias, ids in candidates.items() if len(ids) == 1}


def _source_evidence_matches(actual: Any, expected: Any, label: str, key: str = "") -> bool:
    """Compare a declared source fact tree while allowing line locators to be omitted."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        if key == "prior_geometry_optimization" and "failed_criteria" in actual:
            flags = {"optimization_completed": "optimization_completed_line_1based",
                     "stationary_point_observed": "stationary_point_line_1based",
                     "normal_termination": "normal_termination_line_1based"}
            if not all(type(actual.get(flag)) is bool and actual[flag] == (expected.get(source) is not None)
                       for flag, source in flags.items()): return False
            if not _source_evidence_matches({"failed_criteria": actual["failed_criteria"]}, expected["force_criteria"], label, "force_criteria"): return False
            for field, value in actual.items():
                if field in flags or field == "failed_criteria": continue
                if field in expected and not _source_evidence_matches(value, expected[field], f"{label}.{field}", field): return False
            return True
        if key in {"force_criteria", "frequency_level_force_criteria"}:
            raw_to_snake = {"Maximum Force": "maximum_force", "RMS Force": "rms_force",
                            "Maximum Displacement": "maximum_displacement", "RMS Displacement": "rms_displacement"}
            if set(expected) != set(raw_to_snake): return False
            snake_to_raw = {snake: raw for raw, snake in raw_to_snake.items()}
            scientific = {}
            for field, value in actual.items():
                canonical = field if field in raw_to_snake else snake_to_raw.get(field)
                if canonical is None: continue
                if canonical in scientific: return False
                scientific[canonical] = value
            if "failed_criteria" in actual:
                failed = actual["failed_criteria"]
                if (not isinstance(failed, list) or any(not isinstance(x, str) for x in failed)
                        or len(failed) != len(set(failed))): return False
                if set(failed) != {name for name, record in expected.items() if record["pass"] != "YES"}: return False
            elif set(scientific) != set(expected): return False
            return all(_source_evidence_matches(value, expected[field], f"{label}.{field}", field)
                       for field, value in scientific.items())
        event_flags = {
            "optimization_completed_line_1based": "optimization_completed",
            "stationary_point_line_1based": "stationary_point_observed",
            "normal_termination_line_1based": "normal_termination",
            "gaussian_normal_termination_line_1based": "normal_termination",
            "frequency_link_optimization_completed_line_1based": "frequency_link_optimization_completed",
            "frequency_link_stationary_point_line_1based": "frequency_link_stationary_point_observed",
        }
        optional_locators = {"harmonic_block_line_1based", "frequency_route_line_1based",
                             "frequency_link_floor_line_1based", "geometry_header_line_1based",
                             "vector_line_range_1based", "source_line_range_1based",
                             "final_scf_line_1based", "gaussian_zpe_line_1based"}
        for key, value in expected.items():
            lowered = key.lower()
            if "timestamp" in lowered or lowered.endswith("sha256"):
                continue
            if key in event_flags:
                expected_present = value is not None
                has_line = key in actual
                has_flag = event_flags[key] in actual
                if has_line and ((actual[key] is not None) != expected_present):
                    return False
                if has_flag and (type(actual[event_flags[key]]) is not bool or actual[event_flags[key]] != expected_present):
                    return False
                if not has_line and not has_flag:
                    return False
                continue
            if (key in optional_locators or lowered == "line_1based" or lowered.endswith("_line_1based")
                    or lowered.endswith("_line_range_1based")):
                continue
            if key == "geometry_source_relation":
                continue
            if key not in actual or not _source_evidence_matches(actual[key], value, f"{label}.{key}", key):
                return False
        return True
    if key == "stationary_point_interpretation":
        aliases = {
            "optimized minimum candidate": "minimum", "minimum candidate": "minimum",
            "converged minimum candidate": "minimum",
            "converged first order saddle candidate": "saddle",
            "first order saddle candidate": "saddle", "first order saddle point candidate": "saddle",
            "higher order saddle candidate": "higher_order_saddle",
            "unresolved": "unresolved",
        }
        return _label(_status_head(actual)) in aliases and aliases[_label(_status_head(actual))] == aliases.get(_label(expected))
    if key == "frequency_level_stationarity":
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False
        stationary = {"source_reported_stationary_with_all_four_criteria",
                      "stationary_point_found_at_frequency_level"}
        return actual == expected or (actual in stationary and expected in stationary)
    if key in {"goodvibes_stem", "gaussian_stem"}:
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False

        def source_stem(value: str) -> str | None:
            if re.fullmatch(r"s\d+", value):
                return value
            match = re.fullmatch(r"SC-012-D0SC04896H-(s\d+)", value)
            return match.group(1) if match else None

        actual_stem, expected_stem = source_stem(actual), source_stem(expected)
        return actual_stem is not None and actual_stem == expected_stem
    if key == "standard_state":
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False
        if actual == expected:
            return True
        return _one_molar(actual) and _one_molar(expected)
    if key == "qs_treatment":
        actual_method = normalize_qs_method(actual)
        expected_method = normalize_qs_method(expected)
        return actual_method["method"] == expected_method["method"]
    if key == "pass":
        if type(actual) is bool and isinstance(expected, str) and expected in {"YES", "NO"}:
            return actual == (expected == "YES")
        if type(expected) is bool and isinstance(actual, str) and actual in {"YES", "NO"}:
            return expected == (actual == "YES")
    if key == "execution_state":
        # Allow "failed" plus a native exit-code annotation such as "failed (exit 1)".
        if isinstance(actual, str) and isinstance(expected, str):
            actual_state = actual.strip().split("(", 1)[0].strip().lower()
            expected_state = expected.strip().split("(", 1)[0].strip().lower()
            if actual_state == expected_state:
                return True
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(actual) == len(expected)
                and all(_source_evidence_matches(a, e, label, key) for a, e in zip(actual, expected)))
    if isinstance(expected, bool):
        return type(actual) is bool and actual == expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if isinstance(expected, int):
            return _json_integer(actual, label) == expected
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            raise FormatFailure(f"{label} must be a JSON numeric observation")
        try:
            tolerance = (5e-7 if key in {"final_scf_E_hartree", "goodvibes_E_hartree", "energy_abs_diff_hartree"}
                         else 2e-6 if key in {"goodvibes_qh_G_T_hartree", "goodvibes_H_minus_T_qhS_hartree", "qh_reconciliation_abs_diff_hartree"}
                         else 0.0)
            return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tolerance)
        except (TypeError, ValueError):
            return False
    return actual == expected


def _projection_view(row: dict) -> Any:
    """Combine author-provided observations; each supplied alias is checked against the source."""
    fields = ("reactive_coordinate_projection", "projection")
    views = [row[field] for field in fields if row.get(field) is not None]
    if not views: return None
    if any(not isinstance(view, dict) for view in views):
        raise FormatFailure("projection observations must be objects")
    merged = {}
    for view in reversed(views): merged.update(view)
    return merged


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise FormatFailure(f"{label} must be numeric, not boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FormatFailure(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise FormatFailure(f"{label} must be finite")
    return result


def _close(actual: Any, expected: float, tol: float, label: str) -> None:
    value = _finite(actual, label)
    if not math.isclose(value, expected, rel_tol=0.0, abs_tol=tol):
        raise ScienceFailure(f"{label} differs from source: submitted={value}, source={expected}, absolute_tolerance={tol}")


class ObservedFloat(float):
    """An output numeric token, retaining its exact spelling for identity checks."""
    def __new__(cls, literal):
        value = super().__new__(cls, literal)
        value.literal = literal
        return value


def _json_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FormatFailure(f"{label} must be a JSON integer value")
    number = Decimal(value.literal if isinstance(value, ObservedFloat) else str(value))
    if not number.is_finite() or number != number.to_integral_value() or not -(2**63) <= number < 2**63:
        raise FormatFailure(f"{label} must be an exact finite integer in range")
    return int(number)


def _parse_json(text: str, label: str) -> Any:
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise FormatFailure(f"{label}: duplicate JSON key {key!r}")
            out[key] = value
        return out
    def invalid(value):
        raise FormatFailure(f"{label}: nonfinite JSON number {value}")
    def finite_tree(value):
        if isinstance(value, dict):
            for child in value.values(): finite_tree(child)
        elif isinstance(value, list):
            for child in value: finite_tree(child)
        elif isinstance(value, float) and not math.isfinite(value): invalid(value)
    try:
        value = json.loads(text, object_pairs_hook=unique, parse_constant=invalid, parse_float=ObservedFloat)
    except json.JSONDecodeError as exc:
        raise FormatFailure(f"{label}: invalid JSON: {exc}") from exc
    finite_tree(value)
    return value


def _read_json(path: Path, label: str) -> Any:
    try:
        return _parse_json(path.read_text(encoding="utf-8-sig"), label)
    except (OSError, UnicodeError) as exc:
        raise FormatFailure(f"{label} is missing or unreadable: {exc}") from exc


def _jsonl(path: Path, label: str) -> list[dict]:
    if not path.is_file() or path.is_symlink():
        raise FormatFailure(f"{label} is missing or unsafe")
    result = []
    try:
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip(): continue
            value = _parse_json(line, f"{label}:{number}")
            if not isinstance(value, dict):
                raise FormatFailure(f"{label}:{number} must be a JSON object")
            result.append(value)
    except (OSError, UnicodeError) as exc:
        raise FormatFailure(f"{label} is unreadable JSONL: {exc}") from exc
    return result


def _required_file(root: Path, name: str) -> Path:
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise FormatFailure(f"required output missing or unsafe: {name}")
    return path


def _native_identity(value, label):
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value): return value.lstrip("0") or "0"
    if isinstance(value, (int, float)) and not isinstance(value, bool): return str(_json_integer(value, label))
    raise FormatFailure(f"{label} must contain one integer job identity")


def _audit_locator(value, aliases):
    """Resolve explicit locator syntax only; preserve other descriptions as unverified."""
    if value is None: return None, None
    text = value.strip()
    head, marker, annotation = text.partition(" (")
    annotated = bool(marker and text.endswith(")"))
    token = head if annotated else text
    canonical = aliases.get(token)
    if canonical is None and "#" in token:
        container, fragment = token.split("#", 1)
        base = aliases.get(container)
        native_label = (base == "native-diagnostic-excerpts" or (base is not None and base.startswith("native-diagnostic-excerpts.json#"))
                        or any(alias.startswith(container + "#") and identity.startswith("native-diagnostic-excerpts.json#") for alias, identity in aliases.items()))
        if native_label:
            if not re.fullmatch(r"[0-9]+", fragment): raise FormatFailure("native locator has an invalid explicit job fragment")
            canonical = f"native-diagnostic-excerpts.json#{_native_identity(fragment, 'native locator')}"
            if base is not None and base.startswith("native-diagnostic-excerpts.json#") and base != canonical:
                raise FormatFailure("native source label conflicts with its explicit job fragment")
    job = None
    if canonical and canonical.startswith("native-diagnostic-excerpts.json#"): job = canonical.rsplit("#", 1)[1]
    if canonical is not None and annotated:
        jobs = {_native_identity(x, "native locator") for x in re.findall(r"\bjob_id\s*(?:[:=]\s*)?([0-9]+)\b", annotation)}
        if job is not None: jobs.add(job)
        for label in re.findall(r"\bsource label\s*(?:[:=]\s*)?([A-Za-z0-9_.-]+)", annotation):
            referred = aliases.get(label)
            if referred and referred.startswith("native-diagnostic-excerpts.json#"): jobs.add(referred.rsplit("#", 1)[1])
        if len(jobs) > 1: raise FormatFailure("source locator contains conflicting explicit job identities")
        job = next(iter(jobs)) if jobs else None
    return canonical, job


def _compare_audit(root: Path, facts: dict, identity_audit: list | None = None) -> tuple[list[dict], dict]:
    rows = _jsonl(_required_file(root, "artifact_audit.jsonl"), "artifact_audit.jsonl")
    if len(rows) < 10:
        raise MissingScientificEvidence("artifact_audit.jsonl must supply all eight Gaussian and two native assessments")
    if len(rows) > 10:
        raise FormatFailure("artifact_audit.jsonl has extra or duplicated source assessments")
    gaussian_names = {row["source_file"] for row in facts["gaussian"]}
    native_source = "native-diagnostic-excerpts.json"
    source_aliases = _source_aliases(facts)
    expected_native_ids = {row["job_id"] for row in facts["native"]["records"]}
    gaussian_by_stem = {name.rsplit("-", 1)[-1].removesuffix(".log"): name for name in gaussian_names}
    by_name = {}
    native_by_job = {}
    interpretation_audit = []
    for row in rows:
        name = row.get("source_file")
        if name is not None and not isinstance(name, str): raise FormatFailure("source_file must be a source identifier or description")
        canonical, locator_job = _audit_locator(name, source_aliases)
        row = dict(row)
        native_id = row.get("job_id")
        raw_native_id = native_id
        if canonical in gaussian_by_stem:
            if native_id is not None or row.get("sacct_job_id") is not None or locator_job is not None: raise FormatFailure("Gaussian source and native job_id conflict")
            name = gaussian_by_stem[canonical]
            row["source_file"] = name
            if name in by_name: raise FormatFailure("artifact_audit records duplicate a Gaussian source")
            by_name[name] = row
            continue
        raw_native_id = row.get("job_id")
        raw_sacct_id = row.get("sacct_job_id")
        declared_ids = {field: _native_identity(row[field], field) for field in ("job_id", "sacct_job_id") if row.get(field) is not None}
        identities = set(declared_ids.values()) | ({locator_job} if locator_job is not None else set())
        if not identities: raise FormatFailure("provide one known native job identity or a uniquely qualified source locator")
        if len(identities) != 1: raise FormatFailure("conflicting explicit native job identities")
        native_id = next(iter(identities))
        if native_id not in expected_native_ids: raise FormatFailure("native identity does not identify a supplied job")
        row.update(declared_ids)
        if canonical is not None and canonical != Path(native_source).stem and canonical != f"{native_source}#{native_id}":
            raise FormatFailure("native identity conflicts with a different supplied source")
        row["job_id"] = native_id
        if canonical is None and isinstance(name, str): canonical = source_aliases.get(f"{name}#{native_id}")
        if native_id in native_by_job: raise FormatFailure(f"duplicate native record identity {native_id}")
        native_by_job[native_id] = row
        if identity_audit is not None:
            identity_audit.append({"job_id": native_id, "raw_locator": name,
                "raw_job_id": raw_native_id, "raw_sacct_job_id": raw_sacct_id, "locator_status": "not_provided" if name is None else "verified" if canonical is not None else "unverified_description",
                "description_semantics_verified": False, "identity_verified": True})
    if set(by_name) != gaussian_names or set(native_by_job) != expected_native_ids:
        raise ScienceFailure("artifact_audit inventory must match all eight Gaussian logs and both native diagnostics")
    for expected in facts["gaussian"]:
        name = expected["source_file"]
        row = by_name[name]
        stem = name.rsplit("-", 1)[-1].removesuffix(".log")
        fixed_join = next((item for item in facts["source_joins"] if item["gaussian_stem"] == stem), None)
        if fixed_join is None:
            raise ScienceFailure(f"{name}: trusted thermochemistry join is missing")
        fixed_join = {key: value for key, value in fixed_join.items() if "sha256" not in key}
        join = row.get("thermochemistry_join")
        required_join_keys = {"final_scf_E_hartree", "gaussian_zpe_hartree"}
        if not isinstance(join, dict) or not required_join_keys.issubset(join):
            raise ScienceFailure(f"{name}: thermochemistry_join must identify its GoodVibes report and report the source-joined energies")
        join = dict(join)
        if "goodvibes_stem" in join:
            if not isinstance(join["goodvibes_stem"], str): raise FormatFailure(f"{name}: GoodVibes source identifier must be a string")
            join["goodvibes_stem"] = source_aliases.get(join["goodvibes_stem"], join["goodvibes_stem"])
            if not _source_evidence_matches(join["goodvibes_stem"], fixed_join["goodvibes_stem"], f"{name}.goodvibes_stem", "goodvibes_stem"):
                raise ScienceFailure(f"{name}: supplied GoodVibes binding contradicts the source-matched report")
        for key, value in fixed_join.items():
            if key in join and not _source_evidence_matches({key: join[key]}, {key: value}, f"{name}.thermochemistry_join.{key}"):
                raise ScienceFailure(f"{name}: thermochemistry_join.{key} differs from source")
        for key in ("n_atoms", "formal_mode_count", "formal_negative_mode_count"):
            if key in row and _json_integer(row[key], f"{name}.{key}") != expected[key]:
                raise ScienceFailure(f"{name}: {key} differs from the parsed source")
        for field, source_value in (("prior_geometry_optimization", expected["prior_geometry_optimization"]),
                                    ("frequency_level_force_criteria", expected["frequency_level_force_criteria"]),
                                    ("frequency_level_stationarity", expected["frequency_level_stationarity"])):
            if field == "frequency_level_stationarity" and field not in row: continue
            if not _source_evidence_matches(row.get(field), source_value, f"{name}.{field}", field):
                raise ScienceFailure(f"{name}: {field} differs from source evidence")
        for line_field, flag_field in (("frequency_link_optimization_completed_line_1based", "frequency_link_optimization_completed"),
                                       ("frequency_link_stationary_point_line_1based", "frequency_link_stationary_point_observed")):
            source_present = expected.get(line_field) is not None
            if line_field in row:
                if (row[line_field] is not None) != source_present:
                    raise ScienceFailure(f"{name}: {line_field} completion evidence differs from source")
            if flag_field in row and (type(row[flag_field]) is not bool or row[flag_field] != source_present):
                raise ScienceFailure(f"{name}: {flag_field} must preserve whether the frequency-link event occurred")
            if line_field not in row and flag_field not in row:
                raise ScienceFailure(f"{name}: provide {line_field} or {flag_field}")
        interpretation_evidence = expected["stationary_point_interpretation_evidence"]
        interpretation = row.get("stationary_point_interpretation")
        allowed = interpretation_evidence["allowed_interpretations"]
        interpretation_ok = any(_source_evidence_matches(interpretation, label, name,
                                                         "stationary_point_interpretation") for label in allowed)
        recognized_interpretation = any(_source_evidence_matches(interpretation, label, name, "stationary_point_interpretation") for label in
            ("optimized minimum candidate", "first order saddle candidate", "higher order saddle candidate", "unresolved"))
        interpretation_audit.append({
            "source_file": name,
            "context_id": (_projection_view(row).get("context_id") if isinstance(_projection_view(row), dict) else None),
            "verified_goodvibes_stem": fixed_join["goodvibes_stem"],
            "source_observations": interpretation_evidence["observed"],
            "source_observations_status": "PASS",
            "allowed_interpretations": allowed,
            "submitted_interpretation": interpretation,
            "interpretation_status": "PASS" if interpretation_ok else "REVIEW_REQUIRED" if isinstance(interpretation, str) and interpretation.strip() and not recognized_interpretation else "FAIL",
            "interpretation_error": None if interpretation_ok else (
                f"submitted interpretation {interpretation!r} is not supported by the source-derived options {allowed}"),
            "source_limitations": interpretation_evidence["limitations"],
        })
        modes = row.get("negative_modes")
        if not isinstance(modes, list) or len(modes) != expected["formal_negative_mode_count"]:
            raise ScienceFailure(f"{name}: every formal negative mode must be reported")
        modes = [{"frequency_cm-1": mode} if isinstance(mode, (int, float)) and not isinstance(mode, bool) else mode for mode in modes]
        row["negative_modes"] = modes
        source_modes = expected["negative_modes"]
        for candidate, fixed in zip(modes, source_modes):
            if not isinstance(candidate, dict):
                raise FormatFailure(f"{name}: negative-mode item must be a finite frequency or observation object")
            if "mode_index_zero_based" in candidate and _json_integer(candidate["mode_index_zero_based"], f"{name}.mode_index_zero_based") != fixed["mode_index_zero_based"]:
                raise ScienceFailure(f"{name}: negative mode index differs from source")
            _close(candidate.get("frequency_cm-1"), fixed["frequency_cm-1"], 0.0001,
                   f"{name} negative mode frequency")
        stem = name.rsplit("-", 1)[-1].split(".")[0]
        # Validate every supplied scientific view independently against the same trusted
        # geometry/mode. Extra notes do not define equality; a complete global sign flip
        # is physically equivalent, while a wrong index or component still fails.
        merged_projection = _projection_view(row)
        supplied_views = [row[field] for field in ("reactive_coordinate_projection", "projection")
                          if isinstance(row.get(field), dict)]
        if not supplied_views: supplied_views = [merged_projection]
        for view in supplied_views:
            variant = {key: value for key, value in row.items() if key not in {"reactive_coordinate_projection", "projection"}}
            variant["reactive_coordinate_projection"] = ({**merged_projection, **view}
                                                          if isinstance(merged_projection, dict) else view)
            _check_reactive_role_mapping(stem, name, variant, expected)
    return interpretation_audit, native_by_job


def _check_mpi_causality(value: Any, label: str) -> None:
    if isinstance(value, dict):
        if not {"established", "reason"}.issubset(value):
            raise MissingScientificEvidence(f"{label}: MPI causality needs established and a reason")
        if type(value["established"]) is not bool:
            raise FormatFailure(f"{label}: MPI established must be boolean")
        if value["established"]:
            raise ScienceFailure(f"{label}: the source does not establish an MPI/OpenFabrics cause")
        if not isinstance(value["reason"], str) or not value["reason"].strip():
            raise MissingScientificEvidence(f"{label}: MPI causality reason is missing")
        return
    if isinstance(value, str) and value.strip().lower() in {
            "suspected_only_not_proven", "suspected only, not proven",
            "suspected only; not proven", "suspected only and not proven"}:
        return
    if isinstance(value, str) and value.strip():
        raise ReviewRequired(f"{label}: MPI causality free text has no explicit established boolean: {value!r}")
    raise MissingScientificEvidence(f"{label}: MPI causal assessment was not supplied")


def _compare_native(native_by_job: dict, facts: dict) -> None:
    fixed_success, fixed_failure = facts["native"]["records"]
    success = native_by_job[fixed_success["job_id"]]
    failure = native_by_job[fixed_failure["job_id"]]
    success_fields = ("job_id", "engine_termination", "frequencies_count", "negative_frequency_count",
                      "frequency_zero_or_near_zero_count",
                      "thermochemistry_temperature_K", "final_gibbs_hartree", "coordinate_atom_count")
    failure_fields = ("job_id", "engine_termination", "execution_state", "scheduler_state",
                      "scheduler_exit_code", "sacct_job_id", "mpi_openfabrics_causality")
    for candidate, fixed, fields in ((success, fixed_success, success_fields), (failure, fixed_failure, failure_fields)):
        for field in fields:
            if field == "sacct_job_id" and field not in candidate: continue
            if field == "mpi_openfabrics_causality":
                _check_mpi_causality(candidate.get(field), f"native job {fixed['job_id']}")
                continue
            if field == "engine_termination":
                if not _engine_termination_matches(candidate.get(field), fixed[field]):
                    raise ScienceFailure(f"native job {fixed['job_id']}: {field}; submitted={candidate.get(field)!r}, source={fixed[field]!r}")
                continue
            if field not in candidate or not _source_evidence_matches(candidate[field], fixed[field], field):
                raise ScienceFailure(f"native job {fixed['job_id']}: {field}; submitted={candidate.get(field)!r}, source={fixed[field]!r}")
    if "geometry_converged" in success:
        if type(success["geometry_converged"]) is not bool:
            raise FormatFailure(f"native job {fixed_success['job_id']}: geometry_converged must be boolean")
        if not success["geometry_converged"]:
            raise ScienceFailure(f"native job {fixed_success['job_id']}: geometry_converged=false contradicts source convergence")
    else:
        if "geometry_convergence_yes_line_count" not in success:
            raise MissingScientificEvidence(f"native job {fixed_success['job_id']}: geometry convergence observation is missing")
        count = _json_integer(success["geometry_convergence_yes_line_count"], "native geometry convergence count")
        if count != fixed_success["geometry_convergence_yes_line_count"] or count < 5:
            raise ScienceFailure(f"native job {fixed_success['job_id']}: legacy convergence evidence differs from source")


def _check_reactive_role_mapping(stem: str, name: str, row: dict, expected: dict) -> None:
    """Validate source-mapped atom roles by presence, then every derivable distance/projection."""
    mapping = REACTIVE_ROLE_MAPS.get(stem)
    if mapping is None:
        raise ScienceFailure(f"{name}: trusted reactive-role mapping is unavailable")
    submitted = _projection_view(row)
    if not isinstance(submitted, dict):
        raise MissingScientificEvidence(f"{name}: source-mapped reactive-role observation was not supplied")
    if submitted.get("context_id") != mapping["context_id"]:
        raise ScienceFailure(f"{name}: reactive-role context differs from the source mapping")

    field_for_role = {
        "carbon": "central_carbon_atom_index_1based",
        "nucleophile": "nucleophile_atom_index_1based",
        "leaving_group": "leaving_group_atom_index_1based",
    }
    source_atoms = {atom["atom_index_1based"]: atom for atom in expected["geometry"]["atoms"]}
    submitted_roles = {}
    for role, field in field_for_role.items():
        expected_index = mapping[role]
        actual_index = submitted.get(field)
        if expected_index is None:
            if actual_index is not None:
                raise ScienceFailure(f"{name}: absent {role} atom index must be omitted or null")
            submitted_roles[role] = None
            continue
        if actual_index is None: raise MissingScientificEvidence(f"{name}: observed {role} atom index was not supplied")
        if _json_integer(actual_index, f"{name}.{field}") != expected_index:
            raise ScienceFailure(f"{name}: mapped {role} atom index differs from source evidence")
        atom = source_atoms.get(expected_index)
        if atom is None or atom["element"] != mapping["elements"][role]:
            raise ScienceFailure(f"{name}: mapped {role} atom does not have the source-supported element")
        submitted_roles[role] = expected_index

    geometry = {atom["atom_index_1based"]: atom["xyz_angstrom"] for atom in expected["geometry"]["atoms"]}
    for first, second, field in (("carbon", "nucleophile", "C_Nu_distance_angstrom"),
                                 ("carbon", "leaving_group", "C_X_distance_angstrom")):
        a, b = submitted_roles[first], submitted_roles[second]
        if a is None or b is None:
            if submitted.get(field) is not None:
                raise ScienceFailure(f"{name}: {field} must be omitted or null because one atom role is absent")
            continue
        try:
            distance = math.dist(geometry[a], geometry[b])
        except (KeyError, TypeError, ValueError):
            raise ScienceFailure(f"{name}: mapped atoms do not support {field}") from None
        _close(submitted.get(field), distance, 0.0051, f"{name} {field}")

    projection_fields = ("projected_C_Nu_change_raw", "projected_C_X_change_raw",
                         "projected_delta_r_raw", "sign_equivalent_magnitude")
    if all(submitted_roles.values()) and expected["formal_negative_mode_count"] > 0:
        _check_projection(stem, row, expected, mapping)
        return
    for field in projection_fields:
        if submitted.get(field) is not None:
            raise ScienceFailure(f"{name}: {field} must be omitted or null without a complete mapped negative-mode projection")


def _vec_sub(a: list[float], b: list[float]) -> list[float]:
    return [a[i] - b[i] for i in range(3)]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(a[i] * b[i] for i in range(3))


def _norm(a: list[float]) -> float:
    return math.sqrt(_dot(a, a))


def _project(geometry: dict[int, list[float]], mode: dict, mapping: dict) -> dict:
    c, nu, x = mapping["carbon"], mapping["nucleophile"], mapping["leaving_group"]
    vec = {int(k): v for k, v in mode["vector_atoms"].items()}
    c_nu = _vec_sub(geometry[nu], geometry[c])
    c_x = _vec_sub(geometry[x], geometry[c])
    u_nu, u_x = [v / _norm(c_nu) for v in c_nu], [v / _norm(c_x) for v in c_x]
    d_nu = _dot(u_nu, _vec_sub(vec[nu], vec[c]))
    d_x = _dot(u_x, _vec_sub(vec[x], vec[c]))
    return {"central_carbon_atom_index_1based": c, "nucleophile_atom_index_1based": nu,
            "leaving_group_atom_index_1based": x,
            "C_Nu_distance_angstrom": _norm(c_nu), "C_X_distance_angstrom": _norm(c_x),
            "projected_C_Nu_change_raw": d_nu, "projected_C_X_change_raw": d_x,
            "projected_delta_r_raw": d_nu - d_x,
            "sign_equivalent_magnitude": abs(d_nu - d_x)}


def _check_projection(name: str, row: dict, expected: dict, mapping: dict) -> None:
    source_atoms = {a["atom_index_1based"]: a["xyz_angstrom"] for a in expected["geometry"]["atoms"]}
    projection = _project(source_atoms, expected["negative_modes"][0], mapping)
    submitted = _projection_view(row)
    if isinstance(submitted, dict):
        components = ("projected_C_Nu_change_raw", "projected_C_X_change_raw")
        if all(math.isclose(_finite(submitted.get(key), f"{name}.{key}"), -projection[key], rel_tol=0.0, abs_tol=0.0051) for key in components):
            for key in (*components, "projected_delta_r_raw"): projection[key] = -projection[key]
    if not isinstance(submitted, dict):
        raise ScienceFailure(f"{name}: reactive C-Nu/C-X projection evidence is required")
    for key, value in projection.items():
        if key in {"projected_delta_r_raw", "sign_equivalent_magnitude"} and key not in submitted: continue
        if submitted.get(key) != value and isinstance(value, (str, int)):
            raise ScienceFailure(f"{name}: projection field {key} is incorrect")
        if isinstance(value, float):
            _close(submitted.get(key), value, 0.0051, f"{name} projection {key}")
    if submitted.get("context_id") != mapping["context_id"]:
        raise ScienceFailure(f"{name}: reactive coordinate context mapping is incorrect")


def _compare_thermochemistry(root: Path, facts: dict, report: dict) -> dict:
    def close_field(stage: str, actual: Any, expected: float, tolerance: float, label: str) -> None:
        try:
            _close(actual, expected, tolerance, label)
        except ScienceFailure as exc:
            raise (StageFormatFailure if isinstance(exc, FormatFailure) else StageFailure)(stage, str(exc)) from exc

    path = _required_file(root, "thermochemistry.csv")
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames or []
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise StageFailure("thermochemistry_source", f"thermochemistry.csv unreadable: {exc}") from exc
    required_columns = {"record_type", "source_file", "source_ids", "coefficients",
                        "identity_status", "temperature_K", "concentration_mol_L",
                        "qh_G_T_hartree", "scale_factor", "qs_treatment",
                        "frequency_cutoff_cm-1", "candidate_delta_g_kcal_mol"}
    if len(columns) != len(set(columns)) or not required_columns.issubset(columns):
        raise StageFormatFailure("thermochemistry_source", "thermochemistry.csv has duplicate or missing required columns")
    if any(None in row for row in rows):
        raise StageFormatFailure("thermochemistry_source", "thermochemistry.csv contains rows with extra undeclared fields")
    source = [row for row in rows if row.get("record_type") in {"source", "goodvibes_source"}]
    differences = [row for row in rows if row.get("record_type") in {"candidate_difference", "candidate_delta_g"}]
    if len(source) != 8 or len(source) + len(differences) != len(rows):
        raise StageFormatFailure("thermochemistry_source", "thermochemistry row types must be eight source rows and candidate_difference rows")
    expected = {row["source_file"]: row for row in facts["goodvibes"]}
    goodvibes_by_stem = {row["source_file"].rsplit("-", 1)[-1].split(".")[0]: row["source_file"]
                         for row in facts["goodvibes"]}
    gaussian_to_goodvibes = {
        f"SC-012-D0SC04896H-{join['gaussian_stem']}.log": goodvibes_by_stem[join["goodvibes_stem"]]
        for join in facts["source_joins"] if join["goodvibes_stem"] in goodvibes_by_stem
    }
    aliases = _source_aliases(facts)
    gaussian_stem_to_gv = {join["gaussian_stem"]: join["goodvibes_stem"] for join in facts["source_joins"]}
    submitted_sources = {}
    for row in source:
        identifier = row.get("source_file")
        canonical = aliases.get(identifier) if isinstance(identifier, str) else None
        canonical = gaussian_stem_to_gv.get(canonical, canonical)
        name = goodvibes_by_stem.get(canonical)
        if name is None: raise StageFormatFailure("thermochemistry_source", f"unknown or ambiguous thermochemistry source: {identifier!r}")
        if name in submitted_sources: raise StageFormatFailure("thermochemistry_source", f"duplicated thermochemistry source: {identifier!r}")
        submitted_sources[name] = row
    if set(submitted_sources) != set(expected):
        raise StageFailure("thermochemistry_source", "thermochemistry source row names are incomplete")

    source_parameters = []
    for name, fixed in expected.items():
        row = submitted_sources[name]
        if "source_energy_label" in row and row["source_energy_label"] != fixed["source_energy_label"]:
            raise StageFailure("thermochemistry_source", f"{name}: source_energy_label differs from source")
        close_field("thermochemistry_source", row.get("temperature_K"), fixed["temperature_K"], 0.0,
                    f"{name} temperature_K")
        close_field("thermochemistry_source", row.get("concentration_mol_L"), fixed["concentration_mol_L"], 0.0,
                    f"{name} concentration_mol_L")
        close_field("thermochemistry_source", row.get("qh_G_T_hartree"), fixed["qh_G_T_hartree"], 0.00000051,
                    f"{name} qh_G_T_hartree")
        close_field("thermochemistry_source", row.get("scale_factor"), fixed["scale_factor"], 0.0,
                    f"{name} scale_factor")
        close_field("thermochemistry_source", row.get("frequency_cutoff_cm-1"), fixed["frequency_cutoff_cm-1"], 0.0,
                    f"{name} frequency_cutoff_cm-1")
        energy_units = {"au", "a.u.", "eh", "hartree", "hartrees"}
        expected_unit = _label(fixed["reported_energy_unit"])
        if (("standard_state" in row and not _source_evidence_matches({"standard_state": row["standard_state"]},
                                         {"standard_state": fixed["standard_state"]}, f"{name}.standard_state"))
                or ("energy_unit" in row and _label(row["energy_unit"]) not in energy_units)
                or expected_unit not in energy_units):
            raise StageFailure("thermochemistry_source", f"{name}: standard_state or energy_unit differs from source")
        source_parameters.append({"source_file": name, "temperature_K": fixed["temperature_K"],
                                  "concentration_mol_L": fixed["concentration_mol_L"],
                                  "scale_factor": fixed["scale_factor"],
                                  "frequency_cutoff_cm-1": fixed["frequency_cutoff_cm-1"]})
    report["criteria"]["thermochemistry_source"] = "PASS"
    report["thermochemistry_audit"] = {"source_parameters": source_parameters,
                                       "conventions": [], "qs_methods": [],
                                       "derived_energies": [], "barrier_claims": []}

    convention_audit = []
    for name, row in submitted_sources.items():
        if "convention" in row and not _qh_convention(row["convention"]):
            raise StageFailure("thermochemistry_convention", f"{name}: convention must identify qh-G(T)")
        convention_audit.append({"source_file": name, "status": "PASS"})
        report["thermochemistry_audit"]["conventions"] = convention_audit
    report["criteria"]["thermochemistry_convention"] = "PASS"
    report["thermochemistry_audit"]["conventions"] = convention_audit

    method_audit = []
    for name, fixed in expected.items():
        row = submitted_sources[name]
        try:
            actual_method = normalize_qs_method(row.get("qs_treatment"))
            expected_method = normalize_qs_method(fixed["qs_treatment"])
        except ReviewRequired as exc:
            raise StageReviewRequired("qs_method_identity", f"{name}: {exc}") from exc
        except ScienceFailure as exc:
            raise StageFailure("qs_method_identity", f"{name}: {exc}") from exc
        if actual_method["method"] != expected_method["method"]:
            raise StageFailure("qs_method_identity",
                               f"{name}: qs_treatment method is {actual_method['method']}, source method is {expected_method['method']}")
        method_audit.append({"source_file": name, "method": actual_method["method"],
                             "annotation": actual_method["annotation"], "status": "PASS"})
        report["thermochemistry_audit"]["qs_methods"] = method_audit
    report["criteria"]["qs_method_identity"] = "PASS"
    report["thermochemistry_audit"]["qs_methods"] = method_audit

    gaussian_to_goodvibes_stem = {join["gaussian_stem"]: join["goodvibes_stem"]
                                  for join in facts["source_joins"]}
    def species_stem(value: str) -> str:
        stem = aliases.get(value)
        if stem is None: raise StageFormatFailure("derived_energy", f"unknown or ambiguous species source: {value!r}")
        stem = gaussian_to_goodvibes_stem.get(stem, stem)
        if stem not in goodvibes_by_stem: raise StageFormatFailure("derived_energy", f"source is not a thermochemical species: {value!r}")
        return stem
    expected_diffs = facts["candidate_differences"]
    gaussian_by_gv = {join["goodvibes_stem"]: next(item for item in facts["gaussian"]
                       if item["source_file"].endswith(f"-{join['gaussian_stem']}.log"))
                       for join in facts["source_joins"]}
    context_by_gv = {join["goodvibes_stem"]: REACTIVE_ROLE_MAPS[join["gaussian_stem"]]["context_id"]
                     for join in facts["source_joins"]}
    thermo_by_stem = {stem: next(item for item in facts["goodvibes"] if item["source_file"] == name)
                      for stem, name in goodvibes_by_stem.items()}
    def comparison_key(source_ids, coefficients):
        return tuple(sorted(zip(source_ids, coefficients)))
    required_keys = {comparison_key([species_stem(item) for item in fixed["source_ids"]], fixed["coefficients"])
                     for fixed in expected_diffs}
    parsed_rows = []
    observed_keys = set()
    for row in differences:
        try:
            source_ids = [species_stem(item) for item in
                          _split_csv_values(row.get("source_ids"), "candidate-difference source_ids")]
        except FormatFailure as exc:
            raise StageFormatFailure("derived_energy", str(exc)) from exc
        if len(source_ids) != len(set(source_ids)):
            raise StageFailure("derived_energy", "candidate-difference source_ids must not repeat within a row")
        try:
            coefficients = _parse_coefficients(row.get("coefficients"))
        except FormatFailure as exc:
            raise StageFormatFailure("derived_energy", str(exc)) from exc
        if len(coefficients) != len(source_ids):
            raise StageFailure("derived_energy", "each candidate-difference source ID needs one paired coefficient")
        key = comparison_key(source_ids, coefficients)
        if key in observed_keys:
            raise StageFormatFailure("derived_energy", "duplicated candidate comparison after source normalization")
        observed_keys.add(key)
        if not coefficients or 0 in coefficients or not (min(coefficients) < 0 < max(coefficients)):
            raise StageFailure("derived_energy", "candidate comparison requires nonzero reactant and product coefficients")
        if len({context_by_gv[stem] for stem in source_ids}) != 1:
            raise StageFailure("derived_energy", "candidate comparison mixes reaction contexts")
        balance = Counter()
        charge = 0
        for stem, coefficient in zip(source_ids, coefficients):
            gaussian = gaussian_by_gv[stem]
            for atom in gaussian["geometry"]["atoms"]: balance[atom["element"]] += coefficient
            charge += coefficient * gaussian["charge"]
        if any(balance.values()) or charge:
            raise StageFailure("derived_energy", "candidate comparison does not balance source elements and charge")
        conditions = ("temperature_K", "concentration_mol_L", "reported_energy_unit", "qs_treatment",
                      "frequency_cutoff_cm-1", "standard_state", "scale_factor")
        terms = [thermo_by_stem[stem] for stem in source_ids]
        if any(any(term[field] != terms[0][field] for field in conditions) for term in terms[1:]):
            raise StageFailure("derived_energy", "candidate comparison mixes thermochemical conditions")
        for field, tolerance in (("temperature_K", 1e-6), ("concentration_mol_L", 1e-6),
                                 ("scale_factor", 1e-6), ("frequency_cutoff_cm-1", 1e-6)):
            if row.get(field, "").strip():
                close_field("derived_energy", row[field], terms[0][field], tolerance,
                            f"{source_ids} {field} for candidate comparison")
        value = sum(term["qh_G_T_hartree"] * float(coefficient) for term, coefficient in zip(terms, coefficients)) * HARTREE_TO_KCAL
        close_field("derived_energy", row.get("candidate_delta_g_kcal_mol"), value, TOL,
                    f"{source_ids} candidate_delta_g_kcal_mol")
        if not isinstance(row.get("identity_status"), str) or not row["identity_status"].strip():
            raise StageFailure("derived_energy", f"{source_ids}: identity_status is required")
        parsed_rows.append((row, source_ids, coefficients, value, key))
    energy_audit = []
    barrier_audit = []
    for name, row in submitted_sources.items():
        try:
            claim = normalize_barrier_claim(row.get("reaction_barrier_kcal_mol"),
                                            row.get("reaction_barrier_status"))
        except ReviewRequired as exc:
            raise StageReviewRequired("barrier_claim", f"{name}: {exc}") from exc
        except ScienceFailure as exc:
            raise StageFailure("barrier_claim", f"{name}: {exc}") from exc
        if claim["local_candidate_comparison"]:
            raise StageFailure("barrier_claim", f"{name}: source rows cannot claim a candidate barrier comparison")
        barrier_audit.append({"source_file": name, "claim_scope": "source_record", **claim})
    for row, source_ids, coefficients, value, key in parsed_rows:
        energy_audit.append({"source_ids": source_ids,
                             "coefficients": [int(x) if x.denominator == 1 else float(x) for x in coefficients],
                             "exact_coefficient_fractions": [str(x) for x in coefficients],
                             "candidate_delta_g_kcal_mol": value,
                             "context_id": context_by_gv[source_ids[0]],
                             "required_saddle_comparison": key in required_keys, "status": "PASS"})
    report["thermochemistry_audit"]["derived_energies"] = energy_audit
    missing = required_keys - observed_keys
    if missing:
        report["thermochemistry_audit"]["missing_required_comparisons"] = [dict(key) for key in sorted(missing)]
        raise StageMissingScientificEvidence("derived_energy", f"MISSING_REQUIRED_COMPARISON: {sorted(missing)}")
    report["criteria"]["derived_energy"] = "PASS"
    report["thermochemistry_audit"]["derived_energies"] = energy_audit
    barrier_audit = []
    for row, source_ids, coefficients, value, key in parsed_rows:
        ids = ",".join(source_ids)
        try:
            claim = normalize_barrier_claim(row.get("reaction_barrier_kcal_mol"),
                                            row.get("reaction_barrier_status"))
        except ReviewRequired as exc:
            raise StageReviewRequired("barrier_claim", f"{ids}: {exc}") from exc
        except ScienceFailure as exc:
            raise StageFailure("barrier_claim", f"{ids}: {exc}") from exc
        barrier_audit.append({"source_ids": source_ids, **claim})
        report["thermochemistry_audit"]["barrier_claims"] = barrier_audit
    report["criteria"]["barrier_claim"] = "PASS"
    return {"source_parameters": source_parameters, "conventions": convention_audit,
            "qs_methods": method_audit, "derived_energies": energy_audit,
            "barrier_claims": barrier_audit}

def _chemical_claims(row: dict, context: str, facts: dict) -> dict:
    """Verify bounded chemical propositions, not the wording of an explanation."""
    label = f"mechanism.{context}"
    if row.get("claim_scope") != "local_context":
        raise ScienceFailure(f"{label}: only local_context is established by the supplied evidence")
    mechanism = row.get("mechanism")
    if not isinstance(mechanism, str):
        raise FormatFailure(f"{label}: mechanism must be a chemical candidate label")
    if mechanism not in {"SNAr_candidate", "stepwise_SNAr_candidate", "unresolved"}:
        raise ScienceFailure(f"{label}: mechanism must be a bounded SNAr candidate or unresolved; submitted={mechanism!r}")
    raw_evidence = row.get("mechanism_evidence")
    if not isinstance(raw_evidence, str):
        raise FormatFailure(f"{label}: mechanism_evidence must be a JSON object in its CSV cell")
    evidence = _parse_json(raw_evidence, f"{label}.mechanism_evidence")
    if not isinstance(evidence, dict) or set(evidence) != {"local_steps", "intermediate_candidates"}:
        raise FormatFailure(f"{label}: mechanism_evidence needs local_steps and intermediate_candidates")
    aliases = _source_aliases(facts)
    logs = {Path(g["source_file"]).stem.rsplit("-", 1)[-1]: g for g in facts["gaussian"]}
    def source(raw):
        stem = aliases.get(raw) if isinstance(raw, str) else None
        if stem not in logs:
            raise FormatFailure(f"{label}: cite a supplied Gaussian filename or unambiguous stem; submitted={raw!r}")
        if REACTIVE_ROLE_MAPS[stem]["context_id"] != context:
            raise ScienceFailure(f"{label}: {raw} belongs to a different reaction context")
        return stem
    expected_steps, intermediates, projections = {}, set(), {}
    for stem, record in logs.items():
        mapping = MAPPED.get(stem)
        if mapping is None or mapping["context_id"] != context:
            continue
        count = record["formal_negative_mode_count"]
        if count == 0:
            intermediates.add(stem)
        elif count == 1:
            geometry = {a["atom_index_1based"]: a["xyz_angstrom"] for a in record["geometry"]["atoms"]}
            projection = _project(geometry, record["negative_modes"][0], mapping)
            cn, cx = projection["projected_C_Nu_change_raw"], projection["projected_C_X_change_raw"]
            # The normal-mode sign is arbitrary. Only relative magnitudes and
            # opposite bond-length changes support these local candidate roles.
            if cn * cx >= 0 or abs(cn) == abs(cx):
                raise InfraFailure(f"{label}: source mode does not resolve a dominant substitution coordinate")
            expected_steps[stem] = "addition_like" if abs(cn) > abs(cx) else "elimination_like"
            projections[stem] = {"abs_C_Nu_projection": abs(cn), "abs_C_X_projection": abs(cx)}
    steps = evidence["local_steps"]
    if not isinstance(steps, dict):
        raise FormatFailure(f"{label}: local_steps must map Gaussian sources to candidate roles")
    actual_steps = {}
    for raw, role in steps.items():
        stem = source(raw)
        if stem in actual_steps:
            raise FormatFailure(f"{label}: duplicated source after normalization: {raw}")
        actual_steps[stem] = role
    if set(actual_steps) != set(expected_steps):
        raise MissingScientificEvidence(f"{label}: local_steps must cover all one-negative-mode complete complexes; submitted={sorted(actual_steps)}, required={sorted(expected_steps)}")
    for stem, expected in expected_steps.items():
        if actual_steps[stem] != expected:
            raise ScienceFailure(f"{label}.{stem}: local candidate role contradicts mapped mode; submitted={actual_steps[stem]!r}, source_supported={expected!r}, projections={projections[stem]}")
    raw_intermediates = evidence["intermediate_candidates"]
    if not isinstance(raw_intermediates, list):
        raise FormatFailure(f"{label}: intermediate_candidates must be an array")
    actual_intermediates = [source(raw) for raw in raw_intermediates]
    if len(actual_intermediates) != len(set(actual_intermediates)):
        raise FormatFailure(f"{label}: duplicated intermediate candidate")
    if set(actual_intermediates) != intermediates:
        raise ScienceFailure(f"{label}: intermediate candidates must be the complete zero-negative-mode records; submitted={actual_intermediates}, source_supported={sorted(intermediates)}")
    sequential = (list(expected_steps.values()).count("addition_like") == 1
                  and list(expected_steps.values()).count("elimination_like") == 1
                  and len(intermediates) == 1)
    if mechanism == "stepwise_SNAr_candidate" and not sequential:
        raise ScienceFailure(f"{label}: no addition/intermediate/elimination candidate set supports a stepwise candidate")
    raw_conditional = row.get("model_conditional_RDS")
    if not isinstance(raw_conditional, str):
        raise FormatFailure(f"{label}: model_conditional_RDS must be a JSON object in its CSV cell")
    conditional = _parse_json(raw_conditional, f"{label}.model_conditional_RDS")
    if not isinstance(conditional, dict) or set(conditional) != {"model", "step"}:
        raise FormatFailure(f"{label}: model_conditional_RDS needs model and step")
    model, step = conditional["model"], conditional["step"]
    if not isinstance(model, str) or not isinstance(step, str):
        raise FormatFailure(f"{label}: model and step must be string labels")
    if step not in {"addition", "elimination", "unresolved"}:
        raise ScienceFailure(f"{label}: conditional step is not a chemical step of the stated model; submitted={step!r}")
    local_barriers = None
    if model == "none":
        expected_step = "unresolved"
    elif model == "irreversible_equal_prefactors_unit_activity":
        if not sequential:
            raise MissingScientificEvidence(f"{label}: the declared two-step model lacks an addition/intermediate/elimination candidate set")
        joins = {x["gaussian_stem"]: x["goodvibes_stem"] for x in facts["source_joins"]}
        therm = {Path(g["source_file"]).stem.rsplit("-", 1)[-1]: g for g in facts["goodvibes"]}
        addition = next(stem for stem, role in expected_steps.items() if role == "addition_like")
        elimination = next(stem for stem, role in expected_steps.items() if role == "elimination_like")
        intermediate = next(iter(intermediates))
        add_gv = joins[addition]
        # Reactant references are derived by the independent source parser from
        # source stationarity and exact elemental/charge balance, not a filename label.
        add_comparison = next(x for x in facts["candidate_differences"] if x["source_ids"][0] == add_gv)
        terms = [therm[joins[x]] for x in (addition, elimination, intermediate)]
        convention = ("temperature_K", "concentration_mol_L", "qs_treatment", "scale_factor", "frequency_cutoff_cm-1")
        if any(any(a[k] != terms[0][k] for k in convention) for a in terms[1:]):
            raise InfraFailure(f"{label}: trusted candidate thermochemistry conditions differ")
        # For the declared irreversible two-waiting-time model, the observable
        # is inverse mean completion time, k_add*k_elim/(k_add+k_elim).
        # With equal prefactors and unit activity, the larger local TST
        # barrier has the larger degree of control of this observable only.
        local_barriers = {"addition": add_comparison["candidate_delta_g_kcal_mol"],
                          "elimination": (terms[1]["qh_G_T_hartree"] - terms[2]["qh_G_T_hartree"]) * HARTREE_TO_KCAL}
        expected_step = ("unresolved" if math.isclose(local_barriers["addition"], local_barriers["elimination"], rel_tol=0.0, abs_tol=TOL)
                         else max(local_barriers, key=local_barriers.get))
    else:
        raise StageReviewRequired("mechanism_claims", f"{label}: model {model!r} needs independent validation; no automatic chemical verdict")
    if step != expected_step:
        raise ScienceFailure(f"{label}: conditional RDS contradicts the declared model; submitted={step!r}, expected={expected_step!r}, candidate_barriers_kcal_mol={local_barriers}")
    return {"mechanism": mechanism, "local_steps": actual_steps,
            "intermediate_candidates": sorted(intermediates), "mode_basis": projections,
            "conditional_model": model, "conditional_step": step,
            "candidate_local_barriers_kcal_mol": local_barriers,
            "conditional_observable": "inverse_mean_completion_time" if local_barriers is not None else None,
            "conditional_rate_law": "k_add*k_elim/(k_add+k_elim)" if local_barriers is not None else None,
            "connected_path_established": False, "global_RDS_established": False}


def _compare_mechanism(root: Path, facts: dict, audited_sources: list[dict], energy_audit: list[dict]) -> list[dict]:
    path = _required_file(root, "mechanism.csv")
    required = {"context_id", "claim_scope", "reactive_site", "identity_status", "mechanism",
                "mechanism_evidence", "rate_determining_step", "barrier_status", "model_conditional_RDS"}
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            names = reader.fieldnames or []
            columns = set(names)
            if len(names) != len(columns):
                raise FormatFailure("mechanism.csv has duplicate columns")
            if "rate_determining_step (global)" in columns:
                columns.add("rate_determining_step")
            if not required.issubset(columns):
                raise FormatFailure("mechanism.csv is missing required columns")
            rows = list(reader)
            if any(None in row for row in rows):
                raise FormatFailure("mechanism.csv contains rows with extra undeclared fields")
            for row in rows:
                if "rate_determining_step (global)" in row:
                    alternate = row["rate_determining_step (global)"]
                    if "rate_determining_step" in row and row["rate_determining_step"] != alternate:
                        raise FormatFailure("mechanism.csv has conflicting global RDS column aliases")
                    row["rate_determining_step"] = alternate
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ScienceFailure(f"mechanism.csv unreadable: {exc}") from exc
    if len(rows) != 2 or any(not isinstance(row.get("claim_scope"), str)
                             or not row["claim_scope"].strip() for row in rows):
        raise ScienceFailure("mechanism.csv must have exactly one scoped row per supplied context")
    keyed = {row.get("context_id"): row for row in rows}
    barrier_audit = []
    context_map = {"E1-entry-28": ("s456", 298.0), "E1-entry-90": ("s1584", 273.0)}
    if set(keyed) != set(context_map):
        raise ScienceFailure("mechanism.csv context rows must match the two supplied records exactly")
    context_sources = {}
    for source in audited_sources:
        context = source.get("context_id")
        if context:
            context_sources.setdefault(context, {context}).update({
                _source_aliases(facts)[source["source_file"]], source["verified_goodvibes_stem"]})
    for context_id, (source_file, temp) in context_map.items():
        differences = [item for item in energy_audit if item["context_id"] == context_id]
        row = keyed[context_id]
        linked = context_sources.get(context_id, set())
        if source_file not in linked: raise ScienceFailure(f"{context_id}: no uniquely audited source mapping supports this context")
        if row.get("source_ids") and str(row["source_ids"]).strip().lower() not in {"null", ""}:
            citations, _ = _limitation_sources(row["source_ids"], _source_aliases(facts), f"mechanism.{context_id}.source_ids")
            if not citations.issubset(linked): raise ScienceFailure(f"{context_id}: supplied sources conflict with the audited context")
        else: citations = linked
        path = row.get("path_connectivity")
        if path is not None and (not isinstance(path, str) or not path.strip()): raise FormatFailure(f"{context_id}: path assessment is required")
        if path is not None and not (_unresolved(path) or _label(_status_head(path)) in {"unvalidated", "not validated", "no validated path"}):
            if _label(_status_head(path)) in {"validated", "connected", "verified", "irc validated"}:
                raise ScienceFailure(f"{context_id}: validated path connectivity is not established")
            raise StageReviewRequired("mechanism_claims", f"{context_id}: unrecognized path status; submitted={path!r}")
        if path is None:
            path_sources = set()
            if (root / "failures.jsonl").is_file():
                for diagnostic in _jsonl(root / "failures.jsonl", "failures.jsonl"):
                    if _limitation_topic(diagnostic, "failures.jsonl") == "path_connectivity":
                        linked, _ = _limitation_sources(diagnostic.get("source_ids"), _source_aliases(facts), "failures.jsonl.source_ids")
                        path_sources |= linked
            if not {"s456", "s797", "s1584"}.issubset(path_sources):
                raise FormatFailure(f"{context_id}: state path_connectivity once in the mechanism table")
        try:
            barrier_claim = normalize_barrier_claim(None, row.get("barrier_status"))
        except ReviewRequired as exc:
            raise StageReviewRequired("barrier_claim", f"{context_id}: {exc}") from exc
        except ScienceFailure as exc:
            raise StageFailure("barrier_claim", f"{context_id}: {exc}") from exc
        barrier_audit.append({"context_id": context_id, **barrier_claim})
        identity = row.get("identity_status")
        if identity not in {"supported_by_atom_inventory_and_reactive_geometry", "ambiguous"}:
            raise ScienceFailure(f"{context_id}: identity status must be evidence-based or explicitly ambiguous")
        chemical_claims = _chemical_claims(row, context_id, facts)
        barrier_audit[-1]["chemical_claims"] = chemical_claims
        if identity == "supported_by_atom_inventory_and_reactive_geometry":
            expected_map = MAPPED[source_file]
            expected_atoms = {"carbon": expected_map["carbon"], "nucleophile": expected_map["nucleophile"],
                              "leaving_group": expected_map["leaving_group"]}
            site = _parse_reactive_site(row.get("reactive_site", ""))
            source_record = next(item for item in facts["gaussian"] if item["source_file"].endswith(f"{source_file}.log"))
            source_atoms = {item["atom_index_1based"]: item["element"] for item in source_record["geometry"]["atoms"]}
            expected_symbols = {role: source_atoms.get(index) for role, index in expected_atoms.items()}
            if (site["carbon_index"] != expected_atoms["carbon"] or site["nucleophile_index"] != expected_atoms["nucleophile"]
                    or site["leaving_group_index"] != expected_atoms["leaving_group"]
                    or expected_symbols["carbon"] != "C" or expected_symbols["nucleophile"] not in {"N", "O"}
                    or site["carbon_symbol"] != expected_symbols["carbon"]
                    or site["leaving_group_symbol"] != expected_symbols["leaving_group"]
                    or expected_symbols["leaving_group"] not in {"F", "Cl"}):
                raise ScienceFailure(f"{context_id}: reactive-site roles, element labels, and indices must match source geometry")
            if row.get("dg_kcal_mol", "").strip():
                submitted_dg = _finite(row["dg_kcal_mol"], f"{context_id} candidate-state ΔG")
                if not any(math.isclose(submitted_dg, difference["candidate_delta_g_kcal_mol"],
                                        rel_tol=0.0, abs_tol=TOL)
                           for difference in differences):
                    raise ScienceFailure(f"{context_id} candidate-state ΔG")
            if row.get("convention", "").strip():
                if (not _qh_convention(row.get("convention"))
                        or not _one_molar(row.get("convention"))):
                    raise ScienceFailure(f"{context_id}: mechanism row must state the GoodVibes convention")
        else:
            if row.get("reactive_site", "").strip() or not _unresolved(row.get("mechanism")):
                raise ScienceFailure(f"{context_id}: ambiguous identity must keep mapping and mechanism unresolved")
            if barrier_claim["local_candidate_comparison"]:
                raise ScienceFailure(f"{context_id}: an unassigned context cannot carry a local candidate comparison")
            if row.get("dg_kcal_mol", "").strip().lower() not in {"", "null", "unresolved"}:
                raise ScienceFailure(f"{context_id}: candidate-state ΔG cannot be assigned to an unjoined context")
        if not isinstance(row.get("rate_determining_step"), str) or not row["rate_determining_step"].strip():
            raise FormatFailure(f"{context_id}: a global RDS assessment is required")
        if not _unresolved(row.get("rate_determining_step")):
            step = _label(_status_head(row.get("rate_determining_step")))
            if step in MAPPED or step in {"addition", "elimination", "nucleophilic addition", "fluoride elimination", "chloride elimination", "departure", "substitution"}:
                raise ScienceFailure(f"{context_id}: global rate-determining step is not established")
            raise StageReviewRequired("mechanism_claims", f"{context_id}: global RDS wording is not a supported explicit status; submitted={row.get('rate_determining_step')!r}")
        if row.get("temperature_K", "").strip(): _close(row["temperature_K"], temp, 0.0, f"{context_id} temperature")
    return barrier_audit


def _sequence_values(value: Any, label: str) -> list:
    if isinstance(value, str):
        text = value.strip()
        values = _parse_json(text, label) if text.startswith("[") else re.split(r"[;,]", text)
    else:
        values = value
    if not isinstance(values, list) or not values:
        raise FormatFailure(f"{label}: provide a nonempty JSON array or delimited list")
    return values


def _split_csv_values(value: Any, label: str) -> list[str]:
    values = _sequence_values(value, label)
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise FormatFailure(f"{label}: source references must be nonempty strings")
    return [item.strip() for item in values]


def _parse_coefficients(value: Any) -> list[Fraction]:
    result = []
    for token in _sequence_values(value, "candidate-difference coefficients"):
        if isinstance(token, bool) or not isinstance(token, (str, int, float)):
            raise FormatFailure("stoichiometric coefficients must be numbers or numeric strings")
        try:
            number = Decimal(token.literal if isinstance(token, ObservedFloat) else str(token).strip())
        except InvalidOperation as exc:
            raise FormatFailure("stoichiometric coefficients must be numeric") from exc
        if not number.is_finite() or not math.isfinite(float(number)):
            raise FormatFailure("stoichiometric coefficients must be finite")
        result.append(Fraction(number))
    return result


def _parse_reactive_site(value: Any) -> dict:
    if not isinstance(value, str):
        raise FormatFailure("reactive_site must serialize the carbon, nucleophile, and leaving-group roles")
    match = re.fullmatch(r"\s*C\s*(\d+)\s*[/,;]\s*Nu\s*(\d+)\s*[/,;]\s*(Cl|F)\s*(\d+)\s*", value)
    if not match:
        raise FormatFailure("reactive_site must use element/index labels for C, Nu, and the leaving group")
    return {"carbon_symbol": "C", "carbon_index": int(match.group(1)), "nucleophile_role": "Nu",
            "nucleophile_index": int(match.group(2)), "leaving_group_symbol": match.group(3),
            "leaving_group_index": int(match.group(4))}


_LIMIT_TOPICS = {"global_rds", "path_connectivity", "native_execution"}
_LEGACY_TOPIC_CODES = {
    "global_rate_determining_step_unresolved": "global_rds",
    "formal_barrier_path_connection_missing": "path_connectivity",
    "native_3887010_engine_failure_not_scheduler_cause": "native_execution",
}


def _limitation_topic(row: dict, label: str) -> str | None:
    code = row.get("reason_code")
    if not isinstance(code, str) or not code.strip():
        raise FormatFailure(f"{label}: reason_code must be a nonempty record identifier")
    encoded = _LEGACY_TOPIC_CODES.get(code)
    for topic in _LIMIT_TOPICS:
        if code == topic or re.fullmatch(re.escape(topic) + r"[_:/.-].+", code):
            encoded = topic
    explicit = row.get("topic")
    if explicit is not None:
        if not isinstance(explicit, str) or not explicit.strip():
            raise FormatFailure(f"{label}: topic must be a nonempty identifier")
        if encoded is not None and explicit != encoded:
            raise FormatFailure(f"{label}: explicit topic conflicts with reason_code topic")
    return explicit if explicit is not None else encoded


def _limitation_sources(value: Any, aliases: dict, label: str) -> tuple[set[str], int]:
    values = _split_csv_values(value, label)
    unknown = [item for item in values if item not in aliases]
    if unknown:
        raise FormatFailure(f"{label}: unknown or ambiguous source aliases: {unknown}")
    canonical = {aliases[item] for item in values}
    return canonical, len(values) - len(canonical)


def check_submission(submission: Path, assets: Path, refs_path: Path) -> dict:
    try:
        try:
            refs = json.loads(refs_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise InfraFailure(f"trusted tests/refs.json is missing or invalid: {exc}") from exc
        if not isinstance(refs, dict):
            raise InfraFailure("trusted tests/refs.json must be a JSON object")
        if (refs.get("schema") != "case01-trusted-source-pins/v4" or refs.get("version") != "8"
                or refs.get("case_id") != CASE_ID):
            raise InfraFailure("trusted Case01 refs identity mismatch")
        facts = build_source_facts(assets, refs)
    except (SourceError, OSError, UnicodeError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        raise InfraFailure(str(exc)) from exc
    if not submission.is_dir() or submission.is_symlink():
        raise ScienceFailure("final/ directory is missing or unsafe")
    entries = list(submission.iterdir())
    actual = {p.name for p in entries if p.is_file() and not p.is_symlink()}
    if any(not p.is_file() or p.is_symlink() for p in entries):
        raise ScienceFailure("final/ may contain only regular deliverable files")
    if not REQUIRED.issubset(actual):
        raise ScienceFailure(f"final/ is missing required deliverables; actual={sorted(actual)}")
    for name in REQUIRED:
        _required_file(submission, name)
    criteria = {
        "source_observations": "NOT_RUN", "stationary_point_interpretation": "NOT_RUN",
        "source_inventory_complete": "NOT_RUN", "thermochemistry_source": "NOT_RUN",
        "thermochemistry_convention": "NOT_RUN", "qs_method_identity": "NOT_RUN",
        "derived_energy": "NOT_RUN", "barrier_claim": "NOT_RUN",
        "mechanism_claims": "NOT_RUN", "native_failure_diagnosis": "NOT_RUN",
        "limitation_report": "NOT_RUN",
    }
    report = {"status": "PASS", "coverage": "trusted_source_recomputation_and_structured_chemical_claims_v7",
        "public_source_facts_recomputed_by_grader": True,
        "candidate_analyze_executed_by_grader": False,
        "submitted_code_execution_verified": False,
        "candidate_internals_verified": False,
        "optional_raw_displays_assessed": False,
        "free_explanatory_text_semantics_assessed": False,
        "criteria": criteria,
        "formal_reaction_barriers_claimed": False}
    try:
        stationary_point_interpretation_audit, native_by_job = _compare_audit(submission, facts, report.setdefault("native_identity_audit", []))
    except ReviewRequired as exc:
        criteria["source_observations"] = "REVIEW_REQUIRED"
        report.update(status="REVIEW_REQUIRED", error=str(exc))
        return report
    except ScienceFailure as exc:
        criteria["source_observations"] = "FAIL"
        kind = "MISSING_SCIENTIFIC_EVIDENCE" if isinstance(exc, MissingScientificEvidence) else "OUTPUT_FORMAT" if isinstance(exc, FormatFailure) else "SCIENTIFIC_CONTRADICTION"
        report.update(status="FAIL" if isinstance(exc, FormatFailure) else "SCIENTIFIC_FAIL", error=str(exc), failure_kind=kind)
        return report
    interpretation_failures = [
        f"{entry['source_file']}: {entry['interpretation_error']}"
        for entry in stationary_point_interpretation_audit
        if entry["interpretation_status"] == "FAIL"
    ]
    report["stationary_point_interpretation_audit"] = stationary_point_interpretation_audit
    criteria["source_observations"] = "PASS"
    criteria["source_inventory_complete"] = "PASS"
    interpretation_reviews = [entry for entry in stationary_point_interpretation_audit if entry["interpretation_status"] == "REVIEW_REQUIRED"]
    criteria["stationary_point_interpretation"] = "FAIL" if interpretation_failures else "REVIEW_REQUIRED" if interpretation_reviews else "PASS"
    if not interpretation_failures and interpretation_reviews:
        report.update(status="REVIEW_REQUIRED", error=f"unrecognized stationary assessment: {[(entry['source_file'], entry['submitted_interpretation']) for entry in interpretation_reviews]}")
        return report
    if interpretation_failures:
        report["status"] = "SCIENTIFIC_FAIL"
        report["error"] = "; ".join(interpretation_failures)
        return report
    try:
        _compare_native(native_by_job, facts)
    except ReviewRequired as exc:
        criteria["native_failure_diagnosis"] = "REVIEW_REQUIRED"
        report.update(status="REVIEW_REQUIRED", error=str(exc))
        return report
    except ScienceFailure as exc:
        criteria["native_failure_diagnosis"] = "FAIL"
        kind = "MISSING_SCIENTIFIC_EVIDENCE" if isinstance(exc, MissingScientificEvidence) else "OUTPUT_FORMAT" if isinstance(exc, FormatFailure) else "SCIENTIFIC_CONTRADICTION"
        report.update(status="FAIL" if isinstance(exc, FormatFailure) else "SCIENTIFIC_FAIL", error=str(exc), failure_kind=kind)
        return report
    criteria["native_failure_diagnosis"] = "PASS"
    try:
        thermo_audit = _compare_thermochemistry(submission, facts, report)
    except StageReviewRequired as exc:
        criteria[exc.stage] = "REVIEW_REQUIRED"
        report.update(status="REVIEW_REQUIRED", error=str(exc))
        return report
    except StageFailure as exc:
        criteria[exc.stage] = "FAIL"
        report.update(status="FAIL" if isinstance(exc, FormatFailure) else "SCIENTIFIC_FAIL", error=str(exc), failure_kind=("MISSING_SCIENTIFIC_EVIDENCE" if isinstance(exc, MissingScientificEvidence) else "OUTPUT_FORMAT" if isinstance(exc, FormatFailure) else "SCIENTIFIC_CONTRADICTION"))
        return report
    except ScienceFailure as exc:
        criteria["thermochemistry_source"] = "FAIL"
        report.update(status="FAIL" if isinstance(exc, FormatFailure) else "SCIENTIFIC_FAIL", error=str(exc), failure_kind=("MISSING_SCIENTIFIC_EVIDENCE" if isinstance(exc, MissingScientificEvidence) else "OUTPUT_FORMAT" if isinstance(exc, FormatFailure) else "SCIENTIFIC_CONTRADICTION"))
        return report
    report["thermochemistry_audit"] = thermo_audit
    for stage in ("thermochemistry_source", "thermochemistry_convention", "qs_method_identity", "derived_energy", "barrier_claim"):
        criteria[stage] = "PASS"
    try:
        mechanism_barriers = _compare_mechanism(submission, facts, stationary_point_interpretation_audit, thermo_audit["derived_energies"])
    except StageReviewRequired as exc:
        criteria[exc.stage] = "REVIEW_REQUIRED"
        report.update(status="REVIEW_REQUIRED", error=str(exc))
        return report
    except StageFailure as exc:
        criteria[exc.stage] = "FAIL"
        report.update(status="FAIL" if isinstance(exc, FormatFailure) else "SCIENTIFIC_FAIL", error=str(exc), failure_kind=("MISSING_SCIENTIFIC_EVIDENCE" if isinstance(exc, MissingScientificEvidence) else "OUTPUT_FORMAT" if isinstance(exc, FormatFailure) else "SCIENTIFIC_CONTRADICTION"))
        return report
    except ScienceFailure as exc:
        criteria["mechanism_claims"] = "FAIL"
        report.update(status="FAIL" if isinstance(exc, FormatFailure) else "SCIENTIFIC_FAIL", error=str(exc), failure_kind=("MISSING_SCIENTIFIC_EVIDENCE" if isinstance(exc, MissingScientificEvidence) else "OUTPUT_FORMAT" if isinstance(exc, FormatFailure) else "SCIENTIFIC_CONTRADICTION"))
        return report
    report["mechanism_barrier_audit"] = mechanism_barriers
    criteria["mechanism_claims"] = "PASS"
    all_barrier_claims = thermo_audit["barrier_claims"] + mechanism_barriers
    if any(claim["formal_claim"] or claim["canonical_status"] != "unassigned"
           for claim in all_barrier_claims):
        criteria["barrier_claim"] = "FAIL"
        report.update(status="SCIENTIFIC_FAIL", error="barrier_claim: cross-table formal reaction barrier claim is unsupported")
        return report
    report["barrier_cross_table_consistency"] = "PASS"
    report["barrier_claim_audit"] = all_barrier_claims
    report["limitation_audit"] = {"evidence_scope": "mechanism_path_and_RDS_plus_native_causality",
                                  "separate_inventory_required": False,
                                  "supplementary_diagnostics_automatically_assessed": False}
    criteria["limitation_report"] = "PASS"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", type=Path, default=None)
    parser.add_argument("--assets", type=Path, default=None)
    parser.add_argument("--refs", type=Path, default=None)
    args = parser.parse_args(argv)
    app = Path(os.environ.get("APP", "/app"))
    tests = Path(os.environ.get("TESTS", "/tests"))
    assets = args.assets or app / "assets"
    submission = args.submission or app / "final"
    refs = args.refs or tests / "refs.json"
    try:
        result = check_submission(submission, assets, refs)
    except InfraFailure as exc:
        print(json.dumps({"status": "INFRA_ERROR", "error": str(exc)}), file=sys.stderr)
        return 2
    except FormatFailure as exc:
        print(json.dumps({"status": "FAIL", "failure_kind": "OUTPUT_FORMAT", "error": str(exc)}))
        return 1
    except ScienceFailure as exc:
        print(json.dumps({"status": "SCIENTIFIC_FAIL", "failure_kind": "OUTPUT_FORMAT" if isinstance(exc, FormatFailure) else "SCIENTIFIC_CONTRADICTION", "error": str(exc)}))
        return 1
    except ReviewRequired as exc:
        print(json.dumps({"status": "REVIEW_REQUIRED", "error": str(exc)}))
        return 11
    except Exception as exc:
        print(json.dumps({"status": "INFRA_ERROR", "failure_kind": "TRUSTED_EXECUTION", "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 2
    if result["status"] in {"SCIENTIFIC_FAIL", "FAIL"}:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 1
    if result["status"] == "REVIEW_REQUIRED":
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 11
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
