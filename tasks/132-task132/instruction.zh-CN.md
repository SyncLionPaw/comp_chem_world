# 任务：热与自旋贡献一致的反应吉布斯自由能计算

## 背景

气相反应的吉布斯自由能由各物种的电子能与其平动、转动、振动贡献组合而成。每个物种贡献由自身振动分析得到的热校正；分子对称性、几何类型与自旋态都显式进入该校正——其中氧气是三重态，必须把其多重度传给计算器。

输入与可用资源按下文说明；需要自行获取的资料仍由任务执行者获取。

## 任务

对反应 CH₄ + 2 O₂ → CO₂ + 2 H₂O，用 GFN2-xTB 计算 298.15 K、1 atm 下的反应吉布斯自由能。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、NumPy、RDKit、SciPy、tblite。不要自行安装额外软件包，也不要通过网络获取依赖。

- 对四个物种分别用 `ase.build.molecule(name)` 建立参考几何，再用 GFN2-xTB（`tblite`）经 ASE `BFGS` 优化到 `fmax = 0.02` eV/Å。
- 做振动分析（`ase.vibrations.Vibrations`），把电子能与振动能送入 `ase.thermochemistry.IdealGasThermo`，得到各物种在 298.15 K、101325 Pa 下的吉布斯自由能。
- 各物种参数：CH₄（`geometry="nonlinear"`、`symmetrynumber=12`、`spin=0`）；O₂（`geometry="linear"`、`symmetrynumber=2`、`spin=1`，三重态，向计算器传 `multiplicity=3`）；CO₂（`geometry="linear"`、`symmetrynumber=2`、`spin=0`）；H₂O（`geometry="nonlinear"`、`symmetrynumber=2`、`spin=0`）。
- 按 ΔG = [G(CO₂) + 2·G(H₂O)] − [G(CH₄) + 2·G(O₂)] 组合。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/inputs.json` | 随题提供的分子或反应输入。 |

将结果以 JSON 写入 `/app/final/reaction.json`：一个只含 `reaction_gibbs_eV` 键的对象，其值为反应吉布斯自由能，单位为 eV。绝对误差须小于 0.02 eV。
