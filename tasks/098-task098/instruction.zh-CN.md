# 任务：MD 谱与弹性模量反演

## 背景

给定数据包括十二个压力下的六层 MoS₂ 质心轨迹，以及层序和轨迹格式信息。提取剪切（S）支与层间呼吸（LB）支。体相 LB 是相邻层反相运动的面外光学模，须与整体平动和均匀层间距变化区分。

## 任务

分析全部压力点，将指认频率换算为层间力常数和弹性模量，并为每个压力的模态指认提供定量证据。说明信号处理与模态跟踪方法。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

采用固定网格 `[0, 0.5, 1.65, 2.4, 3.06, 4.09, 4.7, 5.48, 6.3, 7.25, 8, 9.6]` GPa、`t(P)=6.15×10⁻¹⁰(1−0.0104P)` m 以及单位面积质量 `μ=3.0738408378142946×10⁻⁶ kg m⁻²`。频率用 cm⁻¹，`alpha` 用 10¹⁹ N m⁻³，模量用 GPa。保留频率–质量恒等式≤6%、`C=alpha·t(P)`≤8%、独立 S/LB 峰位偏差（3/8 cm⁻¹）、6.3 GPa 以内平行力常数与独立参考相差≤15%，以及独立高压覆盖。其他字段和判据按 `/app/verification.md`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 按压力组织的轨迹、晶胞与层定义。 |
| `/app/verification.md` | 方法与输出规范。 |

输入：`/app/assets/P_*.txt`、`/app/assets/trajectory_format.md`、`/app/assets/conventions.md`、`/app/assets/P_0.00.lammpstrj`（晶胞）和 `/app/assets/6L_MoS2_origin`（层序）。提交与全部压力对齐的 `/app/final/results.json`、`/app/final/methods.md`，以及 `/app/final/mode_evidence.md` 或 `/app/final/spectra.csv`.
