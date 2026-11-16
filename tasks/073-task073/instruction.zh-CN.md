# 任务：不同装配与配体条件下的催化几何比较

## 背景

输入为 `/app/assets/Fig_9a.dat` 和 `/app/assets/data_dictionary.md`。数据包含单环 S、D-AspAsh、D-ADP-Pi 条件下 WT 与 V72I 的逐帧 δ/γ 测量。D-ADP-Pi 中 Asp397 已质子化，ATP 被 ADP 与 HPO₄²⁻取代。请严格按字典映射体系、列和单位；最后一个面板的第 11 列是 γ、第 12 列是 δ，与其他面板的列序相反。

数据是合并后的帧测量，没有重复实验标签或时间轴。应描述经验分布及其局限，不得将帧视为独立重复，也不得据此提出无依据的显著性结论。

## 任务

比较 WT 和 V72I 在三种条件下的 δ（Å）与 γ（度）分布，以刻画催化口袋几何和 ATP 裂解后的顶端域运动。根据数据判断变化的方向和幅度；任务不预设口袋或顶端域变化方向。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas。不要自行安装额外软件包，也不要通过网络获取依赖。

报告解释结构化比较、口袋距离与顶端角变化、相对 S 的距离，以及合并帧数据的不确定性和采样限制。单位及面板/列映射以数据字典为准。

### 输入与产物细则

`findings.json` 须严格使用 `post-hydrolysis/v1`：顶层仅含 `schema_version,summary_statistics,statistical_methods,comparisons,return_toward_S,uncertainty`。`summary_statistics` 恰含 12 个条件×变体×观测量记录，每项仅含 `condition,variant,observable,n,mean,std,median,q25,q75`；`std` 为样本标准差。`statistical_methods` 为非空字符串数组。

`comparisons` 恰含四项 WT/V72I × δ/γ 比较，每项仅含 `variant,observable,baseline,target,location_statistic,effect,units,conclusion`。`baseline` 为 `D-AspAsh`，`target` 为 `D-ADP-Pi`；`location_statistic` 可选 `mean` 或 `median`，`effect` 为目标减基线；单位分别为 `angstrom`、`degree`。效应大于 2e-6 时 `conclusion` 为 `increased`，小于 -2e-6 时为 `decreased`，其余为 `inconclusive`。

`return_toward_S` 恰含 WT 与 V72I 各一项，每项仅含 `variant,location_statistic,baseline_condition,target_condition,reference_condition,before_distance,after_distance,units,closer_to_S`。条件依次为 `D-AspAsh`、`D-ADP-Pi`、`S`，单位为 `angstrom`；`location_statistic` 必须与同一变体 δ 比较相同。两个距离为各条件 δ 统计量到 S δ 统计量的绝对差；仅当 `after_distance < before_distance` 时 `closer_to_S` 为 `true`。这些定义不预设结果。

`uncertainty` 须仅含 `approach,independent_sampling_claim,series_spread,applicability,limitations`。描述性分析使用 `approach: descriptive`、`independent_sampling_claim: false`、`applicability: pooled_empirical_data`；`series_spread` 恰含 12 项，每项仅含 `condition,variant,observable,q25,q75`。`limitations` 为非空字符串或非空字符串数组，明确披露缺少独立重复标签/标识和时间轴。四分位距描述逐帧经验分布，不是置信区间。若采用推断方法，核验结果需人工审查；不得把帧数当作独立样本数。机器数值应由未预先舍入的数据计算并保留完整精度，报告可为可读性适度舍入。

在 `final/` 提交 `findings.json` 与 `report.md`。JSON 必须完整满足上述字段、记录数量、比较定义和数据限制；报告解释这些数值结果，不以文字替代结构化结论。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/Fig_9a.dat` | 给定科学输入或资源；格式和单位见任务要求。 |
| `/app/assets/data_dictionary.md` | 给定数据、参数或方法说明；用途见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/findings.json` | 匹配比较及描述性统计 |
| `/app/final/report.md` | 科学解读 |
