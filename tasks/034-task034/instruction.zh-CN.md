# A2 干预如何影响凝聚相结构？

## 背景

公开模型是由 `AllSys.in.init`、`N130_WT.in.settings`、`WT.data` 和 `methods.yaml` 定义的 N130–rpL5 粗粒化体系。`WT.data` 是 466 珠子构造单元，不是已平衡凝聚相。A2 是规定的干预：指定酸性区段的电荷中和，以及相应的自 Lennard-Jones 参数变化。

## 任务

评估 A2 是否改变凝聚相中的 PD 空间结构和 A2–rpL5 关联。证据可以支持、反驳或暂不能确定其影响。自行选择并论证体系制备、积分、采样、独立重复、不确定性和分析；不预设优化器、步长、运行时长、种子、重复数、指标或响应方向。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、MDAnalysis、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

如果使用 HPC 计算资源，请见 `/app/AGENTS.md`，并通过 SSH 别名 `hpc` 连接。

遵循 `/app/environment/RPC-PROTOCOL.md` 中的远程执行接口及主机访问和调度政策。记录实际资源用量、作业 ID、提交脚本、状态、退出码及收集产物哈希。建立凝聚相，而不是把 466 珠子构造单元当作凝聚相。保持力场和干预身份：A2 同时包含电荷和 Lennard-Jones 变化，仅电荷中和不等于 A2 干预。区分新执行证据与已发表结果。报告平衡和采样证据、不确定性、局限及解释。结论可以是有证据支持、被反驳或基于证据的暂不能确定。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/simulation/` | 公开模拟输入。 |

运行目录 `/app`；公开输入 `/app/environment/assets`；交付目录 `/app/final/`。保留可重放的分析代码、生成的模型输入、日志、轨迹、分析数据及其来源。

- `report.md`：问题、方法、发现、不确定性、局限和解释。
- `run_manifest.json`：非空 `model_identity`、`intervention_identity`、`protocol_rationale`、`environment` 对象、把四个公开输入 basename 与文件校验值绑定的 `provenance` 数组，以及 `analysis_replay`。重放声明以 `python3 analysis.py` 开头的 `argv`（不得用 shell）、非空 final 相对 `inputs`/`outputs` 列表且所有输入都在 `final/` 下、非空 `dependencies` 对象和非空 `resources` 对象。
- `native-artifacts.json`：非空 `artifacts`，含唯一 final 相对 `path`、`role`、`size_bytes` 和 `sha256`，覆盖 `model_input`、`simulation_log`、`trajectory` 和 `analysis_data`。列出并哈希每个重放输出。
- `analysis.py`：可读、可复现的分析入口。
- `diagnostics.json`：数值有效性、平衡、采样和不确定性证据。
- `scientific-answer.json`：非空 `overall_assessment`；非空 `outcomes` 同时覆盖 `PD_spatial_structure` 和 `A2_rpL5_association`。每项声明 `metric`、`unit`、`method`、`uncertainty_method`、`interval_type`、`interval_coverage`、`decision_rule`、`interpretation`、有限 `wt_estimate`、`a2_estimate`、`difference_a2_minus_wt`（A2 减 WT）、有序两值 `difference_interval`，以及 `evidence_direction`（`supports_effect`、`no_resolved_effect` 或 `inconclusive`）。

不设物理阈值或原始响应方向。
