# 任务：由已提供 CI-NEB 路径重建迁移势垒

## 背景

提供了 TiS₂ 中 Li、Mg、Na 迁移的已完成爬坡图像 NEB 输出，无需 `neb.dat`、已有势垒数值或重新计算。实验背景比较了 O1 中 Mg–Li 共嵌与 Mg–Na 体系中有限的 Mg 共嵌，以及宿主堆垛变化。

## 任务

重算全部十条路径势垒：`O1_Li`、`O1_Mg`、`O1_Na`、`Li05_Li`、`Li05_Mg`、`O3_Na`、`O3_Mg_PATH1`、`O3_Mg_PATH2`、`P3_Na`、`P3_Mg`，并评估比较所支持的结论。`Li05` 表示 Li0.5TiS₂；两条 O3 Mg 路径均须纳入。

## 要求

每个图像使用 `OSZICAR` 最后离子步的 `F=` 自由能，以图像 00 为零点。势垒为最大相对能，报告整数图像索引；仅当最大值严格位于两个端点之间时才称为内部鞍点。以 0.05 eV 阈值比较：O1 Mg 与 O1 Li；O1 与 Li0.5 中 Li、Mg 分别比较；P3 与 O3 的 Na 比较；P3 Mg 与两条 O3 Mg 路径分别比较。报告 `delta_Mg_O1_minus_Li05_eV = barrier(O1_Mg)-barrier(Li05_Mg)`。只有当 P3 Na 和 Mg 势垒都比对应 O3 势垒高出 >0.05 eV（Mg 须对两条路径均成立）时，P3 比较才支持“解释 Mg–Na 储存较差”；仅凭势垒不能确立实验机理。

写 `/app/barriers.json`，schema version 2，十条路径均包含整数 `n_images`、按图像顺序排列的 `energies_rel_eV`、`barrier_eV`、整数 `barrier_image`、`endpoint_rel_eV` 和布尔值 `interior_saddle`；另含上述 delta、结论字段 `O1_Mg_slower_than_O1_Li`、`O1_Na_interior_saddle`、`Li05_lowers_Mg_barrier`、`Li05_lowers_Li_barrier`、`P3_Na_below_O3_Na`、`P3_Mg_below_both_O3_paths`、`low_P3_barrier_explains_poor_Mg_Na_storage`，以及 `methods.energy_source=last_ionic_F`。用提供的 renderer 生成 `/app/report.md`。

能量比较的绝对容差为 0.002 eV。历史字段 `low_P3_barrier_explains_poor_Mg_Na_storage` 的真值按上述 P3 势垒较高的条件确定。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 原生 NEB 图像、能量及路径定义。 |

读取 `/app/environment/assets/neb/<path_id>/` 下全部图像 `OSZICAR`、`CONTCAR` 及父目录 `INCAR`，并读取 `/app/environment/assets/PATHS.md`。提交 `/app/barriers.json` 和 `/app/report.md`。
