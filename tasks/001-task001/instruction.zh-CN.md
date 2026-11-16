# SNAr 反应与过渡态证据审计

## 背景

给定两个 SNAr 反应背景的计算记录，需区分有证据支持的局部结构和热化学结论与已确立的反应路径。

## 任务

审计八份 Gaussian 日志及其八份 GoodVibes 报告，诊断两项原生作业。解释驻点和反应模式证据，计算三组配平的候选态自由能差，分别评估局部机理、路径连接、正式能垒及全局与模型条件下的决速步骤。

只用给定记录，不运行量化或调度作业，不编造缺失证据。

## 要求

- 区分此前优化与频率步骤的收敛证据，报告失败的力／位移准则及全部负频率。零负频率本身不证明驻点；仅在来源证据不完整时采用保守的未定解释。
- 识别每份 Gaussian 记录中实际存在的反应中心、亲核原子和离去基原子，包括分离物种及零负模中间体，报告可得的 C–Nu、C–X 距离。对完整映射的负模式，将相对原子位移投影到对应键单位向量；两个投影可统一变号。来源未声明正规坐标的位移单位。
- 依据来源证据关联 Gaussian 与 GoodVibes，保留温度、浓度、QS 方法、截断值及缩放因子的区别。对每个恰有一个负频率的完整复合体，计算 qh-G(候选态) − qh-G(分离优化底物) − qh-G(分离优化亲核试剂)，同一背景与条件下系数为 +1、−1、−1。共有三项必需对照；可补充元素和电荷配平的其他对照，但不能替代这三项。
- 区分局部证据与已验证路径、正式能垒和全局决速步骤，独立说明模型条件下的决速步骤。区分原生引擎结果、失败模块及调度状态，判断是否建立 MPI/OpenFabrics 因果归因。原生近零频率定义为 |ν| < 1 cm⁻¹。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 已发表记录、基准数据与本题输入。 |

```text
/app/assets/                  给定背景、计算及原生作业记录
/app/final/
  artifact_audit.jsonl        八项 Gaussian 与两项原生作业评估
  thermochemistry.csv        八个来源行及至少三个差值
  mechanism.csv              每个背景一项判断
```

按下列简洁结构提交；可选说明或分析代码不必重复观测。

**`artifact_audit.jsonl`**：每条记录一个 JSON 对象。Gaussian 对象包含：

```text
source_file
prior_geometry_optimization:
  optimization_completed, stationary_point_observed, normal_termination（布尔值）
  failed_criteria（列表）
frequency_link_optimization_completed, frequency_link_stationary_point_observed（布尔值）
frequency_level_force_criteria: {failed_criteria: [...]}
negative_modes: [{frequency_cm-1: ...}, ...]
stationary_point_interpretation
thermochemistry_join: {final_scf_E_hartree: ..., gaussian_zpe_hartree: ...}
reactive_coordinate_projection:
  context_id
  central_carbon_atom_index_1based, nucleophile_atom_index_1based
  leaving_group_atom_index_1based
  C_Nu_distance_angstrom, C_X_distance_angstrom
  projected_C_Nu_change_raw, projected_C_X_change_raw
```

准则名使用 `Maximum Force`、`RMS Force`、`Maximum Displacement`、`RMS Displacement`，全通过时列表为空。驻点标签为 `optimized minimum candidate`、`first order saddle candidate`、`higher order saddle candidate` 或 `unresolved`。仅缺失角色或不可得的距离／投影可省略或为 null。投影对象也可名为 `projection`；唯一的源能量关联无需重复填写 GoodVibes 标识。

原生对象包含 `job_id`、`engine_termination` 及适用观测：

```text
成功作业：
  frequencies_count, negative_frequency_count, frequency_zero_or_near_zero_count
  geometry_converged（布尔值）, thermochemistry_temperature_K
  final_gibbs_hartree, coordinate_atom_count
失败作业：
  execution_state, scheduler_state, scheduler_exit_code
  mpi_openfabrics_causality: {established: <布尔值>, reason: <说明>}
```

