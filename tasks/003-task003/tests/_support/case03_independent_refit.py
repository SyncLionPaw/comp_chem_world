"""Evaluator-owned numerical refit for the declared Case 03 protocol.

This code runs in the ordinary offline grader. It never imports or executes
submitted Python; unsupported scientific methods are routed to REVIEW_REQUIRED
rather than labeled scientifically wrong.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import sklearn
from case03_protocol_compat import normalize_v6_protocol
from sklearn.decomposition import PCA
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.kernel_ridge import KernelRidge
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ARMS = {
    "mechanistic": "SC-012-D0SC04896H-s120.csv",
    "no_ts": "SC-012-D0SC04896H-s138.csv",
    "fingerprint": "SC-012-D0SC04896H-s131.csv",
}
FORBIDDEN_COLUMNS = {"exp_activation_energy", "activation_energy", "row_index", "reaction_smiles",
                     "reaction_smiles_orig", "reaction_id"}


class CandidateValidationError(Exception):
    """A checked candidate declaration violates the published protocol."""


class ReviewRequired(CandidateValidationError):
    """A potentially valid method is outside the independently implemented vocabulary."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _read_table(path: Path, *, target: bool = False):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if len(fields) < 2 or len(rows) != 443 or fields[0] not in ("", "Unnamed: 0"):
        raise ValueError(f"invalid canonical input table: {path.name}")
    ids = [int(float(row[fields[0]])) for row in rows]
    if ids != list(range(443)):
        raise ValueError(f"input row order changed: {path.name}")
    if target:
        values = np.asarray([float(row["exp_activation_energy"]) for row in rows], dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("target contains nonfinite values")
        return values
    columns = [name for name in fields[1:] if name not in FORBIDDEN_COLUMNS]
    matrix = np.asarray([[float(row[name]) for name in columns] for row in rows], dtype=float)
    if not np.isfinite(matrix).all() or matrix.shape != (443, len(columns)):
        raise ValueError(f"invalid matrix values: {path.name}")
    return columns, matrix


def _validate_spec(spec, columns_by_arm, *, controlled=True):
    if not isinstance(spec, dict) or not {"schema", "arms"}.issubset(spec) or spec.get("schema") != "case03-model-spec/v1":
        raise CandidateValidationError("protocol.model_spec must use case03-model-spec/v1")
    arms = spec.get("arms")
    if not isinstance(arms, dict) or set(arms) != set(ARMS):
        raise CandidateValidationError("model_spec must define exactly the three scored arms")
    family_counts, grid_counts, fold_counts = set(), set(), set()
    normalized = {}
    for arm in ARMS:
        item = arms[arm]
        required_arm_fields = {"feature_columns", "scaler", "pca", "target_scaler", "estimator", "cv"}
        if not isinstance(item, dict) or not required_arm_fields.issubset(item):
            raise CandidateValidationError(f"model_spec arm {arm} has unexpected fields")
        columns = item["feature_columns"]
        if (not isinstance(columns, list) or not columns
                or any(type(column) is not str for column in columns)
                or len(columns) != len(set(columns))
                or any(column not in columns_by_arm[arm] or column.lower() in FORBIDDEN_COLUMNS for column in columns)):
            raise CandidateValidationError(f"model_spec feature selection is invalid for {arm}")
        if item["scaler"] not in ("none", "standard") or item["target_scaler"] not in ("none", "standard"):
            raise ReviewRequired("a declared scaler is outside the integrated independent-refit vocabulary")
        pca = item["pca"]
        if pca is not None:
            pca_keys = {"n_components", "copy", "whiten", "svd_solver", "tol", "iterated_power",
                        "n_oversamples", "power_iteration_normalizer", "random_state"}
            if (not isinstance(pca, dict) or not {"n_components", "random_state"}.issubset(pca)
                    or set(pca) - pca_keys or type(pca["n_components"]) is not int
                    or pca["n_components"] < 1 or pca["n_components"] > len(columns)
                    or type(pca["random_state"]) is not int
                    or not 0 <= pca["random_state"] <= 2**32 - 1):
                raise CandidateValidationError("PCA declaration is invalid")
            if "svd_solver" in pca and (type(pca["svd_solver"]) is not str or pca["svd_solver"] not in {
                    "auto", "full", "arpack", "randomized", "covariance_eigh"}):
                raise CandidateValidationError("PCA svd_solver is unsupported by the pinned scikit-learn protocol")
            if any(type(pca[key]) is not bool for key in ("copy", "whiten") if key in pca):
                raise CandidateValidationError("PCA copy and whiten parameters must be booleans")
            if "tol" in pca and (type(pca["tol"]) not in (int, float) or not math.isfinite(pca["tol"]) or pca["tol"] < 0):
                raise CandidateValidationError("PCA tol must be finite and nonnegative")
            if "iterated_power" in pca and not (
                    (type(pca["iterated_power"]) is int and pca["iterated_power"] >= 0)
                    or pca["iterated_power"] == "auto"):
                raise CandidateValidationError("PCA iterated_power must be an integer or 'auto'")
            if "n_oversamples" in pca and (type(pca["n_oversamples"]) is not int or pca["n_oversamples"] < 1):
                raise CandidateValidationError("PCA n_oversamples must be a positive integer")
            if ("power_iteration_normalizer" in pca and
                    (type(pca["power_iteration_normalizer"]) is not str
                     or pca["power_iteration_normalizer"] not in {"auto", "QR", "LU", "none"})):
                raise CandidateValidationError("PCA power_iteration_normalizer is unsupported")
        estimator = item["estimator"]
        if not isinstance(estimator, dict) or "family" not in estimator:
            raise CandidateValidationError("estimator declaration must include a family")
        if "parameter_grid" not in estimator and "param_grid" in estimator:
            estimator = {**estimator, "parameter_grid": estimator["param_grid"]}
        if "parameter_grid" not in estimator:
            raise CandidateValidationError("estimator declaration must include parameter_grid")
        family = estimator["family"]
        if type(family) is not str:
            raise CandidateValidationError("estimator family must be a JSON string")
        allowed = {
            "Ridge": {"alpha": ("float", 0.0, math.inf)},
            "KernelRidge": {"alpha": ("float", 0.0, math.inf),
                            "kernel": ("enum", None, ("linear", "rbf", "poly", "sigmoid", "cosine", "laplacian",
                                                       "additive_chi2", "chi2")),
                            "gamma": ("float", 0.0, math.inf),
                            "degree": ("int", 1, math.inf), "coef0": ("float", -math.inf, math.inf)},
            "GaussianProcessRegressor": {"alpha": ("float", 0.0, math.inf),
                                         "normalize_y": ("bool", False, True)},
        }
        if family not in allowed:
            raise ReviewRequired(f"estimator family {family!r} is outside the integrated independent-refit vocabulary")
        grid = estimator["parameter_grid"]
        if isinstance(grid, list) and grid:
            # Explicit candidate dictionaries are equivalent to a cartesian grid
            # when they enumerate its full product.
            keys = list(grid[0]) if isinstance(grid[0], dict) else []
            if (not keys or any(not isinstance(candidate, dict) or set(candidate) != set(keys)
                                for candidate in grid)):
                raise CandidateValidationError("explicit parameter candidates must share one key set")
            columns = {key: [] for key in keys}
            for candidate in grid:
                for key in keys:
                    if candidate[key] not in columns[key]:
                        columns[key].append(candidate[key])
            if math.prod(len(values) for values in columns.values()) != len(grid):
                raise ReviewRequired("explicit parameter candidates are not a full cartesian grid")
            grid = columns
        if not isinstance(grid, dict) or not grid:
            raise CandidateValidationError("estimator parameter_grid must be a nonempty object")
        if set(grid) - set(allowed[family]):
            raise ReviewRequired("estimator parameters are outside the integrated independent-refit vocabulary")
        fixed = estimator.get("fixed_parameters", {})
        if not isinstance(fixed, dict):
            raise CandidateValidationError("estimator fixed_parameters must be an object when supplied")
        if set(fixed) - set(allowed[family]):
            raise ReviewRequired("fixed estimator parameters are outside the integrated independent-refit vocabulary")
        effective_grid = dict(grid)
        for key, value in fixed.items():
            if key in grid:
                values = grid[key]
                if (not isinstance(values, list) or len(values) != 1
                        or type(values[0]) is not type(value) or values[0] != value):
                    raise CandidateValidationError("fixed estimator parameters conflict with the parameter grid")
            else:
                effective_grid[key] = [value]
        grid = effective_grid
        sizes = []
        for key, values in grid.items():
            if not isinstance(values, list) or not values:
                raise CandidateValidationError("parameter grid values must be nonempty lists")
            kind, lo, hi = allowed[family][key]
            if kind == "float" and any(type(v) not in (int, float) or not math.isfinite(v) or not lo <= v <= hi for v in values):
                raise CandidateValidationError("floating model parameter is out of supported bounds")
            if kind == "int" and any(type(v) is not int or not lo <= v <= hi for v in values):
                raise CandidateValidationError("integer model parameter is out of supported bounds")
            if kind == "bool" and any(type(v) is not bool for v in values):
                raise CandidateValidationError("boolean model parameter must use exact JSON booleans")
            if kind == "enum":
                if any(type(v) is not str for v in values):
                    raise CandidateValidationError("categorical model parameters must be JSON strings")
                if family == "KernelRidge" and key == "kernel":
                    if any(v == "precomputed" for v in values):
                        raise ReviewRequired("KernelRidge precomputed-kernel inputs are valid but outside the integrated refit data path")
                    if any(v not in hi and v != "polynomial" for v in values):
                        raise CandidateValidationError("KernelRidge kernel name is not a scikit-learn pairwise kernel")
                elif any(v not in hi for v in values):
                    raise CandidateValidationError("categorical model parameter is unsupported")
            if family == "KernelRidge" and key == "alpha" and any(v <= 0 for v in values):
                raise CandidateValidationError("KernelRidge alpha must be positive")
            if family == "KernelRidge" and key == "gamma" and any(v <= 0 for v in values):
                raise CandidateValidationError("KernelRidge gamma must be positive")
            sizes.append(len(values))
        grid_count = math.prod(sizes)
        if grid_count < 1:
            raise CandidateValidationError("parameter grid must contain at least one parameter combination")
        cv = item["cv"]
        if not isinstance(cv, dict) or not {"n_splits", "shuffle", "random_state", "scoring"}.issubset(cv):
            raise CandidateValidationError("CV declaration has an invalid field set")
        if type(cv["n_splits"]) is not int or cv["n_splits"] < 2:
            raise CandidateValidationError("CV n_splits must be an integer of at least two")
        if cv["n_splits"] > 10 or cv["shuffle"] is not True or cv["scoring"] != "neg_mean_absolute_error":
            raise ReviewRequired("the CV method is outside the integrated independent-refit vocabulary")
        if type(cv["random_state"]) is not int or not 0 <= cv["random_state"] <= 2**32 - 1:
            raise CandidateValidationError("CV random_state must be an integer in 0..2**32-1")
        family_counts.add(family)
        grid_counts.add(grid_count)
        fold_counts.add(cv["n_splits"])
        normalized_item = dict(item)
        if pca is not None:
            normalized_pca = {"svd_solver": "randomized", **pca}
            normalized_item["pca"] = normalized_pca
        normalized_grid = dict(grid)
        if family == "KernelRidge" and "kernel" in grid and "polynomial" in grid["kernel"]:
            normalized_grid["kernel"] = ["poly" if value == "polynomial" else value for value in grid["kernel"]]
        normalized_estimator = dict(estimator)
        normalized_estimator["parameter_grid"] = normalized_grid
        normalized_item["estimator"] = normalized_estimator
        normalized[arm] = normalized_item
    if controlled:
        if len(family_counts) != 1 or len(grid_counts) != 1 or len(fold_counts) != 1:
            raise ReviewRequired("model-selection-combination comparison is outside the integrated controlled-representation refit scope")
        cv_contracts = {(item["cv"]["shuffle"], item["cv"]["random_state"], item["cv"]["scoring"])
                        for item in normalized.values()}
        if len(cv_contracts) != 1:
            raise ReviewRequired("arm-specific CV protocols are outside the integrated controlled-representation refit scope")
    return normalized


def _estimator(family, params):
    if family == "Ridge":
        return Ridge(**params)
    if family == "KernelRidge":
        return KernelRidge(**params)
    if family == "GaussianProcessRegressor":
        return GaussianProcessRegressor(**params, optimizer=None, copy_X_train=True)
    raise ValueError("unsupported estimator")


def _pipeline(spec, params):
    steps = []
    if spec["scaler"] == "standard":
        steps.append(("scale", StandardScaler()))
    if spec["pca"] is not None:
        steps.append(("pca", PCA(**spec["pca"])))
    steps.append(("model", _estimator(spec["estimator"]["family"], params)))
    return Pipeline(steps)


def _parameter_grid(spec):
    grid = spec["estimator"]["parameter_grid"]
    keys = sorted(grid)
    out = [{}]
    for key in keys:
        out = [dict(item, **{key: value}) for item in out for value in grid[key]]
    return out


def _fit_predict(spec, X_train, y_train, X_test):
    cv = spec["cv"]
    splitter = KFold(n_splits=cv["n_splits"], shuffle=True, random_state=cv["random_state"])
    pca = spec["pca"]
    if pca is not None:
        smallest_inner_train = len(X_train) - math.ceil(len(X_train) / cv["n_splits"])
        smallest_dimension = min(smallest_inner_train, X_train.shape[1])
        n_components = pca["n_components"]
        solver = pca.get("svd_solver", "randomized")
        if (n_components > smallest_dimension
                or (solver == "arpack" and n_components >= smallest_dimension)):
            raise CandidateValidationError("PCA n_components is invalid for the smallest inner training fold and declared svd_solver")
    grid = _parameter_grid(spec)
    folds = []
    scores = []
    for params in grid:
        fold_scores = []
        for train_local, valid_local in splitter.split(X_train):
            model = _pipeline(spec, params)
            y_fit = y_train[train_local]
            if spec["target_scaler"] == "standard":
                mean = float(np.mean(y_fit)); scale = float(np.std(y_fit)) or 1.0
                y_model = (y_fit - mean) / scale
            else:
                mean, scale, y_model = 0.0, 1.0, y_fit
            model.fit(X_train[train_local], y_model)
            pred = np.asarray(model.predict(X_train[valid_local]), dtype=float) * scale + mean
            fold_scores.append(float(np.mean(np.abs(pred - y_train[valid_local]))))
            if not folds:
                folds.append({"train_local": train_local.tolist(), "validation_local": valid_local.tolist()})
        scores.append(float(np.mean(fold_scores)))
    # Stable tie behavior: first parameter tuple in canonical sorted-key grid order.
    best_index = min(range(len(grid)), key=lambda idx: (scores[idx], idx))
    model = _pipeline(spec, grid[best_index])
    if spec["target_scaler"] == "standard":
        mean = float(np.mean(y_train)); scale = float(np.std(y_train)) or 1.0
        y_model = (y_train - mean) / scale
    else:
        mean, scale, y_model = 0.0, 1.0, y_train
    model.fit(X_train, y_model)
    pred = np.asarray(model.predict(X_test), dtype=float) * scale + mean
    if pred.shape != (len(X_test),) or not np.isfinite(pred).all():
        raise ValueError("independent refit produced nonfinite predictions")
    return pred, grid, scores, best_index, folds


def evaluate(final: Path, assets: Path):
    protocol = json.loads((final / "protocol.json").read_text(encoding="utf-8"))
    splits = json.loads((final / "splits.json").read_text(encoding="utf-8"))
    try:
        protocol = normalize_v6_protocol(protocol, ARMS, splits.get("repeats_per_size"))
    except ValueError as exc:
        raise CandidateValidationError(f"invalid protocol comparison/representation declaration: {exc}") from exc
    comparison_design = protocol.get("comparison_design")
    if comparison_design not in ("controlled_representation", "model_selection_combination"):
        raise CandidateValidationError("protocol.comparison_design must be a registered v6 value")
    columns_by_arm = {arm: _read_table(assets / filename)[0] for arm, filename in ARMS.items()}
    spec = _validate_spec(protocol.get("model_spec"), columns_by_arm,
                          controlled=comparison_design == "controlled_representation")
    if comparison_design == "model_selection_combination":
        raise ReviewRequired("model-selection-combination comparisons are scientifically valid but outside this revision's integrated independent-refit scope")
    budget = protocol.get("tuning_budget", {})
    grid_counts = {arm: math.prod(len(values) for values in item["estimator"]["parameter_grid"].values())
                   for arm, item in spec.items()}
    fold_counts = {arm: item["cv"]["n_splits"] for arm, item in spec.items()}
    if (budget.get("same_across_scored_arms") is not True or
            set(grid_counts.values()) != {budget.get("candidate_models_per_arm")} or
            set(fold_counts.values()) != {budget.get("inner_folds")}):
        raise CandidateValidationError("tuning_budget does not match the declared controlled-representation model_spec")
    target = _read_table(assets / "SC-012-D0SC04896H-s115.csv", target=True)
    matrices = {arm: _read_table(assets / filename) for arm, filename in ARMS.items()}
    candidate = {}
    with (final / "predictions.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (row["representation"], int(row["n_train"]), int(row["repeat_index"]), int(row["row_index"]))
            if key in candidate:
                raise CandidateValidationError("candidate predictions contain duplicate keys")
            candidate[key] = float(row["y_pred_kcal_mol"])
    results, errors = [], []
    common_fold_indices = {}
    for split in splits["records"]:
        n, repeat = int(split["n_train"]), int(split["repeat_index"])
        train, test = [int(i) for i in split["train_indices"]], [int(i) for i in split["test_indices"]]
        for arm, filename in ARMS.items():
            all_columns, matrix = matrices[arm]
            arm_spec = spec[arm]
            column_index = [all_columns.index(name) for name in arm_spec["feature_columns"]]
            X_train = matrix[np.asarray(train)[:, None], column_index]
            X_test = matrix[np.asarray(test)[:, None], column_index]
            pred, grid, scores, best, folds = _fit_predict(arm_spec, X_train, target[train], X_test)
            match = len(pred) == len(test) and all(abs(float(pred[j]) - candidate[(arm, n, repeat, row_id)]) <= 1e-8
                                                   for j, row_id in enumerate(test))
            if not match:
                errors.append(f"{arm}/n{n}/r{repeat}: independent refit differs from submitted predictions")
            fold_rows = []
            splitter = KFold(n_splits=arm_spec["cv"]["n_splits"], shuffle=True,
                             random_state=arm_spec["cv"]["random_state"])
            for fold_index, (tr_local, va_local) in enumerate(splitter.split(X_train)):
                fold_rows.append({"fold": fold_index,
                                  "train_global_indices": [train[int(i)] for i in tr_local],
                                  "validation_global_indices": [train[int(i)] for i in va_local]})
            fold_key = (n, repeat)
            if fold_key not in common_fold_indices:
                common_fold_indices[fold_key] = fold_rows
            elif common_fold_indices[fold_key] != fold_rows:
                raise ValueError("inner validation folds differ across scored arms")
            results.append({"representation": arm, "n_train": n, "repeat_index": repeat,
                            "paired_split_id": split["paired_split_id"],
                            "train_indices_sha256": _sha(_canonical(train)),
                            "test_indices_sha256": _sha(_canonical(test)),
                            "feature_columns": arm_spec["feature_columns"],
                            "parameter_grid": grid, "mean_cv_mae": scores, "selected_grid_index": best,
                            "selected_parameters": grid[best],
                            "folds": fold_rows, "prediction_sha256": _sha(_canonical([float(x) for x in pred])),
                            "candidate_match": match})
    return {"schema": "p01-case03-independent-refit/v1", "status": "ok" if not errors else "candidate_fail",
            "coverage": "PARTIAL", "candidate_internals_proven": False,
            "declared_protocol_independent_refit_verified": not errors,
            "training_execution_verified": False, "sklearn_version": sklearn.__version__,
            "model_spec_sha256": _sha(_canonical(protocol["model_spec"])),
            "protocol_sha256": _sha((final / "protocol.json").read_bytes()),
            "splits_sha256": _sha((final / "splits.json").read_bytes()),
            "predictions_sha256": _sha((final / "predictions.csv").read_bytes()),
            "records": results, "errors": errors}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = evaluate(args.final, args.assets)
    except ReviewRequired as exc:
        result = {"schema": "p01-case03-independent-refit/v2", "status": "review_required",
                  "coverage": "NOT_VERIFIED", "candidate_internals_proven": False,
                  "declared_protocol_independent_refit_verified": False,
                  "training_execution_verified": False, "records": [],
                  "errors": [str(exc)]}
    except CandidateValidationError as exc:
        result = {"schema": "p01-case03-independent-refit/v2", "status": "candidate_fail",
                  "coverage": "PARTIAL", "candidate_internals_proven": False,
                  "declared_protocol_independent_refit_verified": False,
                  "training_execution_verified": False, "records": [],
                  "errors": [f"published candidate protocol violation: {type(exc).__name__}: {exc}"]}
    except Exception as exc:
        result = {"schema": "p01-case03-independent-refit/v2", "status": "infra_error",
                  "coverage": "NOT_VERIFIED", "candidate_internals_proven": False,
                  "declared_protocol_independent_refit_verified": False,
                  "training_execution_verified": False, "records": [],
                  "errors": [f"trusted refit error: {type(exc).__name__}: {exc}"]}
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))


if __name__ == "__main__":
    main()
