# 任务：Hsp60 催化二联体几何与顶端构象

## 背景

`/app/assets/Fig_6b.dat` 和 `Fig_8b.dat` 分别提供 300 K 下双环 D 与 football F 装配体的逐帧数据；`data_dictionary.md` 说明面板、列、单位及质子化状态。分析多聚体面板中 WT/V72I、AspAsp/AshAsp/AspAsh 的 δ（Asp50–Asp397 Cγ–Cγ 距离，Å）和 γ（顶点开合角，度），共 12 组/观测量。单体 M 列仅作可选背景，不纳入这 12 组。

## 任务

以提供的数据评估 V72I 与质子化状态和二联体几何、顶端开合之间的关联。效应方向、相关方向以及是否存在肩峰均由数据决定；不得预设结果。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、NumPy、pandas、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 对 12 组 δ、12 组 γ 分别报告有限值的 `n`、均值、样本标准差（`ddof=1`）、中位数、Q1、Q3。至少给出每组匹配的 WT→V72I δ/γ 对比，以及每个装配体和变体下 AshAsp、AspAsh 分别相对 AspAsp 的 δ 对比；每项标明选用均值或中位数、参考值、目标值、目标减参考的有符号效应、单位和由数值决定的方向。
- 报告原始 δ≤4.35 Å 的经验接触比例和计数，并给出同组内突变对比及单质子化状态相对 AspAsp 的接触比例差。直接从 γ 报告 apical context：F 的中位数和 γ>120° 比例；D 的中位数和 γ≥100° 比例。
- 对 12 组逐帧配对 δ、γ 计算 Pearson 相关系数、配对数和方向。帧是池化的单体观测；没有独立重复标签或时间轴。标准差、四分位数、比例和相关均为描述量，不是置信区间或独立样本推断；勿作因果或显著性结论。
- 提交 δ 的 12 组完整连续直方图。可在 `findings.json` 中声明 `raw_count`、`frequency`、`probability_density` 或 `radius_weighted_probability_density`；`density` 必须严格对应声明的定义，分别为 count、count/N、count/(N·bin_width) 或 bin_center·count/(N·bin_width)。
- 对 AspAsp 的 D/F × WT/V72I，分别以 σ=0.10、0.15 Å 报告共 8 个形状探针。统一算法为 0–16 Å、0.01 Å 的概率密度直方图 p(r)，径向形状 p(r)/r²，以 `gaussian_filter1d`（`sigma_angstrom/0.01`, `mode='nearest'`, `truncate=4.0`）平滑，`numpy.gradient(smoothed,0.01)` 求斜率，`find_peaks(-slope)` 找极小值。报告 D 4.6–5.0 Å、F 4.1–4.7 Å 闭区间内的所有斜率极小值及位置/斜率。`primary_mode_angstrom` 是未平滑径向形状在中心 r 严格大于窗口下界时的最大值位置（并列取最小中心）；`primary_mode_above_feature` 仅当窗口内至少一个极小值低于该模态且模态高于首个此类极小值时为 true。`raw_mass_feature_window` 是原始 δ 落在闭窗口内的比例；`shoulder_present` 当且仅当有窗口内斜率极小值为 true。`feature_positions_angstrom` 与 `feature_slope_values` 按中心升序逐项配对；`feature_type` 固定为 `local_minimum_of_radial_shape_slope`。斜率极小值、次峰和窗口原始概率质量是不同量；不得互相替代，也不预设肩峰存在。
- 所有效应和统计量应由完整精度数据计算；数值字段须为有限数。数值复现允许的误差为普通字段 `max(2e-6, 2e-6×max(|实际值|,|期望值|))`，RDF density 为 `max(2e-8, 2e-6×max(|实际值|,|期望值|))`，形状位置为绝对 0.0200001 Å；RDF 边界须连续且等宽，误差不超过 1e-9 Å。这些是数值容差，不是舍入精度。

### 输入与产物细则

在 `final/` 提交 `distributions.csv`、`rdf.csv`、`findings.json` 和 `report.md`。CSV 列分别为：

