# comp-chem-world

计算化学 agent 评测环境：Harbor 任务 + 共享 Docker 基础镜像。项目主页：<https://synclionpaw.github.io/comp_chem_world/>。研究任务 245 个（编号 `001–245`），另加冒烟任务 `000-hello`。论文与任务对应关系见 [docs/benchmarks/README.md](docs/benchmarks/README.md)。

## 快速开始

按下面顺序做完就能跑全量测评。离线大文件只有一个，放到指定路径即可，不要手动解压。

### 前置

- **Linux 主机内核 ≥ 6.8**（`uname -r`；与 Ubuntu 24.04 LTS 默认内核一致）。基础镜像为 `ubuntu:24.04`，Harbor/Docker 需 **cgroup v2**；低于 6.8 不在支持范围内。macOS / Windows 仅通过 Docker Desktop（或同类）提供的 **Linux VM 内核**满足上述要求，宿主机 Darwin/NT 版本本身不算数。
- Docker 可用（`docker info`；Storage 常用 overlayfs，Cgroup Version 应为 2）
- 离线资源包 `inputs.tar.zst`（约数 GB，不进 git；需向 **AI4EC** 申请获取）
- 模型 API key（默认 DeepSeek，见 `.env.example`）

### 步骤

```bash
# 1. 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. clone 并进入仓库
git clone <本仓库 URL>
cd comp-chem-world

# 3. 放置资源包（唯一固定路径）
mkdir -p shared
mv /path/to/inputs.tar.zst shared/inputs.tar.zst

# 4. 初始化：同步依赖 → 解包物料 → 恢复任务输入 → 生成 .env → 构建基础镜像
uv run init

# 5. 编辑 .env，填入 ANTHROPIC_API_KEY= 与 ANTHROPIC_BASE_URL=
#    （任意 Anthropic 兼容端点均可；默认示例指向 DeepSeek）

# 6. 全量 local 测评（任务集 + agent 两份配置一起传）
uv run harbor run -c configs/local.yaml -c configs/agent.yaml --env-file .env -y
```

`uv run init` 会把 `shared/inputs.tar.zst` 解到 `shared/wheelhouse/` 与 `shared/asset-store/`，再恢复进各任务目录；之后可反复 `uv run harbor …`。默认恢复全部任务输入；加 `-s <job-config.yaml>` 时只 restore 该配置里列出的 tasks（归档路径不变）。恢复后还会去掉 `tasks/*/tests/refs.json` 上的 group/other 写权限（避免 umask 0002 导致独立评分镜像 `prepare` 失败）。

### 常用命令

```bash
# 冒烟（不需要 API key）
uv run harbor run -p tasks/000-hello -a oracle -y

# 只恢复物料，不构建镜像
uv run init --inputs-only

# 只恢复某个任务子集（例如 20 题清单）
uv run init -s configs/local-a-selected-20.yaml
# 可与 --inputs-only 合用：
uv run init --inputs-only -s configs/local-a-selected-20.yaml

# 打包离线资源（需完整 store 且未 restore；必要时先 uv run reset）
uv run pack
uv run pack -s configs/local-a-selected-20.yaml
# 子集包默认写到 shared/inputs-local-a-selected-20.tar.zst；对方改名为 shared/inputs.tar.zst 后再 init

# 卸下 tasks/ 下已恢复的输入（保留镜像、.env、jobs、共享 store）
uv run reset

# HPC / 集群任务（需先构建 connectivity 镜像）
# cp images/connectivity/hpc.toml.example images/connectivity/hpc.toml  # 填 host/user/key
# bash images/connectivity/build.sh   # → compchembench-connectivity:hpc
uv run harbor run -c configs/hpc.yaml -c configs/agent.yaml --env-file .env -y
```

## 评测配置

