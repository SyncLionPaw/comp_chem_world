# 任务：表征 Li–Li RDF 特征并比较比较曲线

## 背景

原始 Li–Li RDF 位于 `environment/assets/li_li_rdf_this_work.csv`，比较曲线位于 `environment/assets/` 的子目录中。`units.txt` 给出距离单位和温度。

## 任务

报告原始接触峰、两个主要环境谷及接触势阱到鞍点的自由能势垒。筛选符合条件的比较峰，判断是否匹配原始峰，并比较势垒与热能。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

将原始 RDF 距离从 pm 换算为 Å。接触峰为 `2.2 < r < 2.8 Å` 内 g(r) 最大值。分别报告 `2.7 < r < 3.3 Å` 和 `3.6 < r < 4.5 Å` 内采样到的最深谷；这些测量谷值不必等于图2的 3.0 和 4.15 Å 区域分界。使用 `F(r) = −k_B T ln g(r)`；势垒单位为 kcal/mol，计算为 `2.7 < r < 3.3 Å` 内 F 最大值减去 `2.2 < r < 2.7 Å` 内 F 最小值，仅用 `g(r) > 10⁻⁸` 的采样点。

比较曲线中的距离依 `units.txt` 换算为 Å，排序并对重复距离取均值。局部极大值须严格高于前一点且不低于后一点。符合条件的峰满足 `r < 3 Å`、`g(r) ≥ 0.6`；位置距原始接触峰不超过 `0.1 Å` 且峰高差不超过原始峰高的20%时视为匹配。若 `0.5 ≤ 势垒/(kBT) ≤ 2`，判为与 `kBT` 相当。以上均为操作性比较判据。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | Li–Li 径向分布函数与已发表的比较曲线。 |

将结果写入 `/app/final/environments.json`：距离用 Å、势垒用 kcal/mol、曲线列表仅写文件名，标志使用 JSON 布尔值。字段：

`r_first_maximum_A`, `g_first_maximum`, `r_boundary_I_II_A`, `r_boundary_II_III_A`, `barrier_I_II_kcal_mol`, `barrier_comparable_to_kT`, `curves_with_maximum_below_3A_and_g_at_least_0.6`, `any_comparison_curve_matches_contact_peak`。
