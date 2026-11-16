# 任务：分析微分电容与 Parsons–Zobel 浓度关系

## 背景

提供的 `reference_sweeps.csv`、`curve_refinement.csv` 与 `analysis_contract.json` 是历史材料中的生成的 Poisson–Fermi 双电层扫描的完整公开数据合同。模型使用 T=300 K、alpha=0.5、元胞长度 0.8 nm 以及 manifest 中的已发表核系数。浓度单位为 mM（数值上等于 mol/m³ 用于数密度换算），`Pbar_C_m2`、`sigma0_C_m2` 单位 C/m²，`phi0_V` 单位 V。

每个分支是固定浓度、固定 `Pbar` 的剖面族：公开 20 个分支（浓度 1、2、3、5、10 mM 与 `Pbar` 0、0.01、0.02、0.03 C/m² 交叉）。原始先解 `sigma0=0`，再分别向正负两臂延拓。必须保持分支身份——不得混合不同浓度或 `Pbar` 的行，也不得按 `phi0` 排序。

## 任务

构建可复用的分支感知分析程序，从扫描数据计算微分电容曲线与 Parsons–Zobel（PZ）浓度诊断。本题关注对给定数据的数值分析与回归，不重新求解双电层边值问题。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、MDAnalysis、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- `final/analyze.py`，可如下运行

  `python3 /app/final/analyze.py --input /app/assets/reference_sweeps.csv --refinement /app/assets/curve_refinement.csv --manifest /app/assets/analysis_contract.json --out /app/final`

  并严格符合 `analysis_contract.json` 中的输出键、CSV 列、单位、枚举与日志 schema。
- 参考电容：Gouy–Chapman 的 `C_GC` 使用给定核在零波矢处的值 `eps_b = 1 + 1/K11 + 1/K21`（≈70.998）——它是固定模型输入的一部分，不是可自由选择的物理量，因此不取水的 78.3；并在 `analysis.json` 中如实报告 `eps_b`。
- 物理电容曲线：`curve_refinement.csv` 对每个分支给出偏移 -2h、-h、0、+h、+2h 处的真实 BVP 电位，覆盖三个五点导数层级（h = 5e-4、2.5e-4、1.25e-4 C/m²）。报告各层的带符号 `d_sigma0/d_phi0`（五点 `d_phi0/d_sigma0` 的倒数）及其绝对值 C、相邻层的电容与导数变化、符号一致性标志，以及粗网格估计相对最细层的相对偏差。若跨层符号不一致或数值区间 `[d3-2|d3-d2|, d3+2|d3-d2|]` 含零则标为 `unresolved`，若 `|C_h3-C_h2|/C_h3 > 0.01` 则标为 `ill_conditioned`，否则 `resolved`。这些都是报告的数值诊断，不是收敛性或稳定性证明。
- PZ 分析：对每个固定 `Pbar`，以 `x=1/C_GC(phi0=0)`、`y=1/C_model(sigma0=0)` 对五个声明的浓度做无权最小二乘拟合；另报告以 `x=1/C_GC(phi_pzc_model)` 的诊断拟合、五个留一浓度拟合，以及 manifest 声明的两个相邻四浓度窗口。给定资料 Figure 8 中印出的斜率仅用于溯源；请根据给定数据和 manifest 声明的窗口计算并报告拟合结果。
- 校验输入（完整、有限、单位正确、无混支），而不是静默填补或重排。
- 写出 `final/capacitance_curves.csv`（每分支每粗网格中心一行）、`final/parsons_zobel.csv`（全部浓度点与拟合摘要）、`final/analysis.json`（完整分支/拟合诊断）与 `final/solver.log`（简明的成功分析记录）。

分析前校验所声明的输入。提交的公开数据结果及程序对有效离格扫描的分析结果均与独立实现比较。

### 输入与产物细则

- 输入：`/app/assets/reference_sweeps.csv`、`/app/assets/curve_refinement.csv`、`/app/assets/analysis_contract.json`
- 输出：`final/analyze.py`、`final/capacitance_curves.csv`、`final/parsons_zobel.csv`、`final/analysis.json`、`final/solver.log`

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/reference_sweeps.csv` | 给定科学输入或资源；格式和单位见任务要求。 |
| `/app/assets/curve_refinement.csv` | 给定科学输入或资源；格式和单位见任务要求。 |
| `/app/assets/analysis_contract.json` | 给定数据、参数或方法说明；用途见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
