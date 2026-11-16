# 任务：Si–O 势的三阶段主动学习标签效率评估

## 背景

可迁移的 Si–O 原子间势需要同时描述晶体、无序、高压、混合组分和表面环境。给定几何结构覆盖六类环境，其已有 DFT 标签可通过受控查询服务获取。本题研究 ACE 主动学习的标签效率，无需新做 DFT 计算。

## 任务

以 12 个初始标签训练三成员 ACE 委员会，再进行两轮主动选点，每轮获取 6 个新标签并重训全部成员：共 24 个标签、9 次真实拟合。判断最终委员会能否提高能量和力的预测精度，同时避免某一域明显退化。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、NumPy、pandas、PyYAML、scikit-learn、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

操作性判据要求能量和力两项汇总指标均至少改善 5%，且各自 95% 置信区间下界至少为 5%。任一域内每项指标的退化不得超过 25%。

- 使用 `/app/inputs/v2/geometry-manifest.json`：每域 2 个初始结构和 20 个候选结构，共 132 个几何构型。只使用该清单列出的构型。保留原子顺序、物种和晶胞。训练只能使用对应构型已经返回的标签；独立测试值和评估结果不得参与训练、选点或停止决策。
- 每轮用上一阶段委员会计算完整固定候选池的力分歧：先对三个成员的每个原子笛卡尔力分量求样本方差（`ddof=1`），再对全部原子和分量取平均并开平方。域内按分歧降序、结构 ID 升序排序，从尚未查询的结构中各取一个；请求中的六个 ID 按域名字母序排列。保留完整排序，将已查询结构标为不可选，并在查询前登记选点。全部可选结构分歧均为零的委员会不足以支持选点。
- 使用提供的 ACE 后端和模板，各阶段采用三个不同随机种子 `7000 + 100*r + 17*m`，其中 `r=0,1,2`，`m=1,2,3`。训练集按标签释放顺序累计。初始参考集保持固定：仅用初始标签最小二乘确定 Si/O 元素能量零点，后续及测试标签不得用于重新拟合零点。保存可重载模型、原生训练日志和精确训练成员。单次拟合上限 1,800 秒；本次试次活跃时间不超过 12 小时，由试次受信服务记录耗时和隔离拟合回执。
- 在独立的 80 帧、16 个来源文件、六域数据上比较第 0 与第 2 阶段的每原子总能量 RMSE 和力分量 RMSE。通过在域内重采样来源文件簇量化不确定度，同时保留规定的帧权重及固定表面簇。此比较不能证明轨迹族独立或保证收敛；说明不确定度与外推局限。
- 通过本次试次的受控查询服务获取标签并登记选点，保留其原始返回记录。拟合由同一受信服务分派至任务提供的隔离 worker。本任务不需要新做 DFT 计算或用户自行管理 HPC 分配。服务或 worker 不可用时如实报告，不得编造标签或执行记录。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/v2/geometry-manifest.json` | 六域结构清单。 |
| `inputs/` | 给定输入与资源目录。 |

输入位于 `inputs/`，结果写入 `/app/outputs/`。能量单位为 eV，力单位为 eV/Å。服务返回的回执和绑定须原样保留。

| 路径 | 必需内容 |
| --- | --- |
| `labels/{seed,round-1,round-2}.extxyz`、`oracle-query-receipts.jsonl` | 原样保留标签释放和查询回执。每个训练帧保留 `queried_id`、`dft_energy` 和有序 `dft_forces`。 |
| `training/round-{0,1,2}.extxyz`、对应 `.ids`、`training/seed-only-reference.extxyz` | 按释放顺序累计的标签帧及顺序一致的逐行 ID；seed-only 参考集保持固定。 |
| `models/round-{r}/member-{m}/` | 原生 `potential.yaml`、`potential.yace`、`manifest.json`、`trusted-fit-binding.json`。各阶段 `committee.json` 使用 `case07-v2-committee/v1`，记录 `round`、`training_sha256` 及三个成员的 `seed`、`model_yace`、`model_sha256`、`backend_manifest_sha256`、`training_sha256`。拟合回执及原生输入/输出保存在 `fit-evidence/round-{r}/member-{m}/`。 |
| `selections/round-{1,2}.json` 及对应 `.request.json` | 选点文件含 `round`、`pool_sha256` 和完整 `ranked` 列表；每项含 `id`、`geometry_sha256`、`force_disagreement_eV_per_A`、`eligible_for_selection`。请求含 `phase`（`round-1` 或 `round-2`）和按域排序的六个 `ids`。 |
| `active-budget-receipt.json`、`stop_decision.json`、`provenance.json` | 原样保留服务生成的预算、来源、回执及独立 attempt 绑定。后两者分别使用 `case07-v2-stop-decision/v1`、`case07-v2-provenance/v1`；记录覆盖 12+6+6 标签、零次新 DFT、所有冻结委员会和本次活跃时间，并与历史来源运行区分。 |
| `/app/case07-artifacts/trusted` | 必需的受信结果。 |
