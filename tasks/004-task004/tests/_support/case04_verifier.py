#!/usr/bin/env python3
"""Independent blind-arm verifier for case 04.

The checker is the only component that opens the grader-side frozen test answers.
It writes aggregate metrics and structural checks, never row-level truth values.
Run from the repository root with:
  uv run --python 3.12 --with numpy --with pandas --with scikit-learn \
    python scripts/verify_case04.py
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import TransformedTargetRegressor
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import RepeatedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

_HERE = Path(__file__).resolve()
CASE = next((p for p in _HERE.parents if p.name == "case-04-uncertainty-applicability-domain"
             and (p / "environment/assets/master_s115_blindarm.csv").is_file()), None)
if CASE is None:
    CASE = next((p for p in _HERE.parents if (p / "task.toml").is_file()
                 and (p / "environment/assets/master_s115_blindarm.csv").is_file()), None)
if CASE is None:
    ROOT = _HERE.parents[1]
    CASE = ROOT / "packages/case-04-uncertainty-applicability-domain"
else:
    ROOT = next((p for p in CASE.parents if (p / "packages" / CASE.name).resolve() == CASE.resolve()), CASE.parents[1])
ASSETS = CASE / "environment/assets"
GOLD = ROOT / "data/gold/derived/test_answers_s118_v1.csv"
RUNTIME = ROOT / "data/gold/derived/case04_runtime"
CONTRAST = RUNTIME / "protocol_contrast"
_MODEL_CACHE: dict[str, Any] = {}
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import case04_protocol as case04_protocol


def _scope_text(value: Any) -> str:
    """Normalize punctuation so scope wording is compared by meaning, not separators."""
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _is_training_only_oof_scope(value: Any) -> bool:
    text = _scope_text(value)
    training = ("training only" in text or "train only" in text or "frozen train" in text
                or ("train" in text and "test" not in text))
    oof = any(token in text for token in ("oof", "out of fold", "kfold", "k fold"))
    return training and oof


def _array_key(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        value = np.ascontiguousarray(array)
        digest.update(str(value.shape).encode())
        digest.update(str(value.dtype).encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def _base_estimator():
    """Feature-standardized GPR used by the frozen full-train fit."""
    kernel = ConstantKernel() * Matern(nu=1.5) + WhiteKernel()
    return make_pipeline(StandardScaler(), GaussianProcessRegressor(kernel=kernel, random_state=1))


def estimator():
    """Reconstruct the declared s089 GPR including fold-local target scaling."""
    return TransformedTargetRegressor(_base_estimator(), transformer=StandardScaler())


def _item(report: dict[str, Any], name: str, status: str, **details: Any) -> None:
    report["checks"].append({"name": name, "status": status, **details})


def _safe_array(path: Path, dtype=int) -> np.ndarray:
    return np.asarray(np.load(path, allow_pickle=False), dtype=dtype).reshape(-1)


def _input_arrays() -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    master = pd.read_csv(ASSETS / "master_s115_blindarm.csv")
    train = _safe_array(ASSETS / "SC-012-D0SC04896H-s119.npy")
    test = _safe_array(ASSETS / "SC-012-D0SC04896H-s118.npy")
    xbase = pd.read_csv(ASSETS / "SC-012-D0SC04896H-s120.csv", index_col=0).to_numpy(float)
    extra = master["activation_energy_qh_grimme_ts"].to_numpy(float)
    X = np.column_stack([xbase, extra])
    y = master["exp_activation_energy"].to_numpy(float)
    return master, train, test, X, y


def _independent_prediction(X: np.ndarray, y: np.ndarray, train: np.ndarray, test: np.ndarray):
    """Refit on the frozen visible train rows; return prediction and posterior std."""
    key = "blind-refit:" + _array_key(X, y[train], train, test)
    if key in _MODEL_CACHE:
        return tuple(v.copy() for v in _MODEL_CACHE[key])
    yfit = y[train]
    y_scaler = StandardScaler().fit(yfit.reshape(-1, 1))
    model = _base_estimator()
    model.fit(X[train], y_scaler.transform(yfit.reshape(-1, 1)).ravel())
    mean_scaled, sigma_scaled = model[-1].predict(model[0].transform(X[test]), return_std=True)
    mean = y_scaler.inverse_transform(mean_scaled.reshape(-1, 1)).ravel()
    sigma = sigma_scaled * float(y_scaler.scale_[0])
    _MODEL_CACHE[key] = (mean.copy(), sigma.copy())
    return mean, sigma


def _verify_falsification(path: Path, X: np.ndarray, y: np.ndarray, train: np.ndarray) -> dict[str, Any]:
    if not path.exists():
        return {"status": "PENDING", "reason": f"missing {path.name}"}
    submitted = json.loads(path.read_text())
    values = np.asarray(submitted.get("r2_permutations", []), dtype=float)
    mae_values = np.asarray(submitted.get("mae_permutations", []), dtype=float)
    if len(values) != 10 or len(mae_values) != 10 or not np.isfinite(values).all() or not np.isfinite(mae_values).all():
        return {"status": "FAIL", "reason": "expected all 10 finite R2 and MAE permutation statistics"}
    if int(submitted.get("n_train", -1)) != len(train) or int(submitted.get("n_permutations", -1)) != 10:
        return {"status": "FAIL", "reason": "falsification split/count metadata does not match frozen protocol"}

    # Independently regenerate both statistics in one fit pass per fold. This checks
    # every permutation entry and avoids trusting a submitted distribution or pass bit.
    cv = RepeatedKFold(n_splits=10, n_repeats=1, random_state=1)
    splits = list(cv.split(X[train]))
    rng = np.random.RandomState(1)
    targets = [y[train].copy()]
    for _ in range(10):
        permuted_target = y[train].copy()
        rng.shuffle(permuted_target)
        targets.append(permuted_target)
    key = "permutation:" + _array_key(X[train], y[train], train)
    if key in _MODEL_CACHE:
        scores_r2, scores_mae = _MODEL_CACHE[key]
    else:
        scores_r2: list[float] = []
        scores_mae: list[float] = []
        for target in targets:
            fold_r2, fold_mae = [], []
            for tr, te in splits:
                model = estimator().fit(X[train[tr]], target[tr])
                prediction = model.predict(X[train[te]])
                fold_r2.append(float(r2_score(target[te], prediction)))
                fold_mae.append(float(mean_absolute_error(target[te], prediction)))
            scores_r2.append(float(np.mean(fold_r2)))
            scores_mae.append(float(np.mean(fold_mae)))
        _MODEL_CACHE[key] = (list(scores_r2), list(scores_mae))
    observed, permuted, recomputed_mae = scores_r2[0], np.asarray(scores_r2[1:]), np.asarray(scores_mae[1:])
    if not _v2_allclose(values, permuted, rtol=1e-5, atol=1e-5):
        return {"status": "FAIL", "reason": "submitted R2 permutation distribution differs from independent full recomputation",
                "submitted_n": int(len(values)), "recomputed_n": int(len(permuted))}
    if not _v2_allclose(mae_values, recomputed_mae, rtol=1e-5, atol=1e-5):
        return {"status": "FAIL", "reason": "submitted MAE permutation distribution differs from independent full recomputation"}
    if not math.isclose(float(submitted.get("true_r2", math.nan)), observed, rel_tol=1e-5, abs_tol=1e-5):
        return {"status": "FAIL", "reason": "submitted observed R2 differs from independent recomputation"}
    if not math.isclose(float(submitted.get("true_mae", math.nan)), scores_mae[0], rel_tol=1e-5, abs_tol=1e-5):
        return {"status": "FAIL", "reason": "submitted observed MAE differs from independent recomputation"}
    results = submitted.get("permutation_results", [])
    if len(results) != 10 or not _v2_allclose([r.get("r2", math.nan) for r in results], permuted, rtol=1e-5, atol=1e-5) or not _v2_allclose([r.get("mae", math.nan) for r in results], recomputed_mae, rtol=1e-5, atol=1e-5):
        return {"status": "FAIL", "reason": "permutation_results does not preserve aligned complete R2/MAE pairs"}
    separation = float(observed - np.max(permuted))
    # L3 uses the entire distribution, not a submitted pass field or p-value.
    effect_threshold_met = bool(separation >= 0.3 and np.all(observed > permuted))
    return {"status": "PASS", "n_permutations": 10,
            "observed_r2": float(observed), "permutation_r2_min": float(np.min(permuted)),
            "permutation_r2_max": float(np.max(permuted)), "permutation_r2_mean": float(np.mean(permuted)),
            "observed_mae": float(scores_mae[0]), "permutation_mae_min": float(np.min(recomputed_mae)),
            "permutation_mae_max": float(np.max(recomputed_mae)),
            "r2_separation": separation, "registered_benchmark_effect_met": effect_threshold_met,
            "all_permutations_below_observed": bool(np.all(observed > permuted)),
            "distribution_matches_independent_recomputation": True}


def _protocol_contrast(runtime_root: Path = RUNTIME) -> dict[str, Any]:
    """Audit LOGO receipts without using their hidden truths as training inputs."""
    contrast = runtime_root / "protocol_contrast"
    identity_path = runtime_root / "group_identity_audit.json"
    summary_path = contrast / "summary.json"
    split_path = contrast / "fold_splits.jsonl"
    pred_path = contrast / "logo_predictions.csv"
    if not summary_path.exists() or not split_path.exists() or not pred_path.exists():
        return {"status": "PENDING", "reason": "protocol contrast summary or fold evidence is missing"}
    summary = json.loads(summary_path.read_text())
    vectors = {
        "substrate": _safe_array(ASSETS / "SC-012-D0SC04896H-s117.npy"),
        "nucleophile": _safe_array(ASSETS / "SC-012-D0SC04896H-s114.npy"),
    }
    train = _safe_array(ASSETS / "SC-012-D0SC04896H-s119.npy")
    all_rows = np.arange(443, dtype=int)
    datasets = {
        "author_354_rows_34_features": (train, 34),
        "all_443_rows_34_features": (all_rows, 34),
        "author_354_rows_33_features": (train, 33),
    }
    results: dict[str, Any] = {}
    failures = []
    folds_by_key: dict[str, list[dict[str, Any]]] = {}
    for line_no, line in enumerate(split_path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        fold = json.loads(line)
        key = f"{fold.get('dataset')}/{fold.get('group_role')}"
        folds_by_key.setdefault(key, []).append(fold)
    pred = pd.read_csv(pred_path)
    pred_required = {"dataset", "group_role", "group_id", "fold", "row_index", "prediction", "absolute_error"}
    if not pred_required <= set(pred.columns):
        return {"status": "FAIL", "reason": "protocol prediction receipt missing required columns"}
    master, _, _, X34, y_public = _input_arrays()
    X33 = pd.read_csv(ASSETS / "SC-012-D0SC04896H-s120.csv", index_col=0).to_numpy(float)
    # A deterministic reconstruction of split indices can check the claimed partition,
    # but is not itself native evidence of which rows were fitted. Refit representative
    # author-route folds below to independently confirm the estimator and predictions.
    refit_checks = []
    for dataset, (expected_rows, feature_count) in datasets.items():
        for role, full_group_vector in vectors.items():
            key = f"{dataset}/{role}"
            records = folds_by_key.get(key, [])
            if not records:
                failures.append(f"{key}: fold split receipt missing")
                continue
            group_on_rows = full_group_vector[expected_rows]
            seen_test: list[int] = []
            group_to_fold: dict[int, int] = {}
            held_fold_metrics = []
            for fold in records:
                if fold.get("dataset") != dataset or fold.get("group_role") != role:
                    failures.append(f"{key}: dataset/role mismatch")
                if int(fold.get("features", -1)) != feature_count:
                    # Older normalized receipts omit this field; feature count is set by route name.
                    if "features" in fold:
                        failures.append(f"{key}: feature count mismatch")
                test_rows = [int(v) for v in fold.get("test_global_indices", [])]
                train_rows = [int(v) for v in fold.get("train_global_indices", [])]
                held = int(fold.get("group_id", -1))
                if not test_rows or len(set(test_rows)) != len(test_rows):
                    failures.append(f"{key}: empty or duplicate test rows")
                    continue
                if set(train_rows) & set(test_rows):
                    failures.append(f"{key}: train/test global row leakage")
                if set(train_rows) | set(test_rows) != set(expected_rows.tolist()):
                    failures.append(f"{key}: train/test rows do not partition declared dataset")
                pos = {int(row): i for i, row in enumerate(expected_rows.tolist())}
                if any(row not in pos for row in test_rows + train_rows):
                    failures.append(f"{key}: row outside declared data scope")
                elif any(int(group_on_rows[pos[row]]) != held for row in test_rows):
                    failures.append(f"{key}: held test rows do not match the declared group vector")
                elif any(int(group_on_rows[pos[row]]) == held for row in train_rows):
                    failures.append(f"{key}: held group appears in training rows")
                if held in group_to_fold:
                    failures.append(f"{key}: group appears in multiple test folds")
                group_to_fold[held] = int(fold.get("fold", -1))
                seen_test.extend(test_rows)
                pr = pred[(pred.dataset == dataset) & (pred.group_role == role) & (pred.fold == int(fold.get("fold", -1)))]
                pr = pr[pr.group_id.astype(int) == held]
                if set(pr.row_index.astype(int).tolist()) != set(test_rows):
                    failures.append(f"{key}: fold predictions do not cover the declared held-out rows")
                else:
                    actual_mae = float(pr.absolute_error.astype(float).mean())
                    if not math.isclose(actual_mae, float(fold.get("mae", math.nan)), rel_tol=2e-5, abs_tol=2e-5):
                        failures.append(f"{key}: fold MAE does not match per-row predictions")
                    held_fold_metrics.append((actual_mae, len(test_rows)))
            if sorted(seen_test) != sorted(expected_rows.tolist()):
                failures.append(f"{key}: test rows are not an exact once-only cover of the dataset")
            if len(group_to_fold) != int(np.unique(group_on_rows).size):
                failures.append(f"{key}: expected each released group exactly once as held-out group")
            if not held_fold_metrics or sum(n for _, n in held_fold_metrics) != len(expected_rows):
                failures.append(f"{key}: incomplete fold MAE evidence")
                continue
            results[key] = {
                "n_groups": int(len(group_to_fold)), "n_scored": int(sum(n for _, n in held_fold_metrics)),
                "macro_group_mae": float(np.mean([m for m, _ in held_fold_metrics])),
                "micro_row_mae": float(np.average([m for m, _ in held_fold_metrics], weights=[n for _, n in held_fold_metrics])),
                "macro_group_sem": float(np.std([m for m, _ in held_fold_metrics], ddof=1) / np.sqrt(len(held_fold_metrics))) if len(held_fold_metrics) > 1 else 0.0,
                "fold_training_and_group_disjointness_checked": True,
            }
            declared = summary.get("results", {}).get(key)
            if not declared:
                failures.append(f"{key}: no corresponding summary entry")
            else:
                for metric in ("n_groups", "n_scored", "macro_group_mae", "micro_row_mae", "macro_group_sem"):
                    if not math.isclose(float(declared[metric]), float(results[key][metric]), rel_tol=2e-5, abs_tol=2e-5):
                        failures.append(f"{key}: summary {metric} differs from fold receipts")

            # Refit two author-354/34 folds per direction with only public training
            # responses and compare every emitted prediction in those folds.
            if dataset == "author_354_rows_34_features":
                selected = sorted(records, key=lambda x: int(x.get("fold", -1)))
                if selected:
                    sample_folds = [selected[0], selected[len(selected) // 2]]
                    for fold in sample_folds:
                        tr = np.asarray(fold["train_global_indices"], dtype=int)
                        te = np.asarray(fold["test_global_indices"], dtype=int)
                        if not np.isfinite(y_public[tr]).all():
                            failures.append(f"{key}: refit train rows include masked targets")
                            continue
                        feat = X34 if feature_count == 34 else X33
                        refit_key = "logo-refit:" + _array_key(feat[tr], y_public[tr], tr, te)
                        if refit_key in _MODEL_CACHE:
                            p_refit = _MODEL_CACHE[refit_key].copy()
                        else:
                            m = estimator().fit(feat[tr], y_public[tr])
                            p_refit = np.asarray(m.predict(feat[te]), dtype=float)
                            _MODEL_CACHE[refit_key] = p_refit.copy()
                        pr = pred[(pred.dataset == dataset) & (pred.group_role == role) & (pred.fold == int(fold["fold"]))]
                        pr = pr.sort_values("row_index")
                        pr = pr[pr.group_id.astype(int) == int(fold["group_id"]) ]
                        want = pr.set_index("row_index").loc[te, "prediction"].to_numpy(float)
                        delta = float(np.max(np.abs(p_refit - want))) if len(want) else math.inf
                        passed = len(want) == len(te) and delta <= 2e-5
                        refit_checks.append({"route": key, "fold": int(fold["fold"]), "n_train": len(tr),
                                             "n_test": len(te), "prediction_matches_refit": bool(passed),
                                             "max_abs_prediction_delta": delta})
                        if not passed:
                            failures.append(f"{key}: independent representative fold refit mismatch")

    group_counts = {role: int(np.unique(vector).size) for role, vector in vectors.items()}
    id_status = "PENDING"
    id_details: dict[str, Any] = {}
    if identity_path.exists():
        identity = json.loads(identity_path.read_text())
        reported = identity.get("vectors", {})
        roles_ok = (reported.get("SC-012-D0SC04896H-s114.npy", {}).get("role") == "nucleophile"
                    and reported.get("SC-012-D0SC04896H-s117.npy", {}).get("role") == "substrate"
                    and reported.get("SC-012-D0SC04896H-s113.npy", {}).get("role") == "reaction")
        vector_audit_ok = all(
            reported.get(filename, {}).get(field) is True
            for filename in ("SC-012-D0SC04896H-s113.npy", "SC-012-D0SC04896H-s114.npy", "SC-012-D0SC04896H-s117.npy")
            for field in ("row_count_match", "raw_label_exact_match", "membership_partition_match")
        )
        counts_ok = (int(reported.get("SC-012-D0SC04896H-s114.npy", {}).get("n_groups", -1)) == group_counts["nucleophile"]
                     and int(reported.get("SC-012-D0SC04896H-s117.npy", {}).get("n_groups", -1)) == group_counts["substrate"]
                     and int(reported.get("SC-012-D0SC04896H-s113.npy", {}).get("n_groups", -1)) == int(np.unique(_safe_array(ASSETS / "SC-012-D0SC04896H-s113.npy")).size))
        id_status = "PASS" if roles_ok and counts_ok and vector_audit_ok else "FAIL"
        id_details = {"identity_roles_match_released_vectors": roles_ok, "vector_audit_matches_reconstruction": vector_audit_ok,
            "vector_cardinalities": {
            "reaction": int(np.unique(_safe_array(ASSETS / "SC-012-D0SC04896H-s113.npy")).size),
            "nucleophile": group_counts["nucleophile"], "substrate": group_counts["substrate"]}}
    # A protocol-level explanation is supported when the author 354/34 macro averages
    # reproduce the paper's 1.20 substrate and 0.68 nucleophile figures. This checks
    # the protocol, not which direction is easier.
    s = results.get("author_354_rows_34_features/substrate", {})
    n = results.get("author_354_rows_34_features/nucleophile", {})
    matches_paper = (abs(float(s.get("macro_group_mae", math.inf)) - 1.20) <= 0.05
                     and abs(float(n.get("macro_group_mae", math.inf)) - 0.68) <= 0.05)
    status = "PASS" if not failures and id_status == "PASS" and matches_paper and len(refit_checks) >= 4 else "FAIL"
    return {"status": status, "failures": failures, "identity_status": id_status, **id_details,
            "protocol_explanation_reproduces_published_macro_group_mae": matches_paper,
            "author_354_34_substrate": s, "author_354_34_nucleophile": n,
            "representative_independent_refits": refit_checks,
            "all_routes": results,
            "interpretation": "The published direction values are reproduced by macro-averaging one MAE per held-out group on the authors' 354-row, 34-feature LOGO route; row-weighted micro MAE and 443-row routes answer different questions. No direction is a pass condition."}


def _noise_differences() -> list[float]:
    frame = pd.read_csv(ASSETS / "S12_replicate_barrier_pairs.csv")
    return case04_protocol.summarize_replicate_pairs(
        frame["g_kcal_mol"].dropna().astype(str).tolist())["pair_differences_kcal_mol"]


def _verify_multicondition(final_dir: Path, master: pd.DataFrame, train: np.ndarray,
                           X: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    split_path = final_dir / "multicondition_folds.jsonl"
    oof_path = final_dir / "multicondition_oof.csv"
    summary_path = final_dir / "multicondition.json"
    if not all(p.exists() for p in (split_path, oof_path, summary_path)):
        return {"status": "PENDING", "reason": "multi-condition summary, fold splits and OOF predictions are required"}
    split_records = [json.loads(line) for line in split_path.read_text().splitlines() if line.strip()]
    oof = pd.read_csv(oof_path)
    summary = json.loads(summary_path.read_text())
    groups = _safe_array(ASSETS / "SC-012-D0SC04896H-s113.npy")
    counts = pd.Series(groups[train]).value_counts()
    pools = {"all_354": np.asarray(train, dtype=int),
             "single_reaction_only": np.asarray([i for i in train if counts.get(groups[i], 0) == 1], dtype=int)}
    failures: list[str] = []
    route_summary = {}
    pred_required = {"route", "fold", "row_index", "prediction", "absolute_error"}
    if not pred_required <= set(oof.columns):
        return {"status": "FAIL", "reason": "multi-condition OOF rows lack required columns"}
    for route, expected in pools.items():
        records = [r for r in split_records if r.get("route") == route]
        if len(records) != 10:
            failures.append(f"{route}: expected ten explicit folds")
            continue
        seen: list[int] = []
        maes, fold_sizes, row_errors = [], [], []
        for record in records:
            tr = np.asarray(record.get("train_global_indices", []), dtype=int)
            te = np.asarray(record.get("test_global_indices", []), dtype=int)
            fold = int(record.get("fold", -1))
            if len(np.unique(tr)) != len(tr) or len(np.unique(te)) != len(te) or np.intersect1d(tr, te).size:
                failures.append(f"{route}/fold{fold}: duplicate or overlapping train/test indices")
                continue
            if set(np.r_[tr, te].tolist()) != set(expected.tolist()):
                failures.append(f"{route}/fold{fold}: train/test indices do not partition the declared pool")
                continue
            if route == "single_reaction_only" and set(groups[tr].tolist()) & set(groups[te].tolist()):
                failures.append(f"{route}/fold{fold}: a reaction group leaks across the split")
            pred_fold = oof[(oof.route == route) & (oof.fold.astype(int) == fold)].sort_values("row_index")
            if set(pred_fold.row_index.astype(int).tolist()) != set(te.tolist()):
                failures.append(f"{route}/fold{fold}: OOF predictions do not cover the test rows")
                continue
            ordered = pred_fold.set_index("row_index").loc[te]
            err = np.abs(ordered.prediction.to_numpy(float) - y[te])
            if not _v2_allclose(ordered.absolute_error.to_numpy(float), err, rtol=2e-5, atol=2e-5):
                failures.append(f"{route}/fold{fold}: reported row errors do not match public train targets")
            mae = float(err.mean())
            if not math.isclose(mae, float(record.get("mae", math.nan)), rel_tol=2e-5, abs_tol=2e-5):
                failures.append(f"{route}/fold{fold}: fold MAE does not match recomputed errors")
            # Independently refit the model on these exact training rows.
            refit_key = "multi-refit:" + _array_key(X[tr], y[tr], tr, te)
            if refit_key in _MODEL_CACHE:
                refit_prediction = _MODEL_CACHE[refit_key].copy()
            else:
                fitted = estimator().fit(X[tr], y[tr])
                refit_prediction = np.asarray(fitted.predict(X[te]), dtype=float)
                _MODEL_CACHE[refit_key] = refit_prediction.copy()
            match = _v2_allclose(refit_prediction, ordered.prediction.to_numpy(float), rtol=2e-5, atol=2e-5)
            if not match:
                failures.append(f"{route}/fold{fold}: OOF predictions differ from independent fold refit")
            seen.extend(te.tolist())
            maes.append(mae)
            fold_sizes.append(len(te))
            row_errors.extend(err.tolist())
        if sorted(seen) != sorted(expected.tolist()):
            failures.append(f"{route}: test folds are not an exact once-only cover")
        declared = summary.get("all_training_rows" if route == "all_354" else "unique_reaction_only", {})
        mean = float(np.mean(maes)) if maes else math.nan
        sd = float(np.std(maes, ddof=1)) if len(maes) > 1 else math.nan
        sem = float(sd / math.sqrt(len(maes))) if len(maes) > 1 else math.nan
        micro = float(np.mean(row_errors)) if row_errors else math.nan
        for field, value in (("fold_mae_mean", mean), ("fold_mae_sd", sd), ("fold_mae_sem", sem), ("row_micro_mae", micro)):
            if not math.isclose(float(declared.get(field, math.nan)), value, rel_tol=2e-5, abs_tol=2e-5):
                failures.append(f"{route}: summary {field} does not match fold receipts")
        if not _v2_allclose(declared.get("fold_mae", []), maes, rtol=2e-5, atol=2e-5):
            failures.append(f"{route}: summary fold MAEs do not match recomputed values")
        route_summary[route] = {"n_scored": len(seen), "folds": len(maes), "fold_mae_mean": mean,
                                "fold_mae_sem": sem, "row_micro_mae": micro,
                                "independent_fold_refits_match": not any(f.startswith(f"{route}/fold") and "refit" in f for f in failures)}
    return {"status": "PASS" if not failures else "FAIL", "failures": failures,
            "expected_unique_reaction_rows": int(len(pools["single_reaction_only"])),
            "excluded_multi_condition_rows": int(len(train) - len(pools["single_reaction_only"])),
            "routes": route_summary,
            "scope": "Both routes refit inside each fold; only single-reaction route is group-disjoint by construction."}


def _verify_candidate_calibration(final_dir: Path, X: np.ndarray, y: np.ndarray,
                                 train: np.ndarray) -> dict[str, Any]:
    report_path = final_dir / "calibration.json"
    oof_path = final_dir / "calibration_oof.csv"
    if not report_path.exists() or not oof_path.exists():
        return {"status": "PENDING", "reason": "candidate calibration.json and calibration_oof.csv are both required"}
    declared = json.loads(report_path.read_text())
    if int(declared.get("n_rows", -1)) != len(train) or not _is_training_only_oof_scope(declared.get("scope")):
        return {"status": "FAIL", "reason": "candidate calibration must state training-only scope and exact frozen train row count"}
    oof = pd.read_csv(oof_path)
    if set(oof.columns) != {"row_index", "prediction", "sigma"}:
        return {"status": "FAIL", "reason": "OOF file must contain row_index,prediction,sigma only"}
    idx = oof.row_index.to_numpy(int)
    if len(idx) != len(train) or len(np.unique(idx)) != len(idx) or set(idx.tolist()) != set(train.tolist()):
        return {"status": "FAIL", "reason": "OOF rows are not an exact once-only cover of frozen training indices"}
    if not np.isfinite(oof[["prediction", "sigma"]].to_numpy(float)).all() or (oof.sigma.to_numpy(float) <= 0).any():
        return {"status": "FAIL", "reason": "OOF prediction/sigma contains invalid values"}
    # Refit all ten folds, so the reported train-only calibration and posterior sigma
    # are checked from the declared estimator rather than from its summary fields.
    oof_key = "oof-refit:" + _array_key(X[train], y[train], train)
    if oof_key in _MODEL_CACHE:
        expected_p, expected_s = (v.copy() for v in _MODEL_CACHE[oof_key])
    else:
        cv = RepeatedKFold(n_splits=10, n_repeats=1, random_state=1)
        expected_p = np.full(len(train), np.nan)
        expected_s = np.full(len(train), np.nan)
        for tr, te in cv.split(X[train]):
            ytr = y[train[tr]]
            scaler = StandardScaler().fit(ytr.reshape(-1, 1))
            model = _base_estimator().fit(X[train[tr]], scaler.transform(ytr.reshape(-1, 1)).ravel())
            pz, sz = model[-1].predict(model[0].transform(X[train[te]]), return_std=True)
            expected_p[te] = scaler.inverse_transform(pz.reshape(-1, 1)).ravel()
            expected_s[te] = sz * float(scaler.scale_[0])
        _MODEL_CACHE[oof_key] = (expected_p.copy(), expected_s.copy())
    pos = {int(r): i for i, r in enumerate(train)}
    ordered = oof.set_index("row_index").loc[train]
    pred = ordered.prediction.to_numpy(float)
    sigma = ordered.sigma.to_numpy(float)
    p_ok = _v2_allclose(pred, expected_p, rtol=2e-5, atol=2e-5)
    s_ok = _v2_allclose(sigma, expected_s, rtol=2e-5, atol=2e-5)
    err = np.abs(pred - y[train])
    coverage = {f"{z:g}sigma": float(np.mean(err <= z * sigma)) for z in (1, 1.96, 2, 2.576)}
    order = np.argsort(sigma)
    risk = {}
    for k in (.5, .75, .9):
        n = max(1, int(round(k * len(train))))
        risk[f"lowest_sigma_{int(k*100)}pct"] = {"n": n, "mae": float(err[order[:n]].mean())}
    overall = float(err.mean())
    discrepancies = []
    intervals = declared.get("intervals", {})
    for label, value in (("1sigma", coverage["1sigma"]), ("1.96sigma", coverage["1.96sigma"]),
                         ("2sigma", coverage["2sigma"]), ("2.576sigma", coverage["2.576sigma"])):
        stated = intervals.get(label, {}).get("empirical_coverage", math.nan)
        if not math.isclose(float(stated), value, rel_tol=1e-6, abs_tol=1e-6):
            discrepancies.append(f"{label} coverage summary mismatch")
    if not math.isclose(float(declared.get("overall_oof_mae", math.nan)), overall, rel_tol=1e-6, abs_tol=1e-6):
        discrepancies.append("overall OOF MAE summary mismatch")
    declared_risk = declared.get("risk_filter", {})
    for label, stats in risk.items():
        theirs = declared_risk.get(label, {})
        if not math.isclose(float(theirs.get("mae", math.nan)), stats["mae"], rel_tol=1e-6, abs_tol=1e-6):
            discrepancies.append(f"{label} MAE summary mismatch")
    ok = p_ok and s_ok and not discrepancies
    return {"status": "PASS" if ok else "FAIL", "n_rows": len(train),
            "independent_all_fold_refit_prediction_match": bool(p_ok),
            "independent_all_fold_refit_sigma_match": bool(s_ok),
            "recomputed_coverage": coverage, "recomputed_overall_oof_mae": overall,
            "recomputed_risk_filter": risk, "summary_discrepancies": discrepancies}


def _verify_legacy(final_dir: Path | None = None, runtime_root: Path = RUNTIME,
           gold_path: Path = GOLD) -> dict[str, Any]:
    final_dir = final_dir or CASE / "final"
    report: dict[str, Any] = {"schema": "case04-verification/v1", "case_id": "case-04-uncertainty-applicability-domain",
                              "status": "PARTIAL", "checks": []}
    pred_path = final_dir / "predictions_with_uncertainty.csv"
    fals_path = final_dir / "falsification.json"
    domain_path = final_dir / "domain.csv"
    extrap_path = final_dir / "extrapolation.json"
    noise_path = final_dir / "noise_floor.json"
    required = [pred_path, fals_path, domain_path, final_dir / "notes.md", extrap_path,
                noise_path, final_dir / "calibration.json", final_dir / "calibration_oof.csv",
                final_dir / "multicondition.json", final_dir / "multicondition_folds.jsonl",
                final_dir / "run_manifest.json"]
    absent = [p.name for p in required if not p.exists()]
    _item(report, "deliverables", "PASS" if not absent else "PENDING", missing=absent)

    try:
        master, train, test, X, y_visible = _input_arrays()
        split_ok = (len(master) == 443 and len(train) == 354 and len(test) == 89
                    and len(np.unique(train)) == len(train) and len(np.unique(test)) == len(test)
                    and not np.intersect1d(train, test).size
                    and set(np.r_[train, test].tolist()) == set(range(443)))
        masked_ok = np.isnan(y_visible[test]).all() and np.isfinite(y_visible[train]).all()
        _item(report, "frozen_split_partition_and_blinding", "PASS" if split_ok and masked_ok else "FAIL",
              n_rows=len(master), n_train=len(train), n_test=len(test), train_test_disjoint=not bool(np.intersect1d(train, test).size),
              test_targets_masked_in_public_master=bool(masked_ok))
    except Exception as exc:
        _item(report, "frozen_split_partition_and_blinding", "FAIL", reason=f"input validation error: {exc}")
        report["status"] = "PARTIAL"
        return report

    manifest_path = final_dir / "run_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            blind_manifest_ok = manifest.get("execution_mode") == "blind" and manifest.get("grader_answers_read") is False
            output_hashes = manifest.get("output_sha256", {})
            hash_checks = {}
            hash_ok = bool(output_hashes)
            for name, digest in output_hashes.items():
                artifact = final_dir / name
                exists = artifact.is_file()
                actual = hashlib.sha256(artifact.read_bytes()).hexdigest() if exists else None
                matched = bool(actual and actual == str(digest).removeprefix("sha256:"))
                hash_checks[name] = {"exists": exists, "sha256_matches": matched}
                hash_ok = hash_ok and matched
            input_hashes = manifest.get("input_sha256", {})
            input_checks = {}
            input_ok = bool(input_hashes)
            for relpath, digest in input_hashes.items():
                asset = (ROOT / relpath).resolve()
                exists = asset.is_file()
                actual = hashlib.sha256(asset.read_bytes()).hexdigest() if exists else None
                matched = bool(actual and actual == str(digest).removeprefix("sha256:"))
                input_checks[relpath] = {"exists": exists, "sha256_matches": matched}
                input_ok = input_ok and matched
            man_status = "PASS" if blind_manifest_ok and hash_ok and input_ok else "FAIL"
            _item(report, "candidate_runtime_manifest", man_status, blind_mode=blind_manifest_ok,
                  declared_input_hashes_match=bool(input_ok), input_hashes=input_checks,
                  declared_output_hashes_match=bool(hash_ok), output_hashes=hash_checks)
        except Exception as exc:
            _item(report, "candidate_runtime_manifest", "FAIL", reason=f"manifest validation error: {exc}")
    else:
        _item(report, "candidate_runtime_manifest", "PENDING", reason="run_manifest.json missing")

    pred_rows = None
    pred_valid = False
    if pred_path.exists():
        pred_rows = pd.read_csv(pred_path)
        columns_ok = set(pred_rows.columns) == {"row_index", "prediction", "sigma"}
        idx = pred_rows["row_index"].to_numpy(int) if "row_index" in pred_rows else np.array([], dtype=int)
        pred_ok = (columns_ok and len(idx) == len(test) and len(np.unique(idx)) == len(idx)
                   and set(idx.tolist()) == set(test.tolist())
                   and np.isfinite(pred_rows[["prediction", "sigma"]].to_numpy(float)).all()
                   and (pred_rows["sigma"].to_numpy(float) > 0).all())
        _item(report, "prediction_rows_and_sigma", "PASS" if pred_ok else "FAIL",
              expected_test_rows=len(test), submitted_rows=len(pred_rows), exact_test_index_match=bool(set(idx.tolist()) == set(test.tolist())),
              submitted_truth_column=bool("truth" in pred_rows.columns))
        pred_valid = bool(pred_ok)
        if pred_ok:
            ordered = pred_rows.sort_values("row_index")
            pred_idx = ordered["row_index"].to_numpy(int)
            expected, expected_sigma = _independent_prediction(X, y_visible, train, pred_idx)
            match_p = _v2_allclose(ordered["prediction"].to_numpy(float), expected, rtol=2e-5, atol=2e-5)
            match_s = _v2_allclose(ordered["sigma"].to_numpy(float), expected_sigma, rtol=2e-5, atol=2e-5)
            variable = float(np.std(ordered["sigma"].to_numpy(float))) > 1e-8
            _item(report, "gpr_refit_prediction_and_posterior_sigma", "PASS" if match_p and match_s and variable else "FAIL",
                  estimator="StandardScaler -> GaussianProcessRegressor(ConstantKernel*Matern(nu=1.5)+WhiteKernel), target StandardScaler",
                  prediction_matches_refit=bool(match_p), sigma_matches_predict_return_std=bool(match_s),
                  sigma_is_nonconstant=bool(variable), max_abs_prediction_delta=float(np.max(np.abs(ordered["prediction"].to_numpy(float)-expected))),
                  max_abs_sigma_delta=float(np.max(np.abs(ordered["sigma"].to_numpy(float)-expected_sigma))))

    try:
        false_res = _verify_falsification(fals_path, X, y_visible, train)
    except Exception as exc:
        false_res = {"status": "FAIL", "reason": f"falsification validation error: {exc}"}
    _item(report, "falsification_full_permutation_distribution", false_res.pop("status"), **false_res)

    try:
        train_calibration = _verify_candidate_calibration(final_dir, X, y_visible, train)
    except Exception as exc:
        train_calibration = {"status": "FAIL", "reason": f"candidate calibration validation error: {exc}"}
    _item(report, "candidate_train_oof_calibration", train_calibration.pop("status"), **train_calibration)

    # The answer file is opened only here, after checking the submitted predictions and
    # never copied into any candidate-facing artifact.
    calibration: dict[str, Any] = {"schema": "case04-calibration-grader/v1", "n_test": len(test), "status": "PENDING"}
    if pred_valid and pred_rows is not None and set(pred_rows.columns) == {"row_index", "prediction", "sigma"}:
        answers = pd.read_csv(gold_path)
        if set(answers.columns) != {"row_index", "exp_activation_energy"}:
            _item(report, "hidden_answer_join", "FAIL", reason="unexpected answer schema")
        else:
            merged = pred_rows.merge(answers, on="row_index", how="outer", validate="one_to_one", indicator=True)
            answer_ok = len(merged) == len(test) and (merged["_merge"] == "both").all() and merged["exp_activation_energy"].notna().all()
            if not answer_ok:
                _item(report, "hidden_answer_join", "FAIL", reason="prediction indices do not exactly join the frozen answer set")
            else:
                err = np.abs(merged["prediction"].to_numpy(float) - merged["exp_activation_energy"].to_numpy(float))
                sigma = merged["sigma"].to_numpy(float)
                coverage = {f"within_{z:g}_sigma": float(np.mean(err <= z * sigma)) for z in (1.0, 1.96, 2.0, 2.576)}
                order = np.argsort(sigma)
                nlow = max(1, int(round(0.5 * len(err))))
                low_mae = float(err[order[:nlow]].mean())
                overall_mae = float(err.mean())
                risk_improved = bool(low_mae < overall_mae)
                coverage_in_registered_benchmark_band = bool(0.60 <= coverage["within_2_sigma"] <= 1.0)
                calibration = {"schema": "case04-calibration-grader/v1", "n_test": len(test),
                               "interval_multipliers": [1.0, 1.96, 2.0, 2.576], "coverage": coverage,
                               "overall_mae": overall_mae, "risk_filter": {"subset": "lowest_sigma_50_percent",
                               "n": nlow, "mae": low_mae, "lower_than_overall": risk_improved},
                               "two_sigma_coverage_in_registered_benchmark_band": coverage_in_registered_benchmark_band,
                               "status": "PASS"}
                _item(report, "hidden_answer_join", "PASS", exact_index_join=True, answer_count=len(merged))
                _item(report, "coverage_and_risk_filter", calibration["status"],
                      coverage=coverage, overall_mae=overall_mae, low_sigma_50pct_mae=low_mae,
                      sigma_thresholds_distinguished=True)
    # Keep grader-only frozen-test metrics beside the report. Candidate calibration.json
    # remains an auditable submission and is never overwritten by hidden-truth scoring.
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "grader_calibration.json").write_text(json.dumps(calibration, indent=2) + "\n")

    if domain_path.exists():
      try:
        domain = pd.read_csv(domain_path)
        required_domain = {"row_index", "nearest_train_distance", "training_loo_q95_cutoff", "out_of_domain", "rule"}
        domain_ok = set(domain.columns) >= required_domain and set(domain["row_index"].astype(int)) == set(test.tolist()) and len(domain) == len(test)
        if domain_ok:
            mu = X[train].mean(axis=0)
            scale = X[train].std(axis=0, ddof=0)
            scale[scale == 0] = 1.0
            ztr = (X[train] - mu) / scale
            sorted_domain = domain.sort_values("row_index")
            zte = (X[sorted_domain["row_index"].to_numpy(int)] - mu) / scale
            dtr = np.sqrt(((ztr[:, None, :] - ztr[None, :, :]) ** 2).mean(axis=2))
            np.fill_diagonal(dtr, np.inf)
            cutoff = float(np.quantile(dtr.min(axis=1), .95))
            dist = np.sqrt(((zte[:, None, :] - ztr[None, :, :]) ** 2).mean(axis=2)).min(axis=1)
            supplied = sorted_domain
            dist_ok = _v2_allclose(supplied["nearest_train_distance"].to_numpy(float), dist, rtol=1e-6, atol=1e-6)
            cutoff_ok = _v2_allclose(supplied["training_loo_q95_cutoff"].to_numpy(float), cutoff, rtol=1e-6, atol=1e-6)
            flags = supplied["out_of_domain"].astype(str).str.lower().isin(["true", "1"]).to_numpy()
            flag_ok = np.array_equal(flags, dist > cutoff)
            domain_status = "PASS" if dist_ok and cutoff_ok and flag_ok else "FAIL"
            hits = int((dist > cutoff).sum())
            _item(report, "domain_rule_and_hit_counts", domain_status, rule_recomputed=True,
                  nearest_neighbor_distances_match=bool(dist_ok), train_loo_q95_cutoff_matches=bool(cutoff_ok),
                  out_of_domain_flags_match=bool(flag_ok), out_of_domain_test_rows=hits, threshold=cutoff)
        else:
            _item(report, "domain_rule_and_hit_counts", "FAIL", reason="missing required columns or incomplete test coverage")
      except Exception as exc:
        _item(report, "domain_rule_and_hit_counts", "FAIL", reason=f"domain validation error: {exc}")
    else:
        _item(report, "domain_rule_and_hit_counts", "PENDING", reason="domain.csv missing")

    try:
        protocol = _protocol_contrast(runtime_root)
    except Exception as exc:
        protocol = {"status": "FAIL", "reason": f"protocol receipt validation error: {exc}"}
    # These are repo-side reference witnesses used to adjudicate the paper conflict.
    # They are reported separately and cannot substitute for candidate deliverables.
    _item(report, "protocol_reference_witness_only", protocol.pop("status"), **protocol)
    expected_diffs = [0.08, 0.10, 0.55, 1.63]

    if extrap_path.exists():
        candidate_extrap = json.loads(extrap_path.read_text())
        witness_summary = protocol.get("all_routes", {})
        cand_results = candidate_extrap.get("results", candidate_extrap.get("directions", {}))
        expected_routes = {"substrate": witness_summary.get("author_354_rows_34_features/substrate", {}),
                           "nucleophile": witness_summary.get("author_354_rows_34_features/nucleophile", {})}
        route_payload = {role: cand_results.get(f"author_354_rows_34_features/{role}", cand_results.get(role, {}))
                         for role in expected_routes}
        complete_extrap = all(isinstance(route_payload.get(r), dict) for r in expected_routes)
        results_match = complete_extrap
        if complete_extrap:
            for role, reference in expected_routes.items():
                item = route_payload[role]
                for field in ("n_groups", "n_scored", "macro_group_mae", "macro_group_sem", "micro_row_mae"):
                    if field not in item or field not in reference or not math.isclose(float(item[field]), float(reference.get(field, math.nan)), rel_tol=1e-4, abs_tol=0.01):
                        results_match = False
        execution_scope_ok = candidate_extrap.get("execution_scope") == "candidate_local_execution"
        explanation = str(candidate_extrap.get("explanation", candidate_extrap.get("interpretation", candidate_extrap.get("protocol_explanation", "")))).lower()
        explanation_ok = ("macro" in explanation and
                          ("micro" in explanation or "weighting each row equally" in explanation or "row-weighted" in explanation))
        evidence_files = candidate_extrap.get("evidence_files", {})
        evidence_hashes = candidate_extrap.get("evidence_sha256", {})
        evidence_ok = False
        evidence_checked = []
        if isinstance(evidence_files, dict) and isinstance(evidence_hashes, dict) and evidence_files:
            evidence_ok = True
            for label, raw_path in evidence_files.items():
                source = (ROOT / str(raw_path)).resolve()
                expected_hash = evidence_hashes.get(label)
                exists = source.is_file()
                digest = hashlib.sha256(source.read_bytes()).hexdigest() if exists else None
                matched = bool(expected_hash and digest == str(expected_hash).removeprefix("sha256:"))
                evidence_checked.append({"label": label, "exists": exists, "sha256_matches": matched})
                evidence_ok = evidence_ok and matched
        route_status = "PASS" if complete_extrap and results_match and execution_scope_ok and explanation_ok and evidence_ok else "PENDING"
        _item(report, "candidate_extrapolation_report", route_status,
              both_directions_reported=complete_extrap, all_macro_micro_uncertainty_metrics_match_receipts=bool(results_match),
              candidate_local_execution_scope=bool(execution_scope_ok), macro_vs_micro_protocol_explained=bool(explanation_ok),
              evidence_files_checked=evidence_checked, evidence_hashes_match=bool(evidence_ok),
              no_directional_ordering_as_pass_gate=True,
              note="Candidate report must carry both directions, counts, SEM, micro MAE and evidence hashes; direction ordering is never an acceptance condition.")
    else:
        _item(report, "candidate_extrapolation_report", "PENDING", reason="candidate final/extrapolation.json missing")

    try:
        multi_result = _verify_multicondition(final_dir, master, train, X, y_visible)
    except Exception as exc:
        multi_result = {"status": "FAIL", "reason": f"multi-condition validation error: {exc}"}
    _item(report, "candidate_multi_condition_removal", multi_result.pop("status"), **multi_result)

    if noise_path.exists():
        noise = json.loads(noise_path.read_text())
        vals = noise.get("pair_differences_kcal_mol", noise.get("differences_kcal_mol", noise.get("observed_pair_differences", [])))
        try:
            candidate_diffs = [float(x) for x in vals]
        except (TypeError, ValueError):
            candidate_diffs = []
        candidate_noise_ok = len(candidate_diffs) == 4 and _v2_allclose(sorted(candidate_diffs), sorted(expected_diffs), atol=0.02)
        precision = noise.get("claimed_precision_kcal_mol", noise.get("target_precision_claim"))
        reason = str(noise.get("below_noise_floor_justification", noise.get("reasoning", ""))).strip()
        claim_text = str(precision or "").lower()
        precision_ok = (precision is None or "not_claimed_below_0.1" in claim_text
                        or (isinstance(precision, (int, float)) and float(precision) >= 0.1)
                        or bool(reason and ("0.1" in reason or "noise floor" in reason.lower())))
        _item(report, "candidate_noise_floor_interpretation", "PASS" if candidate_noise_ok and precision_ok else "FAIL",
              observed_pair_differences=candidate_diffs, precision_claim=precision,
              below_0_1_justification_present=bool(reason), candidate_report_matches_pairs=bool(candidate_noise_ok))
    else:
        _item(report, "candidate_noise_floor_interpretation", "PENDING", reason="candidate final/noise_floor.json missing")

    try:
        diffs = _noise_differences()
    except Exception as exc:
        diffs = []
        noise_error = str(exc)
    else:
        noise_error = None
    noise_ok = len(diffs) == len(expected_diffs) and _v2_allclose(sorted(diffs), sorted(expected_diffs), atol=0.02)
    _item(report, "replicate_reference_values", "PASS" if noise_ok else "FAIL", observed_pair_differences=diffs,
          reason=noise_error,
          expected_pair_differences=expected_diffs, tolerance_kcal_mol=0.02)

    statuses = [c["status"] for c in report["checks"]]
    report["status"] = "FAIL" if "FAIL" in statuses else ("PASS" if statuses and all(v == "PASS" for v in statuses) else "PARTIAL")
    report["verification_coverage"] = "COMPLETE"
    report["verification_scope"] = "supported_local_GPR_protocol"
    report["execution_checks_complete"] = bool(statuses and all(v != "PENDING" for v in statuses))
    report["qualification_granted"] = False
    return report


_V2_OUTPUTS = {
    "protocol.json", "protocol_binding.json", "predictions_with_uncertainty.csv", "calibration_folds.jsonl",
    "calibration_oof.csv", "calibration.json", "permutation_folds.jsonl", "permutation_predictions.csv",
    "falsification.json", "logo_folds.jsonl", "logo_predictions.csv", "extrapolation.json",
    "multicondition_folds.jsonl", "multicondition_oof.csv", "multicondition.json", "domain.csv",
    "noise_floor.json", "notes.md", "run_manifest.json",
}
_V2_REQUIRED_OUTPUTS = {"protocol.json", "predictions_with_uncertainty.csv", "permutation_predictions.csv",
    "logo_predictions.csv", "multicondition_oof.csv", "domain.csv", "noise_floor.json", "notes.md"}
_V2_RTOL = 2e-5
_V2_ATOL = 2e-5
_V2_REFIT_CACHE: dict[str, Any] = {}


class OutputFormatError(ValueError):
    """Invalid or ambiguous candidate output representation."""


class ScientificMismatch(ValueError):
    """Well-formed observations contradict an independently computed value."""


_OUTPUT_STAGES = {
    "protocol.json": "protocol_schema", "protocol_binding.json": "protocol_binding",
    "calibration_folds.jsonl": "candidate_train_oof_calibration", "calibration_oof.csv": "candidate_train_oof_calibration",
    "calibration.json": "candidate_train_oof_calibration", "falsification.json": "falsification_summary",
    "permutation_folds.jsonl": "falsification_distribution_refits", "permutation_predictions.csv": "falsification_distribution_refits",
    "logo_folds.jsonl": "candidate_extrapolation_report", "logo_predictions.csv": "candidate_extrapolation_report",
    "extrapolation.json": "candidate_extrapolation_report", "multicondition_folds.jsonl": "candidate_multi_condition_removal",
    "multicondition_oof.csv": "candidate_multi_condition_removal", "multicondition.json": "candidate_multi_condition_removal",
    "domain.csv": "domain_rule_and_hit_counts", "noise_floor.json": "candidate_noise_floor_interpretation",
    "predictions_with_uncertainty.csv": "gpr_refit_prediction_and_posterior_sigma",
}


def _output_error(message, label=None):
    error = OutputFormatError(message)
    if label is not None:
        error.stage = _OUTPUT_STAGES.get(Path(str(label).split(":", 1)[0]).name)
    return error


def _stage_call(stage, function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (OutputFormatError, ScientificMismatch, NotImplementedError, ValueError) as exc:
        if not getattr(exc, "stage", None): exc.stage = stage
        raise


class ObservedFloat(float):
    def __new__(cls, literal):
        value = super().__new__(cls, literal)
        value.literal = literal
        return value


def _v2_decode(text, label):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out: raise _output_error(f"{label}: duplicate JSON key {key!r}", label)
            out[key] = value
        return out
    def invalid(value):
        raise _output_error(f"{label}: nonfinite JSON number {value}", label)
    try:
        value = json.loads(text, object_pairs_hook=unique, parse_float=ObservedFloat, parse_constant=invalid)
    except json.JSONDecodeError as exc:
        raise _output_error(f"{label}: invalid JSON: {exc}", label) from exc
    _v2_finite_tree(value, label)
    return value


def _v2_json(path: Path):
    try: text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc: raise _output_error(f"{path.name}: {exc}", path.name) from exc
    return _v2_decode(text, path.name)


def _v2_jsonl(path: Path):
    rows = []
    try: text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc: raise _output_error(f"{path.name}: {exc}", path.name) from exc
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        row = _v2_json_line(line, path.name, line_no)
        if not isinstance(row, dict): raise _output_error(f"{path.name}:{line_no} must be an object", path.name)
        scope = {"route", "fold", "schema", "protocol_digest"}
        if path.name == "logo_folds.jsonl": scope |= {"group_role", "group_id"}
        if path.name == "permutation_folds.jsonl": scope.add("permutation_id")
        outside = ({"route", "fold", "schema", "protocol_digest", "group_role", "group_id", "row_index", "permutation_id"} & set(row)) - scope
        if outside: raise _output_error(f"{path.name}:{line_no}: selectors outside fold scope: {sorted(outside)}", path.name)
        for key in ("fold", "group_id", "permutation_id"):
            if key in row: row[key] = _v2_int(row[key], f"{path.name}:{line_no}.{key}")
        for key in ("train_global_indices", "test_global_indices"):
            if key in row: row[key] = _v2_indices(row[key], f"{path.name}:{line_no}.{key}")
        rows.append(row)
    return rows


def _v2_json_line(line: str, name: str, line_no: int):
    return _v2_decode(line, f"{name}:{line_no}")


def _v2_finite_tree(value, name):
    if isinstance(value, dict):
        for key, item in value.items():
            _v2_finite_tree(item, f"{name}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _v2_finite_tree(item, f"{name}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise OutputFormatError(f"{name} contains a non-finite number")


def _v2_int(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _output_error(f"{name} must be a JSON integer value")
    number = Decimal(value.literal if isinstance(value, ObservedFloat) else str(value))
    if not number.is_finite() or number != number.to_integral_value() or not -(2**63) <= number < 2**63:
        raise _output_error(f"{name} must be an exact finite integer in range")
    return int(number)


def _v2_exact_keys(value, allowed, name):
    """Project required observations; annotations do not redefine computation."""
    if not isinstance(value, dict):
        raise _output_error(f"{name} must be an object", name)
    missing = set(allowed) - set(value)
    if missing:
        raise _output_error(f"{name} is missing required fields {sorted(missing)}", name)
    selectors = {"route", "group_role", "group_id", "fold", "permutation_id", "row_index", "schema", "protocol_digest"}
    optional_bindings = {"permutation_id", "protocol_digest"} if "permutation_results[" in name else set()
    outside = (set(value) - set(allowed) - optional_bindings) & selectors
    if outside:
        raise _output_error(f"{name}: selectors outside this scope: {sorted(outside)}", name)
    known_quantities = {"mae", "r2", "absolute_error", "prediction", "sigma", "score", "threshold",
                        "precision_claim", "precision_justification", "claimed_bound_kcal_mol", "confidence",
                        "train_global_indices", "test_global_indices"}
    outside_quantities = (set(value) - set(allowed)) & known_quantities
    if outside_quantities:
        raise NotImplementedError(f"{name}: scientific assertions outside this scope: {sorted(outside_quantities)}")
    undeclared_computation = (set(value) - set(allowed)) & {
        "model", "preprocessing", "cv", "parameter_grid", "kernel", "optimizer",
        "feature_scaling", "target_scaling", "rule_id", "ad", "permutation", "logo", "multicondition"
    }
    if undeclared_computation:
        raise NotImplementedError(f"{name}: computational assertions are not defined in this output: {sorted(undeclared_computation)}")
    return value


def _v2_collection_keys(value, expected, name):
    _v2_exact_keys(value, expected, name)
    extra = set(value) - set(expected) - {"note", "description", "provenance", "metadata"}
    if extra: raise _output_error(f"{name}: unexpected collection identities {sorted(extra)}", name)
    return value


def _v2_allclose(a, b, *, rtol=1e-5, atol=1e-8):
    try:
        aa, bb = np.asarray(a), np.asarray(b)
        if aa.shape != bb.shape:
            return False
        return bool(np.allclose(aa, bb, rtol=rtol, atol=atol))
    except (TypeError, ValueError):
        return False


def _protected_answer_preflight(gold_path: Path, test_indices: np.ndarray):
    """Validate protected grader custody and the full frozen answer table before any fit."""
    local_refs = Path(__file__).resolve().parent.parent / "refs.json"
    refs_path = local_refs if local_refs.is_file() else CASE / "tests/refs.json"
    try:
        if refs_path.is_symlink() or not refs_path.is_file():
            return "ENVIRONMENT_ERROR", "trusted Case04 refs.json is missing or unsafe", None
        refs = _v2_json(refs_path)
        pinned = refs.get("protected_answers_sha256")
        if isinstance(pinned, str) and pinned.startswith("sha256:"):
            pinned = pinned[7:]
        if not isinstance(pinned, str) or not re.fullmatch(r"[0-9a-f]{64}", pinned):
            return "ENVIRONMENT_ERROR", "trusted refs.json has no valid protected-answer SHA-256 pin", None
    except Exception:
        return "ENVIRONMENT_ERROR", "trusted refs.json could not be read or parsed", None

    answer_path = Path(gold_path)
    if answer_path.is_symlink():
        return "GRADER_INPUT_ERROR", "protected answer path is a symlink", None
    try:
        answer_stat = answer_path.lstat()
    except FileNotFoundError:
        return "NEEDS_PROTECTED_ANSWERS", "protected answer file is unavailable", None
    except OSError:
        return "GRADER_INPUT_ERROR", "protected answer file could not be inspected", None
    if not stat.S_ISREG(answer_stat.st_mode):
        return "GRADER_INPUT_ERROR", "protected answer path is not a regular file", None
    if stat.S_IMODE(answer_stat.st_mode) & 0o444 == 0 or not os.access(answer_path, os.R_OK):
        return "GRADER_INPUT_ERROR", "protected answer file is not readable by the verifier", None
    try:
        raw = answer_path.read_bytes()
    except OSError:
        return "GRADER_INPUT_ERROR", "protected answer file could not be read", None
    actual = hashlib.sha256(raw).hexdigest()
    if actual != pinned:
        return "GRADER_INPUT_ERROR", "protected answer bytes do not match the trusted SHA-256 pin", None
    try:
        answers = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
        if list(answers.columns) != ["row_index", "exp_activation_energy"]:
            return "GRADER_INPUT_ERROR", "protected answer table has an unexpected schema", None
        raw_idx = pd.to_numeric(answers["row_index"], errors="coerce").to_numpy(float)
        raw_y = pd.to_numeric(answers["exp_activation_energy"], errors="coerce").to_numpy(float)
    except Exception:
        return "GRADER_INPUT_ERROR", "protected answer table is unreadable or malformed", None
    expected = np.asarray(test_indices, dtype=int).reshape(-1)
    if (len(answers) != 89 or len(raw_idx) != len(expected)
            or not np.isfinite(raw_idx).all()
            or not np.equal(raw_idx, np.floor(raw_idx)).all()
            or not np.isfinite(raw_y).all()):
        return "GRADER_INPUT_ERROR", "protected answers must contain 89 finite rows and targets", None
    indices = raw_idx.astype(int)
    if len(set(indices.tolist())) != 89 or set(indices.tolist()) != set(expected.tolist()):
        return "GRADER_INPUT_ERROR", "protected answer indices are not an exact unique cover of frozen s118", None
    answers["row_index"] = indices
    answers["exp_activation_energy"] = raw_y
    return "PASS", actual, answers


def _v2_finite(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _output_error(f"{name} must be finite numeric", name)
    try:
        number = float(value)
    except OverflowError as exc:
        raise _output_error(f"{name} must be finite numeric", name) from exc
    if not math.isfinite(number):
        raise _output_error(f"{name} must be finite numeric", name)
    return number


def _v2_numbers(value, name):
    if not isinstance(value, list): raise _output_error(f"{name} must be a numeric array")
    return [_v2_finite(item, f"{name}[{i}]") for i, item in enumerate(value)]


def _v2_indices(value, name: str) -> list[int]:
    if not isinstance(value, list): raise _output_error(f"{name} must be an integer list")
    out = [_v2_int(v, name) for v in value]
    if len(set(out)) != len(out): raise _output_error(f"{name} contains duplicate rows")
    return out


_SELECTOR_COLUMNS = {"route", "group_role", "group_id", "fold", "permutation_id"}
_HELDOUT_ANSWER_COLUMNS = {"truth", "truths", "target", "targets", "absolute_error", "error", "errors",
                           "residual", "residuals", "exp_activation_energy", "true_experimental_barrier"}


def _v2_read_predictions(path: Path, required: set[str]):
    # Inspect the raw header before pandas can mangle duplicate column names.
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream); header = next(reader)
            if len(header) != len(set(header)):
                raise _output_error(f"{path.name} contains duplicate CSV headers", path.name)
            minimum = {
                "permutation_predictions.csv": {"permutation_id", "row_index", "prediction", "sigma"},
                "logo_predictions.csv": {"group_role", "row_index", "prediction", "sigma"},
                "multicondition_oof.csv": {"row_index", "prediction", "sigma"},
                "domain.csv": {"row_index", "score", "out_of_domain"},
            }.get(path.name, required)
            if not minimum.issubset(header):
                raise _output_error(f"{path.name} missing columns {sorted(minimum-set(header))}", path.name)
            if any(len(row) != len(header) for row in reader):
                raise _output_error(f"{path.name} contains a row with incorrect column count", path.name)
        frame = pd.read_csv(path, dtype={name: str for name in ("row_index", "fold", "permutation_id", "group_id") if name in header})
    except (OSError, UnicodeError, csv.Error, StopIteration, pd.errors.ParserError) as exc:
        raise _output_error(f"{path.name}: unreadable CSV: {exc}", path.name) from exc
    extra_selectors = (_SELECTOR_COLUMNS & set(frame)) - required
    # OOF may carry its known row-to-fold binding, which is checked at the join below.
    if path.name == "calibration_oof.csv": extra_selectors -= {"route", "fold"}
    if extra_selectors:
        raise _output_error(f"{path.name}: selectors outside this scope: {sorted(extra_selectors)}", path.name)
    if path.name in {"predictions_with_uncertainty.csv", "domain.csv"} and _HELDOUT_ANSWER_COLUMNS & set(frame):
        raise _output_error(f"{path.name}: held-out answer/error columns are not permitted", path.name)
    for col in ("row_index", "fold", "permutation_id", "group_id"):
        if col not in frame: continue
        integers = []
        for raw in frame[col]:
            try: number = Decimal(str(raw))
            except InvalidOperation as exc:
                raise _output_error(f"{path.name}.{col} must contain integers", path.name) from exc
            if (not number.is_finite() or number != number.to_integral_value()
                    or number < -(2**63) or number >= 2**63):
                raise _output_error(f"{path.name}.{col} must contain exact finite integers", path.name)
            integers.append(int(number))
        frame[col] = np.asarray(integers, dtype=np.int64)
    for col in ("prediction", "sigma", "absolute_error", "score", "threshold"):
        if col in frame:
            if pd.api.types.is_bool_dtype(frame[col]): raise _output_error(f"{path.name}.{col} cannot be boolean", path.name)
            try: values = pd.to_numeric(frame[col], errors="raise").to_numpy(float)
            except (ValueError, TypeError) as exc: raise _output_error(f"{path.name}.{col} must be numeric", path.name) from exc
            if not np.isfinite(values).all(): raise _output_error(f"{path.name}.{col} must be finite", path.name)
            frame[col] = values
    optional_science = ({"mae", "r2", "rule_id", "score", "threshold", "prediction", "sigma"} & set(frame)) - required
    if optional_science:
        raise NotImplementedError(f"{path.name}: unsupported scientific assertions in this table: {sorted(optional_science)}")
    return frame


def _table_binding(frame, digest, label):
    if "protocol_digest" in frame and not (frame.protocol_digest.astype(str) == digest).all():
        raise _output_error(f"{label}: optional protocol_digest conflicts with protocol.json", label)
    if "schema" in frame:
        raise NotImplementedError(f"{label}: no CSV schema assertion is defined for this output")
    return frame


_CSV_REQUIRED_OBSERVATIONS = {
    "predictions_with_uncertainty.csv": {"row_index", "prediction", "sigma"},
    "calibration_oof.csv": {"row_index", "prediction", "sigma"},
    "permutation_predictions.csv": {"route", "fold", "permutation_id", "row_index", "prediction", "sigma", "absolute_error"},
    "logo_predictions.csv": {"route", "group_role", "group_id", "fold", "row_index", "prediction", "sigma", "absolute_error"},
    "multicondition_oof.csv": {"route", "fold", "row_index", "prediction", "sigma", "absolute_error"},
    "domain.csv": {"row_index", "score", "threshold", "out_of_domain", "rule_id"},
}


def _v2_output_surface(final_dir):
    """Check representation before unsupported computation can obscure invalid output."""
    reviews = []
    for name in sorted(_V2_OUTPUTS):
        path = final_dir / name
        if not path.is_file(): continue
        try:
            if path.suffix == ".json":
                if not isinstance(_v2_json(path), dict): raise _output_error(f"{name} must be an object", name)
            elif path.suffix == ".jsonl": _v2_jsonl(path)
            elif name in _CSV_REQUIRED_OBSERVATIONS: _v2_read_predictions(path, _CSV_REQUIRED_OBSERVATIONS[name])
        except NotImplementedError as exc:
            exc.stage = _OUTPUT_STAGES.get(name)
            reviews.append(exc)
    if reviews: raise reviews[0]


def _permutation_result_rows(raw, count, digest=None):
    if not isinstance(raw, list) or len(raw) != count:
        raise _output_error("permutation_results must contain one metric pair per null draw", "falsification.json")
    for i, row in enumerate(raw):
        _v2_exact_keys(row, {"r2", "mae"}, f"falsification.json:permutation_results[{i}]")
        outside = {"route", "fold", "row_index", "group_role", "group_id", "schema"} & set(row)
        if outside: raise _output_error(f"permutation_results[{i}]: selectors outside paired-null scope: {sorted(outside)}", "falsification.json")
        if "protocol_digest" in row and row["protocol_digest"] != digest:
            raise _output_error(f"permutation_results[{i}]: conflicting protocol digest", "falsification.json")
        _v2_finite(row["r2"], f"permutation_results[{i}].r2")
        _v2_finite(row["mae"], f"permutation_results[{i}].mae")
    has_ids = ["permutation_id" in row for row in raw]
    if any(has_ids) and not all(has_ids):
        raise _output_error("permutation_results cannot mix positional and ID bindings", "falsification.json")
    if not any(has_ids): return raw
    ids = [_v2_int(row["permutation_id"], "permutation_results.permutation_id") for row in raw]
    if len(set(ids)) != count or set(ids) != set(range(1, count + 1)):
        raise _output_error("permutation_results IDs must uniquely cover 1..count", "falsification.json")
    return [row for _, row in sorted(zip(ids, raw))]



def _v2_cached_fit(protocol, xtr, ytr, xte, fit_cache):
    h = hashlib.sha256()
    h.update(case04_protocol.canonical_protocol_digest(protocol).encode())
    for arr in (np.asarray(xtr, float), np.asarray(ytr, float), np.asarray(xte, float)):
        a = np.ascontiguousarray(arr)
        h.update(str(a.shape).encode()); h.update(a.tobytes())
    key = h.hexdigest()
    if key not in fit_cache:
        fit_cache[key] = case04_protocol.fit_predict_with_sigma(protocol, xtr, ytr, xte)
    return tuple(v.copy() for v in fit_cache[key])


def _summary_observations(value, required, optional, name, schema=None, digest=None):
    _v2_exact_keys(value, required | (set(value) & optional if isinstance(value, dict) else set()), name)
    if "schema" in value and value["schema"] != schema: raise _output_error(f"{name}: conflicting optional schema", name)
    if "protocol_digest" in value and value["protocol_digest"] != digest: raise _output_error(f"{name}: conflicting optional protocol_digest", name)
    return value


def _reported_identities(value, allowed, name):
    if not isinstance(value, dict): raise _output_error(f"{name} must be an object", name)
    unexpected = set(value) - set(allowed) - {"note", "description", "provenance", "metadata"}
    if unexpected: raise _output_error(f"{name}: unknown scientific identities {sorted(unexpected)}", name)
    return set(value) & set(allowed)


def _declared_cv_folds(protocol, digest, rows, route, permutation_id=None):
    records = []
    for fid, (tr, te) in enumerate(case04_protocol.make_cv_splits(protocol, len(rows))):
        record = {"schema": "case04-fold/v2", "protocol_digest": digest, "route": route, "fold": fid,
                  "train_global_indices": np.asarray(rows)[tr].tolist(), "test_global_indices": np.asarray(rows)[te].tolist()}
        if permutation_id is not None: record["permutation_id"] = permutation_id
        records.append(record)
    return records


def _folds_or_declared(path, declared):
    return _v2_jsonl(path) if path.is_file() else declared


def _cv_prediction_bindings(frame, protocol, rows, route):
    frame = frame.copy()
    membership = {int(row): fid for fid, (_, te) in enumerate(case04_protocol.make_cv_splits(protocol, len(rows))) for row in np.asarray(rows)[te]}
    if not set(frame.row_index).issubset(membership): raise OutputFormatError(f"{route}: prediction row outside its population")
    expected = frame.row_index.map(membership)
    if "fold" in frame and not (frame.fold == expected).all(): raise OutputFormatError(f"{route}: supplied fold contradicts protocol split")
    frame["fold"] = expected
    if "route" in frame and not (frame.route == route).all(): raise OutputFormatError(f"{route}: supplied route contradicts its table scope")
    frame["route"] = route
    return frame


def _logo_prediction_bindings(frame, protocol, rows, groups):
    frame = frame.copy();parts = []
    for role in protocol["logo"]["group_roles"]:
        part = frame[frame.group_role == role].copy()
        membership = {int(row): (fid, gid) for fid, (_, te, gid) in enumerate(case04_protocol.make_logo_splits(rows, groups[role])) for row in te}
        if not set(part.row_index).issubset(membership): raise OutputFormatError(f"LOGO {role}: row outside frozen training population")
        for key, position in (("fold", 0), ("group_id", 1)):
            expected = part.row_index.map(lambda row: membership[row][position])
            if key in part and not (part[key] == expected).all(): raise OutputFormatError(f"LOGO {role}: supplied {key} contradicts released groups")
            part[key] = expected
        parts.append(part)
    if set(frame.group_role) != set(protocol["logo"]["group_roles"]): raise OutputFormatError("LOGO missing or unknown role")
    frame = pd.concat(parts, ignore_index=True)
    if "route" in frame and not (frame.route == "logo").all(): raise OutputFormatError("LOGO route mismatch")
    frame["route"] = "logo"
    return frame


def _v2_permutation_structure(final_dir: Path, protocol: dict[str, Any], digest: str,
                              rows: np.ndarray) -> dict[str, Any]:
    """Check draw/fold identities before any model refits; ID0 is identity only."""
    count = protocol["permutation"]["count"]
    expected_ids = list(range(count + 1))
    expected_folds = list(range(protocol["cv"]["n_splits"]))
    issues = []
    try:
        records = _folds_or_declared(final_dir / "permutation_folds.jsonl", [r for pid in expected_ids for r in _declared_cv_folds(protocol, digest, rows, "falsification", pid)])
        actual_ids = sorted({_v2_int(v.get("permutation_id"), "permutation_id") for v in records})
        expected_membership = {
            fid: (set(np.asarray(rows)[tr].tolist()), set(np.asarray(rows)[te].tolist()))
            for fid, (tr, te) in enumerate(case04_protocol.make_cv_splits(protocol, len(rows)))
        }
        duplicate_pairs = []
        for pid in actual_ids:
            fids = [_v2_int(v.get("fold"), "fold") for v in records if v.get("permutation_id") == pid]
            if len(fids) != len(set(fids)):
                duplicate_pairs.append(pid)
            if sorted(fids) != expected_folds:
                issues.append({"field": "permutation_fold_ids", "permutation_id": pid,
                               "actual": sorted(fids), "expected": expected_folds})
        if actual_ids != expected_ids:
            issues.append({"field": "permutation_ids", "actual": actual_ids,
                           "expected": expected_ids, "missing": sorted(set(expected_ids)-set(actual_ids)),
                           "unexpected": sorted(set(actual_ids)-set(expected_ids))})
        if duplicate_pairs:
            issues.append({"field": "duplicate_permutation_fold_pairs", "actual_permutation_ids": duplicate_pairs,
                           "expected": "one record per (permutation_id, fold)"})
        expected_record_count = (count + 1) * len(expected_folds)
        if len(records) != expected_record_count:
            issues.append({"field": "permutation_fold_record_count", "actual": len(records),
                           "expected": expected_record_count})
        for rec in records:
            if rec.get("schema") != "case04-fold/v2" or rec.get("protocol_digest") != digest or rec.get("route") != "falsification":
                issues.append({"field": "permutation_fold_binding", "permutation_id": rec.get("permutation_id"),
                               "fold": rec.get("fold"), "actual": {"schema": rec.get("schema"),
                               "protocol_digest": rec.get("protocol_digest"), "route": rec.get("route")},
                               "expected": {"schema": "case04-fold/v2", "protocol_digest": digest,
                                            "route": "falsification"}})
                break
            fid = _v2_int(rec.get("fold"), "fold")
            expected_train, expected_test = expected_membership.get(fid, (set(), set()))
            train_values = _v2_indices(rec.get("train_global_indices"), "train_global_indices")
            test_values = _v2_indices(rec.get("test_global_indices"), "test_global_indices")
            actual_train, actual_test = set(train_values), set(test_values)
            if actual_train != expected_train or actual_test != expected_test:
                issues.append({"field": "permutation_fold_membership", "permutation_id": rec.get("permutation_id"),
                               "fold": fid, "actual_train_n": len(actual_train), "expected_train_n": len(expected_train),
                               "actual_test_n": len(actual_test), "expected_test_n": len(expected_test),
                               "missing_train": sorted(expected_train-actual_train), "extra_train": sorted(actual_train-expected_train),
                               "missing_test": sorted(expected_test-actual_test), "extra_test": sorted(actual_test-expected_test)})
        pred = _v2_read_predictions(final_dir / "permutation_predictions.csv",
            {"route", "fold", "permutation_id", "row_index", "prediction", "sigma", "absolute_error"})
        pred = _cv_prediction_bindings(pred, protocol, rows, "falsification")
        pred_ids = sorted(set(_v2_int(v, "prediction permutation_id") for v in pred.permutation_id.tolist()))
        if pred_ids != expected_ids:
            issues.append({"field": "permutation_prediction_ids", "actual": pred_ids,
                           "expected": expected_ids, "missing": sorted(set(expected_ids)-set(pred_ids)),
                           "unexpected": sorted(set(pred_ids)-set(expected_ids))})
        if set(pred.route.astype(str)) != {"falsification"}:
            issues.append({"field": "permutation_prediction_routes", "actual": sorted(set(pred.route.astype(str))),
                           "expected": ["falsification"]})
        for pid in expected_ids:
            subset = pred[pred.permutation_id == pid]
            actual_rows = set(_v2_int(v, "prediction row_index") for v in subset.row_index.tolist())
            if len(subset) != len(rows) or actual_rows != set(np.asarray(rows, int).tolist()):
                issues.append({"field": "permutation_prediction_row_cover", "permutation_id": pid,
                               "actual_n": len(subset), "expected_n": len(rows),
                               "missing_rows": sorted(set(rows.tolist())-actual_rows),
                               "unexpected_rows": sorted(actual_rows-set(rows.tolist()))})
            for fid, (_, expected_test) in expected_membership.items():
                fold_rows = subset.loc[subset.fold == fid, "row_index"].astype(int).tolist()
                actual_fold_rows = set(fold_rows)
                if len(fold_rows) != len(expected_test) or actual_fold_rows != expected_test:
                    issues.append({"field": "permutation_prediction_fold_membership", "permutation_id": pid,
                                   "fold": fid, "actual_n": len(actual_fold_rows), "expected_n": len(expected_test),
                                   "missing_rows": sorted(expected_test-actual_fold_rows),
                                   "unexpected_rows": sorted(actual_fold_rows-expected_test)})
        summary = _v2_json(final_dir / "falsification.json") if (final_dir / "falsification.json").is_file() else {}
        summary_arrays = {name: summary[name] for name in ("r2_permutations", "mae_permutations", "permutation_results") if name in summary}
        for name, values in summary_arrays.items():
            actual = len(values) if isinstance(values, list) else None
            if actual != count:
                issues.append({"field": f"{name}_count", "actual": actual, "expected": count,
                               "meaning": "null entries must represent IDs 1..count; ID0 is identity"})
        if "permutation_results" in summary: _permutation_result_rows(summary["permutation_results"], count, digest)
        if "n_permutations" in summary and _v2_int(summary["n_permutations"], "n_permutations") != count:
            issues.append({"field": "n_permutations", "actual": summary.get("n_permutations"), "expected": count})
        return {"ok": not issues, "count": count, "expected_permutation_ids": expected_ids,
                "actual_permutation_ids": actual_ids, "actual_fold_records": len(records),
                "expected_fold_records": expected_record_count, "issues": issues}
    except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "count": count, "expected_permutation_ids": expected_ids,
                "issues": [{"field": "permutation_surface_parse", "actual": f"{type(exc).__name__}: {exc}",
                            "expected": "well-formed identity ID0 and null IDs 1..count with complete folds"}]}


def _v2_check_cv_route(protocol, digest, folds, predictions, route, rows, X, y, fit_cache,
                       permutation_id=None, target_override=None):
    _table_binding(predictions, digest, f"{route} predictions")
    rows = np.asarray(rows, int)
    target = np.asarray(y[rows] if target_override is None else target_override, float)
    splits = case04_protocol.make_cv_splits(protocol, len(rows))
    all_route_folds = [r for r in folds if r.get("route") == route]
    if permutation_id is None:
        if any("permutation_id" in r for r in all_route_folds):
            raise OutputFormatError(f"{route}: unexpected permutation_id in fold record")
    else:
        fold_ids = [_v2_int(r.get("permutation_id"), "permutation_id") for r in all_route_folds]
        expected_ids = set(range(protocol["permutation"]["count"] + 1))
        if set(fold_ids) != expected_ids or len(fold_ids) != len(expected_ids) * len(splits):
            raise OutputFormatError(f"{route}: permutation fold ids/count do not match declaration")
        if set(predictions.route.astype(str)) != {route}:
            raise OutputFormatError(f"{route}: prediction table contains unexpected routes")
        prediction_ids = [_v2_int(v, "prediction permutation_id") for v in predictions.permutation_id.tolist()]
        if set(prediction_ids) != expected_ids:
            raise OutputFormatError(f"{route}: prediction permutation ids do not match declaration")
    route_folds = [r for r in folds if r.get("route") == route and (permutation_id is None or r.get("permutation_id") == permutation_id)]
    for r in route_folds:
        if permutation_id is not None and _v2_int(r.get("permutation_id"), "permutation_id") != permutation_id:
            raise OutputFormatError(f"{route}: invalid permutation id")
    if len(route_folds) != len(splits):
        raise OutputFormatError(f"{route}: fold record count actual={len(route_folds)}, expected={len(splits)}")
    by_fold = {}
    for item in route_folds:
        fid = _v2_int(item.get("fold"), "fold")
        if fid in by_fold:
            raise OutputFormatError(f"{route}: duplicate fold {fid}")
        if item.get("schema") != "case04-fold/v2" or item.get("protocol_digest") != digest:
            raise OutputFormatError(f"{route}/fold{fid}: schema or protocol digest mismatch")
        by_fold[fid] = item
    if set(by_fold) != set(range(len(splits))):
        raise OutputFormatError(f"{route}: fold ids do not match declared CV")
    rowset = set(rows.tolist())
    subset = predictions[predictions.route == route]
    if permutation_id is not None:
        ids = predictions.loc[predictions.route == route, "permutation_id"].unique().tolist()
        if set(ids) != set(range(protocol["permutation"]["count"] + 1)):
            raise OutputFormatError(f"{route}: prediction permutation ids are incomplete or unexpected")
        subset = subset[subset.permutation_id == permutation_id]
    if len(subset) != len(rows):
        raise OutputFormatError(f"{route}: prediction row count is not one full CV cover")
    if set(_v2_int(v, "prediction fold") for v in subset.fold.unique().tolist()) != set(range(len(splits))):
        raise OutputFormatError(f"{route}: prediction rows contain missing or unexpected fold ids")
    fold_maes, fold_r2 = [], []
    all_pred, submitted_all_pred = [], []
    trusted_fold_maes, trusted_fold_r2 = [], []
    for fid, (local_tr, local_te) in enumerate(splits):
        rec = by_fold[fid]
        expected_tr, expected_te = rows[local_tr], rows[local_te]
        tr, te = _v2_indices(rec.get("train_global_indices"), "train_global_indices"), _v2_indices(rec.get("test_global_indices"), "test_global_indices")
        if set(tr) & set(te) or set(tr) != set(expected_tr.tolist()) or set(te) != set(expected_te.tolist()):
            raise OutputFormatError(f"{route}/fold{fid}: split mismatch; train actual_n={len(tr)} expected_n={len(expected_tr)}, "
                f"train_missing={len(set(expected_tr.tolist())-set(tr))}, train_unexpected={len(set(tr)-set(expected_tr.tolist()))}; "
                f"test actual_n={len(te)} expected_n={len(expected_te)}, "
                f"test_missing={len(set(expected_te.tolist())-set(te))}, test_unexpected={len(set(te)-set(expected_te.tolist()))}")
        if not set(tr + te) <= rowset:
            raise OutputFormatError(f"{route}/fold{fid}: row outside declared route")
        p_fold = subset[subset.fold == fid]
        if permutation_id is not None:
            p_fold = p_fold[p_fold.permutation_id == permutation_id]
        if p_fold.row_index.duplicated().any() or set(p_fold.row_index.tolist()) != set(expected_te.tolist()):
            raise OutputFormatError(f"{route}/fold{fid}: prediction rows are duplicate or incomplete")
        p_fold = p_fold.set_index("row_index")
        expected_p, expected_s = _v2_cached_fit(protocol, X[expected_tr], target[local_tr], X[expected_te], fit_cache)
        submitted_p = p_fold.loc[expected_te, "prediction"].to_numpy(float)
        submitted_s = p_fold.loc[expected_te, "sigma"].to_numpy(float)
        pred_delta, sigma_delta = np.abs(submitted_p-expected_p), np.abs(submitted_s-expected_s)
        if (submitted_s <= 0).any() or not _v2_allclose(submitted_p, expected_p, rtol=_V2_RTOL, atol=_V2_ATOL) or not _v2_allclose(submitted_s, expected_s, rtol=_V2_RTOL, atol=_V2_ATOL):
            raise ScientificMismatch(f"{route}/fold{fid}: independent refit mismatch; prediction max_abs_delta={float(pred_delta.max())}, "
                f"sigma max_abs_delta={float(sigma_delta.max())}, prediction tolerance rtol={_V2_RTOL} atol={_V2_ATOL}, "
                f"sigma tolerance rtol={_V2_RTOL} atol={_V2_ATOL}, nonpositive_sigma_count={int((submitted_s<=0).sum())}")
        submitted_e = np.abs(submitted_p - target[local_te])
        trusted_e = np.abs(expected_p - target[local_te])
        if "absolute_error" in p_fold and not _v2_allclose(
                p_fold.loc[expected_te, "absolute_error"].to_numpy(float), submitted_e,
                rtol=1e-7, atol=1e-7):
            raise ScientificMismatch(f"{route}/fold{fid}: reported absolute_error differs from submitted prediction and public target")
        mae = float(submitted_e.mean())
        trusted_mae = float(trusted_e.mean())
        if "mae" in rec and not math.isclose(_v2_finite(rec["mae"], "fold mae"), mae, rel_tol=1e-7, abs_tol=1e-7):
            raise ScientificMismatch(f"{route}/fold{fid}: reported MAE mismatch")
        fold_maes.append(mae)
        trusted_fold_maes.append(trusted_mae)
        if len(local_te) > 1:
            r2 = float(r2_score(target[local_te], submitted_p))
            trusted_r2 = float(r2_score(target[local_te], expected_p))
            if "r2" in rec and not math.isclose(_v2_finite(rec["r2"], "fold r2"), r2, rel_tol=1e-7, abs_tol=1e-7):
                raise ScientificMismatch(f"{route}/fold{fid}: reported R2 mismatch")
            fold_r2.append(r2)
            trusted_fold_r2.append(trusted_r2)
        all_pred.extend({"row_index": int(index), "prediction": float(v), "sigma": float(sd), "absolute_error": float(a)}
                        for index, v, sd, a in zip(expected_te, expected_p, expected_s, trusted_e))
        submitted_all_pred.extend({"row_index": int(index), "prediction": float(v), "sigma": float(sd), "absolute_error": float(a)}
                                  for index, v, sd, a in zip(expected_te, submitted_p, submitted_s, submitted_e))
    mean_r2 = float(np.mean(fold_r2)) if fold_r2 else math.nan
    trusted_mean_r2 = float(np.mean(trusted_fold_r2)) if trusted_fold_r2 else math.nan
    return {"fold_mae": fold_maes, "fold_r2": fold_r2, "mean_mae": float(np.mean(fold_maes)),
            "mean_r2": mean_r2, "predictions": all_pred,
            "trusted_fold_mae": trusted_fold_maes, "trusted_fold_r2": trusted_fold_r2,
            "trusted_mean_mae": float(np.mean(trusted_fold_maes)), "trusted_mean_r2": trusted_mean_r2,
            "submitted_predictions": submitted_all_pred}



def _v2_check_logo(protocol, digest, folds, predictions, rows, X, y, groups, fit_cache):
    _table_binding(predictions, digest, "logo_predictions.csv")
    if set(f.get("route") for f in folds) != {"logo"} or set(predictions.route.astype(str)) != {"logo"}:
        raise OutputFormatError("LOGO evidence contains unexpected route values")
    if set(predictions.group_role.astype(str)) != set(protocol["logo"]["group_roles"]):
        raise OutputFormatError("LOGO predictions contain missing or unexpected group roles")
    if set(str(f.get("group_role")) for f in folds) != set(protocol["logo"]["group_roles"]):
        raise OutputFormatError("LOGO fold evidence contains missing or unexpected group roles")
    results = {}
    optional_r2_audit = []
    for role in protocol["logo"]["group_roles"]:
        expected_splits = case04_protocol.make_logo_splits(rows, groups[role])
        role_folds = [r for r in folds if r.get("route") == "logo" and r.get("group_role") == role]
        role_preds = predictions[(predictions.route == "logo") & (predictions.group_role == role)]
        if len(role_folds) != len(expected_splits) or len(role_preds) != len(rows):
            raise OutputFormatError(f"LOGO {role}: expected complete one-fold-per-group evidence")
        by_fold = {}
        for r in role_folds:
            if "permutation_id" in r:
                raise _output_error(f"LOGO {role}: permutation_id is outside the LOGO scope", "logo_folds.jsonl")
            fid = _v2_int(r.get("fold"), "LOGO fold")
            if fid in by_fold:
                raise OutputFormatError(f"LOGO {role}: duplicate fold")
            if r.get("schema") != "case04-fold/v2" or r.get("protocol_digest") != digest:
                raise OutputFormatError(f"LOGO {role}/fold{fid}: schema/digest mismatch")
            _v2_exact_keys(r, {"schema", "protocol_digest", "route", "fold", "group_role", "group_id", "train_global_indices", "test_global_indices"} | ({"mae"} if "mae" in r else set()) | ({"r2"} if "r2" in r else set()), f"LOGO {role}/fold{fid}")
            by_fold[fid] = r
        errors, group_maes, scored = [], [], []
        seen_groups = set()
        for fid, (tr, te, gid) in enumerate(expected_splits):
            rec = by_fold.get(fid)
            if rec is None or _v2_int(rec.get("group_id"), "group_id") != gid:
                raise OutputFormatError(f"LOGO {role}/fold{fid}: missing or incorrect held group")
            if rec.get("group_role") != role:
                raise OutputFormatError(f"LOGO {role}/fold{fid}: incorrect group role")
            if set(_v2_indices(rec.get("train_global_indices"), "train_global_indices")) != set(tr.tolist()) or set(_v2_indices(rec.get("test_global_indices"), "test_global_indices")) != set(te.tolist()):
                raise OutputFormatError(f"LOGO {role}/fold{fid}: indices do not match released group vector")
            if set(groups[role][tr].tolist()) & {gid}:
                raise OutputFormatError(f"LOGO {role}/fold{fid}: held group leaks into training")
            pred = role_preds[(role_preds.fold == fid) & (role_preds.group_id == gid)]
            if pred.row_index.duplicated().any() or set(pred.row_index.tolist()) != set(te.tolist()):
                raise OutputFormatError(f"LOGO {role}/fold{fid}: predictions missing/duplicate")
            pred = pred.set_index("row_index")
            pp, ss = _v2_cached_fit(protocol, X[tr], y[tr], X[te], fit_cache)
            submitted_p, submitted_s = pred.loc[te, "prediction"].to_numpy(float), pred.loc[te, "sigma"].to_numpy(float)
            p_delta, s_delta = np.abs(submitted_p-pp), np.abs(submitted_s-ss)
            if (submitted_s <= 0).any() or not _v2_allclose(submitted_p, pp, rtol=_V2_RTOL, atol=_V2_ATOL) or not _v2_allclose(submitted_s, ss, rtol=_V2_RTOL, atol=_V2_ATOL):
                raise ScientificMismatch(f"LOGO {role}/fold{fid}: independent refit mismatch; prediction max_abs_delta={float(p_delta.max())}, "
                    f"sigma max_abs_delta={float(s_delta.max())}, tolerances rtol={_V2_RTOL} atol={_V2_ATOL}, "
                    f"nonpositive_sigma_count={int((submitted_s<=0).sum())}")
            e = np.abs(submitted_p - y[te]); mae = float(e.mean())
            if "mae" in rec and not math.isclose(_v2_finite(rec["mae"], "LOGO mae"), mae, rel_tol=1e-7, abs_tol=1e-7):
                raise ScientificMismatch(f"LOGO {role}/fold{fid}: fold MAE mismatch")
            if "absolute_error" in pred and not _v2_allclose(pred.loc[te, "absolute_error"].to_numpy(float), e, rtol=1e-7, atol=1e-7):
                raise ScientificMismatch(f"LOGO {role}/fold{fid}: reported absolute_error differs from submitted prediction and public target")
            if "r2" in rec and rec["r2"] is not None:
                observed_r2 = _v2_finite(rec["r2"], f"LOGO {role}/fold{fid}.r2")
                if len(te) < 2:
                    optional_r2_audit.append({"group_role": role, "fold": fid, "group_id": gid,
                        "status": "supplementary_undefined_numeric", "submitted_r2": observed_r2,
                        "canonical_r2": None, "used_in_required_aggregates": False})
                else:
                    expected_r2 = float(r2_score(y[te], submitted_p, force_finite=True))
                    if not math.isclose(observed_r2, expected_r2, rel_tol=1e-7, abs_tol=1e-7):
                        raise ScientificMismatch(f"LOGO {role}/fold{fid}: optional r2 mismatch; submitted={observed_r2}, expected={expected_r2}")
                    optional_r2_audit.append({"group_role": role, "fold": fid, "group_id": gid,
                        "status": "convention_only" if np.all(y[te] == y[te][0]) else "independently_verified",
                        "submitted_r2": observed_r2, "canonical_r2": expected_r2,
                        "used_in_required_aggregates": False})
            group_maes.append(mae); errors.extend(e.tolist()); scored.extend(te.tolist()); seen_groups.add(gid)
        if sorted(scored) != sorted(np.asarray(rows, int).tolist()) or len(seen_groups) != len(expected_splits):
            raise OutputFormatError(f"LOGO {role}: test coverage/group count mismatch")
        results[role] = {"n_groups": len(group_maes), "n_scored": len(scored),
            **case04_protocol.summarize_group_mae(group_maes,
                [len(s[1]) for s in expected_splits])}
    results["optional_r2_audit"] = optional_r2_audit
    return results



def _verify_v2(final_dir: Path, runtime_root: Path, gold_path: Path, report=None) -> dict[str, Any]:
    report = report if report is not None else {"schema": "case04-verification/v2", "case_id": "case-04-uncertainty-applicability-domain",
              "status": "FAIL", "protocol_supported": False, "checks": [], "qualification_granted": False}
    def check(name, status, **fields):
        if status == "FAIL" and "failure_kind" not in fields:
            fields["failure_kind"] = ("OUTPUT_FORMAT" if name in {
                "v2_deliverables", "v2_output_surface", "protocol_schema", "protocol_binding",
                "permutation_evidence_structure", "prediction_rows_and_sigma"
            } else "SCIENTIFIC_CONTRADICTION")
        report["checks"].append({"name": name, "status": status, **fields})
    try:
        data = case04_protocol.load_public_inputs()
    except Exception as exc:
        check("public_input_profile", "ENVIRONMENT_ERROR", reason=str(exc))
        report.update(status="ENVIRONMENT_ERROR", execution_status="NOT_EVALUATED",
                      execution_checks_complete=False, scientific_status="NOT_EVALUATED",
                      verification_coverage="COMPLETE", verification_scope="case04-protocol/v2",
                      environment_error=True, qualification_granted=False)
        return report
    preflight_status, preflight_detail, preflight_answers = _protected_answer_preflight(gold_path, data["test"])
    if preflight_status != "PASS":
        check("protected_answers_preflight", preflight_status, reason=preflight_detail)
        report.update(status=preflight_status, protocol_supported=report.get("protocol_supported", False),
                      execution_status="NOT_EVALUATED", execution_checks_complete=False,
                      scientific_status="NOT_EVALUATED", verification_coverage="COMPLETE",
                      verification_scope="supported_declarative_GPR_v2", qualification_granted=False,
                      needs_protected_answers=(preflight_status == "NEEDS_PROTECTED_ANSWERS"),
                      grader_input_error=(preflight_status == "GRADER_INPUT_ERROR"),
                      environment_error=(preflight_status == "ENVIRONMENT_ERROR"))
        return report
    check("protected_answers_preflight", "PASS", answer_count=len(preflight_answers),
          exact_frozen_test_index_cover=True, target_values_finite=True,
          trusted_sha256_matches=True)

    absent = sorted(name for name in _V2_REQUIRED_OUTPUTS if not (final_dir / name).is_file())
    if absent:
        check("v2_deliverables", "FAIL", missing=absent)
        report.update(execution_status="FAIL", execution_checks_complete=False, scientific_status="NOT_EVALUATED",
                      verification_coverage="COMPLETE", verification_scope="case04-protocol/v2")
        return report
    unsafe = sorted(p.relative_to(final_dir).as_posix() for p in final_dir.rglob("*") if p.is_symlink())
    if unsafe:
        check("v2_output_surface", "FAIL", escaped_or_symlinked_files=unsafe)
        report.update(execution_status="FAIL", execution_checks_complete=False, scientific_status="NOT_EVALUATED",
                      verification_coverage="COMPLETE", verification_scope="case04-protocol/v2")
        return report
    _v2_output_surface(final_dir)
    if not (final_dir / "notes.md").read_text(encoding="utf-8").strip(): raise _output_error("notes.md must explain scientific conclusions")
    try:
        protocol = case04_protocol.load_and_validate_protocol(final_dir / "protocol.json")
    except case04_protocol.InputBindingConflict as exc:
        check("protocol_input_bindings", "FAIL", failure_kind="SCIENTIFIC_CONTRADICTION", reason=str(exc))
        result = _v2_early_fail(report)
        result.update(protocol_supported=False, verification_scope="fixed_public_input_assertions")
        return result
    except NotImplementedError as exc:
        check("protocol_schema", "UNSUPPORTED", reason=str(exc))
        report.update(status="UNSUPPORTED", protocol_supported=False, verification_coverage="PARTIAL", verification_scope="unsupported_protocol")
        return report
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        check("protocol_schema", "FAIL", reason=f"invalid protocol: {exc}")
        report.update(execution_status="FAIL", execution_checks_complete=False, scientific_status="NOT_EVALUATED",
                      verification_coverage="COMPLETE", verification_scope="case04-protocol/v2")
        return report
    pdigest = case04_protocol.canonical_protocol_digest(protocol)
    report["protocol_supported"] = True
    check("protocol_schema", "PASS", schema=protocol["schema"], protocol_digest=pdigest, verified_source_assertions=getattr(protocol, "source_assertions", []), annotation_semantics_verified=False)
    try:
        y, raw_train, test, groups = data["y"], data["train"], data["test"], data["groups"]
        calibration_receipts = _v2_jsonl(final_dir / "calibration_folds.jsonl") if (final_dir / "calibration_folds.jsonl").is_file() else []
        if not calibration_receipts and "row_order" not in protocol["cv"]:
            raise NotImplementedError("cv.row_order must identify training order when no historical fold receipt is supplied")
        train, row_order_id, order_evidence = case04_protocol.resolve_training_order(
            protocol, raw_train, calibration_receipts)
        feature_names, feature_sources = data["feature_names"], data["feature_sources"]
        check("public_input_profile", "PASS", n_train=len(train), n_test=len(test),
              hidden_targets_masked=True, canonical_feature_count=len(feature_names))
        check("training_row_order", "PASS", order_id=row_order_id, **order_evidence,
              applied_to="full_fit,calibration,permutation,LOGO,multicondition,applicability_domain")
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        check("public_input_profile", "FAIL", failure_kind="OUTPUT_FORMAT", stage="input_profile_or_row_order", actual=str(exc), expected="354 training rows and one valid global row order")
        report.update(execution_status="FAIL", execution_checks_complete=False, scientific_status="NOT_EVALUATED",
                      verification_coverage="COMPLETE", verification_scope="case04-protocol/v2")
        return report

    binding = (_v2_exact_keys(_v2_json(final_dir / "protocol_binding.json"), {"schema", "protocol_digest"}, "protocol_binding")
               if (final_dir / "protocol_binding.json").is_file() else {"schema": "case04-protocol-reference/v2", "protocol_digest": pdigest})
    binding_ok = (binding.get("schema") == "case04-protocol-reference/v2"
                  and binding.get("protocol_digest") == pdigest)
    check("protocol_binding", "PASS" if binding_ok else "FAIL", protocol_digest_matches=binding_ok)
    if not binding_ok:
        return _v2_early_fail(report)
    permutation_structure = _v2_permutation_structure(final_dir, protocol, pdigest, train)
    check("permutation_evidence_structure", "PASS" if permutation_structure["ok"] else "FAIL",
          **{k: v for k, v in permutation_structure.items() if k != "ok"})
    if not permutation_structure["ok"]:
        return _v2_early_fail(report)
    if "basis" not in protocol["features"]:
        check("feature_basis", "UNSUPPORTED", actual="legacy protocol omits features.basis",
              expected=case04_protocol.FEATURE_BASIS,
              reason="the historical prompt did not identify the ordered input matrix; no basis is inferred from prediction error")
        report.update(status="UNSUPPORTED", protocol_supported=True, execution_status="NOT_EVALUATED",
                      scientific_status="NOT_EVALUATED", execution_checks_complete=False,
                      verification_coverage="PARTIAL", verification_scope="legacy_feature_basis_unknown",
                      qualification_granted=False)
        return report
    try:
        X = case04_protocol.select_features(data["X"], protocol)
    except NotImplementedError as exc:
        check("feature_basis", "UNSUPPORTED", actual=protocol["features"].get("basis"),
              expected=case04_protocol.FEATURE_BASIS, reason=str(exc))
        report.update(status="UNSUPPORTED", protocol_supported=True, execution_status="NOT_EVALUATED",
                      scientific_status="NOT_EVALUATED", execution_checks_complete=False,
                      verification_coverage="PARTIAL", verification_scope="unsupported_feature_basis",
                      qualification_granted=False)
        return report
    selected_indices = protocol["features"]["indices"]
    check("feature_basis", "PASS", actual=protocol["features"]["basis"], expected=case04_protocol.FEATURE_BASIS,
          n_features=int(X.shape[1]), selected_indices=selected_indices,
          selected_names=[feature_names[i] for i in selected_indices],
          selected_sources=[feature_sources[i] for i in selected_indices], row_index_is_not_a_feature=True)

    # A candidate manifest is optional self-reported provenance, never an attestation.
    manifest_path = final_dir / "run_manifest.json"
    if manifest_path.is_file():
        check("candidate_runtime_manifest", "OPTIONAL_UNVERIFIED", present=True,
              used_for_scoring=False, trusted_execution=False,
              reason="candidate-provided manifest claims are not independently attested")
    else:
        check("candidate_runtime_manifest", "OPTIONAL_NOT_PROVIDED", present=False,
              used_for_scoring=False, trusted_execution=False)

    predicted = _v2_read_predictions(final_dir / "predictions_with_uncertainty.csv", {"row_index", "prediction", "sigma"})
    _table_binding(predicted, pdigest, "predictions_with_uncertainty.csv")
    if predicted.row_index.duplicated().any() or set(predicted.row_index.tolist()) != set(test.tolist()) or len(predicted) != len(test):
        check("prediction_rows_and_sigma", "FAIL", reason="test predictions must be finite, positive-sigma and an exact once-only frozen test cover")
        return _v2_early_fail(report)
    if (predicted.sigma <= 0).any():
        raise ScientificMismatch("full-fit posterior sigma must be positive")
    ptest, stest = case04_protocol.fit_predict_with_sigma(protocol, X[train], y[train], X[predicted.row_index.to_numpy(int)])
    ordered_test = predicted.set_index("row_index").loc[predicted.row_index.to_numpy(int)]
    test_p_ok = _v2_allclose(ordered_test.prediction.to_numpy(float), ptest, rtol=_V2_RTOL, atol=_V2_ATOL)
    test_s_ok = _v2_allclose(ordered_test.sigma.to_numpy(float), stest, rtol=_V2_RTOL, atol=_V2_ATOL)
    p_delta = np.abs(ordered_test.prediction.to_numpy(float) - ptest)
    s_delta = np.abs(ordered_test.sigma.to_numpy(float) - stest)
    check("gpr_refit_prediction_and_posterior_sigma", "PASS" if test_p_ok and test_s_ok else "FAIL",
          stage="full_train_test_refit", prediction_matches_refit=bool(test_p_ok),
          sigma_matches_refit=bool(test_s_ok), prediction_max_abs_delta=float(p_delta.max()),
          sigma_max_abs_delta=float(s_delta.max()), prediction_rtol=_V2_RTOL, prediction_atol=_V2_ATOL,
          sigma_rtol=_V2_RTOL, sigma_atol=_V2_ATOL,
          feature_basis=case04_protocol.FEATURE_BASIS, selected_feature_indices=protocol["features"]["indices"],
          selected_feature_names=[data["feature_names"][i] for i in protocol["features"]["indices"]],
          constant_sigma_allowed=True)
    if not (test_p_ok and test_s_ok):
        return _v2_early_fail(report)

    fit_cache = _V2_REFIT_CACHE
    # Calibration: verify native fold evidence, then summary and OOF rows.
    cf = calibration_receipts or _declared_cv_folds(protocol, pdigest, train, "calibration")
    if any(r.get("route") != "calibration" for r in cf):
        check("candidate_train_oof_calibration", "FAIL", failure_kind="OUTPUT_FORMAT", reason="unexpected route in calibration fold file")
        return _v2_early_fail(report)
    if (final_dir / "calibration_oof.csv").is_file():
        cpred = _v2_read_predictions(final_dir / "calibration_oof.csv", {"row_index", "prediction", "sigma"})
    else:
        identity = _v2_read_predictions(final_dir / "permutation_predictions.csv", {"route", "fold", "permutation_id", "row_index", "prediction", "sigma", "absolute_error"})
        cpred = identity[identity.permutation_id == 0].drop(columns=["permutation_id", "route"], errors="ignore")
    cpred = _cv_prediction_bindings(cpred, protocol, train, "calibration")
    _table_binding(cpred, pdigest, "calibration_oof.csv")
    if cpred.row_index.duplicated().any() or set(cpred.row_index.tolist()) != set(train.tolist()):
        check("candidate_train_oof_calibration", "FAIL", failure_kind="OUTPUT_FORMAT", reason="OOF predictions must exactly cover training rows with positive sigma")
        return _v2_early_fail(report)
    if (cpred.sigma <= 0).any():
        raise ScientificMismatch("calibration posterior sigma must be positive")
    # Evidence uses the same semantic keys and supports shuffled row order.
    # calibration_oof is the prediction evidence; fold route ids bind each row to its fold.
    if len(cf) != protocol["cv"]["n_splits"]:
        check("candidate_train_oof_calibration", "FAIL", failure_kind="OUTPUT_FORMAT", reason="calibration fold receipt count mismatch")
        return _v2_early_fail(report)
    # Build prediction table by joining OOF rows to declared fold test membership.
    cal_records = []
    for fold in cf:
        for row in _v2_indices(fold.get("test_global_indices"), "calibration test indices"):
            candidate = cpred[cpred.row_index == row]
            if len(candidate) != 1:
                check("candidate_train_oof_calibration", "FAIL", failure_kind="OUTPUT_FORMAT", reason="OOF row absent or duplicated")
                return _v2_early_fail(report)
            for selector, expected_selector in (("route", "calibration"), ("fold", fold.get("fold"))):
                if selector in cpred and candidate.iloc[0][selector] != expected_selector:
                    raise _output_error(f"calibration_oof.csv:{row}: {selector} contradicts fold membership", "calibration_oof.csv")
            if "absolute_error" in cpred and not math.isclose(float(candidate.iloc[0].absolute_error), abs(float(candidate.iloc[0].prediction)-float(y[row])), rel_tol=1e-7, abs_tol=1e-7):
                raise ScientificMismatch(f"calibration_oof.csv:{row}: optional absolute_error mismatch")
            cal_records.append({"route": "calibration", "fold": fold.get("fold"), "row_index": row,
                                "prediction": float(candidate.iloc[0].prediction), "sigma": float(candidate.iloc[0].sigma),
                                "absolute_error": abs(float(candidate.iloc[0].prediction) - float(y[row]))})
    cal_pred_frame = pd.DataFrame(cal_records)
    cal_result = _stage_call("candidate_train_oof_calibration", _v2_check_cv_route, protocol, pdigest, cf, cal_pred_frame, "calibration", train, X, y, fit_cache)
    cal_by_idx = {v["row_index"]: v for v in cal_result["predictions"]}
    oof_match = all(_v2_allclose([float(cpred.set_index("row_index").loc[i, "prediction"]), float(cpred.set_index("row_index").loc[i, "sigma"])],
                               [cal_by_idx[i]["prediction"], cal_by_idx[i]["sigma"]], rtol=_V2_RTOL, atol=_V2_ATOL) for i in train)
    submitted_cal_by_idx = {v["row_index"]: v for v in cal_result["submitted_predictions"]}
    errors = np.asarray([submitted_cal_by_idx[int(i)]["absolute_error"] for i in train], float)
    sigmas = np.asarray([submitted_cal_by_idx[int(i)]["sigma"] for i in train], float)
    cal_stats = case04_protocol.summarize_calibration(train,
        [submitted_cal_by_idx[int(i)]["prediction"] for i in train], sigmas, y[train])
    coverage, errors = cal_stats["coverage"], cal_stats["errors"]
    risk = cal_stats["risk_filter"]
    cal_summary = _v2_json(final_dir / "calibration.json") if (final_dir / "calibration.json").is_file() else {}
    _summary_observations(cal_summary, set(), {"intervals", "overall_oof_mae", "risk_filter", "schema", "protocol_digest", "scope", "n_rows"},
        "calibration.json", "case04-calibration/v2", pdigest)
    cal_summary_ok = "scope" not in cal_summary or _is_training_only_oof_scope(cal_summary["scope"])
    if "n_rows" in cal_summary: cal_summary_ok &= _v2_int(cal_summary["n_rows"], "calibration.n_rows") == len(train)
    if "intervals" in cal_summary:
        for label in _reported_identities(cal_summary["intervals"], coverage, "calibration.intervals"):
            record = cal_summary["intervals"][label]
            if isinstance(record, dict):
                _v2_exact_keys(record, {"empirical_coverage"}, f"calibration.intervals.{label}")
                record = record["empirical_coverage"]
            cal_summary_ok &= math.isclose(_v2_finite(record, "coverage"), coverage[label], rel_tol=1e-7, abs_tol=1e-7)
    if "overall_oof_mae" in cal_summary:
        cal_summary_ok &= math.isclose(_v2_finite(cal_summary["overall_oof_mae"], "OOF MAE"), cal_stats["overall_oof_mae"], rel_tol=1e-7, abs_tol=1e-7)
    if "risk_filter" in cal_summary:
        for key in _reported_identities(cal_summary["risk_filter"], risk, "calibration.risk_filter"):
            item = cal_summary["risk_filter"][key]
            if not isinstance(item, dict): item = {"mae": item}
            _v2_exact_keys(item, set(item) & {"mae", "n", "overall_mae"}, f"calibration.risk_filter.{key}")
            candidates = risk[key]
            submitted_n = _v2_int(item["n"], f"{key}.n") if "n" in item else candidates[0]["n"]
            match = next((v for v in candidates if v["n"] == submitted_n), None)
            cal_summary_ok &= match is not None
            if match is not None and "mae" in item: cal_summary_ok &= math.isclose(_v2_finite(item["mae"], "risk MAE"), match["mae"], rel_tol=1e-7, abs_tol=1e-7)
            if "overall_mae" in item: cal_summary_ok &= math.isclose(_v2_finite(item["overall_mae"], "risk overall MAE"), cal_stats["overall_oof_mae"], rel_tol=1e-7, abs_tol=1e-7)
    report["candidate_calibration_metrics"] = {"coverage": coverage, "overall_oof_mae": cal_stats["overall_oof_mae"],
        "risk_filter": cal_stats["risk_filter"], "derived_from": "row-aligned submitted predictions and public training targets"}
    cal_ok = oof_match and cal_summary_ok
    check("candidate_train_oof_calibration", "PASS" if cal_ok else "FAIL", stage="training_oof_calibration",
          independent_all_fold_refit_match=bool(oof_match), summary_matches_recomputed_rows=bool(cal_summary_ok),
          coverage_actual=coverage, coverage_expected=cal_stats["coverage"],
          overall_oof_mae_actual=cal_summary.get("overall_oof_mae"),
          overall_oof_mae_expected=cal_stats["overall_oof_mae"],
          risk_filter_actual=cal_summary.get("risk_filter"), risk_filter_expected=cal_stats["risk_filter"])
    if not cal_ok:
        return _v2_early_fail(report)

    # Full paired permutation evidence is independently fitted for every split/target.
    pf = _folds_or_declared(final_dir / "permutation_folds.jsonl", [r for pid in range(protocol["permutation"]["count"] + 1) for r in _declared_cv_folds(protocol, pdigest, train, "falsification", pid)])
    if any(r.get("route") != "falsification" for r in pf):
        check("falsification_full_permutation_distribution", "FAIL", failure_kind="OUTPUT_FORMAT", reason="unexpected route in permutation fold file")
        return _v2_early_fail(report)
    ppred = _v2_read_predictions(final_dir / "permutation_predictions.csv", {"route", "fold", "permutation_id", "row_index", "prediction", "sigma", "absolute_error"})
    ppred = _cv_prediction_bindings(ppred, protocol, train, "falsification")
    count = protocol["permutation"]["count"]
    expected_targets = case04_protocol.permutation_targets(protocol, y[train])
    permutation_scores, perm_failed = [], False
    for pid, target in enumerate(expected_targets):
        rr = _stage_call("falsification_distribution_refits", _v2_check_cv_route, protocol, pdigest, pf, ppred, "falsification", train, X, y, fit_cache,
                                permutation_id=pid, target_override=target)
        permutation_scores.append({"r2": rr["mean_r2"], "mae": rr["mean_mae"],
                                   "trusted_r2": rr["trusted_mean_r2"],
                                   "trusted_mae": rr["trusted_mean_mae"]})
    fals_raw = _v2_json(final_dir / "falsification.json") if (final_dir / "falsification.json").is_file() else {}
    fals = _summary_observations(fals_raw,
        set(),
        {"true_r2", "true_mae", "r2_separation", "r2_pvalue_plus_one", "schema", "protocol_digest", "n_train", "n_permutations", "r2_permutations", "mae_permutations", "permutation_results",
         "r2_separation_reference", "r2_separation_mean_null", "r2_separation_maximum_null"},
        "falsification.json", "case04-falsification/v2", pdigest)
    obs, nulls = permutation_scores[0], permutation_scores[1:]
    reference = fals.get("r2_separation_reference")
    if reference is not None and not isinstance(reference, str): raise _output_error("falsification.json: separation reference must be a method name", "falsification.json")
    expected_fals = case04_protocol.summarize_permutation(obs, nulls, reference if reference is not None else "maximum_null")
    sep = float(expected_fals["r2_separation_maximum_null"])
    summary_core_ok = True
    for key, expected_count in (("n_train", len(train)), ("n_permutations", count)):
        if key in fals: summary_core_ok &= _v2_int(fals[key], f"falsification.{key}") == expected_count
    for key in ("r2_permutations", "mae_permutations"):
        if key in fals: summary_core_ok &= _v2_allclose(_v2_numbers(fals[key], f"falsification.json:{key}"), expected_fals[key], rtol=1e-7, atol=1e-7)
    for key in ("true_r2", "true_mae"):
        if key in fals: summary_core_ok &= math.isclose(_v2_finite(fals[key], key), expected_fals[key], rel_tol=1e-7, abs_tol=1e-7)
    if "permutation_results" in fals:
        perm_summary = _stage_call("falsification_summary", _permutation_result_rows, fals["permutation_results"], count, pdigest)
        for metric, array in (("r2", "r2_permutations"), ("mae", "mae_permutations")):
            summary_core_ok &= _v2_allclose([row[metric] for row in perm_summary], expected_fals[array], rtol=1e-7, atol=1e-7)
    if reference is not None and reference not in ("mean_null", "maximum_null"):
        raise NotImplementedError(f"unsupported r2_separation_reference: {reference!r}")
    submitted_sep = _v2_finite(fals["r2_separation"], "r2_separation") if "r2_separation" in fals else None
    mean_sep_match = submitted_sep is not None and math.isclose(submitted_sep, expected_fals["r2_separation_mean_null"], rel_tol=1e-7, abs_tol=1e-7)
    max_sep_match = submitted_sep is not None and math.isclose(submitted_sep, expected_fals["r2_separation_maximum_null"], rel_tol=1e-7, abs_tol=1e-7)
    if reference == "mean_null":
        separation_match, resolved_reference = mean_sep_match, reference
    elif reference == "maximum_null":
        separation_match, resolved_reference = max_sep_match, reference
    else:
        separation_match = mean_sep_match or max_sep_match
        resolved_reference = "equivalent" if mean_sep_match and max_sep_match else (
            "mean_null" if mean_sep_match else "maximum_null" if max_sep_match else None)
    summary_core_ok = summary_core_ok and (submitted_sep is None or separation_match)
    expected_p = expected_fals["r2_pvalue_plus_one"]
    if "r2_pvalue_plus_one" in fals: summary_core_ok &= math.isclose(_v2_finite(fals["r2_pvalue_plus_one"], "r2_pvalue_plus_one"), expected_p, rel_tol=1e-7, abs_tol=1e-7)
    report["candidate_permutation_metrics"] = {**expected_fals, "derived_from": "all submitted identity/null row predictions and public permuted training targets"}
    if "r2_separation_mean_null" in fals:
        summary_core_ok = summary_core_ok and math.isclose(_v2_finite(fals["r2_separation_mean_null"], "r2_separation_mean_null"), expected_fals["r2_separation_mean_null"], rel_tol=1e-7, abs_tol=1e-7)
    if "r2_separation_maximum_null" in fals:
        summary_core_ok = summary_core_ok and math.isclose(_v2_finite(fals["r2_separation_maximum_null"], "r2_separation_maximum_null"), expected_fals["r2_separation_maximum_null"], rel_tol=1e-7, abs_tol=1e-7)
    check("falsification_distribution_refits", "PASS", stage="foldwise_refit", n_permutations=count,
          identity_id=0, null_ids=[1, count], observed_r2=obs["r2"],
          null_r2_mean=float(np.mean(expected_fals["r2_permutations"])),
          null_r2_maximum=float(np.max(expected_fals["r2_permutations"])),
          independent_all_fold_refits=True)
    check("falsification_summary", "PASS" if summary_core_ok else "FAIL", stage="derived_summary",
          true_r2_actual=fals.get("true_r2"), true_r2_expected=expected_fals["true_r2"],
          true_mae_actual=fals.get("true_mae"), true_mae_expected=expected_fals["true_mae"],
          null_r2_actual_count=len(fals["r2_permutations"]) if "r2_permutations" in fals else None, null_r2_expected_count=count,
          null_mae_actual_count=len(fals["mae_permutations"]) if "mae_permutations" in fals else None, null_mae_expected_count=count,
          r2_separation_actual=submitted_sep, r2_separation_mean_null=expected_fals["r2_separation_mean_null"],
          r2_separation_maximum_null=expected_fals["r2_separation_maximum_null"],
          r2_separation_reference_resolved=resolved_reference, p_plus_one_actual=fals.get("r2_pvalue_plus_one"),
          p_plus_one_expected=expected_p, summary_matches_recomputed_distribution=bool(summary_core_ok))
    if not summary_core_ok:
        return _v2_early_fail(report)
    trusted_obs = permutation_scores[0]
    trusted_nulls = permutation_scores[1:]
    trusted_summary = case04_protocol.summarize_permutation(
        {"r2": trusted_obs["trusted_r2"], "mae": trusted_obs["trusted_mae"]},
        [{"r2": v["trusted_r2"], "mae": v["trusted_mae"]} for v in trusted_nulls], resolved_reference if resolved_reference in ("mean_null", "maximum_null") else "maximum_null")
    falsification_observed_exceeds_null = bool(trusted_summary["true_r2"] > max(trusted_summary["r2_permutations"]))
    check("scientific_falsification_control", "PASS", observed_r2=trusted_summary["true_r2"],
          permutation_r2_mean=float(np.mean(trusted_summary["r2_permutations"])),
          permutation_r2_max=max(trusted_summary["r2_permutations"]),
          r2_separation_mean_null=trusted_summary["r2_separation_mean_null"],
          r2_separation_maximum_null=trusted_summary["r2_separation_maximum_null"],
          observed_exceeds_all_permutations=falsification_observed_exceeds_null,
          acceptance_gate=False)

    # LOGO and multi-condition evidence is candidate-native; every fold is refit.
    declared_logo = []
    for role in protocol["logo"]["group_roles"]:
        for fid, (tr, te, gid) in enumerate(case04_protocol.make_logo_splits(train, groups[role])):
            declared_logo.append({"schema": "case04-fold/v2", "protocol_digest": pdigest, "route": "logo", "fold": fid,
                                 "group_role": role, "group_id": gid, "train_global_indices": tr.tolist(), "test_global_indices": te.tolist()})
    lf = _folds_or_declared(final_dir / "logo_folds.jsonl", declared_logo)
    lp = _v2_read_predictions(final_dir / "logo_predictions.csv", {"route", "group_role", "group_id", "fold", "row_index", "prediction", "sigma", "absolute_error"})
    lp = _logo_prediction_bindings(lp, protocol, train, groups)
    logo_metrics = _stage_call("candidate_extrapolation_report", _v2_check_logo, protocol, pdigest, lf, lp, train, X, y, groups, fit_cache)
    optional_logo_r2_audit = logo_metrics.pop("optional_r2_audit", [])
    report["optional_logo_r2_audit"] = optional_logo_r2_audit
    report["scientific_explanation"] = {"provided": True, "automated_semantic_verification": False, "scope": "free research interpretation remains separately reviewable"}
    extrap = _v2_json(final_dir / "extrapolation.json") if (final_dir / "extrapolation.json").is_file() else {}
    _summary_observations(extrap, set(), {"results", "schema", "protocol_digest", "execution_scope", "aggregation", "explanation"}, "extrapolation.json", "case04-extrapolation/v2", pdigest)
    ex_ok = "execution_scope" not in extrap or extrap["execution_scope"] == "candidate_local_execution"
    if "aggregation" in extrap:
        aggregation = extrap["aggregation"]
        if not isinstance(aggregation, dict): raise _output_error("extrapolation.aggregation must be an object")
        fixed = {"macro_weighting": "equal_group", "micro_weighting": "equal_row", "direction_is_acceptance_gate": False}
        ex_ok &= all(key not in aggregation or aggregation[key] == value for key, value in fixed.items())
    if "results" in extrap:
        for role in _reported_identities(extrap["results"], ("substrate", "nucleophile"), "extrapolation.results"):
            entry = extrap["results"][role]
            fields = {"macro_group_mae", "macro_group_sem", "micro_row_mae", "n_groups", "n_scored", "interpretation"}
            _v2_exact_keys(entry, set(entry) & fields if isinstance(entry, dict) else set(), f"extrapolation.results.{role}")
            for key, val in logo_metrics[role].items():
                if key not in entry: continue
                if key in {"n_groups", "n_scored"}: ex_ok &= _v2_int(entry[key], f"extrapolation.{role}.{key}") == val
                else: ex_ok &= math.isclose(_v2_finite(entry[key], f"LOGO {key}"), val, rel_tol=1e-7, abs_tol=1e-7)
    report["candidate_logo_metrics"] = logo_metrics
    check("candidate_extrapolation_report", "PASS" if ex_ok else "FAIL", stage="LOGO_summary",
          actual={role: extrap.get("results", {}).get(role, {}) for role in ("substrate", "nucleophile")},
          expected=logo_metrics, numerical_rtol=1e-7, numerical_atol=1e-7,
          candidate_local_fold_refits=True, no_directional_ordering_as_pass_gate=True)
    if not ex_ok:
        return _v2_early_fail(report)

    mf = _v2_jsonl(final_dir / "multicondition_folds.jsonl") if (final_dir / "multicondition_folds.jsonl").is_file() else []
    if any(r.get("route") not in {"all_train", "single_reaction_only"} for r in mf):
        check("candidate_multi_condition_removal", "FAIL", failure_kind="OUTPUT_FORMAT", reason="unexpected route in multi-condition fold file")
        return _v2_early_fail(report)
    mp = _v2_read_predictions(final_dir / "multicondition_oof.csv", {"route", "fold", "row_index", "prediction", "sigma", "absolute_error"})
    rxn = groups["reaction"]
    train_counts = pd.Series(rxn[train]).value_counts()
    single = train[np.asarray([train_counts.get(rxn[i], 0) == 1 for i in train])]
    if "route" not in mp: mp["route"] = "single_reaction_only"
    if not set(mp.route.astype(str)).issubset({"all_train", "single_reaction_only"}) or "single_reaction_only" not in set(mp.route):
        raise OutputFormatError("multi-condition prediction route set is invalid")
    parts = []
    for route, population in (("all_train", train), ("single_reaction_only", single)):
        part = mp[mp.route == route]
        if route == "all_train" and part.empty: part = cpred.drop(columns=["route"], errors="ignore")
        parts.append(_cv_prediction_bindings(part, protocol, population, route))
    mp = pd.concat(parts, ignore_index=True)
    if not mf: mf = _declared_cv_folds(protocol, pdigest, train, "all_train") + _declared_cv_folds(protocol, pdigest, single, "single_reaction_only")
    multi_summaries = {}
    for route, rows in (("all_train", train), ("single_reaction_only", single)):
        rr = _stage_call("candidate_multi_condition_removal", _v2_check_cv_route, protocol, pdigest, mf, mp, route, rows, X, y, fit_cache)
        row_mae = float(np.mean([r["absolute_error"] for r in rr["submitted_predictions"]]))
        vals = np.asarray(rr["fold_mae"], float)
        multi_summaries[route] = {"n_rows": len(rows), "n_folds": len(vals), "n_scored": len(rows),
            **case04_protocol.summarize_fold_mae(vals,
                [r["absolute_error"] for r in rr["submitted_predictions"]]), "fold_mae": vals.tolist()}
    multi = _v2_json(final_dir / "multicondition.json") if (final_dir / "multicondition.json").is_file() else {}
    _summary_observations(multi, set(), {"routes", "schema", "protocol_digest", "n_excluded_multi_condition_rows"}, "multicondition.json", "case04-multicondition/v2", pdigest)
    multi_ok = "n_excluded_multi_condition_rows" not in multi or _v2_int(multi["n_excluded_multi_condition_rows"], "n_excluded_multi_condition_rows") == len(train)-len(single)
    if "routes" in multi:
        for route in _reported_identities(multi["routes"], ("all_train", "single_reaction_only"), "multicondition.routes"):
            item = multi["routes"][route]; summary = multi_summaries[route]
            _v2_exact_keys(item, set(item) & set(summary) if isinstance(item, dict) else set(), f"multicondition.routes.{route}")
            for key, value in summary.items():
                if key not in item: continue
                if key == "fold_mae": multi_ok &= _v2_allclose(_v2_numbers(item[key], f"{route}.fold_mae"), value, rtol=1e-7, atol=1e-7)
                elif key in {"n_rows", "n_folds", "n_scored"}: multi_ok &= _v2_int(item[key], f"{route}.{key}") == value
                else: multi_ok &= math.isclose(_v2_finite(item[key], f"{route}.{key}"), value, rel_tol=1e-7, abs_tol=1e-7)
    report["candidate_multicondition_metrics"] = multi_summaries
    check("candidate_multi_condition_removal", "PASS" if multi_ok else "FAIL", stage="multi_condition_summary",
          actual=multi.get("routes", {}), expected=multi_summaries,
          n_excluded_actual=multi.get("n_excluded_multi_condition_rows"),
          n_excluded_expected=len(train)-len(single), numerical_rtol=1e-7, numerical_atol=1e-7,
          singleton_rows=len(single), all_train_group_disjoint=False)
    if not multi_ok:
        return _v2_early_fail(report)

    # AD row scores and flags are reconstructed from the declared public training features.
    domain = _v2_read_predictions(final_dir / "domain.csv", {"row_index", "score", "threshold", "out_of_domain", "rule_id"})
    _table_binding(domain, pdigest, "domain.csv")
    domain_cols = {"row_index", "score", "threshold", "out_of_domain", "rule_id"}
    if not {"row_index", "score", "out_of_domain"}.issubset(domain.columns):
        check("domain_rule_and_hit_counts", "FAIL", failure_kind="OUTPUT_FORMAT", reason="domain schema mismatch")
        return _v2_early_fail(report)
    domain_rows = pd.to_numeric(domain.row_index, errors="raise").to_numpy(float)
    flags_raw = domain.out_of_domain.astype(str).str.lower()
    if (not np.isfinite(domain_rows).all() or not np.equal(domain_rows, np.floor(domain_rows)).all()
            or domain.duplicated(subset=["row_index"]).any()
            or set(domain_rows.astype(int)) != set(test.tolist()) or len(domain) != len(test)
            or not flags_raw.isin(["true", "false", "1", "0"]).all()):
        check("domain_rule_and_hit_counts", "FAIL", failure_kind="OUTPUT_FORMAT", reason="domain rows/schema do not match frozen test set")
        return _v2_early_fail(report)
    domain["row_index"] = domain_rows.astype(int)
    dsort = domain.set_index("row_index").loc[test]
    adscore, cutoff, flags = case04_protocol.compute_ad(protocol, X[train], X[test])
    domain_score = pd.to_numeric(dsort.score, errors="raise").to_numpy(float)
    domain_threshold = pd.to_numeric(dsort.threshold, errors="raise").to_numpy(float) if "threshold" in dsort else np.full(len(test), cutoff)
    if not np.isfinite(domain_score).all() or not np.isfinite(domain_threshold).all():
        check("domain_rule_and_hit_counts", "FAIL", failure_kind="OUTPUT_FORMAT", reason="domain score or threshold is non-finite")
        return _v2_early_fail(report)
    parsed_flags = dsort.out_of_domain.astype(str).str.lower().map({"true": True, "1": True, "false": False, "0": False}).to_numpy(bool)
    rule_ids_match = True
    for value in dsort.rule_id.astype(str) if "rule_id" in dsort else []:
        rule = _v2_decode(value, "domain.csv:rule_id")
        if not isinstance(rule, dict): raise _output_error("domain.csv:rule_id must describe the AD calculation", "domain.csv")
        rule = dict(rule)
        if "k" in rule: rule["k"] = _v2_int(rule["k"], "domain.csv:rule_id.k")
        if "quantile" in rule: _v2_finite(rule["quantile"], "domain.csv:rule_id.quantile")
        try:
            asserted = case04_protocol.load_and_validate_protocol({**protocol, "ad": rule})
        except NotImplementedError:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise _output_error(f"domain.csv:rule_id: {exc}", "domain.csv") from exc
        rule_ids_match = rule_ids_match and asserted["ad"] == protocol["ad"]
    ad_ok = (_v2_allclose(domain_score, adscore, rtol=1e-7, atol=1e-7)
             and _v2_allclose(domain_threshold, np.full(len(test), cutoff), rtol=1e-7, atol=1e-7)
             and np.array_equal(parsed_flags, flags)
             and rule_ids_match)
    check("domain_rule_and_hit_counts", "PASS" if ad_ok else "FAIL", stage="applicability_domain_recomputation",
          rule=protocol["ad"], threshold_actual_unique=np.unique(domain_threshold).tolist(), threshold_expected=float(cutoff),
          score_max_abs_delta=float(np.max(np.abs(domain_score-adscore))),
          numerical_rtol=1e-7, numerical_atol=1e-7,
          out_of_domain_rows_actual=int(np.sum(parsed_flags)), out_of_domain_rows_expected=int(np.sum(flags)),
          rule_recomputed=True)
    if not ad_ok:
        return _v2_early_fail(report)

    # Replicate input integrity is an execution check; precision claims are a separate scientific check.
    noise = _v2_json(final_dir / "noise_floor.json")
    optional_precision = {"precision_justification"} if isinstance(noise, dict) and "precision_justification" in noise else set()
    _summary_observations(noise, {"precision_claim", "reasoning"}, {"schema", "pair_differences_kcal_mol"} | optional_precision, "noise_floor.json", "case04-noise-floor/v2")
    noise_stats = case04_protocol.summarize_replicate_pairs(
        pd.read_csv(ASSETS / "S12_replicate_barrier_pairs.csv")["g_kcal_mol"].dropna().astype(str).tolist())
    expected_diffs = noise_stats["pair_differences_kcal_mol"]
    vals = noise.get("pair_differences_kcal_mol")
    noise_ok = vals is None or (isinstance(vals, list) and len(vals) == 4 and _v2_allclose(
        sorted([_v2_finite(v, "noise difference") for v in vals]), sorted(expected_diffs), atol=0.02))
    if not isinstance(noise["reasoning"], str) or not noise["reasoning"].strip():
        raise _output_error("noise_floor.json: reasoning must explain the precision claim", "noise_floor.json")
    precision = noise.get("precision_claim")
    if not isinstance(precision, str): _v2_finite(precision, "noise_floor.precision_claim")
    precision_justification = noise.get("precision_justification")
    if (precision == "no_sub_0.1_kcal_mol_claim" and isinstance(precision_justification, dict)
            and "claimed_bound_kcal_mol" in precision_justification):
        if isinstance(precision_justification["claimed_bound_kcal_mol"], bool):
            precision = None
        else:
            try:
                bound_claim = float(precision_justification["claimed_bound_kcal_mol"])
            except (TypeError, ValueError, OverflowError):
                precision = None
            else:
                precision = bound_claim if math.isfinite(bound_claim) else None
    noise_ok = noise_ok and isinstance(noise.get("reasoning"), str) and bool(noise["reasoning"].strip())
    check("candidate_noise_floor_interpretation", "PASS" if noise_ok else "FAIL", stage="replicate_source_comparison",
          actual_pair_differences=vals, source_pair_differences=expected_diffs, tolerance_kcal_mol=0.02,
          source_95pct_t_halfwidths_kcal_mol=noise_stats["student_t_95_halfwidths_kcal_mol"],
          largest_source_halfwidth_kcal_mol=noise_stats["uniform_bound_kcal_mol"])

    # Protected answers were byte/schema-preflighted before fitting; join them only now,
    # after all candidate predictions and execution evidence have passed.
    if not noise_ok:
        return _v2_early_fail(report)
    scientific_noise = True
    precision_result = "PASS"
    required_bound = None
    if precision == "no_sub_0.1_kcal_mol_claim":
        check("noise_floor_precision_science", precision_result, precision_claim=precision,
              reason="no sub-0.1 precision claim is made", single_observation_or_model_accuracy_claim_supported=False)
    elif isinstance(precision, (int, float)) and not isinstance(precision, bool) and math.isfinite(float(precision)):
        claimed = float(precision)
        justification = noise.get("precision_justification")
        if justification is None and claimed < 0.1:
            precision_result = "FAIL"
            scientific_noise = False
        elif justification is None:
            precision_result = "PASS"
        else:
            scientific_j = {"confidence", "claimed_bound_kcal_mol", "explanation"}
            fixed_j = {"schema": "case04-precision-evidence/v1", "kind": "replicate_mean_ci",
                "claim_scope": "source_replicate_means_only", "estimand": "mean_of_independent_replicates",
                "evidence_ref": "S12_replicate_barrier_pairs/v1", "rule": "student_t_two_sided_mean_ci"}
            _v2_exact_keys(justification, scientific_j | (set(justification) & set(fixed_j)) if isinstance(justification, dict) else scientific_j, "noise_floor.precision_justification")
            if any(key in justification and justification[key] != value for key, value in fixed_j.items()):
                precision_result = "UNSUPPORTED"
            else:
                explanation_text = justification.get("explanation")
                conf = _v2_finite(justification.get("confidence"), "precision confidence")
                bound = _v2_finite(justification.get("claimed_bound_kcal_mol"), "precision bound")
                explanation_lower = explanation_text.lower() if isinstance(explanation_text, str) else ""
                iid_explicit = ("iid" in explanation_lower
                    or "independent and identically distributed" in explanation_lower
                    or ("independent replicates" in explanation_lower and "within-pair" in explanation_lower))
                if conf != 0.95 or not isinstance(explanation_text, str) or not explanation_text.strip() or not iid_explicit:
                    precision_result = "FAIL"
                    scientific_noise = False
                else:
                    required_bound = noise_stats["uniform_bound_kcal_mol"]
                    valid_bound = bound >= required_bound and claimed >= bound
                    precision_result = "PASS" if valid_bound else "FAIL"
                    scientific_noise = valid_bound
        check("noise_floor_precision_science", precision_result, precision_claim=precision,
              supported_scope="four S12 replicate means only", recomputed_95pct_t_interval_max_halfwidth=required_bound if precision_result in ("PASS", "FAIL") and isinstance(noise.get("precision_justification"), dict) else None,
              single_observation_or_model_accuracy_claim_supported=False)
    elif isinstance(precision, str):
        check("noise_floor_precision_science", "UNSUPPORTED", precision_claim=precision,
              reason="declare a numeric kcal/mol precision bound or the supported no-sub-0.1 enum")
        precision_result = "UNSUPPORTED"
    else:
        check("noise_floor_precision_science", "FAIL", precision_claim_type=type(precision).__name__,
              reason="precision claim must be numeric kcal/mol or the supported no-sub-0.1 enum")
        precision_result = "FAIL"
        scientific_noise = False
    if precision_result == "UNSUPPORTED":
        report.update(status="UNSUPPORTED", execution_status="PASS", execution_checks_complete=True,
            scientific_status="UNSUPPORTED", verification_coverage="COMPLETE", verification_scope="unsupported_precision_claim",
            needs_external_evidence=True, qualification_granted=False)
        return report
    answers = preflight_answers
    merged = predicted.merge(answers, on="row_index", how="outer", validate="one_to_one", indicator=True)
    if len(merged) != len(test) or not (merged._merge == "both").all() or merged.exp_activation_energy.isna().any():
        check("hidden_answer_join", "FAIL", reason="prediction rows do not exactly join hidden answers")
        return _v2_early_fail(report)
    trusted_test_by_row = {int(i): (float(p), float(s))
                           for i, p, s in zip(predicted.row_index.to_numpy(int), ptest, stest)}
    trusted_test_prediction = np.asarray([trusted_test_by_row[int(i)][0] for i in merged.row_index], float)
    hidden_sigma = np.asarray([trusted_test_by_row[int(i)][1] for i in merged.row_index], float)
    hidden_error = np.abs(trusted_test_prediction - merged.exp_activation_energy.to_numpy(float))
    hidden_cov = {f"{z:g}sigma": float(np.mean(hidden_error <= z*hidden_sigma)) for z in (1, 1.96, 2, 2.576)}
    low_n = max(1, int(round(0.5*len(hidden_error))))
    hidden_order = np.lexsort((merged.row_index.to_numpy(int), hidden_sigma))
    all_mae, low_mae = float(hidden_error.mean()), float(hidden_error[hidden_order[:low_n]].mean())
    coverage_in_registered_benchmark_band, risk_improved = 0.60 <= hidden_cov["2sigma"] <= 1.0, low_mae < all_mae
    check("hidden_answer_join", "PASS", exact_index_join=True, answer_count=len(merged))
    check("coverage_and_risk_filter", "PASS", coverage=hidden_cov,
          overall_mae=all_mae, low_sigma_50pct_mae=low_mae,
          registered_benchmark_two_sigma_coverage_band_met=bool(coverage_in_registered_benchmark_band),
          low_sigma_half_mae_below_overall=bool(risk_improved))
    if not scientific_noise: report["failure_kind"] = "SCIENTIFIC_CONTRADICTION"
    scientific_status = "PASS" if scientific_noise else "FAIL"
    report.update(status="PASS" if scientific_status == "PASS" else "FAIL", scientific_status=scientific_status,
        execution_status="PASS", execution_checks_complete=True, verification_coverage="COMPLETE", verification_scope="supported_declarative_GPR_v2",
        qualification_granted=False, protocol_digest=pdigest,
        scientific_effect={"falsification_observed_exceeds_null": falsification_observed_exceeds_null,
                           "precision_interpretation_pass": bool(scientific_noise), "blind_two_sigma_coverage": hidden_cov["2sigma"],
                           "blind_overall_mae": all_mae, "blind_low_sigma_half_mae": low_mae},
        hidden_answer_output="aggregate metrics only; no row-level answers or residuals")
    return report


def _v2_early_fail(report):
    failed = [item for item in report.get("checks", []) if item["status"] == "FAIL"]
    kind = failed[-1].get("failure_kind", "SCIENTIFIC_CONTRADICTION") if failed else "OUTPUT_FORMAT"
    report["failure_kind"] = kind
    report.update(status="FAIL", protocol_supported=True, execution_status="FAIL", execution_checks_complete=False,
                  scientific_status="NOT_EVALUATED" if kind == "OUTPUT_FORMAT" else "FAIL",
                  verification_coverage="COMPLETE", verification_scope="supported_declarative_GPR_v2",
                  qualification_granted=False)
    return report


def verify(final_dir: Path | None = None, runtime_root: Path = RUNTIME,
           gold_path: Path = GOLD, legacy_audit: bool = False) -> dict[str, Any]:
    final_dir = Path(final_dir or CASE / "final")
    if not final_dir.is_dir() or not any(final_dir.iterdir()):
        return {"schema": "case04-verification/v2", "case_id": "case-04-uncertainty-applicability-domain",
                "status": "FAIL", "protocol_supported": False, "execution_status": "FAIL",
                "scientific_status": "NOT_EVALUATED", "execution_checks_complete": False,
                "verification_coverage": "COMPLETE", "verification_scope": "case04-protocol/v2",
                "qualification_granted": False, "checks": [{"name": "v2_deliverables", "status": "FAIL",
                    "reason": "candidate final directory is absent or empty"}]}
    final_resolved = final_dir.resolve()
    runtime_resolved = Path(runtime_root).resolve()
    if runtime_resolved == final_resolved or final_resolved in runtime_resolved.parents:
        raise ValueError("grader runtime directory must remain outside candidate final")
    if (final_dir / "protocol.json").is_file():
        progress = {"schema": "case04-verification/v2", "case_id": "case-04-uncertainty-applicability-domain", "status": "FAIL", "protocol_supported": False, "qualification_granted": False, "checks": []}
        try:
            return _verify_v2(final_dir, runtime_root, gold_path, progress)
        except NotImplementedError as exc:
            return {**progress, "schema": "case04-verification/v2", "case_id": "case-04-uncertainty-applicability-domain",
                    "status": "UNSUPPORTED", "protocol_supported": False, "execution_checks_complete": False,
                    "execution_status": "UNSUPPORTED", "scientific_status": "NOT_EVALUATED",
                    "verification_coverage": "PARTIAL", "verification_scope": "unsupported_protocol",
                    "qualification_granted": False, "checks": progress["checks"] + [{"name": getattr(exc, "stage", None) or "protocol_schema", "status": "UNSUPPORTED", "reason": str(exc)}]}
        except Exception as exc:
            if not isinstance(exc, (OutputFormatError, ScientificMismatch)):
                return {**progress, "schema": "case04-verification/v2", "case_id": "case-04-uncertainty-applicability-domain",
                        "status": "GRADER_ERROR", "protocol_supported": True, "execution_status": "GRADER_ERROR",
                        "scientific_status": "NOT_EVALUATED", "execution_checks_complete": False,
                        "verification_coverage": "PARTIAL", "verification_scope": "trusted_execution_error",
                        "qualification_granted": False, "grader_error": True,
                        "checks": progress["checks"] + [{"name": "trusted_verifier_execution", "status": "GRADER_ERROR",
                                    "reason": f"{type(exc).__name__}: {exc}"}]}
            return {**progress, "schema": "case04-verification/v2", "case_id": "case-04-uncertainty-applicability-domain",
                    "status": "FAIL", "protocol_supported": True, "execution_status": "FAIL", "scientific_status": "NOT_EVALUATED" if isinstance(exc, OutputFormatError) else "FAIL",
                    "execution_checks_complete": False, "failure_kind": "OUTPUT_FORMAT" if isinstance(exc, OutputFormatError) else "SCIENTIFIC_CONTRADICTION",
                    "verification_coverage": "COMPLETE", "verification_scope": "supported_declarative_GPR_v2",
                    "qualification_granted": False, "checks": progress["checks"] + [{"name": getattr(exc, "stage", None) or _v2_error_check(str(exc)), "status": "FAIL", "failure_kind": "OUTPUT_FORMAT" if isinstance(exc, OutputFormatError) else "SCIENTIFIC_CONTRADICTION", "reason": str(exc)}]}
    manifest_path = final_dir / "run_manifest.json"
    if manifest_path.is_file():
        try:
            if _v2_json(manifest_path).get("schema") == "case04-runtime-manifest/v2" or (final_dir / "protocol_binding.json").exists():
                return {"schema": "case04-verification/v2", "case_id": "case-04-uncertainty-applicability-domain",
                        "status": "FAIL", "protocol_supported": False, "execution_status": "FAIL",
                        "scientific_status": "NOT_EVALUATED", "execution_checks_complete": False,
                        "verification_coverage": "COMPLETE", "verification_scope": "case04-protocol/v2",
                        "qualification_granted": False, "checks": [{"name": "protocol_schema", "status": "FAIL", "reason": "v2 submission is missing required protocol.json"}]}
        except Exception:
            pass
    if legacy_audit:
        return _verify_legacy(final_dir, runtime_root, gold_path)
    # Only a recognizable historical v1 runtime manifest earns the explicit
    # migration-required state. Empty/unknown directories are ordinary failures.
    if manifest_path.is_file():
        try:
            old = _v2_json(manifest_path)
            if old.get("schema") == "case04-runtime-manifest/v1":
                if not isinstance(old.get("input_sha256"), dict) or not isinstance(old.get("output_sha256"), dict):
                    raise ValueError("historical v1 manifest has no input/output digests")
                for group in (old["input_sha256"], old["output_sha256"]):
                    if any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in group.values()):
                        raise ValueError("historical v1 manifest contains malformed SHA-256 declarations")
                return {"schema": "case04-verification/v2", "case_id": "case-04-uncertainty-applicability-domain",
                    "status": "LEGACY_MIGRATION_REQUIRED", "protocol_supported": False,
                    "execution_status": "NOT_EVALUATED", "scientific_status": "NOT_EVALUATED", "execution_checks_complete": False,
                    "verification_coverage": "PARTIAL", "verification_scope": "legacy_submission_requires_v2_execution",
                    "qualification_granted": False, "checks": [{"name": "protocol_schema", "status": "UNSUPPORTED",
                        "reason": "verified historical v1 receipt recognized; reexecute under protocol.json v2"}]}
        except Exception:
            pass
    return {"schema": "case04-verification/v2", "case_id": "case-04-uncertainty-applicability-domain",
            "status": "LEGACY_MIGRATION_REQUIRED", "protocol_supported": False,
            "execution_status": "NOT_EVALUATED", "scientific_status": "NOT_EVALUATED", "execution_checks_complete": False,
            "verification_coverage": "PARTIAL", "verification_scope": "legacy_submission_requires_v2_execution",
            "qualification_granted": False, "checks": [{"name": "protocol_schema", "status": "UNSUPPORTED",
                "reason": "protocol.json v2 is required; select explicit legacy audit for historical evidence or rerun with the v2 runner"}]}


def _v2_error_check(message: str) -> str:
    low = message.lower()
    for needles, name in ((('calibration', 'oof'), 'candidate_train_oof_calibration'),
                          (('logo', 'group_role', 'held group'), 'candidate_extrapolation_report'),
                          (('permutation', 'falsification'), 'falsification_distribution_refits'),
                          (('multi', 'singleton', 'single_reaction'), 'candidate_multi_condition_removal'),
                          (('domain', 'ad ', 'rule_id', 'out_of_domain'), 'domain_rule_and_hit_counts'),
                          (('noise', 'precision', 'replicate'), 'candidate_noise_floor_interpretation'),
                          (('protocol', 'schema'), 'protocol_schema'), (('manifest', 'binding', 'hash'), 'candidate_runtime_manifest'),
                          (('prediction', 'sigma', 'test rows'), 'gpr_refit_prediction_and_posterior_sigma'),
                          (('hidden', 'answer join'), 'hidden_answer_join')):
        if any(n in low for n in needles):
            return name
    return "v2_independent_verification"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final-dir", type=Path, default=None, help="candidate output directory; defaults to package/final")
    parser.add_argument("--runtime-dir", type=Path, default=RUNTIME, help="grader evidence directory; defaults to data/gold/derived/case04_runtime")
    parser.add_argument("--report", type=Path, default=None, help="verification report path")
    parser.add_argument("--gold-path", type=Path, default=GOLD, help="protected grader answer file (never candidate input)")
    parser.add_argument("--legacy-audit", action="store_true", help="explicitly audit historical v1 evidence; not suitable for new submissions")
    args = parser.parse_args(argv)
    final_dir = args.final_dir or CASE / "final"
    report_path = args.report or (args.runtime_dir / "verification_report.json")
    for grader_path, label in ((args.runtime_dir, "--runtime-dir"), (report_path, "--report")):
        if grader_path.resolve() == final_dir.resolve() or final_dir.resolve() in grader_path.resolve().parents:
            parser.error(f"{label} must be outside candidate final directory")
    result = verify(final_dir, runtime_root=args.runtime_dir, gold_path=args.gold_path, legacy_audit=args.legacy_audit)
    result["scorer_revision"] = "case04-verifier-D2"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "report": str(report_path),
                      "checks": [{"name": c["name"], "status": c["status"]} for c in result["checks"]]}, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else (1 if result["status"] == "FAIL" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
