# 任务：比较配位与角度分布

## 背景

`window_blue.dat`、`window_green.dat` 和 `window_red.dat` 是三个 Li–Li 距离窗口的 Li–O 配位直方图；`window_all.dat` 为无条件直方图。各列依次为配位数、总氧百分比、阴离子氧百分比和水氧百分比。图4脚本将 blue/green/red 对应区域 I/II/III，`window_all` 对应 Ave；图2给出的区域边界为 3.0 和 4.15 Å，但未规定端点归属。角度文件分别为轨迹 Li–Ow–Li 和实验体相水 O–O–O 直方图。

## 任务

确定与短 Li–Li 接触相符的窗口，报告其总氧和阴离子氧配位众数，并与无条件众数比较。在 `0° < θ < 90°` 内取直方图值最大的角度为锐角众数，在 `90° < θ < 180°` 内同法取钝角众数；每个报告值距采样众数不超过 2°。将锐角众数与实验体相水众数比较。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

众数是相应直方图数值最大的配位数或角度；无条件众数不是均值。比较角度峰位而非峰宽，体相水众数从其直方图计算，并根据数据确定大小关系。2°是报告精度，不是统计抽样不确定度。按上述原始窗口映射解释数据，比较众数而非均值。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 配位数与键角直方图。 |

输入位于 `environment/assets/`。将结果写入 `/app/final/solvation.json`：`short_contact_window`（`blue`、`green` 或 `red`），整数 `short_contact_mode_total_cn`、`average_mode_total_cn`（无条件众数）、布尔值 `short_contact_cn_higher_than_average`、整数 `short_contact_modal_anion_cn`、按锐角再钝角排序的双元素数值数组 `angle_modes_deg`，以及布尔值 `acute_mode_tighter_than_bulk_water`（锐角小于体相水众数时为 true）。
