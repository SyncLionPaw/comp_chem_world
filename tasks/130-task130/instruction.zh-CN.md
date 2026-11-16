# 任务：SMILES 衍生优化坐标的规范导出

## 背景

优化后的结构通常以坐标文件交换。本题沿用常规做法：以分子名而非通用文件名命名结果文件。

输入与可用资源按下文说明；需要自行获取的资料仍由任务执行者获取。

## 任务

用 GFN2-xTB 优化丙酮（SMILES 为 `CC(=O)C`）的分子几何，并把最终结构保存到以分子命名的文件中。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、NumPy、RDKit、SciPy、tblite。不要自行安装额外软件包，也不要通过网络获取依赖。

- 用 `Chem.AddHs` 添加显式氢，再以 `AllChem.EmbedMolecule(mol, randomSeed=42)` 嵌入单个构象，其余参数采用默认值。
- 用默认参数调用 `AllChem.MMFFOptimizeMolecule(mol)` 预优化。
- 用默认设置的 ASE BFGS 调用 GFN2-xTB 计算器（`tblite`）优化，力的收敛判据为 `fmax = 0.02` eV/Å。
- 保留该流程产生的原子顺序和笛卡尔坐标系。坐标以 Å 为单位逐分量比较，绝对容差为 0.001 Å，相对容差为 0.00001。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/inputs.json` | 随题提供的分子或反应输入。 |

将优化后的结构以标准 XYZ 格式写入 `/app/final/acetone.xyz`。
