# Low-data model and representation comparison

## Background

Compare mechanistic, no-TS and structural reaction-difference representations as training data become scarce. All 443 experimental labels are public; the frozen holdout is not blind. Published solvent PC1–PC5 are fixed descriptors and must not be refit.

## Task

Build paired learning curves at two or more increasing training sizes, with at least 20 repeats per size. Compare mechanistic MAE with each alternative, quantify conditional repeat uncertainty and assess whether a crossover is supported. No arm must win and no crossover is required; published Fig. 8 is auxiliary context, not a target error curve.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas, scikit-learn, SciPy. Do not install additional packages or fetch dependencies from the network.

- Use `exp_activation_energy` in `SC-012-D0SC04896H-s115.csv`, training pool `s119.npy` and test indices `s118.npy` (354/89). Representation sources are `s120.csv` (mechanistic), `s138.csv` (no_ts), `s131.csv` (fingerprint), with prefix `SC-012-D0SC04896H-`.
- Every repeat shares its ordered training subset and all 89 test rows across arms. Below full-pool size, subsets must be distinct; full-pool repeats use the whole pool.
- Fit learned preprocessing and model selection only within each sampled training subset and inner folds. Match estimator family, grid cardinality, CV folds, shuffle seed and MAE objective across arms. Record enough detail to reproduce every fit.
- Compute comparator MAE minus mechanistic MAE on paired repeats. Empirical 95% repeat intervals describe variation conditional on this fixed holdout, not population uncertainty. Interpret mean sign changes separately from intervals strictly excluding zero.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Published records, benchmark data and task-specific inputs. |

```text
/app/assets/                  released matrices, labels and frozen indices
/app/final/
  predictions.csv
  learning_curves.csv
  splits.json
  paired_summary.json
  crossover.json
  protocol.json
  notes.md
```

```csv
# predictions.csv
representation,source_matrix_file,paired_split_id,n_train,repeat_index,row_index,y_true_kcal_mol,y_pred_kcal_mol
# learning_curves.csv
representation,source_matrix_file,n_train,repeat_index,split_kind,paired_split_id,mae_kcal_mol,rmse_kcal_mol
```


Each `paired_split_id` links the same size/repeat across files; repeat indices start at 0. `split_kind` is `test` or `fixed_test_resampled_train`, both referring to the frozen test set. Numerical agreement tolerance is 1e-8.

- **`splits.json`**: `train_pool_indices,test_indices,sizes,repeats_per_size,seed_policy,records`. Each record is `{paired_split_id,n_train,repeat_index,seed,train_indices,test_indices}`. Preserve index order.
- **`protocol.json`**: `case_id:case-03-low-data-model-selection`, matching `sizes,repeats_per_size,seed_policy`, `scored_representations` listing `mechanistic,no_ts,fingerprint` exactly once, `comparison_design:controlled_representation` (required for automatic scoring; `model_selection_combination` is scientifically allowed but outside the integrated independent-refit scope and yields `REVIEW_REQUIRED` rather than a pass/fail reward), `model_spec`, `same_sampled_training_indices_across_representations:true,same_frozen_test_set_across_representations_and_repeats:true`, `tuning_budget:{same_across_scored_arms:true,candidate_models_per_arm,inner_folds,description}`, `learned_preprocessing:{fit_within_training_subset:true,steps}`, `interval_scope:training_subset_repeat_conditional_on_frozen_test_set`. The seed policy is a nonempty string/object and must agree across files.
- **`model_spec`**: `schema:case03-model-spec/v1`, arms `mechanistic,no_ts,fingerprint`; each declares `feature_columns,scaler,pca,target_scaler,estimator:{family,parameter_grid},cv:{n_splits,shuffle:true,random_state,scoring:neg_mean_absolute_error}`. Grids are parameter-to-list objects or explicit parameter dictionaries. Use 2–10 folds and integer CV seed. Supported models are Ridge (alpha≥0), KernelRidge (alpha>0; kernels `linear,rbf,poly,sigmoid,cosine,laplacian,additive_chi2,chi2`) or GPR (alpha≥0, optional `normalize_y`, with the fixed kernel and optimizer below). Scaling is `none|standard`; PCA is null or a training-only fit with integer `n_components,random_state`. Optional PCA parameters are `copy,whiten,svd_solver,tol,iterated_power,n_oversamples,power_iteration_normalizer`; solvers are `auto,full,arpack,randomized,covariance_eigh` (default `randomized`).
- **`paired_summary.json`**: array of `{n_train,comparator,difference_definition:comparator_mae_minus_mechanistic_mae,mean,repeat_differences,conditional_repeat_percentile_95_interval}`. Use the empirical 2.5th/97.5th percentiles.
- **`crossover.json`**: `comparisons.no_ts` and `comparisons.fingerprint`, each `{status,basis,training_size_bracket,supporting_summary_rows,reason}`. Status is `observed`, `no_crossover_in_tested_range` or `inconclusive`; basis is `mean` (strict paired-mean sign change) or `interval` (adjacent intervals strictly on opposite sides of zero). An observed bracket spans adjacent tested sizes; otherwise it is null. Cite supporting sizes as `n=<size>` in increasing order (all sizes for a non-observed result), and explain the basis and conditional scope.

In `notes.md`, interpret the measured curves, uncertainty and methodological limits. Optional `scientific_disclosures` can describe input provenance/limitations; optional `software_versions` supplies nonempty `python,numpy,scikit_learn` strings. Additional scientifically relevant results are welcome.

Select minimum equal-fold mean MAE, breaking ties by grid order with parameter names sorted. Explicit candidate lists must enumerate a full Cartesian grid. Standard scaling uses training population SD (zero-variance scale 1). GPR uses sklearn's fixed default ConstantKernel(1)*RBF(1), optimizer=None; its grid parameters are alpha and normalize_y.
