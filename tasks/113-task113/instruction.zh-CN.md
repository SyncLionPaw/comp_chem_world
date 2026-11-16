# 任务：计算 LiFePO4 平均嵌锂电压

## 背景

橄榄石型 LiFePO4 的平均锂嵌入电压由锂化/脱锂主体的能量差相对于金属锂参考态决定。使用同一原子间模型一致弛豫可使能量比较自洽。

## 任务

使用 `CHGNet-PES-MatPES-PBE-2025.2.10` 计算 LiFePO4 的平均嵌锂电压。以所给满锂正极和金属锂结构为起点，通过移除 Li 自行构造空主体。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、MatGL、NumPy、pymatgen、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

使用同一模型弛豫满锂正极、构造的空主体和金属锂参考。所有能量均由这些弛豫结果得到，不使用表列能量。以一致方式报告电压（V）、锂化学势（eV/原子）、满锂减空主体能量差（eV）及金属锂总贡献（eV）。使用转移被移除 Li 数目的标准平均电压关系。不得使用本题专用的外部解答。

写 `/app/final/voltage_results.json`，可使用简洁 JSON 或短文本报告，所有数值均须注明含义和单位。推荐键名为 `voltage_V`、`mu_metal_eV`、`energy_difference_eV` 和 `metal_contribution_eV`。

电压、锂化学势、满空结构能量差和金属贡献的绝对容差依次为 0.02 V、0.01 eV/原子、0.08 eV 和 0.04 eV。每项比较采用该容差与参考值绝对值乘以 1e−5 两者中较大者。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/lifepo4.cif` | 嵌锂正极结构。 |
| `/app/inputs/li_metal.cif` | 金属锂参考结构。 |

输入：`/app/inputs/lifepo4.cif`（满锂正极）和 `/app/inputs/li_metal.cif`。提交 `/app/final/voltage_results.json`。时间预算：1,800 秒。
