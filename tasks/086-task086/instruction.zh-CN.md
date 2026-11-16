# 任务：复核官能团识别结果与失效解释

## 背景

本包包含一篇模拟红外研究的主文、其补充信息（SI）以及补充工作簿，其中公开了该研究的官能团识别结果。结果只以聚合表形式给出：逐类支持数与 Top-k 百分比、逐类 precision/recall/F1，以及易混官能团对之间的相对过/欠代表矩阵。同一名称会在不同表下以不同分母重复出现。

你的任务是独立于原始叙述去核对这些公开聚合量：厘清每张表实际描述的是哪个样本总体、公开数字支持哪些官能团结论、哪些仍只是原始提出的机制假设，以及哪些因果表述超出了聚合数据所能支持的范围。

## 任务

阅读给定来源，产出一份机器可读的核对结果。需要回答的问题是：

- 各公开表覆盖多少个类别，以及它们的整体性能如何。
- precision/recall/F1 与识别出的支持数之间是什么关系，以及在"表中显示的 count 代表什么"这一显式假设下，哪些混淆整数与打印出的逐类指标**相容**。
- 哪些组名在两套表中以不同分母出现，两个支持数相差多少。
- 哪些组对在错误中相对过度/不足代表，方向如何。
- 哪些解释是这些聚合量中的直接证据关联，哪些是原始关于频带重叠的假设，哪些必须有样本级数据才能建立。

无需任何新的测量：所有提交值都从给定来源转录，或按所述公式从这些来源计算得出。

## 要求

### 提交结构

把 `submission.json` 写成一个 JSON 对象，结构严格如下；数值与解释必须从给定来源独立得出。

```json
{
  "summary": {"figure4_class_count": 0, "figure4_macro_top1_percent": 0.0, "table6_class_count": 0, "macro_f1": 0.0, "support_weighted_f1": 0.0},
  "figure4_metrics": [{"group":"", "count":0, "top1_percent":0.0, "top5_percent":0.0, "top10_percent":0.0}],
  "class_metrics": [{"group":"", "support":0, "precision":0.0, "recall":0.0, "f1":0.0}],
  "conditional_support_assumption": "",
  "conditional_confusion": [{"group":"", "tp":0, "fp":0, "fn":0}],
  "category_counts": [{"source_id":"si_section6_smarts|si_table5|si_table6", "count":0}],
  "cross_table_comparisons": [{"group":"", "source_a":"", "count_a":0, "source_b":"", "count_b":0}],
  "error_relations": [{"source":"", "row_group":"", "column_group":"", "value":0.0, "direction":"overrepresented|underrepresented|neutral"}],
  "interpretations": [{"code":"support_association|spectral_overlap_hypothesis|error_composition", "evidence_refs":[], "causal_claim":false, "limits":[]}],
  "limitations": [],
  "follow_up": "optional exploratory proposal"
}
```

`summary`、`figure4_metrics`、`class_metrics`、`conditional_support_assumption`、`conditional_confusion`、`category_counts`、`cross_table_comparisons`、`error_relations`、`interpretations`、`limitations` 为必填，`follow_up` 可选。

### 固定字段规则

