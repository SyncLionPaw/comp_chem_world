#!/usr/bin/env python3
"""Fail-closed verifier for a Case-02 independent submission.

The verifier never executes submitted training code. It replays public target/split joins and
recomputes reported metrics from submitted row-level predictions, while treating model-selection
and feature-identity evidence as declared protocol evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import stat
import sys
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

import numpy as np
from case02_independent_refit import (refit as independent_refit, candidate_count,
                                       ReviewRequired, CandidateProtocolError, prediction_matches_refit,
                                       normalize_cv, normalize_arm, canonical_estimator)

REQUIRED_OUTPUTS = {
    "model_comparison.csv",
    "feature_set_map.json",
    "test_predictions.csv",
    "notes.md",
    "protocol.json",
    "model_spec.json",
}
MATRIX_FILES = {
    "Full": "SC-012-D0SC04896H-s120.csv",
    "No TS": "SC-012-D0SC04896H-s138.csv",
    "Small": "SC-012-D0SC04896H-s140.csv",
    "Surface": "SC-012-D0SC04896H-s141.csv",
    "Traditional": "SC-012-D0SC04896H-s142.csv",
    "Only TS": "SC-012-D0SC04896H-s143.csv",
}
REQUIRED_MODELS = {"direct_barrier", "linear_correction", "mean_baseline", "no_ts", "hybrid"}
PRED_COLUMNS = {"row_index", "true_experimental_barrier", "predicted_barrier"}
COMPARISON_COLUMNS = {
    "model", "feature_set_label", "source_matrix_file", "protocol", "seed",
    "n_train", "n_test", "mae_kcal_mol", "rmse_kcal_mol", "r2",
    "prediction_file", "is_preferred",
}
TOL = 1e-7


class ScienceFailure(Exception):
    pass


class InfrastructureFailure(Exception):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def read_json(path: Path, label: str) -> Any:
    try:
        def no_duplicate_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key: {key}")
                result[key] = value
            return result
        def reject_constant(value):
            raise ValueError(f"non-finite JSON constant: {value}")
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_pairs,
                          parse_constant=reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ScienceFailure(f"{label} is missing or invalid JSON: {exc}") from exc


def check_evaluation_inputs(assets: Path, refs: Path) -> None:
    """Broken evaluator inputs are infrastructure failures, never candidate failures."""
    try:
        if not assets.is_dir() or assets.is_symlink() or not refs.is_file() or refs.is_symlink():
            raise ValueError("assets or protected refs unavailable/unsafe")
        reference = json.loads(refs.read_text(encoding="utf-8"))
        if not isinstance(reference, dict) or reference.get("case_id") != "case-02-mechanistic-feature-gain":
            raise ValueError("protected refs must identify Case 02")
        pins = reference.get("asset_hashes")
        expected = set(MATRIX_FILES.values()) | {
            "SC-012-D0SC04896H-s112.csv", "SC-012-D0SC04896H-s115.csv",
            "SC-012-D0SC04896H-s007.py", "SC-012-D0SC04896H-s144.csv", "SC-012-D0SC04896H-s118.npy",
            "SC-012-D0SC04896H-s119.npy", "S5_model_benchmark.csv",
        }
        if not isinstance(pins, dict) or set(pins) != {"assets/" + name for name in expected}:
            raise ValueError("protected refs asset hashes are incomplete or unexpected")
        for name in sorted(expected):
            path = assets / name
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"evaluator input missing or unsafe: {name}")
            if pins["assets/" + name] != sha256(path):
                raise ValueError(f"evaluator input SHA-256 mismatch: {name}")
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise InfrastructureFailure(f"evaluation input validation failed: {exc}") from exc


def finite(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScienceFailure(f"{label} is not numeric") from exc
    if not math.isfinite(number):
        raise ScienceFailure(f"{label} is not finite")
    return number


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=TOL)


def csv_rows(path: Path, required: set[str], label: str) -> list[dict[str, str]]:
    if not path.is_file() or path.is_symlink():
        raise ScienceFailure(f"required output missing or unsafe: {label}")
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or [])
            if not required.issubset(fields):
                raise ScienceFailure(f"{label} missing columns: {sorted(required - fields)}")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ScienceFailure(f"cannot read {label}: {exc}") from exc
    if not rows:
        raise ScienceFailure(f"{label} has no rows")
    return rows


def check_submission_manifest(final: Path) -> None:
    """Validate an exact byte inventory; the manifest intentionally excludes itself."""
    manifest = read_json(final / "submission_manifest.json", "submission_manifest.json")
    if (not isinstance(manifest, dict)
            or manifest.get("schema") != "case02-submission-manifest/v1"
            or not isinstance(manifest.get("files"), dict)):
        raise ScienceFailure("submission_manifest.json must use case02-submission-manifest/v1")
    declared = manifest["files"]
    if not declared:
        raise ScienceFailure("submission manifest must inventory all submission files except itself")
    normalized: set[str] = set()
    for name, digest in declared.items():
        if not isinstance(name, str) or "\\" in name:
            raise ScienceFailure("submission manifest contains an unsafe path")
        rel = PurePosixPath(name)
        if rel.is_absolute() or not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
            raise ScienceFailure("submission manifest contains an unsafe path")
        if name != rel.as_posix() or name == "submission_manifest.json":
            raise ScienceFailure("submission manifest paths must be normalized and exclude the manifest itself")
        if not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
            raise ScienceFailure(f"submission manifest has an invalid SHA-256 value: {name}")
        target = final.joinpath(*rel.parts)
        try:
            resolved = target.resolve(strict=True)
            resolved.relative_to(final.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise ScienceFailure(f"submission manifest path escapes final/ or is missing: {name}") from exc
        if target.is_symlink() or not target.is_file():
            raise ScienceFailure(f"submission manifest path is not a regular file: {name}")
        if sha256(target) != digest:
            raise ScienceFailure(f"submission manifest SHA-256 mismatch: {name}")
        normalized.add(name)
    actual: set[str] = set()
    for path in final.rglob("*"):
        if path.is_symlink():
            raise ScienceFailure(f"submission contains a symbolic link: {path.relative_to(final).as_posix()}")
        if path.is_file():
            name = path.relative_to(final).as_posix()
            if name != "submission_manifest.json":
                actual.add(name)
    if actual != normalized:
        raise ScienceFailure(f"submission manifest inventory mismatch; missing={sorted(actual-normalized)}, extra={sorted(normalized-actual)}")


def resolve_prediction_path(final: Path, raw_path: str) -> Path:
    """Resolve a normalized relative CSV path without following symlink components."""
    if not isinstance(raw_path, str):
        raise ScienceFailure("prediction_file must be a normalized safe relative CSV path")
    relative = PurePosixPath(raw_path)
    if (not raw_path or "\\" in raw_path or relative.is_absolute()
            or raw_path != relative.as_posix()
            or any(part in {"", ".", ".."} for part in raw_path.split("/"))
            or relative.suffix != ".csv"):
        raise ScienceFailure("prediction_file must be a normalized safe relative CSV path")
    final_root = final.resolve(strict=True)
    target = final
    for index, part in enumerate(relative.parts):
        target = target / part
        try:
            mode = target.lstat().st_mode
        except OSError as exc:
            raise ScienceFailure(f"prediction_file is missing or inaccessible: {raw_path}") from exc
        if stat.S_ISLNK(mode):
            raise ScienceFailure(f"prediction_file traverses a symbolic link: {raw_path}")
        if index < len(relative.parts) - 1:
            if not stat.S_ISDIR(mode):
                raise ScienceFailure(f"prediction_file parent is not a regular directory: {raw_path}")
        elif not stat.S_ISREG(mode):
            raise ScienceFailure(f"prediction_file is not a regular file: {raw_path}")
    try:
        target.resolve(strict=True).relative_to(final_root)
    except (OSError, ValueError) as exc:
        raise ScienceFailure(f"prediction_file escapes final/: {raw_path}") from exc
    return target


def load_targets(assets: Path) -> dict[int, float]:
    paths = [assets / "SC-012-D0SC04896H-s144.csv", assets / "SC-012-D0SC04896H-s115.csv"]
    tables = []
    for path in paths:
        rows = csv_rows(path, {"exp_activation_energy"}, path.name)
        fields = list(rows[0])
        index_name = fields[0]
        table = {int(float(row[index_name])): finite(row["exp_activation_energy"], f"{path.name} target") for row in rows}
        if set(table) != set(range(443)):
            raise InfrastructureFailure(f"{path.name} must contain exactly row indices 0..442")
        tables.append(table)
    if tables[0] != tables[1]:
        raise InfrastructureFailure("s144 and s115 public target columns disagree")
    return tables[0]


def load_declared_barrier(assets: Path, declaration: dict[str, Any]) -> np.ndarray:
    source = declaration.get("source_matrix_file")
    column = declaration.get("column") or declaration.get("barrier_column")
    if not isinstance(source, str) or not isinstance(column, str):
        raise ReviewRequired("raw-barrier baseline must identify a supported public activation-energy column")
    if not column.startswith("activation_energy_"):
        raise ReviewRequired("declared direct barrier is not in the public activation-energy column domain")
    try:
        trusted = csv_rows(assets / "SC-012-D0SC04896H-s112.csv", {column}, "s112 barrier table")
    except ScienceFailure:
        raise ReviewRequired(f"declared barrier column {column} is not a supported public s112 column") from None
    if len(trusted) != 443:
        raise InfrastructureFailure("s112 barrier table must contain 443 rows")
    index_name = next(iter(trusted[0]))
    if [int(float(row[index_name])) for row in trusted] != list(range(443)):
        raise InfrastructureFailure("s112 barrier table row indices are not canonical")
    values = np.asarray([finite(row[column], f"s112:{column}") for row in trusted], dtype=float)
    if source != "SC-012-D0SC04896H-s112.csv":
        path = assets / source
        if not path.is_file() or path.is_symlink():
            raise ReviewRequired(f"declared barrier table {source} is not a public asset")
        rows = csv_rows(path, {column}, source)
        if len(rows) != 443:
            raise InfrastructureFailure(f"{source} barrier table must contain 443 rows")
        submitted_index = next(iter(rows[0]))
        if [int(float(row[submitted_index])) for row in rows] != list(range(443)):
            raise InfrastructureFailure(f"{source} barrier table row indices are not canonical")
        submitted = np.asarray([finite(row[column], f"{source}:{column}") for row in rows], dtype=float)
        if not np.allclose(submitted, values, rtol=0.0, atol=1e-12):
            raise ScienceFailure("declared barrier column differs from the trusted public s112 barrier column")
    return values


def load_split(assets: Path) -> tuple[list[int], list[int]]:
    try:
        train = np.load(assets / "SC-012-D0SC04896H-s119.npy", allow_pickle=False)
        test = np.load(assets / "SC-012-D0SC04896H-s118.npy", allow_pickle=False)
    except Exception as exc:
        raise InfrastructureFailure(f"cannot load frozen split arrays: {exc}") from exc
    if train.ndim != 1 or test.ndim != 1 or not np.issubdtype(train.dtype, np.integer) or not np.issubdtype(test.dtype, np.integer):
        raise InfrastructureFailure("frozen split arrays must be one-dimensional integer vectors")
    train_list, test_list = train.astype(int).tolist(), test.astype(int).tolist()
    if len(train_list) != 354 or len(test_list) != 89:
        raise InfrastructureFailure("frozen split must contain 354 training and 89 test rows")
    if len(set(train_list)) != 354 or len(set(test_list)) != 89 or set(train_list) & set(test_list):
        raise InfrastructureFailure("frozen train/test indices overlap or contain duplicates")
    if set(train_list) | set(test_list) != set(range(443)):
        raise InfrastructureFailure("frozen train/test indices do not partition rows 0..442")
    return train_list, test_list


def load_matrix_headers(assets: Path) -> dict[str, list[str]]:
    headers = {}
    for label, filename in MATRIX_FILES.items():
        path = assets / filename
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                fields = csv.DictReader(handle).fieldnames or []
        except (OSError, UnicodeError, csv.Error) as exc:
            raise InfrastructureFailure(f"cannot read {filename}: {exc}") from exc
        if len(fields) != 443 and not fields:
            raise InfrastructureFailure(f"{filename} has no usable header")
        if not fields or fields[0] != "":
            raise InfrastructureFailure(f"{filename} does not expose the released row-index column")
        headers[label] = fields[1:]
    return headers


def load_prediction(path: Path, targets: dict[int, float], test_indices: list[int], label: str) -> dict[int, tuple[float, float]]:
    rows = csv_rows(path, PRED_COLUMNS, label)
    if len(rows) != len(test_indices):
        raise ScienceFailure(f"{label} must contain exactly {len(test_indices)} declared test rows")
    result = {}
    for row in rows:
        try:
            idx = int(row["row_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ScienceFailure(f"{label} has invalid row_index") from exc
        if idx in result or idx not in set(test_indices):
            raise ScienceFailure(f"{label} has duplicate or non-test row_index {idx}")
        truth = finite(row["true_experimental_barrier"], f"{label} truth")
        pred = finite(row["predicted_barrier"], f"{label} prediction")
        if not close(truth, targets[idx]):
            raise ScienceFailure(f"{label} true target disagrees with public target at row {idx}")
        result[idx] = (truth, pred)
    if set(result) != set(test_indices):
        raise ScienceFailure(f"{label} does not cover its declared test set exactly")
    return result


def metrics(predictions: dict[int, tuple[float, float]]) -> tuple[float, float, float]:
    truth = np.asarray([v[0] for _, v in sorted(predictions.items())], dtype=float)
    pred = np.asarray([v[1] for _, v in sorted(predictions.items())], dtype=float)
    residual = pred - truth
    mae = float(np.mean(np.abs(residual)))
    rmse = float(np.sqrt(np.mean(residual ** 2)))
    variance = float(np.sum((truth - np.mean(truth)) ** 2))
    r2 = float(1.0 - np.sum(residual ** 2) / variance) if variance else float("nan")
    return mae, rmse, r2


def verify_shared_feature_rows(assets: Path) -> dict[str, Any]:
    """Prove that released No TS is Full with its TS-named columns removed."""
    full_path = assets / MATRIX_FILES["Full"]
    no_ts_path = assets / MATRIX_FILES["No TS"]
    full = csv_rows(full_path, set(), full_path.name)
    no_ts = csv_rows(no_ts_path, set(), no_ts_path.name)
    with full_path.open(encoding="utf-8-sig", newline="") as handle:
        full_fields = csv.DictReader(handle).fieldnames or []
    with no_ts_path.open(encoding="utf-8-sig", newline="") as handle:
        no_ts_fields = csv.DictReader(handle).fieldnames or []
    full_cols, no_ts_cols = full_fields[1:], no_ts_fields[1:]
    shared = [column for column in full_cols if column in set(no_ts_cols)]
    full_only = [column for column in full_cols if column not in set(no_ts_cols)]
    no_ts_only = [column for column in no_ts_cols if column not in set(full_cols)]
    if len(full) != 443 or len(no_ts) != 443:
        raise ScienceFailure("Full/No TS must each contain all 443 rows")
    if full_only != [column for column in full_cols if "ts" in column.lower()] or no_ts_only:
        raise ScienceFailure("Full/No TS difference is not exactly the TS-named columns")
    for index, (full_row, no_ts_row) in enumerate(zip(full, no_ts)):
        if full_row.get("") != no_ts_row.get("") or int(float(full_row[""])) != index:
            raise ScienceFailure("Full/No TS row indices are not aligned over 0..442")
        for column in shared:
            try:
                a, b = float(full_row[column]), float(no_ts_row[column])
            except (KeyError, TypeError, ValueError) as exc:
                raise ScienceFailure(f"invalid shared feature value {column} at row {index}") from exc
            if not math.isfinite(a) or not math.isfinite(b) or a != b:
                raise ScienceFailure(f"Full/No TS shared feature differs at {column}, row {index}")
    return {"shared_column_count": len(shared), "shared_row_value_count": len(shared) * 443,
            "full_only_columns": full_only, "no_ts_only_columns": no_ts_only}


def validate_cv_splits(path: Path, seed: int, expected_positions: int, n_folds: int = 3) -> list[dict[str, list[int]]]:
    cv = read_json(path, path.name)
    if isinstance(cv, dict):
        declared_seed = cv.get("seed")
        if declared_seed is not None and declared_seed != seed:
            raise ScienceFailure(f"seed {seed} CV split file declares a different seed")
        wrapped = cv.get("folds", cv.get("splits"))
        if not isinstance(wrapped, list):
            raise ScienceFailure(f"seed {seed} CV split file lacks an explicit fold list")
        cv = wrapped
    if not isinstance(cv, list) or len(cv) != n_folds:
        raise ScienceFailure(f"seed {seed} CV must contain exactly {n_folds} folds")
    universe = set(range(expected_positions))
    validated = []
    validation_all: list[int] = []
    for fold_index, fold in enumerate(cv):
        if not isinstance(fold, dict):
            raise ScienceFailure(f"seed {seed} fold {fold_index} is invalid")
        train = fold.get("train_local", fold.get("train_positions"))
        validation = fold.get("validation_local", fold.get("validation_positions"))
        if (not isinstance(train, list) or not isinstance(validation, list)
                or any(type(i) is not int for i in train + validation)):
            raise ScienceFailure(f"seed {seed} fold {fold_index} positions must be integer lists")
        train_set, validation_set = set(train), set(validation)
        if (len(train_set) != len(train) or len(validation_set) != len(validation)
                or train_set & validation_set or train_set | validation_set != universe):
            raise ScienceFailure(f"seed {seed} fold {fold_index} is not a legal partition of training positions")
        validation_all.extend(validation)
        validated.append({"train_positions": train, "validation_positions": validation})
    if set(validation_all) != universe or len(validation_all) != expected_positions:
        raise ScienceFailure(f"seed {seed} validation folds do not cover every training position exactly once")
    return validated


def validate_cv_evidence(path: Path, seed: int, label: str, alphas: list[float]) -> None:
    evidence = read_json(path, path.name)
    if evidence.get("seed") != seed or evidence.get("label") != label:
        raise ScienceFailure(f"{path.name} seed/model identity mismatch")
    candidates = evidence.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != len(alphas):
        raise ScienceFailure(f"{path.name} does not report the complete alpha search")
    scores = []
    observed_alphas = []
    for candidate in candidates:
        params = candidate.get("params", {})
        score = finite(candidate.get("cv_mae_kcal_mol"), f"{path.name} CV MAE")
        finite(candidate.get("cv_mae_std_kcal_mol"), f"{path.name} CV MAE spread")
        if set(params) != {"gpr__alpha"}:
            raise ScienceFailure(f"{path.name} has an unexpected model parameter")
        observed_alphas.append(float(params["gpr__alpha"]))
        scores.append(score)
    if observed_alphas != alphas:
        raise ScienceFailure(f"{path.name} alpha search differs from the declared protocol")
    best_index = min(range(len(scores)), key=scores.__getitem__)
    if (evidence.get("best_params") != {"gpr__alpha": alphas[best_index]}
            or not close(finite(evidence.get("best_cv_mae_kcal_mol"), f"{path.name} best CV MAE"), scores[best_index])):
        raise ScienceFailure(f"{path.name} best configuration does not match its CV scores")


def validate_paired_summary(summary: dict[str, Any], rows: list[dict[str, str]], seeds: list[int],
                            delta_key: str, direction_positive: str,
                            direction_other: str) -> dict[str, Any]:
    deltas = np.asarray([finite(row[delta_key], delta_key) for row in rows], dtype=float)
    mean, spread = float(deltas.mean()), float(deltas.std(ddof=1))
    spread_population = float(deltas.std(ddof=0))
    minimum, maximum = float(deltas.min()), float(deltas.max())
    full_better = bool(np.all(deltas > 0))
    direction = direction_positive if full_better else direction_other
    expected = {"seed_count": len(seeds), "seeds": seeds, "delta_mean_kcal_mol": mean,
                "delta_std_kcal_mol": spread, "delta_min_kcal_mol": minimum,
                "delta_max_kcal_mol": maximum, "full_better_for_all_seeds": full_better,
                "direction": direction}
    for key, value in expected.items():
        if key in {"direction"} and key not in summary:
            continue
        actual = summary.get(key)
        if key == "delta_std_kcal_mol":
            if (not isinstance(actual, (int, float))
                    or not any(close(float(actual), candidate) for candidate in (spread, spread_population))):
                raise ScienceFailure(f"paired summary {key} does not recompute from seed rows")
        elif isinstance(value, float):
            if not isinstance(actual, (int, float)) or not close(float(actual), value):
                raise ScienceFailure(f"paired summary {key} does not recompute from seed rows")
        elif key == "direction":
            def direction_key(raw):
                if not isinstance(raw, str):
                    return None
                compact = "".join(ch.lower() for ch in raw if ch.isalnum())
                if compact in {"fullbetter", "fullbetterforallseeds", "fullwinsallseeds", "fullisconsistentlybetter", "fullisbetterforallseeds"}:
                    return "full"
                if compact in {"mixedornotsbetter", "mixedornots", "nostsbetter", "nostsbetterormixed", "mixedoutcomesnotsisnotconsistentlyworse", "mixedoutcomesnostsisnotconsistentlyworse", "mixedoutcomesnostsnotconsistentlyworse", "notconsistentlyfullbetter"}:
                    return "other"
                if compact in {"tsgain", "tsgainforallseeds", "fullbetter"}:
                    return "full"
                if compact in {"nostabletsgain", "nostabletsgainobserved", "mixedornostsgain"}:
                    return "other"
                return None
            expected_kind = direction_key(value)
            actual_kind = direction_key(actual)
            if expected_kind is None:
                raise ScienceFailure(f"paired summary {key} does not match the seed-derived direction")
            if actual is not None and actual_kind is not None and actual_kind != expected_kind:
                raise ScienceFailure(f"paired summary {key} does not match the seed-derived direction")
        elif actual != value:
            raise ScienceFailure(f"paired summary {key} does not match seed rows")
    if "delta_definition" not in summary:
        return expected
    raw_definition = summary["delta_definition"]
    if not isinstance(raw_definition, str) or not raw_definition.strip():
        raise ScienceFailure("paired summary delta_definition must be a nonempty string")
    if delta_key == "delta_mae_no_ts_minus_full_kcal_mol":
        expected_operands = ("nots", "full")
        reversed_operands = ("full", "nots")
    elif delta_key == "delta_mae_full_minus_ts_minus_full_kcal_mol":
        expected_operands = ("fullminusts", "full")
        reversed_operands = ("full", "fullminusts")
    else:
        raise ReviewRequired(f"no public delta-definition parser for {delta_key}")
    formula = re.fullmatch(
        r"\s*MAE\s*\(\s*([^()]+?)\s*\)\s*(.*?)\s*MAE\s*\(\s*([^()]+?)\s*\)\s*",
        raw_definition,
        flags=re.IGNORECASE,
    )
    if formula is None:
        # delta_definition is optional narrative; the signed deltas themselves are already verified.
        return expected
    labels = tuple("".join(ch.lower() for ch in formula.group(index) if ch.isalnum()) for index in (1, 3))
    operator_text = formula.group(2).strip().lower()
    if operator_text in {"-", "−", "–", "—", "minus"}:
        if labels == expected_operands:
            pass
        elif labels == reversed_operands:
            raise ScienceFailure("paired summary delta_definition reverses the declared subtraction")
        else:
            raise ReviewRequired("paired summary delta_definition uses unrecognized MAE operands")
    elif operator_text in {"+", "plus", "add", "added to", "/", "÷", "divide", "divided by", "dividedby", "*", "×", "times", "multiply", "multiplied by", "multipliedby"}:
        if labels in {expected_operands, reversed_operands}:
            raise ScienceFailure("paired summary delta_definition uses a non-subtraction operator")
        raise ReviewRequired("paired summary delta_definition uses unrecognized MAE operands")
    else:
        raise ReviewRequired("paired summary delta_definition uses an unrecognized binary operator")
    return expected


def check_feature_map(final: Path, assets: Path, headers: dict[str, list[str]]) -> None:
    data = read_json(final / "feature_set_map.json", "feature_set_map.json")
    if not isinstance(data, dict):
        raise ScienceFailure("feature_set_map.json must be an object")
    try:
        json.dumps(data, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ScienceFailure("feature_set_map.json contains invalid JSON values") from exc
    labels = set(MATRIX_FILES)
    metadata = {"schema", "evidence", "notes", "description", "metadata"}
    wrapper = next((key for key in ("feature_sets", "labels") if key in data), None)
    if wrapper is not None:
        nested = data[wrapper]
        if not isinstance(nested, dict) or set(nested) != labels:
            raise ScienceFailure(f"feature_set_map.json {wrapper} must contain exactly the six required labels")
        def _declared(entry):
            return {key: entry[key] for key in
                    ("source_matrix_file", "feature_columns", "appended_barrier_uncertainty")
                    if isinstance(entry, dict) and key in entry}

        direct = {label: _declared(data[label]) for label in labels if label in data}
        try:
            direct_json = json.dumps(direct, sort_keys=True, allow_nan=False)
            nested_json = json.dumps({label: _declared(nested[label]) for label in direct},
                                     sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ScienceFailure("duplicated feature map entries contain invalid JSON values") from exc
        if direct_json != nested_json:
            raise ScienceFailure("direct and nested feature map entries conflict")
        extra = set(data) - labels - metadata - {wrapper}
        if extra:
            raise ScienceFailure(f"feature_set_map.json has undeclared top-level keys: {sorted(extra)}")
        items = nested
    else:
        items = {label: data[label] for label in labels if label in data}
        if set(data) - labels - metadata or set(items) != labels:
            raise ScienceFailure("feature_set_map.json must contain exactly the six required labels")
    if set(items) != labels:
        raise ScienceFailure("feature_set_map.json must contain exactly Full, No TS, Small, Surface, Traditional and Only TS")
    global_evidence = data.get("evidence")
    global_groups = (global_evidence.get("descriptor_groups")
                     if isinstance(global_evidence, dict) else None)
    seen = set()
    for label, filename in MATRIX_FILES.items():
        item = items[label]
        if not isinstance(item, dict) or item.get("source_matrix_file") != filename:
            raise ScienceFailure(f"feature map source mismatch for {label}")
        if type(item.get("appended_barrier_uncertainty")) is not bool:
            raise ScienceFailure(f"feature map uncertainty flag must be a JSON boolean for {label}")
        cols = item.get("feature_columns")
        if not isinstance(cols, list) or any(not isinstance(column, str) for column in cols):
            raise ScienceFailure(f"feature map columns must be a string list for {label}")
        evidence = item.get("evidence")
        if not isinstance(evidence, dict) and isinstance(global_groups, dict):
            evidence = {"descriptor_groups": {
                name: [column for column in cols if column in values]
                for name, values in global_groups.items() if isinstance(values, list)
            }}
        if not isinstance(evidence, dict):
            raise ScienceFailure(f"feature map evidence must be a structured object for {label}")
        if not isinstance(cols, list) or any(not isinstance(column, str) for column in cols):
            raise ScienceFailure(f"feature map columns must be a string list for {label}")
        if "matched_descriptors" in evidence and evidence["matched_descriptors"] != cols:
            raise ScienceFailure(f"feature map descriptor evidence does not match its declared columns for {label}")
        groups = evidence.get("descriptor_groups")
        group_names = {"transition_state", "electrostatic", "surface_steric", "other"}
        if (not isinstance(groups, dict) or set(groups) != group_names
                or any(not isinstance(values, list) or any(not isinstance(column, str) for column in values)
                       for values in groups.values())):
            raise ScienceFailure(f"feature map for {label} lacks structured descriptor-family evidence")
        grouped = [column for values in groups.values() for column in values]
        if len(cols) != len(set(cols)) or len(grouped) != len(set(grouped)) or set(grouped) != set(cols):
            raise ScienceFailure(f"feature map descriptor families do not partition the declared columns for {label}")
        if cols != headers[label]:
            raise ScienceFailure(f"feature map columns do not exactly match {label} matrix")
        if filename in seen:
            raise ScienceFailure("feature map reuses one matrix for multiple labels")
        seen.add(filename)

def _canonical_fold_partitions(folds: object) -> tuple | None:
    if not isinstance(folds, list) or not folds:
        return None
    result = []
    for fold in folds:
        if not isinstance(fold, dict):
            return None
        train_local = fold.get("train_local", fold.get("train_positions"))
        validation_local = fold.get("validation_local", fold.get("validation_positions"))
        if (not isinstance(train_local, list) or not isinstance(validation_local, list)
                or any(type(index) is not int for index in train_local + validation_local)
                or len(set(train_local)) != len(train_local)
                or len(set(validation_local)) != len(validation_local)
                or set(train_local) & set(validation_local)):
            return None
        result.append((tuple(sorted(train_local)), tuple(sorted(validation_local))))
    return tuple(sorted(result))


def normalize_protocol(final: Path, protocol: object, train: list[int], test: list[int]) -> dict:
    """Return a local canonical view of explicitly equivalent protocol layouts."""
    if not isinstance(protocol, dict):
        raise ScienceFailure("protocol.json must be an object")
    normalized = dict(protocol)

    frozen_split = protocol.get("frozen_split")
    if isinstance(frozen_split, bool):
        # A boolean here is a flag asserting use of the frozen split, not a layout.
        if not frozen_split:
            raise ScienceFailure("protocol frozen_split flag contradicts the frozen split requirement")
        frozen_split = None
    if frozen_split is not None and not isinstance(frozen_split, dict):
        raise ScienceFailure("protocol frozen_split must be an object")
    split = frozen_split if isinstance(frozen_split, dict) else {}
    train_values = [protocol[key] for key in ("train_indices",) if key in protocol]
    test_values = [protocol[key] for key in ("test_indices",) if key in protocol]
    if "train_indices" in split:
        train_values.append(split["train_indices"])
    if "test_indices" in split:
        test_values.append(split["test_indices"])
    for values, expected, label in ((train_values, train, "train_indices"), (test_values, test, "test_indices")):
        if not values or any(not isinstance(value, list) or any(type(index) is not int for index in value) for value in values):
            raise ScienceFailure(f"protocol must explicitly declare integer {label}")
        if any(len(value) != len(set(value)) or set(value) != set(expected) for value in values):
            raise ScienceFailure(f"protocol {label} do not match frozen s118/s119")
    normalized["train_indices"] = train
    normalized["test_indices"] = test

    actually_disjoint = not (set(train) & set(test))
    disjoint_values = [protocol[key] for key in ("train_test_disjoint",) if key in protocol]
    if "disjoint" in split:
        disjoint_values.append(split["disjoint"])
    if any(type(value) is not bool or value != actually_disjoint for value in disjoint_values):
        raise ScienceFailure("protocol disjoint-split declarations conflict with frozen indices")
    if not actually_disjoint:
        raise ScienceFailure("frozen train/test indices overlap")
    normalized["train_test_disjoint"] = True

    target_exclusion = protocol.get("target_exclusion")
    if target_exclusion is not None and not isinstance(target_exclusion, dict):
        raise ScienceFailure("protocol target_exclusion must be an object")
    target_values = [protocol[key] for key in ("target_excluded_from_features",) if key in protocol]
    if isinstance(target_exclusion, dict):
        required_target_claims = (
            "experimental_target_excluded",
            "target_derived_values_excluded_from_preprocessing_selection_tuning",
        )
        if any(type(target_exclusion.get(key)) is not bool for key in required_target_claims):
            raise ScienceFailure("nested target_exclusion must explicitly declare both target-use boundaries")
        target_values.append(all(target_exclusion[key] for key in required_target_claims))
    if not target_values or any(type(value) is not bool or value is not True for value in target_values):
        raise ScienceFailure("protocol does not prove target exclusion")
    normalized["target_excluded_from_features"] = True

    preprocessing = protocol.get("preprocessing")
    if preprocessing is not None and not isinstance(preprocessing, dict):
        raise ScienceFailure("protocol preprocessing must be an object")
    preprocessing_claims = []
    if "preprocessing_fit_scope" in protocol:
        preprocessing_claims.append(protocol["preprocessing_fit_scope"] == "training_folds_only")
    if isinstance(preprocessing, dict):
        fold_only = preprocessing.get("fold_only_preprocessing")
        test_used = preprocessing.get("test_rows_used_in_fit")
        if type(fold_only) is not bool or type(test_used) is not bool:
            raise ScienceFailure("nested preprocessing must explicitly declare fold-only fitting and test-row use")
        preprocessing_claims.append(fold_only is True and test_used is False)
    if not preprocessing_claims or any(claim is not True for claim in preprocessing_claims):
        raise ScienceFailure("protocol must prove fold-local preprocessing without test-row fitting")
    normalized["preprocessing_fit_scope"] = "training_folds_only"

    budget = protocol.get("search_budget")
    if not isinstance(budget, dict):
        raise ScienceFailure("protocol search_budget must be an object")
    nested_counts = {key: budget[key] for key in ("hybrid", "no_ts") if key in budget}
    if any(type(count) is not int or count <= 0 for count in nested_counts.values()):
        raise ScienceFailure("nested preferred-arm candidate counts must be positive integers")
    declared_counts = budget.get("per_arm_candidate_parameterizations")
    if declared_counts is not None:
        if type(declared_counts) is int and declared_counts > 0:
            declared_counts = {"hybrid": declared_counts, "no_ts": declared_counts}
        if not isinstance(declared_counts, dict) or set(declared_counts) != {"hybrid", "no_ts"}:
            raise ScienceFailure("per-arm search budget must declare exactly hybrid and no_ts")
        if any(type(count) is not int or count <= 0 for count in declared_counts.values()):
            raise ScienceFailure("canonical preferred-arm candidate counts must be positive integers")
        if nested_counts and nested_counts != declared_counts:
            raise ScienceFailure("nested and canonical per-arm search budgets conflict")
        nested_counts = declared_counts
    if set(nested_counts) != {"hybrid", "no_ts"} or any(type(count) is not int or count <= 0 for count in nested_counts.values()):
        raise ScienceFailure("protocol must declare positive candidate counts for both preferred arms")

    model_spec = read_json(final / "model_spec.json", "model_spec.json")
    arms = model_spec.get("arms") if isinstance(model_spec, dict) else None
    if not isinstance(arms, dict) or not {"hybrid", "no_ts"}.issubset(arms):
        raise ScienceFailure("model_spec must explicitly declare hybrid and no_ts arms for CV comparison")
    arm_partitions = []
    for name in ("hybrid", "no_ts"):
        arm = arms[name]
        if not isinstance(arm, dict):
            raise ScienceFailure(f"model_spec arm {name} must be an object")
        cv = arm.get("cv")
        candidates = []
        if "cv_folds" in arm:
            candidates.append(arm["cv_folds"])
        if isinstance(cv, dict) and "folds" in cv:
            candidates.append(cv["folds"])
        if not candidates:
            raise ScienceFailure(f"model_spec arm {name} lacks explicit CV fold partitions")
        canonical = [_canonical_fold_partitions(candidate) for candidate in candidates]
        if any(partition is None for partition in canonical) or any(partition != canonical[0] for partition in canonical[1:]):
            raise ScienceFailure(f"model_spec arm {name} has invalid or conflicting CV fold declarations")
        arm_partitions.append(canonical[0])
    folds_match = arm_partitions[0] == arm_partitions[1]
    if "same_frozen_split" in budget and (type(budget["same_frozen_split"]) is not bool or budget["same_frozen_split"] is not True):
        raise ScienceFailure("search budget same_frozen_split conflicts with verified frozen indices")
    if "same_cv_folds" in budget and (type(budget["same_cv_folds"]) is not bool or budget["same_cv_folds"] != folds_match):
        raise ScienceFailure("search budget same_cv_folds conflicts with explicit model_spec partitions")
    normalized_budget = dict(budget)
    normalized_budget.update({
        "per_arm_candidate_parameterizations": dict(nested_counts),
        "same_frozen_split": True,
        "same_cv_folds": folds_match,
    })
    normalized["search_budget"] = normalized_budget
    return normalized


def check_protocol(final: Path, train: list[int], test: list[int], headers: dict[str, list[str]]) -> dict:
    protocol = normalize_protocol(final, read_json(final / "protocol.json", "protocol.json"), train, test)
    seeds = protocol.get("seeds")
    if isinstance(seeds, dict):
        seed_lists = [value for value in seeds.values()
                      if isinstance(value, list) and value
                      and all(type(item) is int for item in value)]
        seeds = max(seed_lists, key=len) if seed_lists else None
    if seeds is not None and (not isinstance(seeds, list) or len(set(seeds)) != len(seeds)):
        raise ScienceFailure("optional protocol seeds must be unique")
    budget = protocol.get("search_budget")
    if (not isinstance(budget,dict) or budget.get("same_frozen_split") is not True
            or type(budget.get("same_cv_folds")) is not bool
            or not isinstance(budget.get("per_arm_candidate_parameterizations"),dict)):
        raise ScienceFailure("protocol must declare its CV matching policy and each preferred arm's search budget")
    if (final / "fit_evidence.json").exists():
        evidence = read_json(final / "fit_evidence.json", "fit_evidence.json")
        if not isinstance(evidence, dict) or evidence.get("train_indices") != train or evidence.get("test_indices") != test:
            raise ScienceFailure("fit evidence does not carry frozen indices")
        if evidence.get("target_column_used_as_feature") is not False or evidence.get("preprocessing_fit_scope") != "training_folds_only":
            raise ScienceFailure("fit evidence does not prove target exclusion and train-only preprocessing")
        for item in evidence.get("models", []):
            cols = item.get("feature_columns", [])
            if any(c in {"exp_activation_energy", "true_experimental_barrier", "predicted_barrier"} for c in cols):
                raise ScienceFailure(f"target-derived feature in fit evidence for {item.get('model')}")
            if item.get("train_indices") != train:
                raise ScienceFailure(f"model fit evidence has wrong training indices for {item.get('model')}")
    for label, cols in headers.items():
        if any(c == "exp_activation_energy" for c in cols):
            raise InfrastructureFailure(f"public feature matrix {label} exposes target as a feature")
    return protocol


def check_ts_ablation(ablation: Path, assets: Path) -> dict:
    protocol=read_json(ablation/"ablation_protocol.json","ablation_protocol.json")
    seeds=protocol.get("seeds"); cv=protocol.get("cv")
    if protocol.get("ablation_kind")!="full_vs_full_minus_ts": raise ScienceFailure("TS ablation kind is invalid")
    if not isinstance(seeds,list) or len(seeds)!=5 or len(set(seeds))!=5 or any(type(x)is not int for x in seeds): raise ScienceFailure("TS ablation requires five distinct declared seeds")
    if not isinstance(cv,dict) or type(cv.get("folds")) is not int or not 2<=cv["folds"]<=10 or cv.get("shuffle") is not True or cv.get("same_splits_per_seed_across_arms") is not True or cv.get("selection_metric")!="MAE" or protocol.get("test_used_for_selection") is not False: raise ReviewRequired("unsupported TS ablation CV protocol")
    spec=protocol.get("model_spec")
    if not isinstance(spec,dict) or spec.get("schema")!="case02-model-spec/v1" or set(spec.get("arms",{}))!={"Full","Full_minus_TS"}: raise ReviewRequired("TS ablation requires independently replayable model_spec")
    train,test=load_split(assets)
    if protocol.get("train_indices")!=train or protocol.get("test_indices")!=test: raise ScienceFailure("TS ablation must use frozen primary indices")
    if protocol.get("input_sha256")!={p.name:sha256(p) for p in assets.iterdir() if p.is_file()}: raise ScienceFailure("TS ablation public input hashes mismatch")
    headers=load_matrix_headers(assets); shared=verify_shared_feature_rows(assets)
    diff=read_json(ablation/"feature_diff.json","feature_diff.json")
    if diff.get("full_columns")!=headers["Full"] or diff.get("reduced_columns")!=headers["No TS"] or diff.get("removed_ts_columns")!=shared["full_only_columns"]: raise ScienceFailure("TS removal columns do not match the released Full/No TS descriptor identity")
    targets=load_targets(assets); rows=csv_rows(ablation/"paired_ts_ablation.csv",{"seed","full_mae_kcal_mol","full_minus_ts_mae_kcal_mol","delta_mae_full_minus_ts_minus_full_kcal_mol"},"paired_ts_ablation.csv")
    if len(rows)!=5 or {int(r["seed"]) for r in rows}!=set(seeds): raise ScienceFailure("TS ablation must include exactly five declared seeds")
    source="SC-012-D0SC04896H-s120.csv"; matrices={}
    for name,expected_cols in (("Full",headers["Full"]),("Full_minus_TS",headers["No TS"])):
        arm=spec["arms"][name]
        if not isinstance(arm,dict) or arm.get("matrix_file")!=source or arm.get("feature_columns")!=expected_cols: raise ScienceFailure(f"TS ablation feature declaration invalid: {name}")
        matrices[name]=load_selected_matrix(assets/source,expected_cols)
    if spec["arms"]["Full"].get("estimator")!=spec["arms"]["Full_minus_TS"].get("estimator") or spec["arms"]["Full"].get("budget")!=spec["arms"]["Full_minus_TS"].get("budget") or spec["arms"]["Full"].get("preprocessing")!=spec["arms"]["Full_minus_TS"].get("preprocessing"): raise ScienceFailure("TS ablation arms must use matched estimator, budget and preprocessing")
    for row in rows:
        seed=int(row["seed"]); split=validate_cv_splits(ablation/f"cv_splits_seed{seed}.json",seed,len(train),cv["folds"]); folds=[{"train_local":f["train_positions"],"validation_local":f["validation_positions"]} for f in split]
        metrics_by={}
        for name,file_key,row_key in (("Full","full","full_mae_kcal_mol"),("Full_minus_TS","full_minus_ts","full_minus_ts_mae_kcal_mol")):
            arm={**spec["arms"][name],"cv":dict(spec["arms"][name].get("cv",{}))}
            if arm.get("seed_policy")!="paired_seed": raise ScienceFailure("invalid TS ablation seed policy")
            check_paired_cv(arm["cv"], cv["folds"], name)
            arm["cv"]={"n_splits":cv["folds"],"shuffle":True,"random_state":seed,"scoring":"MAE"}
            pred,_=independent_refit(arm,matrices[name][np.asarray(train)],np.asarray([targets[i] for i in train]),matrices[name][np.asarray(test)],folds,seed)
            reported=load_prediction(ablation/f"predictions_{file_key}_seed{seed}.csv",targets,test,f"{file_key}_{seed}")
            submitted=np.asarray([reported[i][1] for i in test])
            if not prediction_matches_refit(submitted, pred, arm, matrices[name][np.asarray(train)], np.asarray([targets[i] for i in train]), matrices[name][np.asarray(test)], folds, seed): raise ScienceFailure(f"TS ablation seed {seed} {name} differs from independent refit")
            mae=metrics(reported)[0]; metrics_by[name]=mae
            if not close(mae,float(row[row_key])): raise ScienceFailure("TS ablation MAE does not recompute")
        delta=metrics_by["Full_minus_TS"]-metrics_by["Full"]
        if not close(delta,float(row["delta_mae_full_minus_ts_minus_full_kcal_mol"])): raise ScienceFailure("TS ablation delta does not recompute")
    summary=read_json(ablation/"paired_ts_summary.json","paired_ts_summary.json")
    checked=validate_paired_summary(summary,rows,seeds,"delta_mae_full_minus_ts_minus_full_kcal_mol","TS_gain","no_stable_TS_gain")
    return {"status":"PASS","seed_count":5,"coverage":"PARTIAL","training_execution_verified":False,"declared_protocol_independent_refit_verified":True,"delta_mean_kcal_mol":checked["delta_mean_kcal_mol"],"delta_range":[checked["delta_min_kcal_mol"],checked["delta_max_kcal_mol"]],"interpretation":checked["direction"]}


def check_paired_cv(declared, folds, label):
    """Validate CV meaning without rejecting consistent explanatory metadata."""
    normalized = normalize_cv(declared, paired=True, expected_n_splits=folds)
    required = {"n_splits": folds, "shuffle": True,
                "random_state_policy": "seed", "scoring": "MAE"}
    if any(normalized.get(k) != v for k, v in required.items()):
        raise ScienceFailure(f"inconsistent paired CV specification for {label}")
    if type(normalized["n_splits"]) is not int or normalized["shuffle"] is not True:
        raise ScienceFailure(f"invalid paired CV types for {label}")


def check_ablation(ablation: Path, assets: Path) -> dict:
    protocol = read_json(ablation / "ablation_protocol.json", "ablation_protocol.json")
    seeds = protocol.get("seeds")
    if not isinstance(seeds,list) or len(seeds)!=5 or len(set(seeds))!=5 or any(type(x) is not int for x in seeds):
        raise ScienceFailure("paired ablation must declare five distinct integer seeds")
    cv = protocol.get("cv")
    if (not isinstance(cv,dict) or type(cv.get("folds")) is not int or not 2 <= cv["folds"] <= 10
            or cv.get("shuffle") is not True or cv.get("same_splits_per_seed_across_arms") is not True
            or cv.get("selection_metric") != "MAE" or protocol.get("test_used_for_selection") is not False
            or protocol.get("preprocessing_fit_scope") not in {"training_fold_only", "training_folds_only"}):
        raise ScienceFailure("paired ablation CV or test isolation declaration is invalid")
    model_spec=protocol.get("model_spec")
    if not isinstance(model_spec,dict) or model_spec.get("schema")!="case02-model-spec/v1" or set(model_spec.get("arms",{}))!={"Full","No TS"}:
        raise ReviewRequired("paired ablation model_spec is missing or unsupported")
    declared_arms={label: normalize_arm(model_spec["arms"][label], paired=True) for label in ("Full", "No TS")}
    for label in ("Full","No TS"):
        arm=declared_arms[label]
        if not isinstance(arm,dict) or arm.get("seed_policy")!="paired_seed": raise ScienceFailure(f"invalid paired seed declaration for {label}")
        check_paired_cv(arm.get("cv"), cv["folds"], label)
    if (declared_arms["Full"].get("preprocessing")!=declared_arms["No TS"].get("preprocessing")
            or declared_arms["Full"].get("target_transform")!=declared_arms["No TS"].get("target_transform")
            or declared_arms["Full"].get("budget")!=declared_arms["No TS"].get("budget")):
        raise ScienceFailure("paired Full/No TS preprocessing, target transform, or search budget differs")
    if canonical_estimator(declared_arms["Full"], paired=True) != canonical_estimator(declared_arms["No TS"], paired=True):
        raise ScienceFailure("paired Full/No TS estimator declarations differ")
    full_folds = declared_arms["Full"].get("cv_folds")
    no_ts_folds = declared_arms["No TS"].get("cv_folds")
    if full_folds is not None and no_ts_folds is not None and full_folds != no_ts_folds:
        raise ScienceFailure("paired Full/No TS inline CV folds differ")
    train_indices, test_indices = load_split(assets)
    declared_train = protocol.get("train_indices")
    declared_test = protocol.get("test_indices")
    frozen = protocol.get("frozen_indices")
    if isinstance(frozen, dict):
        train_forms = [x for x in (declared_train, frozen.get("train"), frozen.get("train_indices")) if x is not None]
        test_forms = [x for x in (declared_test, frozen.get("test"), frozen.get("test_indices")) if x is not None]
        if any(x != train_forms[0] for x in train_forms) or any(x != test_forms[0] for x in test_forms):
            raise ScienceFailure("conflicting paired ablation index declarations")
        declared_train = train_forms[0] if train_forms else None
        declared_test = test_forms[0] if test_forms else None
    if (not isinstance(declared_train, list) or not isinstance(declared_test, list)
            or len(declared_train) != len(set(declared_train))
            or len(declared_test) != len(set(declared_test))
            or set(declared_train) != set(train_indices)
            or set(declared_test) != set(test_indices)):
        raise ScienceFailure("Full/No TS 消融协议索引与冻结划分不一致")
    expected_hashes = {p.name: sha256(p) for p in assets.iterdir() if p.is_file()}
    declared_hashes = protocol.get("input_sha256", expected_hashes)
    if (not isinstance(declared_hashes, dict) or set(declared_hashes) != set(expected_hashes)
            or any(not isinstance(declared_hashes[name], str)
                   or declared_hashes[name].split(":", 1)[-1].lower()
                   != expected_hashes[name].split(":", 1)[-1].lower()
                   for name in expected_hashes)):
        raise ScienceFailure("Full/No TS 消融输入哈希与当前公开 assets 不一致")
    feature_diff = read_json(ablation / "feature_diff.json", "feature_diff.json")
    headers = load_matrix_headers(assets)
    shared_rows = verify_shared_feature_rows(assets)
    if feature_diff.get("full_columns") != headers["Full"] or feature_diff.get("no_ts_columns") != headers["No TS"]:
        raise ScienceFailure("feature_diff.json 与公开矩阵列不一致")
    for key in ("full_only_columns", "no_ts_only_columns"):
        if set(feature_diff.get(key, [])) != set(shared_rows[key]):
            raise ScienceFailure(f"feature_diff.json {key} 与实际矩阵不一致")
    if feature_diff.get("shared_column_count") != shared_rows["shared_column_count"]:
        raise ScienceFailure("feature_diff.json shared_column_count 与实际矩阵不一致")
    rows = csv_rows(ablation / "paired_ablation.csv", {"seed", "full_mae_kcal_mol", "no_ts_mae_kcal_mol", "delta_mae_no_ts_minus_full_kcal_mol"}, "paired_ablation.csv")
    got = {int(r["seed"]) for r in rows}
    if got != set(seeds) or len(rows) != 5:
        raise ScienceFailure("paired_ablation.csv 未完整覆盖预先声明的五个 seed")
    targets = load_targets(assets); _, test = load_split(assets)
    for row in rows:
        seed = int(row["seed"])
        split_rows = validate_cv_splits(ablation / f"cv_splits_seed{seed}.json", seed, len(train_indices), cv["folds"])
        folds=[{"train_local":f["train_positions"],"validation_local":f["validation_positions"]} for f in split_rows]
        for label, column_key, prediction_label in (("Full", "full", "full"), ("No TS", "no_ts", "no_ts")):
            arm=declared_arms[label]
            expected_file=MATRIX_FILES[label]
            if not isinstance(arm,dict) or arm.get("matrix_file")!=expected_file:
                raise ScienceFailure(f"ablation feature source mismatch: {label}")
            columns=arm.get("feature_columns")
            if columns!=headers[label]: raise ScienceFailure(f"ablation feature columns mismatch: {label}")
            matrix=load_selected_matrix(assets/expected_file,columns)
            arm_seed=arm.get("seed_policy")
            if arm_seed not in {"paired_cv_seed","paired_seed"}: raise ScienceFailure(f"ablation seed policy invalid: {label}")
            inline_folds=arm.get("cv_folds")
            if inline_folds is not None and inline_folds != folds:
                raise ScienceFailure(f"seed {seed} {label} inline CV folds conflict with the seed split file")
            arm={**arm,"estimator":dict(arm.get("estimator",{})),"cv":{"n_splits":cv["folds"],"shuffle":True,"random_state":seed,"scoring":"MAE"}}
            arm.pop("cv_folds_source", None)
            expected_pred,audit=independent_refit(arm,matrix[np.asarray(train_indices)],np.asarray([targets[i] for i in train_indices]),matrix[np.asarray(test)],folds,seed)
            pred = load_prediction(ablation / f"predictions_{prediction_label}_seed{seed}.csv", targets, test, f"{prediction_label}_{seed}")
            submitted=np.asarray([pred[i][1] for i in test])
            if not prediction_matches_refit(submitted, expected_pred, arm, matrix[np.asarray(train_indices)], np.asarray([targets[i] for i in train_indices]), matrix[np.asarray(test)], folds, seed, audit):
                raise ScienceFailure(f"seed {seed} {label} differs from independent fold refit")
            mae, _, _ = metrics(pred)
            if not close(mae, float(row[f"{column_key}_mae_kcal_mol"])):
                raise ScienceFailure(f"seed {seed} {label} MAE cannot be recomputed")
        delta = float(row["no_ts_mae_kcal_mol"]) - float(row["full_mae_kcal_mol"])
        if not close(delta, float(row["delta_mae_no_ts_minus_full_kcal_mol"])):
            raise ScienceFailure(f"seed {seed} 的 Delta MAE 无法重算")
    summary = read_json(ablation / "paired_summary.json", "paired_summary.json")
    verified_summary = validate_paired_summary(summary, rows, seeds,
                                               "delta_mae_no_ts_minus_full_kcal_mol",
                                               "Full better", "mixed_or_No_TS_better")
    return {"status": "PASS", "seed_count": 5,
            "coverage": "PARTIAL", "training_execution_verified": False,
            "declared_protocol_independent_refit_verified": True,
            "delta_mean_kcal_mol": verified_summary["delta_mean_kcal_mol"],
            "delta_range": [verified_summary["delta_min_kcal_mol"], verified_summary["delta_max_kcal_mol"]],
            "interpretation": verified_summary["direction"],
            "feature_identity": shared_rows}


def load_selected_matrix(path: Path, columns: list[str]) -> np.ndarray:
    rows = csv_rows(path, set(columns), path.name)
    if len(rows) != 443:
        raise InfrastructureFailure(f"{path.name} must contain 443 rows")
    fields = list(rows[0]); index_col = fields[0]
    if [int(float(r[index_col])) for r in rows] != list(range(443)):
        raise InfrastructureFailure(f"{path.name} row indices are not canonical")
    forbidden={"", "unnamed: 0", "row_index", "exp_activation_energy", "true_experimental_barrier", "predicted_barrier"}
    if not columns or any(c not in fields or c.strip().lower() in forbidden or c.strip().lower().startswith("exp_activation_energy") for c in columns):
        raise ScienceFailure(f"invalid or target-derived declared features in {path.name}")
    return np.asarray([[finite(r[c], f"{path.name}:{c}") for c in columns] for r in rows], dtype=float)


def select_comparison_rows(rows, protocol, model_spec):
    """Select required frozen comparisons by model and declared seed, not preference."""
    selected = {}
    arms = model_spec.get("arms", {})
    for model in REQUIRED_MODELS:
        candidates = [row for row in rows if row["model"] == model]
        if not candidates:
            raise ScienceFailure(f"required comparison row missing: {model}")
        try:
            seeds = [int(row["seed"]) for row in candidates]
        except (TypeError, ValueError):
            raise ScienceFailure(f"comparison model {model} has a non-integer seed")
        if len(seeds) != len(set(seeds)):
            raise ScienceFailure(f"ambiguous duplicate comparison rows for {model} and seed")
        seed = arms.get(model, {}).get("seed")
        if seed is None:
            seed = protocol.get("primary_seed", arms.get("hybrid", {}).get("seed"))
        if model in ("hybrid", "no_ts") or len(candidates) > 1:
            if type(seed) is not int or seed not in seeds:
                raise ScienceFailure(f"comparison {model} missing declared primary seed")
            selected[model] = candidates[seeds.index(seed)]
        else:
            selected[model] = candidates[0]
    return selected


def check_independent_refits(final: Path, assets: Path, targets: dict[int, float], train: list[int], test: list[int], by_model: dict[str, dict[str, str]], pred_cache: dict[str, dict[int, tuple[float, float]]]) -> dict[str, Any]:
    spec = read_json(final / "model_spec.json", "model_spec.json")
    if not isinstance(spec, dict) or spec.get("schema") != "case02-model-spec/v1":
        raise ScienceFailure("model_spec.json must use case02-model-spec/v1")
    selection = spec.get("selection")
    if selection is not None:
        if not isinstance(selection, dict):
            raise CandidateProtocolError("model_spec selection must be an object")
        allowed = {"tune_on", "refit", "average_fold_models", "tie_break", "description", "note"}
        extra = set(selection) - allowed
        if extra:
            raise ReviewRequired(f"unsupported model selection options: {sorted(extra)}")
        for key, expected in (("tune_on", "cv_folds"),
                              ("refit", "once_on_all_354_training_rows"),
                              ("average_fold_models", False)):
            if key in selection and selection[key] != expected:
                raise ScienceFailure(f"model selection {key} contradicts required tuning/refit semantics")
        if "tie_break" in selection:
            tie = selection["tie_break"]
            if not isinstance(tie, str) or tie not in {
                    "first minimum in row-major declared grid order (alpha outer, gamma inner)",
                    "first minimum in declared parameter-grid order",
                    "first minimum in row-major declared grid order"}:
                raise ReviewRequired(f"unsupported model selection tie_break: {tie!r}")
    arms = spec.get("arms")
    if not isinstance(arms, dict) or set(arms) != {"hybrid", "no_ts"}:
        raise ScienceFailure("model_spec must declare preferred hybrid and no_ts arms")
    normalized_protocol = normalize_protocol(
        final, read_json(final/"protocol.json", "protocol.json"), train, test
    )
    search_budget = normalized_protocol["search_budget"]
    declared_budget = search_budget.get("per_arm_candidate_parameterizations",{})
    for name in ("hybrid","no_ts"):
        expected=candidate_count(arms[name])
        if declared_budget.get(name)!=expected or arms[name].get("budget",{}).get("candidate_parameterizations")!=expected:
            raise ScienceFailure(f"declared search budget disagrees with model_spec for {name}")
    if search_budget.get("same_cv_folds") is True:
        def canonical_folds(folds):
            if not isinstance(folds, list):
                return None
            try:
                return sorted((tuple(sorted(f["train_local"])), tuple(sorted(f["validation_local"]))) for f in folds)
            except (KeyError, TypeError):
                return None
        if canonical_folds(arms["hybrid"].get("cv_folds")) != canonical_folds(arms["no_ts"].get("cv_folds")):
            raise ScienceFailure("preferred arms declare same_cv_folds=true but their explicit fold partitions differ")
    refit_info = {}; ytrain = np.asarray([targets[i] for i in train], float)
    for model, expected_file in (("hybrid", "SC-012-D0SC04896H-s120.csv"), ("no_ts", "SC-012-D0SC04896H-s138.csv")):
        arm = normalize_arm(arms[model])
        if not isinstance(arm, dict) or arm.get("matrix_file") != expected_file:
            raise ScienceFailure(f"model_spec actual feature source is invalid for {model}")
        columns = arm.get("feature_columns")
        if not isinstance(columns, list) or not columns or len(columns) != len(set(columns)):
            raise ScienceFailure(f"model_spec feature_columns invalid for {model}")
        matrix = load_selected_matrix(assets / expected_file, columns)
        folds = arm.get("cv_folds")
        if not isinstance(folds, list) or len(folds) < 2:
            raise ReviewRequired(f"explicit inner CV splits missing for {model}")
        seed = arm.get("seed")
        if type(seed) is not int: raise ScienceFailure(f"model_spec seed invalid for {model}")
        expected, audit = independent_refit(arm, matrix[np.asarray(train)], ytrain, matrix[np.asarray(test)], folds, seed)
        submitted = pred_cache[str(final / by_model[model]["prediction_file"])]
        values = np.asarray([submitted[i][1] for i in test])
        if not prediction_matches_refit(values, expected, arm, matrix[np.asarray(train)], ytrain, matrix[np.asarray(test)], folds, seed, audit):
            raise ScienceFailure(f"independent numerical refit disagrees with submitted {model} predictions")
        refit_info[model] = {"selected_params": audit["selected_params"], "inner_cv_mae": audit["cv_mae"], "layout_replay": audit.get("layout_replay")}
    baseline = spec.get("baselines")
    if (not isinstance(baseline, dict)
            or not {"direct_barrier", "linear_correction"}.issubset(baseline)
            or not set(baseline) <= {"direct_barrier", "linear_correction", "mean_baseline"}):
        raise ScienceFailure("model_spec baselines must declare direct_barrier and linear_correction")
    direct_decl = baseline["direct_barrier"]
    linear_decl = baseline["linear_correction"]
    if not isinstance(direct_decl, dict) or not isinstance(linear_decl, dict):
        raise ScienceFailure("baseline declarations must be typed objects")
    direct_column = direct_decl.get("column") or direct_decl.get("barrier_column")
    linear_column = linear_decl.get("column") or linear_decl.get("barrier_column")
    linear_source = linear_decl.get("source_matrix_file") or direct_decl.get("source_matrix_file")
    if (linear_source != direct_decl.get("source_matrix_file")
            or linear_column != direct_column):
        raise ScienceFailure("linear correction must use the declared direct-barrier column")
    if (by_model["direct_barrier"]["source_matrix_file"] != direct_decl.get("source_matrix_file")
            or by_model["linear_correction"]["source_matrix_file"] != direct_decl.get("source_matrix_file")):
        raise ScienceFailure("comparison table baseline source does not match model_spec")
    barrier = load_declared_barrier(assets, direct_decl)
    family = linear_decl.get("family") or linear_decl.get("method")
    alpha = linear_decl.get("alpha")
    from sklearn.linear_model import LinearRegression, Ridge
    if family == "OLS":
        if alpha not in (None, 0, 0.0):
            raise ScienceFailure("OLS linear correction must not declare nonzero alpha")
        linear_model = LinearRegression()
    elif family == "Ridge":
        if type(alpha) not in (int, float) or not math.isfinite(alpha) or alpha < 0:
            raise ScienceFailure("Ridge linear correction alpha must be finite and nonnegative")
        linear_model = Ridge(alpha=float(alpha))
    else:
        raise ReviewRequired(f"unsupported linear-correction family: {family}")
    ixtr, ixt = np.asarray(train), np.asarray(test)
    linear_model.fit(barrier[ixtr, None], ytrain)
    expected_baselines = {"direct_barrier": barrier[ixt],
        "linear_correction": linear_model.predict(barrier[ixt, None]),
        "mean_baseline": np.full(len(test), float(ytrain.mean()))}
    for model, expected in expected_baselines.items():
        submitted=pred_cache[str(final / by_model[model]["prediction_file"])]
        values=np.asarray([submitted[i][1] for i in test])
        if not np.allclose(values,expected,rtol=0.0,atol=1e-7):
            raise ScienceFailure(f"independently reconstructed {model} baseline disagrees with submission")
    return {"declared_protocol_independent_refit_verified": True, "baseline_reconstruction": "PASS", "arms": refit_info}


def check_submission(submission: Path, assets: Path, refs: Path) -> dict:
    check_evaluation_inputs(assets, refs)
    final = submission / "final"
    if not final.is_dir() or final.is_symlink():
        raise ScienceFailure("missing or unsafe final/")
    missing = REQUIRED_OUTPUTS - {p.name for p in final.iterdir()}
    if missing:
        raise ScienceFailure(f"missing required outputs: {sorted(missing)}")
    if not (final / "ablation-v2").is_dir() or (final / "ablation-v2").is_symlink():
        raise ScienceFailure("missing or unsafe required ablation-v2/")
    rows = csv_rows(final / "model_comparison.csv", COMPARISON_COLUMNS, "model_comparison.csv")
    prediction_paths = {}
    for row in rows:
        raw_path = row["prediction_file"]
        if raw_path not in prediction_paths:
            prediction_paths[raw_path] = resolve_prediction_path(final, raw_path)
    if (final / "submission_manifest.json").exists():
        check_submission_manifest(final)
    targets = load_targets(assets)
    train, test = load_split(assets)
    headers = load_matrix_headers(assets)
    protocol = check_protocol(final, train, test, headers)
    check_feature_map(final, assets, headers)
    if not rows:
        raise ScienceFailure("model_comparison.csv is empty")
    additional = protocol.get("additional_comparisons", {})
    if not isinstance(additional,dict): raise ScienceFailure("additional_comparisons must be an object")
    for row in rows:
        model=row["model"]
        if model in REQUIRED_MODELS:
            if int(row["n_train"])!=354 or int(row["n_test"])!=89:
                raise ScienceFailure(f"preferred model {model} must use frozen 354/89 indices")
            if row["protocol"]!=protocol.get("protocol_id"):
                raise ScienceFailure(f"protocol mismatch for preferred {model}")
        else:
            if model not in additional: raise ScienceFailure(f"undeclared additional comparison: {model}")
            declaration=additional[model]
            if not isinstance(declaration,dict) or not isinstance(declaration.get("purpose"),str) or not declaration["purpose"].strip():
                raise ScienceFailure(f"additional comparison {model} needs a declared purpose")
            atrain=declaration.get("train_indices"); atest=declaration.get("test_indices"); population=declaration.get("population_indices")
            if not all(isinstance(x,list) and x and all(type(i) is int for i in x) for x in (atrain,atest,population)):
                raise ScienceFailure(f"additional comparison {model} requires explicit population/train/test indices")
            if (len(set(atrain))!=len(atrain) or len(set(atest))!=len(atest) or len(set(population))!=len(population)
                    or set(atrain)&set(atest) or set(atrain)|set(atest)!=set(population) or min(population)<0 or max(population)>=443):
                raise ScienceFailure(f"additional comparison {model} indices are not disjoint within their declared population")
            overlap=bool(set(atest)&set(test))
            if type(declaration.get("uses_frozen_89_labels")) is not bool or declaration["uses_frozen_89_labels"]!=overlap:
                raise ScienceFailure(f"additional comparison {model} must accurately disclose overlap with frozen public labels")
            if declaration.get("metrics") != ["mae_kcal_mol","rmse_kcal_mol","r2"]:
                raise ScienceFailure(f"additional comparison {model} must declare recomputed MAE/RMSE/R2 metrics")
            if int(row["n_train"])!=len(atrain) or int(row["n_test"])!=len(atest) or row["protocol"]!=declaration.get("protocol_id"):
                raise ScienceFailure(f"additional comparison {model} count/protocol mismatch")
    by_model = select_comparison_rows(rows, protocol, read_json(final / "model_spec.json", "model_spec.json"))
    submitted_additional={r["model"] for r in rows if r["model"] not in REQUIRED_MODELS}
    if submitted_additional!=set(additional): raise ScienceFailure("declared additional comparisons must exactly match submitted rows")
    pred_cache = {}
    for row in rows:
        pred_path=prediction_paths[row["prediction_file"]]
        if not pred_path.resolve().is_relative_to(final.resolve()): raise ScienceFailure("prediction_file escapes final/")
        model=row["model"]
        indices=test if model in REQUIRED_MODELS else additional[model]["test_indices"]
        pred_cache[str(pred_path)]=load_prediction(pred_path,targets,indices,model)
        mae,rmse,r2=metrics(pred_cache[str(pred_path)])
        for key,actual in (("mae_kcal_mol",mae),("rmse_kcal_mol",rmse),("r2",r2)):
            if not close(float(row[key]),actual): raise ScienceFailure(f"{model} reported {key} does not recompute from predictions")
        if model not in REQUIRED_MODELS:
            decl=additional[model]; arm=decl.get("model_spec")
            if not isinstance(arm,dict): raise ReviewRequired(f"additional comparison {model} lacks a supported model_spec")
            matrix_file=arm.get("matrix_file")
            if matrix_file not in set(MATRIX_FILES.values()): raise ReviewRequired(f"additional comparison {model} uses an unsupported feature source")
            columns=arm.get("feature_columns")
            matrix=load_selected_matrix(assets/matrix_file,columns)
            atrain=decl["train_indices"]; atest=decl["test_indices"]
            folds=arm.get("cv_folds")
            pred_expected,_=independent_refit(arm,matrix[np.asarray(atrain)],np.asarray([targets[i] for i in atrain]),matrix[np.asarray(atest)],folds,arm.get("seed"))
            pred_actual=np.asarray([pred_cache[str(pred_path)][i][1] for i in atest])
            if not prediction_matches_refit(pred_actual, pred_expected, arm, matrix[np.asarray(atrain)], np.asarray([targets[i] for i in atrain]), matrix[np.asarray(atest)], folds, arm.get("seed")):
                raise ScienceFailure(f"additional comparison {model} differs from independent refit")
    refit_audit = check_independent_refits(final, assets, targets, train, test, by_model, pred_cache)
    preferred_metrics = {m: metrics(pred_cache[str(final / by_model[m]["prediction_file"])]) for m in REQUIRED_MODELS}
    hybrid_mae = preferred_metrics["hybrid"][0]
    direct_mae = preferred_metrics["direct_barrier"][0]
    mean_mae = preferred_metrics["mean_baseline"][0]
    band = {
        "hybrid_mae_at_most_1_10": hybrid_mae <= 1.10,
        "hybrid_improves_direct_by_1": direct_mae - hybrid_mae >= 1.0,
        "hybrid_beats_mean": hybrid_mae < mean_mae,
    }
    test_predictions = load_prediction(final / "test_predictions.csv", targets, test, "test_predictions.csv")
    if test_predictions != pred_cache[str(final / by_model["hybrid"]["prediction_file"])]:
        raise ScienceFailure("test_predictions.csv must be the preferred hybrid prediction artifact")
    result = {
        "status": "PASS" if all(band.values()) else "SCIENTIFIC_BAND_FAIL",
        "coverage": "PARTIAL",
        "training_execution_verified": False,
        "declared_protocol_independent_refit_verified": True,
        "refit_audit": refit_audit,
        "protocol_checks": "PASS",
        "leakage_checks": "PASS",
        "metrics": {m: {"mae": v[0], "rmse": v[1], "r2": v[2]} for m, v in preferred_metrics.items()},
        "scientific_band": band,
        "additional_comparisons": {name:{"purpose":decl["purpose"],"n_train":len(decl["train_indices"]),"n_test":len(decl["test_indices"]),"metrics":{k:metrics(pred_cache[str(final/next(r["prediction_file"] for r in rows if r["model"]==name))])[i] for i,k in enumerate(("mae","rmse","r2"))}} for name,decl in additional.items()},
        "warnings": ["Full vs No TS direction is reported, not imposed as a pass condition."],
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=Path, default=Path("."))
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--refs", type=Path, required=True)
    parser.add_argument("--ablation", type=Path, help="Full/No TS 配对消融目录")
    parser.add_argument("--ts-ablation", type=Path, help="可选：Full/删除 TS 列配对消融目录")
    args = parser.parse_args(argv)
    try:
        check_evaluation_inputs(args.assets.absolute(), args.refs.absolute())
        if args.ts_ablation:
            result = check_ts_ablation(args.ts_ablation.resolve(), args.assets.resolve())
        elif args.ablation:
            result = check_ablation(args.ablation.resolve(), args.assets.resolve())
        else:
            result = check_submission(args.submission.resolve(), args.assets.resolve(), args.refs.resolve())
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["status"] == "PASS" else 1
    except ScienceFailure as exc:
        print(json.dumps({"status": "FAIL", "coverage": "PARTIAL", "errors": [str(exc)]}, indent=2, ensure_ascii=False))
        return 1
    except ReviewRequired as exc:
        print(json.dumps({"status": "REVIEW_REQUIRED", "coverage": "NOT_VERIFIED", "errors": [str(exc)]}, indent=2, ensure_ascii=False))
        return 11
    except CandidateProtocolError as exc:
        print(json.dumps({"status": "FAIL", "coverage": "PARTIAL", "errors": [f"invalid or inconsistent declared protocol: {exc}"]}, indent=2, ensure_ascii=False))
        return 1
    except InfrastructureFailure as exc:
        print(json.dumps({"status": "INFRA_ERROR", "errors": [str(exc)]}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        print(json.dumps({"status": "INFRA_ERROR", "errors": [f"trusted checker execution error: {type(exc).__name__}: {exc}"]}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