| 配置 | 内容 |
|------|------|
| `configs/local.yaml` | 全部 local 任务（196，含 `000-hello`） |
| `configs/local-a.yaml` | local 前半：benches 01–18 + `000-hello`（98） |
| `configs/local-b.yaml` | local 后半：benches 19–38（98） |
| `configs/local-a-selected-20.yaml` | local-a 的 20 题子集（可配合 `uv run init -s`） |
| `configs/hpc.yaml` | HPC / 集群任务（50） |
| `configs/agent.yaml` | 默认 agent / 模型（与上面任一任务集组合使用） |

`local-a` / `local-b` 按论文（bench）边界前后拆分，合起来等于完整 local 集、互不重叠，方便两人并行。切点不会落在同一篇文章中间。

默认 agent 为 `claude-code`，默认模型为 `deepseek/deepseek-flash`（在 `configs/agent.yaml`）。凭证统一走 `.env` 的 `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL`（任意 Anthropic 兼容网关）。不要提交 `.env`。

### 切换模型与 base_url

- **换端点 / key**：改 `.env` 的 `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY`
- **换默认模型**：改 `configs/agent.yaml` 的 `model_name`
- **单次覆盖**：用 CLI（先 `agents.clear.yaml` 清掉默认 agent，再传 `-a` / `-m`）

```bash
# 换推理端点（本次）
uv run harbor run -c configs/local.yaml -c configs/agent.yaml --env-file .env \
  --base-url https://your-gateway.example/anthropic -y

# 换模型（本次）
uv run harbor run -c configs/local.yaml -c configs/agents.clear.yaml \
  -a claude-code -m anthropic/claude-sonnet-4-5 --ak version=2.1.317 \
  --api-key-name ANTHROPIC_API_KEY --env-file .env -y

# 先看 Harbor 实际会选用哪套凭证/端点
uv run harbor run --dry-run -c configs/local.yaml -c configs/agent.yaml --env-file .env -y
```

## 资源包

唯一需要手动放置的大文件。不进 git，请向 **AI4EC** 申请后再放到下列路径：

| 文件 | 放置路径 |
|------|----------|
| `inputs.tar.zst` | `shared/inputs.tar.zst` |

维护者在本地 store 齐备后重打包：

```bash
python3 -I scripts/task_inputs.py pack   # → shared/inputs.tar.zst
```

## 基础镜像

`uv run init` 已包含构建。单独重建：

```bash
bash images/build.sh      # 构建全部
bash images/build.sh -f   # 删旧镜像后再建
```

需要代理时设置 `http_proxy` / `https_proxy`。镜像链：

```text
ubuntu:24.04
  └── comp-chem-world-base              # Python、uv、pytest、Claude Code
        └── comp-chem-world-base-chem   # + ase、rdkit
```

## 目录结构

```text
src/comp_chem_world/   # 可安装 Python 包
tasks/                 # Harbor 任务（000-hello + 001–245）
docs/benchmarks/       # 论文—任务索引与各 bench README
shared/inputs.tar.zst  # 离线资源包（gitignored）
shared/wheelhouse/     # 解包后的离线 wheel
shared/asset-store/    # 解包后的 asset blob
scripts/               # 打包 / 恢复 / 校验
images/                # 共享基础镜像
configs/               # Harbor job 配置（任务集 + agent.yaml）
```

## 说明

- 首次 `uv run …` 会按 `uv.lock` 自动创建 `.venv`，一般不必手动 `uv sync`。
- 磁盘建议预留数十 GB（镜像 + 解包物料）。
- 缺少 `compchembench-connectivity:hpc` 时，只有 HPC 配置里的任务会失败，local 不受影响。构建：填好 `images/connectivity/hpc.toml` 后执行 `bash images/connectivity/build.sh`。镜像只烘焙 SSH（alias `hpc`）和 `/app/AGENTS.md`；agent 用 SSH 自探集群，作业目录须唯一且勿扫登录节点其它路径。
- 仓库约定与维护细节见 [`AGENTS.md`](AGENTS.md)。
