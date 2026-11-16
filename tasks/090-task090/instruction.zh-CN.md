# 任务：按变分边界与固定粗糙度约定计算水合压力

## 背景

公开输入 `/app/assets/model_constants.json` 固定了核、表面极化、能量密度、压力换算与粗糙度约定。边界数据是反对称 Dirichlet 极化值，两端自然条件为 `P1''=0`，不是 `P1'=0`。给定资料 Eq. 16 的表面束缚电荷（`P1'=-rho_b`）不属于本题。压力按输入中的 `energy_code` 计算：`Pi = -d/dL_A (integral energy_code dz_A) / eps0`，`z` 用 Å，极化用 C/m²。

## 任务

计算尖锐压力曲线，以及题目规定的粗糙度平均。粗糙度使用题目自己的高斯，而非给定资料 Eq. 19 的宽度定义：每侧表面位移支撑区间为 `[0,L/2]`、中心为 0，密度为 `exp(-x^2/(2 sigma^2))`，`sigma=1.25 Å`；输入中的 `2.5 Å` 是 `2*sigma`，不是给定资料粗糙度宽度。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、MDAnalysis、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 尖锐曲线 `final/force_sharp.csv`（列 `L_A,Pi_Pa`）：2–20 Å，步长不超过 0.08 Å。涂抹曲线 `final/force_smeared.csv`：5–20 Å，使用上述 `sigma`，步长不超过 0.11 Å。两者均需至少 100 行有限值，`L_A` 严格递增。
- 剔除薄膜厚度小于 `0.40 Å` 的样本并对保留权重重新归一化，在每个保留间距下计算尖锐压力直至 0.40 Å——不能用 `Pi(2 Å)` 代替。公开尖锐曲线从 2 Å 开始，但内部积分表须达到 0.40 Å。
- `final/analysis.json`：有限数值字段 `lambda_d1_A`、`lambda_o_A`、`lambda_d2_A`、`oscillation_period_A`、`sharp_sign_changes_4_20`、`smeared_sign_changes_5_20`、`smeared_sign_changes_10_20`、`film_floor_A`(0.40)、`task_two_sigma_A`(2.5)、`internal_sharp_start_A`(0.40)。
- 符号变化数：使用字段名所指闭区间内的交付采样点，先删除压力恰为零的点，再统计相邻剩余点间的符号变化。`oscillation_period_A`：只使用交付尖锐曲线中 `L_A` 位于 `[4,16] Å` 的内部采样点，取相邻压力差之积为负的点作为极值位置（不插值、不拟合，至少三个极值），报告相邻极值间距中位数的两倍。
- 三个 `lambda_*_A` 是由固定公开输入确定的核极点诊断：`lambda_d1_A` 为振荡共轭极点模态的衰减长度，`lambda_o_A` 为其波长，`lambda_d2_A` 为单调极点衰减长度；本输入下 `lambda_d1_A < lambda_d2_A`。各按绝对误差 0.08 Å 检查。
- `final/solver.log` 以 `字段 数值` 形式报告四个诊断，数值须有限且非负：`max_boundary_residual`（不超过 1e-8）、`pressure_step_relative_change_at_0.40A` 与 `quadrature_relative_change_at_0.40A`（各不超过 1e-5）、`energy_reproducibility_residual_at_8A`。

尖锐与涂抹曲线会在各自全区间与独立重算的参考比较；极点长度、符号变化数、周期与物理约定均从交付数据检查——日志文字不构成证明。

### 输入与产物细则

- 输入：`/app/assets/model_constants.json`
- 输出：`final/force_sharp.csv`、`final/force_smeared.csv`、`final/analysis.json`、`final/solver.log`

在完整网格上，以参考曲线峰值幅度归一化的最大绝对偏差，尖锐曲线不得超过 0.012，涂抹曲线不得超过 0.015。尖锐曲线在 4–20 Å 至少变号六次，周期为 2.10 ± 0.30 Å；涂抹曲线在 10–20 Å 不变号。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/model_constants.json` | 给定数据、参数或方法说明；用途见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/analysis.json` | 完整字段、单位和内容按上文要求。 |
