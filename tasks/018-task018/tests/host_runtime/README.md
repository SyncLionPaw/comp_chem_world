# AutoSolvateWeb — Harbor 执行版

使用 Harbor **0.25.0**。七个任务保留中英文科研题面、公开输入、参考解和独立评分器；候选镜像不包含 `tests/` 或 `solution/`，评分在独立、无网络的容器中进行。

| 目录 | Case | 科研任务 | 运行方式 | 最新 Agent 结果 |
| --- | --- | --- | --- | --- |
| task 14 | C01 | 约束 RESP 电荷拟合 | 本地 | PASS |
| task 15 | C02 | AM1-BCC/GAFF 与显式乙腈溶剂盒 | 本地 | PASS |
| task 16 | C03 | 原生轨迹与采样充分性审核 | 本地 | 模型 FAIL |
| task 17 | C04 | 周期微溶剂化簇提取 | 本地 | PASS |
| task 18 | C05 | Reichardt 染料溶剂与局部氢键对照 | HPC | MVP 可测评；完整科研未运行 |
| task 19 | C06 | 化学适用域与电子态路由 | 本地 | PASS |
| task 20 | C07 | 数值失稳诊断与短轨迹恢复 | 本地 | PASS |

## 文件布局

```text
task 14/ … task 20/
 ├── task.toml
 ├── instruction.md
 ├── instruction.zh-CN.md
 ├── environment/
 │   ├── Dockerfile
 │   └── assets/
 ├── solution/solve.sh
 └── tests/
     ├── test.sh
     ├── verify.py
     └── refs.json
```

本说明、依赖锁和 C05 主机端 HPC 接入均位于 `task 18/tests/host_runtime/`；主机回归和 MVP 探针位于其 `tests/`。测评原始记录独立保存在 bench 外，不是运行输入。以下命令从包含 `task 14` 至 `task 20` 的 bench 根目录执行。

C05 的 `tests/` 还包含独立评分容器所需的 `Dockerfile` 和 `docker-compose.yaml`。Task 内的科学溯源文件、公开资产清单及依赖锁属于必要输入。

## 安装与本地测评

需要 Python 3.12、uv、Docker 和下述基础镜像。安装只依赖锁定的 Harbor 及其依赖，**不需要同级 `compchembench` checkout 或其 Python 包**。六个本地任务由原生 Harbor 执行；C05 接入所需代码已随本 bench 提供。

本机需提供与 Bench01 一致的 `compchembench-base:2.1.267`；C05 候选环境使用 `compchembench-connectivity:hpc`。科学软件按各 Dockerfile 的版本与哈希约束安装，构建时需要相应下载网络。模型凭据由调用者配置，不写入任务包。

```sh
RUNTIME="$PWD/task 18/tests/host_runtime"
uv sync --project "$RUNTIME" --frozen
uv run --project "$RUNTIME" harbor --version
uv run --project "$RUNTIME" harbor run -p 'task 14' -a oracle
uv run --project "$RUNTIME" harbor run -p 'task 14' -a claude-code --ak version=2.1.267 -m provider/model
```

本地任务目录为 `task 14`、`task 15`、`task 16`、`task 17`、`task 19`、`task 20`。Oracle 和 Agent 都会执行真实工作，并使用同一科学评分器。

本轮 deepseek-flash 使用 Messages 接口和镜像已有的 Claude Code 2.1.267。使用自己的 `.env` 时，可用 `uv run --project "$RUNTIME" --env-file /absolute/path/to/.env ...`；对于 `API_KEY` / `BASE_URL` 命名的配置，另通过 Harbor 原生参数指定 `--api-key-name API_KEY`、`--base-url <BASE_URL>`、`--api-format anthropic_messages`，模型为 `anthropic/deepseek-flash`。先确认本次费用授权与服务端额度，再启动新的模型测评。任务的网络策略由 Harbor 执行，独立评分器保持无网络。

## C05 的 HPC 接入

