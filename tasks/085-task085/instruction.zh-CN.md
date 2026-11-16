# 任务：受控模拟光谱扰动下的预测稳定性

## 背景

本包提供为一个大分子库计算的模拟红外谱，并按 SI §6 记录公开分子的八个官能团类别。同一批盲测谱提供了五种扰动形式作为条件：两种采样相位切分（`phase400`、`phase402`）、两种高斯平滑（`smooth075`、`smooth125`），以及逐谱的频率打乱。

这些扰动都留在模拟源域之内。它们不模拟仪器标定，不等价于刚性 ±2 cm⁻¹ 平移，也不能说明对实测 NIST 谱的泛化能力。

## 任务

只用公开数据训练一个轻量的八类预测器，然后检验它在这些扰动下是否稳定。一个在平滑与重相位后仍保持的干净排序，说明模型读取的是宽频带结构，而不是某个窄特征或频率坐标的任意排列。

频率打乱用于检验频率位置的作用。打乱后仍有预测能力，不能据此证明模型利用了频率定位信息。干净条件必须先相对仅公式基线、并相对打乱对照成立，之后任何扰动结果才能被解读为该模型的稳健性。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas、pillow、PyYAML、RDKit、scikit-learn、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

**模型。** 作用于 1791 点光谱的线性一对多 logistic 模型，scaler 只用训练数据拟合，使每个条件的概率都能由提交参数精确复现。

**条件。** 对每条盲测样本，在共同分析坐标上给出全部六个光谱条件与仅公式基线的概率。扰动输入按下方变换定义；频率打乱按样本标识符设定种子，因此标识符、分子式与候选顺序都不受影响。

**不确定度。** 科学比较包括干净条件相对基线和相对频率打乱的平均精度增益及分子级自举区间，也包括扰动下的概率漂移与标签翻转。公开输入不含盲测标签：请提交这些比较所需的成对概率，不要自行报告依赖盲测标签计算的增益或区间。这些诊断量是描述性的：干净条件必须先胜过两个对照，才能据此主张稳健性。

**禁止的捷径。** 不得复用未经审计的原始 checkpoint，也不得使用盲测标签做拟合。

### 输入与产物细则

运行时输入以只读方式位于 `/app/assets/`：

- `cohort-train.npz`、`cohort-validation.npz` — 含 `sample_id`、`formula`、`spectra`、`smiles`、`group_labels`、`group_names`；类别列顺序按 `group_names`。
- `cohort-blind-test.npz` — 只含 `sample_id`、`formula`、`spectra`。
- `axis-cm-1.npy` — 1791 点，400 至 3980 cm⁻¹，步长 2 cm⁻¹。
- `SOURCES.yaml` — 派生输入的来源说明。

写入 `/app/final/`：

- `submission.csv` — 表头为 `sample_id,condition_id,` 后接按 `group_names` 顺序的八个类名；每条盲测标识符在 `clean`、`formula_only`、`phase400`、`phase402`、`smooth075`、`smooth125`、`frequency_scrambled` 每个条件下各出现一次。概率为 [0, 1] 内的有限值。
- `model.npz` — 以 `allow_pickle=False` 读取；只含数值数组：`coef` (8, 1791)、`intercept` (8,)、`scaler_mean` (1791,)、`scaler_scale` (1791,)，全部有限且尺度严格为正。概率为 `expit(((X - scaler_mean) / scaler_scale) @ coef.T + intercept)`，六个光谱条件共用同一组参数。

`formula_only` 行不是提交的模型输出：它是平滑基线 `(该分子式与类别的正例数 + 1) / (该分子式样本数 + 2)`，对训练集中未出现的分子式回退到整个训练集。

### 变换定义

所有条件都映射到共同的 2 cm⁻¹ 分析坐标。归一化 `norm` 把每行除以 `max(max(spectrum), 1e-12)`、乘 99、截断为整数并裁剪到 [0, 99]，返回 float32。盲测谱须先转为 float32；变换前不要提升为 float64。

```python
import hashlib
import numpy as np
from scipy.interpolate import interp1d
from scipy.ndimage import gaussian_filter1d

blind = np.load("/app/assets/cohort-blind-test.npz")
axis = np.load("/app/assets/axis-cm-1.npy")
raw = np.asarray(blind["spectra"], dtype=np.float32)
ids = blind["sample_id"].astype(str)
orig = np.arange(400, 3982, 2)
short = np.arange(400, 3982, 4)

def norm(x):
    return np.clip((x / np.maximum(np.max(x, axis=1, keepdims=True), 1e-12) * 99).astype(np.int16), 0, 99).astype(np.float32)

def itp(a, old_axis):
    return norm(np.stack([interp1d(old_axis, row)(axis) for row in a]))

def scramble(x, sample_ids):
    out = np.empty_like(x)
    for i, sample_id in enumerate(sample_ids):
        seed = int.from_bytes(hashlib.sha256(f"ir-local-frequency-scramble-v1|20261006|{sample_id}".encode()).digest()[:8], "little")
        out[i] = x[i, np.random.default_rng(seed).permutation(x.shape[1])]
    return out

set1 = raw[:, ::2]
set2 = np.concatenate([raw[:, 1::2], raw[:, -1:]], axis=1)
inputs = {
    "clean": norm(raw),
    "phase400": itp(set1, short),
    "phase402": itp(set2, short),
    "smooth075": itp(np.stack([gaussian_filter1d(row, 0.75) for row in raw]), orig),
    "smooth125": itp(np.stack([gaussian_filter1d(row, 1.25) for row in raw]), orig),
    "frequency_scrambled": norm(scramble(raw, ids)),
}
```

`phase402` 是同一短坐标轴上的另一种采样相位，不是从 402 cm⁻¹ 起步的独立坐标轴。两个相位都用 SciPy 的默认线性插值映射到共同坐标，高斯滤波使用 SciPy 默认的 `reflect` 边界。

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
| `/app/final/submission.csv` | 表头为 `sample_id,condition_id,` 后接按 `group_names` 顺序的八个类名 |
| `/app/final/model.npz` | 以 `allow_pickle=False` 读取 |
