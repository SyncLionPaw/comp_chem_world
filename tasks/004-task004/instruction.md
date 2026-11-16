# Uncertainty calibration and applicability domain

## Background

Assess uncertainty, transferability, risk filtering and experimental repeatability for SNAr predictions. The frozen split contains 354 training and 89 test reactions; test targets are masked, but overlap with public barrier values limits claims of blind validation.

## Task

Declare one reproducible model protocol before examining test errors. Produce test predictions, training out-of-fold (OOF) predictions and response-permutation controls, substrate/nucleophile leave-one-group-out (LOGO) predictions, and a single-condition comparison. Interpret the observed calibration, controls, applicability and precision limits. Negative or non-improving results are valid.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas, scikit-learn, SciPy. Do not install additional packages or fetch dependencies from the network.

- Use local CPU, with fitting/tuning confined to frozen training targets. In `protocol.json`, declare `features.basis` as `s120-drop-row-index-plus-qhbarrier/v1` and `cv.row_order` as `frozen_vector` or `global_index_ascending`; use `s119.npy` in that declared training order and `s118.npy` for test.
- Select 1–34 unique feature indices: 0–32 are the numeric columns of `s120.csv` after removing its first row-index column; index 33 is `master_s115_blindarm.csv:activation_energy_qh_grimme_ts`. Group vectors are `s117.npy` (substrate), `s114.npy` (nucleophile), `s113.npy` (reaction). File prefix is `SC-012-D0SC04896H-`.
- Use one shuffled KFold repeat for identity/permutation OOF. Initialize `RandomState(seed)` once: ID0 uses ordered original targets, IDs1–N use consecutive permutation draws. Refit every fold for every ID. Hold out each training group once per LOGO role. The single-condition route retains reaction groups occurring once in the training pool, preserving row order; identity OOF already represents the all-training comparison.
- Fit scaling on each fit's training data using population SD (zero-variance scale 1). GPR sigma includes WhiteKernel and is rescaled to target units. AD uses selected features, training-only scaling and RMS-Euclidean distances; its cutoff is the linear quantile of training leave-one-out nearest/k-nearest mean distances, with only strictly larger scores flagged.
- Interpret OOF coverage at z=1,1.96,2,2.576 and MAE in the lowest-sigma 50%,75%,90% (floor-sized subsets sorted by sigma, then row index). True/null R² and MAE are equal-fold means; one-sided plus-one p includes ties: `(1+count(null_R²>=true_R²))/(N+1)`. Separation may use true R² minus mean or maximum null R². LOGO macro MAE weights groups equally, micro MAE weights rows equally; SEM is sample group SD/√group count. Route comparisons use fold-MAE mean/sample SD/SEM and row-micro MAE; singleton R² is undefined.
- Interpret the four S12 replicate pairs without equating repeatability with model accuracy. A numeric precision claim below 0.1 kcal/mol needs an explicit within-pair IID assumption and a 95% replicate-mean interval bound covering all four Student-t half-widths `12.7062047361747*abs(pair_difference)/2`; the claimed precision must be at least that bound. This does not establish single-observation noise or model accuracy.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Published records, benchmark data and task-specific inputs. |

The protocol example below illustrates the required structure, not prescribed scientific choices.

```text
/app/assets/                  frozen inputs and S12 replicate pairs
/app/final/
  protocol.json
  predictions_with_uncertainty.csv
  permutation_predictions.csv
  logo_predictions.csv
  multicondition_oof.csv
  domain.csv
  noise_floor.json
  notes.md
```

```json
{
  "features": {"basis": "s120-drop-row-index-plus-qhbarrier/v1", "indices": [0, 1, 33]},
  "model": {
    "kernel": {"family": "rbf", "constant_value": 1.0, "constant_bounds": "fixed",
      "length_scale": 1.0, "length_scale_bounds": "fixed",
      "noise_level": 0.1, "noise_level_bounds": "fixed"},
    "alpha": 1e-10, "optimizer": null, "n_restarts_optimizer": 0, "seed": 42
  },
  "preprocessing": {"feature_scaling": "standard", "target_scaling": "standard"},
  "cv": {"n_splits": 5, "seed": 42, "row_order": "global_index_ascending"},
  "permutation": {"count": 10, "seed": 42},
  "ad": {"rule": "nearest_neighbor", "scaling": "standard", "quantile": 0.95}
}
```

```csv
# predictions_with_uncertainty.csv: 89 test rows
row_index,prediction,sigma
# permutation_predictions.csv: every training row, each ID 0..N
permutation_id,row_index,prediction,sigma
# logo_predictions.csv: every training row, each group role
group_role,row_index,prediction,sigma
# multicondition_oof.csv: single-reaction-only training rows
row_index,prediction,sigma
# domain.csv: 89 test rows
row_index,score,out_of_domain
```


Supported protocol choices are GPR with RBF or Matern (`matern_nu:0.5|1.5|2.5`); positive kernel values with `fixed` or positive increasing bounds; alpha≥0; optimizer null or `fmin_l_bfgs_b`; 0–5 restarts; `none|standard` feature/target scaling; 2–20 folds; 10–100 permutations; unsigned 32-bit seeds. AD is `nearest_neighbor` (k=1) or `knn_mean_distance` (declare k=2–10), `none|standard` scaling and quantile 0.80–0.99. GPR uses `normalize_y:false`. Optional `target`/`groups` assertions must match frozen sources; repeated scientific choices must agree.

Cover every keyed population exactly once. CSV order is free; predictions/sigma are finite, sigma positive, flags Boolean or 0/1, and integer IDs exact numeric integers excluding booleans. Use unique JSON keys/CSV headings. Do not submit held-out targets, errors or metrics. Fold receipts, repeated source bindings and separate statistical summaries are unnecessary.

`noise_floor.json` contains `precision_claim` (a numeric kcal/mol precision or `no_sub_0.1_kcal_mol_claim`) and `reasoning`. A justified numeric claim adds `precision_justification:{confidence:0.95,claimed_bound_kcal_mol,explanation}`, explicitly stating within-pair IID. In `notes.md`, explain OOF coverage/selective risk, permutation controls, both LOGO roles, single-condition results and AD/transferability limits. Report scientific results once; optional annotations must not contradict the observations.