C05 使用本 bench 的 Harbor 环境扩展、生命周期插件和 `task 18/tests/host_runtime/bench03_hpc/` 采集器。候选容器继承测评者构建的 `compchembench-connectivity:hpc`，从镜像使用 SSH 和 `hpc`；Task Compose 将测评者共享的公共提交配置只读挂载到 `/app/submit-job.json`，默认来自 `~/.config/submit-job/config.json`，也可用 `CCB_SLURM_CONFIG=/absolute/path/to/config.json` 指定。无需额外的 Task 专用 HPC TOML 或主机 SSH 文件挂载。完整科研作答入口为：

```sh
PYTHONPATH="$RUNTIME" uv run --project "$RUNTIME" harbor run -p 'task 18' \
  -a claude-code --ak version=2.1.267 -m provider/model \
  -e harbor_runtime:Bench03DockerEnvironment \
  --plugin harbor_runtime:Bench03SlurmPlugin
```

此命令启动完整科研作答，不是 MVP。完整任务上限为 10 小时、8 个串行 allocation，每个最多 4 CPU / 8 GiB / 30 分钟；另有题面规定的排队预算。

插件创建唯一远程目录和作业名前缀。答题开始后，runner 以候选实际运行的不可变镜像 ID 启动独立 trusted helper 执行 SSH 采证；helper 不共享候选容器卷，候选容器的 SSH 操作不用于可信采证。答题结束后冻结候选进程、核对产物，由 helper 独立采集本次作业与原生文件，再给独立评分容器只读挂载可信证据；评分容器不接收 SSH 或公共提交配置挂载。网络、排队或证据采集故障不计为模型科学失败。

历史 MVP（迁移前）：曾验证一个 1 CPU / 256 MiB / 2 分钟上限的 allocation，计算节点读取公开染料结构，Slurm 为 COMPLETED / 0:0；独立采证与评分闭环正常，故意不完整的科研提交得到预期零分，无 Harbor 异常。该历史结果不代表本次 helper 迁移后的 Harbor MVP，也不代表完整 MD/ORCA 科研通过。迁移后仅验证两次真实 SSH/sinfo、复用镜像内 known_hosts 策略及 helper 删除；19 项离线 host_runtime 回归通过。本次未重跑 Harbor MVP、MD 或 ORCA。

## 已完成的验收

2026-10-30—31，六题有效 deepseek-flash Agent 测评为 **5 PASS、1 模型 FAIL（C03）**，正式 trial 均无 infra exception。C03 候选代码写死控制序列 ID `D3`，重命名重放时崩溃；题面明确要求分析不依赖数据集名称或行序。该真实模型失败保留，科学阈值未放宽。六个本地 Oracle 此前也均通过。

本轮模型调用前的无效启动记录与临时缓存已删除，未归档；六题有效原始记录、C03 归因、HPC MVP 证据和全部 task 文件经清理前后完整哈希复核保持一致。历史真实失败仍保留，本轮结果单独记录。

- [测评结果、原始绑定与 HPC 验证范围](EVALUATION.md)

原始测评与清理收据已完整移至 bench 外的独立本机记录目录，不随执行代码上传，也不是运行输入。根级 `.release-work/`、`provenance/` 和 NAS 均不是运行时依赖。`task.toml` 中的旧配置元数据仅记录来源，不执行其中的旧 runner 配置。

## 独立执行版验证

运行离线主机回归：

```sh
uv run --project "$RUNTIME" python -B "$RUNTIME/tests/test_hpc_runtime.py"
```

HPC 接入代码从既有实现中按实际调用闭包抽取，来源与原始符号哈希见 `task 18/tests/host_runtime/bench03_hpc/SOURCES.json`；未引入旧 runner、模型网关或其他 bench 模块。证据协议名及远端命名空间保留原有名称以兼容当前科学评分器，这些名称不表示需要本机同级目录。

独立安装、无同级 checkout 的迁移验证、17 项回归、本地 C06 Oracle 与新 HPC MVP 均通过，验证范围见 [EVALUATION.md](EVALUATION.md)。新 MVP 的远端文件已核验删除。此前六题 Agent 原始记录和 C03 真实失败按原始绑定保留，不改写为新运行。
