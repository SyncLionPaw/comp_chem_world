# 任务：SiO 热处理结晶动力学与散射响应

## 背景

现有四种 SiO 样品的结晶度时间序列，以及处理前后的结构因子。比较其动力学响应，并判断其与结构散射证据是否一致。

## 任务

分析每种样品条件和两种散射状态。在 `outputs/` 中报告结晶度、起始行为、峰指标，以及动力学与散射证据之间的关系。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

分析四种样品标签、全部原生结晶度记录及两种散射状态。结晶度以来源筛选子集为分母，而非全部原子；按给定时间步长换算时间，启动记录不作起始点。区分样品制备速率标签与 1400→1200 K 热处理速率（`1e10 K/s`）；序列记录至 20200 ps，不含配置的最后 10 ps 保温。`state` 使用 `before`/`after`；处理前后使用相同的 X-ray S(q) 通道（第 2 列）、q 窗口和归一化。说明起始规则（阈值 0.001–0.05、持续 1–5 次观察）并报告 0.001、0.01、0.05 的敏感性。峰宽使用 `scipy_prominence_half_height` 或 `window_minimum_half_prominence`，在 3.00–4.20 Å⁻¹ 区间和 0.01 Å⁻¹ 网格上计算。报告不确定性及局限，包括 q 位置不确定度 ≥0.01 Å⁻¹、观测窗口和子集限制，并解释未定义值。

CSV 使用带表头的 UTF-8 格式，JSON 须有效，数值须有限。

摘要中的 `method.onset.threshold_fraction` 取 0.001–0.05，`method.onset.consecutive_observations` 取 1–5 的整数；记录 `method.uncertainty.q_peak_A_inv`，至少为 0.01。`scattering_consistency` 使用 `channel: "X-ray (second column)"`、`fixed_q_window_A_inv: [3.0, 4.2]`、`limitations`、引用 Figure 6 的 `source_data_calibration`，以及 `peak_width_method`（`scipy_prominence_half_height` 或 `window_minimum_half_prominence`）。最终子集比例按 `strong`（≥0.1）、`weak`（≥0.005 且 <0.1）或 `trace`（<0.005）分类。散射类别使用 `resolved_crystalline_doublet` 或 `broad_peak_only_in_fixed_window`。摘要的逐速率记录使用 `kinetics_class`、`scattering_class`、`joint_evidence`；证据一致时用 `consistent`。

每条 `rate_results` 记录还须包含 `rate_label`、`final_subset_fraction` 和 `onset_ps_declared_rule`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `inputs/SiO/` | 给定输入与资源目录。 |
| `inputs/method-note.md` | 给定数据、参数或方法说明；用途见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `outputs/crystallinity_timeseries.csv` | `rate_K_per_s,step,time_ps,n_cubic,n_hex,n_other,n_filtered_subset,crystalline_fraction_subset,temperature_K,temperature_source` |
| `outputs/scattering_peak_metrics.csv` | `rate_K_per_s,state,peak_rank_q_ascending,q_peak_A_inv,peak_height,peak_width_A_inv,peak_width_method,window_A_inv,normalization` |
| `outputs/rate_comparison.csv` | `rate_K_per_s,onset_ps,onset_reason,final_subset_fraction,delta_peak_width_A_inv,kinetics_trend,scattering_trend,agreement,onset_definition` |
| `outputs/summary.json` | 覆盖四种标签，包含 `method`、`rate_results`、`time_unit`、`denominator_definition`、`scattering_consistency`、`onset_sensitivity_ps`、`source_data_check`、`source_scattering_check`。说明起始阈值/持续次数、时间换算、筛选子集分母、第 2 列 X-ray、q 窗口、峰宽方法/不确定度（q 位置 ≥0.01 Å⁻¹）、观测窗口/子集限制及 Source Data Figure 6 对照。逐速率结果须与 `rate_comparison.csv` 一致。 |
| `outputs/figures/crystallinity_and_sq.png` | 有效、清晰可读的 PNG。 |
