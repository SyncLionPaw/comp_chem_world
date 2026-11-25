# 任务：比较八个同组成结构弛豫候选

## 背景

提供了八个 Li41Ti40O96 起始结构、共用的自旋极化弛豫输入、输出 schema，以及经授权的归档重放或单独授权 HPC 计算证据路线。归档设置只是实际观察值，不能证明使用了指定优化器。

## 任务

依据原生末态弛豫证据比较各候选的能量、物理力、结构、收敛情况及全部两两差异，并说明这组有限同组成候选能够支持的结论及其边界。

## 要求

如需新计算，见 `/app/AGENTS.md`，用 SSH 别名 `hpc` 探测已授权资源，在本题预算内自行安排 MPI 核数、内存、时限和并行方式。提交后等待终态，回收原生输出并核验科学结果。

保留每个起始结构并使用共用方法。新计算须为自旋极化变胞弛豫，使用 `IBRION=1`、`NPAR=2` 和标准 PAW_PBE Li 17Jan2003、Ti 08Apr2002、O 08Apr2002，并遵守主机授权资源及密封 PAW 策略。不得合并候选，也不得从另一候选的弛豫结构开始。将归档中观察到的设置与新计算要求分开报告。在 `method.paw_policy` 和 `method.paw_identity` 中保留所选策略及主机密封的来源/运行观察；不得公开 POTCAR 内容。备用 `hpc_standard_native_v1` 来源经主机资质确认，但不声称与归档字节相同或数值等价。

对每个候选分析最后一个离子步、`TOTEN`、`energy(sigma->0)`、物理力、末态结构及电子/结构终止证据。要求正常终止、电子收敛、结构停止证据，且最大力 ≤0.02 eV/Å。按两种能量定义报告全部 28 个带符号两两能量差，并依 `/app/assets/output-schema.json` 的保物种周期指标比较结构。讨论排序、能量定义敏感性及记录未量化的不确定性。结论限于这八个候选；不得外推为跨组成稳定性或全局基态。

任何运行前先读取 `/app/hpc-attempt.json`。仅在主机执行可用且已授权时提交 HPC 计算；不得绕过禁用的提交、传输或 shell。利用现有受支持记录，对缺失证据如实说明，不得编造。保留原生记录及 provenance。按 `/app/assets/output-schema.json` 写 `/app/final/results.json`。

从 `/app/hpc-attempt.json` 读取授权入口、作业名 `attempt_id` 和工作目录模板 `workdir_template`。通过 `hpc` 探测并选择站点和分区，提交时使用该作业名和目录。将所选 SSH 别名单独写入 `/app/final/hpc-host.txt`，供回收原生作业证据。 在可写工作目录执行 Slurm 命令，并将 `/app/submit-job.json` 链接为该目录下的 `submit-job.json`。

新计算须在作业目录提供 `accepted-plan.json`，记录 `ntasks`、`memory_gib`、`walltime_seconds`、`concurrent_runs`, `ranks_per_run`、`vasp_path` 和 `mpi_path`。在提交的批处理脚本中单独保留一行 `# CCB_ACCEPTED_PLAN_SHA256=<摘要>`。计算摘要时使用 UTF-8 JSON，键名排序，分隔符无空格，末尾无换行。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 候选结构、计算设置与输出格式。 |
| `/app/assets/output-schema.json` | 提交格式及结构比较约定 |
| `/app/hpc-attempt.json` | 主机执行状态及授权资源 |

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/final/results.json` | 按公开格式提交的科学结果。 |
| `/app/final/hpc-host.txt` | 新计算所选站点的 SSH 别名。 |
