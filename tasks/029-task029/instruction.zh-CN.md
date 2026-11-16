# 从散射曲线估计可靠的相关长度

## 背景

供给的 SANS 测量在 150 mM NaCl 下完成。给定资料的 20 mM ABSINTH 原子级 Monte Carlo 计算是独立的参数化参考；没有供给 RDF 曲线。散射强度包含背景、形状因子和结构因子，最低 q 点对背景和有限采样尤其敏感。

## 任务

从 SANS 曲线识别稳健的实空间相关长度 \(d=2\pi/q\)。判断哪些特征有数据支持、哪些是噪声或低 q 伪影，并说明背景、峰窗口和不确定性选择如何影响结果。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

使用供给的 `error_cminv` 不确定度，或论证替代噪声估计。说明背景模型、峰/拟合窗口、不确定性传播，以及对模型和窗口选择的敏感性。不要把测量的 \(I(q)\) 等同于结构因子 \(S(q)\)，也不要声称与 20 mM 原子级参考数值一致。只有在合理改变背景和窗口后仍能区别于低 q 噪声的特征才算稳健。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/sans.csv` | 散射强度与误差。 |

输入位于 `/app/environment/assets/`（`sans.csv`，含 `q_Ainv`、`I_cminv`、`error_cminv`）。把结果写入 `/app/final/`：

- `peaks.json`：非空 `peaks` 列表。每个峰给出正的有限 `q_Ainv`（Å⁻¹）、包含 `q_Ainv` 的有序区间 `q_interval_Ainv=[low,high]`（Å⁻¹）、`length_A=2*pi/q_Ainv`（Å）和 JSON 布尔 `reliable`。另加非空 `noise_method` 和 `low_q_limitations` 字符串。
- `diagnostics.csv`：每个输入 q bin 一行，列为 `q_Ainv,raw_I,estimated_background,processed_signal,uncertainty`。`raw_I` 复现输入 `I_cminv`；`processed_signal = raw_I - estimated_background`；不确定性有限且非负。
- `report.md`：方法、峰与长度、不确定性、模型/窗口敏感性、低 q 限制，以及 \(I(q)\)、\(S(q)\)、150 mM 实验和 20 mM 原子级参考的区别。
- `analysis.py`：确定性、可复现的分析。必须接受 `--input-dir` 和 `--output-dir`，从输入目录读取 `sans.csv`，写出其余三个输出，并记录方法、窗口和不确定性。

使用足够的数值精度以复现输入网格和 `length_A` 关系；避免 NaN/Infinity。`/app/final/` 中只放这四个文件。

`analysis.py` 必须在容器自带的 Python 下、仅使用其预装包（NumPy、SciPy、matplotlib）运行。分析须自包含，不得依赖额外安装的包、网络访问或其它解释器。
