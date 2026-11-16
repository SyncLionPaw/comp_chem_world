# 模型执行前的环境失败：修复与复测

对应原始 job：`jobs/comp-chem-world-local`。本页覆盖 042、061、071–074、110、112、113；015/020 的离线依赖修复见 [Bench 03](03-autosolvateweb-explicit-solvation.md#environment-preparation-and-reruns)。这些 trial 在 agent 开始回答前失败，不能据此评估模型能力。

| 任务 | 原因 | 修复 |
| --- | --- | --- |
| 042 | AMD64 上 PyTorch 引入没有锁定哈希的 CUDA 依赖 | 按 ARM64/AMD64 选择官方 PyTorch 2.8.0 CPU wheel，继续强制哈希校验 |
| 061 | pip 下载依赖读取超时 | 使用 uv、300 秒请求超时、5 次重试和 BuildKit 下载缓存，保留依赖锁和哈希 |
| 071–074 | Compose 强制 ARM64，离线运行工具仅提供 ARM64 包 | 使用主机原生架构，补齐同版本 AMD64 deb；072 的 chroot 动态库路径使用 Python 的 MULTIARCH |
| 110 | 1200 秒构建超时 | 预置固定版本 MACE-OFF23-small，缓存依赖下载；构建上限调整为 3600 秒 |
| 112 | MACE 模型下载连接中断 | 预置固定的 MACE-MATPES-PBE-0 checkpoint 并断网加载检查 |
| 113 | Hugging Face 网络不可达 | 预置固定 commit 的 CHGNet 快照和 main 缓存引用，设置 HF_HUB_OFFLINE=1 并断网加载检查 |

模型名称、任务要求和评分逻辑保持原有语义。模型缓存内的 `manifest.json` 记录版本、实际下载地址、大小与校验来源，`SHA256SUMS` 在构建时强制校验。MACE-OFF23 对照上游 Git blob 哈希，CHGNet 对照上游 Git/LFS 哈希。MACE-MATPES 的上游 release 没有公布完整文件摘要：本地副本核对了上游大小、直接下载的字节区间和 ZIP CRC，再固定本地 SHA-256；这些校验不等同于上游签名。

新资源已随任务目录提供，测评构建无需在线下载这些模型。Python 依赖、Ubuntu 包及固定 commit 的 AtomisticSkills 源码仍需在首次构建时联网获取；超时和重试不能替代可用的构建网络。MACE 模型沿用上游 ASL 许可，详情见缓存清单链接。

在测评机仓库根目录运行，使用同一个 Docker daemon：

```bash
uv run init
bash scripts/prebuild_environment_repairs.sh
uv run harbor run -c configs/environment-oracle.yaml --env-file .env -y
```

预构建脚本串行构建这 9 个环境，再以 `--network none` 启动 Python 导入/模型加载检查；Harbor 后续构建可以复用同一 daemon 的层缓存。不要在预构建和测评之间清理 Docker 构建缓存。预构建失败时先修环境，不要启动付费模型 trial。

Oracle 配置覆盖 8 个提供参考解的任务。061 明确声明 `reference_solution_provided = false`，因此仅做环境冒烟检查，后续仍需检查真实模型运行和 verifier 输出。042 的 verifier 需要有效的 `BENCH07_REVIEW_API_KEY`、`BENCH07_REVIEW_BASE_URL`、`BENCH07_REVIEW_MODEL`；按 `.env.example` 配置后再验证，不要为了通过 oracle 关闭评审。

Oracle 必须无异常、产生数值 reward，并检查是否达到任务预期；有参考解的任务应达到 reward 1。通过后再运行：

```bash
uv run harbor run -c configs/environment-rerun.yaml --env-file .env -y
```

重跑配置串行执行这 9 个任务，使用单独的 job 名称，保留原始失败结果。它不会自动重跑 015/020；那两个任务继续使用 `configs/autosolvate-rerun.yaml`。API 余额、评审服务配置以及模型作答后的 verifier 失败需另行核查。

本次开发检查通过：9 个任务的 TOML 与 Docker RUN shell 语法、重跑配置 YAML、28 份 deb 和 5 个模型文件的哈希/归档校验、MACE 上游源码的缓存选择检查、两种架构的工具包选择与 072 动态库路径生成。共享资源校验通过（467 个 wheel 映射、77 个 wheel blob；302 个 asset 映射、79 个 asset blob）。

本次开发机器没有 Docker/Harbor，未执行镜像构建和 oracle，也未在真实科学运行时反序列化模型。文件校验及源码层面的检查不能代替上述容器验证。
