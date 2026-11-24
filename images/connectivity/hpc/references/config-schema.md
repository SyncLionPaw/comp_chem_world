# submit-job.json v0.6.0

每个 target 需要 `backend: "slurm"`、`host`、`resource_class`、`partition`，并为其每个可选 partition 提供 `partition_limits`。limits 的字段必须全部存在：

可选的 target 字段 `transfer_timeout` 是上传和 collect 下载的 rsync 超时秒数，必须是 JSON 整数（布尔值不算整数），范围 1-3600，默认 300。由维护者配置，不可从命令行覆盖，并纳入 dry-run、plan hash 和提交意图 state。仓库三个 target 中，`hpc-cpu` 为 3600 秒，`hpc-gpu` 为 1800 秒，`bigu-gpu` 为 3600 秒。

`snapshot_max_age_seconds` 可选，整数 1-86400，默认 900；提交操作开始时拒绝过期、无时区或超前超过 30 秒的 captured_at。它和 typed GRES 策略纳入 plan hash；CLI 不覆盖维护者策略。`allow_typed_gres` 可选，必须为布尔值，默认 true；设为 false 时只允许 gpu:N，仍可使用 --gpus N。当前 hpc-gpu 设为 false，依据现场提交插件的实际拒绝；这不是其它站点的通用限制。时效绑定的是开始提交时的资源决策；上传可能耗时，sbatch 时的可用资源由 Slurm 决定。

必需字段为 `enabled`、`max_nodes`、`max_ntasks`、`max_ntasks_per_node`、`max_cpus_per_task`、`max_total_cpus`、`max_memory_per_node`、`max_total_memory`、`max_walltime`、`max_gpus_per_node` 和 `max_total_gpus`。完整可复制结构与 operator 数值只维护在 [submit-job.example.json](submit-job.example.json)。

这里的数字是 operator 配置，不是硬件事实。唯一完整 operator 数值来源为 [submit-job.example.json](submit-job.example.json)；根目录的 `submit-job.json` 是当前安装配置，两者应保持 JSON 语义一致。配置 ceiling 限制单次作业成本，不替 Agent 选择工作流阶段或具体请求。

`gpuv100` 的 `max_memory_per_node` 与 `max_total_memory` 当前均为 `16G`：这是因一次现场提交被 Slurm 明确以 `requested 32.0GB memory/node exceeds allowed 16.0GB for gpuv100` 拒绝后设置的 operator ceiling，表示已观测到的分区/QOS 请求上限，不代表节点硬件内存容量。只有重新验证分区策略后才应调整。

bigroup target 的 resource_class 为 gpu，必须请求 GPU。其 CPU、主机内存上限供 GPU 作业配套使用；mem 指主机内存，不是显存。工具不从软件名或命令文本判断是否实际使用 GPU。

若将配置用于其他站点或扩大额度，operator 必须先重新 `probe --json`，按“节点数不超过目标 partition 可见节点数、每节点 CPU/GPU/内存不超过该 partition 的最小节点能力、总量按允许节点数计算、walltime 不超过站点 MaxTime”重算并审阅。`enabled:false` 或缺失策略会安全拒绝提交。内存使用显式 K/M/G/T 单位并解析为 bytes，walltime 解析为 seconds。请求需提供或继承 nodes、ntasks（或 ntasks-per-node）、cpus、mem、time；GPU target 仍需显式 `--gpus` 或 `--gres`，CPU target 的 GPU 上限必须为 0。

同一种 `resource_class` 可以有多个 target。profile 必须映射到配置中的 target；每个 GPU target 必须显式声明 `allowed_partitions`。可根据实时 probe 和任务需求将 profile 映射到任何适用 target；改变目标必须重新绑定对应快照和理由。
