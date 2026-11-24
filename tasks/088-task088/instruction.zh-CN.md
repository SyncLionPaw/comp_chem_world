# 任务：从新的 SPC/E 水分子动力学生产轨迹计算体相响应

## 背景

公开输入为 `/app/public/protocol.json` 与 `/app/public/output-contract.json`。科学目标是按已发表的平衡流程，对 9033 个 SPC/E 水分子完成一次新的 20 ns NVT 生产模拟，并由此计算约 0–6 Å⁻¹ 范围的纵向介电响应、五个观测量及其统计不确定度。

## 任务

实现规定的 GROMACS 工作流程，自行准备计算环境并提交远程作业，取回原生输出并分析轨迹。说明给定资料未规定的选择。已有轨迹或预先计算的私有结果不能替代本次新生产模拟；调度器成功退出本身不代表科学结果有效。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、MDAnalysis、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

使用 HPC 时，按 `hpc` 的统一流程执行：探测已授权的目标，提交作业，等待终态，回收原生输出，再核验科学结果。

- 遵循主机提供的执行配置并使用其支持的软件环境。
- 记录约束、PME 与邻居表设置，体系构建与平衡检查，输出频率，倒空间估计器与不确定度方法。按流式或有界内存方式处理轨迹，不得分配帧×原子×波矢数组。讨论有限尺寸分辨率与估计器混叠、低 k 极小是否得到统计分辨、`delta_k` 的基线。静态介电涨落与有限 k 估计分开报告。软件版本与资源须实测报告。
- 保留你产生的平衡证据：溶剂化初始结构与运行时拓扑，EM/NVT/NPT 的 TPR/log/GRO 以及 EM 能量文件。它们用于证明生产接续自你自己的平衡流程。
- 在 `final/` 提供机器可读的执行证据（例如 `final/provenance.json`），将调度/记账记录、作业与 allocation、资源、含时区的开始/结束时间、实际提交的批处理或工作流脚本、stdout/stderr、阶段顺序（EM → NVT → NPT → production）以及每个原生文件绑定到相对路径和文件校验值。请提供实际证据文件；仅有状态摘要不够。遵循主机执行配置；不规定特定命令、远程目录布局或回执 schema。

### 输入与产物细则

- 输入：`/app/public/protocol.json`、`/app/public/output-contract.json`、`/app/public/runtime-instructions.md`
- `final/` 输出：`/app/public/output-contract.json` 要求的全部文件，以及机器可读执行证据和其引用文件
- `/app/` 原生产物：`production.tpr/xtc/edr/log`、`em.tpr/log/gro/edr`、`nvt.tpr/log/gro`、`npt.tpr/log/gro`、`solvated.gro`、`topol.runtime.top` 以及你实际执行的流程脚本

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/public/protocol.json` | 给定数据、参数或方法说明；用途见任务要求。 |
| `/app/public/output-contract.json` | 给定数据、参数或方法说明；用途见任务要求。 |
| `/app/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
| `/app/production.tpr` | 提交结果；内容与格式按上文要求。 |
| `/app/production.xtc` | 提交结果；内容与格式按上文要求。 |
| `/app/production.edr` | 提交结果；内容与格式按上文要求。 |
| `/app/production.log` | 提交结果；内容与格式按上文要求。 |
| `/app/npt.gro` | 提交结果；内容与格式按上文要求。 |
| `/app/nvt.log` | 提交结果；内容与格式按上文要求。 |
| `/app/npt.log` | 提交结果；内容与格式按上文要求。 |
| `/app/nvt.tpr` | 提交结果；内容与格式按上文要求。 |
| `/app/nvt.edr` | 提交结果；内容与格式按上文要求。 |
| `/app/nvt.gro` | 提交结果；内容与格式按上文要求。 |
| `/app/nvt.cpt` | 提交结果；内容与格式按上文要求。 |
| `/app/npt.tpr` | 提交结果；内容与格式按上文要求。 |
| `/app/production.mdp` | 提交结果；内容与格式按上文要求。 |
| `/app/nvt.mdp` | 提交结果；内容与格式按上文要求。 |
| `/app/npt.mdp` | 提交结果；内容与格式按上文要求。 |
| `/app/em.mdp` | 提交结果；内容与格式按上文要求。 |
| `/app/em.tpr` | 提交结果；内容与格式按上文要求。 |
| `/app/em.log` | 提交结果；内容与格式按上文要求。 |
| `/app/em.gro` | 提交结果；内容与格式按上文要求。 |
| `/app/em.edr` | 提交结果；内容与格式按上文要求。 |
| `/app/solvated.gro` | 提交结果；内容与格式按上文要求。 |
| `/app/topol.runtime.top` | 提交结果；内容与格式按上文要求。 |
| `/app/run_case01.sh` | 提交结果；内容与格式按上文要求。 |
