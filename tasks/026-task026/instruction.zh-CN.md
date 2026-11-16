# 任务：有机硝酸酯能量核对

## 背景

SI Table 9 已标出 benzene 和四个 toluene 羟基加成位点。沉积的 Gaussian 与 Molpro 文件包含双环有机硝酸酯、开环物种和烷氧基物种能量；部分产物含游离 NO2。

## 任务

根据原生文件重算并映射 SI 能量项。核查两个标称 meta-烷氧基身份，用 SI 寿命陈述核对已标记列，并报告未解决的能量、速率及鞍点归属。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

- 以每列 B-RONO2 为锚点，重算 20 个选定单元格和全部 30 个候选；需要时加入游离 NO2 的 F12 能量和 Gaussian 零点能校正。
- 报告 DFT-only（DFT 电子能＋ZPE）与复合能（F12 电子能＋DFT ZPE）、SI 值及偏差。每行保留四条原生路径 `source_dft_file,source_f12_file,anchor_dft_file,anchor_f12_file`；CSV 的 `includes_no2` 表示所报告能量是否计入单独的游离 NO2 项。
- 依据哈希、F12 内嵌源日志身份和计入 NO2 后的能量核验两个 meta-烷氧基输入；区分 SI 寿命/速率证据与原生动力学证据，并标记无原生见证的速率。
- 按位点列出全部鞍点候选和偏差。多个候选处于 0.10 kcal/mol 内时标明歧义；不预设通道唯一。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 用于分析的来源记录与反应数据。 |

输入为 `/app/assets/41467_2023_40675_MOESM1_ESM.docx` 和 `/app/assets/RONO2/`；无需新计算。`column_assignment.json` 的 `assigned_column` 可用规范键或对应 SI 显示名（`Benzene`、`Toluene (site)`）。在 `/app/final/` 提交：
- `rono2_energies.csv`：20 个选定单元格，含 `species_column,quantity,file_stem,source_dft_file,source_f12_file,anchor_dft_file,anchor_f12_file,includes_no2,dft_zero_point_kcal_per_mol,composite_kcal_per_mol,published_kcal_per_mol,deviation`。
- `rono2_candidates.csv`：全部 30 个候选，使用相同列。
- `column_assignment.json`：顶层 `columns`（五条 `{species_column,assigned_column}`）、`lifetime_evidence`（三条 `{species_column,published_rate_per_s,lifetime_minutes,assigned_column}`）、`rate_witness_scope`（`SI_only` 或 `native_supported`）和 `channel_selection`（五条 `{species_column,candidates,selected_file_stem,ambiguous}`）。鞍点候选含 `{file_stem,composite_kcal_per_mol,published_kcal_per_mol,abs_deviation}`。可选 `comparison_rule` 可注明 `comparison_tolerance_kcal_per_mol:0.10`。
- `identity_conflict.json`：B-RO 与 RB-C1-RO 的两条 `advertised_species` 记录，各含 `{label,dft_file,f12_file,dft_sha256,f12_sha256,f12_source_log_name,f12_energy_au,computed_with_free_no2_kcal_per_mol,published_kcal_per_mol,abs_deviation_kcal_per_mol,status}`。`status` 表示原生文件内容是否支持标称身份，且独立于 SI 单元格归属；`resolved` 须有几何与来源证据。无原生支持的选定能量格或速率须列入 `unverified_rows.json`；候选身份判断记录于此文件。
- `unverified_rows.json`：`rows` 记录缺少原生支持的选定能量单元格或 SI 速率，每条含 `{species_column,quantity,status,reason}`。选定能量单元格因身份未解决而无原生见证时使用 `unverified_input_identity_conflict`；缺少原生支持的速率使用 `unsupported_no_native_witness`，并另含 `published_rate_per_s`。候选层面的身份疑问记录在 `identity_conflict.json`。
- `discrepancies.md`：解释来源身份与可恢复性、原生速率证据限制及鞍点可辨识性。

物种列为 `benzene,toluene-ipso,toluene-ortho,toluene-meta,toluene-para`；能量数量为 `x-B-RO + NO2,TSrearrangement,x-RB-RONO2,x-RB-RO + NO2`（`x-` 可省略）；速率数量为 `kx-B-RONO2 => x-B-RO + NO2` 和 `kx-B-RONO2 => x-RB-RO + NO2`（亦接受 `k_B-RO`,`k_RB-RO`）。路径可用资产相对路径、`assets/…` 或 `/app/assets/…`。DFT-only 值与独立重算值相差不得超过 0.01 kcal/mol；复合能和绝对偏差须在 0.002 kcal/mol 内，发表值转录须在 0.001 kcal/mol 内；复合能和偏差至少三位小数。候选科学比较容差为 0.10 kcal/mol。寿命可按速率倒算，或引用注明来源的 SI 近似寿命。缺失见证说明可用中英文。
