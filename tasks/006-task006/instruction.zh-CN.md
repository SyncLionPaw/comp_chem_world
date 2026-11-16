# 独立研究：实验 SNAr 活化自由能

## 背景

可靠预测未见 SNAr 反应，需要化学证据、计算和独立验证。本题不提供科学数据、指定来源或模型。

## 任务

研究外部证据及你实际执行的计算能否、以及在何种条件下支持可靠预测实验 SNAr 活化自由能。自主获取证据、界定范围、选择并论证方法、开展研究及评价结论。有证据支持的否定或不确定结果同样有效。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas、scikit-learn、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

使用 HPC 时，按 `ikkem-slurm` 的统一流程执行：探测已授权的目标，提交作业，等待终态，回收原生输出，再核验科学结果。

- 自主选择数据、方法、对照及验证；可访问公共互联网，并遵守环境资源限制。
- 定义物理量、单位、条件和总体，根据主张检查验证独立性、重复／相关观测及标签暴露；公开标签不是前瞻盲测。
- 区分外部结果与自行计算。保留输入、代码、原生输出及可得回执，包括失败／中止的尝试，记录关键决策和限制。
- 用可检查的计算、适当对照、不确定度及适用范围分析支持数值主张，区分证据与推测。不要求指定数据集、引擎、模型、准确度阈值或正向计算增益。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| — | 未预置科研数据。 |

```text
/app/final/
  claim.md
  provenance.json
  results.json
  native_evidence/             获取的输入、代码、原生输出及回执
```

```text
provenance.json:
  sources:    [{id,origin,acquisition,path}]
  decisions:  [{id,decision,reason,evidence_ids}]
  executions: [{id,stage,input_paths,output_paths,receipt_paths,status}]
  claims:     [{id,statement,result_ids,evidence_paths,source_ids,execution_ids}]
results.json:
  scope, validation
  conclusion: {status,rationale,limitations,claim_ids}
  quantities: [{id,name,value,unit,conditions,population,uncertainty,evidence_paths}]
```


`claim.md` 说明问题、方法、验证、结果和限制；代码／数据须足以复现核心数值结果。

上述结构中 `acquisition` 为 `acquired|constructed`，并说明 URL 或构造来源。来源文件置于 `native_evidence/`。每类 ID 为唯一非空字符串；引用对应来源、执行、主张或量。除来源 `path` 外，路径字段均为数组，使用提交目录内普通文件的相对 POSIX 路径，不用符号链接。回执不可得时可留空并披露限制；自报时间不构成独立证明。

`scope`、`validation` 为非空文本／对象；结论状态为 `supported|refuted|inconclusive`，附理由和限制。量为有限数值或非空嵌套数值数组，说明条件、总体和不确定度，未量化时披露限制。JSON 使用 UTF-8 且键唯一；允许方法专用字段／文件。

对可直接重算的标量汇总，可选 `results.json.checks` 每项为 `{id,quantity_id,path,operation,column}`。量的 `evidence_paths` 须引用该表；使用表头唯一、数值有限的 UTF-8 CSV。支持 `sum,mean,min,max,count,mae,rmse`，MAE/RMSE 另需 `reference_column`；count 指行数。兼容单位可用正数 `unit_factor` 换算；数值一致性容差为绝对 1e-8 加相对 1e-6。这些可选汇总不限制研究方法。
