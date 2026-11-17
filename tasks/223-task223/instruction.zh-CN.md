# 接触动力学与复合评分计算

## 背景

在结合姿态元动力学（OpenBPMD）中，配体对沿其 RMSD 集体变量施加的偏置势的抵抗能力反映了其姿态稳定性。为了克服传统 PersScore 仅关注氢键（对疏水或 π-π 堆积相互作用配体失效）的局限，OpenBPMD 提出了基于广义重原子接触的 `ContactScore` 以及复合评分 `CompScore = PoseScore - 5 * ContactScore`。

输入包含平衡并居中的蛋白-配体参考结构，以及含 99 个生产帧的 OpenBPMD 轨迹。

## 任务

解析蛋白-配体复合物的增强采样轨迹，计算配体重原子位移时间序列（`PoseScore`）与非键重原子接触持久度（`ContactScore`），并基于模拟最后 2 ns 计算最终复合稳定性评分。

## 要求

- 以 `solute.dcd` 第0帧为参考，不计入99个生产帧；每生产帧先用蛋白 `backbone` 对齐参考，再计算配体RMSD（Å）。
- 分别选择原子：PoseScore使用 `resname UNK and not name H*`；接触使用配体 `resname UNK and not name *H*`，蛋白邻域为固定于第0帧的 `protein and not name H* and around 5 resname UNK`。数字开头氢名可能保留在第一种选择中，不能直接将该集合用于接触。
- 原生接触是参考距离<3.5 Å的配体/蛋白原子对。逐帧Q为距离不大于各自参考距离的比例，以前9个生产帧Q均值归一化并截断至1.0；包括全部规定非共价接触，不只统计氢键。
- 对99个生产帧的最后20帧（100 ps间隔下约2 ns）以未舍入值求PoseScore与ContactScore均值，不以快照或全轨迹平均替代。
- `CompScore = PoseScore - 5 * ContactScore` 误差须≤1e-4。独立参考使用未舍入尾部均值；PoseScore/ContactScore可报告三位小数，CompScore由实际报告值计算。允许更多位数，不规定预舍入顺序。
- CSV与汇总分数均为有限数值，JSON布尔值不作为分数。

提交 JSON 对象，包含有限且非布尔数值 `PoseScore`（Å）、归一化 `ContactScore` 和 `CompScore = PoseScore - 5 * ContactScore`。CSV 须有 99 行及唯一表头，至少包含整数 `frame` 和有限数值 `PoseScore`、`ContactScore`、`CompScore`；可包含其他不重复列。

提交的 JSON 对象成员名必须唯一，数值必须有限；产物路径可指向 `/app` 内的文件。

## 文件

| 路径 | 说明 |
| --- | --- |
| `/app/inputs/` | 参考结构与轨迹。 |
| `/app/scores.json` | 姿态稳定性指标。 |
| `/app/timeseries.csv` | 逐帧姿态与接触指标。 |