- `summary`：`figure4_class_count` 为 Figure 4 的数据行数；`figure4_macro_top1_percent` 为该表 Top 1% 列的未加权均值；`table6_class_count` 为 Figure 5 的数据行数；`macro_f1` 为 Figure 5 中 F1 列的未加权均值；`support_weighted_f1` 为按该表显示 `count` 加权的 Figure 5 F1 均值。
- `figure4_metrics`：Figure 4 每个数据行一个对象，保留来源的 `count` 与百分比（沿用来源的百分比单位）。
- `class_metrics`：Figure 5 每个数据行一个对象；`support` 等于来源显示的 `count`，precision/recall/F1 取来源小数。
- `conditional_support_assumption` 固定为 `figure5_displayed_count_assumed_positive_class_support`。
- `conditional_confusion`：Figure 5 每行一个对象，含非负整数 `tp`、`fp`、`fn`。这是在"显示 count 即正类支持数"这一显式假设下做的条件整数重建，**不是**实测混淆矩阵。必须满足 `tp + fn = count`，且这些整数须在舍入容差内复现来源的 precision、recall、F1。不得把该重建当作样本级混淆统计。
- `category_counts`：每个官方来源一个对象，`source_id` 取固定值 `si_section6_smarts`、`si_table5`、`si_table6`。`count` 是该来源中定义或列出的**不同类别数**——不是某个输入文件的行数，也不是样本支持数。
- `cross_table_comparisons`：对象 `{group, source_a, count_a, source_b, count_b}`。至少比较两套表中同名但分母不同的组 `Tertiary Amine` 与 `Benzene`：Figure 4 对应 `si_table5`，Figure 5 对应 `si_table6`，两个 count 分别从各自表中转录。不得把两个支持数当作同一样本分母。
- `error_relations`：对象 `{source, row_group, column_group, value, direction}`。`source` 固定为 `workbook:Figure6`。报告 Figure 6 中行 `Secondary Amine` 与列 `Amide`、`Primary Amine`、`Tertiary Amine` 的单元格，转录其数值；`direction` 在正/负/零时分别取 `overrepresented`/`underrepresented`/`neutral`。Figure 6 表示错误中的相对过/欠代表，不是相关性或因果。
- `interpretations`：恰好三个对象，分别对应 `code` 取值 `support_association`、`spectral_overlap_hypothesis`、`error_composition`。每个对象都带 `evidence_refs`、`causal_claim: false` 与 `limits`，且 `limits` 至少含 `aggregate_only` 与 `association_not_cause`。引用只能使用 `main_p7`、`si_table6`、`si_table5`、`si_section6`、`workbook_figure4`、`workbook_figure5`、`workbook_figure6`，且每个 code 必须引用其直接来源：`support_association` 需要 `main_p7`、`si_table6`、`workbook_figure5`；`spectral_overlap_hypothesis` 需要 `main_p7`、`si_table6`；`error_composition` 需要 `main_p7`、`workbook_figure6`。
  - `support_association` 另带 `low_support_classes` 与 `counterexample`。`low_support_classes` 列出 Figure 5 中所有满足 `count < 100` 的行，每项为从 Figure 5 转录的 `{group, support, f1}`。`counterexample` 是主文中关于支持数多少与识别性能讨论所给的高支持、较低 F1 反例，取 Figure 5 的 `Secondary Amine` 行，形如 `{group, support, f1}`。两者都只用于展示关联与反例；都不支持"支持数变化驱动性能"的推断。
  - `spectral_overlap_hypothesis` 另带 `groups` 与 `band_cm1`。`groups` 恰为 `Secondary Amine`、`Amide`、`Primary Amine`、`Tertiary Amine`；`band_cm1` 是主文报告的重叠区间，写成 `[下界, 上界]` 的 cm⁻¹ 数对。这是给定的频带重叠假设，并未被这些聚合表证明。
  - `error_composition` 另带 `figure6_semantics`，固定为 `relative_over_underrepresentation_in_errors_not_correlation`。
- `limitations` 至少含 `aggregate_not_sample_level`、`no_causal_identification`、`table5_table6_denominators_differ`、`conditional_confusion_only`，且这些限制须体现在文字结论中。`follow_up` 是可选字段，用于提出获取样本级证据的途径。

聚合混淆数据无法建立样本级因果，支持数多少也无法在这些表内与频带拥挤分离开来；文字解释必须停留在这些限度之内。

### 输入与产物细则

运行时输入以只读方式位于 `/app/assets/`：

- `official_main_article.pdf`、`official_supplementary_information.pdf` — 主文与其 SI，含上文引用的 Table 5 / Table 6 语义与频带拥挤讨论。
- `official_supplementary_data.xlsx` — 含 Figure 4、Figure 5、Figure 6 工作表的补充工作簿。
- `figure4_structure_topk.csv`、`figure5_group_metrics.csv`、`figure6_error_over_under.csv` — 从工作簿抽出的三张结果表。
- `SOURCES.yaml` — 抽出输入的来源说明。

把交付物写入 `/app/final/submission.json`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 给定输入与资源目录。 |

分析结果写入 `/app/final/submission.json`。源数据表和 `SOURCES.yaml` 是 `/app/assets/` 下的输入。
