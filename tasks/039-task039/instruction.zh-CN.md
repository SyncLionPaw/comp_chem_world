# 任务：有限预算下的外球抽样与 Marcus 推断

## 背景

本任务重分析已完成的 revision 3（R3）外球能隙研究。公开材料包括水/K、中性/阴离子原始轨迹、冻结抽样设计、方法与预算说明，以及 R3 原生计算归档。本轮只分析这些证据，不执行 DFT/MD 或提交 HPC 作业。

## 任务

从冻结设计和原生记录重建各态能量、局部能隙、有限轨迹总体的设计估计及设置敏感性，并判断总体量和 Marcus 模型量的可识别性。目标对象为有限轨迹总体；丢弃前 2000 帧不证明已平衡。清楚区分归档中的既有计算和本轮分析，历史尝试数不得写成本轮新增计算。

## 要求

按 `gap_eV = E_anion_eV − E_neutral_eV` 重建能隙，保留逐态 DFT 与 TS09 分项及原始来源。核验配对态的同几何、原子映射、总电荷、局域电荷和收敛。复核至少两组来自阴离子系综、采用严格设置且几何相同的中性态和阴离子态配对，把设置敏感性与样本差异分开。区分 existing helper、逐态 TS09 和标准 free/extrapolated 能量约定；不得把它们视为等价或唯一物理 diabatic 能量。也须区分 MD、原始 vertical 与 R3 的状态/自旋协议。M=0 本身既不能证伪某个态，也不能证明全局最低态或自由基身份。

报告分层抽样的 HT 点估计、纳入概率及其限制。层内不同帧的联合纳入概率为零，设计方差不能无偏识别；不得用两点 IID bootstrap 或正态性检验给出无条件总体区间。HT 均值不验证代表性。证明或以反例说明总体均值、方差及水/K 排序的可识别性，并在可辩护的能隙边界或分布假设下分析结论是否翻转；没有可靠边界时保留为未知。

分别讨论数值设置误差、有限总体设计误差、MD 非遍历性和 Marcus 模型误差。收敛阈值不构成总误差上界。对总体排序、Marcus 参数/能垒、化学态身份及物理能量解释，依据证据和明确假设各自选择并论证适当状态（`supported`、`conditional` 或 `not_established`），不预设科学结论。数据不足以支持的参数用 JSON `null` 并说明原因。追加计算方案可针对公开的六类不确定性之一：有限总体抽样、数值设置误差、MD 时间相关、化学态身份、热力学转移或 Marcus 能隙分布。须提供该目标专属的 `proposal_details`、至少一个缺失前提、两个不同的可能结果及诚实的资源估计。抽样方案须引用经验证的信息增益设计；其它目标须使用自己的类型化方案细节。数值设置方案须在无既有 tight 重算的冻结几何上，以现有 base 设置为基准比较中性态和阴离子态。化学态身份方案须提出两种明确的 CO₂ 位点初始磁矩 SCF 变体（`co2_site_initial_moment_0_mu_B` 和 `co2_site_initial_moment_1_mu_B`），保持几何、电荷和 Hamiltonian 相同，并指定自旋/电荷诊断。MD 时间相关方案可采用一条延长轨迹或独立副本，并提供自相关和分块敏感性诊断。静态计算量按几何 × 状态 × 新设置变体计数；动态方案报告副本数和步数，不得虚构态计算次数。未知成本用 `null` 和 `not_estimated`，不得写成零。仅提出方案，不实际执行。

### 输入与产物细则

交付字段、类型、单位、容差、来源约束和重放布局以 `/app/assets/output-contract.json` 为准。将 13 项规定产物写入 `/app/final/`：`sampling_plan.json`、`decision_log.json`、`energy_gaps.csv`、`marcus.json`、`native/`、`analysis.py`、`report.md`、`source-manifest.json`、`budget-interpretation.json`、`scientific-claims.json`、`standard-electronic-gap-diagnostics.json`、`standard-electronic-gap-diagnostics.csv`、`sampling-design-audit.json`。

`scientific-claims.json` 须遵循 `case04-scientific-claims/v2.2`：报告带值、单位和作用域的来源量；列明假设；报告候选人计算的证明结果；并提供状态针对目标命题的类型化 claims。只能使用公开合同中具有完整证明语义的谓词。每个 claim 必须引用自身目标和作用域所需的证明；单独假设或无关证明不能支持它。后续计算方案须仅选择一个不确定性目标，并匹配其公开 observable/calculation class；关联 relevance proof 须验证同一目标，且方案须写明缺失前提和两种可能结果。只有有限总体抽样目标使用抽样设计 proof。集合型 scope.id 的分号成员可任意排序，但不得留空、重复、缺项或多项。对 `cross_ensemble_contrast` claim，`scope.id` 编码为有序 `<left_ensemble>-minus-<right_ensemble>` 配对；多组配对以分号连接，并须与其引用证明完全一致。证明协议定义归一化来源字段类型；未知或未显式指定的值不能证明差异。证明某总体量不可识别，意味着目标排序仍为 `not_established`，不表示目标排序本身 `supported`。报告的证明结果须能追溯到冻结来源和原生记录。

`report.md` 仅使用中性标题 `Overview`、`Evidence`、`Methods`、`Inference`、`Limitations`、`Follow-up`，以及 `{{claim:<claim_id>}}` 格式的行；每个 claim 都须被引用。不得添加解释性散文、表格、HTML、注释、隐藏文本或额外交付附件。输出 JSON 的解释字段只能使用可解析到已验证证明的 `proof:<proof_id>` 引用；固定来源标签和 schema 枚举不属于解释字段。

输入均在 `/app/assets/` 下：

- `water_CO2/`、`water_CO2anion/`、`2K_CO2/`、`2K_CO2anion/` 各目录中的 `10ps.traj` 与 `calc.py`。
- `computegaps.py`、`methods.json`、`OS_budget.json`。
- `revision3/tasks.json`、`revision3/sampling_plan.json`、`r3-native-raw.tar.gz`。
- `output-contract.json`，包含上述交付与证明约定。

`analysis.py` 是需要编写的提交产物。下述重放工作区并非镜像中预置的目录，须从公开输入建立：将脚本放在 `analysis/revision3/analysis.py`，恢复的原生记录放在 `analysis/revision3/native/`；将提供的 `revision3/tasks.json`、`revision3/sampling_plan.json` 复制到 `runtimes/hpc/case04/review-v3/`，将 `methods.json` 复制到 `inputs/methods.json`。以上路径均相对于重放工作区根目录。从该根目录无参数执行 `python3 analysis/revision3/analysis.py`，须在脚本旁重算 `energy_gaps.csv` 和 `marcus.json`。最终仍按上述约定将脚本、生成结果和原生证据提交到 `/app/final/`。不要将输入轨迹或历史计算误写为本轮产生的证据。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/output-contract.json` | 给定数据、参数或方法说明；用途见任务要求。 |
| `/app/assets/` | 给定输入与资源目录。 |
| `inputs/methods.json` | 给定数据、参数或方法说明；用途见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
