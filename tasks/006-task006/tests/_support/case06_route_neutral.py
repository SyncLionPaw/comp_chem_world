"""Bounded, route-neutral arithmetic for Case06 evidence tables.

This module checks submitted bytes and recomputes declared statistics only. It
does not run candidate code or certify scientific provenance/method validity.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
from pathlib import Path, PurePosixPath
from typing import Any


VERSION = "case06-route-neutral-analysis/v1"
REL_TOL = 1e-8
ABS_TOL = 1e-8
UNIT = {
    "kcal/mol": ("energy", 1.0), "kcal mol^-1": ("energy", 1.0),
    "kcal mol-1": ("energy", 1.0), "kJ/mol": ("energy", 1 / 4.184),
    "kJ mol^-1": ("energy", 1 / 4.184), "kJ mol-1": ("energy", 1 / 4.184),
}
ENERGY_STATS = {"mae", "rmse", "signed_bias", "group_macro_mae", "interval_mean_width", "paired_delta_mae"}
COUNT_STATS = {"population_n", "predicted_n", "group_n", "interval_n", "paired_n", "stratum_population_n"}
RATIO_STATS = {"usable_coverage", "r2", "interval_coverage", "interval_eligible_coverage", "paired_usable_coverage"}
SUPPORTED_STATS = ENERGY_STATS | COUNT_STATS | RATIO_STATS


def _same_num(value: float, reference: float) -> bool:
    return abs(value-reference) <= max(ABS_TOL, REL_TOL*abs(reference))


class CandidateFailure(ValueError):
    """Malformed or contradictory candidate evidence under the supported contract."""


class ReviewRequired(ValueError):
    """Valid scientific evidence uses a method outside this bounded implementation."""


class ProtectedInputError(RuntimeError):
    """A promised trusted evaluator input is missing or invalid."""


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or type(value) not in (int, float):
        raise CandidateFailure(f"{label} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise CandidateFailure(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise CandidateFailure(f"{label} must be a finite number")
    return number


def _unit(value: Any) -> tuple[str, float]:
    if not isinstance(value, str) or value not in UNIT:
        raise ReviewRequired("valid but unsupported physical quantity or unit")
    return UNIT[value]


def _energy(value: Any, unit: Any, label: str) -> float:
    dimension, scale = _unit(unit)
    if dimension != "energy":
        raise ReviewRequired("unsupported quantity dimension")
    return _finite(value, label) * scale


def _unique_ids(value: Any, valid: set[str], label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise CandidateFailure(f"{label} must be an array of nonempty IDs")
    # Set semantics: repeated references are redundant and do not add evidence.
    result = sorted(set(value))
    if not set(result) <= valid:
        raise CandidateFailure(f"{label} references an unknown ID")
    return result


def _load_table(path: Path, fmt: str) -> list[dict[str, Any]]:
    try:
        raw = path.read_bytes()
        if fmt == "json":
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError(f"duplicate JSON key: {key}")
                    result[key] = value
                return result
            rows = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                              parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        elif fmt == "csv":
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
            if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError("CSV header is empty or has duplicate column names")
            rows = list(reader)
            numeric = {"target_value", "prediction_value", "interval_lower", "interval_upper", "interval_level"}
            arrays = {"source_ids", "execution_ids"}
            for row in rows:
                for key in numeric & row.keys():
                    value = row[key]
                    if value == "":
                        row[key] = None
                    else:
                        try:
                            row[key] = json.loads(value, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
                        except ValueError:
                            raise ValueError(f"invalid numeric CSV field {key}")
                for key in arrays & row.keys():
                    try:
                        row[key] = json.loads(row[key])
                    except (TypeError, ValueError):
                        raise ValueError(f"invalid JSON-array CSV field {key}")
        else:
            raise ReviewRequired("valid unsupported table format")
    except ReviewRequired:
        raise
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        raise CandidateFailure("analysis table is missing or malformed") from exc
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CandidateFailure("analysis table must be an array of row objects")
    return rows


def _safe_table(final: Path, spec: dict[str, Any]) -> Path:
    if not isinstance(spec, dict):
        raise CandidateFailure("table declaration must be an object")
    rel = spec.get("path")
    if not isinstance(rel, str):
        raise CandidateFailure("table path is missing")
    pp = PurePosixPath(rel)
    if pp.is_absolute() or not pp.parts or any(part in ("", ".", "..") for part in pp.parts):
        raise CandidateFailure("table path must remain inside final")
    path = final.joinpath(*pp.parts)
    cur = final
    for part in pp.parts:
        cur = cur / part
        if cur.is_symlink():
            raise CandidateFailure("table path contains a symlink")
    if not path.is_file():
        raise CandidateFailure("table file is missing")
    raw = path.read_bytes()
    expected = spec.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64 or hashlib.sha256(raw).hexdigest() != expected:
        raise CandidateFailure("table SHA-256 does not match")
    return path


def _safe_evidence_file(final: Path, rel: Any, expected_sha: Any, label: str) -> Path:
    if not isinstance(rel, str) or not isinstance(expected_sha, str) or len(expected_sha) != 64 or any(c not in "0123456789abcdef" for c in expected_sha):
        raise CandidateFailure(f"{label} path or SHA-256 is malformed")
    pp = PurePosixPath(rel)
    if pp.is_absolute() or not pp.parts or any(part in ("", ".", "..") for part in pp.parts):
        raise CandidateFailure(f"{label} path must remain inside final")
    path = final.joinpath(*pp.parts)
    current = final
    for part in pp.parts:
        current = current / part
        if current.is_symlink(): raise CandidateFailure(f"{label} path contains a symlink")
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
        raise CandidateFailure(f"{label} file is missing or its SHA-256 differs")
    return path


def _safe_local_path(final: Path, rel: Any, label: str) -> Path:
    if not isinstance(rel, str): raise CandidateFailure(f"{label} must be a string path")
    pp = PurePosixPath(rel)
    if pp.is_absolute() or not pp.parts or any(part in ("", ".", "..") for part in pp.parts):
        raise CandidateFailure(f"{label} path must remain inside final")
    path = final.joinpath(*pp.parts)
    current = final
    for part in pp.parts:
        current = current / part
        if current.is_symlink(): raise CandidateFailure(f"{label} path contains a symlink")
    if not path.exists(): raise CandidateFailure(f"{label} target is missing")
    return path


def _registry(rows: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise CandidateFailure(f"provenance.{label} must be an array")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            raise CandidateFailure(f"provenance.{label} entries need nonempty typed IDs")
        previous = result.get(row["id"])
        if previous is not None and previous != row:
            raise CandidateFailure(f"provenance.{label} contains conflicting duplicate IDs")
        result[row["id"]] = row
    return result


def _normalise_rows(rows: list[dict[str, Any]], source_ids: set[str], execution_ids: set[str]) -> list[dict[str, Any]]:
    required = {"observation_id", "reaction_id", "condition_id", "group_id", "arm_id",
                "evaluation_role", "target_quantity", "target_value", "target_unit",
                "prediction_value", "prediction_unit", "source_ids", "execution_ids"}
    by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for raw in rows:
        if not required <= set(raw):
            raise CandidateFailure("analysis row is missing required fields")
        ident_fields = ("observation_id", "reaction_id", "condition_id", "group_id", "arm_id", "evaluation_role")
        if any(not isinstance(raw.get(k), str) or not raw[k].strip() for k in ident_fields):
            raise CandidateFailure("typed row identifiers must be nonempty strings")
        instance = raw.get("evaluation_instance_id", "default")
        if not isinstance(instance, str) or not instance:
            raise CandidateFailure("evaluation_instance_id must be a nonempty string")
        if raw.get("target_quantity") != "activation_free_energy":
            raise ReviewRequired("valid unsupported target quantity")
        target = _energy(raw["target_value"], raw["target_unit"], "target_value")
        pv, pu = raw.get("prediction_value"), raw.get("prediction_unit")
        abstain = pv in (None, "") and pu in (None, "")
        if not abstain and (pv in (None, "") or pu in (None, "")):
            raise CandidateFailure("prediction value and unit must both be present or absent")
        prediction = None if abstain else _energy(pv, pu, "prediction_value")
        reason = raw.get("abstention_reason")
        if abstain and (not isinstance(reason, str) or not reason.strip()):
            raise CandidateFailure("abstention requires a nonempty reason")
        src = _unique_ids(raw["source_ids"], source_ids, "source_ids")
        exe = _unique_ids(raw["execution_ids"], execution_ids, "execution_ids")
        interval_values = [raw.get(k) for k in ("interval_lower", "interval_upper", "interval_unit", "interval_level")]
        interval = None
        if any(v not in (None, "") for v in interval_values):
            if any(v in (None, "") for v in interval_values):
                raise CandidateFailure("interval fields must be all present or all absent")
            lo = _energy(interval_values[0], interval_values[2], "interval_lower")
            hi = _energy(interval_values[1], interval_values[2], "interval_upper")
            level = _finite(interval_values[3], "interval_level")
            if lo > hi or not 0 < level < 1:
                raise CandidateFailure("interval bounds or nominal level are invalid")
            interval = (lo, hi, level)
        row = {"instance": instance, "observation": raw["observation_id"],
               "reaction": raw["reaction_id"], "condition": raw["condition_id"],
               "group": raw["group_id"], "replicate": raw.get("replicate_id"),
               "arm": raw["arm_id"], "role": raw["evaluation_role"], "target": target,
               "prediction": prediction, "interval": interval,
               "stratum": raw.get("population_stratum"), "sources": src, "executions": exe}
        if row["replicate"] is not None and not isinstance(row["replicate"], str):
            raise CandidateFailure("replicate_id must be a string when supplied")
        key = (instance, row["observation"], row["arm"], row["role"])
        prior = by_key.get(key)
        if prior is not None:
            if prior != row:
                raise CandidateFailure("conflicting rows share a typed identity")
            continue
        by_key[key] = row
    normalised = list(by_key.values())
    # One physical observation cannot silently change identity/target between
    # arms or roles in the same declared instance.
    by_observation: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in normalised:
        by_observation.setdefault((row["instance"], row["observation"]), []).append(row)
    for records in by_observation.values():
        first = records[0]
        for row in records[1:]:
            if any(row[key] != first[key] for key in ("reaction", "condition", "group", "replicate")) or not _same_num(row["target"], first["target"]):
                raise CandidateFailure("one observation has conflicting reaction, condition, group, replicate, or target")
    return normalised


def _validate_protocol(protocol: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(protocol, dict):
        raise CandidateFailure("analysis.protocol must be an object")
    required = {"evaluation_roles", "target_quantity", "label_exposure", "replicate_policy", "missing_prediction_policy"}
    if not required <= set(protocol):
        raise CandidateFailure("protocol is missing required declarations")
    if protocol["target_quantity"] != "activation_free_energy":
        raise ReviewRequired("valid unsupported protocol target quantity")
    roles = protocol["evaluation_roles"]
    if not isinstance(roles, list) or any(not isinstance(x, str) or not x for x in roles):
        raise CandidateFailure("evaluation_roles must be nonempty strings")
    if set(roles) != {r["role"] for r in rows}:
        raise CandidateFailure("declared evaluation roles differ from table roles")
    for key in ("label_exposure", "replicate_policy"):
        if not isinstance(protocol[key], str) or not protocol[key].strip():
            raise CandidateFailure(f"{key} must be disclosed")
    if protocol["missing_prediction_policy"] != "retain_abstention_rows":
        raise ReviewRequired("unsupported missing-prediction denominator policy")
    if protocol["replicate_policy"] != "retain_distinct_observations_no_aggregation":
        raise ReviewRequired("replicate aggregation is not implemented")
    freezes = protocol.get("freeze_evidence", [])
    if not isinstance(freezes, list):
        raise CandidateFailure("freeze_evidence must be an array")
    # Hash integrity is checked; these bytes alone do not establish chronology.
    # File checks run at the top-level once final is known.
    disjointness = protocol.get("group_disjointness", [])
    if not isinstance(disjointness, list):
        raise CandidateFailure("group_disjointness must be an array")
    for declaration in disjointness:
        if not isinstance(declaration, dict) or set(declaration) != {"evaluation_instance_id", "roles", "group_field", "required"}:
            raise CandidateFailure("group_disjointness declaration is malformed")
        inst, pair = declaration["evaluation_instance_id"], declaration["roles"]
        if not isinstance(inst, str) or not isinstance(pair, list) or len(pair) != 2 or len(set(pair)) != 2 or any(x not in roles for x in pair) or declaration["group_field"] != "group_id" or type(declaration["required"]) is not bool:
            raise CandidateFailure("group_disjointness declaration is contradictory")
        if declaration["required"]:
            groups = [{r["group"] for r in rows if r["instance"] == inst and r["role"] == role} for role in pair]
            if groups[0] & groups[1]:
                raise CandidateFailure("declared within-instance group disjointness is violated")
    comparisons = protocol.get("comparisons", [])
    if not isinstance(comparisons, list):
        raise CandidateFailure("comparisons must be an array")
    comparison_ids: set[str] = set()
    for comp in comparisons:
        if not isinstance(comp, dict) or not {"id", "candidate_arm_id", "control_arm_id", "evaluation_role", "pair_by", "unmatched_policy"} <= set(comp):
            raise CandidateFailure("comparison declaration is malformed")
        if comp["pair_by"] != "observation_id":
            raise ReviewRequired("unsupported pairing identity")
        if comp["unmatched_policy"] != "reject":
            raise ReviewRequired("comparison intersection/exclusion policy is not implemented")
        if comp["candidate_arm_id"] == comp["control_arm_id"] or comp["evaluation_role"] not in roles or not isinstance(comp["id"], str) or not comp["id"]:
            raise CandidateFailure("comparison declaration is contradictory")
        if comp["id"] in comparison_ids: raise CandidateFailure("comparison IDs must be unique")
        comparison_ids.add(comp["id"])
    return protocol


def _stat(rows: list[dict[str, Any]], claim: dict[str, Any], comparisons: dict[str, dict[str, Any]]) -> tuple[Any, str, dict[str, int]]:
    instance = claim.get("evaluation_instance_id", "default")
    if not isinstance(instance, str) or not instance:
        raise CandidateFailure("metric claim evaluation_instance_id must be a nonempty string")
    selected = [r for r in rows if r["role"] == claim["evaluation_role"] and r["instance"] == instance]
    if "stratum_value" in claim:
        if claim.get("stratum_field") != "population_stratum":
            raise ReviewRequired("unsupported stratum filter")
        selected = [r for r in selected if r["stratum"] == claim["stratum_value"]]
    elif "stratum_field" in claim:
        raise CandidateFailure("stratum_field requires stratum_value")
    stats, unit = claim["statistic"], "1"
    if stats == "stratum_population_n" and "stratum_value" not in claim:
        raise CandidateFailure("stratum_population_n requires an exact stratum")
    if "comparison_id" in claim:
        comp = comparisons.get(claim["comparison_id"])
        if not comp:
            raise CandidateFailure("claim references an unknown comparison")
        if claim["evaluation_role"] != comp["evaluation_role"]:
            raise CandidateFailure("metric claim role differs from its comparison role")
        arms = {arm: {r["observation"]: r for r in selected if r["arm"] == arm} for arm in (comp["candidate_arm_id"], comp["control_arm_id"])}
        candidate_arm, control_arm = comp["candidate_arm_id"], comp["control_arm_id"]
        if set(arms[candidate_arm]) != set(arms[control_arm]):
            raise CandidateFailure("reject-unmatched comparison has asymmetric registered IDs")
        ids = sorted(arms[candidate_arm])
        if any(not _same_num(arms[candidate_arm][i]["target"], arms[control_arm][i]["target"]) for i in ids):
            raise CandidateFailure("paired targets conflict")
        eligible = [i for i in ids if arms[candidate_arm][i]["prediction"] is not None and arms[control_arm][i]["prediction"] is not None]
        counts = {"registered_n": len(ids), "paired_n": len(eligible), "contributing_group_n": len({arms[candidate_arm][i]["group"] for i in eligible})}
        if stats == "paired_n": return len(eligible), "observation", counts
        if stats == "paired_usable_coverage":
            if not ids: raise ReviewRequired("paired coverage denominator is empty")
            return len(eligible) / len(ids), "1", counts
        if stats == "paired_delta_mae":
            if not eligible: raise ReviewRequired("paired MAE is undefined for zero eligible pairs")
            ca, co = comp["candidate_arm_id"], comp["control_arm_id"]
            val = sum(abs(arms[ca][i]["prediction"]-arms[ca][i]["target"]) - abs(arms[co][i]["prediction"]-arms[co][i]["target"]) for i in eligible) / len(eligible)
            return val, "kcal/mol", counts
        raise ReviewRequired("statistic is not supported for a paired comparison")
    if "arm_id" not in claim:
        raise CandidateFailure("metric claim requires exactly one arm_id or comparison_id")
    selected = [r for r in selected if r["arm"] == claim["arm_id"]]
    n = len(selected)
    predicted = [r for r in selected if r["prediction"] is not None]
    pairs = [(r["prediction"], r["target"]) for r in predicted]
    groups = sorted({r["group"] for r in selected})
    counts = {"population_n": n, "predicted_n": len(predicted), "group_n": len(groups), "contributing_group_n": len({r["group"] for r in predicted})}
    if stats in (COUNT_STATS - {"interval_n", "paired_n"}):
        key = "stratum_population_n" if stats == "stratum_population_n" else stats
        value = {"population_n": n, "predicted_n": len(predicted), "group_n": len(groups), "stratum_population_n": n}.get(key)
        if stats in ("interval_n", "paired_n"):
            raise ReviewRequired("count requires interval or comparison context")
        return value, "group" if stats == "group_n" else "observation", counts
    if stats == "usable_coverage":
        if not n: raise ReviewRequired("coverage denominator is empty")
        return len(predicted)/n, "1", counts
    if stats in {"mae", "rmse", "signed_bias", "r2", "group_macro_mae"}:
        if not pairs: raise ReviewRequired("metric population is empty")
        errors = [p-y for p,y in pairs]
        unit = "kcal/mol"
        if stats == "mae": value = sum(abs(e) for e in errors)/len(errors)
        elif stats == "rmse": value = math.sqrt(sum(e*e for e in errors)/len(errors))
        elif stats == "signed_bias": value = sum(errors)/len(errors)
        elif stats == "r2":
            denom = sum((y-sum(y for _,y in pairs)/len(pairs))**2 for _,y in pairs)
            if denom == 0: raise ReviewRequired("R2 is undefined for a constant target population")
            value = 1-sum(e*e for e in errors)/denom
            unit = "1"
        else:
            by_group: dict[str, list[float]] = {}
            for row in predicted: by_group.setdefault(row["group"], []).append(abs(row["prediction"]-row["target"]))
            value = sum(sum(vals)/len(vals) for vals in by_group.values())/len(by_group)
        return value, unit, counts
    if stats in {"interval_n", "interval_coverage", "interval_eligible_coverage", "interval_mean_width"}:
        level = _finite(claim.get("interval_level"), "interval_level")
        if not 0 < level < 1: raise CandidateFailure("interval_level must be between zero and one")
        interval_rows = [r for r in selected if r["interval"] is not None and r["interval"][2] == level]
        eligible = [r for r in interval_rows if r["prediction"] is not None]
        counts.update({"interval_n": len(interval_rows), "interval_eligible_n": len(eligible)})
        if stats == "interval_n": return len(interval_rows), "observation", counts
        if stats == "interval_eligible_coverage":
            if not n: raise ReviewRequired("interval eligible denominator is empty")
            return len(interval_rows)/n, "1", counts
        if not eligible: raise ReviewRequired("interval metric has no eligible rows")
        if stats == "interval_coverage":
            return sum(_inside_interval(r["interval"][0], r["target"], r["interval"][1]) for r in eligible)/len(eligible), "1", counts
        return sum(r["interval"][1]-r["interval"][0] for r in eligible)/len(eligible), "kcal/mol", counts
    if stats not in SUPPORTED_STATS:
        raise ReviewRequired("valid unsupported statistic")
    raise ReviewRequired("statistic is not supported in this context")


def _inside_interval(lower: float, value: float, upper: float) -> bool:
    """Inclusive membership with only machine-scale tolerance after unit conversion."""
    return (lower <= value <= upper or _same_num(value, lower) or _same_num(value, upper))


def _claim_matches(recomputed: Any, reported: Any, claim: dict[str, Any]) -> bool:
    if type(recomputed) is int:
        return type(reported) is int and reported == recomputed
    value = _finite(reported, "reported metric")
    rounding = claim.get("rounding")
    if rounding is not None:
        if not isinstance(rounding, dict) or set(rounding) != {"decimal_places", "mode"} or type(rounding["decimal_places"]) is not int or not 0 <= rounding["decimal_places"] <= 12 or rounding["mode"] not in {"half_even", "half_up"}:
            raise ReviewRequired("valid but unsupported rounding declaration")
        mode = ROUND_HALF_EVEN if rounding["mode"] == "half_even" else ROUND_HALF_UP
        quantum = Decimal(1).scaleb(-rounding["decimal_places"])
        return Decimal(str(recomputed)).quantize(quantum, rounding=mode) == Decimal(str(value))
    return _same_num(float(value), float(recomputed))


def evaluate_results(final: Path, results: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    """Validate/evaluate the bounded protocol; never returns whole-case science PASS."""
    if not isinstance(results, dict) or results.get("schema_version") != "case06-results/v2":
        raise CandidateFailure("results.json must use case06-results/v2")
    if not {"scope", "validation", "quantities", "conclusion", "analysis"} <= set(results):
        raise CandidateFailure("results.json is missing a required top-level field")
    if not isinstance(results["scope"], dict) or not isinstance(results["validation"], dict):
        raise CandidateFailure("results.scope and results.validation must be objects")
    analysis = results.get("analysis")
    if not isinstance(analysis, dict) or analysis.get("schema_version") != VERSION:
        raise CandidateFailure("results.analysis schema is missing or unsupported")
    if final.is_symlink() or not final.is_dir():
        raise CandidateFailure("final submission directory is missing or redirected")
    claim_path = final / "claim.md"
    native_path = final / "native_evidence"
    if claim_path.is_symlink() or not claim_path.is_file() or native_path.is_symlink() or not native_path.is_dir():
        raise CandidateFailure("claim.md and native_evidence/ are required submission artifacts")
    if not isinstance(provenance, dict):
        raise CandidateFailure("provenance.json must be an object")
    if provenance.get("schema_version") != "case06-provenance/v1":
        raise CandidateFailure("provenance schema version is unsupported")
    source_registry = _registry(provenance.get("sources"), "sources")
    execution_registry = _registry(provenance.get("executions"), "executions")
    claim_registry = _registry(provenance.get("claims"), "claims")
    if not isinstance(provenance.get("decisions"), list):
        raise CandidateFailure("provenance.decisions must be an array")
    source_ids = set(source_registry)
    execution_ids = set(execution_registry)
    claim_ids = set(claim_registry)
    for row in source_registry.values():
        if not {"origin", "acquisition", "path", "sha256"} <= set(row) or row["acquisition"] not in {"acquired", "constructed"}:
            raise CandidateFailure("source provenance entry is structurally incomplete")
        _safe_evidence_file(final, row["path"], row["sha256"], "provenance source")
    for row in execution_registry.values():
        if not {"stage", "input_paths", "output_paths", "receipt_paths", "status", "resource_usage"} <= set(row):
            raise CandidateFailure("execution provenance entry is structurally incomplete")
        if any(not isinstance(row[key], list) for key in ("input_paths", "output_paths", "receipt_paths", "resource_usage")):
            raise CandidateFailure("execution provenance paths/resource_usage must be arrays")
        for key in ("input_paths", "output_paths", "receipt_paths"):
            for path in row[key]:
                _safe_local_path(final, path, f"execution {key}")
    for row in claim_registry.values():
        if not {"statement", "result_ids", "evidence_paths", "source_ids", "execution_ids"} <= set(row):
            raise CandidateFailure("claim provenance entry is structurally incomplete")
        if any(not isinstance(row[key], list) for key in ("result_ids", "evidence_paths", "source_ids", "execution_ids")):
            raise CandidateFailure("claim provenance references must be arrays")
    quantities = results.get("quantities")
    if not isinstance(quantities, list): raise CandidateFailure("quantities must be an array")
    quantity_fields = {"id", "name", "role", "value", "unit", "conditions", "population", "uncertainty", "evidence_paths"}
    quantity_registry = _registry(quantities, "results.quantities")
    for quantity in quantity_registry.values():
        if not quantity_fields <= set(quantity) or quantity["role"] not in {"prediction", "measurement", "aggregate"} or not isinstance(quantity["evidence_paths"], list):
            raise CandidateFailure("quantity entry is structurally incomplete")
        for path in quantity["evidence_paths"]:
            _safe_local_path(final, path, "quantity evidence")
    quantity_ids = set(quantity_registry)
    conclusion = results["conclusion"]
    if not isinstance(conclusion, dict) or conclusion.get("status") not in {"supported", "refuted", "inconclusive"} or not isinstance(conclusion.get("claim_ids"), list):
        raise CandidateFailure("conclusion schema or status is invalid")
    if not set(conclusion["claim_ids"]) <= claim_ids:
        raise CandidateFailure("conclusion references an unknown claim ID")
    for decision in provenance["decisions"]:
        if not isinstance(decision, dict) or not {"id", "timestamp", "decision", "reason", "evidence_ids"} <= set(decision) or not isinstance(decision["evidence_ids"], list):
            raise CandidateFailure("decision provenance entry is malformed")
        if not set(decision["evidence_ids"]) <= (source_ids | execution_ids | claim_ids):
            raise CandidateFailure("decision references an unknown evidence ID")
    for claim in claim_registry.values():
        if not set(claim["result_ids"]) <= quantity_ids or not set(claim["source_ids"]) <= source_ids or not set(claim["execution_ids"]) <= execution_ids:
            raise CandidateFailure("claim provenance references an unknown registered ID")
        for path in claim["evidence_paths"]:
            _safe_local_path(final, path, "claim evidence")
    table_specs = analysis.get("tables")
    if not isinstance(table_specs, list) or not table_specs: raise CandidateFailure("analysis.tables must be nonempty")
    all_rows: dict[str, list[dict[str, Any]]] = {}
    protocols = _validate_protocol(analysis.get("protocol"), []) if False else analysis.get("protocol")
    if not isinstance(protocols, dict): raise CandidateFailure("analysis.protocol must be an object")
    protocol_fields = {"evaluation_roles", "target_quantity", "label_exposure", "replicate_policy",
                       "missing_prediction_policy", "group_disjointness", "comparisons", "freeze_evidence"}
    if set(protocols) - protocol_fields:
        raise ReviewRequired("valid protocol declarations outside the supported method subset")
    for spec in table_specs:
        if not isinstance(spec, dict): raise CandidateFailure("table declaration must be an object")
        if spec.get("kind") != "prediction_measurement" or spec.get("quantity") != "activation_free_energy":
            raise ReviewRequired("valid unsupported table kind or quantity")
        ident = spec.get("id")
        if not isinstance(ident, str) or not ident or ident in all_rows: raise CandidateFailure("table IDs must be unique")
        path = _safe_table(final, spec)
        rows = _normalise_rows(_load_table(path, spec.get("format")), source_ids, execution_ids)
        all_rows[ident] = rows
    # One protocol applies to the complete bundle; roles may be distributed among tables.
    bundle_rows = [row for rows in all_rows.values() for row in rows]
    _validate_protocol(protocols, bundle_rows)
    for frozen in protocols.get("freeze_evidence", []):
        if not isinstance(frozen, dict) or set(frozen) != {"path", "sha256"}:
            raise CandidateFailure("freeze_evidence entries require exactly path and sha256")
        _safe_evidence_file(final, frozen["path"], frozen["sha256"], "freeze evidence")
    comp_by_id = {c["id"]: c for c in protocols.get("comparisons", [])}
    claims = analysis.get("metric_claims")
    if not isinstance(claims, list): raise CandidateFailure("metric_claims must be an array")
    output = []
    seen = set()
    for claim in claims:
        required = {"id", "claim_id", "quantity_id", "table_id", "statistic", "evaluation_role"}
        if not isinstance(claim, dict) or not required <= set(claim): raise CandidateFailure("metric claim is malformed")
        if ("arm_id" in claim) == ("comparison_id" in claim): raise CandidateFailure("metric claim needs exactly one arm or comparison")
        ident = claim["id"]
        if not isinstance(ident, str) or not ident or ident in seen: raise CandidateFailure("metric claim IDs must be unique")
        seen.add(ident)
        if claim["claim_id"] not in claim_ids or claim["quantity_id"] not in quantity_ids or claim["table_id"] not in all_rows: raise CandidateFailure("metric claim references unknown provenance/result/table ID")
        claim_fields = {"id", "claim_id", "quantity_id", "table_id", "statistic", "evaluation_role",
                        "arm_id", "comparison_id", "interval_level", "stratum_field", "stratum_value",
                        "evaluation_instance_id", "unit", "value", "rounding"}
        if set(claim) - claim_fields:
            raise ReviewRequired("valid metric claim uses an unsupported filter or method option")
        if "comparison_id" in claim:
            declared_comparison = comp_by_id.get(claim["comparison_id"])
            if declared_comparison and claim["evaluation_role"] != declared_comparison["evaluation_role"]:
                raise CandidateFailure("metric claim role differs from its comparison role")
        if claim["evaluation_role"] not in protocols["evaluation_roles"]:
            raise CandidateFailure("metric claim uses an undeclared evaluation role")
        value, unit, counts = _stat(all_rows[claim["table_id"]], claim, comp_by_id)
        if unit == "kcal/mol":
            claim_unit = claim.get("unit")
            if claim_unit not in {"kcal/mol", "kJ/mol"}:
                raise ReviewRequired("valid but unsupported reported energy unit")
            if claim_unit == "kJ/mol":
                value *= 4.184
            unit = claim_unit
        if claim.get("unit") != unit or "value" not in claim or not _claim_matches(value, claim["value"], claim):
            raise CandidateFailure(f"metric claim {ident} has an unsupported unit or incorrect recomputed value")
        quantity = quantity_registry[claim["quantity_id"]]
        provenance_claim = claim_registry[claim["claim_id"]]
        if quantity.get("role") != "aggregate":
            raise CandidateFailure(f"metric claim {ident} must reference an aggregate quantity")
        if quantity.get("unit") != unit or not _claim_matches(value, quantity.get("value"), claim):
            raise CandidateFailure(f"metric claim {ident} differs from its linked aggregate quantity")
        if quantity.get("value") != claim["value"] or quantity.get("unit") != claim["unit"]:
            raise CandidateFailure(f"metric claim {ident} and linked quantity must report the same value and unit")
        rows_for_claim = all_rows[claim["table_id"]]
        selected_rows = [r for r in rows_for_claim if r["role"] == claim["evaluation_role"] and r["instance"] == claim.get("evaluation_instance_id", "default")]
        if "arm_id" in claim:
            selected_rows = [r for r in selected_rows if r["arm"] == claim["arm_id"]]
        else:
            comparison = comp_by_id[claim["comparison_id"]]
            selected_rows = [r for r in selected_rows if r["arm"] in {comparison["candidate_arm_id"], comparison["control_arm_id"]}]
        selected_sources = {x for r in selected_rows for x in r["sources"]}
        selected_executions = {x for r in selected_rows for x in r["executions"]}
        table_path = next(spec["path"] for spec in table_specs if spec["id"] == claim["table_id"])
        if (claim["quantity_id"] not in provenance_claim["result_ids"] or
                table_path not in provenance_claim["evidence_paths"] or
                not selected_sources <= set(provenance_claim["source_ids"]) or
                not selected_executions <= set(provenance_claim["execution_ids"])):
            raise CandidateFailure(f"metric claim {ident} is not bound to its provenance evidence")
        output.append({"id": ident, "claim_id": claim["claim_id"], "table_id": claim["table_id"],
                       "statistic": claim["statistic"], "evaluation_role": claim["evaluation_role"],
                       "evaluation_instance_id": claim.get("evaluation_instance_id", "default"),
                       "arm_id": claim.get("arm_id"), "comparison_id": claim.get("comparison_id"),
                       "interval_level": claim.get("interval_level"),
                       "value": value, "unit": unit, "denominators": counts, "component_status": "PASS"})
    return {"schema": "case06-route-neutral-component-report/v1", "component_status": "PASS",
            "overall_status": "REVIEW_REQUIRED", "reward": None,
            "science_decision": "NOT_EVALUATED", "metrics": output,
            "limits": ["No candidate code was executed", "Source truth, label timing, method authenticity, and scientific conclusion are not assessed", "No whole-case science PASS is available in this version"]}
