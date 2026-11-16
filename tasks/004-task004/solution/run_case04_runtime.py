#!/usr/bin/env python3
"""Execute a declarative Case 04 v2 protocol using the public blind input surface."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score

import case04_protocol as cp

ROOT = cp.ROOT
ASSETS = cp.ASSETS
FINAL = cp.CASE / "final"
OUTPUT_ALLOWLIST = {
    "protocol.json", "protocol_binding.json", "predictions_with_uncertainty.csv", "calibration_folds.jsonl",
    "calibration_oof.csv", "calibration.json", "permutation_folds.jsonl", "permutation_predictions.csv",
    "falsification.json", "logo_folds.jsonl", "logo_predictions.csv", "extrapolation.json",
    "multicondition_folds.jsonl", "multicondition_oof.csv", "multicondition.json", "domain.csv",
    "noise_floor.json", "notes.md", "run_manifest.json",
}


def dump_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def fold_run(protocol, X, y, global_rows, splits, route, digest_value, permutation_id=None, groups=None):
    folds, predictions = [], []
    for fold_id, (tr, te) in enumerate(splits):
        p, sigma = cp.fit_predict_with_sigma(protocol, X[tr], y[tr], X[te])
        errors = np.abs(p - y[te])
        row = {"schema": "case04-fold/v2", "protocol_digest": digest_value, "route": route,
               "fold": int(fold_id), "train_global_indices": np.asarray(global_rows)[tr].astype(int).tolist(),
               "test_global_indices": np.asarray(global_rows)[te].astype(int).tolist(),
               "mae": float(errors.mean())}
        if len(te) > 1:
            row["r2"] = float(r2_score(y[te], p))
        if permutation_id is not None:
            row["permutation_id"] = int(permutation_id)
        if groups is not None:
            row["group_role"], row["group_id"] = groups
        folds.append(row)
        for j, (global_i, pred, sig, err) in enumerate(zip(np.asarray(global_rows)[te], p, sigma, errors)):
            item = {"route": route, "fold": int(fold_id), "row_index": int(global_i),
                    "prediction": float(pred), "sigma": float(sig), "absolute_error": float(err)}
            if permutation_id is not None:
                item["permutation_id"] = int(permutation_id)
            if groups is not None:
                item["group_role"], item["group_id"] = groups
            predictions.append(item)
    return folds, predictions


def summarize_predictions(folds, predictions, route):
    fr = [f for f in folds if f["route"] == route]
    pr = [p for p in predictions if p["route"] == route]
    errors = np.asarray([r["absolute_error"] for r in pr], float)
    maes = np.asarray([f["mae"] for f in fr], float)
    return {"n_scored": int(len(errors)), "n_folds": int(len(fr)),
            **cp.summarize_fold_mae(maes, errors), "fold_mae": maes.tolist()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, help="protocol.json; defaults to the author-equivalent v2 declaration")
    parser.add_argument("--final-dir", type=Path, default=FINAL)
    args = parser.parse_args(argv)
    final = args.final_dir if args.final_dir.is_absolute() else ROOT / args.final_dir
    final.mkdir(parents=True, exist_ok=True)
    unexpected = sorted(p.name for p in final.iterdir() if p.is_file() and p.name not in OUTPUT_ALLOWLIST)
    if unexpected:
        raise ValueError(f"candidate output directory contains non-v2 or grader artifacts: {unexpected}")
    default_protocol = Path(__file__).with_name("case04_protocol_v2_author.json")
    if not default_protocol.is_file():
        default_protocol = Path(__file__).parents[1] / "protocol-author-equivalent.v2.json"
    protocol_path = args.protocol or default_protocol
    protocol = cp.load_and_validate_protocol(protocol_path)
    pdigest = cp.canonical_protocol_digest(protocol)
    data = cp.load_public_inputs()
    X = cp.select_features(data["X"], protocol)
    y, train, test = data["y"], cp.training_rows_for_protocol(protocol, data["train"]), data["test"]
    for obsolete in ("protocol_binding.json", "calibration_folds.jsonl", "calibration_oof.csv", "calibration.json", "permutation_folds.jsonl", "falsification.json", "logo_folds.jsonl", "extrapolation.json", "multicondition_folds.jsonl", "multicondition.json", "run_manifest.json"):
        (final / obsolete).unlink(missing_ok=True)
    dump_json(final / "protocol.json", getattr(protocol, "declaration", protocol))

    # Blind full-train fit. Test responses are masked in the public master.
    p, s = cp.fit_predict_with_sigma(protocol, X[train], y[train], X[test])
    pd.DataFrame({"row_index": test, "prediction": p, "sigma": s}).sort_values("row_index").to_csv(final / "predictions_with_uncertainty.csv", index=False)

    # One declared shuffled KFold is reused for calibration and all target permutations.
    splits = cp.make_cv_splits(protocol, len(train))
    local_rows = np.arange(len(train), dtype=int)
    Xtr, ytr = X[train], y[train]
    cal_folds, cal_predictions = fold_run(protocol, Xtr, ytr, train, splits, "calibration", pdigest)
    cal = pd.DataFrame(cal_predictions)[["row_index", "prediction", "sigma"]].sort_values("row_index")
    # Align by global row index, independent of CSV row order.
    truth_map = dict(zip(train.astype(int), ytr.astype(float)))
    cal_stats = cp.summarize_calibration(cal.row_index.to_numpy(int), cal.prediction.to_numpy(float),
        cal.sigma.to_numpy(float), np.asarray([truth_map[int(i)] for i in cal.row_index], float))
    cov, err, risk = cal_stats["coverage"], cal_stats["errors"], {}
    for fraction in (.5, .75, .9):
        key = f"lowest_sigma_{int(fraction*100)}pct"
        n = max(1, int(math.floor(fraction * len(err))))
        item = next(v for v in cal_stats["risk_filter"][key] if v["n"] == n)
        risk[key] = item["mae"]

    # Paired response randomization; retain every prediction and metric per fold.
    perm_folds, perm_preds, fals_rows = [], [], []
    for permutation_id, target in enumerate(cp.permutation_targets(protocol, ytr)):
        folds, predictions = fold_run(protocol, Xtr, target, train, splits, "falsification", pdigest, permutation_id)
        perm_folds.extend(folds); perm_preds.extend(predictions)
        fals_rows.append({"permutation_id": permutation_id, "r2": float(np.mean([f["r2"] for f in folds])),
                          "mae": float(np.mean([f["mae"] for f in folds]))})
    pd.DataFrame(perm_preds)[["permutation_id", "row_index", "prediction", "sigma"]].to_csv(final / "permutation_predictions.csv", index=False)
    observed, null = fals_rows[0], fals_rows[1:]
    fals_stats = cp.summarize_permutation(observed, null, "maximum_null")

    # Candidate-native LOGO receipts from the two frozen released group vectors.
    logo_folds, logo_preds, logo_results = [], [], {}
    for role in protocol["logo"]["group_roles"]:
        groups = data["groups"][role]
        splits_logo = cp.make_logo_splits(train, groups)
        fr, pr = [], []
        for fold_id, (tr_global, te_global, group_id) in enumerate(splits_logo):
            pred, sigma = cp.fit_predict_with_sigma(protocol, X[tr_global], y[tr_global], X[te_global])
            errors = np.abs(pred - y[te_global])
            f = {"schema": "case04-fold/v2", "protocol_digest": pdigest, "route": "logo", "fold": fold_id,
                 "group_role": role, "group_id": int(group_id), "train_global_indices": tr_global.astype(int).tolist(),
                 "test_global_indices": te_global.astype(int).tolist(), "mae": float(errors.mean())}
            fr.append(f); logo_folds.append(f)
            for idx, value, sd, e in zip(te_global, pred, sigma, errors):
                pr.append({"route": "logo", "group_role": role, "group_id": int(group_id), "fold": fold_id,
                           "row_index": int(idx), "prediction": float(value), "sigma": float(sd), "absolute_error": float(e)})
        logo_preds.extend(pr)
        fold_maes = [r["mae"] for r in fr]
        group_summary = cp.summarize_group_mae(fold_maes, [len([p for p in pr if p["group_id"] == r["group_id"]]) for r in fr])
        logo_results[role] = {"n_groups": len(fr), "n_scored": len(pr), "macro_group_mae": group_summary["macro_group_mae"],
            "macro_group_sem": group_summary["macro_group_sem"], "micro_row_mae": group_summary["micro_row_mae"],
            "interpretation": "macro is the unweighted mean of held-group MAEs; micro weights each row equally"}
    pd.DataFrame(logo_preds)[["group_role", "row_index", "prediction", "sigma"]].to_csv(final / "logo_predictions.csv", index=False)

    # Two multi-condition routes share the same frozen CV settings.
    rxn = data["groups"]["reaction"]
    counts = pd.Series(rxn[train]).value_counts()
    singleton_rows = train[np.asarray([counts.get(rxn[i], 0) == 1 for i in train])]
    multicond_folds, multicond_preds, multicond_summary = [], [], {}
    for route, rows in (("all_train", train), ("single_reaction_only", singleton_rows)):
        local = np.asarray([int(np.where(rows == i)[0][0]) for i in rows])
        splits_mc = cp.make_cv_splits(protocol, len(rows))
        folds, preds = fold_run(protocol, X[rows], y[rows], rows, splits_mc, route, pdigest)
        multicond_folds.extend(folds); multicond_preds.extend(preds)
        summary = summarize_predictions(folds, preds, route)
        summary["n_rows"] = len(rows)
        multicond_summary[route] = summary
    single_predictions = pd.DataFrame(multicond_preds)
    single_predictions[single_predictions.route == "single_reaction_only"][["row_index", "prediction", "sigma"]].to_csv(final / "multicondition_oof.csv", index=False)

    scores, threshold, _ = cp.compute_ad(protocol, X[train], X[test])
    flags = scores > threshold
    pd.DataFrame({"row_index": test, "score": scores, "out_of_domain": flags}).sort_values("row_index").to_csv(final / "domain.csv", index=False)

    # Published repeatability is copied in the public package and never read from gold here.
    pair_frame = pd.read_csv(ASSETS / "S12_replicate_barrier_pairs.csv")
    noise_stats = cp.summarize_replicate_pairs(pair_frame["g_kcal_mol"].dropna().astype(str).tolist())
    dump_json(final / "noise_floor.json", {"precision_claim": "no_sub_0.1_kcal_mol_claim",
        "reasoning": "No sub-0.1 kcal/mol precision claim is made; replicate repeatability alone does not establish model accuracy."})
    # Interpret the scientific outcomes once; raw predictions determine these metrics.
    notes = (f"# Uncertainty and applicability assessment\n\n"
        f"Training OOF MAE is {cal_stats['overall_oof_mae']:.6g} kcal/mol. Interval coverage is {cov}; "
        f"MAE in floor-sized lowest-sigma subsets is {risk}. Selective risk is measured on training OOF predictions only.\n\n"
        f"Identity mean-fold R2 is {fals_stats['true_r2']:.6g}; null mean/max are "
        f"{np.mean(fals_stats['r2_permutations']):.6g}/{max(fals_stats['r2_permutations']):.6g}. "
        f"The plus-one value is {fals_stats['r2_pvalue_plus_one']:.6g}; separation from the maximum null is "
        f"{fals_stats['r2_separation_maximum_null']:.6g}. Every declared draw is included.\n\n"
        f"Held-group MAE summaries are {logo_results}. Macro weights groups equally and micro weights rows equally; "
        f"ordinary shuffled CV does not establish unseen-group transferability.\n\n"
        f"All-training versus reaction-singleton fold results are {multicond_summary}; these assess sensitivity "
        f"to repeated conditions without requiring a favorable direction.\n\n"
        f"The training LOO applicability cutoff is {threshold:.6g}; {int(flags.sum())} of {len(test)} test rows exceed it. "
        f"Distance flags mark feature-space extrapolation, not a guarantee of error control.\n\n"
        f"Source replicate differences are {noise_stats['pair_differences_kcal_mol']} kcal/mol. "
        f"The largest within-pair IID 95% t mean-CI half-width is {noise_stats['uniform_bound_kcal_mol']:.6g} kcal/mol. "
        f"These pairs do not establish single-measurement noise or model accuracy.\n")
    (final / "notes.md").write_text(notes)

    print(json.dumps({"status": "EXECUTED", "protocol_digest": pdigest, "n_features": X.shape[1], "cv_folds": len(splits),
        "n_permutations": len(null), "logo_groups": {r: v["n_groups"] for r, v in logo_results.items()},
        "final_dir": str(final)}, indent=2))


if __name__ == "__main__":
    main()
