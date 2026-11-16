# 任务：拟合常压 MCM 层间力常数

## 背景

给定的少层 MoS₂ 常压 Raman 序列遵循有限链关系 `ω_N = ω_bulk sin[(N−1)π/(2N)]`。目标分支为最高剪切模（`S_N1`）和最高层间呼吸模（`LB_highest`）。

## 任务

用带标签的层数序列拟合各分支的体极限频率，并按给定单位面积约化质量换算层间力常数。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

频率用 cm⁻¹，`alpha` 用 10¹⁹ N m⁻³。各拟合的 RMS 误差须≤1.5 cm⁻¹；两个力常数均须为正，满足频率–质量恒等式（4%以内），比较两种拟合常数。N=16 体相剪切参考可选。字段与拟合表覆盖范围按 `/app/verification.md`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 常压剪切和层间呼吸模序列。 |
| `/app/verification.md` | 方法与输出规范。 |

输入：`/app/assets/ambient_s_lb_series.csv` 和 `/app/assets/conventions.md`（分支定义、质量和单位）。按公开契约提交 `/app/final/results.json` 和 `/app/final/fit_table.csv`.
