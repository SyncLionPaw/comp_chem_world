---
name: hpc
description: 通过 HPC 双入口 SLURM 提交、监控并回收可追溯的 CPU/GPU 作业；只提供资源探测与调度适配，不编排具体软件工作流。
metadata:
  version: "0.6.0"
---

# HPC 双入口 Slurm 调度适配

这个 skill 是维护者调度层：把已完成引擎侧预检的命令提交到 HPC Slurm，判定调度终态并回收结果。它不做 CP2K、DeepMD、LAMMPS 或 AI2-kit 等工作流编排，也不替调用者选择科学阶段、软件参数或 CPU/GPU 分配。资源由 agent 按任务需求、软件环境、规模、实时 probe 和排队情况选定，并在提交记录里写下理由。

## 入口与资源事实

- 按计算需求、软件兼容性和可用资源，自行决定本地或 HPC、是否需要 GPU。HPC 的 `host`、`resource_class` 和允许分区以任务 `submit-job.json` 中的 target 为准。显式选 target；只有任务配置已定义映射时才用 profile。不要探测未配置的入口。
- 若环境提供 `task-compute` 作为受信远程执行入口，用 `task-compute --help` 看接口，经该入口发现授权资源、提交并回收结果，保留任务要求的执行证据。
- GPU 作业先分别探测适用入口的目标分区，比较节点 GPU 分配、排队、所需卡型和软件环境，再选 target，并把依据写入 `--reason`。节点 `mixed` 不表示有空闲 GPU。仅当 `gpu_allocation_known=true` 时使用 `gpu_allocated`；`gpu_available=null` 表示未知，不能当成 0 或容量全空。缺 GPU TRES、字段冲突或共享 GRES 时，不要推断整卡可用数。queue 的 count 是作业条目数（数组可能合并），不保证实际开始时间。
- 每个 target 可配置维护者管理的 `transfer_timeout`（秒，1-3600，默认 300；仓库里 `hpc-cpu` 为 3600，`hpc-gpu` 为 1800，`bigu-gpu` 为 3600）。该值同时限制提交源目录上传和 collect 下载，不能用 CLI 覆盖，会出现在 dry-run 与 plan/state 绑定中。
- CPU 不得带 `--gpus`/`--gres`。GPU 必须显式给 `--gpus N`，或安全的 `--gres gpu:N` / `gpu:type:N`，二者互斥。当前 hpc/gpu 站点策略拒绝 typed GRES（`allow_typed_gres:false`），用 `--gpus N` 或 `--gres gpu:N`；其它 target 由维护者配置允许格式。
- 两个入口不保证共享文件系统，也不假设跨 Slurm 实例的 dependency 可用。跨入口交接按 `wait → collect → scientific validate → checksum/manifest transfer → next submit`，每步结果和校验由调用者保存。
- 每次新提交必须提供 `--probe-snapshot` 文件和匹配的 `snapshot_sha256`，并且恰好提供 `--reason` 或 UTF-8 `--reason-file`。dry-run 与实际提交输出/保存相同的 plan、reason、script 和 snapshot 哈希。`--probe-snapshot` 会重算哈希并核对 host/partition。提交开始时，快照默认最多 900 秒，过期后重新探测；维护者可配置 `snapshot_max_age_seconds`。
- target 的 `partition_limits` 是维护者封顶策略，字段与核验边界见 [references/config-schema.md](references/config-schema.md)。策略缺失、disabled、单位无效或请求超限时 fail closed。CPU 目标的 GPU 上限必须为 0；GPU 请求仍需显式给出。

## 边界与安全规则

- 只通过 `hpc` CLI 操作目标集群；不要另写 SSH、rsync 或 sbatch 流程绕过状态记录。
- 新提交只接受 `slurm`。直接 SSH 仅用于旧状态查询/诊断，不能创建新任务。
- 登录节点只做只读探测、传输和提交；计算必须进入 Slurm。调度器 `COMPLETED` 只表示进程正常退出，科学结果仍要走对应 parser/验证。
- 只访问用户指定的本地源目录和工具创建的远程作业目录；不要猜测 SSH 用户、密钥、IP 或公网入口。
- 提交前确认资源会计费及 walltime/QOS 限制；路由、分区或 GRES 不确定时先 probe。

## 配置

在项目根目录创建 `submit-job.json`，可从 [references/submit-job.example.json](references/submit-job.example.json) 复制。profile 只引用 target；任何路由模式都不能用 CLI 改写 host/backend。direct `--target` 按 target 的 `resource_class` 与 `allowed_partitions` 校验。

字段与维护者策略见 [references/config-schema.md](references/config-schema.md)，现场探测边界见 [references/cluster.md](references/cluster.md)。limits 是维护者封顶值，不是硬件事实。

