# 任务：评估五图像 Li5+x 普通 NEB 路径

## 背景

提供了 hop-1 五图像路径，每个图像使用独立晶胞，并附有冻结的 NEB 输入、历史弛豫端点证据和输出 schema。端点来自上游弛豫，不是新做的静态计算。

## 任务

重建采样能量剖面，并核查原生力、切线、弹簧贡献及报告中的算术，以评估有限普通 NEB 证据。说明其对力收敛和鞍点证据的支持程度；短的有限路径不能证明鞍点已收敛。

## 要求

如需新计算，使用 `ikkem-slurm` 探测已授权的资源，在本题预算内自行安排 MPI 核数、内存、时限和并行方式。提交后等待终态，回收原生输出并核验科学结果。

使用冻结的五个图像、`LCLIMB=.FALSE.` 的普通 NEB、三个活动图像、`NPAR=4` 和指定的标准 PAW_PBE Li 17Jan2003、Ti 08Apr2002、O 08Apr2002。新运行受主机授权的四步资源计划限制。不得修改输入、替换 PAW 标识或改用爬坡图像 NEB，也不得用新静态计算替代历史端点证据。区分物理原子力和投影 NEB 力；保留各图像晶胞；报告两种能量定义并以 sigma-zero 为主要比较。活动图像 01–03 至少报告四个共同完整离子步，并提供主机可验证的原生 provenance 和观测方法对比。不得把几何切线检查称作 VTST 内部切线，也不得声称有限路径给出已收敛鞍点。不得公开 POTCAR 内容。

新运行前先读取 `/app/hpc-attempt.json`。遵循主机密封 PAW 策略及授权。备用 `hpc_standard_native_v1` 来源由已安装路径、标题、组分哈希/顺序及合并哈希限定，但不声称与归档来源字节相同或数值等价。冻结端点须作为独立历史证据保留。采用该备用策略时，分别报告活动图像同一步能量，说明仅有历史端点对照，并将完整端点到活动图像剖面标为 `INCOMPARABLE/NOT_ESTABLISHED`；不得报告混合来源势垒。不得绕过主机禁用的提交、传输或 shell；缺失证据须如实说明。

使用 `/app/assets/output-schema.json` 及相关输入，按该 schema 写 `/app/final/results.json`，保留原生记录和 provenance。

从 `/app/hpc-attempt.json` 读取授权入口、作业名 `attempt_id` 和工作目录模板 `workdir_template`。通过 `ikkem-slurm` 探测并选择站点和分区，提交时使用该作业名和目录。将所选 SSH 别名单独写入 `/app/final/hpc-host.txt`，供回收原生作业证据。 在可写工作目录执行 Slurm 命令，并将 `/app/submit-job.json` 链接为该目录下的 `submit-job.json`。

新计算须在作业目录提供 `accepted-plan.json`，记录 `ntasks`、`memory_gib`、`walltime_seconds`、`neb_ranks`、`vasp_path` 和 `mpi_path`。在提交的批处理脚本中单独保留一行 `# CCB_ACCEPTED_PLAN_SHA256=<摘要>`。计算摘要时使用 UTF-8 JSON，键名排序，分隔符无空格，末尾无换行。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | NEB 输入、上游记录与输出格式。 |
| `/app/assets/output-schema.json` | 提交格式 |
| `/app/hpc-attempt.json` | 主机执行状态及授权资源 |

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/final/results.json` | 按公开格式提交的科学结果。 |
| `/app/final/hpc-host.txt` | 新计算所选站点的 SSH 别名。 |
