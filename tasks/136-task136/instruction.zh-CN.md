# 任务：已发表 TNEP 数值与约定复核

## 背景

复核已发表的 TNEP 数值与约定，包括物理定义及已报告证据的边界。

## 任务

记录所用来源版本及精确出处。根据原始来源填写下列单元格，并评估科学约定及汇总证据的边界。

下列 `(table, cell)` 标识列出必须报告的数值。请从来源文档确定数值、单位和证据边界。

### 必需数值单元格

| 来源 | 单元格标识 |
|---|---|
| Table 1 | H2O rmse; H2O rrmse; (H2O)2 rmse; (H2O)2 rrmse; H5O2+ rmse; H5O2+ rrmse; liquid water rmse; liquid water rrmse |
| Table 2 | H2O diag rmse; H2O offdiag rmse; (H2O)2 diag rmse; (H2O)2 offdiag rmse; H5O2+ diag rmse; H5O2+ offdiag rmse; liquid water diag rmse; liquid water offdiag rmse |
| QM7B | dipole rmse per atom; alpha diag rmse per atom; alpha offdiag rmse per atom; dipole r2 |
| Table S1 | H2O Nneu; QM7B Nneu; rRc; rAc |
| Table S2 | BaZrO3 Nneu; BaZrO3 Ngen; BaZrO3 Npop; BaZrO3 nmax |
| Table S3 | liquid water Nneu; liquid water Ngen |
| Text | BaZrO3 structures; BaZrO3 R2 diagonal; BaZrO3 R2 off-diagonal; OH stretch FWHM cm-1; experimental FWHM cm-1 |

`Text` 表示正文，提交的 table 标识仍为 `Text`。

### 约定与证据边界

对每个固定主题，同时提供有出处的文字陈述和记录结论的结构化字段。相关单位约定须采用来源所报告或定义的一套一致单位体系，并说明依据。使用以下字段形状，但不要从本说明中预填内容：

示例中的 `<boolean>` 是占位符：请将其替换为不带引号的 JSON `true` 或 `false` 值。

在 `liquid water dipole normalization` 对象中，`count` 是可选的来源备注；若提供，必须是有限的非负整数。

方程请写成普通算术等式：显式写出乘法和除法，整数幂使用 `^` 或 `**` 表示。

```json
"normalized": {
  "liquid water dipole normalization": {"entity": "<entity>"},
  "qm7b normalization": {"denominator_entity": "<entity>"},
  "unit conventions": {"mu": "<unit>", "alpha": "<unit>", "chi": "<unit>"},
  "clausius-mossotti": {"equation": "<equation>", "applicability": ["<condition>"]},
  "chi/rho reconstructability": {"unique": "<boolean>", "reason": "<reason>"}
}
```

每个固定主题都要提供一条有来源依据的陈述：

- `liquid water dipole normalization`
- `qm7b normalization`
- `unit conventions`
- `clausius-mossotti`
- `chi/rho reconstructability`

对于 `chi/rho reconstructability`，请判断在仅给出报告中的 `chi/rho` 比值、且没有独立提供 `chi` 或 `rho` 数值时，能否唯一重建分子极化率 `alpha`。对于 `clausius-mossotti`，请解释该关系适用的相关物理前提，并评估所述适用条件是否完整；可以报告多个条件。

请至少评估以下一个固定类别所代表的推断是否有足够的已发表证据支持。`hardware_performance_extrapolation` 询问报告的测量结果是否足以支持对未测试硬件或超出所研究系统尺寸范围的性能主张；`per_configuration_error_distribution` 询问报告的汇总指标是否能确定逐个构型的误差分布。`claim` 和 `why` 必须针对所选固定推断。记录独立得出的布尔判断和基于来源的理由。类别名称和 `unsupported` 键名用于组织报告；具体判断须由来源证据支持。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

对每个单元格，报告数值、来源中印出或隐含的单位、约定以及精确出处（页码/表格/行或章节）。定义不同的单元格不要合并。转录误差指标的相对容差为 2%；R² 和 OH 伸缩振动 FWHM 为 1%；实验宽度比较为 3%。离散计数和超参数设置须与来源完全一致。单位字符串可使用来源记法或明确无歧义的 ASCII 等价形式；若数值按明确的十进制倍率表示，也可在单位中保留该倍率。无量纲 RRMSE 和 R² 可使用百分数记法。本说明不为各单元格指定单位。

自动检查核验结构化数值和约定字段。引用来源的文字说明及其与结构化结论的一致性须经科学复核。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/inputs/` | 本题的来源材料与科学输入。 |

在 `/app/final/reconciliation.json` 写入：

```json
{
  "values": [{"table": "Table 1", "cell": "<identifier>", "value": 0,
              "units": "<unit found in source>", "provenance": "<page/table/row>"}],
  "normalized": {},
  "conventions": [{"topic": "<fixed topic>", "statement": "<your conclusion>",
                    "basis": "<source location>"}],
  "unsupported": [{"category": "<evidence-boundary class>", "supported": "<boolean>",
                   "claim": "<claim>", "why": "<evidence-based reason for your assessment>"}]
}
```

每个必需单元格须恰好出现一次，数值须有限。结构化约定和文字结论须彼此一致，并能由所引来源支持。科学来源仅限官方论文及其补充信息。
