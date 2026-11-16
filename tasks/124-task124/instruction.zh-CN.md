# 任务：对称性与自旋一致的分子热化学计算

## 背景

分子的吉布斯自由能由电子能与其平动、转动、振动贡献组合而成。`ase` 的 `IdealGasThermo` 依据振动分析和分子对称性计算这些贡献，因此必须显式给出几何类型、对称数和自旋态。


## 任务

用 GFN2-xTB 计算氨在 298.15 K、1 atm 下的吉布斯自由能。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、NumPy、RDKit、SciPy、tblite。不要自行安装额外软件包，也不要通过网络获取依赖。

- 从本题提供的名称到 SMILES 查找表中取得该化合物的 SMILES。
- 先优化几何：用 RDKit 添加显式氢后，以随机种子 42 嵌入，MMFF 预优化，再用 GFN2-xTB（`tblite`）经 ASE `BFGS` 最小化到 `fmax = 0.02` eV/Å。
- 做振动分析（`ase.vibrations.Vibrations`），在 298.15 K 和 101325 Pa 下，把电子能与振动能送入 `ase.thermochemistry.IdealGasThermo`，参数为 `geometry="nonlinear"`、`symmetrynumber=3`、`spin=0`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/name_lookup.json` | 化合物名称到 SMILES 的查找表。 |

从 `/app/environment/assets/name_lookup.json` 读取名称到 SMILES 的查找表。

将结果以 JSON 写入 `/app/final/thermo.json`，单位为 eV，键名为 `gibbs_free_energy_eV`。绝对误差须小于 0.01 eV。
