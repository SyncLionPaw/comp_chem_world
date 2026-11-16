# 小数据模型与表示比较

## 背景

比较数据稀缺时机制特征、无 TS 特征和结构反应差分指纹的预测表现。443 个实验标签均已公开，冻结留出集不是盲测。已发布溶剂 PC1–PC5 为固定描述符，不重拟合。

## 任务

至少选两个递增训练规模，每个规模至少做 20 次配对重复，构建学习曲线。比较各替代表示与机制表示的 MAE，量化条件重复不确定度，判断是否支持交叉。不要求任何表示胜出或出现交叉；文献 Fig. 8 仅作辅助背景，不是必须贴合的误差曲线。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas、scikit-learn、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 目标为 `SC-012-D0SC04896H-s115.csv` 的 `exp_activation_energy`，训练池为 `s119.npy`，测试索引为 `s118.npy`（354/89）。表示来源为 `s120.csv`（mechanistic）、`s138.csv`（no_ts）、`s131.csv`（fingerprint），文件前缀均为 `SC-012-D0SC04896H-`。
- 每次重复中三臂共用有序训练子集及全部 89 个测试行。小于全池的子集不得重复；全池重复使用完整训练池。
- 学习型预处理与模型选择仅在抽样训练子集及内层折中拟合。三臂匹配估计器族、网格基数、CV 折、打乱种子和 MAE 目标，记录足以复现每次拟合的细节。
- 配对计算 comparator MAE 减机制 MAE。经验 95% 重复区间只描述固定留出集条件下的变化，不是总体不确定度。区分均值变号与区间严格排除零的证据。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 已发表记录、基准数据与本题输入。 |

```text
/app/assets/                  公开矩阵、标签及冻结索引
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


`paired_split_id` 在各文件中关联同一规模／重复，重复编号从 0 开始。`split_kind` 为 `test` 或 `fixed_test_resampled_train`，均指冻结测试集。数值一致性容差为 1e-8。

- **`splits.json`**：`train_pool_indices,test_indices,sizes,repeats_per_size,seed_policy,records`。每条记录为 `{paired_split_id,n_train,repeat_index,seed,train_indices,test_indices}`，保留索引顺序。
- **`protocol.json`**：`case_id:case-03-low-data-model-selection`，与划分一致的 `sizes,repeats_per_size,seed_policy`，包含 `mechanistic,no_ts,fingerprint` 各一次的 `scored_representations`，`comparison_design:controlled_representation|model_selection_combination`、`model_spec`、`same_sampled_training_indices_across_representations:true,same_frozen_test_set_across_representations_and_repeats:true`、`tuning_budget:{same_across_scored_arms:true,candidate_models_per_arm,inner_folds,description}`、`learned_preprocessing:{fit_within_training_subset:true,steps}`、`interval_scope:training_subset_repeat_conditional_on_frozen_test_set`。种子策略为非空字符串／对象，跨文件保持一致。
- **`model_spec`**：`schema:case03-model-spec/v1`，含 `mechanistic,no_ts,fingerprint` 三臂；每臂声明 `feature_columns,scaler,pca,target_scaler,estimator:{family,parameter_grid},cv:{n_splits,shuffle:true,random_state,scoring:neg_mean_absolute_error}`。网格为参数→列表或显式参数字典列表，使用 2–10 折及整数 CV 种子。支持 Ridge（alpha≥0）、KernelRidge（alpha>0；核为 `linear,rbf,poly,sigmoid,cosine,laplacian,additive_chi2,chi2`）或 GPR（alpha≥0，可选 `normalize_y`，核与优化器按下文的固定设置）。缩放为 `none|standard`；PCA 为空或仅用训练数据拟合，声明整数 `n_components,random_state`。可选 PCA 参数为 `copy,whiten,svd_solver,tol,iterated_power,n_oversamples,power_iteration_normalizer`；solver 为 `auto,full,arpack,randomized,covariance_eigh`（默认 `randomized`）。
- **`paired_summary.json`**：数组，每项为 `{n_train,comparator,difference_definition:comparator_mae_minus_mechanistic_mae,mean,repeat_differences,conditional_repeat_percentile_95_interval}`，区间取经验 2.5／97.5 百分位数。
- **`crossover.json`**：含 `comparisons.no_ts`、`comparisons.fingerprint`，每项为 `{status,basis,training_size_bracket,supporting_summary_rows,reason}`。状态为 `observed`、`no_crossover_in_tested_range` 或 `inconclusive`；依据为 `mean`（配对均值严格变号）或 `interval`（相邻区间严格位于零点两侧）。observed 的 bracket 为相邻测试规模，其他状态为 null。支持规模按升序写为 `n=<size>`，未观察到交叉时列出全部规模；解释依据及条件性范围。

在 `notes.md` 中解释实测曲线、不确定度及方法限制。可选 `scientific_disclosures` 说明来源／限制；可选 `software_versions` 含非空 `python,numpy,scikit_learn` 字符串。可补充有科学意义的其他结果。

选择等权折 MAE 均值最小者，并列时按参数名排序后的网格顺序选首项；显式候选列表须覆盖完整笛卡尔网格。标准缩放使用训练总体 SD（零方差 scale=1）。GPR 使用 sklearn 固定默认 ConstantKernel(1)*RBF(1)、optimizer=None，网格参数为 alpha 和 normalize_y。
