# 机制特征与实验能垒预测

## 背景

研究机制描述符能否改善实验 SNAr 能垒预测。443 个实验标签均已公开，冻结的 89 行测试集不是盲测。

## 任务

依据描述符组成识别六种已发表特征集，在冻结 354/89 划分上比较含 TS 的混合模型、无 TS 模型、直接计算能垒、仅训练集拟合的线性校正及训练均值基线。用五个配对种子量化 Full/No TS 差异，不要求 TS 有正向收益。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas、scikit-learn、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 实验目标及其派生值不得参与特征、预处理或调参。学习型预处理在训练折内拟合；以打乱折的 MAE 调参，再用全部训练行重拟合，不平均折模型。
- 五种子 Full/No TS 比较须匹配估计器、预处理、搜索网格、预算、折和测试行。报告 MAE(No TS) − MAE(Full) 及其变化。
- 首选混合模型测试 MAE 须 ≤1.10 kcal/mol，比声明的直接能垒至少低 1.0 kcal/mol，并优于训练均值基线。五类主比较均使用冻结划分。
- 用描述符证据而非 MAE 相近程度识别特征集。说明历史附加能垒描述符的不确定性；可声明科学有效的替代能垒。补充划分须披露总体、互斥索引、目的、指标及冻结测试重叠，不能替代主比较。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 已发表记录、基准数据与本题输入。 |

```text
/app/assets/                         公开矩阵、目标及划分索引
/app/final/
  model_comparison.csv
  feature_set_map.json
  test_predictions.csv               主混合模型预测
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


`prediction_file` 使用规范相对路径。五个 `model` 标识为 `direct_barrier,linear_correction,mean_baseline,no_ts,hybrid`，不因描述性的 `is_preferred` 而免除。同一模型／种子组合唯一；有重复时主比较使用对应 arm 的 seed，基线使用 `protocol.primary_seed`（默认 hybrid seed）。每种基线只需一行。数值一致性容差为 1e-7。

- **`feature_set_map.json`**：六个键 `Full,No TS,Small,Surface,Traditional,Only TS` 可直接置于顶层或 `labels` 下。每项含 `source_matrix_file,feature_columns,appended_barrier_uncertainty`（布尔值），以及将列分为 `transition_state,electrostatic,surface_steric,other` 的 `evidence.descriptor_groups`。在证据／说明中解释映射及不确定性。
- **`model_spec.json`**：`schema: case02-model-spec/v1`，含 `arms:{hybrid:...,no_ts:...}` 及 `baselines`。每臂声明 `matrix_file,feature_columns,estimator:{family,parameter_grid},preprocessing:{scaler,fit_scope},target_transform,seed,cv:{n_splits,shuffle,random_state,scoring},cv_folds:[{train_local,validation_local}],budget:{candidate_parameterizations}`。使用 2–10 个打乱折及 MAE，预算等于网格基数。基线 `direct_barrier,linear_correction` 各含 `source_matrix_file,column`；校正另含 `family:OLS|Ridge,alpha`，两者引用同一公开 `activation_energy_*` 列。
- **可用模型**：Ridge（alpha≥0）、KernelRidge（alpha>0；核为 `linear,rbf,poly,sigmoid,cosine,laplacian`，可选 `gamma,degree,coef0`），或 GPR/GaussianProcessRegressor（alpha≥0；核为 `ConstantKernel*Matern+WhiteKernel`，声明初值／边界及 `matern_nu`，可选 `normalize_y`，optimizer 为 null 或 `fmin_l_bfgs_b`）。网格可为参数→列表或显式参数字典列表；GPR 网格键为 `alpha,matern_nu`。核分量可用直接数值／边界、`{initial,bounds}` 或 sklearn 命名分量 `constant_kernel,matern,white_kernel`。缩放为 `standard|none`，目标变换为 `none` 或 GPR `normalize_y`。完整的 C／Fortran 布局 GPR 拟合均可，不拼接不同拟合的预测。
- **`protocol.json`**：`train_indices,test_indices,train_test_disjoint,target_excluded_from_features,preprocessing_fit_scope:training_folds_only,protocol_id,search_budget:{same_frozen_split,same_cv_folds,per_arm_candidate_parameterizations:{hybrid,no_ts}}`。每臂预算对象也可用一个整数代替。补充比较在此声明。
- **`ablation_protocol.json`**：五个不同整数 `seeds`、冻结 `train_indices,test_indices`、`preprocessing_fit_scope:training_fold_only,test_used_for_selection:false`、`cv:{folds,shuffle:true,same_splits_per_seed_across_arms:true,selection_metric:MAE}`，以及 `schema:case02-model-spec/v1`、含 `Full,No TS` 两臂的 `model_spec`。臂结构同上，以 `seed_policy:paired_seed` 及 CV `{n_splits,shuffle:true,random_state_policy:seed,scoring:MAE}` 代替固定种子／折。划分文件为 `{train_positions,validation_positions}` 折数组或置于 `folds` 下，位置对应有序 354 行训练池。冻结索引也可置于 `frozen_indices`，使用 `train,test` 或 `train_indices,test_indices`；重复声明须一致。
- **`feature_diff.json`**：`full_columns,no_ts_columns,full_only_columns,no_ts_only_columns,shared_column_count`。**`paired_summary.json`**：`seed_count,seeds,delta_mean_kcal_mol,delta_std_kcal_mol,delta_min_kcal_mol,delta_max_kcal_mol,full_better_for_all_seeds`。报告样本 SD（也接受总体 SD）。每个配对预测文件覆盖全部 89 行。CV 别名 `MAE,mean_absolute_error,neg_mean_absolute_error` 均表示最小化折 MAE；附注不得改变协议。

模型选择最小化等权折 MAE 均值，并列时取声明网格中的首个候选；字典轴保留声明顺序。标准缩放使用训练总体 SD（零方差 scale=1），GPR 的 target_transform 须与 normalize_y 一致。
