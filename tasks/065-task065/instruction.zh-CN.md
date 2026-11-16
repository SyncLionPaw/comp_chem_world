# 任务：检验 G4 水合与水桥机理

## 背景

输入包括 source-bound 的 8,834 行 G4 观测表，以及带明确 host、guest、水原子 ID 和旋转盒子的 64 帧真实坐标。全记录和坐标片段覆盖范围不同，须按各自适用范围分析。

## 任务

按时间将观测与原生标量/偏置行连接。用 coordinate-defined z/r 几何检验湿/干态和水桥假说。对任何候选水桥，报告水 O/H ID、O–O 距离、donor–H–acceptor 角以及 guest-Br 接触；几何合理性和因果解释分开评价。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

状态按完整表的 native z/r 定义：bound-like 为 z<0.8 nm 且 r≤0.45 nm；unbound-like 为 z≥1.25 nm 且 r≤0.45 nm；其余为 intermediate。300 K 下用 `β·opes_bias_kJ_mol` 计算权重，先减最大 log weight 再归一化（不得用 RCT 代替偏置）；分别报告 burn-in 0、20,000、40,000 ps 的归一化窗口，并用 45 个不重叠的 4,000 ps 时间块覆盖全程，末端取 `min(start+4000 ps,last_time+1 ps)`。报告权重、ESS 与有限样本块统计；额外敏感性只能作为补充。

使用公开原子映射。坐标片段含 8 个映射 host 氧，完整轨迹 provenance 涵盖 32 个；基于片段的无水桥结论只能限定于该子集。单条偏置轨迹的稀疏样本不是平衡布居、速率或独立 replica。块内 log-mass ratio 只是条件有限样本 proxy，不是标准态结合自由能。报告阈值敏感性和可推翻结论的证据；若重加权支持不足，应标记 HOLD/不可估计。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 公开输入和方法资料 |
| `/app/environment/assets/output-contract.json` | 提交格式、证据约定及适用容差 |

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/coordinate-observables.csv` | 坐标观测量 |
| `/app/geometry-evidence.csv` | 几何证据 |
| `/app/state-hypotheses.json` | 状态假设 |
| `/app/mechanism-decision.md` | 机理判断 |
| `/app/state-analysis.json` | 状态分析 |
| `/app/state-frames.csv` | 逐帧状态 |
| `/app/state-blocks.csv` | 分块估计 |
