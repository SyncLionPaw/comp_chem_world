# Slurm 终态回执接口

只在 runner 接入或验收调度取证时读取。终态回执的 `receipt_schema` 为 `ikkem-slurm-sacct-receipt/v1`。现有解析字段继续保留；新增字段是对同一次查询实际 stdout 的字节取证，不是从解析字段重新格式化的文本。

查询使用精确数字根 JobID：

```text
sacct -j JOBID -X -n -P --format=JobIDRaw,Partition,ReqTRES,AllocTRES,NodeList,Elapsed,MaxRSS,State,ExitCode
```

`sacct_rows_base64` 是该命令 stdout 的 Base64 编码；`sacct_rows_sha256` 是同一份 stdout 字节的 SHA-256 小写十六进制摘要。换行符和末尾换行都属于原始字节。`JobIDRaw`、八个解析字段及 `captured_at` 与它们放在同一个 `receipt` 对象中。

消费方应解码 Base64、核对摘要，再以严格 UTF-8 解析为恰好一条九列 `|` 分隔的行。第 1 列必须等于请求的根 JobID，第 2 列 partition、第 8 列 State、第 9 列 ExitCode 不能为空；ExitCode 必须是 `数字:数字`。逐列核对解析字段，空的可选字段映射为 JSON `null`。只有 `State=COMPLETED` 且 `ExitCode=0:0` 才是调度成功。查询错误、无输出、多行、字段冲突或无法解析都不能推断成功。

此回执存在维护者本地状态中，本身不证明候选 Agent 未篡改。正式评测的 runner 必须从受控 skill 进程取得回执，独立校验上述字节/字段一致性，并将它与 attempt、plan、job ID、固定 skill 版本一起在 runner 私有区域封存。runner 适配层需要显式传递并验证原始字节字段；旧状态缺少原始字节时不能补造或升格。

## GPU 分配补充证据

GPU status/wait/collect 额外只读查询 `scontrol show job -d -o JOBID`，输出 resource_evidence，schema 为 ikkem-slurm-resource-evidence/v1。scontrol_rows_base64 与 scontrol_rows_sha256 保留同次查询原始 stdout 字节；JobIDRaw、host、Partition、JobState、NodeList 与 captured_at 绑定该观察。JobId 必须精确唯一，配置分区与已有 job name 必须匹配。

gpu_allocation_known/gpu_allocated 只由明确的 AllocTRES 或节点绑定 GRES 得到；TresPerNode 只证明请求，不能证明实际分配。节点范围等暂未支持的细节保留原始字节而不猜总量。scontrol 不可用或缺分配字段时保留 unknown；resource_evidence_query 显式报告本次查询是否有效。resource_evidence 表示本次有效观察；查询不可用时为 null。历史确认分配另存为 resource_evidence_last_allocation，captured_at 仍为原观察时间。重排队的新观察不得被旧 RUNNING 记录覆盖；历史分配不能证明当前仍分配或作业后来成功。

这项证据与 sacct 调度终态分别采集，不能互相替代。COMPLETED 文本必须精确匹配，只有 CANCELLED by 数字UID 允许取消者后缀。计划分区与 sacct 不一致时状态保持 unknown。runner 必须独立重放原始字节解析与绑定校验；哈希证明字节一致性，不证明来源真实性。
