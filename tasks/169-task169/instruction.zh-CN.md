# 任务：—应变与掺杂趋势

## 背景

`assets/a2f-tuning-series.csv` 包含 11 个应变/掺杂成员的合成 α²F 谱。
正频率 α²F 数据不包含声子本征值、色散或虚频。
低频筛查不是动力学稳定性判定。

## 任务

对每个成员计算 λ、ω_log（cm⁻¹）、μ*=0.16 与 0.10 下的 Tc，以及 ω<12 cm⁻¹ 的 λ 占比。
占比>0.30 时设 `soft_mode_risk=true`、`proxy_safe=false`，并将两个 Tc 设为 null；
否则分别为 false/true 并报告估算值。
空穴代理区间的端点应为采样中最高的 proxy-safe 浓度和最低的风险浓度。
报告所有趋势及 +1% 极端耦合比较。
解释为何合成标量 α²F 和 Allen–Dynes 无法确定真实材料的定量 Tc、给定资料为何把该低频区域视为超导理论检验，以及为何单独的大 λ 既不能证明 Migdal 框架失效，也不能证明动力学不稳定。
提供非空的物理论证 `rationale`。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

恰好各覆盖一次以下 ID：`strain_-2p0pct`、`strain_-1p0pct`、`strain_-0p5pct`、`strain_0p0pct`、`strain_+0p5pct`、`strain_+1p0pct`、`hole_0p10h`、`hole_0p15h`、`hole_0p20h`、`electron_0p5e`、`electron_1p0e`。
使用 λ=2∫α²F/ω dω、ω_log=exp[(2/λ)∫(α²F/ω)ln(ω)dω]、`Tc=(ω_log,K/1.2)exp[-1.04(1+λ)/(λ−μ*(1+0.62λ))]`。
不得将代理状态作为稳定性证据。
单位换算：1 cm⁻¹=1.4387769 K。
`compression_reduces_lambda` 与 `compression_raises_omega_log` 比较 −2% 成员和 0% 成员；`hole_doping_raises_lambda` 比较 0.10 h/u.c. 与 0%。`expansion_1pct_lambda` 和 `extreme_coupling.lambda_value` 须与 +1% 成员一致；`electron_1p0e_tc_mu016_K` 须与 1.0 e/u.c. 成员一致。若 +1% λ 超过已知材料最大值约 2.6，则 `exceeds_known_materials` 为真。若 1.0 e/u.c. 时 μ*=0.16 的 Tc 落在 0.4–1.6 K 范围，则 `electron_doping_tc_in_paper_range` 为真（端点容差 ±0.1 K）。数值比较容差：λ/ω_log 3%，Tc 1 K，低频占比 0.05。根据给定成员及上述比较定义得出趋势和代理区间。

### 输入与产物细则

写入 `/app/final/tuning-report.json`。
`members` 为 11 个对象组成的数组，每个对象有字符串 `series_id`、数值 `lambda`、数值 `omega_log_cm1`、布尔 `soft_mode_risk`、布尔 `proxy_safe`、数值或 null 的 `tc_mu016_K` 和 `tc_mu01_K`、数值 `soft_lambda_fraction_below_12cm1`。
`trends` 对象必需布尔值 `compression_reduces_lambda`、`compression_raises_omega_log`、`hole_doping_raises_lambda`、`electron_doping_tc_in_paper_range`；
数值 `expansion_1pct_lambda`、`electron_1p0e_tc_mu016_K`；
以及两个数值构成的 `hole_soft_mode_risk_bracket`。
`extreme_coupling` 必需字符串 `series_id`（`strain_+1p0pct`）、数值 `lambda_value`、布尔 `exceeds_known_materials` 和 `quantitative_tc_reliable`、非空的 `rationale`。
可选 `notes` 为文本。
不要使用预填答案模板。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `assets/a2f-tuning-series.csv` | 给定科学输入或资源；格式和单位见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/tuning-report.json` | 提交结果；内容与格式按上文要求。 |
