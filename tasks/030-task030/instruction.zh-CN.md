# 酸性区段增强后的恢复动力学

## 背景

WT 与 +A2 的 FRAP 恢复各有 12 条重复曲线。Methods 使用有理恢复模型 \(I(t)=(I_0+I_\infty t/t_{1/2})/(1+t/t_{1/2})\)；其参数是半时间 \(t_{1/2}\)，不是指数时间常数 \(\tau\)。基线、平台、加权、拟合窗口和模型选择都会影响推断的时间尺度和不可动分数。

## 任务

分别拟合 WT 与 +A2，用重复曲线的不确定性比较恢复动力学，并评估模型和拟合窗口选择如何影响比较。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

用重复曲线表征重复间变异，并与曲线拟合协方差、已发表误差区分。不要把时间点当作独立重复。说明恢复模型与方程、基线/平台处理、加权、拟合窗口和可识别性限制。单一 FRAP 模型不能唯一确定微观扩散系数或不可动分数。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | FRAP 汇总及副本观测。 |

输入位于 `/app/environment/assets/`（`frap.csv`、`frap_replicates.csv`）。把结果写入 `/app/final/`：

- `fits.json`：顶层恰好为 `WT` 和 `plusA2`。每项声明 `family`（`rational` 或 `exponential`）、`equation`、有限 `baseline` 和 `plateau`、正的 `timescale_s`、`time_parameter`（有理模型 `t_half`，指数模型 `tau`）、包含至少四个汇总时间点的有序 `window_s=[low,high]`、`weighting`、`unweighted_sse`，以及描述重复和模型不确定性的非空 `uncertainty`。`unweighted_sse` 是汇总均值在声明窗口内的无权平方残差。
- `fitted_curves.csv`：列为 `time_s,WT_observed,WT_fitted,plusA2_observed,plusA2_fitted`；每个输入汇总时间一行；观测值为输入均值；拟合值按声明模型给出，包括拟合窗口外的时间点。
- `report.md`：带不确定性的恢复时间；有理 \(t_{1/2}\) 与指数 \(\tau\) 的比较（\(t_{1/2}=\ln 2\,\tau\)）；模型、基线和可识别性限制；重复间、曲线拟合和已发表误差的区别。
- `analysis.py`：确定性、可复现的分析。必须接受 `--input-dir` 和 `--output-dir`，从输入目录读取两个 CSV，写出其余输出，并记录方法、窗口和不确定性。

避免 NaN/Infinity，`/app/final/` 中只放这四个文件。

`analysis.py` 必须在容器自带的 Python 下、仅使用其预装包（NumPy、SciPy、matplotlib）运行。分析须自包含，不得依赖额外安装的包、网络访问或其它解释器。
