# 任务：判断水 CV 验证是否充分

## 背景

本包提供一条完整归档 G4 标量轨迹及其公开 provenance，并提供 64 行 legacy descriptor、Deep-LDA 权重和方法说明。三个网络评估的是同一条偏置记录，并非独立模拟。

## 任务

判断 water-aware collective variable 现在可接受、应暂缓验证还是应拒绝。重算三个模型的输出与 descriptor 梯度，与每个原生标量列比较，并设计能解决泛化问题的最小留出验证。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

使用公开模型结构和权重。在 64 个 descriptor 帧上，将三个模型输出分别与 `node0`、`node1`、`node2`、`sw`、`swb`、`swc` 比较，按指定仿射拟合和残差报告全部配对；不得凭文件名或相关性推断模型与原生列的身份。按指定的有符号梯度和绝对值分位数约定，汇总全部 d(sw)/d(d1…d12)。descriptor 时间只可与原生时间精确匹配或在 0.01 ps 内唯一最近匹配，不得插值。

报告 trace provenance、重复列审计策略及其限制：转换后 NPZ 不含原始重复列，无法从该文件重审其相等性。说明如何用 run-level 或连续块留出避免相邻帧泄漏。该归档记录有偏，不能证明独立 B/U 泛化；未能确定的映射与主张须保持未解决。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 公开输入和方法资料 |
| `/app/environment/assets/output-contract.json` | 提交格式、证据约定及适用容差 |

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/cv-audit.csv` | 集体变量审计 |
| `/app/validation-plan.json` | 验证设计 |
| `/app/decision.json` | 研究判断 |
| `/app/rationale.md` | 科学依据 |
| `/app/model-output-audit.csv` | 模型输出核对 |
| `/app/model-gradient-audit.csv` | 模型梯度核对 |
