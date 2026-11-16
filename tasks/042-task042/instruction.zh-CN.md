# 从 DFT 数据训练并诊断势能面

## 背景

本题提供一个含 304 个原子的深共熔溶剂的小规模、公开可见 DFT 样本。清单指定了 64 个训练帧（32 个 `init`、32 个 `extr`）和 16 个留出帧。留出标签及四个原始模型的预测均可见，因此本题不能证明盲测泛化能力或生产级精度。

## 任务

用 64 个训练帧训练一个新的 DeePMD-kit TensorFlow 模型，预测 16 个留出帧，与四个给定模型及训练集平均能量／零力基线比较，并根据证据推荐后续路线。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 h5py、keras、NetworkX、NumPy、pandas、PyTorch、PyYAML、SciPy、sympy、TensorFlow。不要自行安装额外软件包，也不要通过网络获取依赖。

- 严格遵守清单中的 ID 和顺序；不得用留出数据训练、复制标签或原始预测，也不得将原始模型冒充新模型。
- 在总计 20 个优化步的预算内训练一个最终模型；额外用于超参数选择的训练运行不在该预算许可范围内。保留 `training-trace/train.json`、`lcurve.out`、可重放的 `model.ckpt*`、随机种子、软件版本和原生日志。训练体系必须为 `/app/inputs/short-training/train`，`stop_batch` 为 1–20。在本次运行内完成交付，不将预算用于额外实验。
- 提交可重放的 DeePMD TensorFlow 计算图 `model/graph.pb`，以及 `type.raw` 和 `type_map.raw`；不支持其他格式。保存的计算图和检查点必须能重现提交的预测。
- `predictions.npz` 必须保持留出帧顺序，包含有限能量值 `(16,)`，单位 eV，以及有限力值 `(16,304,3)`，单位 eV/Å。`metrics.json` 的字段和定义遵循 `output-contract.json`；比较候选模型、全部原始模型及基线的原始能量误差、去偏置能量误差、偏置和笛卡尔力分量 RMSE。
- 报告去偏置能量误差和力误差各自最优的原始模型、`chosen_route`（`candidate`、原始 ID 或 `none`）及有证据支持的理由。并列容差为 `1e-12`，并列时取原始索引最小者。这只是公开小样本上的相对比较，不能证明生产级精度。
- 在 `report.md` 中解释偏置与去偏置误差的区别、排名、力误差、训练限制、公开留出集的重复使用及推荐理由。如实报告失败或不稳定的运行。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/` | 训练样本、体系定义和作者预测。 |
| `/app/output-contract.json` | 输出及证据约定。 |

工作目录为 `/app/`，下述输入和输出路径均相对此目录。

读取 `inputs/short-training/`、`inputs/sample-manifest.json`、`inputs/system-spec-304.json` 和 `inputs/author-predictions/`。提交 `model/`、`predictions.npz`、`metrics.json`、`report.md` 及规定的可重放 `training-trace/`。准确的输出约定见 `output-contract.json`。
