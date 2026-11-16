# 任务：单状态双相自由能与误差预算决策

## 背景

在 600 K、20,000 bar 下，使用任务包提供的 SiOx YACE 哈密顿量比较有限胞 alpha-quartz（576 个原子）与 coesite（384 个原子）的 Gibbs 自由能。报告有证据支持的 ΔG = G_coesite − G_alpha 符号及不确定度，或报告 `unresolved`。这是单一状态下的有限胞比较；不得推断相界或热力学极限下的相序。

## 任务

生成可追溯至源数据的比较结果与不确定度证据。正向和反向方向须分别保留。本次研究包含四个基线方向（B）、四个使用独立随机种子的重复方向（R），以及四个用于一种自适应检查的方向：时长（D）或尺寸（S）。重复须使用独立随机种子和快照；时长比较须共享其基线快照和 seed。执行所选检查前，冻结选择规则和比较标准。

12小时主动计算额度包含提交结果固定后的独立参考准备；无需重复生成参考，须为其预留额度，并按下文核算可追溯主动计算时段。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、PyYAML、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

使用完全一致的任务包哈密顿量、来源可绑定的输入、可执行文件、软件和调用接口。公开计算配置位于 `/app/inputs/candidate-runtime/candidate-scope.json` 和 `/app/inputs/candidate-runtime/native_inputs/input-template*.json`。这些文件定义各角色的采样方式：B/R/S 每个方向切换 20,000 步，D 每个方向切换 40,000 步。保持温度、压力、胞、势函数和采样条件与来源文件一致，不得替换协议。

如果使用 HPC 计算资源，请查阅 `ikkem-slurm`。

本次计算最多进行 12 次方向尝试（包括失败和重试），实际或保守预留 MD 步数不超过 484,000。每相共享平衡最多 20,000 步，每个共享阶段只计一次。每次独立评测的活跃计算时间不超过 12 小时。按有来源的活跃区间计时；仅当独立调度记录证明排队时间与活跃工作不重叠时，才可排除排队时间。上述均为上限，不保证收敛。计算资源不可用时如实报告 `NOT_RUN`；不得伪造运行证据。

证明原生稳定性、定胞统计充分性、体积与三斜晶胞面高/cutoff 安全性、Einstein 参考及 PV 归一化正确，并给出经过校准的不确定度。未测系统误差须明确标为 `UNKNOWN`，不能写成零；不得声称合并不确定度已控制未测误差。报告有限胞结论及其局限，或报告 `unresolved`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/candidate-runtime/candidate-scope.json` | 公开范围、方法和运行时身份输入。 |
| `/app/inputs/candidate-runtime/native_inputs/input-template*.json` | 各角色的原生采样模板。 |

所有结果写入 `/app/outputs/`。

| 路径 | 必需内容 |
| --- | --- |
| `gibbs_free_energy.csv` | 每个方向/重复分别一行，精确表头：`phase,T_K,P_bar,G_eV_per_atom,replicate,direction,cell_atoms,equilibration_steps,switching_steps,window_start,window_end,uncertainty_eV_per_atom,status,reason`。 |
| `delta_g.csv` | 基线比较，精确表头：`T_K,P_bar,G_coesite_minus_G_alpha_eV_per_atom,repeat_uncertainty_eV_per_atom,direction_uncertainty_eV_per_atom,switching_uncertainty_eV_per_atom,finite_size_uncertainty_eV_per_atom,combined_uncertainty_eV_per_atom,decision,reason`；`decision` 为 `same_sign_resolved` 或 `unresolved`，reason 非空。 |
| `error_budget.csv` | 至少包含 `quantity,estimate_eV_per_atom,status,reason`，并分别记录 `repeat`、`direction`、`switching`、`finite_size`。可增加科学分析列；未知估计不得写成数值零。 |
| `allocation_log.json`、`summary.json` | allocation log 记录初始状态理由、自适应观测与选择、被拒方案、剩余预算和停止原因。summary 包含 `temperature_scope_K:[600]`、`pressure_scope_bar:[20000]`、`phase_boundary_claim:false`、`total_md_steps`、`total_atom_steps`，以及状态、哈密顿量/软件/元素身份、方向与重试数、活跃/排队时间、资源用量、结论、证据和局限；总量须与原生证据一致。 |
| `native_inputs/`、`integration_runs/`、`figures/` | 保留原生输入、日志、来源记录及至少一张图。原样保留服务生成的调度回执、`outputs-manifest.json` 和 `native-event-ledger.json`。 |
| `campaign-evidence.json` | 使用 schema `case06-single-state-v2-campaign-evidence/v2`、protocol `single-state-v2`；保留运行时生成的绑定与来源证据。每次方向尝试均须追溯到共享阶段及正反向来源片段。 |
