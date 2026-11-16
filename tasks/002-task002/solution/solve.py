#!/usr/bin/env python3
"""Private reference computation; consumes public assets, never verifier modules."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import warnings

# Keep optimization deterministic and avoid oversubscribing the task's CPU budget.
for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[variable] = "1"

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore", category=ConvergenceWarning)
PREFIX = "SC-012-D0SC04896H-"
FILES = {"Full": PREFIX + "s120.csv", "No TS": PREFIX + "s138.csv",
         "Small": PREFIX + "s140.csv", "Surface": PREFIX + "s141.csv",
         "Traditional": PREFIX + "s142.csv", "Only TS": PREFIX + "s143.csv"}
SEEDS = [42, 43, 44, 45, 46]
FOLDS = 5
PROTOCOL = "preferred_frozen_354_89_v1"
BARRIER_FILE = PREFIX + "s112.csv"
BARRIER_COLUMN = "activation_energy_none"
GRID = [{"matern_nu": nu, "alpha": alpha}
        for nu in (0.5, 1.5, 2.5) for alpha in (1e-6, 0.0)]
ESTIMATOR = {
    "family": "GaussianProcessRegressor",
    "parameter_grid": GRID,
    "kernel": {
        "constant_value": {"initial": 1.0, "bounds": "fixed"},
        "length_scale": {"initial": 1.0, "bounds": [1e-5, 1e5]},
        "white_noise_level": {"initial": 1.0, "bounds": [1e-5, 1e5]},
    },
    "normalize_y": True,
    "optimizer": "fmin_l_bfgs_b",
    "n_restarts_optimizer": 0,
}
PREPROCESSING = {"scaler": "standard", "fit_scope": "training_folds_only"}


def read_table(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames[1:]
        rows = list(reader)
    assert [int(row[""]) for row in rows] == list(range(443)), path
    return columns, np.asarray([[float(row[col]) for col in columns] for row in rows])


def dump_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def dump_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def metrics(truth, predicted):
    residual = predicted - truth
    return {"mae_kcal_mol": float(np.mean(np.abs(residual))),
            "rmse_kcal_mol": float(np.sqrt(np.mean(residual ** 2))),
            "r2": float(1 - np.sum(residual ** 2) / np.sum((truth - truth.mean()) ** 2))}


def estimator(params, seed):
    kernel = (ConstantKernel(1.0, constant_value_bounds="fixed")
              * Matern(length_scale=1.0, length_scale_bounds=(1e-5, 1e5),
                       nu=params["matern_nu"])
              + WhiteKernel(noise_level=1.0, noise_level_bounds=(1e-5, 1e5)))
    return make_pipeline(StandardScaler(), GaussianProcessRegressor(
        kernel=kernel, alpha=params["alpha"], normalize_y=True,
        optimizer="fmin_l_bfgs_b", n_restarts_optimizer=0, random_state=seed))


def train_arm(matrix, target, train, test, folds, seed):
    xtrain, ytrain = matrix[train], target[train]
    scores = []
    for params in GRID:
        fold_scores = []
        for fit, validation in folds:
            model = estimator(params, seed)
            model.fit(xtrain[fit], ytrain[fit])
            fold_scores.append(float(np.mean(np.abs(model.predict(xtrain[validation])
                                                    - ytrain[validation]))))
        scores.append({"parameters": params, "fold_mae": fold_scores,
                       "mean_cv_mae": float(np.mean(fold_scores))})
    # Stable grid order breaks ties; one final fit on every frozen training row.
    best = min(range(len(GRID)), key=lambda i: (scores[i]["mean_cv_mae"], i))
    model = estimator(GRID[best], seed)
    model.fit(xtrain, ytrain)
    return model.predict(matrix[test]), {
        "candidates": scores, "selected_index": best, "selected_params": GRID[best],
        "refit_training_count": len(train), "fitted_kernel": str(model[-1].kernel_)}


def arm_spec(label, matrices, seed=None, folds=None):
    spec = {"matrix_file": FILES[label], "feature_columns": matrices[label][0],
            "estimator": ESTIMATOR, "preprocessing": PREPROCESSING,
            "target_transform": "normalize_y",
            "budget": {"candidate_parameterizations": len(GRID)}}
    if seed is None:
        spec.update(seed_policy="paired_seed", cv={"n_splits": FOLDS, "shuffle": True,
                    "random_state_policy": "seed", "scoring": "MAE"})
    else:
        spec.update(seed=seed, cv={"n_splits": FOLDS, "shuffle": True,
                    "random_state": seed, "scoring": "MAE"},
                    cv_folds=[{"train_local": a.tolist(), "validation_local": b.tolist()}
                              for a, b in folds])
    return spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, default=Path("/app"))
    root = parser.parse_args().app_root
    assets, out = root / "assets", root / "final"
    out.mkdir(parents=True, exist_ok=True)
    (out / "predictions").mkdir(exist_ok=True)
    ablation = out / "ablation-v2"
    ablation.mkdir(exist_ok=True)
    matrices = {label: read_table(assets / filename) for label, filename in FILES.items()}
    target_columns, targets = read_table(assets / (PREFIX + "s144.csv"))
    target = targets[:, target_columns.index("exp_activation_energy")]
    train = np.load(assets / (PREFIX + "s119.npy"), allow_pickle=False)
    test = np.load(assets / (PREFIX + "s118.npy"), allow_pickle=False)
    assert train.shape == (354,) and test.shape == (89,)
    assert len(set(train)) == 354 and len(set(test)) == 89
    assert not set(train) & set(test)
    assert set(train) | set(test) == set(range(443))
    for columns, matrix in matrices.values():
        assert np.isfinite(matrix).all()
        assert not any("exp" in col.lower() or "activation" in col.lower() for col in columns)
    full, no_ts = matrices["Full"][0], matrices["No TS"][0]
    ts = matrices["Only TS"][0]
    assert [len(matrices[label][0]) for label in FILES] == [33, 25, 11, 13, 21, 8]
    assert set(full) - set(no_ts) == set(ts)
    assert not set(no_ts) - set(full)
    assert set(matrices["Surface"][0]) - set(matrices["Small"][0]) == {"p_int_central", "p_int_nu"}
    assert set(no_ts) - set(matrices["Traditional"][0]) == {
        "v_av_central_atom", "v_av_nu_atom", "is_av", "es_av"}
    for col in no_ts:
        assert np.array_equal(matrices["Full"][1][:, full.index(col)],
                              matrices["No TS"][1][:, no_ts.index(col)])

    electrostatic = {"epn_central", "epn_nu", "epn_lg", "nu_charge", "central_charge",
                     "lg_charge", "omega", "local_electrophilicity_center",
                     "local_nucleophilicity_nu", "p_int_central", "p_int_nu"}
    surface = {"v_av_central_atom", "v_av_nu_atom", "sasa_ratio_nu", "sasa_ratio_central",
               "is_av", "es_av"}
    rationale = {
        "Full": "All 33 descriptors: the 25 No TS columns and exactly the eight Only TS columns.",
        "No TS": "All 25 non-TS descriptors, with no computed barrier or experimental target appended.",
        "Small": "The 11-column volume/SASA/is_av/es_av and five-PC matrix.",
        "Surface": "The 13-column matrix: all Small columns plus p_int_central and p_int_nu.",
        "Traditional": "The 21-column matrix: No TS minus v_av_central_atom, v_av_nu_atom, is_av and es_av.",
        "Only TS": "Exactly eight TS electrostatic/charge and bond-order descriptors, all ending in _ts.",
    }
    uncertainty = ("The released feature matrices contain no activation_energy_* column. "
                   "The released files alone do not establish whether a computed barrier was appended "
                   "in the historical benchmark workflow. Historical appended-barrier use is uncertain; "
                   "this reproduction uses only the released descriptors and appends no barrier. "
                   "Labels follow the current task's six released matrices; composition is explicit "
                   "and is not inferred by matching published MAEs.")
    feature_map = {}
    for label, (columns, _) in matrices.items():
        groups = {"transition_state": [], "electrostatic": [], "surface_steric": [], "other": []}
        for col in columns:
            group = ("transition_state" if col.endswith("_ts") else "electrostatic"
                     if col in electrostatic else "surface_steric" if col in surface else "other")
            groups[group].append(col)
        feature_map[label] = {"source_matrix_file": FILES[label], "feature_columns": columns,
                              "appended_barrier_uncertainty": True,
                              "evidence": {"descriptor_groups": groups,
                                           "identification_rationale": rationale[label],
                                           "appended_barrier_assessment": uncertainty}}
    dump_json(out / "feature_set_map.json", feature_map)

    splits = {seed: list(KFold(FOLDS, shuffle=True, random_state=seed).split(train)) for seed in SEEDS}
    primary = SEEDS[0]
    dump_json(out / "model_spec.json", {
        "schema": "case02-model-spec/v1", "protocol_id": PROTOCOL,
        "arms": {"hybrid": arm_spec("Full", matrices, primary, splits[primary]),
                 "no_ts": arm_spec("No TS", matrices, primary, splits[primary])},
        "baselines": {
            "direct_barrier": {"source_matrix_file": BARRIER_FILE, "column": BARRIER_COLUMN},
            "linear_correction": {"source_matrix_file": BARRIER_FILE, "column": BARRIER_COLUMN,
                                  "family": "OLS", "alpha": 0.0, "fit_scope": "training_only"},
            "mean_baseline": {"statistic": "training_mean", "fit_scope": "training_only"}}})
    dump_json(out / "protocol.json", {
        "protocol_id": PROTOCOL, "train_indices": train.tolist(), "test_indices": test.tolist(),
        "train_test_disjoint": True, "target_excluded_from_features": True,
        "target_derived_values_excluded": True, "preprocessing_fit_scope": "training_folds_only",
        "search_budget": {"same_frozen_split": True, "same_cv_folds": True,
                          "per_arm_candidate_parameterizations": {"hybrid": len(GRID), "no_ts": len(GRID)}},
        "seeds": SEEDS, "primary_seed": primary, "supplementary_split_used": False,
        "test_used_for_selection": False, "barrier_variant": BARRIER_COLUMN,
        "performance_requirements": {"hybrid_mae_max_kcal_mol": 1.10,
                                     "improvement_over_direct_min_kcal_mol": 1.0,
                                     "hybrid_must_beat_training_mean": True}})
    dump_json(ablation / "ablation_protocol.json", {
        "schema": "case02-ablation-protocol/v1", "seeds": SEEDS,
        "frozen_indices": {"train": train.tolist(), "test": test.tolist()},
        "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(assets.iterdir()) if p.is_file()},
        "preprocessing_fit_scope": "training_fold_only", "test_used_for_selection": False,
        "target_excluded_from_features": True, "supplementary_split_used": False,
        "cv": {"folds": FOLDS, "shuffle": True, "same_splits_per_seed_across_arms": True,
               "selection_metric": "MAE"},
        "model_spec": {"schema": "case02-model-spec/v1",
                       "arms": {label: arm_spec(label, matrices) for label in ("Full", "No TS")}}})
    dump_json(ablation / "feature_diff.json", {
        "full_columns": full, "no_ts_columns": no_ts,
        "full_only_columns": [col for col in full if col not in no_ts],
        "no_ts_only_columns": [col for col in no_ts if col not in full],
        "shared_column_count": len(set(full) & set(no_ts))})
    for seed, folds in splits.items():
        dump_json(ablation / f"cv_splits_seed{seed}.json", {
            "seed": seed, "position_space": "0-based positions in frozen 354-row training pool",
            "folds": [{"train_positions": a.tolist(), "validation_positions": b.tolist()}
                      for a, b in folds]})

    def prediction_file(relative, predicted):
        dump_csv(out / relative, [{"row_index": int(index),
                  "true_experimental_barrier": float(target[index]),
                  "predicted_barrier": float(value)} for index, value in sorted(zip(test, predicted))])

    def comparison(model, label, source, predicted, relative):
        prediction_file(relative, predicted)
        return {"model": model, "feature_set_label": label, "source_matrix_file": source,
                "protocol": PROTOCOL, "seed": primary, "n_train": len(train), "n_test": len(test),
                **metrics(target[test], predicted), "prediction_file": relative, "is_preferred": "true"}

    barrier_columns, barrier_matrix = read_table(assets / BARRIER_FILE)
    barrier = barrier_matrix[:, barrier_columns.index(BARRIER_COLUMN)]
    corrected = LinearRegression().fit(barrier[train, None], target[train]).predict(barrier[test, None])
    rows = [comparison("direct_barrier", "computed_barrier", BARRIER_FILE, barrier[test],
                       "predictions/direct_barrier.csv"),
            comparison("linear_correction", "computed_barrier", BARRIER_FILE, corrected,
                       "predictions/linear_correction.csv"),
            comparison("mean_baseline", "training_mean", PREFIX + "s144.csv",
                       np.full(len(test), target[train].mean()), "predictions/mean_baseline.csv")]
    paired, selection = [], {}
    for seed in SEEDS:
        scores = {}
        selection[str(seed)] = {}
        for label, model, suffix in (("Full", "hybrid", "full"), ("No TS", "no_ts", "no_ts")):
            predicted, audit = train_arm(matrices[label][1], target, train, test, splits[seed], seed)
            selection[str(seed)][label] = audit
            relative = f"ablation-v2/predictions_{suffix}_seed{seed}.csv"
            prediction_file(relative, predicted)
            scores[suffix] = metrics(target[test], predicted)["mae_kcal_mol"]
            if seed == primary:
                if model == "hybrid":
                    relative = "test_predictions.csv"
                rows.append(comparison(model, label, FILES[label], predicted, relative))
            print(f"seed={seed} arm={label} test_MAE={scores[suffix]:.9f} "
                  f"selected={audit['selected_params']}", flush=True)
        paired.append({"seed": seed, "full_mae_kcal_mol": scores["full"],
                       "no_ts_mae_kcal_mol": scores["no_ts"],
                       "delta_mae_no_ts_minus_full_kcal_mol": scores["no_ts"] - scores["full"]})
    dump_csv(out / "model_comparison.csv", rows)
    dump_csv(ablation / "paired_ablation.csv", paired)
    deltas = np.asarray([row["delta_mae_no_ts_minus_full_kcal_mol"] for row in paired])
    summary = {"seed_count": len(SEEDS), "seeds": SEEDS,
               "delta_mean_kcal_mol": float(deltas.mean()),
               "delta_std_kcal_mol": float(deltas.std(ddof=1)),
               "delta_min_kcal_mol": float(deltas.min()), "delta_max_kcal_mol": float(deltas.max()),
               "full_better_for_all_seeds": bool(np.all(deltas > 0)),
               "delta_definition": "MAE(No TS) - MAE(Full)"}
    dump_json(ablation / "paired_summary.json", summary)
    dump_json(out / "selection_log.json", selection)
    hybrid = next(row for row in rows if row["model"] == "hybrid")["mae_kcal_mol"]
    direct, mean = rows[0]["mae_kcal_mol"], rows[2]["mae_kcal_mol"]
    (out / "notes.md").write_text(
        "Public-data reproduction with released experimental labels; the frozen 89-row test is not blind.\n\n"
        + uncertainty + "\n\n"
        "The direct baseline uses the public s112 activation_energy_none electronic barrier. "
        "Quasi-harmonic Grimme/Truhlar and nu/ts variants are valid alternatives, but are not searched here. "
        "The OLS correction with an intercept and the mean baseline fit only the 354 training labels.\n\n"
        "Full and No TS use identical standard scaling, six explicit GPR candidates, five shuffled "
        "MAE folds and five paired seeds. Scaling and target normalization fit within each training fold. "
        "Candidates minimize mean validation-fold MAE with grid-order tie breaking. Each selected model "
        "is refit once on all training rows; no fold-model averaging is used. Full contains TS descriptors; "
        "neither arm appends a computed barrier. No supplementary population or split is evaluated.\n\n"
        f"Preferred seed: {primary}; Full MAE: {hybrid:.9f}; direct MAE: {direct:.9f}; "
        f"training-mean MAE: {mean:.9f} kcal/mol. Required thresholds: Full MAE <= 1.10, "
        "direct-minus-Full MAE >= 1.0 and Full better than training mean.\n\n"
        f"Paired MAE(No TS)-MAE(Full): mean {deltas.mean():.9f}, sample standard deviation "
        f"{deltas.std(ddof=1):.9f}, range [{deltas.min():.9f}, {deltas.max():.9f}] kcal/mol. "
        "A positive value favors Full; a positive TS gain is not required. Seed variation describes "
        "CV selection on one fixed test set, not independent test-sample uncertainty.\n",
        encoding="utf-8")
    assert hybrid <= 1.10, f"Full MAE exceeds requirement: {hybrid}"
    assert direct - hybrid >= 1.0, "Full does not improve direct barrier by required margin"
    assert hybrid < mean, "Full does not beat training mean"
    print(json.dumps({"preferred_hybrid_mae": hybrid, "paired_summary": summary}), flush=True)


if __name__ == "__main__":
    main()
