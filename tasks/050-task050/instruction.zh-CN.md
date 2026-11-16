# 任务：历史在线 VES 轨迹分析

## 背景

所给 Wolfe–Quapp 历史记录包含八个副本、偏置系数历史和保存轨迹。轨迹每 5,000 步保存，优化器每 500 步更新，内部每 50 步采样，三者不能混同。这些记录支持历史分析，不能独立还原优化器内部批次或证明新的收敛结论。

## 任务

实现 `/app/solution/analyze.py --data-dir PATH --output PATH [--analysis-cutoff STEP]`，审计偏置历史和样本，重建截止点后的自由能剖面，并评价其统计支持。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

核查系数版本完整性、时间顺序、副本暴露量及逐帧记录偏置。按副本和步数读取轨迹，不依赖 CSV 物理行序。默认截止点为最后一次完整记录更新；显式截止点须为所有副本均保存、且不早于该更新的整数步。仅使用严格晚于所选截止点的样本；移动分析边界不代表新的冻结事件。

采用 `statistics_builder.py` 中的定义计算 60 箱有限域 FES、existing 与 conservative ESS、可观测量自相关、共同支持域删块不确定性、窗口比较及块长/窗口敏感性。用 `exp(bias_x − max(bias_x))` 稳定重加权；对数权重的共同常数不应改变结果。给全部 RBF 系数加相同常数并非规范变换。空箱 FES 和无法解析的 jackknife 不确定性用 null 并保留 builder 状态；conservative 支持不足不使原本有定义的 existing FES 失效。

支持箱须满足计数为正、目标质量 ≥0.001、conservative ESS ≥20。扣除目标质量加权残差常数后，要求目标质量覆盖率 ≥0.90、加权 RMSE ≤1.0 kBT、普通绝对误差 P95 ≤2.0 kBT。报告是否满足条件；支持不足也是有效科研结论。不得宣称生产收敛、首次合格冻结、CV 充分性或新采样，不运行模拟或优化器重放。

### 输入与产物细则

输入位于 `/app/environment/assets/`：`run-protocol.json`、`bias-history.csv`、`trajectory.csv`、`statistics_builder.py`。向 `--output` 写一个有限 JSON 对象，数值不用布尔值代替；无效 CLI 输入须非零退出。

保留以下必需成员，可省略可选元数据：

- `recorded_update_cutoff` 与 `cutoff`：分别记录最后完整更新和所选分析边界的 `{step,bias_version}`。
- `history_audit`：`complete_updates`（含版本零）、`parameter_count`、升序配对的 `versions`/`update_steps`、`last_complete_update:{step,bias_version}`。
- `sample_audit`：`trajectory_rows`、整数 `replica_ids`、按十进制副本 ID 索引的 `per_replica`（每项 `{rows,first_step,last_step,strict_post_cutoff_rows}`）、`optimizer_sample_interval_steps`、`optimizer_update_interval`、`saved_trajectory_stride` 和总 `strict_post_cutoff_rows`。
- `fes_bins` 对应 builder 的 `reweighted_fes`；`legacy`、`conservative`、`support`、`windows`、`sensitivity` 对应 `derived_diagnostics` 同名成员。后几组中的 `pre_freeze`、`post_freeze`、`late_post` 分别改名为 `pre_analysis_cutoff`、`post_analysis_cutoff`、`late_post_analysis_cutoff`。
- `instance_adequacy:{thresholds_met}` 为上述判断的布尔值。若另含 `window_boundary` 标记，使用 `"analysis_cutoff"` 或所选截止步。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 给定输入与资源目录。 |

提交 `/app/solution/analyze.py`。调用方式和输出约定见上文。
