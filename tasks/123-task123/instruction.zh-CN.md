# 任务：基于 Hessian 的分子振动频率计算

## 背景

振动频率来自势能面在极小点处的曲率。在优化几何上做数值 Hessian 即得到简正模式频率，其中非线性分子有 3N-6 个真实振动模式。


## 任务

用 GFN2-xTB 计算水的振动频率。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、NumPy、RDKit、SciPy、tblite。不要自行安装额外软件包，也不要通过网络获取依赖。

- 从本题提供的名称到 SMILES 查找表中取得该化合物的 SMILES。
- 先优化几何：用 RDKit 添加显式氢后，以随机种子 42 嵌入，MMFF 预优化，再用 GFN2-xTB（`tblite`）经 ASE `BFGS` 最小化到 `fmax = 0.02` eV/Å。
- 在优化几何上做数值 Hessian（`ase.vibrations.Vibrations`）。
- 只报告真实的振动模式（水为 3N-6 个），单位为 cm⁻¹，并从低到高排序。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/name_lookup.json` | 化合物名称到 SMILES 的查找表。 |

从 `/app/environment/assets/name_lookup.json` 读取名称到 SMILES 的查找表。

将频率以 JSON 列表写入 `/app/final/frequencies.json`。各振动频率的误差不得超过 5 cm⁻¹。
