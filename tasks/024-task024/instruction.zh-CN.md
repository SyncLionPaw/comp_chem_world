# 任务：双环过氧自由基的条件性去向

## 背景

所给 SI 报告 O2 加成平衡常数、RO2 + NO 速率常数和有效去除速率极限估值。原生 MESMER XML 提供两个 BPR 开环通道。资料缺少独立验证所给平衡常数或前平衡条件所需的热化学与回返动力学。

输入与可用资源按下文说明；需要自行获取的资料仍由任务执行者获取。

## 任务

使用 /app/assets/ 中的 SI DOCX、Source Data 工作簿和 MESMER XML，定量分析双环烷基自由基的重排与 NO 竞争。无需运行 MESMER 或量子化学。对所选温度的两个原生通道求和，计算浓度、有效系数、竞争和平衡总池速率；仅比较物种基准相同的速率，并说明假设和限制。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

引用 SI Eq. (2) 及其参数陈述中的 K_eq 和 k_RO2+NO，说明 K_eq 未验证。给出温度、压力、O2 摩尔分数、NO ppbv、数密度和量纲一致的单位换算。报告以 B-alkyl 为基准的 MR/NO 速率、比值与分支分数、NO 交叉浓度及总池对比。300 K 下将 0.03 s^-1 上限与 BPR 基准的原生 k_mer 比较；有效速率和 k_oxy 使用 B-alkyl 基准，并保留 SI 估值及其物种基准。

敏感性分析至少覆盖两个原生温度、O2 水平和 NO 水平；使用各温度的原生 k_mer，标明固定 SI 参数，包含温度/压力/NO 相同而 O2 不同的一对（主条件可作其中一行），不外推 SI 温度依赖。推导同时含两个汇的有限回返 MR QSSA 式，以及以 [B-alkyl]+[BPR] 总浓度为基准的前平衡 MR 系数。通过 approximation.QSSA_MR_basis 或 expression_targets.QSSA_MR_expression 声明基准，值为 B-alkyl 或 total_pool；目标不明确时须提供前者，且不支持 BPR 基准。旧结果未声明时默认每 B-alkyl。pool_MR_expression 始终指总池基准，且须为前平衡系数，不得写成有限回返总池式。公式仅用 + - * /、括号及 k_add,k_return,k_mer,k_NO,NO,O2,K_eq，须为通用式并定义 K_eq=k_add/k_return。说明 k_return >> k_mer+k_NO*NO，披露 k_return 未知，并区分每 B-alkyl 的 SI 系数与总池逆寿命。

### 输入与产物细则

写入 final/fate_analysis.json、final/fate_sensitivity.csv、final/unit_conventions.json 和 final/conclusion.md。JSON 含 conditions,parameters,SI_provenance,native_rate_records,quantities,comparisons,competition,temperature_model,approximation；除数组 native_rate_records 外均为非空对象。conditions 含数值 temperature_K,pressure_Pa,x_O2,NO_ppbv。SI 参数 K_eq,k_RO2_NO 含 value,unit,basis=supplied_SI，且 K_eq.independently_verified=false。SI_provenance 用 source_file 或 source_asset 提供 SI 路径；二者并存时须一致。原生记录含 temperature_K,source_file,source_pressure_Torr,bath_gas,k_mer_per_s,channels；通道含 fromRef,toRef,rate_per_s。来源路径使用 assets/。

必需 quantities：air_molecules_cm3,O2_molecules_cm3,NO_molecules_cm3,k_mer_per_s,K_eq_cm3_per_molecule,k_NO_cm3_per_molecule_s,q_BPR_over_Balkyl,k_NO_pseudo_per_s,k_eff_MR_per_Balkyl_s,k_eff_NO_per_Balkyl_s,MR_fraction_two_sinks,k_MR_per_equilibrated_pool_s。必需 comparisons：prior_ceiling_per_BPR_s,prior_reference_species,prior_comparison_temperature_K,MR_over_prior_BPR_ceiling,k_oxy_per_Balkyl_s,MR_effective_over_oxy_Balkyl,SI_effective_MR_per_s,SI_effective_NO_per_s。competition 含 MR_over_NO,MR_fraction_two_sinks,NO_crossover_ppbv、恰好两个 MR/NO 汇及 other_sinks_excluded；汇可用字符串或含 sink 标识的对象表示。若提供 number_of_sinks 或 sink_count，须为 2；included/is_included 须为 true。汇身份或排除声明矛盾时无效。NO 为零时比值用 JSON null。

temperature_model 含 K_eq,k_RO2_NO,thermodynamic_prediction=false,bath_gas_composition_recomputed=false,source_pressure_Torr。参数可用 `fixed_SI` 字符串，或用与 SI 一致的数值/单位及 label 或 basis=`fixed_SI`、temperature_dependence_applied=\"none\"。approximation 必需 QSSA_MR_expression,pool_MR_expression,return_must_dominate_sink_sum,k_return_known,K_eq_independently_verified,explanation。可用 QSSA_MR_basis 或 expression_targets 声明 QSSA 基准。

CSV 含条件、所有必需数量、source_pressure_Torr 和 scenario_kind=fixed_K_eq_and_k_NO。单位 JSON 含 k_B_J_per_K,N_A_per_mol,Pa_per_atm,cm3_per_m3,cm3_per_L,mole_fraction_per_ppbv,K_eq_L_per_mol,k_NO_L_per_mol_s,molar_to_molecular_factor 及可核验的摩尔浓度换算恒等式，可置于 `concentration_relation`、`concentration_expression`、`concentration_identity_molar` 或 `molar_concentration_identity`。`concentration_expression` 也可给出理想气体数密度；所有给出的摩尔换算恒等式须一致，等式方向不限。分子制单位可用 cm3/molecule (/s) 或等价 cm³ molecule⁻¹、cm^3 molecule^-1 s^-1；摩尔制可用 L/mol (/s) 或 L mol⁻¹ (/s)。浓度表达式可用 N_A 或 N_A_per_mol 与 mol_per_L、cm3_per_L。任何旧式表达式均须通过对应单位数值核验；若因子表示参数换算，另给 molar_to_molecular_factor_for_concentrations。结论概述竞争、物种基准、条件、固定 SI 温度假设和限制。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 用于分析的来源记录与反应数据。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
