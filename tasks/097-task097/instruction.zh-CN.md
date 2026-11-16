# 任务：压力系数与 S/LB 交叉

## 背景

给定的实验峰位序列包含多个层数下剪切（S）支与层间呼吸（LB）支的压力依赖。压力斜率和两支交叉位置随层数及交叉定义而变。

## 任务

确定各可用分支的压力系数，定位连续 S/LB 交叉，找出整数层序首次反转处，并评估备选压力窗口的影响。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

主拟合区间为 1–8 GPa，并报告实际区间。按声明的有限递增备选窗口重算。不得插补缺失的 N=3 LB 序列。连续交叉方法须声明为 `experimental_interpolation` 或 `mcm`，并至少提供六个有效的备选 S 斜率。斜率单位为 cm⁻¹ GPa⁻¹；覆盖 N=2–9 的 S 及所有可用 LB 序列。字段和 0.35 cm⁻¹ GPa⁻¹ 重拟合容差见 `/app/verification.md`。

斜率比较容差为 0.05，截距及连续交点比较容差为 0.8，均沿用对应量的单位。斜率随层数的回归系数，S 须大于 0.02，LB 须小于 −0.02。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 压力相关剪切及层间呼吸模序列。 |
| `/app/verification.md` | 方法与输出规范。 |

输入：`/app/assets/public_s_n1_vs_p.csv`、`/app/assets/public_lb_nnminus1_vs_p.csv`、`/app/assets/data_notes.md` 和 `/app/assets/conventions.md`。按公开契约提交 `/app/final/results.json` 和 `/app/final/slope_fits.csv`.
