# 任务：诊断 wrapped 水轨迹中的位移信息

## 背景

输入是两条固定的历史 300 K 周期水轨迹，每条 10 ps、201 帧，间隔 50 fs，含 64 个 O 和 128 个 H，晶胞为边长 12.4 Å 的立方体（类型 1 为 O，类型 2 为 H）。坐标为 wrapped x/y/z，没有 image flags。

输入与可用资源按下文说明；需要自行获取的资料仍由任务执行者获取。

## 任务

计算逐帧最小镜像位移诊断，并判断采样坐标是否能确定唯一的 unwrapped MSD 或扩散系数 D。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

按 O 原子 ID 对齐，对每对相邻帧位移应用正交晶胞 MIC。从第 0 帧起累加这些增量，对全部 201 个采样点报告时间和 64 个 O 相对第 0 帧的均方位移。将其说明为最小镜像路径重建，不要称为观测到的 unwrapped 路径。

每条轨迹报告相邻帧 MIC 向量范数和分量的最大值、被 MIC 折回的 wrapped 坐标分量数，以及来源数据对应的最大步长见证。另提供一个采样端点对，列出 wrapped delta、MIC 位移和相差非零晶格矢量的替代位移，并说明两者周期端点相同而长度不同。根据这些证据判断 D；不得从 MIC 重建路径拟合扩散系数。只有采样数据支持唯一确定时才报告数值 D。

### 输入与产物细则

固定输入与条件见 environment/assets/public-inputs-v2/trajectory-manifest.json。提交 final/validation/displacement-assessment.json，包含 201 个采样点的 MIC 路径诊断、wrap 计数、最大步长及晶格 alias 见证、来源哈希、D 判断和解释限制。完整输出字段与形状见公开输出格式：environment/assets/public-docs-v2/output-schema-v2.md。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/public-inputs-v2/` | 两条归档水轨迹及配套输入。 |
| `/app/environment/assets/public-docs-v2/` | 数据定义及分析约定。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
