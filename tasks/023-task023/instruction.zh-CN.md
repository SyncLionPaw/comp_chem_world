# 任务：开环速率的温度依赖与分支

## 背景

沉积的 MESMER 输出给出了甲苯 ipso-BPR 在 760 Torr 氮气下随温度变化的两个开环通道速率。Source Data 工作簿包含部分温度下已发表的速率。

## 任务

提取每个温度下的两个原生通道速率，与已发表表格的匹配温度比较；为 C1、C2 及总速率拟合修正 Arrhenius 曲线，并描述现有压力条件下分支比的温度变化。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 使用全部 23 个原生 XML 文件。在 MESMER 命名空间中读取 `<me:analysis>/<me:rateList>` 下两个 `<me:firstOrderRate>` 条目，而非 population/density 记录或输入参数；记录两个条目的 `fromRef`、`toRef`、源路径、温度、压力和浴气。
- 在全部 23 个温度报告 C1、C2 及总速率，单位为 s⁻¹。与工作簿重合的 20 个温度中，每个通道与已发表值的相对偏差须不超过 1e-4。也须纳入工作簿中没有的三个温度。
- 用 200–500 K 的全部 23 个点拟合 `k(T)=A*(T/T_ref)^n*exp[-Ea/(R*T)]`，其中 `R=0.00198720425864 kcal mol⁻¹ K⁻¹`。分别为 C1、C2 和总速率报告 A、n、Ea、拟合范围、点数及直接重算的 ln(k) 最大绝对残差；不得低报残差。
- 用两个原生速率计算各温度的 C1 分支比。报告 300 K 的分支比及 200–500 K 的范围和端点温度；不要声称分支比不随温度变化。
- 说明所有文件均对应 760 Torr N2，单压不能推断压力依赖性。说明拟合窗口的选择与查看已发表分支比的先后关系。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 用于分析的来源记录与反应数据。 |

在 `/app/final/` 下提交：

- `rates_by_temperature.csv`：23 个唯一行；列为 `source_file,temperature_K,pressure_Torr,bath_gas,k_C1_per_s,k_C2_per_s,k_total_per_s,C1_fromRef,C1_toRef,C2_fromRef,C2_toRef`。
- `arrhenius_fit.json`：为 `c1`、`c2`、`total`（或 `k_c1_full_range`、`k_c2_full_range`、`k_total_full_range`）提供记录，字段为 `A_per_s,n_T_exponent,Ea_kcal_per_mol,T_ref_K,fit_min_K,fit_max_K,n_points,max_ln_k_deviation,formula`。使用 200–500 K 全部 23 点。可采用等价算术形式、因子重排、`^` 或 `**`，以及别名 `Ea`、`T_ref`、`n`、`A`。其他参考温度也可，但 A 和所得曲线须一致。`;` 后可用逗号或分号分隔注明 `R`、`T_ref`/`T_ref_K`、`Ea`、`A`、`n` 的数值或单位；R 注释须与给定气体常数 `0.00198720425864 kcal mol⁻¹ K⁻¹` 的差不超过 `max(|R|×10⁻¹⁰, 10⁻¹⁴)`，T_ref 注释须与 `T_ref_K` 的差不超过 `10⁻⁹ K`，Ea、A、n 按所报精度与 JSON 字段一致。R、T_ref、A 必须为正；并遵守科学单位（分别为 kcal mol⁻¹ K⁻¹、K、kcal mol⁻¹、s⁻¹、无量纲）。重复注明时各项均须一致。公式和参数须能复现原生速率。
- `branching_curve.csv`：列为 `temperature_K,branching_C1_percent`，每个温度一行。
- `derivation_notes.md`：说明原生速率提取、拟合与分支范围、固定压力限制、端点分支值/范围，以及拟合窗口选择与查看已发表分支比的先后关系。

源路径可为资产相对路径（可选 `assets/` 前缀）或唯一文件名。科学范围说明可用中英文撰写。

输入：23 个 XML 文件（200–500 K，包括 255–310 K 的 5 K 加密网格）位于 `/app/assets/Toluene-iBPR-rearrangement-Tdep-MESMER/`；Source Data 工作簿和 SI DOCX 位于 `/app/assets/`。无需运行 MESMER 或量子化学计算。
