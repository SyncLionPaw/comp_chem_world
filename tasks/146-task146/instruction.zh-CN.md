# 光致发光速率的可辨识性

## 背景

给定三组无噪声荧光和磷光轨迹，描述单重态—三重态动力学。每组包含 100 个从 10⁻⁹ 到 10⁻² s 对数均匀分布的时刻。各条件内，荧光除以其零时刻强度，磷光除以观测窗口内最大值；不提供绝对强度及跨通道校准。

## 任务

判断轨迹能够约束哪些速率常数，以数值证据说明可能的歧义，并提出能够区分未分辨参数组的额外测量。

采用 \(\dot p=Ap\)、\(p(0)=(1,0)\)，各速率为正，单位 s⁻¹：

\[
A=\begin{pmatrix}-(f+nrS+isc)&risc\\isc&-(risc+ph1+nr1)\end{pmatrix}.
\]

相对于 `baseline`，`intervention_A` 仅将 `ph1` 乘以 3，`intervention_B` 仅将 `nr1` 乘以 3。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 h5py、NumPy、PySCF、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 一致拟合全部条件，记录拟合坐标、正值边界、时间窗口、权重，以及至少两个起点和各自拟合后的 RMS 残差。选择 RMS 最小的结果；其对全部观测的 RMS 不超过 10⁻⁸。
- 提供另一组正值参数，其 RMS 及与所选结果的曲线最大绝对差均不超过 10⁻⁸。差异应超过舍入影响：至少一个速率差大于所选最大速率与 1 s⁻¹ 中较大者的 10⁻⁸ 倍。若仅保持观测曲线而非生成矩阵不变，还须有至少一个速率的相对变化大于 10⁻⁶。
- 区分结构歧义与实际不确定性；只有在明确噪声模型并给出支持的参数剖面时，才量化不确定性。
- 计算两组参数的绝对荧光产率、直接测得的某个速率，或校准荧光通量，说明额外测量为何能够区分两组参数。产率差须大于 10⁻⁵；速率或通量差须大于两预测绝对值较大者的 10⁻⁶ 倍。
- 提交能从给定输入复现分析的程序，可在仅含 `inputs/` 和 `final/` 的目录中，以 `python final/experiment.py` 运行。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/observations.csv` | 观测数据。 |
| `/app/inputs/benchmark.json` | 基准参数与条件。 |

输入为 `/app/inputs/observations.csv` 和 `/app/inputs/benchmark.json`。将程序保存为 `/app/final/experiment.py`，简短科研解释写入 `/app/final/diagnosis.md`，数值结果写入 `/app/final/result.json`：

- `rates`：所选参数及替代参数的列表，每组含 `f`、`nrS`、`isc`、`risc`、`ph1`、`nr1`，单位 s⁻¹。
- `fit`：`coordinates`、`bounds`（坐标 → `[lower, upper]`）、`starts`（按坐标顺序的向量）、各起点拟合后的 `rms`、`window_s` 和 `weights`。起点及所选参数应满足边界；窗口至少覆盖两个观测时刻。
- `measurement`：`type`（`yield`、`rate` 或 `flux`）及前两组参数对应的两个 `predictions`。`rate` 另给 `parameter`；`flux` 另给 `scenario` 和非负 `time_s`，通量按每个初始激发分子计算。
- `uncertainty`：未量化时为 `noise_model: null`；否则给出明确模型，并以 `profile_indices` 指向 `rates` 中支持该分析的替代参数组，索引从零开始。

数值须有限并保留完整计算精度。
