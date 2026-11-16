# 任务：过渡态验证与构象筛选

## 背景

审计频率、构象和势垒。

## 任务

按原生频率分类驻点、筛选构象，重算位点势垒、比对发表值。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

- 纳入全部 196 个日志。逐项报告确切源路径、理论水平、多重度、原子数、分子式、振动模式数、全部虚频、分类及正常终止状态。使用最新且完整的谐振频率块，并据此计数；从最终几何核实分子式、从日志核实电子态。非线性结构使用 3N−6 模式；沉积的线性双原子 NO 使用一个物理模式（3N−5）。
- 根据频率证据而非文件名，将每项归为 `transition_state`、`minimum` 或 `higher_order_saddle` 之一。披露异常或非正常终止。
- 仅将物种、源目录、分子式、驻点类别和理论水平相同的计算归为一族。去掉 `Conf` 编号后缀以识别母体，但极小点与鞍点须分开。纳入所有成员，包括单成员族及超出保留窗口者；检查母体/Conf 命名中的别名，记录任何身份不一致。若同目录、同批次中一个无编号记录与某 `ConfN` 系列具有相同分子式、方法、电荷/多重度和连接关系，应归入该母体族，不得另立单族。
- 每族仅在相同理论水平内以 Gaussian 电子能与零点能之和比较；标明最低能成员、各成员偏移、是否在 2.0 kcal/mol 内及保留能量跨度。不得跨理论水平比较能量。
- 对四个位点的 C1、C2 通道，分别标出极小点和鞍点的 DFT/F12 源文件。复合势垒为 `(F12 鞍点 − F12 极小点 + DFT 鞍点 ZPE − DFT 极小点 ZPE) × 627.509474063 kcal mol⁻¹ Hartree⁻¹`。报告各通道及每个位点较低通道。以 0.20 kcal/mol 为一致性容差，将各位点结果与已发表剖面比较，报告并分析任何位点差异。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 用于分析的来源记录与反应数据。 |

在 `/app/final/` 下提交：

- `saddle_audit.csv`：恰好 196 行；列为 `file,directory,level,multiplicity,n_atoms,formula,n_modes,n_imaginary,imaginary_freq_cm1,classification,normal_termination`。
- `conformer_members.csv`：全部 196 个成员；列为 `relative_path,family_id,level,zpe_au,delta_from_family_min_kcal_per_mol,within_2_kcal,selected_lowest`。此处 `zpe_au` 指 Gaussian 电子能与零点能之和。布尔值可统一使用 true/false、yes/no 或 1/0。
- `conformer_selection.csv`：每族一行；列为 `reaction_key,n_conformers_found,selected_file,energy_quantity_used,spread_within_window_kcal_per_mol`。`reaction_key` 和 `family_id` 使用同一标签；注明采用 Gaussian 电子能与零点能之和。
- `isomer_barriers.csv`：恰好八个位点/通道行；列为 `site,channel,minimum_dft,minimum_f12,saddle_dft,saddle_f12,composite_kcal_per_mol,published_kcal_per_mol,deviation_kcal_per_mol`。注明沉积源文件；偏差可带符号或取绝对值。发表参考值可采用 SI 的位点最低通道约定，或在 Source Data 提供时采用对应通道的剖面值；每项偏差须使用同一参考值计算。位点层面的比较仍使用计算所得较低通道。
- `validation_rules.json`：窗口为 2.0 kcal/mol。可用 `conformer_window_kcal_per_mol` + `saddle_rule`，或 `conformer_retention.window_kcal_per_mol` + `saddle_point_acceptance.acceptance_rule`。鞍点和极小点均须正常终止，前者恰有一个虚频，后者为零虚频。文本可分句说明过渡态、极小点及高阶鞍点判据，须按各自语境判断；必需条件须以肯定式表述，否定、含糊或限定措辞不构成满足。规则可用文本或含 `acceptance_rule` 及/或布尔别名 `require_normal_termination` / `normal_termination_required`、`exactly_one_imaginary_frequency` / `n_imaginary: 1` 的字典；矛盾即失败。
- `audit_notes.md`：说明所用证据，逐一列出被排除的成员/文件及原因，并记录发现的命名别名。

分类标签须使用上述名称。六份输出都须与原生证据一致。资产相对路径可带 `assets/` 前缀；也可使用文件名并同时注明所在目录。不要求量子化学计算。

输入：196 个 Gaussian 日志分布于 `/app/assets/Figure2/`、`/app/assets/Figure4/`、`/app/assets/RONO2/` 和 `/app/assets/Toluene-iBPR-rearrangment/`；Source Data 工作簿和 SI DOCX 位于 `/app/assets/`；各位点极小点及 C1/C2 鞍点对应的 12 个 Molpro F12 输出位于 `/app/assets/Figure4/Toluene/`。确切文件名以资产目录为准。
