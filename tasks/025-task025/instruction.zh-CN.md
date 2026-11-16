# 任务：芳香族 BPR 速率的跨来源一致性

## 背景

沉积包含 15 个单温度 MESMER 输出，涵盖七种芳香族前体形成的双环过氧自由基。工作簿给出无行标签的 16 格速率表；原生文件可能有两个产物通道且温度不同。

## 任务

依据所给证据将已发表单元格映射到分子和加成位点，用合理的原生速率定义进行比较，报告不可调和单元格，并判断温度差异是否允许提出取代基趋势。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

- 读取每个 XML 的两个原生一阶通道速率并记录分子、位点、文件和条件。将全部 16 格与 channel1、channel2、较快通道或总和比较；缺少原生见证时，不可用字段留空。
- 对每个冲突报告全部候选定义、数值和相对偏差。不要强行使用统一定义或隐去未解释单元格。
- 按记录温度（298、298.15、300 K）比较。给出甲苯 ipso 从 298 到 300 K 的有限敏感性示例，分别考虑仅活化项和含温度指数的变化；评估现有温度证据是否足以归一化接近的跨分子排序。
- 判断是否有单一规则解释全部单元格，以及证据能否区分接近的跨分子排序。取代基趋势的范围须与数据支持的条件和不确定度一致。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 用于分析的来源记录与反应数据。 |

XML 位于 `/app/assets/Figure4/`，工作簿和 SI DOCX 位于 `/app/assets/`；化学别名为 ethylbenzene/E-Benzene、isopropylbenzene/I-Benzene。苯的唯一位点可标为 `ipso` 或 `unique`/等价位点；此别名仅适用于苯。不需运行 MESMER。于 `/app/final/` 提交：
- `bpr_rate_matrix.csv`：15 行，列 `molecule,oh_addition_site,source_file,temperature_K,pressure_Torr,bath_gas,k_channel1_per_s,k_channel2_per_s,k_dominant_per_s`。
- `cell_reconciliation.csv`：16 行，列 `molecule,oh_addition_site,published_value_per_s,source_file,temperature_K,matched_definition,matched_value_per_s,relative_deviation,reconciled`。定义为 `channel1,channel2,faster,sum,missing_native`。有原生见证时报告原生值；匹配容差 5%。缺失时来源、温度、匹配值和偏差留空。
- `anomalies.json`：含 `unreconciled` 数组，元素字段为 `{molecule,site,source_file,temperature_K,published_value_per_s,candidates,reason}`。候选字段为 `definition,value_per_s,relative_deviation`；有原生数据的冲突列出四种定义，缺失见证格的候选为空。
- `trend_evidence.json`：布尔值 `single_definition_claim`；`temperature_scope` 含 `recorded_temperatures_K,normalisation_status,toluene_ipso_298_to_300_activation_percent_range,with_n_percent,close_orderings_indeterminate`，可选 `activation_basis`。默认使用 270–310 K 局部修正 Arrhenius 拟合（`local_modified_arrhenius_fit` 或 `local_modified_arrhenius_fit_270_310K`）；也可用固定甲苯 ipso XML 的 TS1/TS2 静态势垒（`native_static_barriers`），并在分析中说明依据及对应 `n_eff`。`with_n_percent` 报告观测到的 298→300 K 通道变化：可给二元范围，或给主通道标量并在 `trend_analysis.md` 写明两个通道端点。范围和趋势只限现有证据；说明归一化为 `indeterminate` 或 `established` 的理由。
- `trend_analysis.md`：说明映射、冲突、温度、敏感性示例及普适归一化限制。

相对偏差 `d=(native-published)/published`（可带符号或取绝对值），按 `abs(d)<=0.05` 判断匹配。路径可相对资产目录、带 `assets/` 前缀或用唯一文件名；布尔值可用 true/false、yes/no、1/0 或 reconciled/unreconciled。缺失见证说明可用中英文。
