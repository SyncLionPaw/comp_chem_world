# HPC 入口与能力参考

本文件是资源能力的探测起点，不是实时集群保证。提交前必须用 `probe` 验证 partition、QOS、可用节点和 GRES；不要把历史快照当作排队或容量承诺。SSH alias、用户名、地址和密钥来自用户的本地 SSH 配置，本 skill 不写入也不猜测这些值。

## 配置路由

profile 必须映射到显式配置的 target。target 声明入口、资源类别、默认分区和允许分区；GPU target 必须列出非空 `allowed_partitions`。本地 SSH alias 和集群实际分区由 operator 配置，不由 skill 内置，也不从软件名称推断。GPU 请求还须显式给出 GPU 数量或 GRES。

## 只读探测

```bash
hpc probe --host hpc --json > probe.json
hpc probe --host hpc --partition cpu --json > probe-cpu.json
hpc probe --host '<configured-gpu-host>' --partition '<configured-gpu-partition>' --json --detail > probe-gpu.json
```

`probe --json` 优先走稳定的 `sinfo`/`squeue` 格式，输出单一可复算快照：所有分区、请求分区的全部匹配节点（含每节点异构的 GRES、CPU 数、memory MB 和 features）和 queue 聚合，并包含 `snapshot_sha256`（canonical UTF-8 JSON，`sort_keys=True`、紧凑 separators）。节点字段来自稳定的 `sinfo -N -o %P|%n|%T|%G|%c|%m|%f` fallback，不依赖现场是否支持 `--json`。哈希覆盖不含自身的快照对象；输出中的 `snapshot_sha256` 是该无哈希对象的自描述校验值。探测失败或信息沉默表示未知，不得生成部分快照。

节点始终区分 gpu_capacity 与 GPU 占用。只有显式 GPU AllocTRES/GresUsed 且两者不冲突时，`gpu_allocation_known` 才为 true；无数据不是零占用。`gpu_available` 仅在容量、占用均已知且不涉及 mps/shard 时提供；null 表示未知，显式 0 表示已知无剩余计数。这里的计数可能是 MIG 实例，不能混同整张物理卡。`queue_count_unit` 为 jobs/entries，每行 squeue 记一条；合并的数组不是单个数组任务，条目数不代表等待时间。

选择 GPU 入口时，对适合该任务的各分区分别探测。`--detail` 逐节点读取 Slurm 的 `AllocTRES`/`GresUsed`，输出 `alloc_tres`/`gres_used`，用来判断当前 GPU 占用；再结合 `queue` 中各分区的待运行作业、所需 GPU 型号、显存、软件环境和数据位置决定 target。`mixed` 节点可能已分配全部 GPU；空闲 GPU 数量和队列长度也不能保证等待时间。把选择理由写入提交的 `--reason`；提交必须使用所选 target 对应 host/partition 的 probe 快照。

探测只运行 `sinfo`、`squeue`（必要时可由维护者增加只读 `scontrol` fallback），用于确认分区状态、时间/QOS 限制、节点和 GRES。探测失败或信息沉默表示未知：不得因此在登录节点跑计算，也不得自动切到未声明的入口。

## Slurm 表达与安全边界

- `--gpus N` 被渲染为 `--gres=gpu:N`；`--gres` 仅接受安全的 `gpu:N` 或 `gpu:type:N`。
- `--gpus` 与 `--gres` 互斥；CPU target/profile 携带任一项都会在远程动作前拒绝。
- profile 锁定 host/backend；target 的 `resource_class` 和 `allowed_partitions` 在解析时校验。
- 新提交只能是 `backend=slurm`。旧 SSH 状态可查询/回收以便诊断，但不能创建新任务。
- 当前 hpc/gpu 只允许非 typed 的 GPU 请求；这是现场提交策略限制。
- 登录节点只用于传输和 `sbatch`；作业必须进入 Slurm 分配的节点。

历史 snapshot（包括节点名、价格、QOS 和时间上限）可能过时，只有 probe 输出可作为本次提交的依据。官方命令语义见 [sbatch](https://slurm.schedmd.com/sbatch.html)、[squeue](https://slurm.schedmd.com/squeue.html) 和 [sacct](https://slurm.schedmd.com/sacct.html)。

## 维护者 limits

target 必须为每个可选 partition 配置完整 `partition_limits`。operator 的数值配置以 [submit-job.example.json](submit-job.example.json) 为唯一示例来源；本文只说明探测方法与能力核验边界，不重复维护 ceiling 数字。

扩大任何 ceiling 前，operator 必须重新获取目标分区所有匹配节点的快照，按“节点数不超过分区可见节点数、每节点 CPU/GPU/内存不超过该分区最小节点能力、总量按允许节点数计算、walltime 不超过站点 MaxTime”重算、审阅并更新配置。CLI 不能覆盖策略。请求的 nodes、ntasks/ntasks-per-node、cpus、带单位 mem、time 必须显式提供或由 target 默认提供；内存按节点和总量、CPU 按 effective ntasks×cpus、GPU 按节点和总量检查，任一缺失、单位错误或超过上限都 fail closed。
