# 任务：有限温 SiO₂ 相稳定性与自由能敏感性

## 背景

现有 `alpha_quartz`、`beta_quartz`、`coesite`、`cristobalite`、`melt`、`tridymite`、`tridymite_low` 七种 SiO₂ 相在有限温度和压力范围内的热力学拟合。绘制稳定相和相界，并评估自由能扰动对结论的影响。

## 任务

分析适用范围内的相网格、相界和敏感性，并将完整结果、摘要及图表提交至 `outputs/`。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、NetworkX、NumPy、pandas、ParmEd、pillow、PROPKA、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

在完整网格上绘制稳定相：601–3999 K、步长 1 K；0–50000 bar、步长 100 bar。报告压力支持区间和稳定区间，并用 `crossing`、`support_edge` 或 `alpha_beta_line` 作为 `kind` 区分共同有效区间内的交点与支持边缘转换。每个温度下相邻压力网格点之间的每次稳定相变化均须记录一行，不得跨温度合并；若摘要包含 `grid_transition_count`，它只计压力方向的变化。对每个存在共同有效网格交点的不同相对，按温度、压力排序交点记录并选择温度上中位数，再在该温度选取最近的已报告交点评估敏感性。对两相分别施加正负方向的 0.1、2、5 meV/atom 扰动。若扰动后共同压力支持区间内不存在根，或有第三个有效相能量更低，则标记该相对结果有歧义。α–β 线性拟合使用全部 15 行或绘图区间子集之一，并显示在 2759–32400 bar 范围内。解释未定义值，确保各项结果一致。

相图须为非空、可检查的 PNG。CSV 使用带表头的 UTF-8 格式，JSON 须有效，数值须有限。`phase_grid.csv` 按温度递增、同温度下按压力递增排列。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `inputs/phase_diagram/` | 包含各相的 `fit_gibbs_energy.csv` 和 `alpha_quartz_beta_quartz.txt`。 |

| 路径 | 内容 |
| --- | --- |
| `outputs/phase_grid.csv` | `T_K,P_bar,valid_phases,G_min_meV_per_atom,stable_phase,reason` |
| `outputs/boundaries.csv` | `boundary_id,phase_a,phase_b,T_K,P_bar,kind,valid_overlap,uncertainty_bar,basis,reason` |
| `outputs/sensitivity.csv` | `perturbation_meV_per_atom,perturbed_phase,sign,boundary_id,phase_a,phase_b,T_K,nominal_P_bar,perturbed_P_bar,delta_P_bar,valid_overlap,ambiguous_domain,reason` |
| `outputs/summary.json` | 包含 `units`、`method`、`boundaries`、`sensitivity`、`alpha_beta_treatment` 和 `limitations`。详细稳定区间由 `phase_grid.csv` 表示，不要在摘要中重复完整网格。α–β 部分报告三个输入列、拟合子集与行数，以及 `fit_slope_K_per_GPa`、`fit_intercept_K`、`mean_abs_estimate_gap_K`、`max_abs_estimate_gap_K`。 |
| `outputs/figures/phase_map.png` | 非空、可检查的相图。 |

摘要须为 JSON 对象。`units` 须声明 `pressure: bar`、`temperature: K` 和 Gibbs 能量单位 `meV/atom`（Gibbs 键可用 `gibbs` 或 `gibbs_energy`；单位后可附注）。方法、边界、敏感性和限制字段可用简洁文字说明；详细数值以网格和 CSV 文件为准。允许增加解释字段。

每条边界的 `basis` 须提供非空说明，不限定固定措辞。`valid_overlap` 表示两个拟合在所报温压点是否均有压力支持；它不决定 `kind` 应为 `crossing` 还是 `support_edge`。共同有效区间内 Gibbs 交点的压力不确定度按报告压力处的 `max(50 bar, 50 bar + hypot(max(std_a,maxdev_a), max(std_b,maxdev_b)) / |d(G_a-G_b)/dP|)` 计算。支持边缘记录至少使用半个网格步长（50 bar）。允许普通小数舍入。α–β 外部拟合线的不确定度为有限且非负的估计差换算值，不受网格半步长下限约束；绘图范围 2759–32400 bar 内至少提供 10 个线段采样点。外部拟合摘要按源文件顺序报告三个输入列，列名可用描述性写法，并且不要把任一估计值指定为特定初始相。拟合行数可用 `fit_rows` 或 `fit_row_count`，拟合子集可用 `fit_basis` 或 `fit_subset`（`all_15_rows` 或 `plot_window_only`）；斜率可用 K/GPa 或 K/bar。标准摘要字段为 `fit_slope_K_per_GPa`、`fit_intercept_K`、`mean_abs_estimate_gap_K` 和 `max_abs_estimate_gap_K`。扰动后若共同有效区间内不存在根，须标记 `valid_overlap=false`、`ambiguous_domain=true` 并说明原因。`perturbed_P_bar` 和 `delta_P_bar` 可留空或填写有限占位值；占位值不代表真实根。
