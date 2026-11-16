# comp-chem-world

计算化学 agent 评测环境（Harbor task + 共享 Docker 基础镜像）。

## 新人：从 clone 到全量测评

按顺序做完即可开跑（不要跳过资源包）。

### 前置

- Docker 已安装且当前用户可执行 `docker info`
- 能拿到离线资源包 **`inputs.tar.zst`**（约数 GB；不进 git，单独分发）
- 有模型 API key（默认 DeepSeek，见 `.env.example`）

### 步骤

```bash
# 1) 安装 uv（macOS / Linux）
curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version

# 2) clone 本仓库
git clone <本仓库 URL>
cd comp-chem-world   # 若目录名不同，以实际为准

# 3) 把压缩包放到固定路径（不要解压，不要放进 tasks/）
mkdir -p shared
mv /path/to/inputs.tar.zst shared/inputs.tar.zst
ls -lh shared/inputs.tar.zst

# 4) 一键初始化：同步依赖（含 Harbor，版本 pin 在 pyproject）→ 解包物料 → 恢复任务输入 → 建 .env → 构建基础镜像
uv run init

# 5) 填 API key
#    init 若已生成 .env，直接编辑；否则：
cp -n .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY=
# 自定义推理端点：改 .env 里的 DEEPSEEK_BASE_URL（默认 DeepSeek 官方 Anthropic 兼容端点）

# 6) 全量 local 测评
uv run harbor run -c configs/local.yaml --env-file .env -y
```

`shared/inputs.tar.zst` 是**唯一**需要手动放置的大文件。`uv run init` 会把它解到 `shared/wheelhouse/` 与 `shared/asset-store/`，再恢复到各任务目录，之后可反复 `uv run harbor …`。

冒烟（不需要 API key）：

```bash
uv run harbor run -p tasks/000-hello -a oracle -y
```

只要恢复物料、不建镜像时：

```bash
uv run init --inputs-only
```

卸下恢复到 `tasks/` 的输入副本（保留镜像、`.env`、jobs、共享 store）：

```bash
uv run reset
```

### 说明

- 首次 `uv run …` 会按 `uv.lock` 自动建 `.venv`，一般不必手动 `uv sync`。
- 磁盘建议预留数十 GB（镜像 + 解包物料）。
- 部分 HPC/集群任务仍依赖单独的 `compchembench-connectivity:hpc` 镜像；缺该镜像时这些任务会失败，其余本地任务不受影响。
- 更细的仓库约定见 [`AGENTS.md`](AGENTS.md)。

## 资源包位置（必读）

| 文件 | 放置路径 | 说明 |
|------|----------|------|
| `inputs.tar.zst` | **`shared/inputs.tar.zst`** | 离线 wheels + 科学 assets 的唯一分发包（gitignored） |

维护者在本地 store 齐备后重打包：

```bash
python3 -I scripts/task_inputs.py pack    # -> shared/inputs.tar.zst
```

## 构建基础镜像

`uv run init` 已包含镜像构建。需要单独重建：

```bash
bash images/build.sh      # 构建全部
bash images/build.sh -f   # 先删旧镜像再重建
```

需外网时先设 `http_proxy` / `https_proxy`。镜像链：

```text
ubuntu:24.04
  └── comp-chem-world-base            # Python、uv、pytest、Claude Code
        └── comp-chem-world-base-chem   # + ase、rdkit
```

## 目录结构

```text
src/comp_chem_world/   # 可安装 Python 包
tasks/                 # Harbor 任务（000-hello + 001–185 + 189–248）
docs/benchmarks/       # 论文—任务映射索引及 bench README
shared/inputs.tar.zst  # 唯一需放置的资源包（gitignored）
shared/wheelhouse/     # 解包后的离线 wheel（*.whl 不进 git）
shared/asset-store/    # 解包后的 assets blob（*.blob 不进 git）
scripts/               # 打包 / 恢复 / 校验
images/                # 共享基础镜像
configs/               # Harbor job 配置（local.yaml / hpc.yaml = 分类全量）
```

## 跑任务（补充）

```bash
# 参考答案
uv run harbor run -p tasks/000-hello -a oracle -y

# 全量
uv run harbor run -c configs/local.yaml --env-file .env -y

# 全量 HPC 任务
uv run harbor run -c configs/hpc.yaml --env-file .env -y
```

默认 agent 为 `claude-code`，模型为 `deepseek/deepseek-flash`（见 `configs/local.yaml` / `configs/hpc.yaml`）。推理端点由 `.env` 的 `DEEPSEEK_BASE_URL` 控制（默认 DeepSeek 官方 Anthropic 兼容端点，可换成自建网关；单次运行也可用 `--base-url` 覆盖）。不要提交 `.env`。

**论文与任务索引：** [docs/benchmarks/README.md](docs/benchmarks/README.md)。
