"""Independent, grader-owned replay of the supported Case06 tabular domain.

This module imports no candidate module. Its input is the private native source
authority plus the candidate's declarative study and output tables.
"""
from __future__ import annotations

import json
import math
import re
from decimal import Decimal, ROUND_CEILING
from typing import Any

from case06_route_neutral import CandidateFailure, ProtectedInputError, ReviewRequired
from case06_source_authority import (
    RECOMPUTED_PROFILE, TABULATED_PROFILE, ProtectedSourceError, SourceAdapterError, load_protected_s050,
    match_candidate_source,
)


REPLAY_ABS_TOL = 1e-8
REPLAY_REL_TOL = 1e-8
ROLE = {"fit", "tuning", "calibration", "heldout"}
FEATURE_COLUMNS = {
    "temperature_k": ("Temp (K)", "K", "condition"),
    "solvent": ("Solvent", "1", "condition"),
    "substrate": ("Substrate SMILES", "1", "structure"),
    "nucleophile": ("Nucleophile SMILES", "1", "structure"),
    "leaving_group": ("Leaving Group", "1", "condition"),
}


def grouped_conformal_rank(group_count: int, level: float) -> int:
    if type(group_count) is not int or group_count <= 0:
        raise CandidateFailure("calibration group count must be a positive integer")
    if isinstance(level, bool) or type(level) not in (int, float) or not math.isfinite(float(level)) or not 0 < level < 1:
        raise CandidateFailure("interval level must be finite and strictly between zero and one")
    return int((Decimal(group_count + 1) * Decimal(str(level))).to_integral_value(rounding=ROUND_CEILING))


