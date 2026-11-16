# 任务：选择非局域水描述符

## 背景

本包包含从一条偏置 OAMe–G4 轨迹按时间均匀抽取的 64 帧及对应配位数据。它们是稀疏样本，不代表平衡分布。`environment/assets/geometry-method.md` 定义坐标系、PBC、原子 ID、切换函数、归一化和单位；`training-design.json` 概述来源研究报告的 B/U 训练设计。

## 任务

从配体邻近点 L1–L4 与腔轴点 V1–V8 中选择并论证低维候选特征组。用 coordinate-defined z/r 匹配样本作对照，量化特征变化与冗余，并说明训练或批准该集体变量前还需要哪些独立 B/U 证据。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

按公开几何方法重算坐标特征，并提供闭式与晶格平移不变性检查。找出一对 bound-like 帧，使 z 与半径均在 0.02 nm 内匹配而 V1–V8 配位不同。特征子集由你决定；须用各特征族的观测数据和备选方案支撑选择。

说明来源设计（五条 4 ns 的 B 轨迹和五条 4 ns 的 U 轨迹，描述符步长 0.25 ps）与本题单条偏置轨迹片段的区别。不得由这些帧推断平衡频率、因果性、CV 最优性或泛化能力；说明解决这些限制所需的独立留出证据。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 公开输入和方法资料 |
| `/app/environment/assets/output-contract.json` | 提交格式、证据约定及适用容差 |

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/feature-audit.csv` | 特征审计 |
| `/app/geometry-check.json` | 几何核对 |
| `/app/decision.json` | 研究判断 |
| `/app/research-rationale.md` | 科学依据 |
