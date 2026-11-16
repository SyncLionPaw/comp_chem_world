# 任务：Hsp60 V72I 单体动力学：柔性与变构通信

## 背景

`environment/assets/` 提供野生型 M_WT 与突变体 M_V72I 的溶剂化 Amber 拓扑和坐标；力场与溶剂为 ff14SB/TIP3P。拓扑含 Ala0，成熟蛋白编号比系统残基编号小 1；系统 Val73/Ile73 是成熟 V72。`md_inputs/` 中的预生产和生产输入仅供参考，生产输入示例时长不是必须时长。提交工作的总运行时间上限为 12 小时（43,200 秒）。

## 任务

基于两种单体体系，研究 V72I 与柔性、主导运动、催化二联体预组织及结构区域间通信的关系。刚性化、预组织和变构重连都是待检验假设，不预设方向或结果。根据采样和收敛证据限定结论；证据不足时应报告 `INSUFFICIENT_SAMPLING`。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

如果使用 HPC 计算资源，请查阅 `ikkem-slurm`。

自行选择副本数、生产长度、平衡判据和分析区段，并说明选择及局限。每种变体至少使用两个不同速度随机种子的独立副本；每副本至少 2 帧，每种变体合计至少 21 帧。该最低数据量仅保证所述分析可计算，不代表采样充分或生物学结论可靠。

使用成熟蛋白编号映射特征原子，并按所给拓扑核对：γ 为 Cα(Val232)–Cα(Ala404)–Cα(Leu513)，δ 为 Asp50:Cγ–Asp397:Cγ。报告 δ 距离（Å）和 γ 角度（度），逐帧给出与原生轨迹帧对应的值。RMSF 对每个副本分别计算：各帧先以该副本第一帧作最小二乘拟合，再计算总体均方波动（`ddof=0`）。

DF 对每种变体合并全部生产帧，计算各 CA 对距离的总体方差（`ddof=0`）；`|i-j|<2` 的元素设为 0。百分比变化为 `100*(M_V72I-M_WT)/M_WT`；当 `|M_WT|<=1e-15` 时写 NaN。PCA 将所有 CA 坐标拟合至 WT 副本 1 的第一生产帧，仅分析成熟残基 2–522（含端点），逐坐标中心化后用 SVD 计算各变体前 20 个方差比例及两者 top-20 RMSIP。坐标数组第 0 帧必须是第一生产帧。

遵循主机执行配置及本题运行预算，保留原生输出、执行记录和实际资源用量证据。总预算为 12 小时。

### 输入与产物细则

在 `final/` 提交 `run_manifest.json`、`native-artifacts.json`、`convergence.json`、`descriptors.csv`、`pca.json`、`df_delta.npy`、`rmsf.csv`、`conclusions.json` 和 `report.md`。`run_manifest.json` 使用 `hsp60-case01-run-manifest/v1`，记录输入 `input_sha256`、运行列表 `runs` 及 `runtime`；每次运行含 `variant`、正整数 `replica`、`seed`、`production_frames`、`production_steps`、拓扑/重启哈希、CA 原生原子选择哈希和 `artifacts`。输入哈希覆盖两个变体各自的 `.top`、`.rst` 和 `md_inputs/minimisation_stage1.in`。每次运行的工件须包括名称以 `-analysis-coordinates.npz`、`.dcd`、`-state.csv`、`-engine.log` 结尾的文件，以及以 `-final-state.xml`、`.rst7`、`.nc` 之一结尾的重启；要求整数的字段必须使用 JSON 整数，不接受布尔值、字符串或小数。`runtime.elapsed_seconds_total` 为不超过 43,200 的有限非负 JSON 数，`within_deadline` 为反映该上限的布尔值。状态列为 `step,time_ps,temperature_K,density_g_ml,volume_nm3`；NPZ 含 `ca_angstrom`、`gamma_delta_angstrom`、`ca_mature_indices`、`feature_atom_indices`。坐标数组分别为 `(帧数,526,3)` 与 `(帧数,5,3)`；特征顺序为 Val232、Ala404、Leu513 的 CA，然后 Asp50、Asp397 的 CG；CA 成熟编号索引恰为 0–525。`native-artifacts.json` 使用 `hsp60-case01-native-artifacts/v1`，其 `files` 为所有原生工件及派生结果（不含清单自身）的相对路径、字节数和 文件校验值。

`descriptors.csv` 含 `variant,replica,seed,frame,time_ps,delta_angstrom,gamma_degrees`；`rmsf.csv` 含 `variant,replica,mature_residue_index,rmsf_angstrom`。`pca.json` 含每变体 20 个 `top20_variance_fraction`、非空 `fit_reference`，以及数值型 `cross_variant.top20_rmsip`。`convergence.json` 的 `overall` 为 `INSUFFICIENT` 或 `DEMONSTRATED`；若声称已证明收敛，须列出判据。

`conclusions.json` 使用 `hsp60-case01-conclusions/v1`；含 `overall`，以及 `claims.<名称>.{status,effect,replicate_effects,ci95}` 和 `evidence.{convergence_demonstrated,independent_replicas_per_variant}`。总体及 `rigidification`、`dyad_preorganisation`、`pca_similarity`、`allosteric_rewiring` 各自的状态为 `INSUFFICIENT_SAMPLING`、`NO_SIGNIFICANT_DIFFERENCE` 或 `SUPPORTED_MUTATION_EFFECT`。任何非不足采样的分项判断都须提供已证明收敛、每变体至少两个独立副本、有限效应、至少两个有限副本效应及包含该效应的有序有限 95% 区间；效应应与副本效应均值一致。无显著差异的区间须包含零；支持突变效应的区间须排除零且各副本方向一致。非不足采样的总体结论也须满足收敛和副本要求；总体支持效应须至少有一个支持分项，总体无显著差异不得与支持分项冲突。不要把最低帧数当作收敛证据。`report.md` 须为可读且非空的科学报告，说明方法、采样、不确定性和解释边界，以及本包未提供的原始 2 μs 轨迹这一限制；不得以该轨迹替代自己的证据。

输入拓扑、重启文件和 `md_inputs/` 示例均位于 `environment/assets/`。所有提交结果置于 `final/`，并保持上述文件名、字段单位、成熟残基编号和原生证据的对应关系。结论应以自己的可审计数据为依据，不要求得到特定方向。

若使用环境提供的辅助脚本，应遵循其公开接口，并自行确定所选工作流需要的设置；不要假设特定集群、目标、路径或私有配置。只将成功收集到的 `final/` 内容放入新的空输出目录。保留足以追踪或检查超时作业的提交状态，避免对状态未知的作业重复提交。

每条轨迹的引擎日志须写明 `engine=openmm`、`engine=pmemd` 或 `engine=pmemd.cuda`，并以 `seed=<整数>` 记录实际副本种子。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `environment/assets/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
