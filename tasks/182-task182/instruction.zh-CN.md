# 任务：分析固定的非盲水轨迹中的氧结构

## 背景

输入是两条历史非盲的 300 K 周期水轨迹，每条 10 ps、201 帧，间隔 50 fs，含 64 个 O 和 128 个 H，晶胞为边长 12.4 Å 的立方体；类型 1 为 O，类型 2 为 H。本题不要求新模拟或电子结构计算。

输入与可用资源按下文说明；需要自行获取的资料仍由任务执行者获取。

## 任务

计算两条轨迹的 O–O 径向分布函数（RDF）和第一壳层配位数。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

按原子 ID 对齐并使用 MIC 距离。使用 0.05 Å 分箱，计算每条轨迹至 6.2 Å 的 RDF；采用不同 O–O 原子无序对和有限 N 归一化：

    g(r) = H(r) V / (Nframes × N_O(N_O−1)/2 × shell_volume(r))

其中 shell_volume = 4π/3 × (r_outer³ − r_inner³)，N_O = 64。报告全程 RDF 以及两个描述性时间段：0 ≤ t ≤ 5.00 ps 和 5.00 < t ≤ 10.00 ps。合并两条全程 RDF，在中心位于 [2.40, 3.10] Å 的 bin 中找 g 值最大者（并列时取半径较小的 bin）。对合并 RDF 作居中三 bin 均值平滑，报告峰值后的第一个局部极小值：中心位于 [3.00, 4.00] Å，平滑值不大于左邻且严格小于右邻。第一壳积分固定使用 3.55 Å 上边界，氧数密度为 (N_O−1)/V；积分至 6.2 Å 得到的是累计配位数。分段与两条轨迹仅作描述，不是独立样本；不得声称独立标准误、平衡或收敛。

### 输入与产物细则

输入为 environment/assets/public-inputs-v2/trajectories/replica-00.lammpstrj 和 replica-01.lammpstrj；environment/assets/public-inputs-v2/trajectory-manifest.json 记录条件与来源哈希。提交 final/exploration/rdf-analysis.json，包含 RDF 数组、峰与极小值、方法和 cutoff、全程与分段第一壳配位数、来源哈希及解释限制。完整输出字段与形状见[公开输出格式](environment/assets/public-docs-v2/output-schema-v2.md)。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/public-inputs-v2/` | 两条归档水轨迹及配套输入。 |
| `/app/environment/assets/public-docs-v2/` | 数据定义及分析约定。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
