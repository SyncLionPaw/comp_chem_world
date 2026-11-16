# 任务：同分子式候选异构体排序

## 背景

本包提供为一个大分子库计算的模拟红外谱。公开训练/验证集给出本任务之外分子的结构–谱配对；query 集只给出不透明标识符、分子式、谱，以及共享该分子式的一小组宪法异构体候选。候选顺序已被随机化。

源模拟库是公开的，因此某条 query 谱原则上可与外部参考表精确匹配。由此得到的一切结论都必须理解为在该库上的内部闭集重排结果，而不是独立的盲测泛化。

## 任务

为每个查询排序其构造异构体。评估原始谱相比仅用候选结构和使用频率打乱谱两种方法提供了多少额外信息。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas、pillow、PyYAML、RDKit、scikit-learn、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

提交三种排序。主要数值判据将完整谱排序的 Top-1 准确率与逐查询均匀随机选取候选的基线比较。准确率须高于随机期望，且单侧精确检验 p 值小于 0.05。仅候选排序和频率打乱排序作为诊断性对照。

**化学有效性。** 每个候选都必须是中性、连通、结构合法且符合 query 分子式的结构；用 RDKit 复核分子式与图的唯一性。每个 query 的每个候选必须在该 query 的排序中恰好出现一次，按递减的有限分数排列。

**不确定度。** 每套排序都带有 [0, 1] 内的不确定度，反映尚未排除的备选结构；这些是可解释的模型分数，不是校准过的概率。

**禁止的捷径。** 不得检索候选结构的源谱、不得查外部谱库、不得使用任何隐藏真值。

### 输入与产物细则

运行时输入以只读方式位于 `/app/assets/`：

- `cohort-train.npz`、`cohort-validation.npz` — 结构–谱配对，含 `sample_id`、`formula`、`spectra`、`smiles`、`group_labels`、`group_names`。
- `isomer-query-public.npz` — 含 `sample_id`、`formula`、`spectra`；谱矩阵形状为（query 数, 1791）。
- `isomer-candidates-public.json` — 每个 `query_id` 一道题，含 `formula`、`candidate_count` 与 `candidates`；每个候选带 `candidate_id` 与一个 SMILES 字符串。
- `axis-cm-1.npy` — 1791 点，400 至 3980 cm⁻¹，步长 2 cm⁻¹。
- `SOURCES.yaml` — 派生输入的来源说明。

向 `/app/final/submission.jsonl` 每行写入一个 JSON 对象，覆盖每个 `query_id` 在三个 `condition_id`（`full_spectrum`、`candidate_only`、`frequency_scrambled_query`）下的结果：

```
{"query_id": ..., "condition_id": ..., "uncertainty": <0..1>,
 "ranked_candidates": [{"candidate_id": ..., "score": ...}, ...]}
```

`full_spectrum` 依据 query 谱排序，`candidate_only` 只依据共享分子式与结构排序，`frequency_scrambled_query` 依据同一 query 谱但频率顺序按 query 打乱后的版本排序；该置换不得改变任何 query 或候选标识符。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 给定输入与资源目录。 |

**输入**

| 路径 | 内容 |
| --- | --- |
| `/app/assets/isomer-query-public.npz` | 含 `sample_id`、`formula`、`spectra` |
| `/app/assets/isomer-candidates-public.json` | 每个 `query_id` 一道题，含 `formula`、`candidate_count` 与 `candidates` |
| `/app/assets/axis-cm-1.npy` | 1791 点，400 至 3980 cm⁻¹，步长 2 cm⁻¹。 |
| `/app/assets/SOURCES.yaml` | 派生输入的来源说明。 |

**交付物**

将排序结果写入 `/app/final/submission.jsonl`。
