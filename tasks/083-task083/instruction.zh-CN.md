# 任务：模拟红外谱中的官能团信号

## 背景

本包提供为一个大分子库计算的模拟气相红外谱，以及每个分子携带的官能团。公开训练集与验证集给出结构–谱配对；盲测集只给出不透明标识符、分子式与谱。官能团取 SI §6 中结构明晰的八类：alcohol、carboxylic acid、ester、ketone、alkene、alkyne、benzene、cyano；二/三级胺被排除，因其 SMARTS 口径存在争议。

由于源库是公开的，某条谱原则上可与外部参考表精确匹配。在本包内标识符是不透明的，运行时只暴露派生后的谱，因此任何关于"光谱信息"的结论都应理解为在该公开库内部进行的诊断，而不是独立的盲测泛化。

## 任务

为这八个类别建立一个可解释的多标签分类器，只使用训练集拟合、在验证集上检查，然后用于盲测集。科学问题不是分类器能否预测官能团，而是**光谱是否携带了超出分子式的信息**——仅凭分子式约束的先验就已经大幅缩小了可能的类别。

回答方式是把盲测排序与两个参照比较：由训练标签导出的仅公式先验，以及一个对照——把每条盲测谱替换为同分子式组内另一条谱的循环移位版本。提交用于结合盲测标签估计增益及不确定度的预测。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas、pillow、PyYAML、RDKit、scikit-learn、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

**分类器。** 必须是作用于 1791 点光谱的线性一对多（one-vs-rest）模型，使得提交的概率可由提交的参数精确复现。逐谱缩放只能使用训练数据拟合。

**条件。** 对每条盲测样本提交 `full_spectrum` 预测；对每个含至少两条谱的盲测分子式组，对其成员提交 `within_formula_spectrum_shuffle` 预测。移位对照定义如下：把盲测样本按分子式字符串升序分组；组内按 `sample_id` 升序排列，组大小为 `n`。对分子式 `f`：

```
seed   = int.from_bytes(SHA256(UTF8("ir-local-formula-row-shuffle-v1|20261005|" + f))[:8], "little")
offset = numpy.random.default_rng(seed).integers(1, n)
```

排序后第 `j` 行的输出谱取自排序后第 `(j + offset) mod n` 行的原始谱。标识符与分子式不变，大小为 1 的组不参与该对照。移位必须与任何模型输出无关地确定。

**频带。** 报告模型所依赖的频带，只用训练数据选择并在验证集上独立确认。每条频带是一个窄区间，含 cm⁻¹ 范围、方向、验证集效应及其不确定度。未能在验证集上获得支持的频带也必须如实报告。

验证字段会由公开验证集重算，因此必须严格按下列定义给出。验证集每条谱先按行除以 `max(max(abs(spectrum)), 1e-12)` 归一化；窗口特征是这些归一化强度在满足 `lo <= axis <= hi` 的坐标点上的均值。`validation_mean_difference` 为正例特征的均值减去负例特征的均值，**不**随 `direction` 翻转。`validation_ci95` 是 500 次分子式聚类自举的 2.5% 与 97.5% 分位数：按文件顺序把验证集各行分成分子式聚类，种子为

```
seed = int.from_bytes(SHA256(UTF8("ir-local01-band-bootstrap-v1|20261104|" + f"{group}|{lo:.1f}|{hi:.1f}"))[:8], "little")
```

每次自举有放回地抽取与聚类数同样多的聚类、取其全部谱，仅当该次抽取同时含正负两类时才记录"正例均值减负例均值"。

**比较。** 科学比较包括盲测排序相对仅公式先验，以及符合条件的分子式组中干净谱相对移位对照；比较量为平均精度增益及其分子式聚类自举区间。公开输入不含盲测标签：请按要求的行集提交预测，不要自行报告依赖盲测标签计算的增益或区间。只有两项增益均得到支持，证据才可判为 resolved。

不得使用盲测标签做拟合或频带选择，也不得查阅外部谱库。

### 输入与产物细则

运行时输入以只读方式位于 `/app/assets/`：

- `cohort-train.npz`、`cohort-validation.npz` — 含 `sample_id`、`formula`、`spectra`、`smiles`、`group_labels`、`group_names`；类别列顺序严格按 `group_names`。
- `cohort-blind-test.npz` — 只含 `sample_id`、`formula`、`spectra`。
- `axis-cm-1.npy` — 1791 点，400 至 3980 cm⁻¹，步长 2 cm⁻¹。
- `SOURCES.yaml` — 派生输入的来源说明。

把交付物写入 `/app/final/`：

- `submission.csv` — 表头为 `sample_id,condition_id,` 后接按 `group_names` 顺序的八个类名。`condition_id` 取 `full_spectrum` 或 `within_formula_spectrum_shuffle`。概率为 [0, 1] 内的有限值。
- `model.npz` — 以 `allow_pickle=False` 读取；只含数值数组：`coef` (8, 1791)、`intercept` (8,)、`scaler_mean` (1791,)、`scaler_scale` (1791,)，全部有限且尺度严格为正。每条谱先除以 `max(max(abs(spectrum)), 1e-12)`，再按 `(x - scaler_mean) / scaler_scale` 标准化，最后通过 `x @ coef.T + intercept` 的 logistic sigmoid。
- `band_evidence.json` — `classes` 以全部八个组名为键；每项是 1–5 条频带的列表，每条含 `range_cm1` `[lo, hi]`、`direction`（`higher_in_positive` 或 `lower_in_positive`）、`validation_mean_difference` 与 `validation_ci95`。区间有限、位于 400–3980 cm⁻¹ 之内、宽度不超过 4 cm⁻¹、至少覆盖一个坐标点，且同一类内不重复。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 给定输入与资源目录。 |

**输入**

| 路径 | 内容 |
| --- | --- |
| `/app/assets/cohort-blind-test.npz` | 只含 `sample_id`、`formula`、`spectra`。 |
| `/app/assets/axis-cm-1.npy` | 1791 点，400 至 3980 cm⁻¹，步长 2 cm⁻¹。 |
| `/app/assets/SOURCES.yaml` | 派生输入的来源说明。 |

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/final/submission.csv` | 完整字段、单位和内容按上文要求。 |
| `/app/final/model.npz` | 以 `allow_pickle=False` 读取 |
| `/app/final/band_evidence.json` | `classes` 以全部八个组名为键 |
