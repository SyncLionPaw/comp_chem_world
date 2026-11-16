# 任务：重算结合自由能并作停止/继续判断

## 背景

本包提供完整的 353,353 行归档 G4 COLVAR 记录及 provenance。`environment/assets/thermodynamic-method.md` 定义基线 FES、funnel 标准态积分、块权重和不确定量。

## 任务

重算基线结合自由能，再至少执行一项预先声明的 burn-in、bin-count 或 time-window 敏感性分析。结合结果和采样证据说明当前记录支持的精度，以及分析应停止还是继续。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

遵循方法文件中的原生单位、wall 与 z 筛选、300 K 重加权、72-bin 基线、funnel 几何及空 bin 规则。分别报告五个等历时块估计、加权块 SD 与形式 SE，并与逐帧 ESS 区分。说明时间相关和单 replica 的限制；接近外部数值不构成收敛证据。

bin-count 敏感性最多使用 144 bins。若必需的 unbound bin 确实为空，应说明原因并将该敏感性标为不支持，不得编造有限结果。不得声称完整复现已发表 Table 1。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 公开输入和方法资料 |
| `/app/environment/assets/output-contract.json` | 提交格式、证据约定及适用容差 |
| `/app/environment/assets/thermodynamic-method.md` | 热力学分析方法 |

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/FES.csv` | 自由能面 |
| `/app/blocks.csv` | 分块估计 |
| `/app/thermodynamics.json` | 热力学估计 |
| `/app/sensitivity.csv` | 敏感性分析 |
| `/app/sampling-decision.json` | 采样判断 |
| `/app/audit-report.md` | 审计报告 |
| `/app/provenance.json` | 数据来源 |
