# 任务：SMILES 指定分子的振动频率计算

## 背景

振动频率来自势能面在极小点处的曲率。在优化几何上做数值 Hessian 即得到简正模式频率，其中非线性分子有 3N-6 个真实振动模式。

输入与可用资源按下文说明；需要自行获取的资料仍由任务执行者获取。

## 任务

用 GFN2-xTB 计算甲醛（SMILES 为 `C=O`）的振动频率。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、NumPy、RDKit、SciPy、tblite。不要自行安装额外软件包，也不要通过网络获取依赖。

- 先优化几何：用 RDKit 添加显式氢后，以随机种子 42 嵌入，MMFF 预优化，再用 GFN2-xTB（`tblite`）经 ASE `BFGS` 最小化到 `fmax = 0.02` eV/Å。
- 在优化几何上做数值 Hessian（`ase.vibrations.Vibrations`）。
- 只报告真实的振动模式（甲醛为 3N-6 = 6 个），单位为 cm⁻¹，并从低到高排序。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/inputs.json` | 随题提供的分子或反应输入。 |

将频率以 JSON 列表写入 `/app/final/frequencies.json`。各振动频率的误差不得超过 5 cm⁻¹。
