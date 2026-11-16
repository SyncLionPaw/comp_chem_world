# 任务：估计 apo 腔体水合并审计偏置有效性

## 背景

本包提供来自偏置 OAH/OAMe 模拟的稀疏 host-aligned 坐标片段，含显式水原子 ID、旋转盒子、原生时间，以及短连续 COLVAR/偏置窗口。坐标与偏置窗口的采样步长和时间偏移不同。

## 任务

围绕公开 PLUMED 轴自行定义腔体，并比较至少两个几何区域。计数并检验边界敏感性；结合时间戳和 provenance 核对坐标与偏置片段，判断能否得到无偏水合分布；若不能，明确缺失证据。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

对每个区域说明形状、中心/轴、尺寸、体积、原子选择、PBC 处理和敏感性。报告逐帧整数计数及 PBC-aware 水 O–O/H-angle 图，包括原子级边、连通分量和 cycle rank。使用完整映射的水原子 ID，并区分各 host 的来源范围。

计数应标为 sparse biased-sample frequency，不能称为平衡概率。原始 alpha-shape 参数和机器可读 mask 未提供，不得声称已复现该区域。OAMe 的 XTC 间隔为 5 ps、COLVAR 为 0.5 ps；OAH 的 XTC 间隔为 5 ps，COLVAR 从 1.5 ps 开始且步长为 2 ps。最近时间的偏置未必对应坐标实际时刻；末态 kernel 或稳定 kernel 计数不能证明历史同帧偏置。没有经过验证的同构型历史权重时，不得报告无偏 P(n)。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 公开输入和方法资料 |
| `/app/environment/assets/output-contract.json` | 提交格式、证据约定及适用容差 |

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/cavity-definition.json` | 空腔定义 |
| `/app/occupancy-region-sensitivity.csv` | 占据敏感性 |
| `/app/wire-geometry.csv` | 水链几何 |
| `/app/bias-validity-audit.json` | 偏置有效性审计 |
| `/app/decision.md` | 科学判断 |
