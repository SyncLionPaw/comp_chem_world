# 调度交接检查表

只在准备或复盘计算任务时读取。本 reference 描述调度交接和可追溯性；具体引擎参数、科学阶段和 CPU/GPU 分配由调用方按任务与现场信息决定。

## 提交前

- 固定 case 名、输入版本或 checksum、引擎/环境信息，以及本次资源选择理由。
- 完成引擎侧输入完整性、可执行程序、并行模型、checkpoint 和 walltime 预检。
- GPU 任务只对任务配置中适用的 GPU 入口和分区做只读 `probe --json --detail`，比较逐节点 `alloc_tres`、队列、卡型、软件环境与数据位置；保存所选入口的 snapshot 及 `snapshot_sha256`。CPU 任务同样探测目标分区。探测结果是提交时的快照，不保证之后的排队或空余资源。
- 先做 dry-run，复核 host、target/profile、`resource_class`、资源、workdir 和完整 sbatch 脚本。
- 提交必须恰好绑定 `--reason`/`--reason-file` 与 `--snapshot-sha256`；target 的 partition_limits 在 dry-run 和实际提交前都完整校验，不能由 CLI 覆盖。
- 资源请求应写清楚：CPU 的 ranks/threads，GPU 的 GPU 数量或 typed GRES。不要同时给 `--gpus` 与 `--gres`，也不要让 CPU route 携带 GPU 字段。

## 提交和监控

- `hpc` 原子保留 job name；提交结果不确定时记录 `SUBMISSION_UNKNOWN`，禁止同名自动重试。
- 记录 job id、入口、target/profile、resource class、partition、资源、workdir、提交时间和 `reason_sha256`、`snapshot_sha256`、`script_sha256`、`plan_sha256`。
- 登录节点只做传输、提交和查询。查询失败、网络超时或队列与 sacct 暂时沉默都应报告 unknown，不得当作完成。
- 通过 `wait`/`status` 以精确唯一根 `JobIDRaw` 和 `ExitCode=0:0` 判定 scheduler success；`Partition,ReqTRES,AllocTRES,NodeList,Elapsed,MaxRSS,State,ExitCode` 八字段 receipt 在完成、失败和取消终态原子保存；同一回执保留实际 `sacct` stdout 的 `sacct_rows_base64` 和 `sacct_rows_sha256`。必须从原始字节计算摘要并解析，不能从字段重建字节。根缺失、冲突、非单行九字段或查询失败只能是 unknown。旧状态无原始数据时不得补造。

## 结果与跨入口交接

1. `wait` 得到精确调度终态。
2. `collect` 回收到新的本地目录；失败任务只用 `--allow-unsuccessful` 取诊断材料。
3. 调用方运行对应 parser/scientific validation，并区分 scheduler completed 与 scientific valid。
4. 若下一任务使用另一入口，显式生成 checksum/manifest，传输并独立校验输入；两个入口之间不假设共享文件系统，也不假设跨 Slurm dependency 可用。
5. 确认交接材料完整后，才由调用方提交下一任务，并保留前后 job 的关联记录。

`collect` 不覆盖已有目标目录；续算使用新 job name，并注明 checkpoint/前序结果来源。传输超时后目标目录可能只有部分文件；换新的 `--dest` 重试，不要续传或自动删除部分目录。
