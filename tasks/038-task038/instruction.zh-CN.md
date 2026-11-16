# 任务：定电势近似与路径排序稳健性

## 背景

公开资料中的 Fermi 能级、反应能垒和条件性扰动可用于检查定电势近似及特定假设下的路径排序；它们不等同于实验速率、统计误差或电极内电势测量。

## 任务

依据公开的 `kinetics.json` 计算中性/阴离子 Fermi 均值变化、两组名义能垒速率比及独立扰动下的最坏情形能垒差。说明计算依赖的假设，以及缺失证据限制的推断。

## 要求

- 只读 `/app/environment/assets/kinetics.json`，使用 Python 3.12。采用 `T=300 K`、`kB=8.617333262145e-5 eV/K` 和相同 Eyring 前因子；用对数表达式计算 `K_vs_water_OS_log10_rate=log10(k_KOS/k_waterOS)` 与 `K_IS_vs_OS_log10_rate=log10(k_KIS/k_KOS)`。
- `water_fermi_shift_eV`、`K_fermi_shift_eV` 为同体系阴离子均值减中性态均值。不要把 Fermi 能级变化称为电极内电势变化。
- 对每条相关路径独立施加输入正负扰动，计算 `OS_barrier_gap_lower_eV`、`K_pathway_gap_lower_eV` 最坏情形下界；速率比仍用名义能垒。说明共同前因子条件和最小正能垒差。
- `robustness.json` 提供上述六个有限数值及 `claims`；速率比无量纲，其余数值为 eV。`uncertainty_semantics` 可选，若提供须为 `conditional_bounds_not_Fermi_spread_CI`。结果与输入/公式的绝对误差不超过 `1e-6`。
- claims 覆盖 `K_slower_OS_than_water`、`K_IS_faster_than_K_OS`、`fermi_spread_is_SEM`、`strict_constant_electrode_potential`、`barrier_bounds_are_measured_uncertainty`、`experimental_TOF_determined`、`short_range_causality_proven`。每项含 `verdict`（`supported`、`conditional`、`not_established`）、`evidence`（JSON Pointer 字符串列表）和非空自然语言 `rationale`；`scope` 可省略，若提供为非空文本或单文本列表。证据用 `input:/...` 指向输入、`result:/...` 指向本次结果，可指向字段或适当父节点。证据应覆盖：路径排序的能垒下界与前因子/扰动假设；SEM判断的Fermi spread与有效样本量缺口；恒电势判断的Fermi变化与内电势缺口；扰动误差判断的扰动假设与电容/路径定电势修正缺口；TOF判断的名义能垒与模型前因子；因果判断的内电势和路径特异修正缺口。按证据判断结论，不预设 verdict 或 scope。

### 输入与产物细则

- `/app/environment/assets/kinetics.json`
- 将 `robustness.json`、可执行 `analysis.py` 和 `report.md` 写入 `/app/final/`。`python analysis.py ASSET_DIR OUTPUT_DIR` 应重算并重复生成数据文件。报告说明计算假设、Fermi spread 与均值标准误之别、数据缺口及条件推断的适用范围；claims JSON 标记区块可省略，若提供须与 `robustness.json` 的 claims 一致。该说明不构成实测速率、统计置信区间或短程因果证据。

上述 `ASSET_DIR` 为 `/app/environment/assets/`，`OUTPUT_DIR` 为 `/app/final/`。`analysis.py` 是需要编写的提交产物，并非预置分析脚本。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/kinetics.json` | 给定数据、参数或方法说明；用途见任务要求。 |
| `/app/environment/assets/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |

输出格式摘要见 `/app/environment/assets/output-contract.json`。科学定义和数值约定以上文为准。
