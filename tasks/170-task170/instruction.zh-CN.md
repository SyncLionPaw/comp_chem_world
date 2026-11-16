# 任务：—规划 QE 7.2 电声输入链

## 背景

本题仅设计静态输入，不要求运行 Quantum ESPRESSO。
给定资料使用更密的网格（192×192×1 k、96×96×1 q）。
阅读 `assets/computational-brief.md`，并以 `assets/W2N3-monolayer.poscar` 为固定初始结构（五原子 W₂N₃，a=2.9131 Å，P-6m2）。

## 任务

建立连贯的 QE 7.2 原生插值链、可审计的成本计划，以及根据实际 PH lambda 文件 q 头计算不可约 q 权重的辅助程序。
提供两种 μ* 后处理输入。
计划估算不是实测性能。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

使用 64×64×1 **未移位**密集 SCF 拟合并启用 `la2F=.true.`，粗 SCF 为 16×16×1，q 网格为未移位 4×4×1。两个 SCF deck 共用 prefix、outdir、晶胞和有序坐标；均须用 `ATOMIC_POSITIONS (crystal)`，且与 POSCAR 每原子周期等价误差≤0.001 Å、晶格矢量误差≤0.001 Å。粗 SCF 保留对称性。`ecutwfc≥60 Ry`，占据方式为 smearing 且 `degauss=0.005–0.02 Ry`；结构净真空≥15 Å、c≥20 Å。使用 QE 7.2 `electron_phonon='interpolated'`；`ph.in` 声明 `fildvscf` 与 `fildyn`。`q2r.in` 启用 `la2F`，读取与 PH 相同的 `fildyn` 并写出 `flfrc`；`matdyn.in` 启用 `la2F` 与 DOS，声明 `fldos`，并提供正整数 `nk1`、`nk2`、`nk3`，读取相同的 `flfrc`。再运行两次 lambda.x 后处理。`make-lambda-input.py` 根据输入结构和完整网格用 spglib 求轨道重数；读取实际 PH lambda 文件头，将 QE `tpiba`（笛卡尔 2π/alat）坐标转换为倒易晶格分数坐标；遇到 q 缺失/重复或总权重≠16 时失败关闭，然后为 μ*=0.16/0.10 写标准 stdin。`run.sh` 顺序为：密集 SCF 拟合 → 粗 SCF → ph.x → q2r.x → matdyn.x → q 映射辅助程序 → 两次 lambda.x。PH 文件生成前不得写 lambda 输入。不得声称已运行 QE、实测可行性、实际误差方向或收敛性。对密集 k、粗 k、q 插值和 smearing 的不确定性须说明为未解决；不得作无依据的误差方向或无额外误差声明。总估算≤300 core-hours，DFPT≤40；估算为计划值，各组成项为正有限数并加总一致。

### 输入与产物细则

在 `/app/final/` 提供 `scf.in`、`coarse_scf.in`、`ph.in`、`q2r.in`、`matdyn.in`、`make-lambda-input.py`、`run.sh`、`plan.json`。
使用完整的**紧凑** `plan.json` 格式（扩展格式仍受支持）：`route`=`qe_native`；
`qe_target`=`QE 7.2`；
`execution_order` 按序列出 `dense_scf_fit, coarse_scf, ph, q2r, matdyn_a2f, lambda_postprocess`；
`structure` 对象含数值 `n_atoms`、`cell_height_z_A`；
`cutoffs.ecutwfc_ry` 为数值；
`smearing` 含字符串 `occupations`、数值 `degauss_ry`；
`grids` 含整数数组 `dense_scf_k`、`coarse_scf_k`、`q`；
`estimated_core_hours` 对象含正有限数 `dense_scf`、`coarse_scf`、`ph`、`post`、`total`（总计与组件差≤1e-6）；
字符串 `estimate_basis` 明确费用是计划估算而非实测；
`justifications` 对象含 `dense_scf_k`、`coarse_scf_k`、`q`、`degauss` 的说明，描述取舍和不确定性且不声称误差方向。
还要说明 cutoff/smearing 选择、执行/数据流以及预算和精度限制。
交付件由静态检查；
生产计算前须换成有许可且兼容的赝势文件。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `assets/computational-brief.md` | 给定数据、参数或方法说明；用途见任务要求。 |
| `assets/W2N3-monolayer.poscar` | 给定科学输入或资源；格式和单位见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
