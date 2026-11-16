# 使用 Ai2-Kit 构建并评估水势函数

## 背景

本题不提供水结构、标签、训练模型或参考结果。研究者自行选择合适的数据与评估来源；历史基准材料不是本题输入。

## 任务

使用 Ai2-Kit 协调可复现的水势函数构建和评估工作流。选择水构型和标签，拟合模型，并在留出样本上定量评估。报告数据来源、方法、实测结果、计算资源、不确定性和局限。训练损失本身不能证明预测精度。区分工作流运行证据与模型在所述物理范围内准确的证据。

## 要求

使用 HPC 时，按 `ikkem-slurm` 的统一流程执行：探测已授权的目标，提交作业，等待终态，回收原生输出，再核验科学结果。自行管理并清理本次研究的作业和临时文件。

使用科学上适当的独立评估集，并说明测试相态、温度、构型和可观测量。选择适合数据的指标和单位，解释数据划分及采样或收敛限制。保留足够的配置和执行记录，使他人能够复现 Ai2-Kit 如何协调模型拟合。可使用已有且可追溯的标签；无须新做第一性原理标注。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| — | 未预置科研数据。 |

将全部研究证据保存在 `/app/submission/` 下，并提交：

| 文件路径 | 说明 |
| --- | --- |
| `/app/submission/claim.md` | 研究报告，讨论方法、结果和局限，关联 claim ID；标题和排版不限。 |
| `/app/submission/provenance.json` | 含非空的 `sources`、`decisions`、`executions`、`claims` 数组和全局唯一 ID。每项 source 记录相对 `path` 和匹配的 `sha256`；decision 含 `evidence_ids`；每项 claim 含 `source_ids`、`execution_ids` 和相对 `evidence_paths`。 |
| `/app/submission/results.json` | `workflow` 含 `data_paths`、`model_path`、声明的 `model_sha256` 和 `training_record_paths`；`trajectory_paths`、`label_paths` 可选。训练记录说明方法或配置，并含至少一个有限拟合/目标统计量。模型作为可检查工件保存；说明其格式和使用方式。 |

- 水结构采用 extxyz 帧，包含 物种与位置 Properties 声明（如 `Properties=species:S:1:pos:R:3`），坐标有限且 O:H = 1:2。周期结构须有有限、正体积的晶胞；也可使用非周期水团簇。若提交标签，使用 `sample_id`、`source_path`、`frame_index` 将标签映射到结构帧，并为能量、力或其他可观测量说明数值与单位。
- 定量验证时，`results.json.validation` 含互不重叠的 `train_sample_ids`、`test_sample_ids` 和 `table_path`。逐样本表包含 `sample_id`、`quantity`、`unit`、`predicted`、`reference`，并映射到已提交标签。已有且合适、可追溯的标签可用，无须新做参考计算。
- 对每项可复算指标，`results.json` 含 `quantities` 条目 `{id, name, unit, value}` 和对应的 `checks` 条目 `{quantity_id, path, operation, value}`，指向验证表。使用 `mae` 或 `rmse`；数值须可由预测值和参考值复算。

讨论来源质量、测试数据的独立性与范围、模型适用性和剩余不确定性。本题为开放研究，不规定精度阈值或唯一科学路线。

标签使用 `energy`/`energy_unit`、`forces`/`force_unit` 或 `observables`（条目含 `name`、`unit`、`value`）。
