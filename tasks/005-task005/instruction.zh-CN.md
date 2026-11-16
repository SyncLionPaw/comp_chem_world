# 盲化原生证据审查

## 背景

五个盲化挑战使用 ORCA 记录，考察一次双路径比较及四类证据质量问题。

## 任务

按每个挑战的 `source_evidence_ids` 通过 `evidence-index.csv` 追溯记录。评估主要及列出的主张，报告所需观测和有证据支持的问题，仅在依据充分时比较能垒。区分数值电子能量排序与对实验产物偏好的信心。

## 要求

- 结论基于给定原生证据。引用相对解压目录的路径及索引中的内容标识；`metadata-index` 指由 `bundle-manifest.json` 标识的任务索引。
- 使用给定操作性准则：显著 TS 虚频指沿映射反应坐标低于 −100 cm⁻¹ 的频率。极小值判断依据负频率计数；|ν| < 10 cm⁻¹ 视为不确定，低于 −20 cm⁻¹ 的模式不符合极小值判据。依赖 IRC 的主张要求两个方向均收敛；只比较单点协议匹配的能垒。
- 有依据的双路径比较须报告 kcal/mol 能垒及其数值顺序。报告容差为 0.02 kcal/mol、1e-6 Eh 和 0.1 cm⁻¹，不代表科学确定性；计数及观测类型须符合原生记录。
- `near_degenerate` 指绝对能垒差 <1.0 kcal/mol；`confidence` 针对实验产物偏好。主张为 `supported`、`contradicted` 或 `underdetermined`；请求的判定尚未解决时用 `insufficient_evidence`。信心须有证据依据。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/participant-audit-v2.zip` | 挑战说明、证据与提交格式。 |

```text
/app/assets/participant-audit-v2.zip   挑战说明、证据及已有输出格式
/app/input/                          解压目录
/app/final/submissions/
  <case_id>.json                     每个挑战一项评估
```


解压后按各挑战的 `submission_schema`，使用包根目录已有的 `submission.schema.json`。每个结果包含判定、支持的问题、主张评估和类型化观测，引用采用从证据索引复制的 `{path,sha256}`。仅在适用时报告能垒、排序、近简并及信心。Schema 约定输出格式，不提供科学答案。
