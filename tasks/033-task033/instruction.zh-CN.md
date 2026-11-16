# 从均方位移识别动力学区间

## 背景

供给的 `msd.csv` 包含 PD、A0/A1/A2 酸性区段和 rpL5 的平均 MSD 对缩放时间 \(t/t_D\)，其中 \(t_D=100\) ps，MSD 单位为 Å²。曲线是分子平均；它们不提供独立重复不确定性或逐分子分布。

## 任务

估计各物种的早期和晚期幂律，判断平均曲线是否支持不同的动力学区间，并检验拟合窗口和目标函数选择如何影响指数。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

说明并论证早期/晚期拟合窗口、目标函数以及交叉点或区间选择。使用自然对数空间的无权普通最小二乘：\(\ln \mathrm{MSD} = \ln A + n\ln(t/t_D)\)，其中 `exponent = n`、`amplitude_A2 = A`、`log_residual_sse` 为对数残差平方和。每个窗口至少包含三个正 MSD 点。提供替代窗口的敏感性拟合。区分平均曲线的时间变化与分子级异质性；不要从平均 MSD 推断独立重复误差、双峰性或唯一微观机制。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/msd.csv` | 均方位移数据。 |

输入为 `/app/environment/assets/msd.csv`。把结果写入 `/app/final/`：

- `exponents.json`：`t_D_ps = 100`、`msd_unit = "angstrom_squared"`，以及恰好含 `PD`、`A0`、`A1`、`A2`、`rpL5` 的 `species` 对象。每个物种恰好有 `early` 和 `late`。每个主拟合声明 `objective`（`log_ols` 或论证的替代）、有序 `window_t_over_tD=[low,high]`、`exponent`、`amplitude_A2`（Å²）、`log_residual_sse`，以及非空 `sensitivity` 列表，每项为含 `window_t_over_tD`、`exponent`、`amplitude_A2`、`log_residual_sse` 的替代拟合。
- `fits.csv`：列为 `species,t_over_tD,observed_MSD,fitted_MSD,regime`；每个主窗口中所有正 MSD 输入 bin 都有一行，覆盖五个物种和两个区间。`observed_MSD` 为原始均值；`fitted_MSD = amplitude_A2*(t/t_D)^exponent`。
- `report.md`：数据约定、方法、主窗口和替代窗口、区间解释、窗口敏感性，以及平均曲线行为与逐分子异质性或重复不确定性的区别。
- `analysis.py`：确定性、可复现的分析。必须接受 `--input-dir` 和 `--output-dir`，从输入目录读取 `msd.csv`，写出其余输出，并记录方法、窗口和不确定性。

使用完整精度；避免 NaN/Infinity。`/app/final/` 中只放这四个文件。

`analysis.py` 必须在容器自带的 Python 下、仅使用其预装包（NumPy、SciPy、matplotlib）运行。分析须自包含，不得依赖额外安装的包、网络访问或其它解释器。
