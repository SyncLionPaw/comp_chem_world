# 任务：比较 TIP3P 与 TIP4P/Ew 的结合自由能误差

## 背景

六配体 OAMe 表格提供实验、TIP3P 和 TIP4P/Ew 的结合自由能均值（kcal mol⁻¹）及报告的模拟 σ。比较方法由 `environment/assets/method-basis.md` 固定。

## 任务

区分两种水模型的绝对误差、共同偏移和配体排序；解释逐配体 TIP4P/Ew−TIP3P 变化及比较的证据边界。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

等权计算 RMSE、预测减实验的均值偏移、偏移校正 RMSE、Pearson 相关系数平方、预测对实验的 OLS 斜率和 Kendall tau-a。报告六个配体的配对变化，区分排序表现与绝对准确度。

报告的 σ 描述模拟估计，不是力场不确定度，也不作为本协议权重。不得声称新 MD 运行、模型训练或力场因果诊断。结论限定于这六个配体，并说明采样和模型形式限制。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 公开输入和方法资料 |
| `/app/environment/assets/output-contract.json` | 提交格式、证据约定及适用容差 |

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/submission/metrics.json` | 比较指标 |
| `/app/submission/per_ligand_effects.csv` | 逐配体差异 |
| `/app/submission/interpretation.json` | 结果解释 |
| `/app/submission/comparison-report.md` | 比较报告 |
| `/app/submission/provenance.json` | 数据来源 |
