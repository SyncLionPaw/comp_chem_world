# 任务：双环过氧自由基开环能量剖面的重构

## 背景

依据甲苯 ipso-BPR 的 Gaussian/Molpro 原生输出与 Source Data，重构能量剖面并判断支持的组合规则。

## 任务

求出相对于 ipso-BPR 的两个过渡态势垒和两个产物能量。将使用的能量量追溯到所选原生计算块，处理 Gaussian 日志中重复的计算块，并把所选组合与至少两种不同备选规则比较。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

- 使用提供的 Gaussian、Molpro 输出和工作簿；仅抄录已发表数值不够。
- 对五个驻点报告来源文件并标明原生能量量及所选计算块，并说明所选计算块、组合规则、零点能校正、Hartree 到 kcal/mol 换算值及 BPR 参考物种。
- 根据原生计算核验物种与电子态：每个物种均为 21 个原子、57 个振动模式，多重度为 2；两个过渡态各有且仅有一个虚频，BPR 和两个产物均无虚频。结论限于该沉积簇体系和已报告剖面。
- 所选剖面的四个非参考能量须与工作簿值相差不超过 0.10 kcal/mol。在 `energy_rule.md` 中至少比较两种被排除的规则；按 C1、C2、P-C1、P-C2 顺序给出每种规则的四个预测值及对应带符号或绝对偏差，精度须在计算值的 0.02 kcal/mol 内。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 用于分析的来源记录与反应数据。 |

在 `/app/final/` 下提交四个文件：

- `bpr_profile.csv`：五行，对应 `BPR`、`C1`、`C2`、`P-C1`、`P-C2`；列为 `species,file_dft,file_f12,e_electronic_au,zpe_au,e_zero_point_au,e_f12_au,derived_kcal_per_mol`。BPR 推导能量为零。
- `bpr_profile.json`：`rule.rejected_alternatives[].scheme` 可使用 `dft_zero_point`、`dft_electronic`、`dft_gibbs` 或 `f12_only`。`rule` 含字符串字段 `electronic_source`、`correction_source`、`reference_species`、`unit` 和数值 `hartree_to_kcal`（与 627.509 相差不超过 0.001）；顶层含以四个非参考物种为键的 `derived_values_kcal_per_mol` 和 `published_values_kcal_per_mol`；`rule.rejected_alternatives` 至少有两个不同的 `{scheme, values_kcal_per_mol}` 记录，且每条含全部四个物种。电子能与校正量用化学方法名称或原生来源标识说明，以 BPR 为参考并使用 kcal/mol。请依据原生证据自行判断并论证所支持的组合。派生值与 CSV 相差不超过 0.01 kcal/mol，已发表值与工作簿相差不超过 0.01 kcal/mol。JSON 数值须有限。
- `energy_rule.md`：说明规则依据、单位与参考约定，至少列出两种命名备选规则及各自四个预测值和逐项对应偏差，顺序如上。将各规则的预测值和偏差分别列成表格行，行标识与 JSON 中的 scheme 名称一致，四个物种按上述顺序排列。用公式说明规则。
- `native_parse_manifest.json`：`records` 中为每个物种的 `zpe_au`、`e_zero_point_au`、`e_f12_au` 提供 `{species, quantity, source_file, value_au}`，数值须匹配该物种的原生输出。可选填 `label` 和 `line_number` 作为定位信息；若提供，须指向实际最新的匹配源行。路径可含 `assets/`，也可用唯一文件名；若用文件名，则设 `source_directory` 为 `Toluene-iBPR-rearrangment`。可选 `e_dft_gibbs_au` 或 `e_gibbs_au` 须追溯至该物种 Gaussian 日志最新的 Gibbs 行；每个物种/quantity 仅一条，Gibbs 别名二选一。

无需量子化学引擎。输入在 `/app/assets/`：`41467_2023_40675_MOESM1_ESM.docx`（SI）、`41467_2023_40675_MOESM3_ESM.xlsx`（Source Data）及 `Toluene-iBPR-rearrangment/` 下五个物种的 Gaussian/Molpro 文件。
