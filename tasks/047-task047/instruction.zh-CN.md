# NE 电导率与相关因子的科学审计

## 背景

给定的 reline 数据包含六个温度的盒长、黏度、离子扩散系数及 Green–Kubo 电导率。扩散系数已经包含有限尺寸修正；体系说明给出了组成和分子电荷。

## 任务

重新计算 Nernst–Einstein 电导率、`gamma=sigma_GK/sigma_NE` 及 Yeh–Hummer 扩散增量。解释这些比值对电荷电流相关和分子缔合意味着什么，以及还需要哪些证据。

## 要求

- 根据体系说明推导离子数密度和电荷贡献。将经过舍入的表格换算为 SI 单位，使用立方体体积 `L³`，并考虑已有的扩散修正。单独报告 Yeh–Hummer 增量；计算电导率时不得重复施加修正。
- 使用 `e=1.602176634×10⁻¹⁹ C`、`k_B=1.380649×10⁻²³ J/K` 和立方晶胞常数 2.837297。对每个给定温度，分别以 S/m 和 m²/s 报告电导率和扩散增量。
- 识别 gamma 大于／小于 1 的温度。解释其物理含义、允许范围、物种间相关、是否支持离子对解释，以及判断显著性所需的不确定性。结论应根据计算得出，不得采用预设分类。
- 提供仅依赖 Python 3 标准库的程序，通过 `--input` 读取 CSV，并可用 `python calculations.py --input INPUT.csv --output DIR` 重新生成输出。当盒长、黏度、扩散系数或电导率改变时，程序仍须有效。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/` | 电导率审计表及体系定义。 |
| `/app/output-contract.json` | 输出及证据约定。 |

工作目录为 `/app/`，下述输入和输出路径均相对此目录。

读取 `/app/inputs/conductivity-audit.csv` 和 `/app/inputs/system-spec.json`。写入 `/app/results.csv`、`/app/analysis.json` 及 `/app/calculations.py`；字段定义见 `/app/output-contract.json`。记录修正处理方式、温度分类、SI 单位及科学解释。
