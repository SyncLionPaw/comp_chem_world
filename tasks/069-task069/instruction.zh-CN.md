# 任务：短程 MD 数值检查与继续/停止决策

## 背景

本任务要求真实远端分子动力学计算。输入包提供 G4 B/U 体系、拓扑、模板、两份最长 50 ps 的安全 NVT MDP 及输入 provenance。计划、复制或参考轨迹和本地分析都不算实际运行证据。

## 任务

在可用的单节点 CPU 环境执行 B、U 各自 1 fs 和 2 fs（四种条件）。每种状态的 1 fs/2 fs 初速度须配对：使用完全相同的实际速度，或同一显式随机种子生成；B 和 U 可用不同种子。比较数值稳定性与水几何，再决定继续或停止。

## 要求

使用 HPC 时，见 `/app/AGENTS.md`：用 SSH 别名 `hpc`，远程工作目录使用唯一的 `~/submit-jobs/<task>-<utc>-<rand>/`，再核验科学结果。

每组配对比较的起始 TPR 坐标和速度必须一致。使用共同种子时，仍须确认实际起始向量一致。

每个运行最多 50 ps，总计最多 200 ps；1 fs 最多 50,000 步，2 fs 最多 25,000 步，最多 8 CPUs、单节点、8 GiB RAM，目标运行时间 30 分钟。上限不是最低时长，较短的安全探测有效。保留原始 300 K NVT、力场/拓扑、水/离子/盒子、PME、all-bonds LINCS 约束和 thermostat。记录实际引擎/设置、资源、原生日志、能量、checkpoint、坐标和错误。比较温度、势能项、LINCS/NaN/盒子行为、警告及少量水几何。

用原生最终步数/时间核验配置时长，并另报采样覆盖。若预算内无法完成，停止并记录实际进度，不得扩大上限。原始 NVT MDP 仅作 provenance；不得使用 PLUMED/OPES、学习权重或额外 production runs。50 ps 探测不能证明平衡、结合自由能、动力学、CV 泛化或训练充分性；没有统一温度或能量漂移阈值。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 公开输入和方法资料 |
| `/app/environment/assets/output-contract.json` | 提交格式、证据约定及适用容差 |

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/submission/input-audit.json` | 输入审计 |
| `/app/submission/remote-provenance.json` | 远程执行来源 |
| `/app/submission/diagnostics.csv` | 运行诊断 |
| `/app/submission/numerical-comparison.json` | 数值比较 |
| `/app/submission/continuation-decision.json` | 继续运行判断 |
| `/app/submission/scientific-rationale.md` | 科学依据 |

另外在 `/app/submission/` 保留四个原生运行目录。实际早停造成的缺项须说明。
