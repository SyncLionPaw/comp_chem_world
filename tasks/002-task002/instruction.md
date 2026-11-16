# Mechanistic features and experimental barrier prediction

## Background

Assess whether mechanistic descriptors improve experimental SNAr barrier prediction. All 443 target labels are public; the frozen 89-row test set is not blind.

## Task

Identify six published feature sets from descriptor composition and compare a TS-informed hybrid, a no-TS model, a direct computed barrier, a train-only linear correction and a training-mean baseline on the frozen 354/89 split. Quantify Full/No TS differences over five paired seeds; no positive TS gain is required.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas, scikit-learn, SciPy. Do not install additional packages or fetch dependencies from the network.

- Exclude experimental targets and target-derived values from features, preprocessing and tuning. Fit learned preprocessing within training folds; tune by shuffled MAE CV, then refit once on all training rows rather than averaging fold models.
- Match estimator, preprocessing, search grid, budget, folds and test rows across the five-seed Full/No TS comparison. Report MAE(No TS) − MAE(Full) and its variation.
- The preferred hybrid test MAE must be ≤1.10 kcal/mol, at least 1.0 kcal/mol below the declared direct barrier and below the training-mean baseline. Keep the frozen split for all five primary models.
- Establish feature-set identities from descriptor evidence, not MAE similarity. Discuss uncertainty about historical appended barrier descriptors; a declared scientifically justified alternative barrier is allowed. Supplementary splits must disclose population, disjoint indices, purpose, metrics and frozen-test overlap, and cannot replace the primary comparison.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Published records, benchmark data and task-specific inputs. |

```text
/app/assets/                         released matrices, targets and split indices
/app/final/
  model_comparison.csv
  feature_set_map.json
  test_predictions.csv               primary hybrid predictions
  model_spec.json
  protocol.json
  notes.md
  ablation-v2/
    ablation_protocol.json
    feature_diff.json
    paired_ablation.csv
    paired_summary.json
    cv_splits_seed<seed>.json
    predictions_full_seed<seed>.csv
    predictions_no_ts_seed<seed>.csv
```

```csv
# model_comparison.csv
model,feature_set_label,source_matrix_file,protocol,seed,n_train,n_test,mae_kcal_mol,rmse_kcal_mol,r2,prediction_file,is_preferred
# all prediction files
row_index,true_experimental_barrier,predicted_barrier
# ablation-v2/paired_ablation.csv
seed,full_mae_kcal_mol,no_ts_mae_kcal_mol,delta_mae_no_ts_minus_full_kcal_mol
```


Use normalized relative `prediction_file` paths. The five `model` identifiers are `direct_barrier,linear_correction,mean_baseline,no_ts,hybrid`; all are required irrespective of descriptive `is_preferred`. Each model/seed pair is unique. When repeated, primary rows use their arm seed; baseline rows use `protocol.primary_seed` (default hybrid seed). One baseline row per model is sufficient. Numerical agreement tolerance is 1e-7.

- **`feature_set_map.json`**: keys `Full,No TS,Small,Surface,Traditional,Only TS`, directly or under `labels`. Each supplies `source_matrix_file,feature_columns,appended_barrier_uncertainty` (boolean), and `evidence.descriptor_groups` partitioning columns into `transition_state,electrostatic,surface_steric,other`. Explain the mapping and uncertainty in the evidence/notes.
- **`model_spec.json`**: `schema: case02-model-spec/v1`, `arms: {hybrid: ..., no_ts: ...}` and `baselines`. Each arm declares `matrix_file,feature_columns,estimator:{family,parameter_grid},preprocessing:{scaler,fit_scope},target_transform,seed,cv:{n_splits,shuffle,random_state,scoring},cv_folds:[{train_local,validation_local}],budget:{candidate_parameterizations}`. Use 2–10 shuffled folds and MAE; budget equals grid cardinality. Baseline declarations `direct_barrier,linear_correction` each contain `source_matrix_file,column`; correction adds `family: OLS|Ridge,alpha`. Both use the same public `activation_energy_*` column.
- **Supported models**: Ridge (alpha≥0), KernelRidge (alpha>0; `linear,rbf,poly,sigmoid,cosine,laplacian`, optional `gamma,degree,coef0`), or GPR/GaussianProcessRegressor (alpha≥0; `ConstantKernel*Matern+WhiteKernel`, declared initial values/bounds, `matern_nu`, optional `normalize_y`, optimizer null or `fmin_l_bfgs_b`). Grids are parameter-to-list objects or explicit parameter dictionaries; GPR grid keys are `alpha,matern_nu`. GPR kernel components may use direct values/bounds, `{initial,bounds}`, or named sklearn components `constant_kernel,matern,white_kernel`. Scaling is `standard|none`; target transform is `none` or GPR `normalize_y`. Complete C- or Fortran-layout GPR fits are equivalent replay options, without mixing their predictions.
- **`protocol.json`**: `train_indices,test_indices,train_test_disjoint,target_excluded_from_features,preprocessing_fit_scope:training_folds_only,protocol_id,search_budget:{same_frozen_split,same_cv_folds,per_arm_candidate_parameterizations:{hybrid,no_ts}}`. One integer may replace the per-arm budget object. Declare any supplementary comparisons here.
- **`ablation_protocol.json`**: five distinct integer `seeds`, frozen `train_indices,test_indices`, `preprocessing_fit_scope:training_fold_only,test_used_for_selection:false`, `cv:{folds,shuffle:true,same_splits_per_seed_across_arms:true,selection_metric:MAE}`, and a `case02-model-spec/v1` `model_spec` with arms `Full,No TS`. These arms use the same structure as above, replacing fixed seed/folds with `seed_policy:paired_seed` and CV `{n_splits,shuffle:true,random_state_policy:seed,scoring:MAE}`. Split files contain folds `{train_positions,validation_positions}`, as an array or under `folds`; positions refer to the ordered 354-row pool. Frozen indices may alternatively be under `frozen_indices` using `train,test` or `train_indices,test_indices`. Duplicate declarations must agree.
- **`feature_diff.json`**: `full_columns,no_ts_columns,full_only_columns,no_ts_only_columns,shared_column_count`. **`paired_summary.json`**: `seed_count,seeds,delta_mean_kcal_mol,delta_std_kcal_mol,delta_min_kcal_mol,delta_max_kcal_mol,full_better_for_all_seeds`. Report sample SD (population SD is also accepted). Each paired prediction file covers all 89 test rows. CV aliases `MAE,mean_absolute_error,neg_mean_absolute_error` express minimization of fold MAE; explanatory notes must not change the protocol.

Model selection minimizes equal-fold mean MAE and breaks ties by first candidate in declared grid order; dictionary axes retain their declaration order. Standard scaling uses training population SD (zero-variance scale 1). GPR target_transform must agree with normalize_y.
