"""Typed, deterministic decision algebra for the supported Case06 science route."""
from __future__ import annotations

import math
from typing import Any

from case06_route_neutral import CandidateFailure, ReviewRequired


OPS = {"lt": "lt", "<": "lt", "le": "le", "<=": "le", "≤": "le",
       "eq": "eq", "=": "eq", "ge": "ge", ">=": "ge", "≥": "ge",
       "gt": "gt", ">": "gt", "between": "between", "区间内": "between"}
TYPES = {"heldout_accuracy", "paired_computation_contribution", "interval_performance", "applicability_scope"}
ENERGY_UNITS = {"kcal/mol": 1.0, "kJ/mol": 1/4.184}


def aggregate_required_criteria(states: list[str]) -> str:
    if not states:
        raise CandidateFailure("required-criteria conjunction must be nonempty")
    if any(state not in {"T", "F", "U"} for state in states):
        raise CandidateFailure("criterion state must be T, F, or U")
    if all(state == "T" for state in states):
        return "supported"
    if "F" in states:
        return "refuted"
    return "inconclusive"


def _numeric(value, label):
    if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CandidateFailure(f"{label} must be a finite number")
    return float(value)


def decide(science: dict[str, Any], route_metrics: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    criteria = science.get("criteria")
    claims = science.get("typed_claims")
    if not isinstance(criteria, list) or not criteria:
        raise CandidateFailure("science.criteria must be nonempty")
    if not isinstance(claims, list) or not claims:
        raise CandidateFailure("science.typed_claims must be nonempty")
    metric_map = {x["id"]: x for x in route_metrics.get("metrics", []) if isinstance(x, dict) and isinstance(x.get("id"), str)}
    primary_arm = science.get("model", {}).get("primary_arm_id") if isinstance(science.get("model"), dict) else None
    control_arm = science.get("control", {}).get("arm_id") if isinstance(science.get("control"), dict) else None
    interval_level = science.get("interval", {}).get("level") if isinstance(science.get("interval"), dict) else None
    seen_criteria, criterion_states, by_type = set(), {}, {}
    for item in criteria:
        if not isinstance(item, dict) or set(item) != {"id", "claim_type", "metric_claim_id", "operator", "threshold", "unit", "basis", "scope", "scope_kind"}:
            raise CandidateFailure("science criterion is malformed")
        ident, ctype = item["id"], item["claim_type"]
        if not isinstance(item["operator"], str) or not isinstance(item["scope_kind"], str):
            raise CandidateFailure("science criterion operator and scope_kind must be strings")
        if item["scope_kind"] not in {"registered_population", "beyond_registered_population"}:
            raise ReviewRequired("criterion scope kind outside supported typed scope domain")
        if (item["scope_kind"] == "beyond_registered_population"
                and item["operator"] != "unverified_scope"):
            raise ReviewRequired("numeric criteria cannot verify applicability beyond the registered population")
        if not isinstance(ident, str) or not ident or ident in seen_criteria:
            raise CandidateFailure("science criterion IDs must be unique nonempty strings")
        seen_criteria.add(ident)
        if not isinstance(ctype, str) or not isinstance(item["metric_claim_id"], str):
            raise CandidateFailure("science criterion claim type and metric reference must be strings")
        if ctype not in TYPES:
            raise ReviewRequired("typed claim category outside the supported claim domain")
        metric = metric_map.get(item["metric_claim_id"])
        if metric is None:
            raise ReviewRequired("criterion metric is not among independently recomputed route metrics")
        statistic = metric.get("statistic")
        if ctype in {"heldout_accuracy", "applicability_scope", "interval_performance"}:
            if metric.get("evaluation_role") != "heldout" or metric.get("arm_id") != primary_arm:
                raise CandidateFailure("claim metric does not use the primary heldout population")
        if ctype == "paired_computation_contribution":
            if (statistic != "paired_delta_mae" or metric.get("evaluation_role") != "heldout"
                    or metric.get("comparison_id") is None
                    or metric.get("table_id") != science.get("model", {}).get("prediction_table_id")
                    or metric.get("evaluation_instance_id") != "default"):
                raise CandidateFailure("computation contribution requires a paired heldout delta metric")
            comparisons = results.get("analysis", {}).get("protocol", {}).get("comparisons", [])
            comparison = next((x for x in comparisons if isinstance(x, dict)
                               and x.get("id") == metric.get("comparison_id")), None)
            if (comparison is None or comparison.get("candidate_arm_id") != primary_arm
                    or comparison.get("control_arm_id") != control_arm
                    or comparison.get("evaluation_role") != "heldout"
                    or comparison.get("pair_by") != "observation_id"
                    or comparison.get("unmatched_policy") != "reject"):
                raise CandidateFailure("paired computation criterion must compare the replayed primary and control arms")
            denominators = metric.get("denominators")
            if (not isinstance(denominators, dict)
                    or denominators.get("registered_n") != denominators.get("paired_n")
                    or denominators.get("paired_n", 0) <= 0
                    or denominators.get("contributing_group_n", 0) <= 0):
                raise CandidateFailure("paired computation metric must cover the complete replayed heldout population")
        if ctype == "interval_performance":
            if statistic not in {"interval_coverage", "interval_mean_width"} or metric.get("interval_level") != interval_level:
                raise CandidateFailure("interval claim must use exact declared level on the primary heldout arm")
        if ctype == "applicability_scope" and statistic != "group_macro_mae":
            raise CandidateFailure("applicability claim requires source-group macro error")
        if ctype == "heldout_accuracy" and statistic not in {"mae", "rmse"}:
            raise CandidateFailure("accuracy claim requires heldout MAE or RMSE")
        value = _numeric(metric.get("value"), "recomputed metric")
        threshold = item["threshold"]
        operator = OPS.get(item["operator"])
        if item["operator"] == "unverified_scope":
            if ctype != "applicability_scope" or statistic != "group_macro_mae" or item["scope_kind"] != "beyond_registered_population":
                raise CandidateFailure("unverified_scope is only valid for an explicit beyond-population applicability limitation")
            if item["threshold"] is not None:
                raise CandidateFailure("unverified_scope uses a null threshold")
            if not isinstance(item.get("basis"), str) or not item["basis"].strip():
                raise CandidateFailure("unverified scope requires an explicit evidence limitation")
            criterion_states[ident] = "U"
            by_type.setdefault(ctype, []).append(metric)
            continue
        if item["operator"] == "observed":
            if ctype != "paired_computation_contribution":
                raise ReviewRequired("observed-only evidence is limited to reporting a paired computation contrast")
            if item["threshold"] is not None:
                raise CandidateFailure("observed criterion uses a null threshold")
            denominators = metric.get("denominators", {})
            if not isinstance(denominators, dict) or not denominators:
                raise CandidateFailure("observed criterion needs recomputed nonempty denominators")
            if any(type(v) is not int or v <= 0 for v in denominators.values()):
                raise ReviewRequired("observed metric has an empty or undefined scientific denominator")
            if not isinstance(item["basis"], str) or not item["basis"].strip() or not isinstance(item["scope"], str) or not item["scope"].strip():
                raise CandidateFailure("observed criterion basis and scope must be nonempty")
            criterion_states[ident] = "T"
            by_type.setdefault(ctype, []).append(metric)
            continue
        if operator is None:
            raise ReviewRequired("criterion operator outside supported semantic aliases")
        if operator == "between":
            if not isinstance(threshold, dict) or set(threshold) != {"lower", "upper"}:
                raise CandidateFailure("between criterion requires lower and upper thresholds")
            lower = _numeric(threshold["lower"], "lower threshold")
            upper = _numeric(threshold["upper"], "upper threshold")
            if lower > upper: raise CandidateFailure("between bounds are reversed")
            threshold = {"lower": lower, "upper": upper}
        if metric.get("unit") in ENERGY_UNITS:
            if item["unit"] not in ENERGY_UNITS:
                raise ReviewRequired("criterion unit is incompatible with an energy metric")
            value *= ENERGY_UNITS[metric["unit"]]
            if operator == "between":
                threshold = {k: v*ENERGY_UNITS[item["unit"]] for k,v in threshold.items()}
            else:
                threshold = _numeric(threshold, "criterion threshold") * ENERGY_UNITS[item["unit"]]
        else:
            if item["unit"] != metric.get("unit"):
                raise ReviewRequired("criterion unit differs from recomputed dimensionless metric")
            if operator != "between":
                threshold = _numeric(threshold, "criterion threshold")
        if not isinstance(item["basis"], str) or not item["basis"].strip() or not isinstance(item["scope"], str) or not item["scope"].strip():
            raise CandidateFailure("criterion basis and scope must be nonempty")
        if operator == "lt": ok = value < threshold
        elif operator == "le": ok = value <= threshold
        elif operator == "eq": ok = value == threshold
        elif operator == "ge": ok = value >= threshold
        elif operator == "gt": ok = value > threshold
        else:
            ok = threshold["lower"] <= value <= threshold["upper"]
        criterion_states[ident] = "T" if ok else "F"
        by_type.setdefault(ctype, []).append(metric)
    required_stats = {
        "heldout_accuracy": {"mae", "rmse"},
        "paired_computation_contribution": {"paired_delta_mae"},
        "interval_performance": {"interval_coverage", "interval_mean_width"},
        "applicability_scope": {"group_macro_mae"},
    }
    for ctype, stats in required_stats.items():
        if ctype not in by_type or not stats <= {x.get("statistic") for x in by_type[ctype]}:
            raise CandidateFailure(f"scientific study lacks required metric support for {ctype}")
    claim_ids, covered_criteria, observed_types = set(), set(), set()
    claim_criteria = {}
    for claim in claims:
        expected_claim_fields = {"claim_id", "claim_type", "criterion_ids", "metric_claim_ids",
                                 "decision_rule", "scope", "limitations"}
        if not isinstance(claim, dict) or set(claim) != expected_claim_fields:
            raise CandidateFailure("typed claim is malformed")
        cid, ctype = claim["claim_id"], claim["claim_type"]
        if not isinstance(cid, str) or not cid or cid in claim_ids: raise CandidateFailure("typed claim IDs must be unique")
        if ctype not in TYPES: raise ReviewRequired("typed claim category outside supported domain")
        if not isinstance(claim["criterion_ids"], list) or not claim["criterion_ids"] or not set(claim["criterion_ids"]) <= seen_criteria:
            raise CandidateFailure("typed claim must reference known nonempty criteria")
        if claim["decision_rule"] != "all_required_criteria_and_v1":
            raise ReviewRequired("valid typed-claim aggregation rule outside the supported all-required conjunction")
        expected_metrics = {next(c for c in criteria if c["id"] == x)["metric_claim_id"]
                            for x in claim["criterion_ids"]}
        if (not isinstance(claim["metric_claim_ids"], list) or not claim["metric_claim_ids"]
                or len(set(claim["metric_claim_ids"])) != len(claim["metric_claim_ids"])
                or set(claim["metric_claim_ids"]) != expected_metrics):
            raise CandidateFailure("typed claim metric references do not match its criteria")
        if not isinstance(claim["scope"], str) or not claim["scope"].strip() or not isinstance(claim["limitations"], list) or not claim["limitations"]:
            raise CandidateFailure("typed claim requires a scope and stated limitations")
        if any(next(c for c in criteria if c["id"] == x)["claim_type"] != ctype for x in claim["criterion_ids"]):
            raise CandidateFailure("typed claim and criterion categories differ")
        claim_ids.add(cid); observed_types.add(ctype); covered_criteria.update(claim["criterion_ids"])
        claim_criteria[cid] = claim["criterion_ids"]
    if observed_types != TYPES or covered_criteria != seen_criteria:
        raise CandidateFailure("typed claims must cover accuracy, computation, intervals, applicability and every criterion")
    states = [criterion_states[x] for x in covered_criteria]
    expected = aggregate_required_criteria(states)
    conclusion = results.get("conclusion")
    if not isinstance(conclusion, dict) or conclusion.get("status") != expected or set(conclusion.get("claim_ids", [])) != claim_ids:
        raise CandidateFailure("conclusion does not follow the declared nonempty three-valued AND rule")
    if not isinstance(conclusion.get("rationale"), str) or not conclusion["rationale"].strip():
        raise CandidateFailure("conclusion rationale must be nonempty")
    checked = sorted(cid for cid, ids in claim_criteria.items()
                     if all(criterion_states[key] != "U" for key in ids))
    unverified = sorted(cid for cid, ids in claim_criteria.items()
                       if any(criterion_states[key] == "U" for key in ids))
    return {"status": expected, "criterion_states": criterion_states,
            "checked_claims": checked,
            "unverified_claims": unverified + ["general chemical truth", "population reliability beyond declared groups",
                                               "label blindness", "arbitrary candidate model honesty"]}
