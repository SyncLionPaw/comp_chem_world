# 任务：DCM 反演层内与层间力常数

## 背景

给定压力依赖 Raman 数据包含多个层数的 E₂g¹ 与 E₂g² 频率。公开约定定义双原子链模型（DCM）所需的质量、单位和符号。

## 任务

对每个可用层数/压力组合反演 DCM，得到层内与层间力常数及其压力斜率与 `Cs_b/Cs_w`；说明物理根的选择和两支模态的配对方法。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

按各层 E₂g² 序列中实际存在的压力点计算，不假设共同网格。将 E₂g¹ 与 E₂g² 按最近源点配对，压力差须≤0.25 GPa。力常数用 N m⁻¹，斜率用 N m⁻¹ GPa⁻¹，比值无量纲。说明分别放入 `physical_root_rationale` 和 `pairing_rule`。保留斜率容差 0.08、评价路线 `Cs_b`/`Cs_w` 容差 6%/8%、比值误差≤5%且比值≤0.05、反算频率误差≤1 cm⁻¹。精确字段与覆盖范围见 `/app/verification.md`。

`physical_root_rationale` 和 `pairing_rule` 均须提供非空的科学说明。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 压力相关拉曼序列及约定。 |
| `/app/verification.md` | 方法与输出规范。 |

输入：`/app/assets/public_e2g1_vs_p.csv`、`/app/assets/public_e2g2_vs_p.csv` 和 `/app/assets/conventions.md`。按公开契约提交 `/app/final/results.json` 和 `/app/final/dcm_table.csv`.
