# 任务：从 MoS₂ 原生轨迹指认层间模态

## 背景

公开 manifest 将实例固定为双层 MoS₂（`N=2`、seed `24101`）。须从完整原生分子动力学轨迹指认剪切（S）与层间呼吸（LB）两个模态。指定流程为全尺寸面内晶胞、`p p f` 边界、REBO-only 加 ILP 势、300 K 零目标应力 NPT 平衡 250 ps，随后固定晶胞 NVE 生产 50 ps。实验频率或合成信号不能替代候选轨迹证据。

## 任务

对给定实例按指定流程计算，并从原生轨迹确定模态频率、不确定度和可靠性。提交可独立核查计算与模态指认的证据。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

使用 HPC 时，按 `ikkem-slurm` 的统一流程执行：探测已授权的目标，提交作业，等待终态，回收原生输出，再核验科学结果。

记录实际 MPI ranks 和候选提交的执行记录。按 `/app/verification.md` 保留所需原生输入、输出、势函数核验与分阶段证据，并遵守其中频率、稳定性、相位、不确定度、来源和资源判据；不得用合成数据替代。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 模拟结构、势函数及清单。 |
| `/app/verification.md` | 方法与输出规范。 |

输入：`/app/assets/n2-seed24101/manifest.json` 及其绑定的结构、去重映射和势函数，以及 `/app/verification.md`。按公开契约提交 `/app/final/modes.json`、`/app/final/md_inputs/`、`/app/final/equilibrium.md` 和 `/app/final/mode_evidence/`.
