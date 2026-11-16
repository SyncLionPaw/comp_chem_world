# 酸性区段的相互作用层级与模块性

## 背景

供给的 WT 与中和突变体 RDF 描述 N130 凝聚体中 A0/A1/A2 的相关性。源文件仅把不确定度标为 `error`，其含义（SD、SEM 或其它）未定。由 RDF 得到的成对 PMF 是有效成对势，不是结合自由能。

## 任务

把区段 RDF 转换为 PMF，确定第一壳层峰窗口，并利用 WT 与突变体响应评估 A0/A1/A2 的相互作用层级与模块性。判断供给证据实际支持哪些比较。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

在 300 K、\(R=0.00198720425864083\) kcal mol⁻¹ K⁻¹ 下计算 \(-\!RT\ln g\)。报告 PMF 变换、选定峰与响应窗口、相对效应和不确定性。说明 RDF 误差语义未定；不要把供给的 `author_error` 转换为标准误或推断独立重复。论证窗口选择和敏感性，仅在供给误差支持的范围内排序区段，并评估突变响应是否模块化。不要把中和呈现为孤立的纯电荷因果效应，也不要把成对 PMF 称为结合自由能。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 野生型与突变体的片段测量。 |

输入位于 `/app/environment/assets/`（`tracts_WT.csv`、`mutants_{PD,A0,A1,A2}.csv`）。把结果写入 `/app/final/`：

- `pmf.csv`：列为 `r_A,A0_kcalmol,A1_kcalmol,A2_kcalmol`；每个 RDF bin 一行。为每个区段计算 PMF；仅当该区段 \(g=0\) 时把该单元格留空。
- `interventions.json`：`window_A` 为 PD 峰窗口（有序有限对，至少三个 bin）；`PD_peaks` 含 `WT`、`A0mut`、`A1mut`、`A2mut`，每项给出 `mutants_PD.csv` 中该列在窗口内最大值处的 `r_A`、`height` 和 `author_error`。`tract_response` 含 `metric: "relative_peak_change"`、自己的 `window_A`，以及 `matrix[mutant][tract]`。外层突变体键可用 `A0`、`A1`、`A2` 或 `A0mut`、`A1mut`、`A2mut`；内层区段键必须恰为 `A0`、`A1`、`A2`。突变体峰取自 `mutants_<tract>.csv` 中对应的 `A0mut`、`A1mut` 或 `A2mut` 列，WT 基线取自 `tracts_WT.csv` 的 `<tract>` 列，条目为 `(mutant_peak - WT_peak)/WT_peak`。另加非空 `supported_rank`（文本，或含非空 `summary` 的对象）、`uncertainty_definition`，以及列表 `indistinguishable_contrasts`。
- `report.md`：PMF 约定、窗口与敏感性、有证据支持的层级与模块性、未定的误差语义，以及成对 PMF/纯电荷解释的注意事项。
- `analysis.py`：确定性、可复现的分析。必须接受 `--input-dir` 和 `--output-dir`，从输入目录读取五个 CSV，写出其余输出，并记录方法、窗口和不确定性。

避免 NaN/Infinity，`/app/final/` 中只放这四个文件。

`analysis.py` 必须在容器自带的 Python 下、仅使用其预装包（NumPy、SciPy、matplotlib）运行。分析须自包含，不得依赖额外安装的包、网络访问或其它解释器。
