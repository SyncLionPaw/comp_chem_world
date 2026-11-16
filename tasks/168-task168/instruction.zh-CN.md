# 任务：—Eliashberg 谱数值计算

## 背景

输入是合成重建谱，不是给定资料原始谱。给定资料关于 μ* 敏感性的陈述针对各向同性 Migdal–Eliashberg 结果，其适用范围与本题 Allen–Dynes 代理谱不同。

## 任务

根据 `assets/a2f-unstrained.csv` 计算 λ、ω_log（cm⁻¹ 和 K）以及 μ*=0.16、0.10 时的 Allen–Dynes Tc；
报告 `Tc(0.10)/Tc(0.16)` 及其是否≤1.10。
将 λ 分为 [0,200]、(200,300]、(300,360]、(360,450]、(450,∞) cm⁻¹ 五段。
用敏感性说明解释适用范围；
不要将合成代理结果等同于给定资料各向同性 Migdal–Eliashberg 结果。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

使用 λ=2∫α²F(ω)/ω dω，ω_log=exp[(2/λ)∫(α²F(ω)/ω)ln(ω)dω]，积分内单位须一致；
`1 cm⁻¹ = 0.12398420 meV = 1.4387769 K`。
Allen–Dynes 修正 McMillan 公式为 `Tc=(ω_log,K/1.2) exp[-1.04(1+λ)/(λ−μ*(1+0.62λ))]`。
正确处理网格起点处有限的低频极限。
可用梯形、Simpson、解析或等效积分；
方法敏感性须<0.5%。
数值比较容差：λ 和 ω_log ±2%，Tc ±0.6 K，分段 λ ±8%；
比值须在 ±2% 内符合 Tc 相除结果，分段和与总 λ 差异须在 2% 内。

### 输入与产物细则

写入 `/app/final/eliashberg-results.json`。
必需键/类型：数值 `lambda`、`omega_log_cm1`、`omega_log_K`、`tc_mu016_K`、`tc_mu01_K`；
对象 `mu_star_sensitivity` 含数值 `ratio_tc_mu01_over_mu016`、布尔 `ad_surrogate_le_10pct_supported`（仅当比值≤1.10 为真）、字符串 `sensitivity_note`（非空文本）；
对象 `decomposition` 含数值 `lambda_0_200_cm1`、`lambda_200_300_cm1`、`lambda_300_360_cm1`、`lambda_360_450_cm1`、`lambda_above_450_cm1`。
频段端点遵循上述区间；
λ 无量纲。
允许额外字段。

在 `integration_check` 中给出数值 `trapezoid_lambda`、`trapezoid_omega_log_cm1`、`midpoint_lambda`、`midpoint_omega_log_cm1`。中点积分先把 α²F 线性插值到各区间中点，再除以频率。两种方法使用相同的频率范围，每个积分结果相对梯形积分的差异均须小于 0.5%。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `assets/a2f-unstrained.csv` | 给定科学输入或资源；格式和单位见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/eliashberg-results.json` | 提交结果；内容与格式按上文要求。 |
