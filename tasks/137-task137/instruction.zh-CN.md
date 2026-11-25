# 张量性质与振动光谱

## 背景

神经进化势（NEP）用于原子性质建模。本研究考察 NEP 能否表示秩-1 分子偶极矩和秩-2 极化率张量、预测有多准确和高效，以及所得模型能否支持红外（IR）和拉曼光谱。本题不提供科学数据、模型或参考结果。

## 任务

自行选择物理体系和可复现的研究设计。回答六个目标：`rank1_dipole`、`rank2_polarizability`、`accuracy`、`efficiency`、`infrared_spectroscopy` 和 `raman_spectroscopy`。使用合适的参考数据评估模型性质；区分已发表证据与自行计算，并说明单位、方法、范围、不确定性和局限。证据不足的目标标记为 `insufficient`；不得把未执行的计算写成结果。

## 要求

如果使用 HPC 计算资源，请见 `/app/AGENTS.md`，并通过 SSH 别名 `hpc` 连接。

仅使用你获准访问的资源。根据科学需求选择资源，不得假设存在 GPU，也不要猜测主机或账户信息。使用新的作业目录，保持研究独立于基准参考材料和历史运行记录。记录实际方法、数据、资源用量、执行结果及复现报告所需的证据。服务不可用时，应作为局限报告，而非科学反证。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| — | 未预置科研数据。 |

提交 `/app/final/research.json`及其引用的全部证据文件。ID 全局唯一。路径相对于提交目录、不得越界或穿越符号链接。JSON 数值必须有限。

| 记录 | 必需字段与约定 |
|---|---|
| 顶层 | `question`；数组 `claims`、`sources`、`artifacts`、`evaluations`、`executions`、`target_coverage`。 |
| `claims` | `id`、`statement`、`conclusion`（`supports`、`contradicts`、`insufficient`）、`scope`、`evidence_ids`、`limitations`。 |
| `sources` | `id`、公开来源 `url`、本地来源工件 ID `local_artifact`、来源字节的 `sha256`、`acquisition_note`。 |
| `artifacts` | `id`、相对 `path`、`sha256`、`role`。 |
| `evaluations` | `id`、`kind`（`numeric`、`qualitative` 或 `scientific_constraint`）、`evidence_ids`。定性项含 `description`；数值项含 `metric`、`calculation`、`artifact_id`、`value`、`unit`，并按下文补充输入字段。 |
| `executions` | `id`、`role`（`selected_result`、`retry`、`postprocess`、`other`）、`status`（`completed`、`failed`、`cancelled`）、`resource_mode`（`declared_local_only`、`slurm_accounted`）、`command`、`input_artifact_ids`、`output_artifact_ids`、`evidence_ids`、`exit_code`、`elapsed_seconds`，以及 `cpu_cores`、`memory_gib`、`gpu_count`、`gpu_memory_gb`、`allocated_gpu_hours`。适用时保留并核算失败、重试和后处理作业。若未运行计算，`executions` 可为空，但须在报告中说明；`selected_result` 必须为已完成且退出码为 0。本地 CPU 运行须提供 GNU `/usr/bin/time -v` 工件，设置 `timing_artifact_id`，并确保其命令、耗时和退出状态与 execution 记录相符，记录的峰值内存不得超过声明的 `memory_gib`。 |
| `target_coverage` | `id` 为目标 ID，每个目标恰一项；`status` 为 `supports`、`contradicts` 或 `insufficient`，并提供非空 `claim_ids`、`evaluation_ids`、`artifact_ids`。每项 claim 须引用 evaluation；evaluation 须引用相关来源或工件证据。 |

数值 evaluation 支持指标 `rmse`、`mae`、`r2`、`mean`、`std`、`l2_norm` 和 `relative_difference`。成对数组使用 `reference_key`、`prediction_key`；数组汇总使用 `values_key`；`relative_difference` 另含 `reference_value`。成对数组须同形且至少含两个值，`r2` 的参考数组须非恒定；`std` 使用 ddof=0，`relative_difference=abs(mean(values)-reference_value)/abs(reference_value)`。重算数值容差为 atol=1e-8、rtol=1e-7。其他指标可保留供独立复核。效率指标可自行选择，须说明单位、硬件、计算规模和测量方法，并提供相应证据。

可选张量协变 evaluation 可支持 `rank1_dipole` 或 `rank2_polarizability`。使用 `constraint: "tensor_rotation_covariance"`、`target_id`、`artifact_id` 和 `unit`，并指定 `original_key`、`rotated_key`、`rotation_key`、`original_positions_key`、`rotated_positions_key`。在同一个 NPZ 文件内保留五组实数数组：偶极 `(3,)`、极化率 `(3,3)`、正旋转 `(3,3)`、原子位置 `(N,3)` 且原子顺序一致。旋转矩阵为 R 时，位置按 r′=rRᵀ 变换，偶极按 μ′=Rμ 变换，极化率按 α′=RαRᵀ 变换。归一化最大绝对残差不得超过 `1e-7`；张量和坐标残差分别按原数组的最大绝对分量归一化。选用非平凡旋转；几何或张量未发生变化时，不能区分协变行为与不变输出。这检验协变性，不代表预测精度。

提交目录为 `/app/final/`，其中含 `research.json` 及该索引引用的全部来源、数据、模型、脚本、报告和执行工件。
