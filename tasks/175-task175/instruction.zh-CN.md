# 任务：比较两帧中的锂接触与氧桥连接

## 背景

`frame_early.xyz` 是 0 ps 经典分子动力学终点，`frame_late.xyz` 是 70 ps 从头算重启构型；注释行给出立方盒边长（Å）。两帧来自同一 LiTFSI 水溶液体系。

## 任务

比较两帧中的 Li–Li 接触、氧桥和接触图连通分量，报告规定统计量，并评估链结构证据及系综群体占比。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

选择并报告 Li–Li 截断 `[2.7, 3.2] Å` 与 Li–O 截断 `[2.4, 3.0] Å` 内的值，两帧使用相同截断。使用周期最小镜像距离，截断边界计入。若一个氧同时处于一对锂离子的 Li–O 截断内，即为桥氧；若氧距任一氢小于 `1.25 Å`，归为水氧，否则为 TFSI 氧。接触图包含所有 Li，每个 Li–Li 接触均构成一条边，无论是否有桥氧。此处链指至少含三个 Li 的连通分量，不表示几何上线性。

每帧报告 `n_contact_pairs`、`fraction_oxygen_bridged`（至少共享一个氧的接触比例；无接触时为零）、`max_component_size` 和 `fraction_Li_in_components_ge_3`。`contacts_share_water` 表示后期帧是否有接触共享水氧；`anion_can_co_bridge` 表示是否有后期接触同时共享水氧与 TFSI 氧。后期最大分量至少含三个 Li 时，`chains_present_in_late_frame` 为 true；早期最大分量至少含四个 Li 时，`extended_chains_present_at_classical_start` 为 true。评估两种构型是否足以确立系综群体占比。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 用于锂网络分析的结构。 |

输入位于 `environment/assets/`。将结果写入 `/app/final/topology.json`。比例为数值，计数与大小为整数，标志使用 JSON 布尔值。包含 `li_li_cutoff_A`、`li_o_cutoff_A`、`late` 与 `early`（各含上述四项统计量）、`contacts_share_water`、`anion_can_co_bridge`、`chains_present_in_late_frame`、`extended_chains_present_at_classical_start` 和 `ensemble_population_established`。