`host` 是用户已有的 SSH alias；示例不含用户名、私钥或地址。具体 cluster 事实见 [references/cluster.md](references/cluster.md)。

## 调度接口

先对目标做只读探测，再 dry-run，核对 host、partition、资源、工作目录和完整 sbatch 脚本：

```bash
hpc probe --host hpc --partition cpu --json > probe.json
hpc probe --host '<configured-gpu-host>' --partition '<configured-gpu-partition>' --json --detail > gpu-probe.json
hpc submit --profile cpu --name <name> --cmd '<command>' \
  --reason '<why this resource choice>' --probe-snapshot probe.json \
  --snapshot-sha256 <sha256-in-probe-json> \
  --src <dir> --nodes 1 --ntasks <mpi-ranks> --cpus <threads> --mem <memory> \
  --time <walltime> --dry-run
hpc submit --target '<selected-gpu-target>' --name <name> --cmd '<command>' \
  --reason '<why this GPU choice>' --probe-snapshot gpu-probe.json \
  --snapshot-sha256 <sha256-in-probe-json> --src <dir> --gpus 1 \
  --partition '<configured-gpu-partition>' --nodes 1 --ntasks 1 --cpus 1 --mem <memory> \
  --time <walltime> --dry-run
# 提交所用的快照必须与选定 target 的 host 和分区一致。
```

去掉 `--dry-run` 后正式提交。CLI 会原子保留不可复用的本地 job name，创建唯一远程 workdir，上传源目录后只恢复该 workdir 的 owner-write 位（不改已上传文件的只读权限），再执行 `sbatch --parsable`，并记录 `job_id`、`resource_class`、资源、日志和 `script_sha256`。

```bash
hpc list
hpc status  --job <name>
hpc wait    --job <name> --poll 60 --timeout <seconds>
hpc logs    --job <name> --lines 100
hpc cancel  --job <name>
hpc collect --job <name> [--dest <dir>]
```

`probe --json` 输出可复算的 canonical snapshot（含所有匹配节点和 queue 聚合），并带 `snapshot_sha256`。`wait`/`status`/`collect` 以精确根 `JobIDRaw` 保存维护者侧 sacct receipt；终态回执按 `ikkem-slurm-sacct-receipt/v1` 保留本次 `sacct -X -n -P` 的未修改 stdout 字节（`sacct_rows_base64`）及其 `sacct_rows_sha256`。只有 UTF-8、单行九字段、根 JobID 精确匹配且关键字段完整的输出才形成回执；否则保持 unknown。不要从解析字段重建“原始”字节。格式与验证边界见 [references/sacct-receipt.md](references/sacct-receipt.md)。

`ExitCode=0:0` 才确认调度成功。`squeue` 仅在返回单行已知活跃态时直接给状态；终态、未知值、多行输出，以及部分站点返回的 `Invalid job id specified`，都会转查 `sacct` 并核对唯一匹配的根 `JobIDRaw` 行。查询失败或回执无效时保持未知。提交超时、`sbatch` 返回码不明或输出无法解析时记录 `SUBMISSION_UNKNOWN`，禁止盲目重试同名作业。`collect` 默认写入新目录，拒绝覆盖已有目录；传输超时可能留下不完整目录，重试须换新的 `--dest`，工具不会删除或续传部分结果。回收后由调用者完成科学验证、checksum/manifest 和结果报告。

GPU 的 status/wait/collect 会补采 `scontrol show job -d -o` 原始字节，输出独立的 `resource_evidence`。只把 AllocTRES 或绑定节点的 GRES 当作分配证据；TresPerNode 仅证明请求。控制器记录可能很快过期，GPU 作业运行期间及时做 status/wait。分配未知不改变调度终态，也不证明命令实际跑了 GPU 计算。回执分区必须匹配提交计划；未知终态文本不能按前缀认定成功。`resource_evidence_last_allocation` 单独保留历史分配，不能代替最新状态，也不能证明重排队后仍占用 GPU。

原始字节与摘要只是 skill 侧的采集材料。正式评测的 runner 仍需私有地固定 skill 版本、作业和 attempt 的绑定，并通过桥接传递、验证这些字段。旧状态没有原始字节时，不得从解析字段补造。

`plan_sha256` 绑定 host、工作目录、资源、命令/理由摘要、probe 摘要及有序 rsync excludes；它描述路径与上传筛选规则，不是源文件内容字节的哈希。非终态 sacct 状态可继续等待；只有明确成功、失败或取消才写入终态缓存；未知状态不推断为失败。

按需读取：资源快照和探测边界见 [references/cluster.md](references/cluster.md)；跨入口交接与调用边界见 [references/benchmark-workflow.md](references/benchmark-workflow.md)。
