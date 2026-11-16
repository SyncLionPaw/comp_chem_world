# 不确定度校准与适用域

## 背景

评估 SNAr 预测的不确定度、迁移性、风险筛选和实验重复性。冻结划分含 354 个训练反应、89 个测试反应；测试目标已遮蔽，但与公开能垒值的重叠限制了盲测主张。

## 任务

在查看测试误差前声明一个可复现模型协议，完成测试预测、训练折外（OOF）预测与响应置换对照、底物／亲核试剂留组（LOGO）预测及单条件比较，解释校准、对照、适用性和精度限制。否定或未改善的结果同样有效。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas、scikit-learn、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 使用本地 CPU，拟合／调参限于冻结训练目标。在 `protocol.json` 中声明 `features.basis` 为 `s120-drop-row-index-plus-qhbarrier/v1`，并将 `cv.row_order` 声明为 `frozen_vector` 或 `global_index_ascending`；训练行按该顺序读取 `s119.npy`，测试行为 `s118.npy`。
- 选择 1–34 个不同特征索引：0–32 为 `s120.csv` 去掉首个行索引列后的数值列，33 为 `master_s115_blindarm.csv:activation_energy_qh_grimme_ts`。分组向量为 `s117.npy`（底物）、`s114.npy`（亲核试剂）、`s113.npy`（反应）。文件前缀为 `SC-012-D0SC04896H-`。
- identity／置换 OOF 使用一次打乱 KFold。只初始化一次 `RandomState(seed)`：ID0 使用有序原目标，ID1–N 为连续置换抽样，每个 ID 重拟合全部折。LOGO 在各角色上逐组留出训练行。单条件路线仅保留训练池中出现一次的反应组，保持行顺序；identity OOF 已代表全训练比较。
- 缩放仅使用每次拟合的训练均值和总体 SD（零方差 scale=1）。GPR sigma 包含 WhiteKernel 并换回目标单位。AD 使用所选特征、训练内缩放及 RMS 欧氏距离；阈值为训练留一最近／k 近邻平均距离的线性分位数，仅严格超过阈值时标记域外。
- 解释 z=1、1.96、2、2.576 的 OOF 覆盖率，以及最低 sigma 50%、75%、90% 子集的 MAE（按 sigma、行索引排序，子集大小向下取整）。真／置换 R² 和 MAE 为等权折均值；单侧 plus-one p 含并列：`(1+count(null_R²>=true_R²))/(N+1)`。separation 可用真 R² 减置换均值或最大值。LOGO macro MAE 等权分组、micro MAE 等权行，SEM 为分组样本 SD/√组数。路线比较使用折 MAE 均值／样本 SD／SEM 及行 micro MAE；单行组 R² 无定义。
- 解释四组 S12 重复对，不能将重复性等同模型准确度。低于 0.1 kcal/mol 的数值精度主张须明确组内 IID 假设，95% 重复均值区间上界覆盖全部四个 Student-t 半宽 `12.7062047361747*abs(pair_difference)/2`，且声明精度不小于该上界；这不证明单次观测噪声或模型准确度。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 已发表记录、基准数据与本题输入。 |

下例说明协议结构，不指定应选择的科学方案。

```text
/app/assets/                  冻结输入及 S12 重复对
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
# predictions_with_uncertainty.csv: 89 个测试行
row_index,prediction,sigma
# permutation_predictions.csv: ID 0..N 各自覆盖全部训练行
permutation_id,row_index,prediction,sigma
# logo_predictions.csv: 每类分组均覆盖全部训练行
group_role,row_index,prediction,sigma
# multicondition_oof.csv: 只出现一次的反应组训练行
row_index,prediction,sigma
# domain.csv: 89 个测试行
row_index,score,out_of_domain
```


协议支持：GPR 的 RBF 或 Matern 核（`matern_nu:0.5|1.5|2.5`）；正核参数及 `fixed` 或正数递增边界；alpha≥0；optimizer 为 null 或 `fmin_l_bfgs_b`；0–5 次重启；`none|standard` 特征／目标缩放；2–20 折；10–100 次置换；无符号 32 位种子。AD 为 `nearest_neighbor`（k=1）或 `knn_mean_distance`（声明 k=2–10），缩放为 `none|standard`、分位数为 0.80–0.99。GPR 使用 `normalize_y:false`。可选 `target`／`groups` 声明须符合冻结来源，重复科学选择须一致。

每个索引总体完整且唯一，CSV 行序不限；预测／sigma 有限且 sigma>0，标志为布尔值或 0/1，整数 ID 为精确数值整数而非布尔值。JSON 键及 CSV 表头唯一。不提交留出目标、误差或指标，无需折回执、重复来源绑定或独立统计摘要。

`noise_floor.json` 含 `precision_claim`（kcal/mol 数值精度或 `no_sub_0.1_kcal_mol_claim`）及 `reasoning`。有依据的数值主张另含 `precision_justification:{confidence:0.95,claimed_bound_kcal_mol,explanation}`，明确组内 IID。在 `notes.md` 解释 OOF 覆盖／选择风险、置换对照、两类 LOGO、单条件结果及 AD／迁移限制。科学结果只报告一次，附注不得与观测矛盾。
