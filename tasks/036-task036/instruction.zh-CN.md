# 任务：水与含钾界面的 CO₂ 结构涨落

## 背景

四条原始分子动力学轨迹记录水与含钾界面中 CO₂ 中性态和还原态的结构涨落。键长和键角描述几何，不能单独测量局域电荷或证明反应机制和因果关系。

## 任务

识别各轨迹中的 CO₂，重建其键长和键角随时间的变化，并比较两种电荷态的结构统计。说明有限、时间相关轨迹支持的几何结论及尚未解决的不确定性。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、matplotlib、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 只读 `/app/environment/assets/` 中的四条公开轨迹。逐体系在首帧按元素组成和空间邻近识别一个 C 与其两个 O，此后固定原子索引；距离和角度使用周期边界最小镜像。
- 对每体系按零基帧 `range(1000, n_frames, 10)` 采样。`geometry.csv` 的列为 `system,frame,co_short_A,co_long_A,oco_deg`；按 `water_CO2`、`water_CO2anion`、`2K_CO2`、`2K_CO2anion` 排序，再按帧递增。键长以 Å、角度以度表示。
- `summary.json` 包含四体系的 `systems` 映射。每项给出 `n_frames`、`n_samples`、`co_short_mean_A`、`co_long_mean_A`、`oco_mean_deg`、`co_short_std_A`、`co_long_std_A`、`oco_std_deg` 和 `block_means`。按时间用 `numpy.array_split` 分五块；每块可用 `[短键均值, 长键均值, 键角均值]` 三数数组，或仅含 `co_short_mean_A`、`co_long_mean_A`、`oco_mean_deg` 的对象记录。每帧先将两键长排序，标准差使用 `ddof=1`。
- `conclusions` 提供 `water_reduction_bends`、`K_reduction_bends`、`K_anion_more_bent_than_water`、`water_reduction_elongates`、`K_reduction_elongates` 五项布尔值。弯曲按平均 O–C–O 角比较；伸长按还原态短键与对应中性态长键均值比较。
- `interpretation` 提供 `geometry_directly_measures_electronic_charge`、`geometry_alone_proves_causal_mechanism`、`sample_std_is_SEM`、`five_block_means_are_independent_CI` 四项布尔值。结合采样和时间相关性说明判断；不得把帧间标准差或五块范围当作均值置信区间。
- 重算几何与独立结果的绝对差不超过 `1e-4 Å`（键长）和 `1e-2°`（角度）；样本数和结论字段按定义精确。以上是计算一致性容差，不是物理误差或置信区间。

### 输入与产物细则

- `/app/environment/assets/water_CO2/10ps.traj`
- `/app/environment/assets/water_CO2anion/10ps.traj`
- `/app/environment/assets/2K_CO2/10ps.traj`
- `/app/environment/assets/2K_CO2anion/10ps.traj`
- 使用 Python 3.12、ASE 和 NumPy。将 `geometry.csv`、`summary.json`、可执行的 `analysis.py` 和 `report.md` 写入 `/app/final/`。`python analysis.py ASSET_DIR OUTPUT_DIR` 从公开轨迹重算科学数据并重现两个数据文件。报告说明原子识别、PBC/minimum-image、采样统计、时间相关性及结论适用范围。

上述 `ASSET_DIR` 为 `/app/environment/assets/`，`OUTPUT_DIR` 为 `/app/final/`。`analysis.py` 是需要编写的提交产物，并非预置分析脚本。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 给定输入与资源目录。 |
| `/app/environment/assets/water_CO2/10ps.traj` | 给定科学输入或资源；格式和单位见任务要求。 |
| `/app/environment/assets/water_CO2anion/10ps.traj` | 给定科学输入或资源；格式和单位见任务要求。 |
| `/app/environment/assets/2K_CO2/10ps.traj` | 给定科学输入或资源；格式和单位见任务要求。 |
| `/app/environment/assets/2K_CO2anion/10ps.traj` | 给定科学输入或资源；格式和单位见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
