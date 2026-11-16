# 任务：比较总 X 射线散射曲线

## 背景

`sfac_xray_calc.csv` 给出计算总 S(q)，q 单位为 nm⁻¹（除以 10 转为 Å⁻¹）；`saxs_experiment.dat` 给出垂直对齐前的实验曲线，单位为 Å⁻¹。参见 `units.txt`。

## 任务

比较 0.5–8.0 Å⁻¹ 内的曲线，评估吻合程度，并说明总 S(q) 比较能否确立短 Li–Li 链结构。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

按 q 排序并对重复 q 取均值，再线性插值。以最小二乘法拟合并加到实验曲线上的常数垂直偏移。在含两端点的区间内取 300 个等距 q 点，报告偏移量（误差不超过 0.01）以及偏移前后 RMSE（误差不超过 0.005）。偏移后 RMSE≤0.10（无量纲）定义为定性吻合，是本题操作性阈值。报告偏移量，并据比较给出定性和结构判断；无需绘图或指定软件。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 散射输入及实验参考数据。 |

输入位于 `environment/assets/`。将结果写入 `/app/final/scattering.json`：数值字段 `experimental_vertical_shift`（加到实验值）、`q_min_Ainv`、`q_max_Ainv`、`rmse_unshifted`、`rmse_shifted`；布尔字段 `qualitative_agreement`、`total_s_uniquely_proves_short_li_chains`；以及简短科学说明 `rationale`，概述比较结论及其结构判别局限。