- `distributions.csv`：`assembly,variant,protonation,observable,n,mean,std,median,q25,q75`，恰含 24 个 D/F × WT/V72I × 三种质子化 × δ/γ 组合。
- `rdf.csv`：`assembly,variant,protonation,bin_left,bin_right,count,density`，覆盖全部 12 组完整 δ 范围。
- `findings.json`：顶层必需键为 `schema`（固定 `assembly-dyad/v1`）、`rdf_normalization`、`statistical_methods`（非空字符串数组）、`inference_status`（固定 `descriptive_only`）、`limitations`（非空解释字符串数组）、`uncertainty_provenance` 及以下七个结果数组。所有 JSON 数值须为有限数，计数须为整数。
  - `mutation_effects`：12 行，每个 assembly × protonation × observable 一行；匹配键为 `assembly,protonation,observable`，另含适用的 `statistic,reference_variant,target_variant,reference_protonation,target_protonation,observable,units,conclusion` 字符串字段，以及有限数 `reference_value,target_value,effect`。`statistic` 为 `mean` 或 `median`，变体为 WT→V72I。
  - `protonation_effects`：8 行，每个 assembly × variant × 单质子化目标一行；匹配键为 `assembly,variant,target_protonation`，另含适用的 `statistic,reference_variant,target_variant,reference_protonation,observable,units,conclusion` 字符串字段，以及有限数 `reference_value,target_value,effect`。`statistic` 为 `mean` 或 `median`，参照固定 AspAsp，目标为 AshAsp 或 AspAsh，观测量为 δ。方向 `conclusion` 取 `higher,lower,equal`，效应定义为目标减参考，`equal` 对应 |effect|≤1e-12。
  - `local_contact_state`：12 行，含 `assembly,variant,protonation` 字符串、`n` 整数及有限数 `threshold_angstrom,probability_delta_le_threshold`。
  - `local_contact_differences`：14 行，含 `contrast,assembly,variant,protonation,reference,target,conclusion` 字符串及有限数 `effect`；`contrast` 为 `mutation` 或 `protonation`，方向为 `higher,lower,equal`（|effect|≤1e-12 时为 `equal`），含 6 个 WT→V72I 和 8 个单质子化状态相对 AspAsp 的差值。突变行 `variant` 为空字符串、`reference=WT,target=V72I`；质子化行 `variant=WT` 或 `V72I`、`reference=AspAsp,target=AshAsp` 或 `AspAsh`。所有差值均为目标接触比例减参考接触比例。
  - `apical_context`：12 行，含 `assembly,variant,protonation,cutoff_operator` 字符串、`n` 整数及有限数 `gamma_location_median_degree,cutoff_degree`，另含 D 的有限数 `fraction_gamma_ge_100_degree` 或 F 的 `fraction_gamma_gt_120_degree`。
  - `delta_gamma_dependence`：12 行，含 `assembly,variant,protonation,method,interpretation` 字符串、`n_paired` 整数及有限数 `coefficient`；`method` 为 `Pearson`，方向为 `positive_association`、`negative_association` 或 `zero_association`。
  - `shape_features`：8 行，键含 `assembly,variant,sigma_angstrom,feature_window_low_angstrom,feature_window_high_angstrom,feature_type,feature_positions_angstrom,feature_slope_values,shoulder_present,primary_mode_above_feature,primary_mode_angstrom,raw_mass_feature_window`。`feature_type` 为 `local_minimum_of_radial_shape_slope`；位置和斜率数组逐项配对并列出所有窗口极小值，可为空数组。
- `uncertainty_provenance` 四个布尔字段 `independent_replicates_available`、`time_axis_available`、`pooled_frame_spread_is_confidence_interval`、`frames_treated_as_independent_samples` 均为 `false`。
- `report.md` 用简洁文字说明统计量、匹配比较、RDF 归一化、直接 γ 指标、形状探针及描述性不确定性限制。报告中的数值应与 `findings.json` 和两份 CSV 一致。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/Fig_6b.dat` | 给定科学输入或资源；格式和单位见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/distributions.csv` | δ 和 γ 的描述性统计 |
| `/app/final/rdf.csv` | 径向分布 |
| `/app/final/findings.json` | 结构化比较 |
| `/app/final/report.md` | 科学解读 |