def _num(x: Any, label: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        raise CandidateFailure(f"{label} must be a finite JSON number")
    return float(x)


def _close(a: float, b: float) -> bool:
    return abs(a-b) <= max(REPLAY_ABS_TOL, REPLAY_REL_TOL*abs(b))


def _require_object(x: Any, label: str) -> dict[str, Any]:
    if not isinstance(x, dict):
        raise CandidateFailure(f"{label} must be an object")
    return x


def _bind_native_observation(bindings, instance_id, native, observation_id):
    """A source measurement can have only one candidate observation label per instance."""
    native_key = (instance_id, native["entry"], native["source_row"])
    prior = bindings.setdefault(native_key, observation_id)
    if prior != observation_id:
        raise CandidateFailure("one native source row cannot be duplicated under multiple observation IDs")


def _safe_final_file(final, raw_path):
    from pathlib import Path, PurePosixPath
    if not isinstance(raw_path, str):
        raise CandidateFailure("evidence path must be a relative string")
    if "\\" in raw_path or "\x00" in raw_path:
        raise CandidateFailure("evidence path must use normalized POSIX separators")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or not relative.parts or any(p in ("", ".", "..") for p in relative.parts):
        raise CandidateFailure("evidence path is unsafe")
    path = Path(final).joinpath(*relative.parts)
    cursor = Path(final)
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise CandidateFailure("evidence path contains a symlink")
    if not path.is_file():
        raise CandidateFailure("required scientific evidence file is missing")
    return path


def _rows(final, results, provenance):
    analysis = results.get("analysis")
    science = _require_object(analysis.get("science") if isinstance(analysis, dict) else None,
                              "analysis.science")
    if science.get("schema_version") != "case06-route-neutral-science/v1":
        raise CandidateFailure("analysis.science schema_version is unsupported")
    if not {"schema_version", "precommit_path", "study", "model", "control", "interval", "criteria", "typed_claims"}.issubset(science):
        raise CandidateFailure("analysis.science is missing required top-level fields")
    try:
        authority = load_protected_s050()
    except ProtectedSourceError as exc:
        raise ProtectedInputError(str(exc)) from exc
    study = _require_object(science.get("study"), "analysis.science.study")
    required_study = {"study_id", "question_scope", "estimand", "source_ids", "label_exposure",
                      "selection_rules", "limitations", "target_definition", "data_use_map",
                      "grouping_definition"}
    if not required_study.issubset(study):
        raise CandidateFailure("science.study is missing required scope/source/selection disclosures")
    if (not isinstance(study.get("study_id"), str) or not study["study_id"].strip()
            or not isinstance(study.get("question_scope"), str) or not study["question_scope"].strip()
            or not isinstance(study.get("selection_rules"), list) or not study["selection_rules"]
            or any(not isinstance(x, str) or not x.strip() for x in study["selection_rules"])
            or not isinstance(study.get("limitations"), list) or not study["limitations"]
            or any(not isinstance(x, str) or not x.strip() for x in study["limitations"])
            or not isinstance(study.get("label_exposure"), dict)
            or not isinstance(study.get("data_use_map"), list) or not study["data_use_map"]):
        raise CandidateFailure("science.study scope, selection and exposure disclosure is incomplete")
    exposure = study["label_exposure"]
    if not {"status", "details"}.issubset(exposure) or not isinstance(exposure.get("details"), str) or not exposure["details"].strip():
        raise CandidateFailure("published-source label exposure must be disclosed as public/acquired, not blind")
    if not isinstance(exposure.get("status"), str):
        raise CandidateFailure("label_exposure status must be a string")
    if exposure.get("status") in {"restricted_before_assessment", "unknown"}:
        raise ReviewRequired("blind or unresolved label timing requires an additional registered authority")
    if exposure.get("status") not in {"public_before_study", "acquired_during_study"}:
        raise CandidateFailure("label_exposure status is outside the declared source-exposure domain")
    grouping = _require_object(study.get("grouping_definition"), "study.grouping_definition")
    if set(grouping) != {"method", "condition_specific_observations", "chemical_independence_claim"}:
        raise CandidateFailure("grouping_definition has unsupported fields")
    if grouping.get("chemical_independence_claim") is True:
        raise CandidateFailure("native duplicate/reaction groups do not establish chemical independence")
    if (grouping.get("method") != "native_doi_reaction_duplicate_component/v1"
            or grouping.get("condition_specific_observations") is not True
            or grouping.get("chemical_independence_claim") is not False):
        raise ReviewRequired("valid grouping/independence design outside registered native-source grouping")
    estimand = _require_object(study.get("estimand"), "science.study.estimand")
    if not {"quantity", "unit", "population_definition", "conditions"}.issubset(estimand):
        raise CandidateFailure("estimand has unsupported fields")
    if (estimand.get("quantity") != "activation_free_energy"
            or estimand.get("unit") not in {"kcal/mol", "kJ/mol"}
            or not isinstance(estimand.get("population_definition"), str)
            or not estimand["population_definition"].strip()
            or not isinstance(estimand.get("conditions"), list)
            or any(not isinstance(x, str) for x in estimand["conditions"])
            or not {"Temp (K)", "Solvent"} <= set(estimand["conditions"])):
        raise CandidateFailure("study estimand must identify quantity, units, population and conditions")
    target_spec = _require_object(study.get("target_definition"), "science.study.target_definition")
    target_profile = target_spec.get("profile_id")
    locator = _require_object(target_spec.get("native_locator"), "target_definition.native_locator")
    common_locator = {"native_si_sha256": "ec3744548892430c8c32c6c520eb06e6820638bdf4c6ea33c686e6f8cf3b6a43",
                      "page": 25, "table": "Table S11", "archive_sha256": "ce339248e5d4db6c3939624d08e5a7fdf8a83bcff8f3ddb0543721638641aa8e",
                      "archive_member": "SC-012-D0SC04896H-s050.csv", "archive_member_sha256": "590153f74fd27a1414cf6d1cdae3758e68cc9e137da81bd58fa84cc5c9750107",
                      "row_key": "Entry"}
    if target_profile == TABULATED_PROFILE:
        if set(target_spec) != {"profile_id", "operation", "source_column", "unit", "is_direct_measurement", "native_locator"}:
            raise CandidateFailure("tabulated target profile has unsupported fields")
        if locator != {**common_locator, "target_column": "Activation Free Energy (kcalmol-1)"}:
            raise CandidateFailure("tabulated target locator does not bind the native SI/archive row and column")
        if (target_spec.get("operation") != "copy_native_column"
                or target_spec.get("source_column") != "Activation Free Energy (kcalmol-1)"
                or target_spec.get("unit") != "kcal/mol"
                or target_spec.get("is_direct_measurement") is not False):
            raise CandidateFailure("tabulated target profile does not match its explicit native definition")
    elif target_profile == RECOMPUTED_PROFILE:
        constants = target_spec.get("constants")
        required_constant_fields = {"R_J_mol_K", "h_J_s", "kB_J_K", "J_per_kcal", "C0_mol_L"}
        registered_constants = {"R_J_mol_K": 8.31446261815324, "h_J_s": 6.62607015e-34,
                                "kB_J_K": 1.380649e-23, "J_per_kcal": 4184}
        standard_state = target_spec.get("standard_state")
        if set(target_spec) != {"profile_id", "operation", "source_columns", "unit", "constants", "constants_version", "equation", "standard_state", "is_direct_measurement", "native_locator"}:
            raise CandidateFailure("recomputed target profile has unsupported fields")
        if locator != {**common_locator, "input_columns": ["Exp_Rate_Constant k1 (M-1s-1)", "Temp (K)"]}:
            raise CandidateFailure("recomputed target locator does not bind the native SI/archive inputs")
        if (not isinstance(constants, dict) or set(constants) != required_constant_fields
                or any(constants.get(k) != v for k, v in registered_constants.items())):
            raise CandidateFailure("recomputed target uses invalid registered physical constants")
        if (isinstance(constants.get("C0_mol_L"), bool)
                or not isinstance(constants.get("C0_mol_L"), (int, float))
                or not math.isfinite(constants["C0_mol_L"]) or constants["C0_mol_L"] <= 0
                or not isinstance(standard_state, dict)
                or set(standard_state) != {"concentration_mol_L", "authority"}
                or standard_state.get("concentration_mol_L") != constants["C0_mol_L"]
                or not isinstance(standard_state.get("authority"), str)
                or not standard_state["authority"].strip()):
            raise CandidateFailure("recomputed target standard state must be explicit, sourced, and dimensionally consistent")
        if constants["C0_mol_L"] != 1.0:
            raise ReviewRequired("valid second-order standard state outside the registered source adapter")
        if (target_spec.get("operation") != "registered_eyring_formula"
                or not isinstance(target_spec.get("source_columns"), list)
                or not target_spec["source_columns"]
                or any(not isinstance(x, str) or not x.strip() for x in target_spec["source_columns"])
                or target_spec["source_columns"] != locator["input_columns"]
                or target_spec.get("unit") != "kcal/mol"
                or target_spec.get("constants_version") != "case06-eyring-constants-si-2026-v1"
                or target_spec.get("is_direct_measurement") is not False
                or not isinstance(target_spec.get("equation"), str)
                or not target_spec["equation"].strip()):
            raise CandidateFailure("recomputed target profile formula/constants do not match the registered operation")
    else:
        raise ReviewRequired("valid target quantity/profile outside registered native target definitions")
    source_list = study.get("source_ids")
    if (not isinstance(source_list, list) or len(source_list) != 1
            or not isinstance(source_list[0], str) or not source_list[0].strip()):
        raise ReviewRequired("initial supported science route registers one source authority")
    source_id = source_list[0]
    sources = {x.get("id"): x for x in provenance.get("sources", []) if isinstance(x, dict)}
    source_spec = sources.get(source_id)
    if source_spec is None:
        raise CandidateFailure("science.source_id does not resolve to provenance.sources")
    try:
        parsed = match_candidate_source(final, source_spec, authority)
    except SourceAdapterError as exc:
        if "outside the registered" in str(exc):
            raise ReviewRequired("valid scientific source outside registered source authority") from exc
        raise CandidateFailure(str(exc)) from exc
    source_by_locator = {(row["entry"], row["source_row"]): row for row in parsed["included"]}
    target_differences = [abs(row["native_tabulated_kcal_mol"]-row["measurement_kcal_mol"])
                         for row in parsed["included"] if row["native_tabulated_kcal_mol"] is not None]
    source_profile_diagnostic = {"rows_with_both_values": len(target_differences),
                                 "max_abs_difference_kcal_mol": max(target_differences) if target_differences else None,
                                 "min_abs_difference_kcal_mol": min(target_differences) if target_differences else None,
                                 "interpretation": "unresolved; no target substitution or constant reconciliation implied"}
    table_specs = analysis.get("tables")
    if not isinstance(table_specs, list):
        raise CandidateFailure("analysis.tables must be an array")
    import case06_route_neutral as arithmetic
    source_ids = {source_id}
    execution_ids = {x.get("id") for x in provenance.get("executions", []) if isinstance(x, dict)}
    declared_use = {}
    native_observation_bindings = {}
    condition_columns = {"Temp (K)": "temperature_k", "Solvent": "solvent",
                         "Leaving Group": "leaving_group"}
    conditions = estimand["conditions"]
    if len(set(conditions)) != len(conditions) or set(conditions) - set(condition_columns):
        raise ReviewRequired("valid estimand condition fields outside the registered source adapter")
    for item in study["data_use_map"]:
        fields = {"observation_id", "source_id", "role", "instance_id", "group_id",
                  "native_row_locator", "condition_values"}
        if not isinstance(item, dict) or set(item) != fields:
            raise CandidateFailure("study.data_use_map entry is malformed")
        if any(not isinstance(item.get(k), str) or not item[k].strip()
               for k in ("observation_id", "source_id", "role", "instance_id", "group_id")):
            raise CandidateFailure("study.data_use_map identifiers must be nonempty strings")
        if item["source_id"] != source_id or item["role"] not in {"fit", "calibration", "heldout"}:
            raise CandidateFailure("study.data_use_map source or role conflicts with the supported study")
        key = (item["instance_id"], item["observation_id"])
        if key in declared_use:
            raise CandidateFailure("study.data_use_map has duplicate observation assignments")
        locator_row = item["native_row_locator"]
        if not isinstance(locator_row, dict) or set(locator_row) != {"key_field", "key_value", "source_row_index"}:
            raise CandidateFailure("study.data_use_map native_row_locator is malformed")
        if (locator_row["key_field"] != common_locator["row_key"]
                or not isinstance(locator_row["key_value"], str) or not locator_row["key_value"].strip()
                or type(locator_row["source_row_index"]) is not int or locator_row["source_row_index"] < 1):
            raise CandidateFailure("study.data_use_map native_row_locator is not a typed source row key")
        native = source_by_locator.get((locator_row["key_value"], locator_row["source_row_index"]))
        if native is None:
            raise CandidateFailure("study.data_use_map native locator does not resolve to an eligible source row")
        _bind_native_observation(native_observation_bindings, item["instance_id"], native,
                                 item["observation_id"])
        condition_values = item["condition_values"]
        if not isinstance(condition_values, dict) or set(condition_values) != set(conditions):
            raise CandidateFailure("study.data_use_map condition_values must match the declared estimand fields")
        for field in conditions:
            expected = native[condition_columns[field]]
            typed_actual = condition_values[field]
            if not isinstance(typed_actual, dict) or set(typed_actual) != {"value", "unit"}:
                raise CandidateFailure("study.data_use_map condition values require value and unit")
            actual = typed_actual["value"]
            if field == "Temp (K)":
                if typed_actual["unit"] != "K":
                    raise ReviewRequired("valid temperature unit outside the registered source adapter")
                if (isinstance(actual, bool) or not isinstance(actual, (int, float))
                        or not math.isfinite(actual) or not _close(actual, expected)):
                    raise CandidateFailure("study.data_use_map temperature condition differs from native source")
            else:
                if typed_actual["unit"] != "source_label":
                    raise ReviewRequired("valid categorical condition unit outside the registered source adapter")
                if not isinstance(actual, str):
                    raise CandidateFailure("study.data_use_map categorical condition value is malformed")
                if actual != expected:
                    raise ReviewRequired("valid categorical condition normalization outside the registered source adapter")
        declared_use[key] = {**item, "native": native}
    all_rows = {}
    condition_ids = {}
    candidate_reaction_to_native = {}
    native_reaction_to_candidate = {}
    native_group_to_candidate_groups = {}
    for table in table_specs:
        if not isinstance(table, dict) or not isinstance(table.get("path"), str):
            raise CandidateFailure("analysis table declaration is malformed")
        path = arithmetic._safe_table(final, table)
        rows = arithmetic._normalise_rows(arithmetic._load_table(path, table.get("format")),
                                          source_ids, execution_ids)
        for row in rows:
            if row["role"] not in {"fit", "calibration", "heldout"}:
                raise ReviewRequired("valid observation-role design outside the registered fit/calibration/heldout adapter")
            row["table_id"] = table.get("id")
            if source_id not in row["sources"]:
                raise CandidateFailure("scientific prediction row is not source-linked")
            data_use = declared_use.get((row["instance"], row["observation"]))
            if data_use is None:
                raise CandidateFailure("prediction observation has no declared native-row mapping")
            if (row["role"] != data_use["role"] or row["group"] != data_use["group_id"]):
                raise CandidateFailure("prediction table roles/groups differ from the declared data-use map")
            native = data_use["native"]
            reaction_key = (row["instance"], row["reaction"])
            native_reaction = native["reaction_smiles_raw"].strip()
            prior_native = candidate_reaction_to_native.setdefault(reaction_key, native_reaction)
            prior_candidate = native_reaction_to_candidate.setdefault((row["instance"], native_reaction), row["reaction"])
            if prior_native != native_reaction or prior_candidate != row["reaction"]:
                raise CandidateFailure("researcher-defined reaction labels do not map consistently to native reaction identities")
            condition_key = (row["instance"], row["observation"])
            prior_condition_id = condition_ids.setdefault(condition_key, row["condition"])
            if prior_condition_id != row["condition"]:
                raise CandidateFailure("paired prediction rows use conflicting researcher-defined condition IDs")
            native_group_to_candidate_groups.setdefault((row["instance"], native["group_id"]), set()).add(row["group"])
            if target_profile == TABULATED_PROFILE:
                expected_target = native["native_tabulated_kcal_mol"]
                if expected_target is None:
                    raise CandidateFailure("candidate used a source row with no native tabulated target")
            else:
                expected_target = native["measurement_kcal_mol"]
            if not _close(row["target"], expected_target):
                raise CandidateFailure("candidate target differs from its explicitly committed native target profile")
            row["native"] = native
            row["estimand_conditions"] = set(conditions)
            all_rows.setdefault(row["instance"], []).append(row)
    expected_use = {}
    for instance_id, entries in all_rows.items():
        for row in entries:
            key = (instance_id, row["observation"])
            value = (row["role"], row["group"], row["native"]["entry"], row["native"]["source_row"])
            prior = expected_use.get(key)
            if prior is not None and prior != value:
                raise CandidateFailure("the same source observation is assigned conflicting data-use roles")
            expected_use[key] = value
    declared_uses_normalized = {key: (value["role"], value["group_id"], value["native"]["entry"], value["native"]["source_row"])
                                for key, value in declared_use.items()}
    if declared_uses_normalized != expected_use:
        raise CandidateFailure("study.data_use_map does not exactly match submitted source-linked rows")
    if any(len(group_ids) != 1 for group_ids in native_group_to_candidate_groups.values()):
        raise CandidateFailure("candidate grouping splits a native reaction/duplicate component across groups")
    return science, authority, all_rows, source_profile_diagnostic


def _encode_feature(rows, feature, fit_count):
    fid, op = feature.get("id"), feature.get("operation")
    required = {"id", "source_field", "operation", "fit_scope", "missing_rule", "order"}
    optional = {"estimand_condition_fields", "unknown_category", "n_min", "n_max", "weighting", "case"}
    if not required <= set(feature) or set(feature)-required-optional:
        raise ReviewRequired("feature object differs from the supported exact schema")
    if not isinstance(fid, str) or not fid or feature.get("fit_scope") != "fit_only" or feature.get("missing_rule") != "reject":
        raise ReviewRequired("feature fit or missing-value policy outside supported domain")
    if type(feature.get("order")) is not int or feature["order"] < 0:
        raise CandidateFailure("feature order must be a nonnegative integer")
    key = feature.get("source_field")
    if not isinstance(key, str):
        raise ReviewRequired("valid feature source outside the registered source-field domain")
    if isinstance(key, str):
        compact_key = re.sub(r"[^a-z0-9]", "", key.casefold())
        target_derived = {
            "exprateconstantk1m1s1", "exprateconstantk1", "rateconstant", "rate", "k1", "logk",
            "activationfreeenergy", "activationfreeenergykcalmol1", "activationfreeenergykcalmol",
            "reportedactivationfreeenergy", "nativeactivationfreeenergy", "target", "targetvalue",
        }
        compact_op = re.sub(r"[^a-z0-9]", "", str(op).casefold())
        if compact_key in target_derived or any(token in compact_op for token in ("eyring", "ratetobarrier", "targetderived")):
            raise CandidateFailure("target-derived rate/barrier input cannot be claimed as an independent predictor")
    if key not in FEATURE_COLUMNS:
        raise ReviewRequired("valid feature source or feature generator outside initial supported domain")
    native_col, _, category = FEATURE_COLUMNS[key]
    if category == "condition" and key in {"temperature_k", "solvent", "leaving_group"}:
        declared = feature.get("estimand_condition_fields", [])
        if not isinstance(declared, list) or any(not isinstance(x, str) for x in declared):
            raise CandidateFailure("condition feature estimand_condition_fields must be a string array")
        if declared != [native_col]:
            raise ReviewRequired("condition feature declaration must name exactly its native estimand field")
        if native_col not in rows[0].get("estimand_conditions", set()):
            raise CandidateFailure("condition feature is not included in the declared estimand conditions")
    vals = [r["native"].get({"temperature_k":"temperature_k", "solvent":"solvent",
                              "substrate":"substrate_smiles", "nucleophile":"nucleophile_smiles",
                              "leaving_group":"leaving_group"}[key]) for r in rows]
    if op == "identity_numeric" and key == "temperature_k":
        return [[_num(v, "temperature feature")] for v in vals], ["temperature_k"]
    if op == "one_hot" and key in {"solvent", "leaving_group"}:
        categories = sorted(set(vals[:fit_count]))
        unknown_category = feature.get("unknown_category")
        if not isinstance(unknown_category, str) or unknown_category not in {"error", "all_zero"}:
            raise CandidateFailure("one_hot must declare unknown_category handling")
        if unknown_category == "error" and any(value not in categories for value in vals[fit_count:]):
            raise CandidateFailure("heldout row has an unknown one-hot category under error policy")
        return [[float(value == c) for c in categories] for value in vals], [f"{key}={c}" for c in categories]
    if op == "character_ngram" and key in {"substrate", "nucleophile"}:
        n_min, n_max = feature.get("n_min"), feature.get("n_max")
        if type(n_min) is not int or type(n_max) is not int or not (1 <= n_min <= n_max <= 8):
            raise CandidateFailure("character ngram bounds must be integers 1..8")
        if not isinstance(feature.get("weighting"), str) or feature.get("weighting") not in {"binary", "count"} or feature.get("case") != "preserve":
            raise ReviewRequired("valid character tokenization outside the supported exact policy")
        vocab = sorted({value[i:i+n] for value in vals[:fit_count] for n in range(n_min,n_max+1)
                        for i in range(max(0, len(value)-n+1))})
        x = []
        for value in vals:
            grams = [value[i:i+n] for n in range(n_min,n_max+1)
                     for i in range(max(0, len(value)-n+1))]
            x.append([float((grams.count(g) if feature["weighting"] == "count" else g in grams))
                      for g in vocab])
        return x, [f"{fid}:{g}" for g in vocab]
    raise ReviewRequired("valid feature operation outside initial supported source-field operations")


def _matrix(rows, features, fit_count):
    if not isinstance(features, list) or not features:
        raise CandidateFailure("model.features must be a nonempty ordered array")
    blocks = []
    names = []
    for feature in features:
        block, block_names = _encode_feature(rows, _require_object(feature, "feature"), fit_count)
        if len(block) != len(rows):
            raise CandidateFailure("feature encoder returned an inconsistent row count")
        blocks.append(block)
        names.extend(block_names)
    if len({feature.get("id") for feature in features if isinstance(feature, dict)}) != len(features):
        raise CandidateFailure("feature IDs must be unique")
    if not blocks or not names:
        raise CandidateFailure("feature matrix has inconsistent shape")
    matrix = [[value for block in blocks for value in block[row_index]] for row_index in range(len(rows))]
    orders = [feature.get("order") for feature in features]
    if orders != list(range(len(orders))):
        raise CandidateFailure("features must use contiguous order values starting at zero")
    return matrix, names


def _preprocess(x_train, x_predict, preprocessing):
    import numpy as np
    prep = _require_object(preprocessing, "preprocessing")
    if set(prep) != {"scaler", "pca"}:
        raise ReviewRequired("preprocessing must declare exactly scaler and pca")
    scaler = prep.get("scaler")
    pca = prep.get("pca")
    a, b = np.asarray(x_train, dtype=float), np.asarray(x_predict, dtype=float)
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise CandidateFailure("feature matrix contains missing or nonfinite values")
    if scaler == "standard_scale":
        mean, sd = a.mean(axis=0), a.std(axis=0)
        sd[sd == 0] = 1.0
        a, b = (a-mean)/sd, (b-mean)/sd
    elif scaler != "none":
        raise ReviewRequired("valid scaler outside supported preprocessing")
    if pca is not None:
        if not isinstance(pca, dict) or set(pca) - {"n_components", "solver"}:
            raise ReviewRequired("valid PCA configuration outside supported preprocessing")
        n = pca.get("n_components")
        if type(n) is not int or not 1 <= n <= min(a.shape):
            raise CandidateFailure("PCA n_components is outside the training matrix domain")
        if pca.get("solver") != "full":
            raise ReviewRequired("only deterministic full-SVD PCA is supported")
        from sklearn.decomposition import PCA
        transformer = PCA(n_components=n, svd_solver="full")
        a, b = transformer.fit_transform(a), transformer.transform(b)
    elif "pca" not in prep:
        raise CandidateFailure("preprocessing.pca is required (null or supported object)")
    return a, b


def _estimator(method, config):
    from sklearn.kernel_ridge import KernelRidge
    from sklearn.linear_model import Ridge
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, RBF, Matern, WhiteKernel
    cfg = _require_object(config, "model.configuration")
    if method == "ridge":
        if set(cfg) != {"alpha", "fit_intercept"}:
            raise ReviewRequired("Ridge parameter configuration is outside the exact supported form")
        alpha = _num(cfg.get("alpha"), "Ridge alpha")
        if alpha < 0: raise CandidateFailure("Ridge alpha must be nonnegative")
        if alpha > 1e6: raise ReviewRequired("valid Ridge alpha outside evaluator capability")
        if type(cfg.get("fit_intercept")) is not bool: raise CandidateFailure("fit_intercept must be boolean")
        return Ridge(alpha=alpha, fit_intercept=cfg["fit_intercept"])
    if method == "kernel_ridge":
        alpha = _num(cfg.get("alpha"), "KernelRidge alpha")
        kernel = cfg.get("kernel")
        if alpha <= 0: raise CandidateFailure("KernelRidge alpha must be positive")
        if alpha > 1e6: raise ReviewRequired("valid KernelRidge alpha outside evaluator capability")
        if not isinstance(kernel, str) or kernel not in {"linear", "rbf", "poly", "sigmoid", "laplacian"}:
            raise ReviewRequired("valid KernelRidge kernel outside supported domain")
        allowed = {"alpha", "kernel", "gamma", "degree", "coef0"}
        if set(cfg)-allowed: raise ReviewRequired("unsupported KernelRidge parameter")
        kwargs = {"alpha": alpha, "kernel": kernel}
        if "gamma" in cfg:
            gamma = _num(cfg["gamma"], "gamma")
            if gamma <= 0: raise CandidateFailure("KernelRidge gamma must be positive")
            if gamma > 1e6: raise ReviewRequired("valid KernelRidge gamma outside evaluator capability")
            kwargs["gamma"] = gamma
        if "degree" in cfg:
            if type(cfg["degree"]) is not int or cfg["degree"] < 1: raise CandidateFailure("degree must be a positive integer")
            if cfg["degree"] > 8: raise ReviewRequired("valid polynomial degree outside evaluator capability")
            kwargs["degree"] = cfg["degree"]
        if "coef0" in cfg:
            coef0 = _num(cfg["coef0"], "coef0")
            if abs(coef0) > 1e6: raise ReviewRequired("valid coef0 outside evaluator capability")
            kwargs["coef0"] = coef0
        return KernelRidge(**kwargs)
    if method == "gaussian_process":
        if cfg.get("optimizer") != "none": raise ReviewRequired("GPR optimizer outside supported fixed-kernel domain")
        if set(cfg)-{"optimizer", "kernel", "alpha", "normalize_y"}: raise ReviewRequired("unsupported GPR parameter")
        kernel_spec = _require_object(cfg.get("kernel"), "GPR kernel")
        if set(kernel_spec) != {"amplitude", "length_scale", "noise_level", "base_kernel", "nu"}:
            raise ReviewRequired("GPR kernel tree is outside supported exact configuration")
        amp, ell, noise = (_num(kernel_spec[x], f"GPR {x}") for x in ("amplitude", "length_scale", "noise_level"))
        if not all(v > 0 for v in (amp,ell,noise)): raise CandidateFailure("GPR covariance scales must be positive")
        if not all(1e-8 <= v <= 1e6 for v in (amp,ell,noise)): raise ReviewRequired("valid GPR covariance scale outside evaluator capability")
        base = kernel_spec["base_kernel"]
        if base == "rbf" and kernel_spec.get("nu") is None: base_kernel = RBF(length_scale=ell)
        elif (base == "matern" and type(kernel_spec.get("nu")) in (int, float)
              and kernel_spec.get("nu") in {0.5,1.5,2.5}): base_kernel = Matern(length_scale=ell,nu=kernel_spec["nu"])
        else: raise ReviewRequired("GPR base kernel outside supported domain")
        alpha = _num(cfg.get("alpha"), "GPR alpha")
        if alpha < 0: raise CandidateFailure("GPR alpha must be nonnegative")
        if alpha > 1e6: raise ReviewRequired("valid GPR alpha outside evaluator capability")
        if type(cfg.get("normalize_y")) is not bool: raise CandidateFailure("normalize_y must be boolean")
        return GaussianProcessRegressor(kernel=ConstantKernel(amp)*base_kernel+WhiteKernel(noise),
                                        alpha=alpha, optimizer=None, normalize_y=cfg["normalize_y"])
    raise ReviewRequired("valid estimator outside supported method domain")


def _predict(rows_fit, rows_predict, model):
    import numpy as np
    features = model.get("features")
    x_all, names = _matrix(rows_fit+rows_predict, features, len(rows_fit))
    x_fit, x_pred = x_all[:len(rows_fit)], x_all[len(rows_fit):]
    x_fit, x_pred = _preprocess(x_fit, x_pred, model.get("preprocessing"))
    y = np.asarray([r["target"] for r in rows_fit], dtype=float)
    if len(y) < 2: raise ReviewRequired("independent fit requires at least two observations")
    estimator = _estimator(model.get("method"), model.get("configuration"))
    estimator.fit(x_fit, y)
    pred = np.asarray(estimator.predict(x_pred), dtype=float)
    if not np.isfinite(pred).all(): raise CandidateFailure("independent replay produced nonfinite predictions")
    return pred.tolist(), names, estimator


def _selected_configuration(model, fit_rows):
    selection = _require_object(model.get("selection"), "model.selection")
    fit_ids = {r["observation"] for r in fit_rows}
    fit_by_id = {r["observation"]: r for r in fit_rows}
    if selection == {"mode": "none"}:
        return model.get("configuration"), {"mode": "none"}
    if set(selection) != {"mode", "configurations", "folds", "score", "direction", "tie_rule"} or selection.get("mode") != "grid":
        raise ReviewRequired("valid model-selection protocol outside supported none/grid forms")
    configs, folds = selection.get("configurations"), selection.get("folds")
    if not isinstance(configs, list) or not configs or not isinstance(folds, list) or not folds:
        raise CandidateFailure("selection requires a nonempty configuration grid and explicit folds")
    if len(folds) < 2:
        raise ReviewRequired("valid single-split model selection is outside the registered replay")
    if len(configs) > 100:
        raise ReviewRequired("valid model-selection grid exceeds the registered evaluator limit")
    if (selection.get("score"), selection.get("direction"), selection.get("tie_rule")) != ("mae", "minimize", "first_declared_order"):
        raise ReviewRequired("valid model selection scoring/tie protocol is unsupported")
    scores = []
    canonical_configs = []
    for cfg in configs:
        _require_object(cfg, "selection configuration")
        canonical = json.dumps(cfg, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if canonical in canonical_configs:
            raise CandidateFailure("selection configuration grid contains duplicates")
        canonical_configs.append(canonical)
        fold_scores = []
        for fold in folds:
            if not isinstance(fold, dict) or set(fold) != {"train_observation_ids", "validation_observation_ids"}:
                raise CandidateFailure("selection fold must list exact train and validation observation IDs")
            train_ids, valid_ids = fold["train_observation_ids"], fold["validation_observation_ids"]
            if (not isinstance(train_ids, list) or not isinstance(valid_ids, list)
                    or any(not isinstance(x, str) for x in train_ids+valid_ids)
                    or len(set(train_ids)) != len(train_ids) or len(set(valid_ids)) != len(valid_ids)
                    or not set(train_ids) or not set(valid_ids)
                    or not set(train_ids) <= fit_ids or not set(valid_ids) <= fit_ids
                    or set(train_ids) & set(valid_ids)):
                raise CandidateFailure("selection fold IDs are duplicate, empty, outside fit role, or overlapping")
            tr, va = [fit_by_id[x] for x in train_ids], [fit_by_id[x] for x in valid_ids]
            if {r["group"] for r in tr} & {r["group"] for r in va}:
                raise CandidateFailure("selection fold leaks a native reaction/source group")
            probe = dict(model, configuration=cfg)
            predictions, _, _ = _predict(tr, va, probe)
            fold_scores.append(sum(abs(y["target"]-p) for y,p in zip(va,predictions))/len(va))
        scores.append(sum(fold_scores)/len(fold_scores))
    best = min(range(len(scores)), key=lambda idx: (scores[idx], idx))
    if model.get("configuration") != configs[best]:
        raise CandidateFailure("declared final configuration is not the independently selected grid minimum")
    return configs[best], {"mode": "grid", "mean_fold_mae": scores, "selected_index": best}


def evaluate_science(final, results, provenance, route_metrics):
    """Return independent science evidence and typed decision or raise a verdict error."""
    science, authority, instances, source_profile_diagnostic = _rows(final, results, provenance)
    # Additional branches are applied in case06_science_decision after the
    # primary/control and interval computations have been independently replayed.
    model = _require_object(science.get("model"), "analysis.science.model")
    model_fields = {"method", "configuration", "features", "preprocessing", "roles", "primary_arm_id",
                    "fit_scope", "fit_observation_ids", "fit_group_ids", "prediction_table_id",
                    "implementation", "seed", "selection"}
    if set(model) != model_fields:
        raise ReviewRequired("model declaration uses unsupported or missing fields")
    table_ids = {t.get("id") for t in results.get("analysis", {}).get("tables", []) if isinstance(t, dict)}
    if not isinstance(model.get("prediction_table_id"), str) or model["prediction_table_id"] not in table_ids:
        raise CandidateFailure("model.prediction_table_id must resolve to an analysis table")
    if table_ids != {model["prediction_table_id"]}:
        raise ReviewRequired("multiple prediction tables are valid but outside the initial single-table science replay")
    roles = _require_object(model["roles"], "model.roles")
    if set(roles) != {"fit", "calibration", "heldout"}:
        raise CandidateFailure("supported model roles must name fit, calibration and heldout sets")
    primary_arm = model.get("primary_arm_id")
    if not isinstance(primary_arm, str) or not primary_arm:
        raise CandidateFailure("model.primary_arm_id must be a nonempty string")
    pred_rows = []
    held_replay = {}
    control_replay = {}
    seed = model.get("seed")
    if seed is not None and (type(seed) is not int or not 0 <= seed <= 2**32-1):
        raise CandidateFailure("model.seed must be null or an integer in [0,2^32-1]")
    if model.get("fit_scope") != "declared_fit_role_only" or not isinstance(model.get("implementation"), str) or not model["implementation"].strip():
        raise CandidateFailure("model fit scope and implementation identity must be explicit")
    control_spec = _require_object(science.get("control"), "analysis.science.control")
    if set(control_spec) != {"arm_id", "kind", "definition", "computation_record_path"}:
        raise ReviewRequired("control definition is outside the supported typed domain")
    control_arm = control_spec.get("arm_id")
    if not isinstance(control_arm, str) or not control_arm or control_arm == primary_arm:
        raise CandidateFailure("control arm identity is invalid")
    _safe_final_file(final, control_spec.get("computation_record_path"))
    if len(instances) != 1:
        raise ReviewRequired("multiple independent evaluation instances are valid but outside this replay adapter")
    for instance_id, rows in instances.items():
        primary_rows = [r for r in rows if r["arm"] == primary_arm and r["table_id"] == model["prediction_table_id"]]
        if not primary_rows:
            raise CandidateFailure("model.primary_arm_id has no registered prediction rows")
        by_role = {role: [r for r in primary_rows if r["role"] == role] for role in ROLE}
        for role in ("fit", "calibration", "heldout"):
            ids = roles.get(role)
            if (not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids)
                    or len(set(ids)) != len(ids)):
                raise CandidateFailure(f"model.roles.{role} must be a nonempty observation ID array")
            expected = {r["observation"] for r in by_role[role]}
            if set(ids) != expected:
                raise CandidateFailure(f"model role IDs disagree with prediction table role {role}")
        if set(roles["fit"]) & (set(roles["calibration"]) | set(roles["heldout"])) or set(roles["calibration"]) & set(roles["heldout"]):
            raise CandidateFailure("fit/calibration/heldout observation roles overlap")
        lookup = {r["observation"]: r for r in primary_rows}
        fit = [lookup[x] for x in roles["fit"]]
        cal = [lookup[x] for x in roles["calibration"]]
        held = [lookup[x] for x in roles["heldout"]]
        group_sets = [{r["group"] for r in part} for part in (fit,cal,held)]
        if any(group_sets[i]&group_sets[j] for i,j in ((0,1),(0,2),(1,2))):
            raise CandidateFailure("supported scientific validation requires disjoint source groups")
        fit_declared, groups_declared = model.get("fit_observation_ids"), model.get("fit_group_ids")
        if (not isinstance(fit_declared, list) or not isinstance(groups_declared, list)
                or any(not isinstance(x, str) for x in fit_declared+groups_declared)
                or len(fit_declared) != len(set(fit_declared)) or len(groups_declared) != len(set(groups_declared))
                or set(fit_declared) != {r["observation"] for r in fit}
                or set(groups_declared) != {r["group"] for r in fit}):
            raise CandidateFailure("model fit observation/group identities differ from its committed fit role")
        _, selection_report = _selected_configuration(model, fit)
        cal_and_held = cal + held
        pred, feature_names, estimator = _predict(fit, cal_and_held, model)
        cal_pred, held_pred = pred[:len(cal)], pred[len(cal):]
        for row, value in zip(cal, cal_pred):
            if row["prediction"] is None or not _close(row["prediction"], value):
                raise CandidateFailure("candidate calibration prediction differs from grader independent refit")
        interval_spec = _require_object(science.get("interval"), "analysis.science.interval")
        if set(interval_spec) != {"method", "level", "group_unit"} or interval_spec.get("method") != "split_conformal_abs_residual" or interval_spec.get("group_unit") != "max_abs_residual_per_group":
            raise ReviewRequired("valid interval method outside registered grouped split-conformal domain")
        level = _num(interval_spec.get("level"), "interval level")
        if not 0 < level < 1:
            raise CandidateFailure("interval level must be strictly between zero and one")
        residual_by_group = {}
        for row, value in zip(cal, cal_pred):
            residual_by_group[row["group"]] = max(residual_by_group.get(row["group"], 0.0), abs(row["target"]-value))
        n_groups = len(residual_by_group)
        rank = grouped_conformal_rank(n_groups, level)
        if rank > n_groups:
            raise ReviewRequired("group conformal quantile is infinite at the declared calibration-group count/level")
        quantile = sorted(residual_by_group.values())[rank-1]
        # Candidate interval rows must agree with the grader's fit-only model,
        # calibration-only residual quantile and exact test row.
        for row, value in zip(held, held_pred):
            if row["prediction"] is None or not _close(row["prediction"], value):
                raise CandidateFailure("candidate heldout prediction differs from grader independent refit")
            expected_interval = (value-quantile, value+quantile, level)
            if row["interval"] is None or not all(_close(a,b) for a,b in zip(row["interval"], expected_interval)):
                raise CandidateFailure("candidate heldout interval differs from grouped split-conformal replay")
            pred_rows.append({"observation_id": row["observation"], "prediction": value,
                              "target": row["target"], "group_id": row["group"],
                              "role": "heldout", "instance_id": instance_id})
            held_replay[row["observation"]] = {"prediction": value, "target": row["target"],
                "group_id": row["group"], "lower": value-quantile, "upper": value+quantile}
        control_rows = [r for r in rows if r["arm"] == control_arm and r["role"] == "heldout"
                        and r["table_id"] == model["prediction_table_id"]]
        if any(r["arm"] == control_arm and r["role"] != "heldout" for r in rows):
            raise ReviewRequired("control rows outside heldout are not replayed in this adapter")
        table_arms = {r["arm"] for r in rows if r["table_id"] == model["prediction_table_id"]}
        if table_arms != {primary_arm, control_arm}:
            raise ReviewRequired("additional prediction arms are valid but outside this replay route")
        if {r["observation"] for r in control_rows} != {r["observation"] for r in held}:
            raise CandidateFailure("control and primary heldout rows are not exactly paired")
        control_by_id = {r["observation"]: r for r in control_rows}
        kind = control_spec.get("kind")
        if not isinstance(kind, str):
            raise CandidateFailure("control.kind must be a string")
        if kind in {"training_mean", "training_median"}:
            expected_definition = {"fit_scope": "fit_role_only",
                                   "statistic": "arithmetic_mean" if kind == "training_mean" else "median"}
            if control_spec.get("definition") != expected_definition:
                raise CandidateFailure("control baseline definition does not match its typed statistic and fit scope")
            train_targets = [r["target"] for r in fit]
            if kind == "training_mean": expected_control = sum(train_targets)/len(train_targets)
            else:
                ordered = sorted(train_targets)
                mid = len(ordered)//2
                expected_control = ordered[mid] if len(ordered)%2 else (ordered[mid-1]+ordered[mid])/2
            for row in held:
                actual = control_by_id[row["observation"]]["prediction"]
                if actual is None or not _close(actual, expected_control):
                    raise CandidateFailure("control prediction differs from independently replayed fit-only baseline")
                control_replay[row["observation"]] = {"prediction": expected_control, "target": row["target"],
                    "group_id": row["group"]}
        elif kind == "model":
            submodel = _require_object(control_spec.get("definition"), "control model")
            if set(submodel) != {"method", "configuration", "features", "preprocessing"}:
                raise ReviewRequired("valid control estimator outside the fixed independently replayable model form")
            control_pred, _, _ = _predict(fit, held, submodel)
            for row, value in zip(held, control_pred):
                actual = control_by_id[row["observation"]]["prediction"]
                if actual is None or not _close(actual, value):
                    raise CandidateFailure("control prediction differs from independent estimator replay")
                control_replay[row["observation"]] = {"prediction": value, "target": row["target"],
                    "group_id": row["group"]}
        elif kind == "native_published_prediction":
            raise ReviewRequired("native published prediction control requires an additional registered authority adapter")
        else:
            raise ReviewRequired("valid control route outside the supported baseline/model subset")
        if any(r["interval"] is not None for r in control_rows):
            raise ReviewRequired("control prediction intervals are not independently replayed in this initial route")
        _validate_control_record(final, control_spec, fit, held, control_replay)
    replay_metrics = _recompute_claimed_metrics(results, route_metrics, science, held_replay, control_replay)
    return {"status": "REPLAYED_PRIMARY_AND_CONTROL", "rows": pred_rows, "metrics": replay_metrics,
            "source": {"doi": "10.1039/D0SC04896H", "native_si_sha256": authority["native_si_sha256"],
                       "archive_sha256": authority["raw_archive_sha256"], "member_sha256": authority["source_csv_sha256"],
                       "target_profile": science["study"]["target_definition"]["profile_id"],
                       "derived_target_audit": authority["target_spec"],
                       "profile_difference_diagnostic": source_profile_diagnostic},
            "primary_arm_id": primary_arm, "control_arm_id": control_arm,
            "model_selection": selection_report,
            "control_kind": control_spec["kind"],
            "limits": ["Published SI correspondence is not authentication of primary experimental truth",
                       "Public labels are exposed unless separately restricted evidence is validated"]}


def _validate_control_record(final, control_spec, fit_rows, held_rows, replay):
    import json
    path = _safe_final_file(final, control_spec.get("computation_record_path"))
    try:
        record = json.loads(path.read_text(encoding="utf-8"),
                            parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (OSError, UnicodeError, ValueError) as exc:
        raise CandidateFailure("control computation record is missing or malformed") from exc
    expected = {"schema", "arm_id", "kind", "definition", "fit_observation_ids", "fit_group_ids",
                "heldout_observation_ids", "predictions"}
    if not isinstance(record, dict) or set(record) != expected or record.get("schema") != "case06-control-computation/v1":
        raise CandidateFailure("control computation record schema is invalid")
    fit_ids = sorted(r["observation"] for r in fit_rows)
    fit_groups = sorted({r["group"] for r in fit_rows})
    held_ids = sorted(r["observation"] for r in held_rows)
    if (record.get("arm_id") != control_spec.get("arm_id") or record.get("kind") != control_spec.get("kind")
            or record.get("definition") != control_spec.get("definition")
            or record.get("fit_observation_ids") != fit_ids or record.get("fit_group_ids") != fit_groups
            or record.get("heldout_observation_ids") != held_ids):
        raise CandidateFailure("control computation record does not bind the actual replay fit/heldout roles")
    declared_predictions = record.get("predictions")
    if not isinstance(declared_predictions, dict) or set(declared_predictions) != set(held_ids):
        raise CandidateFailure("control computation record must contain one prediction per paired heldout observation")
    for observation_id in held_ids:
        value = _num(declared_predictions[observation_id], "control computation record prediction")
        if not _close(value, replay[observation_id]["prediction"]):
            raise CandidateFailure("control computation record prediction differs from independent replay")


def _recompute_claimed_metrics(results, route_metrics, science, primary_rows, control_rows):
    """Recompute the finite typed-claim metrics from full-precision independent replays."""
    metric_specs = {x.get("id"): x for x in results.get("analysis", {}).get("metric_claims", [])
                    if isinstance(x, dict) and isinstance(x.get("id"), str)}
    supplied = {x.get("id"): x for x in route_metrics.get("metrics", [])
                if isinstance(x, dict) and isinstance(x.get("id"), str)}
    criteria = science.get("criteria", [])
    requested = {x.get("metric_claim_id") for x in criteria if isinstance(x, dict)}
    comparisons = {x.get("id"): x for x in results.get("analysis", {}).get("protocol", {}).get("comparisons", [])
                   if isinstance(x, dict)}
    output = []
    for ident in sorted(requested):
        spec, prior = metric_specs.get(ident), supplied.get(ident)
        if spec is None or prior is None:
            raise CandidateFailure("typed criterion metric does not resolve to one reported metric claim")
        if (spec.get("table_id") != science["model"]["prediction_table_id"]
                or spec.get("evaluation_role") != "heldout"
                or spec.get("evaluation_instance_id", "default") != "default"
                or "stratum_value" in spec):
            raise ReviewRequired("valid metric population outside the initial single heldout replay scope")
        stat = spec.get("statistic")
        common = {"id": ident, "table_id": spec["table_id"],
                  "evaluation_instance_id": spec.get("evaluation_instance_id", "default"),
                  "statistic": stat, "evaluation_role": "heldout",
                  "arm_id": spec.get("arm_id"), "comparison_id": spec.get("comparison_id"),
                  "unit": "kcal/mol" if stat in {"mae", "rmse", "group_macro_mae", "interval_mean_width", "paired_delta_mae"} else "1",
                  "interval_level": spec.get("interval_level"), "denominators": {}}
        rows = list(primary_rows.values())
        errors = [r["prediction"]-r["target"] for r in rows]
        if stat in {"mae", "rmse", "group_macro_mae", "interval_coverage", "interval_mean_width"}:
            if spec.get("arm_id") != science["model"]["primary_arm_id"]:
                raise CandidateFailure("heldout science metric is not linked to the independently replayed primary arm")
            if stat == "mae": value = sum(abs(e) for e in errors)/len(errors)
            elif stat == "rmse": value = math.sqrt(sum(e*e for e in errors)/len(errors))
            elif stat == "group_macro_mae":
                grouped = {}
                for r in rows: grouped.setdefault(r["group_id"], []).append(abs(r["prediction"]-r["target"]))
                value = sum(sum(v)/len(v) for v in grouped.values())/len(grouped)
            elif stat == "interval_coverage":
                if spec.get("interval_level") != science["interval"]["level"]:
                    raise CandidateFailure("claimed interval metric does not use the committed level")
                value = sum(r["lower"] <= r["target"] <= r["upper"] for r in rows)/len(rows)
                common["unit"] = "1"
            else:
                if spec.get("interval_level") != science["interval"]["level"]:
                    raise CandidateFailure("claimed interval metric does not use the committed level")
                value = sum(r["upper"]-r["lower"] for r in rows)/len(rows)
            common["denominators"] = {"population_n": len(rows), "group_n": len({r["group_id"] for r in rows})}
        elif stat == "paired_delta_mae":
            comp = comparisons.get(spec.get("comparison_id"))
            if (comp is None or comp.get("candidate_arm_id") != science["model"]["primary_arm_id"]
                    or comp.get("control_arm_id") != science["control"]["arm_id"]
                    or comp.get("evaluation_role") != "heldout"):
                raise CandidateFailure("paired heldout metric is not the declared primary-versus-replayed-control comparison")
            if set(primary_rows) != set(control_rows):
                raise CandidateFailure("independently replayed primary and control populations are not paired")
            value = sum(abs(primary_rows[k]["prediction"]-primary_rows[k]["target"])
                        - abs(control_rows[k]["prediction"]-control_rows[k]["target"])
                        for k in primary_rows)/len(primary_rows)
            common["denominators"] = {"registered_n": len(primary_rows), "paired_n": len(primary_rows),
                                       "contributing_group_n": len({r["group_id"] for r in primary_rows.values()})}
        else:
            raise ReviewRequired("typed claim statistic is outside the independent replay metric domain")
        if not math.isfinite(value):
            raise ReviewRequired("independent replay produced an undefined scientific metric")
        common["value"] = value
        output.append(common)
    return {"metrics": output, "component_metrics": list(route_metrics.get("metrics", []))}
