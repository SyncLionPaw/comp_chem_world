# 任务：计算 3C-SiC 晶格热导率

## 背景

声子间散射决定晶格热导率。计算需要谐性及非谐性原子间力常数，并对倒空间积分进行收敛处理；机器学习势可提供所需力计算。

## 任务

以 `/app/inputs/sic_bulk.cif` 中的常规晶胞为起点，使用 `MACE-MATPES-PBE-0` 计算立方 3C-SiC 在 100 K 和 300 K 的各向同性晶格热导率。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、MACE、NumPy、Phonopy、pymatgen、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

先约化为原胞，再同时弛豫晶胞和原子位置，力容差为 0.01 eV/Å。有限差分力常数计算使用 float64。用原胞的 2×2×2 超胞计算二阶和三阶力常数，以 5×5×5 布里渊区网格积分，并报告两个温度下张量平均的各向同性热导率，单位 W m⁻¹ K⁻¹。不得使用本题专用的外部解答。

在 `/app/final/thermal_conductivity_results.json` 中提供 `thermal_conductivity_summary.temp_100K` 和 `.temp_300K`。

两个温度下的热导率均采用 5% 相对比较容差。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/sic_bulk.cif` | 常规晶胞的块体 SiC 结构。 |

输入：`/app/inputs/sic_bulk.cif`。提交 `/app/final/thermal_conductivity_results.json`。时间预算：3,600 秒。
