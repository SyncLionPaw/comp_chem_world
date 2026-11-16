# 任务：求解耦合 Poisson–Fermi 双电层

## 背景

公开请求 `/app/assets/edl_request.json` 固定了模型：核常数 `K11=0.140125`、`K12=-0.207118 Å²`、`K13=0.011290 Å⁴`、`K21=0.015908`、`K22=2.003940 Å²`；`T=300 K`、`alpha=0.5`、`a=0.8 nm`、`sigma0=0.1 C/m²`；以及 `c={1,10} mM` × `Pbar={-0.05,0,0.05,0.1} C/m²` 的八个条件。方程用 SI 单位、`z` 用米；剖面坐标用 Å。

令 `psi=q phi/(kB T)`，使用格气闭合

```
n+ = nb exp(-psi) / [1 + 2 nb a^3 (cosh(psi)-1)]
n- = nb exp(+psi) / [1 + 2 nb a^3 (cosh(psi)-1)]
```

求解耦合方程

```
eps0 phi'' - P1' - P2' + q(n+ - n-) = 0
K11 P1 - K12 P1'' + K13 P1'''' + eps0 phi' = 0
K21 P2 - K22 P2'' + eps0 phi' = 0
```

壁面处施加 `P1=(1-alpha)Pbar`、`P2=alpha Pbar`、自然变分条件 `P1''=0` 和 `eps0 phi'=Pbar-sigma0`；远场 `phi=P1=P1'=P2=0`。`P1'(0)` 是求解输出而非边界输入。报告 `rho1_wall=-P1'(0)` 与 `rho_total_wall=-(P1'+P2')(0)`（单位 C/m³）——它们是极化梯度观测量，不是表面电荷密度。

## 任务

实现可复用的求解器，重现所要求的尖锐与粗糙度平均剖面。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、MDAnalysis、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 提交 `final/solver.py`（可在 `final/` 内附常规 `.py` 辅助文件）。须暴露 `Parameters`、`DoubleLayer(parameters)`、`DoubleLayer.solve(tol=...)`、`DoubleLayer.profile(z_A=...)`，并支持

  `python3 /app/final/solver.py --input /app/request/edl_request.json --output-dir /app/final`

- 离格请求必须按实际的 `sigma0`、浓度与 `Pbar` 重新计算，不得按 `run_id` 从存储表中选择。探针范围为 `c=1–10 mM`、`Pbar=-0.05–0.1 C/m²`、`sigma0=0.08–0.12 C/m²`，T、alpha、a、K 固定。每个解支从零场基线连续延拓，不要在折叠处切换分支——应细化步长或网格后继续。
- 两张剖面表使用请求规定的精确网格：`z` 从 0 到 12 个 Gouy–Chapman 长度向上取整到 10 Å 的整数倍，每行对应 `z_i=i*0.05 Å`。内部网格可以更细。输出元数据中保留全部输入参数与单位标注。
- 粗糙度重建：对每个尖锐场沿 `ell>=0` 用归一化的 Eq. 19 分布 `exp(-((ell-mean)/delta)^2)` 卷积，`mean=2.5 Å`、`delta=1.5 Å`（标准差为 `delta/sqrt(2)`）。`n+` 与 `n-` 分别平均——闭合是非线性的，绝不可由平均后的 `phi` 重算——导数列取局部尖锐导数的平均。粗糙密度与占据数在舍入误差内须非负，且占据数不得超过局部液相分数。
- 写出 `final/dl_profiles_sharp.csv`、`final/dl_profiles_smeared.csv`（列序与行集合按请求的 `output_contract`）、`final/analysis.json`（必需键 schema：BVP 收敛、边界、积分电荷、占据数、能量与积分收敛、驻定性诊断）与 `final/solver.log`。数值须有限；不得把有限扰动检验当作全局极小值的证明。

八个公开条件与每个剖面点都会与独立收敛的参考按请求容差比较；另有四个离格参数请求会在实际提交的可执行文件上运行；闭合关系、边界、电荷平衡与占据数均从提交行独立重算。

请安排好时间：求解阶段有 3600 秒墙钟上限。请边做边将完整交付物写入 `final/`，因为达到上限时该目录内容会被冻结。

### 输入与产物细则

- 输入：`/app/assets/edl_request.json`
- 输出：`final/solver.py`（及其辅助文件）、`final/dl_profiles_sharp.csv`、`final/dl_profiles_smeared.csv`、`final/analysis.json`、`final/solver.log`

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/edl_request.json` | 给定数据、参数或方法说明；用途见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