可用唯一的作业限定来源定位代替 `job_id`。引擎状态为 `normal`、`failed_<module>`，或含 `status`、`failed_module`、`reason` 的对象；单独的 `failed` 状态需提供模块。显式身份及模块声明须一致。

**`thermochemistry.csv`**：`record_type` 为 `source` 或 `candidate_difference`：

```csv
record_type,source_file,source_ids,coefficients,identity_status,temperature_K,concentration_mol_L,qh_G_T_hartree,scale_factor,qs_treatment,frequency_cutoff_cm-1,candidate_delta_g_kcal_mol
```

来源行报告 qh-G(T) 及条件；差值行报告配对来源／系数、有证据边界的身份判断及 kcal/mol 差值。`qs_treatment` 写方法名，附注用分号、冒号或括号分隔。Gaussian 标识可关联其唯一 GoodVibes 配对。

**`mechanism.csv`**：

```csv
context_id,claim_scope,reactive_site,identity_status,mechanism,mechanism_evidence,rate_determining_step,model_conditional_RDS,barrier_status,path_connectivity
```

使用 `claim_scope:local_context`。有支持的位点写为 `C<i>/Nu<j>/F<k>` 或 `C<i>/Nu<j>/Cl<k>`，身份为 `supported_by_atom_inventory_and_reactive_geometry`；身份不明确时写 `ambiguous`，位点留空且机理为 `unresolved`。

化学判断只报告一次，使用以下简短主张，不用自由文字替代：

```text
mechanism: SNAr_candidate | stepwise_SNAr_candidate | unresolved
mechanism_evidence（CSV 单元格内的 JSON）：
  {"local_steps": {"<Gaussian 来源>": "addition_like|elimination_like"},
   "intermediate_candidates": ["<Gaussian 来源>"]}
model_conditional_RDS（CSV 单元格内的 JSON）：
  {"model": "none|irreversible_equal_prefactors_unit_activity",
   "step": "unresolved|addition|elimination"}
```

`local_steps` 覆盖该背景全部完整的单负模复合体，以 Gaussian 文件名或无歧义 stem 引用。对给定的异号 C–Nu／C–X 投影，以绝对值较大的分量区分加成型（C–Nu）或消除型（C–X）**局部候选**，不依赖模式整体符号。完整零负模记录列为中间体候选，不因此认证其稳定性或连接关系。逐步候选须同时有两类局部步骤及中间体候选；保守地报告 `SNAr_candidate` 或完整机理未定也有效。

`model:none` 对应条件步骤未定。另一模型假设不可逆串联加成／消除、相同动力学前因子及单位反应物活度，以平均完成时间的倒数 `k_add*k_elim/(k_add+k_elim)` 为观测量。比较 G(加成候选) − G(分离反应物) 与 G(消除候选) − G(中间体候选)，较大的局部 TST 差值对应条件慢步骤（0.01 kcal/mol 内相等时未定）。此模型需两类局部步骤和中间体候选，不证明真实全局决速步骤或路径连接；无需额外能量表。全局决速步骤与未验证能垒／路径状态独立报告，未定标签可用 `unresolved`、`unknown`、`not established`、`unassigned`，能垒／路径也可用 `unvalidated`。自由讨论可放在 `notes.md`，不能替代上述化学主张。

能量和频率保留来源打印精度；距离、投影及 ΔG 至少保留两位小数。原子索引从 1 开始，可选模式索引从 0 开始。数值须有限，JSON 键及 CSV 表头须唯一，布尔观测使用布尔值；数值相等的整数表示等价。来源可用精确文件名、无歧义 stem 或 context ID。来源／系数列表可用 JSON 数组（包括 CSV 单元格内）或逗号／分号分隔字符串；系数可为有限十进制数或数值字符串。配对不变时来源顺序不限；整体缩放的对照属于附加结果。不必抄录完整坐标／向量、来源行号、重复量或另列限制清单；已报告科学观测须一致。
