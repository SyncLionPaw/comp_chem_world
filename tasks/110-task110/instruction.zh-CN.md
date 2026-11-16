# 任务：生成并排序阿司匹林构象系综

## 背景

阿司匹林气相中热可及构象的结果取决于采样、对称等价极小值的识别，以及一致的统计加权。

## 任务

使用 `MACE-OFF23-small`，为 `/app/inputs/molecule.smi` 中的分子生成并弛豫多样构象系综，识别不同弛豫盆地，并估算 298.15 K 下的 Boltzmann 布居。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、MACE、NumPy、RDKit。不要自行安装额外软件包，也不要通过网络获取依赖。

所有生成的候选构象均使用所给模型弛豫，能量采用该模型的能量标度。合并弛豫后对称等价的结构，使保留结构各代表不同盆地。按能量升序排列，以全局最低能为基准计算相对能，并在 298.15 K 下计算归一化 Boltzmann 布居。报告实际找到的系综；可及布居比例取决于去重粒度，不预设唯一答案。不得使用本题专用的外部解答。

在 `/app/final/result.json` 中写入 `n_unique_conformers`、`global_minimum_energy_eV` 和按能量排序的 `conformers`，每项含连续的从 1 开始的 `rank`、`relative_energy_eV`、`boltzmann_population`。在 `/app/final/conformers.sdf` 中按相同顺序提交相同的弛豫结构，每个构象一条记录。

操作性验收范围为 2–5 个不同构象。第一激发构象相对最低能量不得超过 0.05 eV，最低能量与参考相差不得超过 0.1 eV，SDF 中前两个构象的最佳对齐 RMSD 至少为 0.10 Å。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/molecule.smi` | SMILES 格式的输入分子。 |

输入：`/app/inputs/molecule.smi`。提交 `/app/final/result.json` 和 `/app/final/conformers.sdf`。温度 298.15 K。时间预算：3,600 秒。
